"""Tenant + JWT enforcement middleware (foundation layer).

Responsibilities
----------------
1. Extract a ``Bearer <token>`` JWT from the Authorization header (or the
   demo allowlist) and decode it via ``app.auth.decode_jwt``.
2. Stash the user_id + tenant_id on ``request.state`` so downstream
   handlers and the asyncpg pool helper can scope queries.
3. Rough out the ``princeps.tenant_id`` GUC pattern: when a handler asks
   the pool for a *tenant-scoped* connection (see ``acquire_tenant_conn``),
   the middleware-set GUC is applied. We don't do this on every request
   because most queries would hit the GUC-unset permissive RLS policy
   anyway.
4. Reject unauthenticated requests **except** when one of:
     * The path is on the allowlist (health, auth, static, public assets).
     * Demo mode is enabled (``PRINCEPS_DEMO_MODE=true``, default true).
   This keeps the existing demo working while we ramp up auth.

The asyncpg pool's ``SET LOCAL`` discipline is documented in
``acquire_tenant_conn`` below — handlers that need RLS isolation should
go through it instead of ``pool.acquire()`` directly.
"""

from __future__ import annotations

import logging
import os
from typing import Final

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.auth import decode_jwt
from app.security.safe_log import safe_log

log = logging.getLogger("princeps.middleware.tenant_jwt")

# Default tenant uuid — shipped by ``2026_05_01_tenant_rls.sql`` and used
# whenever a request has no JWT but is allowed through (health, auth,
# demo). Stays in sync with the migration's INSERT.
DEFAULT_TENANT_ID: Final = "00000000-0000-0000-0000-000000000001"

# Path prefixes that bypass JWT entirely. Health checks, auth flows, and
# static assets must remain reachable without a token. The list is
# deliberately conservative — we accept a slightly wider blast radius
# rather than break the existing demo. Tighten in week 2 once every
# router reads request.state.user_id.
_DEFAULT_ALLOWLIST: tuple[str, ...] = (
    "/health",
    "/api/readiness",
    "/api/auth/",                      # in-memory demo auth router
    "/api/v1/auth/",                   # DB-backed auth router
    "/api/asset-intel/healthz",
    "/static/",
    "/assets/",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/favicon.ico",
)

# Demo mode mirrors app/deps.py:DEMO_MODE — when set, we do not enforce JWT
# but still try to decode it if provided (so smoke tests work as expected).
# Default: ON in development, OFF in production (PRINCEPS_ENV=production).
# An explicit PRINCEPS_DEMO_MODE always wins over the env-derived default.
def _resolve_demo_mode() -> bool:
    raw = os.getenv("PRINCEPS_DEMO_MODE")
    if raw is not None:
        return raw.lower() == "true"
    return os.getenv("PRINCEPS_ENV", "development").lower() != "production"


DEMO_MODE = _resolve_demo_mode()


def _is_allowlisted(path: str, extra: tuple[str, ...] = ()) -> bool:
    full = (*_DEFAULT_ALLOWLIST, *extra)
    return any(path == p.rstrip("/") or path.startswith(p) for p in full)


class TenantJWTMiddleware(BaseHTTPMiddleware):
    """Decode the JWT, stash tenant_id on request.state, gate unauth'd traffic."""

    def __init__(self, app: ASGIApp, *, allowlist: tuple[str, ...] = ()):
        super().__init__(app)
        self._extra_allowlist = tuple(allowlist or ())

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Default state — populated below if a valid token is present.
        request.state.user_id = None
        request.state.tenant_id = DEFAULT_TENANT_ID
        request.state.auth_source = None

        token = self._extract_bearer(request)

        if token:
            try:
                payload = decode_jwt(token)
                request.state.user_id = payload.get("sub")
                request.state.tenant_id = (
                    payload.get("tenant_id") or DEFAULT_TENANT_ID
                )
                request.state.auth_source = "jwt"
                safe_log(
                    "auth.jwt_decoded",
                    user_id=request.state.user_id,
                    tenant_id=request.state.tenant_id,
                    path=path,
                )
            except Exception as exc:
                # Invalid token — only enforce on non-allowlisted paths.
                if not (DEMO_MODE or _is_allowlisted(path, self._extra_allowlist)):
                    safe_log(
                        "auth.jwt_invalid",
                        path=path,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    return JSONResponse(
                        status_code=401,
                        content={
                            "error": "unauthorized",
                            "message": "Invalid or expired token.",
                        },
                    )
                # Otherwise drop to the allowlist branch below.
                log.debug("token decode failed on allowlisted path %s: %s", path, exc)

        # Reject anonymous calls outside the allowlist + outside demo mode.
        if (
            request.state.user_id is None
            and not DEMO_MODE
            and not _is_allowlisted(path, self._extra_allowlist)
        ):
            safe_log("auth.unauthenticated_blocked", path=path)
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "message": (
                        "Missing Authorization: Bearer <token>. "
                        "Set PRINCEPS_DEMO_MODE=true for local dev."
                    ),
                },
            )

        return await call_next(request)

    @staticmethod
    def _extract_bearer(request: Request) -> str | None:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip() or None
        return None


# ---------------------------------------------------------------------------
# Tenant-scoped connection helper
# ---------------------------------------------------------------------------
#
# Handlers that NEED RLS isolation (e.g. cross-tenant audit reports) acquire
# a connection via this helper instead of ``pool.acquire()``. It runs
# ``SET LOCAL princeps.tenant_id = '<uuid>'`` inside a transaction so the
# RLS policy in ``2026_05_01_tenant_rls.sql`` matches rows.
#
# Most handlers don't need this on day 1 — the migration's policy is
# permissive when the GUC is unset, so plain pool.acquire() still works.
# Tighten in week 2 by removing the "GUC IS NULL" branch from the policy
# and routing every query through this helper.

from contextlib import asynccontextmanager  # noqa: E402  (kept near use site)


@asynccontextmanager
async def acquire_tenant_conn(pool, tenant_id: str | None):
    """Yield an asyncpg connection with ``princeps.tenant_id`` set.

    Wraps the connection in a transaction so ``SET LOCAL`` actually scopes
    to the right work — outside a transaction, ``SET LOCAL`` is a no-op.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            if tenant_id:
                await conn.execute(
                    "SELECT set_config('princeps.tenant_id', $1, true)",
                    str(tenant_id),
                )
            yield conn


# ---------------------------------------------------------------------------
# Drop-in tenant-scoped pool wrapper
# ---------------------------------------------------------------------------
# Purpose: routers that took ``pool: asyncpg.Pool = Depends(get_pool)`` can
# swap to ``Depends(get_tenant_pool)`` with no other code changes — every
# ``async with pool.acquire() as conn`` now runs inside the tenant GUC.
#
# Why a wrapper over passing acquire_tenant_conn directly: routers commonly
# do ``async with pool.acquire() as conn: ... conn.fetchrow ...`` in many
# places per file. A wrapper preserves that exact ergonomics.

class TenantPool:
    """Pool-shaped wrapper that scopes every acquired connection to a tenant."""

    __slots__ = ("_pool", "_tenant_id")

    def __init__(self, pool, tenant_id: str | None):
        self._pool = pool
        self._tenant_id = tenant_id

    @property
    def tenant_id(self) -> str | None:
        return self._tenant_id

    def acquire(self):
        # Returns the async context manager — same call shape as pool.acquire().
        return acquire_tenant_conn(self._pool, self._tenant_id)

    # Forward common one-shot helpers — they each open a transient connection,
    # so route them through the GUC-scoped path too.
    async def fetch(self, query, *args, **kwargs):
        async with self.acquire() as conn:
            return await conn.fetch(query, *args, **kwargs)

    async def fetchrow(self, query, *args, **kwargs):
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args, **kwargs)

    async def fetchval(self, query, *args, **kwargs):
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args, **kwargs)

    async def execute(self, query, *args, **kwargs):
        async with self.acquire() as conn:
            return await conn.execute(query, *args, **kwargs)


async def get_tenant_pool(request: Request) -> TenantPool:
    """FastAPI dependency: drop-in replacement for ``get_pool`` that scopes
    every query to ``request.state.tenant_id`` (set by the middleware).

    The ``: Request`` type annotation is **load-bearing** — without it
    FastAPI treats ``request`` as a query-parameter and 422s every call
    with ``{"loc":["query","request"],"msg":"Field required"}``.
    """
    raw_pool = request.app.state.pool
    tenant_id = getattr(request.state, "tenant_id", DEFAULT_TENANT_ID)
    return TenantPool(raw_pool, tenant_id)


def extract_tenant_from_token(token_payload: dict | None) -> str:
    """Pull the tenant UUID from a decoded JWT payload.

    Recognises (in order):
      1. ``princeps_tenant``    — preferred, set by SSO callback
      2. ``org_id``             — common in IdP claim mappings (Auth0, Okta)
      3. ``tenant_id``          — legacy field used by in-memory login
    Falls back to ``DEFAULT_TENANT_ID`` so callers don't need to None-check.
    """
    if not token_payload:
        return DEFAULT_TENANT_ID
    for key in ("princeps_tenant", "org_id", "tenant_id"):
        value = token_payload.get(key)
        if value:
            return str(value)
    return DEFAULT_TENANT_ID


__all__ = [
    "DEFAULT_TENANT_ID",
    "TenantJWTMiddleware",
    "TenantPool",
    "acquire_tenant_conn",
    "extract_tenant_from_token",
    "get_tenant_pool",
]
