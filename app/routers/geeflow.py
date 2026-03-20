"""GeeFlow Earth Engine extraction, background analysis, grid context, and deferral optimizer."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.deps import get_pool

# ── External utility imports ────────────────────────────────────────────────
from utils.deferral import greedy_allocate, store_allocations
from utils.uk_grid_analysis import full_grid_context
from utils.grid_data_platform import (
    find_nearest_substation as gdp_nearest_sub,
)

import app.jobs as jobs

log = logging.getLogger("princeps.geeflow")

# ── Configuration ───────────────────────────────────────────────────────────
_geeflow_default = str(Path(__file__).resolve().parent.parent / ".venv-geeflow" / "bin" / "python")
GEEFLOW_PYTHON = os.environ.get("GEEFLOW_PYTHON", _geeflow_default)
GEEFLOW_RUNNER = str((Path(__file__).resolve().parent.parent / "utils" / "geeflow_runner.py").resolve())
GEE_PROJECT = os.environ.get("GEE_PROJECT", "")
_geeflow_path = Path(GEEFLOW_PYTHON).absolute()
GEEFLOW_PYTHON = str(_geeflow_path)


# ── Subprocess runners ──────────────────────────────────────────────────────


async def run_geeflow_subprocess(
    mode: str, lat: float, lon: float,
    radius_km: float = 5.0, year: int = 2024, timeout: int = 300,
) -> dict[str, Any]:
    """Run GeeFlow extraction in a subprocess (needs separate Python 3.12 venv)."""
    import asyncio as _aio

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
    proc = await _aio.create_subprocess_exec(
        *cmd,
        stdout=_aio.subprocess.PIPE,
        stderr=_aio.subprocess.PIPE,
    )
    stdout, stderr = await _aio.wait_for(proc.communicate(), timeout=timeout)
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"GeeFlow extraction failed: {stderr.decode()[:500]}",
        )
    return json.loads(stdout.decode())


async def geeflow_with_cache(
    pool: asyncpg.Pool,
    mode: str, lat: float, lon: float, radius_km: float = 5.0,
    year: int = 2024, parcel_id: str | None = None,
) -> dict[str, Any]:
    """Run GeeFlow extraction with PostGIS caching."""
    # Cache TTL by mode (days)
    ttl_days = {"land_use": 30, "vegetation": 30, "terrain": 90, "solar_resource": 7}
    ttl = ttl_days.get(mode, 30)

    # Check cache
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

    # Run extraction
    result = await run_geeflow_subprocess(mode, lat, lon, radius_km, year)

    # Store in cache
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


# ── Simulated deferral fallback ─────────────────────────────────────────────


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


# ── Pydantic models ─────────────────────────────────────────────────────────


class GeeFlowAnalysisRequest(BaseModel):
    lat: float
    lon: float
    radius_km: float = 5.0
    year: int = 2024
    modes: list[str] = ["land_use", "terrain", "solar_resource", "vegetation"]
    parcel_id: str | None = None


# ═══════════════════════════════════════════════════════════════════════════
# Router
# ═══════════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["geeflow"])


# ---------------------------------------------------------------------------
# GeeFlow extraction
# ---------------------------------------------------------------------------


@router.get("/geeflow/extract/{mode}")
async def geeflow_extract(
    mode: str,
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(5.0, ge=0.5, le=50),
    year: int = Query(2024, ge=2017, le=2026),
    parcel_id: str = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Extract Earth observation data for a location using GeeFlow."""
    valid_modes = ["land_use", "terrain", "solar_resource", "vegetation", "change_detection", "site_composite",
                    "sar_backscatter", "flood_risk", "ndvi_timeseries"]
    if mode not in valid_modes:
        raise HTTPException(400, f"Invalid mode. Choose from: {valid_modes}")
    return await geeflow_with_cache(pool, mode, lat, lon, radius_km, year, parcel_id)


# ---------------------------------------------------------------------------
# Background multi-mode GeeFlow analysis job
# ---------------------------------------------------------------------------


@router.post("/job/geeflow_analysis")
async def start_geeflow_analysis(
    body: GeeFlowAnalysisRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Submit a background multi-mode GeeFlow analysis job."""

    async def _run_geeflow_analysis(lat, lon, radius_km, year, modes, parcel_id):
        results = {}
        for mode in modes:
            try:
                results[mode] = await geeflow_with_cache(pool, mode, lat, lon, radius_km, year, parcel_id)
            except Exception as exc:
                log.warning("GeeFlow mode %s failed: %s", mode, exc)
                results[mode] = {"error": str(exc)[:300]}

        # Fetch grid data — nearest substation + NGED headroom
        grid_data = None
        try:
            nearest = gdp_nearest_sub(lat, lon)
            if nearest:
                grid_data = {
                    "distance_km": nearest.get("distance_km"),
                    "name": nearest.get("name"),
                    "voltage_kv": nearest.get("voltage_kv"),
                }
            # Try NGED CIM for headroom data
            async with pool.acquire() as conn:
                from utils.nged_cim import find_opportunities_near
                opp = await find_opportunities_near(conn, lat, lon, radius_km=15, min_headroom_mw=0)
                if opp.get("results"):
                    best = opp["results"][0]  # sorted by headroom DESC
                    if grid_data is None:
                        grid_data = {}
                    grid_data["headroom_mw"] = best["headroom_mw"]
                    if grid_data.get("distance_km") is None:
                        grid_data["distance_km"] = best["distance_km"]
        except Exception as exc:
            log.warning("Grid data fetch failed: %s", exc)

        # Fetch planning data — nearby energy applications
        planning_data = None
        try:
            async with pool.acquire() as conn:
                from utils.planning_energy import query_energy_applications
                # Build bbox ~10km around point
                delta = 0.1  # ~10km at UK latitudes
                bbox = (lon - delta, lat - delta, lon + delta, lat + delta)
                apps = await query_energy_applications(conn, category="solar", bbox=bbox, limit=100)
                if apps:
                    approved = sum(1 for a in apps if a.get("application_decision") in ("Approved", "Granted", "Permitted"))
                    total = len(apps)
                    planning_data = {
                        "nearby_energy_apps": total,
                        "approval_rate": approved / total if total > 0 else None,
                    }
        except Exception as exc:
            log.warning("Planning data fetch failed: %s", exc)

        # Compute site score with all available data
        from utils.geeflow_site_scorer import compute_site_score
        score = compute_site_score(
            terrain_data=results.get("terrain"),
            land_use_data=results.get("land_use"),
            solar_data=results.get("solar_resource"),
            grid_data=grid_data,
            planning_data=planning_data,
            flood_data=results.get("flood_risk"),
        )

        return {
            "lat": lat, "lon": lon, "radius_km": radius_km,
            "extractions": results,
            "grid_data": grid_data,
            "planning_data": planning_data,
            "site_score": score,
        }

    job = await jobs.submit(
        "geeflow_analysis",
        _run_geeflow_analysis,
        body.lat, body.lon, body.radius_km, body.year, body.modes, body.parcel_id,
    )
    return {"job_id": job.id, "status": job.status.value}


# ---------------------------------------------------------------------------
# Grid context (non-site-specific)
# ---------------------------------------------------------------------------


@router.get("/grid/context")
async def grid_context(
    day_of_year: int = Query(172, ge=1, le=365),
):
    """
    UK grid demand, embedded generation, weather, and curtailment risk
    for a given day of year. Based on 15 years of half-hourly grid data.
    """
    return full_grid_context(day_of_year)


# ---------------------------------------------------------------------------
# Network deferral optimiser
# ---------------------------------------------------------------------------


@router.post("/opt/run")
async def run_deferral_optimizer(
    plan_name: str = Query("demo_plan"),
    load_mw: float = Query(5.0, ge=0),
    gen_mw: float = Query(4.0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Run greedy deferral allocator. Returns per-node load/gen allocation in kW."""
    total_load_kw = load_mw * 1000.0
    total_gen_kw = gen_mw * 1000.0
    try:
        async with pool.acquire() as conn:
            alloc = await greedy_allocate(conn, total_load_kw, total_gen_kw)
            await store_allocations(conn, plan_name, alloc)
    except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
        log.info("Deferral tables unavailable, using simulation: %s", exc)
        alloc = _simulated_deferral(total_load_kw, total_gen_kw)
    return {
        "plan_name": plan_name,
        "total_load_kw": total_load_kw,
        "total_gen_kw": total_gen_kw,
        "allocations": alloc,
    }
