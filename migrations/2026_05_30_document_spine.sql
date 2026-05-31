-- Document spine for the Contract Intelligence workspace.
-- Lives in its own `contracts` schema to avoid collision with the
-- existing public.documents table from the dockets module.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS contracts;

-- Try to create pgvector; if the platform doesn't allow it, fall back
-- to a bytea embedding column on contracts.clauses.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector') THEN
    BEGIN
      CREATE EXTENSION vector;
    EXCEPTION WHEN OTHERS THEN
      NULL;
    END;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS contracts.documents (
  document_rid   text PRIMARY KEY DEFAULT ('rid.princeps.document.' || gen_random_uuid()::text),
  project_rid    text,
  tenant_id      uuid,
  kind           text NOT NULL,           -- CTA | OEM | EPC | PPA | GridAgreement | OTHER
  title          text NOT NULL,
  party_first    text,
  party_second   text,
  status         text DEFAULT 'active',
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_contracts_documents_project ON contracts.documents (project_rid);
CREATE INDEX IF NOT EXISTS idx_contracts_documents_tenant  ON contracts.documents (tenant_id);
CREATE INDEX IF NOT EXISTS idx_contracts_documents_kind    ON contracts.documents (kind);

CREATE TABLE IF NOT EXISTS contracts.document_drafts (
  draft_rid       text PRIMARY KEY DEFAULT ('rid.princeps.draft.' || gen_random_uuid()::text),
  document_rid    text NOT NULL REFERENCES contracts.documents(document_rid) ON DELETE CASCADE,
  version_label   text NOT NULL,
  draft_date      date,
  page_count      integer,
  source_hash     text NOT NULL,
  source_path     text,
  uploaded_by     text,
  uploaded_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_drafts_document ON contracts.document_drafts (document_rid, draft_date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_drafts_hash ON contracts.document_drafts (document_rid, source_hash);

CREATE TABLE IF NOT EXISTS contracts.clauses (
  clause_rid      text PRIMARY KEY DEFAULT ('rid.princeps.clause.' || gen_random_uuid()::text),
  draft_rid       text NOT NULL REFERENCES contracts.document_drafts(draft_rid) ON DELETE CASCADE,
  section         text,
  heading         text,
  page            integer,
  span_start      integer,
  span_end        integer,
  text            text NOT NULL,
  text_tsv        tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(text,''))) STORED
);
CREATE INDEX IF NOT EXISTS idx_clauses_draft   ON contracts.clauses (draft_rid);
CREATE INDEX IF NOT EXISTS idx_clauses_section ON contracts.clauses (draft_rid, section);
CREATE INDEX IF NOT EXISTS idx_clauses_tsv     ON contracts.clauses USING GIN (text_tsv);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector') THEN
    EXECUTE 'ALTER TABLE contracts.clauses ADD COLUMN IF NOT EXISTS embedding vector(1024)';
  ELSE
    EXECUTE 'ALTER TABLE contracts.clauses ADD COLUMN IF NOT EXISTS embedding bytea';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS contracts.obligations (
  obligation_rid  text PRIMARY KEY DEFAULT ('rid.princeps.obligation.' || gen_random_uuid()::text),
  clause_rid      text NOT NULL REFERENCES contracts.clauses(clause_rid) ON DELETE CASCADE,
  draft_rid       text NOT NULL,
  party           text,
  trigger         text,
  action          text,
  penalty         text,
  deadline_iso    text,
  status          text DEFAULT 'open',
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_obligations_draft ON contracts.obligations (draft_rid);
CREATE INDEX IF NOT EXISTS idx_obligations_party ON contracts.obligations (party);

CREATE TABLE IF NOT EXISTS contracts.citations (
  citation_rid    text PRIMARY KEY DEFAULT ('rid.princeps.citation.' || gen_random_uuid()::text),
  claim_id        text NOT NULL,
  clause_rid      text NOT NULL REFERENCES contracts.clauses(clause_rid) ON DELETE CASCADE,
  similarity      numeric,
  verbatim        text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_citations_claim  ON contracts.citations (claim_id);
CREATE INDEX IF NOT EXISTS idx_citations_clause ON contracts.citations (clause_rid);

CREATE TABLE IF NOT EXISTS contracts.chat_verdicts (
  verdict_rid     text PRIMARY KEY DEFAULT ('rid.princeps.verdict.' || gen_random_uuid()::text),
  message_id      text NOT NULL,
  session_id      text NOT NULL,
  project_rid     text,
  rating          text NOT NULL,
  coverage        numeric,
  justification   text,
  bounds          jsonb,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_verdicts_session ON contracts.chat_verdicts (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_verdicts_project ON contracts.chat_verdicts (project_rid);

CREATE TABLE IF NOT EXISTS contracts.change_alerts (
  alert_rid       text PRIMARY KEY DEFAULT ('rid.princeps.alert.' || gen_random_uuid()::text),
  document_rid    text NOT NULL REFERENCES contracts.documents(document_rid) ON DELETE CASCADE,
  draft_rid_a     text,
  draft_rid_b     text,
  summary         text,
  delta           jsonb,
  acknowledged    boolean DEFAULT false,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_alerts_doc ON contracts.change_alerts (document_rid, created_at DESC);
