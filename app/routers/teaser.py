"""TEASER router — building thermal model generation and retrofit analysis."""

from __future__ import annotations

from fastapi import APIRouter, Query

from utils.teaser_runner import (
    generate_building_model,
    compare_retrofit_scenarios,
    list_building_types,
)

router = APIRouter(prefix="/teaser", tags=["teaser"])


@router.get("/building-types")
async def building_types():
    """List available building archetypes."""
    return list_building_types()


@router.get("/model")
async def thermal_model(
    building_type: str = Query("office"),
    name: str = Query("Site Building"),
    year_of_construction: int = Query(2000, ge=1850, le=2025),
    number_of_floors: int = Query(3, ge=1, le=50),
    height_of_floors: float = Query(3.5, ge=2.0, le=6.0),
    net_leased_area: float = Query(2000, ge=10, le=500000),
    lat: float = Query(52.5, ge=49, le=61),
):
    """Generate a building thermal model from archetype parameters."""
    return generate_building_model(
        building_type=building_type,
        name=name,
        year_of_construction=year_of_construction,
        number_of_floors=number_of_floors,
        height_of_floors=height_of_floors,
        net_leased_area=net_leased_area,
        lat=lat,
    )


@router.get("/retrofit")
async def retrofit_comparison(
    building_type: str = Query("office"),
    year_of_construction: int = Query(1970, ge=1850, le=2025),
    net_leased_area: float = Query(2000, ge=10, le=500000),
    number_of_floors: int = Query(3, ge=1, le=50),
    height_of_floors: float = Query(3.5, ge=2.0, le=6.0),
    lat: float = Query(52.5, ge=49, le=61),
):
    """Compare retrofit scenarios against baseline building."""
    return compare_retrofit_scenarios(
        building_type=building_type,
        year_of_construction=year_of_construction,
        net_leased_area=net_leased_area,
        number_of_floors=number_of_floors,
        height_of_floors=height_of_floors,
        lat=lat,
    )
