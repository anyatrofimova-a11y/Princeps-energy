"""JWT helpers for the Princeps login flow (BOT-LOG-AUTH).

This module is deliberately lightweight and independent from the existing
DB-backed auth in ``app/auth.py`` / ``app/routers/auth.py``. It powers the
new ``/api/auth/*`` endpoints consumed by the React login page.

Design choices:
* Uses PyJWT if importable (it is in requirements.txt as ``pyjwt``) —
  falls back to ``python-jose`` if only that is installed, and finally to
  a stdlib HMAC-SHA256 signer so we never add a new dependency.
* Algorithm fixed to HS256.
* Secret from ``PRINCEPS_JWT_SECRET`` env var with a dev-only default.
* ``decode_access_token`` returns ``None`` on any failure rather than
  raising — callers decide whether to 401.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Optional

from fastapi import Header, HTTPException, status

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
JWT_SECRET = os.environ.get(
    "PRINCEPS_JWT_SECRET",
    "princeps-dev-secret-do-not-use-in-prod",
)
JWT_ALGORITHM = "HS256"
# 7 days in seconds.
JWT_EXP_SECONDS = 7 * 24 * 60 * 60


# ---------------------------------------------------------------------------
# Library selection — prefer pyjwt, then jose, then stdlib fallback
# ---------------------------------------------------------------------------
_BACKEND: str
try:
    import jwt as _pyjwt  # type: ignore
    _BACKEND = "pyjwt"
except Exception:  # pragma: no cover
    try:
        from jose import jwt as _jose_jwt  # type: ignore
        _BACKEND = "jose"
    except Exception:
        _BACKEND = "stdlib"


# ---------------------------------------------------------------------------
# Stdlib HMAC fallback (used only when neither pyjwt nor jose is installed)
# ---------------------------------------------------------------------------
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = (-len(data)) % 4
    return base64.urlsafe_b64decode(data + ("=" * pad))


def _stdlib_encode(payload: dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url_encode(json.dumps(payload, separators=(",", ":"), default=str).encode())
    signing_input = f"{h}.{p}".encode()
    sig = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url_encode(sig)}"


def _stdlib_decode(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token")
    h_b64, p_b64, s_b64 = parts
    expected = hmac.new(
        JWT_SECRET.encode(), f"{h_b64}.{p_b64}".encode(), hashlib.sha256
    ).digest()
    actual = _b64url_decode(s_b64)
    if not hmac.compare_digest(expected, actual):
        raise ValueError("bad signature")
    payload = json.loads(_b64url_decode(p_b64))
    exp = payload.get("exp")
    if exp is not None and float(exp) < time.time():
        raise ValueError("expired")
    return payload


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def create_access_token(email: str, first_name: str, role: str) -> str:
    """Create a 7-day HS256 access token for the given user."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": email,
        "first_name": first_name,
        "role": role,
        "iat": now,
        "exp": now + JWT_EXP_SECONDS,
    }
    if _BACKEND == "pyjwt":
        token = _pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        # PyJWT >=2 returns str; <2 returned bytes.
        return token.decode("utf-8") if isinstance(token, bytes) else token
    if _BACKEND == "jose":
        return _jose_jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return _stdlib_encode(payload)


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Decode a token. Return the payload dict or ``None`` on any failure."""
    if not token:
        return None
    try:
        if _BACKEND == "pyjwt":
            return _pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if _BACKEND == "jose":
            return _jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return _stdlib_decode(token)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """FastAPI dependency — parses ``Authorization: Bearer <token>``.

    Returns the decoded claim dict on success; raises 401 otherwise.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return payload
