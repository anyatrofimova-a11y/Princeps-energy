-- ──────────────────────────────────────────────────────────────────────
-- Grid events, alert rules, notifications, portfolio snapshots.
-- Supports the Pulse "live intelligence" capability set.
-- ──────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS grid_events (
    event_id       BIGSERIAL PRIMARY KEY,
    event_type     TEXT NOT NULL,           -- withdrawal | new_offer | restudy | cost_reallocation | energisation | cluster_recompute | substation_headroom_change | new_constraint | regulatory
    severity       TEXT NOT NULL DEFAULT 'info',  -- info | warn | critical
    project_id     TEXT,
    substation_id  TEXT,
    upgrade_id     INTEGER,
    payload        JSONB,
    source         TEXT,
    detected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    observed_at    TIMESTAMPTZ,
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_grid_events_project_time  ON grid_events (project_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_grid_events_type_time     ON grid_events (event_type, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_grid_events_severity_time ON grid_events (severity, detected_at DESC);


CREATE TABLE IF NOT EXISTS alert_rules (
    rule_id        SERIAL PRIMARY KEY,
    user_id        TEXT DEFAULT 'default',
    name           TEXT,
    project_scope  TEXT DEFAULT 'owned',   -- owned | cluster_neighbours | all | by_region | by_technology
    scope_value    TEXT,
    event_types    TEXT[],
    min_severity   TEXT DEFAULT 'info',
    channels       TEXT[] DEFAULT ARRAY['inapp'],
    enabled        BOOLEAN DEFAULT TRUE,
    created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alert_rules_user ON alert_rules (user_id, enabled);


CREATE TABLE IF NOT EXISTS notifications (
    notification_id BIGSERIAL PRIMARY KEY,
    user_id         TEXT,
    rule_id         INTEGER REFERENCES alert_rules(rule_id) ON DELETE SET NULL,
    event_id        BIGINT REFERENCES grid_events(event_id) ON DELETE CASCADE,
    title           TEXT,
    body            TEXT,
    read            BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications (user_id, read, created_at DESC);


CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_id     BIGSERIAL PRIMARY KEY,
    taken_at        DATE NOT NULL,
    project_id      TEXT NOT NULL,
    metrics         JSONB,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (taken_at, project_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_project_time ON portfolio_snapshots (project_id, taken_at DESC);


-- Diff snapshot tables (internal)
CREATE TABLE IF NOT EXISTS tec_register_snapshot (
    tec_id        TEXT PRIMARY KEY,
    hash          TEXT,
    status        TEXT,
    tec_mw        NUMERIC,
    offer_date    DATE,
    last_seen     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS substation_snapshot (
    substation_id   TEXT PRIMARY KEY,
    headroom_mw     NUMERIC,
    hash            TEXT,
    last_seen       TIMESTAMPTZ DEFAULT now()
);
