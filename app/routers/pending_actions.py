"""Action approval workflow — Foundry's preview → approve/reject pattern.

  POST   /api/pending-actions                              — stage an action
                                                              body {object_type, object_id, action_name, args, requested_by}
                                                              returns {pending_id, preview}
  GET    /api/pending-actions?status=&rid=                 — list
  GET    /api/pending-actions/{pending_id}                 — detail
  POST   /api/pending-actions/{pending_id}/approve         — runs the real
                                                              dispatch and
                                                              records the
                                                              audit log id
  POST   /api/pending-actions/{pending_id}/reject          — body {note?}
  DELETE /api/pending-actions/{pending_id}                 — discard

The "preview" payload is currently a static description of what would
happen (action + args + base object snapshot). It does NOT execute. A
future enhancement could fork an object_branch, apply the action, return
the resolved branch state, then merge on approve.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.deps import get_pool
from app.ontology.dispatch import OBJECTS, dispatch as run_dispatch
from app.ontology.dispatch import _TYPE_TO_LABEL

log = logging.getLogger("princeps.pending_actions")
router = APIRouter(prefix="/api/pending-actions", tags=["pending-actions"])


def _parse_uuid(s: str) -> UUID:
    try:
        return UUID(s)
    except (ValueError, TypeError):
        raise HTTPException(400, f"invalid pending_id: {s}")


def _row_to_dict(r) -> dict:
    return {
        "pending_id": str(r["pending_id"]),
        "object_type": r["object_type"],
        "object_id": r["object_id"],
        "rid": r["rid"],
        "action_name": r["action_name"],
        "args": r["args_json"] if isinstance(r["args_json"], dict) else json.loads(r["args_json"] or "{}"),
        "preview": r["preview_json"] if isinstance(r["preview_json"], dict) else (json.loads(r["preview_json"]) if r["preview_json"] else None),
        "status": r["status"],
        "requested_by": r["requested_by"],
        "requested_at": r["requested_at"].isoformat() if r["requested_at"] else None,
        "resolved_by": r["resolved_by"],
        "resolved_at": r["resolved_at"].isoformat() if r["resolved_at"] else None,
        "resolution_note": r["resolution_note"],
        "result_log_id": str(r["result_log_id"]) if r["result_log_id"] else None,
        "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
    }


@router.post("")
async def stage_action(
    body: dict[str, Any] = Body(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    object_type = body.get("object_type")
    object_id = body.get("object_id")
    action_name = body.get("action_name")
    args = body.get("args") or {}
    requested_by = body.get("requested_by", "anonymous")

    if not object_type or not object_id or not action_name:
        raise HTTPException(400, "object_type, object_id, action_name required")
    if object_type not in OBJECTS:
        raise HTTPException(400, f"unknown object_type: {object_type}")

    rid = (object_id if str(object_id).startswith("rid.princeps.")
           else f"rid.princeps.{object_type}.{object_id}")
    label = _TYPE_TO_LABEL.get(object_type, object_type.capitalize())

    # Build a static preview — describe WHAT will run, snapshot current state
    preview = {
        "label": label,
        "rid": rid,
        "action": action_name,
        "args": args,
        "summary": f"{label} {object_id} → {action_name}({json.dumps(args, default=str)})",
    }

    # Try to load the current object so we can show before-state in the UI
    try:
        obj = await OBJECTS[object_type].load_from_db(pool, object_id)
        if hasattr(obj, "metadata"):
            preview["current_state"] = obj.metadata
    except Exception as exc:
        preview["load_error"] = str(exc)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO pending_actions
              (object_type, object_id, rid, action_name, args_json,
               preview_json, requested_by)
            VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7)
            RETURNING *
            """,
            object_type, str(object_id), rid, action_name,
            json.dumps(args, default=str),
            json.dumps(preview, default=str),
            requested_by,
        )

    return _row_to_dict(row)


@router.get("")
async def list_pending(
    rid: str | None = Query(None),
    status: str | None = Query("pending"),
    limit: int = Query(50, ge=1, le=500),
    pool: asyncpg.Pool = Depends(get_pool),
):
    where = []
    params: list[Any] = []
    def _b(v):
        params.append(v); return f"${len(params)}"
    if rid: where.append(f"rid = {_b(rid)}")
    if status and status != "all":
        where.append(f"status = {_b(status)}")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT * FROM pending_actions {where_sql}
        ORDER BY requested_at DESC LIMIT {int(limit)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return {"pending": [_row_to_dict(r) for r in rows], "count": len(rows)}


@router.get("/{pending_id}")
async def get_pending(
    pending_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    pid = _parse_uuid(pending_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM pending_actions WHERE pending_id = $1", pid)
    if not row:
        raise HTTPException(404, "pending action not found")
    return _row_to_dict(row)


@router.post("/{pending_id}/approve")
async def approve_pending(
    pending_id: str,
    body: dict[str, Any] | None = Body(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    pid = _parse_uuid(pending_id)
    actor = (body or {}).get("actor", "anonymous")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM pending_actions WHERE pending_id = $1", pid)
    if not row:
        raise HTTPException(404, "pending action not found")
    if row["status"] != "pending":
        raise HTTPException(409, f"pending action is {row['status']}")

    # Run the real dispatch — this hits the same handler that the chat tools
    # use, fires preconditions, writes ontology_action_log, syncs graph_nodes.
    args = row["args_json"] if isinstance(row["args_json"], dict) else json.loads(row["args_json"] or "{}")
    result = await run_dispatch(
        pool,
        row["object_type"],
        row["object_id"],
        row["action_name"],
        actor=f"approval:{actor}",
        args=args,
    )

    async with pool.acquire() as conn:
        # Locate the audit row we just produced for the link-back
        log_row = await conn.fetchrow(
            """
            SELECT log_id FROM ontology_action_log
            WHERE object_id = $1 AND action = $2 AND actor = $3
            ORDER BY started_utc DESC LIMIT 1
            """,
            row["rid"], row["action_name"], f"approval:{actor}",
        )
        await conn.execute(
            """
            UPDATE pending_actions
               SET status = $2, resolved_by = $3, resolved_at = NOW(),
                   result_log_id = $4
             WHERE pending_id = $1
            """,
            pid,
            "approved" if result.ok else "pending",  # leave pending if dispatch failed so we can retry
            actor,
            log_row["log_id"] if log_row else None,
        )

    return {
        "pending_id": pending_id,
        "ok": result.ok,
        "error": result.error,
        "duration_ms": result.duration_ms,
        "result_log_id": str(log_row["log_id"]) if log_row else None,
    }


@router.post("/{pending_id}/reject")
async def reject_pending(
    pending_id: str,
    body: dict[str, Any] | None = Body(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    pid = _parse_uuid(pending_id)
    actor = (body or {}).get("actor", "anonymous")
    note = (body or {}).get("note")
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE pending_actions
               SET status = 'rejected', resolved_by = $2, resolved_at = NOW(),
                   resolution_note = $3
             WHERE pending_id = $1 AND status = 'pending'
            """,
            pid, actor, note,
        )
    if result == "UPDATE 0":
        raise HTTPException(409, "pending action already resolved")
    return {"pending_id": pending_id, "status": "rejected"}


@router.delete("/{pending_id}")
async def discard_pending(
    pending_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    pid = _parse_uuid(pending_id)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM pending_actions WHERE pending_id = $1 AND status = 'pending'",
            pid,
        )
    if result == "DELETE 0":
        raise HTTPException(409, "already resolved")
    return {"pending_id": pending_id, "discarded": True}
