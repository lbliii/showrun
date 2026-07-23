"""Artifact contract and import behavior."""

import json

import pytest

from showrun.artifacts import (
    FORMAT_VERSION,
    artifact_from_json,
    create_artifact_from_text,
    direct_artifact,
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


def test_codex_import_excludes_internal_messages_and_sanitizes_tool_evidence() -> None:
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
                        "name": "mcp__railway__deployment_list",
                        "call_id": "call-1",
                        "arguments": '{"secret":"not-uploaded"}',
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:05Z",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-1",
                        "output": {
                            "status": "SUCCESS",
                            "path": "/Users/example/private/project",
                        },
                    },
                }
            ),
        ]
    )

    artifact = create_artifact_from_text(transcript, filename="rollout.jsonl")

    serialized = artifact.to_json()
    assert artifact.source_format == "codex-jsonl"
    assert artifact.events[0].text == "Build a replay."
    tool = artifact.events[1]
    assert tool.activity == "mcp"
    assert tool.provider == "Railway"
    assert tool.operation == "mcp__railway__deployment_list"
    assert tool.status == "success"
    assert tool.elapsed_ms == 2000
    assert tool.input_preview == '{"secret":"[REDACTED]"}'
    assert "[LOCAL PATH]" in tool.output_preview
    assert tool.redactions == ("Sensitive values removed locally.",)
    assert "private control text" not in serialized
    assert "not-uploaded" not in serialized
    assert "/Users/example" not in serialized
    assert artifact.warnings


def test_high_fidelity_event_round_trip_sanitizes_sources_and_details() -> None:
    transcript = "\n".join(
        [
            json.dumps({"type": "session", "id": "proof", "name": "Execution proof"}),
            json.dumps(
                {
                    "type": "message",
                    "at": 0,
                    "message": {"role": "user", "content": "Prove the MCP call."},
                }
            ),
            json.dumps(
                {
                    "type": "event",
                    "at": 3,
                    "event": {
                        "kind": "tool",
                        "activity": "mcp",
                        "name": "Railway deployment",
                        "content": "Inspected the production deployment.",
                        "provider": "Railway",
                        "operation": "deployment.list",
                        "status": "success",
                        "elapsed_ms": 842,
                        "input": {
                            "environment": "production",
                            "token": "abcdefghijk12345",
                            "access_token": "access-secret-value",
                            "client_secret": "client-secret-value",
                            "Set-Cookie": "session=private",
                        },
                        "output": {"status": "SUCCESS"},
                        "sources": [
                            {
                                "title": "Railway deployment",
                                "url": "https://railway.com/project/example?token=private#fragment",
                            }
                        ],
                        "redactions": ["Authentication removed"],
                    },
                }
            ),
        ]
    )

    artifact = create_artifact_from_text(transcript)
    restored = artifact_from_json(artifact.to_json())
    event = restored.events[1]

    assert restored == artifact
    assert event.activity == "mcp"
    assert event.status == "success"
    assert event.elapsed_ms == 842
    assert event.input_preview == (
        '{"environment":"production","token":"[REDACTED]",'
        '"access_token":"[REDACTED]","client_secret":"[REDACTED]",'
        '"Set-Cookie":"[REDACTED]"}'
    )
    assert event.output_preview == '{"status":"SUCCESS"}'
    assert event.sources[0].title == "Railway deployment"
    assert event.sources[0].url == "https://railway.com/project/example"
    assert event.sources[0].domain == "railway.com"
    assert "private" not in restored.to_json()
    assert "Potential credentials were redacted locally." in restored.warnings


def test_codex_imports_native_web_custom_and_shell_test_events() -> None:
    transcript = "\n".join(
        [
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {"id": "native-events"},
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Prove the workflow."}],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "payload": {
                        "type": "web_search_call",
                        "status": "completed",
                        "action": {
                            "type": "search",
                            "query": "agent trace documentation",
                            "sources": [
                                {
                                    "title": "Trace documentation",
                                    "url": "https://example.com/traces?token=private",
                                }
                            ],
                        },
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:02Z",
                    "payload": {
                        "type": "custom_tool_call",
                        "name": "apply_patch",
                        "call_id": "patch-1",
                        "input": "*** Update File: showrun.py",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:03Z",
                    "payload": {
                        "type": "custom_tool_call_output",
                        "call_id": "patch-1",
                        "output": "Success",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:04Z",
                    "payload": {
                        "type": "function_call",
                        "name": "shell_command",
                        "call_id": "test-1",
                        "arguments": '{"command":"uv run pytest tests/test_artifacts.py -q"}',
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "timestamp": "2026-01-01T00:00:06Z",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "test-1",
                        "output": "10 passed",
                    },
                }
            ),
        ]
    )

    artifact = create_artifact_from_text(transcript, filename="rollout.jsonl")

    assert [event.activity for event in artifact.events] == ["", "search", "file", "test"]
    assert artifact.events[1].status == "success"
    assert artifact.events[1].sources[0].url == "https://example.com/traces"
    assert "?token=" not in artifact.events[1].input_preview
    assert artifact.events[2].status == "success"
    assert artifact.events[2].operation == "apply_patch"
    assert artifact.events[3].status == "success"
    assert artifact.events[3].elapsed_ms == 2000


def test_manifest_round_trip_is_stable() -> None:
    artifact = create_artifact_from_text(CANONICAL)
    restored = artifact_from_json(artifact.to_json())

    assert restored == artifact
    assert restored.to_json() == artifact.to_json()


def test_portable_artifact_validation_redacts_secrets_and_rejects_bad_timing() -> None:
    artifact = create_artifact_from_text(CANONICAL)
    manifest = artifact.to_manifest()
    manifest["events"][0]["text"] = "token=abcdefghijk12345"

    restored = artifact_from_json(json.dumps(manifest))

    assert restored.events[0].text == "[REDACTED]"
    assert "Potential credentials were redacted locally." in restored.warnings

    manifest["events"][0]["at"] = "not-a-number"
    with pytest.raises(ValueError, match="event 1 is invalid"):
        artifact_from_json(json.dumps(manifest))


def test_portable_artifact_requires_sequential_events_and_chapters() -> None:
    artifact = create_artifact_from_text(CANONICAL)
    manifest = artifact.to_manifest()
    manifest["events"][1]["id"] = 9
    with pytest.raises(ValueError, match="IDs must be sequential"):
        artifact_from_json(json.dumps(manifest))

    manifest = artifact.to_manifest()
    manifest["chapters"].append(
        {
            "name": "Out of order",
            "at": -1,
            "caption": "",
            "note": "",
            "teaching_point": "",
        }
    )
    with pytest.raises(ValueError, match="chapter 2 is invalid"):
        artifact_from_json(json.dumps(manifest))


def test_director_reorders_and_rewrites_events_and_chapters() -> None:
    artifact = create_artifact_from_text(CANONICAL)

    directed = direct_artifact(
        artifact,
        title="  A directed lesson ",
        description="Teach the useful path.",
        included_event_ids={1, 2},
        event_durations={1: "3", 2: "4"},
        event_orders={1: "2", 2: "1"},
        event_pauses={1: "1.5", 2: "2"},
        event_labels={1: "Learner question", 2: "Core answer"},
        event_texts={
            1: "password=supersecret123",
            2: "Begin with the recording.",
        },
        chapter_values=(
            {
                "include": "",
                "order": "1",
                "name": "Removed",
                "at": "0",
            },
            {
                "include": "on",
                "order": "2",
                "name": "Conclusion",
                "at": "5",
                "caption": "Finish",
            },
            {
                "include": "on",
                "order": "1",
                "name": "New opening",
                "at": "2",
                "caption": "Start",
            },
        ),
    )

    assert [event.label for event in directed.events] == ["Core answer", "Learner question"]
    assert directed.events[0].text == "Begin with the recording."
    assert directed.events[1].text == "[REDACTED]"
    assert "Potential credentials were redacted locally." in directed.warnings
    assert directed.events[0].pause_after == 2
    assert directed.events[1].at == 6
    assert [chapter.name for chapter in directed.chapters] == ["New opening", "Conclusion"]
    assert directed.chapters[0].at == 0


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
