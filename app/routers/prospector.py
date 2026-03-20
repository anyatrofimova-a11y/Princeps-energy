"""Site Prospector router."""

from __future__ import annotations

from fastapi import APIRouter, Query

from utils.site_prospector import (
    score_candidate_site,
    regional_scan,
    find_similar_sites,
    UK_REGIONAL_RESOURCE,
)

router = APIRouter(tags=["prospector"])


@router.get("/prospector/score")
async def api_score_site(
    lat: float = Query(...),
    lon: float = Query(...),
    technology: str = Query("solar"),
):
    """Score a candidate site for energy development potential."""
    return score_candidate_site(lat, lon, technology)


@router.get("/prospector/scan")
async def api_regional_scan(
    region: str = Query("south_west"),
    technology: str = Query("solar"),
    grid_points: int = Query(25, ge=4, le=100),
):
    """Scan a UK region for new site opportunities."""
    return regional_scan(region, technology, grid_points)


@router.get("/prospector/similar")
async def api_find_similar(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_km: float = Query(50, ge=5, le=200),
    technology: str = Query("solar"),
    num_candidates: int = Query(20, ge=5, le=50),
):
    """Find sites similar to a reference location."""
    return find_similar_sites(lat, lon, radius_km, num_candidates, technology)


@router.get("/prospector/regions")
async def api_regions():
    """List UK regions with resource data."""
    return UK_REGIONAL_RESOURCE
