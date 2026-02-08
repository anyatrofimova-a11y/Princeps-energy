"""
Structured agentic analysis using Claude (Anthropic SDK).

Supports intent-based prompting and returns structured JSON with
confidence, risks, opportunities, next_steps, and actionable commands.
Includes NDJSON audit logging for traceability.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic
from pydantic import BaseModel as PydanticBaseModel, field_validator

log = logging.getLogger(__name__)


class AgentOutput(PydanticBaseModel):
    """Validated schema for Claude agent responses."""
    verdict: str = "CAUTION"
    confidence: float = 0.5
    summary: str = ""
    risks: list[str] = []
    opportunities: list[str] = []
    recommended_capacity_kw: float | None = None
    estimated_roi_years: float | None = None
    next_steps: list[str] = []
    actions: list[dict] = []
    intent: str = "feasibility"

    @field_validator("verdict")
    @classmethod
    def validate_verdict(cls, v: str) -> str:
        v = v.upper().strip()
        if v not in ("GO", "CAUTION", "NO-GO"):
            return "CAUTION"
        return v

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

AUDIT_DIR = Path(os.environ.get("AUDIT_DIR", "audit_logs"))

# Intent → system prompt fragments
INTENT_PROMPTS: dict[str, str] = {
    "feasibility": (
        "You are a senior solar energy feasibility analyst. "
        "Evaluate whether this site is suitable for a solar PV installation. "
        "Consider terrain, grid connection, environmental designations, and solar resource. "
        "Provide a GO / CAUTION / NO-GO verdict with confidence score."
    ),
    "grid_study": (
        "You are a UK Distribution Network Operator (DNO) connections engineer. "
        "Assess grid connection feasibility: substation headroom, cable distance, "
        "reinforcement needs, connection cost estimate, and timeline."
    ),
    "financial": (
        "You are a renewable energy project finance analyst. "
        "Calculate ROI, LCOE, payback period, revenue scenarios (SEG, PPA, merchant), "
        "and financing options for the proposed solar installation."
    ),
    "environmental": (
        "You are an environmental impact assessment specialist. "
        "Evaluate ecological constraints: flood risk, AONB/SSSI designations, "
        "biodiversity net gain requirements, and mitigation measures."
    ),
    "planning": (
        "You are a UK planning consultant specialising in renewable energy. "
        "Assess planning permission likelihood, relevant NPPF policies, "
        "local plan alignment, and pre-application strategy."
    ),
}

OUTPUT_SCHEMA = """\
Return ONLY a valid JSON object with these exact fields:
{
  "verdict": "GO" | "CAUTION" | "NO-GO",
  "confidence": 0.0 to 1.0,
  "summary": "2-3 sentence assessment",
  "risks": ["risk1", "risk2", ...],
  "opportunities": ["opp1", "opp2", ...],
  "recommended_capacity_kw": number,
  "estimated_roi_years": number or null,
  "next_steps": ["step1", "step2", ...],
  "actions": [
    {"label": "human-readable label", "endpoint": "/api/path", "method": "POST", "payload": {}}
  ]
}

The "actions" array lists concrete API calls the user can trigger.
Only output valid JSON — no markdown, no explanation text.
Use the data below — do not invent numbers.\
"""


def _audit_log(entry: dict) -> None:
    """Append an NDJSON audit entry."""
    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = AUDIT_DIR / f"agent_{today}.ndjson"
        with open(path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        log.warning("Failed to write audit log", exc_info=True)


def _extract_json(text: str) -> dict:
    """Extract and validate the first balanced JSON object from text."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("No JSON object found in response")
    raw = json.loads(text[start:end])
    validated = AgentOutput(**raw)
    return validated.model_dump()


async def run_structured_agent(
    client: anthropic.AsyncAnthropic,
    model: str,
    context: dict[str, Any],
    intent: str = "feasibility",
    max_tokens: int = 1200,
) -> dict[str, Any]:
    """
    Run a structured agent analysis using Claude.

    Args:
        client: AsyncAnthropic client instance
        model: Claude model identifier
        context: dict of parcel/site data
        intent: one of INTENT_PROMPTS keys
        max_tokens: response length limit

    Returns:
        Parsed JSON dict with verdict, risks, etc.
    """
    system_prompt = INTENT_PROMPTS.get(intent, INTENT_PROMPTS["feasibility"])
    t0 = time.time()

    try:
        message = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"{OUTPUT_SCHEMA}\n\nData:\n{json.dumps(context, indent=2)}",
                }
            ],
        )
        raw_text = message.content[0].text
        agent_output = _extract_json(raw_text)
        agent_output.setdefault("intent", intent)
        elapsed = round(time.time() - t0, 2)

        # Suggest actions based on intent if none provided
        if not agent_output.get("actions"):
            agent_output["actions"] = _default_actions(intent, context)

        _audit_log(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "intent": intent,
                "parcel_id": context.get("parcel_id"),
                "model": model,
                "elapsed_s": elapsed,
                "verdict": agent_output.get("verdict"),
                "confidence": agent_output.get("confidence"),
                "input_tokens": getattr(message.usage, "input_tokens", None),
                "output_tokens": getattr(message.usage, "output_tokens", None),
            }
        )
        return agent_output

    except (anthropic.APIError, json.JSONDecodeError, ValueError, KeyError) as exc:
        elapsed = round(time.time() - t0, 2)
        log.warning("Structured agent call failed: %s", exc)
        _audit_log(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "intent": intent,
                "parcel_id": context.get("parcel_id"),
                "error": str(exc),
                "elapsed_s": elapsed,
            }
        )
        raise


def _default_actions(intent: str, ctx: dict) -> list[dict]:
    """Generate sensible default actions based on intent."""
    pid = ctx.get("parcel_id", "")
    cap = ctx.get("capacity_kw", 100)
    actions = []

    if intent == "feasibility":
        actions = [
            {
                "label": "Run Grid Study",
                "endpoint": f"/job/grid_study",
                "method": "POST",
                "payload": {"parcel_id": pid, "capacity_kw": cap},
            },
            {
                "label": "Generate BOM",
                "endpoint": f"/site/{pid}/bom?capacity_kw={cap}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Financial Analysis",
                "endpoint": f"/site/{pid}/agent",
                "method": "POST",
                "payload": {"intent": "financial", "capacity_kw": cap},
            },
        ]
    elif intent == "grid_study":
        actions = [
            {
                "label": "Run Deferral Optimiser",
                "endpoint": "/opt/run",
                "method": "POST",
                "payload": {"plan_name": "agent_grid", "load_mw": cap / 1000, "gen_mw": cap / 1000},
            },
        ]
    elif intent == "financial":
        actions = [
            {
                "label": "Energy Price Forecast",
                "endpoint": f"/site/{pid}/energy_price?capacity_kw={cap}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "UK Energy System Context",
                "endpoint": f"/site/{pid}/energy_system_context?capacity_kw={cap}",
                "method": "GET",
                "payload": {},
            },
        ]
    elif intent == "planning":
        actions = [
            {
                "label": "View Planning Applications",
                "endpoint": "/planning/energy/summary",
                "method": "GET",
                "payload": {},
            },
        ]

    return actions
