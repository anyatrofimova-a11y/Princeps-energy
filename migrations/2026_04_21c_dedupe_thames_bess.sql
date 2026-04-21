-- Migration: 2026-04-21 (c)  Dedupe "Thames BESS Phase 1" duplicate project row
-- ----------------------------------------------------------------------
-- BOT-DQ: `list_projects` returned two rows for "Thames BESS Phase 1"
-- (different project_ids, both in Default Portfolio) — pre-existing,
-- not user-created. One row carries the real Coryton Grid 132/33kV
-- metadata (chemistry=LFP, duration_h=2) and is referenced by
-- `feasi-frontend/src/data/mock-grid-connection.json` and by 3 rows in
-- `project_candidate_sites`; the other is an orphan duplicate seeded
-- during a later boot when the ON CONFLICT guard in db_setup.py did
-- not cover the non-unique name collision.
--
--   KEEP   0367bdbc-4a81-4f15-aa8d-5d2190221104  (2026-04-17, has FK refs)
--   DELETE 6c4473a3-80c6-4c9a-aea0-86954334bfdc  (2026-04-19, no refs)
--
-- Idempotent: the DELETE is guarded by an EXISTS clause that ensures
-- BOTH rows still exist and NO FK references to the losing row remain.
-- Re-applying after the first run is a no-op (the losing row is gone
-- so the EXISTS check returns false).
--
-- Cascade analysis (ran pre-apply — see BOT-DQ report):
--   agent_analyses, assessment_snapshots, design_layouts,
--   document_project_pins, land_options, placed_assets,
--   project_candidate_sites, project_dno_engagements,
--   project_docket_pins, project_documents, project_sites,
--   project_stage_history, site_boundaries, workflow_runs
--     → 0 rows reference 6c4473a3 (the losing row is orphan).
--     → 3 project_candidate_sites rows reference 0367bdbc (keeper).
-- No re-parenting required.
-- ----------------------------------------------------------------------

BEGIN;

-- Defensive: re-parent any FK references to the losing row onto the
-- keeper, in case a later boot inserted children against the duplicate
-- before this migration ran. All no-ops on the first clean apply.
-- (Every table below has project_id FK → projects.project_id.)
UPDATE agent_analyses
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid);

UPDATE assessment_snapshots
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid);

UPDATE design_layouts
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid);

UPDATE document_project_pins AS dpp
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE dpp.project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid)
   AND NOT EXISTS (
       SELECT 1 FROM document_project_pins dpp2
        WHERE dpp2.project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
          AND dpp2.doc_id = dpp.doc_id
   );

UPDATE land_options
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid);

UPDATE placed_assets
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid);

UPDATE project_candidate_sites
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid);

UPDATE project_dno_engagements
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid);

UPDATE project_docket_pins AS pdp
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE pdp.project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid)
   AND NOT EXISTS (
       SELECT 1 FROM project_docket_pins pdp2
        WHERE pdp2.project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
          AND pdp2.docket_id = pdp.docket_id
   );

UPDATE project_documents
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid);

UPDATE project_sites
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid);

UPDATE project_stage_history
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid);

UPDATE site_boundaries
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid);

UPDATE workflow_runs
   SET project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
 WHERE project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (SELECT 1 FROM projects WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid);

-- Now delete the losing row. Guarded: only runs while BOTH the keeper
-- and the loser are present. After the first successful run the loser
-- is gone, so the EXISTS check returns false and this is a no-op.
DELETE FROM projects
 WHERE project_id = '6c4473a3-80c6-4c9a-aea0-86954334bfdc'::uuid
   AND EXISTS (
       SELECT 1 FROM projects
        WHERE project_id = '0367bdbc-4a81-4f15-aa8d-5d2190221104'::uuid
   );

COMMIT;

-- ===== VERIFICATION ==================================================
--   SELECT name, count(*) FROM projects
--    WHERE name = 'Thames BESS Phase 1' GROUP BY name;
--     → expect 1 row
--
--   SELECT name, count(*) FROM projects
--    GROUP BY name HAVING count(*) > 1 AND name = 'Thames BESS Phase 1';
--     → expect 0 rows
-- ----------------------------------------------------------------------
