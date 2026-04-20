-- =============================================================================
-- 0011_site_memos.sql
-- -----------------------------------------------------------------------------
-- Princeps — AI Site Memo persistence.
--
-- Each generation of a one-page investment memo is versioned per project so
-- investment-committee trails can be reconstructed deterministically. The
-- ``memo_json`` column stores the validated JSON emitted by the composer
-- (schema in utils/site_memo/memo_composer.py::MEMO_SCHEMA). ``pdf_path`` is
-- a filesystem path — PDFs live under ``data/site_memos/`` by default so we
-- can move to S3 later without table changes.
--
-- Idempotent: safe to re-run.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;


CREATE TABLE IF NOT EXISTS site_memos (
    memo_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     uuid NOT NULL,
    version        integer NOT NULL,
    memo_json      jsonb NOT NULL,
    pdf_path       text,
    generated_by   text,
    generated_at   timestamptz DEFAULT now()
);


-- One row per (project, version) — versions increment on each re-run.
CREATE UNIQUE INDEX IF NOT EXISTS uq_site_memos_project_version
    ON site_memos(project_id, version);

-- Reverse-chronological lookups power the "past memos" history panel.
CREATE INDEX IF NOT EXISTS idx_site_memos_project_time
    ON site_memos(project_id, generated_at DESC);

-- Verdict histogram (CAUTION trending to GO across time) — useful for
-- investment-committee dashboards that count verdict transitions.
CREATE INDEX IF NOT EXISTS idx_site_memos_verdict
    ON site_memos(((memo_json ->> 'investment_verdict')));
