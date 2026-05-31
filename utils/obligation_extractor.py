"""Obligation extractor — Phase F.

For each clause in a draft, asks Claude for the structured obligation
fields (party, trigger, action, penalty, deadline). Returns nothing for
clauses that don't bear obligations.

Persisted to contracts.obligations and used by the watcher swarm to
diff obligations across drafts.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import asyncpg
import httpx

log = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-opus-4-7"  # current default; falls back via Anthropic alias

_EXTRACTOR_PROMPT = """You are extracting structured obligation records from energy-sector contract clauses (CTA, OEM, EPC, PPA, grid agreements).

For the clause below, return one of:

A) If the clause does NOT contain an enforceable obligation (e.g. it's a definition, recital, or boilerplate severability):
{"is_obligation": false}

B) If it contains one or more obligations, an array of:
{"is_obligation": true, "obligations": [
  {
    "party": "Owner | Contractor | Lender | Operator | Off-taker | Grid Operator",
    "trigger": "<short phrase: event or condition that activates the duty>",
    "action": "<what the obligor must do, terse>",
    "penalty": "<consequence on breach, or null>",
    "deadline_iso": "<ISO date or 'within N days/months of <trigger>' or null>"
  }
]}

Rules:
- Be precise about the party — if "Contractor shall" the party is Contractor, not Both.
- If a clause spawns multiple duties (e.g. notify AND remedy), emit each as a separate row.
- Do not fabricate deadlines or penalties — null if not stated.
- Respond with ONLY the JSON object. No prose, no markdown.

CLAUSE TEXT:
"""


async def _extract_one(clause_text: str, api_key: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 1500,
                "messages": [
                    {"role": "user", "content": _EXTRACTOR_PROMPT + clause_text[:6000]},
                ],
            },
        )
        r.raise_for_status()
        body = r.json()
        text = body["content"][0]["text"].strip()
        # Strip fenced ``json blocks if Claude added them
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        parsed = json.loads(text)
        if not parsed.get("is_obligation"):
            return []
        return parsed.get("obligations", [])


async def extract_obligations(
    pool: asyncpg.Pool,
    draft_rid: str,
    *,
    max_clauses: int = 250,
    only_unprocessed: bool = True,
) -> dict[str, Any]:
    """Walk clauses in the draft, extract obligations, persist rows."""
    api_key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "CLAUDE_API_KEY not set"}

    async with pool.acquire() as conn:
        if only_unprocessed:
            rows = await conn.fetch(
                """
                SELECT c.clause_rid, c.text
                  FROM contracts.clauses c
                 WHERE c.draft_rid = $1
                   AND NOT EXISTS (SELECT 1 FROM contracts.obligations o
                                    WHERE o.clause_rid = c.clause_rid)
                 ORDER BY c.page, c.span_start
                 LIMIT $2
                """,
                draft_rid, max_clauses,
            )
        else:
            rows = await conn.fetch(
                "SELECT clause_rid, text FROM contracts.clauses "
                "WHERE draft_rid = $1 ORDER BY page, span_start LIMIT $2",
                draft_rid, max_clauses,
            )

    inserted = 0
    skipped = 0
    failed = 0
    for row in rows:
        try:
            obs = await _extract_one(row["text"], api_key)
        except Exception as exc:
            log.warning("extract failed clause=%s: %s", row["clause_rid"], exc)
            failed += 1
            continue
        if not obs:
            skipped += 1
            continue
        async with pool.acquire() as conn:
            for o in obs:
                await conn.execute(
                    """
                    INSERT INTO contracts.obligations
                        (clause_rid, draft_rid, party, trigger, action,
                         penalty, deadline_iso)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    row["clause_rid"], draft_rid,
                    o.get("party"), o.get("trigger"), o.get("action"),
                    o.get("penalty"), o.get("deadline_iso"),
                )
                inserted += 1

    return {"draft_rid": draft_rid, "clauses_scanned": len(rows),
            "obligations_inserted": inserted, "skipped_non_obligation": skipped,
            "failed": failed}
