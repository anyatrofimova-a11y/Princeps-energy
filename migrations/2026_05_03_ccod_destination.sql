-- 2026_05_03_ccod_destination.sql
-- Destination table for the HM Land Registry Corporate & Commercial Ownership
-- Data (CCOD) connector. Idempotent; safe to apply repeatedly.
--
-- Driven by app/connectors/sources/ccod.py (slug: hm_land_registry_ccod).
-- License: OGL-3.0. Cadence: monthly.

CREATE TABLE IF NOT EXISTS hm_land_registry_ccod (
  id BIGSERIAL PRIMARY KEY,
  title_number TEXT NOT NULL,
  tenure TEXT,
  proprietor_name_1 TEXT,
  company_registration_no_1 TEXT,
  proprietorship_category_1 TEXT,
  country_incorporated_1 TEXT,
  proprietor_name_2 TEXT,
  company_registration_no_2 TEXT,
  proprietor_name_3 TEXT,
  company_registration_no_3 TEXT,
  proprietor_name_4 TEXT,
  company_registration_no_4 TEXT,
  property_address TEXT,
  district TEXT,
  county TEXT,
  region TEXT,
  postcode TEXT,
  date_proprietor_added DATE,
  multiple_address_indicator TEXT,
  change_indicator TEXT,
  change_date DATE,
  ingested_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT ux_ccod_title UNIQUE (title_number)
);

CREATE INDEX IF NOT EXISTS idx_ccod_postcode ON hm_land_registry_ccod(postcode);
CREATE INDEX IF NOT EXISTS idx_ccod_company_reg ON hm_land_registry_ccod(company_registration_no_1);
CREATE INDEX IF NOT EXISTS idx_ccod_district ON hm_land_registry_ccod(district);
