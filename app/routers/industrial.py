"""Industrial Base Graph router — UK-only.

Endpoints:
  GET  /api/industrial/entities/{rid}                 — entity by RID
  GET  /api/industrial/entities/{rid}/relationships   — outgoing edges
  GET  /api/industrial/lei/{lei}                      — GLEIF cache lookup (refresh on stale)
  GET  /api/industrial/companies/{ch_number}          — Companies House lookup (refresh on stale)
  GET  /api/industrial/sanctions/screen               — fuzzy-match a name
  POST /api/industrial/sanctions/refresh              — pull latest UK sanctions list
  GET  /api/industrial/search                         — fulltext over entities + caches

All sources are commercial-safe (CC0 / OGL).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from utils import companies_house_ingester as ch
from utils import lei_ingester as lei
from utils import uk_sanctions_ingester as sanctions

router = APIRouter(prefix="/api/industrial", tags=["industrial"])


class Entity(BaseModel):
    rid: str
    legal_name: str
    lei: str | None = None
    ch_number: str | None = None
    role: str | None = None
    parent_rid: str | None = None
    sanctions_flag: bool = False


class Relationship(BaseModel):
    rid: str
    from_rid: str
    to_rid: str
    rel_type: str
    properties: dict | None = None


@router.get("/entities/{rid}")
async def get_entity(rid: str, request: Request):
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT rid, legal_name, lei, ch_number, role, parent_rid, sanctions_flag "
            "FROM entities WHERE rid=$1", rid,
        )
    if not row:
        raise HTTPException(404, f"entity not found: {rid}")
    return dict(row)


@router.get("/entities/{rid}/relationships")
async def list_relationships(rid: str, request: Request, direction: str = Query("out", enum=["out", "in", "both"])):
    pool = request.app.state.pool
    where = {
        "out": "from_rid=$1",
        "in":  "to_rid=$1",
        "both": "from_rid=$1 OR to_rid=$1",
    }[direction]
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT rid, from_rid, to_rid, rel_type, properties, since, until "
            f"FROM entity_relationships WHERE {where}", rid,
        )
    return [dict(r) for r in rows]


@router.get("/lei/{lei_id}")
async def get_lei(lei_id: str, request: Request, force_refresh: bool = False):
    rec = await lei.lookup_by_lei(request.app.state.pool, lei_id, force_refresh=force_refresh)
    if rec is None:
        raise HTTPException(404, f"LEI not found: {lei_id}")
    return rec


@router.get("/lei/{lei_id}/tree")
async def get_corporate_tree(lei_id: str, request: Request, max_hops: int = 4):
    return await lei.crawl_corporate_tree(request.app.state.pool, lei_id, max_hops=max_hops)


@router.get("/companies/{ch_number}")
async def get_company(ch_number: str, request: Request, force_refresh: bool = False):
    rec = await ch.lookup_by_company_number(request.app.state.pool, ch_number, force_refresh=force_refresh)
    if rec is None:
        raise HTTPException(404, f"Company not found: {ch_number}")
    return rec


@router.get("/companies/search")
async def search_companies(q: str, items_per_page: int = 20):
    return await ch.search_companies(q, items_per_page=items_per_page)


@router.get("/sanctions/screen")
async def screen(name: str, request: Request, threshold: float = 0.6, limit: int = 10):
    if not name or len(name) < 2:
        raise HTTPException(400, "name must be at least 2 characters")
    return await sanctions.screen_name(request.app.state.pool, name, threshold=threshold, limit=limit)


@router.post("/sanctions/refresh")
async def refresh_sanctions(request: Request):
    return await sanctions.refresh(request.app.state.pool)


@router.get("/search")
async def search(q: str, request: Request, limit: int = 20):
    """Cross-source name search — tries entities first, then LEI, then CH."""
    async with request.app.state.pool.acquire() as conn:
        ent_rows = await conn.fetch(
            "SELECT rid, legal_name, lei, ch_number, role FROM entities "
            "WHERE legal_name ILIKE $1 LIMIT $2", f"%{q}%", limit,
        )
    lei_rows = await lei.search_by_name(q, limit=limit)
    ch_rows = await ch.search_companies(q, items_per_page=limit)
    return {"entities": [dict(r) for r in ent_rows], "lei": lei_rows, "companies_house": ch_rows}
