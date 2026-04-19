-- migrate_agents_phase2_hotfix.sql
-- Fills in tables referenced by Phase 1 agents (grid_monitor, ingestion,
-- report) but missing from the deployed schema. All stubs are safe to
-- populate later via the relevant ingester / web flow.
--
-- Idempotent — safe to re-run.

-- ── grid_monitor dependencies ──────────────────────────────────────────────
-- Canonical substation table queried by GridMonitorAgent. In production
-- this should be populated by a union / refresh job over the DNO-specific
-- tables (nged_substation, osm_power_substation, etc.). For now it's an
-- empty table so the agent returns 0 changes instead of crashing.
CREATE TABLE IF NOT EXISTS grid_substations (
    substation_id     text PRIMARY KEY,
    name              text NOT NULL,
    dno               text,
    voltage_kv        numeric(6, 1),
    capacity_mva      numeric(10, 2),
    headroom_mw       numeric(10, 2),
    geometry          geometry(Point, 27700),
    source            text,
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS grid_substations_updated_at
    ON grid_substations (updated_at DESC);
CREATE INDEX IF NOT EXISTS grid_substations_dno
    ON grid_substations (dno);
CREATE INDEX IF NOT EXISTS grid_substations_geom
    ON grid_substations USING gist (geometry);

-- Embedded Capacity Register entries (queue + allocated projects).
CREATE TABLE IF NOT EXISTS grid_ecr (
    id                bigserial PRIMARY KEY,
    substation_id     text REFERENCES grid_substations(substation_id) ON DELETE SET NULL,
    dno               text,
    customer          text,
    technology        text,
    capacity_mw       numeric(10, 2),
    status            text,                     -- accepted, energised, queued, withdrawn
    connection_date   date,
    data              jsonb DEFAULT '{}'::jsonb,
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS grid_ecr_substation_status
    ON grid_ecr (substation_id, status);
CREATE INDEX IF NOT EXISTS grid_ecr_updated_at
    ON grid_ecr (updated_at DESC);

-- Periodic snapshots of substation state. GridMonitorAgent diffs
-- consecutive rows to detect headroom / queue changes.
CREATE TABLE IF NOT EXISTS grid_snapshots (
    id                bigserial PRIMARY KEY,
    substation_id     text NOT NULL,
    capacity_mva      numeric(10, 2),
    headroom_mw       numeric(10, 2),
    queue_mw          numeric(10, 2),
    voltage_kv        numeric(6, 1),
    snapshot_at       timestamptz NOT NULL DEFAULT now(),
    data              jsonb DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS grid_snapshots_station_time
    ON grid_snapshots (substation_id, snapshot_at DESC);

-- ── report dependencies ───────────────────────────────────────────────────
-- Minimal users table. The auth-bearing user table may already live
-- elsewhere; this is a lightweight reference for ReportAgent's join and
-- will be superseded if a richer table is introduced.
CREATE TABLE IF NOT EXISTS users (
    user_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email             text UNIQUE,
    name              text,
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- Per-user preferences (weekly report opt-in, digest cadence, etc.).
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id                  uuid PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    weekly_report_enabled    boolean NOT NULL DEFAULT false,
    slack_dm_enabled         boolean NOT NULL DEFAULT false,
    timezone                 text DEFAULT 'Europe/London',
    updated_at               timestamptz NOT NULL DEFAULT now()
);
