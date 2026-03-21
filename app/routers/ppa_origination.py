"""PPA Origination Engine router — buyer matching, pricing, structures."""

from __future__ import annotations

from fastapi import APIRouter, Query
from typing import Optional

from utils.ppa_originator import (
    match_buyers,
    list_buyers,
    list_structures,
    get_price_estimate,
    get_uk_region,
)

router = APIRouter(tags=["ppa"])


@router.get("/api/ppa/match")
async def api_ppa_match(
    lat: float = Query(..., description="Site latitude"),
    lon: float = Query(..., description="Site longitude"),
    technology: str = Query("solar", description="solar, wind, onshore_wind, offshore_wind, bess"),
    capacity_mw: float = Query(50, ge=0.1, le=2000),
    structure: Optional[str] = Query(None, description="Preferred PPA structure"),
    term_years: Optional[int] = Query(None, ge=1, le=30),
    additionality: Optional[bool] = Query(None, description="Site offers additionality"),
):
    """Match a site to PPA buyers. Returns ranked list with scores and indicative prices."""
    region = get_uk_region(lat, lon)
    matches = match_buyers(
        technology=technology,
        capacity_mw=capacity_mw,
        lat=lat,
        lon=lon,
        region=region,
        preferred_structure=structure,
        term_years=term_years,
        additionality=additionality,
    )
    return {
        "site": {"lat": lat, "lon": lon, "region": region},
        "query": {
            "technology": technology,
            "capacity_mw": capacity_mw,
            "structure": structure,
            "term_years": term_years,
        },
        "total_matches": len(matches),
        "matches": matches,
    }


@router.get("/api/ppa/buyers")
async def api_ppa_buyers():
    """List all PPA buyer profiles in the database."""
    buyers = list_buyers()
    return {
        "total_buyers": len(buyers),
        "buyers": buyers,
        "buyer_types": sorted(set(b["type"] for b in buyers)),
    }


@router.get("/api/ppa/price-estimate")
async def api_ppa_price_estimate(
    technology: str = Query("solar"),
    capacity_mw: float = Query(50, ge=0.1, le=2000),
    region: str = Query("Midlands"),
    term_years: int = Query(15, ge=1, le=30),
    structure: str = Query("fixed"),
):
    """Indicative PPA price range (P10/P50/P90) for given parameters."""
    return get_price_estimate(
        technology=technology,
        capacity_mw=capacity_mw,
        region=region,
        term_years=term_years,
        structure=structure,
    )


@router.get("/api/ppa/structures")
async def api_ppa_structures():
    """Explain PPA structure options with pros/cons and market context."""
    return list_structures()
