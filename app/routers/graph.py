"""Graph shim REST surface — three GET endpoints over graph_nodes/graph_edges.

Mounted at /api/graph by FastAPI router prefix. Note: the legacy Neo4j router
in app/graph_neo4j.py also sits at /api/graph but uses path-param routes
(/topology, /hierarchy/{id}, /stats, /path/{from}/{to}, /search), so the new
query-param routes here do not collide.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_pool
from app.graph.cypher_shim import expand, match_nodes, match_path

log = logging.getLogger("princeps.graph_shim")

router = APIRouter(prefix="/api/graph", tags=["graph"])


def _parse_props_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except Exception as exc:
        raise HTTPException(400, f"props_json must be valid JSON: {exc}")
    if not isinstance(v, dict):
        raise HTTPException(400, "props_json must be a JSON object")
    return v


@router.get("/match")
async def graph_match(
    label: str | None = Query(None, description="exact label match"),
    props_json: str | None = Query(None, description="JSON object for jsonb @> match"),
    limit: int = Query(100, ge=1, le=1000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    props_filter = _parse_props_json(props_json)
    nodes = await match_nodes(pool, label=label, props_filter=props_filter, limit=limit)
    return {"count": len(nodes), "nodes": nodes}


@router.get("/expand/{rid}")
async def graph_expand(
    rid: str,
    edge_label: str | None = Query(None),
    direction: str = Query("out", pattern="^(out|in|both)$"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    nodes = await expand(pool, rid=rid, edge_label=edge_label, direction=direction)
    return {"start_rid": rid, "direction": direction, "count": len(nodes), "nodes": nodes}


@router.get("/path")
async def graph_path(
    start_rid: str = Query(..., description="rid to start the walk from"),
    edge_label: str = Query(..., description="edge label to traverse"),
    hops: int = Query(2, ge=1, le=10),
    end_label: str | None = Query(None, description="filter terminal nodes by label"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    paths = await match_path(
        pool, start_rid=start_rid, edge_label=edge_label,
        hops=hops, end_label=end_label,
    )
    return {
        "start_rid": start_rid,
        "edge_label": edge_label,
        "hops": hops,
        "count": len(paths),
        "paths": paths,
    }
