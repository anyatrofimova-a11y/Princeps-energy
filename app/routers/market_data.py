"""Market data routes — live prices, generation mix, capacity market, WebSocket feed."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from utils.market_data_feed import (
    fetch_live_snapshot,
    fetch_day_ahead_prices,
    fetch_generation_mix,
    fetch_capacity_market_register,
    get_market_summary,
)

log = logging.getLogger("princeps.market_data")
router = APIRouter(tags=["market-data"])

# WebSocket client tracking
_ws_clients: set[WebSocket] = set()


@router.get("/api/market/live")
async def market_live():
    return await fetch_live_snapshot()


@router.get("/api/market/prices")
async def market_prices(date: str | None = Query(None)):
    return await fetch_day_ahead_prices(date)


@router.get("/api/market/generation")
async def market_generation(
    from_dt: str | None = Query(None, alias="from"),
    to_dt: str | None = Query(None, alias="to"),
):
    return await fetch_generation_mix(from_dt, to_dt)


@router.get("/api/market/capacity-register")
async def market_capacity_register():
    return await fetch_capacity_market_register()


@router.get("/api/market/summary")
async def market_summary():
    return await get_market_summary()


@router.websocket("/ws/market")
async def ws_market(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    log.info("Market WS client connected (%d total)", len(_ws_clients))
    try:
        while True:
            snapshot = await fetch_live_snapshot()
            await ws.send_json({
                "type": "market_update",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": snapshot,
            })
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.debug("Market WS error: %s", e)
    finally:
        _ws_clients.discard(ws)
        log.info("Market WS client disconnected (%d remaining)", len(_ws_clients))
