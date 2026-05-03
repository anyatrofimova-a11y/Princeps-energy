-- Marketplace v2 — user-published solutions.
--
-- Extends `solution_packages` so any saved workshop_modules row can be
-- republished as an installable package, with author attribution and a
-- visibility scope (public | tenant | private). Backfills the existing
-- built-in catalogue so the new author pill renders sensibly.

BEGIN;

ALTER TABLE solution_packages
  ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'public'
    CHECK (visibility IN ('public','tenant','private')),
  ADD COLUMN IF NOT EXISTS published_by TEXT,
  ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS source_module_slug TEXT;

-- Backfill author for existing built-ins so the new author pill renders sensibly.
UPDATE solution_packages
   SET published_by = 'Princeps (official)'
 WHERE published_by IS NULL;

CREATE INDEX IF NOT EXISTS idx_solpkg_visibility
  ON solution_packages(visibility);
CREATE INDEX IF NOT EXISTS idx_solpkg_source_module
  ON solution_packages(source_module_slug);

COMMIT;
