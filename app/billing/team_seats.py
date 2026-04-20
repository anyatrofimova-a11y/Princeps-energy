"""
app/billing/team_seats.py — team-tier seat management helpers.

Backs ``/api/billing/team/*`` endpoints. Tables (see
``app/migrations/0004_billing_team_seats.sql``):

* ``team_memberships`` — accepted members under an owner's subscription.
* ``team_invites``     — pending invites emailed to prospective members.

Tier resolution
---------------
The Team tier is inherited: a user is on the ``team`` tier if **any** of:
  1. Their own ``user_subscriptions.tier = 'team'`` (they're the owner).
  2. They're a member of a team whose *owner* has ``tier = 'team'`` and the
     membership row has ``accepted_at IS NOT NULL``.

``app/alerts/user_tiers.py::get_user_tier`` is extended to resolve (2).
"""

from __future__ import annotations

import logging
import pathlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

log = logging.getLogger("princeps.billing.team_seats")

INVITE_TOKEN_BYTES = 24
INVITE_TTL_DAYS = 14

_MIGRATION_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "0004_billing_team_seats.sql"
)


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Apply migration 0004 if either team_* table is missing."""
    async with pool.acquire() as conn:
        present = await conn.fetchval(
            "SELECT to_regclass('public.team_memberships') IS NOT NULL "
            "   AND to_regclass('public.team_invites') IS NOT NULL"
        )
        if present:
            return
        if not _MIGRATION_PATH.exists():
            log.warning("team-seats migration file missing at %s", _MIGRATION_PATH)
            return
        try:
            await conn.execute(_MIGRATION_PATH.read_text())
            log.info("Applied 0004_billing_team_seats.sql")
        except Exception:
            log.exception("0004_billing_team_seats.sql failed")


# ---------------------------------------------------------------------------
# Tier resolution helpers
# ---------------------------------------------------------------------------

async def resolve_team_owner_tier(pool: asyncpg.Pool, user_id: str) -> str | None:
    """If *user_id* is an accepted member of a team, return the owner's tier.

    Returns the owner's tier (usually ``'team'``) or ``None`` if the user isn't
    a member of any accepted team. Used by
    ``app/alerts/user_tiers.get_user_tier`` to bubble up inherited tiers.

    Safe: swallows asyncpg.UndefinedTableError so the call works before the
    migration has run (new deploy) — returns ``None``.
    """
    if not user_id:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT s.tier
                  FROM team_memberships tm
                  JOIN user_subscriptions s
                    ON s.user_id = tm.owner_user_id::text
                 WHERE tm.member_user_id::text = $1
                   AND tm.accepted_at IS NOT NULL
                 LIMIT 1
                """,
                str(user_id),
            )
    except asyncpg.UndefinedTableError:
        return None
    except Exception as exc:
        log.warning("resolve_team_owner_tier failed for %s: %s", user_id, exc)
        return None
    if not row:
        return None
    return row["tier"]


# ---------------------------------------------------------------------------
# Membership listing
# ---------------------------------------------------------------------------

async def list_members(pool: asyncpg.Pool, owner_user_id: str) -> list[dict[str, Any]]:
    """List members on *owner_user_id*'s team (including the owner)."""
    async with pool.acquire() as conn:
        # Owner row (not explicitly in team_memberships — they own the subscription).
        owner_rows = await conn.fetch(
            """
            SELECT u.user_id::text AS user_id, u.email, u.name,
                   'owner'::text AS role, NOW() AS joined_at
              FROM users u
             WHERE u.user_id::text = $1
            """,
            str(owner_user_id),
        )

        member_rows = await conn.fetch(
            """
            SELECT u.user_id::text AS user_id, u.email, u.name,
                   tm.role AS role, tm.accepted_at AS joined_at
              FROM team_memberships tm
              JOIN users u ON u.user_id = tm.member_user_id
             WHERE tm.owner_user_id::text = $1
               AND tm.accepted_at IS NOT NULL
             ORDER BY tm.accepted_at ASC
            """,
            str(owner_user_id),
        )

    out = []
    for r in list(owner_rows) + list(member_rows):
        out.append({
            "user_id": r["user_id"],
            "email": r.get("email") if isinstance(r, dict) else r["email"],
            "name": r["name"],
            "role": r["role"],
            "joined_at": r["joined_at"].isoformat() if r.get("joined_at") else None,
        })
    return out


async def list_pending_invites(
    pool: asyncpg.Pool, owner_user_id: str
) -> list[dict[str, Any]]:
    """Return un-accepted, non-expired invites sent by *owner_user_id*."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, invited_email, token, expires_at, created_at
              FROM team_invites
             WHERE owner_user_id::text = $1
               AND accepted_at IS NULL
               AND expires_at > NOW()
             ORDER BY created_at DESC
            """,
            str(owner_user_id),
        )
    return [
        {
            "invite_id": str(r["id"]),
            "invited_email": r["invited_email"],
            "token": r["token"],
            "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Invite lifecycle
# ---------------------------------------------------------------------------

def _new_token() -> str:
    return secrets.token_urlsafe(INVITE_TOKEN_BYTES)


async def create_invite(
    pool: asyncpg.Pool,
    owner_user_id: str,
    invited_email: str,
) -> dict[str, Any]:
    """Create (or refresh) a pending invite for *invited_email*.

    If a live, un-accepted invite already exists we return it unchanged — that
    way re-clicking "Invite" in the UI is idempotent.
    """
    invited_email = invited_email.strip().lower()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            """
            SELECT id, token, expires_at, created_at
              FROM team_invites
             WHERE owner_user_id::text = $1
               AND lower(invited_email) = $2
               AND accepted_at IS NULL
               AND expires_at > NOW()
            """,
            str(owner_user_id), invited_email,
        )
        if existing:
            return {
                "invite_id": str(existing["id"]),
                "invited_email": invited_email,
                "token": existing["token"],
                "expires_at": existing["expires_at"].isoformat(),
                "reused": True,
            }

        token = _new_token()
        expires_at = datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)
        row = await conn.fetchrow(
            """
            INSERT INTO team_invites
                (owner_user_id, invited_email, token, expires_at)
            VALUES ($1, $2, $3, $4)
            RETURNING id, token, expires_at, created_at
            """,
            owner_user_id, invited_email, token, expires_at,
        )
    return {
        "invite_id": str(row["id"]),
        "invited_email": invited_email,
        "token": row["token"],
        "expires_at": row["expires_at"].isoformat(),
        "reused": False,
    }


async def accept_invite(
    pool: asyncpg.Pool,
    token: str,
    accepting_user_id: str,
) -> dict[str, Any]:
    """Accept a pending invite, adding the user to the team.

    Raises ``ValueError`` with a clear message on each failure mode so the
    router can translate to 4xx.
    """
    async with pool.acquire() as conn:
        invite = await conn.fetchrow(
            """
            SELECT id, owner_user_id, invited_email, expires_at, accepted_at
              FROM team_invites
             WHERE token = $1
            """,
            token,
        )
        if not invite:
            raise ValueError("invite_not_found")
        if invite["accepted_at"] is not None:
            raise ValueError("invite_already_accepted")
        if invite["expires_at"] < datetime.now(timezone.utc):
            raise ValueError("invite_expired")

        owner_user_id = invite["owner_user_id"]

        # Upsert the membership row and mark the invite accepted.
        async with conn.transaction():
            membership = await conn.fetchrow(
                """
                INSERT INTO team_memberships
                    (owner_user_id, member_user_id, role, accepted_at)
                VALUES ($1, $2, 'member', NOW())
                ON CONFLICT (owner_user_id, member_user_id)
                DO UPDATE SET accepted_at = COALESCE(team_memberships.accepted_at, NOW())
                RETURNING id, owner_user_id, member_user_id, role, accepted_at
                """,
                owner_user_id, accepting_user_id,
            )
            await conn.execute(
                "UPDATE team_invites SET accepted_at = NOW() WHERE id = $1",
                invite["id"],
            )

    return {
        "membership_id": str(membership["id"]),
        "owner_user_id": str(membership["owner_user_id"]),
        "member_user_id": str(membership["member_user_id"]),
        "role": membership["role"],
        "accepted_at": membership["accepted_at"].isoformat(),
    }


async def remove_member(
    pool: asyncpg.Pool,
    owner_user_id: str,
    member_user_id: str,
) -> bool:
    """Remove *member_user_id* from *owner_user_id*'s team. Returns True if a
    row was removed.

    Does nothing if the owner tries to remove themselves — that should be
    handled by downgrading the subscription instead.
    """
    if str(owner_user_id) == str(member_user_id):
        return False
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM team_memberships
             WHERE owner_user_id::text = $1 AND member_user_id::text = $2
            """,
            str(owner_user_id), str(member_user_id),
        )
    try:
        n = int(result.split()[-1])
    except Exception:
        n = 0
    return bool(n)


__all__ = [
    "ensure_schema",
    "resolve_team_owner_tier",
    "list_members",
    "list_pending_invites",
    "create_invite",
    "accept_invite",
    "remove_member",
]
