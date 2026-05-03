-- Object branches — fork-and-merge over object_versions.
--
-- Foundry-style "what-if" scenarios. Each branch points at a base
-- version; edits append to branch_edits storing full props. Merge
-- reads the latest branch edit and writes it back to graph_nodes,
-- which fires emit_object_mutated and produces a new main version.

BEGIN;

CREATE TABLE IF NOT EXISTS object_branches (
  branch_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rid TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  base_version_id BIGINT REFERENCES object_versions(id) ON DELETE SET NULL,
  parent_branch_id UUID REFERENCES object_branches(branch_id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','merged','discarded')),
  created_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  merged_at TIMESTAMPTZ,
  merged_by TEXT,
  tenant_id UUID DEFAULT '00000000-0000-0000-0000-000000000001',
  CONSTRAINT ux_branch_rid_name UNIQUE (rid, name)
);
CREATE INDEX IF NOT EXISTS idx_obj_branches_rid ON object_branches(rid, status);
CREATE INDEX IF NOT EXISTS idx_obj_branches_recent ON object_branches(created_at DESC);

CREATE TABLE IF NOT EXISTS branch_edits (
  id BIGSERIAL PRIMARY KEY,
  branch_id UUID NOT NULL REFERENCES object_branches(branch_id) ON DELETE CASCADE,
  rid TEXT NOT NULL,
  props JSONB NOT NULL,
  diff JSONB DEFAULT '{}'::jsonb,
  actor TEXT,
  message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_branch_edits_branch ON branch_edits(branch_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_branch_edits_rid ON branch_edits(rid, created_at DESC);

COMMIT;
