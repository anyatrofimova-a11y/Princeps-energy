-- SSO user mapping table — links (issuer, subject) from any spec-compliant
-- OIDC provider (Auth0, Keycloak, Google, Microsoft Entra, Okta, …) to a
-- Princeps user_id + tenant_id. Created by app/routers/sso.py on first
-- successful /api/auth/sso/callback for a given (issuer, subject) pair.
--
-- Idempotent: re-applying this migration is safe.

CREATE TABLE IF NOT EXISTS sso_users (
  id BIGSERIAL PRIMARY KEY,
  issuer TEXT NOT NULL,
  subject TEXT NOT NULL,
  email TEXT,
  name TEXT,
  user_id UUID,
  tenant_id UUID,
  last_login TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT ux_sso_user UNIQUE (issuer, subject)
);

CREATE INDEX IF NOT EXISTS idx_sso_email ON sso_users(email);
