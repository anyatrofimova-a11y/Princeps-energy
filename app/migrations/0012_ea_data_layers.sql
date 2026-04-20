-- =============================================================================
-- 0012_ea_data_layers.sql
-- -----------------------------------------------------------------------------
-- Princeps BOT-EA — Environment Agency flagship datasets
--
--   * Flood Map for Planning (Zones 2 + 3 + climate-change overlay)
--       https://environment.data.gov.uk/
--       WFS  https://environment.data.gov.uk/spatialdata/flood-map-for-planning-rivers-and-sea-flood-zone-{2|3}/wfs
--       WMTS https://environment.data.gov.uk/spatialdata/.../wmts
--       OGL v3 — free, attribution required.
--
--   * National LiDAR Programme 1 m DTM + DSM
--       Table already shipped in 0009_substrate_schema.sql as
--       ``substrate_lidar_tiles``. No DDL here — this migration only adds the
--       flood-zone tables + materialised-view refresh tags for the MVT tiler.
--
-- Idempotent: all CREATE … IF NOT EXISTS. Safe to re-run. Applied on startup
-- by app/db_setup.py.
--
-- SRID: 4326 (geography) to match magic_constraints and the site-enrichment
-- constraint probe in utils/site_enrichment/constraints.py which assumes a
-- ``geom`` column queryable via ``ST_MakePoint(lon, lat), 4326``.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;


-- ── EA Flood Map for Planning — Flood Zone 2 (low-medium probability) ─────
CREATE TABLE IF NOT EXISTS ea_flood_zone_2 (
    id                    bigserial PRIMARY KEY,
    feature_id            text,                         -- upstream OBJECTID / fid
    zone_class            text DEFAULT 'FZ2',           -- FZ2 | FZ2_CC (climate change)
    climate_scenario      text,                         -- 'baseline' | 'rcp45' | 'rcp85' | 'h++'
    source_updated_at     timestamptz,                  -- EA LastReviewed / SurveyDate
    area_ha               double precision,
    attrs                 jsonb DEFAULT '{}'::jsonb,
    geom                  geography(Geometry, 4326) NOT NULL,
    ingested_at           timestamptz DEFAULT now(),
    UNIQUE (feature_id, climate_scenario)
);
CREATE INDEX IF NOT EXISTS idx_ea_flood_zone_2_geom
    ON ea_flood_zone_2 USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_ea_flood_zone_2_scenario
    ON ea_flood_zone_2 (climate_scenario);


-- ── EA Flood Map for Planning — Flood Zone 3 (high probability) ───────────
CREATE TABLE IF NOT EXISTS ea_flood_zone_3 (
    id                    bigserial PRIMARY KEY,
    feature_id            text,
    zone_class            text DEFAULT 'FZ3',           -- FZ3 | FZ3a | FZ3b | FZ3_CC
    climate_scenario      text,
    source_updated_at     timestamptz,
    area_ha               double precision,
    attrs                 jsonb DEFAULT '{}'::jsonb,
    geom                  geography(Geometry, 4326) NOT NULL,
    ingested_at           timestamptz DEFAULT now(),
    UNIQUE (feature_id, climate_scenario)
);
CREATE INDEX IF NOT EXISTS idx_ea_flood_zone_3_geom
    ON ea_flood_zone_3 USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_ea_flood_zone_3_scenario
    ON ea_flood_zone_3 (climate_scenario);


-- ── Ingestion run ledger ──────────────────────────────────────────────────
-- Minimal audit trail so operators can see when an EA bbox was last fetched
-- and how many features came back. Separate from grid_ingestion_log so the
-- EA cadence can evolve independently.
CREATE TABLE IF NOT EXISTS ea_ingest_log (
    id                bigserial PRIMARY KEY,
    dataset           text NOT NULL,           -- 'flood_zone_2' | 'flood_zone_3' | 'lidar_1m'
    bbox_min_lon      double precision,
    bbox_min_lat      double precision,
    bbox_max_lon      double precision,
    bbox_max_lat      double precision,
    features_fetched  integer DEFAULT 0,
    features_upserted integer DEFAULT 0,
    bytes_downloaded  bigint DEFAULT 0,
    status            text DEFAULT 'ok',       -- ok | partial | error
    error_message     text,
    started_at        timestamptz DEFAULT now(),
    finished_at       timestamptz
);
CREATE INDEX IF NOT EXISTS idx_ea_ingest_log_dataset
    ON ea_ingest_log (dataset, started_at DESC);


-- ── Materialised views for MVT tiler (web-mercator projection) ────────────
-- Rebuilt on demand by app.routers.ea_layers.refresh_mvs(); project into 3857
-- so per-request MVT generation is a cheap ``&&`` spatial index probe.

CREATE MATERIALIZED VIEW IF NOT EXISTS ea_mv_flood_zone_2 AS
    SELECT id, feature_id, zone_class, climate_scenario, area_ha,
           ST_Transform(geom::geometry, 3857) AS geom_3857
    FROM ea_flood_zone_2;
CREATE INDEX IF NOT EXISTS idx_ea_mv_fz2_geom
    ON ea_mv_flood_zone_2 USING GIST (geom_3857);

CREATE MATERIALIZED VIEW IF NOT EXISTS ea_mv_flood_zone_3 AS
    SELECT id, feature_id, zone_class, climate_scenario, area_ha,
           ST_Transform(geom::geometry, 3857) AS geom_3857
    FROM ea_flood_zone_3;
CREATE INDEX IF NOT EXISTS idx_ea_mv_fz3_geom
    ON ea_mv_flood_zone_3 USING GIST (geom_3857);


-- ── MV refresh-tag ledger ─────────────────────────────────────────────────
-- Tracks the last REFRESH of each MV so the tiler can decide whether to
-- regenerate or serve cached tiles. One row per MV; upsert on refresh.
CREATE TABLE IF NOT EXISTS ea_mv_refresh_tags (
    mv_name        text PRIMARY KEY,
    last_refresh   timestamptz DEFAULT now(),
    row_count      bigint,
    status         text DEFAULT 'ok'
);
INSERT INTO ea_mv_refresh_tags (mv_name, last_refresh, row_count, status)
VALUES
    ('ea_mv_flood_zone_2', now(), 0, 'pending'),
    ('ea_mv_flood_zone_3', now(), 0, 'pending')
ON CONFLICT (mv_name) DO NOTHING;
