"""Import, direct, and serialize Showrun's portable ``dvd/1`` artifacts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from itertools import pairwise
from pathlib import Path
from typing import Any

from showrun.evidence import (
    ACTIVITY_STATUSES as _ACTIVITY_STATUSES,
)
from showrun.evidence import (
    EvidenceSource,
    redact_text,
)

FORMAT_VERSION = "dvd/1"
ACTIVITY_STATUSES = _ACTIVITY_STATUSES
ACTIVITY_TYPES = frozenset(
    {"", "delegation", "decision", "file", "mcp", "search", "source", "test", "tool"}
)


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One normalized and editorially timed event from an agent session."""

    id: int
    at: float
    duration: float
    kind: str
    label: str
    text: str
    source_at: float = 0
    meta: str = ""
    code: str = ""
    raw_preview: str = ""
    pause_after: float = 0.7
    activity: str = ""
    status: str = ""
    provider: str = ""
    operation: str = ""
    input_preview: str = ""
    output_preview: str = ""
    elapsed_ms: int = 0
    sources: tuple[EvidenceSource, ...] = ()
    redactions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Chapter:
    """Editorial metadata layered over an immutable source trace."""

    name: str
    at: float
    caption: str = ""
    note: str = ""
    teaching_point: str = ""


@dataclass(frozen=True, slots=True)
class ShowrunArtifact:
    """A normalized recording and its directed presentation layer."""

    title: str
    session_id: str
    source_format: str
    events: tuple[TraceEvent, ...]
    chapters: tuple[Chapter, ...]
    duration: float
    description: str = ""
    outputs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def player_config(self) -> dict[str, Any]:
        """Return the browser player's stable input contract."""

        return {
            "format": FORMAT_VERSION,
            "title": self.title,
            "sessionId": self.session_id,
            "duration": self.duration,
            "events": [asdict(event) for event in self.events],
            "chapters": [asdict(chapter) for chapter in self.chapters],
        }

    def to_manifest(self) -> dict[str, Any]:
        """Materialize a portable, self-contained ``dvd/1`` manifest."""

        return {
            "format": FORMAT_VERSION,
            "recording": {
                "session_id": self.session_id,
                "source_format": self.source_format,
            },
            "lesson": {
                "title": self.title,
                "description": self.description,
                "duration": self.duration,
            },
            "events": [asdict(event) for event in self.events],
            "chapters": [asdict(chapter) for chapter in self.chapters],
            "outputs": list(self.outputs),
            "warnings": list(self.warnings),
        }

    def to_json(self) -> str:
        """Serialize the portable manifest deterministically."""

        return json.dumps(self.to_manifest(), ensure_ascii=False, separators=(",", ":"))


def _reading_duration(event: TraceEvent) -> float:
    if event.kind == "tool":
        return 2.4
    words = max(1, len(event.text.split()))
    return round(max(2.5, min(12.0, 1.6 + words / 3.2)), 1)


def apply_smart_pacing(events: tuple[TraceEvent, ...]) -> tuple[TraceEvent, ...]:
    """Compress invisible latency and allocate deterministic reading time."""

    directed: list[TraceEvent] = []
    cursor = 0.0
    for event in events:
        duration = _reading_duration(event)
        pause_after = 0.4 if event.kind == "tool" else 0.7
        directed.append(
            replace(event, at=round(cursor, 1), duration=duration, pause_after=pause_after)
        )
        cursor += duration + pause_after
    return tuple(directed)


def short_title(text: str, fallback: str) -> str:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text)
    if not words:
        return fallback
    title = " ".join(words[:8])
    return title[:1].upper() + title[1:]


def suggest_chapters(events: tuple[TraceEvent, ...]) -> tuple[Chapter, ...]:
    """Propose a compact chapter outline from user turns."""

    selected: list[TraceEvent] = [events[0]]
    for event in events[1:]:
        if event.kind == "user" and event.id - selected[-1].id >= 4:
            selected.append(event)
        if len(selected) == 5:
            break

    chapters: list[Chapter] = []
    for index, event in enumerate(selected):
        name = "Opening" if index == 0 else short_title(event.text, f"Chapter {index + 1}")
        chapters.append(
            Chapter(
                name=name,
                at=event.at,
                caption=name,
                note="Review the decisions and evidence in this part of the run.",
                teaching_point="Notice how the session moves from intent to a verifiable outcome.",
            )
        )
    return tuple(chapters)


def create_artifact_from_text(
    text: str,
    *,
    filename: str = "session.jsonl",
    title: str = "",
) -> ShowrunArtifact:
    """Import a session and automatically direct a watchable draft."""

    from showrun.importers import parse_session_text

    imported_title, session_id, source_format, source_events, warnings = parse_session_text(
        text,
        filename=filename,
    )
    events = apply_smart_pacing(source_events)
    chapters = suggest_chapters(events)
    duration = round(events[-1].at + events[-1].duration + 1.5, 1)
    base_title = title.strip()[:120] or imported_title
    clean_title = redact_text(base_title)
    if clean_title != base_title and "Potential credentials were redacted locally." not in warnings:
        warnings += ("Potential credentials were redacted locally.",)
    return ShowrunArtifact(
        title=clean_title,
        session_id=session_id,
        source_format=source_format,
        events=events,
        chapters=chapters,
        duration=duration,
        description="Automatically directed from an imported agent session.",
        warnings=warnings,
    )


def direct_artifact(
    artifact: ShowrunArtifact,
    *,
    title: str,
    description: str,
    included_event_ids: set[int],
    event_durations: Mapping[int, str | float],
    chapter_values: tuple[dict[str, str], ...],
    event_orders: Mapping[int, str | int] | None = None,
    event_pauses: Mapping[int, str | float] | None = None,
    event_labels: Mapping[int, str] | None = None,
    event_texts: Mapping[int, str] | None = None,
) -> ShowrunArtifact:
    """Apply the small director surface while preserving sanitized source metadata."""

    base_title = " ".join(title.split())[:120]
    base_description = description.strip()[:500]
    clean_title = redact_text(base_title)
    if not clean_title:
        raise ValueError("Give the lesson a title.")
    clean_description = redact_text(base_description)
    credentials_redacted = (clean_title, clean_description) != (
        base_title,
        base_description,
    )

    event_orders = event_orders or {}
    event_pauses = event_pauses or {}
    event_labels = event_labels or {}
    event_texts = event_texts or {}
    selected: list[tuple[float, int, TraceEvent]] = []
    for source_index, source_event in enumerate(artifact.events):
        if source_event.id not in included_event_ids:
            continue
        raw_order = event_orders.get(source_event.id, source_index + 1)
        try:
            order = float(raw_order) if str(raw_order).strip() else float(source_index + 1)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Event {source_event.id} needs a valid order.") from exc
        selected.append((order, source_index, source_event))
    selected.sort(key=lambda item: (item[0], item[1]))

    events: list[TraceEvent] = []
    cursor = 0.0
    for _order, _source_index, source_event in selected:
        try:
            duration = round(float(event_durations[source_event.id]), 1)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Event {source_event.id} needs a valid duration.") from exc
        if not 1 <= duration <= 60:
            raise ValueError(f"Event {source_event.id} duration must be between 1 and 60 seconds.")
        raw_pause = event_pauses.get(source_event.id, source_event.pause_after)
        try:
            pause_after = round(float(raw_pause), 1) if str(raw_pause).strip() else 0.0
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Event {source_event.id} needs a valid pause.") from exc
        if not 0 <= pause_after <= 30:
            raise ValueError(f"Event {source_event.id} pause must be between 0 and 30 seconds.")
        base_label = " ".join(event_labels.get(source_event.id, source_event.label).split())[:80]
        base_text = event_texts.get(source_event.id, source_event.text).strip()[:10000]
        label = redact_text(base_label)
        text = redact_text(base_text)
        credentials_redacted = credentials_redacted or (label, text) != (
            base_label,
            base_text,
        )
        if not label:
            raise ValueError(f"Event {source_event.id} needs a label.")
        if not text:
            raise ValueError(f"Event {source_event.id} needs content.")
        events.append(
            replace(
                source_event,
                id=len(events) + 1,
                at=round(cursor, 1),
                duration=duration,
                pause_after=pause_after,
                label=label,
                text=text,
            )
        )
        cursor += duration + pause_after
    if not events:
        raise ValueError("Keep at least one event in the lesson.")

    duration = round(events[-1].at + events[-1].duration + 1.5, 1)
    ordered_chapters: list[tuple[float, int, Chapter]] = []
    for index, values in enumerate(chapter_values, 1):
        if not values.get("include"):
            continue
        base_name = " ".join(values.get("name", "").split())[:80]
        name = redact_text(base_name)
        if not name:
            raise ValueError(f"Chapter {index} needs a name.")
        try:
            at = round(float(values.get("at", "0")), 1)
        except ValueError as exc:
            raise ValueError(f"Chapter {index} needs a valid start time.") from exc
        if not 0 <= at < duration:
            raise ValueError(f"Chapter {index} must start between 0 and {duration:.1f} seconds.")
        raw_order = values.get("order", str(index))
        try:
            order = float(raw_order) if raw_order.strip() else float(index)
        except ValueError as exc:
            raise ValueError(f"Chapter {index} needs a valid order.") from exc
        base_caption = values.get("caption", "").strip()[:160]
        base_note = values.get("note", "").strip()[:1000]
        base_teaching_point = values.get("teaching_point", "").strip()[:500]
        caption = redact_text(base_caption)
        note = redact_text(base_note)
        teaching_point = redact_text(base_teaching_point)
        credentials_redacted = credentials_redacted or (
            (name, caption, note, teaching_point)
            != (base_name, base_caption, base_note, base_teaching_point)
        )
        ordered_chapters.append(
            (
                order,
                index,
                Chapter(
                    name=name,
                    at=at,
                    caption=caption,
                    note=note,
                    teaching_point=teaching_point,
                ),
            )
        )
    ordered_chapters.sort(key=lambda item: (item[0], item[1]))
    chapters = [item[2] for item in ordered_chapters]
    if not chapters:
        raise ValueError("Keep at least one chapter.")
    if any(current.at < previous.at for previous, current in pairwise(chapters)):
        raise ValueError("Chapter start times must follow chapter order.")
    if chapters[0].at != 0:
        chapters[0] = replace(chapters[0], at=0)
    warnings = artifact.warnings
    redaction_warning = "Potential credentials were redacted locally."
    if credentials_redacted and redaction_warning not in warnings:
        warnings += (redaction_warning,)

    return replace(
        artifact,
        title=clean_title,
        description=clean_description,
        events=tuple(events),
        chapters=tuple(chapters),
        duration=duration,
        warnings=warnings,
    )


def load_artifact(session_path: Path, lesson_path: Path) -> ShowrunArtifact:
    """Load the hand-directed golden fixture."""

    from showrun.lesson_tape import load_artifact as parse_artifact

    return parse_artifact(session_path, lesson_path)


def artifact_from_json(raw: str) -> ShowrunArtifact:
    """Validate and rehydrate a stored immutable manifest."""

    from showrun.artifact_serialization import artifact_from_json as parse_artifact

    return parse_artifact(raw)
