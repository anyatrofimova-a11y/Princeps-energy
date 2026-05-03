-- Time-series store for sensor-style data — Princeps "Palantir-for-energy"
-- complement to point-in-time `object_versions`. One row = one observation.
--
-- Why a single wide table (not partitioned yet):
--   • TimescaleDB is NOT installed (checked `\dx`); we'd rather ship plain
--     Postgres than wedge in an extension. Volume at MVP is BMRS prices
--     (~1.5k rows / month) — partitioning is unnecessary headache.
--   • Index on (sensor_id, ts DESC) gives O(log n) windowed range scans.
--     If we ever cross ~50M rows we add native PARTITION BY RANGE (ts).
--
-- Seed: BMRS settlement prices (last 30 days) into two sensor_ids so the
-- TimeSeriesChart Slate widget has real data the moment this migration
-- runs. Idempotent — NOT EXISTS guard means re-running is a no-op.

BEGIN;

CREATE TABLE IF NOT EXISTS time_series (
  id BIGSERIAL PRIMARY KEY,
  sensor_id TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,
  value NUMERIC NOT NULL,
  label TEXT,
  source_rid TEXT,
  tenant_id UUID DEFAULT '00000000-0000-0000-0000-000000000001'
);

CREATE INDEX IF NOT EXISTS idx_ts_sensor_ts ON time_series (sensor_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_ts_ts ON time_series (ts DESC);
CREATE INDEX IF NOT EXISTS idx_ts_source ON time_series (source_rid)
  WHERE source_rid IS NOT NULL;

-- Hard de-dup guard — a (sensor_id, ts) pair is the natural key for a
-- physical sensor reading. Lets the seed query (and any future ingester)
-- use ON CONFLICT DO NOTHING to stay idempotent across re-runs.
CREATE UNIQUE INDEX IF NOT EXISTS ux_ts_sensor_ts ON time_series (sensor_id, ts);

-- ── Seed: BMRS system_buy_price + system_sell_price (last 30 days) ──
-- BMRS settlement_period is a 1-48 half-hourly slot. Convert via
--   ts = settlement_date::timestamptz + (period - 1) * 30 minutes
-- (UTC; BMRS is reported in UTC). Skip rows where the price is NULL.
--
-- The NOT EXISTS guard wraps the WHOLE seed: once at least one
-- bmrs.system_buy_price row is present, we never re-insert. That keeps
-- the migration safe to re-apply without bloating the table.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM time_series WHERE sensor_id = 'bmrs.system_buy_price' LIMIT 1
  ) THEN
    INSERT INTO time_series (sensor_id, ts, value, label, source_rid)
    SELECT
      'bmrs.system_buy_price',
      (settlement_date::timestamptz AT TIME ZONE 'UTC')
        + ((settlement_period - 1) * INTERVAL '30 minutes'),
      system_buy_price,
      'GBP/MWh',
      'rid.princeps.bmrs.settlement.' || id::text
    FROM bmrs_settlement_prices
    WHERE system_buy_price IS NOT NULL
      AND settlement_date >= (CURRENT_DATE - INTERVAL '30 days')
    ON CONFLICT (sensor_id, ts) DO NOTHING;

    INSERT INTO time_series (sensor_id, ts, value, label, source_rid)
    SELECT
      'bmrs.system_sell_price',
      (settlement_date::timestamptz AT TIME ZONE 'UTC')
        + ((settlement_period - 1) * INTERVAL '30 minutes'),
      system_sell_price,
      'GBP/MWh',
      'rid.princeps.bmrs.settlement.' || id::text
    FROM bmrs_settlement_prices
    WHERE system_sell_price IS NOT NULL
      AND settlement_date >= (CURRENT_DATE - INTERVAL '30 days')
    ON CONFLICT (sensor_id, ts) DO NOTHING;
  END IF;
END $$;

COMMIT;
