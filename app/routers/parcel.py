"""Parcel router — BOT-FF single-page dossier + legacy 10-section detail.

Endpoints
---------
* ``GET /api/parcel/{inspire_id}`` — BOT-FF ``ParcelDossier`` (10 sub-queries
  run concurrently, Redis-cached 24h, 30 req/min/user).
* ``GET /api/parcel/{parcel_id}/detail`` — legacy deep-detail envelope backed
  by ``utils/parcel_detail.py`` (kept for the existing right-side inspector
  and for docket / project endpoints that already import it).

Both endpoints are defensively wrapped and NEVER return 500 — upstream
failures degrade to per-section warnings / a mock dossier.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Request

from app.deps import get_pool, get_current_user

log = logging.getLogger("princeps.routers.parcel")

router = APIRouter(tags=["parcel"])


# ---------------------------------------------------------------------------
# Rate-limiting — 30 req / min / user (in-memory; OK for single-process
# demo + Railway. Replace with Redis ZSET for multi-instance.)
# ---------------------------------------------------------------------------

_RATE_LIMIT_PER_MIN = 30
_RATE_LIMIT_WINDOW_S = 60
_rate_hits: dict[str, deque[float]] = defaultdict(deque)


def _rate_limit(user_id: str) -> None:
    now = time.monotonic()
    q = _rate_hits[user_id]
    while q and (now - q[0]) > _RATE_LIMIT_WINDOW_S:
        q.popleft()
    if len(q) >= _RATE_LIMIT_PER_MIN:
        retry_in = int(_RATE_LIMIT_WINDOW_S - (now - q[0])) + 1
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limited",
                "limit_per_min": _RATE_LIMIT_PER_MIN,
                "retry_after_s": retry_in,
            },
        )
    q.append(now)


# ---------------------------------------------------------------------------
# Redis cache — degrades to Postgres ``parcel_dossier_cache`` if Redis absent.
# ---------------------------------------------------------------------------

_REDIS = None
_REDIS_PROBED = False


async def _get_redis():
    global _REDIS, _REDIS_PROBED  # noqa: PLW0603
    if _REDIS_PROBED:
        return _REDIS
    _REDIS_PROBED = True
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    try:
        import redis.asyncio as redis_asyncio  # type: ignore

        _REDIS = redis_asyncio.from_url(url, decode_responses=True)
        # Touch — fail fast if unreachable.
        await _REDIS.ping()
        return _REDIS
    except Exception as exc:  # noqa: BLE001
        log.info("Redis unavailable (%s) — falling back to PG dossier cache", exc)
        _REDIS = None
        return None


async def _cache_get(pool: asyncpg.Pool, inspire_id: str) -> dict | None:
    r = await _get_redis()
    key = f"parcel:dossier:{inspire_id}"
    if r is not None:
        try:
            raw = await r.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:  # noqa: BLE001
            log.debug("redis get failed: %s", exc)
    # PG fallback
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT dossier_json
                  FROM parcel_dossier_cache
                 WHERE inspire_id = $1
                   AND expires_at > NOW()
                 LIMIT 1
                """,
                inspire_id,
            )
            if row and row["dossier_json"]:
                return (
                    row["dossier_json"]
                    if isinstance(row["dossier_json"], dict)
                    else json.loads(row["dossier_json"])
                )
    except Exception as exc:  # noqa: BLE001
        log.debug("pg cache get failed: %s", exc)
    return None


async def _cache_set(pool: asyncpg.Pool, inspire_id: str, dossier: dict) -> None:
    r = await _get_redis()
    key = f"parcel:dossier:{inspire_id}"
    payload = json.dumps(dossier, default=str)
    if r is not None:
        try:
            await r.set(key, payload, ex=86400)
            return
        except Exception as exc:  # noqa: BLE001
            log.debug("redis set failed: %s", exc)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO parcel_dossier_cache (inspire_id, dossier_json, cached_at, expires_at)
                VALUES ($1, $2::jsonb, NOW(), NOW() + INTERVAL '24 hours')
                ON CONFLICT (inspire_id)
                DO UPDATE SET dossier_json = EXCLUDED.dossier_json,
                              cached_at    = EXCLUDED.cached_at,
                              expires_at   = EXCLUDED.expires_at
                """,
                inspire_id,
                payload,
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("pg cache set failed: %s", exc)


# ---------------------------------------------------------------------------
# BOT-FF dossier endpoint
# ---------------------------------------------------------------------------


@router.get("/api/parcel/{inspire_id}")
async def parcel_dossier(
    request: Request,
    inspire_id: str = Path(..., description="INSPIRE parcel id"),
    pool: asyncpg.Pool = Depends(get_pool),
    user: dict = Depends(get_current_user),
):
    """BOT-FF dossier — 10 sub-queries, concurrent, Redis-cached 24h.

    Always returns 200. If the parcel isn't in the DB and no mock entry
    matches, returns a mock dossier keyed on the first fixture id with
    ``"source": "mock"`` so the drawer still renders.
    """
    user_id = str(user.get("user_id") or user.get("email") or "anon")
    _rate_limit(user_id)

    # Cache hit?
    cached = await _cache_get(pool, inspire_id)
    if cached:
        cached["_cache_hit"] = True
        return cached

    # Build
    try:
        from utils.parcel import build_dossier, mock_dossier

        t0 = time.monotonic()
        dossier = await asyncio.wait_for(
            build_dossier(pool, inspire_id, user=user), timeout=8.0
        )
        elapsed = time.monotonic() - t0
        dossier["_build_ms"] = round(elapsed * 1000, 1)
    except asyncio.TimeoutError:
        log.warning("parcel dossier timeout for %s — returning mock", inspire_id)
        from utils.parcel import mock_dossier

        dossier = mock_dossier(inspire_id, reason="build_timeout")
    except Exception as exc:  # noqa: BLE001
        log.exception("parcel dossier build crashed: %s", exc)
        try:
            from utils.parcel import mock_dossier

            dossier = mock_dossier(inspire_id, reason=f"build_error:{type(exc).__name__}")
        except Exception:  # noqa: BLE001
            # Truly last-resort — return a minimal envelope.
            dossier = {
                "inspire_id": inspire_id,
                "source": "error",
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                "partial": True,
            }

    # Fire-and-forget cache write.
    try:
        await _cache_set(pool, inspire_id, dossier)
    except Exception:  # noqa: BLE001
        pass
    dossier["_cache_hit"] = False
    return dossier


# ---------------------------------------------------------------------------
# Legacy 10-section detail (kept for existing inspector / docket endpoints)
# ---------------------------------------------------------------------------


@router.get("/api/parcel/{parcel_id}/detail")
async def parcel_detail(
    parcel_id: str = Path(..., description="Parcel id (UUID / INSPIRE id / prospect id)"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Deep 10-section parcel dossier (legacy shape).

    Looks up the parcel across ``parcels``, ``hmlr_inspire_parcels``, and
    ``prospect_parcels``, then runs each section builder concurrently.
    """
    from utils.parcel_detail import build_parcel_detail

    try:
        envelope = await build_parcel_detail(pool, parcel_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("parcel_detail top-level crash: %s", exc)
        return {
            "parcel_id": parcel_id,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "identity": {"warning": "top-level build failed"},
            "ownership": {"warning": "top-level build failed"},
            "planning": {"warning": "top-level build failed"},
            "environment": {"warning": "top-level build failed"},
            "grid": {"warning": "top-level build failed"},
            "access": {"warning": "top-level build failed"},
            "utilities": {"warning": "top-level build failed"},
            "utilities_easements": [],
            "topography": {"warning": "top-level build failed"},
            "market": {"warning": "top-level build failed"},
        }

    if envelope is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "parcel not found",
                "parcel_id": parcel_id,
                "searched_tables": ["parcels", "hmlr_inspire_parcels", "prospect_parcels"],
            },
        )
    return envelope


# ---------------------------------------------------------------------------
# HMLR INSPIRE polygon — BOT-B1 shipping the endpoint BOT-DP hacked around
# ---------------------------------------------------------------------------


async def _inspire_geometry_response(
    inspire_id: str,
    pool: asyncpg.Pool,
) -> dict:
    """Shared impl for singular + plural geometry routes."""
    from utils.site_enrichment.hmlr import lookup_by_inspire_id
    try:
        result = await lookup_by_inspire_id(inspire_id, pool=pool)
    except Exception as exc:  # noqa: BLE001
        log.exception("lookup_by_inspire_id crashed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "hmlr_lookup_failed",
                "inspire_id": inspire_id,
                "reason": f"{type(exc).__name__}: {str(exc)[:160]}",
            },
        )

    if not result.get("found"):
        # Honest 404 — caller can fall back to circular buffer and render the
        # ``explanation`` string so the user knows why there's no real polygon.
        raise HTTPException(
            status_code=404,
            detail={
                "error": "inspire_parcel_not_found",
                "inspire_id": inspire_id,
                "explanation": result.get("explanation"),
            },
        )

    geom = result.get("parcel_geom_geojson")
    feature = {
        "type": "Feature",
        "geometry": geom,
        "properties": {
            "inspire_id": result["inspire_id"],
            "parcel_area_ha": result.get("parcel_area_ha"),
            "centroid": result.get("centroid"),
        },
    }
    from datetime import datetime as _dt
    return {
        "type": "FeatureCollection",
        "features": [feature] if geom else [],
        "inspire_id": result["inspire_id"],
        "parcel_area_ha": result.get("parcel_area_ha"),
        "centroid": result.get("centroid"),
        "provenance": {
            "data_provenance": "db_snapshot",
            "last_refreshed_utc": _dt.utcnow().isoformat(timespec="seconds") + "Z",
            "reason": (
                "HMLR INSPIRE index polygon (OGL-licensed monthly publication). "
                "Title number requires paid HMLR Official Copy lookup."
            ),
        },
        "explanation": result.get("explanation"),
    }


@router.get("/api/parcels/{inspire_id}/geometry")
async def parcel_inspire_geometry(
    inspire_id: str = Path(..., description="HMLR INSPIRE parcel id"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return the HMLR INSPIRE polygon for ``inspire_id`` as a GeoJSON
    FeatureCollection (single Feature). Used by DesignCanvas to draw the
    real parcel boundary instead of a circular proxy.

    Returns 404 if the id is unknown or the HMLR table is not yet ingested,
    with an ``explanation`` string so the caller can render a honest fallback.
    """
    return await _inspire_geometry_response(inspire_id, pool)


@router.get("/api/parcel/{inspire_id}/geometry")
async def parcel_inspire_geometry_singular(
    inspire_id: str = Path(..., description="HMLR INSPIRE parcel id"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Alias under the existing ``/api/parcel/{id}`` prefix for backward
    compatibility with clients that used the singular path."""
    return await _inspire_geometry_response(inspire_id, pool)
