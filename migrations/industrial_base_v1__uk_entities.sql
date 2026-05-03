-- Princeps Industrial Base Graph v1 — UK-only.
-- Tables for Companies House (OGL) + GLEIF LEI (CC0) + UK consolidated
-- sanctions list (OGL) + the canonical Princeps `entities` + `entity_relationships`
-- graph that the ontology RIDs hang off.
--
-- All artifact licences are commercial-safe. Registered in
-- app/license_guard/licenses.yaml as: gleif_lei, uk_companies_house,
-- uk_sanctions_consolidated.

-- ---------- 1. Canonical entity + relationship graph -------------------
CREATE TABLE IF NOT EXISTS entities (
    rid             TEXT PRIMARY KEY,
    legal_name      TEXT        NOT NULL,
    lei             TEXT,
    ch_number       TEXT,
    role            TEXT,                                -- developer / landowner / dno / offtaker / ...
    parent_rid      TEXT REFERENCES entities(rid) ON DELETE SET NULL,
    sanctions_flag  BOOLEAN     NOT NULL DEFAULT FALSE,
    geom            geometry(Point, 27700),              -- registered office, OSGB36
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS entities_lei_idx        ON entities (lei);
CREATE INDEX IF NOT EXISTS entities_ch_idx         ON entities (ch_number);
CREATE INDEX IF NOT EXISTS entities_parent_idx     ON entities (parent_rid);
CREATE INDEX IF NOT EXISTS entities_sanctions_idx  ON entities (sanctions_flag) WHERE sanctions_flag;
CREATE INDEX IF NOT EXISTS entities_geom_gix       ON entities USING GIST (geom);


CREATE TABLE IF NOT EXISTS entity_relationships (
    rid          TEXT PRIMARY KEY,
    from_rid     TEXT NOT NULL REFERENCES entities(rid) ON DELETE CASCADE,
    to_rid       TEXT NOT NULL REFERENCES entities(rid) ON DELETE CASCADE,
    rel_type     TEXT NOT NULL,                          -- owns / contracts_with / supplies_to / ...
    properties   JSONB,
    since        DATE,
    until        DATE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS entity_rel_from_idx     ON entity_relationships (from_rid);
CREATE INDEX IF NOT EXISTS entity_rel_to_idx       ON entity_relationships (to_rid);
CREATE INDEX IF NOT EXISTS entity_rel_type_idx     ON entity_relationships (rel_type);


-- ---------- 2. GLEIF LEI cache (CC0) -----------------------------------
CREATE TABLE IF NOT EXISTS gleif_lei_cache (
    lei              TEXT PRIMARY KEY,
    legal_name       TEXT,
    legal_form_code  TEXT,
    jurisdiction     TEXT,
    status           TEXT,                  -- ACTIVE / LAPSED / RETIRED
    parent_lei       TEXT,
    ultimate_lei     TEXT,
    address          JSONB,
    raw              JSONB,
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS gleif_parent_idx        ON gleif_lei_cache (parent_lei);
CREATE INDEX IF NOT EXISTS gleif_jurisdiction_idx  ON gleif_lei_cache (jurisdiction);


-- ---------- 3. Companies House cache (OGL) -----------------------------
CREATE TABLE IF NOT EXISTS companies_house_cache (
    company_number   TEXT PRIMARY KEY,
    name             TEXT,
    status           TEXT,                  -- active / dissolved / liquidation / ...
    incorporation    DATE,
    sic_codes        JSONB,                 -- e.g. ["35110","35120"] — electricity gen + transmission
    registered_office JSONB,
    raw              JSONB,
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ch_status_idx     ON companies_house_cache (status);
CREATE INDEX IF NOT EXISTS ch_sic_gin        ON companies_house_cache USING GIN (sic_codes);


-- ---------- 4. UK consolidated sanctions list (OGL) --------------------
CREATE TABLE IF NOT EXISTS uk_sanctions_list (
    entry_id         TEXT PRIMARY KEY,         -- HMT "Group ID" or stable hash
    full_name        TEXT NOT NULL,
    aliases          TEXT[],
    dob              DATE,
    nationality      TEXT,
    regime           TEXT,                     -- "Russia", "DPRK", "Cyber" ...
    listing_date     DATE,
    sanctions_type   TEXT,                     -- asset_freeze / travel_ban / prohibited_dealings
    raw              JSONB,
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS uk_sanctions_name_trgm
    ON uk_sanctions_list USING GIN (full_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS uk_sanctions_aliases_gin
    ON uk_sanctions_list USING GIN (aliases);

-- pg_trgm needed for fuzzy name matching against UK sanctions.
CREATE EXTENSION IF NOT EXISTS pg_trgm;


-- ---------- 5. Sanctions match journal ---------------------------------
CREATE TABLE IF NOT EXISTS sanctions_matches (
    rid          TEXT PRIMARY KEY,
    entity_rid   TEXT NOT NULL REFERENCES entities(rid) ON DELETE CASCADE,
    sanctions_entry_id TEXT NOT NULL REFERENCES uk_sanctions_list(entry_id) ON DELETE CASCADE,
    score        DOUBLE PRECISION NOT NULL,    -- 0..1, fuzzy score
    matched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed     BOOLEAN NOT NULL DEFAULT FALSE,
    reviewer     TEXT,
    verdict      TEXT                          -- "true_match" / "false_positive" / null
);
CREATE INDEX IF NOT EXISTS sanctions_matches_entity_idx ON sanctions_matches (entity_rid);
CREATE INDEX IF NOT EXISTS sanctions_matches_score_idx  ON sanctions_matches (score DESC);


-- ---------- 6. Updated_at trigger for entities -------------------------
CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END $$;

DROP TRIGGER IF EXISTS entities_touch ON entities;
CREATE TRIGGER entities_touch BEFORE UPDATE ON entities
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
