-- ============================================================================
-- 2026_04_19_srid_canon.sql
-- SRID canonicalisation migration for the feasibly DB (Princeps).
--
-- Canonical SRIDs:
--   * 27700 (British National Grid) for UK-bounded operational tables
--     (grid_*, legacy_assets, parcels, prospect_parcels, dc_*, network_*, etc.)
--   * 4326  (WGS84 lat/lon) for tables populated directly from external
--     APIs / browser input (osm_*, cim_*, geeflow_extractions, nged_*, etc.)
--
-- Strategy:
--   * Use ALTER COLUMN ... TYPE geometry(TYPE, SRID) USING ST_SetSRID(...)
--     so that every geom column has an explicit typed SRID constraint.
--   * Never DROP or RECREATE columns. Never move data across tables.
--   * Idempotent: re-running is a no-op (casting a geom that already has the
--     target SRID is a no-op).
--
-- ----------------------------------------------------------------------------
-- AS-WAS AUDIT (captured 2026-04-19 before applying this migration)
-- Columns listed in geometry_columns, with current SRID and GiST status.
-- Source: SELECT * FROM geometry_columns; + pg_index/pg_am AM='gist'.
-- ----------------------------------------------------------------------------
--
--   table                      | column        | srid  | type         | gist
--   ---------------------------+---------------+-------+--------------+------
--   alc_grades                 | geom          |  4326 | MULTIPOLYGON | yes
--   cim_assets                 | geometry      |  4326 | POINT        | yes
--   cim_substations            | geom          |  4326 | POINT        | yes
--   constraint_groups          | bbox          |  4326 | POLYGON      | NO
--   dc_assessments             | geometry      | 27700 | POINT        | yes
--   dc_constraint_zones        | geometry      | 27700 | GEOMETRY     | yes
--   dc_facilities              | geometry      | 27700 | POINT        | yes
--   dc_fibre_pops              | geometry      | 27700 | POINT        | yes
--   dc_ixp_nodes               | geometry      | 27700 | POINT        | yes
--   dc_water_bodies            | geometry      | 27700 | POINT        | yes
--   dno_substations            | geometry      | 27700 | POINT        | yes
--   environmental_constraints  | geometry      |  4326 | GEOMETRY     | yes
--   eso_tec_project            | geometry      |  4326 | POINT        | yes
--   eso_tec_register           | geometry      | 27700 | POINT        | yes
--   geeflow_extractions        | geometry      |  4326 | POLYGON      | yes
--   grid_assessments           | geom          | 27700 | POINT        | yes
--   grid_dno_boundaries        | geom          | 27700 | MULTIPOLYGON | yes
--   grid_ecr                   | geom          | 27700 | POINT        | yes
--   grid_lines                 | geom          | 27700 | LINESTRING   | yes
--   grid_substations           | geom          | 27700 | POINT        | yes
--   grid_upgrades              | geometry      | 27700 | GEOMETRY     | yes
--   gsp_profiles               | geom          | 27700 | POINT        | yes
--   hmlr_inspire_parcels       | geom          | 27700 | MULTIPOLYGON | yes
--   home_retrofit_assessments  | geometry      | 27700 | POINT        | yes
--   home_retrofit_cases        | geometry      | 27700 | POINT        | yes
--   legacy_assets              | geometry      | 27700 | POINT        | yes
--   ltds_substations           | geom          |  4326 | POINT        | NO
--   network_components         | geometry      | 27700 | LINESTRING   | yes
--   network_nodes              | geom          | 27700 | POINT        | yes
--   network_upgrades           | location_geom | 27700 | POINT        | yes
--   nged_ecr                   | geom          |  4326 | POINT        | yes
--   nged_substation            | geometry      |  4326 | POINT        | yes
--   nuar_assets                | geom          |  4326 | GEOMETRY     | yes
--   osm_power_generator        | geometry      |  4326 | POINT        | yes
--   osm_power_line             | geometry      |  4326 | LINESTRING   | yes
--   osm_power_plant            | geometry      |  4326 | POINT        | yes
--   osm_power_substation       | geometry      |  4326 | POINT        | yes
--   osm_power_tower            | geometry      |  4326 | POINT        | yes
--   osm_power_transformer      | geometry      |  4326 | POINT        | yes
--   overlays                   | geometry      | 27700 | GEOMETRY     | yes
--   parcels                    | geometry      | 27700 | POLYGON      | yes
--   parcels                    | centroid      | 27700 | POINT        | yes
--   peering_facilities         | geom          |  4326 | POINT        | yes
--   planning_applications      | centroid      |  4326 | POINT        | yes
--   prospect_parcels           | geom          | 27700 | POLYGON      | yes
--   repd_project               | geometry      |  4326 | POINT        | yes
--   repd_projects              | geometry      | 27700 | POINT        | NO
--   retrofit_assessments       | geometry      | 27700 | POINT        | yes
--   site_boundaries            | geometry      |  4326 | POLYGON      | yes
--   smart_meter_demand         | geometry      | 27700 | POINT        | yes
--   ukpn_ecr                   | geom          | 27700 | POINT        | NO
--   vision_analyses            | geometry      |  4326 | POINT        | yes
--
-- Findings:
--   * No SRID=0 columns (good).
--   * Four tables missing GiST indexes: constraint_groups.bbox,
--     ltds_substations.geom, repd_projects.geometry, ukpn_ecr.geom
--     (handled in companion file 2026_04_19_spatial_indexes.sql).
--   * Two "twin" tables with different SRIDs — repd_project (4326, API import)
--     vs repd_projects (27700, projected copy) and eso_tec_project (4326, raw)
--     vs eso_tec_register (27700, projected). Both pairs are intentional under
--     the canonical rule (raw API = 4326, operational copy = 27700) so we
--     keep them as-is; no transform needed.
--   * Everything else matches canonical intent. This migration re-asserts the
--     existing SRID via ALTER TYPE so the column's type constraint is explicit.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- UK-bounded operational tables: canonical SRID 27700
-- ALTER TYPE with ST_SetSRID is a no-op when SRID already matches; idempotent.
-- ----------------------------------------------------------------------------

ALTER TABLE grid_substations
    ALTER COLUMN geom TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geom, 27700);

ALTER TABLE grid_lines
    ALTER COLUMN geom TYPE geometry(LINESTRING, 27700)
    USING ST_SetSRID(geom, 27700);

ALTER TABLE grid_dno_boundaries
    ALTER COLUMN geom TYPE geometry(MULTIPOLYGON, 27700)
    USING ST_SetSRID(geom, 27700);

ALTER TABLE grid_ecr
    ALTER COLUMN geom TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geom, 27700);

ALTER TABLE grid_assessments
    ALTER COLUMN geom TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geom, 27700);

ALTER TABLE grid_upgrades
    ALTER COLUMN geometry TYPE geometry(GEOMETRY, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE gsp_profiles
    ALTER COLUMN geom TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geom, 27700);

ALTER TABLE legacy_assets
    ALTER COLUMN geometry TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE parcels
    ALTER COLUMN geometry TYPE geometry(POLYGON, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE parcels
    ALTER COLUMN centroid TYPE geometry(POINT, 27700)
    USING ST_SetSRID(centroid, 27700);

ALTER TABLE prospect_parcels
    ALTER COLUMN geom TYPE geometry(POLYGON, 27700)
    USING ST_SetSRID(geom, 27700);

ALTER TABLE hmlr_inspire_parcels
    ALTER COLUMN geom TYPE geometry(MULTIPOLYGON, 27700)
    USING ST_SetSRID(geom, 27700);

ALTER TABLE dc_assessments
    ALTER COLUMN geometry TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE dc_constraint_zones
    ALTER COLUMN geometry TYPE geometry(GEOMETRY, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE dc_facilities
    ALTER COLUMN geometry TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE dc_fibre_pops
    ALTER COLUMN geometry TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE dc_ixp_nodes
    ALTER COLUMN geometry TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE dc_water_bodies
    ALTER COLUMN geometry TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE dno_substations
    ALTER COLUMN geometry TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE network_components
    ALTER COLUMN geometry TYPE geometry(LINESTRING, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE network_nodes
    ALTER COLUMN geom TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geom, 27700);

ALTER TABLE network_upgrades
    ALTER COLUMN location_geom TYPE geometry(POINT, 27700)
    USING ST_SetSRID(location_geom, 27700);

ALTER TABLE home_retrofit_assessments
    ALTER COLUMN geometry TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE home_retrofit_cases
    ALTER COLUMN geometry TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE retrofit_assessments
    ALTER COLUMN geometry TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE smart_meter_demand
    ALTER COLUMN geometry TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE overlays
    ALTER COLUMN geometry TYPE geometry(GEOMETRY, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE eso_tec_register
    ALTER COLUMN geometry TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE repd_projects
    ALTER COLUMN geometry TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geometry, 27700);

ALTER TABLE ukpn_ecr
    ALTER COLUMN geom TYPE geometry(POINT, 27700)
    USING ST_SetSRID(geom, 27700);

-- ----------------------------------------------------------------------------
-- WGS84 raw-API / imported tables: canonical SRID 4326
-- ----------------------------------------------------------------------------

ALTER TABLE alc_grades
    ALTER COLUMN geom TYPE geometry(MULTIPOLYGON, 4326)
    USING ST_SetSRID(geom, 4326);

ALTER TABLE cim_assets
    ALTER COLUMN geometry TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geometry, 4326);

ALTER TABLE cim_substations
    ALTER COLUMN geom TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geom, 4326);

ALTER TABLE constraint_groups
    ALTER COLUMN bbox TYPE geometry(POLYGON, 4326)
    USING ST_SetSRID(bbox, 4326);

ALTER TABLE environmental_constraints
    ALTER COLUMN geometry TYPE geometry(GEOMETRY, 4326)
    USING ST_SetSRID(geometry, 4326);

ALTER TABLE eso_tec_project
    ALTER COLUMN geometry TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geometry, 4326);

ALTER TABLE geeflow_extractions
    ALTER COLUMN geometry TYPE geometry(POLYGON, 4326)
    USING ST_SetSRID(geometry, 4326);

ALTER TABLE ltds_substations
    ALTER COLUMN geom TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geom, 4326);

ALTER TABLE nged_ecr
    ALTER COLUMN geom TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geom, 4326);

ALTER TABLE nged_substation
    ALTER COLUMN geometry TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geometry, 4326);

ALTER TABLE nuar_assets
    ALTER COLUMN geom TYPE geometry(GEOMETRY, 4326)
    USING ST_SetSRID(geom, 4326);

ALTER TABLE osm_power_generator
    ALTER COLUMN geometry TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geometry, 4326);

ALTER TABLE osm_power_line
    ALTER COLUMN geometry TYPE geometry(LINESTRING, 4326)
    USING ST_SetSRID(geometry, 4326);

ALTER TABLE osm_power_plant
    ALTER COLUMN geometry TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geometry, 4326);

ALTER TABLE osm_power_substation
    ALTER COLUMN geometry TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geometry, 4326);

ALTER TABLE osm_power_tower
    ALTER COLUMN geometry TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geometry, 4326);

ALTER TABLE osm_power_transformer
    ALTER COLUMN geometry TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geometry, 4326);

ALTER TABLE peering_facilities
    ALTER COLUMN geom TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geom, 4326);

ALTER TABLE planning_applications
    ALTER COLUMN centroid TYPE geometry(POINT, 4326)
    USING ST_SetSRID(centroid, 4326);

ALTER TABLE repd_project
    ALTER COLUMN geometry TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geometry, 4326);

ALTER TABLE site_boundaries
    ALTER COLUMN geometry TYPE geometry(POLYGON, 4326)
    USING ST_SetSRID(geometry, 4326);

ALTER TABLE vision_analyses
    ALTER COLUMN geometry TYPE geometry(POINT, 4326)
    USING ST_SetSRID(geometry, 4326);

COMMIT;
