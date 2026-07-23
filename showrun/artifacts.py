"""Import, direct, and serialize Showrun's portable ``dvd/1`` artifacts."""

from __future__ import annotations

import json
import re
import shlex
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
        directed.append(replace(event, at=round(cursor, 1), duration=duration))
        cursor += duration + (0.4 if event.kind == "tool" else 0.7)
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
