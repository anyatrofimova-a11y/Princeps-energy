"""
Settings endpoints — Team, Notifications, API Keys.

Wired under ``/api/v1/settings/*`` and auto-registered by the router
loader in ``app.main``. Each sub-section backs one Settings sidebar tab.

Auth behaviour
--------------
Endpoints use ``get_optional_user``: if a valid JWT is present the
caller's own record is used; otherwise we fall back to the seeded
admin user (``role='admin'``). This lets the Settings UI render for
the bootstrap single-user case without forcing login before the
first password is set. Once real sign-in is mandatory for your
deployment, flip the ``Depends(get_optional_user)`` calls here to
``Depends(get_current_user)``.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.auth import hash_password
from app.deps import get_optional_user, get_pool

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _resolve_user(pool: asyncpg.Pool, optional_user: dict | None) -> dict:
    """Return the authenticated user, or fall back to the admin seed."""
    if optional_user:
        return optional_user
    row = await pool.fetchrow(
        """
        SELECT user_id, email, name, org_name, role
          FROM users
         WHERE role = 'admin'
         ORDER BY created_at ASC
         LIMIT 1
        """
    )
    if not row:
        raise HTTPException(
            status_code=401,
            detail="No authenticated user and no admin seed exists",
        )
    return dict(row)


def _key_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── Team ────────────────────────────────────────────────────────────────────


class InviteRequest(BaseModel):
    email: EmailStr
    name: str | None = None
    role: str = "analyst"


@router.get("/team")
async def list_team(
    user: dict | None = Depends(get_optional_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List users who share an org_name with the authenticated user.

    In the single-org bootstrap case this returns every user row.
    """
    me = await _resolve_user(pool, user)
    where = "WHERE org_name = $1"
    args: list[Any] = [me.get("org_name")]
    if not me.get("org_name"):
        where = ""
        args = []
    rows = await pool.fetch(
        f"""
        SELECT user_id, email, name, role, org_name,
               last_login, created_at,
               password_hash IS NOT NULL AS password_set
          FROM users
          {where}
         ORDER BY created_at ASC
        """,
        *args,
    )
    return {
        "me": {
            "user_id": str(me["user_id"]),
            "email": me["email"],
            "role": me.get("role"),
        },
        "members": [
            {
                "user_id": str(r["user_id"]),
                "email": r["email"],
                "name": r["name"],
                "role": r["role"],
                "org_name": r["org_name"],
                "last_login": r["last_login"].isoformat() if r["last_login"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "password_set": bool(r["password_set"]),
            }
            for r in rows
        ],
    }


@router.post("/team/invite")
async def invite_member(
    body: InviteRequest,
    user: dict | None = Depends(get_optional_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Create a placeholder user record. A real flow would email a
    one-time sign-up link; for now we just seed the row with a random
    password they'll be prompted to reset on first login."""
    me = await _resolve_user(pool, user)
    existing = await pool.fetchrow(
        "SELECT user_id FROM users WHERE email = $1", str(body.email)
    )
    if existing:
        raise HTTPException(status_code=409, detail="Email already on the team")
    tmp_password = secrets.token_urlsafe(16)
    row = await pool.fetchrow(
        """
        INSERT INTO users (email, name, role, org_name, password_hash)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING user_id, email, name, role, org_name, created_at
        """,
        str(body.email),
        body.name,
        body.role,
        me.get("org_name"),
        hash_password(tmp_password),
    )
    return {
        "member": {
            "user_id": str(row["user_id"]),
            "email": row["email"],
            "role": row["role"],
        },
        "tmp_password": tmp_password,  # surfaced once so the admin can send it
    }


# ── Notifications ───────────────────────────────────────────────────────────


class NotificationPrefs(BaseModel):
    weekly_report_enabled: bool | None = None
    slack_dm_enabled: bool | None = None
    timezone: str | None = None


@router.get("/notifications")
async def get_notifications(
    limit: int = 25,
    user: dict | None = Depends(get_optional_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    me = await _resolve_user(pool, user)
    prefs_row = await pool.fetchrow(
        """
        SELECT weekly_report_enabled, slack_dm_enabled, timezone, updated_at
          FROM user_preferences
         WHERE user_id = $1
        """,
        me["user_id"],
    )
    notif_rows = await pool.fetch(
        """
        SELECT id, channel, severity, title, body, link_url,
               source_agent, delivered_at, read_at, created_at
          FROM agent_notifications
         WHERE user_id = $1
         ORDER BY created_at DESC
         LIMIT $2
        """,
        me["user_id"],
        int(limit),
    )
    return {
        "prefs": {
            "weekly_report_enabled": bool(prefs_row["weekly_report_enabled"]) if prefs_row else False,
            "slack_dm_enabled": bool(prefs_row["slack_dm_enabled"]) if prefs_row else False,
            "timezone": prefs_row["timezone"] if prefs_row else "Europe/London",
        },
        "unread_count": sum(1 for r in notif_rows if r["read_at"] is None),
        "notifications": [
            {
                "id": r["id"],
                "channel": r["channel"],
                "severity": r["severity"],
                "title": r["title"],
                "body": r["body"],
                "link_url": r["link_url"],
                "source_agent": r["source_agent"],
                "delivered_at": r["delivered_at"].isoformat() if r["delivered_at"] else None,
                "read_at": r["read_at"].isoformat() if r["read_at"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in notif_rows
        ],
    }


@router.put("/notifications/prefs")
async def update_prefs(
    body: NotificationPrefs,
    user: dict | None = Depends(get_optional_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    me = await _resolve_user(pool, user)
    # Upsert. We compose the update dynamically so unset fields aren't
    # clobbered to NULL.
    current = await pool.fetchrow(
        "SELECT * FROM user_preferences WHERE user_id = $1",
        me["user_id"],
    )
    merged = {
        "weekly_report_enabled": body.weekly_report_enabled
            if body.weekly_report_enabled is not None
            else (current["weekly_report_enabled"] if current else False),
        "slack_dm_enabled": body.slack_dm_enabled
            if body.slack_dm_enabled is not None
            else (current["slack_dm_enabled"] if current else False),
        "timezone": body.timezone or (current["timezone"] if current else "Europe/London"),
    }
    await pool.execute(
        """
        INSERT INTO user_preferences (user_id, weekly_report_enabled, slack_dm_enabled, timezone)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id) DO UPDATE SET
            weekly_report_enabled = EXCLUDED.weekly_report_enabled,
            slack_dm_enabled      = EXCLUDED.slack_dm_enabled,
            timezone              = EXCLUDED.timezone,
            updated_at            = now()
        """,
        me["user_id"],
        merged["weekly_report_enabled"],
        merged["slack_dm_enabled"],
        merged["timezone"],
    )
    return {"prefs": merged}


@router.post("/notifications/{notif_id}/read")
async def mark_read(
    notif_id: int,
    user: dict | None = Depends(get_optional_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    me = await _resolve_user(pool, user)
    await pool.execute(
        """
        UPDATE agent_notifications
           SET read_at = now()
         WHERE id = $1 AND user_id = $2 AND read_at IS NULL
        """,
        notif_id, me["user_id"],
    )
    return {"ok": True}


# ── API Keys ────────────────────────────────────────────────────────────────


class CreateKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    scopes: list[str] = Field(default_factory=lambda: ["read"])


@router.get("/api-keys")
async def list_api_keys(
    user: dict | None = Depends(get_optional_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    me = await _resolve_user(pool, user)
    rows = await pool.fetch(
        """
        SELECT id, name, key_prefix, scopes, created_at, last_used_at, revoked_at
          FROM api_keys
         WHERE user_id = $1
         ORDER BY (revoked_at IS NOT NULL), created_at DESC
        """,
        me["user_id"],
    )
    return {
        "keys": [
            {
                "id": r["id"],
                "name": r["name"],
                "prefix": r["key_prefix"],
                "scopes": list(r["scopes"] or []),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
                "revoked_at": r["revoked_at"].isoformat() if r["revoked_at"] else None,
            }
            for r in rows
        ]
    }


@router.post("/api-keys")
async def create_api_key(
    body: CreateKeyRequest,
    user: dict | None = Depends(get_optional_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    me = await _resolve_user(pool, user)
    token = "pcp_" + secrets.token_urlsafe(32)   # plaintext, shown once
    prefix = token[:12]                          # "pcp_" + first 8 random chars
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO api_keys (user_id, name, key_prefix, key_hash, scopes)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, name, key_prefix, scopes, created_at
            """,
            me["user_id"],
            body.name,
            prefix,
            _key_hash(token),
            body.scopes,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="A key with that name already exists")
    return {
        "key": {
            "id": row["id"],
            "name": row["name"],
            "prefix": row["key_prefix"],
            "scopes": list(row["scopes"]),
            "created_at": row["created_at"].isoformat(),
        },
        "token": token,   # plaintext — shown once, never stored
        "warning": "Copy this token now. You won't see it again.",
    }


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: int,
    user: dict | None = Depends(get_optional_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    me = await _resolve_user(pool, user)
    result = await pool.execute(
        """
        UPDATE api_keys
           SET revoked_at = now()
         WHERE id = $1 AND user_id = $2 AND revoked_at IS NULL
        """,
        key_id, me["user_id"],
    )
    if result.endswith(" 0"):
        raise HTTPException(status_code=404, detail="Key not found or already revoked")
    return {"ok": True}
