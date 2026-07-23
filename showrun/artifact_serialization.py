"""Validation and rehydration for portable ``dvd/1`` manifests."""

from __future__ import annotations

import json
from dataclasses import replace
from math import isfinite
from typing import Any

from showrun.artifacts import (
    ACTIVITY_STATUSES,
    ACTIVITY_TYPES,
    FORMAT_VERSION,
    Chapter,
    ShowrunArtifact,
    TraceEvent,
)
from showrun.evidence import (
    INPUT_PREVIEW_CHARS,
    MAX_ELAPSED_MS,
    MAX_IMPORT_BYTES,
    OUTPUT_PREVIEW_CHARS,
    normalize_redactions,
    redact_text,
    safe_preview,
    sanitize_sources,
)

EVENT_LABEL_CHARS = 80
EVENT_TEXT_CHARS = 10_000
EVENT_META_CHARS = 500
EVENT_CODE_CHARS = 10_000
EVENT_RAW_PREVIEW_CHARS = 2_000
MAX_PLAYBACK_SECONDS = 86_400


def _payload(raw: str) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError("Artifact exceeds the 2 MB import limit")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Artifact must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Artifact must be a JSON object")
    if payload.get("format") != FORMAT_VERSION:
        raise ValueError("Unsupported Showrun artifact format")
    return payload


def _event_from_value(index: int, value: Any) -> tuple[TraceEvent, bool]:
    if not isinstance(value, dict):
        raise ValueError(f"Artifact event {index} must be an object")
    redaction_values = value.get("redactions")
    if redaction_values is None:
        redaction_values = []
    if not isinstance(redaction_values, list):
        raise ValueError(f"Artifact event {index} redactions must be an array")
    try:
        raw_preview, preview_redacted = safe_preview(
            value.get("raw_preview") or "",
            limit=EVENT_RAW_PREVIEW_CHARS,
        )
        input_preview, input_redacted = safe_preview(
            value.get("input_preview") or "",
            limit=INPUT_PREVIEW_CHARS,
        )
        output_preview, output_redacted = safe_preview(
            value.get("output_preview") or "",
            limit=OUTPUT_PREVIEW_CHARS,
        )
        evidence_redacted = preview_redacted or input_redacted or output_redacted
        redactions = normalize_redactions(
            redaction_values,
            evidence_redacted=evidence_redacted,
        )
        event = TraceEvent(
            id=int(str(value.get("id") or 0)),
            at=float(str(value.get("at") or 0)),
            duration=float(str(value.get("duration") or 0)),
            kind=str(value.get("kind") or ""),
            label=str(value.get("label") or ""),
            text=str(value.get("text") or ""),
            source_at=float(str(value.get("source_at") or 0)),
            meta=str(value.get("meta") or ""),
            code=str(value.get("code") or ""),
            raw_preview=raw_preview,
            pause_after=float(str(value.get("pause_after", 0.7))),
            activity=str(value.get("activity") or ""),
            status=str(value.get("status") or ""),
            provider=str(value.get("provider") or ""),
            operation=str(value.get("operation") or ""),
            input_preview=input_preview,
            output_preview=output_preview,
            elapsed_ms=int(str(value.get("elapsed_ms") or 0)),
            sources=sanitize_sources(value.get("sources") or ()),
            redactions=redactions,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Artifact event {index} is invalid") from exc
    _validate_event_contract(event, index)
    clean_event = _sanitize_event_text(event)
    return clean_event, evidence_redacted or clean_event != event


def _validate_event_contract(event: TraceEvent, index: int) -> None:
    if event.id != index:
        raise ValueError("Artifact event IDs must be sequential")
    if event.kind not in {"user", "assistant", "tool", "result"}:
        raise ValueError(f"Artifact event {index} has an unsupported kind")
    if event.activity not in ACTIVITY_TYPES:
        raise ValueError(f"Artifact event {index} has an unsupported activity")
    if event.status not in ACTIVITY_STATUSES:
        raise ValueError(f"Artifact event {index} has an unsupported status")
    if not 0 <= event.elapsed_ms <= MAX_ELAPSED_MS:
        raise ValueError(f"Artifact event {index} has an invalid elapsed time")
    if (
        not isfinite(event.at)
        or not isfinite(event.duration)
        or not 0 <= event.at <= MAX_PLAYBACK_SECONDS
        or not 0 < event.duration <= 60
    ):
        raise ValueError(f"Artifact event {index} has invalid timing")
    if not isfinite(event.pause_after) or not 0 <= event.pause_after <= 30:
        raise ValueError(f"Artifact event {index} has an invalid pause")


def _sanitize_event_text(event: TraceEvent) -> TraceEvent:
    return replace(
        event,
        label=redact_text(" ".join(event.label.split())[:EVENT_LABEL_CHARS]),
        text=redact_text(event.text.strip()[:EVENT_TEXT_CHARS]),
        meta=redact_text(event.meta.strip()[:EVENT_META_CHARS]),
        code=redact_text(event.code.strip()[:EVENT_CODE_CHARS]),
        provider=redact_text(" ".join(event.provider.split())[:80]),
        operation=redact_text(" ".join(event.operation.split())[:120]),
    )


def _events(values: Any) -> tuple[tuple[TraceEvent, ...], bool]:
    if not isinstance(values, list) or not 1 <= len(values) <= 500:
        raise ValueError("Artifact requires between 1 and 500 events")
    events: list[TraceEvent] = []
    credentials_redacted = False
    for index, value in enumerate(values, 1):
        event, evidence_redacted = _event_from_value(index, value)
        if not event.label or not event.text:
            raise ValueError(f"Artifact event {index} needs a label and content")
        if events and event.at < events[-1].at:
            raise ValueError("Artifact events must be ordered by playback time")
        events.append(event)
        credentials_redacted = credentials_redacted or evidence_redacted
    return tuple(events), credentials_redacted


def _chapter_from_value(index: int, value: Any) -> tuple[Chapter, bool]:
    if not isinstance(value, dict):
        raise ValueError(f"Artifact chapter {index} must be an object")
    try:
        raw = Chapter(
            name=str(value.get("name") or ""),
            at=float(str(value.get("at") or 0)),
            caption=str(value.get("caption") or ""),
            note=str(value.get("note") or ""),
            teaching_point=str(value.get("teaching_point") or ""),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Artifact chapter {index} is invalid") from exc
    chapter = replace(
        raw,
        name=redact_text(" ".join(raw.name.split())[:80]),
        caption=redact_text(raw.caption.strip()[:160]),
        note=redact_text(raw.note.strip()[:1000]),
        teaching_point=redact_text(raw.teaching_point.strip()[:500]),
    )
    if not chapter.name or not isfinite(chapter.at) or not 0 <= chapter.at <= MAX_PLAYBACK_SECONDS:
        raise ValueError(f"Artifact chapter {index} is invalid")
    return chapter, chapter != raw


def _chapters(values: Any) -> tuple[tuple[Chapter, ...], bool]:
    if not isinstance(values, list) or not 1 <= len(values) <= 100:
        raise ValueError("Artifact requires at least one event and chapter")
    chapters: list[Chapter] = []
    credentials_redacted = False
    for index, value in enumerate(values, 1):
        chapter, chapter_redacted = _chapter_from_value(index, value)
        if chapters and chapter.at < chapters[-1].at:
            raise ValueError("Artifact chapters must be ordered by playback time")
        chapters.append(chapter)
        credentials_redacted = credentials_redacted or chapter_redacted
    return tuple(chapters), credentials_redacted


def artifact_from_json(raw: str) -> ShowrunArtifact:
    """Validate and rehydrate a stored immutable manifest."""

    payload = _payload(raw)
    recording = payload.get("recording") or {}
    lesson = payload.get("lesson") or {}
    if not isinstance(recording, dict) or not isinstance(lesson, dict):
        raise ValueError("Artifact recording and lesson values must be objects")
    events, event_redacted = _events(payload.get("events") or ())
    chapters, chapter_redacted = _chapters(payload.get("chapters") or ())
    artifact, metadata_redacted = _artifact_metadata(
        payload,
        recording,
        lesson,
        events,
        chapters,
    )
    credentials_redacted = event_redacted or chapter_redacted or metadata_redacted
    redaction_warning = "Potential credentials were redacted locally."
    if credentials_redacted and redaction_warning not in artifact.warnings:
        artifact = replace(
            artifact,
            warnings=(*artifact.warnings, redaction_warning),
        )
    return artifact


def _artifact_metadata(
    payload: dict[str, Any],
    recording: dict[str, Any],
    lesson: dict[str, Any],
    events: tuple[TraceEvent, ...],
    chapters: tuple[Chapter, ...],
) -> tuple[ShowrunArtifact, bool]:
    try:
        duration = float(lesson.get("duration") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Artifact duration must be a number") from exc
    if (
        not isfinite(duration)
        or duration < events[-1].at + events[-1].duration
        or duration > MAX_PLAYBACK_SECONDS
    ):
        raise ValueError("Artifact duration must extend beyond its final event")
    if chapters[-1].at >= duration:
        raise ValueError("Artifact chapters must begin within its duration")
    warning_values = payload.get("warnings", [])
    output_values = payload.get("outputs", [])
    if not isinstance(warning_values, list) or not isinstance(output_values, list):
        raise ValueError("Artifact outputs and warnings must be arrays")

    raw_values = (
        " ".join(str(lesson.get("title") or "Untitled Showrun").split())[:120],
        str(lesson.get("description") or "").strip()[:500],
        str(recording.get("session_id") or "")[:255],
        str(recording.get("source_format") or "unknown")[:80],
        tuple(str(value)[:500] for value in output_values),
        tuple(str(value)[:500] for value in warning_values),
    )
    clean_values = (
        redact_text(raw_values[0]),
        redact_text(raw_values[1]),
        redact_text(raw_values[2]),
        redact_text(raw_values[3]),
        tuple(redact_text(value) for value in raw_values[4]),
        tuple(redact_text(value) for value in raw_values[5]),
    )
    return (
        ShowrunArtifact(
            title=clean_values[0],
            description=clean_values[1],
            session_id=clean_values[2],
            source_format=clean_values[3],
            events=events,
            chapters=chapters,
            duration=duration,
            outputs=clean_values[4],
            warnings=clean_values[5],
        ),
        clean_values != raw_values,
    )
