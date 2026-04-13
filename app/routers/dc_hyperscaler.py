"""DC Hyperscaler Connection router — 9 endpoints from the MSIP extractions."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, HTTPException
import asyncpg

from app.deps import get_pool
from utils.dc_hyperscaler_connection import (
    find_dual_feed_pairs,
    mvs_gap,
    generate_options,
    list_idnos,
    pathway_split,
    sqss_check,
    msip_eligibility,
    switchgear_recommendation,
    generate_connection_bom,
    escalate_price,
)

router = APIRouter(tags=["dc-hyperscaler"], prefix="/api/dc/hyperscaler")


@router.get("/dual-feed-pairs")
async def dual_feed_pairs(
    lat: float = Query(...),
    lon: float = Query(...),
    capacity_mva: float = Query(...),
    max_radius_km: float = Query(25.0),
    min_voltage_kv: float = Query(33.0),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Find pairs of substations that can provide dual-feed resiliency."""
    return await find_dual_feed_pairs(
        pool, lat, lon, capacity_mva, max_radius_km=max_radius_km, min_voltage_kv=min_voltage_kv
    )


@router.post("/mvs-gap")
async def mvs_gap_endpoint(body: dict = Body(...)):
    """Minimum Viable Solution gap and customer one-off charge calculation."""
    return mvs_gap(
        capacity_mva=float(body.get("capacity_mva", 100)),
        has_dual_feed=bool(body.get("has_dual_feed", True)),
        uses_gis_switchgear=bool(body.get("uses_gis_switchgear", False)),
        voltage_kv=float(body.get("voltage_kv", 132)),
        urban=bool(body.get("urban", False)),
        accelerated_delivery=bool(body.get("accelerated_delivery", False)),
    )


@router.post("/optioneer")
async def optioneer(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """Generate and rank all connection options for a DC site.

    Applies the 15 calibration rules derived from MSIP research + RIIO-T3
    Final Determinations (Dec 2025).
    """
    return await generate_options(
        pool,
        lat=float(body["lat"]),
        lon=float(body["lon"]),
        capacity_mva=float(body["capacity_mva"]),
        urban=bool(body.get("urban", False)),
        target_year=int(body.get("target_year", 2028)),
        accelerated=bool(body.get("accelerated", False)),
        customer_role=body.get("customer_role", "demand"),
        in_london_dc_cluster=bool(body.get("in_london_dc_cluster", False)),
        cluster_cumulative_mva=float(body.get("cluster_cumulative_mva", 0)),
        nearest_400kv_km=body.get("nearest_400kv_km"),
        strategic_demand=bool(body.get("strategic_demand", False)),
        risk_allowance_pct=float(body.get("risk_allowance_pct", 7.5)),
    )


@router.get("/idnos")
async def idnos(region: str | None = Query(None)):
    """List available iDNOs (optionally filtered by region)."""
    return list_idnos(region=region)


@router.post("/pathway-split")
async def pathway_split_endpoint(body: dict = Body(...)):
    """Split total connection cost between NGET transmission and iDNO distribution."""
    return pathway_split(
        total_cost_gbp=float(body["total_cost_gbp"]),
        uses_idno=bool(body.get("uses_idno", False)),
        transmission_voltage_kv=float(body.get("transmission_voltage_kv", 400)),
        distribution_voltage_kv=float(body.get("distribution_voltage_kv", 66)),
    )


@router.post("/sqss-check")
async def sqss_check_endpoint(body: dict = Body(...)):
    """Check proposed connection against SQSS rules."""
    return sqss_check(
        capacity_mva=float(body["capacity_mva"]),
        voltage_kv=float(body["voltage_kv"]),
        has_dual_feed=bool(body.get("has_dual_feed", False)),
        above_minimum=bool(body.get("above_minimum", False)),
    )


@router.post("/msip-eligibility")
async def msip_eligibility_endpoint(body: dict = Body(...)):
    """Check MSIP re-opener eligibility."""
    return msip_eligibility(
        capacity_mva=float(body["capacity_mva"]),
        estimated_cost_gbp=float(body["estimated_cost_gbp"]),
        expected_application_date=body.get("expected_application_date"),
    )


@router.get("/switchgear")
async def switchgear(
    capacity_mva: float = Query(...),
    urban: bool = Query(False),
    voltage_kv: float = Query(132),
    available_land_ha: float | None = Query(None),
):
    """Recommend AIS or GIS switchgear with cost/footprint comparison."""
    return switchgear_recommendation(
        capacity_mva=capacity_mva, urban=urban,
        voltage_kv=voltage_kv, available_land_ha=available_land_ha,
    )


@router.post("/connection-bom")
async def connection_bom(body: dict = Body(...)):
    """Ofgem-format Direct Cost / Asset Table for a DC connection."""
    return generate_connection_bom(
        capacity_mva=float(body["capacity_mva"]),
        voltage_kv=float(body.get("voltage_kv", 132)),
        has_dual_feed=bool(body.get("has_dual_feed", True)),
        uses_gis=bool(body.get("uses_gis", False)),
        cable_length_km=float(body.get("cable_length_km", 2.0)),
        price_base_year=int(body.get("price_base_year", 2018)),
    )


@router.get("/escalate")
async def escalate(
    cost_gbp: float = Query(...),
    from_year: int = Query(...),
    to_year: int = Query(...),
):
    """Escalate a cost between price bases using ONS CPIH-H."""
    return escalate_price(cost_gbp=cost_gbp, from_year=from_year, to_year=to_year)


@router.get("/stats")
async def stats():
    """Summary of the DC hyperscaler suite capabilities."""
    return {
        "module": "dc_hyperscaler_connection",
        "source": "NGET MSIP Willesden/Kensal Green (Jan 2024)",
        "capabilities": [
            "dual_feed_resiliency", "mvs_gap", "optioneer",
            "idno_registry", "sqss_compliance", "msip_eligibility",
            "switchgear_recommendation", "connection_bom", "price_escalation",
        ],
        "idno_count": len(list_idnos()),
    }
