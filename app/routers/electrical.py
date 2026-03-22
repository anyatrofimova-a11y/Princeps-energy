"""Electrical eBOS design router — auto-string, inverter, transformer, cable, SLD."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import Optional

from utils.electrical_design import (
    design_electrical,
    INVERTERS,
    TRANSFORMERS,
    CABLE_SPECS,
)

router = APIRouter(prefix="/api/electrical", tags=["electrical"])


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------
class ElectricalDesignRequest(BaseModel):
    layout_summary: dict = Field(..., description="Layout summary with total_panels / total_mwp")
    panel_watts: int = Field(600, ge=100, le=1000)
    panel_voc: float = Field(51.8, gt=0, description="Panel open-circuit voltage (V)")
    panel_isc: float = Field(14.5, gt=0, description="Panel short-circuit current (A)")
    modules_per_string: int = Field(24, ge=1, le=60)
    inverter_type: str = Field("huawei_sun2000_215")
    transformer_voltage_kv: int = Field(33, description="Collection voltage: 33 or 11")
    poc_lat: Optional[float] = Field(None, description="Point of connection latitude")
    poc_lon: Optional[float] = Field(None, description="Point of connection longitude")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/design")
async def electrical_design(req: ElectricalDesignRequest):
    """Auto-generate full eBOS electrical design from a solar panel layout.

    Returns string configuration, inverter/transformer counts, cable schedule,
    cost breakdown, loss budget, single-line diagram data, and equipment list.
    """
    return design_electrical(
        layout_summary=req.layout_summary,
        panel_watts=req.panel_watts,
        panel_voc=req.panel_voc,
        panel_isc=req.panel_isc,
        modules_per_string=req.modules_per_string,
        inverter_type=req.inverter_type,
        transformer_voltage_kv=req.transformer_voltage_kv,
        poc_lat=req.poc_lat,
        poc_lon=req.poc_lon,
    )


@router.get("/inverters")
async def list_inverters():
    """List available inverter specifications."""
    return {
        "inverters": {k: v for k, v in INVERTERS.items()},
        "count": len(INVERTERS),
    }


@router.get("/transformers")
async def list_transformers():
    """List available transformer options."""
    return {
        "transformers": {k: v for k, v in TRANSFORMERS.items()},
        "count": len(TRANSFORMERS),
    }


@router.get("/cables")
async def list_cables():
    """List cable specifications and costs."""
    return {
        "cables": {k: v for k, v in CABLE_SPECS.items()},
        "count": len(CABLE_SPECS),
    }
