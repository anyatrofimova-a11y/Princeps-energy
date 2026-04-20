"""UPRN / USRN / address-line resolution via OS Places API.

Activation
----------
Requires ``OS_PLACES_KEY`` environment variable.  If unset we return an empty
dict plus a structured TODO so the endpoint degrades gracefully rather than
erroring.  Production deployments should provision an OS Data Hub API key
with the Places API endpoint enabled.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

log = logging.getLogger("princeps.site_enrichment.uprn")

OS_PLACES_NEAREST = "https://api.os.uk/search/places/v1/nearest"
HTTP_TIMEOUT = 2.5


async def lookup(
    lat: float,
    lon: float,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Return the nearest UPRN to (lat, lon) or a TODO stub when no key is set.

    Structure::
        {
          "uprn": "100023336956",
          "usrn": "21500023",
          "address_line": "10 DOWNING STREET, LONDON, SW1A 2AA",
          "distance_m": 3.2,
        }
    """
    key = os.environ.get("OS_PLACES_KEY")
    if not key:
        return {
            "uprn": None,
            "usrn": None,
            "address_line": None,
            "todo": "Set OS_PLACES_KEY env var (OS Data Hub — Places API) to populate UPRN/USRN.",
        }

    owns = client is None
    if owns:
        client = httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True)
    try:
        # OS Places API expects BNG eastings / northings OR a lat/lon pair
        # via ``point`` (comma-separated).  We use EPSG:4326 via srs=WGS84.
        params = {
            "point": f"{lat},{lon}",
            "srs": "WGS84",
            "radius": 100,
            "output_srs": "WGS84",
            "key": key,
        }
        r = await client.get(OS_PLACES_NEAREST, params=params)
        if r.status_code == 404:
            return {"uprn": None, "usrn": None, "address_line": None,
                    "todo": "OS Places returned 404 (no address within 100 m)."}
        r.raise_for_status()
        payload = r.json() or {}
        results = payload.get("results") or []
        if not results:
            return {"uprn": None, "usrn": None, "address_line": None}
        dpa = (results[0] or {}).get("DPA") or {}
        return {
            "uprn": str(dpa.get("UPRN")) if dpa.get("UPRN") is not None else None,
            "usrn": str(dpa.get("USRN")) if dpa.get("USRN") is not None else None,
            "address_line": dpa.get("ADDRESS"),
            "distance_m": dpa.get("DISTANCE"),
        }
    except httpx.HTTPError as exc:
        raise ValueError(f"os_places: {exc}") from exc
    finally:
        if owns:
            await client.aclose()
