-- =============================================================================
-- 0010_parcel_cache.sql
-- -----------------------------------------------------------------------------
-- BOT-FF parcel dossier cache (fallback when Redis is not available).
--
-- The canonical cache lives in Redis under `parcel:dossier:{inspire_id}` with
-- a 24h TTL. When REDIS_URL is unset (dev / minimal deployments) the router
-- in app/routers/parcel.py writes the same JSON envelope to this table
-- instead — read path prefers Redis, then falls back here.
--
-- The dossier_json payload is expected to be the full ParcelDossier shape
-- documented in utils/parcel/dossier_builder.py.
--
-- Idempotent: safe to re-run.
-- =============================================================================

CREATE TABLE IF NOT EXISTS parcel_dossier_cache (
    inspire_id    text        PRIMARY KEY,
    dossier_json  jsonb       NOT NULL,
    cached_at     timestamptz NOT NULL DEFAULT NOW(),
    expires_at    timestamptz NOT NULL
);

-- Index on expires_at so a periodic sweeper can cheaply delete stale rows.
CREATE INDEX IF NOT EXISTS parcel_dossier_cache_expires_idx
    ON parcel_dossier_cache (expires_at);

-- Optional: cheap "last-N refreshed" listing for the admin diag page.
CREATE INDEX IF NOT EXISTS parcel_dossier_cache_cached_at_idx
    ON parcel_dossier_cache (cached_at DESC);

COMMENT ON TABLE  parcel_dossier_cache          IS 'Fallback cache for BOT-FF parcel dossier envelopes (Redis preferred).';
COMMENT ON COLUMN parcel_dossier_cache.dossier_json IS 'Full ParcelDossier JSON as returned by GET /api/parcel/{inspire_id}.';
COMMENT ON COLUMN parcel_dossier_cache.expires_at IS '24h TTL from cached_at; router refuses to serve rows past this.';
