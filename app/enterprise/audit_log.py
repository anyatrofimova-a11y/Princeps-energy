"""
app/enterprise/audit_log.py — structured audit log + ASGI middleware (Task #13).

Every HTTP request the backend handles can be journalled into the
``audit_log_v2`` table. The write is fire-and-forget so it never adds
latency to the response: ``dispatch`` schedules the DB insert via
``asyncio.create_task`` after the response has already been returned.

PII hygiene
-----------
The raw request body is NEVER persisted. We hash it with SHA-256 and store
only the hex digest under ``payload_hash``. Auth headers / cookies are never
read by this module.

Gating
------
The middleware only engages when ``PRINCEPS_AUDIT_ENABLED=true``. Default
is off so existing dev / test flows are unaffected by Task #13.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import pathlib
import time
from typing import Any
from uuid import UUID

import asyncpg
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

log = logging.getLogger("princeps.enterprise.audit_log")

_MIGRATION_PATH = (
    pathlib.Path(__file__).resolve().parents[1] / "migrations" / "0006_audit_log.sql"
)

# Skip audit for these paths — health checks etc. would otherwise flood the
# table with noise and drown real traffic for investigators.
_SKIP_PATH_PREFIXES: tuple[str, ...] = (
    "/health",
    "/api/readiness",
    "/assets/",
    "/static/",
    "/favicon.ico",
)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Apply migration 0006 if the ``audit_log_v2`` table is missing."""
    async with pool.acquire() as conn:
        present = await conn.fetchval(
            "SELECT to_regclass('public.audit_log_v2') IS NOT NULL"
        )
        if present:
            return
        if not _MIGRATION_PATH.exists():
            log.warning("0006_audit_log.sql missing at %s", _MIGRATION_PATH)
            return
        try:
            await conn.execute(_MIGRATION_PATH.read_text())
            log.info("Applied 0006_audit_log.sql")
        except Exception:
            log.exception("0006_audit_log.sql failed — audit logging disabled")


# ---------------------------------------------------------------------------
# Core writer
# ---------------------------------------------------------------------------

async def write_entry(
    pool: asyncpg.Pool,
    *,
    tenant_id: str | UUID | None = None,
    user_id: str | UUID | None = None,
    session_id: str | UUID | None = None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | UUID | None = None,
    http_method: str | None = None,
    http_path: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    payload_hash: str | None = None,
    response_status: int | None = None,
    error_message: str | None = None,
) -> None:
    """Insert a single audit entry. Safe to call from async workers."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log_v2
                    (tenant_id, user_id, session_id, action,
                     resource_type, resource_id, http_method, http_path,
                     ip_address, user_agent, payload_hash, response_status,
                     error_message)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                """,
                _nullable_uuid(tenant_id),
                _nullable_uuid(user_id),
                _nullable_uuid(session_id),
                action,
                resource_type,
                _nullable_uuid(resource_id),
                http_method,
                http_path,
                ip_address,
                user_agent,
                payload_hash,
                response_status,
                error_message,
            )
    except asyncpg.UndefinedTableError:
        log.debug("audit_log_v2 missing — skipping entry (action=%s)", action)
    except Exception as exc:
        # Never propagate: audit logging must never break a user request.
        log.warning("audit_log write failed (action=%s): %s", action, exc)


async def query(
    pool: asyncpg.Pool,
    *,
    tenant_id: str | UUID,
    user_id: str | UUID | None = None,
    action: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    limit: int = 100,
    cursor_id: str | UUID | None = None,
) -> list[dict[str, Any]]:
    """Cursor-paginated audit-log read. Newest-first."""
    clauses = ["tenant_id = $1"]
    params: list[Any] = [_nullable_uuid(tenant_id)]

    if user_id:
        params.append(_nullable_uuid(user_id))
        clauses.append(f"user_id = ${len(params)}")
    if action:
        params.append(action)
        clauses.append(f"action = ${len(params)}")
    if from_ts:
        params.append(from_ts)
        clauses.append(f"occurred_at >= ${len(params)}")
    if to_ts:
        params.append(to_ts)
        clauses.append(f"occurred_at <= ${len(params)}")
    if cursor_id:
        params.append(_nullable_uuid(cursor_id))
        clauses.append(f"id < ${len(params)}")

    params.append(int(limit))
    q = (
        "SELECT id, tenant_id, user_id, session_id, action, "
        "resource_type, resource_id, http_method, http_path, "
        "host(ip_address) AS ip_address, user_agent, payload_hash, "
        "response_status, error_message, occurred_at "
        "FROM audit_log_v2 WHERE " + " AND ".join(clauses) +
        f" ORDER BY occurred_at DESC, id DESC LIMIT ${len(params)}"
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(q, *params)
    return [_serialise_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class AuditLogMiddleware(BaseHTTPMiddleware):
    """Captures every HTTP request and writes an async audit entry.

    Fire-and-forget: the DB insert is launched AFTER the response has been
    returned to the client, so request latency is unaffected.
    """

    def __init__(self, app: ASGIApp, *, skip_prefixes: tuple[str, ...] | None = None):
        super().__init__(app)
        self.skip_prefixes = skip_prefixes or _SKIP_PATH_PREFIXES

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in self.skip_prefixes):
            return await call_next(request)

        # Read the body for hashing *before* call_next consumes it. Starlette
        # caches the body inside the Request so downstream parsers still see
        # it after we call .body() here. Skip body hashing for upload-shaped
        # requests (multipart, octet-stream) where the hash would add latency
        # without improving investigation signal.
        body_hash = None
        content_type = request.headers.get("content-type", "") or ""
        is_upload = (
            content_type.startswith("multipart/")
            or content_type.startswith("application/octet-stream")
        )
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and not is_upload:
            try:
                body = await request.body()
                if body:
                    body_hash = hashlib.sha256(body).hexdigest()
            except Exception:
                body_hash = None

        t0 = time.monotonic()
        error: str | None = None
        status: int | None = None
        try:
            response: Response = await call_next(request)
            status = response.status_code
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            elapsed_ms = (time.monotonic() - t0) * 1000
            # Launch the DB write without awaiting it — the response is
            # already on its way back to the client.
            try:
                pool = getattr(request.app.state, "pool", None)
                if pool is not None:
                    asyncio.create_task(self._record(
                        pool=pool,
                        request=request,
                        status=status,
                        error=error,
                        body_hash=body_hash,
                        elapsed_ms=elapsed_ms,
                    ))
            except Exception:
                # Never break the request over an audit-log hiccup.
                log.debug("audit middleware: failed to schedule write", exc_info=True)

        return response

    async def _record(
        self,
        *,
        pool: asyncpg.Pool,
        request: Request,
        status: int | None,
        error: str | None,
        body_hash: str | None,
        elapsed_ms: float,
    ) -> None:
        # Extract user/tenant if available. The auth system stores the user on
        # request.state when authenticated; we don't rely on it — so if the
        # value is missing we simply write a nulled audit row.
        user = getattr(request.state, "user", None)
        user_id = user.get("user_id") if isinstance(user, dict) else None
        tenant_id = request.headers.get("X-Princeps-Tenant-Id")

        # Basic action labelling: "<METHOD> <route-path>" — cheap, reliable,
        # works for every route without per-route instrumentation.
        route_path = _route_path(request)
        action = f"{request.method} {route_path}"

        await write_entry(
            pool,
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            http_method=request.method,
            http_path=route_path,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            payload_hash=body_hash,
            response_status=status,
            error_message=error,
        )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _route_path(request: Request) -> str:
    # Prefer the route pattern (e.g. "/api/projects/{id}") over the raw URL
    # path so audit rows aggregate cleanly in the admin UI.
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path  # type: ignore[return-value]
    return request.url.path


def _client_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    client = request.client
    return client.host if client else None


def _nullable_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except Exception:
        return None


def _serialise_row(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id":              str(row["id"]),
        "tenant_id":       str(row["tenant_id"]) if row["tenant_id"] else None,
        "user_id":         str(row["user_id"]) if row["user_id"] else None,
        "session_id":      str(row["session_id"]) if row["session_id"] else None,
        "action":          row["action"],
        "resource_type":   row["resource_type"],
        "resource_id":     str(row["resource_id"]) if row["resource_id"] else None,
        "http_method":     row["http_method"],
        "http_path":       row["http_path"],
        "ip_address":      row["ip_address"],
        "user_agent":      row["user_agent"],
        "payload_hash":    row["payload_hash"],
        "response_status": row["response_status"],
        "error_message":   row["error_message"],
        "occurred_at":     row["occurred_at"].isoformat() if row["occurred_at"] else None,
    }


def is_enabled() -> bool:
    return os.getenv("PRINCEPS_AUDIT_ENABLED", "false").lower() == "true"


__all__ = [
    "AuditLogMiddleware",
    "ensure_schema",
    "write_entry",
    "query",
    "is_enabled",
]
