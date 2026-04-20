"""postcodes.io reverse geocode — free, unauthenticated, UK only.

Returns a flat dict:
    {
      "postcode": "SW1A 1AA",
      "lsoa": "Westminster 018C",
      "msoa": "Westminster 018",
      "country": "England",
      "parish": "Westminster, unparished area",
      "admin_district": "Westminster",
      "admin_ward": "St James's",
      "admin_county": None,
    }

Rate-limit: postcodes.io asks for <10 req/s — a process-wide asyncio.Semaphore
caps concurrent calls at 10 and enforces a 100 ms floor between launches.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import httpx

log = logging.getLogger("princeps.site_enrichment.postcode")

BASE = "https://api.postcodes.io"
USER_AGENT = "Princeps/1.0 site-enrichment"
HTTP_TIMEOUT = 2.5  # must be well inside 800 ms per-call budget minus network

# Keep well below the published 10 req/s ceiling.
_MAX_CONCURRENCY = 8
_MIN_GAP_S = 0.1

_semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
_last_launch = 0.0
_gap_lock = asyncio.Lock()


async def _throttle() -> None:
    """Enforce a ≥100 ms spacing between outbound calls."""
    global _last_launch
    async with _gap_lock:
        now = time.monotonic()
        wait = _MIN_GAP_S - (now - _last_launch)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_launch = time.monotonic()


async def lookup(
    lat: float,
    lon: float,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Reverse-geocode (lat, lon) → nearest UK postcode + admin attributes.

    Raises ``ValueError`` with a short reason on network / decoding failure;
    the caller wraps errors into ``errors[]`` so the endpoint never 500s.
    """
    owns = client is None
    if owns:
        client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    try:
        await _throttle()
        async with _semaphore:
            url = f"{BASE}/postcodes"
            r = await client.get(url, params={"lon": lon, "lat": lat, "limit": 1, "radius": 2000})
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        payload = r.json() or {}
        results = payload.get("result") or []
        if not results:
            return {}
        top = results[0]
        return {
            "postcode": top.get("postcode"),
            "lsoa": top.get("lsoa"),
            "msoa": top.get("msoa"),
            "country": top.get("country"),
            "parish": top.get("parish"),
            "admin_district": top.get("admin_district"),
            "admin_ward": top.get("admin_ward"),
            "admin_county": top.get("admin_county"),
            "parliamentary_constituency": top.get("parliamentary_constituency"),
            "eastings": top.get("eastings"),
            "northings": top.get("northings"),
            "distance_m": top.get("distance"),
        }
    except (httpx.HTTPError, ValueError) as exc:
        raise ValueError(f"postcodes.io: {exc}") from exc
    finally:
        if owns:
            await client.aclose()
