"""
app/ingestion/embeddings.py — OpenAI ``text-embedding-3-small`` wrapper.

1536-dim output, matches the ``documents.embedding vector(1536)`` column
in ``app/migrations/0001_intelligence_schema.sql``.

Two use modes:

  - :func:`embed_text` — one-shot call used by workers when ``embed_inline``
    is True.
  - :func:`embed_batch` — batch-async, designed for a nightly pass over
    unembedded documents. Batches up to 100 texts per call, which is
    OpenAI's limit for this model.

All calls degrade to ``None`` if ``OPENAI_API_KEY`` isn't set; workers must
tolerate None and not fail the whole run.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

log = logging.getLogger("princeps.ingestion.embeddings")

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
_MAX_BATCH = 100

_client: Any = None  # httpx-only fallback if the openai SDK isn't present


def _get_client():
    """Return an OpenAI AsyncClient, or None if the SDK / key isn't available."""
    global _client
    if _client is not None:
        return _client

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        log.info("OPENAI_API_KEY not set — embeddings disabled (nightly job will no-op)")
        return None

    try:
        from openai import AsyncOpenAI
    except Exception as e:
        log.warning("openai SDK not importable — embeddings disabled: %s", e)
        return None

    _client = AsyncOpenAI(api_key=key)
    return _client


async def embed_text(text: str) -> list[float] | None:
    """Return a single 1536-dim embedding for ``text`` or ``None`` on failure."""
    if not text or not text.strip():
        return None
    client = _get_client()
    if client is None:
        return None
    try:
        resp = await client.embeddings.create(model=EMBED_MODEL, input=text)
        vec = resp.data[0].embedding
        if len(vec) != EMBED_DIM:
            log.warning("Unexpected embedding dim %d", len(vec))
        return list(vec)
    except Exception as e:
        log.warning("embed_text failed: %s", e)
        return None


async def embed_batch(texts: list[str]) -> list[list[float] | None]:
    """Return a list of embeddings for ``texts``, in order."""
    if not texts:
        return []
    client = _get_client()
    if client is None:
        return [None] * len(texts)

    out: list[list[float] | None] = []
    for i in range(0, len(texts), _MAX_BATCH):
        chunk = [t[:8000] if t else "" for t in texts[i:i + _MAX_BATCH]]
        try:
            resp = await client.embeddings.create(model=EMBED_MODEL, input=chunk)
            # openai returns .data sorted by `index` field
            by_idx = {d.index: d.embedding for d in resp.data}
            for j in range(len(chunk)):
                vec = by_idx.get(j)
                out.append(list(vec) if vec else None)
        except Exception as e:
            log.warning("embed_batch chunk failed: %s", e)
            out.extend([None] * len(chunk))
        # Gentle pacing between chunks
        await asyncio.sleep(0.1)
    return out


# ── Nightly cache job ────────────────────────────────────────────────────────

async def embed_missing_documents(pool, *, limit: int = 500) -> int:
    """
    Populate ``documents.embedding`` for rows that currently have none.

    Intended to be scheduled nightly in :mod:`app.ingestion.scheduler`.
    Bounded by ``limit`` per run to keep cost predictable.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT doc_id, title, body_text
              FROM documents
             WHERE embedding IS NULL
             ORDER BY published_at DESC NULLS LAST
             LIMIT $1
            """,
            limit,
        )
        if not rows:
            return 0

        texts = [
            (r["title"] or "") + "\n\n" + (r["body_text"] or "")
            for r in rows
        ]
        vectors = await embed_batch(texts)

        written = 0
        for r, vec in zip(rows, vectors, strict=True):
            if not vec:
                continue
            try:
                await conn.execute(
                    "UPDATE documents SET embedding = $2 WHERE doc_id = $1",
                    r["doc_id"], vec,
                )
                written += 1
            except Exception as e:
                log.warning("embed update failed for %s: %s", r["doc_id"], e)
        return written
