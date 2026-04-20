"""
app/routers/enterprise_admin.py — enterprise-tier admin surface (Task #13).

Mounted at ``/api/enterprise``. All endpoints require authentication AND an
``enterprise`` tier entry in ``user_subscriptions``. The router wires into:

* :mod:`app.enterprise.tenants`     — tenant / membership CRUD
* :mod:`app.enterprise.sso`         — OIDC provider config + login flow
* :mod:`app.enterprise.audit_log`   — paginated audit-log read + CSV export

Endpoints
---------
* ``POST   /tenants``                          — create a tenant
* ``GET    /tenants/{slug}``                   — read tenant metadata
* ``POST   /tenants/{slug}/sso/configure``     — attach an IdP config
* ``POST   /tenants/{slug}/sso/login``         — redirect to IdP
* ``GET    /tenants/{slug}/sso/callback``      — handle IdP callback
* ``GET    /tenants/{slug}/audit-log``         — paginated audit log
* ``GET    /tenants/{slug}/audit-log/export.csv`` — CSV dump
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field
import asyncpg

from app.alerts.user_tiers import get_user_tier
from app.deps import get_current_user, get_pool
from app.enterprise import audit_log as audit_log_mod
from app.enterprise import sso as sso_mod
from app.enterprise import tenants as tenants_mod

log = logging.getLogger("princeps.enterprise.admin")

router = APIRouter(prefix="/api/enterprise", tags=["enterprise"])


# ---------------------------------------------------------------------------
# Gate — enterprise-tier only
# ---------------------------------------------------------------------------

async def require_enterprise_tier(
    user = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Reject non-enterprise callers with 403.

    This is layered *on top* of the normal auth dependency: you must be
    authenticated AND your subscription tier must be ``enterprise``. In
    demo mode the demo user has no subscription row — we fall back to the
    role claim on the user dict so demos don't break.
    """
    tier = await get_user_tier(pool, str(user["user_id"]))
    if tier == "enterprise":
        return user
    # Escape hatch for demo mode: role=admin → enterprise access.
    if user.get("role") == "admin":
        return user
    raise HTTPException(
        status_code=403,
        detail="Enterprise tier required for this endpoint.",
    )


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CreateTenantRequest(BaseModel):
    slug: str = Field(..., min_length=2, max_length=60)
    display_name: str = Field(..., min_length=2, max_length=120)
    plan: Literal["individual", "team", "enterprise"] = "enterprise"
    white_label: dict | None = None
    owner_user_id: str | None = None


class ConfigureSSORequest(BaseModel):
    provider: Literal["google", "azure", "okta", "generic_oidc"]
    issuer_url: str
    client_id: str
    client_secret: str
    metadata_url: str | None = None
    allowed_email_domains: list[str] | None = None
    jit_provisioning: bool = True
    default_role: Literal["owner", "admin", "member", "viewer"] = "member"


# ---------------------------------------------------------------------------
# Tenant CRUD
# ---------------------------------------------------------------------------

@router.post("/tenants")
async def create_tenant(
    body: CreateTenantRequest,
    _user = Depends(require_enterprise_tier),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Create a tenant. Intended target for Stripe enterprise-checkout webhooks."""
    await tenants_mod.ensure_schema(pool)
    try:
        tenant = await tenants_mod.create_tenant(
            pool,
            slug=body.slug,
            display_name=body.display_name,
            plan=body.plan,
            white_label=body.white_label,
            owner_user_id=body.owner_user_id,
        )
    except Exception as exc:
        log.exception("create_tenant failed")
        raise HTTPException(status_code=500, detail=f"create_tenant: {exc}")
    return {"tenant": tenant}


@router.get("/tenants/{slug}")
async def get_tenant(
    slug: str,
    _user = Depends(require_enterprise_tier),
    pool: asyncpg.Pool = Depends(get_pool),
):
    tenant = await tenants_mod.get_tenant_by_slug(pool, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"tenant": tenant}


# ---------------------------------------------------------------------------
# SSO — configure
# ---------------------------------------------------------------------------

@router.post("/tenants/{slug}/sso/configure")
async def configure_sso(
    slug: str,
    body: ConfigureSSORequest,
    _user = Depends(require_enterprise_tier),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Attach or update an IdP config for a tenant.

    The ``client_secret`` is encrypted at rest via ``app.enterprise.encryption``
    before insert. The response never echoes the secret back.
    """
    tenant = await tenants_mod.get_tenant_by_slug(pool, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    try:
        config = await sso_mod.register_tenant_idp(
            pool,
            tenant_id=tenant["id"],
            provider=body.provider,
            issuer_url=body.issuer_url,
            client_id=body.client_id,
            client_secret=body.client_secret,
            metadata_url=body.metadata_url,
            allowed_email_domains=body.allowed_email_domains,
            jit_provisioning=body.jit_provisioning,
            default_role=body.default_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.exception("configure_sso failed")
        raise HTTPException(status_code=500, detail=f"configure_sso: {exc}")
    return {"sso": config}


# ---------------------------------------------------------------------------
# SSO — login flow
# ---------------------------------------------------------------------------

@router.post("/tenants/{slug}/sso/login")
async def sso_login(
    slug: str,
    request: Request,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Redirect the browser to the tenant's IdP authorize URL."""
    if not sso_mod.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="SSO disabled (set PRINCEPS_SSO_ENABLED=true)",
        )
    callback_url = str(request.url_for("sso_callback", slug=slug))
    try:
        start = await sso_mod.initiate_sso(
            pool,
            tenant_slug=slug,
            redirect_uri=callback_url,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        log.exception("sso_login failed")
        raise HTTPException(status_code=500, detail=f"sso_login: {exc}")

    # Set the expected state as a secure cookie so handle_callback can verify.
    response = RedirectResponse(url=start["authorize_url"], status_code=302)
    response.set_cookie(
        key="princeps_sso_state",
        value=start["state"],
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=600,
    )
    return response


@router.get("/tenants/{slug}/sso/callback", name="sso_callback")
async def sso_callback(
    slug: str,
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Handle IdP redirect: exchange code, JIT-provision user, issue Princeps JWT."""
    if not sso_mod.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="SSO disabled (set PRINCEPS_SSO_ENABLED=true)",
        )
    expected_state = request.cookies.get("princeps_sso_state")
    callback_url = str(request.url_for("sso_callback", slug=slug))

    try:
        result = await sso_mod.handle_callback(
            pool,
            tenant_slug=slug,
            code=code,
            state=state,
            expected_state=expected_state,
            redirect_uri=callback_url,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        log.exception("sso_callback failed")
        raise HTTPException(status_code=500, detail=f"sso_callback: {exc}")

    # Mint a standard Princeps JWT so the frontend can continue without a
    # separate session cookie for SSO users.
    from app.auth import encode_jwt
    user = result["user"]
    token = encode_jwt({
        "sub":       str(user["user_id"]),
        "email":     user["email"],
        "role":      user.get("role", "member"),
        "tenant_id": result["tenant"]["id"],
    })

    response = Response(
        content=(
            b'{"ok": true, "user_id": "' + str(user["user_id"]).encode() + b'", "token": "' +
            token.encode() + b'", "tenant_slug": "' + slug.encode() + b'"}'
        ),
        media_type="application/json",
    )
    response.delete_cookie("princeps_sso_state")
    return response


# ---------------------------------------------------------------------------
# Audit log read + CSV export
# ---------------------------------------------------------------------------

@router.get("/tenants/{slug}/audit-log")
async def audit_log_query(
    slug: str,
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str]   = Query(None, alias="to"),
    user_id: Optional[UUID] = Query(None),
    action: Optional[str]   = Query(None),
    cursor: Optional[UUID]  = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    _user = Depends(require_enterprise_tier),
    pool: asyncpg.Pool = Depends(get_pool),
):
    tenant = await tenants_mod.get_tenant_by_slug(pool, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    entries = await audit_log_mod.query(
        pool,
        tenant_id=tenant["id"],
        user_id=user_id,
        action=action,
        from_ts=from_ts,
        to_ts=to_ts,
        limit=limit,
        cursor_id=cursor,
    )
    next_cursor = entries[-1]["id"] if len(entries) == limit else None
    return {
        "entries":     entries,
        "count":       len(entries),
        "next_cursor": next_cursor,
    }


@router.get("/tenants/{slug}/audit-log/export.csv")
async def audit_log_export_csv(
    slug: str,
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str]   = Query(None, alias="to"),
    user_id: Optional[UUID] = Query(None),
    action: Optional[str]   = Query(None),
    _user = Depends(require_enterprise_tier),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Bulk CSV dump for SOC 2 evidence / customer compliance reviews.

    Hard cap at 100k rows per export — anything larger should use a signed
    S3 URL workflow (follow-up task).
    """
    tenant = await tenants_mod.get_tenant_by_slug(pool, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    entries = await audit_log_mod.query(
        pool,
        tenant_id=tenant["id"],
        user_id=user_id,
        action=action,
        from_ts=from_ts,
        to_ts=to_ts,
        limit=100_000,
    )

    columns = [
        "id", "occurred_at", "user_id", "action",
        "resource_type", "resource_id", "http_method", "http_path",
        "ip_address", "user_agent", "payload_hash",
        "response_status", "error_message",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in entries:
        writer.writerow(row)

    filename = f"audit-log-{slug}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]
