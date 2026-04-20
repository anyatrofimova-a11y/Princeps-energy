"""Site enrichment router — ``GET /api/analysis/enrich``.

Single endpoint that returns everything a developer wants to know about a
point: postcode, LPA, DNO, UPRN, HMLR parcel, 12 planning constraints, EPC
certificates, and DynamicWorld land use.  Delegates to the 8 sub-enrichers
in ``utils.site_enrichment.enricher``; every call is time-boxed so the
overall p95 stays under 800 ms.

Auth: standard Princeps ``get_current_user`` dependency — falls back to the
demo user when ``PRINCEPS_DEMO_MODE`` is truthy, which it is in dev and in
all test fixtures.

Rate limit: 60 requests / minute / user. Implemented in-process with an
asyncio lock and a simple sliding-window counter keyed by user_id.  Not
cluster-aware; for multi-worker deployments the gateway layer should also
throttle.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.deps import get_current_user, get_pool

log = logging.getLogger("princeps.enrichment")

router = APIRouter(prefix="/api/analysis", tags=["enrichment"])


_RATE_WINDOW_S = 60.0
_RATE_LIMIT = 60
_rate_lock = asyncio.Lock()
_rate_log: dict[str, deque[float]] = {}


async def _rate_limit(user_id: str) -> None:
    """Enforce 60 req/min/user via an in-memory sliding window."""
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW_S
    async with _rate_lock:
        bucket = _rate_log.setdefault(user_id, deque())
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT:
            retry_after = max(1, int(bucket[0] + _RATE_WINDOW_S - now))
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded (60/min). Retry in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)


@router.get("/enrich")
async def enrich_endpoint(
    request: Request,
    lat: float = Query(..., ge=-90.0, le=90.0, description="WGS84 latitude"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="WGS84 longitude"),
    no_cache: bool = Query(False, description="Bypass the 24h Redis cache."),
    user: dict[str, Any] = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Return a full enrichment record for the supplied point.

    The response is always 200-OK with a ``success``-shaped body.  Any
    sub-enricher that couldn't deliver data leaves its slot ``null`` and
    logs a line in ``errors[]`` — callers NEVER see a 500 for partial
    infra.
    """
    user_id = str(user.get("user_id") or user.get("email") or "anon")
    await _rate_limit(user_id)

    # Late import — keep top-of-module fast for cold starts.
    from utils.site_enrichment.enricher import enrich as _enrich

    result = await _enrich(lat, lon, pool=pool, use_cache=not no_cache)
    return result.to_dict()
