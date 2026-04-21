-- =============================================================================
-- 0017_dno_engagement_workflow.sql
-- -----------------------------------------------------------------------------
-- Princeps — DNO engagement workflow: every time a project team sends a
-- structured engagement pack to a DNO, we version it and (later) track the
-- response. This lets Princeps surface "what have we actually asked the DNO
-- for, and what did they say" at pipeline-column granularity.
--
-- Scope notes:
--   * Princeps is NOT the sender of email — mailto: handoff only per council
--     decision. `sent_at` / `sent_by` / `recipient_email` are populated from
--     the client-side "I've sent it" confirm step, not an SMTP relay.
--   * Phase 7f may add inbound `engage-{uuid}@princeps.energy` via Postmark —
--     schema supports that via `dno_engagement_responses.channel='email'` and
--     `raw_body` / `raw_pdf_path`.
--   * The PDF itself is rendered by a sibling engine package
--     (`utils/dno_engagement/`) and stored on disk under `data/dno_engagement/`
--     — this table only holds the sha256 fingerprint + a path pointer.
--
-- Idempotent: safe to re-run on warm starts. Wired in via app/db_setup.py.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- ── project_dno_engagements ────────────────────────────────────────────────
-- One row per (project, pack_version). Status tracks the lifecycle — every
-- version is immutable once `status='sent'` (a revised pack increments the
-- version and carries the prior row to `status='superseded'`).
CREATE TABLE IF NOT EXISTS project_dno_engagements (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id           uuid NOT NULL,
    tenant_id            uuid,
    dno_slug             text NOT NULL,
    pack_version         integer NOT NULL DEFAULT 1,
    pdf_sha256           text NOT NULL,
    pdf_path             text,
    sent_at              timestamptz,
    sent_by              uuid,
    recipient_email      text,
    status               text CHECK (status IN (
                             'drafting', 'previewing', 'sent',
                             'responded', 'withdrawn', 'superseded'
                         )) DEFAULT 'drafting',
    structured_snapshot  jsonb,
    created_at           timestamptz DEFAULT now(),
    updated_at           timestamptz DEFAULT now(),
    UNIQUE (project_id, pack_version)
);

-- Project-scoped status lookups power the pipeline chip + EngagementsIndex.
CREATE INDEX IF NOT EXISTS idx_project_dno_engagements_project_status
    ON project_dno_engagements (project_id, status);

-- Tenant-scoped time ordering powers the Intelligence tab's "recent sends"
-- view and the days_since_sent aggregation.
CREATE INDEX IF NOT EXISTS idx_project_dno_engagements_tenant_sent
    ON project_dno_engagements (tenant_id, sent_at DESC);

-- Keep updated_at fresh on row updates (no trigger on insert — DEFAULT covers).
CREATE OR REPLACE FUNCTION _touch_project_dno_engagements_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_project_dno_engagements_touch
    ON project_dno_engagements;
CREATE TRIGGER trg_project_dno_engagements_touch
    BEFORE UPDATE ON project_dno_engagements
    FOR EACH ROW EXECUTE FUNCTION _touch_project_dno_engagements_updated_at();


-- ── dno_engagement_responses ───────────────────────────────────────────────
-- Many rows per engagement — a DNO can send a holding ack, then a formal
-- response, then clarifications. Each response is parsed (Claude) into
-- `structured_extract` and can optionally trigger a verdict recompute
-- on the parent project.
CREATE TABLE IF NOT EXISTS dno_engagement_responses (
    id                            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id                 uuid NOT NULL
        REFERENCES project_dno_engagements(id) ON DELETE CASCADE,
    received_at                   timestamptz DEFAULT now(),
    channel                       text CHECK (channel IN (
                                      'email', 'upload', 'api', 'manual'
                                  )) NOT NULL,
    raw_body                      text,
    raw_pdf_path                  text,
    structured_extract            jsonb,
    acknowledgement_sent_at       timestamptz,
    triggered_verdict_recompute   boolean DEFAULT false
);

-- Engagement-scoped reverse-chronological lookups power the response
-- history card on the EngagementsIndex detail drawer.
CREATE INDEX IF NOT EXISTS idx_dno_engagement_responses_engagement_received
    ON dno_engagement_responses (engagement_id, received_at DESC);
