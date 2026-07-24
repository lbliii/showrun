-- Fork ancestry: a private draft lesson in the forking workspace, permanently
-- linked to the source technique version and its creator. Ancestry uses
-- ON DELETE RESTRICT so a fork's lineage can never be silently removed by
-- deleting the source. Idempotent per (workspace, request_key).
CREATE TABLE IF NOT EXISTS technique_forks (
    id TEXT PRIMARY KEY,
    child_lesson_id TEXT NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    child_workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    source_technique_id TEXT NOT NULL REFERENCES techniques(id) ON DELETE RESTRICT,
    source_version_id TEXT NOT NULL REFERENCES technique_versions(id) ON DELETE RESTRICT,
    source_profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE RESTRICT,
    request_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (child_workspace_id, request_key)
);

CREATE INDEX IF NOT EXISTS technique_forks_child_idx
    ON technique_forks (child_lesson_id);

CREATE INDEX IF NOT EXISTS technique_forks_source_idx
    ON technique_forks (source_technique_id);
