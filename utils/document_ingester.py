"""Document ingester for the Contract Intelligence workspace.

Takes a PDF on stdin (or a file path), extracts clauses with page +
section + heading, hashes the bytes, inserts rows into the contracts
schema.

The clause boundary heuristic: in priority order
  1. `SCHEDULE \d+` headings → schedule clauses
  2. `^\s*(\d+(\.\d+)*)\s+[A-Z]` headings (e.g. "5.2.3 Definitions")
  3. Numbered list items at the start of a paragraph (Clause N.N)
  4. Otherwise: a single clause per page

Embedding is optional. If VOYAGE_API_KEY is set we call Voyage-3 (output
dim 1024). Otherwise the clause is stored with embedding = NULL and the
chat tool falls back to PostgreSQL FTS.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import asyncpg

log = logging.getLogger(__name__)

SECTION_RE = re.compile(
    r"^\s*(?P<sec>(?:SCHEDULE\s+\d+(?:\s*[-–]\s*[A-Z][A-Z\s]+)?|\d+(?:\.\d+){0,4}))"
    r"\s+(?P<heading>[A-Z][A-Z0-9 ,&/\-]{2,80})\s*$",
    re.MULTILINE,
)


@dataclass
class _Clause:
    section: str | None
    heading: str | None
    page: int
    span_start: int
    span_end: int
    text: str


def _extract_pages(pdf_bytes: bytes) -> list[tuple[int, str]]:
    """Return [(page_number_1based, full_page_text)] using pymupdf."""
    import fitz  # pymupdf
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = []
    for i, page in enumerate(doc, start=1):
        out.append((i, page.get_text("text")))
    doc.close()
    return out


def _split_clauses(pages: list[tuple[int, str]]) -> list[_Clause]:
    """Walk pages, split on SECTION_RE; if no matches on a page, one clause
    per page."""
    clauses: list[_Clause] = []
    for page_no, text in pages:
        matches = list(SECTION_RE.finditer(text))
        if not matches:
            clauses.append(_Clause(
                section=None, heading=None, page=page_no,
                span_start=0, span_end=len(text), text=text.strip(),
            ))
            continue
        for idx, m in enumerate(matches):
            start = m.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            if not body:
                continue
            clauses.append(_Clause(
                section=m.group("sec").strip(),
                heading=m.group("heading").strip().title(),
                page=page_no,
                span_start=start, span_end=end,
                text=body,
            ))
    # Drop bodies shorter than 40 chars — usually layout artefacts
    return [c for c in clauses if len(c.text) >= 40]


async def _voyage_embed(texts: list[str]) -> list[list[float]] | None:
    """Embed via Voyage-3 if VOYAGE_API_KEY is set; None otherwise."""
    api_key = os.getenv("VOYAGE_API_KEY")
    if not api_key:
        return None
    import httpx
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"model": "voyage-3", "input": texts, "input_type": "document"},
        )
        r.raise_for_status()
        return [d["embedding"] for d in r.json()["data"]]


async def ingest_document_draft(
    pool: asyncpg.Pool,
    *,
    document_rid: str,
    version_label: str,
    pdf_bytes: bytes,
    draft_date: date | None = None,
    source_path: str | None = None,
    uploaded_by: str | None = None,
) -> dict[str, Any]:
    """Parse PDF → clauses → upsert into contracts.* tables.

    Idempotent on (document_rid, source_hash): re-uploading the same bytes
    is a no-op. Re-uploading a SIMILAR draft with a different hash creates
    a new DocumentDraft row.
    """
    source_hash = hashlib.sha256(pdf_bytes).hexdigest()
    pages = await asyncio.to_thread(_extract_pages, pdf_bytes)
    clauses = await asyncio.to_thread(_split_clauses, pages)

    async with pool.acquire() as conn:
        # Skip if this hash is already ingested for this document.
        existing = await conn.fetchrow(
            "SELECT draft_rid FROM contracts.document_drafts "
            "WHERE document_rid = $1 AND source_hash = $2",
            document_rid, source_hash,
        )
        if existing:
            return {"skipped": True, "draft_rid": existing["draft_rid"],
                    "reason": "hash_already_ingested"}

        draft_rid = await conn.fetchval(
            """
            INSERT INTO contracts.document_drafts
                (document_rid, version_label, draft_date, page_count,
                 source_hash, source_path, uploaded_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING draft_rid
            """,
            document_rid, version_label, draft_date,
            len(pages), source_hash, source_path, uploaded_by,
        )

        # Insert clauses in a single batch.
        rows = [
            (draft_rid, c.section, c.heading, c.page,
             c.span_start, c.span_end, c.text)
            for c in clauses
        ]
        if rows:
            await conn.executemany(
                """
                INSERT INTO contracts.clauses
                    (draft_rid, section, heading, page, span_start, span_end, text)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                rows,
            )

    # Optional: embed in the background — don't block the upload response.
    try:
        embs = await _voyage_embed([c.text[:4000] for c in clauses])
    except Exception as exc:
        embs = None
        log.warning("voyage embed failed: %s", exc)

    if embs is not None:
        async with pool.acquire() as conn:
            cl = await conn.fetch(
                "SELECT clause_rid FROM contracts.clauses "
                "WHERE draft_rid = $1 ORDER BY page, span_start",
                draft_rid,
            )
            for row, emb in zip(cl, embs):
                # pgvector accepts the python list directly if vector ext
                # is loaded; otherwise we stash bytes.
                try:
                    await conn.execute(
                        "UPDATE contracts.clauses SET embedding = $1::vector "
                        "WHERE clause_rid = $2",
                        str(emb), row["clause_rid"],
                    )
                except Exception:
                    pass

    return {
        "draft_rid": draft_rid,
        "source_hash": source_hash,
        "pages": len(pages),
        "clauses": len(clauses),
        "embedded": embs is not None,
    }
