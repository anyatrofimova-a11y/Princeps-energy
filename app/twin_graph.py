"""Twin graph traversal helpers — recursive-CTE based.

Pragmatic stand-in for Apache AGE openCypher queries while AGE isn't
installed locally. Covers the queries the Twin Explorer + Object Inspector
need today:
  • bfs_neighbors(rid, hops, rel_filter)
  • subgraph_for(root_rid, hops) — returns {nodes, edges} for cytoscape
  • shortest_path(from_rid, to_rid, max_hops)

Swap implementations for openCypher (`SELECT * FROM cypher(...)`) once
Apache AGE is built against Postgres 17.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger("princeps.twin_graph")


async def bfs_neighbors(pool, rid: str, *, hops: int = 2, rel_filter: str | None = None) -> list[dict]:
    """Return distinct neighbor rids within `hops`, with their min-depth and
    the first relationship name traversed.
    """
    sql = """
    WITH RECURSIVE traverse(rid, depth, last_rel) AS (
        SELECT $1::text, 0, NULL::text
        UNION
        SELECT
            CASE WHEN tr.from_rid = t.rid THEN tr.to_rid ELSE tr.from_rid END,
            t.depth + 1,
            tr.rel_name
        FROM twin_relationships tr
        JOIN traverse t ON tr.from_rid = t.rid OR tr.to_rid = t.rid
        WHERE t.depth < $2
          AND ($3::text IS NULL OR tr.rel_name = $3)
    )
    SELECT rid, MIN(depth) AS depth, MIN(last_rel) AS first_rel
    FROM traverse
    WHERE rid != $1
    GROUP BY rid
    ORDER BY depth, rid
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, rid, hops, rel_filter)
    return [dict(r) for r in rows]


async def subgraph_for(pool, root_rid: str, *, hops: int = 2) -> dict:
    """Return {nodes, edges} dict suitable for cytoscape / D3 rendering.

    Nodes: [{rid, dtmi, label, properties}]
    Edges: [{rid, from_rid, to_rid, rel_name, properties}]
    """
    neighbors = await bfs_neighbors(pool, root_rid, hops=hops)
    rids = [root_rid] + [n["rid"] for n in neighbors]

    async with pool.acquire() as conn:
        nodes = await conn.fetch(
            """
            SELECT rid, dtmi, properties
            FROM twin_instances
            WHERE rid = ANY($1::text[])
            """,
            rids,
        )
        edges = await conn.fetch(
            """
            SELECT rid, from_rid, to_rid, rel_name, properties
            FROM twin_relationships
            WHERE from_rid = ANY($1::text[]) AND to_rid = ANY($1::text[])
            """,
            rids,
        )

    out_nodes = []
    for n in nodes:
        props = _to_dict(n["properties"])
        out_nodes.append({
            "rid": n["rid"], "dtmi": n["dtmi"],
            "label": props.get("name") or n["rid"].split(".")[-1],
            "properties": props,
        })
    out_edges = [
        {
            "rid": e["rid"], "from_rid": e["from_rid"], "to_rid": e["to_rid"],
            "rel_name": e["rel_name"], "properties": _to_dict(e["properties"]),
        }
        for e in edges
    ]
    return {"nodes": out_nodes, "edges": out_edges}


async def shortest_path(pool, from_rid: str, to_rid: str, *, max_hops: int = 6) -> list[str] | None:
    """BFS shortest hop path. Returns the rid sequence including endpoints,
    or None if no path within max_hops.
    """
    sql = """
    WITH RECURSIVE traverse(rid, path) AS (
        SELECT $1::text, ARRAY[$1::text]
        UNION
        SELECT
            CASE WHEN tr.from_rid = t.rid THEN tr.to_rid ELSE tr.from_rid END,
            t.path || CASE WHEN tr.from_rid = t.rid THEN tr.to_rid ELSE tr.from_rid END
        FROM twin_relationships tr
        JOIN traverse t ON (tr.from_rid = t.rid OR tr.to_rid = t.rid)
        WHERE NOT (CASE WHEN tr.from_rid = t.rid THEN tr.to_rid ELSE tr.from_rid END = ANY(t.path))
          AND array_length(t.path, 1) <= $3
    )
    SELECT path
    FROM traverse
    WHERE rid = $2
    ORDER BY array_length(path, 1)
    LIMIT 1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, from_rid, to_rid, max_hops)
    return list(row["path"]) if row else None


def _to_dict(v) -> dict:
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
