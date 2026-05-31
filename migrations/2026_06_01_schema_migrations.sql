-- Track which migration files have been applied, so the platform agent
-- can detect drift and apply the missing ones (or enqueue a build task
-- when a migration looks risky).

CREATE TABLE IF NOT EXISTS schema_migrations (
  filename       text PRIMARY KEY,
  applied_at     timestamptz NOT NULL DEFAULT now(),
  sha256         text,
  applied_by     text DEFAULT 'platform_agent'
);

-- Backfill all the SQL files that already landed by inspecting the repo
-- at agent boot (the platform agent populates this on first run by
-- assuming everything currently in migrations/ is applied if the DDL
-- it would add already exists).
