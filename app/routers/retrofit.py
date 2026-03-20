"""Retrofit router -- Infrastructure Retrofit & Energy Storage."""

from __future__ import annotations

from fastapi import APIRouter, Body

from utils.infrastructure_retrofit import (
    match_storage_technologies, assess_retrofit_feasibility,
    assess_grid_flexibility as retrofit_grid_flexibility,
    assess_circularity as retrofit_circularity,
    assess_socioeconomic_impact as retrofit_socioeconomic,
    assess_security as retrofit_security,
    generate_disruption_plan,
    INFRASTRUCTURE_TYPES as RETROFIT_INFRA_TYPES,
    STORAGE_TECHNOLOGIES as RETROFIT_STORAGE_TECHS,
    INFRASTRUCTURE_STORAGE_COMPATIBILITY,
)

router = APIRouter(tags=["retrofit"])


@router.post("/retrofit/assess")
async def api_retrofit_assess(body: dict = Body(...)):
    """Run full retrofit feasibility assessment."""
    return assess_retrofit_feasibility(
        infrastructure_type=body.get("infrastructure_type", "coal_power_plant"),
        storage_technology=body.get("storage_technology", "li_ion_bess"),
        capacity_mw=body.get("capacity_mw", 50),
        duration_hours=body.get("duration_hours", 4),
        structural_condition_score=body.get("structural_condition_score", 70),
        grid_connection_kv=body.get("grid_connection_kv", 132),
        grid_headroom_mw=body.get("grid_headroom_mw", 30),
        distance_to_grid_km=body.get("distance_to_grid_km", 1.0),
        environmental_overlays=body.get("environmental_overlays"),
        site_area_m2=body.get("site_area_m2", 50000),
        existing_remediation=body.get("existing_remediation", False),
        lat=body.get("lat", 52.5),
        lon=body.get("lon", -1.5),
    )


@router.post("/retrofit/match-storage")
async def api_retrofit_match_storage(body: dict = Body(...)):
    """Match compatible storage technologies to infrastructure type."""
    techs = match_storage_technologies(
        infrastructure_type=body.get("infrastructure_type", "coal_power_plant"),
        capacity_mw=body.get("capacity_mw", 50),
        duration_hours=body.get("duration_hours", 4),
        grid_connection_kv=body.get("grid_connection_kv", 132),
        site_area_m2=body.get("site_area_m2", 50000),
        structural_condition_score=body.get("structural_condition_score", 70),
    )
    return {"infrastructure_type": body.get("infrastructure_type"), "technologies": techs}


@router.post("/retrofit/disruption-plan")
async def api_retrofit_disruption_plan(body: dict = Body(...)):
    """Generate phased disruption plan for retrofit."""
    return generate_disruption_plan(
        infra_type=body.get("infrastructure_type", "coal_power_plant"),
        storage_tech=body.get("storage_technology", "li_ion_bess"),
        capacity_mw=body.get("capacity_mw", 50),
        phased=body.get("phased", True),
    )


@router.get("/retrofit/technologies")
async def api_retrofit_technologies():
    """Return infrastructure types, storage technologies, and compatibility matrix."""
    return {
        "infrastructure_types": RETROFIT_INFRA_TYPES,
        "storage_technologies": RETROFIT_STORAGE_TECHS,
        "compatibility": INFRASTRUCTURE_STORAGE_COMPATIBILITY,
    }


@router.post("/retrofit/circularity")
async def api_retrofit_circularity(body: dict = Body(...)):
    """Combined circularity, socioeconomic, security, and grid flexibility assessment."""
    infra = body.get("infrastructure_type", "coal_power_plant")
    tech = body.get("storage_technology", "li_ion_bess")
    cap = body.get("capacity_mw", 50)
    dur = body.get("duration_hours", 4)
    return {
        "circularity": retrofit_circularity(infra, tech, cap),
        "socioeconomic": retrofit_socioeconomic(infra, tech, cap),
        "security": retrofit_security(tech, cap),
        "grid_flexibility": retrofit_grid_flexibility(tech, cap, dur),
    }
