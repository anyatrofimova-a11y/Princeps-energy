-- NUAR — National Underground Asset Register (public beta)
-- Source: https://www.gov.uk/guidance/national-underground-asset-register-nuar
-- Programme access: apply via the Geospatial Commission. Full-dataset API
-- requires an asset-owner or authorised-user agreement; this table accepts
-- local GeoJSON exports shared by permitted parties.

CREATE TABLE IF NOT EXISTS nuar_assets (
    id              SERIAL PRIMARY KEY,
    nuar_id         TEXT,                          -- NUAR ref if supplied
    asset_type      TEXT NOT NULL,                 -- water, gas, electric, telecom, sewer, other
    owner           TEXT,
    material        TEXT,
    diameter_mm     NUMERIC,
    voltage_kv      NUMERIC,
    depth_m         NUMERIC,
    installed_year  INTEGER,
    geom            GEOMETRY(Geometry, 4326) NOT NULL,   -- lines or points
    raw_data        JSONB DEFAULT '{}'::jsonb,
    ingested_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nuar_geom
    ON nuar_assets USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_nuar_asset_type
    ON nuar_assets (asset_type);
CREATE INDEX IF NOT EXISTS idx_nuar_owner
    ON nuar_assets (owner);
