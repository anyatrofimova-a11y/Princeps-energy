"""OIDC-based federated identity (SSO) router.

Generic OpenID Connect Authorization Code Flow — works with any
spec-compliant IdP (Auth0, Keycloak, Google, Microsoft Entra, Okta).

Mounted by ``app/main.py`` (registered in ``_ROUTER_MODULES`` as ``sso``).
All endpoints live under ``/api/auth/sso/*`` and short-circuit cleanly
when no OIDC env config is present (``GET /config`` returns
``{enabled: false}``), so existing in-memory ``/api/auth/login`` keeps
working untouched.

Env vars (read at startup):
  PRINCEPS_OIDC_ISSUER          (e.g. https://accounts.google.com)
  PRINCEPS_OIDC_CLIENT_ID
  PRINCEPS_OIDC_CLIENT_SECRET
  PRINCEPS_OIDC_REDIRECT_URI    (e.g. http://localhost:8000/api/auth/sso/callback)
  PRINCEPS_OIDC_SCOPES          (default: 'openid email profile')
  PRINCEPS_JWT_SECRET / JWT_SECRET — used by app.auth.encode_jwt
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import uuid
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, status
from starlette.responses import JSONResponse, RedirectResponse

from app.auth import encode_jwt
from app.auth_oidc import OidcClient, OidcError

log = logging.getLogger("princeps.sso")

router = APIRouter(prefix="/api/auth/sso", tags=["sso"])

# ---------------------------------------------------------------------------
# Config (env-driven; absent env => feature disabled, never raises at import)
# ---------------------------------------------------------------------------
_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_STATE_COOKIE = "princeps_sso_state"
_NONCE_COOKIE = "princeps_sso_nonce"
_RETURN_COOKIE = "princeps_sso_return"
_TOKEN_COOKIE = "princeps_token"
# Deterministic per-domain UUID namespace — used to project an email's
# domain into a tenant_id when the IdP doesn't supply one.
_TENANT_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _config() -> dict[str, str | None]:
    return {
        "issuer": os.environ.get("PRINCEPS_OIDC_ISSUER"),
        "client_id": os.environ.get("PRINCEPS_OIDC_CLIENT_ID"),
        "client_secret": os.environ.get("PRINCEPS_OIDC_CLIENT_SECRET"),
        "redirect_uri": os.environ.get("PRINCEPS_OIDC_REDIRECT_URI"),
        "scopes": os.environ.get("PRINCEPS_OIDC_SCOPES", "openid email profile"),
    }


def _enabled(cfg: dict[str, str | None] | None = None) -> bool:
    cfg = cfg or _config()
    return all(cfg.get(k) for k in ("issuer", "client_id", "client_secret", "redirect_uri"))


def _build_client() -> OidcClient:
    cfg = _config()
    if not _enabled(cfg):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSO not configured (set PRINCEPS_OIDC_* env vars).",
        )
    return OidcClient(
        issuer=cfg["issuer"],
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        redirect_uri=cfg["redirect_uri"],
        scopes=cfg["scopes"] or "openid email profile",
    )


# ---------------------------------------------------------------------------
# Tenant resolution
# ---------------------------------------------------------------------------
def _resolve_tenant(claims: dict[str, Any]) -> str:
    """Map ID-token / userinfo claims to a Princeps tenant UUID."""
    raw = claims.get("princeps_tenant") or claims.get("org_id")
    if raw:
        try:
            return str(uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            log.warning("sso.tenant_claim_invalid value=%s", raw)
    email = (claims.get("email") or "").strip().lower()
    if "@" in email:
        domain = email.split("@", 1)[1]
        return str(uuid.uuid5(_TENANT_NAMESPACE, domain))
    return _DEFAULT_TENANT_ID


# ---------------------------------------------------------------------------
# DB upsert (best-effort — degrades to no-op when the pool isn't ready)
# ---------------------------------------------------------------------------
async def _upsert_sso_user(
    request: Request,
    *,
    issuer: str,
    subject: str,
    email: str | None,
    name: str | None,
    tenant_id: str,
) -> str | None:
    """Upsert into sso_users and return the resulting user_id (or None)."""
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO sso_users (issuer, subject, email, name, user_id, tenant_id, last_login)
                VALUES ($1, $2, $3, $4, gen_random_uuid(), $5, NOW())
                ON CONFLICT ON CONSTRAINT ux_sso_user
                DO UPDATE SET email = EXCLUDED.email,
                              name = EXCLUDED.name,
                              tenant_id = COALESCE(sso_users.tenant_id, EXCLUDED.tenant_id),
                              last_login = NOW()
                RETURNING user_id
                """,
                issuer, subject, email, name, uuid.UUID(tenant_id),
            )
            return str(row["user_id"]) if row and row["user_id"] else None
    except Exception as exc:  # pragma: no cover — DB schema race / no pool
        log.warning("sso.upsert_failed issuer=%s subject=%s err=%s", issuer, subject, exc)
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/config")
async def sso_config() -> dict[str, Any]:
    """Tell the frontend whether SSO is wired and to which issuer."""
    cfg = _config()
    enabled = _enabled(cfg)
    return {
        "enabled": enabled,
        "issuer": cfg["issuer"] if enabled else None,
    }


@router.get("/login")
async def sso_login(request: Request, return_to: str = "/") -> RedirectResponse:
    """302 the browser to the IdP's /authorize endpoint."""
    client = _build_client()
    try:
        meta = await client.discover()
    except OidcError as exc:
        log.error("sso.discover_failed err=%s", exc)
        raise HTTPException(status_code=502, detail=f"OIDC discovery failed: {exc}")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    url = client.authorize_url(state=state, nonce=nonce, meta=meta)

    resp = RedirectResponse(url, status_code=302)
    # Cookies are http-only + same-site=lax; production should also set
    # secure=True behind TLS.
    cookie_kwargs = dict(httponly=True, samesite="lax", max_age=600, path="/")
    resp.set_cookie(_STATE_COOKIE, state, **cookie_kwargs)
    resp.set_cookie(_NONCE_COOKIE, nonce, **cookie_kwargs)
    resp.set_cookie(_RETURN_COOKIE, return_to or "/", **cookie_kwargs)
    return resp


@router.get("/callback")
async def sso_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Exchange the auth code, mint a Princeps JWT, drop a cookie, redirect."""
    if error:
        raise HTTPException(status_code=400, detail=f"OIDC error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code/state")

    expected_state = request.cookies.get(_STATE_COOKIE)
    if not expected_state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="State mismatch")
    nonce = request.cookies.get(_NONCE_COOKIE)
    return_to = request.cookies.get(_RETURN_COOKIE) or "/"

    client = _build_client()
    try:
        token_resp = await client.exchange_code(code)
    except OidcError as exc:
        log.error("sso.exchange_failed err=%s", exc)
        raise HTTPException(status_code=502, detail=f"OIDC token exchange failed: {exc}")

    id_token = token_resp.get("id_token")
    access_token = token_resp.get("access_token")
    claims: dict[str, Any] = {}

    if id_token:
        try:
            claims = await client.verify_id_token(id_token, nonce=nonce)
        except OidcError as exc:
            log.warning("sso.id_token_verify_failed err=%s", exc)
            raise HTTPException(status_code=401, detail=f"ID token invalid: {exc}")

    if access_token and not claims.get("email"):
        try:
            userinfo = await client.fetch_userinfo(access_token)
            claims = {**userinfo, **claims}  # ID token wins on conflict
        except OidcError as exc:
            log.warning("sso.userinfo_failed err=%s", exc)

    issuer = claims.get("iss") or _config()["issuer"] or ""
    subject = claims.get("sub") or ""
    if not issuer or not subject:
        raise HTTPException(status_code=400, detail="OIDC claims missing iss/sub")

    email = claims.get("email")
    name = claims.get("name") or claims.get("preferred_username")
    tenant_id = _resolve_tenant(claims)

    user_id = await _upsert_sso_user(
        request,
        issuer=issuer,
        subject=subject,
        email=email,
        name=name,
        tenant_id=tenant_id,
    )

    # Mint Princeps JWT (HS256, signed with PRINCEPS_JWT_SECRET / JWT_SECRET).
    payload: dict[str, Any] = {
        "sub": user_id or f"{issuer}#{subject}",
        "email": email,
        "name": name,
        "tenant_id": tenant_id,
        "princeps_tenant": tenant_id,
        "auth_source": "sso",
        "issuer": issuer,
    }
    princeps_token = encode_jwt(payload)

    safe_return = return_to if return_to.startswith("/") else "/"
    resp = RedirectResponse(safe_return, status_code=302)
    resp.set_cookie(
        _TOKEN_COOKIE,
        princeps_token,
        httponly=True,
        samesite="lax",
        max_age=86400,
        path="/",
    )
    # Drop the short-lived state cookies.
    for cookie in (_STATE_COOKIE, _NONCE_COOKIE, _RETURN_COOKIE):
        resp.delete_cookie(cookie, path="/")
    return resp


@router.post("/logout")
async def sso_logout(request: Request) -> RedirectResponse:
    """Clear the Princeps cookie and redirect home."""
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(_TOKEN_COOKIE, path="/")
    return resp


__all__ = ["router"]
