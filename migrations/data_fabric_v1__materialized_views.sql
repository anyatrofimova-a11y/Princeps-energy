-- Princeps Data Fabric v1 — live materialized views + Postgres LISTEN/NOTIFY plumbing.
-- Idempotent (CREATE IF NOT EXISTS / OR REPLACE) — safe to re-run.
--
-- Depends on: existing grid_substations table (PostGIS, SRID 27700).
-- Future: RID columns from Swarm 1 will replace the ad-hoc `id` join key.

-- ---------- 1. Streamed BMRS landing table -----------------------------
CREATE TABLE IF NOT EXISTS demand_historical_stream (
    id                BIGSERIAL PRIMARY KEY,
    settlement_date   DATE        NOT NULL,
    settlement_period SMALLINT    NOT NULL,
    demand_mw         DOUBLE PRECISION,
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (settlement_date, settlement_period)
);
CREATE INDEX IF NOT EXISTS demand_historical_stream_ingested_idx
    ON demand_historical_stream (ingested_at DESC);


-- ---------- 2. Substation telemetry landing table ----------------------
CREATE TABLE IF NOT EXISTS grid_telemetry (
    id              BIGSERIAL PRIMARY KEY,
    substation_id   TEXT             NOT NULL,
    utilisation_pct DOUBLE PRECISION,
    headroom_mw     DOUBLE PRECISION,
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS grid_telemetry_sub_updated_idx
    ON grid_telemetry (substation_id, updated_at DESC);


-- ---------- 3. Materialized view: live_grid_state ----------------------
-- Latest telemetry per substation, joined with PostGIS geometry for map use.
DROP MATERIALIZED VIEW IF EXISTS live_grid_state;
CREATE MATERIALIZED VIEW live_grid_state AS
SELECT
    s.id                AS substation_id,
    s.name,
    s.geom,
    latest.utilisation_pct,
    latest.headroom_mw,
    latest.updated_at
FROM grid_substations s
LEFT JOIN LATERAL (
    SELECT utilisation_pct, headroom_mw, updated_at
    FROM grid_telemetry t
    WHERE t.substation_id = s.id::text
    ORDER BY t.updated_at DESC
    LIMIT 1
) latest ON TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS live_grid_state_substation_idx
    ON live_grid_state (substation_id);


-- ---------- 4. LISTEN/NOTIFY trigger -----------------------------------
-- Telemetry inserts/updates fire `grid_state_change` so subscribed
-- FastAPI WS clients can refetch the view (or the changed row).
CREATE OR REPLACE FUNCTION notify_grid_state_change()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify(
        'grid_state_change',
        json_build_object(
            'substation_id',   NEW.substation_id,
            'utilisation_pct', NEW.utilisation_pct,
            'headroom_mw',     NEW.headroom_mw,
            'updated_at',      NEW.updated_at
        )::text
    );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS grid_telemetry_notify ON grid_telemetry;
CREATE TRIGGER grid_telemetry_notify
    AFTER INSERT OR UPDATE ON grid_telemetry
    FOR EACH ROW EXECUTE FUNCTION notify_grid_state_change();


-- ---------- 5. Refresher functions -------------------------------------
-- Call from a cron / background task. CONCURRENTLY needs the unique index
-- above and avoids an exclusive lock on the view.
CREATE OR REPLACE FUNCTION refresh_live_grid_state()
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY live_grid_state;
END;
$$;


-- ---------- 6. Demand stream change notification -----------------------
CREATE OR REPLACE FUNCTION notify_demand_arrival()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify(
        'demand_stream_arrival',
        json_build_object(
            'settlement_date',   NEW.settlement_date,
            'settlement_period', NEW.settlement_period,
            'demand_mw',         NEW.demand_mw
        )::text
    );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS demand_stream_notify ON demand_historical_stream;
CREATE TRIGGER demand_stream_notify
    AFTER INSERT ON demand_historical_stream
    FOR EACH ROW EXECUTE FUNCTION notify_demand_arrival();
