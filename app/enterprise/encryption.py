"""
app/enterprise/encryption.py — AES-GCM helpers for secrets at rest.

Used by ``app/enterprise/sso.py`` to encrypt the per-tenant IdP
``client_secret`` before writing it to ``tenant_sso_configs.client_secret_encrypted``.

Key is read from the ``PRINCEPS_ENCRYPTION_KEY`` env var (base64-encoded
32-byte random key). The key is validated at first use — the module is
always importable so unit tests / dev stacks that don't exercise SSO
can keep running without provisioning a key.

Production behaviour
--------------------
In production (``PRINCEPS_ENV=production`` or ``APP_ENV=production``), the key
MUST be set; ``_load_key()`` will raise ``RuntimeError`` otherwise. For
dev / CI a missing key silently falls back to a development-only stub key so
the rest of the app can boot.

Threat model
------------
Attacker has read-only access to Postgres (leaked backup, SQL-injection read
primitive). Ciphertext without the application key is useless. Attacker with
filesystem read on the app container can still decrypt — that is out of scope
for this layer and is handled by host-level KMS in a future iteration.

Format
------
Ciphertext layout (bytes):

    [12-byte nonce][N-byte ciphertext+tag]

AES-GCM's 16-byte auth tag is appended to the ciphertext by
``cryptography``'s API; we do not split it out.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
from typing import Final

log = logging.getLogger("princeps.enterprise.encryption")

_KEY_ENV: Final[str] = "PRINCEPS_ENCRYPTION_KEY"
_NONCE_LEN: Final[int] = 12  # AES-GCM recommended nonce size
_KEY_LEN: Final[int] = 32    # AES-256


def _is_production() -> bool:
    env = (os.environ.get("PRINCEPS_ENV") or os.environ.get("APP_ENV") or "").lower()
    return env in ("production", "prod")


_cached_key: bytes | None = None


def _load_key() -> bytes:
    """Resolve and cache the 32-byte AES-GCM key.

    Raises ``RuntimeError`` in production when the key is missing or malformed.
    Outside production, falls back to a non-secret deterministic dev stub so
    local tests and demos still work.
    """
    global _cached_key
    if _cached_key is not None:
        return _cached_key

    raw = os.environ.get(_KEY_ENV, "").strip()

    if not raw:
        if _is_production():
            raise RuntimeError(
                f"{_KEY_ENV} is required in production. Generate one with: "
                f"python -c \"import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())\""
            )
        log.warning(
            "%s not set — using DEV stub key. SSO client_secret ciphertext "
            "is NOT secure. Do not use this build in production.",
            _KEY_ENV,
        )
        _cached_key = b"\x00" * _KEY_LEN
        return _cached_key

    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise RuntimeError(
            f"{_KEY_ENV} must be base64-encoded 32 bytes (AES-256). "
            f"Decode failed: {exc}"
        ) from exc

    if len(decoded) != _KEY_LEN:
        raise RuntimeError(
            f"{_KEY_ENV} decoded to {len(decoded)} bytes, expected {_KEY_LEN}."
        )

    _cached_key = decoded
    return _cached_key


def encrypt(plaintext: str) -> bytes:
    """Encrypt *plaintext* with AES-256-GCM. Returns ``nonce || ciphertext``.

    The nonce is generated fresh per call from ``secrets.token_bytes``.
    """
    if plaintext is None:
        raise ValueError("encrypt() requires a non-None plaintext")

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "cryptography package missing — install via requirements.txt "
            "(`cryptography>=42`)"
        ) from exc

    key = _load_key()
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(_NONCE_LEN)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return nonce + ct


def decrypt(ciphertext: bytes) -> str:
    """Decrypt a blob produced by :func:`encrypt`. Returns the plaintext string."""
    if not ciphertext or len(ciphertext) <= _NONCE_LEN:
        raise ValueError("Ciphertext too short to contain nonce + payload")

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "cryptography package missing — install via requirements.txt "
            "(`cryptography>=42`)"
        ) from exc

    key = _load_key()
    aesgcm = AESGCM(key)
    nonce = ciphertext[:_NONCE_LEN]
    body = ciphertext[_NONCE_LEN:]
    return aesgcm.decrypt(nonce, body, associated_data=None).decode("utf-8")


def reset_cache_for_tests() -> None:
    """Clear the cached key so tests can swap the env var mid-run."""
    global _cached_key
    _cached_key = None


__all__ = ["encrypt", "decrypt", "reset_cache_for_tests"]
