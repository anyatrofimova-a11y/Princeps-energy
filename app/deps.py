"""Shared FastAPI dependencies — DB pool, Claude client, auth, pagination."""

from __future__ import annotations

from fastapi import Query, Request, HTTPException
import asyncpg


async def get_pool(request: Request) -> asyncpg.Pool:
    """Yield the application-wide asyncpg connection pool."""
    return request.app.state.pool


async def get_claude(request: Request):
    """Yield the Anthropic AsyncAnthropic client."""
    return request.app.state.claude


async def get_optional_user(request: Request):
    """Return the current user or None if no auth header present.

    Used during transition period — existing endpoints keep working
    without auth while new /api/v1/ endpoints can require it.
    """
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    api_key = request.headers.get("X-API-Key")

    if not token and not api_key:
        return None

    pool = request.app.state.pool

    if api_key:
        row = await pool.fetchrow(
            "SELECT * FROM users WHERE api_key = $1", api_key
        )
        return dict(row) if row else None

    if token:
        try:
            from app.auth import decode_jwt
            payload = decode_jwt(token)
            row = await pool.fetchrow(
                "SELECT * FROM users WHERE user_id = $1",
                payload["sub"],
            )
            return dict(row) if row else None
        except Exception:
            return None

    return None


async def get_current_user(request: Request):
    """Require and return the authenticated user. Raises 401 if not authenticated."""
    user = await get_optional_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


class PageParams:
    """Pagination parameters."""
    def __init__(self, offset: int = 0, limit: int = 50):
        self.offset = offset
        self.limit = limit


async def get_page(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> PageParams:
    return PageParams(offset, limit)
