-- Pipeline Builder — Foundry-style DAG composer.
--
-- Each pipeline is a JSON manifest of typed nodes (connector_source,
-- sql_transform, set_filter, dataset_sink). Execution is topological;
-- every node-fire writes to pipeline_node_runs for full lineage.

BEGIN;

CREATE TABLE IF NOT EXISTS data_pipelines (
  pipeline_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  manifest JSONB NOT NULL,                 -- {nodes:[{id,kind,props,inputs}], edges:[]}
  cadence TEXT,                            -- 'on_demand'|'hourly'|'daily'|'weekly' (future-proof)
  enabled BOOLEAN DEFAULT TRUE,
  created_by TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  last_run_at TIMESTAMPTZ,
  last_run_ok BOOLEAN,
  tenant_id UUID DEFAULT '00000000-0000-0000-0000-000000000001'
);
CREATE INDEX IF NOT EXISTS idx_pipelines_recent ON data_pipelines(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipelines_enabled ON data_pipelines(enabled, cadence);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_id UUID NOT NULL REFERENCES data_pipelines(pipeline_id) ON DELETE CASCADE,
  started_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  ok BOOLEAN,
  rows_processed BIGINT DEFAULT 0,
  duration_ms INT,
  error TEXT,
  triggered_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_pipe_runs_pipe ON pipeline_runs(pipeline_id, started_at DESC);

CREATE TABLE IF NOT EXISTS pipeline_node_runs (
  id BIGSERIAL PRIMARY KEY,
  run_id UUID NOT NULL REFERENCES pipeline_runs(run_id) ON DELETE CASCADE,
  node_id TEXT NOT NULL,
  node_kind TEXT NOT NULL,
  started_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  ok BOOLEAN,
  rows_in BIGINT DEFAULT 0,
  rows_out BIGINT DEFAULT 0,
  duration_ms INT,
  error TEXT,
  result_summary JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_pnr_run ON pipeline_node_runs(run_id);

-- Auto-touch updated_at
CREATE OR REPLACE FUNCTION _touch_data_pipelines() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_pipelines_touch ON data_pipelines;
CREATE TRIGGER trg_pipelines_touch
  BEFORE UPDATE ON data_pipelines
  FOR EACH ROW EXECUTE FUNCTION _touch_data_pipelines();

COMMIT;
