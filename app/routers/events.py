"""Events router — grid events, notifications, alert rules, and live WebSocket."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
import asyncpg

from app.deps import get_pool
from utils.grid_events import (
    emit_event,
    list_events,
    list_notifications,
    mark_notification_read,
    create_alert_rule,
    list_alert_rules,
    run_full_diff_cycle,
    get_stats,
    event_bus,
)

router = APIRouter(tags=["events"], prefix="/api/events")


@router.get("/")
async def list_(
    project_id: str | None = Query(None),
    event_type: str | None = Query(None),
    min_severity: str = Query("info"),
    since: datetime | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List recent events with optional filters."""
    return await list_events(
        pool, project_id=project_id, event_type=event_type,
        min_severity=min_severity, since=since, limit=limit,
    )


@router.post("/emit")
async def emit(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """Dev endpoint — manually emit an event for testing the stream."""
    if "event_type" not in body:
        raise HTTPException(400, "event_type required")
    eid = await emit_event(
        pool,
        event_type=body["event_type"],
        severity=body.get("severity", "info"),
        project_id=body.get("project_id"),
        substation_id=body.get("substation_id"),
        upgrade_id=body.get("upgrade_id"),
        payload=body.get("payload"),
        source=body.get("source", "manual"),
    )
    return {"event_id": eid}


@router.post("/diff/run")
async def diff(pool: asyncpg.Pool = Depends(get_pool)):
    """Run a full TEC + substation diff cycle and persist detected events."""
    return await run_full_diff_cycle(pool)


@router.get("/notifications")
async def notifications(
    user_id: str = Query("default"),
    unread_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List notifications for the given user."""
    return await list_notifications(pool, user_id=user_id, unread_only=unread_only, limit=limit)


@router.post("/notifications/{notification_id}/read")
async def mark_read(notification_id: int, pool: asyncpg.Pool = Depends(get_pool)):
    """Mark a single notification as read."""
    ok = await mark_notification_read(pool, notification_id)
    if not ok:
        raise HTTPException(404, "Notification not found")
    return {"notification_id": notification_id, "read": True}


@router.get("/rules")
async def rules(user_id: str = Query("default"), pool: asyncpg.Pool = Depends(get_pool)):
    """List alert rules for a user."""
    return await list_alert_rules(pool, user_id=user_id)


@router.post("/rules")
async def create_rule(body: dict = Body(...), pool: asyncpg.Pool = Depends(get_pool)):
    """Create a new alert rule."""
    rid = await create_alert_rule(pool, **body)
    return {"rule_id": rid}


@router.get("/stats")
async def stats(user_id: str = Query("default"), pool: asyncpg.Pool = Depends(get_pool)):
    """Aggregate stats for the Pulse header strip."""
    return await get_stats(pool, user_id=user_id)


@router.websocket("/ws")
async def ws_events(ws: WebSocket):
    """WebSocket — streams events and notifications to the connected client."""
    await ws.accept()
    try:
        # Heartbeat task
        async def heartbeat():
            while True:
                await asyncio.sleep(20)
                try:
                    await ws.send_text(json.dumps({"kind": "heartbeat", "ts": datetime.utcnow().isoformat()}))
                except Exception:
                    return
        hb_task = asyncio.create_task(heartbeat())

        async for message in event_bus.subscribe():
            try:
                await ws.send_text(json.dumps(message, default=str))
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        try:
            hb_task.cancel()
        except Exception:
            pass
