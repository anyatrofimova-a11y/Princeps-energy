-- 0020_nged_substation_dedupe.sql
--
-- Fixes the "Astrazeneca east_midlands" bug: 953 of 2,059 rows in
-- nged_substation are duplicates at the same coordinate (different
-- name spellings + region tags ingested from each NGED licence-area
-- LTDS bundle).
--
-- Non-destructive approach: add an is_canonical flag, populate it by
-- preferring the row whose `region` matches the DNO licence area at
-- that coordinate, and have the read-side query in utils/nged_cim.py
-- filter on is_canonical = TRUE. Reversible — UPDATE … SET
-- is_canonical = TRUE restores all rows.
--
-- Idempotent: re-running recomputes the flag from scratch.

ALTER TABLE nged_substation
  ADD COLUMN IF NOT EXISTS is_canonical boolean DEFAULT TRUE;
ALTER TABLE nged_substation
  ADD COLUMN IF NOT EXISTS canonical_reason text;

UPDATE nged_substation SET is_canonical = TRUE, canonical_reason = NULL;

WITH ranked AS (
  SELECT
    s.id,
    COUNT(*) OVER (PARTITION BY s.geometry) AS coord_group_size,
    ROW_NUMBER() OVER (
      PARTITION BY s.geometry
      ORDER BY
        -- 1. prefer the row whose `region` matches the DNO licence area
        --    at that coord (this is what fixes the Astrazeneca bug)
        CASE
          WHEN LOWER(REPLACE(s.region, '_', ' '))
             = LOWER((SELECT b.dno_name FROM grid_dno_boundaries b
                       WHERE ST_Intersects(b.geom, s.geometry) LIMIT 1))
          THEN 0 ELSE 1
        END,
        -- 2. then prefer rows with more linked transformers
        (SELECT COUNT(*) FROM nged_transformer t
          WHERE t.substation_id = s.id) DESC,
        -- 3. then alphabetic for determinism
        s.name ASC
    ) AS rn
  FROM nged_substation s
  WHERE s.geometry IS NOT NULL
)
UPDATE nged_substation s
   SET is_canonical = (r.rn = 1),
       canonical_reason = CASE
         WHEN r.coord_group_size = 1 THEN 'unique_coord'
         WHEN r.rn = 1 THEN 'best_in_group'
         ELSE 'duplicate_of_canonical'
       END
  FROM ranked r
 WHERE s.id = r.id;

CREATE INDEX IF NOT EXISTS idx_nged_sub_canonical
  ON nged_substation (is_canonical) WHERE is_canonical = TRUE;
