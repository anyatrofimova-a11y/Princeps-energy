-- Ontology action audit log.
--
-- Every mutation that passes through app.ontology.dispatch writes one row here.
-- Used by:
--   * Agent replay / debugging
--   * "What happened to this project?" UI timeline
--   * Forensic / compliance review (who set this verdict? when?)
--
-- Shape is action-generic: object_type + object_id identify the target,
-- args_json captures the user intent, result_json captures the outcome.

CREATE TABLE IF NOT EXISTS ontology_action_log (
    log_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    object_type   text NOT NULL,
    object_id     text NOT NULL,
    action        text NOT NULL,
    actor         text,
    ok            boolean NOT NULL DEFAULT false,
    args_json     jsonb NOT NULL DEFAULT '{}'::jsonb,
    result_json   jsonb NOT NULL DEFAULT '{}'::jsonb,
    error         text,
    duration_ms   integer,
    started_utc   timestamptz NOT NULL DEFAULT now(),
    completed_utc timestamptz
);

CREATE INDEX IF NOT EXISTS idx_ontology_log_object
    ON ontology_action_log (object_type, object_id, started_utc DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_log_action
    ON ontology_action_log (action, started_utc DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_log_recent
    ON ontology_action_log (started_utc DESC);
