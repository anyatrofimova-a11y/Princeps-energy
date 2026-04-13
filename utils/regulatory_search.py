"""Regulatory Intelligence & Document Search — full-text search with pgvector upgrade path."""

from __future__ import annotations
import logging
from typing import Any
from datetime import date

import httpx

log = logging.getLogger(__name__)


async def setup_regulatory_schema(conn) -> None:
    """Create regulatory docs table with full-text search."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS regulatory_docs (
            id SERIAL PRIMARY KEY,
            url TEXT,
            source TEXT,
            doc_type TEXT,
            title TEXT,
            doc_date DATE,
            chunk_text TEXT,
            chunk_index INT,
            tsv tsvector,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS reg_docs_tsv_idx ON regulatory_docs USING gin(tsv);
        CREATE INDEX IF NOT EXISTS reg_docs_source_idx ON regulatory_docs(source);
    """)


async def ingest_document(conn, url: str, source: str, doc_type: str, title: str = None) -> dict[str, Any]:
    """Fetch and chunk a document for search indexing."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(url)
            text = r.text
    except Exception as e:
        return {"error": f"Failed to fetch: {e}", "chunks_stored": 0}

    # Simple chunking: split by paragraphs, ~500 chars each
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
    chunks = []
    current = ""
    for p in paragraphs:
        if len(current) + len(p) > 500:
            if current:
                chunks.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        chunks.append(current)

    stored = 0
    for i, chunk in enumerate(chunks[:200]):  # Max 200 chunks per doc
        await conn.execute("""
            INSERT INTO regulatory_docs (url, source, doc_type, title, doc_date, chunk_text, chunk_index, tsv)
            VALUES ($1, $2, $3, $4, $5, $6, $7, to_tsvector('english', $6))
        """, url, source, doc_type, title or url, date.today(), chunk, i)
        stored += 1

    return {"url": url, "source": source, "doc_type": doc_type, "chunks_stored": stored, "title": title}


async def search_regulatory(conn, query: str, limit: int = 10, source: str = None, doc_type: str = None) -> list[dict]:
    """Full-text search across regulatory documents."""
    conditions = ["tsv @@ plainto_tsquery('english', $1)"]
    params = [query]
    idx = 2

    if source:
        conditions.append(f"source = ${idx}")
        params.append(source)
        idx += 1
    if doc_type:
        conditions.append(f"doc_type = ${idx}")
        params.append(doc_type)
        idx += 1

    where = " AND ".join(conditions)
    params.append(limit)

    rows = await conn.fetch(f"""
        SELECT id, url, source, doc_type, title, doc_date, chunk_text,
               ts_rank(tsv, plainto_tsquery('english', $1)) AS relevance
        FROM regulatory_docs
        WHERE {where}
        ORDER BY relevance DESC
        LIMIT ${idx}
    """, *params)

    return [
        {
            "id": r["id"], "url": r["url"], "source": r["source"],
            "doc_type": r["doc_type"], "title": r["title"],
            "date": str(r["doc_date"]) if r["doc_date"] else None,
            "chunk_text": r["chunk_text"][:500],
            "relevance": round(float(r["relevance"]), 4),
        }
        for r in rows
    ]


async def rag_answer(conn, query: str, anthropic_client) -> dict[str, Any]:
    """RAG: search + synthesize answer with Claude."""
    results = await search_regulatory(conn, query, limit=5)

    if not results:
        return {"answer": "No relevant regulatory documents found.", "sources": [], "confidence": "low"}

    context = "\n\n---\n\n".join(
        f"[{r['source']} — {r['title']}]\n{r['chunk_text']}" for r in results
    )

    msg = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"Based on the following UK regulatory documents, answer this question concisely:\n\nQuestion: {query}\n\nDocuments:\n{context}\n\nAnswer with specific references to the source documents.",
        }],
    )

    return {
        "answer": msg.content[0].text,
        "sources": [{"url": r["url"], "title": r["title"], "excerpt": r["chunk_text"][:200]} for r in results],
        "confidence": "high" if len(results) >= 3 else "medium" if results else "low",
    }
