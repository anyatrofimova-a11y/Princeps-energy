-- 2026_05_03_bmrs_prices.sql
-- Destination table for the BMRS settlement-period system prices connector.
-- Idempotent; safe to apply repeatedly.
--
-- Driven by app/connectors/sources/bmrs_prices.py (slug: bmrs_settlement_prices).
-- License: OGL-3.0 (NESO open licence). Cadence: daily; 30-day rolling window.

CREATE TABLE IF NOT EXISTS bmrs_settlement_prices (
  id BIGSERIAL PRIMARY KEY,
  settlement_date DATE NOT NULL,
  settlement_period SMALLINT NOT NULL,
  system_sell_price NUMERIC(10,2),
  system_buy_price NUMERIC(10,2),
  bsad_defaulted BOOL,
  price_derivation_code TEXT,
  reserve_scarcity_price NUMERIC(10,2),
  indicative_net_imbalance_volume NUMERIC(10,2),
  ingested_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT ux_bmrs_price_period UNIQUE (settlement_date, settlement_period)
);

CREATE INDEX IF NOT EXISTS idx_bmrs_prices_date ON bmrs_settlement_prices(settlement_date DESC);
