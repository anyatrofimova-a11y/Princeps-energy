"""Hardware configurator router — modular IoT monitoring kit builder."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from utils.hardware_configurator import (
    recommend_kit, get_catalogue, get_module,
    list_kit_templates, custom_kit,
)

router = APIRouter(prefix="/hardware", tags=["hardware"])


@router.get("/catalogue")
async def catalogue(category: str = Query(None)):
    """Return the sensor module catalogue, optionally filtered by category."""
    return get_catalogue(category)


@router.get("/catalogue/{module_id}")
async def module_detail(module_id: str):
    """Get details for a single module."""
    mod = get_module(module_id)
    if not mod:
        return {"error": f"Module {module_id} not found"}
    return mod


@router.get("/templates")
async def templates():
    """List available kit templates."""
    return list_kit_templates()


@router.get("/recommend")
async def recommend(
    site_type: str = Query("solar_farm"),
    capacity_mw: float = Query(5.0, ge=0.01, le=1000),
    include_optional: bool = Query(False),
):
    """Recommend a monitoring kit for a site type and capacity."""
    return recommend_kit(site_type, capacity_mw, include_optional)


class CustomKitRequest(BaseModel):
    modules: list[dict]  # [{module_id, qty, role?}]


@router.post("/custom")
async def build_custom_kit(req: CustomKitRequest):
    """Build a custom kit from selected modules."""
    return custom_kit(req.modules)
