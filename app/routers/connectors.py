"""Connector introspection + manual refresh endpoints.

    GET  /api/connectors/health        -> [ConnectorHealth, ...]
    GET  /api/connectors                -> [{source_name, schedule}, ...]
    POST /api/connectors/{name}/refresh -> IngestReport

Connectors register themselves at import time (``app.connectors``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.deps import get_pool

# Importing app.connectors side-effect-registers every connector.
from app.connectors import get_connector, list_connectors

log = logging.getLogger("princeps.connectors.router")

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


@router.get("")
async def list_all_connectors() -> list[dict[str, Any]]:
    """List every registered connector (name + cron schedule)."""
    return [
        {
            "source_name": getattr(c, "source_name", "?"),
            "schedule": getattr(c, "schedule", ""),
        }
        for c in list_connectors()
    ]


@router.get("/health")
async def connector_health(
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[dict[str, Any]]:
    """Return a ConnectorHealth snapshot for every registered connector."""
    results: list[dict[str, Any]] = []
    for c in list_connectors():
        pool_fn = getattr(c, "health_with_pool", None)
        try:
            if pool_fn is not None:
                h = await pool_fn(pool)
            else:
                h = await c.health()
        except Exception as e:
            log.warning("health for %s failed: %s",
                        getattr(c, "source_name", "?"), e)
            results.append({
                "source_name": getattr(c, "source_name", "?"),
                "status": "red",
                "message": f"health() error: {e}",
                "schedule": getattr(c, "schedule", ""),
            })
            continue
        results.append(h.to_json())
    return results


@router.get("/{name}/health")
async def one_connector_health(
    name: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    c = get_connector(name)
    if c is None:
        raise HTTPException(404, f"connector {name!r} not registered")
    health_fn = getattr(c, "health_with_pool", None)
    if health_fn is not None:
        h = await health_fn(pool)
    else:
        h = await c.health()
    return h.to_json()


@router.post("/{name}/refresh")
async def refresh_connector(
    name: str,
    background: BackgroundTasks,
    wait: bool = False,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Trigger a refresh. ``wait=true`` runs in-request; otherwise enqueue."""
    c = get_connector(name)
    if c is None:
        raise HTTPException(404, f"connector {name!r} not registered")

    if wait:
        report = await c.refresh(pool)
        return {"queued": False, "report": report.to_json()}

    async def _runner() -> None:
        try:
            await c.refresh(pool)
        except Exception as e:
            log.exception("background refresh %s failed: %s", name, e)

    background.add_task(asyncio.create_task, _runner())  # type: ignore[arg-type]
    return {
        "queued": True,
        "source_name": name,
        "schedule": getattr(c, "schedule", ""),
    }
