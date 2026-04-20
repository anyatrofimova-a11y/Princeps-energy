"""
app/billing/seats_check.py — seat-limit helpers for the Team tier.

``current_seats_used(pool, owner_user_id)``
    Count of accepted members **including the owner**.

``can_add_seat(pool, owner_user_id, tier)``
    True if adding one more seat stays within the tier's ``seat_count``
    allowance. ``enterprise`` → unlimited seats.

Pending invites are *not* counted against the cap: a Team owner can send 20
invites but only 5 can accept (the rest get a friendly "seats_full" error when
they click the link).
"""

from __future__ import annotations

import logging
from typing import Literal

import asyncpg

from app.billing.price_catalog import seat_count_for_tier

log = logging.getLogger("princeps.billing.seats_check")

TierSlug = Literal["free", "individual", "team", "enterprise"]


async def current_seats_used(pool: asyncpg.Pool, owner_user_id: str) -> int:
    """Return the number of occupied seats on *owner_user_id*'s team.

    Seats occupied = 1 (owner) + count of accepted team_memberships rows.
    """
    try:
        async with pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT count(*)
                  FROM team_memberships
                 WHERE owner_user_id::text = $1
                   AND accepted_at IS NOT NULL
                """,
                str(owner_user_id),
            )
    except asyncpg.UndefinedTableError:
        # Migration 0004 hasn't run yet — just the owner.
        return 1
    except Exception as exc:
        log.warning("current_seats_used failed for %s: %s", owner_user_id, exc)
        return 1
    return int(n or 0) + 1  # +1 for the owner


async def can_add_seat(
    pool: asyncpg.Pool, owner_user_id: str, tier: str
) -> bool:
    """Return True if *owner_user_id* on *tier* can add one more seat."""
    cap = seat_count_for_tier(tier)
    if cap is None:
        return True  # unlimited (enterprise)
    if tier in ("free", "individual"):
        # These tiers don't have teams; always disallow adding seats.
        return False
    used = await current_seats_used(pool, owner_user_id)
    return used < cap


async def seats_summary(
    pool: asyncpg.Pool, owner_user_id: str, tier: str
) -> dict:
    """Return ``{used, total, unlimited}`` for API responses."""
    used = await current_seats_used(pool, owner_user_id)
    total = seat_count_for_tier(tier)
    return {
        "used": used,
        "total": total,      # None = unlimited (enterprise)
        "unlimited": total is None,
    }


__all__ = [
    "current_seats_used",
    "can_add_seat",
    "seats_summary",
]
