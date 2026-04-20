"""
/api/lccc/* — LCCC daily CfD reference price + top-up payment endpoints.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_pool
from utils.substrate.lccc_cfd_ingester import ingest_daily_reference_prices

log = logging.getLogger("princeps.routers.lccc")

router = APIRouter(prefix="/api/lccc", tags=["lccc"])


@router.get("/reference-price")
async def reference_prices(
    series: Literal["imrp", "bmrp", "topup"] = Query("imrp"),
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    """Return a range of LCCC daily reference prices."""
    today = date.today()
    try:
        d_from = date.fromisoformat(from_date) if from_date else today - timedelta(days=30)
        d_to = date.fromisoformat(to_date) if to_date else today
    except ValueError as e:
        raise HTTPException(400, f"invalid date: {e}")

    sql = """
        SELECT trading_date, price_gbp_mwh, ingested_at
        FROM lccc_daily_reference_prices
        WHERE series = $1 AND trading_date BETWEEN $2::date AND $3::date
        ORDER BY trading_date ASC
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, series, d_from.isoformat(), d_to.isoformat())
    except Exception as e:
        log.warning("query failed: %s", e)
        return {"series": series, "from": d_from.isoformat(), "to": d_to.isoformat(), "points": [], "error": str(e)}

    return {
        "series": series,
        "from": d_from.isoformat(),
        "to": d_to.isoformat(),
        "points": [
            {
                "date": r["trading_date"].isoformat(),
                "price_gbp_mwh": float(r["price_gbp_mwh"]) if r["price_gbp_mwh"] is not None else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.post("/ingest")
async def trigger_ingest(
    days_back: int = Query(7, ge=1, le=365),
    pool=Depends(get_pool),
) -> dict[str, Any]:
    """Trigger on-demand ingest of the last N days of daily prices."""
    try:
        result = await ingest_daily_reference_prices(pool, days_back=days_back)
        return {"status": "ok", "result": result}
    except Exception as e:
        log.error("LCCC ingest failed: %s", e)
        raise HTTPException(500, f"ingest failed: {e}")
