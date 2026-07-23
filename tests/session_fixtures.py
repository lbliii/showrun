"""Reusable agent-session fixtures."""

import json

RICH_SESSION = "\n".join(
    json.dumps(record, separators=(",", ":"))
    for record in (
        {"type": "session", "id": "import-test", "name": "Imported test session"},
        {
            "type": "message",
            "at": 0,
            "message": {"role": "user", "content": "Can this become a show?"},
        },
        {
            "type": "message",
            "at": 8,
            "message": {"role": "assistant", "content": "Yes. Normalize it first."},
        },
        {
            "type": "event",
            "at": 12,
            "event": {
                "kind": "tool",
                "activity": "test",
                "status": "success",
                "provider": "pytest",
                "operation": "pytest -q",
                "name": "pytest",
                "content": "Tests passed.",
                "input": {"suite": "tests"},
                "output": {"passed": 32},
                "elapsed_ms": 412,
                "sources": [
                    {
                        "title": "Test report",
                        "url": "https://docs.example/test-report?token=private",
                    }
                ],
            },
        },
    )
)
