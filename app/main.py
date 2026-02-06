import asyncio
import csv
import math
import os
import json
import subprocess
from contextlib import asynccontextmanager
from io import StringIO
from typing import Any
from uuid import UUID

import sys

import anthropic
import asyncpg

# Allow importing from project root (for utils/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.deferral import greedy_allocate, store_allocations
from utils.ml_solar_predictor import predict_24h as ml_predict_24h, train_model as ml_train_model
from utils.energy_price_forecast import predict_24h as price_predict_24h, estimate_revenue, train_model as price_train_model
from utils.uk_grid_analysis import full_grid_context, demand_for_day, curtailment_risk
from utils.planning_energy import (
    setup_table as planning_setup, seed_sample_data as planning_seed,
    query_energy_applications, energy_summary, applications_geojson,
    ENERGY_CATEGORIES,
)
from utils.uk_energy_scenario import system_scenario, site_in_national_context, capacity_sweep
from utils.solar_inventory import (
    generate_site_bom, repository_stock, check_bom_availability,
    catalogue_summary, setup_inventory_table, REPOSITORIES as SOLAR_REPOS,
    SOLAR_CATALOGUE,
)
from utils.grid_data_platform import (
    UK_DATA_SOURCES, UK_SUBSTATIONS,
    find_nearest_substation as gdp_nearest_sub,
    substations_in_radius, connection_cost_estimate,
    dashboard_stats as gdp_dashboard_stats,
    health_check as gdp_health_check,
    record_metric, query_metrics,
)
from utils.bipv_calculator import (
    calculate_bipv, bipv_24h_profile, bipv_annual_estimate,
    bipv_multi_surface, bipv_catalogue, sun_position, BIPV_MODULES, SURFACE_TYPES,
)
from agent_claude import get_structured_agent_output

# Import sibling modules (app/ directory)
_app_dir = os.path.dirname(__file__)
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)
from agent import run_structured_agent, INTENT_PROMPTS, _default_actions
import jobs
from pipeline import fetch_vibe_raster, clip_and_reproject, compute_slope, generate_tiles
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

DATABASE_URL = os.environ.get("DATABASE_URL")
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")

SAM_PYTHON = os.environ.get("SAM_PYTHON", os.path.join(
    os.path.dirname(__file__), "..", ".venv-sam", "bin", "python"
))
SAM_RUNNER = os.path.join(os.path.dirname(__file__), "..", "utils", "sam_runner.py")

if not DATABASE_URL:
    raise RuntimeError("Set DATABASE_URL env var")
if not CLAUDE_API_KEY:
    raise RuntimeError("Set CLAUDE_API_KEY env var")

pool: asyncpg.Pool | None = None
claude = anthropic.AsyncAnthropic(api_key=CLAUDE_API_KEY)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    # Setup planning applications table and seed sample energy data
    async with pool.acquire() as conn:
        await planning_setup(conn)
        await planning_seed(conn)
        await setup_inventory_table(conn)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS site_layouts (
                parcel_id UUID PRIMARY KEY,
                layout_data JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    yield
    await pool.close()


app = FastAPI(title="Feasibly API", lifespan=lifespan)


class SiteExplanation(BaseModel):
    explanation: str
    score_total: float
    context: dict[str, Any]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def check_overlay(conn: asyncpg.Connection, layer_pattern: str, geojson: str) -> bool:
    """Check if a parcel geometry intersects a named overlay layer."""
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


# ---------------------------------------------------------------------------
# Claude integration
# ---------------------------------------------------------------------------

async def explain_with_claude(context: dict[str, Any]) -> str:
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


# ---------------------------------------------------------------------------
# Location picker — create parcel from map click
# ---------------------------------------------------------------------------

class LocationInput(BaseModel):
    lat: float
    lon: float
    area_m2: float = 50000.0  # default 5 hectares


@app.post("/site/from-location")
async def create_from_location(body: LocationInput):
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

    return {
        "parcel_id": row["parcel_id"],
        "lat": float(row["lat"]),
        "lon": float(row["lon"]),
        "area_m2": body.area_m2,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/site/{parcel_id}/explain", response_model=SiteExplanation)
async def explain_site(parcel_id: str):
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        context = await fetch_parcel_context(pid, conn)
        try:
            explanation = await explain_with_claude(context)
        except Exception:
            # Deterministic fallback
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


@app.get("/site/{parcel_id}/context")
async def get_context(parcel_id: str):
    """Return raw scored context without calling Claude (useful for debugging)."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="parcel_id must be a valid UUID")

    async with pool.acquire() as conn:
        return await fetch_parcel_context(pid, conn)


@app.get("/site/{parcel_id}/slope_stats")
async def slope_stats(
    parcel_id: str,
    fmt: str = Query("json", alias="format", pattern="^(json|csv)$"),
    bins: int = Query(10, ge=2, le=100),
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
# Tile helpers
# ---------------------------------------------------------------------------

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


@app.get("/tiles/slope/{z}/{x}/{y}.png")
async def slope_tile(z: int, x: int, y: int):
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


@app.get("/site/{parcel_id}/heightmap")
async def site_heightmap(
    parcel_id: str,
    size: int = Query(64, ge=8, le=256),
):
    """Return a size x size grid of elevation values (from dem_elev) clipped to the parcel."""
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

    if not result or result.get("vals") is None:
        # Simulated heightmap when no DEM raster is available
        import random
        rng = random.Random(hash(parcel_id))
        base_elev = rng.uniform(20, 150)
        slope_x = rng.uniform(-0.3, 0.3)
        slope_y = rng.uniform(-0.3, 0.3)
        vals = []
        for r in range(size):
            row = []
            for c in range(size):
                elev = base_elev + slope_x * (c - size/2) + slope_y * (r - size/2)
                elev += rng.gauss(0, 1.5)  # noise
                row.append(round(elev, 1))
            vals.append(row)
        return {
            "parcel_id": parcel_id,
            "width": size,
            "height": size,
            "bbox_27700": f"BOX(0 0,{size} {size})",
            "values": vals,
        }

    return {
        "parcel_id": parcel_id,
        "width": result["width"],
        "height": result["height"],
        "bbox_27700": result["bbox"],
        "values": result["vals"],
    }


# ---------------------------------------------------------------------------
# SAM solar yield estimation (PvWattsv8 via subprocess)
# ---------------------------------------------------------------------------

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


@app.get("/site/{parcel_id}/solar_yield")
async def solar_yield(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    tilt: float = Query(25.0, ge=0, le=90),
    azimuth: float = Query(180.0, ge=0, le=360),
    losses: float = Query(14.0, ge=0, le=50),
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


@app.get("/site/{parcel_id}/solar_hourly")
async def solar_hourly(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    tilt: float = Query(25.0, ge=0, le=90),
    azimuth: float = Query(180.0, ge=0, le=360),
    day_of_year: int = Query(172, ge=1, le=365, description="Day of year for 24h profile"),
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

@app.get("/site/{parcel_id}/solar_yield_ml")
async def solar_yield_ml(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    day_of_year: int = Query(172, ge=1, le=365),
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

@app.get("/site/{parcel_id}/energy_price")
async def energy_price_forecast(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    day_of_year: int = Query(172, ge=1, le=365),
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
        solar_hourly = solar_result.get("hourly_kwh", [0] * 24)
    except Exception:
        solar_hourly = [0] * 24

    # Calculate revenue
    revenue = estimate_revenue(solar_hourly, price_result["hourly_price_gbp"])

    return {
        "parcel_id": parcel_id,
        "day_of_year": day_of_year,
        "price": price_result,
        "revenue": revenue,
    }


# ---------------------------------------------------------------------------
# UK Grid context (from CarlosYazid/Energy-UK)
# ---------------------------------------------------------------------------

@app.get("/grid/context")
async def grid_context(
    day_of_year: int = Query(172, ge=1, le=365),
):
    """
    UK grid demand, embedded generation, weather, and curtailment risk
    for a given day of year. Based on 15 years of half-hourly grid data.
    """
    return full_grid_context(day_of_year)


@app.get("/site/{parcel_id}/grid_context")
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
# Network deferral optimiser (demo greedy heuristic)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Simulated EPC summary (when PBCC zone layers are unavailable)
# ---------------------------------------------------------------------------

@app.get("/site/{parcel_id}/epc_summary")
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
# Energy planning applications (from buildwithtract/planning-applications)
# ---------------------------------------------------------------------------

@app.get("/planning/energy")
async def planning_energy_apps(
    category: str = Query(None),
    status: str = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """Query energy-relevant planning applications."""
    async with pool.acquire() as conn:
        apps = await query_energy_applications(conn, category=category, status=status, limit=limit)
    # Convert dates to strings for JSON
    for app in apps:
        for k in ("submitted_date", "application_decision_date", "validated_date"):
            if app.get(k):
                app[k] = str(app[k])
    return {"applications": apps, "count": len(apps)}


@app.get("/planning/energy/summary")
async def planning_energy_summary_endpoint():
    """Summary statistics for energy planning applications."""
    async with pool.acquire() as conn:
        return await energy_summary(conn)


@app.get("/planning/energy/geojson")
async def planning_energy_geojson_endpoint(
    category: str = Query(None),
):
    """Energy planning applications as GeoJSON for map display."""
    async with pool.acquire() as conn:
        return await applications_geojson(conn, category=category)


# ---------------------------------------------------------------------------
# Solar Inventory & BOM (from Amr-Namora/Solar-System-Repositories-management)
# ---------------------------------------------------------------------------

@app.get("/inventory/catalogue")
async def inventory_catalogue():
    """Full solar component catalogue grouped by category."""
    return catalogue_summary()


@app.get("/inventory/repositories")
async def inventory_repositories():
    """List regional solar component repositories/warehouses."""
    return {"repositories": SOLAR_REPOS}


@app.get("/site/{parcel_id}/bom")
async def site_bom(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    mount_type: str = Query("ground_fixed"),
    include_battery: bool = Query(False),
    battery_hours: float = Query(2.0, ge=0.5, le=8),
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


@app.get("/site/{parcel_id}/bom/availability")
async def site_bom_availability(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    mount_type: str = Query("ground_fixed"),
    include_battery: bool = Query(False),
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


class CustomLayoutRequest(BaseModel):
    layout: list[dict[str, Any]]


@app.post("/site/{parcel_id}/bom/custom")
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


@app.post("/site/{parcel_id}/layout/save")
async def save_layout(parcel_id: str, req: CustomLayoutRequest):
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


@app.get("/site/{parcel_id}/layout")
async def get_layout(parcel_id: str):
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
# ---------------------------------------------------------------------------
# Grid Data Platform — from owen-saunders/Theridian
# ---------------------------------------------------------------------------

@app.get("/grid/data_sources")
async def list_data_sources():
    """List UK DNO and grid data sources."""
    return UK_DATA_SOURCES


@app.get("/grid/substations")
async def list_substations(
    lat: float = Query(None),
    lon: float = Query(None),
    radius_km: float = Query(50, ge=1, le=500),
    min_voltage_kv: int = Query(0, ge=0),
):
    """List UK substations, optionally filtered by proximity."""
    if lat is not None and lon is not None:
        return substations_in_radius(lat, lon, radius_km)
    subs = UK_SUBSTATIONS
    if min_voltage_kv > 0:
        subs = [s for s in subs if s["voltage_kv"] >= min_voltage_kv]
    return subs


@app.get("/grid/substations/nearest")
async def nearest_substation(
    lat: float = Query(52.5),
    lon: float = Query(-1.5),
    min_voltage_kv: int = Query(0),
):
    """Find the nearest registered UK substation."""
    result = gdp_nearest_sub(lat, lon, min_voltage_kv)
    if not result:
        raise HTTPException(status_code=404, detail="No matching substation found")
    return result


@app.get("/grid/connection_cost")
async def grid_connection_cost(
    distance_km: float = Query(2.0, ge=0.1),
    capacity_kw: float = Query(100, ge=1),
    voltage_kv: int = Query(33),
):
    """Estimate grid connection cost for a solar installation."""
    return connection_cost_estimate(distance_km, capacity_kw, voltage_kv)


@app.get("/site/{parcel_id}/grid/connection")
async def site_grid_connection(
    parcel_id: str,
    capacity_kw: float = Query(100, ge=1),
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


@app.get("/grid/dashboard")
async def grid_dashboard():
    """Grid data platform dashboard statistics."""
    from app.jobs import list_jobs
    return gdp_dashboard_stats(list_jobs())


@app.get("/grid/health")
async def grid_health():
    """Multi-component system health check."""
    return await gdp_health_check(pool)


@app.get("/grid/metrics")
async def grid_metrics(
    name: str = Query(None),
    metric_type: str = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """Query collected grid/system metrics."""
    return query_metrics(name=name, metric_type=metric_type, limit=limit)


# ---------------------------------------------------------------------------
# BIPV (Building-Integrated Photovoltaics) — from tejas-raskar/SolarBIPV
# ---------------------------------------------------------------------------

@app.get("/bipv/catalogue")
async def get_bipv_catalogue():
    """Return available BIPV module types and building surface types."""
    return bipv_catalogue()


@app.get("/bipv/sun_position")
async def get_sun_pos(
    lat: float = Query(52.5),
    lon: float = Query(-1.5),
    date: str = Query("2025-06-21"),
    time_minutes: int = Query(720, ge=0, le=1439),
):
    """Get sun altitude/azimuth for a location, date, and time."""
    from datetime import datetime as DT, timezone as TZ
    hours = time_minutes // 60
    mins = time_minutes % 60
    dt = DT(
        *map(int, date.split("-")), hours, mins, tzinfo=TZ.utc
    )
    return sun_position(lat, lon, dt)


class BIPVCalcRequest(BaseModel):
    lat: float = 52.5
    lon: float = -1.5
    date: str = "2025-06-21"
    time_minutes: int = 720
    area_m2: float = 100.0
    module_type: str = "mono_roof_tile"
    surface_type: str = "pitched_roof_south"
    shadow_factor: float | None = None
    efficiency: float | None = None


@app.post("/bipv/calculate")
async def bipv_instant(body: BIPVCalcRequest):
    """Calculate instantaneous BIPV power output."""
    from datetime import datetime as DT, timezone as TZ
    hours = body.time_minutes // 60
    mins = body.time_minutes % 60
    dt = DT(
        *map(int, body.date.split("-")), hours, mins, tzinfo=TZ.utc
    )
    return calculate_bipv(
        body.lat, body.lon, dt, body.area_m2,
        module_type=body.module_type,
        surface_type=body.surface_type,
        shadow_factor=body.shadow_factor,
        efficiency_override=body.efficiency,
    )


@app.get("/site/{parcel_id}/bipv/profile")
async def bipv_profile(
    parcel_id: str,
    date: str = Query("2025-06-21"),
    area_m2: float = Query(100.0),
    module_type: str = Query("mono_roof_tile"),
    surface_type: str = Query("pitched_roof_south"),
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


@app.get("/site/{parcel_id}/bipv/annual")
async def bipv_annual(
    parcel_id: str,
    area_m2: float = Query(100.0),
    module_type: str = Query("mono_roof_tile"),
    surface_type: str = Query("pitched_roof_south"),
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


class MultiSurfaceRequest(BaseModel):
    surfaces: list[dict[str, Any]]
    module_type: str = "mono_roof_tile"


@app.post("/site/{parcel_id}/bipv/multi_surface")
async def bipv_multi(parcel_id: str, body: MultiSurfaceRequest):
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
# UK Energy System 2050 scenario analysis (from samvanstroud/UK-Energy-Modelling)
# ---------------------------------------------------------------------------

@app.get("/energy_system/scenario")
async def energy_system_scenario(
    renewable_gw: float = Query(200.0, ge=50, le=600),
):
    """
    2050 UK energy system scenario for a given renewable capacity.
    Returns generation mix, costs, storage, carbon metrics.
    """
    return system_scenario(renewable_gw)


@app.get("/site/{parcel_id}/energy_system_context")
async def site_energy_system_context(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    renewable_gw: float = Query(200.0, ge=50, le=600),
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


@app.get("/energy_system/capacity_sweep")
async def energy_system_sweep(
    min_gw: float = Query(100, ge=50, le=400),
    max_gw: float = Query(400, ge=100, le=600),
    step_gw: float = Query(50, ge=10, le=100),
):
    """
    Sweep renewable capacity to show cost-generation trade-offs.
    """
    return {"sweep": capacity_sweep(min_gw, max_gw, step_gw)}


def _simulated_deferral(total_load_kw: float, total_gen_kw: float) -> dict[str, dict[str, float]]:
    """Simulated network deferral when no network_nodes table exists."""
    import random
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


@app.post("/opt/run")
async def run_deferral_optimizer(
    plan_name: str = Query("demo_plan"),
    load_mw: float = Query(5.0, ge=0),
    gen_mw: float = Query(4.0, ge=0),
):
    """Run greedy deferral allocator. Returns per-node load/gen allocation in kW."""
    total_load_kw = load_mw * 1000.0
    total_gen_kw = gen_mw * 1000.0
    try:
        async with pool.acquire() as conn:
            alloc = await greedy_allocate(conn, total_load_kw, total_gen_kw)
            await store_allocations(conn, plan_name, alloc)
    except Exception:
        # Simulated fallback when network tables don't exist
        alloc = _simulated_deferral(total_load_kw, total_gen_kw)
    return {
        "plan_name": plan_name,
        "total_load_kw": total_load_kw,
        "total_gen_kw": total_gen_kw,
        "allocations": alloc,
    }


# ---------------------------------------------------------------------------
# Agentic analysis — orchestrates all models + Claude reasoning
# ---------------------------------------------------------------------------

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
        opps.append(f"Large site ({area:,.0f} m²) can accommodate significant capacity")
    if comps.get("planning", 0) >= 25:
        opps.append("Strong planning score — no statutory designation conflicts")

    # Recommended capacity
    rec_cap = ctx.get("capacity_kw", 100)
    if area:
        # ~10 W/m² for ground-mount solar
        max_cap = area * 0.01  # kW
        rec_cap = min(rec_cap, max_cap)

    # ROI estimate
    roi = None
    if sam.get("annual_energy_kwh") and rec_cap:
        # UK export tariff ~5p/kWh, install cost ~£800/kW
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


@app.get("/site/{parcel_id}/agent_analysis")
async def agent_analysis(
    parcel_id: str,
    capacity_kw: float = Query(100.0, ge=1, le=100000),
    day_of_year: int = Query(172, ge=1, le=365),
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
        slope_stats = await fetch_slope_stats(conn, geojson)

    # SAM + ML can run outside the DB connection
    sam_result = None
    ml_result = None
    try:
        sam_result = await run_sam_subprocess(lat, lon, capacity_kw)
    except Exception:
        pass
    try:
        ml_result = ml_predict_24h(lat, lon, day_of_year, capacity_kw)
    except Exception:
        pass

    # Step 3: Build comprehensive context for Claude
    agent_context = {
        "parcel_id": parcel_id,
        "location": {"lat": lat, "lon": lon},
        "area_m2": area_m2,
        "feasibility_score": context.get("score_total"),
        "score_components": context.get("score_components"),
        "overlays": context.get("overlays"),
        "mean_slope_deg": context.get("mean_slope_deg"),
        "slope_stats": slope_stats,
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
        # Extract JSON from response
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            agent_output = json.loads(raw_text[start:end])
        else:
            agent_output = {"verdict": "CAUTION", "summary": raw_text, "confidence": 0.5}
    except Exception:
        # Deterministic fallback agent when Claude is unavailable
        agent_output = _deterministic_agent(agent_context)

    return {
        "parcel_id": parcel_id,
        "context": agent_context,
        "agent": agent_output,
    }


# ---------------------------------------------------------------------------
# VIBE pipeline + Claude agent positioning
# ---------------------------------------------------------------------------

class ParcelContext(BaseModel):
    parcel_id: str
    bbox_27700: list  # [minx, miny, maxx, maxy]
    notes: str = ""


@app.post("/site/{parcel_id}/positioning")
async def site_positioning(parcel_id: str, body: ParcelContext):
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
            slope_stats = await fetch_slope_stats(
                conn, (await conn.fetchval(
                    "SELECT ST_AsGeoJSON(geometry) FROM parcels WHERE parcel_id = $1", pid
                )) or "{}"
            )

        context = {
            "parcel_id": parcel_id,
            "terrain": {
                "mean_slope_deg": db_context.get("mean_slope_deg"),
                "std_slope_deg": slope_stats["stddev"] if slope_stats else None,
                "max_slope_deg": slope_stats["max"] if slope_stats else None,
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
    except Exception as e:
        logging.getLogger(__name__).exception("positioning failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Enhanced agentic analysis — intent-based with structured actions
# ---------------------------------------------------------------------------

class AgentRequest(BaseModel):
    intent: str = "feasibility"
    capacity_kw: float = 100.0
    day_of_year: int = 172
    notes: str = ""


@app.post("/site/{parcel_id}/agent")
async def enhanced_agent(parcel_id: str, body: AgentRequest):
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
        slope_stats = await fetch_slope_stats(conn, geojson)

    # SAM + ML
    sam_result = None
    ml_result = None
    try:
        sam_result = await run_sam_subprocess(lat, lon, body.capacity_kw)
    except Exception:
        pass
    try:
        ml_result = ml_predict_24h(lat, lon, body.day_of_year, body.capacity_kw)
    except Exception:
        pass

    agent_context = {
        "parcel_id": parcel_id,
        "intent": body.intent,
        "location": {"lat": lat, "lon": lon},
        "area_m2": area_m2,
        "feasibility_score": context.get("score_total"),
        "score_components": context.get("score_components"),
        "overlays": context.get("overlays"),
        "mean_slope_deg": context.get("mean_slope_deg"),
        "slope_stats": slope_stats,
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

    try:
        agent_output = await run_structured_agent(
            client=claude,
            model=CLAUDE_MODEL,
            context=agent_context,
            intent=body.intent,
        )
    except Exception:
        # Deterministic fallback
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
# Background jobs — grid study, optimisation, etc.
# ---------------------------------------------------------------------------

class GridStudyRequest(BaseModel):
    parcel_id: str
    capacity_kw: float = 100.0


@app.post("/job/grid_study")
async def start_grid_study(body: GridStudyRequest):
    """Submit a background grid connection study job."""

    async def _run_grid_study(parcel_id: str, capacity_kw: float):
        """Heavy grid study coroutine — runs SAM, deferral, and grid context."""
        try:
            pid = UUID(parcel_id)
        except ValueError:
            return {"error": "Invalid parcel_id"}

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
                return {"error": "Parcel not found"}
            lat = float(row["lat"]) if row["lat"] is not None else 52.5
            lon = float(row["lon"]) if row["lon"] is not None else -1.5
            context = await fetch_parcel_context(pid, conn)

        # Run SAM
        sam_result = None
        try:
            sam_result = await run_sam_subprocess(lat, lon, capacity_kw)
        except Exception:
            pass

        # Grid context
        grid = full_grid_context(172)

        # Deferral
        load_mw = capacity_kw / 1000
        gen_mw = capacity_kw / 1000
        try:
            async with pool.acquire() as conn:
                alloc = await greedy_allocate(conn, load_mw * 1000, gen_mw * 1000)
        except Exception:
            alloc = _simulated_deferral(load_mw * 1000, gen_mw * 1000)

        return {
            "parcel_id": parcel_id,
            "capacity_kw": capacity_kw,
            "sam": sam_result,
            "grid_context": grid,
            "deferral": alloc,
            "substation": context.get("nearest_substation"),
        }

    job = await jobs.submit(
        "grid_study", _run_grid_study, body.parcel_id, body.capacity_kw
    )
    return {"job_id": job.id, "status": job.status.value}


@app.get("/job/{job_id}")
async def get_job_status(job_id: str):
    """Poll a background job for status and results."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@app.get("/jobs")
async def list_all_jobs(kind: str = None, limit: int = 50):
    """List recent jobs, optionally filtered by kind."""
    return jobs.list_jobs(kind=kind, limit=limit)
