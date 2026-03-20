"""Legacy Asset Planning & Compliance router."""

from __future__ import annotations

import json

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.deps import get_pool
from utils.legacy_asset_compliance import (
    assess_asset_lifecycle,
    compliance_check,
    UK_ASSET_LIFECYCLES,
    DECOMMISSIONING_COSTS_PER_KW,
)

router = APIRouter(tags=["legacy"])


@router.get("/legacy/assets")
async def get_legacy_assets(
    lat: float = Query(None),
    lon: float = Query(None),
    radius_km: float = Query(25, ge=1, le=100),
    asset_type: str = Query(None),
    status: str = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Query legacy energy assets, optionally filtered by location/type/status."""
    async with pool.acquire() as conn:
        conditions = []
        params: list = []
        idx = 1

        if lat is not None and lon is not None:
            conditions.append(
                f"ST_DWithin(geometry, ST_Transform(ST_SetSRID(ST_MakePoint(${idx}, ${idx+1}), 4326), 27700), ${idx+2})"
            )
            params.extend([lon, lat, radius_km * 1000])
            idx += 3

        if asset_type:
            conditions.append(f"asset_type = ${idx}")
            params.append(asset_type)
            idx += 1

        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await conn.fetch(f"""
            SELECT asset_id, name, asset_type, capacity_kw, commissioning,
                   status, condition_score, owner, notes,
                   ST_X(ST_Transform(geometry, 4326)) as lon,
                   ST_Y(ST_Transform(geometry, 4326)) as lat
            FROM legacy_assets
            {where}
            ORDER BY name
            LIMIT 200
        """, *params)

        return {
            "count": len(rows),
            "assets": [
                {
                    "asset_id": str(r["asset_id"]),
                    "name": r["name"],
                    "asset_type": r["asset_type"],
                    "capacity_kw": r["capacity_kw"],
                    "commissioning": r["commissioning"].isoformat() if r["commissioning"] else None,
                    "status": r["status"],
                    "condition_score": r["condition_score"],
                    "owner": r["owner"],
                    "lat": round(r["lat"], 6) if r["lat"] else None,
                    "lon": round(r["lon"], 6) if r["lon"] else None,
                }
                for r in rows
            ],
        }


@router.get("/legacy/assets/geojson")
async def get_legacy_assets_geojson(
    asset_type: str = Query(None),
    status: str = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return legacy assets as GeoJSON for map display."""
    async with pool.acquire() as conn:
        conditions = []
        params: list = []
        idx = 1
        if asset_type:
            conditions.append(f"asset_type = ${idx}")
            params.append(asset_type)
            idx += 1
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await conn.fetch(f"""
            SELECT asset_id, name, asset_type, capacity_kw, commissioning,
                   status, condition_score,
                   ST_AsGeoJSON(ST_Transform(geometry, 4326))::json as geojson
            FROM legacy_assets
            {where}
            LIMIT 500
        """, *params)

        features = []
        for r in rows:
            features.append({
                "type": "Feature",
                "geometry": r["geojson"] if isinstance(r["geojson"], dict) else json.loads(r["geojson"]),
                "properties": {
                    "asset_id": str(r["asset_id"]),
                    "name": r["name"],
                    "asset_type": r["asset_type"],
                    "capacity_kw": r["capacity_kw"],
                    "status": r["status"],
                    "condition_score": r["condition_score"],
                },
            })
        return {"type": "FeatureCollection", "features": features}


@router.get("/legacy/lifecycle")
async def get_lifecycle_assessment(
    asset_type: str = Query("solar_farm"),
    commissioning_date: str = Query("2015-01-01"),
    capacity_kw: float = Query(100),
    condition_score: float = Query(None),
):
    """Assess asset lifecycle position, compliance milestones, repowering, and decommissioning."""
    return assess_asset_lifecycle(asset_type, commissioning_date, capacity_kw, condition_score)


@router.get("/legacy/compliance")
async def get_compliance_check(
    asset_type: str = Query("solar_farm"),
    capacity_kw: float = Query(100),
    commissioning_date: str = Query("2015-01-01"),
    has_consent: bool = Query(True),
):
    """Run UK regulatory compliance check for an energy asset."""
    return compliance_check(asset_type, capacity_kw, commissioning_date, has_planning_consent=has_consent)


@router.get("/legacy/asset-types")
async def get_asset_types():
    """List supported asset types with lifecycle parameters."""
    return {
        "types": UK_ASSET_LIFECYCLES,
        "decommissioning_costs_per_kw": DECOMMISSIONING_COSTS_PER_KW,
    }
