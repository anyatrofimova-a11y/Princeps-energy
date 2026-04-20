"""5-year LPA planning-history lookup around a parcel centroid.

Preferred source is the PlanIt API (https://www.planit.org.uk/api/).
If the network call fails or returns nothing, falls back to the local
``planning_applications`` table (from BOT-Planning ingestion) so dev /
offline environments still render rows in the drawer.

Returns at most ``limit`` records, each shaped as:

    {
        "ref": "24/01234/FUL",
        "address": "Land at ...",
        "description": "Erection of solar PV array ...",
        "status": "approved" | "refused" | "pending" | ...,
        "decision_date": "2025-06-14" | None,
        "officer_report_url": "https://...",
        "distance_m": 340.5,
        "applicant": "...",
        "source": "planit" | "local"
    }
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

import asyncpg

log = logging.getLogger("princeps.parcel.planning_history")

# Lazy-imported httpx — keep module import cheap.
_HTTPX = None


def _get_httpx():
    global _HTTPX  # noqa: PLW0603
    if _HTTPX is None:
        try:
            import httpx  # type: ignore

            _HTTPX = httpx
        except ImportError:
            _HTTPX = False
    return _HTTPX


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


async def _planit_lookup(
    lat: float, lon: float, radius_m: int, years: int, limit: int
) -> list[dict[str, Any]]:
    httpx = _get_httpx()
    if not httpx:
        return []

    radius_km = max(radius_m / 1000.0, 0.1)
    url = "https://www.planit.org.uk/api/applics/json"
    params = {
        "pg_sz": str(limit),
        "select": "all",
        "recent": f"{years} years",
        "near": f"{lat},{lon}",
        "krad": f"{radius_km:.3f}",
    }
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.debug("planit lookup failed: %s", exc)
        return []

    records = data.get("records") if isinstance(data, dict) else None
    if not records:
        return []

    rows: list[dict[str, Any]] = []
    for rec in records[:limit]:
        try:
            r_lat = float(rec.get("lat") or 0.0)
            r_lon = float(rec.get("lng") or 0.0)
            distance = _haversine_m(lat, lon, r_lat, r_lon) if r_lat and r_lon else None
        except (TypeError, ValueError):
            distance = None

        rows.append(
            {
                "ref": rec.get("reference") or rec.get("name"),
                "address": rec.get("address") or rec.get("location"),
                "description": (rec.get("description") or "")[:400],
                "status": (rec.get("app_state") or rec.get("status") or "pending").lower(),
                "decision_date": rec.get("decided"),
                "officer_report_url": rec.get("url"),
                "distance_m": round(distance, 1) if distance else None,
                "applicant": rec.get("agent") or rec.get("applicant"),
                "source": "planit",
            }
        )
    return rows


async def _local_lookup(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    radius_m: int,
    years: int,
    limit: int,
) -> list[dict[str, Any]]:
    try:
        exists = await conn.fetchval(
            "SELECT to_regclass('public.planning_applications') IS NOT NULL"
        )
    except Exception:  # noqa: BLE001
        return []
    if not exists:
        return []

    try:
        rows = await conn.fetch(
            f"""
            SELECT ref,
                   address,
                   description,
                   status,
                   decision_date,
                   officer_report_url,
                   applicant,
                   ST_Distance(
                       geom::geography,
                       ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                   ) AS distance_m
              FROM planning_applications
             WHERE ST_DWithin(
                       geom::geography,
                       ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                       $3
                   )
               AND (decision_date IS NULL OR decision_date >= NOW() - INTERVAL '{int(years)} years')
             ORDER BY distance_m ASC
             LIMIT $4
            """,
            lon,
            lat,
            radius_m,
            limit,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("local planning_applications query failed: %s", exc)
        return []

    return [
        {
            "ref": r["ref"],
            "address": r["address"],
            "description": (r["description"] or "")[:400],
            "status": r["status"],
            "decision_date": r["decision_date"].isoformat() if r["decision_date"] else None,
            "officer_report_url": r["officer_report_url"],
            "distance_m": round(float(r["distance_m"]), 1) if r["distance_m"] else None,
            "applicant": r["applicant"],
            "source": "local",
        }
        for r in rows
    ]


async def planning_history(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    *,
    radius_m: int = 500,
    years: int = 5,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Return planning apps within ``radius_m`` in the last ``years`` years."""

    # Race PlanIt + local together; prefer PlanIt when non-empty.
    tasks = [
        _planit_lookup(lat, lon, radius_m, years, limit),
        _local_lookup(conn, lat, lon, radius_m, years, limit),
    ]
    results: list[list[dict[str, Any]]] = []
    try:
        results = await asyncio.gather(*tasks, return_exceptions=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("planning_history gather failed: %s", exc)
        return []

    planit_rows, local_rows = results
    if planit_rows:
        return planit_rows[:limit]
    return local_rows[:limit]
