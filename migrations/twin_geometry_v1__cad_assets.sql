-- Twin geometry pipeline — IFC4 → glTF → 3D-Tiles asset registry.

CREATE TABLE IF NOT EXISTS geometry_assets (
    rid             TEXT PRIMARY KEY,
    twin_rid        TEXT NOT NULL,
    source_format   TEXT NOT NULL,            -- 'ifc' | 'glb' | 'step' | 'rvt' | 'procedural'
    source_path     TEXT,                     -- local file path (or s3:// later)
    tileset_url     TEXT,                     -- e.g. /static/tiles/<id>/tileset.json
    glb_url         TEXT,                     -- e.g. /static/glb/<id>.glb (close-up viewer)
    bbox_min_xyz    DOUBLE PRECISION[],
    bbox_max_xyz    DOUBLE PRECISION[],
    metadata        JSONB,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS geometry_assets_twin_idx ON geometry_assets (twin_rid);
CREATE INDEX IF NOT EXISTS geometry_assets_format_idx ON geometry_assets (source_format);


-- Mesh-to-RID bindings — auto-extracted at IFC ingest time from GlobalId.
CREATE TABLE IF NOT EXISTS mesh_bindings (
    geometry_rid   TEXT NOT NULL REFERENCES geometry_assets(rid) ON DELETE CASCADE,
    mesh_node_id   TEXT NOT NULL,             -- IFC GlobalId or 3D-Tiles batch id
    twin_rid       TEXT NOT NULL,             -- the Princeps twin_instance this mesh represents
    ifc_class      TEXT,                      -- 'IfcSpace' | 'IfcBuilding' | 'IfcEquipment' | …
    PRIMARY KEY (geometry_rid, mesh_node_id)
);
CREATE INDEX IF NOT EXISTS mesh_bindings_twin_idx     ON mesh_bindings (twin_rid);
CREATE INDEX IF NOT EXISTS mesh_bindings_geometry_idx ON mesh_bindings (geometry_rid);
