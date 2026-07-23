"""Parser for Showrun's intentionally small editorial tape language."""

from __future__ import annotations

import shlex
from dataclasses import replace
from pathlib import Path
from typing import Any

from showrun.artifacts import Chapter, ShowrunArtifact
from showrun.importers import parse_session_text


def load_lesson(path: Path) -> tuple[str | None, tuple[Chapter, ...], tuple[str, ...]]:
    """Parse a hand-authored lesson overlay."""

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
        elif command not in {"Source", "Set", "Focus", "Pause", "Highlight", "Assert"}:
            raise ValueError(f"Unknown tape command {command!r} on line {line_number}")
    commit()
    if not chapters:
        raise ValueError("The lesson contains no chapters")
    return title, tuple(chapters), tuple(outputs)


def load_artifact(session_path: Path, lesson_path: Path) -> ShowrunArtifact:
    """Load the hand-directed golden fixture."""

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
