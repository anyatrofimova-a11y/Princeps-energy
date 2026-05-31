"""Phase C — clause retrieval for the cite_clause action.

Two backends, in priority order:
  1. pgvector cosine (if embedding column populated)
  2. PostgreSQL FTS via plainto_tsquery + ts_rank_cd

The output shape is what the chat layer renders into the right-rail
citations panel: ``[{clause_rid, section, heading, page, verbatim, similarity}]``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import asyncpg
import httpx

log = logging.getLogger(__name__)


async def _voyage_embed_query(query: str) -> list[float] | None:
    api_key = os.getenv("VOYAGE_API_KEY")
    if not api_key:
        return None
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"model": "voyage-3", "input": [query], "input_type": "query"},
        )
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]


async def cite_clauses(
    pool: asyncpg.Pool,
    *,
    project_rid: str | None = None,
    document_rid: str | None = None,
    draft_rid: str | None = None,
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Return top-k matching clauses scoped by project / document / draft."""
    where_clauses = []
    params: list[Any] = []

    def _bind(v):
        params.append(v)
        return f"${len(params)}"

    if draft_rid:
        where_clauses.append(f"c.draft_rid = {_bind(draft_rid)}")
    elif document_rid:
        where_clauses.append(
            f"c.draft_rid IN (SELECT draft_rid FROM contracts.document_drafts "
            f"WHERE document_rid = {_bind(document_rid)})"
        )
    elif project_rid:
        where_clauses.append(
            f"c.draft_rid IN (SELECT dd.draft_rid FROM contracts.document_drafts dd "
            f"JOIN contracts.documents d ON dd.document_rid = d.document_rid "
            f"WHERE d.project_rid = {_bind(project_rid)})"
        )
    where_sql = ("AND " + " AND ".join(where_clauses)) if where_clauses else ""

    emb = await _voyage_embed_query(query)
    rows = []
    if emb is not None:
        # Vector path
        try:
            params_vec = params + [str(emb), top_k]
            rows = await pool.fetch(
                f"""
                SELECT c.clause_rid, c.section, c.heading, c.page,
                       c.text AS verbatim,
                       1 - (c.embedding <=> ${len(params)+1}::vector) AS similarity
                  FROM contracts.clauses c
                 WHERE c.embedding IS NOT NULL
                   {where_sql}
                 ORDER BY c.embedding <=> ${len(params)+1}::vector
                 LIMIT ${len(params)+2}
                """,
                *params_vec,
            )
        except Exception as exc:
            log.info("vector search failed, falling back to FTS: %s", exc)
            rows = []

    if not rows:
        # FTS path
        params_fts = params + [query, top_k]
        rows = await pool.fetch(
            f"""
            SELECT c.clause_rid, c.section, c.heading, c.page,
                   c.text AS verbatim,
                   ts_rank_cd(c.text_tsv, plainto_tsquery('english', ${len(params)+1}))
                       AS similarity
              FROM contracts.clauses c
             WHERE c.text_tsv @@ plainto_tsquery('english', ${len(params)+1})
               {where_sql}
             ORDER BY similarity DESC
             LIMIT ${len(params)+2}
            """,
            *params_fts,
        )

    out = []
    for r in rows:
        body = r["verbatim"] or ""
        out.append({
            "clause_rid": r["clause_rid"],
            "section": r["section"],
            "heading": r["heading"],
            "page": r["page"],
            "verbatim": body[:600],
            "similarity": float(r["similarity"]) if r["similarity"] is not None else None,
        })
    return out
