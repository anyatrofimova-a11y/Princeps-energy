"""
/api/scan/* — search-zone scanner inspired by the LinkedIn one-click PV/BESS
risk tool. Given a bbox, returns:

  POST /api/scan/zone        — layer manifest (counts per layer, grouped)
  GET  /api/constraints/union — ST_Union of all "negative" constraint polys
                                (one combined fill instead of 7 overlays)
  GET  /api/scan/grid-corridors — top-2 routed connection corridors from
                                  bbox centroid to nearest substations
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.deps import get_pool

log = logging.getLogger("princeps.routers.scan")
router = APIRouter(tags=["scan"])

# Layer manifest. (key, label, table, geom_col, geom_type, group)
# group_order drives the categorised LayerControlPanel sections.
_LAYERS: list[dict[str, Any]] = [
    # 1 — Suitable / positive zones
    {"key": "lr_parcels_own",   "label": "Parcels by ownership", "table": "land_rights_parcel_ownership",
     "needs_geom_join": True, "group": "1 - Positive zones"},
    # 2 — Grid
    {"key": "grid_substations", "label": "Substations",         "table": "grid_substations",
     "geom": "geom", "type": "geometry", "srid": 27700, "group": "2 - Grid connection"},
    {"key": "nged_substation",  "label": "NGED LTDS substations","table": "nged_substation",
     "geom": "geometry", "type": "geometry", "srid": 4326, "group": "2 - Grid connection"},
    # 3 — Heritage & monuments
    {"key": "listed_buildings", "label": "Listed buildings",     "table": "listed_buildings_he",
     "geom": "geom", "type": "geography", "group": "3 - Heritage & monuments"},
    {"key": "nhle_heritage",    "label": "Historic England NHLE","table": "nhle_heritage_entries",
     "geom": "geom", "type": "geography", "group": "3 - Heritage & monuments"},
    # 4 — Wetlands & nature
    {"key": "ramsar",           "label": "Ramsar wetlands",      "table": "designations_ramsar",
     "geom": "geom", "type": "geometry", "srid": 4326, "group": "4 - Wetlands & nature"},
    {"key": "sssi",             "label": "SSSI",                 "table": "designations_sssi",
     "geom": "geom", "type": "geometry", "srid": 4326, "group": "4 - Wetlands & nature"},
    {"key": "sac",              "label": "SAC",                  "table": "designations_sac",
     "geom": "geom", "type": "geometry", "srid": 4326, "group": "4 - Wetlands & nature"},
    {"key": "spa",              "label": "SPA",                  "table": "designations_spa",
     "geom": "geom", "type": "geometry", "srid": 4326, "group": "4 - Wetlands & nature"},
    # 5 — Land cover & soil
    {"key": "woodland",         "label": "Woodland",             "table": "substrate_woodland",
     "geom": "geom", "type": "geometry", "srid": 4326, "group": "5 - Land cover & soil"},
    {"key": "alc_grade",        "label": "ALC grade",            "table": "designations_alc_grade",
     "geom": "geom", "type": "geometry", "srid": 4326, "group": "5 - Land cover & soil"},
    # 6 — Flood risk
    {"key": "ea_flood_zone_3",  "label": "EA Flood Zone 3",      "table": "ea_flood_zone_3",
     "geom": "geom", "type": "geography", "group": "6 - Flood risk"},
    {"key": "ea_flood_zone_2",  "label": "EA Flood Zone 2",      "table": "ea_flood_zone_2",
     "geom": "geom", "type": "geography", "group": "6 - Flood risk"},
    # 7 — Land rights
    {"key": "lr_crown",         "label": "Crown Estate",         "table": "crown_estate_land",
     "geom": "geom", "type": "geography", "group": "7 - Land rights"},
    {"key": "lr_mod",           "label": "MOD safeguarding",     "table": "mod_safeguarding_zones",
     "geom": "geom", "type": "geography", "group": "7 - Land rights"},
    {"key": "lr_forestry",      "label": "Forestry estate",      "table": "land_rights_forestry_estate",
     "geom": "geom", "type": "geography", "group": "7 - Land rights"},
    {"key": "lr_nt",            "label": "National Trust",       "table": "land_rights_national_trust",
     "geom": "geom", "type": "geography", "group": "7 - Land rights"},
    {"key": "lr_common",        "label": "Common land",          "table": "land_rights_common_land",
     "geom": "geom", "type": "geography", "group": "7 - Land rights"},
    {"key": "lr_prow",          "label": "Public rights of way", "table": "land_rights_prow_lines",
     "geom": "geom", "type": "geography", "group": "7 - Land rights"},
    # 8 — Restrictive
    {"key": "green_belt",       "label": "Green Belt",           "table": "designations_green_belt",
     "geom": "geom", "type": "geometry", "srid": 4326, "group": "8 - Restrictive"},
    {"key": "aonb",             "label": "AONB / National Landscape", "table": "designations_aonb",
     "geom": "geom", "type": "geometry", "srid": 4326, "group": "8 - Restrictive"},
]

# Tables that count as "negative" (constraint) for the union mode.
_NEGATIVE_KEYS = {
    "ea_flood_zone_3", "ea_flood_zone_2", "sssi", "sac", "spa", "ramsar",
    "green_belt", "aonb", "lr_mod", "lr_common", "lr_nt", "woodland",
    "listed_buildings",
}


class ZoneIn(BaseModel):
    bbox: list[float] = Field(..., description="[minLon,minLat,maxLon,maxLat]")
    layers: list[str] | None = Field(None, description="Optional subset of layer keys")


def _check_bbox(bbox: list[float]) -> tuple[float, float, float, float]:
    if not bbox or len(bbox) != 4:
        raise HTTPException(400, "bbox must be [minLon,minLat,maxLon,maxLat]")
    w, s, e, n = bbox
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise HTTPException(400, "invalid bbox extent")
    return w, s, e, n


def _intersect_clause(layer: dict[str, Any]) -> str:
    """SQL fragment that bbox-intersects this layer's geom column."""
    geom = layer.get("geom", "geom")
    if layer.get("type") == "geography":
        return f"ST_Intersects({geom}, ST_MakeEnvelope($1,$2,$3,$4,4326)::geography)"
    srid = layer.get("srid", 4326)
    if srid == 4326:
        return f"{geom} && ST_MakeEnvelope($1,$2,$3,$4,4326)"
    return (
        f"{geom} && ST_Transform(ST_MakeEnvelope($1,$2,$3,$4,4326), {srid})"
    )


@router.post("/api/scan/zone")
async def scan_zone(req: ZoneIn, pool=Depends(get_pool)) -> dict[str, Any]:
    """Run a layer-discovery scan across the bbox.

    Returns one entry per layer: {key, label, group, count, has_features}.
    Empty layers are still listed so the frontend can show "0/N" badges
    (matching the (0/5) badge pattern in the reference UI).
    """
    w, s, e, n = _check_bbox(req.bbox)
    wanted = set(req.layers) if req.layers else None

    out: list[dict[str, Any]] = []
    async with pool.acquire() as conn:
        for layer in _LAYERS:
            if wanted is not None and layer["key"] not in wanted:
                continue
            if layer.get("needs_geom_join"):
                # ownership table has no geom of its own — skip in scan,
                # but list it so the panel still shows it.
                out.append({
                    "key": layer["key"], "label": layer["label"],
                    "group": layer["group"], "count": None,
                    "has_features": None, "is_negative": False,
                })
                continue
            sql = (
                f"SELECT COUNT(*) FROM {layer['table']} "
                f"WHERE {_intersect_clause(layer)}"
            )
            try:
                n_features = await conn.fetchval(sql, w, s, e, n)
            except Exception as exc:
                log.warning("scan layer %s failed: %s", layer["key"], exc)
                n_features = None
            out.append({
                "key": layer["key"],
                "label": layer["label"],
                "group": layer["group"],
                "count": n_features,
                "has_features": (n_features is not None and n_features > 0),
                "is_negative": layer["key"] in _NEGATIVE_KEYS,
            })

    # Group summary for the UI badges (active/total)
    groups: dict[str, dict[str, int]] = {}
    for row in out:
        g = row["group"]
        bucket = groups.setdefault(g, {"available": 0, "with_features": 0})
        bucket["available"] += 1
        if row["has_features"]:
            bucket["with_features"] += 1

    return {
        "bbox": [w, s, e, n],
        "layers": out,
        "groups": [
            {"group": g, **counts}
            for g, counts in sorted(groups.items())
        ],
    }


@router.get("/api/constraints/union")
async def constraints_union(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    """One PostGIS ST_Union polygon covering all negative constraints in
    bbox. Renders as a single translucent fill in the UI (the purple wash
    in the reference screenshot)."""
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat")
    try:
        w, s, e, n = (float(p) for p in parts)
    except ValueError:
        raise HTTPException(400, "bbox values must be numeric")

    selects: list[str] = []
    for layer in _LAYERS:
        if layer["key"] not in _NEGATIVE_KEYS:
            continue
        if layer.get("needs_geom_join"):
            continue
        # Convert geography → geometry(4326) so ST_Union can combine all sources.
        geom = layer.get("geom", "geom")
        cast = (
            f"({geom}::geometry)" if layer.get("type") == "geography"
            else f"ST_Transform({geom}, 4326)" if layer.get("srid", 4326) != 4326
            else geom
        )
        selects.append(
            f"SELECT ST_Intersection({cast}, ST_MakeEnvelope($1,$2,$3,$4,4326)) AS g, "
            f"'{layer['key']}' AS layer FROM {layer['table']} "
            f"WHERE {_intersect_clause(layer)}"
        )

    if not selects:
        return {"type": "FeatureCollection", "features": []}

    sql = f"""
        WITH parts AS ( {' UNION ALL '.join(selects)} )
        SELECT ST_AsGeoJSON(
                 ST_Buffer(ST_Union(g), 0)
               )::jsonb AS union_geom,
               array_agg(DISTINCT layer) AS contributing_layers,
               COUNT(*) AS source_features
          FROM parts
         WHERE g IS NOT NULL AND NOT ST_IsEmpty(g)
    """
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(sql, w, s, e, n)
        except Exception as exc:
            log.warning("constraints_union failed: %s", exc)
            return {
                "type": "FeatureCollection", "features": [],
                "error": str(exc)[:200],
            }
    if not row or not row["union_geom"]:
        return {"type": "FeatureCollection", "features": []}
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "contributing_layers": list(row["contributing_layers"] or []),
                "source_features": row["source_features"],
            },
            "geometry": row["union_geom"],
        }],
    }


@router.get("/api/scan/grid-corridors")
async def grid_corridors(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    capacity_mw: float = Query(50.0, ge=0.1, le=2000),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    """Two best connection corridors: bbox centroid → nearest two substations
    that have enough headroom. Returns straight LineStrings styled at the
    frontend (orange = primary, yellow = alternate)."""
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(400, "bbox must be minLon,minLat,maxLon,maxLat")
    try:
        w, s, e, n = (float(p) for p in parts)
    except ValueError:
        raise HTTPException(400, "bbox values must be numeric")
    cx, cy = (w + e) / 2.0, (s + n) / 2.0

    # DISTINCT ON (name) so the same substation doesn't appear as both
    # primary and alternate when multiple records exist for the same site.
    sql = """
        SELECT DISTINCT ON (name)
               name, voltage_kv, gen_headroom_mw,
               ST_Y(ST_Transform(geom, 4326)) AS lat,
               ST_X(ST_Transform(geom, 4326)) AS lon,
               ST_Distance(
                 ST_Transform(geom, 4326)::geography,
                 ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
               ) / 1000.0 AS distance_km
          FROM grid_substations
         WHERE geom IS NOT NULL
           AND ST_DWithin(
                 ST_Transform(geom, 4326)::geography,
                 ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                 30000
               )
         ORDER BY name, distance_km ASC
    """
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(sql, cx, cy)
        except Exception as exc:
            log.warning("grid_corridors failed: %s", exc)
            return {
                "type": "FeatureCollection", "features": [],
                "error": str(exc)[:200],
            }

    # Re-sort by distance after the DISTINCT ON (which had to sort by name).
    rows = sorted(rows, key=lambda r: float(r["distance_km"] or 0))
    # Prefer subs with declared headroom ≥ requested capacity; else fall back.
    suitable = [r for r in rows if r["gen_headroom_mw"] and float(r["gen_headroom_mw"]) >= capacity_mw]
    chosen = (suitable[:2] if len(suitable) >= 2 else rows[:2])

    feats = []
    for idx, r in enumerate(chosen):
        feats.append({
            "type": "Feature",
            "properties": {
                "rank": idx + 1,                       # 1=primary, 2=alternate
                "substation_name": r["name"],
                "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
                "headroom_mw": float(r["gen_headroom_mw"]) if r["gen_headroom_mw"] else None,
                "distance_km": round(float(r["distance_km"]), 2),
                "estimated_cost_gbp": _estimate_cost(
                    float(r["distance_km"]),
                    float(r["voltage_kv"] or 33),
                ),
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [cx, cy],
                    [float(r["lon"]), float(r["lat"])],
                ],
            },
        })
    return {"type": "FeatureCollection", "features": feats}


def _estimate_cost(distance_km: float, voltage_kv: float) -> int:
    """UK rates from project memory: 11kV £80k/km, 33kV £150k/km, 132kV £500k/km."""
    if voltage_kv >= 132:
        rate = 500_000
    elif voltage_kv >= 33:
        rate = 150_000
    else:
        rate = 80_000
    return int(distance_km * rate)
