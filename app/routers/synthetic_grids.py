"""Synthetic Grids API — Princeps PowerGridSynth substitute (Task #19).

Generate realistic UK distribution networks on demand for capacity studies,
what-if analysis, and CGMES (IEC 61970-552) export.

Endpoints
---------
POST   /api/synthetic-grids/generate         Synthesise + persist a new grid
GET    /api/synthetic-grids                  List recent grids
GET    /api/synthetic-grids/{id}             Get metadata for one grid
GET    /api/synthetic-grids/{id}/export/cgmes  CGMES EQ-profile XML
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.deps import get_pool
from utils.synthetic_grid import (
    export_cgmes,
    get_synthetic_grid,
    list_synthetic_grids,
    synthesise_and_persist,
)

router = APIRouter(tags=["synthetic-grids"], prefix="/api/synthetic-grids")


class GenerateRequest(BaseModel):
    name: str | None = Field(default=None, description="Display name; auto-generated if omitted")
    dno_proxy: str = Field(default="NGED", description="DNO context: NGED|UKPN|NPg|SSEN|SPEN|ENWL")
    voltage_kv: int = Field(default=33, description="Primary distribution voltage (kV)")
    n_primary_busbars: int = Field(default=6, ge=2, le=24)
    n_secondary_per_primary: int = Field(default=3, ge=1, le=8)
    target_capacity_mw: float = Field(default=120.0, gt=0)
    load_diversity: float = Field(default=0.7, ge=0.1, le=1.0)
    seed: int = Field(default=42, description="Deterministic topology seed")
    centre: dict[str, float] | None = Field(
        default=None,
        description='WGS84 anchor, e.g. {"lat": 51.5, "lon": -0.6}',
    )


@router.post("/generate")
async def generate(req: GenerateRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """Synthesise a new UK distribution network and persist it.

    Returns the full topology (buses/lines/transformers with WGS84 coords)
    plus CGMES EQ-profile XML for downstream tools.
    """
    result = await synthesise_and_persist(pool, req.model_dump(exclude_none=False))
    if not result.get("success"):
        raise HTTPException(500, result.get("error", "synthesis failed"))
    return result


@router.get("")
async def list_grids(limit: int = Query(100, ge=1, le=500),
                     pool: asyncpg.Pool = Depends(get_pool)):
    return {"grids": await list_synthetic_grids(pool, limit=limit)}


@router.get("/{grid_id}")
async def get_grid(grid_id: int, pool: asyncpg.Pool = Depends(get_pool)):
    grid = await get_synthetic_grid(pool, grid_id)
    if not grid:
        raise HTTPException(404, f"Synthetic grid {grid_id} not found")
    return grid


@router.get("/{grid_id}/export/cgmes")
async def export_cgmes_xml(grid_id: int, pool: asyncpg.Pool = Depends(get_pool)):
    xml = await export_cgmes(pool, grid_id)
    if xml is None:
        raise HTTPException(404, f"Synthetic grid {grid_id} not found")
    return Response(content=xml, media_type="application/rdf+xml; profile=cgmes")
