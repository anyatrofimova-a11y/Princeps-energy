"""
app/dockets/stakeholder_extractor.py — post-ingest NER for docket participants.

Called after a batch of ``documents`` land. For each doc we ask Claude to
extract:

- counsel / legal representatives ("on behalf of …")
- intervenor organisations
- authority signatures (decision letters / relreps from statutory bodies)
- applicants / co-applicants / SPVs

Matches are reconciled against:

- ``authorities`` (by name / acronym / slug)
- Companies House (by company number, if already populated)

and upserted into ``stakeholders``. Each submission (doc) is recorded in
``stakeholder_submissions`` with a ``position`` classification that uses
Claude Haiku (cheap, batched) for for/against/conditions/neutral.

The extractor is idempotent — rerunning a doc batch updates counts and
last_submission_at but does not duplicate rows (UNIQUE(docket_id, display_name)
on stakeholders and UNIQUE(stakeholder_id, doc_id) on submissions).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any
from uuid import UUID

import anthropic
import asyncpg

log = logging.getLogger("princeps.dockets.stakeholder_extractor")

MODEL_SONNET = os.environ.get("CLAUDE_DOCKET_MODEL",  "claude-sonnet-4-6")
MODEL_HAIKU  = os.environ.get("CLAUDE_POSITION_MODEL","claude-haiku-4-5-20251001")


_ON_BEHALF_RE = re.compile(r"on behalf of ([A-Z][^.\n,;]{2,80})", re.IGNORECASE)


# ── Claude prompts ─────────────────────────────────────────────────────

_NER_SYSTEM = """You are an entity extractor for UK energy proceedings.
Return strict JSON: a list of participants. For each participant:
- display_name (canonical casing; no trailing Ltd. unless on the document)
- role: one of applicant, co_applicant, spv, statutory_consultee, regulator,
  network_operator, lpa, parish_council, county_council, consumer_body,
  industry_body, objector, supporter, interested_party, government_agency,
  political, legal_rep, technical_reviewer, lender, neutral, intervenor,
  consultee
- is_authority_signature: true/false — true if this participant is the
  authority that SIGNED the document (EA, NE, LPA decision officer, etc.)
- on_behalf_of: if this is counsel/agent filing on behalf of someone else,
  the client name; otherwise null
- company_number: UK Companies House number if mentioned; otherwise null
Be conservative — do not invent parties. One entity per entry. De-duplicate."""


_NER_USER = """Document title: {title}
Source: {source}
Filing type: {filing_type}
---
{body}
---
Return JSON: {{"participants": [...]}}. Up to 15 entries."""


_POSITION_SYSTEM = """You are a one-shot classifier. Read a UK consultation
response and return exactly one of: for, against, conditions, neutral,
withdrawn. Output the single word only."""


# ── Public entry points ────────────────────────────────────────────────

async def extract_and_upsert_for_document(
    pool: asyncpg.Pool,
    claude: anthropic.AsyncAnthropic,
    doc_id: UUID,
) -> dict[str, Any]:
    """Run extraction for a single document. Returns a small summary
    useful for logs / background-task telemetry."""
    async with pool.acquire() as conn:
        doc = await conn.fetchrow(
            """SELECT doc_id, docket_id, title, body_text, filing_type,
                      source, published_at, ingested_at
               FROM documents WHERE doc_id = $1""",
            doc_id,
        )
    if not doc or not doc["docket_id"]:
        return {"doc_id": str(doc_id), "skipped": True, "reason": "no docket"}

    body = (doc["body_text"] or "")[:6000]
    if len(body) < 50:
        return {"doc_id": str(doc_id), "skipped": True, "reason": "no body"}

    # 1. NER pass with Sonnet.
    try:
        resp = await claude.messages.create(
            model=MODEL_SONNET,
            max_tokens=1500,
            system=_NER_SYSTEM,
            messages=[{"role": "user", "content": _NER_USER.format(
                title=doc["title"] or "(untitled)",
                source=doc["source"] or "",
                filing_type=doc["filing_type"] or "",
                body=body,
            )}],
        )
        raw = "".join(
            getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"
        )
    except Exception as exc:
        log.warning("NER pass failed for doc %s: %s", doc_id, exc)
        return {"doc_id": str(doc_id), "error": str(exc)[:200]}

    try:
        ents = json.loads(_strip_fence(raw)).get("participants") or []
    except Exception:
        log.debug("NER JSON parse failed: %s", raw[:400])
        ents = []

    # 2. Position classification (Haiku) for non-applicant stakeholders.
    position = await _classify_position(claude, body)

    # 3. Upsert stakeholders + submission.
    submitted_at = doc["published_at"] or doc["ingested_at"] or datetime.utcnow()
    summary = {
        "doc_id": str(doc_id),
        "docket_id": str(doc["docket_id"]),
        "n_participants": len(ents),
        "position": position,
        "stakeholder_ids": [],
    }

    async with pool.acquire() as conn:
        async with conn.transaction():
            for ent in ents:
                stakeholder_id = await _upsert_stakeholder(
                    conn, doc["docket_id"], ent, position,
                )
                if not stakeholder_id:
                    continue
                summary["stakeholder_ids"].append(str(stakeholder_id))

                # submission row
                try:
                    await conn.execute(
                        """
                        INSERT INTO stakeholder_submissions
                            (stakeholder_id, doc_id, submission_type,
                             submitted_at, position_change)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (stakeholder_id, doc_id) DO NOTHING
                        """,
                        stakeholder_id, doc_id,
                        doc["filing_type"] or "submission",
                        submitted_at,
                        position,
                    )
                except Exception as exc:
                    log.debug("submission upsert skipped: %s", exc)

                # counts + position refresh on the stakeholder row
                await conn.execute(
                    """
                    UPDATE stakeholders
                    SET submission_count = (
                            SELECT count(*) FROM stakeholder_submissions
                            WHERE stakeholder_id = $1),
                        last_submission_at = GREATEST(
                            last_submission_at, $2::timestamptz),
                        first_submission_at = LEAST(
                            first_submission_at, $2::timestamptz),
                        position = CASE
                            WHEN $3::text IS NOT NULL AND role NOT IN ('applicant','co_applicant','spv')
                                THEN $3::text
                            ELSE position END
                    WHERE id = $1
                    """,
                    stakeholder_id, submitted_at, position,
                )

            # back-link documents.stakeholder_id to the primary participant
            # (the first non-authority entry, commonly the filer).
            primary = next(
                (s for s, e in zip(summary["stakeholder_ids"], ents)
                 if not bool(e.get("is_authority_signature"))),
                summary["stakeholder_ids"][0] if summary["stakeholder_ids"] else None,
            )
            if primary:
                await conn.execute(
                    "UPDATE documents SET stakeholder_id = $1 WHERE doc_id = $2 "
                    "AND stakeholder_id IS NULL",
                    UUID(primary), doc_id,
                )

    return summary


async def _classify_position(
    claude: anthropic.AsyncAnthropic, body: str
) -> str | None:
    """Return one of the StakeholderPosition enum values, or None if
    Claude's output can't be parsed. Cheap Haiku call."""
    snippet = body[:3000]
    if len(snippet) < 50:
        return None
    try:
        resp = await claude.messages.create(
            model=MODEL_HAIKU,
            max_tokens=10,
            system=_POSITION_SYSTEM,
            messages=[{"role": "user", "content": snippet}],
        )
        raw = "".join(
            getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"
        )
    except Exception as exc:
        log.debug("position classify failed: %s", exc)
        return None
    token = (raw or "").strip().lower().split()[0] if raw.strip() else ""
    if token in ("for", "against", "conditions", "neutral", "withdrawn"):
        return token
    return None


async def _upsert_stakeholder(
    conn: asyncpg.Connection,
    docket_id: UUID,
    ent: dict[str, Any],
    fallback_position: str | None,
) -> UUID | None:
    """UPSERT one stakeholder row; return its id.

    Matching order:
      1. authority slug / acronym / name → authority_id
      2. company_number
      3. (docket_id, display_name) UNIQUE
    """
    display_name = (ent.get("display_name") or "").strip()
    if not display_name:
        return None
    role = (ent.get("role") or "interested_party").strip().lower()
    # Keep role inside the enum CHECK — map unknowns to interested_party.
    _VALID_ROLES = {
        "applicant", "co_applicant", "spv", "statutory_consultee", "regulator",
        "network_operator", "lpa", "parish_council", "county_council",
        "consumer_body", "industry_body", "objector", "supporter",
        "interested_party", "government_agency", "political", "legal_rep",
        "technical_reviewer", "lender", "neutral", "intervenor", "consultee",
    }
    if role not in _VALID_ROLES:
        role = "interested_party"

    # Try authority match.
    authority_id = None
    auth_row = await conn.fetchrow(
        """SELECT id FROM authorities
           WHERE lower(name) = lower($1)
              OR lower(coalesce(acronym,'')) = lower($1)
              OR lower(slug) = lower($1)
           LIMIT 1""",
        display_name,
    )
    if auth_row:
        authority_id = auth_row["id"]

    company_number = (ent.get("company_number") or "").strip() or None

    # Position: applicants / co_applicants default to 'for'. Everyone
    # else gets the passed classification, falling back to unknown.
    position = "for" if role in ("applicant", "co_applicant", "spv") else (
        fallback_position or "unknown"
    )

    row = await conn.fetchrow(
        """
        INSERT INTO stakeholders
            (docket_id, authority_id, company_number, display_name,
             role, position, first_submission_at, last_submission_at,
             submission_count)
        VALUES ($1, $2, $3, $4, $5, $6, now(), now(), 0)
        ON CONFLICT (docket_id, display_name) DO UPDATE SET
            authority_id   = COALESCE(EXCLUDED.authority_id, stakeholders.authority_id),
            company_number = COALESCE(EXCLUDED.company_number, stakeholders.company_number),
            role = CASE
                WHEN stakeholders.role = 'interested_party' THEN EXCLUDED.role
                ELSE stakeholders.role END
        RETURNING id
        """,
        docket_id, authority_id, company_number, display_name,
        role, position,
    )
    return row["id"] if row else None


def _strip_fence(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        parts = s.split("```", 2)
        if len(parts) >= 2:
            body = parts[1]
            if body.lstrip().startswith("json"):
                body = body.split("\n", 1)[1] if "\n" in body else ""
            return body.split("```", 1)[0]
    return s


__all__ = ["extract_and_upsert_for_document", "MODEL_SONNET", "MODEL_HAIKU"]
