-- Object Notes — Foundry Notepad equivalent. Markdown notes pinned to
-- any typed object via its rid. Append-only would be ideal but we
-- allow update/delete so analysts can edit; soft-delete via deleted_at.

BEGIN;

CREATE TABLE IF NOT EXISTS object_notes (
  id BIGSERIAL PRIMARY KEY,
  rid TEXT NOT NULL,
  title TEXT,
  body_md TEXT NOT NULL,
  author TEXT,
  tags TEXT[] DEFAULT ARRAY[]::TEXT[],
  pinned BOOLEAN NOT NULL DEFAULT FALSE,
  parent_note_id BIGINT REFERENCES object_notes(id) ON DELETE SET NULL,
  tenant_id UUID DEFAULT '00000000-0000-0000-0000-000000000001',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_obj_notes_rid ON object_notes(rid, pinned DESC, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_obj_notes_tags ON object_notes USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_obj_notes_recent ON object_notes(created_at DESC) WHERE deleted_at IS NULL;

-- Auto-bump updated_at on edit
CREATE OR REPLACE FUNCTION _touch_object_notes() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_object_notes_touch ON object_notes;
CREATE TRIGGER trg_object_notes_touch
  BEFORE UPDATE ON object_notes
  FOR EACH ROW EXECUTE FUNCTION _touch_object_notes();

COMMIT;
