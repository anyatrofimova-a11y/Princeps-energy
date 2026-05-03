-- 2026_05_03_pins_nsip.sql
-- Destination table for the PINS NSIP/DCO connector
-- (app/connectors/sources/nsip_dco.py, slug 'pins_nsip_dco').
-- Idempotent: every CREATE is IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS pins_nsip_dco (
  id BIGSERIAL PRIMARY KEY,
  case_ref TEXT NOT NULL,
  wp_id INT,
  title TEXT NOT NULL,
  sector TEXT,
  status TEXT,
  promoter TEXT,
  region TEXT,
  applied_date DATE,
  accepted_date DATE,
  decision_date DATE,
  location_lat NUMERIC,
  location_lng NUMERIC,
  capacity_mw NUMERIC,
  source_url TEXT,
  ingested_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT ux_pins_case_ref UNIQUE(case_ref)
);

CREATE INDEX IF NOT EXISTS idx_pins_sector ON pins_nsip_dco(sector);
CREATE INDEX IF NOT EXISTS idx_pins_status ON pins_nsip_dco(status);
