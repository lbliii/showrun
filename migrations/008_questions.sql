-- Task questions and demonstrated answers. A question is public task framing;
-- an answer references a published technique (a demonstrated answer), never
-- free text. The asker may accept exactly one answer. Portable SQL.

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    asker_profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    -- The accepted answer, if any. App-enforced (no FK) to avoid a circular
    -- questions<->answers reference; there is at most one at a time.
    accepted_answer_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS answers (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    technique_id TEXT NOT NULL REFERENCES techniques(id) ON DELETE CASCADE,
    answerer_profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    -- One demonstrated answer per technique per question.
    UNIQUE (question_id, technique_id)
);

CREATE TABLE IF NOT EXISTS question_topics (
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    PRIMARY KEY (question_id, topic_id)
);

CREATE INDEX IF NOT EXISTS questions_created_idx
    ON questions (created_at, id);

CREATE INDEX IF NOT EXISTS answers_question_idx
    ON answers (question_id, created_at);

CREATE INDEX IF NOT EXISTS question_topics_topic_idx
    ON question_topics (topic_id, question_id);
