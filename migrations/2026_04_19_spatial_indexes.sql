-- ============================================================================
-- 2026_04_19_spatial_indexes.sql
-- Ensure every geometry column in feasibly has a GiST index.
--
-- As-was audit (2026-04-19): four geom columns lacked GiST indexes:
--   * constraint_groups.bbox
--   * ltds_substations.geom
--   * repd_projects.geometry
--   * ukpn_ecr.geom
--
-- This file issues CREATE INDEX IF NOT EXISTS for ALL geom columns so it is
-- safe and idempotent to re-run; pre-existing indexes become no-ops.
-- ============================================================================

BEGIN;

-- --- Previously missing (primary intent of this migration) ------------------
CREATE INDEX IF NOT EXISTS idx_constraint_groups_bbox
    ON constraint_groups USING GIST (bbox);

CREATE INDEX IF NOT EXISTS idx_ltds_substations_geom
    ON ltds_substations USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_repd_projects_geom
    ON repd_projects USING GIST (geometry);

CREATE INDEX IF NOT EXISTS idx_ukpn_ecr_geom
    ON ukpn_ecr USING GIST (geom);

-- --- Existing indexes re-asserted under canonical names (idempotent) --------
-- Any index that already exists on the same (table, column) will be a no-op
-- here; the IF NOT EXISTS clause prevents duplicates.
CREATE INDEX IF NOT EXISTS idx_alc_grades_geom              ON alc_grades              USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_cim_assets_geom              ON cim_assets              USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_cim_substations_geom         ON cim_substations         USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_dc_assessments_geom          ON dc_assessments          USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_dc_constraint_zones_geom     ON dc_constraint_zones     USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_dc_facilities_geom           ON dc_facilities           USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_dc_fibre_pops_geom           ON dc_fibre_pops           USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_dc_ixp_nodes_geom            ON dc_ixp_nodes            USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_dc_water_bodies_geom         ON dc_water_bodies         USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_dno_substations_geom         ON dno_substations         USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_env_constraints_geom         ON environmental_constraints USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_eso_tec_project_geom         ON eso_tec_project         USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_eso_tec_register_geom        ON eso_tec_register        USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_geeflow_extractions_geom     ON geeflow_extractions     USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_grid_assessments_geom        ON grid_assessments        USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_grid_dno_boundaries_geom     ON grid_dno_boundaries     USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_grid_ecr_geom                ON grid_ecr                USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_grid_lines_geom              ON grid_lines              USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_grid_substations_geom        ON grid_substations        USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_grid_upgrades_geom           ON grid_upgrades           USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_gsp_profiles_geom            ON gsp_profiles            USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_hmlr_inspire_parcels_geom    ON hmlr_inspire_parcels    USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_home_retrofit_assessments_geom ON home_retrofit_assessments USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_home_retrofit_cases_geom     ON home_retrofit_cases     USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_legacy_assets_geom           ON legacy_assets           USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_network_components_geom      ON network_components      USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_network_nodes_geom           ON network_nodes           USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_network_upgrades_geom        ON network_upgrades        USING GIST (location_geom);
CREATE INDEX IF NOT EXISTS idx_nged_ecr_geom                ON nged_ecr                USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_nged_substation_geom         ON nged_substation         USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_nuar_assets_geom             ON nuar_assets             USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_osm_power_generator_geom     ON osm_power_generator     USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_osm_power_line_geom          ON osm_power_line          USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_osm_power_plant_geom         ON osm_power_plant         USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_osm_power_substation_geom    ON osm_power_substation    USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_osm_power_tower_geom         ON osm_power_tower         USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_osm_power_transformer_geom   ON osm_power_transformer   USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_overlays_geom                ON overlays                USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_parcels_geom                 ON parcels                 USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_parcels_centroid             ON parcels                 USING GIST (centroid);
CREATE INDEX IF NOT EXISTS idx_peering_facilities_geom      ON peering_facilities      USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_planning_applications_centroid ON planning_applications USING GIST (centroid);
CREATE INDEX IF NOT EXISTS idx_prospect_parcels_geom        ON prospect_parcels        USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_repd_project_geom            ON repd_project            USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_retrofit_assessments_geom    ON retrofit_assessments    USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_site_boundaries_geom         ON site_boundaries         USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_smart_meter_demand_geom      ON smart_meter_demand      USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_vision_analyses_geom         ON vision_analyses         USING GIST (geometry);

COMMIT;
