"""
app/dockets/agent_tool.py — new agent tool: ``get_pinned_dockets``.

Exposes a compact JSON payload per pinned docket so the AgentVerdict
engine (``app/agent.py``) can factor them into GO / CAUTION / NO-GO
verdicts.

Shape per docket (spec):

  {
    "docket_id": "...",
    "case_type": "nsip_dco",
    "stage": "examination",
    "applicant_name": "Acme Solar Ltd",
    "statutory_deadline": "2026-11-14",
    "exec_summary_text": "(≤400 chars)",
    "next_deadline": "2026-05-01",
    "stakeholder_position_breakdown": {"for": 3, "against": 11,
                                        "conditions": 4, "neutral": 2,
                                        "unknown": 7},
    "timeline_next_3_events": [...],
    "key_stakeholder_positions": [ top 5 by submission_count ]
  }

The tool definition (``TOOL_DEFINITION``) is exported so a follow-up
task can register it in ``app/agent.py``'s TOOL list without touching
this file.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

import asyncpg

log = logging.getLogger("princeps.dockets.agent_tool")


TOOL_DEFINITION: dict[str, Any] = {
    "name": "get_pinned_dockets",
    "description": (
        "Return a compact JSON digest of all regulatory dockets pinned to "
        "a Princeps project (NSIP DCO examinations, Ofgem code mods, LPA "
        "planning applications, CfD rounds, s36 consents, DNO connection "
        "cases, etc.). Use this when you need to factor live regulatory "
        "context into a GO/CAUTION/NO-GO verdict, identify deadlines, "
        "or surface key stakeholder positions. Returns an empty list if "
        "no dockets are pinned to this project."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "Princeps project UUID.",
            },
        },
        "required": ["project_id"],
    },
}


async def get_pinned_dockets(
    pool: asyncpg.Pool, project_id: str
) -> list[dict[str, Any]]:
    """Execute the tool: return the per-docket compact payload."""
    try:
        proj_uuid = UUID(project_id)
    except (ValueError, TypeError):
        return []

    async with pool.acquire() as conn:
        docket_rows = await conn.fetch(
            """
            SELECT d.docket_id, d.source, d.source_docket_id, d.title,
                   d.case_type, d.industry, d.status, d.stage,
                   d.applicant_name, d.statutory_deadline,
                   d.exec_summary_text, d.exec_summary_cached_at,
                   p.note AS pin_note
            FROM project_docket_pins p
            JOIN dockets d ON d.docket_id = p.docket_id
            WHERE p.project_id = $1
            ORDER BY d.updated_at DESC NULLS LAST
            """,
            proj_uuid,
        )
        if not docket_rows:
            return []

        payloads: list[dict[str, Any]] = []

        for d in docket_rows:
            did = d["docket_id"]

            # Position breakdown
            pos_rows = await conn.fetch(
                """SELECT position, count(*) AS n
                   FROM stakeholders
                   WHERE docket_id = $1
                   GROUP BY position""",
                did,
            )
            breakdown = {
                "for": 0, "against": 0, "conditions": 0,
                "neutral": 0, "unknown": 0, "withdrawn": 0,
            }
            for pr in pos_rows:
                key = (pr["position"] or "unknown")
                if key in breakdown:
                    breakdown[key] = int(pr["n"])

            # Next 3 forward-looking events
            ev_rows = await conn.fetch(
                """SELECT event_type, event_at, summary_text,
                          forward_looking, deadline_at
                   FROM docket_timeline_events
                   WHERE docket_id = $1
                     AND (forward_looking = true OR event_at >= $2)
                   ORDER BY event_at ASC
                   LIMIT 3""",
                did, date.today(),
            )
            next_events = [
                {
                    "event_type":      r["event_type"],
                    "event_at":        r["event_at"].isoformat() if r["event_at"] else None,
                    "summary_text":    r["summary_text"],
                    "forward_looking": bool(r["forward_looking"]),
                    "deadline_at":     r["deadline_at"].isoformat() if r["deadline_at"] else None,
                }
                for r in ev_rows
            ]
            next_deadline = next(
                (e["deadline_at"] or e["event_at"] for e in next_events
                 if e["forward_looking"] and (e["deadline_at"] or e["event_at"])),
                None,
            )

            # Top 5 stakeholders by activity
            top_rows = await conn.fetch(
                """SELECT display_name, role, position, submission_count,
                          last_submission_at
                   FROM stakeholders
                   WHERE docket_id = $1
                   ORDER BY submission_count DESC NULLS LAST,
                            last_submission_at DESC NULLS LAST
                   LIMIT 5""",
                did,
            )
            key_positions = [
                {
                    "display_name":       r["display_name"],
                    "role":               r["role"],
                    "position":           r["position"],
                    "submission_count":   int(r["submission_count"] or 0),
                    "last_submission_at": r["last_submission_at"].isoformat()
                        if r["last_submission_at"] else None,
                }
                for r in top_rows
            ]

            summary = d["exec_summary_text"] or ""
            if len(summary) > 400:
                summary = summary[:397] + "…"

            payloads.append({
                "docket_id":            str(did),
                "source":               d["source"],
                "source_docket_id":     d["source_docket_id"],
                "title":                d["title"],
                "case_type":            d["case_type"],
                "industry":             d["industry"],
                "status":               d["status"],
                "stage":                d["stage"],
                "applicant_name":       d["applicant_name"],
                "statutory_deadline":   d["statutory_deadline"].isoformat()
                    if d["statutory_deadline"] else None,
                "exec_summary_text":    summary,
                "next_deadline":        next_deadline,
                "pin_note":             d["pin_note"],
                "stakeholder_position_breakdown": breakdown,
                "timeline_next_3_events":         next_events,
                "key_stakeholder_positions":      key_positions,
            })

    return payloads


__all__ = ["TOOL_DEFINITION", "get_pinned_dockets"]
