-- Pipeline project management — extends projects table with pipeline fields
-- Run: psql -d feasibly -f sql/migrate_pipeline.sql

-- Add pipeline-specific columns to existing projects table
ALTER TABLE projects ADD COLUMN IF NOT EXISTS technology TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS capacity_mw DOUBLE PRECISION;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS stage TEXT DEFAULT 'prospect';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS verdict TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS blocker TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS stage_entered_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE projects ADD COLUMN IF NOT EXISTS repd_id TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS tec_id TEXT;

CREATE INDEX IF NOT EXISTS idx_projects_stage ON projects(stage);
CREATE INDEX IF NOT EXISTS idx_projects_technology ON projects(technology);

-- Stage history for audit trail
CREATE TABLE IF NOT EXISTS project_stage_history (
    history_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   UUID NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    from_stage   TEXT,
    to_stage     TEXT NOT NULL,
    changed_by   UUID REFERENCES users(user_id),
    notes        TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_stage_history_project ON project_stage_history(project_id);

-- Make user_id nullable (supports unauthenticated project creation)
ALTER TABLE projects ALTER COLUMN user_id DROP NOT NULL;

-- Document storage per project
CREATE TABLE IF NOT EXISTS project_documents (
    doc_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    UUID NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    doc_type      TEXT DEFAULT 'other',
    title         TEXT,
    filename      TEXT NOT NULL,
    content_type  TEXT,
    size_bytes    INTEGER,
    storage_path  TEXT NOT NULL,
    uploaded_by   UUID REFERENCES users(user_id),
    metadata      JSONB DEFAULT '{}',
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_documents_project ON project_documents(project_id);
