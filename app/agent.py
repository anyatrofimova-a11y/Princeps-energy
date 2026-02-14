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
    "grid_opportunity": (
        "You are a UK distribution network connections specialist. "
        "Analyse NGED substation headroom data to identify the best connection "
        "opportunities for solar PV. Consider transformer capacity, existing load, "
        "available headroom, voltage level, and proximity to the proposed site. "
        "Rank substations by connection attractiveness."
    ),
    "satellite_analysis": (
        "You are a geospatial intelligence analyst specialising in renewable energy "
        "site assessment using satellite Earth observation data. Analyse DynamicWorld "
        "land cover, terrain (NASADEM), solar resource (ERA5), and vegetation (Sentinel-2 NDVI) "
        "to assess site suitability for solar PV, battery storage, or wind development. "
        "Provide a composite suitability score and GO / CAUTION / NO-GO recommendation "
        "based on terrain feasibility, land use compatibility, solar resource quality, "
        "and environmental constraints."
    ),
    "legacy_compliance": (
        "You are a UK energy infrastructure asset management and compliance specialist. "
        "Assess legacy asset condition, regulatory compliance status, and lifecycle position. "
        "Evaluate repowering opportunities considering technology improvements since commissioning. "
        "Review planning consent conditions, environmental obligations (BNG, EIA monitoring), "
        "grid connection compliance (G99/G100), and health & safety requirements (CDM 2015). "
        "Identify decommissioning liabilities and estimate costs. Consider GeoAI satellite-derived "
        "condition indicators including vegetation encroachment, structural changes, and land use "
        "changes around the asset. Provide a GO / CAUTION / NO-GO verdict on continued operation "
        "with clear compliance remediation actions."
    ),
    "procurement": (
        "You are a UK energy procurement strategist specialising in tender analysis and bid strategy. "
        "Assess tender viability considering technology match, contract value, deadline, site suitability, "
        "grid capacity, and planning history. Classify tenders by energy technology (solar PV, battery storage, "
        "wind, EV charging, etc.) and match to available sites. Analyse cost benchmarks against tender values. "
        "Provide STRONG_BID / CONDITIONAL_BID / NO_BID recommendation with supporting factors."
    ),
    "grid_efficiency": (
        "You are a UK power systems engineer specialising in grid efficiency and network optimisation. "
        "Analyse transmission and distribution losses by voltage level, identify congested lines, "
        "assess substation health and utilisation. Recommend grid upgrade interventions (line reinforcement, "
        "BESS peak shaving) with cost-benefit analysis and payback periods. Consider satellite-derived "
        "infrastructure condition where available."
    ),
    "site_prospecting": (
        "You are a UK renewable energy site acquisition specialist. "
        "Identify and rank new sites for solar PV, wind, or battery storage development using "
        "multi-criteria analysis: solar/wind resource quality, terrain suitability, land use compatibility, "
        "grid access (substation proximity and headroom), and planning/environmental constraints. "
        "Provide HIGH_PRIORITY / PROMISING / MARGINAL / UNSUITABLE recommendations with composite scores."
    ),
    "bess_optimisation": (
        "You are a UK battery energy storage system (BESS) specialist. "
        "Assess site suitability for BESS deployment considering grid connection capacity, "
        "land availability, and planning constraints. Calculate optimal sizing (MW/MWh) "
        "based on UK revenue opportunities: frequency response (FFR/DC/DM), capacity market, "
        "arbitrage (Agile/wholesale), and DNO peak shaving. Model revenue stacking, financial "
        "returns (NPV, IRR, payback), degradation impacts, and co-location benefits with solar PV. "
        "Provide a GO / CAUTION / NO-GO verdict with confidence score."
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

The "actions" array should be EMPTY — actions are generated server-side.
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

        # Always use validated actions — Claude hallucinates endpoints
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
    loc = ctx.get("location", {})
    lat = loc.get("lat", ctx.get("lat", 52.5))
    lon = loc.get("lon", ctx.get("lon", -1.5))
    actions = []

    if intent == "feasibility":
        actions = [
            {
                "label": "Request Grid Connection Quote",
                "endpoint": "/job/grid_study",
                "method": "POST",
                "payload": {"parcel_id": pid, "capacity_kw": cap},
            },
            {
                "label": "Initiate Planning Pre-App",
                "endpoint": f"/site/{pid}/agent",
                "method": "POST",
                "payload": {"intent": "planning", "capacity_kw": cap},
            },
            {
                "label": "Generate Financial Model",
                "endpoint": f"/site/{pid}/agent",
                "method": "POST",
                "payload": {"intent": "financial", "capacity_kw": cap},
            },
            {
                "label": "Generate Bill of Materials",
                "endpoint": f"/site/{pid}/bom?capacity_kw={cap}",
                "method": "GET",
                "payload": {},
            },
        ]
    elif intent == "grid_study":
        load_mw = cap / 1000
        actions = [
            {
                "label": "Run Deferral Optimiser",
                "endpoint": f"/opt/run?plan_name=agent_grid&load_mw={load_mw}&gen_mw={load_mw}",
                "method": "POST",
                "payload": {},
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
    elif intent == "grid_opportunity":
        actions = [
            {
                "label": "View NGED Substations",
                "endpoint": "/nged/summary",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Find Opportunities Near Site",
                "endpoint": "/nged/opportunities?west=-3&south=51&east=-2&north=52&min_headroom_mw=1",
                "method": "GET",
                "payload": {},
            },
        ]
    elif intent == "satellite_analysis":
        actions = [
            {
                "label": "Run Satellite Analysis",
                "endpoint": "/job/geeflow_analysis",
                "method": "POST",
                "payload": {"lat": lat, "lon": lon, "radius_km": 5,
                            "modes": ["land_use", "terrain", "solar_resource", "vegetation"]},
            },
        ]

    elif intent == "legacy_compliance":
        actions = [
            {
                "label": "Run GeoAI Asset Condition Scan",
                "endpoint": f"/geoai/analyse?lat={lat}&lon={lon}&mode=asset_condition",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Query Legacy Assets Near Site",
                "endpoint": f"/legacy/assets?lat={lat}&lon={lon}&radius_km=10",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Run Compliance Check",
                "endpoint": f"/legacy/compliance?asset_type=solar_farm&capacity_kw={cap}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "View Planning Applications",
                "endpoint": "/planning/energy/summary",
                "method": "GET",
                "payload": {},
            },
        ]

    elif intent == "procurement":
        actions = [
            {
                "label": "View Procurement Pipeline",
                "endpoint": "/procurement/pipeline",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Get Cost Benchmarks",
                "endpoint": "/procurement/cost-benchmarks",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Score Candidate Site",
                "endpoint": f"/prospector/score?lat={lat}&lon={lon}&technology=solar",
                "method": "GET",
                "payload": {},
            },
        ]

    elif intent == "grid_efficiency":
        actions = [
            {
                "label": "Estimate Line Losses",
                "endpoint": "/grid-efficiency/line-losses",
                "method": "POST",
                "payload": {"distance_km": 10, "voltage_kv": 132, "load_mw": 10},
            },
            {
                "label": "Assess Substation Health",
                "endpoint": "/grid-efficiency/substation-health",
                "method": "POST",
                "payload": {"substations": []},
            },
            {
                "label": "View NGED Substations",
                "endpoint": "/nged/summary",
                "method": "GET",
                "payload": {},
            },
        ]

    elif intent == "site_prospecting":
        actions = [
            {
                "label": "Score This Site",
                "endpoint": f"/prospector/score?lat={lat}&lon={lon}&technology=solar",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Scan Region for Sites",
                "endpoint": "/prospector/scan?region=south_west&technology=solar&grid_points=25",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Find Similar Sites",
                "endpoint": f"/prospector/similar?lat={lat}&lon={lon}&radius_km=50&technology=solar",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "View UK Regions",
                "endpoint": "/prospector/regions",
                "method": "GET",
                "payload": {},
            },
        ]

    elif intent == "bess_optimisation":
        actions = [
            {
                "label": "Score Site for BESS",
                "endpoint": f"/bess/score?lat={lat}&lon={lon}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Calculate Optimal Sizing",
                "endpoint": "/bess/sizing",
                "method": "POST",
                "payload": {"capacity_mw": 50, "revenue_strategy": "hybrid", "grid_constraint_mw": 100},
            },
            {
                "label": "Model Revenue Stacking",
                "endpoint": "/bess/revenue",
                "method": "POST",
                "payload": {"power_mw": 50, "energy_mwh": 100, "strategy": "hybrid"},
            },
            {
                "label": "Assess Co-location with Solar",
                "endpoint": f"/bess/colocation?solar_kw={cap}&lat={lat}&lon={lon}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "View UK BESS Benchmarks",
                "endpoint": "/bess/benchmarks",
                "method": "GET",
                "payload": {},
            },
        ]

    # Add satellite analysis as secondary action for feasibility and grid_opportunity
    if intent in ("feasibility", "grid_opportunity"):
        actions.append({
            "label": "Run Satellite Analysis",
            "endpoint": "/job/geeflow_analysis",
            "method": "POST",
            "payload": {"lat": lat, "lon": lon, "radius_km": 5,
                        "modes": ["land_use", "terrain", "solar_resource", "vegetation"]},
        })

    return actions
