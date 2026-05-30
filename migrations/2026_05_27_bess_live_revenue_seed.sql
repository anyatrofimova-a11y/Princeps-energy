-- BESS Live Revenue seed — synthesises 30 days of hourly P10/P50/P90
-- revenue snapshots for the two demo BESS projects so the Live BESS
-- Revenue tile renders an actual chart instead of "Waiting for first
-- snapshot…". Idempotent — clears existing demo rows before inserting.

DELETE FROM bess_live_revenue_snapshots
 WHERE source = 'demo-seed-v1';

INSERT INTO bess_live_revenue_snapshots
  (rid, ts, p10_rev_gbp, p50_rev_gbp, p90_rev_gbp, stack_breakdown, modo_p50_forecast, source)
SELECT
  rid,
  ts,
  -- £/MW/hr revenue varying through the day (low overnight, peak evening).
  -- Formula stays POSITIVE — base load + half-amplitude sine + weekend tilt.
  -- Per-MW figures multiplied by project capacity_mw to give £/hr revenue.
  ROUND(((capacity_mw * (20 + 14 * sin(2 * pi() * (extract(hour from ts) - 6) / 24.0)
                            + 4 * sin(2 * pi() * (extract(dow from ts)) / 7.0))) * 0.75)::numeric, 2)
    AS p10,
  ROUND(((capacity_mw * (34 + 22 * sin(2 * pi() * (extract(hour from ts) - 6) / 24.0)
                             + 6 * sin(2 * pi() * (extract(dow from ts)) / 7.0))))::numeric, 2)
    AS p50,
  ROUND(((capacity_mw * (50 + 32 * sin(2 * pi() * (extract(hour from ts) - 6) / 24.0)
                             + 8 * sin(2 * pi() * (extract(dow from ts)) / 7.0))) * 1.35)::numeric, 2)
    AS p90,
  jsonb_build_object(
    'site_name',      site_name,
    'wholesale_gbp',  ROUND(capacity_mw * 8::numeric,  2),
    'bm_gbp',         ROUND(capacity_mw * 6::numeric,  2),
    'dc_dm_dr_gbp',   ROUND(capacity_mw * 3.5::numeric, 2),
    'capacity_gbp',   ROUND(capacity_mw * 1.2::numeric, 2),
    'ffr_gbp',        ROUND(capacity_mw * 0.8::numeric, 2),
    'tnuos_gbp',     -ROUND(capacity_mw * 1.5::numeric, 2)
  ) AS stack_breakdown,
  ROUND(((capacity_mw * (32 + 18 * sin(2 * pi() * (extract(hour from ts) - 6) / 24.0))))::numeric, 2)
    AS modo_p50,
  'demo-seed-v1' AS source
FROM (
  VALUES
    ('rid.princeps.production.bess.thames-100',     'Thames BESS Phase 1',  50),
    ('rid.princeps.production.bess.pembroke-100',   'Pembroke BESS 100MW', 100),
    ('rid.princeps.production.bess.lower-drointon', 'Lower Farm Drointon',  30)
) AS proj(rid, site_name, capacity_mw)
CROSS JOIN LATERAL (
  -- 30 days × 24 hours = 720 snapshots per project
  SELECT generate_series(
    NOW() - INTERVAL '30 days',
    NOW(),
    INTERVAL '1 hour'
  ) AS ts
) AS hours;
