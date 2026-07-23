"""Bundled dogfood lesson synchronization."""

from dataclasses import replace
from pathlib import Path

from chirp.testing import TestClient

from showrun.golden import sync_golden
from showrun.store import ShowrunStore
from showrun.web import create_app


async def test_changed_golden_creates_one_new_revision(tmp_path: Path) -> None:
    app = create_app(
        f"sqlite:///{tmp_path / 'golden.db'}",
        secret_key="test-signing-key-with-enough-entropy",
    )
    async with TestClient(app):
        store = ShowrunStore(app.db)
        original = await store.get_lesson("lesson_golden")
        assert original is not None
        updated_artifact = replace(original.artifact, description="Updated dogfood evidence.")

        await sync_golden(store, updated_artifact)
        updated = await store.get_lesson("lesson_golden")
        assert updated is not None
        assert updated.revision == original.revision + 1
        assert updated.artifact.description == "Updated dogfood evidence."

        await store.publish("lesson_golden", "public")
        await sync_golden(store, updated_artifact)
        stable = await store.get_lesson("lesson_golden")
        assert stable is not None
        assert stable.revision == updated.revision
