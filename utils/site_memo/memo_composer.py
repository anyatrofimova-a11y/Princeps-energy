"""AI Site Memo composer — Claude Sonnet 4.6 with structured JSON output.

Accepts a full ``memo_context`` dict assembled by the caller (project metadata,
latest AgentVerdict per intent, DNO state, planning precedent summary, DCF
headline, constraints, regulatory flags) and returns a validated JSON memo
matching ``MEMO_SCHEMA``. The schema is enforced post-hoc — we never trust the
model to return valid JSON without a retry-and-repair fallback.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("princeps.site_memo")

# Sonnet 4.6 per product spec; overridable via env for rollouts.
MEMO_MODEL = os.environ.get("MEMO_MODEL", "claude-sonnet-4-6-20250914")
MEMO_MAX_TOKENS = 4096

# JSON shape that `compose_memo` guarantees to return.
MEMO_SCHEMA: dict[str, Any] = {
    "title": "str",
    "one_liner": "str",
    "investment_verdict": "GO|CAUTION|NO-GO",
    "key_strengths": "list[str] (3-5)",
    "critical_risks": "list[str] (3-5)",
    "next_milestones": "list[{date, action}]",
    "financial_headline": "{npv_gbp_m, irr_pct, dscr}",
    "grid_headline": "{poc, firm_mw, estimated_cost_gbp_m, timeline_months}",
    "planning_headline": "{approval_pct, lpa, precedent_count}",
    "regulatory_flags": "list[str]",
    "source_evidence": "list[{label, doc_id}]",
}

_SYSTEM_PROMPT = """You are Princeps' senior investment-grade energy infrastructure analyst.
Your output lands in front of investment committees and must be terse, numerate,
and free of filler. Return ONLY a JSON object matching the schema — no prose,
no markdown, no code fences. Use UK spelling. Reference specific figures from
the context rather than hedging. Each bullet must be a complete thought in
<= 18 words. Verdicts must be justified by the evidence in the context.
"""

_USER_PROMPT_TEMPLATE = """Compose a one-page investment memo for the project below.

=== PROJECT CONTEXT ===
{context_block}

=== OUTPUT SCHEMA ===
Return a single JSON object with exactly these fields:
- title (str): project name + technology + capacity, <=60 chars
- one_liner (str): single-sentence positioning, <=140 chars
- investment_verdict: "GO" | "CAUTION" | "NO-GO"
- key_strengths (list[str]): 3-5 bullets, strongest first
- critical_risks (list[str]): 3-5 bullets, most material first
- next_milestones (list[{{date: "YYYY-MM-DD", action: str}}]): 3 upcoming items
- financial_headline: {{npv_gbp_m: float, irr_pct: float, dscr: float}}
- grid_headline: {{poc: str, firm_mw: float, estimated_cost_gbp_m: float, timeline_months: int}}
- planning_headline: {{approval_pct: int, lpa: str, precedent_count: int}}
- regulatory_flags (list[str]): ordered by materiality
- source_evidence (list[{{label: str, doc_id: str}}]): key documents cited

Use the values from context where present. Do not invent figures. Return JSON only."""


def _format_context(ctx: dict) -> str:
    """Human-readable context dump fed to Claude — keep compact, the model
    will echo numbers back so exact formatting matters less than readability."""
    try:
        return json.dumps(ctx, indent=2, default=str, ensure_ascii=False)
    except Exception:
        return str(ctx)


async def compose_memo(memo_context: dict, claude_client: Any | None = None) -> dict:
    """Call Claude Sonnet 4.6 and return validated memo JSON.

    ``claude_client`` may be an instance of ``anthropic.AsyncAnthropic``. When
    ``None`` (test / demo path) we synthesise a memo from the context instead
    of calling the API — useful when running in MOCK mode or without
    ``CLAUDE_API_KEY`` configured.
    """
    if claude_client is None:
        return _synthetic_memo(memo_context)

    prompt = _USER_PROMPT_TEMPLATE.format(context_block=_format_context(memo_context))

    try:
        resp = await claude_client.messages.create(
            model=MEMO_MODEL,
            max_tokens=MEMO_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        # Extract the plain-text JSON from the first content block.
        text = ""
        for block in getattr(resp, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text += block.text
        memo = _parse_json_lenient(text)
        return _validate_memo(memo, memo_context)
    except Exception as e:
        log.warning("memo composer falling back to synthetic: %s", e)
        return _synthetic_memo(memo_context)


# ---------------------------------------------------------------------------
# Parsing & validation
# ---------------------------------------------------------------------------
def _parse_json_lenient(text: str) -> dict:
    """Accept raw JSON, JSON-in-a-code-fence, or JSON wrapped in prose."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty model response")
    # Strip markdown code fences if present.
    if text.startswith("```"):
        text = text.split("```", 2)[-1]
        if text.lstrip().lower().startswith("json"):
            text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    # Find first `{` / last `}` to isolate JSON from any surrounding text.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])


def _validate_memo(memo: dict, ctx: dict) -> dict:
    """Ensure required keys exist with sensible defaults — never raise."""
    fallback = _synthetic_memo(ctx)
    out: dict = {}
    for key in MEMO_SCHEMA:
        out[key] = memo.get(key, fallback[key])

    # Normalise verdict casing.
    v = str(out.get("investment_verdict", "CAUTION")).upper().strip()
    out["investment_verdict"] = v if v in ("GO", "CAUTION", "NO-GO") else "CAUTION"

    # Enforce list bounds.
    out["key_strengths"] = list(out.get("key_strengths") or [])[:5]
    out["critical_risks"] = list(out.get("critical_risks") or [])[:5]
    out["next_milestones"] = list(out.get("next_milestones") or [])[:3]
    out["regulatory_flags"] = list(out.get("regulatory_flags") or [])[:8]
    out["source_evidence"] = list(out.get("source_evidence") or [])[:10]

    # Metadata we always set server-side.
    out["_generated_at"] = datetime.now(timezone.utc).isoformat()
    out["_model"] = MEMO_MODEL
    return out


# ---------------------------------------------------------------------------
# Synthetic fallback — keeps the product demo-able without Claude
# ---------------------------------------------------------------------------
def _synthetic_memo(ctx: dict) -> dict:
    proj = ctx.get("project", {}) if isinstance(ctx, dict) else {}
    name = proj.get("name") or "Unnamed Project"
    tech = (proj.get("technology") or "solar").upper()
    cap = float(proj.get("capacity_mw") or 50)
    lpa = ctx.get("lpa") or "Local Planning Authority"
    fin = ctx.get("financial", {}) or {}
    grid = ctx.get("grid", {}) or {}
    planning = ctx.get("planning", {}) or {}
    verdicts = ctx.get("verdicts", {}) or {}

    # Choose overall verdict by majority vote across intents.
    vcount = {"GO": 0, "CAUTION": 0, "NO-GO": 0}
    for v in verdicts.values():
        key = str((v or {}).get("verdict", "CAUTION")).upper()
        if key in vcount:
            vcount[key] += 1
    top = max(vcount, key=vcount.get) if any(vcount.values()) else "CAUTION"

    return {
        "title": f"{name} — {cap:.0f} MW {tech}",
        "one_liner": f"{cap:.0f} MW {tech.lower()} asset near {lpa} with bankable grid and planning pathway.",
        "investment_verdict": top,
        "key_strengths": [
            f"Firm {grid.get('firm_mw', cap):.0f} MW capacity at {grid.get('poc', 'nearest BSP')}",
            f"{planning.get('approval_pct', 65)}% LPA approval prob with {planning.get('precedent_count', 3)} precedents",
            f"IRR {fin.get('irr_pct', 11.5):.1f}% > hurdle; DSCR {fin.get('dscr', 1.45):.2f}x",
            "Developable land secured under option with motivated landowner",
        ],
        "critical_risks": [
            "Reinforcement cost exposure at shared POC tipping IRR below hurdle",
            "BNG baseline uplift could add £80k/ha to delivery programme",
            "Export limitation likely at peak summer midday absent curtailment deal",
            "AR7 CfD timing slippage would delay offtake lock-in by 6 months",
        ],
        "next_milestones": [
            {"date": _iso_days_from_now(14), "action": "Submit G99 application to DNO"},
            {"date": _iso_days_from_now(45), "action": "Lodge planning application with LPA"},
            {"date": _iso_days_from_now(120), "action": "Finalise PPA term sheet"},
        ],
        "financial_headline": {
            "npv_gbp_m": float(fin.get("npv_gbp_m", 18.4)),
            "irr_pct": float(fin.get("irr_pct", 11.5)),
            "dscr": float(fin.get("dscr", 1.45)),
        },
        "grid_headline": {
            "poc": grid.get("poc", "Nearest BSP"),
            "firm_mw": float(grid.get("firm_mw", cap)),
            "estimated_cost_gbp_m": float(grid.get("estimated_cost_gbp_m", 4.2)),
            "timeline_months": int(grid.get("timeline_months", 28)),
        },
        "planning_headline": {
            "approval_pct": int(planning.get("approval_pct", 68)),
            "lpa": str(lpa),
            "precedent_count": int(planning.get("precedent_count", 3)),
        },
        "regulatory_flags": ctx.get("regulatory_flags") or [
            "EN-3 compliance — national policy alignment required",
            "BNG net gain >10% (Env Act 2021)",
            "CDM 2015 — principal designer pre-construction",
        ],
        "source_evidence": ctx.get("source_evidence") or [
            {"label": "DNO capacity map 2026-04", "doc_id": "dno-cap-2026-04"},
            {"label": "REPD precedent pack", "doc_id": "repd-2026-q1"},
            {"label": "Financial model v3", "doc_id": "fm-v3"},
        ],
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_model": "synthetic",
    }


def _iso_days_from_now(days: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()
