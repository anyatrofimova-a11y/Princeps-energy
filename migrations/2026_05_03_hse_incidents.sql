-- 2026_05_03_hse_incidents.sql
-- Destination table for the HSE major incidents (RIDDOR) connector
-- (app/connectors/sources/hse_incidents.py, slug 'hse_riddor_incidents').
-- Idempotent.

CREATE TABLE IF NOT EXISTS hse_major_incidents (
  id BIGSERIAL PRIMARY KEY,
  incident_id TEXT NOT NULL,
  date_reported DATE,
  industry_sector TEXT,
  incident_type TEXT,
  location_postcode TEXT,
  summary TEXT,
  fatalities INT DEFAULT 0,
  injuries INT DEFAULT 0,
  source_url TEXT,
  ingested_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT ux_hse_incident UNIQUE(incident_id)
);

CREATE INDEX IF NOT EXISTS idx_hse_sector ON hse_major_incidents(industry_sector);
CREATE INDEX IF NOT EXISTS idx_hse_date ON hse_major_incidents(date_reported DESC);
