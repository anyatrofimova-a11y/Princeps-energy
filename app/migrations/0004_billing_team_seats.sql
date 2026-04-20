-- =============================================================================
-- 0004_billing_team_seats.sql
-- -----------------------------------------------------------------------------
-- Princeps — Team-tier seat management for the Stripe billing router
-- (``app/routers/billing.py``, Task #11).
--
-- Two tables:
--   * ``team_memberships``  — accepted members under an owner's subscription.
--   * ``team_invites``      — pending invite tokens emailed to prospective members.
--
-- Depends on ``user_subscriptions`` (0003_user_subscriptions.sql) — the team
-- tier is resolved by (a) the owner's subscription row and (b) each member
-- being accepted into ``team_memberships``.
--
-- Idempotent: safe to re-run.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- team_memberships
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_memberships (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id    uuid NOT NULL,
    member_user_id   uuid NOT NULL,
    role             text CHECK (role IN ('owner','admin','member')) DEFAULT 'member',
    accepted_at      timestamptz,
    created_at       timestamptz DEFAULT now(),
    UNIQUE (owner_user_id, member_user_id)
);

CREATE INDEX IF NOT EXISTS idx_team_memberships_owner
    ON team_memberships(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_team_memberships_member
    ON team_memberships(member_user_id);

-- ---------------------------------------------------------------------------
-- team_invites
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_invites (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id     uuid NOT NULL,
    invited_email     text NOT NULL,
    token             text UNIQUE NOT NULL,
    expires_at        timestamptz NOT NULL,
    accepted_at       timestamptz,
    created_at        timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_team_invites_token
    ON team_invites(token);
CREATE INDEX IF NOT EXISTS idx_team_invites_email
    ON team_invites(invited_email);
