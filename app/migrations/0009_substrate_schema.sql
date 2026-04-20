-- =============================================================================
-- 0009_substrate_schema.sql
-- -----------------------------------------------------------------------------
-- Princeps BOT-CC — Precision Map Substrate
--
-- Tables for OS MasterMap Topography, EA National LiDAR Programme (DTM/DSM)
-- metadata, and OSM pylons / overhead lines. All geometry columns stored in
-- SRID 27700 (OSGB British National Grid) to match the rest of the Princeps
-- spatial stack. Materialised views per MVT layer are rebuilt nightly by the
-- tiler.
--
-- Idempotent: safe to re-run. Fully guarded CREATE TABLE/INDEX/MATERIALIZED
-- VIEW IF NOT EXISTS. Applied on startup by app/db_setup.py.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;


-- ── OS MasterMap: Buildings ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS substrate_buildings (
    id              bigserial PRIMARY KEY,
    toid            text,                -- OS TOID, unique per feature
    tile_id         text,                -- OSGB 10 km tile (e.g. 'TQ28')
    feature_class   text,                -- 'Building' | 'Structure' | 'Roof'
    use_class       text,                -- residential/commercial/industrial
    height_m        double precision,    -- top-of-roof if available
    theme           text,
    attrs           jsonb DEFAULT '{}'::jsonb,
    geom            geometry(MultiPolygon, 27700) NOT NULL,
    fetched_at      timestamptz DEFAULT now(),
    UNIQUE (toid)
);
CREATE INDEX IF NOT EXISTS idx_substrate_buildings_geom
    ON substrate_buildings USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_substrate_buildings_tile
    ON substrate_buildings (tile_id);


-- ── OS MasterMap: Roads ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS substrate_roads (
    id              bigserial PRIMARY KEY,
    toid            text,
    tile_id         text,
    road_class      text,                -- motorway / a_road / b_road / minor / local
    name            text,
    designation     text,
    form_of_way     text,
    attrs           jsonb DEFAULT '{}'::jsonb,
    geom            geometry(MultiLineString, 27700) NOT NULL,
    fetched_at      timestamptz DEFAULT now(),
    UNIQUE (toid)
);
CREATE INDEX IF NOT EXISTS idx_substrate_roads_geom
    ON substrate_roads USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_substrate_roads_tile
    ON substrate_roads (tile_id);
CREATE INDEX IF NOT EXISTS idx_substrate_roads_class
    ON substrate_roads (road_class);


-- ── OS MasterMap: Water ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS substrate_water (
    id              bigserial PRIMARY KEY,
    toid            text,
    tile_id         text,
    feature_type    text,                -- river / lake / reservoir / canal / stream
    name            text,
    attrs           jsonb DEFAULT '{}'::jsonb,
    geom            geometry(Geometry, 27700) NOT NULL,   -- polygon or line
    fetched_at      timestamptz DEFAULT now(),
    UNIQUE (toid)
);
CREATE INDEX IF NOT EXISTS idx_substrate_water_geom
    ON substrate_water USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_substrate_water_tile
    ON substrate_water (tile_id);


-- ── OS MasterMap: Woodland / Trees ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS substrate_woodland (
    id              bigserial PRIMARY KEY,
    toid            text,
    tile_id         text,
    feature_type    text,                -- woodland / coniferous / deciduous / mixed
    attrs           jsonb DEFAULT '{}'::jsonb,
    geom            geometry(MultiPolygon, 27700) NOT NULL,
    fetched_at      timestamptz DEFAULT now(),
    UNIQUE (toid)
);
CREATE INDEX IF NOT EXISTS idx_substrate_woodland_geom
    ON substrate_woodland USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_substrate_woodland_tile
    ON substrate_woodland (tile_id);


-- ── EA LiDAR tile metadata (rasters live on disk) ───────────────────────────
CREATE TABLE IF NOT EXISTS substrate_lidar_tiles (
    tile_id         text PRIMARY KEY,                 -- OSGB 1km grid ref (e.g. 'TQ2580')
    bbox            geometry(Polygon, 27700) NOT NULL,
    dtm_path        text,                             -- absolute path to DTM GeoTIFF
    dsm_path        text,                             -- absolute path to DSM GeoTIFF
    resolution_m    double precision DEFAULT 1.0,
    product_year    integer,
    size_bytes      bigint,
    source          text DEFAULT 'ea_nlp',            -- EA National LiDAR Programme
    fetched_at      timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_substrate_lidar_tiles_bbox
    ON substrate_lidar_tiles USING GIST (bbox);


-- ── OSM: Pylons / Poles ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS substrate_pylons (
    id              bigserial PRIMARY KEY,
    osm_id          bigint,
    osm_type        text,                -- 'tower' | 'pole'
    voltage_kv      double precision,
    operator        text,
    height_m        double precision,
    material        text,
    attrs           jsonb DEFAULT '{}'::jsonb,
    geom            geometry(Point, 27700) NOT NULL,
    fetched_at      timestamptz DEFAULT now(),
    UNIQUE (osm_type, osm_id)
);
CREATE INDEX IF NOT EXISTS idx_substrate_pylons_geom
    ON substrate_pylons USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_substrate_pylons_voltage
    ON substrate_pylons (voltage_kv);


-- ── OSM: Overhead lines ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS substrate_overhead_lines (
    id              bigserial PRIMARY KEY,
    osm_id          bigint,
    osm_type        text,                -- 'line' | 'minor_line'
    voltage_kv      double precision,
    operator        text,
    circuits        integer,
    cables          integer,
    frequency_hz    double precision,
    attrs           jsonb DEFAULT '{}'::jsonb,
    geom            geometry(MultiLineString, 27700) NOT NULL,
    fetched_at      timestamptz DEFAULT now(),
    UNIQUE (osm_type, osm_id)
);
CREATE INDEX IF NOT EXISTS idx_substrate_overhead_lines_geom
    ON substrate_overhead_lines USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_substrate_overhead_lines_voltage
    ON substrate_overhead_lines (voltage_kv);


-- ── Materialised views for MVT tiler ────────────────────────────────────────
-- MVT generation happens per-request via ST_AsMVT; the MVs here project the
-- geometries into Web Mercator (EPSG:3857) and pre-select the display
-- attribute set. Rebuilt nightly by tiler.refresh_materialized_views().

CREATE MATERIALIZED VIEW IF NOT EXISTS substrate_mv_buildings AS
    SELECT id, toid, feature_class, use_class, height_m,
           ST_Transform(geom, 3857) AS geom_3857
    FROM substrate_buildings;
CREATE INDEX IF NOT EXISTS idx_substrate_mv_buildings_geom
    ON substrate_mv_buildings USING GIST (geom_3857);

CREATE MATERIALIZED VIEW IF NOT EXISTS substrate_mv_roads AS
    SELECT id, toid, road_class, name, form_of_way,
           ST_Transform(geom, 3857) AS geom_3857
    FROM substrate_roads;
CREATE INDEX IF NOT EXISTS idx_substrate_mv_roads_geom
    ON substrate_mv_roads USING GIST (geom_3857);

CREATE MATERIALIZED VIEW IF NOT EXISTS substrate_mv_water AS
    SELECT id, toid, feature_type, name,
           ST_Transform(geom, 3857) AS geom_3857
    FROM substrate_water;
CREATE INDEX IF NOT EXISTS idx_substrate_mv_water_geom
    ON substrate_mv_water USING GIST (geom_3857);

CREATE MATERIALIZED VIEW IF NOT EXISTS substrate_mv_woodland AS
    SELECT id, toid, feature_type,
           ST_Transform(geom, 3857) AS geom_3857
    FROM substrate_woodland;
CREATE INDEX IF NOT EXISTS idx_substrate_mv_woodland_geom
    ON substrate_mv_woodland USING GIST (geom_3857);

CREATE MATERIALIZED VIEW IF NOT EXISTS substrate_mv_pylons AS
    SELECT id, osm_id, osm_type, voltage_kv, operator, height_m,
           ST_Transform(geom, 3857) AS geom_3857
    FROM substrate_pylons;
CREATE INDEX IF NOT EXISTS idx_substrate_mv_pylons_geom
    ON substrate_mv_pylons USING GIST (geom_3857);

CREATE MATERIALIZED VIEW IF NOT EXISTS substrate_mv_overhead_lines AS
    SELECT id, osm_id, osm_type, voltage_kv, operator, circuits,
           ST_Transform(geom, 3857) AS geom_3857
    FROM substrate_overhead_lines;
CREATE INDEX IF NOT EXISTS idx_substrate_mv_overhead_lines_geom
    ON substrate_mv_overhead_lines USING GIST (geom_3857);
