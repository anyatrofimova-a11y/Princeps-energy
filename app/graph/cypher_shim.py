"""Cypher-style helpers over the PG graph shim (graph_nodes / graph_edges).

Pure asyncpg — no AGE, no Cypher engine. Recursive CTEs cover the small set of
queries the MVP needs: label-and-props match, single-hop expand, bounded
multi-hop path. All functions are tenant-agnostic in this MVP (the default
tenant in the migration is fine for demo use); add a tenant arg later.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import asyncpg

# Hard cap on row counts to keep the recursive CTE bounded.
_PATH_HARD_CAP = 1000


async def add_node(
    pool: asyncpg.Pool,
    rid: str,
    label: str,
    props: Optional[dict[str, Any]] = None,
) -> None:
    """UPSERT a node by rid. Updates label/props/updated_at on conflict."""
    payload = json.dumps(props or {})
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO graph_nodes (rid, label, props)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (rid) DO UPDATE SET
                label = EXCLUDED.label,
                props = EXCLUDED.props,
                updated_at = NOW()
            """,
            rid, label, payload,
        )


async def add_edge(
    pool: asyncpg.Pool,
    from_rid: str,
    to_rid: str,
    label: str,
    props: Optional[dict[str, Any]] = None,
) -> None:
    """INSERT an edge. On (from_rid, to_rid, label) collision, refresh props."""
    payload = json.dumps(props or {})
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO graph_edges (from_rid, to_rid, label, props)
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT (from_rid, to_rid, label) DO UPDATE SET
                props = EXCLUDED.props
            """,
            from_rid, to_rid, label, payload,
        )


async def match_nodes(
    pool: asyncpg.Pool,
    label: Optional[str] = None,
    props_filter: Optional[dict[str, Any]] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return nodes matching label and/or jsonb-containment props_filter."""
    limit = max(1, min(int(limit), _PATH_HARD_CAP))
    filter_payload = json.dumps(props_filter) if props_filter else None
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT rid, label, props, tenant_id, created_at, updated_at
            FROM graph_nodes
            WHERE ($1::text IS NULL OR label = $1)
              AND ($2::jsonb IS NULL OR props @> $2::jsonb)
            ORDER BY updated_at DESC
            LIMIT $3
            """,
            label, filter_payload, limit,
        )
    return [_node_row_to_dict(r) for r in rows]


async def expand(
    pool: asyncpg.Pool,
    rid: str,
    edge_label: Optional[str] = None,
    direction: str = "out",
) -> list[dict[str, Any]]:
    """Single-hop expand from rid. direction in {'out','in','both'}."""
    if direction not in ("out", "in", "both"):
        raise ValueError("direction must be 'out', 'in', or 'both'")

    # Single CTE handles all 3 directions; the WHERE-clause picks branches.
    sql = """
        WITH out_hop AS (
            SELECT n.rid, n.label, n.props, n.tenant_id,
                   e.label AS edge_label, e.props AS edge_props,
                   'out'::text AS direction
            FROM graph_edges e JOIN graph_nodes n ON n.rid = e.to_rid
            WHERE $4::text IN ('out','both')
              AND e.from_rid = $1
              AND ($2::text IS NULL OR e.label = $2)
        ),
        in_hop AS (
            SELECT n.rid, n.label, n.props, n.tenant_id,
                   e.label AS edge_label, e.props AS edge_props,
                   'in'::text AS direction
            FROM graph_edges e JOIN graph_nodes n ON n.rid = e.from_rid
            WHERE $4::text IN ('in','both')
              AND e.to_rid = $1
              AND ($2::text IS NULL OR e.label = $2)
        )
        SELECT * FROM out_hop UNION ALL SELECT * FROM in_hop LIMIT $3
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, rid, edge_label, _PATH_HARD_CAP, direction)
    return [_expand_row_to_dict(r) for r in rows]


async def match_path(
    pool: asyncpg.Pool,
    start_rid: str,
    edge_label: str,
    hops: int = 2,
    end_label: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Recursive multi-hop expansion along a single edge label.

    Returns paths as a list of dicts with `rid`, `label`, `depth`, and the
    full chain of rids in `path_rids`. Hard-capped at LIMIT 1000 to keep the
    CTE bounded.
    """
    hops = max(1, min(int(hops), 10))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH RECURSIVE walk AS (
                SELECT  e.to_rid AS rid,
                        1 AS depth,
                        ARRAY[e.from_rid, e.to_rid] AS path_rids
                FROM    graph_edges e
                WHERE   e.from_rid = $1 AND e.label = $2
                UNION ALL
                SELECT  e.to_rid,
                        w.depth + 1,
                        w.path_rids || e.to_rid
                FROM    graph_edges e
                JOIN    walk w ON e.from_rid = w.rid
                WHERE   e.label = $2
                  AND   w.depth < $3
                  AND   NOT (e.to_rid = ANY(w.path_rids))
            )
            SELECT  w.rid, n.label, w.depth, w.path_rids, n.props
            FROM    walk w
            JOIN    graph_nodes n ON n.rid = w.rid
            WHERE   ($4::text IS NULL OR n.label = $4)
            ORDER BY w.depth, w.rid
            LIMIT   $5
            """,
            start_rid, edge_label, hops, end_label, _PATH_HARD_CAP,
        )
    out = []
    for r in rows:
        out.append({
            "rid": r["rid"],
            "label": r["label"],
            "depth": r["depth"],
            "path_rids": list(r["path_rids"]),
            "props": _jsonb_to_dict(r["props"]),
        })
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _jsonb_to_dict(v: Any) -> dict[str, Any]:
    if v is None:
        return {}
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return {}


def _node_row_to_dict(r: asyncpg.Record) -> dict[str, Any]:
    return {
        "rid": r["rid"],
        "label": r["label"],
        "props": _jsonb_to_dict(r["props"]),
        "tenant_id": str(r["tenant_id"]) if r["tenant_id"] else None,
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


def _expand_row_to_dict(r: asyncpg.Record) -> dict[str, Any]:
    return {
        "rid": r["rid"],
        "label": r["label"],
        "props": _jsonb_to_dict(r["props"]),
        "tenant_id": str(r["tenant_id"]) if r["tenant_id"] else None,
        "edge_label": r["edge_label"],
        "edge_props": _jsonb_to_dict(r["edge_props"]),
        "direction": r["direction"],
    }
