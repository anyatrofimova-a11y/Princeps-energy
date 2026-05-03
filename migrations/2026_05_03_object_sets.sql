-- ObjectSet primitives — Foundry's saved typed queries with set algebra.
--
-- Define a set once ("BESS REPDs > 50MW in Greater London"), save it,
-- reuse from any Slate widget by binding to its slug. Derived sets are
-- composed via union/intersect/subtract over other sets.

BEGIN;

CREATE TABLE IF NOT EXISTS object_sets (
  set_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  object_type TEXT NOT NULL,                     -- the type each member belongs to
  filters JSONB NOT NULL DEFAULT '{}'::jsonb,    -- type-aware filter map (status, technology, capacity_min, etc.)
  -- Composition: when op is NOT NULL, the set is derived from member_set_ids
  -- and `filters` is treated as additional post-composition filters.
  op TEXT CHECK (op IN ('union','intersect','subtract')),
  member_set_ids UUID[] DEFAULT ARRAY[]::UUID[],
  tags TEXT[] DEFAULT ARRAY[]::TEXT[],
  pinned BOOLEAN NOT NULL DEFAULT FALSE,
  created_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  tenant_id UUID DEFAULT '00000000-0000-0000-0000-000000000001'
);
CREATE INDEX IF NOT EXISTS idx_obj_sets_type ON object_sets(object_type);
CREATE INDEX IF NOT EXISTS idx_obj_sets_pinned ON object_sets(pinned DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_obj_sets_tags ON object_sets USING GIN(tags);

-- Auto-touch updated_at
CREATE OR REPLACE FUNCTION _touch_object_sets() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_object_sets_touch ON object_sets;
CREATE TRIGGER trg_object_sets_touch
  BEFORE UPDATE ON object_sets
  FOR EACH ROW EXECUTE FUNCTION _touch_object_sets();

COMMIT;
