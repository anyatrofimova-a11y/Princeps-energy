-- Migration: 2026-04-21 (f) — REPD projects uniqueness constraint
-- ----------------------------------------------------------------------
-- BOT-DD companion to 2026_04_21e_repd_dedupe.sql. The dedupe removes
-- the 397 reingest-artefact rows; this migration installs the regression
-- guard so future REPD bulk-importer runs cannot resurrect dupes.
--
-- Why a PARTIAL UNIQUE INDEX (not a regular UNIQUE constraint):
--   • `projects` holds rows from many sources (REPD, user-created, demo
--     anchors, agent-generated). Globally enforcing uniqueness on
--     (name, coord-bucket) would fail for non-REPD rows such as the two
--     Thames-area demo projects that intentionally share a name with
--     the anchoring REPD record.
--   • Predicate `WHERE repd_id IS NOT NULL` scopes the constraint to
--     exactly the REPD bulk-import surface area, mirroring the
--     existing `projects_repd_id_unique` pattern.
--
-- Why (name, ROUND(lat*100), ROUND(lon*100)):
--   • REPD CSV re-publishes the same physical site with a FRESH Ref ID
--     every quarter; `repd_id`-only uniqueness cannot catch that.
--   • Rounding lat/lon to 0.01° buckets (~1.1 km N–S) absorbs the small
--     coord jitter we observed in the Q3/Q4 2025 extracts ("Burcot Solar
--     Farm" moved 51.66→51.67 across quarters) while still separating
--     genuinely distinct sites that share a generic name (Manor Farm is
--     4 sites across 4 counties, all >10 km apart → all survive).
--
-- Effect on the REPD bulk-importer:
--   The importer's `ON CONFLICT (repd_id) DO NOTHING` clause remains the
--   fast path for re-runs with the SAME Ref ID. This new partial index
--   raises IntegrityError on re-runs with a DIFFERENT Ref ID but the
--   same (name, bucket) — the importer already catches generic
--   exceptions in its per-row loop (`except Exception: continue`) so
--   it will skip gracefully instead of duplicating.
--
-- Idempotent: `IF NOT EXISTS` guard on the index creation.
-- ----------------------------------------------------------------------

BEGIN;

-- Functional partial unique index. CONCURRENTLY is not usable inside a
-- transaction block, and boot-apply runs under a single txn; the blocking
-- lock is fine for a table with ~5k rows.
CREATE UNIQUE INDEX IF NOT EXISTS projects_repd_name_coord_unique
    ON projects (
        name,
        (ROUND(lat::numeric * 100)),
        (ROUND(lon::numeric * 100))
    )
    WHERE repd_id IS NOT NULL
      AND lat IS NOT NULL
      AND lon IS NOT NULL;

COMMIT;

-- ===== VERIFICATION ==================================================
--   \d projects
--     → should list `projects_repd_name_coord_unique` among indexes.
--
--   -- Attempting to insert a 2nd REPD row for the same site now fails:
--   INSERT INTO projects (name, repd_id, lat, lon) VALUES
--     ('Tydd Solar Farm', '99999', 52.6876, 0.0781);
--     → ERROR: duplicate key value violates unique constraint
--              "projects_repd_name_coord_unique"
-- ----------------------------------------------------------------------
