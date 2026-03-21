"""Construction timeline & monitoring endpoints.

Gantt-style programme for solar, wind & BESS projects, plus satellite-based
construction activity detection and pipeline monitoring.
"""

from __future__ import annotations

import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app.deps import get_pool
from utils.construction_timeline import construction_timeline, gantt_svg
from utils.construction_monitor import (
    detect_construction_activity,
    monitor_pipeline_sites,
    estimate_completion,
    construction_timeline as monitor_timeline,
)

log = logging.getLogger("princeps.construction")
router = APIRouter(tags=["design"])


class TimelineRequest(BaseModel):
    """Request body for construction timeline generation."""
    capacity_mw: float = 50.0
    technology: str = "solar"
    has_planning: bool = False
    has_grid: bool = False
    fast_track: bool = False
    modular: bool = False


@router.post("/api/design/construction-timeline")
async def api_construction_timeline(req: TimelineRequest):
    """Generate a construction timeline for a solar, wind, or BESS project.

    Returns phase-by-phase Gantt data with start/end months, durations,
    dependencies, milestones, and a project summary.
    """
    try:
        result = construction_timeline(
            capacity_mw=req.capacity_mw,
            technology=req.technology,
            has_planning=req.has_planning,
            has_grid=req.has_grid,
            fast_track=req.fast_track,
            modular=req.modular,
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.post("/api/design/construction-timeline/svg")
async def api_construction_timeline_svg(req: TimelineRequest):
    """Generate an SVG Gantt chart for a construction timeline.

    Returns image/svg+xml content suitable for embedding or download.
    """
    try:
        timeline = construction_timeline(
            capacity_mw=req.capacity_mw,
            technology=req.technology,
            has_planning=req.has_planning,
            has_grid=req.has_grid,
            fast_track=req.fast_track,
            modular=req.modular,
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))

    svg = gantt_svg(timeline)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Content-Disposition": 'inline; filename="construction-timeline.svg"'},
    )


# ---------------------------------------------------------------------------
# Construction monitoring endpoints
# ---------------------------------------------------------------------------

@router.get("/api/construction/detect")
async def api_construction_detect(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    radius_m: float = Query(500, ge=50, le=5000, description="Search radius in metres"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Detect construction activity at a location using satellite NDVI change analysis.

    Queries stored GeeFlow NDVI extractions to identify earthworks, foundation
    work, panel/turbine installation, or energisation at the given coordinates.
    """
    try:
        result = await detect_construction_activity(
            lat=lat, lon=lon, radius_m=radius_m, pool=pool,
        )
    except Exception as exc:
        log.error("Construction detection failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)[:500])
    return result


@router.get("/api/construction/monitor-pipeline")
async def api_monitor_pipeline(
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Scan all construction-stage projects for satellite-detected activity.

    Returns a list of projects with their recorded stage, satellite detection
    results, and flags any stage mismatches.
    """
    try:
        results = await monitor_pipeline_sites(pool)
    except Exception as exc:
        log.error("Pipeline monitoring failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)[:500])
    return {
        "projects_scanned": len(results),
        "projects": results,
        "mismatches": [r for r in results if r.get("stage_mismatch")],
        "mismatch_count": sum(1 for r in results if r.get("stage_mismatch")),
    }


@router.get("/api/construction/timeline")
async def api_construction_monitor_timeline(
    technology: str = Query("solar", description="Technology: solar, wind, bess"),
    capacity_mw: float = Query(50, ge=0.1, le=2000, description="Capacity in MW"),
):
    """Detailed construction milestone timeline for a given technology and capacity.

    Returns phased milestones with durations, start/end weeks, scale factors,
    and technology-specific construction notes.
    """
    tech = technology.lower().replace("battery", "bess")
    if tech not in ("solar", "wind", "bess"):
        raise HTTPException(400, f"Unsupported technology: {technology}. Use solar, wind, or bess.")
    return monitor_timeline(tech, capacity_mw)


@router.get("/api/construction/estimate/{project_id}")
async def api_construction_estimate(
    project_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Estimate construction completion for a specific project.

    Based on technology, capacity, and construction start date, returns
    estimated completion date, percentage complete, and on-track status.
    """
    try:
        result = await estimate_completion(project_id, pool)
    except ValueError:
        raise HTTPException(400, "Invalid project_id format — must be a UUID")
    except Exception as exc:
        log.error("Completion estimate failed for %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)[:500])
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result
