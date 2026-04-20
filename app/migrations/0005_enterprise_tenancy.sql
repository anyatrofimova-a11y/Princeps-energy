-- =============================================================================
-- 0005_enterprise_tenancy.sql
-- -----------------------------------------------------------------------------
-- Princeps — enterprise multi-tenancy primitives (Task #13).
--
-- Ships:
--   * ``tenants``               — one row per customer organisation.
--   * ``tenant_memberships``    — N:M user ↔ tenant with a role.
--   * ``tenant_sso_configs``    — per-tenant OIDC IdP config (JIT, allowed
--                                 email domains, encrypted client_secret).
--   * Additive ``tenant_id`` columns on isolatable resources (projects,
--     alert_subscriptions, document_project_pins, project_docket_pins).
--     Nullable during backfill grace period — application code MUST treat
--     NULL as "legacy single-tenant row" and not rely on tenant_id being
--     populated everywhere until the backfill finishes.
--
-- Idempotent: safe to re-run. ALTERs are guarded by DO-blocks that check
-- ``information_schema.tables`` so environments that have not yet created
-- ``projects`` / ``alert_subscriptions`` don't error out.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- ── tenants ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug           text UNIQUE NOT NULL,
    display_name   text NOT NULL,
    plan           text CHECK (plan IN ('individual','team','enterprise'))
                        DEFAULT 'individual',
    white_label    jsonb,
    trust_badges   jsonb DEFAULT '{}'::jsonb,
    created_at     timestamptz DEFAULT now(),
    updated_at     timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenants_plan ON tenants(plan);


-- ── tenant_memberships ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenant_memberships (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL,
    role        text CHECK (role IN ('owner','admin','member','viewer'))
                     DEFAULT 'member',
    joined_at   timestamptz DEFAULT now(),
    UNIQUE (tenant_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_tenant_memberships_user   ON tenant_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_tenant_memberships_tenant ON tenant_memberships(tenant_id);


-- ── tenant_sso_configs ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenant_sso_configs (
    id                         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider                   text NOT NULL CHECK (provider IN
                                   ('google','azure','okta','generic_oidc')),
    issuer_url                 text NOT NULL,
    client_id                  text NOT NULL,
    client_secret_encrypted    bytea NOT NULL,
    metadata_url               text,
    allowed_email_domains      text[] DEFAULT '{}',
    jit_provisioning           boolean DEFAULT true,
    default_role               text DEFAULT 'member',
    created_at                 timestamptz DEFAULT now(),
    updated_at                 timestamptz DEFAULT now(),
    UNIQUE (tenant_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_tenant_sso_tenant ON tenant_sso_configs(tenant_id);


-- ── Additive tenant_id columns on isolatable resources ─────────────────────
-- Each ALTER is wrapped in a DO-block that first checks the target table
-- exists. This keeps the migration idempotent AND safe on environments where
-- the table has not been created yet (e.g. dockets not rolled out).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'projects') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'projects' AND column_name = 'tenant_id') THEN
            ALTER TABLE projects
                ADD COLUMN tenant_id uuid REFERENCES tenants(id);
        END IF;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'alert_subscriptions') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'alert_subscriptions' AND column_name = 'tenant_id') THEN
            ALTER TABLE alert_subscriptions
                ADD COLUMN tenant_id uuid REFERENCES tenants(id);
        END IF;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'document_project_pins') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'document_project_pins' AND column_name = 'tenant_id') THEN
            ALTER TABLE document_project_pins
                ADD COLUMN tenant_id uuid REFERENCES tenants(id);
        END IF;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'project_docket_pins') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'project_docket_pins' AND column_name = 'tenant_id') THEN
            ALTER TABLE project_docket_pins
                ADD COLUMN tenant_id uuid REFERENCES tenants(id);
        END IF;
    END IF;
END $$;

-- Partial indexes scoped to non-null tenant_id — keeps index small while the
-- legacy single-tenant rows remain untagged during the grace period.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'projects' AND column_name = 'tenant_id') THEN
        CREATE INDEX IF NOT EXISTS idx_projects_tenant
            ON projects(tenant_id) WHERE tenant_id IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'alert_subscriptions' AND column_name = 'tenant_id') THEN
        CREATE INDEX IF NOT EXISTS idx_alert_subs_tenant
            ON alert_subscriptions(tenant_id) WHERE tenant_id IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'document_project_pins' AND column_name = 'tenant_id') THEN
        CREATE INDEX IF NOT EXISTS idx_doc_pins_tenant
            ON document_project_pins(tenant_id) WHERE tenant_id IS NOT NULL;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'project_docket_pins' AND column_name = 'tenant_id') THEN
        CREATE INDEX IF NOT EXISTS idx_docket_pins_tenant
            ON project_docket_pins(tenant_id) WHERE tenant_id IS NOT NULL;
    END IF;
END $$;
