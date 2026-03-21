"""Automated UK-Wide ML Site Prospector (v2) router.

Scans all 2,059 NGED substations and scores surrounding catchment areas
using grid headroom, solar resource, REPD development density, TEC queue
competition, and constraint risk. Returns ranked opportunities, detailed
substation assessments, and GeoJSON heatmaps.
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.deps import get_pool

router = APIRouter(prefix="/api/v2/prospect", tags=["prospector-v2"])


@router.get("/scan")
async def scan_opportunities(
    region: str | None = Query(None, description="UK region filter (e.g. east_midlands)"),
    technology: str | None = Query(None, description="Technology filter (e.g. solar, wind)"),
    min_capacity_mw: float | None = Query(None, ge=0, description="Min capacity threshold (MW)"),
    top_n: int = Query(50, ge=1, le=500, description="Number of top results to return"),
    radius_km: float = Query(10.0, ge=1, le=50, description="Catchment radius (km)"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Scan all UK substations and return top opportunities ranked by composite score.

    Queries all NGED substations, scores each catchment area on grid headroom,
    solar resource, REPD development density, TEC queue competition, and
    constraint risk. Supports filtering by region, technology, and minimum
    capacity.
    """
    from utils.auto_prospector import scan_all
    return await scan_all(
        pool,
        region=region,
        technology=technology,
        min_capacity_mw=min_capacity_mw,
        top_n=top_n,
        radius_km=radius_km,
    )


@router.get("/substation/{sub_id}")
async def substation_assessment(
    sub_id: int,
    radius_km: float = Query(10.0, ge=1, le=50, description="Catchment radius (km)"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Detailed opportunity assessment for a single substation catchment.

    Returns full score breakdown, nearby REPD projects, TEC queue entries,
    technology mix, and total nearby generation capacity.
    """
    from utils.auto_prospector import substation_detail
    return await substation_detail(pool, sub_id, radius_km)


@router.get("/heatmap")
async def opportunity_heatmap(
    radius_km: float = Query(10.0, ge=1, le=50, description="Catchment radius (km)"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """GeoJSON FeatureCollection of all substations colored by opportunity score.

    Each feature includes composite score, recommendation tier, and individual
    scoring dimensions. Suitable for direct rendering on a Mapbox/deck.gl layer.
    """
    from utils.auto_prospector import heatmap_geojson
    return await heatmap_geojson(pool, radius_km)
