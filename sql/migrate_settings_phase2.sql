-- migrate_settings_phase2.sql
-- Fills in gaps needed to wire up the Settings panel (Team / Notifications /
-- API Keys) and aligns the deployed users table with what app.routers.auth
-- expects. Idempotent — safe to re-run.

-- ── Users: add auth columns the hotfix migration missed ──────────────────
-- The minimal users table from migrate_agents_phase2_hotfix.sql shipped with
-- only (user_id, email, name, created_at). app.routers.auth and Settings →
-- Team need org_name, role, password_hash, api_key, last_login.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS org_name       text,
    ADD COLUMN IF NOT EXISTS role           text DEFAULT 'analyst',
    ADD COLUMN IF NOT EXISTS password_hash  text,
    ADD COLUMN IF NOT EXISTS api_key        text UNIQUE,
    ADD COLUMN IF NOT EXISTS last_login     timestamptz;

-- Default org for the single-user seed. Leaving org_name nullable so fresh
-- sign-ups can set it during registration rather than being forced at bootstrap.
UPDATE users
   SET role = COALESCE(role, 'admin')
 WHERE email = 'anya.trofimova@yahoo.com';

-- ── API Keys (token set per user) ───────────────────────────────────────
-- users.api_key gives you exactly one token per user. We want multiple
-- (one per integration, rotatable independently) — same pattern as Stripe
-- restricted keys. Store only the hash, never the plaintext, and expose
-- last_used_at for a "stale? revoke" signal in the UI.
CREATE TABLE IF NOT EXISTS api_keys (
    id              bigserial PRIMARY KEY,
    user_id         uuid NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name            text NOT NULL,              -- user-supplied label (e.g. "CI", "Zapier")
    key_prefix      text NOT NULL,              -- first 8 chars shown in UI (e.g. "pcp_abc1")
    key_hash        text NOT NULL,              -- sha256 of the full token; plaintext never stored
    scopes          text[] NOT NULL DEFAULT '{read}',
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_used_at    timestamptz,
    revoked_at      timestamptz,
    UNIQUE (user_id, name)
);
CREATE INDEX IF NOT EXISTS api_keys_user_active
    ON api_keys (user_id, created_at DESC)
    WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS api_keys_hash
    ON api_keys (key_hash)
    WHERE revoked_at IS NULL;

-- ── Agent notifications (delivery log + inbox) ─────────────────────────
-- Distinct from the pre-existing `notifications` table (which uses a
-- rule-based event schema with user_id::text and a `read` boolean). This
-- table is for agent-generated notifications only — rich enough to drive
-- the Settings → Notifications inbox UI, with a channel + severity +
-- delivery timestamps.
CREATE TABLE IF NOT EXISTS agent_notifications (
    id              bigserial PRIMARY KEY,
    user_id         uuid REFERENCES users(user_id) ON DELETE CASCADE,
    channel         text NOT NULL CHECK (channel IN ('slack', 'email', 'inapp')),
    severity        text NOT NULL DEFAULT 'info'
                    CHECK (severity IN ('info', 'warn', 'alert')),
    title           text NOT NULL,
    body            text,
    link_url        text,
    source_agent    text,
    delivered_at    timestamptz,
    read_at         timestamptz,
    data            jsonb DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_notifications_user_recent
    ON agent_notifications (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS agent_notifications_unread
    ON agent_notifications (user_id, created_at DESC)
    WHERE read_at IS NULL;
