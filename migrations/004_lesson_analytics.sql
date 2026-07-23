CREATE INDEX IF NOT EXISTS usage_events_lesson_idx
    ON usage_events (lesson_id, event_name, occurred_at);
