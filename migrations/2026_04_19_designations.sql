-- ============================================================================
-- 2026_04_19_designations.sql
-- Protected-designation tables + connectors registry for the Princeps
-- Connector framework (BOT-G).
--
-- Every UK energy developer needs binary can/can't-build flags. These tables
-- hold the authoritative polygons for the nine designations that drive
-- planning risk:
--   * AONB (Areas of Outstanding Natural Beauty / National Landscapes)
--   * SSSI (Sites of Special Scientific Interest)
--   * SPA  (Special Protection Areas — Birds Directive)
--   * SAC  (Special Areas of Conservation — Habitats Directive)
--   * Ramsar (Wetlands of International Importance)
--   * Green Belt (MHCLG Local Authority Green Belt)
--   * Flood Zones (EA Flood Map for Planning — zones 1/2/3a/3b)
--   * Priority Habitats (NE Priority Habitat Inventory)
--   * ALC Grade (NE Agricultural Land Classification Post-1988)
--
-- Canonical SRID: 27700 (British National Grid). Incoming WGS84 geometry is
-- reprojected on insert via ST_Transform.
--
-- All CREATEs use IF NOT EXISTS so the migration is idempotent; GiST indexes
-- are created with IF NOT EXISTS too.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------------------
-- Connector registry
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS connectors_registry (
    source_name             text PRIMARY KEY,
    schedule                text NOT NULL,              -- cron expression
    schema_hash             text,                       -- stable hash of output schema
    last_attempted_utc      timestamptz,
    last_successful_utc     timestamptz,
    last_status             text,                       -- green|amber|red
    last_message            text,
    rows_total              bigint DEFAULT 0,
    rows_upserted_last_run  bigint DEFAULT 0,
    next_cursor             text,                       -- opaque resume token
    created_at              timestamptz DEFAULT now(),
    updated_at              timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_connectors_registry_status
    ON connectors_registry (last_status);

-- ---------------------------------------------------------------------------
-- Shared schema for designation tables
--   feature_id      - stable source identifier (upsert key)
--   source_ref      - human-readable source URL/slug for debugging
--   name            - site name (e.g. "The Broads", "Arnside & Silverdale")
--   reference       - official designation reference
--   properties      - full source properties as JSONB
--   geom            - geometry(MULTIPOLYGON, 27700)
--   ingested_at     - last upsert timestamp
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS designations_aonb (
    feature_id      text PRIMARY KEY,
    source_ref      text,
    name            text,
    reference       text,
    properties      jsonb,
    geom            geometry(MultiPolygon, 27700),
    ingested_at     timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_designations_aonb_geom ON designations_aonb USING GIST (geom);

CREATE TABLE IF NOT EXISTS designations_sssi (
    feature_id      text PRIMARY KEY,
    source_ref      text,
    name            text,
    reference       text,
    properties      jsonb,
    geom            geometry(MultiPolygon, 27700),
    ingested_at     timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_designations_sssi_geom ON designations_sssi USING GIST (geom);

CREATE TABLE IF NOT EXISTS designations_spa (
    feature_id      text PRIMARY KEY,
    source_ref      text,
    name            text,
    reference       text,
    properties      jsonb,
    geom            geometry(MultiPolygon, 27700),
    ingested_at     timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_designations_spa_geom ON designations_spa USING GIST (geom);

CREATE TABLE IF NOT EXISTS designations_sac (
    feature_id      text PRIMARY KEY,
    source_ref      text,
    name            text,
    reference       text,
    properties      jsonb,
    geom            geometry(MultiPolygon, 27700),
    ingested_at     timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_designations_sac_geom ON designations_sac USING GIST (geom);

CREATE TABLE IF NOT EXISTS designations_ramsar (
    feature_id      text PRIMARY KEY,
    source_ref      text,
    name            text,
    reference       text,
    properties      jsonb,
    geom            geometry(MultiPolygon, 27700),
    ingested_at     timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_designations_ramsar_geom ON designations_ramsar USING GIST (geom);

CREATE TABLE IF NOT EXISTS designations_green_belt (
    feature_id      text PRIMARY KEY,
    source_ref      text,
    name            text,
    reference       text,
    local_authority text,
    properties      jsonb,
    geom            geometry(MultiPolygon, 27700),
    ingested_at     timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_designations_green_belt_geom
    ON designations_green_belt USING GIST (geom);
CREATE INDEX IF NOT EXISTS ix_designations_green_belt_la
    ON designations_green_belt (local_authority);

CREATE TABLE IF NOT EXISTS designations_flood_zones (
    feature_id      text PRIMARY KEY,
    source_ref      text,
    name            text,
    reference       text,
    flood_zone      text,        -- '1' | '2' | '3' | '3a' | '3b'
    flood_risk_type text,        -- 'Tidal Models' | 'Fluvial Models' | ...
    properties      jsonb,
    geom            geometry(MultiPolygon, 27700),
    ingested_at     timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_designations_flood_zones_geom
    ON designations_flood_zones USING GIST (geom);
CREATE INDEX IF NOT EXISTS ix_designations_flood_zones_zone
    ON designations_flood_zones (flood_zone);

CREATE TABLE IF NOT EXISTS designations_priority_habitats (
    feature_id      text PRIMARY KEY,
    source_ref      text,
    name            text,
    reference       text,
    main_habit      text,        -- main habitat type (NE PHI "Main_Habit")
    properties      jsonb,
    geom            geometry(MultiPolygon, 27700),
    ingested_at     timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_designations_priority_habitats_geom
    ON designations_priority_habitats USING GIST (geom);
CREATE INDEX IF NOT EXISTS ix_designations_priority_habitats_main
    ON designations_priority_habitats (main_habit);

CREATE TABLE IF NOT EXISTS designations_alc_grade (
    feature_id      text PRIMARY KEY,
    source_ref      text,
    name            text,
    reference       text,
    alc_grade       text,        -- '1' | '2' | '3a' | '3b' | '4' | '5' | 'Urban' | 'Non-agricultural'
    area_ha         double precision,
    properties      jsonb,
    geom            geometry(MultiPolygon, 27700),
    ingested_at     timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_designations_alc_grade_geom
    ON designations_alc_grade USING GIST (geom);
CREATE INDEX IF NOT EXISTS ix_designations_alc_grade_grade
    ON designations_alc_grade (alc_grade);
