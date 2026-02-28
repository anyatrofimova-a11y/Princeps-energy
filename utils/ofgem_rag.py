"""
Ofgem RAG — Regulatory document ingestion, chunking, embedding, and retrieval.

Sources: Ofgem website content, DESNZ consultations JSON feed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import time
from typing import Any
from uuid import uuid4

import asyncpg
import httpx

log = logging.getLogger("princeps.ofgem_rag")

_TIMEOUT = 30
_EMBED_PYTHON = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), ".venv-geeflow", "bin", "python"
)
_EMBED_SCRIPT = os.path.join(os.path.dirname(__file__), "rag_embed_runner.py")

# Ofgem publications API (HTML scraping — simplified)
OFGEM_PUBLICATIONS_URL = "https://www.ofgem.gov.uk/publications"
# DESNZ (Department for Energy Security & Net Zero) consultations JSON feed
DESNZ_CONSULTATIONS_URL = (
    "https://www.gov.uk/api/search.json"
    "?filter_organisations=department-for-energy-security-and-net-zero"
    "&filter_content_purpose_supergroup=policy_and_engagement"
    "&count=50&order=-public_timestamp"
)


# ── Table setup ──────────────────────────────────────────────────────────

CREATE_DOCS_SQL = """
CREATE TABLE IF NOT EXISTS rag_documents (
    doc_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source             TEXT,
    title              TEXT,
    url                TEXT,
    published_date     DATE,
    doc_type           TEXT,
    body_text          TEXT,
    page_count         INTEGER,
    file_hash          TEXT,
    metadata           JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_docs_hash ON rag_documents (file_hash);
"""

CREATE_CHUNKS_SQL = """
CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id             UUID REFERENCES rag_documents(doc_id) ON DELETE CASCADE,
    chunk_index        INTEGER NOT NULL,
    content            TEXT NOT NULL,
    token_count        INTEGER,
    metadata           JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc ON rag_chunks (doc_id);
"""

# Added separately — requires pgvector extension
ADD_EMBEDDING_COL_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='rag_chunks' AND column_name='embedding') THEN
        ALTER TABLE rag_chunks ADD COLUMN embedding vector(384);
    END IF;
END $$;
"""


async def setup_rag_tables(conn: asyncpg.Connection):
    """Create rag_documents and rag_chunks tables."""
    for sql in [CREATE_DOCS_SQL, CREATE_CHUNKS_SQL]:
        for stmt in sql.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(stmt)
    # Try to add embedding column (requires pgvector)
    try:
        await conn.execute(ADD_EMBEDDING_COL_SQL)
    except Exception as e:
        log.warning("pgvector not ready for rag_chunks embedding column: %s", e)
    log.info("rag_documents + rag_chunks tables ensured")


# ── Chunking ─────────────────────────────────────────────────────────────

def chunk_document(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    """Split text into overlapping chunks by token-approximation (words)."""
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end >= len(words):
            break
        start += chunk_size - overlap

    return chunks


# ── Embedding ────────────────────────────────────────────────────────────

async def embed_chunks(chunks: list[str]) -> list[list[float]]:
    """Embed text chunks via subprocess call to rag_embed_runner.py."""
    if not chunks:
        return []

    python_path = _EMBED_PYTHON if os.path.isfile(_EMBED_PYTHON) else "python3"

    try:
        proc = subprocess.run(
            [python_path, _EMBED_SCRIPT],
            input=json.dumps({"texts": chunks}),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            log.warning("Embedding subprocess failed: %s", proc.stderr[:500])
            return [[0.0] * 384 for _ in chunks]

        return json.loads(proc.stdout)
    except Exception as e:
        log.warning("Embedding failed: %s — returning zero vectors", e)
        return [[0.0] * 384 for _ in chunks]


# ── Ingestion: Ofgem ─────────────────────────────────────────────────────

async def ingest_ofgem_documents(conn_or_pool) -> dict:
    """Fetch Ofgem publications and DESNZ consultations, chunk, embed, store."""
    t0 = time.time()

    if hasattr(conn_or_pool, "acquire"):
        conn = await conn_or_pool.acquire()
        release = True
    else:
        conn = conn_or_pool
        release = False

    try:
        docs_added = 0
        chunks_added = 0

        # ─ DESNZ consultations via gov.uk search API ─
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
                r = await client.get(DESNZ_CONSULTATIONS_URL)
                r.raise_for_status()
                results = r.json().get("results", [])

            for item in results:
                title = item.get("title", "").strip()
                url = "https://www.gov.uk" + item.get("link", "")
                desc = item.get("description", "")
                pub_date = item.get("public_timestamp", "")[:10] or None

                body = f"{title}\n\n{desc}"
                file_hash = hashlib.sha256(body.encode()).hexdigest()

                # Dedup by hash
                existing = await conn.fetchval(
                    "SELECT doc_id FROM rag_documents WHERE file_hash = $1", file_hash
                )
                if existing:
                    continue

                doc_id = uuid4()
                pub_date_val = None
                if pub_date:
                    try:
                        import datetime
                        pub_date_val = datetime.date.fromisoformat(pub_date)
                    except ValueError:
                        pass

                await conn.execute("""
                    INSERT INTO rag_documents (doc_id, source, title, url, published_date,
                                              doc_type, body_text, file_hash)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                    doc_id, "desnz", title, url, pub_date_val,
                    item.get("content_purpose_supergroup", "consultation"),
                    body, file_hash,
                )
                docs_added += 1

                # Chunk and embed
                chunks = chunk_document(body)
                if chunks:
                    embeddings = await embed_chunks(chunks)
                    for i, (chunk_text, emb) in enumerate(zip(chunks, embeddings)):
                        await conn.execute("""
                            INSERT INTO rag_chunks (doc_id, chunk_index, content, token_count, embedding)
                            VALUES ($1, $2, $3, $4, $5)
                        """,
                            doc_id, i, chunk_text, len(chunk_text.split()), str(emb),
                        )
                        chunks_added += 1

        except Exception as e:
            log.warning("DESNZ ingestion failed: %s", e)

        # ─ Ofgem website (simplified — scrape publication listing) ─
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
                r = await client.get(OFGEM_PUBLICATIONS_URL)
                r.raise_for_status()

            # Extract publication links and titles from HTML
            links = re.findall(
                r'<a[^>]*href="(/publications/[^"]+)"[^>]*>(.*?)</a>',
                r.text, re.DOTALL,
            )
            for href, title_html in links[:30]:
                title = re.sub(r"<[^>]+>", "", title_html).strip()
                url = f"https://www.ofgem.gov.uk{href}"
                body = title  # Minimal — full content would need PDF extraction
                file_hash = hashlib.sha256(url.encode()).hexdigest()

                existing = await conn.fetchval(
                    "SELECT doc_id FROM rag_documents WHERE file_hash = $1", file_hash
                )
                if existing:
                    continue

                doc_id = uuid4()
                await conn.execute("""
                    INSERT INTO rag_documents (doc_id, source, title, url, doc_type, body_text, file_hash)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                    doc_id, "ofgem", title, url, "publication", body, file_hash,
                )
                docs_added += 1

        except Exception as e:
            log.warning("Ofgem scraping failed: %s", e)

        elapsed = round(time.time() - t0, 1)
        log.info("RAG ingestion complete: %d docs, %d chunks in %.1fs", docs_added, chunks_added, elapsed)
        return {"docs_added": docs_added, "chunks_added": chunks_added, "elapsed_s": elapsed}

    except Exception as e:
        log.error("RAG ingestion failed: %s", e)
        return {"error": str(e)}
    finally:
        if release:
            await conn_or_pool.release(conn)


# ── Retrieval ────────────────────────────────────────────────────────────

async def rag_query(
    conn: asyncpg.Connection,
    query: str,
    *,
    top_k: int = 5,
    source_filter: str | None = None,
    doc_type_filter: str | None = None,
) -> list[dict]:
    """Embed query and retrieve top-k matching chunks via pgvector cosine similarity."""
    embeddings = await embed_chunks([query])
    if not embeddings or not embeddings[0]:
        return []

    query_emb = embeddings[0]

    conditions = []
    params: list[Any] = [str(query_emb), top_k]
    idx = 3

    if source_filter:
        conditions.append(f"d.source = ${idx}")
        params.append(source_filter)
        idx += 1
    if doc_type_filter:
        conditions.append(f"d.doc_type = ${idx}")
        params.append(doc_type_filter)
        idx += 1

    extra_where = (" AND " + " AND ".join(conditions)) if conditions else ""

    try:
        rows = await conn.fetch(f"""
            SELECT c.chunk_id, c.content, c.chunk_index, c.token_count,
                   d.doc_id, d.title, d.url, d.source, d.doc_type, d.published_date,
                   c.embedding <=> $1::vector AS distance
            FROM rag_chunks c
            JOIN rag_documents d ON c.doc_id = d.doc_id
            WHERE c.embedding IS NOT NULL {extra_where}
            ORDER BY c.embedding <=> $1::vector
            LIMIT $2
        """, *params)
    except Exception as e:
        log.warning("RAG vector query failed: %s — falling back to text search", e)
        # Fallback: simple text search
        rows = await conn.fetch("""
            SELECT c.chunk_id, c.content, c.chunk_index, c.token_count,
                   d.doc_id, d.title, d.url, d.source, d.doc_type, d.published_date,
                   0.0 AS distance
            FROM rag_chunks c
            JOIN rag_documents d ON c.doc_id = d.doc_id
            WHERE c.content ILIKE $1
            LIMIT $2
        """, f"%{query}%", top_k)

    return [
        {
            "chunk_id": str(r["chunk_id"]),
            "content": r["content"],
            "chunk_index": r["chunk_index"],
            "doc_title": r["title"],
            "doc_url": r["url"],
            "source": r["source"],
            "doc_type": r["doc_type"],
            "published_date": r["published_date"].isoformat() if r["published_date"] else None,
            "distance": round(float(r["distance"]), 4),
        }
        for r in rows
    ]


async def rag_answer(
    conn: asyncpg.Connection,
    client,
    model: str,
    query: str,
    *,
    top_k: int = 5,
    source_filter: str | None = None,
) -> dict:
    """Full RAG pipeline: retrieve chunks then ask Claude to answer with citations."""
    chunks = await rag_query(conn, query, top_k=top_k, source_filter=source_filter)

    if not chunks:
        return {
            "answer": "No relevant regulatory documents found. Please try a different query or ingest documents first.",
            "sources": [],
            "query": query,
        }

    # Build context for Claude
    context_parts = []
    for i, c in enumerate(chunks):
        context_parts.append(
            f"[Source {i+1}] {c['doc_title']} ({c['source']}, {c.get('published_date', 'undated')})\n"
            f"URL: {c['doc_url']}\n"
            f"{c['content']}\n"
        )

    context_text = "\n---\n".join(context_parts)

    system_prompt = (
        "You are a UK energy regulatory intelligence analyst. "
        "Answer the user's question using ONLY the provided source documents. "
        "Cite sources using [Source N] notation. "
        "If the sources don't contain enough information, say so clearly."
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Question: {query}\n\n"
                        f"Source documents:\n{context_text}\n\n"
                        f"Please answer the question with citations."
                    ),
                }
            ],
        )
        answer = response.content[0].text
    except Exception as e:
        log.warning("Claude RAG answer failed: %s", e)
        answer = f"Error generating answer: {e}"

    return {
        "answer": answer,
        "sources": chunks,
        "query": query,
    }
