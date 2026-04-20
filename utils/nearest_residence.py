"""Nearest-residence lookup for noise / setback checks.

We do not hold a Royal Mail PAF licence, so we fall back to OpenStreetMap's
``building=residential|dormitory|apartments|house|detached|semidetached_house``
tags via the Overpass API. This is good enough for a first-pass setback check
(WHO noise guidance + NPS EN-1 residential amenity) but the provenance block
flags that upstream coverage is non-authoritative.

The module is intentionally dependency-light — it reuses the HTTP client and
``_USER_AGENT`` pattern from ``utils/grid_data_ingester.py`` (Overpass) but does
NOT import it to avoid circular dependencies when the grid ingester is busy.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("princeps.nearest_residence")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_USER_AGENT = "Princeps/1.0 nearest-residence"
_TIMEOUT = 45.0

# OSM building tag values we treat as "sensitive residential receptors".
_RESIDENTIAL_TAGS = {
    "residential", "apartments", "dormitory", "house", "detached",
    "semidetached_house", "terrace", "bungalow", "static_caravan",
    "farm", "farmhouse", "cabin",
}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    r = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _build_query(lat: float, lon: float, radius_m: float) -> str:
    """Overpass QL: residential buildings within radius of (lat,lon)."""
    tag_regex = "|".join(sorted(_RESIDENTIAL_TAGS))
    return f"""
    [out:json][timeout:45];
    (
      node["building"~"^({tag_regex})$"](around:{radius_m:.0f},{lat:.6f},{lon:.6f});
      way["building"~"^({tag_regex})$"](around:{radius_m:.0f},{lat:.6f},{lon:.6f});
      relation["building"~"^({tag_regex})$"](around:{radius_m:.0f},{lat:.6f},{lon:.6f});
    );
    out center tags;
    """


def _centroid(el: dict[str, Any]) -> tuple[float, float] | None:
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def _label(tags: dict[str, str], building: str) -> str:
    name = tags.get("name")
    addr = tags.get("addr:housename") or tags.get("addr:full")
    street = tags.get("addr:street")
    house = tags.get("addr:housenumber")
    addr_parts = [p for p in (house, street) if p]
    if name:
        return name
    if addr:
        return addr
    if addr_parts:
        return " ".join(addr_parts)
    return f"OSM {building}".title()


async def nearest_residence(
    lat: float,
    lon: float,
    radius_m: float = 500.0,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Return the nearest residential OSM receptor to (lat, lon).

    Response shape::
        {
          "feature": { "type": "Feature", "geometry": {...}, "properties": {...} }
              or None,
          "distance_m": 412.3,
          "count_within_radius": 27,
          "radius_m": 500,
          "provenance": {
              "data_provenance": "osm",
              "last_refreshed_utc": "2026-04-19T12:00:00Z",
              "reason": "OSM building tags (no Royal Mail PAF licence).",
          },
          "explanation": "Nearest receptor 412 m E — flagged from OSM ...",
        }

    Never raises — if Overpass fails we return ``feature=None`` and a
    synthetic_fallback provenance so the caller can render an honest
    "upstream unavailable" string instead of fabricating a receptor.
    """
    radius_m = max(50.0, min(float(radius_m), 5000.0))
    query = _build_query(lat, lon, radius_m)
    owned_client = False
    if client is None:
        client = httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}
        )
        owned_client = True

    elements: list[dict[str, Any]] = []
    warning: str | None = None
    try:
        r = await client.post(OVERPASS_URL, data={"data": query})
        r.raise_for_status()
        elements = (r.json() or {}).get("elements", []) or []
    except Exception as exc:  # noqa: BLE001
        warning = f"overpass unavailable: {type(exc).__name__}"
        log.info("nearest_residence overpass failed: %s", exc)
    finally:
        if owned_client:
            await client.aclose()

    if warning or not elements:
        return {
            "feature": None,
            "distance_m": None,
            "count_within_radius": 0,
            "radius_m": radius_m,
            "provenance": {
                "data_provenance": "synthetic_fallback" if warning else "osm",
                "last_refreshed_utc": _utcnow_iso(),
                "reason": warning or (
                    f"No OSM residential buildings tagged within {radius_m:.0f} m. "
                    "May be farmland / industrial — treat as low-receptor-density but "
                    "confirm with a site-walk, OSM coverage is non-authoritative."
                ),
            },
            "explanation": (
                "Nearest-residence lookup unavailable: upstream Overpass API did not respond."
                if warning else
                f"No residential OSM receptors within {radius_m:.0f} m. "
                "OSM is community-mapped — absence is not proof; confirm with a walkover."
            ),
        }

    best: dict[str, Any] | None = None
    best_dist = float("inf")
    for el in elements:
        c = _centroid(el)
        if c is None:
            continue
        d = _haversine_m(lat, lon, c[0], c[1])
        if d < best_dist:
            best_dist = d
            best = {"element": el, "lat": c[0], "lon": c[1], "distance_m": d}

    if best is None:
        return {
            "feature": None,
            "distance_m": None,
            "count_within_radius": 0,
            "radius_m": radius_m,
            "provenance": {
                "data_provenance": "osm",
                "last_refreshed_utc": _utcnow_iso(),
                "reason": "Overpass returned elements with no resolvable geometry.",
            },
            "explanation": (
                "OSM returned building records with no coordinates — treat as "
                "no receptor found and confirm via site-walk."
            ),
        }

    tags = best["element"].get("tags") or {}
    building = tags.get("building", "residential")
    label = _label(tags, building)

    # Bearing E/N/W/S for the explanation string.
    dlat = best["lat"] - lat
    dlon = best["lon"] - lon
    bearing_deg = (math.degrees(math.atan2(dlon, dlat)) + 360.0) % 360.0
    compass = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((bearing_deg + 22.5) // 45) % 8]

    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [best["lon"], best["lat"]]},
        "properties": {
            "osm_id": best["element"].get("id"),
            "osm_type": best["element"].get("type"),
            "building": building,
            "label": label,
            "tags": {k: v for k, v in tags.items()
                     if k in ("name", "addr:housename", "addr:housenumber",
                              "addr:street", "building:levels", "source")},
            "distance_m": round(best_dist, 1),
            "bearing_deg": round(bearing_deg, 1),
            "bearing_compass": compass,
        },
    }

    return {
        "feature": feature,
        "distance_m": round(best_dist, 1),
        "count_within_radius": len(elements),
        "radius_m": radius_m,
        "provenance": {
            "data_provenance": "osm",
            "last_refreshed_utc": _utcnow_iso(),
            "reason": (
                "OpenStreetMap building tags (no Royal Mail PAF licence held). "
                "Sufficient for first-pass setback — confirm with a walkover."
            ),
        },
        "explanation": (
            f"Nearest residential receptor: {label} at {best_dist:.0f} m {compass} "
            f"({len(elements)} residential buildings within {radius_m:.0f} m). "
            "Source: OSM — not authoritative, confirm before planning submission."
        ),
    }
