-- Governed discovery taxonomy. Techniques may only be tagged with topics from
-- this curated catalog; auto-provisioning of arbitrary topics is removed. Seed
-- is idempotent (ON CONFLICT(key) DO NOTHING) so it is safe to re-run and to
-- extend in later migrations. Fixed timestamp keeps the migration deterministic.
INSERT INTO topics (id, key, label, description, created_at) VALUES
  ('topic_planning', 'planning', 'Planning',
   'Decomposing tasks and sequencing agent work.', '2026-07-24T00:00:00+00:00'),
  ('topic_debugging', 'debugging', 'Debugging',
   'Diagnosing and fixing failures in agent runs.', '2026-07-24T00:00:00+00:00'),
  ('topic_testing', 'testing', 'Testing',
   'Writing and running tests to verify agent work.', '2026-07-24T00:00:00+00:00'),
  ('topic_reliability', 'reliability', 'Reliability',
   'Making agent behavior resilient and repeatable.', '2026-07-24T00:00:00+00:00'),
  ('topic_tools', 'tools', 'Tool use',
   'Calling tools and interpreting their results.', '2026-07-24T00:00:00+00:00'),
  ('topic_research', 'research', 'Research',
   'Gathering and synthesizing sources during a task.', '2026-07-24T00:00:00+00:00'),
  ('topic_refactoring', 'refactoring', 'Refactoring',
   'Restructuring code safely with an agent.', '2026-07-24T00:00:00+00:00'),
  ('topic_code_review', 'code-review', 'Code review',
   'Reviewing diffs and surfacing defects.', '2026-07-24T00:00:00+00:00'),
  ('topic_security', 'security', 'Security',
   'Handling secrets, permissions, and safe execution.', '2026-07-24T00:00:00+00:00'),
  ('topic_data', 'data', 'Data',
   'Querying, transforming, and validating data.', '2026-07-24T00:00:00+00:00'),
  ('topic_prompting', 'prompting', 'Prompting',
   'Structuring instructions and context for agents.', '2026-07-24T00:00:00+00:00'),
  ('topic_documentation', 'documentation', 'Documentation',
   'Producing durable docs from agent runs.', '2026-07-24T00:00:00+00:00')
ON CONFLICT(key) DO NOTHING;
