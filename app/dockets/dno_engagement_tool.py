"""
app/dockets/dno_engagement_tool.py — agent tool: ``get_dno_engagement_status``.

Exposes a compact JSON digest of a project's DNO engagement state so the
structured-agent verdict engine (``app/agent.py``) and the streaming chat
(``app/chat.py``) can factor in:

* which pack version was last sent,
* whether the DNO has responded,
* what deadlines are outstanding,
* and how the latest response's structured extract differs from the
  previous one (so the agent can flag "they've asked for more info,
  your firm/non-firm split slipped, or they've proposed a different POC").

Shape returned (spec):

    {
      "project_id": "...",
      "dno_slug": "ukpn",
      "latest_pack_version": 3,
      "status": "responded",
      "sent_at": "2026-04-02T10:00:00+00:00",
      "response_summary": {
          "received_at": "2026-04-15T09:42:00+00:00",
          "sentiment": "conditional",
          "requested_info": ["load profile breakdown", "proposed SLD"],
          "proposed_poc": {"sub_id": "...", "name": "...", "voltage_kv": 33},
          "timeline_revision": {...}
      },
      "current_deadlines": [
          {"label": "Load-flow data deadline", "due_at": "..."},
      ],
      "delta_vs_previous": {
          "firm_split_delta_mw": -5.0,
          "timeline_days_delta": 42,
          "poc_changed": true,
          "newly_requested_info": [...]
      }
    }

If the project has no engagements at all, returns ``{"project_id": ...,
"latest_pack_version": 0, "status": "none"}`` — the agent can then
recommend sending one.

The tool definition (``TOOL_DEFINITION``) is exported so ``app/chat.py``
can register it alongside ``get_pinned_dockets``.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import asyncpg

log = logging.getLogger("princeps.dockets.dno_engagement_tool")


TOOL_DEFINITION: dict[str, Any] = {
    "name": "get_dno_engagement_status",
    "description": (
        "Return a compact JSON digest of the project's DNO engagement "
        "workflow: the latest pack version sent, status "
        "(drafting/previewing/sent/responded/withdrawn/superseded), "
        "a summary of the most recent DNO response (sentiment, "
        "requested_info, proposed_poc, timeline_revision), any "
        "outstanding deadlines derived from the response, and the "
        "delta between the latest response and the previous one "
        "(firm/non-firm split change, timeline shift, POC changes, "
        "newly requested info). Use this when the user asks about "
        "the connection application status, when the agent needs to "
        "factor DNO feedback into a GO/CAUTION/NO-GO verdict, or "
        "when drafting a follow-up pack. Returns "
        "`{latest_pack_version: 0, status: 'none'}` if no pack has "
        "ever been sent for this project."
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_jsonb(value: Any) -> Any:
    """asyncpg returns JSONB as `str` on some driver versions. Be defensive."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            return json.loads(value.decode("utf-8"))
        except Exception:
            return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return None
    return value


def _compute_delta(
    current_extract: dict | None,
    previous_extract: dict | None,
    current_snapshot: dict | None,
    previous_snapshot: dict | None,
) -> dict[str, Any]:
    """Return a compact diff between the latest response + pack and the
    previous ones. All fields optional — absence means "no change"."""
    delta: dict[str, Any] = {}
    cur_e = current_extract or {}
    prev_e = previous_extract or {}

    # Firm/non-firm split delta (MW) — pulled from the extract's firm_split_delta,
    # which the dno_response_parser populates directly.
    if "firm_split_delta" in cur_e:
        delta["firm_split_delta_mw"] = cur_e.get("firm_split_delta")

    # Timeline shift — the difference between revised and original connection
    # dates in days. Ingested extract is responsible for computing this;
    # fall back to None if not present.
    tl = cur_e.get("timeline_revision") or {}
    if isinstance(tl, dict) and tl.get("days_delta") is not None:
        try:
            delta["timeline_days_delta"] = int(tl["days_delta"])
        except (TypeError, ValueError):
            pass

    # POC changed — compare proposed_poc.sub_id. If either side missing
    # we can't be sure so we omit the field rather than lie.
    cur_poc = (cur_e.get("proposed_poc") or {}).get("sub_id")
    prev_poc = (prev_e.get("proposed_poc") or {}).get("sub_id")
    if cur_poc and prev_poc:
        delta["poc_changed"] = cur_poc != prev_poc

    # Newly requested info — set difference of requested_info lists.
    cur_req = set(cur_e.get("requested_info") or [])
    prev_req = set(prev_e.get("requested_info") or [])
    new_items = sorted(cur_req - prev_req)
    if new_items:
        delta["newly_requested_info"] = new_items

    # Pack capacity delta — compare MW asked-for in the structured snapshot.
    cur_snap = current_snapshot or {}
    prev_snap = previous_snapshot or {}
    if cur_snap.get("capacity_mw") is not None and prev_snap.get("capacity_mw") is not None:
        try:
            delta["capacity_mw_delta"] = (
                float(cur_snap["capacity_mw"]) - float(prev_snap["capacity_mw"])
            )
        except (TypeError, ValueError):
            pass

    return delta


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def get_dno_engagement_status(
    pool: asyncpg.Pool, project_id: str
) -> dict[str, Any]:
    """Execute the tool: return a compact engagement-status payload."""
    try:
        proj_uuid = UUID(str(project_id))
    except (ValueError, TypeError):
        return {
            "project_id": str(project_id),
            "latest_pack_version": 0,
            "status": "none",
            "error": "invalid_project_id",
        }

    async with pool.acquire() as conn:
        latest = await conn.fetchrow(
            """
            SELECT id, project_id, tenant_id, dno_slug, pack_version,
                   pdf_sha256, pdf_path, sent_at, sent_by, recipient_email,
                   status, structured_snapshot, created_at, updated_at
            FROM project_dno_engagements
            WHERE project_id = $1
            ORDER BY pack_version DESC
            LIMIT 1
            """,
            proj_uuid,
        )

        if latest is None:
            return {
                "project_id": str(proj_uuid),
                "latest_pack_version": 0,
                "status": "none",
            }

        previous = await conn.fetchrow(
            """
            SELECT id, pack_version, structured_snapshot
            FROM project_dno_engagements
            WHERE project_id = $1
              AND pack_version < $2
            ORDER BY pack_version DESC
            LIMIT 1
            """,
            proj_uuid, int(latest["pack_version"]),
        )

        # Latest response on the latest pack
        latest_response = await conn.fetchrow(
            """
            SELECT id, received_at, channel, structured_extract,
                   acknowledgement_sent_at, triggered_verdict_recompute
            FROM dno_engagement_responses
            WHERE engagement_id = $1
            ORDER BY received_at DESC
            LIMIT 1
            """,
            latest["id"],
        )

        # Previous response on the same engagement — used for delta
        prev_response = None
        if latest_response is not None:
            prev_response = await conn.fetchrow(
                """
                SELECT id, received_at, structured_extract
                FROM dno_engagement_responses
                WHERE engagement_id = $1
                  AND received_at < $2
                ORDER BY received_at DESC
                LIMIT 1
                """,
                latest["id"], latest_response["received_at"],
            )
            # If there's no earlier response on the *same* pack, try the
            # response to the previous pack version as the baseline for diff.
            if prev_response is None and previous is not None:
                prev_response = await conn.fetchrow(
                    """
                    SELECT id, received_at, structured_extract
                    FROM dno_engagement_responses
                    WHERE engagement_id = $1
                    ORDER BY received_at DESC
                    LIMIT 1
                    """,
                    previous["id"],
                )

    # ── Assemble payload ──────────────────────────────────────────────────
    cur_snapshot = _load_jsonb(latest["structured_snapshot"])
    prev_snapshot = _load_jsonb(previous["structured_snapshot"]) if previous else None
    cur_extract = (
        _load_jsonb(latest_response["structured_extract"]) if latest_response else None
    )
    prev_extract = (
        _load_jsonb(prev_response["structured_extract"]) if prev_response else None
    )

    response_summary: dict[str, Any] | None = None
    current_deadlines: list[dict[str, Any]] = []
    if latest_response is not None:
        rs: dict[str, Any] = {
            "received_at": (
                latest_response["received_at"].isoformat()
                if latest_response["received_at"] else None
            ),
            "channel": latest_response["channel"],
            "acknowledged":
                latest_response["acknowledgement_sent_at"] is not None,
            "triggered_verdict_recompute":
                bool(latest_response["triggered_verdict_recompute"]),
        }
        if isinstance(cur_extract, dict):
            rs["sentiment"] = cur_extract.get("sentiment")
            rs["requested_info"] = cur_extract.get("requested_info") or []
            rs["proposed_poc"] = cur_extract.get("proposed_poc")
            rs["timeline_revision"] = cur_extract.get("timeline_revision")
            # Pull deadlines out of the extract — parser emits these as a list
            deadlines = cur_extract.get("deadlines") or []
            if isinstance(deadlines, list):
                current_deadlines = [
                    {
                        "label": (d.get("label") if isinstance(d, dict) else None),
                        "due_at": (d.get("due_at") if isinstance(d, dict) else None),
                    }
                    for d in deadlines
                    if isinstance(d, dict)
                ]
        response_summary = rs

    payload: dict[str, Any] = {
        "project_id": str(proj_uuid),
        "dno_slug": latest["dno_slug"],
        "latest_pack_version": int(latest["pack_version"]),
        "status": latest["status"],
        "sent_at": latest["sent_at"].isoformat() if latest["sent_at"] else None,
        "recipient_email": latest["recipient_email"],
        "pdf_sha256": latest["pdf_sha256"],
        "response_summary": response_summary,
        "current_deadlines": current_deadlines,
        "delta_vs_previous": _compute_delta(
            cur_extract, prev_extract, cur_snapshot, prev_snapshot,
        ),
    }
    return payload


__all__ = ["TOOL_DEFINITION", "get_dno_engagement_status"]
