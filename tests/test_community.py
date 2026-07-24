"""Behavioral proof for the Community Hub foundation.

Covers the portable schema and store records (#10) and the discovery/
authorization privacy matrix (#12): private, unlisted, disabled, and
unpublished content must never leak through direct reads, discovery, counts,
topic aggregates, profile pages, search, or version history.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from chirp.testing import TestClient

from showrun.community import (
    CommunityStore,
    TechniqueCardError,
    validate_card,
)
from showrun.store import ShowrunStore
from showrun.web import create_app


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        secret_key="test-signing-key-with-enough-entropy",
    )


def _card(problem: str = "Flaky retries", **overrides):
    values = {
        "problem": problem,
        "pattern": "Wrap the tool call in a bounded retry with jitter.",
        "use_when": "Use when a tool is idempotent but occasionally times out.",
        "objective": "Learn to make agent tool calls resilient.",
        "summary": "Bounded retry with jitter for idempotent tool calls.",
        "limitations": "Not safe for non-idempotent side effects.",
        "topics": ("reliability", "tools"),
    }
    values.update(overrides)
    return validate_card(**values)


async def _creator(store: ShowrunStore, *, email: str, name: str = "Creator"):
    return await store.create_user(email=email, name=name, password_hash="test-only-hash")


async def _published_release(store: ShowrunStore, user, *, title: str = "Retry pattern"):
    golden = await store.get_lesson("lesson_golden")
    assert golden is not None
    draft = await store.create_draft(
        replace(golden.artifact, title=title),
        workspace_id=user.workspace_id,
    )
    release = await store.publish(draft.id, "public", workspace_id=user.workspace_id)
    return draft, release


async def _publish_technique(
    store: ShowrunStore,
    community: CommunityStore,
    user,
    *,
    title: str = "Retry pattern",
    card=None,
):
    draft, release = await _published_release(store, user, title=title)
    technique, version, created = await community.publish_technique_version(
        user_id=user.id,
        workspace_id=user.workspace_id,
        display_name=user.name,
        email=user.email,
        release_slug=release.slug,
        card=card or _card(),
    )
    return draft, release, technique, version, created


# --- #10 schema + records --------------------------------------------------


async def test_card_validation_rejects_missing_fields_and_topics() -> None:
    with pytest.raises(TechniqueCardError):
        validate_card(
            problem="",
            pattern="p",
            use_when="u",
            objective="o",
            summary="s",
            topics=("x",),
        )
    with pytest.raises(TechniqueCardError):
        validate_card(
            problem="p",
            pattern="p",
            use_when="u",
            objective="o",
            summary="s",
            topics=(),
        )
    # Comma/newline separated topic strings normalize to deterministic keys.
    card = validate_card(
        problem="p",
        pattern="p",
        use_when="u",
        objective="o",
        summary="s",
        topics="Reliability, Tool Use\nReliability",
    )
    assert card.topics == ("reliability", "tool-use")


async def test_publish_creates_versioned_technique_backed_by_release(tmp_path: Path) -> None:
    app = _application(tmp_path / "publish.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user = await _creator(store, email="c1@example.com")
        _draft, release, technique, version, created = await _publish_technique(
            store, community, user
        )

        assert created is True
        assert version.version == 1
        assert version.release_id == release.id
        card = await community.get_technique_card(technique.slug)
        assert card is not None
        assert card.release_slug == release.slug
        assert card.handle
        # A profile was provisioned for the creator.
        profile = await community.get_profile_by_user(user.id)
        assert profile is not None and profile.visibility == "public"


async def test_republish_is_idempotent_but_edits_create_new_versions(tmp_path: Path) -> None:
    app = _application(tmp_path / "idempotent.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user = await _creator(store, email="c2@example.com")
        _draft, release, technique, version, created = await _publish_technique(
            store, community, user
        )
        assert created is True

        # Identical resubmission is a no-op.
        _t, again, created_again = await community.publish_technique_version(
            user_id=user.id,
            workspace_id=user.workspace_id,
            display_name=user.name,
            email=user.email,
            release_slug=release.slug,
            card=_card(),
        )
        assert created_again is False
        assert again.id == version.id

        # Editing teaching metadata creates a new immutable version.
        _t, edited, created_edit = await community.publish_technique_version(
            user_id=user.id,
            workspace_id=user.workspace_id,
            display_name=user.name,
            email=user.email,
            release_slug=release.slug,
            card=_card(objective="Learn resilient retries with backoff caps."),
        )
        assert created_edit is True
        assert edited.version == 2
        versions = await community.list_versions(technique.slug)
        assert [v.version for v in versions] == [2, 1]


async def test_technique_requires_public_active_release(tmp_path: Path) -> None:
    app = _application(tmp_path / "release-eligible.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user = await _creator(store, email="c3@example.com")
        golden = await store.get_lesson("lesson_golden")
        assert golden is not None
        draft = await store.create_draft(golden.artifact, workspace_id=user.workspace_id)
        unlisted = await store.publish(draft.id, "unlisted", workspace_id=user.workspace_id)

        # An unlisted release cannot back a public technique version (#11).
        with pytest.raises(TechniqueCardError):
            await community.publish_technique_version(
                user_id=user.id,
                workspace_id=user.workspace_id,
                display_name=user.name,
                email=user.email,
                release_slug=unlisted.slug,
                card=_card(),
            )


async def test_only_release_owner_can_publish_technique(tmp_path: Path) -> None:
    app = _application(tmp_path / "owner.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        owner = await _creator(store, email="owner@example.com")
        stranger = await _creator(store, email="stranger@example.com")
        _draft, release = await _published_release(store, owner)

        with pytest.raises(LookupError):
            await community.publish_technique_version(
                user_id=stranger.id,
                workspace_id=stranger.workspace_id,
                display_name=stranger.name,
                email=stranger.email,
                release_slug=release.slug,
                card=_card(),
            )


# --- #12 privacy / authorization matrix ------------------------------------


async def test_discovery_and_counts_exclude_unlisted_and_disabled(tmp_path: Path) -> None:
    app = _application(tmp_path / "discovery.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user = await _creator(store, email="disc@example.com")

        _d1, _r1, published, _v, _c = await _publish_technique(
            store, community, user, title="Published one"
        )
        _d2, _r2, unlisted, _v2, _c2 = await _publish_technique(
            store, community, user, title="Unlisted one", card=_card(problem="Unlisted problem")
        )
        _d3, _r3, disabled, _v3, _c3 = await _publish_technique(
            store, community, user, title="Disabled one", card=_card(problem="Disabled problem")
        )
        await community.set_technique_status(
            slug=unlisted.slug, workspace_id=user.workspace_id, status="unlisted"
        )
        await community.set_technique_status(
            slug=disabled.slug, workspace_id=user.workspace_id, status="disabled"
        )

        feed = await community.list_public_techniques()
        slugs = {c.slug for c in feed}
        assert published.slug in slugs
        assert unlisted.slug not in slugs
        assert disabled.slug not in slugs
        assert await community.public_technique_count() == 1

        # Unlisted is reachable by direct slug; disabled is not (to non-owners).
        assert await community.get_technique_card(unlisted.slug) is not None
        assert await community.get_technique_card(disabled.slug) is None
        # Search never surfaces unlisted/disabled content.
        assert await community.list_public_techniques(query="Unlisted problem") == []
        assert await community.list_public_techniques(query="Disabled problem") == []


async def test_unpublishing_release_removes_public_eligibility(tmp_path: Path) -> None:
    app = _application(tmp_path / "unpublish.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user = await _creator(store, email="unpub@example.com")
        _draft, release, technique, _v, _c = await _publish_technique(store, community, user)

        assert await community.get_technique_card(technique.slug) is not None
        assert await community.public_technique_count() == 1

        await store.unpublish_release(release.slug, workspace_id=user.workspace_id)

        # Immediately absent from every public surface; history is retained.
        assert await community.get_technique_card(technique.slug) is None
        assert await community.public_technique_count() == 0
        assert await community.list_public_techniques() == []
        # Owner can still preview their own work.
        owner_view = await community.get_technique_card(
            technique.slug, viewer_workspace_id=user.workspace_id
        )
        assert owner_view is not None


async def test_private_profile_hides_all_techniques_from_non_owners(tmp_path: Path) -> None:
    app = _application(tmp_path / "private-profile.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user = await _creator(store, email="priv@example.com")
        _draft, _release, technique, _v, _c = await _publish_technique(store, community, user)
        profile = await community.get_profile_by_user(user.id)
        assert profile is not None

        await community.set_profile_visibility(user_id=user.id, visibility="private")

        # Anonymous and non-owner readers see nothing.
        assert await community.get_technique_card(technique.slug) is None
        assert await community.get_public_profile(profile.handle) is None
        assert await community.list_techniques_by_handle(profile.handle) == []
        assert await community.public_technique_count() == 0
        assert await community.list_public_techniques() == []

        # Owner still sees their own profile and techniques.
        assert (
            await community.get_public_profile(
                profile.handle, viewer_workspace_id=user.workspace_id
            )
            is not None
        )
        owner_list = await community.list_techniques_by_handle(
            profile.handle, viewer_workspace_id=user.workspace_id
        )
        assert {c.slug for c in owner_list} == {technique.slug}


async def test_topic_aggregates_exclude_ineligible_content(tmp_path: Path) -> None:
    app = _application(tmp_path / "topics.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user = await _creator(store, email="topics@example.com")

        _d1, _r1, _pub, _v, _c = await _publish_technique(
            store, community, user, title="Public topic", card=_card(topics=("reliability",))
        )
        _d2, r2, _hidden, _v2, _c2 = await _publish_technique(
            store,
            community,
            user,
            title="Hidden topic",
            card=_card(problem="secret", topics=("security",)),
        )
        await store.unpublish_release(r2.slug, workspace_id=user.workspace_id)

        topics = await community.list_public_topics()
        keys = {topic.key: count for topic, count in topics}
        assert keys.get("reliability") == 1
        assert "security" not in keys
        assert await community.public_technique_count(topic="security") == 0
        assert await community.public_technique_count(topic="reliability") == 1
        assert await community.list_public_techniques(topic="security") == []


async def test_enumeration_returns_none_not_error(tmp_path: Path) -> None:
    app = _application(tmp_path / "enumerate.db")
    async with TestClient(app):
        community = CommunityStore(app.db)
        assert await community.get_technique_card("does-not-exist-abc123") is None
        assert await community.get_public_profile("nobody") is None
        assert await community.list_versions("does-not-exist-abc123") == []
