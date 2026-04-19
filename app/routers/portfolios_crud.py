"""Portfolios — CRUD router for the portfolio container that groups projects.

Distinct from app/routers/portfolio.py which is the portfolio OPTIMISER.
This router manages the navigable Portfolio → Project → Site hierarchy used
by the redesigned UI.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import asyncpg

from app.deps import get_pool, get_optional_user

router = APIRouter(prefix="/api/v1/portfolios", tags=["portfolios"])


class PortfolioCreateRequest(BaseModel):
    name: str
    description: str | None = None


class PortfolioUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


def _pf_row(row) -> dict:
    return {
        "portfolio_id": str(row["portfolio_id"]),
        "user_id": str(row["user_id"]) if row["user_id"] else None,
        "name": row["name"],
        "description": row["description"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def _project_summary_row(row) -> dict:
    return {
        "project_id": str(row["project_id"]),
        "name": row["name"],
        "technology": row["technology"],
        "capacity_mw": float(row["capacity_mw"]) if row["capacity_mw"] else None,
        "stage": row["stage"],
        "verdict": row["verdict"],
        "lat": float(row["lat"]) if row["lat"] else None,
        "lon": float(row["lon"]) if row["lon"] else None,
        "blocker": row["blocker"],
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.get("")
async def list_portfolios(
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    user_id = user["user_id"] if user else None
    async with pool.acquire() as conn:
        if user_id:
            rows = await conn.fetch(
                """SELECT * FROM portfolios
                   WHERE user_id = $1 OR user_id IS NULL
                   ORDER BY created_at DESC""",
                user_id,
            )
        else:
            rows = await conn.fetch("SELECT * FROM portfolios ORDER BY created_at DESC")
    return {"portfolios": [_pf_row(r) for r in rows]}


@router.post("")
async def create_portfolio(
    body: PortfolioCreateRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    user_id = user["user_id"] if user else None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO portfolios (user_id, name, description)
               VALUES ($1, $2, $3) RETURNING *""",
            user_id, body.name, body.description,
        )
    return _pf_row(row)


@router.get("/{portfolio_id}")
async def get_portfolio(portfolio_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    pf_id = UUID(portfolio_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM portfolios WHERE portfolio_id = $1", pf_id)
        if not row:
            raise HTTPException(404, "Portfolio not found")
    return _pf_row(row)


@router.put("/{portfolio_id}")
async def update_portfolio(
    portfolio_id: str,
    body: PortfolioUpdateRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    pf_id = UUID(portfolio_id)
    async with pool.acquire() as conn:
        sets, params = [], []
        idx = 1
        if body.name is not None:
            sets.append(f"name = ${idx}")
            params.append(body.name); idx += 1
        if body.description is not None:
            sets.append(f"description = ${idx}")
            params.append(body.description); idx += 1
        if not sets:
            row = await conn.fetchrow("SELECT * FROM portfolios WHERE portfolio_id = $1", pf_id)
        else:
            sets.append(f"updated_at = NOW()")
            params.append(pf_id)
            row = await conn.fetchrow(
                f"UPDATE portfolios SET {', '.join(sets)} WHERE portfolio_id = ${idx} RETURNING *",
                *params,
            )
        if not row:
            raise HTTPException(404, "Portfolio not found")
    return _pf_row(row)


@router.delete("/{portfolio_id}")
async def delete_portfolio(portfolio_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    pf_id = UUID(portfolio_id)
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM portfolios WHERE portfolio_id = $1", pf_id)
    if res == "DELETE 0":
        raise HTTPException(404, "Portfolio not found")
    return {"deleted": portfolio_id}


@router.get("/{portfolio_id}/projects")
async def list_portfolio_projects(
    portfolio_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List projects under a portfolio. Includes candidate_site counts for tree rendering."""
    pf_id = UUID(portfolio_id)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT p.*,
                      (SELECT count(*) FROM project_candidate_sites cs
                       WHERE cs.project_id = p.project_id) AS candidate_sites_count
               FROM projects p
               WHERE p.portfolio_id = $1
               ORDER BY p.updated_at DESC NULLS LAST""",
            pf_id,
        )
    projects = []
    for r in rows:
        d = _project_summary_row(r)
        d["candidate_sites_count"] = r["candidate_sites_count"]
        projects.append(d)
    return {"portfolio_id": portfolio_id, "projects": projects}


@router.get("/tree/full")
async def portfolio_tree(pool: asyncpg.Pool = Depends(get_pool)):
    """Full nested tree for the ProjectTree sidebar — one request gets everything."""
    async with pool.acquire() as conn:
        pfs = await conn.fetch("SELECT * FROM portfolios ORDER BY created_at DESC")
        prj = await conn.fetch(
            """SELECT project_id, portfolio_id, name, technology, stage, verdict, blocker,
                      capacity_mw, lat, lon
               FROM projects
               ORDER BY updated_at DESC NULLS LAST"""
        )
        sites = await conn.fetch(
            """SELECT candidate_id, project_id, name, verdict, is_preferred
               FROM project_candidate_sites
               ORDER BY is_preferred DESC, created_at ASC"""
        )
    # build index
    sites_by_project: dict[str, list] = {}
    for s in sites:
        sites_by_project.setdefault(str(s["project_id"]), []).append({
            "candidate_id": str(s["candidate_id"]),
            "name": s["name"],
            "verdict": s["verdict"],
            "is_preferred": s["is_preferred"],
        })
    projects_by_portfolio: dict[str | None, list] = {}
    orphan_projects = []
    for p in prj:
        entry = {
            "project_id": str(p["project_id"]),
            "name": p["name"],
            "technology": p["technology"],
            "stage": p["stage"],
            "verdict": p["verdict"],
            "blocker": p["blocker"],
            "capacity_mw": float(p["capacity_mw"]) if p["capacity_mw"] else None,
            "lat": float(p["lat"]) if p["lat"] else None,
            "lon": float(p["lon"]) if p["lon"] else None,
            "sites": sites_by_project.get(str(p["project_id"]), []),
        }
        if p["portfolio_id"]:
            projects_by_portfolio.setdefault(str(p["portfolio_id"]), []).append(entry)
        else:
            orphan_projects.append(entry)

    tree = [
        {
            **_pf_row(pf),
            "projects": projects_by_portfolio.get(str(pf["portfolio_id"]), []),
        }
        for pf in pfs
    ]
    return {"portfolios": tree, "orphan_projects": orphan_projects}
