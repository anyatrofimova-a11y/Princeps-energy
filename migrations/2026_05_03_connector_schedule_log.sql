-- 2026_05_03_connector_schedule_log.sql
-- Princeps APScheduler-driven cadence orchestration for the Magritte
-- connector framework. Idempotent: every CREATE / ALTER is IF NOT EXISTS
-- so this can run repeatedly on the same database without error.
--
-- Used by app/cron/connector_scheduler.py to record every scheduled
-- run (vs dataset_refresh_log which is also written by manual API
-- /api/datasets/{slug}/refresh calls). Adds a schedule_disabled flag
-- to princeps_datasets so license-blocked connectors can be flipped
-- off without losing their registry row.

CREATE TABLE IF NOT EXISTS connector_schedule_log (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT NOT NULL,
    scheduled_at TIMESTAMPTZ NOT NULL,
    fired_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    ok BOOL,
    rows_ingested BIGINT,
    duration_ms INT,
    error TEXT,
    job_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_csl_slug_fired
    ON connector_schedule_log (slug, fired_at DESC);

ALTER TABLE princeps_datasets
    ADD COLUMN IF NOT EXISTS schedule_disabled BOOL DEFAULT FALSE;

ALTER TABLE princeps_datasets
    ADD COLUMN IF NOT EXISTS schedule_disabled_reason TEXT;

ALTER TABLE princeps_datasets
    ADD COLUMN IF NOT EXISTS next_fire_at TIMESTAMPTZ;
