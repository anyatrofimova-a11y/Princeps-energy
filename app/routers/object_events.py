"""Object event stream — live SSE bridge over Postgres LISTEN/NOTIFY.

  GET /api/events/object-mutated/stream?label=&rid=
                                                    SSE feed of every
                                                    auto-emit trigger fire.
                                                    Optional label/rid
                                                    filters narrow the
                                                    delivered events.

Each event:
  data: {"rid": "rid.princeps.project.<uuid>",
         "label": "Project",
         "op": "INSERT|UPDATE|DELETE",
         "ts": 1735741234.567}

Foundry calls this "object event streams" — every Slate widget binds via
useObjectEvents(label_or_rid) and re-fetches when the underlying data
mutates anywhere in the graph.
"""

from __future__ import annotations

import asyncio
import json
import logging

import asyncpg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.deps import get_pool

log = logging.getLogger("princeps.object_events")
router = APIRouter(prefix="/api/events", tags=["events"])

CHANNEL = "princeps_object_mutated"


@router.get("/object-mutated/stream")
async def stream_object_mutations(
    request: Request,
    label: str | None = Query(None, description="filter by ontology label (Project, Substation, ...)"),
    rid: str | None = Query(None, description="filter by exact rid"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """SSE stream of ObjectMutated events. Filters apply server-side so we
    don't broadcast unnecessary bytes to the client."""

    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)

    def _on_notify(_conn, _pid, _channel, payload: str) -> None:
        try:
            event = json.loads(payload)
        except (ValueError, TypeError):
            return
        if label and event.get("label") != label:
            return
        if rid and event.get("rid") != rid:
            return
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("object event queue full — dropping event for rid=%s", event.get("rid"))

    async def gen():
        # Acquire dedicated connection for LISTEN — pool acquire is OK because
        # asyncpg holds it until released, and we only need the lifetime of the
        # SSE stream.
        listener_conn = await pool.acquire()
        try:
            await listener_conn.add_listener(CHANNEL, _on_notify)
            log.info("SSE subscriber attached: label=%s rid=%s", label, rid)

            # Initial heartbeat so the client knows the stream is live.
            yield f"event: ready\ndata: {json.dumps({'channel': CHANNEL, 'label': label, 'rid': rid})}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    # Time out periodically so we can re-check the disconnect flag
                    # and emit keepalive comments through proxies.
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            try:
                await listener_conn.remove_listener(CHANNEL, _on_notify)
            except Exception:
                pass
            try:
                await pool.release(listener_conn)
            except Exception:
                pass
            log.info("SSE subscriber detached: label=%s rid=%s", label, rid)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
