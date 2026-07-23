"""Codex rollout adapter for Showrun's normalized trace contract."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime
from typing import Any

from showrun.artifacts import TraceEvent, short_title
from showrun.evidence import (
    MAX_ELAPSED_MS,
    OUTPUT_PREVIEW_CHARS,
    normalize_redactions,
    normalize_status,
    redact_text,
    safe_preview,
    sanitize_sources,
    sources_from_text,
)

_HIDDEN_BLOCKS = re.compile(
    r"<(?:in-app-browser-context|environment_context|recommended_plugins)\b.*?</"
    r"(?:in-app-browser-context|environment_context|recommended_plugins)>",
    flags=re.DOTALL,
)


def _activity_for_tool(tool_name: str, input_preview: str = "") -> str:
    normalized = tool_name.lower()
    command = f"{normalized} {input_preview.lower()}"
    if normalized.startswith("mcp__") or "mcp" in normalized:
        return "mcp"
    if any(token in normalized for token in ("spawn_agent", "send_message", "collaboration")):
        return "delegation"
    if normalized.startswith("web") or "search" in normalized:
        return "search"
    if any(token in normalized for token in ("apply_patch", "write_file", "edit_file")):
        return "file"
    if any(token in command for token in ("pytest", "ruff", " test", "test_", "ty check")):
        return "test"
    return "tool"


def _provider_for_tool(tool_name: str) -> str:
    if tool_name.startswith("mcp__"):
        provider = tool_name.split("__", 2)[1].replace("_", " ").title()
        return provider or "MCP"
    if tool_name.startswith("web"):
        return "Web"
    if "collaboration" in tool_name or "agent" in tool_name:
        return "Agent runtime"
    return "Local workspace"


def _activity_summary(activity: str, tool_name: str) -> str:
    return {
        "delegation": "Delegated agent work",
        "file": "Changed project files",
        "mcp": "Traversed an MCP",
        "search": "Searched for supporting evidence",
        "source": "Opened a supporting source",
        "test": "Ran verification",
        "tool": f"Ran {tool_name}",
    }[activity]


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
    return cleaned.split(marker, 1)[1].strip() if marker in cleaned else cleaned


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


def _tool_output(
    item: dict[str, Any],
    source_at: float,
    events: list[TraceEvent],
    call_indexes: dict[str, int],
) -> None:
    call_id = str(item.get("call_id") or item.get("id") or "")
    event_index = call_indexes.get(call_id)
    if event_index is None:
        return
    prior = events[event_index]
    output_preview, output_redacted = safe_preview(
        item.get("output") if "output" in item else item.get("content"),
        limit=OUTPUT_PREVIEW_CHARS,
    )
    redactions = normalize_redactions(
        prior.redactions,
        evidence_redacted=output_redacted,
    )
    sources = sanitize_sources(item.get("sources") or ())
    if not sources and prior.activity == "search":
        sources = sources_from_text(output_preview)
    status = normalize_status(item.get("status"), default="success")
    events[event_index] = replace(
        prior,
        status=status,
        output_preview=output_preview,
        elapsed_ms=min(
            MAX_ELAPSED_MS,
            max(0, round((source_at - prior.source_at) * 1000)),
        ),
        sources=sources,
        redactions=redactions,
        raw_preview=json.dumps(
            {
                "type": "function_call",
                "name": prior.operation,
                "status": status,
                "activity": prior.activity,
            },
            separators=(",", ":"),
        ),
    )


def _web_event(item: dict[str, Any], event_id: int, source_at: float) -> TraceEvent:
    action = item.get("action") or {}
    if not isinstance(action, dict):
        action = {}
    action_type = str(action.get("type") or "search")
    activity = "source" if action_type in {"open_page", "find_in_page"} else "search"
    input_preview, input_redacted = safe_preview(action)
    sources = sanitize_sources(
        action.get("sources") or ([action.get("url")] if action.get("url") else ())
    )
    return TraceEvent(
        id=event_id,
        at=source_at,
        source_at=source_at,
        duration=3,
        kind="tool",
        label="Source opened" if activity == "source" else "Web search",
        text=_activity_summary(activity, action_type),
        meta="Imported from Codex",
        raw_preview=json.dumps(
            {"type": "web_search_call", "action": action_type, "activity": activity},
            separators=(",", ":"),
        ),
        activity=activity,
        status=normalize_status(item.get("status"), default="success"),
        provider="Web",
        operation=f"web.{action_type}",
        input_preview=input_preview,
        sources=sources,
        redactions=normalize_redactions((), evidence_redacted=input_redacted),
    )


def _message_or_tool_event(
    item: dict[str, Any],
    event_id: int,
    source_at: float,
) -> TraceEvent | None:
    item_type = item.get("type")
    if item_type == "message" and item.get("role") in {"user", "assistant"}:
        role = str(item["role"])
        text = _content_text(item.get("content"))
        if role == "user":
            text = _clean_user_text(text)
        if not text:
            return None
        return TraceEvent(
            id=event_id,
            at=source_at,
            source_at=source_at,
            duration=3,
            kind=role,
            label="You" if role == "user" else "Codex",
            text=redact_text(text),
            meta="Imported from Codex",
            raw_preview=json.dumps({"type": item_type, "role": role}, separators=(",", ":")),
        )
    if item_type not in {"function_call", "custom_tool_call"}:
        return None
    tool_name = str(item.get("name") or "tool")
    arguments = item.get("arguments") if item_type == "function_call" else item.get("input")
    input_preview, input_redacted = safe_preview(arguments)
    activity = _activity_for_tool(tool_name, input_preview)
    return TraceEvent(
        id=event_id,
        at=source_at,
        source_at=source_at,
        duration=3,
        kind="tool",
        label=tool_name,
        text=_activity_summary(activity, tool_name),
        meta="Imported from Codex",
        raw_preview=json.dumps(
            {"type": item_type, "name": tool_name, "activity": activity},
            separators=(",", ":"),
        ),
        activity=activity,
        status="started",
        provider=_provider_for_tool(tool_name),
        operation=redact_text(tool_name)[:120],
        input_preview=input_preview,
        redactions=normalize_redactions((), evidence_redacted=input_redacted),
    )


def parse_codex_session(
    records: list[dict[str, Any]],
    fallback_id: str,
) -> tuple[str, str, tuple[TraceEvent, ...]]:
    """Normalize a Codex rollout while correlating calls with bounded outputs."""

    session_id = fallback_id
    events: list[TraceEvent] = []
    call_indexes: dict[str, int] = {}
    started_at: datetime | None = None
    for payload in records:
        if payload.get("type") == "session_meta":
            metadata = payload.get("payload") or {}
            session_id = str(metadata.get("id") or metadata.get("session_id") or session_id)
            continue
        if payload.get("type") != "response_item":
            continue
        item = payload.get("payload") or {}
        if not isinstance(item, dict):
            continue
        source_at, started_at = _relative_seconds(payload.get("timestamp"), started_at)
        item_type = item.get("type")
        if item_type in {"function_call_output", "custom_tool_call_output"}:
            _tool_output(item, source_at, events, call_indexes)
            continue
        event = (
            _web_event(item, len(events) + 1, source_at)
            if item_type == "web_search_call"
            else _message_or_tool_event(item, len(events) + 1, source_at)
        )
        if event is None:
            continue
        events.append(event)
        if item_type in {"function_call", "custom_tool_call"}:
            call_id = str(item.get("call_id") or item.get("id") or "")
            if call_id:
                call_indexes[call_id] = len(events) - 1

    title_source = next((event.text for event in events if event.kind == "user"), "")
    return short_title(title_source, "Imported Codex session"), session_id, tuple(events)
