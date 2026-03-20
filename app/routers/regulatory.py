"""Regulatory intelligence router — ESO TEC, REPD, grid upgrade tracker, Ofgem RAG, tenders."""

from __future__ import annotations

import asyncio
import json
import os

import anthropic
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_pool

# ── Utils ──
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from utils.uk_tender_tracker import fetch_all_tenders
from utils.eso_tec import tec_geojson, tec_summary, tec_project_detail
from utils.repd import repd_geojson, repd_summary, repd_project_detail, pipeline_combined
from utils.repd_tracker import (
    ingest_repd, query_repd,
    repd_summary as repd_tracker_summary, repd_geojson as repd_tracker_geojson,
)
from utils.eso_tec_register import (
    query_tec, tec_summary as tec_register_summary, connection_queue_analysis,
)
from utils.grid_upgrade_tracker import (
    query_grid_upgrades, grid_upgrade_summary, dno_investment_summary,
)
from utils.ofgem_rag import rag_query, rag_answer, ingest_ofgem_documents

# Import jobs module from app package
_app_dir = os.path.dirname(os.path.dirname(__file__))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)
import jobs


router = APIRouter(tags=["regulatory"])


# ---------------------------------------------------------------------------
# UK Energy Tender Tracker
# ---------------------------------------------------------------------------

@router.get("/tenders/energy")
async def energy_tenders():
    """Fetch active UK energy/storage procurement tenders from 3 government APIs."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, fetch_all_tenders)
    return result


# ---------------------------------------------------------------------------
# ESO TEC Register (Transmission Entry Capacity)
# ---------------------------------------------------------------------------

@router.get("/eso/tec")
async def eso_tec_geojson_endpoint(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
    plant_type: str = Query(None), status: str = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """GeoJSON of TEC projects within bbox."""
    async with pool.acquire() as conn:
        return await tec_geojson(conn, west, south, east, north, plant_type, status)


@router.get("/eso/tec/summary")
async def eso_tec_summary_endpoint(pool: asyncpg.Pool = Depends(get_pool)):
    """TEC register breakdown by plant type, status, and host TO."""
    async with pool.acquire() as conn:
        return await tec_summary(conn)


@router.get("/eso/tec/project/{project_id}")
async def eso_tec_project_endpoint(project_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Single TEC project detail."""
    async with pool.acquire() as conn:
        detail = await tec_project_detail(conn, project_id)
        if not detail:
            raise HTTPException(404, f"TEC project {project_id} not found")
        return detail


# ---------------------------------------------------------------------------
# REPD (Renewable Energy Planning Database)
# ---------------------------------------------------------------------------

@router.get("/repd/projects")
async def repd_projects_endpoint(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
    technology: str = Query(None), status: str = Query(None),
    min_mw: float = Query(0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """GeoJSON of REPD projects within bbox."""
    async with pool.acquire() as conn:
        return await repd_geojson(conn, west, south, east, north, technology, status, min_mw)


@router.get("/repd/summary")
async def repd_summary_endpoint(pool: asyncpg.Pool = Depends(get_pool)):
    """REPD breakdown by technology, status, and region."""
    async with pool.acquire() as conn:
        return await repd_summary(conn)


@router.get("/repd/project/{ref_id}")
async def repd_project_endpoint(ref_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Single REPD project detail."""
    async with pool.acquire() as conn:
        detail = await repd_project_detail(conn, ref_id)
        if not detail:
            raise HTTPException(404, f"REPD project {ref_id} not found")
        return detail


# ---------------------------------------------------------------------------
# Combined Pipeline (TEC + REPD)
# ---------------------------------------------------------------------------

@router.get("/grid/pipeline")
async def grid_pipeline_endpoint(pool: asyncpg.Pool = Depends(get_pool)):
    """Combined TEC + REPD pipeline summary."""
    async with pool.acquire() as conn:
        return await pipeline_combined(conn)


# ---------------------------------------------------------------------------
# Tracker: REPD (Renewable Energy Planning Database)
# ---------------------------------------------------------------------------

@router.get("/tracker/repd")
async def tracker_repd(
    tech_category: str | None = None,
    status: str | None = None,
    developer: str | None = None,
    region: str | None = None,
    min_capacity_mw: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float = 25,
    page: int = 1,
    limit: int = 50,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Filtered REPD project list."""
    async with pool.acquire() as conn:
        rows = await query_repd(
            conn, tech_category=tech_category, status=status,
            developer=developer, region=region, min_capacity_mw=min_capacity_mw,
            lat=lat, lon=lon, radius_km=radius_km, page=page, limit=limit,
        )
    return {"count": len(rows), "page": page, "projects": rows}


@router.get("/tracker/repd/summary")
async def tracker_repd_summary(pool: asyncpg.Pool = Depends(get_pool)):
    """REPD aggregates by tech/status/region."""
    async with pool.acquire() as conn:
        return await repd_tracker_summary(conn)


@router.get("/tracker/repd/geojson")
async def tracker_repd_geojson(
    tech_category: str | None = None,
    status: str | None = None,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """GeoJSON FeatureCollection for REPD map layer."""
    async with pool.acquire() as conn:
        return await repd_tracker_geojson(conn, tech_category, status)


@router.post("/tracker/repd/ingest")
async def tracker_repd_ingest(pool: asyncpg.Pool = Depends(get_pool)):
    """Trigger REPD data refresh."""
    job = await jobs.submit("repd_ingest", ingest_repd, pool)
    return job.to_dict()


# ---------------------------------------------------------------------------
# Tracker: ESO TEC Register
# ---------------------------------------------------------------------------

@router.get("/tracker/tec")
async def tracker_tec(
    tech_category: str | None = None,
    status: str | None = None,
    connection_site: str | None = None,
    customer_name: str | None = None,
    min_tec_mw: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float = 25,
    limit: int = 50,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Filtered ESO TEC connection queue."""
    async with pool.acquire() as conn:
        rows = await query_tec(
            conn, tech_category=tech_category, status=status,
            connection_site=connection_site, customer_name=customer_name,
            min_tec_mw=min_tec_mw, lat=lat, lon=lon, radius_km=radius_km, limit=limit,
        )
    return {"count": len(rows), "entries": rows}


@router.get("/tracker/tec/summary")
async def tracker_tec_summary(pool: asyncpg.Pool = Depends(get_pool)):
    """TEC aggregates by fuel_type/status/site."""
    async with pool.acquire() as conn:
        return await tec_register_summary(conn)


@router.get("/tracker/tec/queue/{connection_site}")
async def tracker_tec_queue(connection_site: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Detailed queue analysis for one connection site."""
    async with pool.acquire() as conn:
        return await connection_queue_analysis(conn, connection_site)


# ---------------------------------------------------------------------------
# Tracker: Grid Upgrades & DNO Investment
# ---------------------------------------------------------------------------

@router.get("/tracker/grid-upgrades")
async def tracker_grid_upgrades(
    dno: str | None = None,
    status: str | None = None,
    min_voltage_kv: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float = 25,
    limit: int = 50,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Filtered DNO grid upgrade list."""
    async with pool.acquire() as conn:
        rows = await query_grid_upgrades(
            conn, dno=dno, status=status, min_voltage_kv=min_voltage_kv,
            lat=lat, lon=lon, radius_km=radius_km, limit=limit,
        )
    return {"count": len(rows), "upgrades": rows}


@router.get("/tracker/grid-upgrades/summary")
async def tracker_grid_upgrades_summary(pool: asyncpg.Pool = Depends(get_pool)):
    """Grid upgrades by DNO/status/voltage/RIIO."""
    async with pool.acquire() as conn:
        return await grid_upgrade_summary(conn)


@router.get("/tracker/dno-investment")
async def tracker_dno_investment(dno: str | None = None, pool: asyncpg.Pool = Depends(get_pool)):
    """RIIO-ED2 programme delivery dashboard."""
    async with pool.acquire() as conn:
        return await dno_investment_summary(conn, dno)


# ---------------------------------------------------------------------------
# RAG: Regulatory Search (Ofgem)
# ---------------------------------------------------------------------------

@router.post("/rag/query")
async def rag_query_endpoint(body: dict, pool: asyncpg.Pool = Depends(get_pool)):
    """Full RAG: query -> retrieve -> Claude answer with citations."""
    query = body.get("query", "")
    if not query:
        return {"error": "query is required"}
    top_k = body.get("top_k", 5)
    source_filter = body.get("source")
    async with pool.acquire() as conn:
        client = anthropic.Anthropic()
        model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
        return await rag_answer(conn, client, model, query, top_k=top_k, source_filter=source_filter)


@router.get("/rag/search")
async def rag_search(
    q: str = "",
    top_k: int = 5,
    source: str | None = None,
    doc_type: str | None = None,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Chunk retrieval only (no Claude)."""
    if not q:
        return {"error": "q is required"}
    async with pool.acquire() as conn:
        chunks = await rag_query(conn, q, top_k=top_k, source_filter=source, doc_type_filter=doc_type)
    return {"count": len(chunks), "chunks": chunks}


@router.post("/rag/ingest")
async def rag_ingest(pool: asyncpg.Pool = Depends(get_pool)):
    """Trigger regulatory document ingestion."""
    job = await jobs.submit("rag_ingest", ingest_ofgem_documents, pool)
    return job.to_dict()
