"""Grid Efficiency Analysis router."""

from __future__ import annotations

from fastapi import APIRouter, Request

from utils.grid_efficiency_analyser import (
    estimate_line_losses,
    analyse_network_efficiency,
    identify_upgrade_opportunities,
    substation_health_assessment,
)

router = APIRouter(tags=["grid-efficiency"])


@router.post("/grid-efficiency/line-losses")
async def api_line_losses(req: Request):
    """Estimate transmission/distribution line losses."""
    body = await req.json()
    return estimate_line_losses(
        distance_km=body.get("distance_km", 10),
        voltage_kv=body.get("voltage_kv", 132),
        load_mw=body.get("load_mw", 10),
        capacity_mva=body.get("capacity_mva"),
    )


@router.post("/grid-efficiency/network")
async def api_network_efficiency(req: Request):
    """Analyse efficiency across a grid topology."""
    body = await req.json()
    return analyse_network_efficiency(body)


@router.post("/grid-efficiency/upgrade-opportunities")
async def api_upgrade_opportunities(req: Request):
    """Identify grid upgrade opportunities from topology."""
    body = await req.json()
    topology = body.get("topology", body)
    min_congestion = body.get("min_congestion_pct", 70)
    return identify_upgrade_opportunities(topology, min_congestion_pct=min_congestion)


@router.post("/grid-efficiency/substation-health")
async def api_substation_health(req: Request):
    """Assess substation health from data + optional GeoAI condition."""
    body = await req.json()
    substations = body.get("substations", [])
    geoai_condition = body.get("geoai_condition")
    return substation_health_assessment(substations, geoai_condition)
