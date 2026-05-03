"""``/api/connector-scheduler`` — status + manual control surface.

Thin REST surface over the singleton :class:`ConnectorScheduler`
stashed on ``app.state.connector_scheduler`` by ``app/startup.py``.

Endpoints
---------

  GET  /api/connector-scheduler/status
       Return one record per registered connector — cadence, next fire,
       last fire, last ok flag, schedule_disabled, paused, etc.

  POST /api/connector-scheduler/{slug}/pause
  POST /api/connector-scheduler/{slug}/resume
  POST /api/connector-scheduler/{slug}/fire-now
       Operator hooks. fire-now schedules a one-shot run on the next
       event-loop tick; the response is immediate and the caller polls
       ``connector_schedule_log`` (or this endpoint) for completion.

License-blocked connectors land in ``schedule_disabled=true`` via the
scheduler's run loop — the operator's only recourse is to clear that
flag in ``princeps_datasets`` and call /resume. We don't expose a
""force fire"" override here; the license guard is non-negotiable.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

log = logging.getLogger("princeps.connector_scheduler.router")

router = APIRouter(prefix="/api/connector-scheduler", tags=["connector-scheduler"])


def _scheduler_or_404(request: Request):
    cs = getattr(request.app.state, "connector_scheduler", None)
    if cs is None:
        raise HTTPException(
            status_code=503,
            detail="connector scheduler not started",
        )
    return cs


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/status")
async def status(request: Request) -> dict:
    """Per-connector schedule status, merged with princeps_datasets state."""
    cs = _scheduler_or_404(request)
    rows = await cs.status_with_db()
    return {
        "running": cs._scheduler is not None,
        "scheduler": rows,
        "count": len(rows),
    }


@router.post("/{slug}/pause")
async def pause(slug: str, request: Request) -> dict:
    cs = _scheduler_or_404(request)
    result = cs.pause(slug)
    if not result.get("ok"):
        # 404 if the slug is unknown, 409 for other failures
        if result.get("error") == "no_such_job":
            raise HTTPException(status_code=404, detail=result["error"])
        raise HTTPException(status_code=409, detail=result.get("error", "pause failed"))
    return result


@router.post("/{slug}/resume")
async def resume(slug: str, request: Request) -> dict:
    cs = _scheduler_or_404(request)
    result = cs.resume(slug)
    if not result.get("ok"):
        if result.get("error") == "no_such_job":
            raise HTTPException(status_code=404, detail=result["error"])
        raise HTTPException(status_code=409, detail=result.get("error", "resume failed"))
    return result


@router.post("/{slug}/fire-now")
async def fire_now(slug: str, request: Request) -> dict:
    """Schedule an ad-hoc run on the next event-loop tick. Returns immediately."""
    cs = _scheduler_or_404(request)
    result = cs.fire_now(slug)
    if not result.get("ok"):
        err = result.get("error", "fire_now failed")
        status_code = 404 if err == "no_such_connector" else 409
        raise HTTPException(status_code=status_code, detail=err)
    return result


__all__ = ["router"]
