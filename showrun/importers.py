"""Provider-specific session importers that emit safe normalized events."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from showrun.artifacts import TraceEvent, short_title

MAX_IMPORT_BYTES = 2_000_000

_EVENT_META = {
    1: "The spark",
    2: "Category named",
    3: "Scope check",
    4: "Complexity reframed",
    5: "The shortcut",
    6: "Architecture collapses",
    7: "6 sources · 3 exact adjacencies",
    8: "Market wedge",
    9: "Audience clarified",
    10: "Positioning locks",
    11: "Artifact becomes product",
    12: "Source captured · lesson overlay added",
}

_EVENT_CODE = {
    6: "session.jsonl → deterministic player → HTML / GIF / MP4",
}

_HIDDEN_BLOCKS = re.compile(
    r"<(?:in-app-browser-context|environment_context|recommended_plugins)\b.*?</"
    r"(?:in-app-browser-context|environment_context|recommended_plugins)>",
    flags=re.DOTALL,
)
_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*"
        r"([\"']?)[A-Za-z0-9._~+/=-]{8,}\2"
    ),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        flags=re.DOTALL,
    ),
)


def _redact_text(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(part.get("text") or "")
        for part in content
        if isinstance(part, dict) and part.get("type") in {"input_text", "output_text", "text"}
    ).strip()


def _clean_user_text(text: str) -> str:
    cleaned = _HIDDEN_BLOCKS.sub("", text).strip()
    marker = "## My request for Codex:"
    if marker in cleaned:
        cleaned = cleaned.split(marker, 1)[1].strip()
    return cleaned


def _relative_seconds(
    timestamp: str | None,
    started_at: datetime | None,
) -> tuple[float, datetime | None]:
    if not timestamp:
        return 0, started_at
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return 0, started_at
    origin = started_at or parsed
    return max(0, (parsed - origin).total_seconds()), origin


def _canonical_session(
    records: list[dict[str, Any]],
    fallback_id: str,
) -> tuple[str, str, tuple[TraceEvent, ...]]:
    title = "Untitled agent session"
    session_id = fallback_id
    events: list[TraceEvent] = []
    for line_number, payload in enumerate(records, 1):
        record_type = payload.get("type")
        if record_type == "session":
            title = str(payload.get("name") or title)
            session_id = str(payload.get("id") or session_id)
            continue

        event_id = len(events) + 1
        at = float(payload.get("at", event_id - 1))
        if record_type == "message":
            message = payload.get("message") or {}
            role = str(message.get("role") or "assistant")
            kind = "user" if role == "user" else "assistant"
            label = "You" if kind == "user" else "Agent"
            text = _redact_text(str(message.get("content") or ""))
        elif record_type == "event":
            raw_event = payload.get("event") or {}
            kind = str(raw_event.get("kind") or "tool")
            label = str(raw_event.get("name") or ("Tool" if kind == "tool" else "Result"))
            text = _redact_text(str(raw_event.get("content") or ""))
        else:
            raise ValueError(f"Unsupported canonical record on line {line_number}")

        preview = json.dumps(
            {
                "type": record_type,
                "role": (payload.get("message") or {}).get("role"),
                "name": (payload.get("event") or {}).get("name"),
            },
            separators=(",", ":"),
        )
        events.append(
            TraceEvent(
                id=event_id,
                at=at,
                source_at=at,
                duration=3,
                kind=kind,
                label=label,
                text=text,
                meta=_EVENT_META.get(event_id, ""),
                code=_EVENT_CODE.get(event_id, ""),
                raw_preview=preview,
            )
        )
    return title, session_id, tuple(events)


def _codex_session(
    records: list[dict[str, Any]],
    fallback_id: str,
) -> tuple[str, str, tuple[TraceEvent, ...]]:
    session_id = fallback_id
    source_events: list[TraceEvent] = []
    started_at: datetime | None = None

    for payload in records:
        if payload.get("type") == "session_meta":
            metadata = payload.get("payload") or {}
            session_id = str(metadata.get("id") or metadata.get("session_id") or session_id)
            continue
        if payload.get("type") != "response_item":
            continue

        item = payload.get("payload") or {}
        item_type = item.get("type")
        kind = ""
        label = ""
        text = ""
        if item_type == "message" and item.get("role") in {"user", "assistant"}:
            role = str(item["role"])
            text = _content_text(item.get("content"))
            if role == "user":
                text = _clean_user_text(text)
            text = _redact_text(text)
            kind = role
            label = "You" if role == "user" else "Codex"
        elif item_type == "function_call":
            tool_name = str(item.get("name") or "tool")
            kind = "tool"
            label = tool_name
            text = f"Ran {tool_name}"
        if not text:
            continue

        source_at, started_at = _relative_seconds(payload.get("timestamp"), started_at)
        event_id = len(source_events) + 1
        source_events.append(
            TraceEvent(
                id=event_id,
                at=source_at,
                source_at=source_at,
                duration=3,
                kind=kind,
                label=label,
                text=text,
                meta="Imported from Codex",
                raw_preview=json.dumps(
                    {"type": item_type, "role": item.get("role"), "name": item.get("name")},
                    separators=(",", ":"),
                ),
            )
        )

    title_source = next((event.text for event in source_events if event.kind == "user"), "")
    return short_title(title_source, "Imported Codex session"), session_id, tuple(source_events)


def parse_session_text(
    text: str,
    *,
    filename: str = "session.jsonl",
) -> tuple[str, str, str, tuple[TraceEvent, ...], tuple[str, ...]]:
    """Detect and normalize canonical Showrun or Codex JSONL."""

    if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError("Session exceeds the 2 MB import limit")
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    lines = text.splitlines()
    for line_number, raw_line in enumerate(lines, 1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            if line_number == len(lines):
                warnings.append("Ignored an incomplete final JSONL record.")
                continue
            raise ValueError(f"Invalid JSON on line {line_number}") from exc
        if isinstance(payload, dict):
            records.append(payload)

    if not records:
        raise ValueError("The session contains no JSONL records")
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    fallback_id = f"{Path(filename).stem}-{digest}"
    record_types = {str(record.get("type") or "") for record in records}
    if "response_item" in record_types or "session_meta" in record_types:
        title, session_id, events = _codex_session(records, fallback_id)
        source_format = "codex-jsonl"
        warnings.append("System instructions and raw tool outputs were excluded locally.")
    else:
        title, session_id, events = _canonical_session(records, fallback_id)
        source_format = "showrun-jsonl"

    if not events:
        raise ValueError("The session contains no replayable user, assistant, or tool events")
    if any("[REDACTED]" in event.text for event in events):
        warnings.append("Potential credentials were redacted locally.")
    return title, session_id, source_format, events, tuple(warnings)
