-- 2026_05_03_entsoe_da_prices.sql
-- Destination table for the ENTSO-E day-ahead price connector
-- (app/connectors/sources/entsoe_prices.py, slug 'entsoe_da_prices_gb').
-- GB bidding zone EIC: 10Y1001A1001A92E. Idempotent.

CREATE TABLE IF NOT EXISTS entsoe_da_prices_gb (
  id BIGSERIAL PRIMARY KEY,
  bidding_zone TEXT NOT NULL DEFAULT 'GB',
  datetime_utc TIMESTAMPTZ NOT NULL,
  price_eur_mwh NUMERIC(10,2),
  currency TEXT DEFAULT 'EUR',
  document_id TEXT,
  ingested_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT ux_entsoe_da UNIQUE(bidding_zone, datetime_utc)
);

CREATE INDEX IF NOT EXISTS idx_entsoe_da_dt ON entsoe_da_prices_gb(datetime_utc DESC);
