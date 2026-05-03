-- Migration: 2026-04-21 (e) — Dedupe REPD-ingest artefact rows in `projects`
-- ----------------------------------------------------------------------
-- BOT-DD: BOT-DQ audit surfaced 438 duplicate-name groups in `projects`
-- on top of the Thames BESS Phase 1 row it already fixed in 2026_04_21c.
-- Root cause: the REPD bulk-importer (`app/startup.py::_bulk_import_repd_if_thin`
-- and `POST /api/projects/import-repd-bulk`) inserts one row per REPD
-- Ref ID. DESNZ re-publishes the same physical site across quarterly
-- extracts with a FRESH Ref ID, so the existing `ON CONFLICT (repd_id)
-- DO NOTHING` guard cannot catch the re-insert — each run adds a new
-- row for the same site.
--
-- Audit classified dupe groups by shape (see BOT-DD report):
--   • 367 groups (764 rows) = same-name + coord bucket (~1.1 km tolerance
--     via ROUND(lat*100) / ROUND(lon*100)) + distinct repd_id  → DEDUPE.
--   • ~10 same-name groups with coords >10 km apart
--     (e.g. "Manor Farm" × 4 across 4 counties, "Home Farm" × 3)
--     → KEEP BOTH; genuine distinct sites sharing a generic name.
--
-- Keeper-selection criterion (strongest-evidence wins):
--   1. Highest stage rank (energised > construction > fid > planning >
--      grid_applied > prospect) — so progressed rows beat raw imports.
--   2. Tie-break: most recently updated (freshest REPD snapshot).
--   3. Final tie: oldest created_at + smallest project_id UUID
--      (deterministic, stable across re-runs).
--
-- FK-reference audit (ran pre-apply):
--   agent_analyses, assessment_snapshots, design_layouts, land_options,
--   placed_assets, project_candidate_sites, project_documents,
--   project_sites, project_stage_history, site_boundaries, workflow_runs,
--   document_project_pins, project_dno_engagements, project_docket_pins
--     → 0 rows reference any loser project_id.
--   (REPD bulk rows are freshly seeded on every boot; children are
--   created later against the keeper UUID only.)
-- Re-parenting blocks are therefore no-ops on the first apply, but are
-- included defensively so a later boot that inserts children against a
-- duplicate before this migration runs still gets cleaned up.
--
-- Idempotent via `dedupe_plan` CTE: on second apply the plan returns 0
-- rows (every bucket has exactly 1 survivor → no rn>1 rows to delete).
-- The partial UNIQUE INDEX on (name, bucket_lat, bucket_lon) in the
-- companion migration 2026_04_21f_repd_unique_constraint.sql prevents
-- regression.
-- ----------------------------------------------------------------------

BEGIN;

-- 1. Stage-rank helper (inlined as CTE, not a permanent table — cheap,
--    only used during this migration).
WITH stage_rank(stage, r) AS (
    VALUES
        ('energised',    6),
        ('construction', 5),
        ('fid',          4),
        ('planning',     3),
        ('grid_applied', 2),
        ('prospect',     1)
),

-- 2. Rank rows within each (name, coord-bucket) partition.
--    Bucket = ROUND(coord * 100) — collapses sites within ~1.1 km.
--    Only REPD-sourced rows (repd_id IS NOT NULL) are in scope so we
--    don't accidentally touch the Thames BESS / Slough demo rows or
--    any user-created projects.
ranked AS (
    SELECT p.project_id,
           p.name,
           ROUND(p.lat::numeric * 100) AS bucket_lat,
           ROUND(p.lon::numeric * 100) AS bucket_lon,
           ROW_NUMBER() OVER (
               PARTITION BY p.name,
                            ROUND(p.lat::numeric * 100),
                            ROUND(p.lon::numeric * 100)
               ORDER BY COALESCE(sr.r, 0) DESC,
                        p.updated_at         DESC,
                        p.created_at         ASC,
                        p.project_id         ASC
           ) AS rn
    FROM projects p
    LEFT JOIN stage_rank sr ON sr.stage = p.stage
    WHERE p.lat     IS NOT NULL
      AND p.lon     IS NOT NULL
      AND p.repd_id IS NOT NULL
),

-- 3. Keeper per bucket.
keepers AS (
    SELECT name, bucket_lat, bucket_lon, project_id AS keeper_id
    FROM ranked
    WHERE rn = 1
),

-- 4. Losers: every row in a bucket where count > 1 and rn > 1.
losers AS (
    SELECT r.project_id AS loser_id,
           k.keeper_id
    FROM ranked r
    JOIN keepers k
      ON k.name       = r.name
     AND k.bucket_lat = r.bucket_lat
     AND k.bucket_lon = r.bucket_lon
    WHERE r.rn > 1
)
SELECT 1 INTO TEMP TABLE _dedupe_plan_placeholder FROM losers LIMIT 1;

-- Materialise the loser→keeper map as a TEMP TABLE so we can reference
-- it from each UPDATE/DELETE statement below without re-running the
-- ranking window (cheap, ~400 rows max).
DROP TABLE IF EXISTS _repd_dedupe_plan;
CREATE TEMP TABLE _repd_dedupe_plan AS
WITH stage_rank(stage, r) AS (
    VALUES
        ('energised',    6),
        ('construction', 5),
        ('fid',          4),
        ('planning',     3),
        ('grid_applied', 2),
        ('prospect',     1)
),
ranked AS (
    SELECT p.project_id,
           p.name,
           ROUND(p.lat::numeric * 100) AS bucket_lat,
           ROUND(p.lon::numeric * 100) AS bucket_lon,
           ROW_NUMBER() OVER (
               PARTITION BY p.name,
                            ROUND(p.lat::numeric * 100),
                            ROUND(p.lon::numeric * 100)
               ORDER BY COALESCE(sr.r, 0) DESC,
                        p.updated_at         DESC,
                        p.created_at         ASC,
                        p.project_id         ASC
           ) AS rn
    FROM projects p
    LEFT JOIN stage_rank sr ON sr.stage = p.stage
    WHERE p.lat     IS NOT NULL
      AND p.lon     IS NOT NULL
      AND p.repd_id IS NOT NULL
),
keepers AS (
    SELECT name, bucket_lat, bucket_lon, project_id AS keeper_id
    FROM ranked
    WHERE rn = 1
)
SELECT r.project_id AS loser_id,
       k.keeper_id
FROM ranked r
JOIN keepers k
  ON k.name       = r.name
 AND k.bucket_lat = r.bucket_lat
 AND k.bucket_lon = r.bucket_lon
WHERE r.rn > 1;

-- 5. Re-parent FK references from loser → keeper. All 0-row no-ops on
--    a clean first apply (verified pre-migration); kept defensively so
--    any child inserted against a dupe before a re-apply is rescued.
--    NOT EXISTS guards prevent PK collisions on tables with composite
--    uniqueness (document_project_pins, project_docket_pins).

UPDATE agent_analyses a
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE a.project_id = dp.loser_id;

UPDATE assessment_snapshots a
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE a.project_id = dp.loser_id;

UPDATE design_layouts d
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE d.project_id = dp.loser_id;

UPDATE land_options l
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE l.project_id = dp.loser_id;

UPDATE placed_assets pa
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE pa.project_id = dp.loser_id;

UPDATE project_candidate_sites pcs
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE pcs.project_id = dp.loser_id;

UPDATE project_documents pd
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE pd.project_id = dp.loser_id;

UPDATE project_sites ps
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE ps.project_id = dp.loser_id;

UPDATE project_stage_history psh
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE psh.project_id = dp.loser_id;

UPDATE site_boundaries sb
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE sb.project_id = dp.loser_id;

UPDATE workflow_runs wr
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE wr.project_id = dp.loser_id;

-- Tables with composite-key uniqueness — de-dup children that would
-- collide on re-parent.
DELETE FROM document_project_pins dpp
 WHERE EXISTS (SELECT 1 FROM _repd_dedupe_plan dp WHERE dpp.project_id = dp.loser_id)
   AND EXISTS (
       SELECT 1
         FROM document_project_pins dpp2
         JOIN _repd_dedupe_plan dp ON dp.loser_id = dpp.project_id
        WHERE dpp2.project_id = dp.keeper_id
          AND dpp2.doc_id     = dpp.doc_id
   );
UPDATE document_project_pins dpp
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE dpp.project_id = dp.loser_id;

DELETE FROM project_docket_pins pdp
 WHERE EXISTS (SELECT 1 FROM _repd_dedupe_plan dp WHERE pdp.project_id = dp.loser_id)
   AND EXISTS (
       SELECT 1
         FROM project_docket_pins pdp2
         JOIN _repd_dedupe_plan dp ON dp.loser_id = pdp.project_id
        WHERE pdp2.project_id = dp.keeper_id
          AND pdp2.docket_id  = pdp.docket_id
   );
UPDATE project_docket_pins pdp
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE pdp.project_id = dp.loser_id;

UPDATE project_dno_engagements pde
   SET project_id = dp.keeper_id
  FROM _repd_dedupe_plan dp
 WHERE pde.project_id = dp.loser_id;

-- 6. Delete the loser rows. Guarded by EXISTS on the plan; second apply
--    is a no-op because the plan is re-built from current state and
--    post-dedupe there are no rn>1 rows.
DELETE FROM projects p
 WHERE EXISTS (
     SELECT 1 FROM _repd_dedupe_plan dp WHERE dp.loser_id = p.project_id
 );

DROP TABLE IF EXISTS _repd_dedupe_plan;
DROP TABLE IF EXISTS _dedupe_plan_placeholder;

COMMIT;

-- ===== VERIFICATION ==================================================
--   Before: SELECT count(*) FROM (SELECT name FROM projects
--              GROUP BY name HAVING count(*) > 1) t;  → 438
--   After : same query → should drop to the ~10 same-name-distinct-site
--           groups we intentionally kept (Manor Farm, Home Farm, etc.).
--
--   Bucket-level dupe check (the real invariant):
--     SELECT count(*) FROM (
--       SELECT name FROM projects
--        WHERE lat IS NOT NULL AND lon IS NOT NULL AND repd_id IS NOT NULL
--       GROUP BY name, ROUND(lat::numeric*100), ROUND(lon::numeric*100)
--       HAVING count(*) > 1
--     ) t;  → expect 0.
-- ----------------------------------------------------------------------
