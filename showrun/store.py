"""Persistence operations for recordings, lessons, and immutable releases."""

from __future__ import annotations

import hashlib
import json
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
class UserRecord:
    id: str
    workspace_id: str
    email: str
    name: str
    password_hash: str
    created_at: str
    is_authenticated: bool = True
    scopes: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ApiTokenRecord:
    id: str
    name: str
    token_prefix: str
    scopes: str
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


@dataclass(frozen=True, slots=True)
class UsageMetrics:
    imports: int = 0
    publishes: int = 0
    views: int = 0
    embeds: int = 0
    plays: int = 0
    completions: int = 0

    @property
    def completion_rate(self) -> int:
        return round(self.completions / self.plays * 100) if self.plays else 0


@dataclass(frozen=True, slots=True)
class LessonRecord:
    id: str
    recording_id: str
    workspace_id: str | None
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

    async def create_user(
        self,
        *,
        email: str,
        name: str,
        password_hash: str,
    ) -> UserRecord:
        now = _now()
        user_id = f"user_{uuid4().hex}"
        workspace_id = f"workspace_{uuid4().hex}"
        async with self.db.transaction():
            await self.db.execute(
                "INSERT INTO workspaces (id, name, created_at) VALUES (?, ?, ?)",
                workspace_id,
                f"{name}'s workspace",
                now,
            )
            await self.db.execute(
                "INSERT INTO users "
                "(id, workspace_id, email, name, password_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                user_id,
                workspace_id,
                email,
                name,
                password_hash,
                now,
            )
        user = await self.get_user(user_id)
        if user is None:
            raise RuntimeError("Account was not persisted")
        return user

    async def get_user(self, user_id: str) -> UserRecord | None:
        return await self.db.fetch_one(
            UserRecord,
            "SELECT id, workspace_id, email, name, password_hash, created_at "
            "FROM users WHERE id = ?",
            user_id,
        )

    async def get_user_by_email(self, email: str) -> UserRecord | None:
        return await self.db.fetch_one(
            UserRecord,
            "SELECT id, workspace_id, email, name, password_hash, created_at "
            "FROM users WHERE email = ?",
            email,
        )

    async def get_user_by_token_hash(self, digest: str) -> tuple[UserRecord, str] | None:
        token = await self.db.fetch_one(
            _TokenUserRow,
            "SELECT u.id, u.workspace_id, u.email, u.name, u.password_hash, u.created_at, "
            "t.scopes FROM api_tokens t JOIN users u ON u.id = t.user_id "
            "WHERE t.token_hash = ? AND t.revoked_at IS NULL",
            digest,
        )
        if token is None:
            return None
        return (
            UserRecord(
                id=token.id,
                workspace_id=token.workspace_id,
                email=token.email,
                name=token.name,
                password_hash=token.password_hash,
                created_at=token.created_at,
            ),
            token.scopes,
        )

    async def create_api_token(
        self,
        *,
        user: UserRecord,
        name: str,
        token_prefix: str,
        token_hash: str,
        scopes: str = "imports:write",
    ) -> ApiTokenRecord:
        token_id = f"token_{uuid4().hex}"
        now = _now()
        await self.db.execute(
            "INSERT INTO api_tokens "
            "(id, user_id, workspace_id, name, token_prefix, token_hash, scopes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            token_id,
            user.id,
            user.workspace_id,
            name,
            token_prefix,
            token_hash,
            scopes,
            now,
        )
        result = await self.db.fetch_one(
            ApiTokenRecord,
            "SELECT id, name, token_prefix, scopes, created_at, last_used_at, revoked_at "
            "FROM api_tokens WHERE id = ?",
            token_id,
        )
        if result is None:
            raise RuntimeError("API token was not persisted")
        return result

    async def list_api_tokens(self, user: UserRecord) -> list[ApiTokenRecord]:
        return await self.db.fetch(
            ApiTokenRecord,
            "SELECT id, name, token_prefix, scopes, created_at, last_used_at, revoked_at "
            "FROM api_tokens WHERE user_id = ? ORDER BY created_at DESC",
            user.id,
        )

    async def revoke_api_token(self, user: UserRecord, token_id: str) -> None:
        await self.db.execute(
            "UPDATE api_tokens SET revoked_at = ? "
            "WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
            _now(),
            token_id,
            user.id,
        )

    async def touch_api_token(self, digest: str) -> None:
        await self.db.execute(
            "UPDATE api_tokens SET last_used_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            _now(),
            digest,
        )

    async def record_usage(
        self,
        event_name: str,
        *,
        workspace_id: str | None = None,
        lesson_id: str | None = None,
        release_id: str | None = None,
        properties: dict[str, str | int | float | bool] | None = None,
    ) -> None:
        resolved_workspace = workspace_id
        if resolved_workspace is None and lesson_id is not None:
            resolved_workspace = await self.db.fetch_val(
                "SELECT workspace_id FROM lessons WHERE id = ?",
                lesson_id,
            )
        await self.db.execute(
            "INSERT INTO usage_events "
            "(id, workspace_id, lesson_id, release_id, event_name, properties_json, "
            "occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            f"usage_{uuid4().hex}",
            resolved_workspace,
            lesson_id,
            release_id,
            event_name,
            json.dumps(properties or {}, ensure_ascii=False, separators=(",", ":")),
            _now(),
        )

    async def usage_metrics(self, workspace_id: str) -> UsageMetrics:
        async def count(name: str) -> int:
            value = await self.db.fetch_val(
                "SELECT COUNT(*) FROM usage_events WHERE workspace_id = ? AND event_name = ?",
                workspace_id,
                name,
            )
            return int(value or 0)

        return UsageMetrics(
            imports=await count("lesson.imported"),
            publishes=await count("lesson.published"),
            views=await count("release.viewed"),
            embeds=await count("release.embedded"),
            plays=await count("playback.started"),
            completions=await count("playback.completed"),
        )

    async def create_draft(
        self,
        artifact: ShowrunArtifact,
        *,
        workspace_id: str | None = None,
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
            "(id, session_id, title, source_format, source_sha256, event_count, created_at, "
            "workspace_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            resolved_recording_id,
            artifact.session_id,
            artifact.title,
            artifact.source_format,
            digest,
            len(artifact.events),
            now,
            workspace_id,
        )
        await self.db.execute(
            "INSERT INTO lessons "
            "(id, recording_id, title, description, status, visibility, revision, "
            "manifest_json, created_at, updated_at, workspace_id) "
            "VALUES (?, ?, ?, ?, 'draft', 'private', 1, ?, ?, ?, ?)",
            resolved_lesson_id,
            resolved_recording_id,
            artifact.title,
            artifact.description,
            manifest_json,
            now,
            now,
            workspace_id,
        )
        result = await self.get_lesson(resolved_lesson_id)
        if result is None:
            raise RuntimeError("Draft was not persisted")
        return result

    async def find_duplicate(self, workspace_id: str, source_sha256: str) -> LessonRecord | None:
        return await self.db.fetch_one(
            LessonRecord,
            "SELECT l.id, l.recording_id, l.workspace_id, l.title, l.description, "
            "l.status, l.visibility, l.revision, l.manifest_json, l.created_at, "
            "l.updated_at, l.published_at FROM lessons l "
            "JOIN recordings r ON r.id = l.recording_id "
            "WHERE l.workspace_id = ? AND r.source_sha256 = ? LIMIT 1",
            workspace_id,
            source_sha256,
        )

    async def update_lesson(
        self,
        lesson_id: str,
        *,
        workspace_id: str,
        artifact: ShowrunArtifact,
    ) -> LessonRecord:
        now = _now()
        changed = await self.db.execute(
            "UPDATE lessons SET title = ?, description = ?, manifest_json = ?, "
            "revision = revision + 1, status = 'draft', visibility = 'private', "
            "updated_at = ? WHERE id = ? AND workspace_id = ?",
            artifact.title,
            artifact.description,
            artifact.to_json(),
            now,
            lesson_id,
            workspace_id,
        )
        if not changed:
            raise LookupError("Lesson not found")
        lesson = await self.get_lesson(lesson_id, workspace_id=workspace_id)
        if lesson is None:
            raise RuntimeError("Lesson update was not persisted")
        return lesson

    async def seed_golden(self, artifact: ShowrunArtifact) -> None:
        if await self.get_lesson("lesson_golden") is not None:
            return
        await self.create_draft(
            artifact,
            recording_id="recording_golden",
            lesson_id="lesson_golden",
        )

    async def list_lessons(
        self,
        *,
        workspace_id: str | None = None,
        public_only: bool = False,
    ) -> list[LessonCard]:
        params: tuple[str, ...] = ()
        if public_only:
            where = " WHERE l.status = 'published' AND l.visibility = 'public'"
        elif workspace_id is not None:
            where = " WHERE l.workspace_id = ?"
            params = (workspace_id,)
        else:
            where = ""
        return await self.db.fetch(
            LessonCard,
            "SELECT l.id, l.title, l.description, l.status, l.visibility, l.revision, "
            "r.event_count, l.updated_at, l.published_at, "
            "(SELECT slug FROM releases rr WHERE rr.lesson_id = l.id "
            "ORDER BY rr.published_at DESC LIMIT 1) AS release_slug "
            "FROM lessons l JOIN recordings r ON r.id = l.recording_id"
            f"{where} ORDER BY l.updated_at DESC, l.id ASC",
            *params,
        )

    async def get_lesson(
        self,
        lesson_id: str,
        *,
        workspace_id: str | None = None,
    ) -> LessonRecord | None:
        ownership = " AND workspace_id = ?" if workspace_id is not None else ""
        params = (lesson_id, workspace_id) if workspace_id is not None else (lesson_id,)
        return await self.db.fetch_one(
            LessonRecord,
            "SELECT id, recording_id, workspace_id, title, description, status, visibility, "
            "revision, "
            "manifest_json, created_at, updated_at, published_at "
            f"FROM lessons WHERE id = ?{ownership}",
            *params,
        )

    async def get_release(self, slug: str) -> ReleaseRecord | None:
        return await self.db.fetch_one(
            ReleaseRecord,
            "SELECT id, lesson_id, revision, slug, visibility, manifest_json, published_at "
            "FROM releases WHERE slug = ?",
            slug,
        )

    async def get_release_for_revision(
        self,
        lesson_id: str,
        revision: int,
        visibility: str,
    ) -> ReleaseRecord | None:
        return await self.db.fetch_one(
            ReleaseRecord,
            "SELECT id, lesson_id, revision, slug, visibility, manifest_json, published_at "
            "FROM releases WHERE lesson_id = ? AND revision = ? AND visibility = ?",
            lesson_id,
            revision,
            visibility,
        )

    async def publish(
        self,
        lesson_id: str,
        visibility: str,
        *,
        workspace_id: str | None = None,
    ) -> ReleaseRecord:
        if visibility not in {"unlisted", "public"}:
            raise ValueError("Published visibility must be unlisted or public")
        lesson = await self.get_lesson(lesson_id, workspace_id=workspace_id)
        if lesson is None:
            raise LookupError("Lesson not found")
        existing = await self.get_release_for_revision(
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


@dataclass(frozen=True, slots=True)
class _TokenUserRow:
    id: str
    workspace_id: str
    email: str
    name: str
    password_hash: str
    created_at: str
    scopes: str
