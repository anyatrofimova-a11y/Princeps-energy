-- Docket enrichment — source-grounded detail per docket.
-- Adds a canonical source_url to dockets + an enrichments table that
-- stores the fetched primary source, structured summary with paragraph
-- citations, stakeholder filings, deadlines, and related dockets.

ALTER TABLE dockets ADD COLUMN IF NOT EXISTS source_url text;
ALTER TABLE dockets ADD COLUMN IF NOT EXISTS canonical_authority text;  -- Ofgem | DESNZ | PINS | ENA | NESO | LPA | DefraHMG
CREATE INDEX IF NOT EXISTS idx_dockets_source_url ON dockets (source_url);

CREATE TABLE IF NOT EXISTS docket_enrichments (
  enrichment_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  docket_id            uuid NOT NULL REFERENCES dockets(docket_id) ON DELETE CASCADE,
  source_url           text NOT NULL,
  fetched_at           timestamptz NOT NULL DEFAULT now(),
  http_status          integer,
  fetch_bytes          integer,
  summary              text,             -- 2-3 paragraph executive summary
  key_paragraphs       jsonb,            -- [{anchor:"§5.3", page:12, quote:"…"}]
  stakeholders         jsonb,            -- [{name, role, position, filing_url, filed_on}]
  deadlines            jsonb,            -- [{name, date_iso, description, source_anchor}]
  related_dockets      jsonb,            -- [{docket_id_or_external, title, relation}]
  expert_take          text,             -- LLM-derived "what this means for a UK developer"
  confidence           text,             -- low | med | high
  bounds               jsonb,            -- ["did not fetch the technical annexes",…]
  raw_excerpt          text              -- first ~8000 chars of the canonical source
);
CREATE INDEX IF NOT EXISTS idx_docket_enrich_docket ON docket_enrichments (docket_id, fetched_at DESC);
