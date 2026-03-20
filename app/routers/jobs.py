"""Jobs router — background job management and grid study submission."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import asyncpg

import jobs
from app.deps import get_pool
from app.helpers import (
    run_sam_subprocess, fetch_parcel_context, _simulated_deferral,
)
from utils.uk_grid_analysis import full_grid_context
from utils.deferral import greedy_allocate

log = logging.getLogger("princeps")

router = APIRouter(tags=["jobs"])


class GridStudyRequest(BaseModel):
    parcel_id: str
    capacity_kw: float = 100.0


@router.post("/job/grid_study")
async def start_grid_study(
    body: GridStudyRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
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
        except (OSError, asyncio.TimeoutError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            log.warning("SAM failed in grid study job: %s", exc)

        # Grid context
        grid = full_grid_context(172)

        # Deferral
        load_mw = capacity_kw / 1000
        gen_mw = capacity_kw / 1000
        try:
            async with pool.acquire() as conn:
                alloc = await greedy_allocate(conn, load_mw * 1000, gen_mw * 1000)
        except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
            log.info("Deferral tables unavailable in grid study, simulating: %s", exc)
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


@router.get("/job/{job_id}")
async def get_job_status(job_id: str):
    """Poll a background job for status and results."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@router.get("/jobs")
async def list_all_jobs(kind: str = None, limit: int = 50):
    """List recent jobs, optionally filtered by kind."""
    return jobs.list_jobs(kind=kind, limit=limit)
