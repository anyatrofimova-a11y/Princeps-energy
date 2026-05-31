-- Multi-step orchestration: queue tasks can depend on each other,
-- agent triggers get logged, research outputs get persisted.

ALTER TABLE builder.queue ADD COLUMN IF NOT EXISTS depends_on uuid[];
ALTER TABLE builder.queue ADD COLUMN IF NOT EXISTS mode text DEFAULT 'build';   -- build | research | agent_trigger
ALTER TABLE builder.queue ADD COLUMN IF NOT EXISTS plan_group uuid;             -- groups tasks from one operator prompt
ALTER TABLE builder.queue ADD COLUMN IF NOT EXISTS research_output text;        -- markdown summary when mode='research'
ALTER TABLE builder.queue ADD COLUMN IF NOT EXISTS sources jsonb DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_queue_depends_on ON builder.queue USING GIN (depends_on);
CREATE INDEX IF NOT EXISTS idx_queue_plan_group ON builder.queue (plan_group);

CREATE TABLE IF NOT EXISTS builder.agent_triggers (
  trigger_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_name      text NOT NULL,
  requested_by    text,
  task_id         uuid REFERENCES builder.queue(task_id) ON DELETE SET NULL,
  status          text DEFAULT 'queued',     -- queued | running | done | failed
  result          jsonb,
  started_at      timestamptz,
  finished_at     timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agent_triggers_status
  ON builder.agent_triggers (status, agent_name);

-- Slash-command audit (for /status, /list-queue, etc.)
CREATE TABLE IF NOT EXISTS builder.commands (
  command_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  command         text NOT NULL,
  args            text,
  requested_by    text,
  output          text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
