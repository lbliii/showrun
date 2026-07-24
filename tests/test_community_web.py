"""End-to-end HTTP proof for publishing and discovering techniques.

Drives the real routes and templates so the technique-card form, publish
transaction, discovery feed, technique page, creator profile, and topic page
work through the web layer — and so unlisted/unpublished content stays absent
from public HTTP surfaces (#11, #12).
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode

from chirp.testing import TestClient

from showrun.web import create_app
from tests.session_fixtures import RICH_SESSION as _SESSION

_CSRF_RE = re.compile(r'name="_csrf_token" value="([^"]+)"')


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        secret_key="test-signing-key-with-enough-entropy",
    )


def _cookie(response) -> str:
    value = response.header("set-cookie", "")
    assert value.startswith("chirp_session=")
    return value.split(";", 1)[0]


def _updated_cookie(response, current: str) -> str:
    value = response.header("set-cookie", "")
    return value.split(";", 1)[0] if value else current


def _csrf(html: str) -> str:
    match = _CSRF_RE.search(html)
    assert match is not None
    return match.group(1)


async def _signup(client: TestClient, *, email: str, name: str) -> str:
    page = await client.get("/signup")
    cookie = _cookie(page)
    response = await client.post(
        "/signup",
        body=urlencode(
            {
                "name": name,
                "email": email,
                "password": "correct horse battery staple",
                "_csrf_token": _csrf(page.text),
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
    )
    assert response.status == 303
    return response.header("set-cookie", "").split(";", 1)[0] or cookie


async def _publish_public_release(
    client: TestClient, cookie: str, *, title: str
) -> tuple[str, str]:
    """Import a session and publish a public release. Returns (lesson_path, cookie)."""

    import_page = await client.get("/imports/new", headers={"Cookie": cookie})
    cookie = _updated_cookie(import_page, cookie)
    imported = await client.post(
        "/imports",
        body=urlencode(
            {"title": title, "transcript": _SESSION, "_csrf_token": _csrf(import_page.text)}
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
    )
    assert imported.status == 303
    lesson_path = imported.header("location").removesuffix("/edit")
    lesson = await client.get(lesson_path, headers={"Cookie": cookie})
    cookie = _updated_cookie(lesson, cookie)
    published = await client.post(
        f"{lesson_path}/publish",
        body=urlencode({"visibility": "public", "_csrf_token": _csrf(lesson.text)}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
    )
    assert published.status == 303
    return lesson_path, cookie


async def _publish_technique(
    client: TestClient,
    cookie: str,
    lesson_path: str,
    *,
    summary: str = "Bounded retry with jitter for idempotent tool calls.",
    topics: str = "reliability, tools",
) -> tuple[str, str]:
    form_page = await client.get(f"{lesson_path}/technique", headers={"Cookie": cookie})
    cookie = _updated_cookie(form_page, cookie)
    assert form_page.status == 200
    assert "Technique card" in form_page.text
    published = await client.post(
        "/techniques",
        body=urlencode(
            {
                "release_slug": _release_slug(form_page.text),
                "problem": "Flaky tool retries lose work.",
                "pattern": "Wrap idempotent tool calls in a bounded retry with jitter.",
                "use_when": "When a tool is idempotent but occasionally times out.",
                "objective": "Learn to make agent tool calls resilient.",
                "summary": summary,
                "limitations": "Not safe for non-idempotent side effects.",
                "topics": topics,
                "_csrf_token": _csrf(form_page.text),
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
    )
    assert published.status == 303
    return published.header("location"), cookie


def _release_slug(html: str) -> str:
    match = re.search(r'name="release_slug" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


async def test_publish_and_discover_technique_end_to_end(tmp_path: Path) -> None:
    app = _application(tmp_path / "web-flow.db")
    async with TestClient(app) as client:
        cookie = await _signup(client, email="creator@example.com", name="Ada Creator")
        lesson_path, cookie = await _publish_public_release(client, cookie, title="Retry pattern")
        technique_path, cookie = await _publish_technique(client, cookie, lesson_path)

        # Technique page renders the card and links to the backing run.
        page = await client.get(technique_path)
        assert page.status == 200
        assert "Bounded retry with jitter" in page.text
        assert "/watch/" in page.text

        # Discovery feed and topic page surface it to anonymous readers.
        discover = await client.get("/discover")
        assert discover.status == 200
        assert technique_path in discover.text
        topic = await client.get("/topics/reliability")
        assert topic.status == 200
        assert technique_path in topic.text

        # Creator profile is public and lists the technique.
        handle_match = re.search(r"/creators/([a-z0-9-]+)", discover.text)
        assert handle_match is not None
        profile = await client.get(f"/creators/{handle_match.group(1)}")
        assert profile.status == 200
        assert technique_path in profile.text

        # Republishing the identical card is idempotent (no second version).
        again_path, cookie = await _publish_technique(client, cookie, lesson_path)
        assert again_path == technique_path


async def test_unpublished_technique_absent_from_public_http_surfaces(tmp_path: Path) -> None:
    app = _application(tmp_path / "web-privacy.db")
    async with TestClient(app) as client:
        cookie = await _signup(client, email="owner@example.com", name="Owner Person")
        lesson_path, cookie = await _publish_public_release(client, cookie, title="Secret pattern")
        technique_path, cookie = await _publish_technique(
            client, cookie, lesson_path, summary="Soon to be unpublished.", topics="security"
        )
        slug = technique_path.rsplit("/", 1)[-1]

        assert (await client.get("/discover")).text.count(technique_path) >= 1

        # Unpublish the backing release.
        editor = await client.get(f"{lesson_path}/edit", headers={"Cookie": cookie})
        cookie = _updated_cookie(editor, cookie)
        release_slug = re.search(r"/releases/([^/]+)/unpublish", editor.text).group(1)
        unpub = await client.post(
            f"/releases/{release_slug}/unpublish",
            body=urlencode({"_csrf_token": _csrf(editor.text)}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert unpub.status == 303

        # Anonymous public surfaces no longer expose it.
        assert technique_path not in (await client.get("/discover")).text
        assert (await client.get(technique_path)).status == 404
        assert technique_path not in (await client.get("/topics/security")).text

        # The owner can still reach their own technique for editing.
        owner_view = await client.get(technique_path, headers={"Cookie": cookie})
        assert owner_view.status == 200
        assert "Soon to be unpublished." in owner_view.text
        assert slug


async def test_stranger_cannot_publish_technique_from_others_release(tmp_path: Path) -> None:
    app = _application(tmp_path / "web-owner.db")
    async with TestClient(app) as client:
        owner_cookie = await _signup(client, email="a@example.com", name="Alpha")
        lesson_path, owner_cookie = await _publish_public_release(
            client, owner_cookie, title="Owned pattern"
        )
        form_page = await client.get(f"{lesson_path}/technique", headers={"Cookie": owner_cookie})
        release_slug = _release_slug(form_page.text)

        stranger_cookie = await _signup(client, email="b@example.com", name="Beta")
        # Stranger needs their own CSRF token from a page they can load.
        discover = await client.get("/discover", headers={"Cookie": stranger_cookie})
        stranger_cookie = _updated_cookie(discover, stranger_cookie)
        attempt = await client.post(
            "/techniques",
            body=urlencode(
                {
                    "release_slug": release_slug,
                    "problem": "hijack",
                    "pattern": "hijack",
                    "use_when": "hijack",
                    "objective": "hijack",
                    "summary": "hijack",
                    "topics": "misc",
                    "_csrf_token": await _any_csrf(client, stranger_cookie),
                }
            ).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": stranger_cookie,
            },
        )
        assert attempt.status == 404


async def _any_csrf(client: TestClient, cookie: str) -> str:
    page = await client.get("/imports/new", headers={"Cookie": cookie})
    return _csrf(page.text)
