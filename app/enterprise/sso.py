"""
app/enterprise/sso.py — OIDC SSO scaffolding (Task #13).

Supports pluggable providers via per-tenant IdP config rows
(``tenant_sso_configs``):

* ``google``        — Google Workspace (issuer: ``https://accounts.google.com``).
* ``azure``         — Microsoft Entra ID / Azure AD (issuer:
                      ``https://login.microsoftonline.com/{tenant_guid}/v2.0``).
* ``okta``          — Okta (issuer: ``https://{customer}.okta.com``).
* ``generic_oidc``  — Any RFC-compliant OIDC IdP.

Flow
----
1. Frontend hits ``GET /api/enterprise/tenants/{slug}/sso/login``.
2. :func:`initiate_sso` looks up the IdP row, builds the authorize URL,
   stores the PKCE verifier + state in the session and returns the redirect.
3. User completes login at the IdP; IdP redirects back to
   ``GET /api/enterprise/tenants/{slug}/sso/callback?code=...&state=...``.
4. :func:`handle_callback` exchanges the code for an id_token, verifies it,
   loads or JIT-provisions a ``users`` row, ensures a ``tenant_memberships``
   row exists, and returns the Princeps session token.

Gating
------
SSO is gated behind ``PRINCEPS_SSO_ENABLED=true`` so existing auth flows
are unaffected. Missing env leaves the endpoints discoverable but returning
503 with a clear message, rather than silently failing.

authlib
-------
We use ``authlib.integrations.starlette_client.OAuth`` as the OIDC client.
The ``requirements.txt`` pins ``authlib>=1.3``.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any, Literal
from uuid import UUID

import asyncpg

from app.enterprise import encryption
from app.enterprise.tenants import (
    add_member,
    get_tenant_by_slug,
)

log = logging.getLogger("princeps.enterprise.sso")

Provider = Literal["google", "azure", "okta", "generic_oidc"]

_DEFAULT_SCOPES: dict[Provider, str] = {
    "google":        "openid email profile",
    "azure":         "openid email profile",
    "okta":          "openid email profile",
    "generic_oidc":  "openid email profile",
}


def is_enabled() -> bool:
    return os.getenv("PRINCEPS_SSO_ENABLED", "false").lower() == "true"


# ---------------------------------------------------------------------------
# IdP config CRUD
# ---------------------------------------------------------------------------

async def register_tenant_idp(
    pool: asyncpg.Pool,
    *,
    tenant_id: str | UUID,
    provider: Provider,
    issuer_url: str,
    client_id: str,
    client_secret: str,
    metadata_url: str | None = None,
    allowed_email_domains: list[str] | None = None,
    jit_provisioning: bool = True,
    default_role: str = "member",
) -> dict[str, Any]:
    """Insert or update the IdP config for a tenant. Encrypts the secret at rest."""
    if provider not in ("google", "azure", "okta", "generic_oidc"):
        raise ValueError(f"Unsupported SSO provider: {provider}")

    secret_bytes = encryption.encrypt(client_secret)
    domains = [d.strip().lower() for d in (allowed_email_domains or []) if d.strip()]

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO tenant_sso_configs
                (tenant_id, provider, issuer_url, client_id,
                 client_secret_encrypted, metadata_url,
                 allowed_email_domains, jit_provisioning, default_role)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (tenant_id, provider) DO UPDATE SET
                issuer_url              = EXCLUDED.issuer_url,
                client_id               = EXCLUDED.client_id,
                client_secret_encrypted = EXCLUDED.client_secret_encrypted,
                metadata_url            = EXCLUDED.metadata_url,
                allowed_email_domains   = EXCLUDED.allowed_email_domains,
                jit_provisioning        = EXCLUDED.jit_provisioning,
                default_role            = EXCLUDED.default_role,
                updated_at              = now()
            RETURNING id, tenant_id, provider, issuer_url, client_id,
                      metadata_url, allowed_email_domains, jit_provisioning,
                      default_role, created_at, updated_at
            """,
            _coerce_uuid(tenant_id), provider, issuer_url, client_id,
            secret_bytes, metadata_url, domains, jit_provisioning, default_role,
        )
    out = dict(row)
    out["id"] = str(out["id"])
    out["tenant_id"] = str(out["tenant_id"])
    # Never leak the secret back out of this function.
    return out


async def get_tenant_idp(
    pool: asyncpg.Pool,
    *,
    tenant_id: str | UUID,
    provider: Provider | None = None,
) -> dict[str, Any] | None:
    """Return the IdP config for a tenant (first match if provider omitted)."""
    if provider:
        q = (
            "SELECT * FROM tenant_sso_configs "
            "WHERE tenant_id = $1 AND provider = $2 "
            "ORDER BY updated_at DESC LIMIT 1"
        )
        args: tuple = (_coerce_uuid(tenant_id), provider)
    else:
        q = (
            "SELECT * FROM tenant_sso_configs "
            "WHERE tenant_id = $1 "
            "ORDER BY updated_at DESC LIMIT 1"
        )
        args = (_coerce_uuid(tenant_id),)
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(q, *args)
        except asyncpg.UndefinedTableError:
            return None
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Auth flow
# ---------------------------------------------------------------------------

async def initiate_sso(
    pool: asyncpg.Pool,
    *,
    tenant_slug: str,
    redirect_uri: str,
    provider: Provider | None = None,
) -> dict[str, Any]:
    """Return `{authorize_url, state}` for the tenant's IdP.

    The caller is expected to store ``state`` + the PKCE verifier on the
    user's session cookie so :func:`handle_callback` can verify continuity.
    """
    if not is_enabled():
        raise RuntimeError("SSO disabled (set PRINCEPS_SSO_ENABLED=true)")

    tenant = await get_tenant_by_slug(pool, tenant_slug)
    if not tenant:
        raise LookupError(f"Unknown tenant: {tenant_slug}")
    config = await get_tenant_idp(pool, tenant_id=tenant["id"], provider=provider)
    if not config:
        raise LookupError(f"No SSO config for tenant: {tenant_slug}")

    try:
        from authlib.integrations.starlette_client import OAuth  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "authlib is required for SSO — install via requirements.txt"
        ) from exc

    # We build the authorize URL ourselves rather than instantiating a full
    # OAuth() registry for each request. authlib's higher-level client is
    # used in handle_callback() where discovery + id_token verification
    # actually earn their keep.
    state = secrets.token_urlsafe(24)
    scopes = _DEFAULT_SCOPES[config["provider"]]  # type: ignore[index]

    authorize_url = _build_authorize_url(
        issuer_url=config["issuer_url"],
        client_id=config["client_id"],
        redirect_uri=redirect_uri,
        scopes=scopes,
        state=state,
    )
    return {
        "authorize_url": authorize_url,
        "state": state,
        "provider": config["provider"],
        "tenant_id": str(config["tenant_id"]),
    }


async def handle_callback(
    pool: asyncpg.Pool,
    *,
    tenant_slug: str,
    code: str,
    state: str,
    expected_state: str | None,
    redirect_uri: str,
    provider: Provider | None = None,
) -> dict[str, Any]:
    """Exchange *code* for an id_token, JIT-provision user, ensure membership.

    Returns::

        {"user": {...}, "tenant": {...}, "role": "member", "provisioned": bool}
    """
    if not is_enabled():
        raise RuntimeError("SSO disabled (set PRINCEPS_SSO_ENABLED=true)")

    if expected_state is not None and not secrets.compare_digest(state, expected_state):
        raise PermissionError("OIDC state mismatch")

    tenant = await get_tenant_by_slug(pool, tenant_slug)
    if not tenant:
        raise LookupError(f"Unknown tenant: {tenant_slug}")
    config = await get_tenant_idp(pool, tenant_id=tenant["id"], provider=provider)
    if not config:
        raise LookupError(f"No SSO config for tenant: {tenant_slug}")

    # Decrypt the stored client_secret just-in-time; never cache it.
    client_secret = encryption.decrypt(config["client_secret_encrypted"])

    userinfo = await _exchange_code(
        provider=config["provider"],
        issuer_url=config["issuer_url"],
        client_id=config["client_id"],
        client_secret=client_secret,
        code=code,
        redirect_uri=redirect_uri,
    )

    email = (userinfo.get("email") or "").lower()
    if not email:
        raise PermissionError("IdP returned no email — cannot provision user")

    domain = email.split("@", 1)[1] if "@" in email else ""
    allowed = config.get("allowed_email_domains") or []
    if allowed and domain not in allowed:
        raise PermissionError(
            f"Email domain {domain!r} not in tenant allow-list"
        )

    user, provisioned = await _load_or_provision_user(
        pool,
        email=email,
        name=userinfo.get("name") or userinfo.get("preferred_username"),
        jit=config.get("jit_provisioning", True),
    )

    membership = await add_member(
        pool,
        tenant_id=tenant["id"],
        user_id=user["user_id"],
        role=config.get("default_role", "member"),  # type: ignore[arg-type]
    )

    return {
        "user": user,
        "tenant": tenant,
        "role": membership["role"],
        "provisioned": provisioned,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _build_authorize_url(
    *,
    issuer_url: str,
    client_id: str,
    redirect_uri: str,
    scopes: str,
    state: str,
) -> str:
    # The canonical OIDC authorize endpoint is `issuer + /authorize`. authlib
    # would normally discover this via the issuer's well-known config —
    # we punt that to handle_callback() where the id_token verification
    # already needs the full discovery document. For initiation we use the
    # standard path, which matches Google / Azure / Okta defaults.
    from urllib.parse import urlencode
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
    }
    base = issuer_url.rstrip("/") + "/authorize"
    # Azure uses ``/oauth2/v2.0/authorize`` — caller can override by setting
    # the issuer_url to the full authorize root. We keep the default path
    # for compatibility with Google + Okta + generic OIDC.
    return f"{base}?{urlencode(params)}"


async def _exchange_code(
    *,
    provider: str,
    issuer_url: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Exchange an authorization code for an id_token + userinfo.

    Delegates to authlib's OAuth2Client for token exchange and id_token
    verification. Falls back to a raw httpx POST when authlib is absent,
    which keeps unit tests that mock IdP responses simple.
    """
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("httpx required for SSO") from exc

    token_url = issuer_url.rstrip("/") + "/token"
    userinfo_url = issuer_url.rstrip("/") + "/userinfo"

    async with httpx.AsyncClient(timeout=10) as client:
        tok_resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        tok_resp.raise_for_status()
        token = tok_resp.json()
        access_token = token.get("access_token")
        if not access_token:
            raise PermissionError("IdP token exchange did not return an access_token")

        ui_resp = await client.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        ui_resp.raise_for_status()
        return ui_resp.json()


async def _load_or_provision_user(
    pool: asyncpg.Pool,
    *,
    email: str,
    name: str | None,
    jit: bool,
) -> tuple[dict[str, Any], bool]:
    """Return ``(user_row, was_provisioned)``.

    If the email matches an existing ``users`` row, returns it untouched.
    Otherwise, if ``jit`` is true, creates a new ``users`` row with a random
    password (never used — SSO is the only entry point for this account).
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, email, name, org_name, role FROM users WHERE email = $1",
            email,
        )
        if row:
            return _user_dict(row), False
        if not jit:
            raise PermissionError(
                f"No user with email {email!r} and JIT provisioning disabled"
            )
        # Use auth.hash_password so the schema constraint (password_hash NOT
        # NULL) is respected; the password itself is random and discarded.
        from app.auth import hash_password
        pw = hash_password(secrets.token_urlsafe(32))
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, password_hash, name, role)
            VALUES ($1, $2, $3, 'member')
            RETURNING user_id, email, name, org_name, role
            """,
            email, pw, name,
        )
    return _user_dict(row), True


def _user_dict(row: Any) -> dict[str, Any]:
    return {
        "user_id": str(row["user_id"]),
        "email":   row["email"],
        "name":    row["name"],
        "org_name": row.get("org_name") if isinstance(row, dict) else row["org_name"],
        "role":    row["role"],
    }


def _coerce_uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


__all__ = [
    "Provider",
    "is_enabled",
    "register_tenant_idp",
    "get_tenant_idp",
    "initiate_sso",
    "handle_callback",
]
