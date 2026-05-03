"""Lineage graph — Foundry-style provenance trace.

  GET /api/lineage?root=<id>   — return the upstream + downstream graph for one node

Node shapes (each node has a typed `kind`):
  connector      — a Magritte connector slug (eg `bmrs_settlement_prices`)
  table          — a Postgres destination table (eg `bmrs_settlement_prices` or `repd_projects`)
  ontology_class — DTDL class id (eg `dtmi:com:princeps:Project;1`)
  object         — a single object RID (eg `rid.princeps.project.<uuid>`)
  derived        — a composed analytic view (eg `mission_control:top_owners`)

Edge shapes:
  feeds  — connector → table
  backs  — table → ontology_class
  joins  — derived → component table
  links  — object → linked object (entity_relationships, etc.)

The graph is computed on-demand from `princeps_datasets`, the TYPE_REGISTRY,
a hardcoded derived-views map, and outbound traversal of `entity_relationships`
+ `graph_edges`. Bounded to 2 hops upstream + 2 hops downstream so the response
stays small enough to render as an inline SVG.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_pool
from app.routers.objects import TYPE_REGISTRY

log = logging.getLogger("princeps.lineage")
router = APIRouter(prefix="/api/lineage", tags=["lineage"])


# ── Static lineage facts ────────────────────────────────────────────────────
# Tables → ontology class
_TABLE_TO_CLASS: dict[str, str] = {
    cfg["table"]: f"dtmi:com:princeps:{name};1"
    for name, cfg in TYPE_REGISTRY.items()
}

# Mission Control v2 derived views and their component tables
_DERIVED_VIEWS: dict[str, dict[str, Any]] = {
    "mc:top_owners": {
        "label": "Mission Control · Top Owners",
        "components": [
            "hm_land_registry_ccod",
            "repd_projects",
            "eso_tec_register",
        ],
        "ontology_class": "dtmi:com:princeps:Entity;1",
    },
    "mc:weekly_delta": {
        "label": "Mission Control · Weekly Delta",
        "components": [
            "repd_projects",
            "pins_nsip_dco",
            "dataset_refresh_log",
        ],
    },
    "mc:grid_pulse": {
        "label": "Mission Control · Grid Pulse",
        "components": [
            "bmrs_settlement_prices",
        ],
        "external_sources": [
            "carbonintensity.org.uk",
            "BMRS frequency endpoint",
        ],
    },
    "mc:pipeline_funnel": {
        "label": "Mission Control · Pipeline Funnel",
        "components": ["projects"],
        "ontology_class": "dtmi:com:princeps:Project;1",
    },
    "mc:council_activity": {
        "label": "Mission Control · Council Activity",
        "components": ["council_sessions", "ontology_action_log"],
    },
    "mc:action_queue": {
        "label": "Mission Control · Action Queue",
        "components": ["action_audit_log", "ontology_action_log"],
    },
    "lender_im": {
        "label": "Lender IM PDF",
        "components": [
            "projects",
            "repd_projects",
            "eso_tec_register",
            "grid_substations",
            "grid_ecr",
            "pins_nsip_dco",
        ],
        "ontology_class": "dtmi:com:princeps:Project;1",
    },
    "bess_live_revenue": {
        "label": "BESS Live Revenue",
        "components": ["bess_live_revenue_snapshots", "bmrs_settlement_prices"],
    },
}


def _kind_of(node_id: str) -> str:
    """Heuristic classifier for an opaque root id."""
    if node_id.startswith("rid.princeps."):
        return "object"
    if node_id.startswith("dtmi:"):
        return "ontology_class"
    if node_id.startswith("connector:"):
        return "connector"
    if node_id.startswith("table:"):
        return "table"
    if node_id.startswith("view:") or node_id.startswith("mc:") or node_id in _DERIVED_VIEWS:
        return "derived"
    # Could be a connector slug or a table — distinguish at query time
    return "table_or_connector"


def _ns(kind: str, raw: str) -> str:
    """Apply a namespace prefix so connector + table never collide when
    they share a string id (e.g. `bmrs_settlement_prices`)."""
    if kind == "connector": return f"connector:{raw}"
    if kind == "table":     return f"table:{raw}"
    if kind == "derived":   return raw if raw.startswith(("view:", "mc:")) else f"view:{raw}"
    return raw


def _unns(node_id: str) -> str:
    """Strip the namespace prefix to get the raw id back."""
    for p in ("connector:", "table:", "view:"):
        if node_id.startswith(p):
            return node_id[len(p):]
    return node_id


# ── Public endpoint ─────────────────────────────────────────────────────────
@router.get("")
async def lineage(
    root: str = Query(..., description="Connector slug, table name, ontology class, RID, or derived view id"),
    upstream_hops: int = Query(2, ge=0, le=4),
    downstream_hops: int = Query(2, ge=0, le=4),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return the lineage graph rooted at `root`.

    Returns: ``{root, root_kind, nodes: [{id, kind, label, props}],
                edges: [{from, to, rel}], stats: {n_nodes, n_edges}}``
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    async with pool.acquire() as conn:
        # Resolve "table_or_connector" by consulting princeps_datasets
        connector_rows = await _all_connectors(conn)
        connectors_by_slug = {r["slug"]: r for r in connector_rows}
        connectors_by_table = {r["table_name"]: r for r in connector_rows}

        kind = _kind_of(root)
        raw_root = root
        if kind == "table_or_connector":
            # Disambiguate first by exact slug match, else table.
            if root in connectors_by_slug:
                kind = "connector"
            else:
                kind = "table"
        elif kind == "connector":
            raw_root = _unns(root)
        elif kind == "table":
            raw_root = _unns(root)
        elif kind == "derived":
            raw_root = root  # already includes mc:/view: prefix

        # Seed the root with namespaced id
        root_id = _ns(kind, raw_root)
        _add_node(
            nodes, root_id, kind,
            _label_for(raw_root, connectors_by_slug, connectors_by_table),
        )

        # Walk upstream + downstream — pass the RAW id; walkers do their own namespacing
        await _walk_upstream(
            conn, raw_root, kind, upstream_hops,
            nodes, edges, connectors_by_slug, connectors_by_table,
        )
        await _walk_downstream(
            conn, raw_root, kind, downstream_hops,
            nodes, edges, connectors_by_slug, connectors_by_table,
        )

    return {
        "root": root_id,
        "root_kind": kind,
        "nodes": list(nodes.values()),
        "edges": edges,
        "stats": {"n_nodes": len(nodes), "n_edges": len(edges)},
    }


# ── Helpers ─────────────────────────────────────────────────────────────────
async def _all_connectors(conn) -> list[dict]:
    rows = await conn.fetch("""
        SELECT slug, title, table_name, license, refresh_cadence,
               last_refreshed_at, last_row_count, health_status
        FROM princeps_datasets
        ORDER BY slug
    """)
    return [dict(r) for r in rows]


def _label_for(node_id, by_slug, by_table) -> str:
    if node_id in by_slug:
        return by_slug[node_id]["title"] or node_id
    if node_id in by_table:
        return by_table[node_id]["title"] or node_id
    if node_id in _DERIVED_VIEWS:
        return _DERIVED_VIEWS[node_id]["label"]
    if node_id in _TABLE_TO_CLASS:
        return _TABLE_TO_CLASS[node_id]
    if node_id.startswith("dtmi:"):
        # Pull the type segment
        try:
            return node_id.split(":")[2].split(";")[0]
        except Exception:
            return node_id
    return node_id


def _add_node(nodes, node_id, kind, label, **props):
    if node_id in nodes:
        return
    nodes[node_id] = {
        "id": node_id,
        "kind": kind,
        "label": label,
        **props,
    }


def _add_edge(edges, frm, to, rel):
    for e in edges:
        if e["from"] == frm and e["to"] == to and e["rel"] == rel:
            return
    edges.append({"from": frm, "to": to, "rel": rel})


async def _walk_upstream(conn, raw_id, kind, hops, nodes, edges, by_slug, by_table):
    """Trace upstream: derived → table → connector → external. `raw_id` is
    the unprefixed identifier; we apply namespacing when adding nodes."""
    if hops <= 0:
        return

    if kind == "derived":
        # raw_id already contains mc: or view: prefix
        view_key = raw_id
        view = _DERIVED_VIEWS.get(view_key)
        if not view:
            return
        view_node_id = _ns("derived", view_key)
        for tbl in view.get("components", []):
            tbl_id = _ns("table", tbl)
            _add_node(nodes, tbl_id, "table", _label_for(tbl, by_slug, by_table))
            _add_edge(edges, tbl_id, view_node_id, "joins")
            await _walk_upstream(conn, tbl, "table", hops - 1, nodes, edges, by_slug, by_table)
        for ext in view.get("external_sources", []):
            ext_id = f"ext:{ext}"
            _add_node(nodes, ext_id, "external", ext)
            _add_edge(edges, ext_id, view_node_id, "feeds")

    elif kind == "table":
        tbl_id = _ns("table", raw_id)
        if raw_id in by_table:
            c = by_table[raw_id]
            conn_id = _ns("connector", c["slug"])
            _add_node(
                nodes, conn_id, "connector", c["title"] or c["slug"],
                license=c["license"],
                refresh_cadence=c["refresh_cadence"],
                last_row_count=c["last_row_count"],
                health_status=c["health_status"],
            )
            _add_edge(edges, conn_id, tbl_id, "feeds")
            await _walk_upstream(conn, c["slug"], "connector", hops - 1, nodes, edges, by_slug, by_table)

    elif kind == "connector":
        c = by_slug.get(raw_id)
        if c:
            ext_id = f"ext:upstream:{raw_id}"
            _add_node(nodes, ext_id, "external", c.get("title") or "upstream")
            _add_edge(edges, ext_id, _ns("connector", raw_id), "feeds")

    elif kind == "ontology_class":
        for tbl, cls in _TABLE_TO_CLASS.items():
            if cls == raw_id:
                tbl_id = _ns("table", tbl)
                _add_node(nodes, tbl_id, "table", _label_for(tbl, by_slug, by_table))
                _add_edge(edges, tbl_id, raw_id, "backs")
                await _walk_upstream(conn, tbl, "table", hops - 1, nodes, edges, by_slug, by_table)

    elif kind == "object":
        parts = raw_id.split(".", 3)
        if len(parts) >= 3:
            type_segment = parts[2]
            type_map = {
                "project": "Project", "substation": "Substation",
                "repd": "REPDProject", "nsip": "NSIPProject",
                "tec": "TecQueueEntry", "entity": "Entity",
            }
            cls_short = type_map.get(type_segment.lower())
            if cls_short:
                cls_id = f"dtmi:com:princeps:{cls_short};1"
                _add_node(nodes, cls_id, "ontology_class", cls_short)
                _add_edge(edges, cls_id, raw_id, "instantiates")
                await _walk_upstream(conn, cls_id, "ontology_class", hops - 1, nodes, edges, by_slug, by_table)


async def _walk_downstream(conn, raw_id, kind, hops, nodes, edges, by_slug, by_table):
    """Trace downstream: connector → table → ontology_class → derived."""
    if hops <= 0:
        return

    if kind == "connector":
        c = by_slug.get(raw_id)
        if not c:
            return
        tbl = c["table_name"]
        conn_id = _ns("connector", raw_id)
        tbl_id = _ns("table", tbl)
        _add_node(nodes, tbl_id, "table", _label_for(tbl, by_slug, by_table))
        _add_edge(edges, conn_id, tbl_id, "feeds")
        await _walk_downstream(conn, tbl, "table", hops - 1, nodes, edges, by_slug, by_table)

    elif kind == "table":
        tbl_id = _ns("table", raw_id)
        cls = _TABLE_TO_CLASS.get(raw_id)
        if cls:
            _add_node(nodes, cls, "ontology_class", _label_for(cls, by_slug, by_table))
            _add_edge(edges, tbl_id, cls, "backs")
            await _walk_downstream(conn, cls, "ontology_class", hops - 1, nodes, edges, by_slug, by_table)
        for view_id, view in _DERIVED_VIEWS.items():
            if raw_id in view.get("components", []):
                vid = _ns("derived", view_id)
                _add_node(nodes, vid, "derived", view["label"])
                _add_edge(edges, tbl_id, vid, "joins")

    elif kind == "ontology_class":
        for view_id, view in _DERIVED_VIEWS.items():
            if view.get("ontology_class") == raw_id:
                vid = _ns("derived", view_id)
                _add_node(nodes, vid, "derived", view["label"])
                _add_edge(edges, raw_id, vid, "joins")

    elif kind == "derived":
        return

    elif kind == "object":
        try:
            rows = await conn.fetch(
                """
                SELECT to_rid, label, props
                FROM graph_edges WHERE from_rid = $1 LIMIT 12
                """,
                raw_id,
            )
            for r in rows:
                _add_node(nodes, r["to_rid"], "object", r["to_rid"])
                _add_edge(edges, raw_id, r["to_rid"], r["label"])
        except Exception as exc:
            log.warning("graph_edges traversal failed for %s: %s", raw_id, exc)


@router.get("/catalogue")
async def lineage_catalogue(pool: asyncpg.Pool = Depends(get_pool)):
    """Quick index of everything that has lineage we can show."""
    async with pool.acquire() as conn:
        connectors = await _all_connectors(conn)
    return {
        "connectors": [
            {"slug": c["slug"], "table": c["table_name"], "title": c["title"]}
            for c in connectors
        ],
        "ontology_classes": [
            {"id": cls, "table": tbl, "type": cls.split(":")[2].split(";")[0]}
            for tbl, cls in _TABLE_TO_CLASS.items()
        ],
        "derived_views": [
            {"id": k, "label": v["label"], "components": v["components"]}
            for k, v in _DERIVED_VIEWS.items()
        ],
    }
