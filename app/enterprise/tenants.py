"""
app/enterprise/tenants.py — multi-tenant primitives (Task #13).

Owns the ``tenants`` and ``tenant_memberships`` tables (migration
``0005_enterprise_tenancy.sql``) plus the small helper surface the rest of
the enterprise layer calls into.

Design notes
------------
* ``tenant_id`` on resource tables is **nullable** during the backfill grace
  period so existing single-tenant rows keep working. Application code must
  treat NULL as "legacy" and fall back to user-scoped visibility.
* Roles form a total order: ``owner > admin > member > viewer``. The ACL
  layer converts ``min_role='member'`` into "role rank >= member-rank".
* Slugs are lowercase, hyphenated, unique. Stripe webhooks on enterprise
  checkout call :func:`create_tenant` with a slug derived from the customer
  organisation name.
"""

from __future__ import annotations

import logging
import pathlib
import re
from typing import Any, Literal
from uuid import UUID

import asyncpg

log = logging.getLogger("princeps.enterprise.tenants")

Plan = Literal["individual", "team", "enterprise"]
Role = Literal["owner", "admin", "member", "viewer"]

_MIGRATION_PATH = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "0005_enterprise_tenancy.sql"

# Role rank — higher = more privileged. Used by the ACL dependency.
_ROLE_RANK: dict[Role, int] = {
    "viewer": 10,
    "member": 20,
    "admin":  30,
    "owner":  40,
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Apply migration 0005 if the ``tenants`` table is missing."""
    async with pool.acquire() as conn:
        present = await conn.fetchval(
            "SELECT to_regclass('public.tenants') IS NOT NULL"
        )
        if present:
            return
        if not _MIGRATION_PATH.exists():
            log.warning("0005_enterprise_tenancy.sql missing at %s", _MIGRATION_PATH)
            return
        try:
            await conn.execute(_MIGRATION_PATH.read_text())
            log.info("Applied 0005_enterprise_tenancy.sql")
        except Exception:
            log.exception("0005_enterprise_tenancy.sql failed — tenancy features disabled")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def slugify(value: str) -> str:
    """Normalise an org name into a URL-safe tenant slug."""
    s = (value or "").lower().strip().replace(" ", "-")
    s = _SLUG_RE.sub("", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "tenant"


def role_rank(role: str | None) -> int:
    if not role:
        return 0
    return _ROLE_RANK.get(role, 0)  # type: ignore[arg-type]


def role_at_least(actual: str | None, minimum: Role) -> bool:
    return role_rank(actual) >= role_rank(minimum)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def create_tenant(
    pool: asyncpg.Pool,
    *,
    slug: str,
    display_name: str,
    plan: Plan = "individual",
    white_label: dict | None = None,
    owner_user_id: str | UUID | None = None,
) -> dict[str, Any]:
    """Create a tenant row (idempotent on slug). Optionally add an owner membership."""
    import json
    clean_slug = slugify(slug)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO tenants (slug, display_name, plan, white_label)
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT (slug) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                plan         = EXCLUDED.plan,
                updated_at   = now()
            RETURNING id, slug, display_name, plan, white_label, trust_badges,
                      created_at, updated_at
            """,
            clean_slug, display_name, plan,
            json.dumps(white_label) if white_label else None,
        )
        tenant = dict(row)

        if owner_user_id:
            await conn.execute(
                """
                INSERT INTO tenant_memberships (tenant_id, user_id, role)
                VALUES ($1, $2, 'owner')
                ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = 'owner'
                """,
                tenant["id"], _coerce_uuid(owner_user_id),
            )

    return _serialise_tenant(tenant)


async def get_tenant_by_slug(pool: asyncpg.Pool, slug: str) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM tenants WHERE slug = $1", slugify(slug),
        )
    return _serialise_tenant(dict(row)) if row else None


async def get_tenant_by_id(pool: asyncpg.Pool, tenant_id: str | UUID) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM tenants WHERE id = $1", _coerce_uuid(tenant_id),
        )
    return _serialise_tenant(dict(row)) if row else None


async def add_member(
    pool: asyncpg.Pool,
    *,
    tenant_id: str | UUID,
    user_id: str | UUID,
    role: Role = "member",
) -> dict[str, Any]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO tenant_memberships (tenant_id, user_id, role)
            VALUES ($1, $2, $3)
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = EXCLUDED.role
            RETURNING id, tenant_id, user_id, role, joined_at
            """,
            _coerce_uuid(tenant_id), _coerce_uuid(user_id), role,
        )
    return dict(row)


async def get_user_role(
    pool: asyncpg.Pool,
    *,
    tenant_id: str | UUID,
    user_id: str | UUID,
) -> str | None:
    """Return the user's role in the tenant, or None if no membership."""
    async with pool.acquire() as conn:
        try:
            role = await conn.fetchval(
                """
                SELECT role FROM tenant_memberships
                 WHERE tenant_id = $1 AND user_id = $2
                """,
                _coerce_uuid(tenant_id), _coerce_uuid(user_id),
            )
        except asyncpg.UndefinedTableError:
            return None
        except Exception as exc:
            log.warning("get_user_role failed for %s/%s: %s", tenant_id, user_id, exc)
            return None
    return role


async def list_user_tenants(
    pool: asyncpg.Pool, user_id: str | UUID,
) -> list[dict[str, Any]]:
    """Return all tenants the user belongs to, newest-first."""
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT t.id, t.slug, t.display_name, t.plan, t.white_label,
                       t.trust_badges, t.created_at, t.updated_at, m.role
                  FROM tenants t
                  JOIN tenant_memberships m ON m.tenant_id = t.id
                 WHERE m.user_id = $1
                 ORDER BY t.created_at DESC
                """,
                _coerce_uuid(user_id),
            )
        except asyncpg.UndefinedTableError:
            return []
    return [_serialise_tenant(dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Resource → tenant resolution
# ---------------------------------------------------------------------------

# Map the ``resource_type`` string used by callers onto the table + column
# that holds the ``tenant_id``. Restricting to an explicit whitelist here
# means ACL callers can't accidentally (or maliciously) pass a user-supplied
# table name through to a SQL query.
_RESOURCE_TENANT_QUERY: dict[str, tuple[str, str, str]] = {
    # resource_type  → (table, pk_column, tenant_column)
    "project":              ("projects",              "project_id",      "tenant_id"),
    "alert_subscription":   ("alert_subscriptions",   "id",              "tenant_id"),
    "document_pin":         ("document_project_pins", "id",              "tenant_id"),
    "docket_pin":           ("project_docket_pins",   "id",              "tenant_id"),
    "tenant":               ("tenants",               "id",              "id"),
}


async def tenant_for_resource(
    pool: asyncpg.Pool,
    *,
    resource_type: str,
    resource_id: str | UUID,
) -> str | None:
    """Look up the ``tenant_id`` that owns a resource. Returns ``None`` for
    unknown resource types or rows missing a tenant (legacy single-tenant).
    """
    entry = _RESOURCE_TENANT_QUERY.get(resource_type)
    if not entry:
        return None
    table, pk, tenant_col = entry
    # Parameterise table / column names via static whitelist lookup above.
    # Never interpolate caller input into SQL.
    q = f"SELECT {tenant_col} FROM {table} WHERE {pk} = $1"
    async with pool.acquire() as conn:
        try:
            val = await conn.fetchval(q, _coerce_uuid(resource_id))
        except asyncpg.UndefinedTableError:
            return None
        except Exception as exc:
            log.warning("tenant_for_resource %s/%s failed: %s", resource_type, resource_id, exc)
            return None
    return str(val) if val else None


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _coerce_uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _serialise_tenant(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id":            str(row["id"]) if row.get("id") else None,
        "slug":          row.get("slug"),
        "display_name":  row.get("display_name"),
        "plan":          row.get("plan"),
        "white_label":   row.get("white_label"),
        "trust_badges":  row.get("trust_badges"),
        "created_at":    row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at":    row["updated_at"].isoformat() if row.get("updated_at") else None,
    }
    if "role" in row:
        out["role"] = row["role"]
    return out


__all__ = [
    "Plan",
    "Role",
    "ensure_schema",
    "slugify",
    "role_rank",
    "role_at_least",
    "create_tenant",
    "get_tenant_by_slug",
    "get_tenant_by_id",
    "add_member",
    "get_user_role",
    "list_user_tenants",
    "tenant_for_resource",
]
