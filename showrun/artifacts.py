"""Import, direct, and serialize Showrun's portable ``dvd/1`` artifacts."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

FORMAT_VERSION = "dvd/1"


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
    return ShowrunArtifact(
        title=title.strip()[:120] or imported_title,
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

    clean_title = " ".join(title.split())[:120]
    if not clean_title:
        raise ValueError("Give the lesson a title.")
    clean_description = description.strip()[:500]

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
        label = " ".join(event_labels.get(source_event.id, source_event.label).split())[:80]
        text = event_texts.get(source_event.id, source_event.text).strip()[:10000]
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
        name = " ".join(values.get("name", "").split())[:80]
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
        ordered_chapters.append(
            (
                order,
                index,
                Chapter(
                    name=name,
                    at=at,
                    caption=values.get("caption", "").strip()[:160],
                    note=values.get("note", "").strip()[:1000],
                    teaching_point=values.get("teaching_point", "").strip()[:500],
                ),
            )
        )
    ordered_chapters.sort(key=lambda item: (item[0], item[1]))
    chapters = [item[2] for item in ordered_chapters]
    if not chapters:
        raise ValueError("Keep at least one chapter.")
    if chapters[0].at != 0:
        chapters[0] = replace(chapters[0], at=0)

    return replace(
        artifact,
        title=clean_title,
        description=clean_description,
        events=tuple(events),
        chapters=tuple(chapters),
        duration=duration,
    )


def load_lesson(path: Path) -> tuple[str | None, tuple[Chapter, ...], tuple[str, ...]]:
    """Parse the intentionally small Showrun tape language."""

    title: str | None = None
    chapters: list[Chapter] = []
    outputs: list[str] = []
    current: dict[str, Any] | None = None

    def commit() -> None:
        nonlocal current
        if current is not None:
            chapters.append(Chapter(**current))
            current = None

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            raise ValueError(f"Invalid tape syntax on line {line_number}: {exc}") from exc
        command, *values = parts

        if command == "Title":
            title = " ".join(values)
        elif command == "Chapter":
            commit()
            if len(values) != 3 or values[1] != "At":
                message = f"Chapter requires: Chapter <name> At <seconds> (line {line_number})"
                raise ValueError(message)
            current = {"name": values[0], "at": float(values[2])}
        elif command in {"Caption", "Note", "TeachingPoint"}:
            if current is None:
                raise ValueError(f"{command} must follow a Chapter (line {line_number})")
            field = {
                "Caption": "caption",
                "Note": "note",
                "TeachingPoint": "teaching_point",
            }[command]
            current[field] = " ".join(values)
        elif command == "Output":
            outputs.append(" ".join(values))
        elif command in {"Source", "Set", "Focus", "Pause", "Highlight", "Assert"}:
            continue
        else:
            raise ValueError(f"Unknown tape command {command!r} on line {line_number}")

    commit()
    if not chapters:
        raise ValueError("The lesson contains no chapters")
    return title, tuple(chapters), tuple(outputs)


def load_artifact(session_path: Path, lesson_path: Path) -> ShowrunArtifact:
    """Load the hand-directed golden fixture."""

    from showrun.importers import parse_session_text

    source_text = session_path.read_text(encoding="utf-8")
    source_title, session_id, source_format, events, warnings = parse_session_text(
        source_text,
        filename=session_path.name,
    )
    lesson_title, chapters, outputs = load_lesson(lesson_path)
    timed_events = tuple(
        replace(
            event,
            duration=round(
                max(2, (events[index + 1].at - event.at) - 0.5) if index + 1 < len(events) else 3,
                1,
            ),
        )
        for index, event in enumerate(events)
    )
    duration = max(timed_events[-1].at + 3, chapters[-1].at + 10)
    return ShowrunArtifact(
        title=lesson_title or source_title,
        session_id=session_id,
        source_format=source_format,
        events=timed_events,
        chapters=chapters,
        duration=duration,
        outputs=outputs,
        warnings=warnings,
    )


def artifact_from_json(raw: str) -> ShowrunArtifact:
    """Validate and rehydrate a stored immutable manifest."""

    payload = json.loads(raw)
    if payload.get("format") != FORMAT_VERSION:
        raise ValueError("Unsupported Showrun artifact format")
    recording = payload.get("recording") or {}
    lesson = payload.get("lesson") or {}
    events = tuple(TraceEvent(**event) for event in payload.get("events") or ())
    chapters = tuple(Chapter(**chapter) for chapter in payload.get("chapters") or ())
    if not events or not chapters:
        raise ValueError("Artifact requires at least one event and chapter")
    duration = float(lesson.get("duration") or 0)
    if duration <= events[-1].at:
        raise ValueError("Artifact duration must extend beyond its final event")
    return ShowrunArtifact(
        title=str(lesson.get("title") or "Untitled Showrun"),
        description=str(lesson.get("description") or ""),
        session_id=str(recording.get("session_id") or ""),
        source_format=str(recording.get("source_format") or "unknown"),
        events=events,
        chapters=chapters,
        duration=duration,
        outputs=tuple(payload.get("outputs") or ()),
        warnings=tuple(payload.get("warnings") or ()),
    )
