"""Notifications and alerts router."""

from __future__ import annotations

import asyncio
import json
import os

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from app.deps import get_pool

# ── Utils ──
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from utils.alert_engine import (
    run_daily_alert_check,
    get_notifications, mark_notification_read, mark_all_read,
    get_alert_rules, create_alert_rule, delete_alert_rule,
)


router = APIRouter(tags=["notifications"])


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@router.get("/notifications")
async def notifications_list(
    unread_only: bool = False,
    limit: int = 50,
    user_id: str = "default",
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List notifications for a user."""
    async with pool.acquire() as conn:
        items = await get_notifications(conn, user_id, unread_only=unread_only, limit=limit)
    unread = sum(1 for i in items if not i.get("read"))
    return {"count": len(items), "unread": unread, "notifications": items}


@router.post("/notifications/{notification_id}/read")
async def notification_mark_read(notification_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Mark a single notification as read."""
    async with pool.acquire() as conn:
        await mark_notification_read(conn, notification_id)
    return {"ok": True}


@router.post("/notifications/mark-all-read")
async def notifications_mark_all_read(user_id: str = "default", pool: asyncpg.Pool = Depends(get_pool)):
    """Mark all notifications as read."""
    async with pool.acquire() as conn:
        await mark_all_read(conn, user_id)
    return {"ok": True}


@router.get("/notifications/stream")
async def notifications_stream(user_id: str = "default", pool: asyncpg.Pool = Depends(get_pool)):
    """SSE endpoint for real-time notification push."""

    async def _gen():
        last_count = -1
        while True:
            try:
                async with pool.acquire() as conn:
                    items = await get_notifications(conn, user_id, unread_only=True, limit=10)
                unread = len(items)
                if unread != last_count:
                    last_count = unread
                    data = json.dumps({"unread": unread, "latest": items[:3]})
                    yield f"data: {data}\n\n"
            except Exception:
                pass
            await asyncio.sleep(30)

    return StreamingResponse(_gen(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Alert Rules
# ---------------------------------------------------------------------------

@router.get("/alerts/rules")
async def alert_rules_list(user_id: str = "default", pool: asyncpg.Pool = Depends(get_pool)):
    """List alert rules for a user."""
    async with pool.acquire() as conn:
        rules = await get_alert_rules(conn, user_id)
    return {"count": len(rules), "rules": rules}


@router.post("/alerts/rules")
async def alert_rules_create(body: dict, pool: asyncpg.Pool = Depends(get_pool)):
    """Create a new alert rule."""
    async with pool.acquire() as conn:
        rule = await create_alert_rule(
            conn,
            user_id=body.get("user_id", "default"),
            rule_type=body.get("rule_type", "nearby_planning"),
            config=body.get("config"),
            site_id=body.get("site_id"),
            lat=body.get("lat"),
            lon=body.get("lon"),
            radius_km=body.get("radius_km", 10),
        )
    return rule


@router.delete("/alerts/rules/{rule_id}")
async def alert_rules_delete(rule_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Delete an alert rule."""
    async with pool.acquire() as conn:
        await delete_alert_rule(conn, rule_id)
    return {"ok": True}


@router.post("/alerts/check-now")
async def alert_check_now(pool: asyncpg.Pool = Depends(get_pool)):
    """Manual trigger for alert checks."""
    async with pool.acquire() as conn:
        result = await run_daily_alert_check(conn)
    return result
