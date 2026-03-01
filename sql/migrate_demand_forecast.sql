-- Demand Forecasting module — Princeps
-- Phase 5: Historical demand storage + probabilistic forecasts

-- ─── Historical demand (national & GSP-level, 30-min resolution) ────────────
CREATE TABLE IF NOT EXISTS demand_historical (
    id              BIGSERIAL PRIMARY KEY,
    gsp_id          TEXT NOT NULL,           -- 'national' or GSP identifier
    gsp_name        TEXT,
    timestamp_utc   TIMESTAMPTZ NOT NULL,
    demand_mw       NUMERIC NOT NULL,
    generation_mw   NUMERIC,                 -- embedded generation at GSP
    net_demand_mw   NUMERIC,                 -- demand minus embedded gen
    source          TEXT DEFAULT 'bmrs',      -- bmrs, dno, synthetic
    raw_data        JSONB,
    UNIQUE (gsp_id, timestamp_utc)
);
CREATE INDEX IF NOT EXISTS idx_demand_hist_gsp_ts
    ON demand_historical (gsp_id, timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_demand_hist_ts
    ON demand_historical (timestamp_utc DESC);

-- ─── GSP profiles (metadata per grid supply point) ──────────────────────────
CREATE TABLE IF NOT EXISTS gsp_profiles (
    id              SERIAL PRIMARY KEY,
    gsp_id          TEXT UNIQUE NOT NULL,
    gsp_name        TEXT NOT NULL,
    dno             TEXT,                     -- ukpn, nged, ssen, npg, spen, enwl
    region          TEXT,
    voltage_kv      NUMERIC,
    peak_demand_mw  NUMERIC,
    min_demand_mw   NUMERIC,
    capacity_mw     NUMERIC,                  -- transformer / firm capacity
    embedded_gen_mw NUMERIC,
    geom            GEOMETRY(Point, 27700),
    raw_data        JSONB,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gsp_profiles_geom
    ON gsp_profiles USING GIST(geom);

-- ─── Demand forecasts (probabilistic, per GSP) ─────────────────────────────
CREATE TABLE IF NOT EXISTS demand_forecasts (
    id              BIGSERIAL PRIMARY KEY,
    gsp_id          TEXT NOT NULL,
    model_type      TEXT NOT NULL,            -- prophet, tft, ensemble
    scenario        TEXT DEFAULT 'baseline',  -- baseline, leading_the_way, consumer_transformation, system_transformation, falling_short
    horizon_hours   INTEGER NOT NULL,         -- hours ahead from forecast_from
    forecast_from   TIMESTAMPTZ NOT NULL,
    timestamp_utc   TIMESTAMPTZ NOT NULL,     -- forecast target time
    p10_mw          NUMERIC NOT NULL,
    p50_mw          NUMERIC NOT NULL,
    p90_mw          NUMERIC NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_demand_fc_gsp_ts
    ON demand_forecasts (gsp_id, scenario, timestamp_utc DESC);

-- ─── Scenario parameters (NESO FES pathways + custom) ───────────────────────
CREATE TABLE IF NOT EXISTS demand_scenarios (
    id              SERIAL PRIMARY KEY,
    scenario_name   TEXT UNIQUE NOT NULL,     -- leading_the_way, consumer_transformation, etc.
    description     TEXT,
    ev_growth_rate  NUMERIC,                  -- annual % growth in EV demand
    hp_growth_rate  NUMERIC,                  -- annual % growth in heat pump demand
    solar_growth_rate NUMERIC,                -- annual % growth in embedded solar
    dc_growth_rate  NUMERIC,                  -- annual % growth in data centre demand
    base_year       INTEGER DEFAULT 2024,
    parameters      JSONB,                    -- full parameter set
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Seed NESO FES 2024 scenarios
INSERT INTO demand_scenarios (scenario_name, description, ev_growth_rate, hp_growth_rate, solar_growth_rate, dc_growth_rate, parameters)
VALUES
    ('baseline', 'Current trends extrapolated', 0.15, 0.08, 0.12, 0.20,
     '{"peak_demand_2030_gw": 62, "peak_demand_2035_gw": 68, "peak_demand_2050_gw": 78}'),
    ('leading_the_way', 'NESO FES: fastest decarbonisation, high electrification', 0.28, 0.18, 0.20, 0.30,
     '{"peak_demand_2030_gw": 65, "peak_demand_2035_gw": 78, "peak_demand_2050_gw": 100}'),
    ('consumer_transformation', 'NESO FES: consumer-led, high flexibility', 0.25, 0.15, 0.18, 0.25,
     '{"peak_demand_2030_gw": 63, "peak_demand_2035_gw": 73, "peak_demand_2050_gw": 92}'),
    ('system_transformation', 'NESO FES: supply-side hydrogen focus', 0.20, 0.10, 0.15, 0.22,
     '{"peak_demand_2030_gw": 61, "peak_demand_2035_gw": 70, "peak_demand_2050_gw": 85}'),
    ('falling_short', 'NESO FES: slowest progress', 0.10, 0.05, 0.08, 0.15,
     '{"peak_demand_2030_gw": 58, "peak_demand_2035_gw": 62, "peak_demand_2050_gw": 68}')
ON CONFLICT (scenario_name) DO NOTHING;
