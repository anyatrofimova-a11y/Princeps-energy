"""Adjudication agent — synthesises pod verdicts into a Council decision.

The adjudicator is given (a) the original user query, (b) the three pod
verdicts as structured JSON, and (c) ontology read access (project + linked
substation snapshot). It detects conflicts (e.g. GRID says no headroom for
100 MW while DC pod assumes 100 MW available), and either:

  * Emits a unified ``final_verdict`` (best-of consolidation), or
  * Surfaces a ``clarification_needed`` event with one specific question
    the user must answer; the council router then resumes adjudication.

Conflict detection is deliberately conservative: a verdict-level mismatch
(GO vs NO-GO) is always a conflict; a confidence delta > 0.4 is a
soft conflict; an MW-mismatch (one pod cites 100 MW where another cites
20 MW within the same query) is the canonical "hard" conflict.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import anthropic

from app.agent import AgentOutput
from app.agents.pod import _audit_log

log = logging.getLogger("princeps.council.adjudication")


ADJUDICATION_SYSTEM_PROMPT = """\
You are the Adjudicator on the Princeps Council. You consume three structured
pod verdicts (GRID, BESS, DC) plus the original user query, and emit one
unified verdict for the project.

Operating rules:
- If two pods disagree on a hard fact (MW available, voltage, queue depth,
  RID identity), surface that as a conflict, do not silently average.
- The GRID pod is authoritative on headroom and queue. The BESS pod is
  authoritative on revenue and dispatch. The DC pod is authoritative on
  hyperscaler fit and design. If any pod overreaches outside its lane,
  weight its claim lower.
- If the user query is materially ambiguous (e.g. asks about MW but no
  figure; asks about BESS at a site with no host substation), return a
  clarification request rather than guessing.
- Output JSON only at the end of your turn. Engineering tone. No emojis.
- The "verdict" is a single Council position: GO, CAUTION, or NO-GO.
- The "confidence" is the minimum of the three pod confidences if no
  conflict is detected; if conflict is present and resolved, you may set
  it as the average; if unresolved, set it to 0.3.

When you ask a clarification, give ONE specific question with concrete
options the user can pick. Do not stack multiple questions in one turn.
"""


_FINAL_VERDICT_SCHEMA = """\
End your turn with exactly one JSON object, no prose, with this shape:
{
  "kind": "final_verdict" | "clarification_needed",
  "verdict": "GO" | "CAUTION" | "NO-GO",
  "confidence": 0.0 to 1.0,
  "summary": "council position in 2-3 engineering sentences",
  "risks": ["..."],
  "opportunities": ["..."],
  "conflicts": [
    {"pod_a": "grid", "pod_b": "dc", "field": "mw", "claim_a": "...",
     "claim_b": "...", "resolution": "...|unresolved"}
  ],
  "clarification": {
    "question": "single concrete question",
    "options": ["option a", "option b", "..."]
  } | null,
  "provenance": {"grid": "verdict cite", "bess": "...", "dc": "..."}
}
"""


@dataclass
class AdjudicationResult:
    kind: str  # "final_verdict" | "clarification_needed"
    verdict: str
    confidence: float
    summary: str
    risks: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    clarification: Optional[dict] = None
    provenance: dict[str, str] = field(default_factory=dict)
    elapsed_s: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "summary": self.summary,
            "risks": self.risks,
            "opportunities": self.opportunities,
            "conflicts": self.conflicts,
            "clarification": self.clarification,
            "provenance": self.provenance,
            "elapsed_s": self.elapsed_s,
            "error": self.error,
        }


# Hard conflict heuristics ---------------------------------------------------

_MW_RE = re.compile(r"(\d+(?:\.\d+)?)\s*MW", re.IGNORECASE)


def _extract_mw_claims(verdict: AgentOutput) -> set[float]:
    """Pull MW figures from summary + risks + opportunities."""
    blob = " ".join(
        [verdict.summary] + list(verdict.risks) + list(verdict.opportunities)
    )
    return {float(m.group(1)) for m in _MW_RE.finditer(blob)}


def detect_conflicts(verdicts: dict[str, AgentOutput]) -> list[dict]:
    """Pairwise conflict detection across the pod outputs.

    Returns a list of conflict descriptors. An empty list means the pods are
    coherent enough to ship a unified verdict without clarification.
    """
    conflicts: list[dict] = []
    keys = list(verdicts.keys())
    # Verdict-level disagreement (GO vs NO-GO is always a conflict; CAUTION vs
    # the others is a soft signal but only flagged when paired with NO-GO).
    bad_pairs = {("GO", "NO-GO"), ("NO-GO", "GO")}
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            va = verdicts[a]
            vb = verdicts[b]
            if (va.verdict, vb.verdict) in bad_pairs:
                conflicts.append({
                    "pod_a": a, "pod_b": b, "field": "verdict",
                    "claim_a": va.verdict, "claim_b": vb.verdict,
                    "resolution": "unresolved",
                })
            # Confidence delta
            if abs(va.confidence - vb.confidence) > 0.4:
                conflicts.append({
                    "pod_a": a, "pod_b": b, "field": "confidence",
                    "claim_a": round(va.confidence, 2),
                    "claim_b": round(vb.confidence, 2),
                    "resolution": "soft_disagree",
                })
            # MW mismatch — both pods cite MW figures but the maxima differ
            mw_a = _extract_mw_claims(va)
            mw_b = _extract_mw_claims(vb)
            if mw_a and mw_b:
                hi_a, hi_b = max(mw_a), max(mw_b)
                if hi_a and hi_b and abs(hi_a - hi_b) / max(hi_a, hi_b) > 0.3:
                    conflicts.append({
                        "pod_a": a, "pod_b": b, "field": "mw",
                        "claim_a": f"{hi_a} MW", "claim_b": f"{hi_b} MW",
                        "resolution": "unresolved",
                    })
    return conflicts


def _conservative_verdict(verdicts: dict[str, AgentOutput]) -> tuple[str, float]:
    """Worst-case across pods (NO-GO dominates CAUTION dominates GO).

    Confidence is the minimum across the pods that landed a verdict.
    """
    rank = {"NO-GO": 0, "CAUTION": 1, "GO": 2}
    chosen = min(verdicts.values(), key=lambda v: rank[v.verdict])
    conf = min(v.confidence for v in verdicts.values())
    return chosen.verdict, conf


# ---------------------------------------------------------------------------
# Anthropic-driven synthesis
# ---------------------------------------------------------------------------

async def adjudicate(
    *,
    client: anthropic.AsyncAnthropic,
    model: str,
    query: str,
    verdicts: dict[str, AgentOutput],
    pool,
    session_rid: str,
    project_rid: Optional[str],
    user_clarifications: Optional[list[dict]] = None,
    max_tokens: int = 1500,
) -> AdjudicationResult:
    """Synthesise the three pod verdicts into a unified Council position.

    The adjudicator is given full ontology context (project record + any
    pre-computed conflict heuristics) and produces either a final verdict or
    a clarification request.
    """
    t0 = time.time()
    detected = detect_conflicts(verdicts)
    fallback_verdict, fallback_conf = _conservative_verdict(verdicts)

    # Build a compact context block for Claude.
    pod_block = {
        name: v.model_dump() for name, v in verdicts.items()
    }
    project_snapshot = await _project_snapshot(pool, project_rid) if project_rid else None

    user_msg = (
        f"User query: {query}\n\n"
        f"Project RID: {project_rid or '(unbound)'}\n"
        f"Project snapshot: {json.dumps(project_snapshot, default=str) if project_snapshot else 'null'}\n\n"
        f"Pod verdicts:\n{json.dumps(pod_block, indent=2, default=str)}\n\n"
        f"Heuristic conflicts: {json.dumps(detected, default=str)}\n\n"
    )
    if user_clarifications:
        user_msg += (
            "Prior user clarifications (apply these as authoritative):\n"
            f"{json.dumps(user_clarifications, default=str, indent=2)}\n\n"
        )
    user_msg += _FINAL_VERDICT_SCHEMA

    error: Optional[str] = None
    parsed: Optional[dict] = None
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
            system=ADJUDICATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        parsed = _extract_first_json(text)
    except (anthropic.APIError, ValueError, json.JSONDecodeError) as exc:
        error = f"adjudicate_failed: {exc}"
        log.exception("adjudication call failed: %s", exc)

    elapsed_s = round(time.time() - t0, 2)

    # If parsing failed, build a deterministic fallback so the council still
    # ships a verdict (degraded confidence, conflicts surfaced).
    if parsed is None:
        result = AdjudicationResult(
            kind="final_verdict" if not detected else "clarification_needed",
            verdict=fallback_verdict,
            confidence=max(0.2, fallback_conf - 0.2),
            summary=("Adjudication LLM failed; deterministic fallback "
                     "applied (worst-of pod verdicts)."),
            risks=[error or "adjudication_no_response"],
            conflicts=detected,
            clarification=(
                {
                    "question": (
                        "The pods produced conflicting numeric claims. "
                        "Please confirm the project size you intend (MW)."
                    ),
                    "options": [],
                }
                if detected else None
            ),
            provenance={
                k: f"{v.verdict} @ {v.confidence:.2f}"
                for k, v in verdicts.items()
            },
            elapsed_s=elapsed_s,
            error=error,
        )
    else:
        kind = parsed.get("kind", "final_verdict")
        if kind not in ("final_verdict", "clarification_needed"):
            kind = "final_verdict"
        verdict = (parsed.get("verdict") or fallback_verdict).upper().strip()
        if verdict not in ("GO", "CAUTION", "NO-GO"):
            verdict = fallback_verdict
        try:
            conf = max(0.0, min(1.0, float(parsed.get("confidence", fallback_conf))))
        except (TypeError, ValueError):
            conf = fallback_conf
        result = AdjudicationResult(
            kind=kind,
            verdict=verdict,
            confidence=conf,
            summary=parsed.get("summary", ""),
            risks=list(parsed.get("risks") or []),
            opportunities=list(parsed.get("opportunities") or []),
            conflicts=list(parsed.get("conflicts") or detected),
            clarification=parsed.get("clarification"),
            provenance=dict(parsed.get("provenance") or {
                k: f"{v.verdict} @ {v.confidence:.2f}"
                for k, v in verdicts.items()
            }),
            elapsed_s=elapsed_s,
            error=None,
        )

    # Audit-log the adjudication itself
    await _audit_log(
        pool,
        session_rid=session_rid,
        pod_name="adjudicator",
        action="adjudicate" if not user_clarifications else "adjudicate_resume",
        args={
            "query": query[:500],
            "clarifications": user_clarifications or [],
        },
        result=result.to_dict(),
        ok=result.error is None,
        duration_ms=int(elapsed_s * 1000),
        error=result.error,
    )
    return result


def _extract_first_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("No JSON object in adjudicator response")
    return json.loads(text[start:end])


async def _project_snapshot(pool, project_rid: str) -> Optional[dict]:
    """Best-effort read of the project ontology row keyed by RID/UUID.

    Accepts both a bare UUID and a full ``rid.princeps.project.<uuid>``
    string for compatibility with current frontend wiring.
    """
    if not project_rid or pool is None:
        return None
    pid = project_rid
    if pid.startswith("rid.princeps.project."):
        pid = pid.split(".")[-1]
    try:
        from uuid import UUID as _UUID
        try:
            uid = _UUID(pid)
        except ValueError:
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT project_id, name, technology, capacity_mw, stage, "
                "verdict, lat, lon FROM projects WHERE project_id = $1", uid,
            )
        if not row:
            return None
        return {
            "project_id": str(row["project_id"]),
            "name": row["name"],
            "technology": row["technology"],
            "capacity_mw": float(row["capacity_mw"]) if row["capacity_mw"] else None,
            "stage": row["stage"],
            "verdict": row["verdict"],
            "lat": float(row["lat"]) if row["lat"] else None,
            "lon": float(row["lon"]) if row["lon"] else None,
        }
    except Exception:
        log.warning("project_snapshot read failed for %s", project_rid,
                    exc_info=True)
        return None
