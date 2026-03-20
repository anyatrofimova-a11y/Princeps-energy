"""EuroSAT Land Classification router — spectral LULC from Sentinel-2."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from utils.eurosat_classifier import (
    classify_spectral,
    classify_location,
    classify_patch,
    get_classes,
    compare_with_dynamicworld,
)

router = APIRouter(tags=["eurosat"])


class BandsRequest(BaseModel):
    bands: list[float]


class PatchRequest(BaseModel):
    bands_array: list[list[float]]
    bounds: dict | None = None


@router.get("/api/classification/classes")
async def api_eurosat_classes():
    """Return all EuroSAT classes with feasibility metadata."""
    return get_classes()


@router.post("/api/classification/classify")
async def api_classify_spectral(req: BandsRequest):
    """Classify land use from Sentinel-2 band values."""
    return classify_spectral(req.bands)


@router.get("/api/classification/location")
async def api_classify_location(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    date: str | None = Query(None, description="Date (YYYY-MM-DD)"),
):
    """Classify land use at a geographic location."""
    return classify_location(lat, lon, date)


@router.post("/api/classification/patch")
async def api_classify_patch(req: PatchRequest):
    """Classify a patch of multi-spectral imagery."""
    return classify_patch(req.bands_array, req.bounds)


@router.get("/api/classification/compare")
async def api_compare(
    eurosat_class: str = Query(..., description="EuroSAT class name"),
    dw_class: str = Query(..., description="DynamicWorld class name"),
):
    """Compare EuroSAT classification with DynamicWorld."""
    return compare_with_dynamicworld(eurosat_class, dw_class)
