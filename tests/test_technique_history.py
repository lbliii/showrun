"""Technique version history, source release, and lineage (#34, under #14)."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode

from chirp.testing import TestClient

from showrun.web import create_app
from tests.test_community_web import (
    _csrf,
    _publish_public_release,
    _publish_technique,
    _release_slug,
    _signup,
    _updated_cookie,
)


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        secret_key="test-signing-key-with-enough-entropy",
    )


async def _publish_second_version(client: TestClient, cookie: str, lesson_path: str) -> str:
    form_page = await client.get(f"{lesson_path}/technique", headers={"Cookie": cookie})
    cookie = _updated_cookie(form_page, cookie)
    published = await client.post(
        "/techniques",
        body=urlencode(
            {
                "release_slug": _release_slug(form_page.text),
                "problem": "Flaky tool retries lose work.",
                "pattern": "Wrap idempotent tool calls in a bounded retry with jitter.",
                "use_when": "When a tool is idempotent but occasionally times out.",
                "objective": "Learn resilient retries with backoff caps.",
                "summary": "Bounded retry with jitter and backoff caps.",
                "limitations": "Not safe for non-idempotent side effects.",
                "topics": "reliability, tools",
                "_csrf_token": _csrf(form_page.text),
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
    )
    assert published.status == 303
    return published.header("location")


async def test_version_history_links_each_source_release(tmp_path: Path) -> None:
    app = _application(tmp_path / "history.db")
    async with TestClient(app) as client:
        cookie = await _signup(client, email="creator@example.com", name="Ada Creator")
        lesson_path, cookie = await _publish_public_release(client, cookie, title="Retry pattern")
        technique_path, cookie = await _publish_technique(client, cookie, lesson_path)
        # Edit the card to create version 2.
        again = await _publish_second_version(client, cookie, lesson_path)
        assert again == technique_path

        page = await client.get(technique_path)
        assert page.status == 200
        assert "Version history" in page.text
        # Both versions listed, newest first, current marked.
        assert "v2" in page.text and "v1" in page.text
        assert "current" in page.text
        # Each version links to a source release (the immutable watch page).
        assert page.text.count("Source release") >= 2
        assert re.search(r'href="/watch/[a-z0-9-]+">Source release', page.text)
        # Lineage empty state is present.
        assert "Adaptations" in page.text
        assert "No forks or reproductions yet." in page.text
