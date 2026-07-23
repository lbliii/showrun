"""Provider-specific session importers that emit safe normalized events."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from showrun.artifacts import ACTIVITY_TYPES, TraceEvent
from showrun.evidence import (
    MAX_ELAPSED_MS,
    MAX_IMPORT_BYTES,
    OUTPUT_PREVIEW_CHARS,
    normalize_redactions,
    normalize_status,
    redact_text,
    safe_preview,
    sanitize_sources,
)

_EVENT_META = {
    1: "The spark",
    2: "Category named",
    3: "Scope check",
    4: "Complexity reframed",
    5: "The shortcut",
    6: "Architecture collapses",
    7: "4 sources · 3 exact adjacencies",
    8: "Market wedge",
    9: "Audience clarified",
    10: "Positioning locks",
    11: "Artifact becomes product",
    12: "Source captured · lesson overlay added",
}

_EVENT_CODE = {
    6: "session.jsonl → deterministic player → HTML / GIF / MP4",
}


def _event_evidence(raw_event: dict[str, Any], label: str) -> dict[str, Any]:
    input_preview, input_redacted = safe_preview(raw_event.get("input"))
    output_preview, output_redacted = safe_preview(
        raw_event.get("output"),
        limit=OUTPUT_PREVIEW_CHARS,
    )
    redactions = normalize_redactions(
        raw_event.get("redactions") or (),
        evidence_redacted=input_redacted or output_redacted,
    )
    try:
        elapsed_ms = max(
            0,
            min(MAX_ELAPSED_MS, int(raw_event.get("elapsed_ms") or 0)),
        )
    except TypeError, ValueError:
        elapsed_ms = 0
    return {
        "status": normalize_status(raw_event.get("status")),
        "provider": redact_text(str(raw_event.get("provider") or ""))[:80],
        "operation": redact_text(str(raw_event.get("operation") or label))[:120],
        "input_preview": input_preview,
        "output_preview": output_preview,
        "elapsed_ms": elapsed_ms,
        "sources": sanitize_sources(raw_event.get("sources") or ()),
        "redactions": redactions,
    }


def _canonical_event(payload: dict[str, Any], event_id: int, line_number: int) -> TraceEvent:
    record_type = payload.get("type")
    at = float(payload.get("at", event_id - 1))
    event_values: dict[str, Any] = {}
    if record_type == "message":
        message = payload.get("message") or {}
        role = str(message.get("role") or "assistant")
        kind = "user" if role == "user" else "assistant"
        label = "You" if kind == "user" else "Agent"
        text = redact_text(str(message.get("content") or ""))
    elif record_type == "event":
        raw_event = payload.get("event") or {}
        raw_kind = str(raw_event.get("kind") or "tool")
        activity = str(raw_event.get("activity") or "")
        activity = activity if activity in ACTIVITY_TYPES else "tool"
        kind = raw_kind if raw_kind in {"tool", "result"} else "tool"
        if raw_kind == "decision":
            kind = "assistant"
            activity = "decision"
        label = str(raw_event.get("name") or ("Tool" if kind == "tool" else "Result"))
        text = redact_text(str(raw_event.get("content") or ""))
        event_values = {"activity": activity, **_event_evidence(raw_event, label)}
    else:
        raise ValueError(f"Unsupported canonical record on line {line_number}")
    return TraceEvent(
        id=event_id,
        at=at,
        source_at=at,
        duration=3,
        kind=kind,
        label=redact_text(label),
        text=text,
        meta=_EVENT_META.get(event_id, ""),
        code=_EVENT_CODE.get(event_id, ""),
        raw_preview=json.dumps(
            {
                "type": record_type,
                "role": (payload.get("message") or {}).get("role"),
                "name": (payload.get("event") or {}).get("name"),
            },
            separators=(",", ":"),
        ),
        **event_values,
    )


def _canonical_session(
    records: list[dict[str, Any]],
    fallback_id: str,
) -> tuple[str, str, tuple[TraceEvent, ...]]:
    title = "Untitled agent session"
    session_id = fallback_id
    events: list[TraceEvent] = []
    for line_number, payload in enumerate(records, 1):
        if payload.get("type") == "session":
            title = str(payload.get("name") or title)
            session_id = str(payload.get("id") or session_id)
            continue
        events.append(_canonical_event(payload, len(events) + 1, line_number))
    return title, session_id, tuple(events)


def _jsonl_records(text: str) -> tuple[list[dict[str, Any]], list[str]]:
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
    return records, warnings


def parse_session_text(
    text: str,
    *,
    filename: str = "session.jsonl",
) -> tuple[str, str, str, tuple[TraceEvent, ...], tuple[str, ...]]:
    """Detect and normalize canonical Showrun or Codex JSONL."""

    if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError("Session exceeds the 2 MB import limit")
    records, warnings = _jsonl_records(text)
    if not records:
        raise ValueError("The session contains no JSONL records")
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    fallback_id = f"{Path(filename).stem}-{digest}"
    record_types = {str(record.get("type") or "") for record in records}
    if "response_item" in record_types or "session_meta" in record_types:
        from showrun.codex_importer import parse_codex_session

        title, session_id, events = parse_codex_session(records, fallback_id)
        source_format = "codex-jsonl"
        warnings.append("System instructions and unbounded raw tool outputs were excluded locally.")
    else:
        title, session_id, events = _canonical_session(records, fallback_id)
        source_format = "showrun-jsonl"
    if not events:
        raise ValueError("The session contains no replayable user, assistant, or tool events")
    if any(
        "[REDACTED]" in event.text
        or event.redactions
        or "[REDACTED]" in event.input_preview
        or "[REDACTED]" in event.output_preview
        for event in events
    ):
        warnings.append("Potential credentials were redacted locally.")
    return title, session_id, source_format, events, tuple(warnings)
