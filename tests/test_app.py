"""End-to-end behavioral proof for the persistent Showrun vertical slice."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlencode

from chirp.testing import TestClient

from showrun.artifacts import create_artifact_from_text
from showrun.auth import password_hash
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


async def _signup(
    client: TestClient,
    *,
    email: str = "director@example.com",
    name: str = "Test Director",
) -> str:
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


async def _login(client: TestClient, *, email: str = "director@example.com") -> str:
    page = await client.get("/login")
    cookie = _cookie(page)
    response = await client.post(
        "/login",
        body=urlencode(
            {
                "email": email,
                "password": "correct horse battery staple",
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
    assert '<main id="main">' in library.text
    assert '<div class="library-shell">' in library.text
    assert "chirpui" not in library.text.lower()
    assert 'data-chirp="htmx"' not in library.text
    csp_headers = [
        value for name, value in library.headers if name.lower() == "content-security-policy"
    ]
    assert len(csp_headers) == 1
    assert "'nonce-" in csp_headers[0]
    assert "'unsafe-eval'" in csp_headers[0]
    assert "style-src 'self' 'unsafe-inline'" in csp_headers[0]


async def test_director_can_import_preview_publish_and_embed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SHOWRUN_PUBLIC_URL", "https://showrun.example")
    app = _application(tmp_path / "flow.db")
    async with TestClient(app) as client:
        cookie = await _signup(client)
        import_page = await client.get("/imports/new", headers={"Cookie": cookie})
        cookie = _updated_cookie(import_page, cookie)
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
        editor_path = imported.header("location")
        assert editor_path.endswith("/edit")
        editor = await client.get(editor_path, headers={"Cookie": cookie})
        cookie = _updated_cookie(editor, cookie)
        assert "System instructions" not in editor.text
        assert "Sanitization review + first cut" in editor.text
        lesson_path = editor_path.removesuffix("/edit")
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
        started = await client.post(
            "/api/v1/events",
            body=json.dumps(
                {
                    "event": "playback.started",
                    "releaseSlug": slug,
                    "origin": "https://docs.example",
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        completed = await client.post(
            "/api/v1/events",
            body=json.dumps({"event": "playback.completed", "releaseSlug": slug}).encode(),
            headers={"Content-Type": "application/json"},
        )
        chapter = await client.post(
            "/api/v1/events",
            body=json.dumps(
                {"event": "chapter.viewed", "releaseSlug": slug, "chapter": 1}
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        dashboard = await client.get("/", headers={"Cookie": cookie})
        analytics = await client.get(
            f"{lesson_path}/analytics",
            headers={"Cookie": cookie},
        )

    assert "A published Showrun" in lesson.text
    assert "Publish this revision" in lesson.text
    assert watch.status == embed.status == manifest.status == oembed.status == 200
    assert started.status == completed.status == chapter.status == 204
    assert "showrunPlayer" in watch.text
    assert "Show tool output" in watch.text
    assert "Copy embed" in watch.text
    assert "HTML iframe" in watch.text
    assert "Web component" in watch.text
    assert "/static/embed.js" in watch.text
    assert "navigator.clipboard.writeText($el.dataset.embedCode)" in watch.text
    assert 'data-embed-code="&lt;iframe' in watch.text
    assert f"/embed/{slug}" in watch.text
    assert f"https://showrun.example/embed/{slug}" in watch.text
    assert "navigator.clipboard.writeText(&#34;" not in watch.text
    assert "embed-mode" in embed.text
    assert 'data-chirp="alpine"' in watch.text
    assert "chirpui" not in watch.text.lower()
    assert manifest.header("cache-control") == "public, max-age=31536000, immutable"
    assert json.loads(manifest.text)["format"] == "dvd/1"
    assert f"/embed/{slug}" in json.loads(oembed.text)["html"]
    assert "<strong>1</strong><span>imports</span>" in dashboard.text
    assert "<strong>1</strong><span>publishes</span>" in dashboard.text
    assert "<strong>1</strong><span>watch views</span>" in dashboard.text
    assert "<strong>1</strong><span>embed loads</span>" in dashboard.text
    assert "<strong>1</strong><span>plays</span>" in dashboard.text
    assert "<strong>100%</strong><span>completion</span>" in dashboard.text
    assert "Chapter funnel" in analytics.text
    assert "https://docs.example" in analytics.text
    assert "1 · 100%" in analytics.text
    assert f"{slug}</small>" in analytics.text


async def test_embed_supports_valid_themes_and_rejects_unknown_theme(tmp_path: Path) -> None:
    app = _application(tmp_path / "themes.db")
    async with TestClient(app) as client:
        library = await client.get("/")
        match = re.search(r'href="/watch/([^"]+)"', library.text)
        assert match
        slug = match.group(1)
        dark = await client.get(f"/embed/{slug}?theme=dark&chapter=2")
        unknown = await client.get(f"/embed/{slug}?theme=sepia&start=49.5")
        hydrator = await client.get("/static/embed.js")

    assert "embed-mode theme-dark" in dark.text
    assert '"initialTime": 24.0' in dark.text
    assert "embed-mode theme-auto" in unknown.text
    assert '"initialTime": 49.5' in unknown.text
    assert 'return ["src", "title", "theme", "chapter", "start"]' in hydrator.text
    assert "strict-origin-when-cross-origin" in hydrator.text
    assert 'class="skip-link"' in dark.text


async def test_draft_persists_across_restart(tmp_path: Path) -> None:
    database = tmp_path / "persistent.db"
    first_app = _application(database)
    async with TestClient(first_app) as client:
        cookie = await _signup(client)
        import_page = await client.get("/imports/new", headers={"Cookie": cookie})
        cookie = _updated_cookie(import_page, cookie)
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


async def test_workspaces_are_isolated_and_tokens_are_revocable(tmp_path: Path) -> None:
    app = _application(tmp_path / "isolation.db")
    async with TestClient(app) as client:
        first_cookie = await _signup(client)
        import_page = await client.get("/imports/new", headers={"Cookie": first_cookie})
        first_cookie = _updated_cookie(import_page, first_cookie)
        imported = await client.post(
            "/imports",
            body=urlencode(
                {
                    "title": "Private to workspace one",
                    "transcript": _SESSION,
                    "_csrf_token": _csrf(import_page.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": first_cookie},
        )
        lesson_path = imported.header("location")

        token_page = await client.get("/settings/tokens", headers={"Cookie": first_cookie})
        first_cookie = _updated_cookie(token_page, first_cookie)
        created = await client.post(
            "/settings/tokens",
            body=urlencode(
                {
                    "name": "Test laptop",
                    "_csrf_token": _csrf(token_page.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": first_cookie},
        )
        token_match = re.search(r"<code>(sr_live_[^<]+)</code>", created.text)
        assert token_match is not None
        plaintext_token = token_match.group(1)
        assert plaintext_token not in created.text.replace(token_match.group(0), "")
        token_id_match = re.search(r"/settings/tokens/(token_[^/]+)/revoke", created.text)
        assert token_id_match is not None

        api_session = _SESSION.replace("import-test", "api-test").replace(
            "Imported test session",
            "API imported session",
        )
        api_import = await client.post(
            "/api/v1/imports",
            body=json.dumps(
                {
                    "filename": "api-session.jsonl",
                    "title": "Pushed from sr",
                    "transcript": api_session,
                }
            ).encode(),
            headers={
                "Authorization": f"Bearer {plaintext_token}",
                "Content-Type": "application/json",
            },
        )
        api_duplicate = await client.post(
            "/api/v1/imports",
            body=json.dumps(
                {
                    "filename": "api-session.jsonl",
                    "title": "Pushed again",
                    "transcript": api_session,
                }
            ).encode(),
            headers={
                "Authorization": f"Bearer {plaintext_token}",
                "Content-Type": "application/json",
            },
        )
        assert api_import.status == 201
        assert api_duplicate.status == 200
        assert json.loads(api_duplicate.text)["duplicate"] is True
        portable = create_artifact_from_text(
            api_session.replace("api-test", "portable-test"),
            title="Portable source",
        )
        portable_import = await client.post(
            "/api/v1/imports",
            body=json.dumps(
                {
                    "filename": "portable.dvd.json",
                    "title": "Portable upload",
                    "artifact": portable.to_manifest(),
                }
            ).encode(),
            headers={
                "Authorization": f"Bearer {plaintext_token}",
                "Content-Type": "application/json",
            },
        )
        assert portable_import.status == 201
        api_lessons = await client.get(
            "/api/v1/lessons",
            headers={"Authorization": f"Bearer {plaintext_token}"},
        )
        assert api_lessons.status == 200
        lesson_titles = {lesson["title"] for lesson in json.loads(api_lessons.text)["lessons"]}
        assert {"Private to workspace one", "Pushed from sr", "Portable upload"} <= lesson_titles

        revoked = await client.post(
            f"/settings/tokens/{token_id_match.group(1)}/revoke",
            body=urlencode({"_csrf_token": _csrf(created.text)}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": first_cookie},
        )
        assert revoked.status == 303
        rejected = await client.post(
            "/api/v1/imports",
            body=json.dumps({"transcript": api_session}).encode(),
            headers={
                "Authorization": f"Bearer {plaintext_token}",
                "Content-Type": "application/json",
            },
        )
        assert rejected.status == 401

        logout_page = await client.get("/", headers={"Cookie": first_cookie})
        logged_out = await client.post(
            "/logout",
            body=urlencode({"_csrf_token": _csrf(logout_page.text)}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": first_cookie},
        )
        anonymous_cookie = logged_out.header("set-cookie", "").split(";", 1)[0]
        second_cookie = await _signup(
            client,
            email="other@example.com",
            name="Other Director",
        )
        denied = await client.get(lesson_path, headers={"Cookie": second_cookie})
        second_library = await client.get("/", headers={"Cookie": second_cookie})

    assert anonymous_cookie
    assert denied.status == 404
    assert "Private to workspace one" not in second_library.text
    assert plaintext_token.startswith("sr_live_")


async def test_director_saves_a_new_revision_and_preserves_release(tmp_path: Path) -> None:
    app = _application(tmp_path / "director.db")
    async with TestClient(app) as client:
        cookie = await _signup(client)
        import_page = await client.get("/imports/new", headers={"Cookie": cookie})
        cookie = _updated_cookie(import_page, cookie)
        imported = await client.post(
            "/imports",
            body=urlencode(
                {
                    "title": "First cut",
                    "transcript": _SESSION,
                    "_csrf_token": _csrf(import_page.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        editor_path = imported.header("location")
        editor = await client.get(editor_path, headers={"Cookie": cookie})
        cookie = _updated_cookie(editor, cookie)
        saved = await client.post(
            editor_path,
            body=urlencode(
                {
                    "title": "Directed cut",
                    "description": "A deliberately edited lesson.",
                    "event_1_include": "on",
                    "event_1_duration": "4.5",
                    "event_2_include": "on",
                    "event_2_duration": "5.5",
                    "event_3_duration": "2.5",
                    "chapter_0_include": "on",
                    "chapter_0_order": "1",
                    "chapter_0_name": "The useful opening",
                    "chapter_0_at": "0",
                    "chapter_0_caption": "Start with the learner's question",
                    "chapter_0_note": "The omitted tool event was not instructional.",
                    "chapter_0_teaching_point": "Editing is subtraction.",
                    "_csrf_token": _csrf(editor.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert saved.status == 303
        directed = await client.get(saved.header("location"), headers={"Cookie": cookie})
        preview = await client.get(editor_path.removesuffix("/edit"), headers={"Cookie": cookie})

    assert "r2" in directed.text
    assert "Directed cut" in directed.text
    assert "Revision saved" in directed.text
    assert "Directed cut" in preview.text
    assert 'Event <span x-text="activeEvent.id"></span> of 2' in preview.text


async def test_library_can_filter_duplicate_delete_and_unpublish(tmp_path: Path) -> None:
    app = _application(tmp_path / "library-management.db")
    async with TestClient(app) as client:
        cookie = await _signup(client)
        import_page = await client.get("/imports/new", headers={"Cookie": cookie})
        cookie = _updated_cookie(import_page, cookie)
        imported = await client.post(
            "/imports",
            body=urlencode(
                {
                    "title": "Manage this lesson",
                    "transcript": _SESSION,
                    "_csrf_token": _csrf(import_page.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        editor_path = imported.header("location")
        lesson_path = editor_path.removesuffix("/edit")
        library = await client.get("/?q=manage&status=draft", headers={"Cookie": cookie})
        duplicated = await client.post(
            f"{lesson_path}/duplicate",
            body=urlencode({"_csrf_token": _csrf(library.text)}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        duplicate_editor_path = duplicated.header("location")
        duplicate_lesson_path = duplicate_editor_path.removesuffix("/edit")
        duplicate_editor = await client.get(duplicate_editor_path, headers={"Cookie": cookie})
        deleted = await client.post(
            f"{duplicate_lesson_path}/delete",
            body=urlencode({"_csrf_token": _csrf(duplicate_editor.text)}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )

        preview = await client.get(lesson_path, headers={"Cookie": cookie})
        published = await client.post(
            f"{lesson_path}/publish",
            body=urlencode({"visibility": "unlisted", "_csrf_token": _csrf(preview.text)}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        watch_path = published.header("location")
        slug = watch_path.rsplit("/", 1)[-1]
        editor = await client.get(editor_path, headers={"Cookie": cookie})
        unpublished = await client.post(
            f"/releases/{slug}/unpublish",
            body=urlencode({"_csrf_token": _csrf(editor.text)}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        missing_watch = await client.get(watch_path)
        release_history = await client.get(
            unpublished.header("location"),
            headers={"Cookie": cookie},
        )
        preview_again = await client.get(lesson_path, headers={"Cookie": cookie})
        republished = await client.post(
            f"{lesson_path}/publish",
            body=urlencode(
                {"visibility": "unlisted", "_csrf_token": _csrf(preview_again.text)}
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        restored_watch = await client.get(republished.header("location"))

    assert "Manage this lesson" in library.text
    assert duplicated.status == deleted.status == 303
    assert missing_watch.status == 404
    assert "unpublished" in release_history.text
    assert republished.header("location") == watch_path
    assert restored_watch.status == 200


def test_app_passes_chirp_contract_check(tmp_path: Path) -> None:
    app = _application(tmp_path / "contracts.db")
    app.check()


def test_passwords_use_argon2id() -> None:
    assert password_hash("correct horse battery staple").startswith("$argon2id$")
