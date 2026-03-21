-- Site design — placed assets with BOM linking, validation, and pipeline integration
-- Run: psql -d feasibly -f sql/migrate_site_design.sql

CREATE TABLE IF NOT EXISTS placed_assets (
    asset_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    UUID REFERENCES projects(project_id) ON DELETE CASCADE,
    parcel_id     UUID REFERENCES parcels(parcel_id) ON DELETE SET NULL,
    asset_type    TEXT NOT NULL,
    label         TEXT,
    capacity_mw   DOUBLE PRECISION DEFAULT 0,
    lat           DOUBLE PRECISION NOT NULL,
    lon           DOUBLE PRECISION NOT NULL,
    rotation_deg  DOUBLE PRECISION DEFAULT 0,
    width_m       DOUBLE PRECISION,
    depth_m       DOUBLE PRECISION,
    height_m      DOUBLE PRECISION,
    color         TEXT,
    bom_item_id   TEXT,
    bom_spec      JSONB DEFAULT '{}',
    validation    JSONB DEFAULT '{}',
    sort_order    INTEGER DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_placed_assets_project ON placed_assets(project_id);
CREATE INDEX IF NOT EXISTS idx_placed_assets_parcel ON placed_assets(parcel_id);
