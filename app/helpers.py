"""Shared helpers — scoring functions, DB queries, subprocess runner, Claude explain."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import struct
import subprocess
import hashlib
import random
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import UUID

import anthropic
import asyncpg
from fastapi import HTTPException
from pydantic import BaseModel

log = logging.getLogger("princeps.helpers")

# ---------------------------------------------------------------------------
# Configuration (read from environment, shared across routers)
# ---------------------------------------------------------------------------
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")

_sam_default = os.path.join(os.path.dirname(__file__), "..", ".venv-sam", "bin", "python")
SAM_PYTHON = str(Path(os.environ.get("SAM_PYTHON", _sam_default)).absolute())
SAM_RUNNER = str(Path(os.path.join(os.path.dirname(__file__), "..", "utils", "sam_runner.py")).resolve())

_geeflow_default = os.path.join(os.path.dirname(__file__), "..", ".venv-geeflow", "bin", "python")
GEEFLOW_PYTHON = str(Path(os.environ.get("GEEFLOW_PYTHON", _geeflow_default)).absolute())
GEEFLOW_RUNNER = str(Path(os.path.join(os.path.dirname(__file__), "..", "utils", "geeflow_runner.py")).resolve())
GEE_PROJECT = os.environ.get("GEE_PROJECT", "")

_geoai_default = os.path.join(os.path.dirname(__file__), "..", ".venv-geeflow", "bin", "python")
GEOAI_PYTHON = str(Path(os.environ.get("GEOAI_PYTHON", _geoai_default)).absolute())
GEOAI_RUNNER = str(Path(os.path.join(os.path.dirname(__file__), "..", "utils", "geoai_runner.py")).resolve())

FORECAST_PYTHON = str(Path(os.path.dirname(__file__)).resolve().parent / ".venv-forecast" / "bin" / "python")
DEMAND_INGESTER_SCRIPT = str(Path(os.path.dirname(__file__)).resolve().parent / "utils" / "demand_data_ingester.py")
DEMAND_FORECAST_SCRIPT = str(Path(os.path.dirname(__file__)).resolve().parent / "utils" / "demand_forecaster.py")
CARBON_FORECAST_SCRIPT = str(Path(os.path.dirname(__file__)).resolve().parent / "utils" / "carbon_intensity_forecaster.py")

MAPBOX_TOKEN = os.environ.get("VITE_MAPBOX_TOKEN", os.environ.get("MAPBOX_TOKEN", ""))
ELECTRICITYMAPS_API_KEY = os.environ.get("ELECTRICITYMAPS_API_KEY", "")

import sys
_PHASE7_DIR = str(Path(__file__).resolve().parent.parent / "utils")

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SiteExplanation(BaseModel):
    explanation: str
    score_total: float
    context: dict[str, Any]


class LocationInput(BaseModel):
    lat: float
    lon: float
    area_m2: float = 50000.0


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def compute_grid_score(capacity_kw: float | None, distance_km: float | None) -> int:
    if capacity_kw is None or distance_km is None:
        return 0
    cap_score = min(50.0, max(0.0, (capacity_kw / 1000.0) * 10))
    dist_penalty = min(30.0, max(0.0, distance_km * 2))
    return max(0, int(cap_score - dist_penalty + 20))


def compute_planning_score(aonb: bool, sssi: bool) -> int:
    score = 30
    if aonb:
        score -= 15
    if sssi:
        score -= 20
    return max(0, score)


def compute_terrain_score(flood: bool, mean_slope_deg: float | None) -> int:
    if flood:
        return 0
    if mean_slope_deg is None:
        return 20
    if mean_slope_deg <= 5.0:
        return 40
    if mean_slope_deg <= 15.0:
        return 20
    return 5


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

_ALLOWED_OVERLAY_PATTERNS = {"AONB", "SSSI", "flood%", "greenbelt%", "heritage%"}


async def check_overlay(conn: asyncpg.Connection, layer_pattern: str, geojson: str) -> bool:
    if layer_pattern not in _ALLOWED_OVERLAY_PATTERNS:
        log.warning("Rejected unknown overlay pattern: %s", layer_pattern)
        return False
    return await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1 FROM overlays
            WHERE layer_name ILIKE $1
              AND ST_Intersects(geometry, ST_SetSRID(ST_GeomFromGeoJSON($2), 27700))
        )
        """,
        layer_pattern,
        geojson,
    )


async def fetch_slope_stats(conn: asyncpg.Connection, geojson: str) -> dict[str, Any] | None:
    try:
        row = await conn.fetchrow(
            """
            WITH geom AS (
                SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 27700) AS g
            )
            SELECT (ST_SummaryStatsAgg(ST_Clip(d.rast, geom.g), 1, TRUE)).*
            FROM dem_slope d, geom
            WHERE ST_Intersects(d.rast, geom.g)
            """,
            geojson,
        )
    except asyncpg.PostgresError:
        return None
    if row is None or row["count"] is None or row["count"] == 0:
        return None
    return {
        "count": row["count"],
        "mean": float(row["mean"]) if row["mean"] is not None else None,
        "stddev": float(row["stddev"]) if row["stddev"] is not None else None,
        "min": float(row["min"]) if row["min"] is not None else None,
        "max": float(row["max"]) if row["max"] is not None else None,
    }


async def fetch_slope_histogram(conn: asyncpg.Connection, geojson: str, bins: int = 10) -> list[dict[str, float]] | None:
    try:
        rows = await conn.fetch(
            """
            WITH geom AS (
                SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 27700) AS g
            ),
            merged AS (
                SELECT ST_Union(ST_Clip(d.rast, geom.g)) AS rast
                FROM dem_slope d, geom
                WHERE ST_Intersects(d.rast, geom.g)
            )
            SELECT (h).min AS bin_min, (h).max AS bin_max, (h).count AS px_count,
                   (h).percent AS pct
            FROM merged, LATERAL unnest(ST_Histogram(rast, 1, $2)) AS h
            """,
            geojson,
            bins,
        )
    except asyncpg.PostgresError:
        return None
    if not rows:
        return None
    return [
        {
            "min": float(r["bin_min"]),
            "max": float(r["bin_max"]),
            "count": int(r["px_count"]),
            "percent": float(r["pct"]),
        }
        for r in rows
    ]


async def fetch_mean_slope(conn: asyncpg.Connection, geojson: str) -> float | None:
    try:
        return await conn.fetchval(
            """
            WITH geom AS (
                SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 27700) AS g
            )
            SELECT (ST_SummaryStatsAgg(ST_Clip(d.rast, geom.g), 1, TRUE)).mean
            FROM dem_slope d, geom
            WHERE ST_Intersects(d.rast, geom.g)
            """,
            geojson,
        )
    except asyncpg.PostgresError:
        return None


async def fetch_parcel_context(parcel_id: UUID, conn: asyncpg.Connection) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        SELECT p.parcel_id,
               p.area_m2,
               p.nearest_substation_id,
               p.distance_to_sub_km,
               p.nearest_sub_capacity_kw,
               s.name AS sub_name,
               ST_AsGeoJSON(p.geometry) AS geometry_geojson
        FROM parcels p
        LEFT JOIN dno_substations s ON s.sub_id = p.nearest_substation_id
        WHERE p.parcel_id = $1
        """,
        parcel_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Parcel not found")

    geojson = row["geometry_geojson"]
    if geojson is None:
        raise HTTPException(status_code=500, detail="Parcel geometry missing")

    aonb = await check_overlay(conn, "AONB", geojson)
    sssi = await check_overlay(conn, "SSSI", geojson)
    flood = await check_overlay(conn, "flood%", geojson)
    mean_slope = await fetch_mean_slope(conn, geojson)

    cap_kw = float(row["nearest_sub_capacity_kw"]) if row["nearest_sub_capacity_kw"] is not None else None
    dist_km = float(row["distance_to_sub_km"]) if row["distance_to_sub_km"] is not None else None

    grid_score = compute_grid_score(cap_kw, dist_km)
    planning_score = compute_planning_score(aonb, sssi)
    terrain_score = compute_terrain_score(flood, mean_slope)

    score_components = {
        "grid": grid_score,
        "planning": planning_score,
        "terrain": terrain_score,
    }
    score_total = sum(score_components.values())

    return {
        "parcel_id": str(row["parcel_id"]),
        "area_m2": float(row["area_m2"]) if row["area_m2"] is not None else None,
        "nearest_substation": {
            "id": row["nearest_substation_id"],
            "name": row["sub_name"],
            "capacity_kw": cap_kw,
            "distance_km": dist_km,
        },
        "score_components": score_components,
        "score_total": score_total,
        "overlays": [
            f"FloodZone:{'YES' if flood else 'NO'}",
            f"AONB:{'YES' if aonb else 'NO'}",
            f"SSSI:{'YES' if sssi else 'NO'}",
        ],
        "mean_slope_deg": float(mean_slope) if mean_slope is not None else None,
    }


# ---------------------------------------------------------------------------
# Claude integration
# ---------------------------------------------------------------------------

async def explain_with_claude(claude_client, context: dict[str, Any]) -> str:
    score = context["score_total"]
    message = await claude_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=400,
        temperature=0.0,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Context:\n{json.dumps(context, indent=2)}\n\n"
                    f"Task: In up to 150 words, explain why this parcel scores "
                    f"{score} and list the top 3 mitigations to improve feasibility.\n"
                    f"Constraints: Only reference fields present in the context above. "
                    f"Do not invent numbers. If a dataset is missing, say "
                    f'"data missing: [field]".'
                ),
            }
        ],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Subprocess runners
# ---------------------------------------------------------------------------

async def run_sam_subprocess(
    lat: float, lon: float, capacity_kw: float,
    tilt: float = 25.0, azimuth: float = 180.0, losses: float = 14.0,
) -> dict[str, Any]:
    cmd = [
        SAM_PYTHON, SAM_RUNNER,
        "--lat", str(lat),
        "--lon", str(lon),
        "--capacity_kw", str(capacity_kw),
        "--tilt", str(tilt),
        "--azimuth", str(azimuth),
        "--losses", str(losses),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"SAM simulation failed: {stderr.decode()[:500]}",
        )
    return json.loads(stdout.decode())


async def run_geeflow_subprocess(
    mode: str, lat: float, lon: float,
    radius_km: float = 5.0, year: int = 2024, timeout: int = 300,
) -> dict[str, Any]:
    if not GEE_PROJECT:
        raise HTTPException(
            status_code=500,
            detail="GEE_PROJECT not configured — set in .env",
        )
    cmd = [
        GEEFLOW_PYTHON, GEEFLOW_RUNNER,
        "--mode", mode,
        "--lat", str(lat),
        "--lon", str(lon),
        "--radius_km", str(radius_km),
        "--year", str(year),
        "--gee_project", GEE_PROJECT,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"GeeFlow extraction failed: {stderr.decode()[:500]}",
        )
    return json.loads(stdout.decode())


async def run_geoai_subprocess(
    mode: str, lat: float, lon: float,
    radius_km: float = 2.0, asset_type: str = "solar_farm",
    year_before: int = 2020, year_after: int = 2024,
    timeout: int = 120,
    **extra_args,
) -> dict[str, Any]:
    cmd = [
        GEOAI_PYTHON, GEOAI_RUNNER,
        "--mode", mode,
        "--lat", str(lat),
        "--lon", str(lon),
        "--radius_km", str(radius_km),
        "--asset_type", asset_type,
        "--year_before", str(year_before),
        "--year_after", str(year_after),
    ]
    for key, val in extra_args.items():
        if val is not None and val != "":
            cmd.extend([f"--{key}", str(val)])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"GeoAI analysis failed: {stderr.decode()[:500]}",
        )
    return json.loads(stdout.decode())


async def _run_forecast_subprocess(payload: dict, script: str = None) -> dict:
    proc = await asyncio.create_subprocess_exec(
        FORECAST_PYTHON, script or DEMAND_FORECAST_SCRIPT,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    raw_in = json.dumps(payload).encode()
    stdout, stderr = await asyncio.wait_for(proc.communicate(raw_in), timeout=120)
    return json.loads(stdout)


async def _run_generic_subprocess(script: str, payload: dict, timeout: int = 60) -> dict:
    """Run a utility subprocess that reads JSON from stdin and writes JSON to stdout."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, script,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    raw_in = json.dumps(payload).encode()
    stdout, stderr = await asyncio.wait_for(proc.communicate(raw_in), timeout=timeout)
    return json.loads(stdout)


# ---------------------------------------------------------------------------
# GeeFlow caching
# ---------------------------------------------------------------------------

async def geeflow_with_cache(
    pool, mode: str, lat: float, lon: float, radius_km: float = 5.0,
    year: int = 2024, parcel_id: str | None = None,
) -> dict[str, Any]:
    ttl_days = {"land_use": 30, "vegetation": 30, "terrain": 90, "solar_resource": 7}
    ttl = ttl_days.get(mode, 30)

    async with pool.acquire() as conn:
        cached = await conn.fetchrow(
            """
            SELECT result_data FROM geeflow_extractions
            WHERE mode = $1
              AND abs(lat - $2) < 0.01 AND abs(lon - $3) < 0.01
              AND radius_km = $4
              AND created_at > NOW() - make_interval(days => $5::int)
            ORDER BY created_at DESC LIMIT 1
            """,
            mode, lat, lon, float(radius_km), ttl,
        )
        if cached:
            return json.loads(cached["result_data"]) if isinstance(cached["result_data"], str) else cached["result_data"]

    result = await run_geeflow_subprocess(mode, lat, lon, radius_km, year)

    pid = None
    if parcel_id:
        try:
            pid = UUID(parcel_id)
        except ValueError:
            pass

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO geeflow_extractions (parcel_id, lat, lon, radius_km, mode, result_data, geometry)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb,
                    ST_Buffer(ST_SetSRID(ST_MakePoint($7, $8), 4326)::geography, $9)::geometry)
            """,
            pid, lat, lon, float(radius_km), mode, json.dumps(result),
            lon, lat, float(radius_km) * 1000,
        )

    return result


# ---------------------------------------------------------------------------
# Tile helpers
# ---------------------------------------------------------------------------

_EMPTY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\xdac\xf8\x0f"
    b"\x00\x01\x01\x01\x00\x18\xdd\x02\xa6\x00\x00\x00\x00IEND\xaeB`\x82"
)


def tile_xyz_to_bbox(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    n = 2.0 ** z
    lon_left = x / n * 360.0 - 180.0
    lon_right = (x + 1) / n * 360.0 - 180.0
    lat_top = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_bottom = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return (lon_left, lat_bottom, lon_right, lat_top)


def _compute_satellite_tile(lat: float, lon: float, zoom: int = 17) -> dict:
    n = 2 ** zoom
    tx = int((lon + 180) / 360 * n)
    ty = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return {
        "url": f"https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{zoom}/{ty}/{tx}",
        "zoom": zoom,
        "tile_x": tx,
        "tile_y": ty,
        "bbox": {
            "west": tx / n * 360 - 180,
            "east": (tx + 1) / n * 360 - 180,
            "north": math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n)))),
            "south": math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + 1) / n)))),
        },
    }


def _compute_sun_paths(lat: float, lon: float) -> dict:
    paths = {}
    for label, day_of_year in [("summer", 172), ("winter", 355), ("equinox", 80)]:
        hourly = []
        decl = 23.45 * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
        for hour in range(5, 21):
            hour_angle = 15 * (hour - 12)
            sin_alt = (math.sin(math.radians(lat)) * math.sin(math.radians(decl)) +
                       math.cos(math.radians(lat)) * math.cos(math.radians(decl)) *
                       math.cos(math.radians(hour_angle)))
            altitude = math.degrees(math.asin(max(-1, min(1, sin_alt))))
            cos_az = ((math.sin(math.radians(decl)) -
                        math.sin(math.radians(lat)) * sin_alt) /
                       max(0.001, math.cos(math.radians(lat)) * math.cos(math.radians(altitude))))
            azimuth = math.degrees(math.acos(max(-1, min(1, cos_az))))
            if hour_angle > 0:
                azimuth = 360 - azimuth
            if altitude > 0:
                hourly.append({"hour": hour, "altitude": round(altitude, 1), "azimuth": round(azimuth, 1)})
        paths[label] = hourly
    return paths


# ---------------------------------------------------------------------------
# Deterministic RNG
# ---------------------------------------------------------------------------

def _seed_for(key: str, extra: int = 0) -> random.Random:
    return random.Random(hashlib.md5(f"{key}-{extra}".encode()).hexdigest())


# ---------------------------------------------------------------------------
# Deterministic agent fallback
# ---------------------------------------------------------------------------

def _deterministic_agent(ctx: dict) -> dict:
    score = ctx.get("feasibility_score", 0)
    comps = ctx.get("score_components", {})
    overlays = ctx.get("overlays", [])
    sam = ctx.get("sam_physics") or {}
    ml = ctx.get("ml_prediction") or {}
    area = ctx.get("area_m2")
    slope = ctx.get("mean_slope_deg")

    if score >= 80:
        verdict, conf = "GO", 0.8
    elif score >= 40:
        verdict, conf = "CAUTION", 0.6
    else:
        verdict, conf = "NO-GO", 0.7

    risks = []
    if comps.get("grid", 0) == 0:
        risks.append("No grid connection data — substation capacity and distance unknown")
    elif comps.get("grid", 0) < 20:
        risks.append(f"Weak grid connection (score {comps['grid']}/50)")
    if "FloodZone:YES" in overlays:
        risks.append("Site is in a flood risk zone — significant planning barrier")
    if "AONB:YES" in overlays:
        risks.append("Site overlaps Area of Outstanding Natural Beauty — planning restrictions apply")
    if "SSSI:YES" in overlays:
        risks.append("Site overlaps SSSI — likely planning refusal for solar development")
    if slope and slope > 15:
        risks.append(f"Steep terrain (mean slope {slope:.1f} deg) increases installation cost")
    if sam.get("capacity_factor_pct") and sam["capacity_factor_pct"] < 9:
        risks.append(f"Low capacity factor ({sam['capacity_factor_pct']}%) — marginal solar resource")
    if not risks:
        risks.append("No major risks identified from available data")

    opps = []
    if "FloodZone:NO" in overlays and "AONB:NO" in overlays and "SSSI:NO" in overlays:
        opps.append("No environmental designations — favourable planning outlook")
    if sam.get("annual_energy_kwh"):
        opps.append(f"SAM estimates {sam['annual_energy_kwh']:,.0f} kWh/yr at {ctx.get('capacity_kw', 100)} kW")
    if ml.get("annual_estimate_kwh"):
        opps.append(f"ML model corroborates with {ml['annual_estimate_kwh']:,.0f} kWh/yr estimate")
    if area and area > 20000:
        opps.append(f"Large site ({area:,.0f} m²) can accommodate significant capacity")
    if comps.get("planning", 0) >= 25:
        opps.append("Strong planning score — no statutory designation conflicts")

    rec_cap = ctx.get("capacity_kw", 100)
    if area:
        max_cap = area * 0.01
        rec_cap = min(rec_cap, max_cap)

    roi = None
    if sam.get("annual_energy_kwh") and rec_cap:
        annual_revenue = sam["annual_energy_kwh"] * 0.05
        install_cost = rec_cap * 800
        if annual_revenue > 0:
            roi = round(install_cost / annual_revenue, 1)

    summary = (
        f"Parcel scores {score}/120. "
        f"{'Strong' if score >= 80 else 'Moderate' if score >= 40 else 'Weak'} feasibility "
        f"with grid={comps.get('grid', 0)}, planning={comps.get('planning', 0)}, "
        f"terrain={comps.get('terrain', 0)}."
    )
    if sam.get("capacity_factor_pct"):
        summary += f" Capacity factor {sam['capacity_factor_pct']}%."

    return {
        "verdict": verdict,
        "confidence": conf,
        "summary": summary,
        "risks": risks,
        "opportunities": opps,
        "recommended_capacity_kw": round(rec_cap, 1),
        "estimated_roi_years": roi,
        "next_steps": [
            "Commission detailed grid connection study",
            "Obtain topographical survey for slope verification",
            "Submit pre-application planning enquiry to local authority",
            "Compare quotes from at least 3 EPC-accredited installers",
        ],
    }


# ---------------------------------------------------------------------------
# Simulated deferral (fallback when network_nodes table is unavailable)
# ---------------------------------------------------------------------------

def _simulated_deferral(total_load_kw: float, total_gen_kw: float) -> dict[str, dict[str, float]]:
    """Simulated network deferral when no network_nodes table exists."""
    rng = random.Random(42)
    nodes = [
        ("BSP_A", 25000), ("BSP_B", 18000), ("PRIMARY_1", 12000),
        ("PRIMARY_2", 9000), ("PRIMARY_3", 15000), ("SECONDARY_1", 5000),
        ("SECONDARY_2", 4000), ("SECONDARY_3", 6000),
    ]
    alloc = {}
    remaining_gen = total_gen_kw
    remaining_load = total_load_kw
    for name, capacity in sorted(nodes, key=lambda n: n[1], reverse=True):
        gen_share = min(remaining_gen, capacity * rng.uniform(0.05, 0.15))
        remaining_gen -= gen_share
        alloc[name] = {"load_kw": 0.0, "gen_kw": round(gen_share, 1), "capacity_kw": capacity}
    if remaining_gen > 0:
        per = remaining_gen / len(nodes)
        for n in alloc:
            alloc[n]["gen_kw"] = round(alloc[n]["gen_kw"] + per, 1)
    for name, capacity in sorted(nodes, key=lambda n: n[1]):
        load_share = min(remaining_load, capacity * rng.uniform(0.03, 0.08))
        remaining_load -= load_share
        alloc[name]["load_kw"] = round(load_share, 1)
    if remaining_load > 0:
        per = remaining_load / len(nodes)
        for n in alloc:
            alloc[n]["load_kw"] = round(alloc[n]["load_kw"] + per, 1)
    return alloc


# ---------------------------------------------------------------------------
# Vision deep findings aggregation
# ---------------------------------------------------------------------------

def _aggregate_deep_findings(mode_results: dict) -> dict:
    score = 65
    notes = []

    bf = mode_results.get("building_footprints", {})
    if isinstance(bf, dict) and not bf.get("error"):
        count = bf.get("building_count", bf.get("count", 0))
        if count > 20:
            score -= 10
            notes.append(f"Dense buildings detected ({count})")
        elif count < 5:
            score += 5
            notes.append("Low building density — clear site")

    lc = mode_results.get("land_cover", {})
    if isinstance(lc, dict) and not lc.get("error"):
        dom = lc.get("dominant_class", "")
        if "crop" in dom.lower() or "grass" in dom.lower():
            score += 5
            notes.append(f"Favourable land cover: {dom}")
        elif "forest" in dom.lower() or "tree" in dom.lower():
            score -= 8
            notes.append(f"Forested area may require clearing: {dom}")

    ch = mode_results.get("canopy_height", {})
    if isinstance(ch, dict) and not ch.get("error"):
        avg_h = ch.get("mean_height_m", ch.get("avg_height", 0))
        if avg_h > 10:
            score -= 5
            notes.append(f"Tall canopy ({avg_h:.1f}m avg) — shading risk")

    infra = mode_results.get("infrastructure_detect", {})
    if isinstance(infra, dict) and not infra.get("error"):
        detections = infra.get("detections", [])
        if any(d.get("type") == "substation" for d in detections if isinstance(d, dict)):
            score += 5
            notes.append("Substation detected nearby — grid access advantage")

    score = max(0, min(100, score))
    verdict = "GO" if score >= 65 else "CAUTION" if score >= 40 else "NO-GO"
    return {
        "suitability_score": score,
        "verdict": verdict,
        "notes": notes,
        "modes_completed": [m for m in mode_results if not (isinstance(mode_results[m], dict) and mode_results[m].get("error"))],
    }
