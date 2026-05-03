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

                        poly_id = props.get("POLY_ID") or props.get("poly_id", "")
                        title_no = props.get("TITLE_NO") or props.get("title_no") or props.get("inspireid", "")
                        f["properties"] = {
                            "title_number": title_no,
                            "tenure": tenure,
                            "area_ha": round(area_ha, 2),
                            "color": "#2563eb" if tenure == "freehold" else "#ea580c",
                            "available": area_ha >= 2.0,  # Flag larger parcels as potentially available
                            "poly_id": poly_id,
                            "hmlr_url": f"https://search-property-information.service.gov.uk/search/search-by-inspire-id/{poly_id}" if poly_id else "",
                        }
                        all_features.append(f)
                else:
                    log.warning("INSPIRE WFS %s returned %s — service may be disabled", tenure, resp.status_code)
            except Exception as e:
                log.warning("INSPIRE WFS fetch failed for %s: %s", tenure, e)

    # Fallback: if INSPIRE returned nothing, try OSM landuse polygons
    source = "HM Land Registry INSPIRE"
    if not all_features:
        log.info("INSPIRE returned 0 parcels — falling back to OSM landuse")
        try:
            all_features = await _osm_landuse_fallback(bbox, min_area_ha)
            source = "OpenStreetMap landuse (INSPIRE unavailable)"
        except Exception as e:
            log.warning("OSM landuse fallback failed: %s", e)

    result = {
        "type": "FeatureCollection",
        "features": all_features,
        "metadata": {
            "total": len(all_features),
            "freehold": sum(1 for f in all_features if f["properties"].get("tenure") == "freehold"),
            "leasehold": sum(1 for f in all_features if f["properties"].get("tenure") == "leasehold"),
            "source": source,
        },
    }

    _parcel_cache[key] = (now, result)
    return result


async def _osm_landuse_fallback(bbox: tuple, min_area_ha: float = 0.1) -> list:
    """Fetch landuse polygons from OSM Overpass as parcel approximation."""
    west, south, east, north = bbox
    query = f"""
    [out:json][timeout:15];
    (
      way["landuse"~"farmland|meadow|industrial|brownfield|commercial|grass|orchard|vineyard|allotments|recreation_ground|reservoir|forest"]({south},{west},{north},{east});
      way["natural"~"grassland|scrub|heath|wood"]({south},{west},{north},{east});
      way["leisure"~"park|garden|pitch"]({south},{west},{north},{east});
      relation["landuse"~"farmland|meadow|industrial|brownfield|commercial|grass|forest"]({south},{west},{north},{east});
    );
    out body;
    >;
    out skel qt;
    """
    # Overpass rejects httpx's default User-Agent with HTTP 406. Must spoof a real UA.
    headers = {"User-Agent": "Princeps/1.0 (princeps.energy)"}
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        resp = await client.post("https://overpass-api.de/api/interpreter", data={"data": query})
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []

    # Build node lookup
    nodes = {}
    for el in data.get("elements", []):
        if el["type"] == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])

    features = []
    for el in data.get("elements", []):
        if el["type"] != "way" or "nodes" not in el:
            continue
        coords = [nodes[nid] for nid in el["nodes"] if nid in nodes]
        if len(coords) < 4:
            continue

        area_ha = _polygon_area_ha({"type": "Polygon", "coordinates": [coords]})
        if area_ha < min_area_ha:
            continue

        tags = el.get("tags", {})
        landuse = tags.get("landuse") or tags.get("natural") or tags.get("leisure") or "unknown"
        color = {
            "farmland": "#4ade80", "meadow": "#86efac", "grass": "#a3e635",
            "orchard": "#65a30d", "vineyard": "#84cc16", "allotments": "#22c55e",
            "forest": "#166534", "wood": "#166534",
            "grassland": "#86efac", "scrub": "#a3a37a", "heath": "#c4a882",
            "industrial": "#9C9590", "brownfield": "#C67A1A", "commercial": "#60a5fa",
            "recreation_ground": "#4ade80", "park": "#34d399", "garden": "#6ee7b7",
            "pitch": "#2dd4bf", "reservoir": "#38bdf8",
        }.get(landuse, "#9C9590")

        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {
                "title_number": f"BK{el['id'] % 100000:05d}",
                "tenure": "unknown",
                "area_ha": round(area_ha, 2),
                "color": color,
                "available": area_ha >= 2.0,
                "landuse": landuse,
                "name": tags.get("name", ""),
                "source": "OpenStreetMap",
            },
        })

    return features


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
    lat: float, lon: float, *, radius_km: float = 10, land_type: str = None,
    pool=None,
) -> list[dict]:
    """
    Search land opportunities near a point from real data sources.

    Sources:
    1. REPD projects with stalled/withdrawn status (real lat/lon, capacity, planning history)
    2. Rightmove Commercial search link (deep link, not API scraping)
    3. OnTheMarket land search link
    4. EPC commercial certificates nearby (if DB available)
    """
    listings = []

    # ── Source 1: REPD stalled/withdrawn projects = real development sites ──
    if pool:
        try:
            radius_m = radius_km * 1000
            rows = await pool.fetch("""
                SELECT ref_id, site_name, technology_type, installed_capacity_mw,
                       dev_status, dev_status_short, operator, region, county,
                       mounting_type, address,
                       ST_Y(geometry) AS lat, ST_X(geometry) AS lon
                FROM repd_project
                WHERE geometry IS NOT NULL
                  AND dev_status_short IN ('Abandoned', 'Withdrawn', 'Refused', 'Appeal Refused', 'Awaiting Construction', 'No Application Required')
                  AND ST_DWithin(
                      geometry::geography,
                      ST_SetSRID(ST_Point($1, $2), 4326)::geography,
                      $3
                  )
                ORDER BY installed_capacity_mw DESC NULLS LAST
                LIMIT 20
            """, lon, lat, radius_m)

            for r in rows:
                cap = float(r["installed_capacity_mw"] or 0)
                status = r["dev_status_short"] or r["dev_status"]
                tech = r["technology_type"] or "Unknown"

                # Estimate area from capacity (solar ~2ha/MW, wind ~0.5ha/MW)
                if "solar" in tech.lower():
                    area = cap * 2
                    land_t = "solar_opportunity"
                elif "wind" in tech.lower():
                    area = cap * 0.5
                    land_t = "solar_opportunity"
                elif "battery" in tech.lower() or "storage" in tech.lower():
                    area = max(0.5, cap * 0.1)
                    land_t = "brownfield"
                else:
                    area = max(1, cap * 1)
                    land_t = "commercial"

                # Price estimate from market rates
                price_per_ha = {"solar_opportunity": 30000, "brownfield": 300000, "commercial": 400000}.get(land_t, 25000)

                listings.append({
                    "id": f"repd-{r['ref_id']}",
                    "title": r["site_name"] or f"{cap:.0f}MW {tech} Site",
                    "price_gbp": int(area * price_per_ha),
                    "price_per_ha_gbp": price_per_ha,
                    "area_ha": round(area, 1),
                    "lat": float(r["lat"]),
                    "lon": float(r["lon"]),
                    "type": land_t,
                    "source": "REPD",
                    "source_detail": f"REPD ref {r['ref_id']}",
                    "description": f"{status} {tech} project — {cap:.0f}MW capacity, {r['county'] or r['region'] or ''}. Previously had planning interest.",
                    "url": f"https://www.gov.uk/government/publications/renewable-energy-planning-database-monthly-extract",
                    "status": status,
                    "technology": tech,
                    "capacity_mw": cap,
                    "available": status in ("Abandoned", "Withdrawn", "Refused", "Appeal Refused"),
                })
        except Exception as e:
            log.debug("REPD listings query failed: %s", e)

    # ── Source 2: Rightmove Commercial search link ──
    rm_lat = f"{lat:.4f}"
    rm_lon = f"{lon:.4f}"
    rm_radius = min(int(radius_km), 40)
    listings.append({
        "id": "rightmove-search",
        "title": f"Search Rightmove Commercial Land",
        "price_gbp": None,
        "price_per_ha_gbp": None,
        "area_ha": None,
        "lat": lat,
        "lon": lon,
        "type": "search_link",
        "source": "Rightmove",
        "description": f"Commercial land & development sites within {rm_radius}mi",
        "url": f"https://www.rightmove.co.uk/commercial-property-for-sale/map.html?searchLocation={rm_lat}%2C{rm_lon}&radius={rm_radius}.0&propertyTypes=land&includeSSTC=false",
        "available": True,
    })

    # ── Source 3: OnTheMarket land search link ──
    listings.append({
        "id": "otm-search",
        "title": f"Search OnTheMarket Land",
        "price_gbp": None,
        "price_per_ha_gbp": None,
        "area_ha": None,
        "lat": lat,
        "lon": lon,
        "type": "search_link",
        "source": "OnTheMarket",
        "description": f"Agricultural & commercial land for sale nearby",
        "url": f"https://www.onthemarket.com/land/property/?location-id=&lat={lat}&lng={lon}&radius={rm_radius}",
        "available": True,
    })

    # ── Source 4: Savills farmland search link ──
    listings.append({
        "id": "savills-search",
        "title": f"Search Savills Rural Land",
        "price_gbp": None,
        "price_per_ha_gbp": None,
        "area_ha": None,
        "lat": lat,
        "lon": lon,
        "type": "search_link",
        "source": "Savills",
        "description": f"Farms, estates & rural land for sale",
        "url": f"https://search.savills.com/property/gb/rural/all-types/all-statuses/list?lat={lat}&lon={lon}&radius={rm_radius}mi",
        "available": True,
    })

    # Sort: real REPD listings first, then search links
    listings.sort(key=lambda x: (x["type"] == "search_link", -(x.get("capacity_mw") or 0)))
    return listings


async def get_price_paid(postcode: str, *, max_results: int = 50) -> dict:
    """
    Fetch HMLR Price Paid data for a postcode area.

    Uses the free public Land Registry linked data API:
    https://landregistry.data.gov.uk/data/ppi/transaction-record.json

    Returns recent transactions with price, date, property type, and address.
    """
    clean_pc = postcode.strip().upper()
    transactions = []

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            # HMLR Price Paid API — free, public, no auth
            resp = await client.get(
                "https://landregistry.data.gov.uk/data/ppi/transaction-record.json",
                params={
                    "propertyAddress.postcode": clean_pc,
                    "_pageSize": str(max_results),
                    "_sort": "-transactionDate",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("result", {}).get("items", [])
                for item in items:
                    addr = item.get("propertyAddress", {})
                    transactions.append({
                        "price_gbp": item.get("pricePaid"),
                        "date": item.get("transactionDate"),
                        "property_type": _ppi_property_type(item.get("propertyType", "")),
                        "new_build": item.get("newBuild", False),
                        "estate_type": _ppi_estate_type(item.get("estateType", "")),
                        "address": {
                            "paon": addr.get("paon", ""),
                            "saon": addr.get("saon", ""),
                            "street": addr.get("street", ""),
                            "locality": addr.get("locality", ""),
                            "town": addr.get("town", ""),
                            "district": addr.get("district", ""),
                            "county": addr.get("county", ""),
                            "postcode": addr.get("postcode", clean_pc),
                        },
                    })
            else:
                log.debug("HMLR Price Paid API returned %s for %s", resp.status_code, clean_pc)
        except Exception as e:
            log.warning("HMLR Price Paid fetch failed for %s: %s", clean_pc, e)

    # Summary statistics
    prices = [t["price_gbp"] for t in transactions if t["price_gbp"]]
    avg_price = round(sum(prices) / len(prices)) if prices else None
    min_price = min(prices) if prices else None
    max_price = max(prices) if prices else None

    return {
        "postcode": clean_pc,
        "total": len(transactions),
        "transactions": transactions,
        "summary": {
            "avg_price_gbp": avg_price,
            "min_price_gbp": min_price,
            "max_price_gbp": max_price,
            "by_type": _count_by(transactions, "property_type"),
            "by_estate": _count_by(transactions, "estate_type"),
        },
        "source": "HM Land Registry Price Paid Data",
    }


def _ppi_property_type(uri: str) -> str:
    """Extract readable property type from HMLR URI."""
    mapping = {
        "detached": "Detached",
        "semi-detached": "Semi-Detached",
        "terraced": "Terraced",
        "flat-maisonette": "Flat/Maisonette",
        "other": "Other",
    }
    lower = uri.lower()
    for key, val in mapping.items():
        if key in lower:
            return val
    return uri.split("/")[-1] if "/" in uri else (uri or "Unknown")


def _ppi_estate_type(uri: str) -> str:
    """Extract readable estate type from HMLR URI."""
    lower = uri.lower()
    if "freehold" in lower:
        return "Freehold"
    if "leasehold" in lower:
        return "Leasehold"
    return uri.split("/")[-1] if "/" in uri else (uri or "Unknown")


def _count_by(items: list[dict], key: str) -> dict[str, int]:
    """Count items by a key field."""
    counts: dict[str, int] = {}
    for item in items:
        val = item.get(key, "Unknown")
        counts[val] = counts.get(val, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


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
