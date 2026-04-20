-- =============================================================================
-- 0003_user_subscriptions.sql
-- -----------------------------------------------------------------------------
-- Princeps — Stripe-backed subscription tier per user for the Alerts paywall.
--
-- Drives the 5-alert soft cap on free-tier accounts enforced in
-- ``app/routers/alerts.py``. When a Stripe webhook upgrades a user, it
-- updates this table and the cap is lifted automatically.
--
-- Idempotent: safe to re-run. The ``tier`` column is constrained to the same
-- literals as ``models.intelligence.PriceTier``.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS user_subscriptions (
    user_id                 text PRIMARY KEY,
    tier                    text NOT NULL DEFAULT 'free'
                            CHECK (tier IN ('free','individual','team','enterprise')),
    stripe_customer_id      text,
    stripe_subscription_id  text,
    current_period_end      timestamptz,
    trial_ends_at           timestamptz,
    created_at              timestamptz DEFAULT now(),
    updated_at              timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_subs_tier ON user_subscriptions(tier);
CREATE INDEX IF NOT EXISTS idx_user_subs_stripe_customer
    ON user_subscriptions(stripe_customer_id)
    WHERE stripe_customer_id IS NOT NULL;
