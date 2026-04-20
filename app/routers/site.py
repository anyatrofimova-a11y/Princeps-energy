"""Site-specific endpoints — parcel creation, context, slope, solar, grid, BOM, agent, workflow, BIPV."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import math
import os
import subprocess
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import UUID

import anthropic
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel

from app.deps import get_pool, get_claude

# ── External utility imports ────────────────────────────────────────────────
from utils.ml_solar_predictor import predict_24h as ml_predict_24h
from utils.energy_price_forecast import (
    predict_24h as price_predict_24h,
    estimate_revenue,
)
from utils.uk_grid_analysis import full_grid_context
from utils.solar_inventory import (
    generate_site_bom,
    repository_stock,
    check_bom_availability,
    SOLAR_CATALOGUE,
)
from utils.grid_data_platform import (
    find_nearest_substation as gdp_nearest_sub,
    substations_in_radius,
    connection_cost_estimate,
    record_metric,
)
from utils.bipv_calculator import (
    bipv_24h_profile,
    bipv_annual_estimate,
    bipv_multi_surface,
)
from utils.uk_energy_scenario import site_in_national_context
from utils.infrastructure_retrofit import (
    INFRASTRUCTURE_TYPES as RETROFIT_INFRA_TYPES,
    STORAGE_TECHNOLOGIES as RETROFIT_STORAGE_TECHS,
)
from agent_claude import get_structured_agent_output

# Agent / workflow (sibling modules in app/)
import sys as _sys

_app_dir = os.path.dirname(os.path.dirname(__file__))
if _app_dir not in _sys.path:
    _sys.path.insert(0, _app_dir)

from app.agent import (
    run_structured_agent,
    INTENT_PROMPTS,
    _default_actions,
    AgentOutput,
)
from app.workflows import WORKFLOW_PRESETS, stream_workflow

log = logging.getLogger("princeps.site")

# ── Configuration (mirrors main.py constants) ──────────────────────────────
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
MAPBOX_TOKEN = os.environ.get("VITE_MAPBOX_TOKEN", os.environ.get("MAPBOX_TOKEN", ""))

_project_root = Path(__file__).resolve().parent.parent.parent  # feasibly/
_sam_default = str(_project_root / ".venv-sam" / "bin" / "python")
SAM_PYTHON = os.environ.get("SAM_PYTHON", _sam_default)
SAM_RUNNER = str((_project_root / "utils" / "sam_runner.py").resolve())
_sam_path = Path(SAM_PYTHON).absolute()
SAM_PYTHON = str(_sam_path)

_geeflow_default = str(Path(__file__).resolve().parent.parent / ".venv-geeflow" / "bin" / "python")
GEEFLOW_PYTHON = os.environ.get("GEEFLOW_PYTHON", _geeflow_default)
GEEFLOW_RUNNER = str((Path(__file__).resolve().parent.parent / "utils" / "geeflow_runner.py").resolve())
GEE_PROJECT = os.environ.get("GEE_PROJECT", "")
_geeflow_path = Path(GEEFLOW_PYTHON).absolute()
GEEFLOW_PYTHON = str(_geeflow_path)

# ── Real site context (REPD, OSM, grid, TEC) ─────────────────────────────
from utils.real_site_context import get_real_site_context

# ── Pydantic models ────────────────────────────────────────────────────────


class SiteExplanation(BaseModel):
    explanation: str
    score_total: float
    context: dict[str, Any]


class LocationInput(BaseModel):
    lat: float
    lon: float
    area_m2: float = 50000.0  # default 5 hectares


class CustomLayoutRequest(BaseModel):
    layout: list[dict[str, Any]]


class MultiSurfaceRequest(BaseModel):
    surfaces: list[dict[str, Any]]
    module_type: str = "mono_roof_tile"


class ParcelContext(BaseModel):
    parcel_id: str
    bbox_27700: list  # [minx, miny, maxx, maxy]
    notes: str = ""


class AgentRequest(BaseModel):
    intent: str = "feasibility"
    capacity_kw: float = 100.0
    day_of_year: int = 172
    notes: str = ""


class WorkflowRequest(BaseModel):
    preset: str = "full_feasibility"
    capacity_kw: float = 100.0
    day_of_year: int = 172


# ── Scoring helpers ─────────────────────────────────────────────────────────


def compute_grid_score(capacity_kw: float | None, distance_km: float | None) -> int:
    """Grid connection score (0-50). Higher capacity and shorter distance are better."""
    if capacity_kw is None or distance_km is None:
        return 0
    cap_score = min(50.0, max(0.0, (capacity_kw / 1000.0) * 10))
    dist_penalty = min(30.0, max(0.0, distance_km * 2))
    return max(0, int(cap_score - dist_penalty + 20))


def compute_planning_score(aonb: bool, sssi: bool) -> int:
    """Planning score (0-30). Statutory designations penalise heavily."""
    score = 30
    if aonb:
        score -= 15
    if sssi:
        score -= 20
    return max(0, score)


def compute_terrain_score(flood: bool, mean_slope_deg: float | None) -> int:
    """Terrain score (0-40). Flood zone is a hard fail; slope degrades score."""
    if flood:
        return 0
    if mean_slope_deg is None:
        return 20  # no slope data — conservative middle
    if mean_slope_deg <= 5.0:
        return 40
    if mean_slope_deg <= 15.0:
        return 20
    return 5


# ── Database helpers ────────────────────────────────────────────────────────

_ALLOWED_OVERLAY_PATTERNS = {"AONB", "SSSI", "flood%", "greenbelt%", "heritage%"}


async def check_overlay(conn: asyncpg.Connection, layer_pattern: str, geojson: str) -> bool:
    """Check if a parcel geometry intersects a named overlay layer."""
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


async def fetch_slope_stats(
    conn: asyncpg.Connection, geojson: str
) -> dict[str, Any] | None:
    """Full slope summary stats (count, mean, stddev, min, max) for a parcel."""
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


async def fetch_slope_histogram(
    conn: asyncpg.Connection, geojson: str, bins: int = 10
) -> list[dict[str, float]] | None:
    """Slope histogram for a parcel. Unions clipped tiles first so ST_Histogram sees one raster."""
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
    """Mean slope (degrees) over parcel, clipped from dem_slope raster table."""
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
        return None  # raster table missing or postgis_raster not enabled


async def fetch_parcel_context(parcel_id: UUID, conn: asyncpg.Connection) -> dict[str, Any]:
    """Build deterministic context JSON for a single parcel."""
    row = await conn.fetchrow(
        """
        SELECT p.parcel_id,
               p.area_m2,
               p.nearest_substation_id,
               p.distance_to_sub_km,
               p.nearest_sub_capacity_kw,
               COALESCE(d.name, o.name, n.name, p.nearest_substation_id) AS sub_name,
               ST_AsGeoJSON(p.geometry) AS geometry_geojson
        FROM parcels p
        LEFT JOIN dno_substations d ON d.sub_id = p.nearest_substation_id
        LEFT JOIN osm_power_substation o ON o.osm_id::text = p.nearest_substation_id
        LEFT JOIN nged_substation n ON n.id::text = p.nearest_substation_id
        WHERE p.parcel_id = $1
        """,
        parcel_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Parcel not found")

    geojson = row["geometry_geojson"]
    if geojson is None:
        raise HTTPException(status_code=500, detail="Parcel geometry missing")

    # Overlay intersection checks + slope
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


# ── Claude integration ──────────────────────────────────────────────────────


async def explain_with_claude(claude, context: dict[str, Any]) -> str:
    """Send deterministic context to Claude; return its explanation text."""
    score = context["score_total"]
    message = await claude.messages.create(
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


# ── Subprocess runners ──────────────────────────────────────────────────────


async def run_sam_subprocess(
    lat: float, lon: float, capacity_kw: float,
    tilt: float = 25.0, azimuth: float = 180.0, losses: float = 14.0,
) -> dict[str, Any]:
    """Run SAM PvWattsv8 in a subprocess (needs separate Python 3.11 venv)."""
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


# ── Tile helpers ────────────────────────────────────────────────────────────

# 1x1 transparent PNG fallback
_EMPTY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\xdac\xf8\x0f"
    b"\x00\x01\x01\x01\x00\x18\xdd\x02\xa6\x00\x00\x00\x00IEND\xaeB`\x82"
)


def tile_xyz_to_bbox(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    """Convert XYZ tile coordinates to (minlon, minlat, maxlon, maxlat) in EPSG:4326."""
    n = 2.0 ** z
    lon_left = x / n * 360.0 - 180.0
    lon_right = (x + 1) / n * 360.0 - 180.0
    lat_top = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_bottom = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return (lon_left, lat_bottom, lon_right, lat_top)


def _compute_satellite_tile(lat: float, lon: float, zoom: int = 17) -> dict:
    """Compute ArcGIS World Imagery tile coords for a lat/lon centre point."""
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


# ── Deterministic agent fallback ───────────────────────────────────────────


def _deterministic_agent(ctx: dict) -> dict:
    """Rule-based agent fallback when Claude API is unavailable."""
    score = ctx.get("feasibility_score", 0)
    comps = ctx.get("score_components", {})
    overlays = ctx.get("overlays", [])
    sub = ctx.get("nearest_substation", {})
    sam = ctx.get("sam_physics") or {}
    ml = ctx.get("ml_prediction") or {}
    area = ctx.get("area_m2")
    slope = ctx.get("mean_slope_deg")

    # Verdict
    if score >= 80:
        verdict, conf = "GO", 0.8
    elif score >= 40:
        verdict, conf = "CAUTION", 0.6
    else:
        verdict, conf = "NO-GO", 0.7

    # Risks
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

    # Opportunities
    opps = []
    if "FloodZone:NO" in overlays and "AONB:NO" in overlays and "SSSI:NO" in overlays:
        opps.append("No environmental designations — favourable planning outlook")
    if sam.get("annual_energy_kwh"):
        opps.append(f"SAM estimates {sam['annual_energy_kwh']:,.0f} kWh/yr at {ctx.get('capacity_kw', 100)} kW")
    if ml.get("annual_estimate_kwh"):
        opps.append(f"ML model corroborates with {ml['annual_estimate_kwh']:,.0f} kWh/yr estimate")
    if area and area > 20000:
        opps.append(f"Large site ({area:,.0f} m\u00b2) can accommodate significant capacity")
    if comps.get("planning", 0) >= 25:
        opps.append("Strong planning score — no statutory designation conflicts")

    # Recommended capacity
    rec_cap = ctx.get("capacity_kw", 100)
    if area:
        # ~10 W/m2 for ground-mount solar
        max_cap = area * 0.01  # kW
        rec_cap = min(rec_cap, max_cap)

    # ROI estimate
    roi = None
    if sam.get("annual_energy_kwh") and rec_cap:
        # UK export tariff ~5p/kWh, install cost ~800/kW
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


# ═══════════════════════════════════════════════════════════════════════════
# Router
# ═══════════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["site"])


# ---------------------------------------------------------------------------
# Location picker — create parcel from map click
# ---------------------------------------------------------------------------


@router.post("/site/from-location")
async def create_from_location(
    body: LocationInput,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Create a parcel from clicked map coordinates (WGS84 lat/lon).
    Builds a square polygon in EPSG:27700 centred on the point.
    Returns the new parcel_id for use with all other endpoints.
    """
    side = (body.area_m2 ** 0.5)  # square side in metres
    half = side / 2.0

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            WITH pt AS (
                SELECT ST_Transform(
                    ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700
                ) AS geom
            ),
            poly AS (
                SELECT ST_MakeEnvelope(
                    ST_X(pt.geom) - $3, ST_Y(pt.geom) - $3,
                    ST_X(pt.geom) + $3, ST_Y(pt.geom) + $3,
                    27700
                ) AS geom,
                pt.geom AS centroid
                FROM pt
            )
            INSERT INTO parcels (source, area_m2, geometry, centroid)
            SELECT 'map_pick', $4, poly.geom, poly.centroid
            FROM poly
            RETURNING parcel_id::text,
                      ST_Y(ST_Transform(centroid, 4326)) AS lat,
                      ST_X(ST_Transform(centroid, 4326)) AS lon
            """,
            body.lon,
            body.lat,
            half,
            body.area_m2,
        )

        # Compute nearest substation from NGED (2,059 named substations with voltage)
        parcel_4326 = await conn.fetchval(
            "SELECT ST_Transform(centroid, 4326) FROM parcels WHERE parcel_id = $1::uuid",
            UUID(row["parcel_id"]),
        )
        if parcel_4326:
            nearest = await conn.fetchrow(
                """SELECT id::text AS sub_id, name,
                          ST_Distance(geometry::geography, $1::geography) / 1000.0 AS dist_km,
                          voltage_kv
                   FROM nged_substation
                   ORDER BY geometry <-> $1
                   LIMIT 1""",
                parcel_4326,
            )
            if nearest:
                await conn.execute(
                    """UPDATE parcels
                       SET nearest_substation_id = $2,
                           distance_to_sub_km = $3,
                           nearest_sub_capacity_kw = NULL
                       WHERE parcel_id = $1::uuid""",
                    UUID(row["parcel_id"]),
                    nearest["sub_id"],
                    float(nearest["dist_km"]),
                )

    return {
        "parcel_id": row["parcel_id"],
        "lat": float(row["lat"]),
        "lon": float(row["lon"]),
        "area_m2": body.area_m2,
    }


# ---------------------------------------------------------------------------
# Real site context — REPD, OSM power, grid substations, ESO TEC
# ---------------------------------------------------------------------------


@router.get("/api/site/real-context")
async def real_site_context(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5, ge=0.5, le=50),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Real data context for 3D twin enrichment.

    Queries REPD renewable projects, OSM power infrastructure,
    UK DNO grid substations, and ESO TEC queue within radius of a point.
    """
    return await get_real_site_context(pool, lat, lon, radius_km)


# ---------------------------------------------------------------------------
# Explain / Context
# ---------------------------------------------------------------------------


@router.get("/site/{parcel_id}/explain", response_model=SiteExplanation)
async def explain_site(
    parcel_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    claude=Depends(get_claude),
):
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        context = await fetch_parcel_context(pid, conn)
        try:
            explanation = await explain_with_claude(claude, context)
        except (anthropic.APIError, json.JSONDecodeError, KeyError) as exc:
            log.warning("Claude explanation failed, using deterministic fallback: %s", exc)
            sc = context["score_components"]
            explanation = (
                f"Score: {context['score_total']}/120 "
                f"(grid: {sc['grid']}/50, planning: {sc['planning']}/30, terrain: {sc['terrain']}/40). "
                f"Overlays: {', '.join(context.get('overlays', []))}. "
                f"Mean slope: {context.get('mean_slope_deg', 'N/A')}. "
                f"Mitigations: 1) Identify nearest substation for grid score. "
                f"2) Obtain DEM data for terrain analysis. "
                f"3) Submit pre-app planning enquiry."
            )

        await conn.execute(
            """
            INSERT INTO audit_log (actor, action, target_type, target_id, details)
            VALUES ($1, $2, $3, $4, $5)
            """,
            "api",
            "claude_explain",
            "parcel",
            parcel_id,
            json.dumps(context),
        )

    return SiteExplanation(
        explanation=explanation,
        score_total=context["score_total"],
        context=context,
    )


@router.get("/site/{parcel_id}/context")
async def get_context(
    parcel_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return raw scored context without calling Claude (useful for debugging)."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        return await fetch_parcel_context(pid, conn)


# ---------------------------------------------------------------------------
# Slope stats
# ---------------------------------------------------------------------------


@router.get("/site/{parcel_id}/slope_stats")
async def slope_stats(
    parcel_id: str,
    fmt: str = Query("json", alias="format", pattern="^(json|csv)$"),
    bins: int = Query(10, ge=2, le=100),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Slope raster statistics and histogram for a parcel (JSON or CSV)."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT ST_AsGeoJSON(geometry) AS geojson FROM parcels WHERE parcel_id = $1",
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")
        geojson = row["geojson"]
        if geojson is None:
            raise HTTPException(status_code=500, detail="Parcel geometry missing")

        stats = await fetch_slope_stats(conn, geojson)
        histogram = await fetch_slope_histogram(conn, geojson, bins)

    if stats is None:
        # Simulated terrain when no DEM raster is loaded
        import random
        rng = random.Random(hash(parcel_id))
        mean_slope = rng.uniform(2.0, 12.0)
        std_slope = rng.uniform(1.0, 4.0)
        min_slope = max(0, mean_slope - 2 * std_slope)
        max_slope = mean_slope + 2.5 * std_slope
        stats = {
            "count": rng.randint(800, 4000),
            "mean": round(mean_slope, 2),
            "stddev": round(std_slope, 2),
            "min": round(min_slope, 2),
            "max": round(max_slope, 2),
        }
        # Simulated histogram
        histogram = []
        bin_width = (max_slope - min_slope) / bins
        total_px = stats["count"]
        remaining = total_px
        for i in range(bins):
            b_min = min_slope + i * bin_width
            b_max = b_min + bin_width
            # Bell-shaped distribution centred on mean
            centre = (b_min + b_max) / 2.0
            weight = math.exp(-0.5 * ((centre - mean_slope) / max(std_slope, 0.5)) ** 2)
            px = max(1, int(total_px * weight * 0.4))
            if i == bins - 1:
                px = remaining
            remaining -= px
            histogram.append({
                "min": round(b_min, 2),
                "max": round(b_max, 2),
                "count": max(0, px),
                "percent": round(max(0, px) / total_px * 100, 1),
            })

    payload = {
        "parcel_id": parcel_id,
        "stats": stats,
        "histogram": histogram,
    }

    if fmt == "csv":
        buf = StringIO()
        w = csv.writer(buf)
        w.writerow(["metric", "value"])
        for k, v in stats.items():
            w.writerow([k, v])
        if histogram:
            w.writerow([])
            w.writerow(["bin_min", "bin_max", "count", "percent"])
            for h in histogram:
                w.writerow([h["min"], h["max"], h["count"], h["percent"]])
        return PlainTextResponse(buf.getvalue(), media_type="text/csv")

    return payload


# ---------------------------------------------------------------------------
# Slope tiles
# ---------------------------------------------------------------------------


@router.get("/tiles/slope/{z}/{x}/{y}.png")
async def slope_tile(
    z: int, x: int, y: int,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Render a 256x256 PNG slope tile from dem_slope raster."""
    minlon, minlat, maxlon, maxlat = tile_xyz_to_bbox(x, y, z)

    async with pool.acquire() as conn:
        try:
            png = await conn.fetchval(
                """
                WITH bbox AS (
                    SELECT ST_Transform(
                        ST_MakeEnvelope($1, $2, $3, $4, 4326), 27700
                    ) AS geom
                ),
                clipped AS (
                    SELECT ST_Union(ST_Clip(d.rast, bbox.geom)) AS rast
                    FROM dem_slope d, bbox
                    WHERE ST_Intersects(d.rast, bbox.geom)
                ),
                resized AS (
                    SELECT ST_Resize(rast, 256, 256) AS rast FROM clipped
                    WHERE rast IS NOT NULL
                )
                SELECT ST_AsPNG(rast) FROM resized
                """,
                minlon,
                minlat,
                maxlon,
                maxlat,
            )
        except asyncpg.PostgresError:
            return Response(content=_EMPTY_PNG, media_type="image/png")

    if not png:
        return Response(content=_EMPTY_PNG, media_type="image/png")
    return Response(content=bytes(png), media_type="image/png")


# ---------------------------------------------------------------------------
# Heightmap
# ---------------------------------------------------------------------------


@router.get("/site/{parcel_id}/heightmap")
async def site_heightmap(
    parcel_id: str,
    size: int = Query(128, ge=8, le=256),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return a size x size grid of elevation values (from dem_elev) clipped to the parcel."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT ST_AsGeoJSON(geometry) AS geojson,
                      ST_Y(ST_Transform(centroid, 4326)) AS lat,
                      ST_X(ST_Transform(centroid, 4326)) AS lon
               FROM parcels WHERE parcel_id = $1""",
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")
        geojson = row["geojson"]
        if geojson is None:
            raise HTTPException(status_code=500, detail="Parcel geometry missing")
        lat, lon = float(row["lat"]), float(row["lon"])

        try:
            result = await conn.fetchrow(
                """
                WITH geom AS (
                    SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 27700) AS g
                ),
                clipped AS (
                    SELECT ST_Union(ST_Clip(d.rast, geom.g)) AS rast
                    FROM dem_elev d, geom
                    WHERE ST_Intersects(d.rast, geom.g)
                ),
                resized AS (
                    SELECT ST_Resize(rast, $2, $2) AS rast FROM clipped
                    WHERE rast IS NOT NULL
                )
                SELECT (ST_DumpValues(rast, 1)).valarray AS vals,
                       ST_Width(rast) AS width,
                       ST_Height(rast) AS height,
                       Box2D(ST_Envelope(rast))::text AS bbox
                FROM resized
                """,
                geojson,
                size,
            )
        except asyncpg.PostgresError:
            result = None

    source = None
    vals = None

    if result and result.get("vals") is not None:
        source = "DEM 2m"
        vals = result["vals"]
        width, height = result["width"], result["height"]
        bbox = result["bbox"]
    else:
        # Fallback 1: GeeFlow NASADEM elevation grid
        try:
            if GEE_PROJECT:
                cmd = [
                    GEEFLOW_PYTHON, GEEFLOW_RUNNER,
                    "--mode", "elevation_grid",
                    "--lat", str(lat), "--lon", str(lon),
                    "--radius_km", "0.5",
                    "--grid_size", str(size),
                    "--gee_project", GEE_PROJECT,
                ]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
                if proc.returncode == 0:
                    gee_data = json.loads(stdout.decode())
                    if gee_data.get("values") and not gee_data.get("error"):
                        source = "NASADEM 30m"
                        vals = gee_data["values"]
                        width = gee_data.get("width", size)
                        height = gee_data.get("height", size)
        except Exception as e:
            log.warning("GeeFlow elevation_grid fallback failed: %s", e)

    if vals is None:
        # Fallback 2: synthetic heightmap
        import random
        source = "Synthetic"
        rng = random.Random(hash(parcel_id))
        base_elev = rng.uniform(20, 150)
        slope_x = rng.uniform(-0.3, 0.3)
        slope_y = rng.uniform(-0.3, 0.3)
        vals = []
        for r in range(size):
            row_vals = []
            for c in range(size):
                elev = base_elev + slope_x * (c - size / 2) + slope_y * (r - size / 2)
                elev += rng.gauss(0, 1.5)
                row_vals.append(round(elev, 1))
            vals.append(row_vals)
        width, height = size, size

    # Satellite tile for terrain texture
    satellite_tile = _compute_satellite_tile(lat, lon)

    return {
        "parcel_id": parcel_id,
        "width": width,
        "height": height,
        "values": vals,
        "source": source,
        "lat": lat,
        "lon": lon,
        "satellite_tile": satellite_tile,
    }


# ---------------------------------------------------------------------------
# SAM solar yield estimation (PvWattsv8 via subprocess)
# ---------------------------------------------------------------------------


@router.get("/site/{parcel_id}/solar_yield")
async def solar_yield(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    tilt: float = Query(25.0, ge=0, le=90),
    azimuth: float = Query(180.0, ge=0, le=360),
    losses: float = Query(14.0, ge=0, le=50),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Estimate annual solar yield for a parcel using NREL SAM PvWattsv8.
    Returns energy output, capacity factor, and monthly breakdown.
    """
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon,
                   area_m2
            FROM parcels WHERE parcel_id = $1
            """,
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")

        lat = float(row["lat"]) if row["lat"] is not None else 52.5
        lon = float(row["lon"]) if row["lon"] is not None else -1.5

        result = await run_sam_subprocess(lat, lon, capacity_kw, tilt, azimuth, losses)

        # Strip hourly data from stored result (too large for JSON response)
        summary = {k: v for k, v in result.items() if k != "hourly_gen_kw"}
        summary["parcel_id"] = parcel_id
        if row["area_m2"]:
            area_m2 = float(row["area_m2"])
            summary["yield_kwh_per_m2"] = round(result["annual_energy_kwh"] / area_m2, 2) if area_m2 > 0 else None

        # Store simulation result
        await conn.execute(
            """
            INSERT INTO solar_simulations
                (parcel_id, capacity_kw, tilt_deg, azimuth_deg, losses_pct,
                 annual_energy_kwh, capacity_factor_pct, monthly_kwh)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            pid,
            capacity_kw,
            tilt,
            azimuth,
            losses,
            result["annual_energy_kwh"],
            result["capacity_factor_pct"],
            json.dumps(result.get("monthly_energy_kwh", [])),
        )

    return summary


@router.get("/site/{parcel_id}/solar_hourly")
async def solar_hourly(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    tilt: float = Query(25.0, ge=0, le=90),
    azimuth: float = Query(180.0, ge=0, le=360),
    day_of_year: int = Query(172, ge=1, le=365, description="Day of year for 24h profile"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return a 24-hour generation profile for a specific day of year."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon
            FROM parcels WHERE parcel_id = $1
            """,
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")

        lat = float(row["lat"]) if row["lat"] is not None else 52.5
        lon = float(row["lon"]) if row["lon"] is not None else -1.5

    result = await run_sam_subprocess(lat, lon, capacity_kw, tilt, azimuth)

    # Extract 24h for requested day
    start = (day_of_year - 1) * 24
    end = start + 24
    hourly = result.get("hourly_gen_kw", [])
    day_profile = hourly[start:end] if len(hourly) >= end else []

    return {
        "parcel_id": parcel_id,
        "day_of_year": day_of_year,
        "hourly_kw": day_profile,
        "daily_total_kwh": round(sum(day_profile), 2),
    }


# ---------------------------------------------------------------------------
# ML solar prediction (GBM trained on weather features)
# ---------------------------------------------------------------------------


@router.get("/site/{parcel_id}/solar_yield_ml")
async def solar_yield_ml(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    day_of_year: int = Query(172, ge=1, le=365),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    ML-based solar energy prediction using weather features.
    Complements the SAM physics model with a data-driven approach.
    """
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon
            FROM parcels WHERE parcel_id = $1
            """,
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")

        lat = float(row["lat"]) if row["lat"] is not None else 52.5
        lon = float(row["lon"]) if row["lon"] is not None else -1.5

    try:
        result = ml_predict_24h(lat, lon, day_of_year, capacity_kw)
        result["parcel_id"] = parcel_id
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ---------------------------------------------------------------------------
# Energy price forecast (XGBoost, from Perrupi/energy-price-forecast)
# ---------------------------------------------------------------------------


@router.get("/site/{parcel_id}/energy_price")
async def energy_price_forecast(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    day_of_year: int = Query(172, ge=1, le=365),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Forecast 24h UK day-ahead electricity prices and estimate solar revenue.
    Combines XGBoost price model with SAM/ML solar output for the site.
    """
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon
            FROM parcels WHERE parcel_id = $1
            """,
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")
        lat = float(row["lat"]) if row["lat"] is not None else 52.5

    # Get price forecast
    price_result = price_predict_24h(day_of_year=day_of_year, lat=lat)

    # Get solar output for revenue calculation
    try:
        solar_result = ml_predict_24h(lat, -1.5, day_of_year, capacity_kw)
        solar_hourly_data = solar_result.get("hourly_kwh", [0] * 24)
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("ML solar prediction failed for revenue calc: %s", exc)
        solar_hourly_data = [0] * 24

    # Calculate revenue
    revenue = estimate_revenue(solar_hourly_data, price_result["hourly_price_gbp"])

    return {
        "parcel_id": parcel_id,
        "day_of_year": day_of_year,
        "price": price_result,
        "revenue": revenue,
    }


# ---------------------------------------------------------------------------
# Site-specific grid context
# ---------------------------------------------------------------------------


@router.get("/site/{parcel_id}/grid_context")
async def site_grid_context(
    parcel_id: str,
    day_of_year: int = Query(172, ge=1, le=365),
    capacity_kw: float = Query(100.0, ge=1, le=100000),
):
    """
    Grid context with site-specific curtailment and demand impact analysis.
    Combines national grid data with parcel solar output.
    """
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    ctx = full_grid_context(day_of_year)

    # Add site-specific data: what fraction of demand this site meets
    demand_profile = ctx["demand"]["hourly_demand_mw"]
    site_mw = capacity_kw / 1000.0
    site_pct_of_grid = [
        round(site_mw / max(d, 1) * 100, 6)
        for d in demand_profile
    ]
    ctx["site"] = {
        "parcel_id": parcel_id,
        "capacity_kw": capacity_kw,
        "capacity_mw": round(site_mw, 3),
        "pct_of_grid_demand": site_pct_of_grid,
    }

    return ctx


# ---------------------------------------------------------------------------
# EPC summary (simulated)
# ---------------------------------------------------------------------------


@router.get("/site/{parcel_id}/epc_summary")
async def simulated_epc_summary(parcel_id: str):
    """
    Simulated EPC summary for a parcel location.
    Returns typical UK neighbourhood EPC distribution data.
    """
    import random
    rng = random.Random(hash(parcel_id))

    # Realistic UK EPC distribution (based on national averages)
    total = rng.randint(150, 600)
    epc_weights = [0.02, 0.10, 0.30, 0.35, 0.15, 0.06, 0.02]  # A-G
    epc_counts = [max(0, int(total * w + rng.gauss(0, total * 0.02))) for w in epc_weights]

    # Building types
    type_weights = {"house_detached": 0.22, "house_semi": 0.25, "house_midterrace": 0.12,
                    "house_endterrace": 0.08, "flat": 0.20, "bungalow_detached": 0.08,
                    "maisonette": 0.04, "parkhome": 0.01}
    type_counts = {k: max(0, int(total * v + rng.gauss(0, 3))) for k, v in type_weights.items()}

    # Component ratings (Very Good / Good / Average / Poor / Very Poor)
    def rating_dist():
        weights = [0.08, 0.25, 0.40, 0.20, 0.07]
        return [max(0, int(total * w + rng.gauss(0, total * 0.03))) for w in weights]

    # Fuel types
    fuel = {
        "mainsgas": int(total * rng.uniform(0.70, 0.85)),
        "electric": int(total * rng.uniform(0.08, 0.15)),
        "oil": int(total * rng.uniform(0.03, 0.08)),
        "lpg": int(total * rng.uniform(0.01, 0.04)),
        "biomass": int(total * rng.uniform(0.005, 0.02)),
    }

    # Solar PV uptake
    pv_yes = int(total * rng.uniform(0.04, 0.12))

    wall = rating_dist()
    roof = rating_dist()
    heat = rating_dist()
    window = rating_dist()

    return {
        "lsoa": f"SIM_{parcel_id[:8]}",
        "total_properties": total,
        "epc_A": epc_counts[0], "epc_B": epc_counts[1], "epc_C": epc_counts[2],
        "epc_D": epc_counts[3], "epc_E": epc_counts[4], "epc_F": epc_counts[5],
        "epc_G": epc_counts[6],
        "type_house_detached": type_counts["house_detached"],
        "type_house_semi": type_counts["house_semi"],
        "type_house_midterrace": type_counts["house_midterrace"],
        "type_house_endterrace": type_counts["house_endterrace"],
        "type_flat": type_counts["flat"],
        "type_bungalow_detached": type_counts["bungalow_detached"],
        "type_maisonette": type_counts["maisonette"],
        "type_parkhome": type_counts["parkhome"],
        "wall_verygood": wall[0], "wall_good": wall[1], "wall_average": wall[2],
        "wall_poor": wall[3], "wall_verypoor": wall[4],
        "roof_verygood": roof[0], "roof_good": roof[1], "roof_average": roof[2],
        "roof_poor": roof[3], "roof_verypoor": roof[4],
        "mainheat_verygood": heat[0], "mainheat_good": heat[1], "mainheat_average": heat[2],
        "mainheat_poor": heat[3], "mainheat_verypoor": heat[4],
        "window_verygood": window[0], "window_good": window[1], "window_average": window[2],
        "window_poor": window[3], "window_verypoor": window[4],
        "mainfuel_mainsgas": fuel["mainsgas"], "mainfuel_electric": fuel["electric"],
        "mainfuel_oil": fuel["oil"], "mainfuel_lpg": fuel["lpg"],
        "mainfuel_biomass": fuel["biomass"],
        "solarpv_yes": pv_yes, "solarpv_no": total - pv_yes,
        "epc_score_avg": round(rng.uniform(55, 72), 1),
    }


# ---------------------------------------------------------------------------
# Grid connection
# ---------------------------------------------------------------------------


@router.get("/site/{parcel_id}/grid/connection")
async def site_grid_connection(
    parcel_id: str,
    capacity_kw: float = Query(100, ge=1),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Full grid connection analysis for a site — nearest substation + cost estimate."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon
            FROM parcels WHERE parcel_id = $1
            """,
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")
        lat = float(row["lat"]) if row["lat"] is not None else 52.5
        lon = float(row["lon"]) if row["lon"] is not None else -1.5

    nearest = gdp_nearest_sub(lat, lon)
    nearby = substations_in_radius(lat, lon, radius_km=30)

    # Determine connection voltage based on capacity
    if capacity_kw > 5000:
        voltage_kv = 132
    elif capacity_kw > 500:
        voltage_kv = 33
    else:
        voltage_kv = 11

    cost = connection_cost_estimate(
        nearest["distance_km"] if nearest else 5.0,
        capacity_kw,
        voltage_kv,
    )

    # Record metric
    record_metric("grid_connection_query", capacity_kw,
                  labels={"parcel_id": parcel_id})

    return {
        "parcel_id": parcel_id,
        "location": {"lat": lat, "lon": lon},
        "nearest_substation": nearest,
        "nearby_substations": nearby[:5],
        "connection_estimate": cost,
    }


# ---------------------------------------------------------------------------
# BOM (Bill of Materials)
# ---------------------------------------------------------------------------


@router.get("/site/{parcel_id}/bom")
async def site_bom(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    mount_type: str = Query("ground_fixed"),
    include_battery: bool = Query(False),
    battery_hours: float = Query(2.0, ge=0.5, le=8),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Generate a Bill of Materials for a solar site.
    Auto-sizes panels, inverters, cables, transformers, and monitoring.
    """
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    # Get site area
    area_m2 = None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT area_m2 FROM parcels WHERE parcel_id = $1", pid
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")
        if row["area_m2"]:
            area_m2 = float(row["area_m2"])

    bom = generate_site_bom(capacity_kw, area_m2, mount_type, include_battery, battery_hours)
    bom["parcel_id"] = parcel_id
    return bom


@router.get("/site/{parcel_id}/bom/availability")
async def site_bom_availability(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    mount_type: str = Query("ground_fixed"),
    include_battery: bool = Query(False),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Check BOM component availability across regional repositories.
    Shows which items are in stock, partial, or need ordering.
    """
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    # Get site location and area
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT area_m2,
                   ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon
            FROM parcels WHERE parcel_id = $1
            """,
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")
        area_m2 = float(row["area_m2"]) if row["area_m2"] else None
        lat = float(row["lat"]) if row["lat"] else 52.0
        lon = float(row["lon"]) if row["lon"] else -1.5

    bom = generate_site_bom(capacity_kw, area_m2, mount_type, include_battery)
    stock = repository_stock(lat, lon)
    avail = check_bom_availability(bom["bom"], stock)
    avail["parcel_id"] = parcel_id
    avail["nearest_repository"] = stock[0]["name"] if stock else None
    avail["nearest_distance_km"] = stock[0]["distance_km"] if stock else None
    return avail


@router.post("/site/{parcel_id}/bom/custom")
async def custom_bom(parcel_id: str, req: CustomLayoutRequest):
    """Generate BOM and cost summary from a user's manual component layout."""
    try:
        UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    # Aggregate quantities per component
    counts: dict[str, int] = {}
    for item in req.layout:
        cid = item.get("componentId", "")
        qty = item.get("quantity", 1)
        counts[cid] = counts.get(cid, 0) + qty

    bom = []
    total_cost = 0.0
    total_weight = 0.0
    for comp_id, qty in counts.items():
        comp = next((c for c in SOLAR_CATALOGUE if c["id"] == comp_id), None)
        if not comp:
            continue
        cost = comp["unit_cost_gbp"] * qty
        weight = comp.get("weight_kg", 0) * qty
        total_cost += cost
        total_weight += weight
        bom.append({
            "component_id": comp["id"],
            "name": comp["name"],
            "category": comp["category"],
            "quantity": qty,
            "unit": comp["unit"],
            "unit_cost_gbp": comp["unit_cost_gbp"],
            "total_cost_gbp": round(cost, 2),
            "total_weight_kg": round(weight, 1),
        })

    categories: dict[str, dict] = {}
    for item in bom:
        cat = item["category"]
        if cat not in categories:
            categories[cat] = {"items": [], "subtotal_gbp": 0, "subtotal_weight_kg": 0}
        categories[cat]["items"].append(item)
        categories[cat]["subtotal_gbp"] = round(categories[cat]["subtotal_gbp"] + item["total_cost_gbp"], 2)
        categories[cat]["subtotal_weight_kg"] = round(categories[cat]["subtotal_weight_kg"] + item["total_weight_kg"], 1)

    return {
        "parcel_id": parcel_id,
        "layout_item_count": len(req.layout),
        "unique_components": len(counts),
        "bom": bom,
        "categories": categories,
        "totals": {
            "total_cost_gbp": round(total_cost, 2),
            "total_weight_kg": round(total_weight, 1),
            "component_count": len(bom),
        },
    }


# ---------------------------------------------------------------------------
# Layout persistence
# ---------------------------------------------------------------------------


@router.post("/site/{parcel_id}/layout/save")
async def save_layout(
    parcel_id: str,
    req: CustomLayoutRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Persist component layout to database."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO site_layouts (parcel_id, layout_data, updated_at)
            VALUES ($1, $2::jsonb, NOW())
            ON CONFLICT (parcel_id) DO UPDATE
            SET layout_data = $2::jsonb, updated_at = NOW()
        """, pid, json.dumps(req.layout))

    return {"ok": True, "parcel_id": parcel_id, "items": len(req.layout)}


@router.get("/site/{parcel_id}/layout")
async def get_layout(
    parcel_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Retrieve saved layout for a parcel."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT layout_data FROM site_layouts WHERE parcel_id = $1", pid
        )

    if not row:
        return {"layout": []}
    return {"layout": json.loads(row["layout_data"])}


# ---------------------------------------------------------------------------
# Energy system context (2050 scenario)
# ---------------------------------------------------------------------------


@router.get("/site/{parcel_id}/energy_system_context")
async def site_energy_system_context(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    renewable_gw: float = Query(200.0, ge=50, le=600),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Place a site in the national 2050 energy system context.
    Shows contribution to demand, solar capacity, CO2 reduction.
    """
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    # Try to get site-specific capacity factor from SAM, default to national avg
    site_cf = 0.108
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT capacity_factor_pct FROM solar_simulations
            WHERE parcel_id = $1 ORDER BY created_at DESC LIMIT 1
            """,
            pid,
        )
        if row and row["capacity_factor_pct"]:
            site_cf = float(row["capacity_factor_pct"]) / 100.0

    return site_in_national_context(capacity_kw, site_cf, renewable_gw)


# ---------------------------------------------------------------------------
# BIPV (Building-Integrated PV)
# ---------------------------------------------------------------------------


@router.get("/site/{parcel_id}/bipv/profile")
async def bipv_profile(
    parcel_id: str,
    date: str = Query("2025-06-21"),
    area_m2: float = Query(100.0),
    module_type: str = Query("mono_roof_tile"),
    surface_type: str = Query("pitched_roof_south"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """24-hour BIPV power profile for a site."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon
            FROM parcels WHERE parcel_id = $1
            """,
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")
        lat = float(row["lat"]) if row["lat"] is not None else 52.5
        lon = float(row["lon"]) if row["lon"] is not None else -1.5

    profile = bipv_24h_profile(lat, lon, date, area_m2,
                               module_type=module_type, surface_type=surface_type)
    return {"parcel_id": parcel_id, "date": date, **profile}


@router.get("/site/{parcel_id}/bipv/annual")
async def bipv_annual(
    parcel_id: str,
    area_m2: float = Query(100.0),
    module_type: str = Query("mono_roof_tile"),
    surface_type: str = Query("pitched_roof_south"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Annual BIPV generation estimate with financial projections."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon
            FROM parcels WHERE parcel_id = $1
            """,
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")
        lat = float(row["lat"]) if row["lat"] is not None else 52.5
        lon = float(row["lon"]) if row["lon"] is not None else -1.5

    result = bipv_annual_estimate(lat, lon, area_m2,
                                  module_type=module_type, surface_type=surface_type)
    return {"parcel_id": parcel_id, **result}


@router.post("/site/{parcel_id}/bipv/multi_surface")
async def bipv_multi(
    parcel_id: str,
    body: MultiSurfaceRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Analyse multiple building surfaces for BIPV potential."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon
            FROM parcels WHERE parcel_id = $1
            """,
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")
        lat = float(row["lat"]) if row["lat"] is not None else 52.5
        lon = float(row["lon"]) if row["lon"] is not None else -1.5

    result = bipv_multi_surface(lat, lon, body.surfaces, module_type=body.module_type)
    return {"parcel_id": parcel_id, **result}


# ---------------------------------------------------------------------------
# Agentic analysis — orchestrates all models + Claude reasoning
# ---------------------------------------------------------------------------


@router.get("/site/{parcel_id}/agent_analysis")
async def agent_analysis(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    day_of_year: int = Query(172, ge=1, le=365),
    pool: asyncpg.Pool = Depends(get_pool),
    claude=Depends(get_claude),
):
    """
    Comprehensive agentic analysis: gathers context, SAM, ML, slope
    in parallel, then sends everything to Claude for structured reasoning.
    """
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    # Step 1: Gather parcel location + context (sequential — asyncpg single-conn)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon,
                   area_m2
            FROM parcels WHERE parcel_id = $1
            """,
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")
        lat = float(row["lat"]) if row["lat"] is not None else 52.5
        lon = float(row["lon"]) if row["lon"] is not None else -1.5
        area_m2 = float(row["area_m2"]) if row["area_m2"] else None

        context = await fetch_parcel_context(pid, conn)

        geojson_row = await conn.fetchrow(
            "SELECT ST_AsGeoJSON(geometry) AS geojson FROM parcels WHERE parcel_id = $1", pid
        )
        geojson = geojson_row["geojson"] if geojson_row else "{}"
        slope_stats_data = await fetch_slope_stats(conn, geojson)

    # SAM + ML run concurrently outside the DB connection
    async def _safe_sam():
        try:
            return await run_sam_subprocess(lat, lon, capacity_kw)
        except (OSError, asyncio.TimeoutError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            log.warning("SAM subprocess failed for agent_analysis: %s", exc)
            return None

    async def _safe_ml():
        try:
            return ml_predict_24h(lat, lon, day_of_year, capacity_kw)
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("ML prediction failed for agent_analysis: %s", exc)
            return None

    sam_result, ml_result = await asyncio.gather(_safe_sam(), _safe_ml())

    # Step 3: Build comprehensive context for Claude
    agent_context = {
        "parcel_id": parcel_id,
        "location": {"lat": lat, "lon": lon},
        "area_m2": area_m2,
        "feasibility_score": context.get("score_total"),
        "score_components": context.get("score_components"),
        "overlays": context.get("overlays"),
        "mean_slope_deg": context.get("mean_slope_deg"),
        "slope_stats": slope_stats_data,
        "nearest_substation": context.get("nearest_substation"),
        "sam_physics": {
            "annual_energy_kwh": sam_result.get("annual_energy_kwh") if sam_result else None,
            "capacity_factor_pct": sam_result.get("capacity_factor_pct") if sam_result else None,
            "monthly_energy_kwh": sam_result.get("monthly_energy_kwh") if sam_result else None,
        } if sam_result else None,
        "ml_prediction": {
            "daily_total_kwh": ml_result.get("daily_total_kwh") if ml_result else None,
            "annual_estimate_kwh": ml_result.get("annual_estimate_kwh") if ml_result else None,
        } if ml_result else None,
        "capacity_kw": capacity_kw,
    }

    # Step 4: Send to Claude for agentic reasoning
    try:
        message = await claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            temperature=0.0,
            messages=[{
                "role": "user",
                "content": (
                    f"You are a solar energy feasibility analyst. Analyse this parcel data "
                    f"and return a JSON object with these exact fields:\n"
                    f'{{"verdict": "GO|CAUTION|NO-GO",'
                    f'"confidence": 0.0-1.0,'
                    f'"summary": "2-3 sentence assessment",'
                    f'"risks": ["risk1", "risk2", ...],'
                    f'"opportunities": ["opp1", "opp2", ...],'
                    f'"recommended_capacity_kw": number,'
                    f'"estimated_roi_years": number or null,'
                    f'"next_steps": ["step1", "step2", ...]}}\n\n'
                    f"Only output valid JSON. Use the data below — do not invent numbers.\n\n"
                    f"Data:\n{json.dumps(agent_context, indent=2)}"
                ),
            }],
        )
        raw_text = message.content[0].text
        # Extract and validate JSON from response
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            raw_parsed = json.loads(raw_text[start:end])
            agent_output = AgentOutput(**raw_parsed).model_dump()
        else:
            agent_output = {"verdict": "CAUTION", "summary": raw_text, "confidence": 0.5}
    except (anthropic.APIError, json.JSONDecodeError, KeyError) as exc:
        log.warning("Claude agent_analysis failed, using deterministic fallback: %s", exc)
        agent_output = _deterministic_agent(agent_context)

    return {
        "parcel_id": parcel_id,
        "context": agent_context,
        "agent": agent_output,
    }


# ---------------------------------------------------------------------------
# VIBE pipeline + Claude agent positioning
# ---------------------------------------------------------------------------


@router.post("/site/{parcel_id}/positioning")
async def site_positioning(
    parcel_id: str,
    body: ParcelContext,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Run ingestion (optional) and ask Claude to position the parcel.
    Returns the validated JSON from the agent.
    """
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    try:
        # 1) Optionally fetch VIBE DEM for the parcel and produce slope tiles
        out_dir = os.environ.get("DATA_DIR", "/tmp/feasi_data")
        dem_raw = os.path.join(out_dir, f"{parcel_id}_raw.tif")
        dem_clipped = os.path.join(out_dir, f"{parcel_id}_dem_27700.tif")
        slope_tif = os.path.join(out_dir, f"{parcel_id}_slope.tif")
        tiles_dir = os.path.join(out_dir, "tiles", parcel_id)

        # Example fetch; uncomment when VIBE endpoint is configured
        # fetch_vibe_raster("DEM", body.bbox_27700, dem_raw)
        # clip_and_reproject(dem_raw, dem_clipped, body.bbox_27700)
        # compute_slope(dem_clipped, slope_tif)
        # generate_tiles(slope_tif, tiles_dir)

        # 2) Collect structured context from existing DB helpers
        async with pool.acquire() as conn:
            db_context = await fetch_parcel_context(pid, conn)
            slope_stats_data = await fetch_slope_stats(
                conn, (await conn.fetchval(
                    "SELECT ST_AsGeoJSON(geometry) FROM parcels WHERE parcel_id = $1", pid
                )) or "{}"
            )

        context = {
            "parcel_id": parcel_id,
            "terrain": {
                "mean_slope_deg": db_context.get("mean_slope_deg"),
                "std_slope_deg": slope_stats_data["stddev"] if slope_stats_data else None,
                "max_slope_deg": slope_stats_data["max"] if slope_stats_data else None,
            },
            "solar_resource": {
                "ghi_annual_kwh_m2": None,  # populate from SAM or external source
                "dni": None,
            },
            "grid": {
                "nearest_substation_km": db_context["nearest_substation"]["distance_km"],
                "headroom_kw": db_context["nearest_substation"]["capacity_kw"],
            },
            "overlays": {
                "flood_risk": "FloodZone:YES" in db_context.get("overlays", []),
                "protected_area": (
                    "AONB:YES" in db_context.get("overlays", [])
                    or "SSSI:YES" in db_context.get("overlays", [])
                ),
            },
            "score": db_context.get("score_total"),
            "score_components": db_context.get("score_components"),
            "notes": body.notes or "",
        }

        # 3) Ask Claude agent for a positioning recommendation
        agent_output = get_structured_agent_output(context)
        return {"ok": True, "agent": agent_output}

    except HTTPException:
        raise
    except (asyncpg.PostgresError, anthropic.APIError, json.JSONDecodeError, OSError) as e:
        log.exception("positioning failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Enhanced agentic analysis — intent-based with structured actions
# ---------------------------------------------------------------------------


@router.post("/site/{parcel_id}/agent")
async def enhanced_agent(
    parcel_id: str,
    body: AgentRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    claude=Depends(get_claude),
):
    """
    Intent-based agentic analysis using Claude with structured output.
    Returns verdict, confidence, risks, opportunities, next_steps, and
    actionable endpoint suggestions.
    """
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    if body.intent not in INTENT_PROMPTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown intent '{body.intent}'. Valid: {list(INTENT_PROMPTS.keys())}",
        )

    # Gather context (reuse existing helpers)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon,
                   area_m2
            FROM parcels WHERE parcel_id = $1
            """,
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")
        lat = float(row["lat"]) if row["lat"] is not None else 52.5
        lon = float(row["lon"]) if row["lon"] is not None else -1.5
        area_m2 = float(row["area_m2"]) if row["area_m2"] else None

        context = await fetch_parcel_context(pid, conn)
        geojson_row = await conn.fetchrow(
            "SELECT ST_AsGeoJSON(geometry) AS geojson FROM parcels WHERE parcel_id = $1", pid
        )
        geojson = geojson_row["geojson"] if geojson_row else "{}"
        slope_stats_data = await fetch_slope_stats(conn, geojson)

    # SAM + ML run concurrently
    async def _safe_sam():
        try:
            return await run_sam_subprocess(lat, lon, body.capacity_kw)
        except (OSError, asyncio.TimeoutError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            log.warning("SAM failed for enhanced agent: %s", exc)
            return None

    async def _safe_ml():
        try:
            return ml_predict_24h(lat, lon, body.day_of_year, body.capacity_kw)
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("ML prediction failed for enhanced agent: %s", exc)
            return None

    sam_result, ml_result = await asyncio.gather(_safe_sam(), _safe_ml())

    agent_context = {
        "parcel_id": parcel_id,
        "intent": body.intent,
        "location": {"lat": lat, "lon": lon},
        "area_m2": area_m2,
        "feasibility_score": context.get("score_total"),
        "score_components": context.get("score_components"),
        "overlays": context.get("overlays"),
        "mean_slope_deg": context.get("mean_slope_deg"),
        "slope_stats": slope_stats_data,
        "nearest_substation": context.get("nearest_substation"),
        "sam_physics": {
            "annual_energy_kwh": sam_result.get("annual_energy_kwh") if sam_result else None,
            "capacity_factor_pct": sam_result.get("capacity_factor_pct") if sam_result else None,
            "monthly_energy_kwh": sam_result.get("monthly_energy_kwh") if sam_result else None,
        } if sam_result else None,
        "ml_prediction": {
            "daily_total_kwh": ml_result.get("daily_total_kwh") if ml_result else None,
            "annual_estimate_kwh": ml_result.get("annual_estimate_kwh") if ml_result else None,
        } if ml_result else None,
        "capacity_kw": body.capacity_kw,
        "notes": body.notes,
    }

    # Vision AI context enrichment — inject latest vision analysis if available
    try:
        async with pool.acquire() as conn_v:
            vision_row = await conn_v.fetchrow("""
                SELECT suitability_score, verdict, findings, domain_contributions, analysis_tier
                FROM vision_analyses
                WHERE parcel_id = $1
                ORDER BY created_at DESC LIMIT 1
            """, pid)
            if vision_row:
                agent_context["vision_analysis"] = {
                    "suitability_score": vision_row["suitability_score"],
                    "verdict": vision_row["verdict"],
                    "tier": vision_row["analysis_tier"],
                    "findings": json.loads(vision_row["findings"]) if vision_row["findings"] else None,
                    "domain_contributions": json.loads(vision_row["domain_contributions"]) if vision_row["domain_contributions"] else None,
                }
    except Exception as exc:
        log.debug("Vision context lookup skipped: %s", exc)

    # Intent-specific context enrichment
    if body.intent == "infrastructure_retrofit":
        async with pool.acquire() as conn2:
            nearby = await conn2.fetch("""
                SELECT asset_id, name, asset_type, capacity_kw, condition_score,
                       ST_X(ST_Transform(geometry, 4326)) as lon,
                       ST_Y(ST_Transform(geometry, 4326)) as lat
                FROM legacy_assets
                WHERE ST_DWithin(geometry,
                    ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700), 25000)
                ORDER BY name LIMIT 20
            """, lon, lat)
            agent_context["nearby_legacy_assets"] = [
                {"name": r["name"], "type": r["asset_type"],
                 "capacity_kw": r["capacity_kw"], "condition": r["condition_score"]}
                for r in nearby
            ]
        agent_context["infrastructure_types"] = list(RETROFIT_INFRA_TYPES.keys())
        agent_context["storage_technologies"] = list(RETROFIT_STORAGE_TECHS.keys())

    try:
        agent_output = await run_structured_agent(
            client=claude,
            model=CLAUDE_MODEL,
            context=agent_context,
            intent=body.intent,
            pool=pool,
        )
    except (anthropic.APIError, json.JSONDecodeError, KeyError) as exc:
        log.warning("Structured agent failed, using deterministic fallback: %s", exc)
        agent_output = _deterministic_agent(agent_context)
        agent_output["intent"] = body.intent
        agent_output["actions"] = _default_actions(body.intent, agent_context)

    return {
        "parcel_id": parcel_id,
        "intent": body.intent,
        "context": agent_context,
        "agent": agent_output,
    }


# ---------------------------------------------------------------------------
# Chained Workflows — multi-step agent analysis as a single SSE stream
# ---------------------------------------------------------------------------


@router.post("/site/{parcel_id}/workflow")
async def run_workflow(
    parcel_id: str,
    body: WorkflowRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    claude=Depends(get_claude),
):
    """
    Run a chained agent workflow as an SSE stream.
    Each step's result is compacted and passed as context to the next step.
    """
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    if body.preset not in WORKFLOW_PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset '{body.preset}'. Valid: {list(WORKFLOW_PRESETS.keys())}",
        )

    # Gather base context (same as agent endpoint)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon,
                   area_m2
            FROM parcels WHERE parcel_id = $1
            """,
            pid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")
        lat = float(row["lat"]) if row["lat"] is not None else 52.5
        lon = float(row["lon"]) if row["lon"] is not None else -1.5
        area_m2 = float(row["area_m2"]) if row["area_m2"] else None

        context = await fetch_parcel_context(pid, conn)
        geojson_row = await conn.fetchrow(
            "SELECT ST_AsGeoJSON(geometry) AS geojson FROM parcels WHERE parcel_id = $1", pid
        )
        geojson = geojson_row["geojson"] if geojson_row else "{}"
        slope_stats_data = await fetch_slope_stats(conn, geojson)

    # SAM + ML
    async def _safe_sam():
        try:
            return await run_sam_subprocess(lat, lon, body.capacity_kw)
        except (OSError, asyncio.TimeoutError, json.JSONDecodeError, subprocess.SubprocessError):
            return None

    async def _safe_ml():
        try:
            return ml_predict_24h(lat, lon, body.day_of_year, body.capacity_kw)
        except (ValueError, KeyError, TypeError):
            return None

    sam_result, ml_result = await asyncio.gather(_safe_sam(), _safe_ml())

    base_context = {
        "parcel_id": parcel_id,
        "location": {"lat": lat, "lon": lon},
        "area_m2": area_m2,
        "feasibility_score": context.get("score_total"),
        "score_components": context.get("score_components"),
        "overlays": context.get("overlays"),
        "mean_slope_deg": context.get("mean_slope_deg"),
        "slope_stats": slope_stats_data,
        "nearest_substation": context.get("nearest_substation"),
        "sam_physics": {
            "annual_energy_kwh": sam_result.get("annual_energy_kwh") if sam_result else None,
            "capacity_factor_pct": sam_result.get("capacity_factor_pct") if sam_result else None,
            "monthly_energy_kwh": sam_result.get("monthly_energy_kwh") if sam_result else None,
        } if sam_result else None,
        "ml_prediction": {
            "daily_total_kwh": ml_result.get("daily_total_kwh") if ml_result else None,
            "annual_estimate_kwh": ml_result.get("annual_estimate_kwh") if ml_result else None,
        } if ml_result else None,
        "capacity_kw": body.capacity_kw,
    }

    # Vision context
    try:
        async with pool.acquire() as conn_v:
            vision_row = await conn_v.fetchrow("""
                SELECT suitability_score, verdict, findings, domain_contributions, analysis_tier
                FROM vision_analyses
                WHERE parcel_id = $1
                ORDER BY created_at DESC LIMIT 1
            """, pid)
            if vision_row:
                base_context["vision_analysis"] = {
                    "suitability_score": vision_row["suitability_score"],
                    "verdict": vision_row["verdict"],
                    "tier": vision_row["analysis_tier"],
                    "findings": json.loads(vision_row["findings"]) if vision_row["findings"] else None,
                    "domain_contributions": json.loads(vision_row["domain_contributions"]) if vision_row["domain_contributions"] else None,
                }
    except Exception:
        pass

    return StreamingResponse(
        stream_workflow(
            client=claude,
            model=CLAUDE_MODEL,
            base_context=base_context,
            preset_key=body.preset,
            pool=pool,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ══════════════════════════════════════════════════════════
# Real Site Context — nearby REPD, OSM, grid, TEC data
# ══════════════════════════════════════════════════════════

@router.get("/api/site/real-context")
async def real_site_context(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(5, le=20),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Real data context for 3D twin enrichment — REPD, OSM, grid, TEC."""
    from utils.real_site_context import get_real_site_context
    return await get_real_site_context(pool, lat, lon, radius_km)


# ---------------------------------------------------------------------------
# Construction planning
# ---------------------------------------------------------------------------


@router.post("/api/site/construction-plan")
async def construction_plan(body: dict):
    """
    Generate a parametric construction schedule with cost and traffic estimates.

    Request body:
        capacity_mw: float (required)
        technology: str (solar/wind/bess, default: solar)
        site_area_ha: float (optional)
        grid_distance_km: float (optional)
    """
    from utils.construction_planner import (
        generate_construction_schedule,
        estimate_construction_traffic,
    )

    capacity_mw = body.get("capacity_mw")
    if not capacity_mw or capacity_mw <= 0:
        raise HTTPException(status_code=400, detail="capacity_mw is required and must be > 0")

    technology = body.get("technology", "solar")
    site_area_ha = body.get("site_area_ha")
    grid_distance_km = body.get("grid_distance_km")

    schedule = generate_construction_schedule(
        capacity_mw=capacity_mw,
        technology=technology,
        site_area_ha=site_area_ha,
        grid_distance_km=grid_distance_km,
    )
    traffic = estimate_construction_traffic(
        capacity_mw=capacity_mw,
        technology=technology,
        site_area_ha=site_area_ha,
        grid_distance_km=grid_distance_km,
    )

    return {
        "schedule": schedule,
        "traffic": traffic,
    }


# ---------------------------------------------------------------------------
# BOT-B1 — Nearest residential receptor (OSM, no PAF licence)
# ---------------------------------------------------------------------------

@router.get("/api/site/nearest-residence")
async def site_nearest_residence(
    lat: float = Query(..., ge=49, le=61, description="Site centre latitude (WGS84)"),
    lon: float = Query(..., ge=-8, le=2, description="Site centre longitude (WGS84)"),
    radius_m: float = Query(500.0, ge=50, le=5000,
                            description="Search radius in metres."),
):
    """Return the nearest residential receptor to (lat, lon) for noise /
    setback / visual-amenity checks.

    Source: OpenStreetMap ``building`` tags (``residential``, ``apartments``,
    ``dormitory``, ``house``, ``detached``, ``semidetached_house``,
    ``terrace``, ``bungalow``, ``static_caravan``, ``farm``, ``farmhouse``,
    ``cabin``). Not authoritative — confirm before planning submission.

    Response shape::
        {
          "feature": GeoJSON Feature | null,
          "distance_m": float | null,
          "count_within_radius": int,
          "radius_m": float,
          "provenance": {...},
          "explanation": "..."
        }

    Always returns 200: on upstream failure the response carries
    ``feature=null`` and a ``synthetic_fallback`` provenance so the client
    can render an honest message instead of fabricating a receptor.
    """
    from utils.nearest_residence import nearest_residence
    return await nearest_residence(lat=lat, lon=lon, radius_m=radius_m)
