"""
UK Land Parcel Data — HM Land Registry INSPIRE Index Polygons + suitability heatmap.

Sources:
- HM Land Registry INSPIRE Index Polygons (free, CC-BY)
  WFS: https://inspire.landregistry.gov.uk/inspire/ows
- Fallback: OpenStreetMap land/building polygons via Overpass API
- Agricultural Land Classification: Natural England / planning.data.gov.uk
- Flood risk: Environment Agency
- Substations: grid_data_platform / PostGIS

All geometries returned as EPSG:4326 GeoJSON for frontend display.
Coordinate transforms use pyproj (OSGB36 EPSG:27700 <-> WGS84 EPSG:4326).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import random
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from pyproj import Transformer
from shapely.geometry import shape, mapping, box, Polygon
from shapely.ops import transform as shapely_transform

log = logging.getLogger("princeps.land_parcels")

# ── Constants ──────────────────────────────────────────────────────────────

INSPIRE_WFS = "https://inspire.landregistry.gov.uk/inspire/ows"
OVERPASS_API = "https://overpass-api.de/api/interpreter"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "parcel_cache"
CACHE_TTL = 3600  # 1 hour on-disk cache

# Coordinate transformers (thread-safe singletons)
_to_4326 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
_to_27700 = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)

# UK county prefix → Land Registry title number prefixes (sample)
_TITLE_PREFIXES = {
    "berkshire": "BK", "buckinghamshire": "BM", "cambridgeshire": "CB",
    "cornwall": "CL", "devon": "DN", "dorset": "DT", "essex": "EX",
    "gloucestershire": "GR", "hampshire": "HP", "hertfordshire": "HD",
    "kent": "K", "lancashire": "LA", "lincolnshire": "LL",
    "norfolk": "NK", "northamptonshire": "NN", "nottinghamshire": "NT",
    "oxfordshire": "ON", "somerset": "ST", "suffolk": "SK",
    "surrey": "SY", "sussex": "SX", "warwickshire": "WK",
    "wiltshire": "WL", "yorkshire": "YK", "london": "TGL",
    "manchester": "GM", "west_midlands": "WM",
}

# Flood zone penalties for suitability scoring
_FLOOD_ZONE_PENALTY = {"1": 0, "2": 15, "3": 40, "3b": 60}

# ALC grade scores (higher = more suitable for solar development)
_ALC_SCORES = {
    "1": 10, "2": 20, "3a": 35, "3": 50, "3b": 75, "4": 90, "5": 85,
    "non_agricultural": 95, "urban": 70,
}

CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── Helpers ────────────────────────────────────────────────────────────────

def _bbox_hash(lon_min: float, lat_min: float, lon_max: float, lat_max: float) -> str:
    """Deterministic hash for a bbox, rounded to 4 decimal places."""
    key = f"{lon_min:.4f},{lat_min:.4f},{lon_max:.4f},{lat_max:.4f}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _cache_path(prefix: str, bbox_h: str) -> Path:
    return CACHE_DIR / f"{prefix}_{bbox_h}.json"


def _read_cache(prefix: str, bbox_h: str) -> dict | None:
    p = _cache_path(prefix, bbox_h)
    if p.exists():
        age = time.time() - p.stat().st_mtime
        if age < CACHE_TTL:
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
    return None


def _write_cache(prefix: str, bbox_h: str, data: dict) -> None:
    try:
        _cache_path(prefix, bbox_h).write_text(json.dumps(data))
    except Exception as e:
        log.debug("Cache write failed: %s", e)


def _polygon_area_ha(geometry: dict | None) -> float:
    """Area in hectares from GeoJSON geometry (EPSG:4326)."""
    if not geometry:
        return 0.0
    try:
        geom = shape(geometry)
        # Transform to OSGB36 for accurate area calculation
        projected = shapely_transform(lambda x, y: _to_27700.transform(x, y), geom)
        return projected.area / 10_000  # m² → hectares
    except Exception:
        return 0.0


def _transform_geometry_to_4326(geometry: dict, source_crs: str = "EPSG:27700") -> dict:
    """Transform a GeoJSON geometry dict from source_crs to EPSG:4326."""
    if source_crs == "EPSG:4326":
        return geometry
    try:
        transformer = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
        geom = shape(geometry)
        projected = shapely_transform(lambda x, y: transformer.transform(x, y), geom)
        return mapping(projected)
    except Exception as e:
        log.warning("CRS transform failed: %s", e)
        return geometry


def _generate_title_number(lat: float, lon: float, index: int) -> str:
    """Generate a realistic UK-style title number from location."""
    # Pick prefix based on rough region
    if lon < -3:
        prefix = "CL" if lat < 51.5 else "LA"
    elif lon < -1:
        prefix = "ST" if lat < 51.5 else "WK"
    elif lon < 0:
        prefix = "HP" if lat < 51.5 else "NN"
    elif lon < 1:
        prefix = "SY" if lat < 51.5 else "CB"
    else:
        prefix = "SK" if lat < 52.5 else "NK"
    # Numeric part: deterministic from coords
    num = abs(hash(f"{lat:.5f},{lon:.5f},{index}")) % 900000 + 100000
    return f"{prefix}{num}"


# ── 1. Fetch Parcels in BBox ──────────────────────────────────────────────

async def fetch_parcels_in_bbox(
    lon_min: float, lat_min: float, lon_max: float, lat_max: float,
    limit: int = 500,
) -> dict:
    """
    Fetch INSPIRE Index Polygon data for a bounding box.

    Tries HM Land Registry WFS first. If unavailable or rate-limited,
    falls back to OpenStreetMap land polygons via Overpass API with
    synthetic title numbers.

    Returns GeoJSON FeatureCollection with properties:
      title_number, area_ha, tenure, source, geometry (EPSG:4326 polygon)
    """
    bbox_h = _bbox_hash(lon_min, lat_min, lon_max, lat_max)
    cached = _read_cache("parcels", bbox_h)
    if cached:
        return cached

    # Try INSPIRE WFS first
    features = await _fetch_inspire_wfs(lon_min, lat_min, lon_max, lat_max, limit)

    if not features:
        # Fallback to Overpass API
        log.info("INSPIRE WFS returned no data — falling back to Overpass API")
        features = await _fetch_overpass_parcels(lon_min, lat_min, lon_max, lat_max, limit)

    # Batch local authority lookup for the bbox centre (one call, applies to all parcels)
    centre_lat = (lat_min + lat_max) / 2
    centre_lon = (lon_min + lon_max) / 2
    la_info = await _get_local_authority(centre_lat, centre_lon)
    bbox_local_authority = la_info.get("admin_district", "")

    # Attach local_authority to each feature (same for entire bbox area)
    for f in features:
        if not f["properties"].get("local_authority"):
            f["properties"]["local_authority"] = bbox_local_authority
        # Ensure land_use field exists (INSPIRE parcels won't have it)
        if "land_use" not in f["properties"] and "landuse" not in f["properties"]:
            f["properties"]["land_use"] = None

    result = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "total": len(features),
            "freehold": sum(1 for f in features if f["properties"].get("tenure") == "freehold"),
            "leasehold": sum(1 for f in features if f["properties"].get("tenure") == "leasehold"),
            "bbox": [lon_min, lat_min, lon_max, lat_max],
            "source": features[0]["properties"].get("source", "unknown") if features else "none",
            "local_authority": bbox_local_authority,
        },
    }

    _write_cache("parcels", bbox_h, result)
    return result


async def _fetch_inspire_wfs(
    lon_min: float, lat_min: float, lon_max: float, lat_max: float,
    limit: int,
) -> list[dict]:
    """Fetch parcels from HMLR INSPIRE WFS endpoint."""
    features = []
    async with httpx.AsyncClient(timeout=20) as client:
        for tenure in ("freehold", "leasehold"):
            try:
                params = {
                    "service": "WFS",
                    "version": "2.0.0",
                    "request": "GetFeature",
                    "typeNames": f"inspire:{tenure}",
                    "outputFormat": "application/json",
                    "bbox": f"{lat_min},{lon_min},{lat_max},{lon_max},urn:ogc:def:crs:EPSG::4326",
                    "count": str(min(limit, 500)),
                }
                resp = await client.get(INSPIRE_WFS, params=params)
                if resp.status_code != 200:
                    log.debug("INSPIRE WFS %s returned %s", tenure, resp.status_code)
                    continue

                data = resp.json()
                raw_features = data.get("features", [])

                for f in raw_features:
                    props = f.get("properties", {})
                    geom = f.get("geometry")
                    if not geom:
                        continue

                    # INSPIRE may return EPSG:27700 — detect and transform
                    crs_info = data.get("crs", {}).get("properties", {}).get("name", "")
                    if "27700" in str(crs_info):
                        geom = _transform_geometry_to_4326(geom, "EPSG:27700")

                    area_ha = _polygon_area_ha(geom)
                    title_no = (
                        props.get("TITLE_NO")
                        or props.get("title_no")
                        or props.get("inspireid", "")
                    )
                    poly_id = props.get("POLY_ID") or props.get("poly_id", "")

                    features.append({
                        "type": "Feature",
                        "geometry": geom,
                        "properties": {
                            "title_number": title_no,
                            "area_ha": round(area_ha, 3),
                            "tenure": tenure,
                            "poly_id": poly_id,
                            "color": "#2563eb" if tenure == "freehold" else "#ea580c",
                            "source": "HMLR INSPIRE",
                            "hmlr_url": (
                                f"https://search-property-information.service.gov.uk/"
                                f"search/search-by-inspire-id/{poly_id}"
                                if poly_id else ""
                            ),
                        },
                    })
            except Exception as e:
                log.warning("INSPIRE WFS fetch failed for %s: %s", tenure, e)

    return features


async def _fetch_overpass_parcels(
    lon_min: float, lat_min: float, lon_max: float, lat_max: float,
    limit: int,
) -> list[dict]:
    """
    Fallback: fetch land/building polygons from OpenStreetMap Overpass API,
    assign synthetic UK-style title numbers.
    """
    query = f"""
    [out:json][timeout:25];
    (
      way["landuse"~"farmland|meadow|grass|brownfield|industrial|commercial|residential"]
        ({lat_min},{lon_min},{lat_max},{lon_max});
      way["building"~"industrial|commercial|warehouse|farm"]
        ({lat_min},{lon_min},{lat_max},{lon_max});
      relation["landuse"~"farmland|meadow|grass|brownfield|industrial"]
        ({lat_min},{lon_min},{lat_max},{lon_max});
    );
    out body geom;
    """

    features = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                OVERPASS_API,
                data={"data": query},
                headers={"User-Agent": "Princeps/1.0 (energy site assessment)"},
            )
            if resp.status_code != 200:
                log.warning("Overpass API returned %s", resp.status_code)
                return features

            elements = resp.json().get("elements", [])

            for idx, el in enumerate(elements[:limit]):
                geom = _overpass_element_to_geojson_geom(el)
                if not geom:
                    continue

                area_ha = _polygon_area_ha(geom)
                if area_ha < 0.1:
                    continue

                centroid = shape(geom).centroid
                title_no = _generate_title_number(centroid.y, centroid.x, idx)
                tags = el.get("tags", {})
                landuse = tags.get("landuse", tags.get("building", "unknown"))

                # Assign synthetic tenure (most UK land is freehold)
                tenure = "freehold" if random.random() < 0.85 else "leasehold"

                features.append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {
                        "title_number": title_no,
                        "area_ha": round(area_ha, 3),
                        "tenure": tenure,
                        "landuse": landuse,
                        "land_use": landuse,
                        "osm_id": el.get("id"),
                        "osm_name": tags.get("name", ""),
                        "osm_operator": tags.get("operator", ""),
                        "osm_owner": tags.get("owner", ""),
                        "color": "#2563eb" if tenure == "freehold" else "#ea580c",
                        "source": "OpenStreetMap (synthetic title)",
                        "local_authority": "",
                        "hmlr_url": "",
                    },
                })
    except Exception as e:
        log.warning("Overpass parcel fetch failed: %s", e)

    return features


def _overpass_element_to_geojson_geom(el: dict) -> dict | None:
    """Convert an Overpass element with geometry to a GeoJSON geometry dict."""
    el_type = el.get("type")

    if el_type == "way":
        geom_nodes = el.get("geometry", [])
        if len(geom_nodes) < 4:
            return None
        coords = [[n["lon"], n["lat"]] for n in geom_nodes]
        # Close ring if needed
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        return {"type": "Polygon", "coordinates": [coords]}

    elif el_type == "relation":
        members = el.get("members", [])
        outer_rings = []
        for m in members:
            if m.get("role") == "outer" and m.get("geometry"):
                coords = [[n["lon"], n["lat"]] for n in m["geometry"]]
                if len(coords) >= 4:
                    if coords[0] != coords[-1]:
                        coords.append(coords[0])
                    outer_rings.append(coords)
        if outer_rings:
            if len(outer_rings) == 1:
                return {"type": "Polygon", "coordinates": outer_rings}
            return {"type": "MultiPolygon", "coordinates": [[ring] for ring in outer_rings]}

    return None


# ── 2. Enrichment Helpers ─────────────────────────────────────────────────

_NOMINATIM_LAST_CALL = 0.0  # rate-limit: 1 req/s


async def _reverse_geocode(lat: float, lon: float) -> dict:
    """Reverse geocode via Nominatim (free, 1 req/s rate limit)."""
    global _NOMINATIM_LAST_CALL
    # Respect 1 req/s rate limit
    now = time.time()
    wait = max(0, 1.05 - (now - _NOMINATIM_LAST_CALL))
    if wait > 0:
        await asyncio.sleep(wait)
    _NOMINATIM_LAST_CALL = time.time()

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lon, "format": "json", "zoom": 16},
                headers={"User-Agent": "Princeps/1.0 (energy site assessment)"},
            )
            if resp.status_code == 200:
                data = resp.json()
                addr = data.get("address", {})
                return {
                    "display_name": data.get("display_name", ""),
                    "road": addr.get("road", ""),
                    "suburb": addr.get("suburb", addr.get("hamlet", addr.get("village", ""))),
                    "city": addr.get("city", addr.get("town", addr.get("village", ""))),
                    "county": addr.get("county", ""),
                    "postcode": addr.get("postcode", ""),
                    "country": addr.get("country", ""),
                }
    except Exception as e:
        log.debug("Nominatim reverse geocode failed: %s", e)
    return {}


async def _get_local_authority(lat: float, lon: float) -> dict:
    """Look up local authority via postcodes.io (free, no auth)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.postcodes.io/postcodes",
                params={"lon": lon, "lat": lat, "limit": 1},
                headers={"User-Agent": "Princeps/1.0"},
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("result", [])
                if results and len(results) > 0:
                    r = results[0]
                    return {
                        "admin_district": r.get("admin_district", ""),
                        "admin_county": r.get("admin_county", ""),
                        "parish": r.get("parish", ""),
                        "parliamentary_constituency": r.get("parliamentary_constituency", ""),
                        "region": r.get("region", ""),
                        "postcode": r.get("postcode", ""),
                    }
    except Exception as e:
        log.debug("postcodes.io lookup failed: %s", e)
    return {}


async def _get_osm_land_info(lat: float, lon: float) -> dict:
    """Query OSM for land use and operator/owner at a point."""
    query = f"""
    [out:json][timeout:10];
    (
      way(around:50,{lat},{lon})["landuse"];
      way(around:50,{lat},{lon})["building"];
      way(around:50,{lat},{lon})["leisure"];
      relation(around:50,{lat},{lon})["landuse"];
    );
    out tags 1;
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                OVERPASS_API,
                data={"data": query},
                headers={"User-Agent": "Princeps/1.0 (energy site assessment)"},
            )
            if resp.status_code == 200:
                elements = resp.json().get("elements", [])
                if elements:
                    tags = elements[0].get("tags", {})
                    return {
                        "landuse": tags.get("landuse", tags.get("building", tags.get("leisure", ""))),
                        "operator": tags.get("operator", ""),
                        "owner": tags.get("owner", tags.get("name", "")),
                        "name": tags.get("name", ""),
                        "description": tags.get("description", ""),
                    }
    except Exception as e:
        log.debug("OSM land info lookup failed: %s", e)
    return {}


def _derive_proprietor_category(
    landuse: str, osm_owner: str, local_authority: str,
) -> tuple[str, str]:
    """
    Derive proprietor name and category from land use and OSM data.

    Returns (proprietor_name, proprietor_category).
    """
    landuse_lower = landuse.lower() if landuse else ""
    owner = osm_owner.strip() if osm_owner else ""

    # If OSM has an explicit owner/operator, use it
    if owner:
        # Detect category from owner name patterns
        owner_lower = owner.lower()
        if any(k in owner_lower for k in ("council", "borough", "county", "district", "authority", "government")):
            return owner, "Local Authority"
        if any(k in owner_lower for k in ("church", "diocese", "chapel", "parish")):
            return owner, "Religious Body"
        if any(k in owner_lower for k in ("trust", "charity", "foundation", "society")):
            return owner, "Charity / Trust"
        if any(k in owner_lower for k in ("ltd", "plc", "limited", "holdings", "group", "inc")):
            return owner, "Corporate Body"
        if any(k in owner_lower for k in ("network rail", "highways", "national grid", "crown estate")):
            return owner, "Public Body"
        return owner, "Corporate Body"

    # Derive from land use
    if landuse_lower in ("farmland", "meadow", "orchard", "vineyard", "allotments"):
        return "Private landowner (agricultural)", "Private Individual"
    if landuse_lower in ("grass", "greenfield"):
        return "Private landowner", "Private Individual"
    if landuse_lower in ("industrial", "commercial", "retail", "warehouse"):
        return "Corporate owner (commercial/industrial)", "Corporate Body"
    if landuse_lower in ("residential",):
        return "Private landowner (residential)", "Private Individual"
    if landuse_lower in ("brownfield", "construction"):
        return "Developer / Corporate owner", "Corporate Body"
    if landuse_lower in ("recreation_ground", "park", "village_green"):
        if local_authority:
            return f"{local_authority} (likely)", "Local Authority"
        return "Local authority (likely)", "Local Authority"
    if landuse_lower in ("forest", "wood"):
        return "Forestry Commission / Private owner", "Unknown"
    if landuse_lower in ("military",):
        return "Ministry of Defence", "Public Body"
    if landuse_lower in ("cemetery",):
        if local_authority:
            return f"{local_authority} / Church", "Local Authority"
        return "Local authority / Church", "Unknown"

    # Default
    if local_authority:
        return "Unknown (search HMLR for details)", "Unknown"
    return "Unknown (search HMLR for details)", "Unknown"


async def _enrich_parcel_detail(detail: dict) -> dict:
    """
    Enrich a parcel detail dict with freely available data:
    reverse geocode, local authority, OSM land use, proprietor inference.
    """
    geom = detail.get("geometry")
    if not geom:
        return detail

    # Compute centroid
    try:
        centroid = shape(geom).centroid
        lat, lon = centroid.y, centroid.x
    except Exception:
        return detail

    # Run enrichment lookups in parallel
    geocode_result, la_result, osm_result = await asyncio.gather(
        _reverse_geocode(lat, lon),
        _get_local_authority(lat, lon),
        _get_osm_land_info(lat, lon),
        return_exceptions=True,
    )

    # Handle any exceptions from gather
    if isinstance(geocode_result, Exception):
        log.debug("Geocode enrichment error: %s", geocode_result)
        geocode_result = {}
    if isinstance(la_result, Exception):
        log.debug("LA enrichment error: %s", la_result)
        la_result = {}
    if isinstance(osm_result, Exception):
        log.debug("OSM enrichment error: %s", osm_result)
        osm_result = {}

    # Build address from reverse geocode
    addr_parts = []
    if geocode_result.get("road"):
        addr_parts.append(geocode_result["road"])
    if geocode_result.get("suburb"):
        addr_parts.append(geocode_result["suburb"])
    if geocode_result.get("city"):
        addr_parts.append(geocode_result["city"])
    if geocode_result.get("postcode"):
        addr_parts.append(geocode_result["postcode"])
    address_str = ", ".join(addr_parts) if addr_parts else None

    # Local authority
    local_authority = la_result.get("admin_district", "")

    # Land use and proprietor inference
    osm_landuse = osm_result.get("landuse", "")
    osm_owner = osm_result.get("operator") or osm_result.get("owner", "")
    osm_name = osm_result.get("name", "")

    proprietor_name, proprietor_category = _derive_proprietor_category(
        osm_landuse, osm_owner, local_authority,
    )

    # Update the detail dict
    detail["proprietor_name"] = proprietor_name
    detail["proprietor_category"] = proprietor_category
    detail["proprietor_address"] = address_str
    # date_added stays None — only available via paid HMLR API
    detail["local_authority"] = local_authority
    detail["admin_county"] = la_result.get("admin_county", "")
    detail["parish"] = la_result.get("parish", "")
    detail["region"] = la_result.get("region", "")
    detail["parliamentary_constituency"] = la_result.get("parliamentary_constituency", "")
    detail["land_use"] = osm_landuse or None
    detail["osm_name"] = osm_name or None
    detail["address_road"] = geocode_result.get("road", "")
    detail["address_postcode"] = geocode_result.get("postcode", la_result.get("postcode", ""))
    detail["address_city"] = geocode_result.get("city", "")
    detail["address_county"] = geocode_result.get("county", "")

    return detail


# ── 2b. Parcel Detail ─────────────────────────────────────────────────────

async def get_parcel_detail(title_number: str) -> dict:
    """
    Fetch detailed information for a specific title number.

    Uses HMLR INSPIRE WFS filtered by title number. Proprietor data
    requires paid HMLR Business Gateway access — marked as such when
    unavailable.
    """
    detail = {
        "title_number": title_number,
        "area_ha": None,
        "tenure": None,
        "proprietor_name": None,
        "proprietor_category": None,
        "proprietor_address": None,
        "date_added": None,
        "local_authority": None,
        "land_use": None,
        "geometry": None,
        "source": None,
    }

    # Try INSPIRE WFS with CQL filter
    async with httpx.AsyncClient(timeout=15) as client:
        for tenure in ("freehold", "leasehold"):
            try:
                params = {
                    "service": "WFS",
                    "version": "2.0.0",
                    "request": "GetFeature",
                    "typeNames": f"inspire:{tenure}",
                    "outputFormat": "application/json",
                    "CQL_FILTER": f"TITLE_NO='{title_number}'",
                    "count": "1",
                }
                resp = await client.get(INSPIRE_WFS, params=params)
                if resp.status_code != 200:
                    continue

                data = resp.json()
                feats = data.get("features", [])
                if not feats:
                    continue

                f = feats[0]
                geom = f.get("geometry")

                # CRS transform if needed
                crs_info = data.get("crs", {}).get("properties", {}).get("name", "")
                if "27700" in str(crs_info):
                    geom = _transform_geometry_to_4326(geom, "EPSG:27700")

                area_ha = _polygon_area_ha(geom)
                props = f.get("properties", {})

                detail.update({
                    "area_ha": round(area_ha, 3),
                    "tenure": tenure,
                    "geometry": geom,
                    "poly_id": props.get("POLY_ID") or props.get("poly_id", ""),
                    "source": "HMLR INSPIRE",
                    "hmlr_url": (
                        f"https://search-property-information.service.gov.uk/"
                        f"search/search-by-inspire-id/"
                        f"{props.get('POLY_ID') or props.get('poly_id', '')}"
                    ),
                })
                # Enrich with reverse geocode, local authority, OSM data
                detail = await _enrich_parcel_detail(detail)
                return detail
            except Exception as e:
                log.debug("INSPIRE detail fetch failed for %s/%s: %s", tenure, title_number, e)

    # If INSPIRE didn't find it, it may be a synthetic title — check cache
    for cache_file in CACHE_DIR.glob("parcels_*.json"):
        try:
            fc = json.loads(cache_file.read_text())
            for f in fc.get("features", []):
                if f["properties"].get("title_number") == title_number:
                    detail.update({
                        "area_ha": f["properties"].get("area_ha"),
                        "tenure": f["properties"].get("tenure"),
                        "geometry": f.get("geometry"),
                        "land_use": f["properties"].get("landuse"),
                        "source": f["properties"].get("source", "cache"),
                    })
                    # Enrich with reverse geocode, local authority, OSM data
                    detail = await _enrich_parcel_detail(detail)
                    return detail
        except Exception:
            pass

    return detail


# ── 3. Search Parcels ─────────────────────────────────────────────────────

async def search_parcels(
    query: str,
    near_lat: Optional[float] = None,
    near_lon: Optional[float] = None,
    radius_km: float = 5.0,
) -> list[dict]:
    """
    Search parcels by title number prefix or nearby location.

    If query looks like a title number (starts with uppercase letters),
    searches cached parcels. If near_lat/near_lon provided, fetches
    parcels in a radius around the point.
    """
    results = []

    # If we have a location, fetch parcels in a bbox around it
    if near_lat is not None and near_lon is not None:
        # Convert radius_km to approximate degree offset
        dlat = radius_km / 111.0
        dlon = radius_km / (111.0 * math.cos(math.radians(near_lat)))
        fc = await fetch_parcels_in_bbox(
            near_lon - dlon, near_lat - dlat,
            near_lon + dlon, near_lat + dlat,
            limit=500,
        )
        features = fc.get("features", [])

        # Filter by title number prefix if query provided
        q_upper = query.strip().upper() if query else ""
        for f in features:
            tn = f["properties"].get("title_number", "")
            if q_upper and not tn.upper().startswith(q_upper):
                continue
            results.append({
                "title_number": tn,
                "area_ha": f["properties"].get("area_ha"),
                "tenure": f["properties"].get("tenure"),
                "source": f["properties"].get("source"),
                "centroid": _centroid_of(f.get("geometry")),
            })
        return results

    # No location — search all cached parcels by title prefix
    q_upper = query.strip().upper() if query else ""
    if not q_upper:
        return results

    for cache_file in CACHE_DIR.glob("parcels_*.json"):
        try:
            fc = json.loads(cache_file.read_text())
            for f in fc.get("features", []):
                tn = f["properties"].get("title_number", "")
                if tn.upper().startswith(q_upper):
                    results.append({
                        "title_number": tn,
                        "area_ha": f["properties"].get("area_ha"),
                        "tenure": f["properties"].get("tenure"),
                        "source": f["properties"].get("source"),
                        "centroid": _centroid_of(f.get("geometry")),
                    })
        except Exception:
            pass

    return results[:200]


def _centroid_of(geom: dict | None) -> dict | None:
    if not geom:
        return None
    try:
        c = shape(geom).centroid
        return {"lat": round(c.y, 6), "lon": round(c.x, 6)}
    except Exception:
        return None


# ── 4. Land Classification Suitability Heatmap ───────────────────────────

async def get_land_classification_heatmap(
    lon_min: float, lat_min: float, lon_max: float, lat_max: float,
) -> dict:
    """
    Generate a suitability heatmap for energy development across a bbox.

    Combines multiple scoring layers:
      - Agricultural Land Classification (ALC) grade
      - Slope (from lat-based approximation; GeeFlow NASADEM in production)
      - Flood risk zone
      - Distance to nearest substation
      - Protected area proximity (SSSI, AONB, National Park)

    Returns GeoJSON FeatureCollection of ~250m grid cells, each with:
      overall_score (0-100), breakdown by factor, RAG color.
    """
    bbox_h = _bbox_hash(lon_min, lat_min, lon_max, lat_max)
    cached = _read_cache("heatmap", bbox_h)
    if cached:
        return cached

    # Grid resolution: ~250m cells
    # At UK latitudes, 250m ≈ 0.00225° lat, ~0.0035° lon
    cell_lat = 0.00225
    cell_lon = 0.0035

    # Clamp bbox to reasonable size (max ~20km x 20km)
    max_span_lat = 0.18  # ~20km
    max_span_lon = 0.28  # ~20km
    if (lat_max - lat_min) > max_span_lat:
        mid = (lat_min + lat_max) / 2
        lat_min, lat_max = mid - max_span_lat / 2, mid + max_span_lat / 2
    if (lon_max - lon_min) > max_span_lon:
        mid = (lon_min + lon_max) / 2
        lon_min, lon_max = mid - max_span_lon / 2, mid + max_span_lon / 2

    # Fetch ALC data for the bbox centre (used as baseline for the area)
    centre_lat = (lat_min + lat_max) / 2
    centre_lon = (lon_min + lon_max) / 2
    alc_grade = await _lookup_alc_grade(centre_lat, centre_lon)

    # Fetch flood risk for the centre
    flood_zone = await _lookup_flood_zone(centre_lat, centre_lon)

    # Fetch nearest substation distance
    sub_dist_km = await _nearest_substation_distance(centre_lat, centre_lon)

    features = []
    lat = lat_min
    while lat < lat_max:
        lon = lon_min
        while lon < lon_max:
            cell_centre_lat = lat + cell_lat / 2
            cell_centre_lon = lon + cell_lon / 2

            # Score each factor (0-100, higher = more suitable)
            scores = _score_cell(
                cell_centre_lat, cell_centre_lon,
                alc_grade, flood_zone, sub_dist_km,
                centre_lat, centre_lon,
            )

            # Overall weighted score
            overall = (
                scores["alc"] * 0.30
                + scores["slope"] * 0.15
                + scores["flood"] * 0.20
                + scores["grid_proximity"] * 0.20
                + scores["protected_area"] * 0.15
            )
            overall = round(min(100, max(0, overall)), 1)

            # RAG color
            if overall >= 70:
                rag = "green"
                color = [34, 197, 94, 160]  # green with alpha
            elif overall >= 40:
                rag = "amber"
                color = [245, 158, 11, 160]  # amber
            else:
                rag = "red"
                color = [239, 68, 68, 160]  # red

            cell_geom = {
                "type": "Polygon",
                "coordinates": [[
                    [lon, lat],
                    [lon + cell_lon, lat],
                    [lon + cell_lon, lat + cell_lat],
                    [lon, lat + cell_lat],
                    [lon, lat],
                ]],
            }

            features.append({
                "type": "Feature",
                "geometry": cell_geom,
                "properties": {
                    "overall_score": overall,
                    "rag": rag,
                    "color": color,
                    "alc_score": scores["alc"],
                    "alc_grade": scores["alc_grade"],
                    "slope_score": scores["slope"],
                    "slope_deg": scores["slope_deg"],
                    "flood_score": scores["flood"],
                    "flood_zone": scores["flood_zone"],
                    "grid_proximity_score": scores["grid_proximity"],
                    "nearest_substation_km": scores["nearest_substation_km"],
                    "protected_area_score": scores["protected_area"],
                    "protected_area_note": scores["protected_area_note"],
                },
            })

            lon += cell_lon
        lat += cell_lat

    result = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "total_cells": len(features),
            "cell_size_m": 250,
            "bbox": [lon_min, lat_min, lon_max, lat_max],
            "scoring_weights": {
                "alc": 0.30,
                "slope": 0.15,
                "flood": 0.20,
                "grid_proximity": 0.20,
                "protected_area": 0.15,
            },
            "legend": {
                "green": "Score >= 70 — Highly suitable",
                "amber": "Score 40-69 — Moderate constraints",
                "red": "Score < 40 — Significant constraints",
            },
        },
    }

    _write_cache("heatmap", bbox_h, result)
    return result


def _score_cell(
    lat: float, lon: float,
    base_alc: str, base_flood_zone: str, base_sub_dist_km: float,
    centre_lat: float, centre_lon: float,
) -> dict:
    """Score a single grid cell across all suitability factors."""

    # ── ALC score ──
    # Add some spatial variation around the base grade
    dist_from_centre = math.sqrt((lat - centre_lat) ** 2 + (lon - centre_lon) ** 2)
    alc_grade = base_alc
    # Slight variation: cells further from centre may differ
    if dist_from_centre > 0.05:
        # Small chance of grade change at edges
        grades = list(_ALC_SCORES.keys())
        try:
            idx = grades.index(base_alc)
            shift = random.choice([-1, 0, 0, 0, 1])
            idx = max(0, min(len(grades) - 1, idx + shift))
            alc_grade = grades[idx]
        except ValueError:
            pass
    alc_score = _ALC_SCORES.get(alc_grade, 50)

    # ── Slope score ──
    # Approximate slope from latitude (northern England = hillier)
    # Production: use NASADEM DEM via GeeFlow
    base_slope = 2.0
    if lat > 54.0:
        base_slope = 6.0
    elif lat > 53.0:
        base_slope = 4.0
    elif lat > 52.0:
        base_slope = 3.0
    # Add micro-variation
    slope_deg = max(0, base_slope + random.gauss(0, 1.5))
    slope_deg = round(slope_deg, 1)
    # Score: 0° = 100, 10°+ = 0
    slope_score = max(0, min(100, 100 - slope_deg * 10))

    # ── Flood zone score ──
    flood_zone = base_flood_zone
    # Cells near rivers (lower elevation typically) may have higher flood risk
    penalty = _FLOOD_ZONE_PENALTY.get(flood_zone, 0)
    # Add slight spatial variation
    if random.random() < 0.1:
        flood_zone = random.choice(["1", "1", "1", "2", "2", "3"])
        penalty = _FLOOD_ZONE_PENALTY.get(flood_zone, 0)
    flood_score = max(0, 100 - penalty)

    # ── Grid proximity score ──
    # Vary slightly from base substation distance
    sub_dist = max(0.1, base_sub_dist_km + dist_from_centre * 50)
    sub_dist = round(sub_dist, 2)
    # Score: 0-2km = 100, 20km+ = 0
    grid_score = max(0, min(100, 100 - (sub_dist - 2) * 5.5))

    # ── Protected area score ──
    # Production: query Natural England SSSI/AONB/NP datasets
    # MVP: approximate from UK protected area density
    protected_note = "No known designation"
    protected_score = 95

    # National Parks: Lake District, Peak District, etc. — approximate by lat/lon
    in_national_park = False
    # Peak District rough bbox
    if 53.1 < lat < 53.6 and -2.0 < lon < -1.5:
        in_national_park = True
    # Lake District
    elif 54.3 < lat < 54.7 and -3.3 < lon < -2.7:
        in_national_park = True
    # Dartmoor
    elif 50.4 < lat < 50.7 and -4.1 < lon < -3.7:
        in_national_park = True
    # Snowdonia
    elif 52.7 < lat < 53.1 and -4.1 < lon < -3.6:
        in_national_park = True

    if in_national_park:
        protected_score = 5
        protected_note = "National Park — development highly constrained"
    else:
        # Small random chance of SSSI/AONB proximity
        r = random.random()
        if r < 0.05:
            protected_score = 15
            protected_note = "Within/adjacent to SSSI"
        elif r < 0.10:
            protected_score = 30
            protected_note = "Within AONB buffer zone"
        elif r < 0.15:
            protected_score = 60
            protected_note = "Near protected area (>500m buffer)"

    return {
        "alc": alc_score,
        "alc_grade": alc_grade,
        "slope": slope_score,
        "slope_deg": slope_deg,
        "flood": flood_score,
        "flood_zone": flood_zone,
        "grid_proximity": grid_score,
        "nearest_substation_km": sub_dist,
        "protected_area": protected_score,
        "protected_area_note": protected_note,
    }


async def _lookup_alc_grade(lat: float, lon: float) -> str:
    """Look up ALC grade — try planning.data.gov.uk, fallback to lat-based heuristic."""
    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "Princeps/1.0"}) as client:
            resp = await client.get(
                "https://www.planning.data.gov.uk/entity.json",
                params={
                    "dataset": "agricultural-land-classification",
                    "longitude": lon, "latitude": lat, "limit": 5,
                },
            )
            if resp.status_code == 200:
                entities = resp.json().get("entities", [])
                if entities:
                    grade_str = entities[0].get("name", "") or entities[0].get("reference", "")
                    return _parse_alc_grade(grade_str)
    except Exception as e:
        log.debug("ALC lookup failed: %s", e)

    # Fallback heuristic
    if lat > 54.5:
        return "4"
    elif lat > 53.0:
        return "3b"
    elif lat > 52.0:
        return "3a"
    elif 52.0 < lat < 53.0 and 0 < lon < 1.5:
        return "1"
    elif lat > 51.5:
        return "2"
    return "3a"


def _parse_alc_grade(text: str) -> str:
    """Extract ALC grade from a Natural England string."""
    t = text.lower().strip()
    if "3a" in t:
        return "3a"
    if "3b" in t:
        return "3b"
    if "non" in t or "urban" in t:
        return "non_agricultural"
    for g in ("1", "2", "3", "4", "5"):
        if g in t:
            return g
    return "3"


async def _lookup_flood_zone(lat: float, lon: float) -> str:
    """Look up EA flood zone — try EA Flood Map API, fallback to zone 1."""
    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "Princeps/1.0"}) as client:
            # EA Flood Map for Planning API
            resp = await client.get(
                "https://environment.data.gov.uk/flood-monitoring/id/floodAreas",
                params={"lat": lat, "long": lon, "dist": 1},
            )
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                if items:
                    # Parse flood zone from response
                    for item in items:
                        desc = str(item.get("description", "")).lower()
                        if "zone 3" in desc or "high" in desc:
                            return "3"
                        if "zone 2" in desc or "medium" in desc:
                            return "2"
                    return "2"  # Some flood area found but not zone 3
    except Exception as e:
        log.debug("Flood zone lookup failed: %s", e)

    return "1"  # Default: low risk


async def _nearest_substation_distance(lat: float, lon: float) -> float:
    """Approximate distance to nearest substation in km."""
    # Try the grid_data_platform utility
    try:
        from utils.grid_data_platform import find_nearest_substation
        result = find_nearest_substation(lat, lon)
        if result and "distance_km" in result:
            return result["distance_km"]
    except Exception:
        pass

    # Fallback: rough UK average — rural areas ~5-15km, urban ~1-3km
    # Use population density proxy from lat/lon
    if -0.5 < lon < 0.5 and 51.3 < lat < 51.7:
        return round(random.uniform(0.5, 3.0), 1)  # London area
    elif -2.0 < lon < -1.0 and 52.0 < lat < 52.8:
        return round(random.uniform(1.0, 5.0), 1)  # Midlands
    else:
        return round(random.uniform(3.0, 12.0), 1)  # Rural


# ── 5. Project Parcel Selection (DB) ─────────────────────────────────────

async def setup_project_parcels_table(pool) -> None:
    """Create the project_parcels table if it doesn't exist."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS project_parcels (
                id          SERIAL PRIMARY KEY,
                project_name TEXT NOT NULL,
                title_number TEXT NOT NULL,
                area_ha     DOUBLE PRECISION,
                tenure      TEXT,
                geometry    GEOMETRY(Geometry, 4326),
                added_at    TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(project_name, title_number)
            );
            CREATE INDEX IF NOT EXISTS idx_project_parcels_project
                ON project_parcels (project_name);
            CREATE INDEX IF NOT EXISTS idx_project_parcels_title
                ON project_parcels (title_number);
        """)
    log.info("project_parcels table ready")


async def select_parcels_for_project(
    pool,
    title_numbers: list[str],
    project_name: str,
) -> dict:
    """
    Save selected parcel title numbers to a project.

    Looks up parcel details from cache/INSPIRE and stores in
    project_parcels table with geometry.
    """
    saved = []
    errors = []

    for tn in title_numbers:
        detail = await get_parcel_detail(tn)
        geom_wkt = None
        if detail.get("geometry"):
            try:
                geom_wkt = shape(detail["geometry"]).wkt
            except Exception:
                pass

        try:
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO project_parcels (project_name, title_number, area_ha, tenure, geometry)
                    VALUES ($1, $2, $3, $4,
                            CASE WHEN $5::text IS NOT NULL
                                 THEN ST_SetSRID(ST_GeomFromText($5), 4326)
                                 ELSE NULL END)
                    ON CONFLICT (project_name, title_number) DO UPDATE
                    SET area_ha = EXCLUDED.area_ha,
                        tenure = EXCLUDED.tenure,
                        geometry = EXCLUDED.geometry,
                        added_at = NOW()
                """, project_name, tn,
                     detail.get("area_ha"),
                     detail.get("tenure"),
                     geom_wkt)
                saved.append(tn)
        except Exception as e:
            log.warning("Failed to save parcel %s: %s", tn, e)
            errors.append({"title_number": tn, "error": str(e)})

    return {
        "project_name": project_name,
        "saved": len(saved),
        "title_numbers": saved,
        "errors": errors,
    }


async def get_project_parcels(pool, project_name: str) -> dict:
    """Retrieve all parcels saved for a project as GeoJSON."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT title_number, area_ha, tenure,
                   ST_AsGeoJSON(geometry)::text AS geojson,
                   added_at
            FROM project_parcels
            WHERE project_name = $1
            ORDER BY added_at DESC
        """, project_name)

    features = []
    for r in rows:
        geom = json.loads(r["geojson"]) if r["geojson"] else None
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "title_number": r["title_number"],
                "area_ha": float(r["area_ha"]) if r["area_ha"] else None,
                "tenure": r["tenure"],
                "added_at": r["added_at"].isoformat() if r["added_at"] else None,
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "project_name": project_name,
            "total": len(features),
            "total_area_ha": round(sum(
                f["properties"]["area_ha"] or 0 for f in features
            ), 2),
        },
    }
