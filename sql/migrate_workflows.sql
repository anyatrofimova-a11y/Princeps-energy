-- Workflow engine — persistent, customizable workflows
-- Run: psql -d feasibly -f sql/migrate_workflows.sql

CREATE TABLE IF NOT EXISTS workflow_templates (
    template_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(user_id),
    name        TEXT NOT NULL,
    description TEXT,
    steps       JSONB NOT NULL,
    is_system   BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID REFERENCES workflow_templates(template_id),
    user_id     UUID REFERENCES users(user_id),
    parcel_id   UUID REFERENCES parcels(parcel_id),
    project_id  UUID REFERENCES projects(project_id),
    status      TEXT DEFAULT 'pending',
    current_step INTEGER DEFAULT 0,
    steps_completed JSONB DEFAULT '[]',
    overall_verdict TEXT,
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_project ON workflow_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_user ON workflow_runs(user_id);
