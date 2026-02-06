-- Feasibly schema — requires PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;  -- required for slope raster queries

-- DNO substations (loaded via ogr2ogr from GeoJSON)
CREATE TABLE IF NOT EXISTS dno_substations (
    sub_id       TEXT PRIMARY KEY,
    name         TEXT,
    capacity_kw  NUMERIC,
    source       TEXT,
    geometry     geometry(Point, 27700)
);
CREATE INDEX IF NOT EXISTS idx_dno_sub_geom
    ON dno_substations USING GIST (geometry);

-- Candidate parcels
CREATE TABLE IF NOT EXISTS parcels (
    parcel_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source       TEXT,
    area_m2      NUMERIC,
    geometry     geometry(Polygon, 27700),
    centroid     geometry(Point, 27700),
    lpa_code     TEXT,
    -- populated by nearest-substation query
    nearest_substation_id  TEXT,
    distance_to_sub_km     NUMERIC,
    nearest_sub_capacity_kw NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_parcels_geom
    ON parcels USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_parcels_centroid
    ON parcels USING GIST (centroid);

-- Score history
CREATE TABLE IF NOT EXISTS site_scores (
    run_id           UUID DEFAULT gen_random_uuid(),
    parcel_id        UUID REFERENCES parcels(parcel_id),
    score_total      NUMERIC,
    score_components JSONB,
    passed_filters   BOOLEAN DEFAULT FALSE,
    created_at       TIMESTAMP DEFAULT now(),
    PRIMARY KEY (run_id, parcel_id)
);

-- Constraint overlays (AONB, SSSI, FloodZone, etc.)
-- Load via ogr2ogr with a layer_name column, or insert manually.
CREATE TABLE IF NOT EXISTS overlays (
    overlay_id   SERIAL PRIMARY KEY,
    layer_name   TEXT NOT NULL,       -- e.g. 'AONB', 'SSSI', 'FloodZone2', 'FloodZone3'
    name         TEXT,
    source       TEXT,
    geometry     geometry(Geometry, 27700)
);
CREATE INDEX IF NOT EXISTS idx_overlays_geom
    ON overlays USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_overlays_layer
    ON overlays (layer_name);

-- DEM elevation raster (source for slope computation)
-- Load with: raster2pgsql -s 27700 -I -C -M elevation.tif dem_elev | psql $DATABASE_URL
CREATE TABLE IF NOT EXISTS dem_elev (
    rid    SERIAL PRIMARY KEY,
    rast   raster
);
CREATE INDEX IF NOT EXISTS idx_dem_elev_rast
    ON dem_elev USING GIST (ST_ConvexHull(rast));

-- DEM slope raster (band 1 = slope in degrees, SRID 27700)
-- Generated from dem_elev via: psql -f sql/compute_slope.sql
-- Or loaded directly: raster2pgsql -s 27700 -I -C -M slope.tif dem_slope | psql $DATABASE_URL
CREATE TABLE IF NOT EXISTS dem_slope (
    rid    SERIAL PRIMARY KEY,
    rast   raster
);
CREATE INDEX IF NOT EXISTS idx_dem_slope_rast
    ON dem_slope USING GIST (ST_ConvexHull(rast));

-- ---------------------------------------------------------------------------
-- Network model (deferral analysis)
-- ---------------------------------------------------------------------------

-- Network nodes (buses)
CREATE TABLE IF NOT EXISTS network_nodes (
    node_id          TEXT PRIMARY KEY,
    geom             geometry(Point, 27700),
    current_load_mw  DOUBLE PRECISION DEFAULT 0,
    current_gen_mw   DOUBLE PRECISION DEFAULT 0,
    pf               DOUBLE PRECISION DEFAULT 0.98  -- assumed power factor
);
CREATE INDEX IF NOT EXISTS idx_network_nodes_geom
    ON network_nodes USING GIST (geom);

-- Network components (lines, transformers)
CREATE TABLE IF NOT EXISTS network_components (
    comp_id              TEXT PRIMARY KEY,
    from_node            TEXT REFERENCES network_nodes(node_id),
    to_node              TEXT REFERENCES network_nodes(node_id),
    asset_cost_gbp       DOUBLE PRECISION,       -- Asset_Cl
    capacity_mva         DOUBLE PRECISION,        -- Cap_l
    current_flow_mw      DOUBLE PRECISION,        -- D_l (absolute)
    reactive_flow_mvar   DOUBLE PRECISION DEFAULT 0,
    geometry             geometry(LineString, 27700)
);
CREATE INDEX IF NOT EXISTS idx_network_comp_geom
    ON network_components USING GIST (geometry);

-- DNO parameters / growth rates / discount rates
CREATE TABLE IF NOT EXISTS dno_params (
    id                SERIAL PRIMARY KEY,
    load_growth_pct   DOUBLE PRECISION DEFAULT 3.8,   -- load_r (%)
    dg_growth_pct     DOUBLE PRECISION DEFAULT 11.4,   -- DG_r (%)
    discount_rate_pct DOUBLE PRECISION DEFAULT 6.9     -- d (%)
);

-- Access targets (per-run)
CREATE TABLE IF NOT EXISTS access_targets (
    run_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    demand_access_mw      DOUBLE PRECISION,
    generation_access_mw  DOUBLE PRECISION,
    created_at            TIMESTAMPTZ DEFAULT now()
);

-- Connection queue (available MW per node)
CREATE TABLE IF NOT EXISTS connection_queue (
    node_id            TEXT REFERENCES network_nodes(node_id) PRIMARY KEY,
    available_load_mw  DOUBLE PRECISION DEFAULT 100.0,
    available_gen_mw   DOUBLE PRECISION DEFAULT 100.0
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    record_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor       TEXT,
    action      TEXT,
    target_type TEXT,
    target_id   TEXT,
    details     JSONB,
    ts          TIMESTAMP DEFAULT now()
);
