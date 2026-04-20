-- ============================================================================
-- 2026_04_20_utility_layers.sql
-- Utility context layers for the DC site twin — replaces BOT-DU's Overpass
-- browser fallbacks with proper server-side spatial tables.
--
-- Tables:
--   * utility_waterways      — OSM waterway=river|canal|stream lines
--   * utility_roads          — OSM highway=primary..service classified
--   * utility_gas_pipelines  — OSM man_made=pipeline + substance=gas
--   * fibre_pops             — carrier POP / exchange seed (Openreach +
--                              peering nodes). Static seed; no OSM.
--
-- All tables use SRID 27700 and carry a GiST index on the geom column so
-- /api/utilities/* bbox queries stay sub-second.
--
-- Fully idempotent (CREATE TABLE/INDEX IF NOT EXISTS). Re-running is safe.
-- ============================================================================

BEGIN;

-- ─── Waterways ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS utility_waterways (
    id           SERIAL PRIMARY KEY,
    osm_id       BIGINT,
    name         TEXT,
    waterway     TEXT,           -- river | canal | stream
    width_m      DOUBLE PRECISION,
    intermittent BOOLEAN,
    geom         GEOMETRY(LineString, 27700),
    tags         JSONB DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT utility_waterways_osm_unique UNIQUE (osm_id)
);
CREATE INDEX IF NOT EXISTS idx_utility_waterways_geom
    ON utility_waterways USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_utility_waterways_type
    ON utility_waterways (waterway);

-- ─── Roads ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS utility_roads (
    id           SERIAL PRIMARY KEY,
    osm_id       BIGINT,
    name         TEXT,
    ref          TEXT,
    highway      TEXT,           -- primary | secondary | tertiary | service | unclassified | residential
    access_class TEXT,           -- strategic | local | site (derived)
    surface      TEXT,
    maxspeed     TEXT,
    geom         GEOMETRY(LineString, 27700),
    tags         JSONB DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT utility_roads_osm_unique UNIQUE (osm_id)
);
CREATE INDEX IF NOT EXISTS idx_utility_roads_geom
    ON utility_roads USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_utility_roads_access
    ON utility_roads (access_class);
CREATE INDEX IF NOT EXISTS idx_utility_roads_highway
    ON utility_roads (highway);

-- ─── Gas pipelines ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS utility_gas_pipelines (
    id           SERIAL PRIMARY KEY,
    osm_id       BIGINT,
    name         TEXT,
    operator     TEXT,
    substance    TEXT DEFAULT 'gas',
    pressure     TEXT,
    diameter_mm  DOUBLE PRECISION,
    location     TEXT,          -- overground | underground
    geom         GEOMETRY(LineString, 27700),
    tags         JSONB DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT utility_gas_pipelines_osm_unique UNIQUE (osm_id)
);
CREATE INDEX IF NOT EXISTS idx_utility_gas_pipelines_geom
    ON utility_gas_pipelines USING GIST (geom);

-- ─── Fibre carrier POPs ─────────────────────────────────────────────────────
-- Seeded from a hand-curated list of Openreach exchanges (handful of majors)
-- + LINX / LoNAP / IXScotland peering nodes. Not an exhaustive carrier map —
-- the full public register is not freely available, so this is a deliberate
-- best-effort seed. See utils/utility_ingesters/fibre_pop.py for sources.
CREATE TABLE IF NOT EXISTS fibre_pops (
    id           SERIAL PRIMARY KEY,
    external_id  TEXT UNIQUE,    -- e.g. 'openreach:LDNBX', 'linx:main-site'
    name         TEXT NOT NULL,
    carrier      TEXT,           -- openreach | linx | lonap | ixscotland | neos | zayo | other
    pop_class    TEXT,           -- core | exchange | pop | ix | cls (cable-landing-station)
    address      TEXT,
    city         TEXT,
    lat          DOUBLE PRECISION NOT NULL,
    lon          DOUBLE PRECISION NOT NULL,
    geom         GEOMETRY(Point, 27700),
    source       TEXT,           -- 'seed:openreach-majors' | 'seed:linx' | ...
    notes        TEXT,
    tags         JSONB DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fibre_pops_geom
    ON fibre_pops USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_fibre_pops_carrier
    ON fibre_pops (carrier);

COMMIT;
