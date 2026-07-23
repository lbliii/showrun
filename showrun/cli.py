"""Command-line entry points for local Showrun direction and preview."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from showrun.artifacts import create_artifact_from_text


def _artifact(path: Path, title: str = ""):
    if not path.is_file():
        raise ValueError(f"Session file not found: {path}")
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Session files must be UTF-8 JSONL") from exc
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
