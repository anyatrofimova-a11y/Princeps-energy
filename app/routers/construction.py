"""Construction timeline endpoints — Gantt-style programme for solar, wind & BESS projects."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel

from utils.construction_timeline import construction_timeline, gantt_svg

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
