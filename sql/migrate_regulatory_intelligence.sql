-- Regulatory Intelligence & Structured Asset Tracking
-- Phase 1: Database Migration — 7 new tables + 1 alert table pair
-- Run idempotently via CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS

-- ===========================================================================
-- 1. REPD — Renewable Energy Planning Database (gov.uk monthly extract)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS repd_projects (
    repd_id            TEXT PRIMARY KEY,
    site_name          TEXT,
    technology         TEXT,
    tech_category      TEXT,          -- solar / bess / wind / biomass / other
    capacity_mw        DOUBLE PRECISION,
    status             TEXT,
    developer          TEXT,
    operator           TEXT,
    planning_authority TEXT,
    planning_ref       TEXT,
    address            TEXT,
    county             TEXT,
    region             TEXT,
    country            TEXT,
    postcode           TEXT,
    mounting_type      TEXT,
    height_m           DOUBLE PRECISION,
    turbines           INTEGER,
    battery_mwh        DOUBLE PRECISION,
    co_located         BOOLEAN DEFAULT FALSE,
    appeal_ref         TEXT,
    date_submitted     DATE,
    date_decided       DATE,
    date_operational   DATE,
    planning_url       TEXT,
    metadata           JSONB DEFAULT '{}',
    geometry           GEOMETRY(Point, 27700),
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_repd_geom          ON repd_projects USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_repd_tech_category  ON repd_projects (tech_category);
CREATE INDEX IF NOT EXISTS idx_repd_status         ON repd_projects (status);
CREATE INDEX IF NOT EXISTS idx_repd_developer      ON repd_projects (developer);
CREATE INDEX IF NOT EXISTS idx_repd_region         ON repd_projects (region);

-- ===========================================================================
-- 2. ESO TEC Register — grid connection queue
-- ===========================================================================
CREATE TABLE IF NOT EXISTS eso_tec_register (
    tec_id             TEXT PRIMARY KEY,
    customer_name      TEXT,
    connection_site    TEXT,
    fuel_type          TEXT,
    tech_category      TEXT,          -- solar / bess / wind / gas / other
    tec_mw             DOUBLE PRECISION,
    status             TEXT,
    effective_from     DATE,
    effective_to       DATE,
    connection_date    DATE,
    voltage_kv         DOUBLE PRECISION,
    zone               TEXT,
    dnc_mw             DOUBLE PRECISION,
    spv_name           TEXT,
    parent_company     TEXT,
    queue_position     INTEGER,
    metadata           JSONB DEFAULT '{}',
    geometry           GEOMETRY(Point, 27700),
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tec_geom            ON eso_tec_register USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_tec_tech_category    ON eso_tec_register (tech_category);
CREATE INDEX IF NOT EXISTS idx_tec_status           ON eso_tec_register (status);
CREATE INDEX IF NOT EXISTS idx_tec_connection_site  ON eso_tec_register (connection_site);

-- ===========================================================================
-- 3. Grid Upgrades — DNO network investment projects
-- ===========================================================================
CREATE TABLE IF NOT EXISTS grid_upgrades (
    upgrade_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_ref         TEXT UNIQUE,
    dno                TEXT,
    project_name       TEXT,
    project_type       TEXT,
    voltage_kv         DOUBLE PRECISION,
    capex_gbp          DOUBLE PRECISION,
    status             TEXT,
    start_date         DATE,
    completion_date    DATE,
    riio_period        TEXT,
    constraint_area    TEXT,
    capacity_released_mw DOUBLE PRECISION,
    description        TEXT,
    metadata           JSONB DEFAULT '{}',
    geometry           GEOMETRY(Geometry, 27700),
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_grid_upgrades_geom  ON grid_upgrades USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_grid_upgrades_dno   ON grid_upgrades (dno);
CREATE INDEX IF NOT EXISTS idx_grid_upgrades_status ON grid_upgrades (status);

-- ===========================================================================
-- 4. DNO Investment Plans — RIIO-ED2 programme-level deliverables
-- ===========================================================================
CREATE TABLE IF NOT EXISTS dno_investment_plans (
    plan_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dno                TEXT NOT NULL,
    programme          TEXT,
    riio_period        TEXT,
    total_capex_gbp    DOUBLE PRECISION,
    spend_to_date_gbp  DOUBLE PRECISION,
    target_year        INTEGER,
    deliverable_count  INTEGER,
    delivered_count    INTEGER,
    description        TEXT,
    kpis               JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dno_plans_dno ON dno_investment_plans (dno);

-- ===========================================================================
-- 5. RAG Documents — regulatory document store
-- ===========================================================================
CREATE TABLE IF NOT EXISTS rag_documents (
    doc_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source             TEXT,          -- ofgem / desnz / beis / etc.
    title              TEXT,
    url                TEXT,
    published_date     DATE,
    doc_type           TEXT,          -- decision / consultation / guidance / licence_condition
    body_text          TEXT,
    page_count         INTEGER,
    file_hash          TEXT,
    metadata           JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_docs_hash ON rag_documents (file_hash);

-- ===========================================================================
-- 6. RAG Chunks — chunked documents with vector embeddings
-- ===========================================================================
CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id             UUID REFERENCES rag_documents(doc_id) ON DELETE CASCADE,
    chunk_index        INTEGER NOT NULL,
    content            TEXT NOT NULL,
    token_count        INTEGER,
    embedding          vector(384),
    metadata           JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc ON rag_chunks (doc_id);

-- IVFFlat index for cosine similarity KNN (deferred if <100 rows)
-- CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding
--   ON rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- ===========================================================================
-- 7. Notifications & Alert Rules
-- ===========================================================================
CREATE TABLE IF NOT EXISTS notifications (
    notification_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            TEXT DEFAULT 'default',
    alert_type         TEXT,          -- new_planning / tec_change / dno_update / new_consultation
    title              TEXT NOT NULL,
    body               TEXT,
    severity           TEXT DEFAULT 'info',  -- info / warning / critical
    source_ref         TEXT,
    source_url         TEXT,
    site_id            UUID,
    read               BOOLEAN DEFAULT FALSE,
    metadata           JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_user   ON notifications (user_id, read);
CREATE INDEX IF NOT EXISTS idx_notifications_type   ON notifications (alert_type);

CREATE TABLE IF NOT EXISTS alert_rules (
    rule_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            TEXT DEFAULT 'default',
    rule_type          TEXT NOT NULL,  -- nearby_planning / tec_change / dno_constraint / new_regulation
    enabled            BOOLEAN DEFAULT TRUE,
    config             JSONB DEFAULT '{}',
    site_id            UUID,
    lat                DOUBLE PRECISION,
    lon                DOUBLE PRECISION,
    radius_km          DOUBLE PRECISION DEFAULT 10,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_rules_user ON alert_rules (user_id, enabled);
