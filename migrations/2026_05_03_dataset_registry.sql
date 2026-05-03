-- 2026_05_03_dataset_registry.sql
-- Princeps Magritte connector framework — dataset registry, lineage, and
-- per-refresh log. Idempotent: every CREATE is IF NOT EXISTS so this can
-- run repeatedly on the same database without error.
--
-- Used by app/connectors/{base,health,registry,startup}.py and the
-- /api/datasets router. The two other agents (CCOD, BMRS, NSIP/DCO,
-- ENTSO-E, HSE) write into princeps_datasets through Connector.ingest()
-- — they should not need to touch the schema directly.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS princeps_datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT UNIQUE NOT NULL,                       -- e.g. 'hm_land_registry_ccod'
    title TEXT NOT NULL,                             -- 'HM Land Registry — Corporate Ownership'
    source_url TEXT,                                 -- canonical upstream URL
    license TEXT,                                    -- 'OGL-3.0', 'CC-BY-4.0', 'NC' (blocked)
    refresh_cadence TEXT,                            -- 'daily' | 'monthly' | 'on_demand'
    table_name TEXT NOT NULL,                        -- destination table name
    schema_version INT DEFAULT 1,
    last_refreshed_at TIMESTAMPTZ,
    last_refresh_ok BOOL,
    last_refresh_error TEXT,
    last_row_count BIGINT,
    freshness_threshold_hours INT DEFAULT 168,       -- default = 7 d
    health_status TEXT DEFAULT 'unknown',            -- 'green'|'yellow'|'red'|'unknown'
    health_checked_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb,
    tenant_id UUID DEFAULT '00000000-0000-0000-0000-000000000001',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dataset_lineage (
    id BIGSERIAL PRIMARY KEY,
    upstream_slug TEXT NOT NULL,
    downstream_slug TEXT NOT NULL,
    relationship TEXT DEFAULT 'derives_from',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (upstream_slug, downstream_slug, relationship)
);

CREATE TABLE IF NOT EXISTS dataset_refresh_log (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    ok BOOL,
    rows_ingested BIGINT,
    rows_total BIGINT,
    error TEXT,
    duration_ms INT
);

CREATE INDEX IF NOT EXISTS idx_dataset_refresh_log_slug
    ON dataset_refresh_log (slug, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_princeps_datasets_health
    ON princeps_datasets (health_status);

CREATE INDEX IF NOT EXISTS idx_dataset_lineage_upstream
    ON dataset_lineage (upstream_slug);

CREATE INDEX IF NOT EXISTS idx_dataset_lineage_downstream
    ON dataset_lineage (downstream_slug);
