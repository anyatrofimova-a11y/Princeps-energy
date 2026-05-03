"""Object Notes — Foundry Notepad equivalent.

Markdown notes pinned to any typed object via its rid.

  GET    /api/notes?rid=<rid>&tag=<tag>&q=<text>     — list notes
  POST   /api/notes                                   — create
  GET    /api/notes/{id}                              — read one
  PATCH  /api/notes/{id}                              — edit
  DELETE /api/notes/{id}                              — soft-delete
  POST   /api/notes/{id}/pin                          — toggle pinned
  GET    /api/notes/recent?limit=                     — newest across all rids

Auto-emits an ontology_action_log row on every mutation so the audit
timeline on Object Page → History tab includes notepad activity.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.deps import get_pool

log = logging.getLogger("princeps.notes")
router = APIRouter(prefix="/api/notes", tags=["notes"])


async def _audit(conn, rid: str, action: str, actor: str | None, args: dict | None = None):
    """Best-effort audit row — failure must not block the note write."""
    try:
        await conn.execute(
            """
            INSERT INTO ontology_action_log (
                object_type, object_id, action, actor, ok,
                args_json, result_json, started_utc, completed_utc
            ) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,NOW(),NOW())
            """,
            "Note", rid, action, actor or "anonymous", True,
            json.dumps(args or {}, default=str), "{}",
        )
    except Exception as exc:
        log.warning("note audit failed: %s", exc)


def _row_to_dict(r) -> dict:
    return {
        "id": r["id"],
        "rid": r["rid"],
        "title": r["title"],
        "body_md": r["body_md"],
        "author": r["author"],
        "tags": list(r["tags"] or []),
        "pinned": r["pinned"],
        "parent_note_id": r["parent_note_id"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


@router.get("")
async def list_notes(
    rid: str | None = Query(None),
    tag: str | None = Query(None),
    q: str | None = Query(None, description="case-insensitive substring search on title+body"),
    pinned_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    pool: asyncpg.Pool = Depends(get_pool),
):
    where = ["deleted_at IS NULL"]
    params: list[Any] = []
    def _bind(v):
        params.append(v)
        return f"${len(params)}"
    if rid: where.append(f"rid = {_bind(rid)}")
    if tag: where.append(f"{_bind(tag)} = ANY(tags)")
    if q:   where.append(f"(title ILIKE '%' || {_bind(q)} || '%' OR body_md ILIKE '%' || {_bind(q)} || '%')")
    if pinned_only: where.append("pinned = TRUE")
    sql = f"""
        SELECT * FROM object_notes
        WHERE {' AND '.join(where)}
        ORDER BY pinned DESC, created_at DESC
        LIMIT {int(limit)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return {
        "notes": [_row_to_dict(r) for r in rows],
        "count": len(rows),
        "filters": {"rid": rid, "tag": tag, "q": q, "pinned_only": pinned_only},
    }


@router.get("/recent")
async def recent_notes(
    limit: int = Query(20, ge=1, le=100),
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM object_notes
            WHERE deleted_at IS NULL
            ORDER BY created_at DESC LIMIT $1
            """,
            limit,
        )
    return {"notes": [_row_to_dict(r) for r in rows], "count": len(rows)}


@router.post("")
async def create_note(
    body: dict[str, Any] = Body(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    rid = body.get("rid")
    body_md = body.get("body_md")
    title = body.get("title")
    author = body.get("author", "anonymous")
    tags = body.get("tags") or []
    pinned = bool(body.get("pinned", False))
    parent_note_id = body.get("parent_note_id")

    if not rid:
        raise HTTPException(400, "rid is required")
    if not body_md or not body_md.strip():
        raise HTTPException(400, "body_md is required")
    if not isinstance(tags, list):
        raise HTTPException(400, "tags must be a list")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO object_notes
              (rid, title, body_md, author, tags, pinned, parent_note_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            RETURNING *
            """,
            rid, title, body_md, author, tags, pinned,
            int(parent_note_id) if parent_note_id else None,
        )
        await _audit(conn, rid, "NoteCreated", author, {"note_id": row["id"], "title": title, "tags": tags})
    return _row_to_dict(row)


@router.get("/{note_id}")
async def get_note(note_id: int, pool: asyncpg.Pool = Depends(get_pool)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM object_notes WHERE id = $1 AND deleted_at IS NULL", note_id,
        )
    if not row:
        raise HTTPException(404, "note not found")
    return _row_to_dict(row)


@router.patch("/{note_id}")
async def patch_note(
    note_id: int,
    body: dict[str, Any] = Body(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Partial update. Pass only the fields you want to change."""
    sets: list[str] = []
    params: list[Any] = []
    def _bind(v):
        params.append(v)
        return f"${len(params)}"

    if "title" in body: sets.append(f"title = {_bind(body['title'])}")
    if "body_md" in body: sets.append(f"body_md = {_bind(body['body_md'])}")
    if "tags" in body:
        if not isinstance(body["tags"], list):
            raise HTTPException(400, "tags must be a list")
        sets.append(f"tags = {_bind(body['tags'])}")
    if "pinned" in body: sets.append(f"pinned = {_bind(bool(body['pinned']))}")
    if not sets:
        raise HTTPException(400, "no editable fields supplied")

    params.append(note_id)
    sql = f"UPDATE object_notes SET {', '.join(sets)} WHERE id = ${len(params)} AND deleted_at IS NULL RETURNING *"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *params)
        if not row:
            raise HTTPException(404, "note not found")
        await _audit(conn, row["rid"], "NoteEdited", body.get("actor"), {"note_id": note_id, "fields": list(body.keys())})
    return _row_to_dict(row)


@router.delete("/{note_id}")
async def delete_note(
    note_id: int,
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE object_notes SET deleted_at = NOW()
             WHERE id = $1 AND deleted_at IS NULL
            RETURNING rid
            """,
            note_id,
        )
        if not row:
            raise HTTPException(404, "note not found or already deleted")
        await _audit(conn, row["rid"], "NoteDeleted", None, {"note_id": note_id})
    return {"ok": True, "id": note_id}


@router.post("/{note_id}/pin")
async def pin_note(
    note_id: int,
    body: dict[str, Any] | None = Body(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    pinned = bool((body or {}).get("pinned", True))
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE object_notes SET pinned = $2
             WHERE id = $1 AND deleted_at IS NULL
            RETURNING *
            """,
            note_id, pinned,
        )
        if not row:
            raise HTTPException(404, "note not found")
        await _audit(conn, row["rid"], "NotePinned" if pinned else "NoteUnpinned", None, {"note_id": note_id})
    return _row_to_dict(row)
