-- Grid Connection & Load Capacity module — Princeps
-- Requires: PostGIS extension (already enabled in 01_schema.sql)

-- ─── UK Grid Substations (aggregated from all 6 DNOs) ────────────────────
-- Sources: UKPN, NGED, SSEN, NPG, SPEN, ENWL OpenDataSoft / CKAN APIs
CREATE TABLE IF NOT EXISTS grid_substations (
    id              SERIAL PRIMARY KEY,
    external_id     TEXT,                  -- DNO-specific identifier
    name            TEXT NOT NULL,
    dno             TEXT NOT NULL,          -- ukpn, nged, ssen, npg, spen, enwl
    region          TEXT,                   -- licence area name
    voltage_kv      NUMERIC,
    site_type       TEXT,                   -- GSP, BSP, Primary, Secondary
    demand_mw       NUMERIC,               -- peak demand
    generation_mw   NUMERIC,               -- connected generation
    demand_headroom_mw  NUMERIC,           -- MW available for new demand
    gen_headroom_mw     NUMERIC,           -- MW available for new generation
    fault_level_ka  NUMERIC,
    transformer_rating_mva NUMERIC,
    rag_demand      TEXT,                   -- green/amber/red for demand
    rag_generation  TEXT,                   -- green/amber/red for generation
    postcode        TEXT,
    town            TEXT,
    county          TEXT,
    geom            GEOMETRY(Point, 27700),
    raw_data        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_grid_sub_geom ON grid_substations USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_grid_sub_dno ON grid_substations (dno);
CREATE INDEX IF NOT EXISTS idx_grid_sub_voltage ON grid_substations (voltage_kv);
CREATE INDEX IF NOT EXISTS idx_grid_sub_ext ON grid_substations (external_id, dno);
CREATE UNIQUE INDEX IF NOT EXISTS idx_grid_sub_ext_uniq ON grid_substations (external_id, dno);

-- ─── Embedded Capacity Register (distribution-connected DER) ──────────────
-- Mandated by Ofgem DCP350: all DER sites >1 MW (some DNOs >50 kW)
CREATE TABLE IF NOT EXISTS grid_ecr (
    id              SERIAL PRIMARY KEY,
    external_id     TEXT,
    site_name       TEXT,
    dno             TEXT NOT NULL,
    technology      TEXT,                   -- solar, wind, bess, gas, etc.
    capacity_mw     NUMERIC,
    voltage_kv      NUMERIC,
    substation_name TEXT,
    substation_id   INTEGER REFERENCES grid_substations(id),
    status          TEXT,                   -- connected, accepted, queued
    connection_date DATE,
    geom            GEOMETRY(Point, 27700),
    raw_data        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_grid_ecr_geom ON grid_ecr USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_grid_ecr_dno ON grid_ecr (dno);
CREATE INDEX IF NOT EXISTS idx_grid_ecr_tech ON grid_ecr (technology);
CREATE INDEX IF NOT EXISTS idx_grid_ecr_sub ON grid_ecr (substation_id);

-- ─── DNO Licence Area Boundaries ──────────────────────────────────────────
-- Source: NESO GIS boundaries dataset
CREATE TABLE IF NOT EXISTS grid_dno_boundaries (
    id              SERIAL PRIMARY KEY,
    dno_code        TEXT NOT NULL UNIQUE,   -- ukpn_epn, ukpn_lpn, ukpn_spn, nged_emid, etc.
    dno_name        TEXT NOT NULL,
    long_name       TEXT,
    geom            GEOMETRY(MultiPolygon, 27700)
);
CREATE INDEX IF NOT EXISTS idx_grid_dno_bound_geom ON grid_dno_boundaries USING GIST (geom);

-- ─── Grid Topology (lines from OSM / GridKit) ────────────────────────────
CREATE TABLE IF NOT EXISTS grid_lines (
    id              SERIAL PRIMARY KEY,
    osm_id          BIGINT,
    voltage_kv      NUMERIC,
    circuits        INTEGER DEFAULT 1,
    operator        TEXT,
    from_sub_id     INTEGER REFERENCES grid_substations(id),
    to_sub_id       INTEGER REFERENCES grid_substations(id),
    length_km       NUMERIC,
    geom            GEOMETRY(LineString, 27700),
    raw_data        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_grid_lines_geom ON grid_lines USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_grid_lines_voltage ON grid_lines (voltage_kv);

-- ─── Grid Connection Assessments (cached results) ────────────────────────
CREATE TABLE IF NOT EXISTS grid_assessments (
    id              SERIAL PRIMARY KEY,
    lat             DOUBLE PRECISION NOT NULL,
    lon             DOUBLE PRECISION NOT NULL,
    capacity_mw     NUMERIC NOT NULL,
    technology      TEXT DEFAULT 'solar',
    -- Results
    nearest_sub_id  INTEGER REFERENCES grid_substations(id),
    distance_km     NUMERIC,
    available_mw    NUMERIC,
    queue_depth     INTEGER,
    queued_mw       NUMERIC,
    rag_status      TEXT,                   -- green/amber/red
    estimated_cost_gbp NUMERIC,
    estimated_timeline_weeks INTEGER,
    tier            TEXT DEFAULT 'data',    -- data, powerflow, transmission
    result_data     JSONB DEFAULT '{}',
    geom            GEOMETRY(Point, 27700),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_grid_assess_geom ON grid_assessments USING GIST (geom);

-- ─── Capacity Snapshots (time-series headroom tracking) ──────────────────
CREATE TABLE IF NOT EXISTS grid_capacity_snapshots (
    id              SERIAL PRIMARY KEY,
    substation_id   INTEGER REFERENCES grid_substations(id) NOT NULL,
    snapshot_date   DATE NOT NULL,
    demand_headroom_mw NUMERIC,
    gen_headroom_mw    NUMERIC,
    demand_mw       NUMERIC,
    generation_mw   NUMERIC,
    raw_data        JSONB DEFAULT '{}',
    UNIQUE (substation_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_grid_cap_snap_sub ON grid_capacity_snapshots (substation_id);

-- ─── Data Ingestion Log ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_ingestion_log (
    id              SERIAL PRIMARY KEY,
    source          TEXT NOT NULL,           -- ukpn, npg, neso_tec, osm, etc.
    dataset         TEXT,                    -- substations, ecr, lines, etc.
    status          TEXT DEFAULT 'running',  -- running, done, failed
    records_fetched INTEGER DEFAULT 0,
    records_upserted INTEGER DEFAULT 0,
    error           TEXT,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);
