"""
app/routers/alerts.py — Princeps Alerts router (Task #6).

Wired under ``/api/alerts/*``. Auth via ``app.deps.get_current_user``. Soft
cap on the free tier is enforced via ``app.alerts.user_tiers``.

Endpoints
---------
GET    /api/alerts/library
POST   /api/alerts/subscribe
DELETE /api/alerts/subscribe/{subscription_id}
GET    /api/alerts/digest
GET    /api/alerts/digest/stream
GET    /api/alerts/doc/{doc_id}
POST   /api/alerts/query/stream
POST   /api/alerts/pin
DELETE /api/alerts/pin/{pin_id}
POST   /api/alerts/search
POST   /api/alerts/starter-packs                   (list)
POST   /api/alerts/starter-pack/{slug}/subscribe   (bulk subscribe)
POST   /api/alerts/run-digest/{alert_id}           (dev/ops: force-run one)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

import anthropic
import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.alerts.digest_worker import run_digest
from app.alerts.starter_packs import STARTER_PACKS, list_packs
from app.alerts.user_tiers import get_user_tier
from app.deps import get_claude, get_current_user, get_pool

log = logging.getLogger("princeps.alerts")


router = APIRouter(prefix="/api/alerts", tags=["alerts"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FREE_TIER_CAP = 5

CAP_RESPONSE_BODY = {
    "error": "ALERT_CAP",
    "cap": FREE_TIER_CAP,
    "upgrade_tiers": [
        {"slug": "individual", "gbp_monthly": 79},
        {"slug": "team",       "gbp_monthly": 299},
        {"slug": "enterprise", "gbp_monthly": 1500},
    ],
}

QUERY_MODEL  = "claude-sonnet-4-6"
EMBED_DIM    = 1536


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SubscribeBody(BaseModel):
    alert_id: UUID
    delivery_channels: dict[str, Any] | None = None
    pinned_project_id: UUID | None = None


class PinBody(BaseModel):
    doc_id: UUID
    project_id: UUID
    role: Literal["evidence", "precedent", "constraint", "counterfactual"] | None = "evidence"
    note: str | None = None


class QueryStreamBody(BaseModel):
    doc_ids: list[UUID] = Field(default_factory=list)
    question: str
    project_id: UUID | None = None


class SearchBody(BaseModel):
    commission: str | None = None
    docket_id: UUID | None = None
    keyword: str | None = None
    filing_type: list[str] | None = None
    topic_tags: list[str] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    bbox: list[float] | None = None   # [minLon, minLat, maxLon, maxLat]
    semantic_query: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_id(user: dict) -> str:
    return str(user.get("user_id") or user.get("id") or "anonymous")


def _encode_cursor(dt: datetime, digest_id: UUID) -> str:
    payload = json.dumps({"t": dt.isoformat(), "id": str(digest_id)}).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID] | None:
    try:
        padding = 4 - len(cursor) % 4
        data = base64.urlsafe_b64decode(cursor + "=" * padding)
        obj = json.loads(data)
        return datetime.fromisoformat(obj["t"]), UUID(obj["id"])
    except Exception:
        return None


def _jsonb(value: Any) -> Any:
    """Normalise a JSONB column value regardless of asyncpg version."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


async def _count_active_subs(pool: asyncpg.Pool, user_id: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT count(*)
              FROM alert_subscriptions
             WHERE user_id = $1 AND muted = FALSE
            """,
            user_id,
        ) or 0


async def _cap_exceeded(pool: asyncpg.Pool, user_id: str) -> bool:
    tier = await get_user_tier(pool, user_id)
    if tier != "free":
        return False
    count = await _count_active_subs(pool, user_id)
    return count >= FREE_TIER_CAP


# ---------------------------------------------------------------------------
# Embeddings (soft dep — use the ingestion helper if it ships, else stub)
# ---------------------------------------------------------------------------

async def _embed_text(text: str) -> list[float] | None:
    """Embed *text* via OpenAI. Returns ``None`` if embeddings are unavailable.

    TODO: wire ``app.ingestion.embeddings.embed_text`` once Task #5 lands.
    """
    try:
        from app.ingestion.embeddings import embed_text as _embed  # type: ignore
        return await _embed(text)
    except Exception:
        return None


async def _auto_pick_docs(conn, question: str, k: int = 8) -> list:
    """Pick top-K documents to ground *question* when the caller doesn't
    supply ``doc_ids``.

    Strategy: try pgvector cosine similarity if we can embed the question
    and at least one document has an embedding. Otherwise fall back to the
    ``tsv`` full-text index. As a final fallback return the most recent
    ``k`` documents so the model always has *something* to cite rather
    than replying blindly.
    """
    # 1) pgvector path — requires OpenAI embeddings and a populated vector.
    emb = await _embed_text(question)
    if emb is not None and len(emb) == EMBED_DIM:
        try:
            has_embedding = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM documents WHERE embedding IS NOT NULL)"
            )
            if has_embedding:
                rows = await conn.fetch(
                    """
                    SELECT doc_id, title, source, body_text, pages, source_url,
                           published_at
                      FROM documents
                     WHERE embedding IS NOT NULL
                     ORDER BY embedding <-> $1::vector
                     LIMIT $2
                    """,
                    emb, k,
                )
                if rows:
                    return rows
        except Exception:
            log.exception("pgvector auto-pick failed — falling back to tsvector")

    # 2) tsvector fallback — uses plainto_tsquery over title + body_text.
    try:
        rows = await conn.fetch(
            """
            SELECT doc_id, title, source, body_text, pages, source_url,
                   published_at
              FROM documents
             WHERE tsv @@ plainto_tsquery('english', $1)
             ORDER BY ts_rank(tsv, plainto_tsquery('english', $1)) DESC,
                      published_at DESC NULLS LAST
             LIMIT $2
            """,
            question, k,
        )
        if rows:
            return rows
    except Exception:
        log.exception("tsvector auto-pick failed — falling back to recency")

    # 3) Recency fallback — the model should at least have *some* evidence
    # to reason over. Never return an empty list from auto-pick.
    rows = await conn.fetch(
        """
        SELECT doc_id, title, source, body_text, pages, source_url,
               published_at
          FROM documents
         ORDER BY published_at DESC NULLS LAST
         LIMIT $1
        """,
        k,
    )
    return rows or []


# ---------------------------------------------------------------------------
# GET /api/alerts/library
# ---------------------------------------------------------------------------

@router.get("/library")
async def list_library(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List all alert definitions visible to the user, grouped by cluster."""
    user_id = _user_id(user)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, slug, title, description, cluster,
                   source_filter, cadence, est_docs_per_digest,
                   icp_tags, is_public, created_by, created_at
              FROM alert_definitions
             WHERE is_public = TRUE OR created_by::text = $1
             ORDER BY cluster NULLS LAST, title
             LIMIT $2 OFFSET $3
            """,
            user_id, limit, offset,
        )
        total = await conn.fetchval(
            """
            SELECT count(*) FROM alert_definitions
             WHERE is_public = TRUE OR created_by::text = $1
            """,
            user_id,
        ) or 0

    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"]) if d.get("id") else None
        d["created_by"] = str(d["created_by"]) if d.get("created_by") else None
        d["source_filter"] = _jsonb(d["source_filter"])
        cluster = d.get("cluster") or "Other"
        grouped.setdefault(cluster, []).append(d)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "clusters": [
            {"cluster": name, "items": items}
            for name, items in grouped.items()
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/alerts/subscribe
# ---------------------------------------------------------------------------

@router.post("/subscribe")
async def subscribe(
    body: SubscribeBody,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Subscribe the current user to an alert, enforcing the 5-alert free cap."""
    user_id = _user_id(user)

    if await _cap_exceeded(pool, user_id):
        return JSONResponse(status_code=402, content=CAP_RESPONSE_BODY)

    channels = body.delivery_channels or {"email": True, "in_app": True, "slack": False}

    async with pool.acquire() as conn:
        alert = await conn.fetchrow(
            "SELECT id, slug, title FROM alert_definitions WHERE id = $1",
            body.alert_id,
        )
        if not alert:
            raise HTTPException(status_code=404, detail="alert_not_found")

        row = await conn.fetchrow(
            """
            INSERT INTO alert_subscriptions
                (user_id, alert_id, delivery_channels, pinned_project_id)
            VALUES ($1, $2, $3::jsonb, $4)
            ON CONFLICT (user_id, alert_id, pinned_project_id)
            DO UPDATE SET
                delivery_channels = EXCLUDED.delivery_channels,
                muted = FALSE,
                updated_at = NOW()
            RETURNING id, user_id, alert_id, delivery_channels,
                      pinned_project_id, muted, created_at, updated_at
            """,
            user_id, body.alert_id, json.dumps(channels),
            body.pinned_project_id,
        )
    d = dict(row)
    d["id"] = str(d["id"])
    d["alert_id"] = str(d["alert_id"])
    d["pinned_project_id"] = str(d["pinned_project_id"]) if d.get("pinned_project_id") else None
    d["delivery_channels"] = _jsonb(d["delivery_channels"])
    return {"subscription": d, "alert": {"id": str(alert["id"]), "slug": alert["slug"], "title": alert["title"]}}


# ---------------------------------------------------------------------------
# DELETE /api/alerts/subscribe/{subscription_id}
# ---------------------------------------------------------------------------

@router.delete("/subscribe/{subscription_id}")
async def unsubscribe(
    subscription_id: UUID,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Remove a subscription. Users may only delete their own rows."""
    user_id = _user_id(user)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM alert_subscriptions WHERE id = $1 AND user_id = $2",
            subscription_id, user_id,
        )
    # asyncpg returns 'DELETE <n>'
    n = 0
    try:
        n = int(result.split()[-1])
    except Exception:
        pass
    if not n:
        raise HTTPException(status_code=404, detail="subscription_not_found")
    return {"deleted": n, "subscription_id": str(subscription_id)}


# ---------------------------------------------------------------------------
# GET /api/alerts/digest
# ---------------------------------------------------------------------------

@router.get("/digest")
async def list_digests(
    since: datetime | None = Query(None),
    alert_id: UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return digests for the user's active subscriptions, paginated."""
    user_id = _user_id(user)

    conds = ["s.user_id = $1", "s.muted = FALSE"]
    params: list[Any] = [user_id]
    next_idx = 2

    if alert_id is not None:
        conds.append(f"g.alert_id = ${next_idx}")
        params.append(alert_id)
        next_idx += 1

    if since is not None:
        conds.append(f"g.run_at > ${next_idx}")
        params.append(since)
        next_idx += 1

    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded:
            cursor_t, cursor_id = decoded
            conds.append(
                f"(g.run_at, g.id) < (${next_idx}, ${next_idx + 1})"
            )
            params.extend([cursor_t, cursor_id])
            next_idx += 2

    sql = f"""
        SELECT DISTINCT g.id, g.alert_id, g.run_at, g.document_ids,
               g.llm_extract, g.llm_structured, g.sent_at,
               a.slug AS alert_slug, a.title AS alert_title,
               a.cluster AS alert_cluster
          FROM alert_digests g
          JOIN alert_subscriptions s ON s.alert_id = g.alert_id
          JOIN alert_definitions a ON a.id = g.alert_id
         WHERE {' AND '.join(conds)}
         ORDER BY g.run_at DESC, g.id DESC
         LIMIT ${next_idx}
    """
    params.append(limit + 1)

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    has_more = len(rows) > limit
    rows = rows[:limit]

    digests = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["alert_id"] = str(d["alert_id"])
        d["document_ids"] = [str(x) for x in (d["document_ids"] or [])]
        d["llm_structured"] = _jsonb(d.get("llm_structured"))
        digests.append(d)

    next_cursor = None
    if has_more and digests:
        last = rows[-1]
        next_cursor = _encode_cursor(last["run_at"], last["id"])

    return {"digests": digests, "next_cursor": next_cursor, "count": len(digests)}


# ---------------------------------------------------------------------------
# GET /api/alerts/digest/stream  (SSE — polls and pushes new digests)
# ---------------------------------------------------------------------------

@router.get("/digest/stream")
async def digest_stream(
    request: Request,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Server-Sent Events feed of new digests for the current user.

    Polls every 5s for digests more recent than the high-water mark and pushes
    each as a single SSE ``data:`` line. Reuses the byte-envelope pattern used
    in ``app/chat.py``.
    """
    user_id = _user_id(user)

    async def _gen():
        # Establish high-water mark: anything before "now" is already visible.
        watermark = datetime.now(timezone.utc)
        yield f"data: {json.dumps({'type': 'connected', 't': watermark.isoformat()})}\n\n"

        while True:
            if await request.is_disconnected():
                return
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        """
                        SELECT DISTINCT g.id, g.alert_id, g.run_at, g.document_ids,
                               g.llm_extract, a.slug AS alert_slug,
                               a.title AS alert_title, a.cluster AS alert_cluster
                          FROM alert_digests g
                          JOIN alert_subscriptions s ON s.alert_id = g.alert_id
                          JOIN alert_definitions a ON a.id = g.alert_id
                         WHERE s.user_id = $1
                           AND s.muted = FALSE
                           AND g.run_at > $2
                         ORDER BY g.run_at ASC
                         LIMIT 50
                        """,
                        user_id, watermark,
                    )
                for r in rows:
                    d = dict(r)
                    d["id"] = str(d["id"])
                    d["alert_id"] = str(d["alert_id"])
                    d["document_ids"] = [str(x) for x in (d["document_ids"] or [])]
                    d["run_at"] = d["run_at"].isoformat() if d.get("run_at") else None
                    yield f"data: {json.dumps({'type': 'digest', 'digest': d}, default=str)}\n\n"
                    watermark = max(watermark, r["run_at"])
            except Exception as exc:
                log.warning("digest stream poll failed: %s", exc)
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)[:200]})}\n\n"

            await asyncio.sleep(5)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# GET /api/alerts/doc/{doc_id}
# ---------------------------------------------------------------------------

@router.get("/doc/{doc_id}")
async def get_doc(
    doc_id: UUID,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Full document + neighbours (pgvector <->) + pinned project IDs."""
    async with pool.acquire() as conn:
        doc = await conn.fetchrow(
            """
            SELECT doc_id, source, source_url, docket_id, commission_authority,
                   filing_type, procedural_stage, title, body_text, pages,
                   published_at, ingested_at, topic_tags, extracted_fields,
                   CASE WHEN geometry IS NOT NULL
                        THEN ST_AsGeoJSON(geometry::geometry)::jsonb
                        ELSE NULL END AS geometry_geojson,
                   stakeholder_id, created_at
              FROM documents
             WHERE doc_id = $1
            """,
            doc_id,
        )
        if not doc:
            raise HTTPException(status_code=404, detail="document_not_found")

        # Neighbours via pgvector — ignore if no embedding exists.
        neighbours = []
        try:
            n_rows = await conn.fetch(
                """
                SELECT d2.doc_id, d2.title, d2.source, d2.filing_type,
                       d2.published_at,
                       (d2.embedding <-> d1.embedding) AS distance
                  FROM documents d1
                  JOIN documents d2
                    ON d2.doc_id <> d1.doc_id
                   AND d2.embedding IS NOT NULL
                 WHERE d1.doc_id = $1
                   AND d1.embedding IS NOT NULL
                 ORDER BY d2.embedding <-> d1.embedding
                 LIMIT 5
                """,
                doc_id,
            )
            neighbours = [
                {
                    "doc_id": str(r["doc_id"]),
                    "title": r["title"],
                    "source": r["source"],
                    "filing_type": r["filing_type"],
                    "published_at": r["published_at"].isoformat() if r["published_at"] else None,
                    "distance": float(r["distance"]) if r["distance"] is not None else None,
                }
                for r in n_rows
            ]
        except Exception as exc:
            log.info("neighbour lookup skipped: %s", exc)

        pins = await conn.fetch(
            "SELECT id, project_id, role, note, pinned_by, created_at "
            "FROM document_project_pins WHERE doc_id = $1",
            doc_id,
        )

    d = dict(doc)
    d["doc_id"] = str(d["doc_id"])
    d["docket_id"] = str(d["docket_id"]) if d.get("docket_id") else None
    d["stakeholder_id"] = str(d["stakeholder_id"]) if d.get("stakeholder_id") else None
    d["topic_tags"] = _jsonb(d.get("topic_tags"))
    d["extracted_fields"] = _jsonb(d.get("extracted_fields"))
    d["geometry"] = _jsonb(d.pop("geometry_geojson", None))

    pinned = [
        {
            "id": str(p["id"]),
            "project_id": str(p["project_id"]),
            "role": p["role"],
            "note": p["note"],
            "pinned_by": p["pinned_by"],
            "created_at": p["created_at"].isoformat() if p.get("created_at") else None,
        }
        for p in pins
    ]

    return {"document": d, "neighbours": neighbours, "pinned_project_ids": pinned}


# ---------------------------------------------------------------------------
# POST /api/alerts/query/stream
# ---------------------------------------------------------------------------

@router.post("/query/stream")
async def query_stream(
    body: QueryStreamBody,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
    claude: anthropic.AsyncAnthropic = Depends(get_claude),
):
    """SSE stream — answer *question* over the given docs with ``[n]`` citations."""

    async def _gen():
        # When doc_ids is empty, auto-pick the top-K most relevant documents
        # using pgvector if an embedding is available, else fall back to the
        # tsvector full-text index. This is the live-mode version of the same
        # "give the model something to cite" guarantee that the frontend mock
        # corpus provides in mock mode.
        try:
            async with pool.acquire() as conn:
                if body.doc_ids:
                    rows = await conn.fetch(
                        """
                        SELECT doc_id, title, source, body_text, pages, source_url,
                               published_at
                          FROM documents
                         WHERE doc_id = ANY($1::uuid[])
                        """,
                        list(body.doc_ids),
                    )
                else:
                    rows = await _auto_pick_docs(conn, body.question, k=8)
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)[:200]})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        if not rows:
            yield f"data: {json.dumps({'type': 'error', 'message': 'no_documents_found'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # Build citation index + context
        citations = []
        context_parts: list[str] = []
        for i, r in enumerate(rows, start=1):
            body_text = (r["body_text"] or "")[:8000]
            pages = r.get("pages")
            citations.append({
                "n": i,
                "doc_id": str(r["doc_id"]),
                "page": 1,  # page-level citation requires per-page chunking; MVP uses page=1
                "title": r["title"],
                "source_url": r["source_url"],
            })
            context_parts.append(
                f"[{i}] Title: {r['title']}\n"
                f"    Source: {r['source']}  "
                f"Published: {r['published_at'].isoformat() if r.get('published_at') else '—'}\n"
                f"    Pages: {pages or '—'}\n"
                f"    Body excerpt:\n{body_text}\n"
            )

        # Emit the citation index up front so the UI can anchor [n] to a doc.
        yield f"data: {json.dumps({'type': 'citations', 'citations': citations})}\n\n"

        user_content = (
            f"Question: {body.question}\n\n"
            "Use the documents below. When a sentence is supported by a specific "
            "document, append the bracketed citation number, e.g. [1] or [3]. "
            "Do not fabricate citations. If the documents do not answer the "
            "question, say so and list what is missing.\n\n"
            + "\n---\n".join(context_parts)
        )

        try:
            async with claude.messages.stream(
                model=QUERY_MODEL,
                max_tokens=2048,
                messages=[{"role": "user", "content": user_content}],
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta is not None and hasattr(delta, "text") and delta.text:
                            yield f"data: {json.dumps({'type': 'text_delta', 'content': delta.text})}\n\n"
        except anthropic.APIError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)[:300]})}\n\n"
        except Exception as exc:
            log.exception("query stream failed: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)[:300]})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# POST /api/alerts/pin
# ---------------------------------------------------------------------------

async def _recompute_verdict_async(pool: asyncpg.Pool, project_id: UUID) -> None:
    """Fire-and-forget AgentVerdict delta recompute.

    Current state: the verdict-recompute pipeline lives in the agent module
    and is still being refactored. We defer loading it until pin-time so
    missing modules don't break subscribe / unsubscribe.
    """
    try:
        # Preferred location once the agent-service lands
        from app.agents.verdict import recompute_project_verdict  # type: ignore
        await recompute_project_verdict(pool, project_id)
    except Exception as exc:
        log.info(
            "Verdict recompute stub for project=%s (not yet wired): %s",
            project_id, exc,
        )


@router.post("/pin")
async def pin_document(
    body: PinBody,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Pin a document to a project and trigger a verdict-delta recompute."""
    user_id = _user_id(user)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO document_project_pins
                (project_id, doc_id, pinned_by, role, note)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (project_id, doc_id)
            DO UPDATE SET role = EXCLUDED.role, note = EXCLUDED.note
            RETURNING id, project_id, doc_id, pinned_by, role, note, created_at
            """,
            body.project_id, body.doc_id, user_id, body.role, body.note,
        )
    background_tasks.add_task(_recompute_verdict_async, pool, body.project_id)

    d = dict(row)
    d["id"] = str(d["id"])
    d["project_id"] = str(d["project_id"])
    d["doc_id"] = str(d["doc_id"])
    d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
    return {"pin": d}


@router.delete("/pin/{pin_id}")
async def unpin_document(
    pin_id: UUID,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Remove a pin (owner only) and trigger verdict-delta recompute."""
    user_id = _user_id(user)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            DELETE FROM document_project_pins
             WHERE id = $1 AND pinned_by = $2
            RETURNING project_id
            """,
            pin_id, user_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="pin_not_found")

    background_tasks.add_task(_recompute_verdict_async, pool, row["project_id"])
    return {"deleted": True, "pin_id": str(pin_id), "project_id": str(row["project_id"])}


# ---------------------------------------------------------------------------
# POST /api/alerts/search
# ---------------------------------------------------------------------------

@router.post("/search")
async def search_documents(
    body: SearchBody,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Hybrid search: tsvector + JSONB tags + PostGIS bbox + optional pgvector."""
    conds: list[str] = []
    params: list[Any] = []
    next_idx = 1

    if body.commission:
        conds.append(f"d.commission_authority = ${next_idx}")
        params.append(body.commission)
        next_idx += 1

    if body.docket_id is not None:
        conds.append(f"d.docket_id = ${next_idx}")
        params.append(body.docket_id)
        next_idx += 1

    if body.keyword:
        conds.append(f"d.tsv @@ plainto_tsquery('english', ${next_idx})")
        params.append(body.keyword)
        next_idx += 1

    if body.filing_type:
        conds.append(f"d.filing_type = ANY(${next_idx}::text[])")
        params.append(list(body.filing_type))
        next_idx += 1

    if body.topic_tags:
        conds.append(
            f"""EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(
                    CASE jsonb_typeof(d.topic_tags)
                         WHEN 'array' THEN d.topic_tags
                         ELSE '[]'::jsonb
                    END
                ) t(tag)
                 WHERE t.tag = ANY(${next_idx}::text[])
            )"""
        )
        params.append(list(body.topic_tags))
        next_idx += 1

    if body.date_from is not None:
        conds.append(f"d.published_at >= ${next_idx}")
        params.append(body.date_from)
        next_idx += 1

    if body.date_to is not None:
        conds.append(f"d.published_at <= ${next_idx}")
        params.append(body.date_to)
        next_idx += 1

    if body.bbox and len(body.bbox) == 4:
        conds.append(
            f"""d.geometry IS NOT NULL
                AND ST_Intersects(
                    d.geometry,
                    ST_MakeEnvelope(${next_idx}, ${next_idx + 1},
                                    ${next_idx + 2}, ${next_idx + 3}, 4326)::geography
                )"""
        )
        params.extend(body.bbox)
        next_idx += 4

    order_clause = "ORDER BY d.published_at DESC NULLS LAST"

    if body.semantic_query:
        emb = await _embed_text(body.semantic_query)
        if emb is not None and len(emb) == EMBED_DIM:
            conds.append(f"d.embedding IS NOT NULL")
            order_clause = f"ORDER BY d.embedding <-> ${next_idx}::vector"
            params.append(emb)
            next_idx += 1
        else:
            # Fall back to tsvector match against the semantic query string
            conds.append(f"d.tsv @@ plainto_tsquery('english', ${next_idx})")
            params.append(body.semantic_query)
            next_idx += 1

    where_sql = ("WHERE " + " AND ".join(conds)) if conds else ""

    sql = f"""
        SELECT d.doc_id, d.title, d.source, d.source_url, d.filing_type,
               d.commission_authority, d.procedural_stage, d.docket_id,
               d.published_at, d.topic_tags
          FROM documents d
          {where_sql}
          {order_clause}
          LIMIT ${next_idx}
          OFFSET ${next_idx + 1}
    """
    params.extend([body.limit, body.offset])

    count_sql = f"SELECT count(*) FROM documents d {where_sql}"
    count_params = params[:-2]  # strip limit / offset
    # Drop the embedding/semantic param from count_sql if we used pgvector
    # — the count doesn't care about ORDER BY params. We only stripped
    # LIMIT+OFFSET; but the embedding param is actually used in the WHERE
    # indirectly via `d.embedding IS NOT NULL` which had no param. If we
    # used an embedding for ORDER BY we added one positional param after
    # the conds, so trim it off count_params.
    if body.semantic_query:
        # Figure out whether the last param is the vector / fallback string.
        # Safe heuristic: if the last param is a list of floats, strip it.
        if count_params and isinstance(count_params[-1], list) and all(isinstance(x, (int, float)) for x in count_params[-1]):
            count_params = count_params[:-1]

    # Facets: counts by filing_type and commission
    facet_sql_filing = f"""
        SELECT COALESCE(d.filing_type, '(unknown)') AS v, count(*) AS c
          FROM documents d
          {where_sql}
         GROUP BY 1
         ORDER BY c DESC
         LIMIT 25
    """
    facet_sql_source = f"""
        SELECT COALESCE(d.source, '(unknown)') AS v, count(*) AS c
          FROM documents d
          {where_sql}
         GROUP BY 1
         ORDER BY c DESC
         LIMIT 25
    """

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            total = await conn.fetchval(count_sql, *count_params) or 0
            facet_filing = await conn.fetch(facet_sql_filing, *count_params)
            facet_source = await conn.fetch(facet_sql_source, *count_params)
    except Exception as exc:
        log.exception("search failed: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "search_failed", "reason": str(exc)[:200]})

    docs = []
    for r in rows:
        d = dict(r)
        d["doc_id"] = str(d["doc_id"])
        d["docket_id"] = str(d["docket_id"]) if d.get("docket_id") else None
        d["topic_tags"] = _jsonb(d.get("topic_tags"))
        d["published_at"] = d["published_at"].isoformat() if d.get("published_at") else None
        docs.append(d)

    return {
        "documents": docs,
        "total": total,
        "limit": body.limit,
        "offset": body.offset,
        "facets": {
            "filing_type": [{"value": r["v"], "count": r["c"]} for r in facet_filing],
            "source":      [{"value": r["v"], "count": r["c"]} for r in facet_source],
        },
    }


# ---------------------------------------------------------------------------
# Starter packs
# ---------------------------------------------------------------------------

@router.get("/starter-packs")
async def starter_packs_list(
    user: dict = Depends(get_current_user),
):
    """List available starter packs (ICP bundles)."""
    return {"packs": list_packs()}


@router.post("/starter-pack/{pack_slug}/subscribe")
async def starter_pack_subscribe(
    pack_slug: str,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Bulk-subscribe the user to a starter pack.

    Respects the 5-alert free-tier cap. If the pack would put the user over
    the cap we subscribe up to the cap and return the remaining slugs as
    ``pack_remaining`` so the UI can upsell. Returns 402 only when the user
    is already at the cap and no slugs could be subscribed.
    """
    pack = STARTER_PACKS.get(pack_slug)
    if not pack:
        raise HTTPException(status_code=404, detail="pack_not_found")

    user_id = _user_id(user)
    tier = await get_user_tier(pool, user_id)
    is_free = tier == "free"

    # Resolve slug → alert_id once
    async with pool.acquire() as conn:
        alert_rows = await conn.fetch(
            "SELECT id, slug FROM alert_definitions WHERE slug = ANY($1::text[])",
            list(pack["alerts"]),
        )
    slug_to_id: dict[str, UUID] = {r["slug"]: r["id"] for r in alert_rows}

    subscribed: list[dict[str, Any]] = []
    remaining: list[str] = []

    current_count = await _count_active_subs(pool, user_id)

    for slug in pack["alerts"]:
        alert_id = slug_to_id.get(slug)
        if alert_id is None:
            # Alert slug not seeded — skip gracefully
            continue

        if is_free and current_count >= FREE_TIER_CAP:
            remaining.append(slug)
            continue

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO alert_subscriptions
                    (user_id, alert_id, delivery_channels)
                VALUES ($1, $2, '{"email":true,"in_app":true,"slack":false}'::jsonb)
                ON CONFLICT (user_id, alert_id, pinned_project_id)
                DO UPDATE SET muted = FALSE, updated_at = NOW()
                RETURNING id, alert_id, created_at, updated_at
                """,
                user_id, alert_id,
            )
        subscribed.append({
            "subscription_id": str(row["id"]),
            "alert_id": str(row["alert_id"]),
            "slug": slug,
        })
        current_count += 1

    if is_free and not subscribed and remaining:
        return JSONResponse(status_code=402, content={**CAP_RESPONSE_BODY, "pack_remaining": remaining})

    return {
        "pack_slug": pack_slug,
        "subscribed": subscribed,
        "pack_remaining": remaining,
        "tier": tier,
        "cap": FREE_TIER_CAP if is_free else None,
    }


# ---------------------------------------------------------------------------
# POST /api/alerts/run-digest/{alert_id}  (dev / ops)
# ---------------------------------------------------------------------------

@router.post("/run-digest/{alert_id}")
async def run_digest_endpoint(
    alert_id: UUID,
    force: bool = Query(True),
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
    claude: anthropic.AsyncAnthropic = Depends(get_claude),
):
    """Force-run a single alert's digest. Handy for ops / tests."""
    return await run_digest(pool, alert_id, claude=claude, force=force)
