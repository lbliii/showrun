"""Command-line entry points for local Showrun direction and preview."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from collections.abc import Sequence
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from showrun.artifacts import artifact_from_json, create_artifact_from_text

DEFAULT_HOST = "https://showrun-production.up.railway.app"


def _artifact(path: Path, title: str = ""):
    if not path.is_file():
        raise ValueError(f"Session file not found: {path}")
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Session files must be UTF-8 JSONL") from exc
    if path.name.lower().endswith(".dvd.json"):
        artifact = artifact_from_json(source)
        return replace(artifact, title=title.strip()[:120]) if title.strip() else artifact
    return create_artifact_from_text(source, filename=path.name, title=title)


def _inspect(args: argparse.Namespace) -> int:
    artifact = _artifact(args.path)
    summary = {
        "format": "dvd/1",
        "title": artifact.title,
        "session_id": artifact.session_id,
        "source_format": artifact.source_format,
        "events": len(artifact.events),
        "chapters": len(artifact.chapters),
        "duration": artifact.duration,
        "warnings": list(artifact.warnings),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(f"{summary['title']}")
        print(
            f"{summary['events']} events · {summary['chapters']} chapters · "
            f"{summary['duration']:.1f}s · {summary['source_format']}"
        )
        for warning in summary["warnings"]:
            print(f"warning: {warning}")
    return 0


def _direct(args: argparse.Namespace) -> int:
    artifact = _artifact(args.path, args.title)
    output = args.output or args.path.with_suffix(".dvd.json")
    if output.exists() and not args.force:
        raise ValueError(f"Refusing to overwrite {output}; pass --force to replace it")
    output.write_text(f"{artifact.to_json()}\n", encoding="utf-8")
    print(output)
    return 0


def _serve(args: argparse.Namespace) -> int:
    from showrun.web import create_app

    create_app().run(host=args.host, port=args.port)
    return 0


def _config_path() -> Path:
    configured = os.environ.get("SHOWRUN_CONFIG")
    if configured:
        return Path(configured).expanduser()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "showrun" / "config.json"


def _normalize_host(value: str) -> str:
    host = value.strip().rstrip("/")
    parsed = urlparse(host)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Showrun host must be an http:// or https:// URL")
    return host


def _write_credentials(host: str, token: str) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"host": host, "token": token}, handle, ensure_ascii=False)
        handle.write("\n")
    path.chmod(0o600)


def _load_credentials(
    *,
    host_override: str = "",
    token_override: str = "",
) -> tuple[str, str]:
    saved: dict[str, str] = {}
    path = _config_path()
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"Could not read Showrun credentials at {path}") from exc
        if isinstance(payload, dict):
            saved = {str(key): str(value) for key, value in payload.items()}
    host = host_override or os.environ.get("SHOWRUN_URL", "") or saved.get("host", "")
    token = token_override or os.environ.get("SHOWRUN_TOKEN", "") or saved.get("token", "")
    if not host or not token:
        raise ValueError("Run `showrun login` first, or set SHOWRUN_URL and SHOWRUN_TOKEN")
    return _normalize_host(host), token


def _login_command(args: argparse.Namespace) -> int:
    host = _normalize_host(args.host or os.environ.get("SHOWRUN_URL", "") or DEFAULT_HOST)
    token = args.token or os.environ.get("SHOWRUN_TOKEN", "") or getpass.getpass("Showrun token: ")
    if not token.startswith("sr_live_") or len(token) < 32:
        raise ValueError("That does not look like a Showrun API token")
    _write_credentials(host, token)
    print(f"Saved Showrun credentials for {host}")
    return 0


def find_latest_session(root: Path | None = None) -> Path:
    """Return the newest Codex JSONL session available on this machine."""

    configured = os.environ.get("CODEX_SESSIONS_DIR")
    default_root = Path(configured).expanduser() if configured else Path.home() / ".codex/sessions"
    session_root = root or default_root
    if not session_root.is_dir():
        raise ValueError(f"Codex sessions directory not found: {session_root}")
    candidates = [path for path in session_root.rglob("*.jsonl") if path.is_file()]
    if not candidates:
        raise ValueError(f"No Codex JSONL sessions found under {session_root}")
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def _resolve_session_path(path: Path | None, *, latest: bool) -> Path:
    if latest and path is not None:
        raise ValueError("Pass a session path or --latest, not both")
    resolved = find_latest_session() if latest else path
    if resolved is None:
        raise ValueError("Pass a session path or use --latest")
    if not resolved.is_file():
        raise ValueError(f"Session file not found: {resolved}")
    return resolved


def api_request(
    method: str,
    path: str,
    *,
    host: str,
    token: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(
        urljoin(f"{host}/", path.lstrip("/")),
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"showrun/{version('showrun')}",
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read())
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("error", exc.reason)
        except json.JSONDecodeError, AttributeError:
            detail = exc.reason
        raise ValueError(f"Showrun rejected the request: {detail}") from exc
    except URLError as exc:
        raise ValueError(f"Could not reach {host}: {exc.reason}") from exc
    if not isinstance(result, dict):
        raise ValueError("Showrun returned an invalid API response")
    return result


def push_session(
    path: Path,
    *,
    title: str = "",
    host_override: str = "",
    token_override: str = "",
) -> tuple[str, dict[str, object]]:
    try:
        transcript = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Session files must be UTF-8 JSONL") from exc
    host, token = _load_credentials(
        host_override=host_override,
        token_override=token_override,
    )
    request_payload: dict[str, object] = {
        "filename": path.name,
        "title": title,
    }
    if path.name.lower().endswith(".dvd.json"):
        try:
            portable = json.loads(transcript)
        except json.JSONDecodeError as exc:
            raise ValueError("Portable artifacts must be valid JSON") from exc
        if not isinstance(portable, dict):
            raise ValueError("Portable artifacts must be JSON objects")
        artifact_from_json(transcript)
        request_payload["artifact"] = portable
    else:
        request_payload["transcript"] = transcript
    payload = api_request(
        "POST",
        "/api/v1/imports",
        host=host,
        token=token,
        payload=request_payload,
    )
    lesson_url = str(payload.get("lesson_url") or "")
    if not lesson_url:
        raise ValueError("Showrun returned an invalid import response")
    return urljoin(f"{host}/", lesson_url.lstrip("/")), payload


def _push(args: argparse.Namespace) -> int:
    path = _resolve_session_path(args.path, latest=args.latest)
    lesson_url, payload = push_session(
        path,
        title=args.title,
        host_override=args.host,
        token_override=args.token,
    )
    print(lesson_url)
    if payload.get("duplicate"):
        print("Already imported; opened the existing draft.")
    warnings = payload.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            print(f"warning: {warning}")
    return 0


def _latest(args: argparse.Namespace) -> int:
    path = find_latest_session(args.root)
    if args.json:
        print(
            json.dumps(
                {
                    "path": str(path),
                    "modified_ns": path.stat().st_mtime_ns,
                }
            )
        )
    else:
        print(path)
    return 0


def _mcp(_args: argparse.Namespace) -> int:
    from showrun.mcp_server import run

    run()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="showrun",
        description="Turn agent runs into shows people can learn from.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('showrun')}")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_command = commands.add_parser("inspect", help="Inspect and safely normalize a session")
    inspect_command.add_argument("path", type=Path)
    inspect_command.add_argument("--json", action="store_true")
    inspect_command.set_defaults(handler=_inspect)

    validate_command = commands.add_parser(
        "validate",
        help="Validate and summarize a portable dvd/1 artifact",
    )
    validate_command.add_argument("path", type=Path)
    validate_command.add_argument("--json", action="store_true")
    validate_command.set_defaults(handler=_inspect)

    direct_command = commands.add_parser(
        "import",
        help="Create a locally directed dvd/1 artifact",
    )
    direct_command.add_argument("path", type=Path)
    direct_command.add_argument("--title", default="")
    direct_command.add_argument("-o", "--output", type=Path)
    direct_command.add_argument("--force", action="store_true")
    direct_command.set_defaults(handler=_direct)

    serve_command = commands.add_parser("serve", help="Run the Showrun library locally")
    serve_command.add_argument("--host", default="127.0.0.1")
    serve_command.add_argument("--port", type=int, default=8000)
    serve_command.set_defaults(handler=_serve)

    login_command = commands.add_parser("login", help="Save a hosted Showrun API token")
    login_command.add_argument("--host", default="")
    login_command.add_argument("--token", default="")
    login_command.set_defaults(handler=_login_command)

    push_command = commands.add_parser("push", help="Import a session into hosted Showrun")
    push_command.add_argument("path", type=Path, nargs="?")
    push_command.add_argument("--latest", action="store_true")
    push_command.add_argument("--title", default="")
    push_command.add_argument("--host", default="")
    push_command.add_argument("--token", default="")
    push_command.set_defaults(handler=_push)

    latest_command = commands.add_parser("latest", help="Find the newest Codex session")
    latest_command.add_argument("--root", type=Path)
    latest_command.add_argument("--json", action="store_true")
    latest_command.set_defaults(handler=_latest)

    mcp_command = commands.add_parser("mcp", help="Run the Showrun MCP server over stdio")
    mcp_command.set_defaults(handler=_mcp)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Showrun CLI and translate user errors into parser errors."""

    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ValueError as exc:
        parser.error(str(exc))
    return 2
