-- CIM Asset Library (IEC 61970)
-- SRID 4326 for international interoperability

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Main asset store — typed CIM objects with JSONB payload
CREATE TABLE IF NOT EXISTS cim_assets (
    mrid            TEXT PRIMARY KEY,
    asset_type      TEXT NOT NULL,
    name            TEXT,
    data            JSONB NOT NULL,
    geometry        GEOMETRY(Point, 4326),
    source          TEXT,
    source_region   TEXT,
    tags            TEXT[] DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cim_assets_type   ON cim_assets (asset_type);
CREATE INDEX IF NOT EXISTS idx_cim_assets_geom   ON cim_assets USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_cim_assets_source ON cim_assets (source);
CREATE INDEX IF NOT EXISTS idx_cim_assets_name   ON cim_assets USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_cim_assets_data   ON cim_assets USING gin (data);
CREATE INDEX IF NOT EXISTS idx_cim_assets_tags   ON cim_assets USING gin (tags);

-- Terminals linking conducting equipment to connectivity nodes
CREATE TABLE IF NOT EXISTS cim_terminals (
    mrid                    TEXT PRIMARY KEY,
    conducting_equipment_id TEXT REFERENCES cim_assets(mrid) ON DELETE CASCADE,
    connectivity_node_id    TEXT,
    sequence_number         INTEGER DEFAULT 1,
    connected               BOOLEAN DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_cim_term_equip ON cim_terminals (conducting_equipment_id);
CREATE INDEX IF NOT EXISTS idx_cim_term_cn    ON cim_terminals (connectivity_node_id);

-- Export audit trail
CREATE TABLE IF NOT EXISTS cim_exports (
    id              SERIAL PRIMARY KEY,
    model_id        TEXT NOT NULL,
    profile         TEXT NOT NULL,
    format          TEXT NOT NULL,
    asset_count     INTEGER,
    description     TEXT,
    created_by      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Asset ↔ model composition (which assets belong to which export model)
CREATE TABLE IF NOT EXISTS cim_model_assets (
    model_id    TEXT NOT NULL,
    asset_mrid  TEXT NOT NULL REFERENCES cim_assets(mrid) ON DELETE CASCADE,
    PRIMARY KEY (model_id, asset_mrid)
);
