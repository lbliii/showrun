"""Technique page embeds the player and bounded evidence (#33, under #14)."""

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


async def test_technique_page_embeds_player_and_evidence(tmp_path: Path) -> None:
    app = _application(tmp_path / "technique-page.db")
    async with TestClient(app) as client:
        cookie = await _signup(client, email="creator@example.com", name="Ada Creator")
        lesson_path, cookie = await _publish_public_release(client, cookie, title="Retry pattern")
        technique_path, cookie = await _publish_technique(client, cookie, lesson_path)

        page = await client.get(technique_path)
        assert page.status == 200
        # Embeds the deployed player via its embed route (no duplication).
        assert 'src="/embed/' in page.text
        # Bounded, public-safe evidence reuses the shared evidence macro.
        assert "Evidence from the run" in page.text
        assert "Inspect evidence" in page.text
        # The full watch page remains one click away.
        assert "Open full watch page" in page.text
