"""
Land registry & property rights overlay.

Sources:
- HM Land Registry INSPIRE Index Polygons (free, CC-BY)
  WFS: https://inspire.landregistry.gov.uk/inspire/ows
  Freehold + leasehold polygon boundaries with title numbers

- Agricultural Land Classification (Natural England open data)

- Commercial property listings (MVP: synthetic; prod: Rightmove/Savills API)
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

import httpx

log = logging.getLogger("princeps.land_registry")

# ── Cache ──
_parcel_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 300  # 5 min

INSPIRE_WFS = "https://inspire.landregistry.gov.uk/inspire/ows"


def _cache_key(bbox: tuple) -> str:
    # Round to 0.01° grid for cache hits
    return f"{bbox[0]:.2f},{bbox[1]:.2f},{bbox[2]:.2f},{bbox[3]:.2f}"


async def get_land_parcels(bbox: tuple, *, min_area_ha: float = 0.5, max_features: int = 200) -> dict:
    """
    Fetch HM Land Registry INSPIRE polygons for a bounding box.

    Returns GeoJSON FeatureCollection with freehold + leasehold parcels.
    Each feature has: title_number, tenure, area_ha, color, available flag.
    """
    key = _cache_key(bbox)
    now = time.time()
    if key in _parcel_cache:
        ts, data = _parcel_cache[key]
        if now - ts < CACHE_TTL:
            return data

    west, south, east, north = bbox
    all_features = []

    async with httpx.AsyncClient(timeout=15) as client:
        for tenure in ("freehold", "leasehold"):
            try:
                params = {
                    "service": "WFS",
                    "version": "2.0.0",
                    "request": "GetFeature",
                    "typeNames": f"inspire:{tenure}",
                    "outputFormat": "application/json",
                    "bbox": f"{south},{west},{north},{east},urn:ogc:def:crs:EPSG::4326",
                    "count": str(max_features),
                }
                resp = await client.get(INSPIRE_WFS, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    features = data.get("features", [])
                    for f in features:
                        props = f.get("properties", {})
                        # Calculate area from geometry
                        area_ha = _polygon_area_ha(f.get("geometry"))
                        if area_ha < min_area_ha:
                            continue

                        f["properties"] = {
                            "title_number": props.get("TITLE_NO") or props.get("title_no") or props.get("inspireid", ""),
                            "tenure": tenure,
                            "area_ha": round(area_ha, 2),
                            "color": "#2563eb" if tenure == "freehold" else "#ea580c",
                            "available": area_ha >= 2.0,  # Flag larger parcels as potentially available
                            "poly_id": props.get("POLY_ID") or props.get("poly_id", ""),
                        }
                        all_features.append(f)
                else:
                    log.debug("INSPIRE WFS %s returned %s", tenure, resp.status_code)
            except Exception as e:
                log.warning("INSPIRE WFS fetch failed for %s: %s", tenure, e)

    result = {
        "type": "FeatureCollection",
        "features": all_features,
        "metadata": {
            "total": len(all_features),
            "freehold": sum(1 for f in all_features if f["properties"]["tenure"] == "freehold"),
            "leasehold": sum(1 for f in all_features if f["properties"]["tenure"] == "leasehold"),
            "source": "HM Land Registry INSPIRE",
        },
    }

    _parcel_cache[key] = (now, result)
    return result


async def get_agricultural_land_class(lat: float, lon: float) -> dict:
    """
    Get Agricultural Land Classification grade at a point.

    MVP: Uses approximate regional grades based on known UK patterns.
    Production: Query Natural England ALC dataset WMS/WFS.
    """
    # Approximate ALC grades by latitude bands (England)
    # Grade 1 = excellent, Grade 5 = very poor
    if lat > 54.5:
        grade, desc = "4", "Poor quality agricultural land"
    elif lat > 53.0:
        grade, desc = "3b", "Moderate quality agricultural land"
    elif lat > 52.0:
        grade, desc = "3a", "Good quality agricultural land"
    elif lat > 51.5:
        grade, desc = "2", "Very good quality agricultural land"
    else:
        grade, desc = "3a", "Good quality agricultural land"

    # East Anglia / Fens = Grade 1
    if 52.0 < lat < 53.0 and 0 < lon < 1.5:
        grade, desc = "1", "Excellent quality agricultural land"

    suitable = grade in ("3b", "4", "5")  # Only lower-grade land suitable for development

    return {
        "grade": grade,
        "description": desc,
        "suitable_for_development": suitable,
        "note": "Best and Most Versatile (BMV) land (grades 1, 2, 3a) has planning restrictions" if not suitable else "Non-BMV land — fewer planning restrictions for development",
    }


async def search_commercial_listings(
    lat: float, lon: float, *, radius_km: float = 10, land_type: str = None
) -> list[dict]:
    """
    Search commercial/agricultural land listings near a point.

    MVP: Returns synthetic listings based on typical UK land market patterns.
    Production: Would integrate Rightmove Commercial, Savills, Knight Frank APIs.
    """
    import random

    # Seed based on location for consistent results
    rng = random.Random(int(lat * 1000) + int(lon * 1000))

    types = ["agricultural", "commercial", "brownfield", "solar_opportunity"]
    if land_type:
        types = [land_type]

    listings = []
    for i in range(rng.randint(3, 8)):
        t = rng.choice(types)
        area = rng.uniform(1, 50) if t == "agricultural" else rng.uniform(0.5, 10)
        price_per_ha = {
            "agricultural": rng.uniform(18000, 35000),
            "commercial": rng.uniform(200000, 800000),
            "brownfield": rng.uniform(100000, 500000),
            "solar_opportunity": rng.uniform(25000, 60000),
        }[t]

        offset_lat = rng.uniform(-radius_km / 111, radius_km / 111)
        offset_lon = rng.uniform(-radius_km / 80, radius_km / 80)

        listings.append({
            "id": f"listing-{i}-{int(lat*100)}-{int(lon*100)}",
            "title": f"{area:.1f} ha {t.replace('_', ' ').title()} Land",
            "price_gbp": int(area * price_per_ha),
            "price_per_ha_gbp": int(price_per_ha),
            "area_ha": round(area, 1),
            "lat": round(lat + offset_lat, 5),
            "lon": round(lon + offset_lon, 5),
            "type": t,
            "source": "Princeps Market Intelligence",
            "description": _listing_desc(t, area, rng),
            "available": True,
        })

    listings.sort(key=lambda x: x["price_per_ha_gbp"])
    return listings


def _listing_desc(land_type: str, area: float, rng) -> str:
    descs = {
        "agricultural": [
            f"Arable farmland, {area:.0f} ha with road access. Grade 3b ALC.",
            f"Pasture land suitable for solar development. Good grid proximity.",
            f"Mixed-use agricultural holding. Option agreement available.",
        ],
        "commercial": [
            f"Former industrial site with utilities. Planning-ready.",
            f"Serviced development plot near major substation.",
        ],
        "brownfield": [
            f"Previously developed land, remediated. Outline planning granted.",
            f"Former quarry site with level ground. Excellent for BESS/solar.",
        ],
        "solar_opportunity": [
            f"Land agent marketing for solar farm development. Lease available.",
            f"Landowner seeking solar development partner. 25yr lease terms.",
            f"Pre-screened site — grid connection feasible, planning likely.",
        ],
    }
    return rng.choice(descs.get(land_type, ["Development land available."]))


def _polygon_area_ha(geometry: dict | None) -> float:
    """Approximate area of a GeoJSON polygon in hectares using the Shoelace formula."""
    if not geometry:
        return 0
    coords = geometry.get("coordinates")
    if not coords or not coords[0]:
        return 0
    ring = coords[0]
    if len(ring) < 3:
        return 0

    # Shoelace formula in approximate meters
    lat_mid = sum(p[1] for p in ring) / len(ring)
    m_per_deg_lat = 111320
    m_per_deg_lon = 111320 * math.cos(math.radians(lat_mid))

    area_m2 = 0
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        x1 = ring[i][0] * m_per_deg_lon
        y1 = ring[i][1] * m_per_deg_lat
        x2 = ring[j][0] * m_per_deg_lon
        y2 = ring[j][1] * m_per_deg_lat
        area_m2 += x1 * y2 - x2 * y1

    return abs(area_m2) / 2 / 10000  # m² to hectares
