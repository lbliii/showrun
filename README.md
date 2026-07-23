# Showrun

**Turn agent runs into shows people can learn from.**

Showrun imports agent-session JSONL, removes host-only scaffolding and likely
credentials locally, creates a smart-paced first cut, saves it to a private
library, and publishes immutable watch pages and documentation embeds.

The product, project, package, and primary CLI are named `showrun`. The short
CLI alias is `sr`. Portable releases use the versioned `dvd/1` artifact format.

## Current vertical slice

- Codex rollout, canonical Showrun JSONL, and portable `dvd/1` import
- Typed execution evidence for MCP calls, delegation, web research, sources, file changes,
  tests, and generic tools
- Local structural filtering and common credential redaction
- Deterministic reading-time pacing and proposed chapters
- Sanitization review and an event/chapter lesson director
- Persistent, account-isolated draft libraries
- Email/password accounts with isolated workspaces
- Hashed, revocable API tokens for CLI access
- Public and unlisted immutable releases
- Responsive watch pages plus HTML, MDX, Markdown, and web-component embeds
- Private lesson analytics for chapter reach, origins, completion, and releases
- Searchable draft/published library with release history and unpublishing
- oEmbed discovery and response
- Downloadable `.dvd.json` release manifests
- `showrun` and `sr` CLI login, inspect, validate, import, push, latest, MCP, and serve workflows

The curated conversation in `static/artifacts/` is the golden fixture and
ships as the first public release.

### Execution evidence

Execution events stay compact in the lesson and expand into a public-safe
evidence view with provider, operation, status, elapsed time, bounded inputs
and outputs, and cited sources. This is proof of observable actions, not hidden
chain-of-thought.

The fields are additive to `dvd/1`, so existing artifacts continue to load.
All imports—including already-portable `.dvd.json` files—cross the same local
sanitization boundary. Sensitive structured keys are removed, private paths
are replaced, URL query strings and fragments are stripped, and evidence
previews and source lists are bounded before persistence or publication.

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
showrun validate lesson.dvd.json --json
showrun login --host https://showrun-production.up.railway.app
showrun push session.jsonl --title "A useful agent workflow"
showrun push lesson.dvd.json
sr latest
sr push --latest --title "The session I just finished"
showrun serve --port 8000
```

`showrun import` works locally and never publishes automatically. `showrun
validate` applies the same size, structure, timing, ordering, and redaction
rules used by the hosted product. `showrun push` accepts either a session or a
portable `.dvd.json`, creates a private draft, and never publishes
automatically. API tokens are stored with mode `0600` in the platform config
directory. `SHOWRUN_URL` and `SHOWRUN_TOKEN` override saved credentials for CI.

### MCP

`showrun mcp` exposes four stdio tools:

- `showrun_import_session` imports a path or the latest Codex session.
- `showrun_validate_artifact` validates and summarizes a local `.dvd.json`.
- `showrun_list_drafts` lists the authenticated workspace.
- `showrun_open_editor` returns the hosted editor URL for a lesson.

After installing the package, configure any stdio MCP client with:

```json
{
  "mcpServers": {
    "showrun": {
      "command": "showrun",
      "args": ["mcp"]
    }
  }
}
```

The MCP server uses the same credentials saved by `showrun login`.

## Documentation embeds

Every published watch page provides copy-ready HTML iframe, MDX, Markdown, and
web-component snippets. The framework-free component can be themed:

```html
<script defer src="https://showrun-production.up.railway.app/static/embed.js"></script>
<showrun-player
  src="https://showrun-production.up.railway.app/embed/your-release"
  title="A useful agent workflow"
  theme="dark"
  chapter="2"
></showrun-player>
```

Supported themes are `auto`, `light`, and `dark`. Use `chapter="2"` or
`start="49.5"` for documentation deep links. Attribute changes are observed,
so React, Vue, and other hydrated documentation systems can update a player
without recreating it. Releases are immutable; unpublishing removes public
playback without deleting release history.

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
