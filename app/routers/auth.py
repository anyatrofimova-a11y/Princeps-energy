"""Auth router — register, login, refresh, API keys."""

from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import asyncpg

from app.auth import encode_jwt, decode_jwt, hash_password, verify_password, generate_api_key
from app.deps import get_pool, get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str | None = None
    org_name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/register")
async def register(body: RegisterRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """Register a new user account."""
    existing = await pool.fetchrow(
        "SELECT user_id FROM users WHERE email = $1", body.email
    )
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    pw_hash = hash_password(body.password)
    row = await pool.fetchrow(
        """
        INSERT INTO users (email, password_hash, name, org_name)
        VALUES ($1, $2, $3, $4)
        RETURNING user_id, email, name, org_name, role, created_at
        """,
        body.email, pw_hash, body.name, body.org_name,
    )

    token = encode_jwt({"sub": str(row["user_id"]), "email": row["email"], "role": row["role"]})

    return {
        "user": {
            "user_id": str(row["user_id"]),
            "email": row["email"],
            "name": row["name"],
            "org_name": row["org_name"],
            "role": row["role"],
        },
        "token": token,
    }


@router.post("/login")
async def login(body: LoginRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """Login with email and password."""
    row = await pool.fetchrow(
        "SELECT * FROM users WHERE email = $1", body.email
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Update last_login
    await pool.execute(
        "UPDATE users SET last_login = NOW() WHERE user_id = $1",
        row["user_id"],
    )

    token = encode_jwt({"sub": str(row["user_id"]), "email": row["email"], "role": row["role"]})

    return {
        "user": {
            "user_id": str(row["user_id"]),
            "email": row["email"],
            "name": row["name"],
            "org_name": row["org_name"],
            "role": row["role"],
        },
        "token": token,
    }


@router.post("/refresh")
async def refresh_token(user=Depends(get_current_user)):
    """Refresh JWT token."""
    token = encode_jwt({
        "sub": str(user["user_id"]),
        "email": user["email"],
        "role": user["role"],
    })
    return {"token": token}


@router.get("/me")
async def get_me(user=Depends(get_current_user)):
    """Get current user profile."""
    return {
        "user_id": str(user["user_id"]),
        "email": user["email"],
        "name": user["name"],
        "org_name": user["org_name"],
        "role": user["role"],
        "created_at": user["created_at"].isoformat() if user["created_at"] else None,
        "last_login": user["last_login"].isoformat() if user["last_login"] else None,
    }


@router.post("/api-key")
async def create_api_key(user=Depends(get_current_user), pool: asyncpg.Pool = Depends(get_pool)):
    """Generate a new API key for the current user."""
    key = generate_api_key()
    await pool.execute(
        "UPDATE users SET api_key = $1 WHERE user_id = $2",
        key, user["user_id"],
    )
    return {"api_key": key}
