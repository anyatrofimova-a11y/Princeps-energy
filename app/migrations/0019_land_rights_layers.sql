-- 0019_land_rights_layers.sql — Princeps BOT-LR
-- Backs /api/land-rights/* GeoJSON endpoints; SRID 4326 geography; idempotent.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS land_rights_forestry_estate (
    id bigserial PRIMARY KEY,
    feature_id text UNIQUE,
    forest_name text,
    nation text,
    managing_body text,
    area_ha numeric(14,3),
    source_updated_at timestamptz,
    ingested_at timestamptz DEFAULT now(),
    geom geography(Geometry,4326) NOT NULL,
    raw jsonb DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_lr_forestry_geom ON land_rights_forestry_estate USING GIST (geom);

CREATE TABLE IF NOT EXISTS land_rights_national_trust (
    id bigserial PRIMARY KEY,
    feature_id text UNIQUE,
    property_name text,
    access_type text,
    region text,
    area_ha numeric(14,3),
    source_updated_at timestamptz,
    ingested_at timestamptz DEFAULT now(),
    geom geography(Geometry,4326) NOT NULL,
    raw jsonb DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_lr_nt_geom ON land_rights_national_trust USING GIST (geom);

CREATE TABLE IF NOT EXISTS land_rights_common_land (
    id bigserial PRIMARY KEY,
    feature_id text UNIQUE,
    cl_number text,
    name text,
    parish text,
    county text,
    area_ha numeric(14,3),
    source_updated_at timestamptz,
    ingested_at timestamptz DEFAULT now(),
    geom geography(Geometry,4326) NOT NULL,
    raw jsonb DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_lr_common_geom ON land_rights_common_land USING GIST (geom);

CREATE TABLE IF NOT EXISTS land_rights_conservation_cov (
    id bigserial PRIMARY KEY,
    feature_id text UNIQUE,
    responsible_body text,
    landowner text,
    duration_years integer,
    purpose text,
    registered_at date,
    area_ha numeric(14,3),
    source_updated_at timestamptz,
    ingested_at timestamptz DEFAULT now(),
    geom geography(Geometry,4326) NOT NULL,
    raw jsonb DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_lr_cov_geom ON land_rights_conservation_cov USING GIST (geom);

CREATE TABLE IF NOT EXISTS land_rights_prow_lines (
    id bigserial PRIMARY KEY,
    feature_id text UNIQUE,
    row_class text NOT NULL CHECK (row_class IN
      ('footpath','bridleway','restricted_byway','byway_open_to_traffic','other')),
    name text,
    parish text,
    council text,
    length_m numeric(12,2),
    source_updated_at timestamptz,
    ingested_at timestamptz DEFAULT now(),
    geom geography(LineString,4326) NOT NULL,
    raw jsonb DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_lr_prow_geom ON land_rights_prow_lines USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_lr_prow_class ON land_rights_prow_lines (row_class);

CREATE TABLE IF NOT EXISTS land_rights_parcel_ownership (
    inspire_id text PRIMARY KEY,
    category text NOT NULL CHECK (category IN
      ('uk_company','overseas_company','crown_or_public',
       'individual_or_unknown','charity_or_trust')),
    proprietor_name text,
    title_number text,
    country_incorp text,
    company_number text,
    source text DEFAULT 'hmlr_ccod_ocod',
    refreshed_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lr_parcel_own_cat ON land_rights_parcel_ownership (category);
