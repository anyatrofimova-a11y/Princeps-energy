-- ──────────────────────────────────────────────────────────────────────
-- Cluster dependency graph — models the UK transmission connection queue
-- as a graph where every project in a shared cluster study is linked to
-- the network upgrades it has been allocated costs for. When a project
-- withdraws, siblings' allocated upgrade costs must be recomputed.
-- ──────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cluster_studies (
    study_id            TEXT PRIMARY KEY,
    dno                 TEXT,
    region              TEXT,
    gsp_code            TEXT,
    study_type          TEXT DEFAULT 'group',   -- 'group' | 'single' | 'iso'
    initiated_date      DATE,
    status              TEXT DEFAULT 'active',  -- 'active' | 'complete' | 'demo'
    total_upgrade_cost_gbp NUMERIC,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cluster_studies_gsp ON cluster_studies (gsp_code);
CREATE INDEX IF NOT EXISTS idx_cluster_studies_dno ON cluster_studies (dno);

CREATE TABLE IF NOT EXISTS network_upgrades (
    upgrade_id          SERIAL PRIMARY KEY,
    study_id            TEXT REFERENCES cluster_studies(study_id) ON DELETE CASCADE,
    upgrade_type        TEXT DEFAULT 'generic', -- 'substation_extension','transformer','line_reinforcement','protection','new_build','generic'
    voltage_kv          NUMERIC,
    description         TEXT,
    estimated_cost_gbp  NUMERIC,
    location_geom       GEOMETRY(Point, 27700),
    status              TEXT DEFAULT 'planned',
    completion_date     DATE,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_upgrades_study ON network_upgrades (study_id);
CREATE INDEX IF NOT EXISTS idx_upgrades_geom  ON network_upgrades USING GIST (location_geom);

CREATE TABLE IF NOT EXISTS project_upgrade_allocations (
    allocation_id       SERIAL PRIMARY KEY,
    project_id          TEXT NOT NULL,
    upgrade_id          INTEGER REFERENCES network_upgrades(upgrade_id) ON DELETE CASCADE,
    study_id            TEXT REFERENCES cluster_studies(study_id) ON DELETE CASCADE,
    allocation_method   TEXT DEFAULT 'pro_rata_capacity', -- 'pro_rata_capacity','proportional_use','equal_share','fixed'
    allocation_fraction NUMERIC,
    allocated_cost_gbp  NUMERIC,
    allocated_at        TIMESTAMPTZ DEFAULT now(),
    valid_until         TIMESTAMPTZ,
    is_current          BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_alloc_project_current ON project_upgrade_allocations (project_id, is_current);
CREATE INDEX IF NOT EXISTS idx_alloc_upgrade_current ON project_upgrade_allocations (upgrade_id, is_current);
CREATE INDEX IF NOT EXISTS idx_alloc_study   ON project_upgrade_allocations (study_id);

CREATE TABLE IF NOT EXISTS cluster_dependencies (
    edge_id             SERIAL PRIMARY KEY,
    from_project_id     TEXT NOT NULL,
    to_project_id       TEXT NOT NULL,
    shared_upgrade_id   INTEGER REFERENCES network_upgrades(upgrade_id) ON DELETE CASCADE,
    study_id            TEXT,
    shared_cost_gbp     NUMERIC,
    dependency_strength NUMERIC,   -- 0..1
    computed_at         TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_deps_from  ON cluster_dependencies (from_project_id);
CREATE INDEX IF NOT EXISTS idx_deps_to    ON cluster_dependencies (to_project_id);
CREATE INDEX IF NOT EXISTS idx_deps_study ON cluster_dependencies (study_id);
