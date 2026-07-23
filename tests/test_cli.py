"""Showrun and sr command contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
