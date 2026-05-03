-- Pending actions — Foundry's preview-then-commit pattern.
--
-- Every staged action lands here first. /approve runs the real dispatch
-- (which writes to ontology_action_log + graph_nodes); /reject just flips
-- status. The pending row records WHO requested + WHO approved + WHEN.

BEGIN;

CREATE TABLE IF NOT EXISTS pending_actions (
  pending_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  rid TEXT NOT NULL,                          -- canonical rid form
  action_name TEXT NOT NULL,
  args_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  preview_json JSONB,                         -- best-effort dry-run summary
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','approved','rejected','expired')),
  requested_by TEXT,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_by TEXT,
  resolved_at TIMESTAMPTZ,
  resolution_note TEXT,
  -- Once approved, this points at the actual ontology_action_log row that
  -- the real dispatch produced. Lets the UI link from pending → audit.
  result_log_id UUID,
  expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days'),
  tenant_id UUID DEFAULT '00000000-0000-0000-0000-000000000001'
);
CREATE INDEX IF NOT EXISTS idx_pa_rid_status ON pending_actions(rid, status);
CREATE INDEX IF NOT EXISTS idx_pa_status ON pending_actions(status, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_pa_action ON pending_actions(action_name, status);

COMMIT;
