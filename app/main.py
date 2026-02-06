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
from agent_claude import get_structured_agent_output
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
        raise HTTPException(
            status_code=404,
            detail="No slope raster data intersects this parcel",
        )

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
        except asyncpg.PostgresError as e:
            raise HTTPException(status_code=500, detail=f"DEM extraction error: {e}")

    if not result or result["vals"] is None:
        raise HTTPException(status_code=404, detail="No DEM coverage for this parcel")

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
# Network deferral optimiser (demo greedy heuristic)
# ---------------------------------------------------------------------------

@app.post("/opt/run")
async def run_deferral_optimizer(
    plan_name: str = Query("demo_plan"),
    load_mw: float = Query(5.0, ge=0),
    gen_mw: float = Query(4.0, ge=0),
):
    """Run greedy deferral allocator. Returns per-node load/gen allocation in kW."""
    total_load_kw = load_mw * 1000.0
    total_gen_kw = gen_mw * 1000.0
    async with pool.acquire() as conn:
        alloc = await greedy_allocate(conn, total_load_kw, total_gen_kw)
        await store_allocations(conn, plan_name, alloc)
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
