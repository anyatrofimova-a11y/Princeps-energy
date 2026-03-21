"""Land registry router — property boundaries, ALC, and listings."""

from __future__ import annotations

from fastapi import APIRouter, Query

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
):
    """Commercial/agricultural land listings near a point."""
    from utils.land_registry import search_commercial_listings
    return await search_commercial_listings(lat, lon, radius_km=radius_km, land_type=land_type)
