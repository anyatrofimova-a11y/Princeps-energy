"""Site Prospector router."""

from __future__ import annotations

from typing import Any

import asyncpg
from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel

from app.deps import get_pool
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


# ---------------------------------------------------------------------------
# Planning Risk Scoring
# ---------------------------------------------------------------------------

class PlanningRiskRequest(BaseModel):
    lat: float
    lon: float
    capacity_mw: float = 10.0
    technology: str = "solar"


@router.post("/api/prospector/planning-risk")
async def planning_risk(
    body: PlanningRiskRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Score planning risk for a proposed energy development site."""
    from utils.planning_risk_scorer import score_planning_risk
    return await score_planning_risk(
        pool, body.lat, body.lon, body.capacity_mw, body.technology,
    )


# ---------------------------------------------------------------------------
# Batch Site Screening
# ---------------------------------------------------------------------------

class BatchCandidate(BaseModel):
    lat: float
    lon: float
    capacity_mw: float = 10.0
    technology: str = "solar"
    name: str | None = None


class BatchScreenRequest(BaseModel):
    candidates: list[BatchCandidate]
    top_n: int = 20


@router.post("/api/prospector/batch-screen")
async def batch_screen(
    body: BatchScreenRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Batch screen multiple candidate sites and return ranked shortlist."""
    from utils.batch_screener import screen_sites
    candidates = [c.model_dump() for c in body.candidates]
    return await screen_sites(pool, candidates, top_n=body.top_n)
