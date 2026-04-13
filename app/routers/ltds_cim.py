"""LTDS CIM router — ingest + read endpoints for the NGED CIM model."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
import asyncpg

from app.deps import get_pool
from utils.ltds_cim_ingester import (
    ingest_all,
    ingest_region_file,
    match_coordinates_fuzzy,
    get_cim_stats,
    list_substations,
    get_substation_detail,
    get_substations_geojson,
)

router = APIRouter(tags=["ltds-cim"], prefix="/api/ltds")


@router.post("/ingest")
async def ingest(
    download_dir: str = Query("/Users/anyatrofimova/Downloads"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Ingest every LTDS_*_EQ_*.xml found in the download dir + the CSV."""
    return await ingest_all(pool, download_dir=Path(download_dir))


@router.post("/match-coordinates")
async def match_coordinates(pool: asyncpg.Pool = Depends(get_pool)):
    """Fuzzy-join cim_substations to grid_substations by name to populate lat/lon."""
    n = await match_coordinates_fuzzy(pool)
    return {"updated": n}


@router.get("/stats")
async def stats(pool: asyncpg.Pool = Depends(get_pool)):
    """CIM stats — totals + breakdown by licence area + PSR type."""
    return await get_cim_stats(pool)


@router.get("/substations")
async def substations(
    licence_area: str | None = Query(None),
    psr_type: str | None = Query(None),
    limit: int = Query(20000, ge=1, le=50000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Substation index for the CIM Graph left sidebar."""
    return await list_substations(pool, licence_area=licence_area, psr_type=psr_type, limit=limit)


@router.get("/substations.geojson")
async def substations_geojson(pool: asyncpg.Pool = Depends(get_pool)):
    """Located substations as GeoJSON."""
    return await get_substations_geojson(pool)


@router.get("/substations/{mrid}")
async def substation_detail(mrid: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Full detail for a single substation — voltage levels, transformers, counts."""
    detail = await get_substation_detail(pool, mrid)
    if not detail:
        raise HTTPException(404, f"Substation {mrid} not found")
    return detail
