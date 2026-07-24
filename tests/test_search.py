"""Search, filters, and pagination for discovery (#38, under #15).

Search SQL is portable (LOWER + LIKE over normalized fields), so the behavior
asserted here on SQLite is the same on PostgreSQL.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode

from chirp.testing import TestClient

from showrun.community import CommunityStore, validate_card
from showrun.store import ShowrunStore
from showrun.web import create_app
from tests.test_community_web import _publish_public_release, _publish_technique, _signup


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        secret_key="test-signing-key-with-enough-entropy",
    )


async def _publish(store, community, user, *, title, problem):
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
        card=validate_card(
            problem=problem,
            pattern="pattern text",
            use_when="when",
            objective="obj",
            summary=f"Summary for {title}.",
            topics=("reliability",),
        ),
    )
    return technique


async def test_pagination_is_stable_and_complete(tmp_path: Path) -> None:
    app = _application(tmp_path / "pagination.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        # Two creators so the diversity cap does not defer everything.
        for i in range(2):
            u = await store.create_user(
                email=f"u{i}@example.com", name=f"User {i}", password_hash="test-only-hash"
            )
            await community.ensure_profile(
                user_id=u.id, workspace_id=u.workspace_id, display_name=f"User {i}", email=u.email
            )
            for j in range(2):
                await _publish(store, community, u, title=f"T{i}{j}", problem=f"Problem {i}{j}")

        page1 = await community.discover_page(page=1, page_size=2)
        page2 = await community.discover_page(page=2, page_size=2)
        assert len(page1.items) == 2 and page1.has_next and not page1.has_prev
        assert page2.has_prev
        s1 = {r.card.slug for r in page1.items}
        s2 = {r.card.slug for r in page2.items}
        # Pages are disjoint and cover distinct results.
        assert not (s1 & s2)
        # Deterministic across calls.
        again = await community.discover_page(page=1, page_size=2)
        assert [r.card.slug for r in page1.items] == [r.card.slug for r in again.items]


async def test_search_is_case_insensitive_and_scoped(tmp_path: Path) -> None:
    app = _application(tmp_path / "search.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user = await store.create_user(
            email="c@example.com", name="Creator", password_hash="test-only-hash"
        )
        await community.ensure_profile(
            user_id=user.id,
            workspace_id=user.workspace_id,
            display_name="Creator",
            email=user.email,
        )
        await _publish(store, community, user, title="Retry", problem="Flaky tool retries")

        # Case-insensitive match against the normalized problem field.
        hit = await community.discover_page(query="FLAKY")
        assert len(hit.items) == 1
        assert "Flaky" in hit.items[0].card.problem
        miss = await community.discover_page(query="nonexistent-term")
        assert miss.items == []


async def test_search_empty_state_over_http(tmp_path: Path) -> None:
    app = _application(tmp_path / "search-web.db")
    async with TestClient(app) as client:
        cookie = await _signup(client, email="creator@example.com", name="Ada Creator")
        lesson_path, cookie = await _publish_public_release(client, cookie, title="Retry pattern")
        await _publish_technique(client, cookie, lesson_path)

        found = await client.get("/discover?" + urlencode({"q": "retry"}))
        assert found.status == 200
        miss = await client.get("/discover?" + urlencode({"q": "zzz-nothing"}))
        assert miss.status == 200
        assert "No techniques match" in miss.text
