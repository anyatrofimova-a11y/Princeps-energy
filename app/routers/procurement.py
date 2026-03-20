"""Procurement Intelligence router."""

from __future__ import annotations

from fastapi import APIRouter, Request

from utils.procurement_intelligence import (
    assess_bid_viability,
    match_tenders_to_sites,
    procurement_pipeline_summary,
    COST_BENCHMARKS as PROCUREMENT_COST_BENCHMARKS,
)
from utils.uk_tender_tracker import fetch_all_tenders

router = APIRouter(tags=["procurement"])


@router.get("/procurement/pipeline")
async def procurement_pipeline():
    """Get procurement pipeline analytics from all tender sources."""
    tenders = await fetch_all_tenders()
    return procurement_pipeline_summary(tenders)


@router.post("/procurement/bid-viability")
async def bid_viability(req: Request):
    """Assess viability of bidding on a specific tender."""
    body = await req.json()
    tender = body.get("tender", body)
    return assess_bid_viability(
        tender,
        site_score=body.get("site_score"),
        grid_headroom_mw=body.get("grid_headroom_mw"),
        distance_to_grid_km=body.get("distance_to_grid_km"),
        planning_success_rate=body.get("planning_success_rate"),
    )


@router.post("/procurement/match-sites")
async def match_tender_sites(req: Request):
    """Match tenders to available scored sites."""
    body = await req.json()
    tenders = body.get("tenders", [])
    sites = body.get("sites", [])
    return match_tenders_to_sites(tenders, sites, max_matches=body.get("max_matches", 5))


@router.get("/procurement/cost-benchmarks")
async def procurement_cost_benchmarks():
    """Get UK energy procurement cost benchmarks by technology."""
    return PROCUREMENT_COST_BENCHMARKS
