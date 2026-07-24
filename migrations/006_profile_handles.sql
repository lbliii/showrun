-- Handle registry: every handle a profile has ever held, so past handles keep
-- redirecting and can never be re-claimed by another creator. The current
-- handle still lives authoritatively on profiles.handle; this table is the
-- global uniqueness registry and the alias source for redirects.
CREATE TABLE IF NOT EXISTS profile_handles (
    handle TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS profile_handles_profile_idx
    ON profile_handles (profile_id, created_at);
