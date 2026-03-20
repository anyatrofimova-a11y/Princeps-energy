-- Decision engine — versioned assessments with evidence
-- Run: psql -d feasibly -f sql/migrate_decisions.sql

CREATE TABLE IF NOT EXISTS assessment_snapshots (
    snapshot_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_id     UUID NOT NULL REFERENCES parcels(parcel_id),
    project_id    UUID REFERENCES projects(project_id),
    user_id       UUID REFERENCES users(user_id),
    version       INTEGER NOT NULL DEFAULT 1,
    label         TEXT,
    overall_verdict TEXT,
    overall_confidence FLOAT8,
    intent_verdicts JSONB DEFAULT '{}',
    site_data     JSONB DEFAULT '{}',
    metadata      JSONB DEFAULT '{}',
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(parcel_id, version)
);

CREATE TABLE IF NOT EXISTS assessment_evidence (
    evidence_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id   UUID NOT NULL REFERENCES assessment_snapshots(snapshot_id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,
    title         TEXT,
    content_ref   TEXT,
    content_data  JSONB,
    created_by    UUID REFERENCES users(user_id),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_evidence_snapshot ON assessment_evidence(snapshot_id);

CREATE TABLE IF NOT EXISTS assessment_comparisons (
    comparison_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_a    UUID NOT NULL REFERENCES assessment_snapshots(snapshot_id),
    snapshot_b    UUID NOT NULL REFERENCES assessment_snapshots(snapshot_id),
    diff_data     JSONB,
    notes         TEXT,
    created_by    UUID REFERENCES users(user_id),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
