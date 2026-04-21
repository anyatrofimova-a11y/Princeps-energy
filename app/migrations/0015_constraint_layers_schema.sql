-- =============================================================================
-- 0015_constraint_layers_schema.sql
-- -----------------------------------------------------------------------------
-- Princeps — constraint layers consumed by ``utils/consultee_resolver.py``.
--
-- This migration ships the PostGIS tables that the consultee engine was
-- previously "failing open" on (logging `layer table X missing — rule fails
-- open`). Each table is keyed to a layer name in
-- ``_LAYER_TABLE_MAP`` inside ``consultee_resolver``:
--
--   caa_airspace_buffers      → layer ``airspace_buffer``
--   listed_buildings_he       → layer ``listed_building``
--   crown_estate_land         → layer ``crown_land``
--   ofcom_telecom_links       → layer ``telecom_link``
--   marine_plan_areas         → layer ``marine_plan_area``
--
-- NOTE — ``mod_safeguarding_zones`` already exists from migration 0013 and is
-- NOT re-created here. The resolver's old alias ``mod_safeguarding`` is
-- handled by a thin updatable VIEW so we don't break older references.
--
-- Statutory / publisher basis:
--   * CAA safeguarding      — CAP 738 aerodrome safeguarding; Air Navigation
--                             Order 2016 arts. 242–247. Source: CAA AIP.
--   * Listed Buildings      — Planning (Listed Buildings & Conservation Areas)
--                             Act 1990 s.1; published via Historic England NHLE.
--   * Crown Estate Land     — Crown Estate Act 1961; Crown Estate ArcGIS Hub.
--   * Ofcom Telecom Links   — Wireless Telegraphy Act 2006; Ofcom fixed-link
--                             spectrum register (> 1 GHz).
--   * Marine Plan Areas     — Marine & Coastal Access Act 2009; MMO / UKHO.
--
-- Idempotent. Applied by app/db_setup.py on startup.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;


-- ── CAA airspace safeguarding buffers ─────────────────────────────────────
-- Complements ``caa_aerodrome_safeguarding`` (0013). This table stores the
-- explicit 6 km / 15 km tall-structure consultation buffers as
-- MultiPolygon rings so bbox queries and ST_DWithin tests are O(1).
-- zone_class enforced via CHECK (text-as-enum, idempotent-friendly).
CREATE TABLE IF NOT EXISTS caa_airspace_buffers (
    id                bigserial PRIMARY KEY,
    feature_id        text UNIQUE,
    aerodrome_icao    text,
    aerodrome_name    text,
    zone_class        text NOT NULL CHECK (zone_class IN (
        'inner_6km',
        'outer_15km',
        'wind_turbine_exclusion',
        'tall_structure_consultation',
        'public_safety_zone',
        'obstacle_limitation_surface',
        'radar_line_of_sight'
    )),
    height_limit_m    numeric(8, 2),
    buffer_m          integer,
    source_updated_at timestamptz,
    ingested_at       timestamptz DEFAULT now(),
    geom              geography(MultiPolygon, 4326),
    raw               jsonb
);
CREATE INDEX IF NOT EXISTS idx_caa_airspace_buffers_geom
    ON caa_airspace_buffers USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_caa_airspace_buffers_icao
    ON caa_airspace_buffers (aerodrome_icao);
CREATE INDEX IF NOT EXISTS idx_caa_airspace_buffers_class
    ON caa_airspace_buffers (zone_class);

-- Resolver-friendly alias — ``consultee_resolver._LAYER_TABLE_MAP`` points
-- the ``airspace_buffer`` layer at table name ``caa_airspace``. Keep that
-- working via a VIEW so we don't touch the resolver's old call-sites.
CREATE OR REPLACE VIEW caa_airspace AS
    SELECT id,
           feature_id,
           aerodrome_icao,
           aerodrome_name,
           zone_class,
           height_limit_m,
           buffer_m,
           geom,
           raw,
           ingested_at
    FROM caa_airspace_buffers;


-- ── Historic England — Listed Buildings (narrow NHLE subset) ──────────────
-- Separate from ``nhle_heritage_entries`` (0014) because the resolver's
-- ``listed_building`` layer wants a tightly-scoped Point table for 500 m
-- proximity queries. ``nhle_heritage_entries`` carries the wider NHLE
-- universe (scheduled monuments, parks & gardens, battlefields, etc).
CREATE TABLE IF NOT EXISTS listed_buildings_he (
    list_entry_id     text PRIMARY KEY,     -- HE NHLE number
    name              text,
    grade             text,                  -- I, II*, II
    entry_class       text NOT NULL CHECK (entry_class IN (
        'listed_building',
        'scheduled_monument',
        'park_garden',
        'protected_wreck',
        'battlefield',
        'world_heritage_site',
        'conservation_area'
    )) DEFAULT 'listed_building',
    designated_date   date,
    local_planning_authority text,
    source_updated_at timestamptz,
    ingested_at       timestamptz DEFAULT now(),
    geom              geography(Point, 4326),
    raw               jsonb
);
CREATE INDEX IF NOT EXISTS idx_listed_buildings_he_geom
    ON listed_buildings_he USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_listed_buildings_he_grade
    ON listed_buildings_he (grade) WHERE grade IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_listed_buildings_he_class
    ON listed_buildings_he (entry_class);

-- Resolver alias — ``listed_building`` layer → table name ``listed_buildings``.
CREATE OR REPLACE VIEW listed_buildings AS
    SELECT list_entry_id AS feature_id,
           name, grade, entry_class, designated_date,
           local_planning_authority, geom, raw, ingested_at
    FROM listed_buildings_he;


-- ── Crown Estate onshore & foreshore land ─────────────────────────────────
-- Primarily E+W foreshore / seabed-to-12nm belt, plus rural estates (Windsor,
-- Regents Park, Savernake). Crown Estate Scotland is a separate public body
-- and its land is tracked in ``crown_estate_scotland_land`` (a stub VIEW
-- below — data ingestion is not part of this migration).
CREATE TABLE IF NOT EXISTS crown_estate_land (
    id                bigserial PRIMARY KEY,
    feature_id        text UNIQUE,
    name              text,
    land_class        text NOT NULL CHECK (land_class IN (
        'foreshore',
        'seabed',
        'rural_estate',
        'urban_estate',
        'mineral_rights',
        'windfarm_lease',
        'other'
    )),
    holding_type      text,                  -- freehold | leasehold | minerals
    area_ha           numeric(14, 3),
    source_updated_at timestamptz,
    ingested_at       timestamptz DEFAULT now(),
    geom              geography(Geometry, 4326),
    raw               jsonb
);
CREATE INDEX IF NOT EXISTS idx_crown_estate_geom
    ON crown_estate_land USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_crown_estate_class
    ON crown_estate_land (land_class);

-- Placeholder view so the resolver's ``crown_land_scotland`` layer doesn't
-- hard-fail if the Scottish register hasn't been ingested yet. Empty rows
-- → predicate returns false → rule still fails open.
CREATE OR REPLACE VIEW crown_estate_scotland_land AS
    SELECT * FROM crown_estate_land WHERE false;


-- ── Ofcom fixed telecom links (> 1 GHz) ───────────────────────────────────
-- LineString per link between two terminals. Used for line-of-sight
-- consultation when wind turbines / tall masts are proposed.
CREATE TABLE IF NOT EXISTS ofcom_telecom_links (
    id                bigserial PRIMARY KEY,
    feature_id        text UNIQUE,           -- Ofcom licence reference
    operator          text,
    service_class     text NOT NULL CHECK (service_class IN (
        'fixed_link',
        'scanning_telemetry',
        'satellite_earth_station',
        'pmr',
        'broadcasting',
        'other'
    )) DEFAULT 'fixed_link',
    frequency_mhz_tx  numeric(10, 3),
    frequency_mhz_rx  numeric(10, 3),
    bandwidth_mhz     numeric(10, 3),
    licence_expiry    date,
    source_updated_at timestamptz,
    ingested_at       timestamptz DEFAULT now(),
    geom              geography(LineString, 4326),
    raw               jsonb
);
CREATE INDEX IF NOT EXISTS idx_ofcom_telecom_links_geom
    ON ofcom_telecom_links USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_ofcom_telecom_links_op
    ON ofcom_telecom_links (operator);
CREATE INDEX IF NOT EXISTS idx_ofcom_telecom_links_class
    ON ofcom_telecom_links (service_class);


-- ── Marine Management Organisation (MMO) marine plan areas ────────────────
-- One row per adopted marine plan (11 as of 2026: NE inshore, NE offshore,
-- NW inshore, NW offshore, E inshore, E offshore, SE inshore, S inshore,
-- S offshore, SW inshore, SW offshore). Welsh and Scottish marine plans are
-- handled by Welsh Government / Marine Scotland; those can reuse this table
-- with tier=regional_admin.
CREATE TABLE IF NOT EXISTS marine_plan_areas (
    id                bigserial PRIMARY KEY,
    feature_id        text UNIQUE,
    plan_name         text NOT NULL,
    plan_code         text,                  -- e.g. NE_inshore, SW_offshore
    tier              text NOT NULL CHECK (tier IN (
        'inshore',
        'offshore',
        'regional_admin',
        'transitional'
    )) DEFAULT 'inshore',
    adopted_date      date,
    source_updated_at timestamptz,
    ingested_at       timestamptz DEFAULT now(),
    geom              geography(Geometry, 4326),
    raw               jsonb
);
CREATE INDEX IF NOT EXISTS idx_marine_plan_geom
    ON marine_plan_areas USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_marine_plan_tier
    ON marine_plan_areas (tier);


-- ── Resolver alias for MoD ────────────────────────────────────────────────
-- consultee_resolver maps layer ``mod_safeguard`` → table ``mod_safeguarding``.
-- The real table (from 0013) is named ``mod_safeguarding_zones``.
CREATE OR REPLACE VIEW mod_safeguarding AS
    SELECT id, feature_id, zone_type, name, buffer_m, geom, raw, ingested_at
    FROM mod_safeguarding_zones;


-- ── Ingestion log (shared across constraint layers) ───────────────────────
CREATE TABLE IF NOT EXISTS constraint_layers_ingest_log (
    id              bigserial PRIMARY KEY,
    layer           text NOT NULL,
    bbox            jsonb,
    rows_inserted   integer DEFAULT 0,
    rows_updated    integer DEFAULT 0,
    rows_failed     integer DEFAULT 0,
    status          text DEFAULT 'running',
    error_message   text,
    started_at      timestamptz DEFAULT now(),
    finished_at     timestamptz
);
CREATE INDEX IF NOT EXISTS idx_constraint_layers_log
    ON constraint_layers_ingest_log (layer, started_at DESC);
