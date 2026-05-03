"""DC Design auxiliary endpoints — placement intelligence for the
DC Design Twin canvas.

Currently exposes:
  GET /api/dc-design/forbidden-zones — OSM building footprints within a
       radius around a point. Used by the frontend constraint overlay
       to paint existing buildings red ("you cannot place here") so the
       auto-layout / drag UX can deconflict against real ground truth.

Future:
  GET /api/dc-design/cost-map — per-cell placement cost (forbidden /
       penalised / preferred) baked from buildings + roads + DEM slope.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

log = logging.getLogger("princeps.dc_design")

router = APIRouter(prefix="/api/dc-design", tags=["dc-design"])

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


@router.get("/forbidden-zones")
async def forbidden_zones(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(400, ge=50, le=2000),
):
    """Return OSM building footprints within `radius_m` of (lat, lng)
    as GeoJSON FeatureCollection. Each feature is a `Polygon` with
    properties: {osm_id, building, height, levels}.

    Cached by Overpass for ~24h on their side; we don't cache locally.
    """
    # Build a small bbox from radius (rough — 1° lat ≈ 111 km).
    deg_per_metre = 1.0 / 111_000
    dlat = radius_m * deg_per_metre
    dlng = radius_m * deg_per_metre / max(0.1, abs(_cos_deg(lat)))
    bbox = (lat - dlat, lng - dlng, lat + dlat, lng + dlng)

    query = f"""
        [out:json][timeout:20];
        (
          way["building"]({bbox[0]:.6f},{bbox[1]:.6f},{bbox[2]:.6f},{bbox[3]:.6f});
          relation["building"]({bbox[0]:.6f},{bbox[1]:.6f},{bbox[2]:.6f},{bbox[3]:.6f});
        );
        out geom;
    """.strip()

    last_err: str | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                r = await client.post(endpoint, data={"data": query})
                if r.status_code != 200:
                    last_err = f"{endpoint}: HTTP {r.status_code}"
                    continue
                payload = r.json()
                features = _osm_to_geojson_buildings(payload)
                return {
                    "type": "FeatureCollection",
                    "features": features,
                    "metadata": {
                        "lat": lat, "lng": lng, "radius_m": radius_m,
                        "bbox": list(bbox),
                        "source": endpoint,
                        "feature_count": len(features),
                    },
                }
        except Exception as exc:
            last_err = f"{endpoint}: {type(exc).__name__}: {exc}"
            log.warning("overpass attempt failed: %s", last_err)
            continue

    raise HTTPException(502, f"Overpass unavailable: {last_err}")


def _cos_deg(deg: float) -> float:
    import math
    return math.cos(math.radians(deg))


def _osm_to_geojson_buildings(payload: dict[str, Any]) -> list[dict]:
    """Convert OSM Overpass `out geom` response into GeoJSON Polygon features."""
    features: list[dict] = []
    for elem in payload.get("elements", []):
        if elem.get("type") == "way" and elem.get("geometry"):
            coords = [[pt["lon"], pt["lat"]] for pt in elem["geometry"]]
            if len(coords) < 3:
                continue
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            features.append({
                "type": "Feature",
                "id": elem["id"],
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": {
                    "osm_id": elem["id"],
                    "building": (elem.get("tags") or {}).get("building"),
                    "height": _to_float((elem.get("tags") or {}).get("height")),
                    "levels": _to_float((elem.get("tags") or {}).get("building:levels")),
                    "name": (elem.get("tags") or {}).get("name"),
                },
            })
        elif elem.get("type") == "relation" and elem.get("members"):
            outer_rings: list[list[list[float]]] = []
            for m in elem["members"]:
                if m.get("role") == "outer" and m.get("geometry"):
                    ring = [[pt["lon"], pt["lat"]] for pt in m["geometry"]]
                    if len(ring) >= 3:
                        if ring[0] != ring[-1]:
                            ring.append(ring[0])
                        outer_rings.append(ring)
            if outer_rings:
                features.append({
                    "type": "Feature",
                    "id": elem["id"],
                    "geometry": {"type": "MultiPolygon",
                                 "coordinates": [[r] for r in outer_rings]},
                    "properties": {
                        "osm_id": elem["id"],
                        "building": (elem.get("tags") or {}).get("building"),
                        "name": (elem.get("tags") or {}).get("name"),
                    },
                })
    return features


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).rstrip("m").strip())
    except (ValueError, TypeError):
        return None
