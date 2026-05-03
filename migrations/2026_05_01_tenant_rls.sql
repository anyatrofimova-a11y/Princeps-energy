-- =============================================================================
-- 2026_05_01_tenant_rls.sql
-- -----------------------------------------------------------------------------
-- Princeps — multi-tenant isolation via Postgres Row-Level Security.
--
-- What this lands:
--   * tenant_id (uuid) on the most sensitive tables, with a default tenant
--     UUID for backfill so existing rows keep working without a NULL hole.
--   * RLS enabled on those tables.
--   * A permissive read/write policy gated on
--       current_setting('princeps.tenant_id', true) :: uuid
--     The middleware (app/middleware/tenant_jwt.py) sets this GUC at the
--     start of every authenticated request.
--   * Idempotent — every ALTER, CREATE POLICY and ENABLE is guarded so
--     re-runs are safe.
--
-- Day-1 rollout note (intentional):
--   The policy passes when the GUC is unset OR matches the row's tenant_id.
--   That keeps existing demo / cron / pulse seed jobs running while the
--   middleware ramps up. To tighten in week 2, drop the
--   "GUC IS NULL" branch from the USING / WITH CHECK clauses.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── Default tenant for backfill ─────────────────────────────────────────────
-- Single sentinel UUID so existing rows can be tagged in a single UPDATE.
-- The tenants row itself only needs to exist — the slug name doesn't matter
-- for RLS, only the UUID match against the GUC.
INSERT INTO tenants (id, slug, display_name, plan)
VALUES (
    '00000000-0000-0000-0000-000000000001'::uuid,
    'princeps-default',
    'Princeps Default Tenant',
    'individual'
)
ON CONFLICT (id) DO NOTHING;


-- ── Helper: add tenant_id + backfill + RLS in one DO-block per table ────────
-- Tables we apply this to:
--   * projects                        (already has tenant_id from 0005)
--   * prospect_parcels                (Site ontology object)
--   * planning_applications_submitted (Application ontology object)
--   * procurement_tenders_raw         (Tender ontology object)
--   * ontology_action_log             (audit trail)
--   * action_audit_log                (typed-action audit trail)

-- ── projects ───────────────────────────────────────────────────────────────
-- (column already added by 0005_enterprise_tenancy; just backfill + RLS.)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'projects') THEN
        UPDATE projects
        SET tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
        WHERE tenant_id IS NULL;

        ALTER TABLE projects ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS projects_tenant_isolation ON projects;
        CREATE POLICY projects_tenant_isolation ON projects
            USING (
                current_setting('princeps.tenant_id', true) IS NULL
                OR current_setting('princeps.tenant_id', true) = ''
                OR tenant_id::text = current_setting('princeps.tenant_id', true)
            )
            WITH CHECK (
                current_setting('princeps.tenant_id', true) IS NULL
                OR current_setting('princeps.tenant_id', true) = ''
                OR tenant_id::text = current_setting('princeps.tenant_id', true)
            );
    END IF;
END $$;


-- ── prospect_parcels (Site) ────────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'prospect_parcels') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'prospect_parcels' AND column_name = 'tenant_id') THEN
            ALTER TABLE prospect_parcels
                ADD COLUMN tenant_id uuid REFERENCES tenants(id);
        END IF;

        UPDATE prospect_parcels
        SET tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
        WHERE tenant_id IS NULL;

        CREATE INDEX IF NOT EXISTS idx_prospect_parcels_tenant
            ON prospect_parcels(tenant_id) WHERE tenant_id IS NOT NULL;

        ALTER TABLE prospect_parcels ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS prospect_parcels_tenant_isolation ON prospect_parcels;
        CREATE POLICY prospect_parcels_tenant_isolation ON prospect_parcels
            USING (
                current_setting('princeps.tenant_id', true) IS NULL
                OR current_setting('princeps.tenant_id', true) = ''
                OR tenant_id::text = current_setting('princeps.tenant_id', true)
            )
            WITH CHECK (
                current_setting('princeps.tenant_id', true) IS NULL
                OR current_setting('princeps.tenant_id', true) = ''
                OR tenant_id::text = current_setting('princeps.tenant_id', true)
            );
    END IF;
END $$;


-- ── planning_applications_submitted (Application) ──────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'planning_applications_submitted') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'planning_applications_submitted' AND column_name = 'tenant_id') THEN
            ALTER TABLE planning_applications_submitted
                ADD COLUMN tenant_id uuid REFERENCES tenants(id);
        END IF;

        UPDATE planning_applications_submitted
        SET tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
        WHERE tenant_id IS NULL;

        CREATE INDEX IF NOT EXISTS idx_planning_applications_submitted_tenant
            ON planning_applications_submitted(tenant_id) WHERE tenant_id IS NOT NULL;

        ALTER TABLE planning_applications_submitted ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS pas_tenant_isolation ON planning_applications_submitted;
        CREATE POLICY pas_tenant_isolation ON planning_applications_submitted
            USING (
                current_setting('princeps.tenant_id', true) IS NULL
                OR current_setting('princeps.tenant_id', true) = ''
                OR tenant_id::text = current_setting('princeps.tenant_id', true)
            )
            WITH CHECK (
                current_setting('princeps.tenant_id', true) IS NULL
                OR current_setting('princeps.tenant_id', true) = ''
                OR tenant_id::text = current_setting('princeps.tenant_id', true)
            );
    END IF;
END $$;


-- ── procurement_tenders_raw (Tender) ───────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'procurement_tenders_raw') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'procurement_tenders_raw' AND column_name = 'tenant_id') THEN
            ALTER TABLE procurement_tenders_raw
                ADD COLUMN tenant_id uuid REFERENCES tenants(id);
        END IF;

        UPDATE procurement_tenders_raw
        SET tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
        WHERE tenant_id IS NULL;

        CREATE INDEX IF NOT EXISTS idx_procurement_tenders_raw_tenant
            ON procurement_tenders_raw(tenant_id) WHERE tenant_id IS NOT NULL;

        ALTER TABLE procurement_tenders_raw ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS ptr_tenant_isolation ON procurement_tenders_raw;
        CREATE POLICY ptr_tenant_isolation ON procurement_tenders_raw
            USING (
                current_setting('princeps.tenant_id', true) IS NULL
                OR current_setting('princeps.tenant_id', true) = ''
                OR tenant_id::text = current_setting('princeps.tenant_id', true)
            )
            WITH CHECK (
                current_setting('princeps.tenant_id', true) IS NULL
                OR current_setting('princeps.tenant_id', true) = ''
                OR tenant_id::text = current_setting('princeps.tenant_id', true)
            );
    END IF;
END $$;


-- ── ontology_action_log (audit trail) ──────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'ontology_action_log') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'ontology_action_log' AND column_name = 'tenant_id') THEN
            ALTER TABLE ontology_action_log
                ADD COLUMN tenant_id uuid REFERENCES tenants(id);
        END IF;

        UPDATE ontology_action_log
        SET tenant_id = '00000000-0000-0000-0000-000000000001'::uuid
        WHERE tenant_id IS NULL;

        CREATE INDEX IF NOT EXISTS idx_ontology_action_log_tenant
            ON ontology_action_log(tenant_id, started_utc DESC) WHERE tenant_id IS NOT NULL;

        ALTER TABLE ontology_action_log ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS oal_tenant_isolation ON ontology_action_log;
        CREATE POLICY oal_tenant_isolation ON ontology_action_log
            USING (
                current_setting('princeps.tenant_id', true) IS NULL
                OR current_setting('princeps.tenant_id', true) = ''
                OR tenant_id::text = current_setting('princeps.tenant_id', true)
            )
            WITH CHECK (
                current_setting('princeps.tenant_id', true) IS NULL
                OR current_setting('princeps.tenant_id', true) = ''
                OR tenant_id::text = current_setting('princeps.tenant_id', true)
            );
    END IF;
END $$;


-- ── action_audit_log (typed-action audit) ──────────────────────────────────
-- Note: this table already has a tenant_id text column. We don't drop it —
-- we keep the text column (registry.py inserts a string) and add no RLS-
-- typed conversion. RLS can still gate on the text-cast match.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'action_audit_log') THEN
        UPDATE action_audit_log
        SET tenant_id = '00000000-0000-0000-0000-000000000001'
        WHERE tenant_id IS NULL OR tenant_id = '';

        ALTER TABLE action_audit_log ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS aal_tenant_isolation ON action_audit_log;
        CREATE POLICY aal_tenant_isolation ON action_audit_log
            USING (
                current_setting('princeps.tenant_id', true) IS NULL
                OR current_setting('princeps.tenant_id', true) = ''
                OR tenant_id = current_setting('princeps.tenant_id', true)
            )
            WITH CHECK (
                current_setting('princeps.tenant_id', true) IS NULL
                OR current_setting('princeps.tenant_id', true) = ''
                OR tenant_id = current_setting('princeps.tenant_id', true)
            );
    END IF;
END $$;
