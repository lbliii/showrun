"""A dependency-free MCP stdio surface for Showrun capture workflows."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

from showrun.artifacts import artifact_from_json
from showrun.cli import _load_credentials, api_request, find_latest_session, push_session

PROTOCOL_VERSION = "2025-03-26"

TOOLS = [
    {
        "name": "showrun_import_session",
        "description": "Import a local agent session or dvd/1 artifact as a private draft.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "latest": {"type": "boolean", "default": False},
                "title": {"type": "string"},
            },
        },
    },
    {
        "name": "showrun_validate_artifact",
        "description": "Validate a local portable dvd/1 artifact before sharing it.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "showrun_list_drafts",
        "description": "List lessons in the authenticated Showrun workspace.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "showrun_open_editor",
        "description": "Return the hosted editor URL for a Showrun lesson.",
        "inputSchema": {
            "type": "object",
            "properties": {"lesson_id": {"type": "string"}},
            "required": ["lesson_id"],
        },
    },
]


def _tool_result(payload: object, *, error: bool = False) -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": error,
    }


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, object]:
    """Execute one MCP tool using the same credential and API contracts as the CLI."""

    try:
        if name == "showrun_import_session":
            latest = bool(arguments.get("latest"))
            raw_path = str(arguments.get("path") or "")
            if latest and raw_path:
                raise ValueError("Pass path or latest, not both")
            path = find_latest_session() if latest else Path(raw_path).expanduser()
            if not raw_path and not latest:
                raise ValueError("path is required unless latest is true")
            url, payload = push_session(path, title=str(arguments.get("title") or ""))
            return _tool_result({"editor_url": url, **payload})
        if name == "showrun_list_drafts":
            host, token = _load_credentials()
            return _tool_result(api_request("GET", "/api/v1/lessons", host=host, token=token))
        if name == "showrun_validate_artifact":
            path = Path(str(arguments.get("path") or "")).expanduser()
            if not path.is_file():
                raise ValueError("A valid artifact path is required")
            artifact = artifact_from_json(path.read_text(encoding="utf-8"))
            return _tool_result(
                {
                    "format": "dvd/1",
                    "title": artifact.title,
                    "events": len(artifact.events),
                    "chapters": len(artifact.chapters),
                    "duration": artifact.duration,
                    "warnings": list(artifact.warnings),
                }
            )
        if name == "showrun_open_editor":
            lesson_id = str(arguments.get("lesson_id") or "").strip()
            if not lesson_id.startswith("lesson_"):
                raise ValueError("A valid lesson_id is required")
            host, _token = _load_credentials()
            return _tool_result({"editor_url": f"{host}/lessons/{lesson_id}/edit"})
        raise ValueError(f"Unknown Showrun tool: {name}")
    except (OSError, ValueError) as exc:
        return _tool_result({"error": str(exc)}, error=True)


def handle_message(message: dict[str, Any]) -> dict[str, object] | None:
    """Handle the MCP subset required by stdio clients."""

    method = str(message.get("method") or "")
    request_id = message.get("id")
    if request_id is None:
        return None
    if method == "initialize":
        result: object = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "showrun", "version": "0.1.0"},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        result = call_tool(
            str(params.get("name") or ""),
            dict(params.get("arguments") or {}),
        )
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def run(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    """Serve newline-delimited JSON-RPC until stdin closes."""

    for line in stdin:
        try:
            message = json.loads(line)
            response = handle_message(message)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": str(exc)},
            }
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            stdout.flush()
