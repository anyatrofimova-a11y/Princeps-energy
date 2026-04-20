"""EPC (Energy Performance Certificate) lookup via the EPC Register Open Data API.

Endpoint: https://epc.opendatacommunities.org/api/v1/domestic/search

Auth: HTTP Basic — user = the registered email, password = the API token
(here combined as base64("<email>:<token>")).  We expect a single
``EPC_API_KEY`` env var in the form ``<email>:<token>``.  If unset we return
an empty list plus a TODO.

Strategy:
    1. Resolve the postcode from postcodes.io (postcode.lookup) — cheapest
       proxy for "certificates near this point"; EPC's API doesn't accept
       lat/lon natively but it does accept postcode filter.
    2. Pull up to ``size`` certificates in that postcode.
    3. Score by crude Haversine distance to the supplied lat/lon; drop
       anything > 250 m.

Rate-limit: 2 req/s (we enforce a 500 ms floor between calls).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import math
import os
import time
from typing import Any, Optional

import httpx

log = logging.getLogger("princeps.site_enrichment.epc")

_ENDPOINT = "https://epc.opendatacommunities.org/api/v1/domestic/search"
_HTTP_TIMEOUT = 3.0
_RADIUS_M = 250
_SIZE = 25

_MIN_GAP_S = 0.5  # 2 req/s
_last_launch = 0.0
_gap_lock = asyncio.Lock()


async def _throttle() -> None:
    global _last_launch
    async with _gap_lock:
        now = time.monotonic()
        wait = _MIN_GAP_S - (now - _last_launch)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_launch = time.monotonic()


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


async def lookup(
    lat: float,
    lon: float,
    *,
    postcode: Optional[str] = None,
    limit: int = 5,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Return up to ``limit`` EPC certificates within 250 m of (lat, lon)."""
    key = os.environ.get("EPC_API_KEY")
    if not key:
        return {
            "certificates": [],
            "todo": "Set EPC_API_KEY env var (email:token from epc.opendatacommunities.org).",
        }

    if not postcode:
        return {
            "certificates": [],
            "todo": "EPC search requires a postcode — postcode sub-enricher must run first.",
        }

    owns = client is None
    if owns:
        client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True)

    try:
        await _throttle()
        auth = base64.b64encode(key.encode()).decode()
        r = await client.get(
            _ENDPOINT,
            params={"postcode": postcode, "size": _SIZE},
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {auth}",
            },
        )
        if r.status_code in (401, 403):
            raise ValueError(f"epc auth rejected ({r.status_code})")
        r.raise_for_status()
        payload = r.json() or {}
        rows = payload.get("rows") or []
    except httpx.HTTPError as exc:
        raise ValueError(f"epc: {exc}") from exc
    finally:
        if owns:
            await client.aclose()

    results: list[dict[str, Any]] = []
    for row in rows:
        lat2 = row.get("latitude")
        lon2 = row.get("longitude")
        if lat2 is None or lon2 is None:
            continue
        try:
            d = _haversine_m(lat, lon, float(lat2), float(lon2))
        except Exception:
            continue
        if d > _RADIUS_M:
            continue
        results.append({
            "lmk_key": row.get("lmk-key") or row.get("lmk_key"),
            "rating": row.get("current-energy-rating") or row.get("current_energy_rating"),
            "floor_area_m2": row.get("total-floor-area") or row.get("total_floor_area"),
            "inspection_date": row.get("inspection-date") or row.get("inspection_date"),
            "address": row.get("address"),
            "distance_m": round(d, 1),
        })
    results.sort(key=lambda x: x.get("distance_m") or 0.0)
    return {"certificates": results[:limit]}
