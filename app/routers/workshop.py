"""Workshop shell support endpoints — feeds the left ontology tree and right
ObjectInspector with a uniform shape regardless of underlying table.

Lives under `/api/workshop/*` to avoid colliding with the existing
`app/routers/ontology.py` dispatch router (which owns `/api/ontology/*`).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, HTTPException, Request

log = logging.getLogger("princeps.workshop_router")

router = APIRouter(prefix="/api/workshop", tags=["workshop"])


@router.get("/scene/{rid:path}")
async def get_scene(rid: str, request: Request, hops: int = 3):
    """Returns the full subtree under `rid` for procedural 3D scene rendering."""
    from app.twin_graph import subgraph_for  # lazy
    pool = request.app.state.pool
    return await subgraph_for(pool, rid, hops=hops)


@router.post("/build-geometry/{rid:path}")
async def build_geometry(rid: str, request: Request):
    """Trigger the IFC4 generation pipeline for a twin instance.

    Walks the subtree under `rid` via `subgraph_for`, dispatches to
    cad_pipeline.build_dc_ifc / build_bess_ifc, writes the .ifc file to
    static/cad/, and registers it in geometry_assets + mesh_bindings.
    """
    import os, json, uuid as _uuid
    from pathlib import Path as _Path
    from app.twin_graph import subgraph_for
    from app.twin import build_dc_ifc, build_bess_ifc, convert_ifc_to_glb, rid_to_global_id

    pool = request.app.state.pool
    subtree = await subgraph_for(pool, rid, hops=4)
    if not subtree.get("nodes"):
        raise HTTPException(404, f"no subgraph under {rid}")

    root = next((n for n in subtree["nodes"] if n["rid"] == rid), None)
    if not root:
        raise HTTPException(404, f"root rid not found in subgraph: {rid}")

    cad_dir = _Path("static/cad")
    glb_dir = _Path("static/glb")
    cad_dir.mkdir(parents=True, exist_ok=True)
    glb_dir.mkdir(parents=True, exist_ok=True)
    geometry_rid = f"rid.princeps.production.geometry.{_uuid.uuid4()}"
    ifc_path = cad_dir / f"{geometry_rid}.ifc"
    glb_path = glb_dir / f"{geometry_rid}.glb"

    if root["dtmi"] == "dtmi:com:princeps:DataCentre;1":
        result = build_dc_ifc(subtree, ifc_path)
    elif root["dtmi"] == "dtmi:com:princeps:BESSUnit;1":
        result = build_bess_ifc(subtree, ifc_path)
    else:
        raise HTTPException(400, f"no IFC builder for type {root['dtmi']}")

    # Convert to glTF (best-effort — IFC stays the source of truth).
    try:
        glb_result = convert_ifc_to_glb(ifc_path, glb_path)
        result["glb_path"] = glb_result["glb_path"]
        result["glb_url"] = f"/static/glb/{glb_path.name}"
        result["glb_shapes"] = glb_result["shapes_written"]
    except Exception as exc:
        log.exception("glTF conversion failed: %s", exc)
        result["glb_error"] = f"{type(exc).__name__}: {exc}"

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO geometry_assets (rid, twin_rid, source_format, source_path, glb_url, metadata, ingested_at)
            VALUES ($1, $2, 'ifc', $3, $4, $5, NOW())
            ON CONFLICT (rid) DO UPDATE SET source_path=EXCLUDED.source_path,
                glb_url=EXCLUDED.glb_url, metadata=EXCLUDED.metadata
            """,
            geometry_rid, rid, str(ifc_path), result.get("glb_url"), json.dumps(result),
        )
        # Bind every twin_instance in the subtree to its IFC GlobalId.
        bindings = [
            (geometry_rid, rid_to_global_id(n["rid"]), n["rid"], _ifc_class_for(n["dtmi"]))
            for n in subtree["nodes"]
        ]
        await conn.executemany(
            """
            INSERT INTO mesh_bindings (geometry_rid, mesh_node_id, twin_rid, ifc_class)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT DO NOTHING
            """,
            bindings,
        )

    return {
        "geometry_rid": geometry_rid,
        "twin_rid": rid,
        "ifc_path": str(ifc_path),
        "glb_url": result.get("glb_url"),
        "bindings_created": len(bindings),
        **result,
    }


@router.get("/geometry/{twin_rid:path}")
async def get_geometry_for_twin(twin_rid: str, request: Request):
    """Return the latest geometry_asset for a twin RID PLUS its mesh
    bindings — TwinScene uses bindings to resolve a clicked mesh's
    IFC GlobalId back to a Princeps RID without a second fetch.
    """
    import json as _json
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT rid AS geometry_rid, twin_rid, source_path, glb_url, metadata, ingested_at
            FROM geometry_assets
            WHERE twin_rid = $1
            ORDER BY ingested_at DESC
            LIMIT 1
            """,
            twin_rid,
        )
        if not row:
            return {"geometry_rid": None, "glb_url": None, "twin_rid": twin_rid, "bindings": {}}
        bindings_rows = await conn.fetch(
            """
            SELECT mesh_node_id, twin_rid, ifc_class
            FROM mesh_bindings
            WHERE geometry_rid = $1
            """,
            row["geometry_rid"],
        )
    out = dict(row)
    if out.get("metadata"):
        out["metadata"] = _json.loads(out["metadata"]) if isinstance(out["metadata"], str) else out["metadata"]
    if out.get("ingested_at"):
        out["ingested_at"] = out["ingested_at"].isoformat()
    out["bindings"] = {b["mesh_node_id"]: {"rid": b["twin_rid"], "ifc_class": b["ifc_class"]} for b in bindings_rows}
    return out


def _ifc_class_for(dtmi: str | None) -> str:
    if not dtmi: return "IfcRoot"
    short = dtmi.split(":")[-1].split(";")[0]
    return {
        "DataCentre": "IfcBuilding",
        "BESSUnit":   "IfcBuilding",
        "DcHall":     "IfcSpace",
        "DcAisle":    "IfcSpace",
        "BessBlock":  "IfcSpace",
        "BessRack":   "IfcBuildingElementProxy",
        "Substation": "IfcDistributionElement",
    }.get(short, "IfcProduct")


# ───────── Hierarchy + search for the v2 shell ─────────

_STAGE_ORDER = [
    "prospect", "screened", "grid_applied", "grid_offer",
    "planning", "fid", "construction", "energised", "operational", "decommissioned",
    "unstaged",
]
_WORKFLOW_ORDER = ["site", "study", "connect", "plan", "impact", "act", "unstaged"]


@router.get("/hierarchy")
async def get_hierarchy(request: Request, axis: str = "stage", type: str = "all"):
    """Returns the explorer tree, grouped by `axis` (stage|workflow|type).

    Combines twin_instances + entities into a single normalized list, then
    buckets by the requested axis. Each item has {rid, type, name, badges}.

    Tolerant: if either source table is missing on a fresh DB, that source
    contributes zero items rather than 500-ing the whole endpoint.
    """
    pool = request.app.state.pool
    items: list[dict] = []
    async with pool.acquire() as conn:
        try:
            twins = await conn.fetch(
                "SELECT rid, dtmi, properties FROM twin_instances",
            )
        except asyncpg.UndefinedTableError:
            twins = []
        for t in twins:
            props = _props(t["properties"])
            obj_type = _dtmi_to_type(t["dtmi"])
            if type != "all" and obj_type != type:
                continue
            items.append({
                "rid": t["rid"],
                "type": obj_type,
                "name": props.get("name") or props.get("blockId") or props.get("rackId")
                       or props.get("hallId") or props.get("aisleId") or t["rid"].split(".")[-1],
                "stage": (props.get("stage") or "unstaged").lower(),
                "workflow": (props.get("workflowStage") or "unstaged").lower(),
                "badges": {},
            })
        if type in ("all", "counterparty"):
            try:
                ents = await conn.fetch(
                    "SELECT rid, legal_name, role, sanctions_flag FROM entities ORDER BY legal_name",
                )
            except asyncpg.UndefinedTableError:
                ents = []
            for e in ents:
                items.append({
                    "rid": e["rid"],
                    "type": "counterparty",
                    "name": e["legal_name"],
                    "stage": "unstaged",
                    "workflow": "unstaged",
                    "badges": {"red": 1} if e["sanctions_flag"] else {},
                })

    return _bucket(items, axis)


@router.get("/search")
async def search_ontology(request: Request, q: str, limit: int = 20):
    """Free-text search across entities + twin_instances. ILIKE for now."""
    if not q or len(q) < 2:
        return {"items": []}
    pool = request.app.state.pool
    out: list[dict] = []
    pattern = f"%{q}%"
    async with pool.acquire() as conn:
        twins = await conn.fetch(
            """
            SELECT rid, dtmi, properties FROM twin_instances
            WHERE rid ILIKE $1
               OR (properties->>'name')   ILIKE $1
               OR (properties->>'blockId') ILIKE $1
               OR (properties->>'rackId')  ILIKE $1
               OR (properties->>'hallId')  ILIKE $1
               OR (properties->>'aisleId') ILIKE $1
            LIMIT $2
            """, pattern, limit,
        )
        for t in twins:
            props = _props(t["properties"])
            out.append({
                "rid": t["rid"],
                "type": _dtmi_to_type(t["dtmi"]),
                "name": props.get("name") or t["rid"].split(".")[-1],
                "snippet": props.get("vendor") or props.get("model") or props.get("tier") or "",
            })
        ents = await conn.fetch(
            "SELECT rid, legal_name, role FROM entities WHERE legal_name ILIKE $1 LIMIT $2",
            pattern, limit,
        )
        for e in ents:
            out.append({
                "rid": e["rid"],
                "type": "counterparty",
                "name": e["legal_name"],
                "snippet": e["role"] or "",
            })
    return {"items": out[:limit]}


def _props(v):
    import json as _json
    if v is None: return {}
    if isinstance(v, dict): return v
    if isinstance(v, str):
        try: return _json.loads(v)
        except Exception: return {}
    return {}


def _dtmi_to_type(dtmi: str | None) -> str:
    if not dtmi: return "unknown"
    import re as _re
    # dtmi:com:princeps:DataCentre;1 → data_centre
    # dtmi:com:princeps:BESSUnit;1   → bess_unit (acronyms collapse)
    raw = dtmi.split(":")[-1].split(";")[0]
    s = _re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', raw)
    s = _re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
    return s.lower()


def _bucket(items: list[dict], axis: str) -> list[dict]:
    if axis == "type":
        order = sorted({i["type"] for i in items})
        labels = {t: t.replace("_", " ").title() for t in order}
        key_fn = lambda i: i["type"]
    elif axis == "workflow":
        order = _WORKFLOW_ORDER
        labels = {s: s.title() for s in order}
        key_fn = lambda i: i["workflow"] if i["workflow"] in order else "unstaged"
    else:  # stage
        order = _STAGE_ORDER
        labels = {s: s.replace("_", " ").title() for s in order}
        key_fn = lambda i: i["stage"] if i["stage"] in order else "unstaged"

    grouped: dict[str, list[dict]] = {}
    for it in items:
        grouped.setdefault(key_fn(it), []).append(it)

    return [
        {"bucket_id": k, "label": labels.get(k, k), "count": len(grouped[k]), "items": grouped[k]}
        for k in order if k in grouped
    ]


@router.get("/object/{rid:path}")
async def get_object(rid: str, request: Request):
    """Single-object lookup. Tries entities → twin_instances → grid_substations
    in that order. Returns a uniform `{type, rid, name, properties, relationships}`.
    """
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        ent = await conn.fetchrow(
            "SELECT rid, legal_name, lei, ch_number, role, parent_rid, sanctions_flag "
            "FROM entities WHERE rid=$1", rid,
        )
        if ent:
            rels = await conn.fetch(
                "SELECT rid, from_rid, to_rid, rel_type, properties FROM entity_relationships "
                "WHERE from_rid=$1 OR to_rid=$1 LIMIT 100", rid,
            )
            return {
                "type": "Counterparty", "rid": rid,
                "name": ent["legal_name"],
                "properties": _row_to_props(ent),
                "relationships": [_rel(r) for r in rels],
            }

        twin = await conn.fetchrow(
            "SELECT rid, dtmi, properties, last_telemetry_at FROM twin_instances WHERE rid=$1", rid,
        )
        if twin:
            rels = await conn.fetch(
                "SELECT rid, from_rid, to_rid, rel_name AS rel_type, properties FROM twin_relationships "
                "WHERE from_rid=$1 OR to_rid=$1 LIMIT 100", rid,
            )
            props = _to_dict(twin["properties"])
            return {
                "type": (twin["dtmi"] or "TwinInstance").split(":")[-1].split(";")[0],
                "rid": rid,
                "name": props.get("name") or rid,
                "properties": props,
                "relationships": [_rel(r) for r in rels],
            }

        # Fallback: grid_substations don't yet have RIDs — try by id-locator.
        locator = rid.split(".")[-1]
        sub = await conn.fetchrow(
            "SELECT id, name, voltage_kv, dno_area FROM grid_substations WHERE id::text=$1 LIMIT 1",
            locator,
        )
        if sub:
            return {
                "type": "Substation", "rid": rid,
                "name": sub["name"],
                "properties": _row_to_props(sub),
                "relationships": [],
            }
    raise HTTPException(404, f"object not found: {rid}")


@router.get("/tree")
async def get_tree(request: Request, max_branches: int = 50):
    """Two-level tree for the left rail:
       1. DNO areas → substations
       2. "Counterparties" branch → entities
       3. "Twin instances" branch → twin_instances grouped by DTMI
    """
    pool = request.app.state.pool
    tree: list[dict[str, Any]] = []

    async with pool.acquire() as conn:
        # Branch 1: substations grouped by dno_area.
        try:
            subs = await conn.fetch(
                "SELECT id, name, dno_area FROM grid_substations LIMIT $1", max_branches * 4,
            )
            by_dno: dict[str, list] = {}
            for s in subs:
                by_dno.setdefault(s["dno_area"] or "Unassigned", []).append(s)
            for dno, items in sorted(by_dno.items()):
                tree.append({
                    "rid": f"group:dno:{dno}",
                    "name": f"DNO · {dno}",
                    "badges": {"green": len(items)},
                    "children": [{
                        "rid": f"rid.princeps.production.substation.{i['id']}",
                        "name": i["name"],
                        "badges": {},
                        "children": [],
                    } for i in items[:max_branches]],
                })
        except Exception as exc:
            log.warning("workshop tree: substation branch failed: %s", exc)

        # Branch 2: counterparties (entities).
        try:
            ents = await conn.fetch(
                "SELECT rid, legal_name, role, sanctions_flag FROM entities ORDER BY legal_name LIMIT $1",
                max_branches,
            )
            if ents:
                tree.append({
                    "rid": "group:counterparties",
                    "name": "Counterparties",
                    "badges": {
                        "blue": len(ents),
                        "red": sum(1 for e in ents if e["sanctions_flag"]),
                    },
                    "children": [{
                        "rid": e["rid"], "name": e["legal_name"],
                        "badges": {"red": 1} if e["sanctions_flag"] else {},
                        "children": [],
                    } for e in ents],
                })
        except Exception as exc:
            log.warning("workshop tree: entities branch failed: %s", exc)

        # Branch 3: twin instances by DTMI.
        try:
            twins = await conn.fetch(
                "SELECT rid, dtmi, properties FROM twin_instances LIMIT $1", max_branches * 4,
            )
            by_dtmi: dict[str, list] = {}
            for t in twins:
                by_dtmi.setdefault(t["dtmi"] or "Unknown", []).append(t)
            for dtmi, items in sorted(by_dtmi.items()):
                short = dtmi.split(":")[-1].split(";")[0]
                tree.append({
                    "rid": f"group:dtmi:{dtmi}",
                    "name": f"Twin · {short}",
                    "badges": {"blue": len(items)},
                    "children": [{
                        "rid": t["rid"],
                        "name": _to_dict(t["properties"]).get("name") or t["rid"],
                        "badges": {},
                        "children": [],
                    } for t in items[:max_branches]],
                })
        except Exception as exc:
            log.warning("workshop tree: twin_instances branch failed: %s", exc)

    return tree


def _row_to_props(row) -> dict:
    out = {}
    for k, v in dict(row).items():
        if v is None:
            continue
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _rel(row) -> dict:
    return {
        "rid": row["rid"],
        "from_rid": row["from_rid"],
        "to_rid": row["to_rid"],
        "rel_type": row["rel_type"],
        "properties": _to_dict(row.get("properties")) if "properties" in row.keys() else {},
    }


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
