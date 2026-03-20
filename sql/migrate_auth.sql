-- Auth, Users & Projects migration
-- Run: psql -d feasibly -f sql/migrate_auth.sql

CREATE TABLE IF NOT EXISTS users (
    user_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT UNIQUE NOT NULL,
    name        TEXT,
    org_name    TEXT,
    password_hash TEXT NOT NULL,
    role        TEXT DEFAULT 'analyst',
    api_key     TEXT UNIQUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    last_login  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS projects (
    project_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(user_id),
    name        TEXT NOT NULL,
    description TEXT,
    status      TEXT DEFAULT 'active',
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS project_sites (
    project_id  UUID NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    parcel_id   UUID NOT NULL REFERENCES parcels(parcel_id),
    added_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (project_id, parcel_id)
);

CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_project_sites_parcel ON project_sites(parcel_id);
