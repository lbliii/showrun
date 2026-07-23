"""Artifact contract and import behavior."""

import json

import pytest

from showrun.artifacts import (
    FORMAT_VERSION,
    artifact_from_json,
    create_artifact_from_text,
)
from showrun.importers import parse_session_text

CANONICAL = """\
{"type":"session","id":"session-1","name":"A tiny agent lesson"}
{"type":"message","at":0,"message":{"role":"user","content":"How should we structure this?"}}
{"type":"message","at":9,"message":\
{"role":"assistant","content":"Start with an immutable recording."}}
{"type":"event","at":20,"event":\
{"kind":"tool","name":"tests","content":"Four tests passed. token=abcdefghijk12345"}}
"""


def test_canonical_import_creates_deterministic_directed_artifact() -> None:
    artifact = create_artifact_from_text(CANONICAL, filename="lesson.jsonl")

    assert artifact.source_format == "showrun-jsonl"
    assert artifact.events[0].at == 0
    assert artifact.events[1].at > artifact.events[0].at
    assert artifact.duration > artifact.events[-1].at
    assert artifact.chapters[0].name == "Opening"
    assert artifact.to_manifest()["format"] == FORMAT_VERSION
    assert "[REDACTED]" in artifact.events[-1].text
    assert "abcdefghijk12345" not in artifact.to_json()


def test_codex_import_excludes_internal_messages_and_tool_arguments() -> None:
    transcript = "\n".join(
        [
            json.dumps(
                {
                    "type": "session_meta",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {"id": "codex-session"},
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "payload": {
                        "type": "message",
                        "role": "developer",
                        "content": [{"type": "input_text", "text": "private control text"}],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:02Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "<in-app-browser-context>hidden</in-app-browser-context>"
                                    "\n## My request for Codex:\nBuild a replay."
                                ),
                            }
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:03Z",
                    "payload": {
                        "type": "function_call",
                        "name": "run",
                        "arguments": '{"secret":"not-uploaded"}',
                    },
                }
            ),
        ]
    )

    artifact = create_artifact_from_text(transcript, filename="rollout.jsonl")

    serialized = artifact.to_json()
    assert artifact.source_format == "codex-jsonl"
    assert artifact.events[0].text == "Build a replay."
    assert artifact.events[1].text == "Ran run"
    assert "private control text" not in serialized
    assert "not-uploaded" not in serialized
    assert artifact.warnings


def test_manifest_round_trip_is_stable() -> None:
    artifact = create_artifact_from_text(CANONICAL)
    restored = artifact_from_json(artifact.to_json())

    assert restored == artifact
    assert restored.to_json() == artifact.to_json()


def test_import_ignores_only_an_incomplete_final_record() -> None:
    title, _, _, events, warnings = parse_session_text(CANONICAL + '{"type":')

    assert title == "A tiny agent lesson"
    assert len(events) == 3
    assert warnings == (
        "Ignored an incomplete final JSONL record.",
        "Potential credentials were redacted locally.",
    )


def test_import_rejects_invalid_middle_record() -> None:
    with pytest.raises(ValueError, match="Invalid JSON on line 2"):
        parse_session_text('{"type":"session"}\nnot-json\n{"type":"message"}')
