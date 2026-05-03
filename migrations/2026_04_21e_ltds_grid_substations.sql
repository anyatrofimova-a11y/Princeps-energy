-- ──────────────────────────────────────────────────────────────────────
-- Task #43 — LTDS substations canonicalised into grid_substations
--
-- Adds lightweight provenance + index support so the grid_line_linker
-- (utils/grid_line_linker.py) has real transmission-level endpoints to
-- snap 1.7M grid_lines rows against. No destructive changes.
-- ──────────────────────────────────────────────────────────────────────

-- raw_data on grid_substations already exists (JSONB). LTDS upserts
-- stash:
--   * external_source     — 'ltds_nged' | 'ltds_ukpn' | ...
--   * ltds_mrid           — CIM master resource identifier
--   * ltds_substation_number — NGED ltds-cim-substation-numbers CSV code
--   * ltds_psr_type       — 'GSP' | 'BSP' | 'Primary' | 'Grid'
--   * ltds_licence_area   — 'East Midlands' | 'South West' | ...
--
-- Expression indexes on those JSONB keys so the linker + future queries
-- can filter / join without a full table scan.

CREATE INDEX IF NOT EXISTS idx_grid_sub_ext_source
    ON grid_substations ((raw_data->>'external_source'));

CREATE INDEX IF NOT EXISTS idx_grid_sub_ltds_mrid
    ON grid_substations ((raw_data->>'ltds_mrid'))
    WHERE raw_data ? 'ltds_mrid';

CREATE INDEX IF NOT EXISTS idx_grid_sub_ltds_psr_type
    ON grid_substations ((raw_data->>'ltds_psr_type'))
    WHERE raw_data ? 'ltds_psr_type';

-- Partial index on transmission-level substations (voltage_kv >= 33) so
-- the linker's ORDER BY geom <-> point queries can filter to endpoint
-- candidates cheaply once most OSM 11kV rows are out of scope.
CREATE INDEX IF NOT EXISTS idx_grid_sub_transmission
    ON grid_substations USING GIST (geom)
    WHERE voltage_kv >= 33;
