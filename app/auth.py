"""JWT encoding/decoding and password hashing for Princeps auth."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

# Use bcrypt if available, else fallback to hashlib-based hashing
try:
    import bcrypt
    _HAS_BCRYPT = True
except ImportError:
    _HAS_BCRYPT = False

def _resolve_jwt_secret() -> str:
    """Return JWT_SECRET, failing fast in production rather than silently
    falling back to a per-process random secret (which would invalidate all
    tokens on restart and break multi-replica token verification)."""
    secret = os.environ.get("JWT_SECRET")
    if secret:
        return secret
    if os.environ.get("PRINCEPS_ENV", "development").lower() == "production":
        raise RuntimeError(
            "JWT_SECRET must be set in production. A per-process random "
            "fallback would invalidate all tokens on restart and break "
            "multi-replica token verification."
        )
    import logging as _logging
    _logging.getLogger("princeps.auth").warning(
        "JWT_SECRET unset — using ephemeral random secret (dev only). "
        "Set JWT_SECRET to a stable value before deploying to production."
    )
    return secrets.token_hex(32)


JWT_SECRET = _resolve_jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = int(os.environ.get("JWT_EXPIRY_SECONDS", "86400"))  # 24h default


def _b64encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    return urlsafe_b64decode(s + "=" * padding)


def encode_jwt(payload: dict, expiry_seconds: int | None = None) -> str:
    """Create a simple HS256 JWT token."""
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    payload = {**payload, "exp": time.time() + (expiry_seconds or JWT_EXPIRY_SECONDS)}

    header_b64 = _b64encode(json.dumps(header).encode())
    payload_b64 = _b64encode(json.dumps(payload, default=str).encode())

    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    sig_b64 = _b64encode(signature)

    return f"{signing_input}.{sig_b64}"


def decode_jwt(token: str) -> dict:
    """Decode and verify a JWT token. Raises ValueError on invalid/expired."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")

    header_b64, payload_b64, sig_b64 = parts

    # Verify signature
    signing_input = f"{header_b64}.{payload_b64}"
    expected_sig = hmac.new(
        JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    actual_sig = _b64decode(sig_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid JWT signature")

    payload = json.loads(_b64decode(payload_b64))

    if payload.get("exp", 0) < time.time():
        raise ValueError("JWT token expired")

    return payload


def hash_password(password: str) -> str:
    """Hash a password using bcrypt (or SHA-256 fallback)."""
    if _HAS_BCRYPT:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    # Fallback: salted SHA-256
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"sha256:{salt}:{h}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    if _HAS_BCRYPT and password_hash.startswith("$2"):
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    if password_hash.startswith("sha256:"):
        _, salt, expected = password_hash.split(":", 2)
        h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return hmac.compare_digest(h, expected)
    return False


def generate_api_key() -> str:
    """Generate a random API key."""
    return f"pk_{secrets.token_hex(24)}"
