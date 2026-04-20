-- =============================================================================
-- 0013_lccc_safeguarding_schema.sql
-- -----------------------------------------------------------------------------
-- Princeps — LCCC daily CfD reference prices + MoD DIO + CAA safeguarding
-- zones.
--
--   * LCCC daily IMRP / BMRP / CfD top-ups
--       https://www.lowcarboncontracts.uk/ (Open Data Portal — OGL v3)
--
--   * MoD DIO safeguarding zones (low-flying, radar, explosive storage, training)
--       ODPM Circular 01/2003 basis. Published via MoD open data + data.gov.uk.
--
--   * CAA aerodrome safeguarding zones (CAP 738)
--       https://www.caa.co.uk/commercial-industry/airspace/
--
-- Idempotent. Applied on startup by app/db_setup.py.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;


-- ── LCCC daily reference prices ───────────────────────────────────────────
-- One row per (series, trading_date). series ∈ {imrp, bmrp, topup}.
CREATE TABLE IF NOT EXISTS lccc_daily_reference_prices (
    id              bigserial PRIMARY KEY,
    series          text NOT NULL,
    trading_date    date NOT NULL,
    price_gbp_mwh   numeric(10, 3),
    raw             jsonb,
    ingested_at     timestamptz DEFAULT now(),
    UNIQUE (series, trading_date)
);
CREATE INDEX IF NOT EXISTS idx_lccc_prices_date
    ON lccc_daily_reference_prices (trading_date DESC);
CREATE INDEX IF NOT EXISTS idx_lccc_prices_series
    ON lccc_daily_reference_prices (series, trading_date DESC);


-- ── MoD DIO safeguarding zones ────────────────────────────────────────────
-- zone_type ∈ {low_flying, radar, explosive_storage, training_area,
--              safeguarded_site, wind_turbine_consultation}.
CREATE TABLE IF NOT EXISTS mod_safeguarding_zones (
    id                    bigserial PRIMARY KEY,
    feature_id            text UNIQUE,
    zone_type             text NOT NULL,
    name                  text,
    buffer_m              integer,
    consultation_required boolean DEFAULT true,
    statutory_basis       text,
    source_updated_at     timestamptz,
    ingested_at           timestamptz DEFAULT now(),
    geom                  geography(Geometry, 4326),
    raw                   jsonb
);
CREATE INDEX IF NOT EXISTS idx_mod_safeguarding_geom
    ON mod_safeguarding_zones USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_mod_safeguarding_type
    ON mod_safeguarding_zones (zone_type);


-- ── CAA aerodrome safeguarding zones ──────────────────────────────────────
-- zone_class ∈ {wind_turbine_exclusion_radius, glint_glare, tall_structure_6km,
--               tall_structure_15km, obstacle_limitation_surface,
--               public_safety_zone}.
CREATE TABLE IF NOT EXISTS caa_aerodrome_safeguarding (
    id                bigserial PRIMARY KEY,
    feature_id        text UNIQUE,
    aerodrome_name    text,
    aerodrome_icao    text,
    zone_class        text NOT NULL,
    height_limit_m    numeric(8, 2),
    buffer_m          integer,
    source_updated_at timestamptz,
    ingested_at       timestamptz DEFAULT now(),
    geom              geography(Geometry, 4326),
    raw               jsonb
);
CREATE INDEX IF NOT EXISTS idx_caa_safeguarding_geom
    ON caa_aerodrome_safeguarding USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_caa_safeguarding_aerodrome
    ON caa_aerodrome_safeguarding (aerodrome_icao);
CREATE INDEX IF NOT EXISTS idx_caa_safeguarding_class
    ON caa_aerodrome_safeguarding (zone_class);


-- ── Ingestion log (shared for LCCC + MoD + CAA) ───────────────────────────
CREATE TABLE IF NOT EXISTS substrate_plus_ingest_log (
    id              bigserial PRIMARY KEY,
    dataset         text NOT NULL,
    bbox            jsonb,
    rows_inserted   integer DEFAULT 0,
    rows_updated    integer DEFAULT 0,
    rows_failed     integer DEFAULT 0,
    status          text DEFAULT 'running',
    error_message   text,
    started_at      timestamptz DEFAULT now(),
    finished_at     timestamptz
);
CREATE INDEX IF NOT EXISTS idx_substrate_plus_log_dataset
    ON substrate_plus_ingest_log (dataset, started_at DESC);
