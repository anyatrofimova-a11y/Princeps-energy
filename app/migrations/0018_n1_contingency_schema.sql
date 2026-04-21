-- =============================================================================
-- 0018_n1_contingency_schema.sql
-- -----------------------------------------------------------------------------
-- Princeps — UK N-1 Contingency Map (crown-jewel manufactured dataset).
--
-- One row per primary substation in GB. Columns match the Pydantic
-- `utils.n1_contingency.schema.N1Contingency` record; the per-outage event
-- list is stored as JSONB on the `events` column.
--
-- Geometry is stored as `geography(Point, 4326)` to match the rest of the
-- map-facing Princeps tables (GeoJSON endpoints need WGS84). The source
-- substation geometry in `grid_substations` is SRID 27700 — the batch
-- runner re-projects to 4326 before upsert.
--
-- Idempotent. Applied by `app/db_setup.py` on startup via the migrations
-- loader. Marker table: `n1_contingency_map`.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- ── n1_contingency_map ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS n1_contingency_map (
    substation_id             uuid PRIMARY KEY,                 -- UUID5 of grid_substations.id
    substation_name           text NOT NULL,
    voltage_kv                numeric(8,2),
    dno                       text,                              -- ukpn/ssen/spen/nged/npg/enwl
    worst_case_overload_pct   numeric(6,2) DEFAULT 0,            -- >100 = overload under worst credible N-1
    worst_case_affected_mw    numeric(10,2) DEFAULT 0,           -- downstream MW at risk of shedding
    reliability_score         numeric(5,2),                      -- 0-100; 100 = fully N-1 secure
    events                    jsonb DEFAULT '[]'::jsonb,         -- list[N1Event]
    last_computed_at          timestamptz DEFAULT now(),
    model_version             text DEFAULT 'v1.0.0',
    upstream_assets_scanned   int DEFAULT 0,
    failed_outages            int DEFAULT 0,
    notes                     jsonb DEFAULT '[]'::jsonb,
    geometry                  geography(Point, 4326),
    created_at                timestamptz DEFAULT now(),
    updated_at                timestamptz DEFAULT now()
);


-- Fast ranked lookups ("show me the 50 weakest 132 kV primaries") —
-- composite on voltage + descending reliability underpins the
-- /api/n1/worst-cases endpoint.
CREATE INDEX IF NOT EXISTS idx_n1_voltage_score
    ON n1_contingency_map (voltage_kv, reliability_score DESC);

-- Map bbox queries hit geometry first, then filter by score threshold.
CREATE INDEX IF NOT EXISTS idx_n1_geom
    ON n1_contingency_map USING GIST (geometry);

-- Faceted filters from the Datasets UI.
CREATE INDEX IF NOT EXISTS idx_n1_dno
    ON n1_contingency_map (dno);
CREATE INDEX IF NOT EXISTS idx_n1_score_desc
    ON n1_contingency_map (reliability_score DESC);


-- ── n1_contingency_runs (audit log of batch runs) ──────────────────────────
-- Each weekly / on-demand batch invocation writes one row here so operators
-- can see when the map was last refreshed, how long it took, and whether
-- any substations failed.
CREATE TABLE IF NOT EXISTS n1_contingency_runs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dno_filter       text,
    limit_applied    int,
    workers          int,
    model_version    text,
    target_count     int,
    upserted         int,
    failed           int,
    not_found        int,
    started_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz,
    elapsed_sec      numeric(10,1),
    errors           jsonb DEFAULT '[]'::jsonb,
    trigger          text DEFAULT 'scheduled'         -- scheduled | manual | on_demand
);
CREATE INDEX IF NOT EXISTS idx_n1_runs_started
    ON n1_contingency_runs (started_at DESC);
