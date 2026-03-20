-- Persistent state migration — sessions, jobs, verdicts
-- Run: psql -d feasibly -f sql/migrate_persistence.sql

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id  TEXT PRIMARY KEY,
    user_id     UUID REFERENCES users(user_id),
    parcel_id   UUID REFERENCES parcels(parcel_id),
    title       TEXT,
    messages    JSONB DEFAULT '[]',
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS background_jobs (
    job_id      TEXT PRIMARY KEY,
    user_id     UUID REFERENCES users(user_id),
    kind        TEXT NOT NULL,
    status      TEXT DEFAULT 'pending',
    result_data JSONB,
    error       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_jobs_user_status ON background_jobs(user_id, status);

CREATE TABLE IF NOT EXISTS agent_analyses (
    analysis_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(user_id),
    parcel_id   UUID REFERENCES parcels(parcel_id),
    project_id  UUID REFERENCES projects(project_id),
    intent      TEXT NOT NULL,
    verdict     TEXT NOT NULL,
    confidence  FLOAT8,
    summary     TEXT,
    risks       JSONB DEFAULT '[]',
    opportunities JSONB DEFAULT '[]',
    result_data JSONB,
    model       TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    elapsed_s   FLOAT8,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_analyses_parcel ON agent_analyses(parcel_id, intent);
CREATE INDEX IF NOT EXISTS idx_analyses_project ON agent_analyses(project_id);
