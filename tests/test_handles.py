"""Handle claim/edit with reserved names and redirects (#31, under #13)."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode

import pytest
from chirp.testing import TestClient

from showrun.community import (
    CommunityStore,
    ProfileError,
    validate_handle,
)
from showrun.store import ShowrunStore
from showrun.web import create_app

_CSRF_RE = re.compile(r'name="_csrf_token" value="([^"]+)"')


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        secret_key="test-signing-key-with-enough-entropy",
    )


def _csrf(html: str) -> str:
    match = _CSRF_RE.search(html)
    assert match is not None
    return match.group(1)


def _updated_cookie(response, current: str) -> str:
    value = response.header("set-cookie", "")
    return value.split(";", 1)[0] if value else current


async def _signup(client: TestClient, *, email: str, name: str) -> str:
    page = await client.get("/signup")
    cookie = page.header("set-cookie", "").split(";", 1)[0]
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


async def _profile(store: ShowrunStore, community: CommunityStore, *, email: str, name: str):
    user = await store.create_user(email=email, name=name, password_hash="test-only-hash")
    profile = await community.ensure_profile(
        user_id=user.id,
        workspace_id=user.workspace_id,
        display_name=name,
        email=email,
    )
    return user, profile


def test_validate_handle_rules() -> None:
    assert validate_handle("  Ada-Lovelace ") == "ada-lovelace"
    for bad in ["", "ab", "x" * 33, "-lead", "trail-", "has space", "UPPER!", "settings", "watch"]:
        with pytest.raises(ProfileError):
            validate_handle(bad)


async def test_change_handle_keeps_alias_and_blocks_reuse(tmp_path: Path) -> None:
    app = _application(tmp_path / "handles.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        user, profile = await _profile(store, community, email="a@example.com", name="Ada")
        original = profile.handle

        changed = await community.change_handle(user_id=user.id, new_handle="ada-l")
        assert changed.handle == "ada-l"

        # Old handle resolves to the new current handle (redirect alias).
        assert await community.resolve_handle(original) == "ada-l"
        assert await community.resolve_handle("ada-l") == "ada-l"
        assert await community.resolve_handle("nobody") is None

        # No-op when unchanged.
        same = await community.change_handle(user_id=user.id, new_handle="ada-l")
        assert same.handle == "ada-l"

        # A second creator cannot claim the current handle or the past alias.
        user2, _ = await _profile(store, community, email="b@example.com", name="Grace")
        with pytest.raises(ProfileError):
            await community.change_handle(user_id=user2.id, new_handle="ada-l")
        with pytest.raises(ProfileError):
            await community.change_handle(user_id=user2.id, new_handle=original)


async def test_handle_change_redirects_over_http(tmp_path: Path) -> None:
    app = _application(tmp_path / "handles-web.db")
    async with TestClient(app) as client:
        cookie = await _signup(client, email="ada@example.com", name="Ada")
        page = await client.get("/settings/profile", headers={"Cookie": cookie})
        cookie = _updated_cookie(page, cookie)
        original = re.search(r"/creators/([a-z0-9-]+)", page.text).group(1)

        changed = await client.post(
            "/settings/profile",
            body=urlencode(
                {
                    "handle": "ada-new",
                    "display_name": "Ada Lovelace",
                    "bio": "",
                    "visibility": "public",
                    "_csrf_token": _csrf(page.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert changed.status == 303

        # New handle serves; old handle 301-redirects to it.
        assert (await client.get("/creators/ada-new")).status == 200
        old = await client.get(f"/creators/{original}")
        assert old.status == 301
        assert old.header("location") == "/creators/ada-new"


async def test_reserved_and_taken_handles_rejected_in_form(tmp_path: Path) -> None:
    app = _application(tmp_path / "handles-reject.db")
    async with TestClient(app) as client:
        # First creator claims "taken".
        cookie_a = await _signup(client, email="a@example.com", name="Alpha")
        page_a = await client.get("/settings/profile", headers={"Cookie": cookie_a})
        cookie_a = _updated_cookie(page_a, cookie_a)
        claim = await client.post(
            "/settings/profile",
            body=urlencode(
                {
                    "handle": "taken",
                    "display_name": "Alpha",
                    "bio": "",
                    "visibility": "public",
                    "_csrf_token": _csrf(page_a.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie_a},
        )
        assert claim.status == 303

        cookie_b = await _signup(client, email="b@example.com", name="Beta")
        page_b = await client.get("/settings/profile", headers={"Cookie": cookie_b})
        cookie_b = _updated_cookie(page_b, cookie_b)

        reserved = await client.post(
            "/settings/profile",
            body=urlencode(
                {
                    "handle": "settings",
                    "display_name": "Beta",
                    "bio": "",
                    "visibility": "public",
                    "_csrf_token": _csrf(page_b.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie_b},
        )
        assert reserved.status == 200
        assert "reserved" in reserved.text.lower()

        taken = await client.post(
            "/settings/profile",
            body=urlencode(
                {
                    "handle": "taken",
                    "display_name": "Beta",
                    "bio": "",
                    "visibility": "public",
                    "_csrf_token": _csrf(page_b.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie_b},
        )
        assert taken.status == 200
        assert "taken" in taken.text.lower()
