-- =============================================================================
-- 0001_intelligence_schema.sql
-- -----------------------------------------------------------------------------
-- Princeps Phase 7a — shared Intelligence schema for Alerts, Dockets and
-- Data Subscriptions. Derived from the council-approved final spec.
--
-- Idempotent: safe to re-run. All tables use CREATE TABLE IF NOT EXISTS and
-- all indexes use CREATE INDEX IF NOT EXISTS.
--
-- Applied on startup by app/db_setup.py (gated on existence of `documents`
-- table to keep the check cheap in the hot path).
-- =============================================================================

-- ── Required extensions ─────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
-- pgcrypto provides gen_random_uuid() on Postgres < 13. On 13+ the function
-- is available in core (pg_catalog) but pgcrypto is still the canonical
-- provider and installing the extension is a no-op if already present.
CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- ── AUTHORITIES: publisher / regulator / LPA / DNO / consultee registry ─────
CREATE TABLE IF NOT EXISTS authorities (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug           text UNIQUE NOT NULL,
    name           text NOT NULL,
    acronym        text,
    type           text NOT NULL CHECK (type IN (
                       'regulator','authority','lpa','dno','to','gso',
                       'statutory_consultee','appeal_body','community','ngo',
                       'political','legal','industry_body','lender','devolved',
                       'crown')),
    jurisdiction   text NOT NULL CHECK (jurisdiction IN (
                       'E','W','S','NI','GB','UK','EU')),
    home_url       text,
    logo_url       text,
    api_available  boolean DEFAULT false,
    geometry       geography(Geometry, 4326),
    created_at     timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_authorities_type_juris ON authorities(type, jurisdiction);
CREATE INDEX IF NOT EXISTS idx_authorities_geom      ON authorities USING GIST(geometry);


-- ── DOCKETS: proceedings ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dockets (
    docket_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source                 text NOT NULL,
    source_docket_id       text,
    publisher_id           uuid REFERENCES authorities(id),
    title                  text NOT NULL,
    description            text,
    case_type              text CHECK (case_type IN (
                               'nsip_dco','lpa_planning','section36','scottish_dns',
                               'ofgem_consultation','ofgem_decision','code_mod',
                               'cfd_round','cm_auction','riio_control',
                               'dno_connection_case','appeal','call_in',
                               'cma_appeal','judicial_review','hse_comah',
                               'ea_permit','cmp','gc','cusc','bsc_pmod',
                               'dcusa_dcp','stc','misc')),
    industry               text CHECK (industry IN (
                               'electricity','gas','hydrogen','heat',
                               'interconnector','other')),
    status                 text,
    stage                  text CHECK (stage IN (
                               'pre_app','acceptance','pre_examination',
                               'examination','recommendation','decision',
                               'challenge','post_consent','made','withdrawn',
                               'suspended','closed')),
    applicant_name         text,
    account_name           text,
    statutory_deadline     date,
    opened_at              timestamptz,
    closed_at              timestamptz,
    geometry               geography(Geometry, 4326),
    exec_summary_text      text,
    exec_summary_cached_at timestamptz,
    created_at             timestamptz DEFAULT now(),
    updated_at             timestamptz DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dockets_source_external
    ON dockets(source, source_docket_id);
CREATE INDEX IF NOT EXISTS idx_dockets_case_type       ON dockets(case_type);
CREATE INDEX IF NOT EXISTS idx_dockets_stage_deadline  ON dockets(stage, statutory_deadline);
CREATE INDEX IF NOT EXISTS idx_dockets_geom            ON dockets USING GIST(geometry);
CREATE INDEX IF NOT EXISTS idx_dockets_publisher       ON dockets(publisher_id);


-- ── DOCUMENTS: individual filings ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    doc_id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source               text NOT NULL,
    source_url           text UNIQUE NOT NULL,
    docket_id            uuid REFERENCES dockets(docket_id) ON DELETE SET NULL,
    commission_authority text,
    filing_type          text,
    procedural_stage     text,
    title                text NOT NULL,
    body_text            text,
    body_pdf_path        text,
    pages                int,
    published_at         timestamptz,
    ingested_at          timestamptz DEFAULT now(),
    topic_tags           jsonb,
    extracted_fields     jsonb,
    embedding            vector(1536),
    geometry             geography(Point, 4326),
    stakeholder_id       uuid,  -- FK added after stakeholders table created
    tsv                  tsvector GENERATED ALWAYS AS (
                             to_tsvector('english',
                                 coalesce(title,'') || ' ' || coalesce(body_text,''))
                         ) STORED,
    created_at           timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_documents_source      ON documents(source);
CREATE INDEX IF NOT EXISTS idx_documents_docket      ON documents(docket_id);
CREATE INDEX IF NOT EXISTS idx_documents_filing_type ON documents(filing_type);
CREATE INDEX IF NOT EXISTS idx_documents_published   ON documents(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_embedding
    ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists=50);
CREATE INDEX IF NOT EXISTS idx_documents_geom        ON documents USING GIST(geometry);
CREATE INDEX IF NOT EXISTS idx_documents_tsv         ON documents USING GIN(tsv);
CREATE INDEX IF NOT EXISTS idx_documents_topic_tags  ON documents USING GIN(topic_tags);


-- ── STAKEHOLDERS: per-docket participants ───────────────────────────────────
CREATE TABLE IF NOT EXISTS stakeholders (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    docket_id            uuid NOT NULL REFERENCES dockets(docket_id) ON DELETE CASCADE,
    authority_id         uuid REFERENCES authorities(id),
    company_number       text,
    person_name          text,
    display_name         text NOT NULL,
    role                 text NOT NULL CHECK (role IN (
                             'applicant','co_applicant','spv','statutory_consultee',
                             'regulator','network_operator','lpa','parish_council',
                             'county_council','consumer_body','industry_body',
                             'objector','supporter','interested_party',
                             'government_agency','political','legal_rep',
                             'technical_reviewer','lender','neutral','intervenor',
                             'consultee')),
    position             text CHECK (position IN (
                             'for','against','conditions','neutral','unknown',
                             'withdrawn')) DEFAULT 'unknown',
    represented_by       uuid REFERENCES stakeholders(id),
    first_submission_at  timestamptz,
    last_submission_at   timestamptz,
    submission_count     int DEFAULT 0,
    created_at           timestamptz DEFAULT now(),
    UNIQUE (docket_id, display_name)
);
CREATE INDEX IF NOT EXISTS idx_stakeholders_docket
    ON stakeholders(docket_id, role, position);
CREATE INDEX IF NOT EXISTS idx_stakeholders_authority ON stakeholders(authority_id);
CREATE INDEX IF NOT EXISTS idx_stakeholders_company   ON stakeholders(company_number);


-- Deferred FK: documents.stakeholder_id → stakeholders.id
-- Wrapped so re-runs skip the ADD CONSTRAINT cleanly.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_documents_stakeholder'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT fk_documents_stakeholder
            FOREIGN KEY (stakeholder_id) REFERENCES stakeholders(id)
            ON DELETE SET NULL;
    END IF;
END $$;


-- ── STAKEHOLDER_SUBMISSIONS: audit trail ────────────────────────────────────
CREATE TABLE IF NOT EXISTS stakeholder_submissions (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    stakeholder_id   uuid NOT NULL REFERENCES stakeholders(id) ON DELETE CASCADE,
    doc_id           uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    submission_type  text,
    submitted_at     timestamptz NOT NULL,
    position_change  text,
    created_at       timestamptz DEFAULT now(),
    UNIQUE (stakeholder_id, doc_id)
);
CREATE INDEX IF NOT EXISTS idx_submissions_stakeholder
    ON stakeholder_submissions(stakeholder_id, submitted_at DESC);


-- ── DOCKET_TIMELINE_EVENTS ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS docket_timeline_events (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    docket_id         uuid NOT NULL REFERENCES dockets(docket_id) ON DELETE CASCADE,
    event_type        text NOT NULL,
    event_at          date NOT NULL,
    summary_text      text,
    doc_id            uuid REFERENCES documents(doc_id),
    forward_looking   boolean DEFAULT false,
    deadline_at       date,
    created_at        timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_timeline_docket_event
    ON docket_timeline_events(docket_id, event_at);
CREATE INDEX IF NOT EXISTS idx_timeline_upcoming
    ON docket_timeline_events(docket_id, forward_looking, deadline_at)
    WHERE forward_looking = true;


-- ── CONSULTEE_REQUIREMENTS: rules engine for auto-deriving consultees ───────
CREATE TABLE IF NOT EXISTS consultee_requirements (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_type                text NOT NULL,
    trigger                  jsonb NOT NULL,
    authority_id             uuid NOT NULL REFERENCES authorities(id),
    mandatory                boolean DEFAULT true,
    consultation_period_days int,
    statutory_basis          text,
    reason_code              text,
    draft_letter_slug        text,
    created_at               timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_consultee_req_case ON consultee_requirements(case_type);


-- ── ALERT_DEFINITIONS ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_definitions (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                  text UNIQUE NOT NULL,
    title                 text NOT NULL,
    description           text,
    cluster               text,
    source_filter         jsonb NOT NULL,
    llm_prompt            text,
    cadence               text NOT NULL CHECK (cadence IN (
                              'realtime','daily','weekday',
                              'weekly_mon','weekly_tue','weekly_wed',
                              'weekly_thu','weekly_fri',
                              'biweekly','monthly')),
    est_docs_per_digest   int,
    icp_tags              text[] DEFAULT '{}',
    created_by            uuid,
    is_public             boolean DEFAULT true,
    created_at            timestamptz DEFAULT now(),
    updated_at            timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_alert_defs_cluster ON alert_definitions(cluster);
CREATE INDEX IF NOT EXISTS idx_alert_defs_cadence ON alert_definitions(cadence);


-- ── ALERT_SUBSCRIPTIONS ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_subscriptions (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            text NOT NULL,
    alert_id           uuid NOT NULL REFERENCES alert_definitions(id) ON DELETE CASCADE,
    delivery_channels  jsonb DEFAULT '{"email":true,"in_app":true,"slack":false}'::jsonb,
    pinned_project_id  uuid,
    muted              boolean DEFAULT false,
    created_at         timestamptz DEFAULT now(),
    updated_at         timestamptz DEFAULT now(),
    UNIQUE (user_id, alert_id, pinned_project_id)
);
CREATE INDEX IF NOT EXISTS idx_alert_subs_user  ON alert_subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_alert_subs_alert ON alert_subscriptions(alert_id);


-- ── ALERT_DIGESTS ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_digests (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id        uuid NOT NULL REFERENCES alert_definitions(id) ON DELETE CASCADE,
    run_at          timestamptz NOT NULL,
    document_ids    uuid[] NOT NULL DEFAULT '{}',
    llm_extract     text,
    llm_structured  jsonb,
    sent_at         timestamptz,
    created_at      timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_digests_alert_run
    ON alert_digests(alert_id, run_at DESC);


-- ── DATA_SUBSCRIPTIONS ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS data_subscriptions (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                    text UNIQUE NOT NULL,
    title                   text NOT NULL,
    description             text,
    schema                  jsonb,
    refresh_interval_hours  int DEFAULT 24,
    last_refreshed_at       timestamptz,
    is_public               boolean DEFAULT false,
    price_tier              text CHECK (price_tier IN (
                                'free','individual','team','enterprise')) DEFAULT 'enterprise',
    created_at              timestamptz DEFAULT now(),
    updated_at              timestamptz DEFAULT now()
);


-- ── DATA_SUBSCRIPTION_ROWS (diff-tracked) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS data_subscription_rows (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id  uuid NOT NULL REFERENCES data_subscriptions(id) ON DELETE CASCADE,
    external_id      text,
    row              jsonb NOT NULL,
    geom             geography(Geometry, 4326),
    added_at         timestamptz DEFAULT now(),
    removed_at       timestamptz,
    changed_fields   jsonb,
    created_at       timestamptz DEFAULT now(),
    UNIQUE (subscription_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_data_rows_sub    ON data_subscription_rows(subscription_id);
CREATE INDEX IF NOT EXISTS idx_data_rows_active
    ON data_subscription_rows(subscription_id) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_data_rows_geom
    ON data_subscription_rows USING GIST(geom);


-- ── DOCUMENT_PROJECT_PINS ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS document_project_pins (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL,
    doc_id      uuid NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    pinned_by   text NOT NULL,
    role        text CHECK (role IN (
                    'evidence','precedent','constraint','counterfactual'
                )) DEFAULT 'evidence',
    note        text,
    created_at  timestamptz DEFAULT now(),
    UNIQUE (project_id, doc_id)
);
CREATE INDEX IF NOT EXISTS idx_doc_pins_project ON document_project_pins(project_id);


-- ── PROJECT_DOCKET_PINS ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS project_docket_pins (
    project_id            uuid NOT NULL,
    docket_id             uuid NOT NULL REFERENCES dockets(docket_id) ON DELETE CASCADE,
    pinned_by             text NOT NULL,
    note                  text,
    agent_verdict_impact  jsonb,
    created_at            timestamptz DEFAULT now(),
    PRIMARY KEY (project_id, docket_id)
);


-- ── DOCKET_WATCHES ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS docket_watches (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      text NOT NULL,
    docket_id    uuid NOT NULL REFERENCES dockets(docket_id) ON DELETE CASCADE,
    cadence      text CHECK (cadence IN (
                     'realtime','daily','weekly','on_deadline')) DEFAULT 'daily',
    channels     jsonb DEFAULT '{"email":true,"in_app":true,"slack":false}'::jsonb,
    filters      jsonb,
    created_at   timestamptz DEFAULT now(),
    UNIQUE (user_id, docket_id)
);


-- ── DOCKET_QA_CACHE ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS docket_qa_cache (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    docket_id      uuid NOT NULL REFERENCES dockets(docket_id) ON DELETE CASCADE,
    question       text NOT NULL,
    answer         text NOT NULL,
    citations      jsonb,
    generated_at   timestamptz DEFAULT now(),
    UNIQUE (docket_id, question)
);
