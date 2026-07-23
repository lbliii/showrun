# Showrun

**Showrun turns agent runs into shows people can learn from.**

This is the Chirp-stack reconstruction of AgentTape prototype 1. The source
conversation is stored as immutable JSONL. A separate `.tape` file owns
chapters, captions, notes, pacing, highlights, assertions, and intended output
formats.

The product, project, and package are named `showrun`. The planned CLI uses
`showrun` as its canonical command and `sr` as its short alias. Published
portable replay artifacts use the versioned `.dvd` media format.

## Stack

- Chirp for routing, content negotiation, static assets, health checks, and contracts
- Kida for server-rendered components and templates
- Chirp UI for the application runtime and shared UI primitives
- Alpine for local playback state
- Patitas and Rosettes for Markdown and highlighted learning content
- Plain CSS for the editorial player design

There is no database, account system, or Node build pipeline.

## Run locally

Requires Python 3.14 and `uv`.

```bash
uv sync --frozen
uv run python app.py
```

Open <http://127.0.0.1:8000>.

## Verify

```bash
uv run ruff check .
uv run ruff format . --check
uv run ty check app.py showrun_artifacts.py
uv run pytest -q
env PYTHONPATH=. uv run chirp check app:app
```

## Railway

`railway.json` follows the source-complete Chirp template pattern:

- RAILPACK build
- `python app.py`
- `/ready` health check
- one web service and no required variables

Showrun can add PostgreSQL later when the editor needs durable projects. The player
and portable artifacts do not require it.
