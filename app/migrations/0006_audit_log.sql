-- =============================================================================
-- 0006_audit_log.sql
-- -----------------------------------------------------------------------------
-- Princeps — structured enterprise audit log (Task #13).
--
-- Named ``audit_log_v2`` to avoid colliding with any legacy ``audit_log``
-- table that may exist in older environments. Written to asynchronously by
-- the audit middleware in ``app/enterprise/audit_log.py`` — the middleware
-- fires-and-forgets so request latency is not affected.
--
-- PII hygiene
-- -----------
-- * ``payload_hash`` stores the SHA-256 of the request body, never the body
--   itself. Investigators can correlate requests with known payload hashes
--   (e.g. from a client-side log) without the backend ever persisting raw
--   user data.
-- * ``ip_address`` is stored as PostgreSQL ``inet`` so standard subnet queries
--   work for investigations; it is PII under GDPR and must be included in
--   any retention / deletion policy.
--
-- Idempotent: safe to re-run.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;


CREATE TABLE IF NOT EXISTS audit_log_v2 (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid,
    user_id          uuid,
    session_id       uuid,
    action           text NOT NULL,
    resource_type    text,
    resource_id      uuid,
    http_method      text,
    http_path        text,
    ip_address       inet,
    user_agent       text,
    payload_hash     text,                 -- SHA-256 of request body; never the body itself.
    response_status  int,
    error_message    text,
    occurred_at      timestamptz DEFAULT now()
);


-- Tenant-scoped timeline (most common query from the admin UI).
CREATE INDEX IF NOT EXISTS idx_audit_tenant_time
    ON audit_log_v2(tenant_id, occurred_at DESC);

-- Per-user activity (used in breach-notification + support workflows).
CREATE INDEX IF NOT EXISTS idx_audit_user_time
    ON audit_log_v2(user_id, occurred_at DESC);

-- Action histograms (used for anomaly detection / SOC 2 dashboards).
CREATE INDEX IF NOT EXISTS idx_audit_action
    ON audit_log_v2(action, occurred_at DESC);

-- Resource-change history (used when a customer asks "who touched this").
CREATE INDEX IF NOT EXISTS idx_audit_resource
    ON audit_log_v2(resource_type, resource_id);
