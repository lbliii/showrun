"""Reproducible craft signals on creator profiles (#32, under #13)."""

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


def _card(problem: str, *, topics):
    return validate_card(
        problem=problem,
        pattern="Wrap the tool call in a bounded retry with jitter.",
        use_when="When a tool is idempotent but occasionally times out.",
        objective="Learn resilient tool use.",
        summary=f"Summary for {problem}.",
        topics=topics,
    )


async def _publish(store, community, user, *, title, topics):
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
        card=_card(title, topics=topics),
    )
    return technique, release


async def test_craft_signals_are_eligible_and_reproducible(tmp_path: Path) -> None:
    app = _application(tmp_path / "signals.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user = await store.create_user(
            email="creator@example.com", name="Creator", password_hash="test-only-hash"
        )
        profile = await community.ensure_profile(
            user_id=user.id,
            workspace_id=user.workspace_id,
            display_name="Creator",
            email="creator@example.com",
        )

        await _publish(store, community, user, title="Retry", topics=("reliability", "tools"))
        _t2, r2 = await _publish(
            store, community, user, title="Backoff", topics=("reliability",)
        )

        signals = await community.craft_signals(profile.handle)
        assert signals.published_techniques == 2
        assert {t.key for t in signals.topics} == {"reliability", "tools"}
        assert signals.latest_published_at is not None
        # Placeholders stay 0 — never fabricated.
        assert (signals.reproductions, signals.forks, signals.citations) == (0, 0, 0)

        # Unpublishing a release drops it from the signals immediately.
        await store.unpublish_release(r2.slug, workspace_id=user.workspace_id)
        after = await community.craft_signals(profile.handle)
        assert after.published_techniques == 1
        assert {t.key for t in after.topics} == {"reliability", "tools"}


async def test_private_profile_reports_zero_public_signals(tmp_path: Path) -> None:
    app = _application(tmp_path / "signals-private.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user = await store.create_user(
            email="p@example.com", name="Hidden", password_hash="test-only-hash"
        )
        profile = await community.ensure_profile(
            user_id=user.id,
            workspace_id=user.workspace_id,
            display_name="Hidden",
            email="p@example.com",
        )
        await _publish(store, community, user, title="Retry", topics=("reliability",))
        assert (await community.craft_signals(profile.handle)).published_techniques == 1

        await community.set_profile_visibility(user_id=user.id, visibility="private")
        hidden = await community.craft_signals(profile.handle)
        assert hidden.published_techniques == 0
        assert hidden.topics == ()


async def test_profile_page_renders_signal_strip(tmp_path: Path) -> None:
    app = _application(tmp_path / "signals-web.db")
    async with TestClient(app) as client:
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user = await store.create_user(
            email="web@example.com", name="Web Creator", password_hash="test-only-hash"
        )
        profile = await community.ensure_profile(
            user_id=user.id,
            workspace_id=user.workspace_id,
            display_name="Web Creator",
            email="web@example.com",
        )
        await _publish(store, community, user, title="Retry", topics=("reliability",))

        page = await client.get(f"/creators/{profile.handle}")
        assert page.status == 200
        assert "Craft signals" in page.text
        assert "published" in page.text
        assert "reproductions" in page.text
