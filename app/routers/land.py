"""Land registry router — property boundaries, ALC, listings, price paid, and planning density."""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.deps import get_pool

router = APIRouter(tags=["land"])


@router.get("/api/land/parcels")
async def land_parcels(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
    min_area_ha: float = Query(0.5),
):
    """HM Land Registry INSPIRE polygons as GeoJSON for map overlay."""
    from utils.land_registry import get_land_parcels
    return await get_land_parcels((west, south, east, north), min_area_ha=min_area_ha)


@router.get("/api/land/alc")
async def land_alc(lat: float = Query(...), lon: float = Query(...)):
    """Agricultural Land Classification grade at a point."""
    from utils.land_registry import get_agricultural_land_class
    return await get_agricultural_land_class(lat, lon)


@router.get("/api/land/listings")
async def land_listings(
    lat: float = Query(...), lon: float = Query(...),
    radius_km: float = Query(10), land_type: str = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Land listings from REPD stalled projects + portal search links."""
    from utils.land_registry import search_commercial_listings
    return await search_commercial_listings(lat, lon, radius_km=radius_km, land_type=land_type, pool=pool)


@router.get("/api/land/price-paid")
async def price_paid(postcode: str = Query(..., description="UK postcode e.g. SW1A 1AA")):
    """HMLR Price Paid data for a postcode area."""
    from utils.land_registry import get_price_paid
    return await get_price_paid(postcode)


@router.get("/api/land/planning-density")
async def planning_density(
    lat: float = Query(...), lon: float = Query(...),
    radius_km: float = Query(10),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Planning application density around a point — REPD projects by status/technology."""
    from utils.planning_density import get_planning_density
    return await get_planning_density(pool, lat, lon, radius_km=radius_km)
