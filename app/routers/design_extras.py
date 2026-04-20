"""Design extras — the three endpoints DesignCanvas (D2/D5/D6) depends on
that weren't wired yet:

  GET  /api/grid/nearest-substation     — headroom fetch
  GET  /api/design/buildable-mask       — slope/flood/ALC/protected FC
  GET  /api/design/yield-curtailment    — SAM yield + curtailment heatmap

Kept in a dedicated module to avoid bloating grid.py / design.py further
and to make them easy to iterate independently.
"""

from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_pool

log = logging.getLogger("princeps.design_extras")

router = APIRouter(tags=["design-extras"])


# ═══════════════════════════════════════════════════════════════════════════
# /api/grid/nearest-substation
# Used by DesignCanvas to cap the capacity slider at substation headroom.
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/api/grid/nearest-substation")
async def nearest_substation(
    lat: float = Query(..., description="WGS84 latitude"),
    lon: float = Query(..., description="WGS84 longitude"),
    available_fraction: float = Query(
        0.30, ge=0, le=1,
        description="Assumed unallocated fraction of total substation capacity",
    ),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Nearest DNO substation to the point + estimated headroom (MW)."""
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """SELECT name, sub_id, source, capacity_kw,
                          ST_Distance(
                              geometry::geography,
                              ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                          ) / 1000.0 AS dist_km
                   FROM dno_substations
                   WHERE geometry IS NOT NULL
                   ORDER BY geometry <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
                   LIMIT 1""",
                lon, lat,
            )
        except Exception as e:
            log.warning("nearest-substation query failed: %s", e)
            raise HTTPException(503, f"Substation query failed: {e}")
    if not row:
        return {
            "headroom_mw": None,
            "name": None,
            "distance_km": None,
            "note": "No substation found in dno_substations table.",
        }
    cap_mw = (row["capacity_kw"] or 0) / 1000.0
    return {
        "sub_id": row["sub_id"],
        "name": row["name"],
        "dno": row["source"],
        "distance_km": round(row["dist_km"], 2),
        "total_capacity_mw": round(cap_mw, 1),
        "headroom_mw": round(cap_mw * available_fraction, 1),
        "available_fraction_assumed": available_fraction,
    }


# ═══════════════════════════════════════════════════════════════════════════
# /api/design/buildable-mask
# Returns a GeoJSON FeatureCollection of restricted-area polygons around
# the point, classified so DesignCanvas can tint them correctly.
# Classes match MASK_COLORS keys in DesignCanvas.jsx:
#   restricted_slope | restricted_flood | restricted_alc |
#   restricted_protected | restricted_land
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/api/design/buildable-mask")
async def buildable_mask(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_m: int = Query(1500, ge=100, le=10000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Aggregate buildable-area constraints into a single FeatureCollection."""
    features: list[dict] = []
    # metres → lon/lat degrees at this latitude
    m_per_deg_lat = 111_320
    m_per_deg_lon = 111_320 * math.cos(math.radians(lat))
    r_lat = radius_m / m_per_deg_lat
    r_lon = radius_m / m_per_deg_lon

    # Bounding box polygon for PostGIS intersections
    bbox_wkt = (
        f"POLYGON(({lon - r_lon} {lat - r_lat},"
        f"{lon + r_lon} {lat - r_lat},"
        f"{lon + r_lon} {lat + r_lat},"
        f"{lon - r_lon} {lat + r_lat},"
        f"{lon - r_lon} {lat - r_lat}))"
    )

    async with pool.acquire() as conn:
        # Each constraint table is optional. We probe for existence and
        # silently skip tables that aren't populated on this install.
        probes = [
            ("env_flood_zone_3",        "restricted_flood"),
            ("env_flood_zone_2",        "restricted_flood"),
            ("env_sssi",                "restricted_protected"),
            ("env_aonb",                "restricted_protected"),
            ("env_national_parks",      "restricted_protected"),
            ("env_scheduled_monuments", "restricted_protected"),
            ("env_ancient_woodland",    "restricted_land"),
            ("env_green_belt",          "restricted_land"),
            ("planning_alc_grade_1_2_3a", "restricted_alc"),
        ]
        for table, cls in probes:
            try:
                exists = await conn.fetchval(
                    "SELECT 1 FROM information_schema.tables WHERE table_name=$1 LIMIT 1",
                    table,
                )
                if not exists:
                    continue
                rows = await conn.fetch(
                    f"""SELECT ST_AsGeoJSON(ST_Intersection(geom, ST_GeomFromText($1, 4326))) AS g,
                               COALESCE(name, 'designation') AS name
                        FROM {table}
                        WHERE ST_Intersects(geom, ST_GeomFromText($1, 4326))
                        LIMIT 40""",
                    bbox_wkt,
                )
                for r in rows:
                    if not r["g"]:
                        continue
                    try:
                        geom = json.loads(r["g"])
                    except Exception:
                        continue
                    features.append({
                        "type": "Feature",
                        "properties": {"class": cls, "source": table, "name": r["name"]},
                        "geometry": geom,
                    })
            except Exception as e:
                log.debug("probe %s failed: %s", table, e)

        # Slope mask — derived from the planning-ml slope raster table if
        # present. When absent we skip slope masking entirely.
        try:
            has_slope = await conn.fetchval(
                "SELECT 1 FROM information_schema.tables WHERE table_name='slope_mask_tiles' LIMIT 1",
            )
            if has_slope:
                srows = await conn.fetch(
                    """SELECT ST_AsGeoJSON(geom) AS g
                       FROM slope_mask_tiles
                       WHERE slope_deg > 10
                         AND ST_Intersects(geom, ST_GeomFromText($1, 4326))
                       LIMIT 80""",
                    bbox_wkt,
                )
                for r in srows:
                    try:
                        features.append({
                            "type": "Feature",
                            "properties": {"class": "restricted_slope", "source": "slope_mask_tiles"},
                            "geometry": json.loads(r["g"]),
                        })
                    except Exception:
                        pass
        except Exception as e:
            log.debug("slope probe failed: %s", e)

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "lat": lat, "lon": lon, "radius_m": radius_m,
            "feature_count": len(features),
            "classes_present": sorted(set(f["properties"]["class"] for f in features)),
            "note": "Buildable mask composed from available env_* tables. Missing tables are skipped silently.",
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# /api/design/yield-curtailment
# Solar-only. Returns annual yield, capacity factor, curtailment forecast,
# monthly generation profile, and a representative-week hourly array.
# Uses PySAM if available (via the sam_runner subprocess), else falls back
# to an analytical model so the UI always lights up.
# ═══════════════════════════════════════════════════════════════════════════

_SAM_PY = os.environ.get("SAM_PYTHON")
_SAM_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent / "utils" / "sam_runner.py"
)


def _analytical_solar_yield(lat: float, lon: float, capacity_mw: float) -> dict[str, Any]:
    """Lightweight UK-specific yield model — adequate for UI fallback.

    Capacity factor scales with latitude within GB; monthly shape based on
    a typical south-England irradiance profile (kWh/m²/day).
    """
    cf_base = 0.113 if lat < 52.5 else 0.105 if lat < 55 else 0.095
    annual_mwh = capacity_mw * 8760 * cf_base
    monthly_shape = [0.035, 0.055, 0.085, 0.110, 0.125, 0.130,
                     0.130, 0.120, 0.095, 0.068, 0.028, 0.019]
    monthly_mwh = [round(annual_mwh * s, 1) for s in monthly_shape]
    # Representative clear-sky June week — 24×7 = 168 hours
    peak_mw = capacity_mw * 0.78
    week = []
    for _ in range(7):
        for h in range(24):
            sunangle = max(0, math.sin(math.pi * (h - 5) / 14)) if 5 <= h <= 19 else 0
            week.append(round(peak_mw * sunangle * 0.92, 3))
    return {
        "annual_yield_mwh": round(annual_mwh, 0),
        "capacity_factor_pct": round(cf_base * 100, 2),
        "monthly_mwh": monthly_mwh,
        "representative_week": week,
        "source": "analytical",
    }


async def _sam_solar_yield(lat: float, lon: float, capacity_mw: float):
    """Delegate to the PvWattsv8 subprocess runner. None if unavailable."""
    if not _SAM_PY or not Path(_SAM_PY).is_file() or not _SAM_SCRIPT.exists():
        return None
    try:
        proc = await _run_subprocess([
            _SAM_PY, str(_SAM_SCRIPT),
            "--lat", str(lat), "--lon", str(lon),
            "--capacity-kw", str(capacity_mw * 1000),
            "--json",
        ])
        out = proc.get("stdout", "").strip()
        if not out:
            return None
        return json.loads(out)
    except Exception as e:
        log.debug("SAM yield subprocess failed: %s", e)
        return None


async def _run_subprocess(argv):
    import asyncio
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return {"returncode": proc.returncode, "stdout": stdout.decode(), "stderr": stderr.decode()}


@router.get("/api/design/yield-curtailment")
async def yield_curtailment(
    lat: float = Query(...),
    lon: float = Query(...),
    capacity_mw: float = Query(..., ge=0.1, le=500),
    tech: str = Query("solar"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Solar yield (MWh/yr, CF%, monthly shape, week heatmap) + expected
    curtailment % (derived from nearest substation ANM exposure)."""
    if tech != "solar":
        raise HTTPException(400, "yield-curtailment currently only supports tech=solar")

    # SAM first, analytical fallback.
    # Normalise SAM output: the subprocess runner returns `annual_energy_kwh`,
    # we reshape it to the unified `{annual_yield_mwh, capacity_factor_pct,
    # monthly_mwh, representative_week, source}` contract the UI expects.
    # Previously this comparison used a key that SAM never emitted so the
    # analytical fallback ran 100% of the time.
    sam = await _sam_solar_yield(lat, lon, capacity_mw)
    if sam:
        if "annual_yield_mwh" not in sam and "annual_energy_kwh" in sam:
            sam["annual_yield_mwh"] = round(sam["annual_energy_kwh"] / 1000.0, 0)
        sam.setdefault("capacity_factor_pct",
                       round((sam.get("annual_yield_mwh", 0) / max(1, capacity_mw * 8760)) * 100, 2))
        sam.setdefault("monthly_mwh", None)
        sam.setdefault("representative_week", None)
        sam.setdefault("source", "sam")
    yield_block = sam if sam and sam.get("annual_yield_mwh") else _analytical_solar_yield(lat, lon, capacity_mw)

    # Curtailment estimate — pulls from nearest substation headroom vs capacity
    curtailment_pct = 1.5
    anm_hours_yr = 80
    try:
        async with pool.acquire() as conn:
            sub = await conn.fetchrow(
                """SELECT capacity_kw,
                          ST_Distance(geometry::geography,
                                      ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography) / 1000.0 AS dist_km
                   FROM dno_substations
                   ORDER BY geometry <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
                   LIMIT 1""",
                lon, lat,
            )
            if sub:
                headroom_mw = (sub["capacity_kw"] or 0) / 1000 * 0.30
                if headroom_mw > 0:
                    over = max(0, capacity_mw - headroom_mw) / capacity_mw
                    curtailment_pct = round(1.2 + over * 8.4, 2)
                    anm_hours_yr = int(80 + over * 400)
    except Exception as e:
        log.debug("curtailment substation lookup failed: %s", e)

    yield_block.update({
        "curtailment_pct_expected": curtailment_pct,
        "anm_hours_yr": anm_hours_yr,
        "lat": lat, "lon": lon, "capacity_mw": capacity_mw,
    })
    return yield_block
