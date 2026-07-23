"""Security-boundary coverage for high-fidelity execution evidence."""

import json

import pytest

from showrun.artifacts import artifact_from_json, create_artifact_from_text
from showrun.evidence import MAX_ELAPSED_MS

_BASE = """\
{"type":"session","id":"fidelity","name":"Fidelity boundary"}
{"type":"message","at":0,"message":{"role":"user","content":"Show the evidence."}}
"""


def test_direct_dvd_upload_sanitizes_structured_evidence() -> None:
    artifact = create_artifact_from_text(_BASE)
    manifest = artifact.to_manifest()
    event = manifest["events"][0]
    event["input_preview"] = '{"access_token":"oops","safe":"visible"}'
    event["output_preview"] = '{"client_secret":"private"}'
    event["raw_preview"] = '{"Set-Cookie":"session=private"}'
    event["sources"] = [
        {
            "title": "Invalid supplied domain",
            "domain": "token=abcdefghijk12345",
        }
    ]

    restored = artifact_from_json(json.dumps(manifest))
    serialized = restored.to_json()

    assert restored.events[0].input_preview == ('{"access_token":"[REDACTED]","safe":"visible"}')
    assert restored.events[0].output_preview == '{"client_secret":"[REDACTED]"}'
    assert restored.events[0].raw_preview == '{"Set-Cookie":"[REDACTED]"}'
    assert restored.events[0].sources[0].domain == ""
    assert "session=private" not in serialized
    assert "abcdefghijk12345" not in serialized
    assert "Potential credentials were redacted locally." in restored.warnings


def test_direct_dvd_upload_rejects_impossible_elapsed_time() -> None:
    artifact = create_artifact_from_text(_BASE)
    manifest = artifact.to_manifest()
    manifest["events"][0]["elapsed_ms"] = MAX_ELAPSED_MS + 1

    with pytest.raises(ValueError, match="invalid elapsed time"):
        artifact_from_json(json.dumps(manifest))


def test_redaction_notes_are_bounded_and_round_trip_stably() -> None:
    artifact = create_artifact_from_text(_BASE)
    manifest = artifact.to_manifest()
    manifest["events"][0]["input_preview"] = {"access_token": "secret-value"}
    manifest["events"][0]["redactions"] = [f"note {index}" for index in range(20)]

    first = artifact_from_json(json.dumps(manifest))
    second = artifact_from_json(first.to_json())

    assert len(first.events[0].redactions) == 20
    assert first.events[0].redactions[-1] == "Sensitive values removed locally."
    assert second == first


def test_required_redaction_note_is_reserved_when_already_over_limit() -> None:
    artifact = create_artifact_from_text(_BASE)
    manifest = artifact.to_manifest()
    manifest["events"][0]["input_preview"] = {"access_token": "secret-value"}
    manifest["events"][0]["redactions"] = [
        *(f"note {index}" for index in range(20)),
        "Sensitive values removed locally.",
    ]

    restored = artifact_from_json(json.dumps(manifest))

    assert len(restored.events[0].redactions) == 20
    assert restored.events[0].redactions[-1] == "Sensitive values removed locally."
