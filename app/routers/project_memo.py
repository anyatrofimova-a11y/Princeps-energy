"""Project KPI + AI Site Memo router — `/api/project/*`.

Endpoints
---------
GET  /api/project/{id}/kpis               -> live 5-number KPI strip (Redis-cached 1h)
POST /api/project/{id}/site-memo          -> kicks off memo generation, returns id
GET  /api/project/{id}/site-memo/stream   -> SSE progress for the active job
GET  /api/project/{id}/site-memo/history  -> past memos with PDF URLs

Expensive step (Claude compose + Playwright render) runs as a background
task with stage-by-stage SSE updates so the frontend can show a progress bar.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from utils.project_kpis import compute_kpis
from utils.site_memo import compose_memo, render_memo_pdf

log = logging.getLogger("princeps.routers.project_memo")

router = APIRouter(prefix="/api/project", tags=["project-memo"])

# ---------------------------------------------------------------------------
# In-memory job registry — memo generation is slow so we surface progress.
# One entry per (project_id, memo_id) so multiple memos can run in parallel.
# ---------------------------------------------------------------------------
_JOBS: dict[str, dict[str, Any]] = {}
_JOB_EVENTS: dict[str, asyncio.Queue] = {}


def _pub(memo_id: str, event: str, payload: dict | None = None) -> None:
    """Push a progress event to any subscribed SSE stream."""
    q = _JOB_EVENTS.get(memo_id)
    if q is None:
        return
    try:
        q.put_nowait({"event": event, "at": time.time(), **(payload or {})})
    except asyncio.QueueFull:
        pass


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class SiteMemoTriggerRequest(BaseModel):
    intent: str | None = "full"
    force_refresh: bool = False


class SiteMemoTriggerResponse(BaseModel):
    memo_id: str
    status: str
    stream_url: str


# ---------------------------------------------------------------------------
# GET /{id}/kpis
# ---------------------------------------------------------------------------
@router.get("/{project_id}/kpis")
async def get_project_kpis(project_id: str, request: Request) -> dict:
    pool = getattr(request.app.state, "pool", None)
    kpi = await compute_kpis(project_id, pool=pool)
    return kpi.as_dict()


# ---------------------------------------------------------------------------
# Memo generation — orchestrator + background worker
# ---------------------------------------------------------------------------
async def _gather_memo_context(pool, claude_client, project_id: str) -> dict:
    """Pull everything the composer needs in a single pass."""
    ctx: dict[str, Any] = {"project": {"project_id": project_id}, "verdicts": {}}

    if pool is None:
        return ctx

    try:
        async with pool.acquire() as conn:
            proj = await conn.fetchrow(
                """
                SELECT project_id, name, technology, capacity_mw, stage, verdict,
                       lat, lon, parcel_id, metadata
                FROM projects WHERE project_id::text = $1
                """,
                str(project_id),
            )
            if proj:
                ctx["project"] = {k: proj[k] for k in proj.keys()}

            # Latest verdict per intent.
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (intent)
                    intent, verdict, confidence, summary, result_json, created_at
                FROM agent_analyses
                WHERE parcel_id = COALESCE(
                    (SELECT parcel_id FROM projects WHERE project_id::text = $1),
                    '00000000-0000-0000-0000-000000000000'::uuid
                )
                ORDER BY intent, created_at DESC
                """,
                str(project_id),
            )
            for r in rows:
                ctx["verdicts"][r["intent"]] = {
                    "verdict": r["verdict"],
                    "confidence": float(r.get("confidence") or 0.5),
                    "summary": r["summary"],
                }

            # Grid — latest assessment blob.
            grid_row = await conn.fetchrow(
                """
                SELECT result_json FROM grid_assessments ga
                JOIN projects p ON p.parcel_id = ga.parcel_id
                WHERE p.project_id::text = $1
                ORDER BY ga.created_at DESC LIMIT 1
                """,
                str(project_id),
            )
            if grid_row and grid_row["result_json"]:
                blob = grid_row["result_json"]
                if isinstance(blob, str):
                    try:
                        blob = json.loads(blob)
                    except Exception:
                        blob = {}
                ctx["grid"] = blob
    except Exception as e:  # noqa: BLE001
        log.debug("gather_memo_context partial: %s", e)

    return ctx


async def _save_memo(pool, project_id: str, memo_json: dict, pdf_path: pathlib.Path) -> dict:
    """Persist to the `site_memos` table; best-effort — errors become warnings."""
    if pool is None:
        return {"memo_id": str(uuid4()), "version": 1}

    try:
        async with pool.acquire() as conn:
            version = await conn.fetchval(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM site_memos WHERE project_id::text = $1",
                str(project_id),
            ) or 1
            row = await conn.fetchrow(
                """
                INSERT INTO site_memos (project_id, version, memo_json, pdf_path, generated_by)
                VALUES ($1::uuid, $2, $3::jsonb, $4, $5)
                RETURNING memo_id, version
                """,
                str(project_id),
                version,
                json.dumps(memo_json, default=str),
                str(pdf_path),
                "system",
            )
            return {"memo_id": str(row["memo_id"]), "version": row["version"]}
    except Exception as e:  # noqa: BLE001
        log.warning("site_memos insert failed (table may not exist yet): %s", e)
        return {"memo_id": str(uuid4()), "version": 1}


async def _run_memo_job(
    app_state: Any,
    project_id: str,
    memo_id: str,
) -> None:
    pool = getattr(app_state, "pool", None)
    claude = getattr(app_state, "claude", None)
    job = _JOBS[memo_id]
    try:
        _pub(memo_id, "stage", {"stage": "gather", "pct": 10})
        ctx = await _gather_memo_context(pool, claude, project_id)

        _pub(memo_id, "stage", {"stage": "compose", "pct": 35})
        memo_json = await compose_memo(ctx, claude_client=claude)
        memo_json["_project"] = ctx.get("project", {})

        _pub(memo_id, "stage", {"stage": "render", "pct": 70})
        pdf_bytes, pdf_path = await render_memo_pdf(
            memo_json,
            project=ctx.get("project", {}),
            filename_hint=(ctx.get("project", {}).get("name") or "memo"),
        )

        _pub(memo_id, "stage", {"stage": "persist", "pct": 90})
        saved = await _save_memo(pool, project_id, memo_json, pdf_path)

        pdf_url = f"/api/project/{project_id}/site-memo/{saved['memo_id']}/pdf"
        job.update({
            "status": "done",
            "memo_json": memo_json,
            "pdf_path": str(pdf_path),
            "pdf_bytes_len": len(pdf_bytes),
            "pdf_url": pdf_url,
            "saved_memo_id": saved["memo_id"],
            "version": saved["version"],
        })
        _pub(memo_id, "done", {"pct": 100, "pdf_url": pdf_url, "memo_json": memo_json})
    except Exception as e:  # noqa: BLE001
        log.exception("memo job failed: %s", e)
        job.update({"status": "error", "error": str(e)})
        _pub(memo_id, "error", {"message": str(e)})
    finally:
        # Close the subscriber queue after a short grace period so in-flight
        # SSE readers can drain.
        await asyncio.sleep(0.5)
        _JOB_EVENTS.pop(memo_id, None)


# ---------------------------------------------------------------------------
# POST /{id}/site-memo  — kick off generation
# ---------------------------------------------------------------------------
@router.post("/{project_id}/site-memo", response_model=SiteMemoTriggerResponse)
async def trigger_site_memo(
    project_id: str,
    request: Request,
    body: SiteMemoTriggerRequest | None = None,
) -> SiteMemoTriggerResponse:
    memo_id = str(uuid4())
    _JOBS[memo_id] = {
        "project_id": project_id,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    _JOB_EVENTS[memo_id] = asyncio.Queue(maxsize=64)
    asyncio.create_task(_run_memo_job(request.app.state, project_id, memo_id))
    return SiteMemoTriggerResponse(
        memo_id=memo_id,
        status="running",
        stream_url=f"/api/project/{project_id}/site-memo/stream?memo_id={memo_id}",
    )


# ---------------------------------------------------------------------------
# GET /{id}/site-memo/stream  — SSE progress
# ---------------------------------------------------------------------------
@router.get("/{project_id}/site-memo/stream")
async def site_memo_stream(project_id: str, memo_id: str) -> StreamingResponse:
    async def _generator():
        q = _JOB_EVENTS.get(memo_id)
        if q is None:
            # Job may have already completed — replay final status.
            job = _JOBS.get(memo_id)
            if job and job.get("status") == "done":
                yield _sse("done", {"pct": 100, "pdf_url": job.get("pdf_url"),
                                    "memo_json": job.get("memo_json")})
            else:
                yield _sse("error", {"message": "unknown memo_id"})
            return

        yield _sse("stage", {"stage": "queued", "pct": 5})
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=60)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            event = ev.get("event", "message")
            yield _sse(event, ev)
            if event in ("done", "error"):
                break

    return StreamingResponse(_generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# ---------------------------------------------------------------------------
# GET /{id}/site-memo/history
# ---------------------------------------------------------------------------
@router.get("/{project_id}/site-memo/history")
async def site_memo_history(project_id: str, request: Request, limit: int = 10) -> dict:
    pool = getattr(request.app.state, "pool", None)
    items: list[dict] = []
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT memo_id, version, memo_json, pdf_path, generated_by, generated_at
                    FROM site_memos
                    WHERE project_id::text = $1
                    ORDER BY generated_at DESC LIMIT $2
                    """,
                    str(project_id), limit,
                )
                for r in rows:
                    blob = r["memo_json"]
                    if isinstance(blob, str):
                        try:
                            blob = json.loads(blob)
                        except Exception:
                            blob = {}
                    items.append({
                        "memo_id": str(r["memo_id"]),
                        "version": r["version"],
                        "title": (blob or {}).get("title"),
                        "verdict": (blob or {}).get("investment_verdict"),
                        "generated_by": r["generated_by"],
                        "generated_at": r["generated_at"].isoformat() if r["generated_at"] else None,
                        "pdf_url": f"/api/project/{project_id}/site-memo/{r['memo_id']}/pdf",
                    })
        except Exception as e:  # noqa: BLE001
            log.debug("site_memo_history failed: %s", e)

    # Also include in-flight / just-finished jobs not yet in DB.
    for mid, job in _JOBS.items():
        if job.get("project_id") != project_id:
            continue
        if any(it["memo_id"] == job.get("saved_memo_id") for it in items):
            continue
        items.append({
            "memo_id": job.get("saved_memo_id") or mid,
            "version": job.get("version"),
            "title": (job.get("memo_json") or {}).get("title"),
            "verdict": (job.get("memo_json") or {}).get("investment_verdict"),
            "generated_by": "system",
            "generated_at": job.get("started_at"),
            "pdf_url": job.get("pdf_url"),
            "status": job.get("status"),
        })

    return {"memos": items}


# ---------------------------------------------------------------------------
# GET /{id}/site-memo/{memo_id}/pdf  — download the rendered PDF
# ---------------------------------------------------------------------------
@router.get("/{project_id}/site-memo/{memo_id}/pdf")
async def download_site_memo_pdf(project_id: str, memo_id: str, request: Request):
    # First consult in-memory job map (newest).
    for _mid, job in _JOBS.items():
        if job.get("saved_memo_id") == memo_id and job.get("pdf_path"):
            p = pathlib.Path(job["pdf_path"])
            if p.is_file():
                return FileResponse(p, media_type="application/pdf", filename=p.name)

    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(status_code=404, detail="memo not found")

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT pdf_path FROM site_memos WHERE memo_id::text = $1 AND project_id::text = $2",
                memo_id, str(project_id),
            )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"lookup failed: {e}")

    if not row or not row["pdf_path"]:
        raise HTTPException(status_code=404, detail="memo not found")
    p = pathlib.Path(row["pdf_path"])
    if not p.is_file():
        raise HTTPException(status_code=410, detail="memo PDF no longer on disk")
    return FileResponse(p, media_type="application/pdf", filename=p.name)
