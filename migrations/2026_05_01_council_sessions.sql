-- Council session persistence.
--
-- One row per multi-pod adjudicated query. Each session captures the user
-- query, the project (if any) it was scoped to, the per-pod structured
-- verdicts, the adjudicator's final unified verdict, and any conflicts the
-- adjudicator surfaced (with the user clarifications that resolved them).
--
-- Audit detail (per-pod tool calls, adjudicator decisions) lands in
-- ontology_action_log with object_type='council_session'.

CREATE TABLE IF NOT EXISTS council_sessions (
    session_rid     text PRIMARY KEY,
    project_rid     text,
    query           text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    status          text NOT NULL DEFAULT 'pending',
    -- pending | running | clarification_needed | complete | failed
    pod_verdicts    jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- {grid:{...AgentOutput}, bess:{...}, dc:{...}}
    final_verdict   jsonb,
    conflicts       jsonb NOT NULL DEFAULT '[]'::jsonb,
    clarifications  jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_council_sessions_project
    ON council_sessions (project_rid, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_council_sessions_recent
    ON council_sessions (created_at DESC);
