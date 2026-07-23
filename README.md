# Showrun

**Turn agent runs into shows people can learn from.**

Showrun imports agent-session JSONL, removes host-only scaffolding and likely
credentials locally, creates a smart-paced first cut, saves it to a private
library, and publishes immutable watch pages and documentation embeds.

The product, project, package, and primary CLI are named `showrun`. The short
CLI alias is `sr`. Portable releases use the versioned `dvd/1` artifact format.

## Current vertical slice

- Codex rollout and canonical Showrun JSONL import
- Local structural filtering and common credential redaction
- Deterministic reading-time pacing and proposed chapters
- Persistent draft library
- Email/password accounts with isolated workspaces
- Hashed, revocable API tokens for CLI access
- Public and unlisted immutable releases
- Responsive watch and iframe embed pages
- oEmbed discovery and response
- Downloadable `.dvd.json` release manifests
- `showrun` and `sr` local CLI entry points

The curated conversation in `static/artifacts/` is the golden fixture and
ships as the first public release.

## Stack

- Python 3.14 and `uv`
- Chirp and Pounce
- Kida with Showrun-owned templates and CSS
- Patitas and Rosettes
- Alpine.js
- SQLite for local development
- PostgreSQL on Railway
- Railpack

## Run locally

```bash
uv sync --frozen
uv run python app.py
```

Open <http://127.0.0.1:8000> and create an account.

To use an explicit local configuration:

```bash
CHIRP_SECRET_KEY=replace-with-a-long-random-value \
uv run python app.py
```

## CLI

Both executable names invoke the same CLI:

```bash
showrun --version
sr --version

showrun inspect ~/.codex/sessions/YYYY/MM/DD/rollout-....jsonl
showrun import session.jsonl --output lesson.dvd.json
showrun serve --port 8000
```

`showrun import` works locally and never publishes automatically.

## Verify

```bash
uv run ruff check .
uv run ruff format . --check
uv run ty check showrun app.py
uv run pytest -q
env PYTHONPATH=. uv run chirp check app:app
uv build
```

## Railway

`railway.json` uses Railpack, starts `python app.py`, and checks `/ready`.

Production needs:

- A PostgreSQL service providing `DATABASE_URL`
- `CHIRP_SECRET_KEY`
- `CHIRP_ENV=production`
- `RAILPACK_PYTHON_VERSION=3.14`

Raw imported transcripts are not persisted. The current slice stores the
sanitized `dvd/1` manifest and a source hash in PostgreSQL. Railway object
storage remains a later requirement for raw opt-in archives and generated
video assets.
