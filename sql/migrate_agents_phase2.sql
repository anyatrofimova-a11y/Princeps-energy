-- migrate_agents_phase2.sql
-- Additions for the second wave of agents:
--   * coordination layer (missions)
--   * planning_monitor      (planning_watches, planning_alerts)
--   * market_intel          (market_signals, market_digests)
--
-- The builder agent does NOT need new tables — it only writes to agent_runs
-- (via BaseAgent) and missions (via the coordination layer).
--
-- Idempotent — safe to re-run.

-- ── Missions (shared coordination log) ─────────────────────────────────────
-- One row per agent invocation that opts into the Coordinator context.
-- touches_paths / touches_tables power cross-mission conflict detection.
CREATE TABLE IF NOT EXISTS missions (
    mission_id         text PRIMARY KEY,
    agent_name         text NOT NULL,
    goal               text,
    action_station     text NOT NULL DEFAULT 'stations',
    touches_paths      text[] NOT NULL DEFAULT '{}',
    touches_tables     text[] NOT NULL DEFAULT '{}',
    orders_json        jsonb,
    status             text NOT NULL DEFAULT 'running',
    summary            text,
    outcome            jsonb,
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz
);
CREATE INDEX IF NOT EXISTS missions_running
    ON missions (status)
    WHERE status = 'running';
CREATE INDEX IF NOT EXISTS missions_agent_started
    ON missions (agent_name, started_at DESC);
CREATE INDEX IF NOT EXISTS missions_tables_gin
    ON missions USING gin (touches_tables);

-- ── Planning monitor ────────────────────────────────────────────────────────
-- User-saved watches (AOI + tech + radius). Populated via web UI; the agent
-- is read-only against this table.
CREATE TABLE IF NOT EXISTS planning_watches (
    id                 bigserial PRIMARY KEY,
    user_id            uuid,
    name               text NOT NULL,
    tech               text NOT NULL,              -- solar | bess | dc | wind
    capacity_mw        numeric(8, 2),
    aoi                geometry(Geometry, 27700) NOT NULL,
    radius_km          numeric(5, 1) NOT NULL DEFAULT 5,
    constraints        jsonb DEFAULT '[]'::jsonb,
    active             boolean NOT NULL DEFAULT true,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS planning_watches_active
    ON planning_watches (active) WHERE active;
CREATE INDEX IF NOT EXISTS planning_watches_aoi_gix
    ON planning_watches USING gist (aoi);

-- Alerts emitted by PlanningMonitorAgent. One row per (watch, application).
CREATE TABLE IF NOT EXISTS planning_alerts (
    id                 bigserial PRIMARY KEY,
    user_id            uuid,
    watch_id           bigint NOT NULL REFERENCES planning_watches(id) ON DELETE CASCADE,
    application_id     text NOT NULL,
    relevance          smallint NOT NULL DEFAULT 0,
    threat_level       text NOT NULL DEFAULT 'low',
    reasoning          text,
    action             text NOT NULL DEFAULT 'watch',
    data               jsonb,
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (watch_id, application_id)
);
CREATE INDEX IF NOT EXISTS planning_alerts_user_time
    ON planning_alerts (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS planning_alerts_threat
    ON planning_alerts (threat_level, created_at DESC);

-- ── Market intel ────────────────────────────────────────────────────────────
-- Signals scouted from regulator / SO / govt sources.
CREATE TABLE IF NOT EXISTS market_signals (
    id                 bigserial PRIMARY KEY,
    source_name        text NOT NULL,
    source_category    text,
    source_url         text,
    type               text,
    title              text NOT NULL,
    summary            text,
    published_date     date,
    impact_areas       jsonb DEFAULT '[]'::jsonb,
    severity           text DEFAULT 'low',
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_name, title)
);
CREATE INDEX IF NOT EXISTS market_signals_recent
    ON market_signals (created_at DESC);
CREATE INDEX IF NOT EXISTS market_signals_severity
    ON market_signals (severity, created_at DESC);

-- Weekly synthesised digests from market_intel in digest mode.
CREATE TABLE IF NOT EXISTS market_digests (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    headline           text,
    body               jsonb,
    window_days        integer NOT NULL DEFAULT 7,
    review             jsonb,
    verified           boolean NOT NULL DEFAULT false,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS market_digests_recent
    ON market_digests (created_at DESC);
