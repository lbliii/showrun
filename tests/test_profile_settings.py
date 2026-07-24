"""Profile settings: edit display name, bio, and visibility (#30, under #13)."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode

import pytest
from chirp.testing import TestClient

from showrun.community import (
    CommunityStore,
    ProfileError,
    validate_bio,
    validate_display_name,
    validate_visibility,
)
from showrun.store import ShowrunStore
from showrun.web import create_app

_CSRF_RE = re.compile(r'name="_csrf_token" value="([^"]+)"')


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        secret_key="test-signing-key-with-enough-entropy",
    )


def _cookie(response) -> str:
    return response.header("set-cookie", "").split(";", 1)[0]


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


def test_profile_validators() -> None:
    assert validate_display_name("  Ada  Lovelace ") == "Ada Lovelace"
    assert validate_bio("  hi  there ") == "hi there"
    assert validate_visibility("private") == "private"
    with pytest.raises(ProfileError):
        validate_display_name("   ")
    with pytest.raises(ProfileError):
        validate_bio("x" * 501)
    with pytest.raises(ProfileError):
        validate_visibility("secret")


async def test_settings_page_provisions_and_edits_profile(tmp_path: Path) -> None:
    app = _application(tmp_path / "profile-settings.db")
    async with TestClient(app) as client:
        cookie = await _signup(client, email="ada@example.com", name="Ada")
        page = await client.get("/settings/profile", headers={"Cookie": cookie})
        assert page.status == 200
        assert "Profile settings" in page.text
        cookie = _updated_cookie(page, cookie)

        handle = re.search(r'name="handle"[^>]*value="([^"]+)"', page.text).group(1)
        updated = await client.post(
            "/settings/profile",
            body=urlencode(
                {
                    "handle": handle,
                    "display_name": "Ada Lovelace",
                    "bio": "I demonstrate resilient agent tool use.",
                    "visibility": "public",
                    "_csrf_token": _csrf(page.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert updated.status == 303

        saved = await client.get("/settings/profile?saved=1", headers={"Cookie": cookie})
        assert "Profile saved." in saved.text
        assert "Ada Lovelace" in saved.text

        store = ShowrunStore(app.db)
        user = await store.get_user_by_email("ada@example.com")
        assert user is not None
        community = CommunityStore(app.db)
        profile = await community.get_profile_by_user(user.id)
        assert profile is not None
        assert profile.display_name == "Ada Lovelace"
        assert profile.bio == "I demonstrate resilient agent tool use."

        # The public profile reflects the edit for anonymous viewers.
        public = await client.get(f"/creators/{profile.handle}")
        assert public.status == 200
        assert "Ada Lovelace" in public.text


async def test_settings_rejects_invalid_and_toggles_private(tmp_path: Path) -> None:
    app = _application(tmp_path / "profile-invalid.db")
    async with TestClient(app) as client:
        cookie = await _signup(client, email="grace@example.com", name="Grace")
        page = await client.get("/settings/profile", headers={"Cookie": cookie})
        cookie = _updated_cookie(page, cookie)

        rejected = await client.post(
            "/settings/profile",
            body=urlencode(
                {
                    "display_name": "   ",
                    "bio": "",
                    "visibility": "public",
                    "_csrf_token": _csrf(page.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert rejected.status == 200
        assert "Enter a display name." in rejected.text

        # Toggling private hides the profile from anonymous visitors.
        store = ShowrunStore(app.db)
        user = await store.get_user_by_email("grace@example.com")
        assert user is not None
        community = CommunityStore(app.db)
        profile = await community.get_profile_by_user(user.id)
        assert profile is not None

        made_private = await client.post(
            "/settings/profile",
            body=urlencode(
                {
                    "handle": profile.handle,
                    "display_name": "Grace Hopper",
                    "bio": "Compilers and agents.",
                    "visibility": "private",
                    "_csrf_token": _csrf(page.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert made_private.status == 303
        anon = await client.get(f"/creators/{profile.handle}")
        assert anon.status == 404


async def test_settings_requires_login(tmp_path: Path) -> None:
    app = _application(tmp_path / "profile-auth.db")
    async with TestClient(app) as client:
        page = await client.get("/settings/profile")
        assert page.status in (302, 303)
        assert page.header("location") == "/login"
