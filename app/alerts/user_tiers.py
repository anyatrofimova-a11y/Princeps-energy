"""
app/alerts/user_tiers.py — price-tier helper.

Backs the 5-alert soft cap enforced in ``app/routers/alerts.py``. Reads from
``user_subscriptions`` (migration ``0003_user_subscriptions.sql``). Missing
rows resolve to the ``free`` tier so the first-boot / demo user never trips
the cap unexpectedly for reasons other than genuine overuse.

When a Stripe webhook lands it should upsert this row with the new ``tier``
and the cap is lifted on the next request. Stripe integration lives outside
this module.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Literal

import asyncpg

log = logging.getLogger("princeps.alerts.user_tiers")

Tier = Literal["free", "individual", "team", "enterprise"]

_MIGRATION_PATH = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "0003_user_subscriptions.sql"


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Apply migration 0003 if the ``user_subscriptions`` table is missing."""
    async with pool.acquire() as conn:
        present = await conn.fetchval(
            "SELECT to_regclass('public.user_subscriptions') IS NOT NULL"
        )
        if present:
            return
        if not _MIGRATION_PATH.exists():
            log.warning("user_subscriptions migration file missing at %s", _MIGRATION_PATH)
            return
        try:
            await conn.execute(_MIGRATION_PATH.read_text())
            log.info("Applied 0003_user_subscriptions.sql")
        except Exception:
            log.exception("0003_user_subscriptions.sql failed — alert cap will default every user to free")


async def get_user_tier(pool: asyncpg.Pool, user_id: str) -> Tier:
    """Return the current tier for *user_id*. Defaults to ``'free'``.

    Resolution order:
      1. The user's own ``user_subscriptions.tier`` — if set and non-``free``
         this wins (they pay their own subscription).
      2. Otherwise, a Team membership inherited from an owner: if the user is
         an accepted member of ``team_memberships`` under an owner whose tier
         is ``'team'`` (or ``'enterprise'``), that tier is inherited.
      3. Else ``'free'``.
    """
    if not user_id:
        return "free"
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT tier FROM user_subscriptions WHERE user_id = $1",
                str(user_id),
            )
    except asyncpg.UndefinedTableError:
        # Table does not yet exist — migration will apply on next startup.
        return "free"
    except Exception as exc:
        log.warning("get_user_tier failed for %s: %s — defaulting to free", user_id, exc)
        return "free"

    own_tier: Tier = "free"
    if row:
        candidate = row["tier"] or "free"
        if candidate in ("free", "individual", "team", "enterprise"):
            own_tier = candidate  # type: ignore[assignment]

    if own_tier != "free":
        return own_tier

    # Check for an inherited team/enterprise tier via team_memberships.
    try:
        from app.billing.team_seats import resolve_team_owner_tier
        inherited = await resolve_team_owner_tier(pool, str(user_id))
    except Exception as exc:
        log.info("team tier resolution skipped for %s: %s", user_id, exc)
        inherited = None

    if inherited in ("team", "enterprise"):
        return inherited  # type: ignore[return-value]

    return own_tier


async def seed_user_tier_defaults(pool: asyncpg.Pool) -> None:
    """Ensure every row in ``users`` has a ``user_subscriptions`` entry.

    Idempotent: inserts ``free`` for users without a row, leaves existing
    rows untouched. Runs on startup so every authenticated request can rely
    on a tier being resolvable in one round-trip.
    """
    await ensure_schema(pool)
    try:
        async with pool.acquire() as conn:
            users_present = await conn.fetchval(
                "SELECT to_regclass('public.users') IS NOT NULL"
            )
            if not users_present:
                log.info("users table absent — skipping user_subscriptions default seed")
                return
            inserted = await conn.fetchval(
                """
                WITH new_rows AS (
                    INSERT INTO user_subscriptions (user_id, tier)
                    SELECT u.user_id::text, 'free'
                      FROM users u
                     WHERE NOT EXISTS (
                               SELECT 1 FROM user_subscriptions s
                                WHERE s.user_id = u.user_id::text
                           )
                    ON CONFLICT (user_id) DO NOTHING
                    RETURNING 1
                )
                SELECT count(*) FROM new_rows
                """
            ) or 0
            if inserted:
                log.info("Seeded %d free-tier user_subscriptions rows", inserted)
    except Exception:
        log.exception("seed_user_tier_defaults failed")


__all__ = [
    "Tier",
    "ensure_schema",
    "get_user_tier",
    "seed_user_tier_defaults",
]
