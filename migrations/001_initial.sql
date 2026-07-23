CREATE TABLE IF NOT EXISTS recordings (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source_format TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    event_count INTEGER NOT NULL CHECK (event_count > 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'published')),
    visibility TEXT NOT NULL DEFAULT 'private'
        CHECK (visibility IN ('private', 'unlisted', 'public')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS releases (
    id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    visibility TEXT NOT NULL
        CHECK (visibility IN ('unlisted', 'public')),
    manifest_json TEXT NOT NULL,
    published_at TEXT NOT NULL,
    UNIQUE (lesson_id, revision, visibility)
);

CREATE INDEX IF NOT EXISTS lessons_updated_idx
    ON lessons (updated_at, id);

CREATE INDEX IF NOT EXISTS releases_published_idx
    ON releases (published_at, slug);
