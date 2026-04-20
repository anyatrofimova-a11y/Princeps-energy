-- Defra MAGIC constraints (SSSI, AONB/National Landscapes, Flood Zones 2/3,
-- Priority Habitat Inventory).
-- Source: https://environment.data.gov.uk/arcgis/rest/services/ (ArcGIS REST)
-- Stored in SRID 4326 as GEOGRAPHY for easy cross-layer queries.

CREATE TABLE IF NOT EXISTS magic_constraints (
    id              SERIAL PRIMARY KEY,
    source_layer    TEXT NOT NULL,                 -- sssi | aonb | flood2 | flood3 | habitat
    feature_id      TEXT NOT NULL,                 -- upstream OBJECTID / designation ref
    name            TEXT,
    designation     TEXT,                          -- e.g. Flood Zone 3, AONB name
    area_ha         DOUBLE PRECISION,
    geom            GEOGRAPHY(Geometry, 4326) NOT NULL,
    raw_data        JSONB DEFAULT '{}'::jsonb,
    ingested_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_magic_source_featureid
    ON magic_constraints (source_layer, feature_id);
CREATE INDEX IF NOT EXISTS idx_magic_geom
    ON magic_constraints USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_magic_layer
    ON magic_constraints (source_layer);
