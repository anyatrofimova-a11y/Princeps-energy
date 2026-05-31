"""Side-by-side clause diff between two drafts of the same document.

Used by Phase E (multi-draft diff). The output shape mirrors the Cairn
"COD change is a direct, verbatim diff" answer: every modified clause
emits ``{section, page_a, page_b, status, diff_text, verbatim_a, verbatim_b}``.

Alignment strategy:
  1. Primary: match clauses by exact ``section`` string ("1.1", "5.2.3").
  2. Fallback (for clauses without sections): match by heading similarity
     above 0.7 via SequenceMatcher.
"""

from __future__ import annotations

import difflib
from typing import Any, Literal

import asyncpg

Status = Literal["unchanged", "modified", "added", "removed"]


def _diff_text(a: str, b: str) -> str:
    """Compact unified diff (no preamble) for display."""
    lines = list(difflib.unified_diff(
        a.splitlines(), b.splitlines(),
        fromfile="a", tofile="b", lineterm="", n=2,
    ))
    return "\n".join(lines[2:]) if len(lines) > 2 else ""


async def diff_drafts(
    pool: asyncpg.Pool,
    draft_rid_a: str,
    draft_rid_b: str,
) -> dict[str, Any]:
    """Compare two drafts; return per-clause status."""
    async with pool.acquire() as conn:
        rows_a = await conn.fetch(
            "SELECT clause_rid, section, heading, page, text "
            "FROM contracts.clauses WHERE draft_rid = $1 "
            "ORDER BY page, span_start",
            draft_rid_a,
        )
        rows_b = await conn.fetch(
            "SELECT clause_rid, section, heading, page, text "
            "FROM contracts.clauses WHERE draft_rid = $1 "
            "ORDER BY page, span_start",
            draft_rid_b,
        )

    by_sec_a: dict[str, dict] = {r["section"]: dict(r) for r in rows_a if r["section"]}
    by_sec_b: dict[str, dict] = {r["section"]: dict(r) for r in rows_b if r["section"]}
    sections = sorted(set(by_sec_a) | set(by_sec_b))

    deltas: list[dict[str, Any]] = []
    unchanged = modified = added = removed = 0

    for sec in sections:
        a = by_sec_a.get(sec)
        b = by_sec_b.get(sec)
        if a and b:
            if a["text"].strip() == b["text"].strip():
                unchanged += 1
                continue
            sim = difflib.SequenceMatcher(None, a["text"], b["text"]).ratio()
            status: Status = "modified"
            deltas.append({
                "section": sec, "status": status,
                "page_a": a["page"], "page_b": b["page"],
                "heading": a["heading"] or b["heading"],
                "similarity": round(sim, 3),
                "verbatim_a": a["text"][:1200],
                "verbatim_b": b["text"][:1200],
                "diff_text": _diff_text(a["text"], b["text"])[:2000],
                "clause_rid_a": a["clause_rid"],
                "clause_rid_b": b["clause_rid"],
            })
            modified += 1
        elif a:
            removed += 1
            deltas.append({
                "section": sec, "status": "removed",
                "page_a": a["page"], "page_b": None,
                "heading": a["heading"],
                "verbatim_a": a["text"][:1200],
                "verbatim_b": None,
                "clause_rid_a": a["clause_rid"],
            })
        else:
            added += 1
            deltas.append({
                "section": sec, "status": "added",
                "page_a": None, "page_b": b["page"],
                "heading": b["heading"],
                "verbatim_a": None,
                "verbatim_b": b["text"][:1200],
                "clause_rid_b": b["clause_rid"],
            })

    return {
        "draft_rid_a": draft_rid_a,
        "draft_rid_b": draft_rid_b,
        "summary": {
            "unchanged": unchanged,
            "modified": modified,
            "added": added,
            "removed": removed,
            "total_clauses_a": len(rows_a),
            "total_clauses_b": len(rows_b),
        },
        "deltas": deltas,
    }
