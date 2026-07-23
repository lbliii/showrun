"""Persistence operations for recordings, lessons, and immutable releases."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from showrun.artifacts import ShowrunArtifact, artifact_from_json


@dataclass(frozen=True, slots=True)
class LessonCard:
    id: str
    title: str
    description: str
    status: str
    visibility: str
    revision: int
    event_count: int
    updated_at: str
    published_at: str | None
    release_slug: str | None


@dataclass(frozen=True, slots=True)
class LessonRecord:
    id: str
    recording_id: str
    title: str
    description: str
    status: str
    visibility: str
    revision: int
    manifest_json: str
    created_at: str
    updated_at: str
    published_at: str | None

    @property
    def artifact(self) -> ShowrunArtifact:
        return artifact_from_json(self.manifest_json)


@dataclass(frozen=True, slots=True)
class ReleaseRecord:
    id: str
    lesson_id: str
    revision: int
    slug: str
    visibility: str
    manifest_json: str
    published_at: str

    @property
    def artifact(self) -> ShowrunArtifact:
        return artifact_from_json(self.manifest_json)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _slugify(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48] or "showrun"
    return f"{base}-{uuid4().hex[:7]}"


class ShowrunStore:
    """Small command-oriented repository over Chirp's portable data layer."""

    def __init__(self, database: Any) -> None:
        self.db = database

    async def create_draft(
        self,
        artifact: ShowrunArtifact,
        *,
        source_sha256: str | None = None,
        recording_id: str | None = None,
        lesson_id: str | None = None,
    ) -> LessonRecord:
        now = _now()
        resolved_recording_id = recording_id or f"rec_{uuid4().hex}"
        resolved_lesson_id = lesson_id or f"lesson_{uuid4().hex}"
        manifest_json = artifact.to_json()
        digest = source_sha256 or hashlib.sha256(manifest_json.encode()).hexdigest()
        await self.db.execute(
            "INSERT INTO recordings "
            "(id, session_id, title, source_format, source_sha256, event_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            resolved_recording_id,
            artifact.session_id,
            artifact.title,
            artifact.source_format,
            digest,
            len(artifact.events),
            now,
        )
        await self.db.execute(
            "INSERT INTO lessons "
            "(id, recording_id, title, description, status, visibility, revision, "
            "manifest_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'draft', 'private', 1, ?, ?, ?)",
            resolved_lesson_id,
            resolved_recording_id,
            artifact.title,
            artifact.description,
            manifest_json,
            now,
            now,
        )
        result = await self.get_lesson(resolved_lesson_id)
        if result is None:
            raise RuntimeError("Draft was not persisted")
        return result

    async def seed_golden(self, artifact: ShowrunArtifact) -> None:
        if await self.get_lesson("lesson_golden") is not None:
            return
        await self.create_draft(
            artifact,
            recording_id="recording_golden",
            lesson_id="lesson_golden",
        )

    async def list_lessons(self, *, public_only: bool = False) -> list[LessonCard]:
        where = " WHERE l.status = 'published' AND l.visibility = 'public'" if public_only else ""
        return await self.db.fetch(
            LessonCard,
            "SELECT l.id, l.title, l.description, l.status, l.visibility, l.revision, "
            "r.event_count, l.updated_at, l.published_at, "
            "(SELECT slug FROM releases rr WHERE rr.lesson_id = l.id "
            "ORDER BY rr.published_at DESC LIMIT 1) AS release_slug "
            "FROM lessons l JOIN recordings r ON r.id = l.recording_id"
            f"{where} ORDER BY l.updated_at DESC, l.id ASC",
        )

    async def get_lesson(self, lesson_id: str) -> LessonRecord | None:
        return await self.db.fetch_one(
            LessonRecord,
            "SELECT id, recording_id, title, description, status, visibility, revision, "
            "manifest_json, created_at, updated_at, published_at "
            "FROM lessons WHERE id = ?",
            lesson_id,
        )

    async def get_release(self, slug: str) -> ReleaseRecord | None:
        return await self.db.fetch_one(
            ReleaseRecord,
            "SELECT id, lesson_id, revision, slug, visibility, manifest_json, published_at "
            "FROM releases WHERE slug = ?",
            slug,
        )

    async def publish(self, lesson_id: str, visibility: str) -> ReleaseRecord:
        if visibility not in {"unlisted", "public"}:
            raise ValueError("Published visibility must be unlisted or public")
        lesson = await self.get_lesson(lesson_id)
        if lesson is None:
            raise LookupError("Lesson not found")
        existing = await self.db.fetch_one(
            ReleaseRecord,
            "SELECT id, lesson_id, revision, slug, visibility, manifest_json, published_at "
            "FROM releases WHERE lesson_id = ? AND revision = ? AND visibility = ?",
            lesson.id,
            lesson.revision,
            visibility,
        )
        if existing is not None:
            return existing

        published_at = _now()
        release = ReleaseRecord(
            id=f"release_{uuid4().hex}",
            lesson_id=lesson.id,
            revision=lesson.revision,
            slug=_slugify(lesson.title),
            visibility=visibility,
            manifest_json=lesson.manifest_json,
            published_at=published_at,
        )
        await self.db.execute(
            "INSERT INTO releases "
            "(id, lesson_id, revision, slug, visibility, manifest_json, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            release.id,
            release.lesson_id,
            release.revision,
            release.slug,
            release.visibility,
            release.manifest_json,
            release.published_at,
        )
        await self.db.execute(
            "UPDATE lessons SET status = 'published', visibility = ?, published_at = ?, "
            "updated_at = ? WHERE id = ?",
            visibility,
            published_at,
            published_at,
            lesson.id,
        )
        return release
