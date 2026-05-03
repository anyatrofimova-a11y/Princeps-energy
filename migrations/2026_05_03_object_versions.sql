-- Append-only object_versions table for Foundry-style time-travel.
--
-- Populated by extending emit_object_mutated() so every INSERT/UPDATE/DELETE
-- on graph_nodes produces a row with valid_from / valid_to. A query
-- `WHERE valid_from <= as_of AND (valid_to IS NULL OR valid_to > as_of)`
-- returns the version that was active at any given timestamp.

BEGIN;

CREATE TABLE IF NOT EXISTS object_versions (
  id BIGSERIAL PRIMARY KEY,
  rid TEXT NOT NULL,
  label TEXT NOT NULL,
  props JSONB NOT NULL DEFAULT '{}'::jsonb,
  valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  valid_to TIMESTAMPTZ,
  op TEXT NOT NULL CHECK (op IN ('INSERT','UPDATE','DELETE')),
  actor TEXT,
  diff JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_obj_ver_rid_from ON object_versions(rid, valid_from DESC);
CREATE INDEX IF NOT EXISTS idx_obj_ver_rid_range ON object_versions(rid, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_obj_ver_label ON object_versions(label, valid_from DESC);

-- Replace emit_object_mutated to also write to object_versions.
CREATE OR REPLACE FUNCTION emit_object_mutated() RETURNS TRIGGER AS $$
DECLARE
  op_args JSONB;
  rid_val TEXT;
  lbl_val TEXT;
  diff_obj JSONB;
BEGIN
  IF TG_OP = 'DELETE' THEN
    rid_val := OLD.rid;
    lbl_val := OLD.label;
    op_args := jsonb_build_object('op', 'DELETE', 'before', OLD.props);
    -- Close out current version
    UPDATE object_versions
       SET valid_to = clock_timestamp()
     WHERE rid = OLD.rid AND valid_to IS NULL;
    -- Tombstone row so the timeline shows the deletion event
    INSERT INTO object_versions (rid, label, props, valid_from, valid_to, op, diff)
    VALUES (OLD.rid, OLD.label, '{}'::jsonb, clock_timestamp(), clock_timestamp(), 'DELETE',
            jsonb_build_object('removed', OLD.props));
  ELSIF TG_OP = 'INSERT' THEN
    rid_val := NEW.rid;
    lbl_val := NEW.label;
    op_args := jsonb_build_object('op', 'INSERT', 'after', NEW.props);
    -- Defensive: close any leftover open version (shouldn't exist on INSERT)
    UPDATE object_versions
       SET valid_to = clock_timestamp()
     WHERE rid = NEW.rid AND valid_to IS NULL;
    INSERT INTO object_versions (rid, label, props, valid_from, valid_to, op, diff)
    VALUES (NEW.rid, NEW.label, NEW.props, clock_timestamp(), NULL, 'INSERT',
            jsonb_build_object('added', NEW.props));
  ELSE  -- UPDATE
    rid_val := NEW.rid;
    lbl_val := NEW.label;
    -- Skip if neither props nor label changed
    IF OLD.props = NEW.props AND OLD.label = NEW.label THEN
      RETURN NEW;
    END IF;
    op_args := jsonb_build_object(
      'op', 'UPDATE',
      'before', OLD.props,
      'after',  NEW.props,
      'label_changed', (OLD.label IS DISTINCT FROM NEW.label)
    );
    -- Compute a tiny diff for the timeline (keys whose values changed)
    diff_obj := (
      SELECT jsonb_object_agg(k, jsonb_build_object('before', OLD.props->k, 'after', NEW.props->k))
      FROM jsonb_object_keys(OLD.props || NEW.props) k
      WHERE OLD.props->k IS DISTINCT FROM NEW.props->k
    );
    -- Close out previous version + insert a new one
    UPDATE object_versions
       SET valid_to = clock_timestamp()
     WHERE rid = NEW.rid AND valid_to IS NULL;
    INSERT INTO object_versions (rid, label, props, valid_from, valid_to, op, diff)
    VALUES (NEW.rid, NEW.label, NEW.props, clock_timestamp(), NULL, 'UPDATE',
            COALESCE(diff_obj, '{}'::jsonb));
  END IF;

  -- Existing audit log (unchanged)
  INSERT INTO ontology_action_log (
    object_type, object_id, action, actor, ok,
    args_json, result_json, started_utc, completed_utc
  ) VALUES (
    lbl_val, rid_val, 'ObjectMutated', 'system:auto_emit', TRUE,
    op_args, '{}'::jsonb, NOW(), NOW()
  );

  RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

-- Trigger already exists on graph_nodes; the function replacement is enough.

COMMIT;
