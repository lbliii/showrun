ALTER TABLE releases
    ADD COLUMN disabled_at TEXT;

CREATE INDEX IF NOT EXISTS releases_active_idx
    ON releases (lesson_id, disabled_at, published_at);
