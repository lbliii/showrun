CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    token_prefix TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    scopes TEXT NOT NULL DEFAULT 'imports:write',
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);

ALTER TABLE recordings
    ADD COLUMN workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE;

ALTER TABLE lessons
    ADD COLUMN workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE;

CREATE UNIQUE INDEX IF NOT EXISTS recordings_workspace_source_idx
    ON recordings (workspace_id, source_sha256);

CREATE INDEX IF NOT EXISTS users_workspace_idx
    ON users (workspace_id, id);

CREATE INDEX IF NOT EXISTS api_tokens_workspace_idx
    ON api_tokens (workspace_id, created_at);

CREATE TABLE IF NOT EXISTS usage_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
    lesson_id TEXT REFERENCES lessons(id) ON DELETE SET NULL,
    release_id TEXT REFERENCES releases(id) ON DELETE SET NULL,
    event_name TEXT NOT NULL,
    properties_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS usage_events_workspace_idx
    ON usage_events (workspace_id, occurred_at);
