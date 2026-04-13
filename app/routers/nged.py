"""NGED router — Live Data Feed, Live GSP Data, Embedded Capacity Register, Network Opportunity headroom map."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query
import asyncpg

from app.deps import get_pool
from utils.nged_live_feed import (
    ingest_snapshot as ingest_live_feed,
    get_latest_feed,
    get_licence_areas_geojson,
    get_history as get_live_history,
    get_headroom_geojson,
    get_headroom_stats,
    get_substation_index,
)
from utils.nged_gsp_data import (
    ingest_region as ingest_gsp_region,
    ingest_all_regions as ingest_all_gsp,
    resolve_locations as resolve_gsp_locations,
    get_gsp_geojson,
    get_gsp_timeseries,
    get_stats as get_gsp_stats,
    GSP_PACKAGES,
)
from utils.nged_ecr import (
    ingest_ecr,
    get_ecr_geojson,
    get_ecr_stats,
)

router = APIRouter(tags=["nged"], prefix="/api/nged")


# ────────────────────────────────────────────────────────────────────────
# Live Data Feed (4-licence area aggregate)
# ────────────────────────────────────────────────────────────────────────

@router.post("/live/ingest")
async def live_ingest(pool: asyncpg.Pool = Depends(get_pool)):
    """Scrape and persist the latest NGED Live Data Feed snapshot."""
    return await ingest_live_feed(pool)


@router.get("/live/latest")
async def live_latest(pool: asyncpg.Pool = Depends(get_pool)):
    """Latest licence-area snapshot with totals."""
    return await get_latest_feed(pool)


@router.get("/live/licence-areas.geojson")
async def live_geojson(pool: asyncpg.Pool = Depends(get_pool)):
    """Licence-area polygons with live demand/generation/import for map rendering."""
    return await get_licence_areas_geojson(pool)


@router.get("/live/history")
async def live_history(
    licence_area: str | None = Query(None),
    hours: int = Query(24, ge=1, le=720),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Historical licence-area snapshots (time series)."""
    return await get_live_history(pool, licence_area=licence_area, hours=hours)


# ────────────────────────────────────────────────────────────────────────
# Live GSP Data (per-GSP time series)
# ────────────────────────────────────────────────────────────────────────

@router.post("/gsp/ingest")
async def gsp_ingest(
    region: str | None = Query(None, regex="^(em|wm|sw|wa)$"),
    max_rows_per_gsp: int = Query(500, ge=1, le=20000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Ingest Live GSP Data for one or all NGED regions."""
    if region:
        return await ingest_gsp_region(pool, region, max_rows_per_gsp=max_rows_per_gsp)
    return await ingest_all_gsp(pool, max_rows_per_gsp=max_rows_per_gsp)


@router.post("/gsp/resolve-locations")
async def gsp_resolve(pool: asyncpg.Pool = Depends(get_pool)):
    """Fuzzy-match GSP names to grid_substations to populate lat/lon."""
    n = await resolve_gsp_locations(pool)
    return {"updated": n}


@router.get("/gsp.geojson")
async def gsp_geojson(
    region: str | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """GSP GeoJSON with live values for map display (color-coded utilisation)."""
    return await get_gsp_geojson(pool, region=region)


@router.get("/gsp/{region}/{gsp_name}/timeseries")
async def gsp_timeseries(
    region: str,
    gsp_name: str,
    hours: int = Query(48, ge=1, le=720),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """48-hour-by-default time series for a single GSP."""
    data = await get_gsp_timeseries(pool, region, gsp_name, hours=hours)
    if not data:
        raise HTTPException(404, f"No data for {region}/{gsp_name}")
    return data


@router.get("/gsp/stats")
async def gsp_stats(pool: asyncpg.Pool = Depends(get_pool)):
    """Summary statistics across all ingested NGED GSPs."""
    return await get_gsp_stats(pool)


@router.get("/regions")
async def regions():
    """List the NGED licence areas and their CKAN package IDs."""
    return [{"code": k, "name": v[1], "package_id": v[0]} for k, v in GSP_PACKAGES.items()]


# ────────────────────────────────────────────────────────────────────────
# Embedded Capacity Register
# ────────────────────────────────────────────────────────────────────────

@router.post("/ecr/ingest")
async def ecr_ingest(
    url: str | None = Query(None),
    limit: int | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Download + persist the NGED ECR snapshot. Full reload on each call."""
    return await ingest_ecr(pool, url=url, limit=limit)


@router.get("/ecr.geojson")
async def ecr_geojson(
    status: str | None = Query(None),
    technology: str | None = Query(None),
    min_mw: float | None = Query(None),
    licence_area: str | None = Query(None),
    limit: int = Query(10000, ge=1, le=100000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """ECR as GeoJSON — color-coded by connection status, sized by capacity."""
    return await get_ecr_geojson(
        pool,
        status=status,
        technology=technology,
        min_mw=min_mw,
        licence_area=licence_area,
        limit=limit,
    )


@router.get("/ecr/stats")
async def ecr_stats(pool: asyncpg.Pool = Depends(get_pool)):
    """ECR summary — connected / in-queue counts, total MW, breakdown by tech."""
    return await get_ecr_stats(pool)


# ────────────────────────────────────────────────────────────────────────
# Network Opportunity Map — headroom from grid_substations
# ────────────────────────────────────────────────────────────────────────

@router.get("/headroom.geojson")
async def headroom_geojson(
    kind: str = Query("demand", regex="^(demand|generation)$"),
    dno: str | None = Query(None),
    min_voltage_kv: float = Query(11.0, ge=0.4, le=400),
    limit: int = Query(5000, ge=1, le=20000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Network Opportunity headroom map — substations color-coded by remaining headroom."""
    return await get_headroom_geojson(
        pool, kind=kind, dno=dno, min_voltage_kv=min_voltage_kv, limit=limit
    )


@router.get("/headroom/stats")
async def headroom_stats(
    dno: str | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Aggregate headroom stats (for the Pulse header strip)."""
    return await get_headroom_stats(pool, dno=dno)


# ────────────────────────────────────────────────────────────────────────
# Substation index — lightweight list for the CIM-style asset browser
# ────────────────────────────────────────────────────────────────────────

@router.get("/substations/index")
async def substation_index(
    min_voltage_kv: float = Query(11, ge=0.4, le=400),
    dno: str | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Lightweight substation index for the Grid Graph asset browser.

    One-shot fetch for the CIM-style Map refit — every substation with
    its voltage, DNO, coordinates, headroom, and colour. ≈1.2 MB for all
    14k UK substations.
    """
    return await get_substation_index(pool, min_voltage_kv=min_voltage_kv, dno=dno)
