-- migrate_agent_tables.sql
-- Tables for Princeps runtime agent bots (ProspectorAgent, GridMonitorAgent, etc.)
-- Idempotent — safe to re-run.

-- ── Agent run log (all bots write here on success or failure) ───────────────
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id           text PRIMARY KEY,
    agent_name       text NOT NULL,
    ok               boolean NOT NULL,
    summary          text,
    data             jsonb,
    cost_gbp         numeric(10, 4) DEFAULT 0,
    tokens_in        integer DEFAULT 0,
    tokens_out       integer DEFAULT 0,
    duration_s       numeric(10, 2) DEFAULT 0,
    started_at       timestamptz NOT NULL DEFAULT now(),
    recorded_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_runs_agent_started
    ON agent_runs (agent_name, started_at DESC);
CREATE INDEX IF NOT EXISTS agent_runs_monthly_cost
    ON agent_runs (agent_name, started_at)
    WHERE ok = true;

-- ── Agent failure detail (exceptions) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_failures (
    id               bigserial PRIMARY KEY,
    run_id           text NOT NULL,
    agent_name       text NOT NULL,
    error_type       text,
    error_message    text,
    failed_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_failures_agent_time
    ON agent_failures (agent_name, failed_at DESC);

-- ── Prospect parcels (source pool — populated by data pipeline) ─────────────
-- Placeholder; real schema joins land parcels, grid distance, planning flags.
CREATE TABLE IF NOT EXISTS prospect_parcels (
    id                text PRIMARY KEY,
    name              text NOT NULL,
    region            text NOT NULL,
    geom              geometry(Polygon, 27700),
    area_ha           numeric(10, 2),
    estimated_mw      numeric(10, 2),
    grid_distance_km  numeric(10, 2),
    alc_grade         text,
    planning_flags    text[] DEFAULT ARRAY[]::text[],
    tech_suitable     text[] DEFAULT ARRAY[]::text[],
    status            text NOT NULL DEFAULT 'active',
    source            text,
    ingested_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS prospect_parcels_region
    ON prospect_parcels (region, status);
CREATE INDEX IF NOT EXISTS prospect_parcels_geom
    ON prospect_parcels USING GIST (geom);

-- ── Prospect candidates (ProspectorAgent output per user) ───────────────────
CREATE TABLE IF NOT EXISTS prospect_candidates (
    id               bigserial PRIMARY KEY,
    user_id          uuid,
    parcel_id        text NOT NULL REFERENCES prospect_parcels(id) ON DELETE CASCADE,
    tech             text NOT NULL,
    score            integer NOT NULL CHECK (score BETWEEN 0 AND 100),
    verdict          text NOT NULL CHECK (verdict IN ('GO', 'CAUTION', 'NO-GO')),
    reasoning        text,
    flags            jsonb DEFAULT '[]'::jsonb,
    data             jsonb DEFAULT '{}'::jsonb,
    found_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, parcel_id, tech)
);
CREATE INDEX IF NOT EXISTS prospect_candidates_user_score
    ON prospect_candidates (user_id, score DESC, found_at DESC);
CREATE INDEX IF NOT EXISTS prospect_candidates_verdict
    ON prospect_candidates (verdict, found_at DESC);

-- ── Competitor signals (CompetitorRnDAgent scout output) ────────────────────
CREATE TABLE IF NOT EXISTS competitor_signals (
    id               bigserial PRIMARY KEY,
    competitor       text NOT NULL,
    signal_type      text NOT NULL,   -- feature, hire, customer, pricing, press
    title            text NOT NULL,
    summary          text,
    source_url       text,
    source_fetched_at timestamptz,
    signal_date      date,
    raw              jsonb,
    ingested_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS competitor_signals_competitor_date
    ON competitor_signals (competitor, signal_date DESC);
CREATE INDEX IF NOT EXISTS competitor_signals_type_time
    ON competitor_signals (signal_type, ingested_at DESC);

-- ── Upgrade proposals (CompetitorRnDAgent R&D mode output) ──────────────────
CREATE TABLE IF NOT EXISTS upgrade_proposals (
    id               bigserial PRIMARY KEY,
    title            text NOT NULL,
    motivation       text,                -- why (competitor X shipped Y; users asked; etc.)
    proposal         text,                -- what (design sketch)
    risk_notes       text,
    effort_estimate  text,                -- S / M / L / XL
    related_signals  bigint[],            -- FK-ish to competitor_signals.id
    pr_url           text,                -- draft PR link if one was opened
    status           text NOT NULL DEFAULT 'draft' CHECK (
        status IN ('draft', 'proposed', 'accepted', 'rejected', 'shipped')
    ),
    proposed_at      timestamptz NOT NULL DEFAULT now(),
    decided_at       timestamptz,
    decided_by       text
);
CREATE INDEX IF NOT EXISTS upgrade_proposals_status
    ON upgrade_proposals (status, proposed_at DESC);

-- ── Grid alerts (GridMonitorAgent output) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_alerts (
    id               bigserial PRIMARY KEY,
    substation_id    text,
    severity         text NOT NULL CHECK (severity IN ('info', 'watch', 'critical')),
    headline         text,
    action           text,
    data             jsonb DEFAULT '{}'::jsonb,
    raised_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS grid_alerts_severity_time
    ON grid_alerts (severity, raised_at DESC);

-- ── Procurement tenders (raw feed + classified) ─────────────────────────────
CREATE TABLE IF NOT EXISTS procurement_tenders_raw (
    tender_id        text PRIMARY KEY,
    title            text NOT NULL,
    abstract         text,
    buyer            text,
    closing_date     date,
    url              text,
    published_at     timestamptz NOT NULL DEFAULT now(),
    -- Classified by ProcurementAgent
    tech             text,
    capacity_mw      numeric(10, 2),
    budget_gbp       bigint,
    scope            text,
    bid_viability    integer,
    reasoning        text,
    classified_at    timestamptz
);
CREATE INDEX IF NOT EXISTS procurement_tenders_raw_published
    ON procurement_tenders_raw (published_at DESC);
CREATE INDEX IF NOT EXISTS procurement_tenders_raw_unclassified
    ON procurement_tenders_raw (published_at DESC)
    WHERE classified_at IS NULL;

-- ── Ingestion log (IngestionAgent) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ingestion_log (
    id               bigserial PRIMARY KEY,
    source           text NOT NULL,
    rows_ingested    integer,
    rows_updated     integer,
    anomalies        jsonb DEFAULT '[]'::jsonb,
    started_at       timestamptz NOT NULL,
    finished_at      timestamptz NOT NULL DEFAULT now(),
    ok               boolean NOT NULL DEFAULT true,
    notes            text
);
CREATE INDEX IF NOT EXISTS ingestion_log_source_time
    ON ingestion_log (source, finished_at DESC);

-- ── Agent budget view — live spend per bot (day + month) ────────────────────
-- Safe to re-create; uses CREATE OR REPLACE.
CREATE OR REPLACE VIEW agent_budgets AS
SELECT
    agent_name,
    COUNT(*)                                                           AS runs_total,
    COUNT(*) FILTER (WHERE ok = false)                                 AS runs_failed,
    COUNT(*) FILTER (WHERE started_at > date_trunc('day', now()))      AS runs_today,
    COALESCE(SUM(cost_gbp) FILTER
        (WHERE started_at > date_trunc('day', now())), 0)::numeric(10,4) AS spent_gbp_today,
    COALESCE(SUM(cost_gbp) FILTER
        (WHERE started_at > date_trunc('month', now())), 0)::numeric(10,4) AS spent_gbp_month,
    COALESCE(SUM(tokens_in), 0)                                        AS total_tokens_in,
    COALESCE(SUM(tokens_out), 0)                                       AS total_tokens_out,
    MAX(started_at)                                                    AS last_run_at
FROM agent_runs
GROUP BY agent_name
ORDER BY agent_name;
