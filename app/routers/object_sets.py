"""Object Sets — Foundry's saved typed queries with set algebra.

  GET    /api/object-sets?type=&tag=&q=&pinned_only=
  GET    /api/object-sets/{slug}
  POST   /api/object-sets                          — create from filters
                                                    body {slug, name, object_type,
                                                          filters, tags?}
  POST   /api/object-sets/derive                   — create derived set
                                                    body {slug, name, op:union|intersect|subtract,
                                                          member_slugs|member_ids, filters?}
  PATCH  /api/object-sets/{slug}                   — partial update
  DELETE /api/object-sets/{slug}
  GET    /api/object-sets/{slug}/resolve?limit=    — runs the query, returns
                                                    items + count
  POST   /api/object-sets/{slug}/pin               — toggle pinned
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.deps import get_pool as _raw_pool  # noqa: F401
from app.middleware.tenant_jwt import get_tenant_pool as get_pool

log = logging.getLogger("princeps.object_sets")
router = APIRouter(prefix="/api/object-sets", tags=["object-sets"])

# Whitelist of types we know how to query (matches objects.py TYPE_REGISTRY)
_KNOWN_TYPES = {"Project", "Substation", "REPDProject", "NSIPProject", "TecQueueEntry", "Entity"}


def _row_to_dict(r) -> dict:
    return {
        "set_id": str(r["set_id"]),
        "slug": r["slug"],
        "name": r["name"],
        "description": r["description"],
        "object_type": r["object_type"],
        "filters": r["filters"] if isinstance(r["filters"], dict) else json.loads(r["filters"] or "{}"),
        "op": r["op"],
        "member_set_ids": [str(x) for x in (r["member_set_ids"] or [])],
        "tags": list(r["tags"] or []),
        "pinned": r["pinned"],
        "created_by": r["created_by"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


async def _resolve_member_ids(conn, member_slugs, member_ids) -> list[UUID]:
    out: list[UUID] = []
    if member_ids:
        for s in member_ids:
            try: out.append(UUID(s))
            except (ValueError, TypeError): raise HTTPException(400, f"invalid member id: {s}")
    if member_slugs:
        rows = await conn.fetch(
            "SELECT set_id FROM object_sets WHERE slug = ANY($1::text[])",
            member_slugs,
        )
        if len(rows) < len(set(member_slugs)):
            found = {r["set_id"] for r in rows}
            raise HTTPException(404, f"missing member sets — only resolved {len(found)} of {len(member_slugs)}")
        out.extend(r["set_id"] for r in rows)
    return out


@router.get("")
async def list_sets(
    type: str | None = Query(None),
    tag: str | None = Query(None),
    q: str | None = Query(None),
    pinned_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    pool: asyncpg.Pool = Depends(get_pool),
):
    where = []
    params: list[Any] = []
    def _b(v):
        params.append(v); return f"${len(params)}"
    if type: where.append(f"object_type = {_b(type)}")
    if tag: where.append(f"{_b(tag)} = ANY(tags)")
    if q: where.append(f"(name ILIKE '%' || {_b(q)} || '%' OR description ILIKE '%' || {_b(q)} || '%' OR slug ILIKE '%' || {_b(q)} || '%')")
    if pinned_only: where.append("pinned = TRUE")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT * FROM object_sets {where_sql}
        ORDER BY pinned DESC, updated_at DESC LIMIT {int(limit)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return {
        "sets": [_row_to_dict(r) for r in rows],
        "count": len(rows),
        "filters": {"type": type, "tag": tag, "q": q, "pinned_only": pinned_only},
    }


@router.post("")
async def create_set(
    body: dict[str, Any] = Body(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    slug = body.get("slug")
    name = body.get("name")
    object_type = body.get("object_type")
    filters = body.get("filters") or {}
    tags = body.get("tags") or []
    description = body.get("description")
    created_by = body.get("created_by", "anonymous")

    if not slug or not name or not object_type:
        raise HTTPException(400, "slug, name, object_type required")
    if object_type not in _KNOWN_TYPES:
        raise HTTPException(400, f"unknown object_type: {object_type}; must be one of {_KNOWN_TYPES}")
    if not isinstance(filters, dict):
        raise HTTPException(400, "filters must be a dict")
    if not isinstance(tags, list):
        raise HTTPException(400, "tags must be a list")

    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO object_sets
                  (slug, name, description, object_type, filters, tags, created_by)
                VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7)
                RETURNING *
                """,
                slug, name, description, object_type,
                json.dumps(filters, default=str), tags, created_by,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, f"slug '{slug}' already exists")
    return _row_to_dict(row)


@router.post("/derive")
async def derive_set(
    body: dict[str, Any] = Body(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    slug = body.get("slug")
    name = body.get("name")
    op = body.get("op")
    member_slugs = body.get("member_slugs") or []
    member_ids = body.get("member_ids") or []
    filters = body.get("filters") or {}
    description = body.get("description")
    created_by = body.get("created_by", "anonymous")

    if op not in {"union", "intersect", "subtract"}:
        raise HTTPException(400, "op must be union, intersect, or subtract")
    if not slug or not name:
        raise HTTPException(400, "slug, name required")

    async with pool.acquire() as conn:
        member_ids_resolved = await _resolve_member_ids(conn, member_slugs, member_ids)
        if len(member_ids_resolved) < 2:
            raise HTTPException(400, "need at least 2 member sets")
        # Member type must agree (we union/intersect by id, only meaningful within one type)
        rows = await conn.fetch(
            "SELECT object_type FROM object_sets WHERE set_id = ANY($1::uuid[])",
            member_ids_resolved,
        )
        types = {r["object_type"] for r in rows}
        if len(types) != 1:
            raise HTTPException(400, f"members must share object_type; got {sorted(types)}")
        object_type = types.pop()

        try:
            row = await conn.fetchrow(
                """
                INSERT INTO object_sets
                  (slug, name, description, object_type, filters, op,
                   member_set_ids, created_by)
                VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8)
                RETURNING *
                """,
                slug, name, description, object_type,
                json.dumps(filters, default=str), op,
                member_ids_resolved, created_by,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, f"slug '{slug}' already exists")
    return _row_to_dict(row)


@router.get("/{slug}")
async def get_set(slug: str, pool: asyncpg.Pool = Depends(get_pool)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM object_sets WHERE slug = $1", slug)
    if not row:
        raise HTTPException(404, f"set '{slug}' not found")
    return _row_to_dict(row)


@router.patch("/{slug}")
async def patch_set(
    slug: str,
    body: dict[str, Any] = Body(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    sets = []
    params: list[Any] = []
    def _b(v):
        params.append(v); return f"${len(params)}"
    if "name" in body: sets.append(f"name = {_b(body['name'])}")
    if "description" in body: sets.append(f"description = {_b(body['description'])}")
    if "filters" in body:
        if not isinstance(body["filters"], dict):
            raise HTTPException(400, "filters must be a dict")
        sets.append(f"filters = {_b(json.dumps(body['filters'], default=str))}::jsonb")
    if "tags" in body:
        if not isinstance(body["tags"], list):
            raise HTTPException(400, "tags must be a list")
        sets.append(f"tags = {_b(body['tags'])}")
    if "pinned" in body: sets.append(f"pinned = {_b(bool(body['pinned']))}")
    if not sets:
        raise HTTPException(400, "no editable fields supplied")
    params.append(slug)
    sql = f"UPDATE object_sets SET {', '.join(sets)} WHERE slug = ${len(params)} RETURNING *"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *params)
    if not row:
        raise HTTPException(404, "not found")
    return _row_to_dict(row)


@router.delete("/{slug}")
async def delete_set(slug: str, pool: asyncpg.Pool = Depends(get_pool)):
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM object_sets WHERE slug = $1", slug)
    if result == "DELETE 0":
        raise HTTPException(404, "not found")
    return {"slug": slug, "deleted": True}


@router.post("/{slug}/pin")
async def pin_set(
    slug: str,
    body: dict[str, Any] | None = Body(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    pinned = bool((body or {}).get("pinned", True))
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE object_sets SET pinned = $2 WHERE slug = $1 RETURNING *",
            slug, pinned,
        )
    if not row:
        raise HTTPException(404, "not found")
    return _row_to_dict(row)


@router.get("/{slug}/resolve")
async def resolve_set(
    slug: str,
    limit: int = Query(100, ge=1, le=2000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Resolve the set to its concrete object IDs by hitting `/api/objects/{type}`
    semantics directly via SQL. For derived sets, recurses through members and
    applies the set-algebra op."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM object_sets WHERE slug = $1", slug)
        if not row:
            raise HTTPException(404, "set not found")

        # Recurse
        ids = await _resolve_one(conn, row, limit=limit)

    return {
        "slug": slug,
        "object_type": row["object_type"],
        "count": len(ids),
        "object_ids": list(ids)[:limit],
    }


@router.get("/{slug}/items")
async def items_for_set(
    slug: str,
    limit: int = Query(100, ge=1, le=500),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Same as /resolve but joins to the source table and returns the
    full per-row payload, so Slate widgets can render directly from a set
    without making N detail calls.

    Returns the same shape as /api/objects/{type} (items: [{id,label,properties,...}, count, type)
    so existing widgets that consume that shape can swap their fetch URL
    transparently.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM object_sets WHERE slug = $1", slug)
        if not row:
            raise HTTPException(404, "set not found")
        ids = await _resolve_one(conn, row, limit=limit * 2)  # over-fetch a bit
        if not ids:
            return {"type": row["object_type"], "set_slug": slug, "count": 0, "items": []}
        ids_list = list(ids)[:limit]

        # Look up the full row for each id
        cfg = _TABLE_FOR_RESOLVE.get(row["object_type"])
        if not cfg:
            return {"type": row["object_type"], "set_slug": slug, "count": len(ids), "items": []}
        table, id_col = cfg
        # id_col may include a cast (e.g. "project_id::text"); strip it for filtering
        id_col_raw = id_col.split("::")[0]
        if row["object_type"] == "Project":
            select_sql = f"SELECT * FROM {table} WHERE {id_col_raw}::text = ANY($1::text[])"
        else:
            select_sql = f"SELECT * FROM {table} WHERE {id_col_raw}::text = ANY($1::text[])"
        records = await conn.fetch(select_sql, ids_list)

    # Reuse object loaders from objects.py for consistent shape
    from app.routers.objects import TYPE_REGISTRY
    loader = TYPE_REGISTRY[row["object_type"]]["loader"]
    items = [loader(r) for r in records]
    return {
        "type": row["object_type"],
        "set_slug": slug,
        "count": len(items),
        "items": items,
    }


async def _resolve_one(conn, row, limit: int = 2000) -> set:
    """Compute the concrete id set for one row (filter or derived)."""
    if row["op"]:
        # Derived — union/intersect/subtract over members
        members = await conn.fetch(
            "SELECT * FROM object_sets WHERE set_id = ANY($1::uuid[])",
            list(row["member_set_ids"] or []),
        )
        sets = []
        for m in members:
            sets.append(await _resolve_one(conn, m, limit))
        if not sets:
            return set()
        if row["op"] == "union":
            result = set().union(*sets)
        elif row["op"] == "intersect":
            result = set(sets[0]).intersection(*sets[1:])
        elif row["op"] == "subtract":
            result = set(sets[0]).difference(*sets[1:])
        else:
            result = set()

        # Apply post-composition filters if present (only narrows the set)
        post = row["filters"] if isinstance(row["filters"], dict) else json.loads(row["filters"] or "{}")
        if post:
            narrowed = await _filter_query(conn, row["object_type"], post, limit)
            result = result.intersection(narrowed)
        return result

    # Leaf — pure filter
    filters = row["filters"] if isinstance(row["filters"], dict) else json.loads(row["filters"] or "{}")
    return await _filter_query(conn, row["object_type"], filters, limit)


# Type → table + id-column for fast id-only queries
_TABLE_FOR_RESOLVE = {
    "Project":       ("projects",        "project_id::text"),
    "Substation":    ("grid_substations", "id::text"),
    "REPDProject":   ("repd_projects",   "repd_id"),
    "NSIPProject":   ("pins_nsip_dco",   "case_ref"),
    "TecQueueEntry": ("eso_tec_register", "tec_id"),
}


async def _filter_query(conn, object_type: str, filters: dict, limit: int) -> set:
    cfg = _TABLE_FOR_RESOLVE.get(object_type)
    if not cfg:
        # Entity has no proper table; return empty set rather than 500
        return set()
    table, id_col = cfg

    where = []
    params: list[Any] = []
    def _b(v):
        params.append(v); return f"${len(params)}"

    # Per-type filter mapping — mirrors the /api/objects route
    if object_type == "Project":
        if filters.get("stage"):       where.append(f"stage = {_b(filters['stage'])}")
        if filters.get("status"):      where.append(f"status = {_b(filters['status'])}")
        if filters.get("technology"):  where.append(f"technology = {_b(filters['technology'])}")
        if filters.get("capacity_min") is not None: where.append(f"capacity_mw >= {_b(filters['capacity_min'])}")
    elif object_type == "Substation":
        if filters.get("voltage_min") is not None: where.append(f"voltage_kv >= {_b(filters['voltage_min'])}")
        if filters.get("dno"):           where.append(f"dno = {_b(filters['dno'])}")
    elif object_type == "REPDProject":
        if filters.get("status"):     where.append(f"status ILIKE '%' || {_b(filters['status'])} || '%'")
        if filters.get("technology"): where.append(f"tech_category ILIKE '%' || {_b(filters['technology'])} || '%'")
        if filters.get("capacity_min") is not None: where.append(f"capacity_mw >= {_b(filters['capacity_min'])}")
    elif object_type == "NSIPProject":
        if filters.get("status"):    where.append(f"status ILIKE '%' || {_b(filters['status'])} || '%'")
        if filters.get("sector"):    where.append(f"sector ILIKE '%' || {_b(filters['sector'])} || '%'")
    elif object_type == "TecQueueEntry":
        if filters.get("status"):    where.append(f"status ILIKE '%' || {_b(filters['status'])} || '%'")
        if filters.get("voltage_min") is not None: where.append(f"voltage_kv >= {_b(filters['voltage_min'])}")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"SELECT {id_col} AS id FROM {table} {where_sql} LIMIT {int(limit)}"
    rows = await conn.fetch(sql, *params)
    return {r["id"] for r in rows if r["id"] is not None}
