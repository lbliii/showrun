"""Showrun and sr command contract."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from urllib.request import Request

import pytest

import showrun.cli
from showrun.cli import main

_SESSION = """\
{"type":"session","id":"cli-test","name":"CLI lesson"}
{"type":"message","at":0,"message":{"role":"user","content":"Direct this run."}}
{"type":"message","at":5,"message":{"role":"assistant","content":"Creating the first cut."}}
"""


def test_inspect_prints_human_and_json_summaries(tmp_path: Path, capsys) -> None:
    session = tmp_path / "session.jsonl"
    session.write_text(_SESSION, encoding="utf-8")

    assert main(["inspect", str(session)]) == 0
    human = capsys.readouterr().out
    assert "CLI lesson" in human
    assert "2 events" in human

    assert main(["inspect", str(session), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["format"] == "dvd/1"
    assert payload["source_format"] == "showrun-jsonl"


def test_import_writes_portable_artifact_and_refuses_overwrite(
    tmp_path: Path,
    capsys,
) -> None:
    session = tmp_path / "session.jsonl"
    output = tmp_path / "lesson.dvd.json"
    session.write_text(_SESSION, encoding="utf-8")

    assert main(["import", str(session), "--output", str(output)]) == 0
    assert capsys.readouterr().out.strip() == str(output)
    assert json.loads(output.read_text())["format"] == "dvd/1"

    with pytest.raises(SystemExit) as error:
        main(["import", str(session), "--output", str(output)])
    assert error.value.code == 2


def test_both_installed_entry_points_target_the_same_cli() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'showrun = "showrun.cli:main"' in pyproject
    assert 'sr = "showrun.cli:main"' in pyproject


def test_login_saves_private_credentials(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    config = tmp_path / "config.json"
    monkeypatch.setenv("SHOWRUN_CONFIG", str(config))
    token = "sr_live_" + "a" * 44

    assert main(["login", "--host", "https://showrun.example/", "--token", token]) == 0

    assert json.loads(config.read_text()) == {
        "host": "https://showrun.example",
        "token": token,
    }
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert token not in capsys.readouterr().out


def test_push_uses_saved_credentials_and_prints_editor_url(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    session = tmp_path / "session.jsonl"
    session.write_text(_SESSION, encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "host": "https://showrun.example",
                "token": "sr_live_" + "b" * 44,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SHOWRUN_CONFIG", str(config))
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {
                    "lesson_url": "/lessons/lesson_123/edit",
                    "duplicate": False,
                    "warnings": ["Potential credentials were redacted locally."],
                }
            ).encode()

    def fake_urlopen(request: Request, timeout: int):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(showrun.cli, "urlopen", fake_urlopen)

    assert main(["push", str(session), "--title", "CLI upload"]) == 0
    output = capsys.readouterr().out
    request = captured["request"]

    assert isinstance(request, Request)
    assert request.full_url == "https://showrun.example/api/v1/imports"
    assert request.get_header("Authorization", "").startswith("Bearer sr_live_")
    assert json.loads(request.data or b"{}")["title"] == "CLI upload"
    assert "https://showrun.example/lessons/lesson_123/edit" in output
    assert "warning:" in output
