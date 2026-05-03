-- Solutions marketplace — Foundry-style installable Slate dashboards.
--
-- Packages live in `solution_packages` (curated, versioned). Install
-- clones the manifest into `workshop_modules` under a tenant-chosen slug
-- and increments install_count for popularity ranking.

BEGIN;

CREATE TABLE IF NOT EXISTS solution_packages (
  package_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  category TEXT,                                -- 'BESS' | 'Data Centre' | 'Ops' | 'Grid' | 'Risk'
  vertical TEXT,                                -- 'bess' | 'dc' | 'all'
  version TEXT DEFAULT '1.0.0',
  author TEXT DEFAULT 'Princeps',
  manifest JSONB NOT NULL,
  required_connectors TEXT[] DEFAULT ARRAY[]::TEXT[],
  required_object_types TEXT[] DEFAULT ARRAY[]::TEXT[],
  install_count BIGINT DEFAULT 0,
  featured BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_solpkg_category ON solution_packages(category);
CREATE INDEX IF NOT EXISTS idx_solpkg_featured ON solution_packages(featured DESC, install_count DESC);

CREATE TABLE IF NOT EXISTS solution_installs (
  install_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  package_id UUID NOT NULL REFERENCES solution_packages(package_id) ON DELETE CASCADE,
  module_slug TEXT NOT NULL,                    -- the workshop_modules.slug created on install
  installed_by TEXT,
  installed_at TIMESTAMPTZ DEFAULT NOW(),
  tenant_id UUID DEFAULT '00000000-0000-0000-0000-000000000001'
);
CREATE INDEX IF NOT EXISTS idx_solinst_pkg ON solution_installs(package_id, installed_at DESC);

COMMIT;
