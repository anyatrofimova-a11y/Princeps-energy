-- Agricultural Land Classification (ALC) — Post-1988 England
-- Source: https://naturalengland-defra.opendata.arcgis.com/ (ArcGIS REST, OGL)
-- Grades: 1, 2, 3a, 3b, 4, 5, Urban, Non-Agricultural, Woodland.
-- SRID 4326, polygon geometries.

CREATE TABLE IF NOT EXISTS alc_grades (
    id              SERIAL PRIMARY KEY,
    feature_id      TEXT NOT NULL,
    alc_grade       TEXT NOT NULL,                 -- '1', '2', '3a', '3b', '4', '5', 'Urban', ...
    area_ha         DOUBLE PRECISION,
    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL,
    raw_data        JSONB DEFAULT '{}'::jsonb,
    ingested_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alc_feature_id
    ON alc_grades (feature_id);
CREATE INDEX IF NOT EXISTS idx_alc_geom
    ON alc_grades USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_alc_grade
    ON alc_grades (alc_grade);
