"""Generic OIDC helper for Princeps SSO (single-file package).

Lives at ``app/auth_oidc.py`` rather than ``app/auth/oidc_client.py`` so we
don't conflict with the existing ``app/auth.py`` JWT module — the public
symbol ``OidcClient`` is unchanged.

Implements the bare minimum of OpenID Connect Authorization Code Flow:
  * Provider discovery via ``/.well-known/openid-configuration``
  * Authorize-URL building (with state + nonce + PKCE-friendly extensions)
  * Token exchange (``code`` -> access_token + id_token + refresh_token)
  * Userinfo fetch
  * ID-token verification (RS256 via JWKS, falls back to HS256 client_secret
    if the IdP returns symmetric tokens — Auth0 default)

No new dependency required: uses ``httpx`` + ``pyjwt`` already in the venv.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

try:  # pyjwt is already installed (see /Users/anyatrofimova/feasibly/.venv).
    import jwt
    from jwt import PyJWKClient

    _HAS_PYJWT = True
except ImportError:  # pragma: no cover — defensive only.
    _HAS_PYJWT = False

log = logging.getLogger("princeps.auth.oidc")

_DISCOVERY_TTL_SECONDS = 3600  # OIDC discovery docs change rarely.


@dataclass
class OidcMetadata:
    """Subset of the OIDC discovery document we actually use."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str | None
    jwks_uri: str | None
    end_session_endpoint: str | None = None
    fetched_at: float = field(default_factory=time.time)

    def is_stale(self) -> bool:
        return (time.time() - self.fetched_at) > _DISCOVERY_TTL_SECONDS


class OidcError(Exception):
    """Raised when an OIDC interaction fails (network, schema, signature)."""


class OidcClient:
    """Minimal OIDC client. One instance per (issuer, client_id) tuple."""

    def __init__(
        self,
        issuer: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: str = "openid email profile",
        *,
        timeout: float = 10.0,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.discovery_url = f"{self.issuer}/.well-known/openid-configuration"
        self._timeout = timeout
        self._meta: OidcMetadata | None = None
        self._jwks_client: Any = None  # lazy PyJWKClient

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    async def discover(self) -> OidcMetadata:
        """Fetch + cache the OIDC discovery document."""
        if self._meta is not None and not self._meta.is_stale():
            return self._meta

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.get(self.discovery_url)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise OidcError(
                    f"OIDC discovery failed for {self.discovery_url}: {exc}"
                ) from exc
            doc = resp.json()

        try:
            self._meta = OidcMetadata(
                issuer=doc["issuer"],
                authorization_endpoint=doc["authorization_endpoint"],
                token_endpoint=doc["token_endpoint"],
                userinfo_endpoint=doc.get("userinfo_endpoint"),
                jwks_uri=doc.get("jwks_uri"),
                end_session_endpoint=doc.get("end_session_endpoint"),
            )
        except KeyError as exc:
            raise OidcError(f"OIDC discovery missing required field: {exc}") from exc

        return self._meta

    # ------------------------------------------------------------------
    # Authorize URL
    # ------------------------------------------------------------------
    def authorize_url(
        self,
        state: str,
        nonce: str,
        *,
        meta: OidcMetadata | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> str:
        """Build the full ``/authorize?...`` redirect URL.

        Caller must have already awaited ``discover()`` and pass the result
        as ``meta`` (so this stays a sync function safe to call from a
        302-redirect handler).
        """
        if meta is None:
            if self._meta is None:
                raise OidcError("authorize_url called before discover()")
            meta = self._meta

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scopes,
            "state": state,
            "nonce": nonce,
        }
        if extra_params:
            params.update(extra_params)
        return f"{meta.authorization_endpoint}?{urlencode(params)}"

    # ------------------------------------------------------------------
    # Token exchange
    # ------------------------------------------------------------------
    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange an authorization code for tokens."""
        meta = await self.discover()

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(
                    meta.token_endpoint,
                    data=data,
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise OidcError(f"OIDC token exchange failed: {exc}") from exc
            return resp.json()

    # ------------------------------------------------------------------
    # Userinfo
    # ------------------------------------------------------------------
    async def fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        meta = await self.discover()
        if not meta.userinfo_endpoint:
            return {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.get(
                    meta.userinfo_endpoint,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise OidcError(f"OIDC userinfo failed: {exc}") from exc
            return resp.json()

    # ------------------------------------------------------------------
    # ID-token verification
    # ------------------------------------------------------------------
    async def verify_id_token(
        self,
        id_token: str,
        *,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        """Verify the ID token signature + standard claims."""
        if not _HAS_PYJWT:
            raise OidcError("pyjwt missing — cannot verify ID token")

        meta = await self.discover()
        unverified_header = jwt.get_unverified_header(id_token)
        alg = unverified_header.get("alg", "RS256")

        if alg.startswith("HS"):
            # Symmetric — Auth0 default. Verify with client_secret.
            payload = jwt.decode(
                id_token,
                self.client_secret,
                algorithms=[alg],
                audience=self.client_id,
                issuer=meta.issuer,
            )
        else:
            if not meta.jwks_uri:
                raise OidcError("ID token uses RSA but provider lacks jwks_uri")
            if self._jwks_client is None:
                self._jwks_client = PyJWKClient(meta.jwks_uri)
            signing_key = self._jwks_client.get_signing_key_from_jwt(id_token)
            payload = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=[alg],
                audience=self.client_id,
                issuer=meta.issuer,
            )

        if nonce is not None and payload.get("nonce") != nonce:
            raise OidcError("ID token nonce mismatch")

        return payload


__all__ = ["OidcClient", "OidcError", "OidcMetadata"]
