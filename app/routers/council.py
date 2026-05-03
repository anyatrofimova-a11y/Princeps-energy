"""Council router — SSE-streamed multi-pod adjudication.

Endpoints:
  POST /api/council/session                  — create a session, returns session_rid
  GET  /api/council/session/{rid}/stream     — SSE: pod_started x3, pod_verdict x3,
                                               adjudication, [clarification_needed],
                                               final_verdict
  POST /api/council/session/{rid}/clarify    — answer a clarification, resume adjudication

Each session is persisted in ``council_sessions``. Tool calls and the
adjudication decision land in ``ontology_action_log`` via the pod base class.

Wire shape: ``data: {"type": "...", ...}\\n\\n`` — same as chat.py + dockets.py
so the frontend EventSource consumer is interchangeable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent import AgentOutput
from app.agents.adjudication import (
    AdjudicationResult,
    adjudicate as adjudicate_fn,
)
from app.agents.pod import Pod, PodContext, PodTrace
from app.agents.pods import BessPod, DcPod, GridPod
from app.deps import get_claude, get_pool
from app.helpers import CLAUDE_MODEL

log = logging.getLogger("princeps.council.router")

router = APIRouter(prefix="/api/council", tags=["council"])


# ---------------------------------------------------------------------------
# In-memory session cache — persistent fields are also written to Postgres
# so a server restart loses transient state but not the audit trail.
# ---------------------------------------------------------------------------

class _CouncilSession:
    __slots__ = (
        "session_rid", "project_rid", "query", "pod_verdicts",
        "pod_traces", "adjudication", "clarifications", "ready_event",
        "stream_started", "created_at",
    )

    def __init__(self, session_rid: str, project_rid: Optional[str], query: str):
        self.session_rid = session_rid
        self.project_rid = project_rid
        self.query = query
        self.pod_verdicts: dict[str, AgentOutput] = {}
        self.pod_traces: dict[str, PodTrace] = {}
        self.adjudication: Optional[AdjudicationResult] = None
        self.clarifications: list[dict] = []
        # Set when a clarify request arrives so the streaming task can resume.
        self.ready_event: asyncio.Event = asyncio.Event()
        self.stream_started: bool = False
        self.created_at: float = time.time()


_sessions: dict[str, _CouncilSession] = {}


def _new_rid() -> str:
    return f"rid.princeps.council_session.{uuid.uuid4().hex}"


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


# ---------------------------------------------------------------------------
# Persistence — best-effort, never blocks the SSE stream
# ---------------------------------------------------------------------------

async def _persist_initial(pool, sess: _CouncilSession) -> None:
    if pool is None:
        return
    try:
        await pool.execute(
            """
            INSERT INTO council_sessions
              (session_rid, project_rid, query, created_at, updated_at, status)
            VALUES ($1, $2, $3, NOW(), NOW(), 'pending')
            ON CONFLICT (session_rid) DO NOTHING
            """,
            sess.session_rid, sess.project_rid, sess.query,
        )
    except Exception:
        log.exception("council session insert failed rid=%s", sess.session_rid)


async def _persist_update(pool, sess: _CouncilSession, status: str) -> None:
    if pool is None:
        return
    try:
        pod_dump = {n: v.model_dump() for n, v in sess.pod_verdicts.items()}
        adj_dump = sess.adjudication.to_dict() if sess.adjudication else None
        await pool.execute(
            """
            UPDATE council_sessions
               SET status = $2,
                   pod_verdicts = $3::jsonb,
                   final_verdict = $4::jsonb,
                   conflicts = $5::jsonb,
                   clarifications = $6::jsonb,
                   updated_at = NOW()
             WHERE session_rid = $1
            """,
            sess.session_rid,
            status,
            json.dumps(pod_dump, default=str),
            json.dumps(adj_dump, default=str) if adj_dump else None,
            json.dumps(sess.adjudication.conflicts if sess.adjudication else [], default=str),
            json.dumps(sess.clarifications, default=str),
        )
    except Exception:
        log.exception("council session update failed rid=%s", sess.session_rid)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CreateSessionBody(BaseModel):
    query: str
    project_rid: Optional[str] = None


class ClarifyBody(BaseModel):
    answer: str


# ---------------------------------------------------------------------------
# POST /api/council/session
# ---------------------------------------------------------------------------

@router.post("/session")
async def create_session(
    body: CreateSessionBody,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Create a council session. The actual pod work starts when the client
    opens the SSE stream — keeps the request cheap."""
    if not body.query or not body.query.strip():
        raise HTTPException(400, "query is required")
    sess = _CouncilSession(_new_rid(), body.project_rid, body.query.strip())
    _sessions[sess.session_rid] = sess
    await _persist_initial(pool, sess)
    return {"session_rid": sess.session_rid, "project_rid": sess.project_rid}


# ---------------------------------------------------------------------------
# Pod orchestration — parallel run + as_completed streaming
# ---------------------------------------------------------------------------

async def _run_pod_labeled(
    pod: Pod, query: str, ctx: PodContext, client,
) -> tuple[str, AgentOutput, PodTrace]:
    """Wraps Pod.run so asyncio.as_completed can identify which pod returned."""
    verdict, trace = await pod.run(query, ctx, client)
    return pod.name, verdict, trace


async def _stream_session(
    sess: _CouncilSession,
    pool,
    client,
    model: str,
):
    """Async generator yielding SSE events for the council run."""
    # --- announce + dispatch pods -----------------------------------------
    pods: list[Pod] = [GridPod(model=model), BessPod(model=model), DcPod(model=model)]
    yield _sse({
        "type": "session_started",
        "session_rid": sess.session_rid,
        "project_rid": sess.project_rid,
        "query": sess.query,
        "pods": [p.name for p in pods],
    })

    ctx = PodContext(
        session_rid=sess.session_rid,
        project_rid=sess.project_rid,
        pool=pool,
    )

    for p in pods:
        # Pre-compute bound tools so we can advertise the actual whitelist
        # subset (and any stubbed names) in the pod_started event.
        bound = [t["name"] for t in p._bound_tools()]
        yield _sse({
            "type": "pod_started",
            "pod": p.name,
            "model": p.model,
            "tools_bound": bound,
            "tools_stubbed": getattr(p, "_stubbed", []),
        })

    tasks = [
        asyncio.create_task(_run_pod_labeled(p, sess.query, ctx, client))
        for p in pods
    ]
    try:
        for fut in asyncio.as_completed(tasks):
            try:
                pod_name, verdict, trace = await fut
            except Exception as exc:
                log.exception("pod task crashed: %s", exc)
                yield _sse({
                    "type": "pod_error",
                    "error": str(exc)[:300],
                })
                continue
            sess.pod_verdicts[pod_name] = verdict
            sess.pod_traces[pod_name] = trace
            yield _sse({
                "type": "pod_verdict",
                "pod": pod_name,
                "verdict": verdict.model_dump(),
                "trace": {
                    "elapsed_s": trace.elapsed_s,
                    "tool_calls": trace.tool_calls,
                    "model": trace.model,
                    "error": trace.error,
                },
            })
    except Exception:
        log.exception("council pod fan-out failed")

    if not sess.pod_verdicts:
        yield _sse({
            "type": "error",
            "message": "All pods failed — no verdicts to adjudicate.",
        })
        await _persist_update(pool, sess, "failed")
        yield _sse({"type": "done"})
        return

    # --- adjudication -----------------------------------------------------
    yield _sse({
        "type": "adjudication",
        "stage": "started",
        "pods_received": list(sess.pod_verdicts.keys()),
    })
    adj = await adjudicate_fn(
        client=client,
        model=model,
        query=sess.query,
        verdicts=sess.pod_verdicts,
        pool=pool,
        session_rid=sess.session_rid,
        project_rid=sess.project_rid,
    )
    sess.adjudication = adj
    yield _sse({
        "type": "adjudication",
        "stage": "complete",
        "result": adj.to_dict(),
    })

    # --- conflict / clarification path -----------------------------------
    if adj.kind == "clarification_needed" and adj.clarification:
        yield _sse({
            "type": "clarification_needed",
            "session_rid": sess.session_rid,
            "question": adj.clarification.get("question"),
            "options": adj.clarification.get("options") or [],
            "conflicts": adj.conflicts,
        })
        await _persist_update(pool, sess, "clarification_needed")
        # Wait up to 5 minutes for the client to POST a clarify answer.
        try:
            await asyncio.wait_for(sess.ready_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            yield _sse({
                "type": "error",
                "message": "Clarification timed out — closing session.",
            })
            await _persist_update(pool, sess, "failed")
            yield _sse({"type": "done"})
            return
        # Resume adjudication with the user's clarifications baked in.
        adj2 = await adjudicate_fn(
            client=client,
            model=model,
            query=sess.query,
            verdicts=sess.pod_verdicts,
            pool=pool,
            session_rid=sess.session_rid,
            project_rid=sess.project_rid,
            user_clarifications=sess.clarifications,
        )
        sess.adjudication = adj2
        yield _sse({
            "type": "adjudication",
            "stage": "resumed",
            "result": adj2.to_dict(),
        })
        adj = adj2

    yield _sse({
        "type": "final_verdict",
        "session_rid": sess.session_rid,
        "result": adj.to_dict(),
    })
    await _persist_update(pool, sess, "complete")
    yield _sse({"type": "done"})


# ---------------------------------------------------------------------------
# GET /api/council/session/{rid}/stream
# ---------------------------------------------------------------------------

@router.get("/session/{session_rid}/stream")
async def stream_session(
    session_rid: str,
    request: Request,
    pool: asyncpg.Pool = Depends(get_pool),
    client=Depends(get_claude),
):
    sess = _sessions.get(session_rid)
    if sess is None:
        raise HTTPException(404, "council session not found")
    if sess.stream_started:
        raise HTTPException(409, "stream already opened for this session")
    sess.stream_started = True

    return StreamingResponse(
        _stream_session(sess, pool, client, CLAUDE_MODEL),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Council-Session-RID": session_rid,
        },
    )


# ---------------------------------------------------------------------------
# POST /api/council/session/{rid}/clarify
# ---------------------------------------------------------------------------

@router.post("/session/{session_rid}/clarify")
async def clarify_session(
    session_rid: str,
    body: ClarifyBody,
    pool: asyncpg.Pool = Depends(get_pool),
):
    sess = _sessions.get(session_rid)
    if sess is None:
        raise HTTPException(404, "council session not found")
    if not sess.adjudication or sess.adjudication.kind != "clarification_needed":
        raise HTTPException(409, "session is not waiting on a clarification")
    sess.clarifications.append({
        "answer": body.answer,
        "ts": datetime.now(timezone.utc).isoformat(),
        "question": (sess.adjudication.clarification or {}).get("question"),
    })
    sess.ready_event.set()
    await _persist_update(pool, sess, "running")
    return {"ok": True, "session_rid": session_rid}


# ---------------------------------------------------------------------------
# GET /api/council/session/{rid} — read-only snapshot for replay / debug
# ---------------------------------------------------------------------------

@router.get("/sessions")
async def list_sessions(
    limit: int = 10,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Recent council sessions, newest first. Used by the Mission Control
    Tools card to show council activity badges."""
    limit = max(1, min(50, int(limit)))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT session_rid, query, status, final_verdict, created_at
                 FROM council_sessions
                 ORDER BY created_at DESC
                 LIMIT $1""",
            limit,
        )
    sessions = []
    for r in rows:
        fv = r["final_verdict"]
        verdict = None
        if isinstance(fv, dict):
            verdict = fv.get("verdict") or fv.get("final_verdict")
        elif isinstance(fv, str):
            try:
                import json as _j
                verdict = (_j.loads(fv) or {}).get("verdict")
            except (ValueError, TypeError):
                pass
        sessions.append({
            "session_rid": r["session_rid"],
            "query": r["query"],
            "status": r["status"],
            "verdict": verdict,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/session/{session_rid}")
async def get_session(
    session_rid: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return persisted state for a session, useful for replay UIs."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT session_rid, project_rid, query, status,
                      pod_verdicts, final_verdict, conflicts, clarifications,
                      created_at, updated_at
                 FROM council_sessions WHERE session_rid = $1""",
            session_rid,
        )
    if not row:
        raise HTTPException(404, "council session not found")
    return {
        "session_rid": row["session_rid"],
        "project_rid": row["project_rid"],
        "query": row["query"],
        "status": row["status"],
        "pod_verdicts": row["pod_verdicts"],
        "final_verdict": row["final_verdict"],
        "conflicts": row["conflicts"],
        "clarifications": row["clarifications"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
