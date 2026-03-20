"""Home retrofit router — UK residential CBR retrofit design."""

from __future__ import annotations

import json
import logging
import os
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.deps import get_pool

# ── Utils ──
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from utils.home_retrofit_engine import (
    run_assessment as home_retrofit_assess,
    build_case_library_from_rows as build_home_case_library,
    UK_HOUSE_ARCHETYPES, RETROFIT_INTERVENTIONS, UK_RETROFIT_COSTS,
)


log = logging.getLogger("princeps")

router = APIRouter(tags=["home-retrofit"])


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class HomeRetrofitRequest(BaseModel):
    house_type: str = "1930s_semi"
    plot_width_m: float = 8.0
    plot_depth_m: float = 25.0
    storeys: int = 2
    epc_rating: str = "D"
    heating: str = "gas_boiler"
    conservation: bool = False
    listed: str | None = None
    budget_gbp: float | None = None
    lat: float = 52.5
    lon: float = -1.5
    gfa_m2: float | None = None
    parcel_id: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/home-retrofit/assess")
async def home_retrofit_assess_endpoint(req: HomeRetrofitRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """Full CBR home retrofit assessment -- encode, match, generate options."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM home_retrofit_cases WHERE house_type = $1 OR TRUE ORDER BY house_type LIMIT 200",
            req.house_type,
        )
        case_library = build_home_case_library(rows)

    result = home_retrofit_assess(
        house_type=req.house_type,
        plot_width_m=req.plot_width_m,
        plot_depth_m=req.plot_depth_m,
        storeys=req.storeys,
        epc_rating=req.epc_rating,
        heating=req.heating,
        conservation=req.conservation,
        listed=req.listed,
        budget_gbp=req.budget_gbp,
        lat=req.lat,
        lon=req.lon,
        gfa_m2=req.gfa_m2,
        case_library=case_library,
    )

    # Store assessment
    if req.parcel_id:
        try:
            pid = UUID(req.parcel_id)
            best = result["options"][0] if result["options"] else {}
            last = result["options"][-1] if result["options"] else {}
            geometries = []
            for opt in result["options"]:
                geometries.extend(opt.get("geometries", []))
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO home_retrofit_assessments
                        (parcel_id, house_type, property_encoding, matched_cases,
                         options, total_cost_gbp, energy_saving_kwh_yr, co2_saving_kg_yr,
                         epc_before, epc_after, planning_route, retrofit_geometry,
                         lat, lon, geometry)
                    VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6, $7, $8,
                            $9, $10, $11, $12::jsonb, $13, $14,
                            ST_Transform(ST_SetSRID(ST_MakePoint($15, $16), 4326), 27700))
                    """,
                    pid, req.house_type,
                    json.dumps(result["property_encoding"]),
                    json.dumps(result["matched_cases"], default=str),
                    json.dumps(result["options"], default=str),
                    last.get("total_cost_gbp", 0),
                    last.get("energy", {}).get("energy_saving_kwh", 0),
                    last.get("energy", {}).get("co2_saving_kg", 0),
                    best.get("energy", {}).get("epc_before", ""),
                    last.get("energy", {}).get("epc_after", ""),
                    last.get("planning", {}).get("route", ""),
                    json.dumps(geometries, default=str),
                    req.lat, req.lon, req.lon, req.lat,
                )
        except Exception as e:
            log.warning("Failed to store home retrofit assessment: %s", e)

    return result


@router.get("/home-retrofit/options/{parcel_id}")
async def home_retrofit_options(parcel_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Retrieve stored home retrofit assessment for a parcel."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(400, "Invalid parcel_id")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT house_type, property_encoding, matched_cases, options,
                   total_cost_gbp, energy_saving_kwh_yr, co2_saving_kg_yr,
                   epc_before, epc_after, planning_route, retrofit_geometry,
                   lat, lon, created_at
            FROM home_retrofit_assessments
            WHERE parcel_id = $1
            ORDER BY created_at DESC LIMIT 1
            """,
            pid,
        )
    if not row:
        raise HTTPException(404, "No assessment found for this parcel")
    return {
        "house_type": row["house_type"],
        "options": json.loads(row["options"]) if isinstance(row["options"], str) else row["options"],
        "matched_cases": json.loads(row["matched_cases"]) if isinstance(row["matched_cases"], str) else row["matched_cases"],
        "total_cost_gbp": row["total_cost_gbp"],
        "energy_saving_kwh_yr": row["energy_saving_kwh_yr"],
        "co2_saving_kg_yr": row["co2_saving_kg_yr"],
        "epc_before": row["epc_before"],
        "epc_after": row["epc_after"],
        "planning_route": row["planning_route"],
        "retrofit_geometry": json.loads(row["retrofit_geometry"]) if isinstance(row["retrofit_geometry"], str) else row["retrofit_geometry"],
        "lat": row["lat"],
        "lon": row["lon"],
    }


@router.get("/home-retrofit/precedents/{parcel_id}")
async def home_retrofit_precedents(
    parcel_id: str,
    radius_km: float = Query(10, ge=1, le=50),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Find planning precedents for home retrofit near a parcel."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(400, "Invalid parcel_id")
    async with pool.acquire() as conn:
        parcel = await conn.fetchrow(
            "SELECT ST_Y(ST_Transform(centroid, 4326)) AS lat, ST_X(ST_Transform(centroid, 4326)) AS lon FROM parcels WHERE parcel_id = $1",
            pid,
        )
        if not parcel:
            raise HTTPException(404, "Parcel not found")
        lat, lon = float(parcel["lat"]), float(parcel["lon"])
        rows = await conn.fetch(
            """
            SELECT case_ref, house_type, house_form, era, interventions,
                   planning_ref, planning_route, planning_authority, planning_outcome, planning_date,
                   cost_actual_gbp, epc_before, epc_after,
                   ST_Distance(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000 AS distance_km
            FROM home_retrofit_cases
            WHERE ST_DWithin(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700), $3)
              AND planning_outcome IN ('approved', 'approved_with_conditions')
            ORDER BY ST_Distance(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700))
            LIMIT 20
            """,
            lon, lat, radius_km * 1000,
        )
    return {
        "count": len(rows),
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "precedents": [
            {
                "case_ref": r["case_ref"],
                "house_type": r["house_type"],
                "era": r["era"],
                "interventions": json.loads(r["interventions"]) if isinstance(r["interventions"], str) else r["interventions"],
                "planning_ref": r["planning_ref"],
                "planning_route": r["planning_route"],
                "planning_authority": r["planning_authority"],
                "planning_outcome": r["planning_outcome"],
                "planning_date": r["planning_date"].isoformat() if r["planning_date"] else None,
                "cost_gbp": r["cost_actual_gbp"],
                "epc_before": r["epc_before"],
                "epc_after": r["epc_after"],
                "distance_km": round(r["distance_km"], 1),
            }
            for r in rows
        ],
    }


@router.get("/home-retrofit/archetypes")
async def home_retrofit_archetypes():
    """Return UK house archetype library."""
    return {
        "count": len(UK_HOUSE_ARCHETYPES),
        "archetypes": {
            k: {**v, "id": k}
            for k, v in UK_HOUSE_ARCHETYPES.items()
        },
    }


@router.get("/home-retrofit/interventions")
async def home_retrofit_interventions():
    """Return intervention library with costs."""
    items = {}
    for k, intv in RETROFIT_INTERVENTIONS.items():
        cost = UK_RETROFIT_COSTS.get(k, {})
        items[k] = {
            **intv,
            "id": k,
            "cost_low": cost.get("low"),
            "cost_mid": cost.get("mid"),
            "cost_high": cost.get("high"),
            "cost_unit": cost.get("unit"),
        }
    return {"count": len(items), "interventions": items}
