"""Governed topic catalog + normalized assignment (#36, under #15)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from chirp.testing import TestClient

from showrun.community import CommunityStore, TechniqueCardError, validate_card
from showrun.store import ShowrunStore
from showrun.web import create_app
from tests.test_community_web import (
    _publish_public_release,
    _publish_technique,
    _signup,
)


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        secret_key="test-signing-key-with-enough-entropy",
    )


async def test_catalog_is_seeded(tmp_path: Path) -> None:
    app = _application(tmp_path / "catalog.db")
    async with TestClient(app):
        community = CommunityStore(app.db)
        topics = await community.list_topics()
        keys = {t.key for t in topics}
        assert {"reliability", "tools", "security", "planning"} <= keys
        # Every seeded topic has a human label and description.
        assert all(t.label and t.description for t in topics)


async def test_publish_rejects_ungoverned_topic(tmp_path: Path) -> None:
    app = _application(tmp_path / "govern.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user = await store.create_user(
            email="c@example.com", name="Creator", password_hash="test-only-hash"
        )
        golden = await store.get_lesson("lesson_golden")
        draft = await store.create_draft(
            replace(golden.artifact, title="Retry"), workspace_id=user.workspace_id
        )
        release = await store.publish(draft.id, "public", workspace_id=user.workspace_id)

        # An ungoverned topic is rejected and leaves no partial records.
        with pytest.raises(TechniqueCardError):
            await community.publish_technique_version(
                user_id=user.id,
                workspace_id=user.workspace_id,
                display_name=user.name,
                email=user.email,
                release_slug=release.slug,
                card=validate_card(
                    problem="p",
                    pattern="pattern text",
                    use_when="when",
                    objective="obj",
                    summary="s",
                    topics=("totally-made-up-topic",),
                ),
            )
        assert await community.public_technique_count() == 0

        # A governed topic publishes cleanly.
        _technique, _v, created = await community.publish_technique_version(
            user_id=user.id,
            workspace_id=user.workspace_id,
            display_name=user.name,
            email=user.email,
            release_slug=release.slug,
            card=validate_card(
                problem="p",
                pattern="pattern text",
                use_when="when",
                objective="obj",
                summary="s",
                topics=("reliability",),
            ),
        )
        assert created is True
        assert await community.public_technique_count(topic="reliability") == 1


async def test_topics_index_lists_catalog_with_counts(tmp_path: Path) -> None:
    app = _application(tmp_path / "topics-index.db")
    async with TestClient(app) as client:
        cookie = await _signup(client, email="creator@example.com", name="Ada Creator")
        lesson_path, cookie = await _publish_public_release(client, cookie, title="Retry pattern")
        await _publish_technique(client, cookie, lesson_path, topics="reliability")

        index = await client.get("/topics")
        assert index.status == 200
        assert "Reliability" in index.text
        assert "Planning" in index.text
        # Links to each topic page.
        assert '/topics/reliability' in index.text

        # The publish form advertises the governed catalog.
        form = await client.get(f"{lesson_path}/technique", headers={"Cookie": cookie})
        assert 'id="topic-catalog"' in form.text
        assert "reliability" in form.text


async def test_form_rejects_ungoverned_topic_over_http(tmp_path: Path) -> None:
    app = _application(tmp_path / "form-reject.db")
    async with TestClient(app) as client:
        cookie = await _signup(client, email="creator@example.com", name="Ada Creator")
        lesson_path, cookie = await _publish_public_release(client, cookie, title="Retry pattern")
        # The publish helper asserts a 303; an ungoverned topic must NOT publish.
        with pytest.raises(AssertionError):
            await _publish_technique(client, cookie, lesson_path, topics="nonsense-topic")
