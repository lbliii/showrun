"""Portable trace and lesson artifacts for Showrun."""

from __future__ import annotations

import json
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One normalized event from an agent session."""

    id: int
    at: float
    kind: str
    label: str
    text: str
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
    """A source trace and its presentation layer."""

    title: str
    session_id: str
    events: tuple[TraceEvent, ...]
    chapters: tuple[Chapter, ...]
    duration: float
    outputs: tuple[str, ...]

    def player_config(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "sessionId": self.session_id,
            "duration": self.duration,
            "events": [asdict(event) for event in self.events],
            "chapters": [asdict(chapter) for chapter in self.chapters],
        }


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


def load_session(path: Path) -> tuple[str, str, tuple[TraceEvent, ...]]:
    """Read a JSONL session and normalize its messages and execution events."""

    title = "Untitled agent session"
    session_id = path.stem
    events: list[TraceEvent] = []

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        payload = json.loads(raw_line)
        if payload.get("type") == "session":
            title = str(payload.get("name") or title)
            session_id = str(payload.get("id") or session_id)
            continue

        event_id = len(events) + 1
        at = float(payload.get("at", event_id - 1))
        if payload.get("type") == "message":
            message = payload.get("message") or {}
            role = str(message.get("role") or "assistant")
            kind = "user" if role == "user" else "assistant"
            label = "You" if kind == "user" else "Codex"
            text = str(message.get("content") or "")
        elif payload.get("type") == "event":
            event = payload.get("event") or {}
            kind = str(event.get("kind") or "tool")
            label = "Web research" if kind == "tool" else "Build"
            text = str(event.get("content") or "")
        else:
            raise ValueError(f"Unsupported session record on line {line_number}")

        preview = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        events.append(
            TraceEvent(
                id=event_id,
                at=at,
                kind=kind,
                label=label,
                text=text,
                meta=_EVENT_META.get(event_id, ""),
                code=_EVENT_CODE.get(event_id, ""),
                raw_preview=preview,
            )
        )

    if not events:
        raise ValueError("The session contains no replayable events")
    return title, session_id, tuple(events)


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
    """Load and validate the two-layer Showrun artifact."""

    source_title, session_id, events = load_session(session_path)
    lesson_title, chapters, outputs = load_lesson(lesson_path)
    duration = max(events[-1].at + 3, chapters[-1].at + 10)
    return ShowrunArtifact(
        title=lesson_title or source_title,
        session_id=session_id,
        events=events,
        chapters=chapters,
        duration=duration,
        outputs=outputs,
    )
