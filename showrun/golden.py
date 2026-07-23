"""Keep Showrun's bundled dogfood lesson current across deployments."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from chirp.data import QueryError

from showrun.artifacts import ShowrunArtifact
from showrun.store import ShowrunStore

GOLDEN_LESSON_ID = "lesson_golden"


async def sync_golden(store: ShowrunStore, artifact: ShowrunArtifact) -> None:
    """Create or revision the bundled lesson when its manifest changes."""

    existing = await store.get_lesson(GOLDEN_LESSON_ID)
    if existing is None:
        try:
            await store.seed_golden(artifact)
            return
        except QueryError:
            if await store.get_lesson(GOLDEN_LESSON_ID) is None:
                raise
    manifest_json = artifact.to_json()
    updated_at = datetime.now(UTC).isoformat(timespec="seconds")
    digest = hashlib.sha256(manifest_json.encode()).hexdigest()
    async with store.db.transaction():
        current = await store.get_lesson(GOLDEN_LESSON_ID)
        if current is None or current.manifest_json == manifest_json:
            return
        changed = await store.db.execute(
            "UPDATE lessons SET title = ?, description = ?, manifest_json = ?, "
            "revision = revision + 1, updated_at = ? WHERE id = ? AND manifest_json = ?",
            artifact.title,
            artifact.description,
            manifest_json,
            updated_at,
            current.id,
            current.manifest_json,
        )
        if changed:
            await store.db.execute(
                "UPDATE recordings SET session_id = ?, title = ?, source_format = ?, "
                "source_sha256 = ?, event_count = ? WHERE id = ?",
                artifact.session_id,
                artifact.title,
                artifact.source_format,
                digest,
                len(artifact.events),
                current.recording_id,
            )
