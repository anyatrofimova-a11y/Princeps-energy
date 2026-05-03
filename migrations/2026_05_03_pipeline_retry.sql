-- Pipeline retry — track per-attempt history. attempt_number defaults
-- to 1 so existing rows stay correct.

BEGIN;

ALTER TABLE pipeline_node_runs
  ADD COLUMN IF NOT EXISTS attempt_number INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS attempts_total INT,
  ADD COLUMN IF NOT EXISTS retry_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_pnr_attempt ON pipeline_node_runs(run_id, node_id, attempt_number);

COMMIT;
