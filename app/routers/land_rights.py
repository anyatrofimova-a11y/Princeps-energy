"""
/api/land-rights/* — UK land-rights overlays.

GeoJSON FeatureCollection per dataset, bbox-filtered, capped at 5000 features.
On-demand ingest endpoints mirror the pattern in app/routers/ea_layers.py.

Layers:
    crown          - Crown Estate land (existing crown_estate_land table)
    mod            - MOD safeguarding zones (existing mod_safeguarding_zones)
    forestry       - Forestry England subcompartments (new)
    national-trust - NT Always-Open land (new)
    common         - CRoW s.4 common land (new)
    covenants      - Conservation covenants (new)
    prow           - Public rights of way lines (new)

Plus /parcels/ownership-coloured for HMLR CCOD/OCOD-joined INSPIRE polygons.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_pool

log = logging.getLogger("princeps.routers.land_rights")
router = APIRouter(prefix="/api/land-rights", tags=["land-rights"])

# layer key → (table, list of property cols)
_LAYERS: dict[str, tuple[str, list[str]]] = {
    "crown": (
        "crown_estate_land",
        ["feature_id", "name", "land_class", "holding_type", "area_ha"],
    ),
    "mod": (
        "mod_safeguarding_zones",
        ["feature_id", "site_name", "zone_class", "buffer_m"],
    ),
    "forestry": (
        "land_rights_forestry_estate",
        ["feature_id", "forest_name", "managing_body", "nation", "area_ha"],
    ),
    "national-trust": (
        "land_rights_national_trust",
        ["feature_id", "property_name", "access_type", "region", "area_ha"],
    ),
    "common": (
        "land_rights_common_land",
        ["feature_id", "cl_number", "name", "parish", "county", "area_ha"],
    ),
    "covenants": (
        "land_rights_conservation_cov",
        [
            "feature_id", "responsible_body", "landowner",
            "duration_years", "purpose", "registered_at", "area_ha",
        ],
    ),
    "prow": (
        "land_rights_prow_lines",
        ["feature_id", "row_class", "name", "parish", "council", "length_m"],
    ),
}


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        parts = [float(p) for p in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError
        return tuple(parts)  # type: ignore[return-value]
    except ValueError:
        raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat")


def _coerce(v: Any) -> Any:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    try:
        # Decimals → float for JSON
        from decimal import Decimal
        if isinstance(v, Decimal):
            return float(v)
    except Exception:
        pass
    return v


@router.get("/{layer}")
async def land_rights_geojson(
    layer: str,
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(5000, ge=1, le=20000),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    if layer not in _LAYERS:
        raise HTTPException(404, f"unknown layer: {layer!r}")
    table, cols = _LAYERS[layer]
    min_lon, min_lat, max_lon, max_lat = _parse_bbox(bbox)
    select_cols = ", ".join(cols)
    sql = f"""
        SELECT {select_cols},
               ST_AsGeoJSON(geom::geometry)::jsonb AS geom
          FROM {table}
         WHERE ST_Intersects(geom,
                ST_MakeEnvelope($1, $2, $3, $4, 4326)::geography)
         LIMIT $5
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, min_lon, min_lat, max_lon, max_lat, limit)
    except Exception as exc:
        log.warning("land_rights %s query failed: %s", layer, exc)
        return {
            "type": "FeatureCollection",
            "features": [],
            "error": str(exc)[:200],
            "layer": layer,
        }
    feats = []
    for r in rows:
        props = {c: _coerce(r.get(c)) for c in cols if r.get(c) is not None}
        feats.append({
            "type": "Feature",
            "id": r.get("feature_id"),
            "properties": props,
            "geometry": r["geom"],
        })
    return {
        "type": "FeatureCollection",
        "features": feats,
        "count": len(feats),
        "layer": layer,
    }


@router.get("/parcels/ownership-coloured")
async def parcels_ownership_coloured(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(8000, ge=1, le=20000),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    """INSPIRE parcels intersecting bbox, with an ownership `category` joined
    from CCOD/OCOD. Empty `[]` until hmlr_inspire_polygons is populated."""
    min_lon, min_lat, max_lon, max_lat = _parse_bbox(bbox)
    sql = """
        SELECT p.inspire_id, p.area_ha,
               ST_AsGeoJSON(p.geom::geometry)::jsonb AS geom,
               COALESCE(o.category, 'individual_or_unknown') AS category,
               o.proprietor_name, o.title_number, o.country_incorp
          FROM hmlr_inspire_polygons p
          LEFT JOIN land_rights_parcel_ownership o
                 ON o.inspire_id = p.inspire_id
         WHERE ST_Intersects(p.geom,
                ST_MakeEnvelope($1, $2, $3, $4, 4326)::geography)
         LIMIT $5
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, min_lon, min_lat, max_lon, max_lat, limit)
    except Exception as exc:
        log.warning("ownership-coloured failed: %s", exc)
        return {
            "type": "FeatureCollection",
            "features": [],
            "error": str(exc)[:200],
        }
    feats = [
        {
            "type": "Feature",
            "id": r["inspire_id"],
            "properties": {
                "inspire_id": r["inspire_id"],
                "area_ha": _coerce(r["area_ha"]),
                "category": r["category"],
                "proprietor": r["proprietor_name"],
                "title_number": r["title_number"],
                "country_incorp": r["country_incorp"],
            },
            "geometry": r["geom"],
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": feats, "count": len(feats)}


@router.post("/ingest/{layer}")
async def trigger_ingest(
    layer: str,
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    """Trigger an on-demand bbox ingest for a land-rights layer.
    Each ingester is imported lazily so a missing module doesn't block boot."""
    bbox_t = _parse_bbox(bbox)
    if layer == "crown":
        from utils.substrate.crown_estate_ingester import ingest_crown_estate
        return await ingest_crown_estate(pool, bbox_t)
    if layer == "forestry":
        from utils.land_rights.forestry_ingester import ingest_forestry_estate
        return await ingest_forestry_estate(pool, bbox_t)
    if layer == "national-trust":
        from utils.land_rights.national_trust_ingester import ingest_nt_land
        return await ingest_nt_land(pool, bbox_t)
    if layer == "common":
        from utils.land_rights.common_land_ingester import ingest_common_land
        return await ingest_common_land(pool, bbox_t)
    if layer == "covenants":
        from utils.land_rights.covenants_ingester import ingest_covenants
        return await ingest_covenants(pool, bbox_t)
    if layer == "prow":
        from utils.land_rights.prow_ingester import ingest_prow
        return await ingest_prow(pool, bbox_t)
    raise HTTPException(404, f"no ingester wired for {layer!r}")


@router.get("/status")
async def status(pool=Depends(get_pool)) -> dict[str, Any]:
    sql = """
        SELECT id, layer, bbox, rows_inserted, rows_updated,
               status, started_at, finished_at
          FROM constraint_layers_ingest_log
         WHERE layer LIKE 'land_rights_%' OR layer = 'crown_estate_land'
         ORDER BY started_at DESC
         LIMIT 20
    """
    try:
        async with pool.acquire() as conn:
            return {"runs": [dict(r) for r in await conn.fetch(sql)]}
    except Exception as exc:
        return {"runs": [], "error": str(exc)[:200]}
