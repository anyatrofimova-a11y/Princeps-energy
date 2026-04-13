"""Fiber & Connectivity Assessment for DC siting."""

from __future__ import annotations
import math
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)
_TIMEOUT = httpx.Timeout(15.0)


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))


async def find_nearest_ixps(lat: float, lon: float, limit: int = 10) -> list[dict]:
    """Find nearest Internet Exchange Points via PeeringDB."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get("https://www.peeringdb.com/api/ix", params={"limit": 500, "depth": 0})
            data = r.json().get("data", [])

        ixps = []
        for ix in data:
            if not ix.get("fac_set"):
                continue
            # Use facility location as proxy
            ix_lat = ix.get("latitude") or ix.get("fac_set", [{}])[0].get("latitude")
            ix_lon = ix.get("longitude") or ix.get("fac_set", [{}])[0].get("longitude")
            if not ix_lat or not ix_lon:
                continue

            dist = _haversine(lat, lon, float(ix_lat), float(ix_lon))
            ixps.append({
                "name": ix.get("name", "Unknown"),
                "city": ix.get("city", ""),
                "country": ix.get("country", ""),
                "lat": float(ix_lat),
                "lon": float(ix_lon),
                "distance_km": round(dist, 1),
                "participants": ix.get("net_count", 0),
                "speed_gbps": ix.get("speed", 0),
            })

        ixps.sort(key=lambda x: x["distance_km"])
        return ixps[:limit]
    except Exception as e:
        log.warning("PeeringDB query failed: %s", e)
        # Fallback: major UK IXPs
        uk_ixps = [
            {"name": "LINX LON1", "city": "London", "lat": 51.5074, "lon": -0.1278, "participants": 950},
            {"name": "LINX LON2", "city": "London", "lat": 51.5155, "lon": -0.0922, "participants": 400},
            {"name": "LINX Manchester", "city": "Manchester", "lat": 53.4808, "lon": -2.2426, "participants": 120},
            {"name": "IXLeeds", "city": "Leeds", "lat": 53.8008, "lon": -1.5491, "participants": 45},
            {"name": "LONAP", "city": "London", "lat": 51.5185, "lon": -0.0861, "participants": 180},
        ]
        for ix in uk_ixps:
            ix["distance_km"] = round(_haversine(lat, lon, ix["lat"], ix["lon"]), 1)
            ix["country"] = "GB"
            ix["speed_gbps"] = 0
        uk_ixps.sort(key=lambda x: x["distance_km"])
        return uk_ixps[:limit]


async def find_fiber_routes(lat: float, lon: float, radius_km: float = 10) -> dict[str, Any]:
    """Find telecom fiber routes from OSM Overpass."""
    radius_m = int(radius_km * 1000)
    query = f"""[out:json][timeout:15];
(way["utility"="telecom"](around:{radius_m},{lat},{lon});
 way["man_made"="cable"](around:{radius_m},{lat},{lon});
 way["telecom"="cable"](around:{radius_m},{lat},{lon}););
out geom;"""

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post("https://overpass-api.de/api/interpreter", data={"data": query})
            data = r.json()

        features = []
        for el in data.get("elements", []):
            if el.get("type") != "way" or not el.get("geometry"):
                continue
            coords = [[p["lon"], p["lat"]] for p in el["geometry"]]
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "id": el["id"],
                    "operator": el.get("tags", {}).get("operator", "Unknown"),
                    "type": el.get("tags", {}).get("utility", "telecom"),
                },
            })

        return {
            "type": "FeatureCollection",
            "features": features,
            "stats": {"routes": len(features), "radius_km": radius_km},
        }
    except Exception as e:
        log.warning("Overpass fiber query failed: %s", e)
        return {"type": "FeatureCollection", "features": [], "stats": {"routes": 0, "radius_km": radius_km, "error": str(e)}}


async def score_connectivity(lat: float, lon: float, radius_km: float = 25) -> dict[str, Any]:
    """Compute connectivity score (0-100) for a location."""
    ixps = await find_nearest_ixps(lat, lon, limit=20)
    fiber = await find_fiber_routes(lat, lon, radius_km=10)

    nearest_ixp_km = ixps[0]["distance_km"] if ixps else 999
    ixp_within_25 = sum(1 for ix in ixps if ix["distance_km"] <= 25)
    ixp_within_50 = sum(1 for ix in ixps if ix["distance_km"] <= 50)
    fiber_routes = fiber["stats"]["routes"]

    # Scoring
    ixp_proximity = 30 if nearest_ixp_km < 5 else 20 if nearest_ixp_km < 10 else 10 if nearest_ixp_km < 25 else 5 if nearest_ixp_km < 50 else 0
    ixp_density = min(20, ixp_within_50 * 5)
    fiber_diversity = min(25, fiber_routes * 5)
    fiber_proximity = 25 if fiber_routes > 3 else 15 if fiber_routes > 1 else 10 if fiber_routes > 0 else 0

    score = ixp_proximity + ixp_density + fiber_diversity + fiber_proximity

    return {
        "score": min(100, score),
        "nearest_ixp_km": nearest_ixp_km,
        "nearest_ixp": ixps[0]["name"] if ixps else None,
        "ixp_count_25km": ixp_within_25,
        "ixp_count_50km": ixp_within_50,
        "fiber_routes_10km": fiber_routes,
        "breakdown": {"ixp_proximity": ixp_proximity, "ixp_density": ixp_density, "fiber_diversity": fiber_diversity, "fiber_proximity": fiber_proximity},
        "verdict": "GO" if score >= 60 else "CAUTION" if score >= 30 else "NO-GO",
        "ixps": ixps[:5],
    }
