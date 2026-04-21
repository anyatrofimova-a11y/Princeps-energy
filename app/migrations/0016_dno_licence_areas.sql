-- =============================================================================
-- 0016_dno_licence_areas.sql
-- -----------------------------------------------------------------------------
-- Princeps — DNO / IDNO / TO licence-area polygons for map overlays + spatial
-- inference of which operator a point/line falls in.
--
-- Covers:
--   * 6 GB DNOs (UKPN, SSEN, SPEN, NGED, NPG, ENWL) split into their licensed
--     sub-regions (e.g. UKPN → LPN, EPN, SPN; NGED → WPD legacy areas).
--   * NIE Networks (Northern Ireland).
--   * 3 onshore Transmission Owners for overlay only (NGET, SPT, SHE-T).
--   * IDNO boundaries (populated later — schema supports parent_slug back-ref).
--
-- operator_class ∈ {'DNO','IDNO','TO'}.
-- SRID 27700 MultiPolygon (OSGB36 / British National Grid) to match rest of
-- the Princeps PostGIS stack. Bounding polygons from the seed fixture are
-- approximate; flagged via source + note properties.
--
-- Idempotent. Applied by app/db_setup.py on startup.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;


-- ── operator_class enum ────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'operator_class') THEN
        CREATE TYPE operator_class AS ENUM ('DNO', 'IDNO', 'TO');
    END IF;
END$$;


-- ── dno_licence_areas table ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dno_licence_areas (
    id                bigserial PRIMARY KEY,
    dno_slug          text NOT NULL,                              -- e.g. 'ukpn', 'ukpn-lpn'
    operator_class    operator_class NOT NULL DEFAULT 'DNO',
    display_name      text NOT NULL,
    licence_region    text,                                        -- e.g. 'London', 'Eastern'
    parent_slug       text,                                        -- for sub-regions / IDNOs
    geom              geometry(MultiPolygon, 27700) NOT NULL,
    effective_from    date NOT NULL DEFAULT DATE '1990-03-31',     -- Electricity Act 1989 vesting
    effective_to      date,                                        -- NULL = still in force
    source            text,                                        -- e.g. 'fixture:approximate'
    source_url        text,
    note              text,
    ingested_at       timestamptz DEFAULT now(),
    UNIQUE (dno_slug, effective_from)
);

-- GIST spatial index (for point-in-polygon + bbox queries).
CREATE INDEX IF NOT EXISTS idx_dno_licence_areas_geom
    ON dno_licence_areas USING GIST (geom);

-- Class + slug btree for filter queries.
CREATE INDEX IF NOT EXISTS idx_dno_licence_areas_class
    ON dno_licence_areas (operator_class);
CREATE INDEX IF NOT EXISTS idx_dno_licence_areas_slug
    ON dno_licence_areas (dno_slug);
CREATE INDEX IF NOT EXISTS idx_dno_licence_areas_parent
    ON dno_licence_areas (parent_slug) WHERE parent_slug IS NOT NULL;

-- Effective-date range helper — lets us fetch "as-of" snapshots cheaply.
CREATE INDEX IF NOT EXISTS idx_dno_licence_areas_effective
    ON dno_licence_areas (effective_from, effective_to);
