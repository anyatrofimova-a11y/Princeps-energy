-- AGE auto-emit triggers + DTDL cardinality enforcement.
--
-- Every INSERT/UPDATE/DELETE on graph_nodes writes an ObjectMutated row
-- to ontology_action_log; same for graph_edges → EdgeMutated.
-- BEFORE INSERT on graph_edges enforces DTDL maxMultiplicity from a
-- seeded `dtdl_cardinality` table.

BEGIN;

-- ── Cardinality table ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dtdl_cardinality (
  id BIGSERIAL PRIMARY KEY,
  from_label TEXT NOT NULL,
  edge_label TEXT NOT NULL,
  to_label TEXT,
  min_mult INT DEFAULT 0,
  max_mult INT,                  -- NULL = unbounded
  source_dtmi TEXT,
  CONSTRAINT ux_dtdl_card UNIQUE (from_label, edge_label)
);
CREATE INDEX IF NOT EXISTS idx_dtdl_card_from ON dtdl_cardinality(from_label);

-- ── Auto-emit: ObjectMutated ───────────────────────────────────────────────
CREATE OR REPLACE FUNCTION emit_object_mutated() RETURNS TRIGGER AS $$
DECLARE
  op_args JSONB;
  rid_val TEXT;
  lbl_val TEXT;
BEGIN
  IF TG_OP = 'DELETE' THEN
    rid_val := OLD.rid;
    lbl_val := OLD.label;
    op_args := jsonb_build_object('op', 'DELETE', 'before', OLD.props);
  ELSIF TG_OP = 'INSERT' THEN
    rid_val := NEW.rid;
    lbl_val := NEW.label;
    op_args := jsonb_build_object('op', 'INSERT', 'after', NEW.props);
  ELSE  -- UPDATE
    rid_val := NEW.rid;
    lbl_val := NEW.label;
    -- Skip if neither props nor label changed (avoid self-trigger spam from
    -- updated_at touches)
    IF OLD.props = NEW.props AND OLD.label = NEW.label THEN
      RETURN NEW;
    END IF;
    op_args := jsonb_build_object(
      'op', 'UPDATE',
      'before', OLD.props,
      'after',  NEW.props,
      'label_changed', (OLD.label IS DISTINCT FROM NEW.label)
    );
  END IF;

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

DROP TRIGGER IF EXISTS trg_graph_nodes_emit ON graph_nodes;
CREATE TRIGGER trg_graph_nodes_emit
  AFTER INSERT OR UPDATE OR DELETE ON graph_nodes
  FOR EACH ROW EXECUTE FUNCTION emit_object_mutated();

-- ── Auto-emit: EdgeMutated ─────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION emit_edge_mutated() RETURNS TRIGGER AS $$
DECLARE
  op_args JSONB;
  from_val TEXT;
  to_val TEXT;
  lbl_val TEXT;
BEGIN
  IF TG_OP = 'DELETE' THEN
    from_val := OLD.from_rid; to_val := OLD.to_rid; lbl_val := OLD.label;
    op_args := jsonb_build_object('op', 'DELETE', 'from', OLD.from_rid, 'to', OLD.to_rid, 'label', OLD.label);
  ELSIF TG_OP = 'INSERT' THEN
    from_val := NEW.from_rid; to_val := NEW.to_rid; lbl_val := NEW.label;
    op_args := jsonb_build_object('op', 'INSERT', 'from', NEW.from_rid, 'to', NEW.to_rid, 'label', NEW.label);
  ELSE  -- UPDATE
    from_val := NEW.from_rid; to_val := NEW.to_rid; lbl_val := NEW.label;
    IF OLD.props = NEW.props THEN
      RETURN NEW;
    END IF;
    op_args := jsonb_build_object('op', 'UPDATE', 'from', NEW.from_rid, 'to', NEW.to_rid, 'before', OLD.props, 'after', NEW.props);
  END IF;

  -- object_id := <from>--<label>-->: edges are typed by their from-rid + label.
  INSERT INTO ontology_action_log (
    object_type, object_id, action, actor, ok,
    args_json, result_json, started_utc, completed_utc
  ) VALUES (
    'edge:' || lbl_val, from_val || '--[' || lbl_val || ']-->' || to_val,
    'EdgeMutated', 'system:auto_emit', TRUE,
    op_args, '{}'::jsonb, NOW(), NOW()
  );

  RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_graph_edges_emit ON graph_edges;
CREATE TRIGGER trg_graph_edges_emit
  AFTER INSERT OR UPDATE OR DELETE ON graph_edges
  FOR EACH ROW EXECUTE FUNCTION emit_edge_mutated();

-- ── Cardinality enforcement: BEFORE INSERT on graph_edges ──────────────────
CREATE OR REPLACE FUNCTION check_edge_cardinality() RETURNS TRIGGER AS $$
DECLARE
  from_lbl TEXT;
  card_row RECORD;
  current_count INT;
BEGIN
  -- Look up the from-node's label so we can scope the cardinality rule
  SELECT label INTO from_lbl FROM graph_nodes WHERE rid = NEW.from_rid;
  IF from_lbl IS NULL THEN
    -- Allow the edge — referential FK will catch dangling rids if any
    RETURN NEW;
  END IF;

  SELECT min_mult, max_mult INTO card_row
  FROM dtdl_cardinality
  WHERE from_label = from_lbl AND edge_label = NEW.label;

  IF NOT FOUND OR card_row.max_mult IS NULL THEN
    -- No declared cardinality → unbounded
    RETURN NEW;
  END IF;

  SELECT COUNT(*) INTO current_count
  FROM graph_edges
  WHERE from_rid = NEW.from_rid AND label = NEW.label;

  IF current_count >= card_row.max_mult THEN
    RAISE EXCEPTION 'cardinality_violation: % can have at most % outgoing % edges (current=%)',
      from_lbl, card_row.max_mult, NEW.label, current_count
      USING ERRCODE = 'check_violation';
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_graph_edges_cardinality ON graph_edges;
CREATE TRIGGER trg_graph_edges_cardinality
  BEFORE INSERT ON graph_edges
  FOR EACH ROW EXECUTE FUNCTION check_edge_cardinality();

COMMIT;
