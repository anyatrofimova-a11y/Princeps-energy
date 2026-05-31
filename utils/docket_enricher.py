"""Docket enricher — Halcyon-grade per-docket detail.

Pipeline per docket:
  1. Resolve canonical source URL (mapped registry first, then docket
     fields, then a constrained web search).
  2. Fetch the page with httpx (real UA, redirect-follow).
  3. Strip to readable text (trafilatura → fallback to BeautifulSoup).
  4. Hand the text to Claude with a structured-output prompt that
     extracts: summary, key_paragraphs (with anchor + quote), stakeholders,
     deadlines, related_dockets, expert_take, confidence + bounds.
  5. Persist to ``docket_enrichments`` keyed on docket_id.

Public surface:
    ``enrich_docket(pool, docket_id, force=False) -> dict``
    ``enrich_all_open_dockets(pool, limit=20) -> dict``
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import asyncpg
import httpx

log = logging.getLogger(__name__)

# Canonical source registry — title fragments → authoritative URL.
# Keys are matched case-insensitively as substrings of the docket title.
SOURCE_REGISTRY: dict[str, tuple[str, str]] = {
    "REMA Phase 2": (
        "Ofgem",
        "https://www.ofgem.gov.uk/publications/review-electricity-market-arrangements-rema-phase-2-decision",
    ),
    "Ofgem Data Centre": (
        "Ofgem",
        "https://www.ofgem.gov.uk/publications/data-centre-connections-policy-review-consultation",
    ),
    "NPPF": (
        "DLUHC",
        "https://www.gov.uk/government/publications/national-planning-policy-framework--2",
    ),
    "RIIO-ED3": (
        "Ofgem",
        "https://www.ofgem.gov.uk/publications/riio-ed3-sector-specific-methodology-decision",
    ),
    "waste-heat reuse": (
        "DESNZ",
        "https://www.gov.uk/government/consultations/data-centre-waste-heat-reuse",
    ),
    "Welsh Government Energy": (
        "Welsh Government",
        "https://www.gov.wales/future-wales-net-zero-2026-update",
    ),
    "G99": (
        "ENA",
        "https://www.energynetworks.org/industry-hub/resource-library/engineering-recommendation-g99-issue-2",
    ),
    "G98": (
        "ENA",
        "https://www.energynetworks.org/industry-hub/resource-library/engineering-recommendation-g98-issue-1",
    ),
    "AR7": (
        "DESNZ",
        "https://www.gov.uk/government/publications/contracts-for-difference-cfd-allocation-round-7-ar7",
    ),
    "EN-3": (
        "DESNZ",
        "https://www.gov.uk/government/publications/national-policy-statements-for-energy-infrastructure",
    ),
    "BNG": (
        "Defra",
        "https://www.gov.uk/government/publications/biodiversity-net-gain",
    ),
    "Capacity Market": (
        "NESO",
        "https://www.neso.energy/industry-information/balancing-services/capacity-market",
    ),
    "Strategic Spatial Energy Plan": (
        "NESO",
        "https://www.neso.energy/document/350056/download",
    ),
    "FES": (
        "NESO",
        "https://www.neso.energy/publications/future-energy-scenarios-fes",
    ),
}


def _resolve_source_url(title: str) -> tuple[str | None, str | None]:
    if not title:
        return None, None
    t_low = title.lower()
    for key, (authority, url) in SOURCE_REGISTRY.items():
        if key.lower() in t_low:
            return authority, url
    return None, None


async def _fetch_readable(url: str) -> tuple[int, str, str]:
    """Fetch the URL, return (status, raw_html, readable_text)."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.7",
    }
    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, headers=headers,
    ) as client:
        r = await client.get(url)
    raw = r.text or ""
    readable = _to_readable(raw)
    return r.status_code, raw, readable


def _to_readable(html: str) -> str:
    """trafilatura → fallback to BeautifulSoup → fallback to raw text."""
    if not html:
        return ""
    try:
        import trafilatura
        extracted = trafilatura.extract(
            html, include_comments=False, include_tables=True,
            favor_recall=True, no_fallback=False,
        )
        if extracted and len(extracted) > 200:
            return extracted
    except Exception:
        pass
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text("\n", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)


_ENRICHER_PROMPT = """You are an expert UK energy regulatory analyst extracting structured intelligence from a primary consultation / decision document.

For the document below, return JSON with the following shape (no prose, no markdown):

{
  "summary": "<2-3 paragraph executive summary, suitable for a UK developer or investor>",
  "key_paragraphs": [
    {"anchor": "<§n.n.n or section label>", "page": <int or null>, "quote": "<verbatim ≤320 chars>"}
  ],
  "stakeholders": [
    {"name": "<organisation>", "role": "<applicant | consultee | responder | publisher | …>", "position": "<short stance>", "filing_url": "<url or null>"}
  ],
  "deadlines": [
    {"name": "<event>", "date_iso": "<YYYY-MM-DD>", "description": "<one-line>", "source_anchor": "<§n>"}
  ],
  "related_dockets": [
    {"title": "<related case>", "relation": "<supersedes | informs | depends_on | overlaps>"}
  ],
  "expert_take": "<3-5 sentences: what this means for a UK energy developer in 2026, with reasoning>",
  "confidence": "<low | med | high>",
  "bounds": ["<what you couldn't determine, e.g. 'technical annex Z not fetched'>", "..."]
}

Rules:
- Always cite paragraph anchors when quoting (e.g. "§5.3.2" or "Annex B paragraph 14").
- Be cautious: if a field isn't in the document, return [] or null — don't fabricate.
- For "expert_take", anchor recommendations to specific clauses (cite anchors inline).
- ≤8 key_paragraphs, ≤6 stakeholders, ≤6 deadlines, ≤4 related_dockets.

DOCUMENT:
"""


async def _claude_extract(text: str, title: str, authority: str | None) -> dict[str, Any]:
    """Call Claude with the readable text + structured-output prompt."""
    api_key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "CLAUDE_API_KEY not configured"}
    # Trim aggressively — Claude prompt budget + cost control
    body = text[:18000]
    prompt = (
        f"DOCKET TITLE: {title}\nAUTHORITY: {authority or 'unknown'}\n\n"
        f"{_ENRICHER_PROMPT}{body}"
    )
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-opus-4-7",
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
    r.raise_for_status()
    out_text = r.json()["content"][0]["text"].strip()
    if out_text.startswith("```"):
        out_text = out_text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(out_text)
    except json.JSONDecodeError as exc:
        return {"error": f"json parse failed: {exc}", "raw": out_text[:600]}


async def enrich_docket(
    pool: asyncpg.Pool,
    docket_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Resolve canonical source, fetch, extract structured fields, persist."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT docket_id, title, source_url, canonical_authority "
            "FROM dockets WHERE docket_id::text = $1",
            str(docket_id),
        )
        if not row:
            return {"error": f"docket {docket_id} not found"}

        if not force:
            recent = await conn.fetchval(
                "SELECT enrichment_id FROM docket_enrichments "
                "WHERE docket_id = $1 AND fetched_at > now() - interval '24 hours' "
                "ORDER BY fetched_at DESC LIMIT 1",
                row["docket_id"],
            )
            if recent:
                return {"skipped": True, "reason": "fresh enrichment exists",
                        "enrichment_id": str(recent)}

    title = row["title"]
    authority, url = (row["canonical_authority"], row["source_url"])
    if not url:
        authority, url = _resolve_source_url(title)
    if not url:
        return {"error": f"no canonical source URL for '{title}' — add to SOURCE_REGISTRY"}

    try:
        status, raw, readable = await _fetch_readable(url)
    except Exception as exc:
        return {"error": f"fetch failed: {type(exc).__name__}: {exc}", "url": url}

    if status >= 400 or len(readable) < 300:
        return {"error": f"fetch returned HTTP {status} with {len(readable)} readable chars",
                "url": url}

    extracted = await _claude_extract(readable, title, authority)
    if "error" in extracted:
        return {"error": extracted["error"], "url": url}

    async with pool.acquire() as conn:
        if not row["source_url"]:
            await conn.execute(
                "UPDATE dockets SET source_url = $1, canonical_authority = $2 "
                "WHERE docket_id = $3",
                url, authority, row["docket_id"],
            )
        rid = await conn.fetchval(
            """
            INSERT INTO docket_enrichments
                (docket_id, source_url, http_status, fetch_bytes, summary,
                 key_paragraphs, stakeholders, deadlines, related_dockets,
                 expert_take, confidence, bounds, raw_excerpt)
            VALUES ($1, $2, $3, $4, $5,
                    $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb,
                    $10, $11, $12::jsonb, $13)
            RETURNING enrichment_id
            """,
            row["docket_id"], url, status, len(raw),
            extracted.get("summary"),
            json.dumps(extracted.get("key_paragraphs", [])),
            json.dumps(extracted.get("stakeholders", [])),
            json.dumps(extracted.get("deadlines", [])),
            json.dumps(extracted.get("related_dockets", [])),
            extracted.get("expert_take"),
            extracted.get("confidence", "med"),
            json.dumps(extracted.get("bounds", [])),
            readable[:8000],
        )
    return {
        "enrichment_id": str(rid),
        "source_url": url,
        "authority": authority,
        "http_status": status,
        "fetch_bytes": len(raw),
        "summary": extracted.get("summary"),
        "key_paragraphs": extracted.get("key_paragraphs", []),
        "stakeholders": extracted.get("stakeholders", []),
        "deadlines": extracted.get("deadlines", []),
        "related_dockets": extracted.get("related_dockets", []),
        "expert_take": extracted.get("expert_take"),
        "confidence": extracted.get("confidence"),
        "bounds": extracted.get("bounds", []),
    }


async def enrich_all_open_dockets(
    pool: asyncpg.Pool, limit: int = 20,
) -> dict[str, Any]:
    """Bulk pass — enrich up to N open dockets that have no fresh enrichment."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT docket_id::text AS docket_id
              FROM dockets d
             WHERE (status IS NULL OR status NOT IN ('closed','withdrawn'))
               AND NOT EXISTS (
                 SELECT 1 FROM docket_enrichments e
                  WHERE e.docket_id = d.docket_id
                    AND e.fetched_at > now() - interval '24 hours'
               )
             ORDER BY updated_at DESC NULLS LAST
             LIMIT $1
            """,
            limit,
        )
    enriched = 0
    failed = 0
    skipped = 0
    details = []
    for r in rows:
        out = await enrich_docket(pool, r["docket_id"])
        if out.get("error"):
            failed += 1
        elif out.get("skipped"):
            skipped += 1
        else:
            enriched += 1
        details.append({"docket_id": r["docket_id"], **out})
    return {"scanned": len(rows), "enriched": enriched,
            "failed": failed, "skipped": skipped, "details": details}
