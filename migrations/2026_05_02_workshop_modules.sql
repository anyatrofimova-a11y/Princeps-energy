-- 2026_05_02_workshop_modules.sql
-- Workshop Module Builder MVP — AI-composed module manifests.
-- Idempotent. Skips RLS for MVP.

CREATE TABLE IF NOT EXISTS workshop_modules(
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  target_type TEXT,
  manifest JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workshop_modules_slug ON workshop_modules(slug);
CREATE INDEX IF NOT EXISTS idx_workshop_modules_target ON workshop_modules(target_type);
