"""End-to-end behavioral proof for the persistent Showrun vertical slice."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlencode

from chirp.testing import TestClient

from showrun.web import create_app

_CSRF_RE = re.compile(r'name="_csrf_token" value="([^"]+)"')
_SESSION = """\
{"type":"session","id":"import-test","name":"Imported test session"}
{"type":"message","at":0,"message":{"role":"user","content":"Can this become a show?"}}
{"type":"message","at":8,"message":{"role":"assistant","content":"Yes. Normalize it first."}}
{"type":"event","at":12,"event":{"kind":"tool","name":"pytest","content":"Tests passed."}}
"""


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        admin_token="test-director-token",
        secret_key="test-signing-key-with-enough-entropy",
    )


def _cookie(response) -> str:
    value = response.header("set-cookie", "")
    assert value.startswith("chirp_session=")
    return value.split(";", 1)[0]


def _csrf(html: str) -> str:
    match = _CSRF_RE.search(html)
    assert match is not None
    return match.group(1)


async def _login(client: TestClient) -> str:
    page = await client.get("/login")
    cookie = _cookie(page)
    response = await client.post(
        "/login",
        body=urlencode(
            {
                "token": "test-director-token",
                "_csrf_token": _csrf(page.text),
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
    )
    assert response.status == 303
    return response.header("set-cookie", "").split(";", 1)[0] or cookie


async def test_public_library_and_readiness(tmp_path: Path) -> None:
    app = _application(tmp_path / "public.db")
    async with TestClient(app) as client:
        library = await client.get("/")
        ready = await client.get("/ready")
        css = await client.get("/static/library.css")

    assert library.status == ready.status == css.status == 200
    assert "Turn agent runs into shows" in library.text
    assert "Could agent sessions become documentation?" in library.text
    assert '<main class="library-shell" hx-boost="false">' in library.text
    csp_headers = [
        value for name, value in library.headers if name.lower() == "content-security-policy"
    ]
    assert len(csp_headers) == 1
    assert "'nonce-" in csp_headers[0]
    assert "'unsafe-eval'" in csp_headers[0]
    assert "style-src 'self' 'unsafe-inline'" in csp_headers[0]


async def test_director_can_import_preview_publish_and_embed(tmp_path: Path) -> None:
    app = _application(tmp_path / "flow.db")
    async with TestClient(app) as client:
        cookie = await _login(client)
        import_page = await client.get("/imports/new", headers={"Cookie": cookie})
        imported = await client.post(
            "/imports",
            body=urlencode(
                {
                    "title": "A published Showrun",
                    "transcript": _SESSION,
                    "_csrf_token": _csrf(import_page.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert imported.status == 303
        lesson_path = imported.header("location")
        lesson = await client.get(lesson_path, headers={"Cookie": cookie})
        published = await client.post(
            f"{lesson_path}/publish",
            body=urlencode(
                {
                    "visibility": "public",
                    "_csrf_token": _csrf(lesson.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert published.status == 303
        watch_path = published.header("location")
        slug = watch_path.rsplit("/", 1)[-1]
        watch = await client.get(watch_path)
        embed = await client.get(f"/embed/{slug}")
        manifest = await client.get(f"/releases/{slug}/dvd.json")
        oembed = await client.get(f"/oembed?url=http://testserver/watch/{slug}")

    assert "A published Showrun" in lesson.text
    assert "System instructions" not in lesson.text
    assert "Publish this revision" in lesson.text
    assert watch.status == embed.status == manifest.status == oembed.status == 200
    assert "showrunPlayer" in watch.text
    assert "embed-mode" in embed.text
    assert 'hx-boost="false"' in watch.text
    assert manifest.header("cache-control") == "public, max-age=31536000, immutable"
    assert json.loads(manifest.text)["format"] == "dvd/1"
    assert f"/embed/{slug}" in json.loads(oembed.text)["html"]


async def test_draft_persists_across_restart(tmp_path: Path) -> None:
    database = tmp_path / "persistent.db"
    first_app = _application(database)
    async with TestClient(first_app) as client:
        cookie = await _login(client)
        import_page = await client.get("/imports/new", headers={"Cookie": cookie})
        response = await client.post(
            "/imports",
            body=urlencode(
                {
                    "title": "Persistent lesson",
                    "transcript": _SESSION,
                    "_csrf_token": _csrf(import_page.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert response.status == 303

    second_app = _application(database)
    async with TestClient(second_app) as client:
        cookie = await _login(client)
        library = await client.get("/", headers={"Cookie": cookie})

    assert "Persistent lesson" in library.text


async def test_private_routes_redirect_to_login(tmp_path: Path) -> None:
    app = _application(tmp_path / "private.db")
    async with TestClient(app) as client:
        import_page = await client.get("/imports/new")
        lesson = await client.get("/lessons/lesson_golden")

    assert import_page.status == lesson.status == 303
    assert import_page.header("location") == lesson.header("location") == "/login"


def test_app_passes_chirp_contract_check(tmp_path: Path) -> None:
    app = _application(tmp_path / "contracts.db")
    app.check()
