"""Deterministic, explainable discovery ranking (#37, under #15)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from chirp.testing import TestClient

from showrun.community import CommunityStore, validate_card
from showrun.store import ShowrunStore
from showrun.web import create_app


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        secret_key="test-signing-key-with-enough-entropy",
    )


def _card(problem: str):
    return validate_card(
        problem=problem,
        pattern="Wrap the tool call in a bounded retry.",
        use_when="When a tool is idempotent.",
        objective="Learn resilient tool use.",
        summary=f"Summary for {problem}.",
        topics=("reliability",),
    )


async def _creator(store, community, *, email, name):
    user = await store.create_user(email=email, name=name, password_hash="test-only-hash")
    await community.ensure_profile(
        user_id=user.id, workspace_id=user.workspace_id, display_name=name, email=email
    )
    return user


async def _publish(store, community, user, *, title):
    golden = await store.get_lesson("lesson_golden")
    draft = await store.create_draft(
        replace(golden.artifact, title=title), workspace_id=user.workspace_id
    )
    release = await store.publish(draft.id, "public", workspace_id=user.workspace_id)
    technique, _v, _c = await community.publish_technique_version(
        user_id=user.id,
        workspace_id=user.workspace_id,
        display_name=user.name,
        email=user.email,
        release_slug=release.slug,
        card=_card(title),
    )
    return technique, release


async def test_completion_quality_boosts_and_is_explained(tmp_path: Path) -> None:
    app = _application(tmp_path / "rank-quality.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user = await _creator(store, community, email="c@example.com", name="Creator")
        _low, low_rel = await _publish(store, community, user, title="Low completion")
        high, high_rel = await _publish(store, community, user, title="High completion")

        # High-completion release: 2 plays, 2 completions (100%).
        for _ in range(2):
            await store.record_usage(
                "playback.started", lesson_id=high_rel.lesson_id, release_id=high_rel.id
            )
            await store.record_usage(
                "playback.completed", lesson_id=high_rel.lesson_id, release_id=high_rel.id
            )
        # Low-completion release: 2 plays, 0 completions (0%).
        for _ in range(2):
            await store.record_usage(
                "playback.started", lesson_id=low_rel.lesson_id, release_id=low_rel.id
            )

        ranked = await community.ranked_techniques()
        assert ranked[0].card.slug == high.slug
        assert ranked[0].completion_quality == 100
        assert ranked[0].score == 10
        assert "completion" in ranked[0].explanation

        # Deterministic: identical data → identical order across calls.
        again = await community.ranked_techniques()
        assert [r.card.slug for r in ranked] == [r.card.slug for r in again]


async def test_creator_diversity_cap_defers_prolific_creator(tmp_path: Path) -> None:
    app = _application(tmp_path / "rank-diversity.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        prolific = await _creator(store, community, email="a@example.com", name="Prolific")
        other = await _creator(store, community, email="b@example.com", name="Other")

        for i in range(3):
            await _publish(store, community, prolific, title=f"Prolific {i}")
        await _publish(store, community, other, title="Other one")

        pro = (await community.get_public_profile(
            (await community.get_profile_by_user(prolific.id)).handle
        )).handle
        oth = (await community.get_profile_by_user(other.id)).handle

        ranked = await community.ranked_techniques()
        handles = [r.card.handle for r in ranked]
        # All four present.
        assert handles.count(pro) == 3
        assert handles.count(oth) == 1
        # The other creator surfaces within the first three (not buried by volume).
        assert oth in handles[:3]
        # The prolific creator's overflow is deferred to the very end.
        assert handles[-1] == pro


async def test_empty_feed_ranks_to_empty(tmp_path: Path) -> None:
    app = _application(tmp_path / "rank-empty.db")
    async with TestClient(app):
        community = CommunityStore(app.db)
        assert await community.ranked_techniques() == []
        assert await community.ranked_techniques(query="nothing") == []
