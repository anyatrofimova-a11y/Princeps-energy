-- =============================================================================
-- 0014_nature_heritage_schema.sql
-- -----------------------------------------------------------------------------
-- Princeps — Natural England MAGIC overlays + Historic England NHLE + BNG
-- Register. All OGL v3 via Defra Spatial Data / Natural England / Historic
-- England WFS endpoints.
--
-- Statutory basis for each layer:
--   * AONB / National Landscape — CRoW Act 2000, NPPF para 182
--   * SSSI — Wildlife & Countryside Act 1981
--   * SAC — Habitats Regulations 2017 (as amended 2019)
--   * SPA — Conservation of Habitats and Species Regulations 2017
--   * Ramsar — Ramsar Convention (UK signatory), protected as SPA-equivalent
--   * Ancient Woodland — NPPF para 187(c), irreplaceable habitat
--   * NHLE listed buildings — Planning (Listed Buildings and Conservation
--     Areas) Act 1990
--   * BNG Register — Environment Act 2021, BNG mandatory for T&CP from
--     Feb 2024 and for NSIPs from May 2026
--
-- Idempotent. Applied by app/db_setup.py on startup.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;


-- ── Natural England MAGIC designations ────────────────────────────────────
-- Single shared table for all 6 designation classes with a ``layer`` column.
-- Keeps API + indexes compact. layer ∈ {aonb, sssi, sac, spa, ramsar,
-- ancient_woodland}.
CREATE TABLE IF NOT EXISTS magic_designations (
    id                bigserial PRIMARY KEY,
    layer             text NOT NULL CHECK (layer IN
        ('aonb','sssi','sac','spa','ramsar','ancient_woodland')),
    feature_id        text,
    name              text,
    area_ha           numeric(14, 3),
    designated_date   date,
    condition         text,               -- SSSI: favourable / unfavourable
    statutory_basis   text,
    source_updated_at timestamptz,
    ingested_at       timestamptz DEFAULT now(),
    geom              geography(Geometry, 4326),
    raw               jsonb,
    UNIQUE (layer, feature_id)
);
CREATE INDEX IF NOT EXISTS idx_magic_designations_geom
    ON magic_designations USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_magic_designations_layer
    ON magic_designations (layer);
CREATE INDEX IF NOT EXISTS idx_magic_designations_condition
    ON magic_designations (condition) WHERE condition IS NOT NULL;


-- ── Historic England — National Heritage List for England ─────────────────
-- entry_class ∈ {listed_building, scheduled_monument, park_garden,
--                protected_wreck, battlefield, world_heritage_site}.
CREATE TABLE IF NOT EXISTS nhle_heritage_entries (
    id                bigserial PRIMARY KEY,
    list_entry_id     text UNIQUE,         -- HE NHLE number
    entry_class       text NOT NULL,
    name              text,
    grade             text,                -- I, II*, II for listed buildings
    designated_date   date,
    local_planning_authority text,
    source_updated_at timestamptz,
    ingested_at       timestamptz DEFAULT now(),
    geom              geography(Geometry, 4326),
    raw               jsonb
);
CREATE INDEX IF NOT EXISTS idx_nhle_entries_geom
    ON nhle_heritage_entries USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_nhle_entries_class
    ON nhle_heritage_entries (entry_class);
CREATE INDEX IF NOT EXISTS idx_nhle_entries_grade
    ON nhle_heritage_entries (grade) WHERE grade IS NOT NULL;


-- ── BNG Statutory Register (Natural England, live from Feb 2024) ──────────
-- Every registered Biodiversity Net Gain site with habitat-unit allocation,
-- responsible body, 30-year management period.
CREATE TABLE IF NOT EXISTS bng_register_sites (
    id                       bigserial PRIMARY KEY,
    register_reference       text UNIQUE,          -- NE-issued BNG-SITE-NNN
    site_name                text,
    responsible_body         text,                 -- NE, LPA, RSPB, etc.
    landowner                text,
    habitat_baseline_units   numeric(10, 2),
    habitat_enhanced_units   numeric(10, 2),
    hedgerow_units           numeric(10, 2),
    watercourse_units        numeric(10, 2),
    units_available_for_sale numeric(10, 2),
    management_start         date,
    management_end           date,                  -- baseline + 30y
    lpa_code                 text,
    status                   text,                 -- registered / fulfilled / lapsed
    source_updated_at        timestamptz,
    ingested_at              timestamptz DEFAULT now(),
    geom                     geography(Geometry, 4326),
    raw                      jsonb
);
CREATE INDEX IF NOT EXISTS idx_bng_sites_geom
    ON bng_register_sites USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_bng_sites_status
    ON bng_register_sites (status);
CREATE INDEX IF NOT EXISTS idx_bng_sites_lpa
    ON bng_register_sites (lpa_code);


-- ── Ingestion log (shared) ────────────────────────────────────────────────
-- Logs each layer ingestion run for audit + freshness SLAs.
CREATE TABLE IF NOT EXISTS nature_heritage_ingest_log (
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
CREATE INDEX IF NOT EXISTS idx_nature_heritage_ingest_log
    ON nature_heritage_ingest_log (layer, started_at DESC);
