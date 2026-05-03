-- Live event stream — make emit_object_mutated also pg_notify so the
-- backend SSE bridge can forward mutations to subscribed widgets.
--
-- Channel: 'princeps_object_mutated'
-- Payload: '{"rid": "...", "label": "...", "op": "INSERT|UPDATE|DELETE"}'

BEGIN;

CREATE OR REPLACE FUNCTION emit_object_mutated() RETURNS TRIGGER AS $$
DECLARE
  op_args JSONB;
  rid_val TEXT;
  lbl_val TEXT;
  diff_obj JSONB;
  notify_payload TEXT;
BEGIN
  IF TG_OP = 'DELETE' THEN
    rid_val := OLD.rid;
    lbl_val := OLD.label;
    op_args := jsonb_build_object('op', 'DELETE', 'before', OLD.props);
    UPDATE object_versions
       SET valid_to = clock_timestamp()
     WHERE rid = OLD.rid AND valid_to IS NULL;
    INSERT INTO object_versions (rid, label, props, valid_from, valid_to, op, diff)
    VALUES (OLD.rid, OLD.label, '{}'::jsonb, clock_timestamp(), clock_timestamp(), 'DELETE',
            jsonb_build_object('removed', OLD.props));
  ELSIF TG_OP = 'INSERT' THEN
    rid_val := NEW.rid;
    lbl_val := NEW.label;
    op_args := jsonb_build_object('op', 'INSERT', 'after', NEW.props);
    UPDATE object_versions
       SET valid_to = clock_timestamp()
     WHERE rid = NEW.rid AND valid_to IS NULL;
    INSERT INTO object_versions (rid, label, props, valid_from, valid_to, op, diff)
    VALUES (NEW.rid, NEW.label, NEW.props, clock_timestamp(), NULL, 'INSERT',
            jsonb_build_object('added', NEW.props));
  ELSE
    rid_val := NEW.rid;
    lbl_val := NEW.label;
    IF OLD.props = NEW.props AND OLD.label = NEW.label THEN
      RETURN NEW;
    END IF;
    op_args := jsonb_build_object(
      'op', 'UPDATE',
      'before', OLD.props,
      'after',  NEW.props,
      'label_changed', (OLD.label IS DISTINCT FROM NEW.label)
    );
    diff_obj := (
      SELECT jsonb_object_agg(k, jsonb_build_object('before', OLD.props->k, 'after', NEW.props->k))
      FROM jsonb_object_keys(OLD.props || NEW.props) k
      WHERE OLD.props->k IS DISTINCT FROM NEW.props->k
    );
    UPDATE object_versions
       SET valid_to = clock_timestamp()
     WHERE rid = NEW.rid AND valid_to IS NULL;
    INSERT INTO object_versions (rid, label, props, valid_from, valid_to, op, diff)
    VALUES (NEW.rid, NEW.label, NEW.props, clock_timestamp(), NULL, 'UPDATE',
            COALESCE(diff_obj, '{}'::jsonb));
  END IF;

  -- Existing audit log row
  INSERT INTO ontology_action_log (
    object_type, object_id, action, actor, ok,
    args_json, result_json, started_utc, completed_utc
  ) VALUES (
    lbl_val, rid_val, 'ObjectMutated', 'system:auto_emit', TRUE,
    op_args, '{}'::jsonb, NOW(), NOW()
  );

  -- NEW: broadcast to live widgets. Truncate payload to keep <8KB notify cap.
  notify_payload := jsonb_build_object(
    'rid', rid_val,
    'label', lbl_val,
    'op', TG_OP,
    'ts', extract(epoch from clock_timestamp())
  )::text;
  PERFORM pg_notify('princeps_object_mutated', notify_payload);

  RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

COMMIT;
