-- BESS Live Revenue Snapshots — hourly co-optimised stack snapshots per site.
--
-- Owner: app/cron/bess_revenue_cron.py (writer) + app/routers/bess_live.py (reader/WS).
-- Powers the live dashboard widget on /v2 (LiveBessRevenue.jsx) — the BESS
-- counterpart to the DC lender-IM and a direct closer of the Modo Energy gap.
--
-- One row per site per cron tick (hourly). Frontend pulls last 30d for the
-- bootstrap chart, then subscribes to WS for live appends.
--
-- Idempotent: every CREATE / ALTER / TRIGGER guard is "IF NOT EXISTS"-safe so
-- this file applies cleanly twice (per smoke-test #1).

CREATE TABLE IF NOT EXISTS bess_live_revenue_snapshots (
    snapshot_id     bigserial PRIMARY KEY,
    rid             text        NOT NULL,
    ts              timestamptz NOT NULL DEFAULT now(),
    p10_rev_gbp     numeric     NOT NULL,
    p50_rev_gbp     numeric     NOT NULL,
    p90_rev_gbp     numeric     NOT NULL,
    stack_breakdown jsonb       NOT NULL DEFAULT '{}'::jsonb,
    modo_p50_forecast numeric   NULL,
    source          text        NOT NULL DEFAULT 'cron-stacker-v1',
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Lookup pattern: latest 30d for a given rid, newest first.
CREATE INDEX IF NOT EXISTS idx_bess_live_rev_rid_ts
    ON bess_live_revenue_snapshots (rid, ts DESC);

-- Catalog scan (no rid filter) — used by /api/bess/revenue-snapshot when caller
-- wants the most-recently-updated site as the demo fallback.
CREATE INDEX IF NOT EXISTS idx_bess_live_rev_ts
    ON bess_live_revenue_snapshots (ts DESC);

-- ───────────────────────────────────────────────────────────────────────────
-- LISTEN/NOTIFY plumbing — the cron writes a row, the WS handler in
-- app/routers/bess_live.py subscribes and pushes the new row down to clients.
-- Channel name: bess_live_revenue. Payload: just the snapshot_id (string).
-- The WS handler re-fetches the row by id (cheap, indexed) so we don't have
-- to deal with NOTIFY's 8KB payload cap.
-- ───────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION bess_live_revenue_notify() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('bess_live_revenue', NEW.snapshot_id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS bess_live_revenue_notify_trg ON bess_live_revenue_snapshots;
CREATE TRIGGER bess_live_revenue_notify_trg
    AFTER INSERT ON bess_live_revenue_snapshots
    FOR EACH ROW EXECUTE FUNCTION bess_live_revenue_notify();
