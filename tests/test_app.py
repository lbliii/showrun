"""Behavioral proof for the Showrun prototype."""

from chirp.testing import TestClient

from app import app
from showrun.artifacts import load_artifact


async def test_home_renders_player_and_stack() -> None:
    async with TestClient(app) as client:
        response = await client.get("/")
        assert response.status == 200
        assert "Could agent sessions become documentation?" in response.text
        assert "showrunPlayer" in response.text
        assert "Chirp + Kida" in response.text
        assert "Instructor note" in response.text
        assert "showrun-session.jsonl" in response.text
        assert "chirpui.css" in response.text


async def test_ready_is_plain_and_healthy() -> None:
    async with TestClient(app) as client:
        response = await client.get("/ready")
        assert response.status == 200
        assert response.text.strip()


def test_artifact_parses_both_layers() -> None:
    artifact = load_artifact(
        app.config.static_dir / "artifacts" / "showrun-session.jsonl",
        app.config.static_dir / "artifacts" / "showrun-lesson.tape",
    )
    assert len(artifact.events) == 12
    assert len(artifact.chapters) == 5
    assert artifact.chapters[1].caption == "Replay is not the same as rerun."
    assert artifact.outputs == ("showrun-prototype.html", "showrun-prototype.mp4")


def test_app_passes_chirp_contract_check() -> None:
    app.check()
