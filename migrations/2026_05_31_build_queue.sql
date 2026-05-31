-- Self-build queue for princeps-agent-builder.
--
-- Each row is a work item the builder agent picks up: a free-form
-- brief, optional file targets, branch policy, and an audit trail of
-- what it actually did (commit sha, PR url, deploy outcome).

CREATE SCHEMA IF NOT EXISTS builder;

CREATE TABLE IF NOT EXISTS builder.queue (
  task_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  title            text NOT NULL,
  brief            text NOT NULL,            -- prompt for Claude
  context_paths    text[] DEFAULT '{}',      -- repo files to pre-load as context
  branch_policy    text DEFAULT 'pr',        -- pr | direct-main | dry-run
  auto_merge       boolean DEFAULT false,    -- auto-merge if checks pass (only if branch_policy='pr')
  max_files_changed integer DEFAULT 6,       -- safety cap
  status           text DEFAULT 'pending',   -- pending | in_progress | done | failed | rejected
  priority         integer DEFAULT 5,        -- 1 = urgent ... 9 = nice-to-have
  requested_by     text,                     -- 'user' | agent name
  created_at       timestamptz NOT NULL DEFAULT now(),
  started_at       timestamptz,
  finished_at      timestamptz,
  -- Builder fills these in as it works:
  branch_name      text,
  commit_sha       text,
  pr_number        integer,
  pr_url           text,
  files_changed    jsonb,
  claude_plan      text,                     -- the plan Claude produced
  deploy_run_id    text,                     -- GitHub Actions run id (Fly auto-deploy)
  error            text,
  audit            jsonb DEFAULT '[]'::jsonb -- timeline of events
);

CREATE INDEX IF NOT EXISTS idx_build_queue_status
  ON builder.queue (status, priority, created_at);

CREATE TABLE IF NOT EXISTS builder.runs (
  run_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id          uuid REFERENCES builder.queue(task_id) ON DELETE CASCADE,
  step             text NOT NULL,           -- 'plan' | 'diff' | 'branch' | 'commit' | 'push' | 'pr' | 'merge'
  ok               boolean NOT NULL,
  detail           jsonb,
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_builder_runs_task
  ON builder.runs (task_id, created_at);

-- Seed a few starter tasks so the agent has something to do on first boot.
INSERT INTO builder.queue (title, brief, context_paths, branch_policy, priority, requested_by)
VALUES
  ('Add /api/dockets/sources/registry endpoint',
   'Add a GET endpoint /api/dockets/sources/registry that returns the SOURCE_REGISTRY dict from utils/docket_enricher.py as JSON so the frontend can show available source mappings.',
   ARRAY['utils/docket_enricher.py','app/routers/dockets.py'],
   'pr', 7, 'agent:bootstrap'),
  ('Add UK Strategic Spatial Energy Plan to docket source registry',
   'Add a SOURCE_REGISTRY entry in utils/docket_enricher.py for the latest NESO SSEP if missing. Verify the URL is current via a HEAD probe.',
   ARRAY['utils/docket_enricher.py'],
   'pr', 8, 'agent:bootstrap'),
  ('Surface chat verdict rating in the docket detail UI',
   'In feasi-frontend/src/components/IntelligenceWorkspace.jsx, when the user opens a docket, fetch /api/dockets/{id}/enriched and render the confidence rating as a small pill.',
   ARRAY['feasi-frontend/src/components/IntelligenceWorkspace.jsx'],
   'pr', 6, 'agent:bootstrap')
ON CONFLICT DO NOTHING;
