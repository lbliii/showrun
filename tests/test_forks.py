"""Fork a public technique into a private attributed draft (#18, epic #6)."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode

from chirp.testing import TestClient

from showrun.store import ShowrunStore
from showrun.web import create_app
from tests.test_community_web import (
    _csrf,
    _publish_public_release,
    _publish_technique,
    _signup,
    _updated_cookie,
)


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        secret_key="test-signing-key-with-enough-entropy",
    )


async def _fork(client: TestClient, cookie: str, technique_slug: str) -> tuple[str, str]:
    page = await client.get(f"/techniques/{technique_slug}", headers={"Cookie": cookie})
    cookie = _updated_cookie(page, cookie)
    resp = await client.post(
        f"/techniques/{technique_slug}/fork",
        body=urlencode({"_csrf_token": _csrf(page.text)}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
    )
    assert resp.status == 303
    return resp.header("location"), cookie


async def test_fork_creates_private_attributed_draft_and_ancestry(tmp_path: Path) -> None:
    app = _application(tmp_path / "forks.db")
    async with TestClient(app) as client:
        # Creator A publishes a technique.
        cookie_a = await _signup(client, email="a@example.com", name="Author A")
        lesson_a, cookie_a = await _publish_public_release(client, cookie_a, title="Retry pattern")
        tech_a_path, cookie_a = await _publish_technique(client, cookie_a, lesson_a)
        slug_a = tech_a_path.rsplit("/", 1)[-1]
        page_a = await client.get(tech_a_path)
        handle_a = re.search(r"/creators/([a-z0-9-]+)", page_a.text).group(1)

        # Creator B forks it.
        cookie_b = await _signup(client, email="b@example.com", name="Author B")
        editor_path, cookie_b = await _fork(client, cookie_b, slug_a)
        assert editor_path.endswith("/edit")
        child_lesson_id = editor_path.removesuffix("/edit").rsplit("/", 1)[-1]

        editor = await client.get(editor_path, headers={"Cookie": cookie_b})
        cookie_b = _updated_cookie(editor, cookie_b)
        assert "Forked technique" in editor.text
        assert f"/creators/{handle_a}" in editor.text

        # The fork is a private, unpublished draft in B's workspace.
        store = ShowrunStore(app.db)
        user_b = await store.get_user_by_email("b@example.com")
        child = await store.get_lesson(child_lesson_id, workspace_id=user_b.workspace_id)
        assert child is not None
        assert (child.status, child.visibility) == ("draft", "private")

        # Forking again is idempotent — same draft, not a duplicate.
        again_path, cookie_b = await _fork(client, cookie_b, slug_a)
        assert again_path == editor_path

        # B publishes the fork; the descendant renders the ancestry chain.
        child_path = editor_path.removesuffix("/edit")
        lesson_show = await client.get(child_path, headers={"Cookie": cookie_b})
        cookie_b = _updated_cookie(lesson_show, cookie_b)
        published = await client.post(
            f"{child_path}/publish",
            body=urlencode(
                {"visibility": "public", "_csrf_token": _csrf(lesson_show.text)}
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie_b},
        )
        assert published.status == 303
        descendant_path, cookie_b = await _publish_technique(client, cookie_b, child_path)

        descendant = await client.get(descendant_path)
        assert descendant.status == 200
        assert "Forked from" in descendant.text
        assert f"/techniques/{slug_a}" in descendant.text
        assert f"/creators/{handle_a}" in descendant.text


async def test_fork_requires_login_and_public_technique(tmp_path: Path) -> None:
    app = _application(tmp_path / "forks-auth.db")
    async with TestClient(app) as client:
        cookie = await _signup(client, email="a@example.com", name="Author A")
        page = await client.get("/imports/new", headers={"Cookie": cookie})
        cookie = _updated_cookie(page, cookie)
        # A technique that does not exist cannot be forked.
        missing = await client.post(
            "/techniques/does-not-exist/fork",
            body=urlencode({"_csrf_token": _csrf(page.text)}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert missing.status == 404
