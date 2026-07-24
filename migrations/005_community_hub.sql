-- Community Hub foundation: public creator identity, stable techniques, and
-- immutable technique versions layered on top of the existing immutable
-- releases. Portable across SQLite and PostgreSQL: TEXT primary keys generated
-- by the application, no dialect-specific autoincrement, and CHECK/UNIQUE/FK
-- constraints supported by both engines.

-- A profile is the public identity for one creator (a user and their
-- workspace). Handle is the stable, URL-facing identifier.
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL UNIQUE REFERENCES workspaces(id) ON DELETE CASCADE,
    handle TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    bio TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'public'
        CHECK (visibility IN ('public', 'private')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Governed discovery taxonomy. `key` is the deterministic slug used in URLs and
-- joins; `label` is the human-facing name.
CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- Stable technique identity and lifecycle. Exactly one technique per source
-- lesson so the public URL and lineage remain stable across versions.
--   published  -> discoverable when a public head version exists
--   unlisted   -> reachable by direct slug, never discoverable or counted
--   disabled   -> absent from every public surface, history retained
CREATE TABLE IF NOT EXISTS techniques (
    id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL UNIQUE REFERENCES lessons(id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'published'
        CHECK (status IN ('published', 'unlisted', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Immutable teaching metadata. Every version references exactly one release.
-- `content_hash` is the idempotency key: republishing identical teaching
-- metadata for the same release returns the existing version, while any change
-- creates a new immutable version.
CREATE TABLE IF NOT EXISTS technique_versions (
    id TEXT PRIMARY KEY,
    technique_id TEXT NOT NULL REFERENCES techniques(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version > 0),
    release_id TEXT NOT NULL REFERENCES releases(id) ON DELETE RESTRICT,
    problem TEXT NOT NULL,
    pattern TEXT NOT NULL,
    use_when TEXT NOT NULL,
    objective TEXT NOT NULL,
    limitations TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (technique_id, version),
    UNIQUE (technique_id, content_hash)
);

-- Many-to-many technique/topic assignment.
CREATE TABLE IF NOT EXISTS technique_topics (
    technique_id TEXT NOT NULL REFERENCES techniques(id) ON DELETE CASCADE,
    topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    PRIMARY KEY (technique_id, topic_id)
);

CREATE INDEX IF NOT EXISTS techniques_profile_idx
    ON techniques (profile_id, updated_at);

CREATE INDEX IF NOT EXISTS technique_versions_release_idx
    ON technique_versions (release_id);

CREATE INDEX IF NOT EXISTS technique_versions_head_idx
    ON technique_versions (technique_id, version);

CREATE INDEX IF NOT EXISTS technique_topics_topic_idx
    ON technique_topics (topic_id, technique_id);
