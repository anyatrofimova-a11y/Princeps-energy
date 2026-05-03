"""Login router for the Princeps web login page (BOT-LOG-AUTH).

Mounted at ``/api/auth`` by ``app/main.py``. Endpoints:
  POST /login   — email + password → JWT + user profile
  GET  /me      — returns the profile of the bearer-token holder
  POST /logout  — no-op for v1 (client drops the token)

This router is deliberately *separate* from ``app/routers/auth.py``
(which is the DB-backed v1 auth at ``/api/v1/auth``). We keep both
surfaces alive so the existing user/org flow is untouched.

Login acceptance rules (v1, in-memory allow-list):
  * email is in the owner set (env ``PRINCEPS_OWNER_EMAILS`` comma-separated;
    in dev defaults to the project owner only when ``PRINCEPS_ENV`` is unset
    or != ``production``), OR
  * email ends with ``@princeps.app``, OR
  * password equals the dev master password — env ``PRINCEPS_DEV_PASSWORD``;
    falls back to literal ``"princeps"`` only when ``PRINCEPS_ENV`` is unset
    or != ``production``. In production, the master-password backdoor is
    disabled entirely unless the env var is explicitly set.

Email regex: ``^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$``
Password minimum length: 4.
"""

from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from utils.auth import create_access_token, get_current_user
from fastapi import Depends

router = APIRouter()

# ---------------------------------------------------------------------------
# Config — simple in-memory allow-list; no DB.
#
# Production hardening (PRINCEPS_ENV=production):
#   * OWNER_EMAILS comes from PRINCEPS_OWNER_EMAILS (comma-separated). The
#     hardcoded dev owner is dropped — empty set if no env var is provided.
#   * The dev-master-password backdoor is disabled unless PRINCEPS_DEV_PASSWORD
#     is explicitly set; the literal "princeps" default is dev-only.
# ---------------------------------------------------------------------------
_IS_PRODUCTION = os.environ.get("PRINCEPS_ENV", "development").lower() == "production"

_owner_env = os.environ.get("PRINCEPS_OWNER_EMAILS", "").strip()
if _owner_env:
    OWNER_EMAILS: set[str] = {e.strip().lower() for e in _owner_env.split(",") if e.strip()}
elif not _IS_PRODUCTION:
    OWNER_EMAILS: set[str] = {"anya.trofimova@yahoo.com"}
else:
    OWNER_EMAILS: set[str] = set()

ALLOWED_DOMAIN_SUFFIX = "@princeps.app"

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _dev_master_password() -> str | None:
    """Return the dev master password, or ``None`` to disable the backdoor.

    Production requires ``PRINCEPS_DEV_PASSWORD`` to be explicitly set;
    there is no literal fallback. Dev falls back to ``"princeps"``.
    """
    explicit = os.environ.get("PRINCEPS_DEV_PASSWORD")
    if explicit:
        return explicit
    if _IS_PRODUCTION:
        return None
    return "princeps"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str
    password: str


class UserPayload(BaseModel):
    email: str
    first_name: str
    display_name: str
    role: str


class LoginResponse(BaseModel):
    token: str
    user: UserPayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _derive_first_name(email: str) -> str:
    """Part before the first ``.``, ``_`` or ``-`` in the local-part, title-cased."""
    local = email.split("@", 1)[0]
    # Split on any of . _ -
    parts = re.split(r"[._-]", local, maxsplit=1)
    first = parts[0] if parts and parts[0] else local
    return first.title() if first else "User"


def _derive_display_name(email: str) -> str:
    """Title-case the full local part, swapping separators for spaces."""
    local = email.split("@", 1)[0]
    cleaned = re.sub(r"[._-]+", " ", local).strip()
    if not cleaned:
        return email
    return " ".join(word.title() for word in cleaned.split())


def _role_for(email: str) -> str:
    return "owner" if email.lower() in OWNER_EMAILS else "editor"


def _is_accepted(email: str, password: str) -> bool:
    if email.lower() in OWNER_EMAILS:
        return True
    if email.lower().endswith(ALLOWED_DOMAIN_SUFFIX):
        return True
    master = _dev_master_password()
    if master is not None and password == master:
        return True
    return False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> dict[str, Any]:
    email = (body.email or "").strip()
    password = body.password or ""

    if not _EMAIL_RE.match(email) or len(password) < 4:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not _is_accepted(email, password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    first_name = _derive_first_name(email)
    display_name = _derive_display_name(email)
    role = _role_for(email)

    token = create_access_token(email=email, first_name=first_name, role=role)

    return {
        "token": token,
        "user": {
            "email": email,
            "first_name": first_name,
            "display_name": display_name,
            "role": role,
        },
    }


@router.get("/me")
async def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    email = user.get("sub") or ""
    # Prefer claims from the token; fall back to deriving if missing.
    first_name = user.get("first_name") or _derive_first_name(email)
    display_name = _derive_display_name(email)
    role = user.get("role") or _role_for(email)
    return {
        "email": email,
        "first_name": first_name,
        "display_name": display_name,
        "role": role,
    }


@router.post("/logout")
async def logout() -> dict[str, bool]:
    # Token invalidation is client-side for v1.
    return {"ok": True}
