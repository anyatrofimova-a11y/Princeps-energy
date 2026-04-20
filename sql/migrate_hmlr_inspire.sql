-- HMLR INSPIRE Index Polygons
-- Source: https://use-land-property-data.service.gov.uk/datasets/inspire
-- Monthly GML per local-authority; free, OGL-licensed; British National Grid (EPSG:27700)
-- Each polygon represents a registered land title extent.

CREATE TABLE IF NOT EXISTS hmlr_inspire_parcels (
    id              SERIAL PRIMARY KEY,
    inspire_id      TEXT NOT NULL,
    authority_name  TEXT,                              -- e.g. "City of London"
    authority_code  TEXT,                              -- GSS code if known
    area_m2         DOUBLE PRECISION,
    geom            GEOMETRY(MultiPolygon, 27700) NOT NULL,
    raw_data        JSONB DEFAULT '{}'::jsonb,
    ingested_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_hmlr_inspire_id
    ON hmlr_inspire_parcels (inspire_id);
CREATE INDEX IF NOT EXISTS idx_hmlr_inspire_geom
    ON hmlr_inspire_parcels USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_hmlr_inspire_authority
    ON hmlr_inspire_parcels (authority_name);
