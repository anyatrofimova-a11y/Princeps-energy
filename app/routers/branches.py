"""Object branches — Foundry-style fork-and-merge over object_versions.

Endpoints:
  POST   /api/branches                       — create from {rid, name, description?}
  GET    /api/branches?rid=<rid>             — list branches for an rid
  GET    /api/branches/{branch_id}           — branch metadata + edit timeline
  POST   /api/branches/{branch_id}/edit      — append {props, diff?, message?}
  GET    /api/branches/{branch_id}/resolve   — fully-resolved props (base + edits)
  POST   /api/branches/{branch_id}/merge     — write resolved props to graph_nodes
                                                (auto-emits ObjectMutated; new version
                                                 lands on main); marks status='merged'
  DELETE /api/branches/{branch_id}           — soft-discard (status='discarded')

The graph_nodes upsert at merge fires emit_object_mutated, so the merge
becomes a normal main-line ObjectMutated audit row + a new object_versions
entry. No special main-branch concept — main IS object_versions.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.deps import get_pool

log = logging.getLogger("princeps.branches")
router = APIRouter(prefix="/api/branches", tags=["branches"])


def _parse_uuid(s: str) -> UUID:
    try:
        return UUID(s)
    except (ValueError, TypeError):
        raise HTTPException(400, f"invalid branch_id: {s}")


async def _current_props(conn, rid: str) -> tuple[str | None, dict | None, int | None]:
    """Return (label, props, latest_version_id) for the rid as of now —
    the seed for a new branch. Reads from object_versions (latest open
    valid_to=NULL row) so branches see the same view as time-travel."""
    row = await conn.fetchrow(
        """
        SELECT id, label, props
        FROM object_versions
        WHERE rid = $1 AND valid_to IS NULL AND op != 'DELETE'
        ORDER BY valid_from DESC LIMIT 1
        """,
        rid,
    )
    if not row:
        # Object may exist in graph_nodes but not yet in object_versions
        # (e.g. seeded before triggers landed). Fall back.
        gn = await conn.fetchrow(
            "SELECT label, props FROM graph_nodes WHERE rid = $1",
            rid,
        )
        if not gn:
            return None, None, None
        return gn["label"], _decode(gn["props"]), None
    return row["label"], _decode(row["props"]), row["id"]


def _decode(v):
    if v is None:
        return None
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return None
    return v


@router.post("")
async def create_branch(
    body: dict[str, Any] = Body(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    rid = body.get("rid")
    name = body.get("name")
    description = body.get("description")
    parent_branch_id = body.get("parent_branch_id")
    actor = body.get("actor", "anonymous")

    if not rid or not name:
        raise HTTPException(400, "rid and name are required")
    if name == "main":
        raise HTTPException(400, "'main' is reserved")

    async with pool.acquire() as conn:
        label, props, base_version_id = await _current_props(conn, rid)
        if props is None:
            raise HTTPException(404, f"object {rid} not found")

        try:
            row = await conn.fetchrow(
                """
                INSERT INTO object_branches
                  (rid, name, description, base_version_id, parent_branch_id, created_by)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING branch_id, created_at
                """,
                rid, name, description, base_version_id,
                _parse_uuid(parent_branch_id) if parent_branch_id else None,
                actor,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, f"branch '{name}' already exists for {rid}")

    return {
        "branch_id": str(row["branch_id"]),
        "rid": rid,
        "name": name,
        "base_version_id": base_version_id,
        "base_props": props,
        "base_label": label,
        "created_at": row["created_at"].isoformat(),
        "status": "open",
    }


@router.get("")
async def list_branches(
    rid: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    pool: asyncpg.Pool = Depends(get_pool),
):
    where = []
    params: list[Any] = []
    if rid:
        params.append(rid)
        where.append(f"rid = ${len(params)}")
    if status:
        params.append(status)
        where.append(f"status = ${len(params)}")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    sql = f"""
        SELECT branch_id, rid, name, description, status, base_version_id,
               parent_branch_id, created_by, created_at, merged_at, merged_by
        FROM object_branches
        {where_sql}
        ORDER BY created_at DESC
        LIMIT ${len(params)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return {
        "branches": [
            {
                "branch_id": str(r["branch_id"]),
                "rid": r["rid"],
                "name": r["name"],
                "description": r["description"],
                "status": r["status"],
                "base_version_id": r["base_version_id"],
                "parent_branch_id": str(r["parent_branch_id"]) if r["parent_branch_id"] else None,
                "created_by": r["created_by"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "merged_at": r["merged_at"].isoformat() if r["merged_at"] else None,
                "merged_by": r["merged_by"],
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.get("/{branch_id}")
async def get_branch(
    branch_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    bid = _parse_uuid(branch_id)
    async with pool.acquire() as conn:
        b = await conn.fetchrow(
            "SELECT * FROM object_branches WHERE branch_id = $1", bid,
        )
        if not b:
            raise HTTPException(404, "branch not found")
        edits = await conn.fetch(
            """
            SELECT id, props, diff, actor, message, created_at
            FROM branch_edits WHERE branch_id = $1
            ORDER BY created_at DESC LIMIT 50
            """,
            bid,
        )

    return {
        "branch_id": str(b["branch_id"]),
        "rid": b["rid"],
        "name": b["name"],
        "description": b["description"],
        "status": b["status"],
        "base_version_id": b["base_version_id"],
        "parent_branch_id": str(b["parent_branch_id"]) if b["parent_branch_id"] else None,
        "created_by": b["created_by"],
        "created_at": b["created_at"].isoformat() if b["created_at"] else None,
        "merged_at": b["merged_at"].isoformat() if b["merged_at"] else None,
        "edits": [
            {
                "id": e["id"],
                "props": _decode(e["props"]),
                "diff": _decode(e["diff"]),
                "actor": e["actor"],
                "message": e["message"],
                "created_at": e["created_at"].isoformat() if e["created_at"] else None,
            }
            for e in edits
        ],
    }


@router.post("/{branch_id}/edit")
async def edit_branch(
    branch_id: str,
    body: dict[str, Any] = Body(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    bid = _parse_uuid(branch_id)
    new_props = body.get("props")
    diff = body.get("diff") or {}
    actor = body.get("actor", "anonymous")
    message = body.get("message")

    if not isinstance(new_props, dict):
        raise HTTPException(400, "props must be an object")

    async with pool.acquire() as conn:
        b = await conn.fetchrow(
            "SELECT rid, status FROM object_branches WHERE branch_id = $1", bid,
        )
        if not b:
            raise HTTPException(404, "branch not found")
        if b["status"] != "open":
            raise HTTPException(409, f"branch is {b['status']} — cannot edit")
        row = await conn.fetchrow(
            """
            INSERT INTO branch_edits (branch_id, rid, props, diff, actor, message)
            VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6)
            RETURNING id, created_at
            """,
            bid, b["rid"], json.dumps(new_props, default=str),
            json.dumps(diff, default=str), actor, message,
        )
    return {
        "edit_id": row["id"],
        "branch_id": branch_id,
        "rid": b["rid"],
        "created_at": row["created_at"].isoformat(),
    }


@router.get("/{branch_id}/resolve")
async def resolve_branch(
    branch_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return the fully-resolved object state on this branch.

    Resolution = latest branch_edit's props if any, else the base version
    snapshot at branch creation time.
    """
    bid = _parse_uuid(branch_id)
    async with pool.acquire() as conn:
        b = await conn.fetchrow(
            "SELECT * FROM object_branches WHERE branch_id = $1", bid,
        )
        if not b:
            raise HTTPException(404, "branch not found")

        latest = await conn.fetchrow(
            """
            SELECT props, diff, actor, message, created_at
            FROM branch_edits WHERE branch_id = $1
            ORDER BY created_at DESC LIMIT 1
            """,
            bid,
        )

        # Base props from object_versions (snapshot at branch creation)
        base = None
        if b["base_version_id"]:
            base_row = await conn.fetchrow(
                "SELECT props, label FROM object_versions WHERE id = $1",
                b["base_version_id"],
            )
            if base_row:
                base = _decode(base_row["props"])

    if latest:
        return {
            "rid": b["rid"],
            "branch_id": branch_id,
            "branch_name": b["name"],
            "props": _decode(latest["props"]),
            "diff_from_base": _decode(latest["diff"]),
            "source": "branch_edit",
            "edited_at": latest["created_at"].isoformat() if latest["created_at"] else None,
            "edited_by": latest["actor"],
        }
    return {
        "rid": b["rid"],
        "branch_id": branch_id,
        "branch_name": b["name"],
        "props": base or {},
        "source": "base_version",
        "edited_at": None,
    }


@router.post("/{branch_id}/merge")
async def merge_branch(
    branch_id: str,
    body: dict[str, Any] | None = Body(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Apply the resolved branch state to graph_nodes (which fires the
    auto-emit trigger and produces a new main version), then mark the
    branch as merged."""
    bid = _parse_uuid(branch_id)
    actor = (body or {}).get("actor", "anonymous")

    async with pool.acquire() as conn:
        b = await conn.fetchrow(
            "SELECT * FROM object_branches WHERE branch_id = $1", bid,
        )
        if not b:
            raise HTTPException(404, "branch not found")
        if b["status"] != "open":
            raise HTTPException(409, f"branch is {b['status']}")

        latest = await conn.fetchrow(
            """
            SELECT props FROM branch_edits WHERE branch_id = $1
            ORDER BY created_at DESC LIMIT 1
            """,
            bid,
        )
        if not latest:
            raise HTTPException(400, "branch has no edits — nothing to merge")

        # Pull current label from graph_nodes (or from base_version)
        gn = await conn.fetchrow(
            "SELECT label FROM graph_nodes WHERE rid = $1", b["rid"],
        )
        if gn:
            label = gn["label"]
        else:
            base_row = await conn.fetchrow(
                "SELECT label FROM object_versions WHERE id = $1", b["base_version_id"],
            )
            label = base_row["label"] if base_row else "Object"

        # Apply — UPSERT into graph_nodes triggers emit_object_mutated
        await conn.execute(
            """
            INSERT INTO graph_nodes (rid, label, props, updated_at)
            VALUES ($1, $2, $3::jsonb, NOW())
            ON CONFLICT (rid) DO UPDATE
              SET label = EXCLUDED.label,
                  props = EXCLUDED.props,
                  updated_at = NOW()
            """,
            b["rid"], label,
            json.dumps(_decode(latest["props"]) or {}, default=str),
        )

        # Close out the branch
        await conn.execute(
            """
            UPDATE object_branches
               SET status = 'merged', merged_at = NOW(), merged_by = $2
             WHERE branch_id = $1
            """,
            bid, actor,
        )

    return {
        "branch_id": branch_id,
        "rid": b["rid"],
        "status": "merged",
        "merged_at": "now",
        "merged_by": actor,
    }


@router.delete("/{branch_id}")
async def discard_branch(
    branch_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    bid = _parse_uuid(branch_id)
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE object_branches SET status = 'discarded'
             WHERE branch_id = $1 AND status = 'open'
            """,
            bid,
        )
    if result == "UPDATE 0":
        raise HTTPException(409, "branch already merged or discarded")
    return {"branch_id": branch_id, "status": "discarded"}


@router.get("/{branch_id}/diff")
async def diff_branch(
    branch_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return the field-level diff between this branch's resolved state
    and live main (graph_nodes). What you'd see merged.

    Shape:
      {
        branch_id, branch_name, status,
        main_props: {...},                # live state on main
        branch_props: {...},              # latest edited / base
        added:    {key: branch_value},
        removed:  {key: main_value},
        changed:  {key: {before, after}}
      }
    """
    bid = _parse_uuid(branch_id)
    async with pool.acquire() as conn:
        b = await conn.fetchrow(
            "SELECT * FROM object_branches WHERE branch_id = $1", bid,
        )
        if not b:
            raise HTTPException(404, "branch not found")

        # Resolve branch state — latest edit OR base
        latest = await conn.fetchrow(
            """
            SELECT props FROM branch_edits WHERE branch_id = $1
            ORDER BY created_at DESC LIMIT 1
            """,
            bid,
        )
        if latest:
            branch_props = _decode(latest["props"]) or {}
        elif b["base_version_id"]:
            base_row = await conn.fetchrow(
                "SELECT props FROM object_versions WHERE id = $1",
                b["base_version_id"],
            )
            branch_props = (_decode(base_row["props"]) if base_row else {}) or {}
        else:
            branch_props = {}

        # Resolve current main state
        gn = await conn.fetchrow(
            "SELECT label, props FROM graph_nodes WHERE rid = $1", b["rid"],
        )
        main_props = (_decode(gn["props"]) if gn else {}) or {}

    # Field-level diff
    main_keys = set(main_props.keys())
    branch_keys = set(branch_props.keys())
    added = {k: branch_props[k] for k in branch_keys - main_keys}
    removed = {k: main_props[k] for k in main_keys - branch_keys}
    changed = {}
    for k in main_keys & branch_keys:
        if main_props[k] != branch_props[k]:
            changed[k] = {"before": main_props[k], "after": branch_props[k]}

    return {
        "branch_id": branch_id,
        "branch_name": b["name"],
        "rid": b["rid"],
        "status": b["status"],
        "main_props": main_props,
        "branch_props": branch_props,
        "added": added,
        "removed": removed,
        "changed": changed,
        "field_count": {
            "added": len(added), "removed": len(removed), "changed": len(changed),
        },
        "edit_count": await _edit_count(pool, bid),
    }


async def _edit_count(pool, bid) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM branch_edits WHERE branch_id = $1", bid,
        ) or 0
