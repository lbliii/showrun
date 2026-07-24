"""Technique page share metadata, chapter deep-links, a11y (#35, under #14)."""

from __future__ import annotations

from pathlib import Path

from chirp.testing import TestClient

from showrun.web import create_app
from tests.test_community_web import (
    _publish_public_release,
    _publish_technique,
    _signup,
)


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        secret_key="test-signing-key-with-enough-entropy",
    )


async def test_share_metadata_deeplinks_and_a11y(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SHOWRUN_PUBLIC_URL", "https://showrun.example")
    app = _application(tmp_path / "share.db")
    async with TestClient(app) as client:
        cookie = await _signup(client, email="creator@example.com", name="Ada Creator")
        lesson_path, cookie = await _publish_public_release(client, cookie, title="Retry pattern")
        technique_path, cookie = await _publish_technique(client, cookie, lesson_path)
        slug = technique_path.rsplit("/", 1)[-1]

        page = await client.get(technique_path)
        assert page.status == 200
        # Canonical + OpenGraph/Twitter share metadata.
        canonical = f'<link rel="canonical" href="https://showrun.example/techniques/{slug}">'
        assert canonical in page.text
        assert '<meta property="og:title"' in page.text
        assert '<meta property="og:url" content="https://showrun.example/techniques/' in page.text
        assert '<meta name="twitter:card"' in page.text
        # Accessibility landmarks.
        assert 'aria-labelledby="technique-title"' in page.text
        assert 'id="technique-title"' in page.text
        assert 'aria-label="Chapters"' in page.text

        # Chapter deep-link reflects into the embedded player.
        deep = await client.get(f"{technique_path}?chapter=1")
        assert deep.status == 200
        assert 'src="/embed/' in deep.text
        assert "?chapter=1" in deep.text
        assert 'aria-current="true"' in deep.text

        # Out-of-range chapter is ignored (no unsanitized passthrough).
        bad = await client.get(f"{technique_path}?chapter=999")
        assert bad.status == 200
        assert "?chapter=999" not in bad.text

        # A start time deep-link is accepted and bounded.
        start = await client.get(f"{technique_path}?start=12.5")
        assert "?start=12.5" in start.text
