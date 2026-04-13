"""Portfolio delta router — snapshots and cross-snapshot deltas."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Body, Depends, Query
import asyncpg

from app.deps import get_pool
from utils.portfolio_delta import (
    take_snapshot,
    compute_deltas,
    get_latest_deltas,
    weekly_summary,
)

router = APIRouter(tags=["portfolio-delta"], prefix="/api/portfolio")


@router.post("/snapshot/take")
async def snapshot(taken_at: date | None = Query(None), pool: asyncpg.Pool = Depends(get_pool)):
    """Take a portfolio snapshot for the given date (default today)."""
    n = await take_snapshot(pool, taken_at=taken_at)
    return {"rows_inserted": n, "taken_at": str(taken_at or date.today())}


@router.get("/deltas")
async def deltas(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Compare two snapshots and return per-project per-metric deltas."""
    to_d = to_date or date.today()
    from_d = from_date or (to_d - timedelta(days=1))
    return await compute_deltas(pool, from_d, to_d)


@router.get("/deltas/latest")
async def deltas_latest(
    user_id: str = Query("default"),
    limit: int = Query(50, ge=1, le=200),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Deltas for the two most recent snapshots, sorted by magnitude."""
    return await get_latest_deltas(pool, user_id=user_id, limit=limit)


@router.get("/weekly-summary")
async def weekly(user_id: str = Query("default"), pool: asyncpg.Pool = Depends(get_pool)):
    """Portfolio-level weekly summary — gainers, losers, average score delta."""
    return await weekly_summary(pool, user_id=user_id)
