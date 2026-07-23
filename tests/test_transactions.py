"""Atomic persistence guarantees for drafts and releases."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from chirp.data import QueryError
from chirp.testing import TestClient

from showrun.store import ShowrunStore
from showrun.web import create_app


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        secret_key="test-signing-key-with-enough-entropy",
    )


async def test_failed_lesson_insert_rolls_back_recording(tmp_path: Path) -> None:
    app = _application(tmp_path / "draft-transaction.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        golden = await store.get_lesson("lesson_golden")
        assert golden is not None

        with pytest.raises(QueryError):
            await store.create_draft(
                golden.artifact,
                recording_id="recording_should_rollback",
                lesson_id="lesson_golden",
            )

        count = await app.db.fetch_val(
            "SELECT COUNT(*) FROM recordings WHERE id = ?",
            "recording_should_rollback",
        )
        assert count == 0


async def test_publish_rolls_back_and_repairs_existing_release(tmp_path: Path) -> None:
    app = _application(tmp_path / "publish-transaction.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        golden = await store.get_lesson("lesson_golden")
        assert golden is not None
        draft = await store.create_draft(golden.artifact)
        await app.db.execute(
            "CREATE TRIGGER fail_lesson_publish BEFORE UPDATE ON lessons "
            f"WHEN NEW.id = '{draft.id}' BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
        )

        with pytest.raises(QueryError):
            await store.publish(draft.id, "public")
        release_count = await app.db.fetch_val(
            "SELECT COUNT(*) FROM releases WHERE lesson_id = ?",
            draft.id,
        )
        assert release_count == 0

        await app.db.execute("DROP TRIGGER fail_lesson_publish")
        release = await store.publish(draft.id, "public")
        await app.db.execute(
            "UPDATE lessons SET status = 'draft', visibility = 'private' WHERE id = ?",
            draft.id,
        )
        repaired = await store.publish(draft.id, "public")
        lesson = await store.get_lesson(draft.id)

        assert repaired.id == release.id
        assert lesson is not None
        assert (lesson.status, lesson.visibility) == ("published", "public")


async def test_unlisted_release_never_leaks_through_public_library(tmp_path: Path) -> None:
    app = _application(tmp_path / "release-visibility.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        golden = await store.get_lesson("lesson_golden")
        assert golden is not None
        user = await store.create_user(
            email="privacy@example.com",
            name="Privacy Test",
            password_hash="test-only-hash",
        )
        draft = await store.create_draft(
            golden.artifact,
            workspace_id=user.workspace_id,
        )
        unlisted = await store.publish(
            draft.id,
            "unlisted",
            workspace_id=user.workspace_id,
        )
        public = await store.publish(
            draft.id,
            "public",
            workspace_id=user.workspace_id,
        )

        await store.unpublish_release(public.slug, workspace_id=user.workspace_id)
        public_lessons = await store.list_lessons(public_only=True)
        lesson = await store.get_lesson(draft.id)
        active = await store.get_release(unlisted.slug)

        assert draft.id not in {item.id for item in public_lessons}
        assert lesson is not None
        assert (lesson.status, lesson.visibility) == ("published", "unlisted")
        assert active is not None


async def test_concurrent_publish_returns_one_release(tmp_path: Path) -> None:
    app = _application(tmp_path / "concurrent-publish.db")
    async with TestClient(app):
        first_store = ShowrunStore(app.db)
        second_store = ShowrunStore(app.db)
        golden = await first_store.get_lesson("lesson_golden")
        assert golden is not None
        draft = await first_store.create_draft(golden.artifact)

        first, second = await asyncio.gather(
            first_store.publish(draft.id, "unlisted"),
            second_store.publish(draft.id, "unlisted"),
        )
        count = await app.db.fetch_val(
            "SELECT COUNT(*) FROM releases "
            "WHERE lesson_id = ? AND revision = ? AND visibility = 'unlisted'",
            draft.id,
            draft.revision,
        )

        assert first.id == second.id
        assert count == 1


async def test_public_card_uses_immutable_release_metadata(tmp_path: Path) -> None:
    app = _application(tmp_path / "release-card.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        golden = await store.get_lesson("lesson_golden")
        assert golden is not None
        user = await store.create_user(
            email="release-card@example.com",
            name="Release Card",
            password_hash="test-only-hash",
        )
        draft = await store.create_draft(
            replace(golden.artifact, title="Published snapshot"),
            workspace_id=user.workspace_id,
        )
        release = await store.publish(
            draft.id,
            "public",
            workspace_id=user.workspace_id,
        )
        await store.update_lesson(
            draft.id,
            workspace_id=user.workspace_id,
            artifact=replace(draft.artifact, title="PRIVATE DRAFT TITLE"),
        )

        cards = await store.list_lessons(public_only=True, query="published snapshot")
        card = next(item for item in cards if item.id == draft.id)

        assert card.title == release.artifact.title == "Published snapshot"
        assert "PRIVATE DRAFT TITLE" not in card.title
