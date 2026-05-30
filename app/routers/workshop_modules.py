"""Workshop Module Builder — REST surface.

GET    /api/workshop/modules                list (10 most recent)
GET    /api/workshop/modules/{id_or_slug}   fetch one (uuid or slug)
POST   /api/workshop/modules                upsert by slug
POST   /api/workshop/modules/compose        Claude → manifest (no save)

Companion router to `app/routers/workshop.py` (which owns /scene + /tree).
Lives at the same `/api/workshop` prefix but only on `/modules*` paths.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.ai.module_composer import Manifest, compose_manifest
from app.deps import get_pool

log = logging.getLogger("princeps.workshop_modules")
router = APIRouter(prefix="/api/workshop", tags=["workshop-modules"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class UpsertBody(BaseModel):
    slug: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    target_type: str | None = None
    manifest: dict[str, Any]


class ComposeBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    target_type: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except (ValueError, TypeError):
        return False


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    m = d.get("manifest")
    if isinstance(m, str):
        try:
            d["manifest"] = json.loads(m)
        except json.JSONDecodeError:
            pass
    if d.get("id") is not None:
        d["id"] = str(d["id"])
    for k in ("created_at", "updated_at"):
        v = d.get(k)
        if v is not None and hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/modules")
async def list_modules(pool: asyncpg.Pool = Depends(get_pool)):
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, slug, title, target_type, manifest, created_at, updated_at
                  FROM workshop_modules
              ORDER BY updated_at DESC
                 LIMIT 10
                """
            )
    except asyncpg.UndefinedTableError:
        return {"modules": []}
    return {"modules": [_row_to_dict(r) for r in rows]}


@router.get("/modules/{ident}")
async def get_module(ident: str, pool: asyncpg.Pool = Depends(get_pool)):
    async with pool.acquire() as conn:
        if _is_uuid(ident):
            row = await conn.fetchrow(
                "SELECT id, slug, title, target_type, manifest, created_at, updated_at "
                "FROM workshop_modules WHERE id = $1",
                uuid.UUID(ident),
            )
        else:
            row = await conn.fetchrow(
                "SELECT id, slug, title, target_type, manifest, created_at, updated_at "
                "FROM workshop_modules WHERE slug = $1",
                ident,
            )
    if not row:
        raise HTTPException(status_code=404, detail=f"module not found: {ident}")
    return _row_to_dict(row)


@router.post("/modules")
async def upsert_module(body: UpsertBody, pool: asyncpg.Pool = Depends(get_pool)):
    # Validate manifest shape — reject silently-broken payloads at the door.
    try:
        Manifest.model_validate(body.manifest)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid manifest: {exc}") from exc

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO workshop_modules(slug, title, target_type, manifest)
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT (slug) DO UPDATE
                SET title       = EXCLUDED.title,
                    target_type = EXCLUDED.target_type,
                    manifest    = EXCLUDED.manifest,
                    updated_at  = NOW()
            RETURNING id, slug, title, target_type, manifest, created_at, updated_at
            """,
            body.slug,
            body.title,
            body.target_type,
            json.dumps(body.manifest),
        )
    return _row_to_dict(row)


@router.post("/modules/compose")
async def compose_module(body: ComposeBody, request: Request):
    claude = getattr(request.app.state, "claude", None)
    if claude is None:
        raise HTTPException(status_code=503, detail="claude client not initialised")
    try:
        manifest = await compose_manifest(claude, body.prompt, body.target_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"manifest": manifest}
