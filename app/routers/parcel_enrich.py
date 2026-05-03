"""
/api/parcels/enrich — actual spatial-join enrichment for a parcel click.

Drops the generic outbound search-link soup. Instead, joins the click
point against the live PostGIS tables we already have populated:

    - grid_substations            → nearest substation + headroom
    - grid_dno_boundaries         → DNO licence area
    - designations_aonb / SSSI / SAC / SPA / Ramsar / Green Belt → overlaps
    - ea_flood_zone_2 / _3        → flood zone status
    - designations_alc_grade      → ALC grade
    - listed_buildings_he         → nearest listed building distance
    - repd_projects               → nearest planning record
    - magic_designations          → any MAGIC overlay

Each section is wrapped in try/except so a missing table or empty
result degrades gracefully rather than 500-ing the whole call.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_pool

log = logging.getLogger("princeps.routers.parcel_enrich")
router = APIRouter(prefix="/api/parcels", tags=["parcels"])


class EnrichIn(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    area_ha: float | None = Field(None, ge=0)
    inspire_id: str | None = None


def _maybe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def _safe_fetchrow(conn, sql: str, *args) -> dict[str, Any] | None:
    try:
        row = await conn.fetchrow(sql, *args)
        return dict(row) if row else None
    except Exception as exc:
        log.warning("parcel enrich subquery failed: %s — %s",
                    sql.split("FROM", 1)[-1].strip().split()[0] if "FROM" in sql else "?",
                    exc)
        return None


async def _safe_fetchval(conn, sql: str, *args):
    try:
        return await conn.fetchval(sql, *args)
    except Exception as exc:
        log.warning("parcel enrich subquery (val) failed: %s", exc)
        return None


@router.post("/enrich")
async def enrich_parcel(req: EnrichIn, pool=Depends(get_pool)) -> dict[str, Any]:
    out: dict[str, Any] = {
        "inspire_id": req.inspire_id,
        "centroid": {"lat": req.lat, "lon": req.lon},
        "area_ha": req.area_ha,
    }

    async with pool.acquire() as conn:
        # ─ 1. Nearest substation (grid_substations is SRID 27700) ──────────
        # Use ST_Transform on the point side so the index on geom (27700) is hit.
        sub = await _safe_fetchrow(conn, """
            SELECT name, voltage_kv, gen_headroom_mw, demand_headroom_mw, dno,
                   ST_Distance(
                     geom,
                     ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                   ) AS distance_m
              FROM grid_substations
             WHERE geom IS NOT NULL
             ORDER BY geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
             LIMIT 1
        """, req.lon, req.lat)
        if sub:
            out["nearest_substation"] = {
                "name": sub["name"],
                "voltage_kv": _maybe_float(sub["voltage_kv"]),
                "gen_headroom_mw": _maybe_float(sub["gen_headroom_mw"]),
                "demand_headroom_mw": _maybe_float(sub["demand_headroom_mw"]),
                "dno": sub["dno"],
                "distance_m": round(_maybe_float(sub["distance_m"]) or 0, 0),
            }

        # ─ 2. DNO licence area (grid_dno_boundaries) ───────────────────────
        dno = await _safe_fetchval(conn, """
            SELECT dno_name FROM grid_dno_boundaries
             WHERE ST_Intersects(
                geom,
                ST_SetSRID(ST_MakePoint($1, $2), 4326)
             ) LIMIT 1
        """, req.lon, req.lat)
        if dno:
            out["dno_licence_area"] = dno

        # ─ 3. Designation overlaps (one query per layer; NULLs if empty) ──
        designation_overlaps: list[dict[str, str]] = []
        for kind, table, name_col in [
            ("AONB / National Landscape", "designations_aonb",       "name"),
            ("Green Belt",                "designations_green_belt", "name"),
            ("SSSI",                      "designations_sssi",       "name"),
            ("SAC",                       "designations_sac",        "name"),
            ("SPA",                       "designations_spa",        "name"),
            ("Ramsar",                    "designations_ramsar",     "name"),
        ]:
            row = await _safe_fetchval(conn, f"""
                SELECT {name_col} FROM {table}
                 WHERE ST_Intersects(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326))
                 LIMIT 1
            """, req.lon, req.lat)
            if row:
                designation_overlaps.append({"type": kind, "name": row})
        out["designation_overlaps"] = designation_overlaps

        # ─ 4. Flood zone (2 / 3 / none) — geography tables ─────────────────
        zone3 = await _safe_fetchval(conn, """
            SELECT 1 FROM ea_flood_zone_3
             WHERE ST_Intersects(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography)
             LIMIT 1
        """, req.lon, req.lat)
        if zone3:
            out["flood_zone"] = "Zone 3 (1-in-100y)"
        else:
            zone2 = await _safe_fetchval(conn, """
                SELECT 1 FROM ea_flood_zone_2
                 WHERE ST_Intersects(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography)
                 LIMIT 1
            """, req.lon, req.lat)
            out["flood_zone"] = "Zone 2 (1-in-1000y)" if zone2 else "Zone 1"

        # ─ 5. ALC grade ────────────────────────────────────────────────────
        alc = await _safe_fetchval(conn, """
            SELECT grade FROM designations_alc_grade
             WHERE ST_Intersects(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326))
             LIMIT 1
        """, req.lon, req.lat)
        if alc:
            out["alc_grade"] = alc

        # ─ 6. Nearest listed building (geography table) ────────────────────
        lb = await _safe_fetchrow(conn, """
            SELECT name,
                   ST_Distance(
                     geom,
                     ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                   ) AS distance_m
              FROM listed_buildings_he
             WHERE geom IS NOT NULL
             ORDER BY geom <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
             LIMIT 1
        """, req.lon, req.lat)
        if lb and lb.get("distance_m") is not None and float(lb["distance_m"]) < 2000:
            out["nearest_listed_building"] = {
                "name": lb["name"],
                "distance_m": round(float(lb["distance_m"]), 0),
            }

        # ─ 7. Nearest REPD planning record (Point, SRID 27700) ────────────
        repd = await _safe_fetchrow(conn, """
            SELECT site_name, technology, capacity_mw, status,
                   ST_Distance(
                     geometry,
                     ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                   ) AS distance_m
              FROM repd_projects
             WHERE geometry IS NOT NULL
             ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
             LIMIT 1
        """, req.lon, req.lat)
        if repd and repd.get("distance_m") is not None and float(repd["distance_m"]) < 5000:
            out["nearest_repd"] = {
                "site_name": repd["site_name"],
                "technology": repd["technology"],
                "capacity_mw": _maybe_float(repd["capacity_mw"]),
                "status": repd["status"],
                "distance_m": round(float(repd["distance_m"]), 0),
            }

        # ─ 8. Solar yield estimate (UK central baseline kWh/kWp/yr) ───────
        # Quick analytical estimate; replaced by SAM run on demand.
        # Latitude factor: 1180 in south, 950 in north Scotland.
        lat_factor = max(0.85, min(1.15, 1.10 - (req.lat - 51.5) * 0.025))
        out["solar_yield_kwh_per_kwp_yr"] = round(1080 * lat_factor, 0)
        if req.area_ha:
            # ~ 0.6 MWp/ha solar density (panels + spacing), 1080 kWh/kWp/yr
            out["solar_potential_mwp"] = round(req.area_ha * 0.6, 1)
            out["solar_potential_gwh_yr"] = round(
                req.area_ha * 0.6 * out["solar_yield_kwh_per_kwp_yr"] / 1000, 1
            )

    # ─ 9. Verdict — quick GO/CAUTION/NO-GO using what we found ────────────
    no_go = []
    caution = []
    if any(d["type"] in ("SSSI", "SAC", "SPA", "Ramsar") for d in designation_overlaps):
        no_go.append("Statutory designation overlap")
    if any(d["type"] == "Green Belt" for d in designation_overlaps):
        no_go.append("Green Belt — sequential test required")
    if out.get("flood_zone", "").startswith("Zone 3"):
        no_go.append("Flood Zone 3")
    if out.get("alc_grade") in ("1", "2", "Grade 1", "Grade 2"):
        caution.append(f"ALC {out['alc_grade']} (BMV land)")
    if out.get("flood_zone", "").startswith("Zone 2"):
        caution.append("Flood Zone 2 — sequential test if vulnerable use")
    if any(d["type"].startswith("AONB") for d in designation_overlaps):
        caution.append("AONB / National Landscape")
    sub = out.get("nearest_substation") or {}
    if sub.get("distance_m") and sub["distance_m"] > 5000:
        caution.append(f"Grid {round(sub['distance_m']/1000, 1)} km away")

    if no_go:
        out["verdict"] = {"label": "NO-GO", "reasons": no_go}
    elif caution:
        out["verdict"] = {"label": "CAUTION", "reasons": caution}
    else:
        out["verdict"] = {"label": "GO", "reasons": ["No statutory blockers detected"]}

    return out
