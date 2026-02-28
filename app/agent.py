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

# Cross-cutting data domains that should be considered in holistic analyses.
# Injected into feasibility + other intent prompts so every AI report reflects
# all 8 assessment dimensions from the site dashboard.
DATA_DOMAINS_CONTEXT = """\
When analysing this site you MUST consider ALL of the following data domains
and explicitly reference any that materially affect your verdict:

1. DNO INFRASTRUCTURE — Substation headroom (MW available vs requested),
   cable route distance (km), connection voltage level, estimated connection
   cost (£), reinforcement requirements, and DNO licence area.

2. TOPOGRAPHY — Elevation (m AOD), slope gradient (°), aspect (compass bearing),
   terrain roughness, and suitability for ground-mount solar or BESS foundations.
   Flag slopes >10° as potentially requiring earthworks.

3. SOLAR RESOURCE — Annual GHI (kWh/m²), capacity factor (%), hourly generation
   profile, clearness index, diffuse fraction, and seasonal variation.
   Reference PvWattsv8 or ERA5 data where provided.

4. AGRICULTURAL LAND CLASSIFICATION (ALC) — Grade (1-5 + urban/non-agricultural).
   Grades 1-3a are "Best and Most Versatile" (BMV) — development on BMV land
   is a material planning consideration under NPPF. Flag if site is Grade 1-3a.

5. ADMINISTRATIVE BOUNDARIES — Local planning authority, county, region,
   DNO licence area, electricity supply zone. Note any special planning
   designations (National Park, AONB, Green Belt, Heritage Coast).

6. NEIGHBOURING PROJECTS — Nearby operational/consented/in-planning solar farms,
   wind farms, BESS, and EV charging sites within 5 km. Assess cumulative
   landscape impact and grid capacity competition.

7. FLOOD ZONES — Environment Agency Flood Zones 1-3, JRC Global Surface Water
   occurrence/seasonality, surface water flood risk. Solar PV in Flood Zone 3b
   (functional floodplain) is generally unacceptable. Flood Zone 2-3a requires
   Sequential and Exception Tests.

8. PROTECTED AREAS & EXCLUSION ZONES — SSSI, SAC, SPA, Ramsar, AONB,
   National Parks, Ancient Woodland, Scheduled Monuments, Listed Buildings,
   Green Belt, MOD safeguarding zones, airport safeguarding. Any overlap
   is a significant constraint that must be flagged.

9. VISION AI — AI-analysed imagery from satellite, drone, or aerial sources.
   Suitability score (0-100), terrain flatness, shading risk, access routes,
   flood indicators, vegetation density, infrastructure presence, usable area %.
   Reference vision findings for ground-truth confirmation of other data sources.

If specific data for a domain is absent from the input, state this explicitly
(e.g. "ALC data not provided — recommend obtaining before planning submission").
"""

# Intent → system prompt fragments
INTENT_PROMPTS: dict[str, str] = {
    "feasibility": (
        "You are a senior solar energy feasibility analyst. "
        "Evaluate whether this site is suitable for a solar PV installation. "
        "Your assessment must be holistic, covering all 8 data domains.\n\n"
        + DATA_DOMAINS_CONTEXT +
        "\nProvide a GO / CAUTION / NO-GO verdict with confidence score."
    ),
    "grid_study": (
        "You are a UK Distribution Network Operator (DNO) connections engineer. "
        "Assess grid connection feasibility: substation headroom, cable distance, "
        "reinforcement needs, connection cost estimate, and timeline.\n\n"
        + DATA_DOMAINS_CONTEXT
    ),
    "grid_connection": (
        "You are a senior UK grid connection analyst specialising in DNO and "
        "transmission connections for renewable energy and BESS projects. "
        "Analyse the grid connection assessment data provided and give a "
        "comprehensive verdict covering:\n\n"
        "1. SUBSTATION ANALYSIS — Evaluate each candidate substation's headroom "
        "(demand and generation), fault level capacity, transformer rating, and "
        "RAG status. Identify the optimal connection point.\n\n"
        "2. QUEUE ASSESSMENT — Analyse the connection queue depth at each "
        "substation. Quantify queued MW from ECR and TEC registers. Assess "
        "risk of queue competition consuming available headroom.\n\n"
        "3. CONNECTION COST — Review the P10/P50/P90 cost estimate breakdown "
        "(cable, switchgear, transformer, DNO fees, reinforcement, civils). "
        "Flag if costs are disproportionate to project value.\n\n"
        "4. TIMELINE — Assess connection timeline (G98/G99/formal application), "
        "DNO study timescales, and construction programme. Flag NESO Connections "
        "Reform implications (milestone-based queue management).\n\n"
        "5. VOLTAGE STRATEGY — Recommend optimal connection voltage considering "
        "capacity, distance, losses, and future expansion.\n\n"
        "6. REINFORCEMENT RISK — Assess likelihood of DNO requiring network "
        "reinforcement (upstream transformer upgrade, switchgear replacement, "
        "protection changes, cable replacement). Estimate cost and delay impact.\n\n"
        "7. ALTERNATIVES — If the primary connection point has constraints, "
        "recommend alternative substations, flexible connection arrangements, "
        "or curtailment-based solutions (Active Network Management).\n\n"
        "Reference specific substation names, MW figures, distances, and costs "
        "from the data. Provide GO/CAUTION/NO-GO verdict with confidence."
    ),
    "financial": (
        "You are a renewable energy project finance analyst. "
        "Calculate ROI, LCOE, payback period, revenue scenarios (SEG, PPA, merchant), "
        "and financing options for the proposed solar installation."
    ),
    "environmental": (
        "You are an environmental impact assessment specialist. "
        "Evaluate ecological constraints: flood risk from JRC satellite data (water occurrence, "
        "seasonality, risk classification), AONB/SSSI designations, biodiversity net gain requirements, "
        "and mitigation measures. Assess vegetation trend analysis using multi-year NDVI stability "
        "(greening/browning/stable trends), and enhanced change detection confidence for land use "
        "compliance monitoring.\n\n"
        + DATA_DOMAINS_CONTEXT
    ),
    "planning": (
        "You are a UK planning consultant specialising in renewable energy. "
        "Assess planning permission likelihood, relevant NPPF policies, "
        "local plan alignment, and pre-application strategy.\n\n"
        + DATA_DOMAINS_CONTEXT
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
        "site assessment using satellite Earth observation and deep learning. Analyse DynamicWorld "
        "land cover, terrain (NASADEM), solar resource (ERA5), vegetation (Sentinel-2 NDVI), "
        "SAR backscatter (Sentinel-1 all-weather ground conditions), flood risk (JRC Global Surface Water), "
        "and NDVI timeseries (multi-year vegetation stability). Leverage deep learning capabilities: "
        "OmniCloudMask cloud-free assessment, OpenSR super-resolution imagery, Prithvi foundation "
        "embeddings for site fingerprinting, GroundedSAM infrastructure detection, and torchange "
        "enhanced change detection. Provide a composite suitability score and GO / CAUTION / NO-GO "
        "recommendation based on terrain feasibility, land use compatibility, solar resource quality, "
        "flood risk, ground conditions, and environmental constraints.\n\n"
        + DATA_DOMAINS_CONTEXT
    ),
    "legacy_compliance": (
        "You are a UK energy infrastructure asset management and compliance specialist. "
        "Assess legacy asset condition, regulatory compliance status, and lifecycle position. "
        "Evaluate repowering opportunities considering technology improvements since commissioning. "
        "Review planning consent conditions, environmental obligations (BNG, EIA monitoring), "
        "grid connection compliance (G99/G100), and health & safety requirements (CDM 2015). "
        "Identify decommissioning liabilities and estimate costs. Leverage GroundedSAM infrastructure "
        "detection for pylon/substation/panel identification, and torchange enhanced change detection "
        "for construction/demolition/vegetation/surface change categorisation. Consider GeoAI satellite-derived "
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
        "Leverage Prithvi EO embedding-based similarity search and multi-modal site fingerprinting "
        "(Prithvi + DINOv3 + scalar features) for finding sites with similar characteristics. "
        "Consider temporal NDVI stability scoring for land use risk assessment. "
        "Provide HIGH_PRIORITY / PROMISING / MARGINAL / UNSUITABLE recommendations with composite scores.\n\n"
        + DATA_DOMAINS_CONTEXT
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
    "land_classification": (
        "You are a geospatial land use classification specialist for UK energy infrastructure. "
        "Analyse the enriched 21-class land use classification (based on UC Merced taxonomy) to "
        "assess site composition, identify areas suitable for solar PV, BESS, EV charging, and "
        "other energy infrastructure retrofitting. Evaluate building types and densities for "
        "rooftop solar potential. Analyse land use change trends and forecast future development "
        "pressure. Provide a GO / CAUTION / NO-GO verdict on retrofitting potential."
    ),
    "home_retrofit": (
        "You are a UK residential retrofit design specialist and chartered building surveyor. "
        "Assess the property for retrofit potential using case-based reasoning: match to similar "
        "approved projects, generate retrofit option packages (extensions, insulation, solar PV, "
        "heat pumps), estimate costs using 2024/25 benchmarks, and classify planning routes under "
        "GPDO 2015. Consider house archetype (Victorian terrace, 1930s semi, etc.), current EPC "
        "rating, wall construction, heating system, and planning constraints (conservation area, "
        "listed building). Provide packages ranked from Quick Wins to Full Retrofit with energy "
        "modelling (SAP-lite), CO2 savings, EPC band improvement, and planning precedent references. "
        "Assess heat pump suitability (ASHP/GSHP) including BUS grant eligibility. "
        "Provide a GO / CAUTION / NO-GO verdict on retrofit viability with confidence score."
    ),
    "infrastructure_retrofit": (
        "You are an EU energy infrastructure retrofitting specialist aligned with HORIZON Europe "
        "call HORIZON-CL5-2027-07-D3-27 and the BRIDGE initiative. Assess the feasibility of "
        "retrofitting obsolete infrastructure (dams, power plants, mines, industrial sites, fossil "
        "fuel infrastructure) with energy storage technologies (pumped hydro, CAES, gravity, BESS, "
        "flow batteries, thermal, hydrogen, flywheels). Evaluate cost-effectiveness comparing "
        "retrofit vs greenfield, circularity and EU Battery Regulation 2023/1542 compliance, grid "
        "flexibility contribution (frequency response, capacity firming, arbitrage), environmental "
        "and social sustainability (brownfield remediation, just transition, community benefit), and "
        "NIS2 secure-by-design compliance. Minimise disruption through phased construction planning. "
        "Reference BRIDGE initiative KPIs and EU Taxonomy Activity 4.10 criteria. Provide a GO / "
        "CAUTION / NO-GO verdict with confidence score."
    ),
    "regulatory_intelligence": (
        "You are a UK energy regulatory intelligence analyst specialising in the renewables "
        "planning and grid connection landscape. Analyse the REPD (Renewable Energy Planning "
        "Database), ESO TEC register, DNO investment plans, and Ofgem regulatory decisions. "
        "Assess: (1) nearby competing projects within 10km — their status, capacity, and "
        "developer, (2) grid connection queue depth and expected connection dates at the "
        "nearest substation, (3) planned DNO upgrades that could ease constraints or release "
        "capacity, (4) relevant Ofgem decisions and consultations that impact the project. "
        "Cross-reference NGED CIM headroom with TEC queue to identify real available capacity. "
        "Provide a GO / CAUTION / NO-GO verdict with confidence score.\n\n"
        + DATA_DOMAINS_CONTEXT
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
                "label": "Run Full Satellite Analysis",
                "endpoint": "/job/geeflow_analysis",
                "method": "POST",
                "payload": {"lat": lat, "lon": lon, "radius_km": 5,
                            "modes": ["land_use", "terrain", "solar_resource", "vegetation",
                                      "sar_backscatter", "flood_risk", "ndvi_timeseries"]},
            },
            {
                "label": "Cloud Assessment",
                "endpoint": f"/geoai/analyse?lat={lat}&lon={lon}&mode=cloud_mask",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Generate Embeddings",
                "endpoint": f"/geoai/analyse?lat={lat}&lon={lon}&mode=foundation_embeddings",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Detect Infrastructure",
                "endpoint": f"/geoai/analyse?lat={lat}&lon={lon}&mode=infrastructure_detect",
                "method": "GET",
                "payload": {},
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

    elif intent == "grid_connection":
        actions = [
            {
                "label": "View Capacity Map",
                "endpoint": "/api/grid/capacity-map",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Check Connection Queue",
                "endpoint": f"/api/grid/queue?substation_name={ctx.get('best_substation', '')}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Run Financial Model",
                "endpoint": f"/site/{pid}/agent",
                "method": "POST",
                "payload": {"intent": "financial", "capacity_kw": cap},
            },
            {
                "label": "Run Satellite Analysis",
                "endpoint": "/job/geeflow_analysis",
                "method": "POST",
                "payload": {"lat": lat, "lon": lon, "radius_km": 5,
                            "modes": ["land_use", "terrain", "solar_resource"]},
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
                "label": "Find Similar Sites (Embedding)",
                "endpoint": f"/prospector/similar?lat={lat}&lon={lon}&radius_km=50&technology=solar",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Generate Site Caption",
                "endpoint": f"/geoai/analyse?lat={lat}&lon={lon}&mode=site_caption",
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

    elif intent == "land_classification":
        actions = [
            {
                "label": "Run Land Classification",
                "endpoint": f"/classify/land-use?lat={lat}&lon={lon}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "View Map Overlay",
                "endpoint": f"/classify/map-overlay?lat={lat}&lon={lon}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Assess Retrofitting",
                "endpoint": f"/classify/retrofitting?lat={lat}&lon={lon}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Forecast Land Use",
                "endpoint": f"/classify/forecast?lat={lat}&lon={lon}",
                "method": "GET",
                "payload": {},
            },
        ]

    elif intent == "home_retrofit":
        actions = [
            {
                "label": "Assess Home Retrofit",
                "endpoint": "/home-retrofit/assess",
                "method": "POST",
                "payload": {"house_type": "1930s_semi", "plot_width_m": 8.0, "plot_depth_m": 25.0,
                            "epc_rating": "D", "lat": lat, "lon": lon},
            },
            {
                "label": "View House Archetypes",
                "endpoint": "/home-retrofit/archetypes",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "View Interventions & Costs",
                "endpoint": "/home-retrofit/interventions",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Find Local Precedents",
                "endpoint": f"/home-retrofit/precedents/{pid}",
                "method": "GET",
                "payload": {},
            },
        ]

    elif intent == "infrastructure_retrofit":
        actions = [
            {
                "label": "Assess Retrofit Feasibility",
                "endpoint": "/retrofit/assess",
                "method": "POST",
                "payload": {"infrastructure_type": "coal_power_plant", "storage_technology": "li_ion_bess",
                            "capacity_mw": cap / 1000 if cap > 100 else 50},
            },
            {
                "label": "Match Storage Technologies",
                "endpoint": "/retrofit/match-storage",
                "method": "POST",
                "payload": {"infrastructure_type": "coal_power_plant", "capacity_mw": cap / 1000 if cap > 100 else 50},
            },
            {
                "label": "Generate Disruption Plan",
                "endpoint": "/retrofit/disruption-plan",
                "method": "POST",
                "payload": {"infrastructure_type": "coal_power_plant", "storage_technology": "li_ion_bess",
                            "capacity_mw": cap / 1000 if cap > 100 else 50},
            },
            {
                "label": "View Storage Technologies",
                "endpoint": "/retrofit/technologies",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Circularity Assessment",
                "endpoint": "/retrofit/circularity",
                "method": "POST",
                "payload": {"infrastructure_type": "coal_power_plant", "storage_technology": "li_ion_bess",
                            "capacity_mw": cap / 1000 if cap > 100 else 50},
            },
        ]

    elif intent == "regulatory_intelligence":
        actions = [
            {
                "label": "View REPD Projects Near Site",
                "endpoint": f"/tracker/repd?lat={lat}&lon={lon}&radius_km=10",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Check Connection Queue",
                "endpoint": "/tracker/tec/summary",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "View DNO Investment Plans",
                "endpoint": "/tracker/dno-investment",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Search Regulatory Decisions",
                "endpoint": "/rag/query",
                "method": "POST",
                "payload": {"query": "grid connection reform"},
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


async def enrich_context_with_trackers(conn, context: dict) -> dict:
    """Inject nearby REPD projects and TEC queue data for relevant intents."""
    from utils.repd_tracker import query_repd
    from utils.eso_tec_register import query_tec

    loc = context.get("location", {})
    lat = loc.get("lat", context.get("lat"))
    lon = loc.get("lon", context.get("lon"))
    if lat is None or lon is None:
        return context

    enriched = {**context}

    try:
        nearby_repd = await query_repd(conn, lat=lat, lon=lon, radius_km=10, limit=10)
        if nearby_repd:
            enriched["nearby_repd_projects"] = [
                {
                    "site_name": r.get("site_name"),
                    "tech_category": r.get("tech_category"),
                    "capacity_mw": r.get("capacity_mw"),
                    "status": r.get("status"),
                    "developer": r.get("developer"),
                }
                for r in nearby_repd
            ]
    except Exception as e:
        log.debug("REPD enrichment failed: %s", e)

    try:
        nearby_tec = await query_tec(conn, lat=lat, lon=lon, radius_km=25, limit=10)
        if nearby_tec:
            enriched["nearby_tec_entries"] = [
                {
                    "connection_site": r.get("connection_site"),
                    "tech_category": r.get("tech_category"),
                    "tec_mw": r.get("tec_mw"),
                    "status": r.get("status"),
                }
                for r in nearby_tec
            ]
    except Exception as e:
        log.debug("TEC enrichment failed: %s", e)

    return enriched
