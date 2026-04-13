"""Cluster router — dependency graph, withdrawal simulation, cluster stats."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
import asyncpg

from app.deps import get_pool
from utils.cluster_graph import (
    ingest_from_tec_register,
    compute_dependencies,
    withdraw_project,
    get_cluster_view,
    get_cluster_graph_geojson,
    list_studies,
    get_stats,
)

router = APIRouter(tags=["cluster"], prefix="/api/cluster")


@router.post("/ingest")
async def ingest(
    dry_run: bool = Query(False),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Ingest TEC register rows into cluster studies and allocations."""
    return await ingest_from_tec_register(pool, dry_run=dry_run)


@router.post("/recompute-dependencies")
async def recompute(
    study_id: str | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Recompute cluster_dependencies edges. Optional study_id scope."""
    rows = await compute_dependencies(pool, study_id=study_id)
    return {"rows_inserted": rows, "study_id": study_id}


@router.get("/studies")
async def studies(pool: asyncpg.Pool = Depends(get_pool)):
    """List all cluster studies with project / upgrade counts."""
    return await list_studies(pool)


@router.get("/stats")
async def stats(pool: asyncpg.Pool = Depends(get_pool)):
    """System-wide cluster graph statistics."""
    return await get_stats(pool)


@router.get("/graph/{study_id}.geojson")
async def graph_geojson(study_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Return the cluster graph for a study as a GeoJSON FeatureCollection."""
    return await get_cluster_graph_geojson(pool, study_id)


@router.get("/{project_id}")
async def cluster_view(project_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Return the cluster neighbourhood for a single project."""
    view = await get_cluster_view(pool, project_id)
    if not view.get("upgrades"):
        raise HTTPException(404, f"No cluster allocations found for {project_id}")
    return view


@router.post("/{project_id}/withdraw")
async def withdraw(project_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Withdraw a project — redistributes upgrade cost across siblings and emits events."""
    result = await withdraw_project(pool, project_id)
    if not result["events"]:
        raise HTTPException(404, f"No current allocations for {project_id}")
    return result
