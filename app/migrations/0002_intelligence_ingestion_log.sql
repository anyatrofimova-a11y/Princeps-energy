-- =============================================================================
-- 0002_intelligence_ingestion_log.sql
-- -----------------------------------------------------------------------------
-- Princeps Phase 7a — ingestion-run log for Intelligence workers.
--
-- Distinct from the existing `grid_ingestion_log` (DNO / OSM / TEC pipeline)
-- so the Intelligence workers can evolve their schema independently. Every
-- invocation of an IngestionWorker writes one row.
--
-- Idempotent: safe to re-run.
-- Applied on startup alongside 0001_intelligence_schema.sql.
-- =============================================================================

CREATE TABLE IF NOT EXISTS intelligence_ingestion_log (
    id              SERIAL PRIMARY KEY,
    source          TEXT NOT NULL,            -- ofgem | neso_tec | pins_nsip | planit_lpa | desnz | bmrs | hse_comah | companies_house | find_a_tender
    run_id          TEXT,                     -- optional correlation key (uuid / cron id)
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running','ok','partial','failed')),
    rows_fetched    INTEGER DEFAULT 0,
    rows_inserted   INTEGER DEFAULT 0,
    rows_updated    INTEGER DEFAULT 0,
    rows_failed     INTEGER DEFAULT 0,
    tokens_in       INTEGER DEFAULT 0,
    tokens_out      INTEGER DEFAULT 0,
    cost_gbp        NUMERIC(10,4) DEFAULT 0,
    error_message   TEXT,
    metadata        JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_intel_ingest_source_started
    ON intelligence_ingestion_log (source, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_intel_ingest_status
    ON intelligence_ingestion_log (status, started_at DESC);
