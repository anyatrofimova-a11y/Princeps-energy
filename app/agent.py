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

10. ENERGY MARKET DATA — Carbon intensity (gCO2/kWh, current and forecast),
    marginal emission factors (elmada MEF), wholesale electricity prices (EUR/MWh),
    generation fuel mix, system demand outturn (BMRS), and capacity factors from
    Renewables.ninja. Use these to assess revenue potential, carbon avoidance value,
    and grid decarbonisation contribution.

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
    "connection_strategy": (
        "You are a UK grid connection strategy specialist advising energy developers. "
        "Evaluate connection options (firm, ANM, non-firm, timed export, intertrip) and "
        "recommend the optimal strategy based on multi-criteria analysis: NPV, curtailment "
        "risk, timeline, DLR uplift potential, and flexibility value. Assess annual curtailment "
        "estimates (P10/P50/P90), revenue impact over project lifetime, flexible connection "
        "trade-offs, and milestone-based connection timelines with critical path risks. "
        "Reference NESO Connections Reform, G99/CUSC processes, DNO queue positions, and "
        "UK wholesale price assumptions. Provide GO / CAUTION / NO-GO verdict with confidence."
    ),
    "monitoring_kit": (
        "You are a UK energy infrastructure IoT monitoring specialist. "
        "Recommend a modular sensor monitoring kit for the site based on its type, "
        "capacity, and environmental conditions. Consider IEC 61724 compliance for "
        "solar, NFPA 855 for BESS, IEC 61400-12 for wind. Specify sensor types "
        "(pyranometers, weather stations, power meters, thermal cameras, environmental "
        "sensors), quantities, communication protocols (MQTT, Modbus, LoRaWAN), and "
        "edge gateway requirements. Include bankability requirements for pre-construction "
        "resource assessment. Estimate total monitoring kit cost and ongoing O&M. "
        "Provide GO / CAUTION / NO-GO verdict on monitoring readiness."
    ),
    "advanced_grid": (
        "You are a UK transmission and distribution grid analysis specialist. "
        "Analyse dynamic line ratings (IEEE 738 thermal model), transmission boundary "
        "congestion probabilities, multi-objective connection point optimisation, and "
        "reinforcement cost estimates. Evaluate DLR uplift potential under current weather "
        "conditions, identify congested boundaries (Scotland-England, North-Midlands, etc.), "
        "recommend optimal connection points from the Pareto frontier balancing distance, cost, "
        "and queue wait, and provide Monte Carlo P10/P50/P90 reinforcement cost breakdowns. "
        "Reference specific conductors (Lynx/Zebra/Rubus), boundary loading percentages, "
        "and cost components. Provide a GO / CAUTION / NO-GO verdict with confidence score."
    ),
    "route_to_market": (
        "You are a UK energy route-to-market specialist advising renewable energy developers. "
        "Evaluate PPA structures (fixed, CPI-indexed, floor/cap, baseload, as-generated, synthetic/virtual), "
        "calculate optimal PPA pricing considering capture price discounts, cannibalisation effects, and "
        "seasonal shaping. Match generation assets to corporate offtake buyers (data centres, industrial, "
        "commercial, public sector, EV charging) based on demand-generation correlation and credit quality. "
        "Compare market routes (merchant, CfD, corporate PPA, sleeved PPA, synthetic PPA, private wire) "
        "across multi-criteria scoring (NPV, revenue certainty, bankability). Assess project bankability "
        "using Monte Carlo revenue-at-risk (P10/P50/P90), DSCR analysis, sensitivity tornado charts, and "
        "risk registers covering construction/market/operational/regulatory/financial risks. "
        "Provide GO / CAUTION / NO-GO verdict with investment grade scoring."
    ),
    "sustainability": (
        "You are a UK renewable energy sustainability and lifecycle specialist. "
        "Calculate lifecycle carbon footprints (construction, operation, decommissioning) and compare "
        "against grid average, gas CCGT, and coal benchmarks. Assess grid carbon displacement using "
        "marginal intensity by UK region. Score projects across ESG pillars (Environmental, Social, "
        "Governance) with AAA-B ratings. Analyse multi-site portfolio diversification using Markowitz "
        "variance, Herfindahl concentration, and technology-region correlation matrices. Model community "
        "benefit packages (BEIS/DESNZ fund rates, shared ownership structures, TOMS social value). "
        "Estimate decommissioning costs, material recovery credits, repowering vs new-build NPV, and "
        "bond/escrow sizing. Provide GO / CAUTION / NO-GO verdict with ESG rating."
    ),
    "dispatch_optimisation": (
        "You are a UK energy dispatch optimisation specialist. "
        "Forecast grid constraints across transmission boundaries (Scotland-England, North-Midlands, etc.) "
        "24-48 hours ahead using weather, demand, and generation profiles. Generate optimal dispatch schedules "
        "for generation and BESS assets — balancing wholesale arbitrage, frequency response (FFR/DC/DM), "
        "constraint-aware export, and Balancing Mechanism participation. Model BOA acceptance profiles, "
        "SBP/SSP system prices, constraint payments, and multi-market revenue stacking (wholesale, CfD, "
        "capacity market, frequency response, BM, embedded benefits, Triad avoidance). "
        "Provide GO / CAUTION / NO-GO verdict on dispatch strategy with confidence score."
    ),
    "council_search": (
        "You are a UK planning intelligence analyst specialising in local government "
        "decision-making on energy infrastructure. Analyse council meeting transcripts "
        "to identify discussions about solar farms, wind farms, battery storage, "
        "substations, grid connections, and planning applications. Summarise the "
        "political sentiment (supportive, neutral, hostile) towards renewable energy "
        "in each authority. Flag specific objections raised (landscape, noise, glint, "
        "traffic, heritage, ecology, agricultural land). Identify planning committee "
        "members who are influential on energy decisions. Cross-reference with "
        "REPD/NSIP data to correlate council discussions with actual planning outcomes. "
        "Provide a GO / CAUTION / NO-GO verdict on the local planning environment "
        "for the proposed energy project."
    ),
    "demand_forecast": (
        "You are a UK electricity demand forecasting specialist. "
        "Analyse historical demand patterns at Grid Supply Points (GSPs), generate probabilistic "
        "short-term forecasts (P10/P50/P90 bands) and long-term scenario projections using NESO "
        "Future Energy Scenarios (Leading the Way, Consumer Transformation, System Transformation, "
        "Falling Short). Assess capacity exceedance probability, time-to-constraint, and the impact "
        "of new loads (EVs, heat pumps, data centres) on local demand growth. Recommend demand-side "
        "interventions and reinforcement timing."
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
    "investment_readiness": (
        "You are a UK renewable energy investment analyst and project finance specialist. "
        "Build a 25-year project finance model with levered/unlevered cashflows, WACC, IRR "
        "(project and equity, pre/post-tax), NPV at multiple discount rates, LCOE, and simple "
        "payback. Structure senior debt with sculpted repayment at target DSCR (1.3x), calculate "
        "gearing, lock-up/default covenants, and assess covenant headroom. Model equity returns "
        "including dividend waterfall (EBITDA → debt service → tax → dividend → retention). "
        "Run Monte Carlo sensitivity (2000 sims, correlated inputs via Cholesky decomposition) "
        "and tornado stress tests across 6 variables. Score due diligence across 4 pillars "
        "(Technical, Commercial, Legal, Financial) with RAG ratings. Generate investment memo "
        "with INVEST / CONDITIONAL / DECLINE verdict, 5x5 risk matrix, and phased action plan "
        "to financial close. Provide GO / CAUTION / NO-GO verdict with confidence score."
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
    "dc_colocation": (
        "You are a UK data centre site selection specialist assessing co-location suitability. "
        "Evaluate 15 dimensions: (1) Power Capacity — nearest substation voltage tier and "
        "transformer rating match for requested IT load, (2) Grid Headroom — REAL demand "
        "headroom from DNO data (not N/A), RAG status, queue depth, (3) Fibre Proximity — "
        "distance to nearest telecom exchange/POP, (4) IXP Proximity — distance to nearest "
        "Internet Exchange Point (LINX, LONAP, etc.), (5) Water Cooling — distance to rivers/"
        "reservoirs for cooling, (6) Latency — composite IXP + population centre + fibre "
        "propagation model, (7) Land & Planning — brownfield bonus, flood risk, planning "
        "constraints, (8) Resilience — dual-feed capability, independent substations at "
        "different voltage tiers, (9) Connection Speed — fibre provider count, dark fibre, "
        "carrier-neutral exchanges, (10) 24/7 CFE% — carbon-free energy percentage using "
        "Carbon Intensity API + nearby REPD wind/solar for PPA overlay (Google targets 95%), "
        "(11) Cooling & Climate — PUE/WUE estimation, free cooling hours, UKCP18 projections, "
        "(12) Constraint Clearance — SSSI/SAC/SPA/Ramsar/AONB/Green Belt/ALC exclusion zones, "
        "(13) Water Stress — EA CAMS catchment status for cooling strategy (Google water-positive "
        "by 2030), (14) Incentives — Enterprise Zones, Freeports, AI Growth Zones, Investment "
        "Zones with rates relief and capital allowances, (15) Regulatory Pathway — NSIP "
        "eligibility (opt-in above 50MW), TM04+ gate status, planning authority track record. "
        "Apply facility profile weights: google_hyperscale (100-500MW, CFE-focused), "
        "Hyperscale/Colocation/Edge and gate thresholds. Our KEY advantage: REAL MW headroom "
        "from all 6 UK DNOs + 24/7 CFE% scoring — no competitor integrates both. Reference "
        "specific substations, distances, headroom, costs, CFE%, and PUE. Provide GO / "
        "CAUTION / NO-GO verdict with confidence."
    ),
    "dc_comparison": (
        "You are a UK data centre site comparison specialist. Compare multiple candidate sites "
        "across all 15 scoring dimensions. For each site, provide the DC-SCORE, verdict, and "
        "key differentiators. Identify which site wins on each dimension. Highlight trade-offs "
        "(e.g. Site A has better CFE% but Site B has lower connection cost). Recommend the "
        "overall best site with justification. Reference Google's UK known sites (Waltham Cross, "
        "North Weald, Purfleet, Teesside) as benchmarks where relevant."
    ),
    "dc_prospecting": (
        "You are a UK data centre site discovery specialist. Find candidate sites matching "
        "specified criteria (capacity, CFE%, cooling, constraints, incentives). Use grid headroom "
        "data from all 6 UK DNOs to identify substations with sufficient capacity. Rank results "
        "by 15-dimension DC-SCORE. Highlight Enterprise Zones, Freeports, and AI Growth Zones. "
        "Reference Google's target criteria: 100-500MW, 95% CFE, water-positive, low PUE."
    ),
    "site_layout": (
        "You are a senior UK data centre, BESS, and solar site engineer explaining the reasoning "
        "behind an auto-generated site layout. Given the candidate site (lat, lon, area_ha, "
        "headroom_mw) and workload (technology: dc, bess, or solar; capacity_mw; duration_h for "
        "BESS; pad_count or hall_count), explain the layout rationale in 3-6 short engineering "
        "bullets. No preamble, no marketing language, no markdown tables. Cover: pad/hall count "
        "sizing vs modular commissioning, orientation (DC halls aligned to prevailing wind for "
        "free-cooling; BESS rows N-S for fire-access alleys; solar azimuth 180 deg), fire "
        "setbacks (NFPA 855 / BS 8629:2019: 3m inter-unit Li-ion, 6m property line; BS 9999 "
        "for DC), cable routing (shortest MV run to substation, avoid road crossings), and "
        "interaction with site constraints (slope >10 deg earthworks, flood zone exclusion, "
        "ALC 1-3a avoidance, ancient woodland / SSSI buffers). Reference the headroom_mw vs "
        "capacity_mw ratio when sizing the connection — flag if >0.8 utilisation. End with a "
        "GO/CAUTION/NO-GO verdict on the layout as proposed."
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


async def _persist_analysis(pool, context: dict, intent: str, result: dict,
                            model: str, input_tokens: int | None,
                            output_tokens: int | None, elapsed: float) -> None:
    """Write agent analysis to agent_analyses table (best-effort)."""
    try:
        from uuid import UUID as _UUID
        parcel_id = None
        pid_str = context.get("parcel_id")
        if pid_str:
            try:
                parcel_id = _UUID(str(pid_str))
            except (ValueError, TypeError):
                pass
        await pool.execute(
            """INSERT INTO agent_analyses
               (parcel_id, intent, verdict, confidence, summary,
                risks, opportunities, result_data, model,
                input_tokens, output_tokens, elapsed_s)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            parcel_id, intent,
            result.get("verdict", "CAUTION"),
            result.get("confidence", 0.5),
            result.get("summary", ""),
            json.dumps(result.get("risks", [])),
            json.dumps(result.get("opportunities", [])),
            json.dumps(result),
            model, input_tokens, output_tokens, elapsed,
        )
    except Exception as e:
        log.warning("Failed to persist agent analysis: %s", e)


async def run_structured_agent(
    client: anthropic.AsyncAnthropic,
    model: str,
    context: dict[str, Any],
    intent: str = "feasibility",
    max_tokens: int = 1200,
    pool=None,
) -> dict[str, Any]:
    """
    Run a structured agent analysis using Claude.

    Args:
        client: AsyncAnthropic client instance
        model: Claude model identifier
        context: dict of parcel/site data
        intent: one of INTENT_PROMPTS keys
        max_tokens: response length limit
        pool: optional asyncpg pool for persisting results

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

        input_tok = getattr(message.usage, "input_tokens", None)
        output_tok = getattr(message.usage, "output_tokens", None)

        _audit_log(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "intent": intent,
                "parcel_id": context.get("parcel_id"),
                "model": model,
                "elapsed_s": elapsed,
                "verdict": agent_output.get("verdict"),
                "confidence": agent_output.get("confidence"),
                "input_tokens": input_tok,
                "output_tokens": output_tok,
            }
        )

        # Persist to PostgreSQL (alongside NDJSON audit log)
        if pool is not None:
            await _persist_analysis(
                pool, context, intent, agent_output,
                model, input_tok, output_tok, elapsed,
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
            {
                "label": "Configure Monitoring Kit",
                "action": "open_panel",
                "panel": "hardware",
            },
            {
                "label": "Capacity Factor Map (atlite)",
                "endpoint": f"/api/resource/capacity-map?lon_min={lon - 0.5}&lat_min={lat - 0.5}&lon_max={lon + 0.5}&lat_max={lat + 0.5}&technology=pv",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Land Eligibility (GLAES)",
                "endpoint": f"/api/site/land-eligibility?lon_min={lon - 0.5}&lat_min={lat - 0.5}&lon_max={lon + 0.5}&lat_max={lat + 0.5}&technology=solar",
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
            {
                "label": "BESS Revenue Estimate",
                "endpoint": f"/api/bess/revenue-estimate?capacity_mwh={cap / 1000 * 2}&power_mw={cap / 1000}&year=2025",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Supply Curve (LCOE)",
                "endpoint": f"/api/site/supply-curve?lon_min={lon - 0.5}&lat_min={lat - 0.5}&lon_max={lon + 0.5}&lat_max={lat + 0.5}&technology=pv",
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
            {
                "label": "Search Council Discussions",
                "endpoint": "/api/council/search?q=solar+farm+planning",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Open Council Search",
                "action": "open_panel",
                "panel": "council_search",
            },
        ]

    elif intent == "council_search":
        actions = [
            {
                "label": "Search Council Transcripts",
                "endpoint": "/api/council/search?q=solar+farm",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Energy Discussion Summary",
                "endpoint": "/api/council/energy-summary",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "View Indexed Authorities",
                "endpoint": "/api/council/authorities",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Open Council Search Panel",
                "action": "open_panel",
                "panel": "council_search",
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
    elif intent == "monitoring_kit":
        cap_mw = cap / 1000
        actions = [
            {
                "label": "Configure Monitoring Kit",
                "endpoint": f"/hardware/recommend?site_type=solar_farm&capacity_mw={cap_mw}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "View Sensor Catalogue",
                "endpoint": "/hardware/catalogue",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Open Hardware Configurator",
                "action": "open_panel",
                "panel": "hardware",
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
                "label": "Run Power Flow",
                "endpoint": f"/api/grid/power-flow?lat={lat}&lon={lon}&capacity_mw={cap / 1000}&technology=solar",
                "method": "POST",
                "payload": {},
            },
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

    elif intent == "connection_strategy":
        actions = [
            {
                "label": "Generate Strategy Report",
                "endpoint": "/api/connection-strategy/strategy",
                "method": "POST",
                "payload": {"lat": lat, "lon": lon, "capacity_mw": cap / 1000, "technology": "solar", "headroom_mw": 30},
            },
            {
                "label": "Curtailment Estimate",
                "endpoint": f"/api/connection-strategy/curtailment/estimate?capacity_mw={cap / 1000}&region=Midlands",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Compare Flexible Options",
                "endpoint": "/api/connection-strategy/flexible/compare",
                "method": "POST",
                "payload": {"capacity_mw": cap / 1000, "headroom_mw": 30, "region": "Midlands"},
            },
            {
                "label": "Connection Timeline",
                "endpoint": "/api/connection-strategy/timeline/generate",
                "method": "POST",
                "payload": {"capacity_mw": cap / 1000, "voltage_kv": 132, "connection_type": "firm"},
            },
        ]

    elif intent == "advanced_grid":
        actions = [
            {
                "label": "Dynamic Line Rating",
                "endpoint": "/api/advanced-grid/dlr/rate?conductor=Zebra&ambient_temp_c=15&wind_speed_ms=3",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Congestion Forecast",
                "endpoint": "/api/advanced-grid/congestion/predict?hour=17&month=1&demand_gw=42&wind_gen_gw=8",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Optimise Connection",
                "endpoint": "/api/advanced-grid/optimise",
                "method": "POST",
                "payload": {"lat": lat, "lon": lon, "capacity_mw": cap / 1000, "technology": "solar"},
            },
            {
                "label": "Reinforcement Cost",
                "endpoint": f"/api/advanced-grid/reinforcement/estimate?distance_km=5&voltage_kv=132&capacity_mw={cap / 1000}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "View Boundaries",
                "endpoint": "/api/advanced-grid/congestion/boundaries",
                "method": "GET",
                "payload": {},
            },
        ]

    elif intent == "route_to_market":
        actions = [
            {
                "label": "Compare Market Routes",
                "endpoint": f"/api/rtm/routes/compare?capacity_mw={cap / 1000}&technology=wind&region=Scotland",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "PPA Structure Comparison",
                "endpoint": f"/api/rtm/ppa/structures?capacity_mw={cap / 1000}&technology=wind",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Match Offtake Buyers",
                "endpoint": f"/api/rtm/offtake/match?capacity_mw={cap / 1000}&technology=wind&region=Scotland",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Risk Assessment",
                "endpoint": f"/api/rtm/risk/assessment?capacity_mw={cap / 1000}&technology=wind&region=Scotland",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Bankability Report",
                "endpoint": f"/api/rtm/risk/bankability?capacity_mw={cap / 1000}&technology=wind&region=Scotland",
                "method": "GET",
                "payload": {},
            },
        ]

    elif intent == "sustainability":
        actions = [
            {
                "label": "Carbon Footprint",
                "endpoint": f"/api/sustainability/carbon/footprint?capacity_mw={cap / 1000}&technology=wind",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "ESG Score",
                "endpoint": f"/api/sustainability/esg/score?capacity_mw={cap / 1000}&technology=wind&region=Scotland",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Community Benefit Package",
                "endpoint": f"/api/sustainability/community/package?capacity_mw={cap / 1000}&technology=wind&region=Scotland",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Portfolio Optimisation",
                "endpoint": f"/api/sustainability/portfolio/optimisation?budget_mw=200",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Decommissioning Estimate",
                "endpoint": f"/api/sustainability/decom/estimate?capacity_mw={cap / 1000}&technology=wind",
                "method": "GET",
                "payload": {},
            },
        ]

    elif intent == "dispatch_optimisation":
        actions = [
            {
                "label": "Constraint Forecast",
                "endpoint": "/api/dispatch/constraints/forecast?hours_ahead=48",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Dispatch Schedule",
                "endpoint": f"/api/dispatch/schedule?capacity_mw={cap / 1000}&technology=solar&region=Midlands",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "BM Revenue Estimate",
                "endpoint": f"/api/dispatch/bm/revenue?capacity_mw={cap / 1000}&technology=wind&region=Scotland",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Revenue Stack",
                "endpoint": f"/api/dispatch/revenue/stack?capacity_mw={cap / 1000}&technology=wind&region=Scotland",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Scenario Comparison",
                "endpoint": f"/api/dispatch/revenue/scenarios?capacity_mw={cap / 1000}&technology=wind&region=Scotland",
                "method": "GET",
                "payload": {},
            },
        ]

    elif intent == "demand_forecast":
        actions = [
            {
                "label": "View Demand Forecast",
                "endpoint": f"/api/demand/forecast?gsp_id=ABHA&horizon_hours=168&model=analytical",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Neural Forecast (NHITS)",
                "endpoint": "/api/demand/neural-forecast?gsp_id=ABHA&horizon=48&model=nhits",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Neural Forecast (PatchTST)",
                "endpoint": "/api/demand/neural-forecast?gsp_id=ABHA&horizon=48&model=patchtst",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Scenario Projections",
                "endpoint": f"/api/demand/scenarios?gsp_id=ABHA&years_ahead=10",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "View Historical Demand",
                "endpoint": f"/api/demand/historical?gsp_id=ABHA&days=30",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "List Grid Supply Points",
                "endpoint": "/api/demand/gsps",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Demand Summary",
                "endpoint": "/api/demand/summary",
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
            {
                "label": "Capacity Factor Map (atlite)",
                "endpoint": f"/api/resource/capacity-map?lon_min={lon - 0.5}&lat_min={lat - 0.5}&lon_max={lon + 0.5}&lat_max={lat + 0.5}&technology=pv",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Land Eligibility (GLAES)",
                "endpoint": f"/api/site/land-eligibility?lon_min={lon - 0.5}&lat_min={lat - 0.5}&lon_max={lon + 0.5}&lat_max={lat + 0.5}&technology=solar",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Supply Curve (reV)",
                "endpoint": f"/api/site/supply-curve?lon_min={lon - 0.5}&lat_min={lat - 0.5}&lon_max={lon + 0.5}&lat_max={lat + 0.5}&technology=pv",
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
            {
                "label": "BESS Revenue Estimate (Optimizer)",
                "endpoint": "/api/bess/revenue-estimate?capacity_mwh=100&power_mw=50&year=2025",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Optimize Dispatch Schedule",
                "endpoint": "/api/bess/optimize",
                "method": "POST",
                "payload": {"capacity_mwh": 100, "power_mw": 50, "prices": []},
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

    elif intent == "investment_readiness":
        actions = [
            {
                "label": "Project Finance Model",
                "endpoint": f"/api/investment/finance/project?capacity_mw={cap / 1000}&technology=wind&region=Scotland",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Due Diligence Checklist",
                "endpoint": f"/api/investment/dd/checklist?capacity_mw={cap / 1000}&technology=wind&region=Scotland",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Monte Carlo Scenarios",
                "endpoint": f"/api/investment/scenario/montecarlo?capacity_mw={cap / 1000}&technology=wind",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Investment Memo",
                "endpoint": f"/api/investment/report/memo?capacity_mw={cap / 1000}&technology=wind&region=Scotland",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Risk Matrix",
                "endpoint": f"/api/investment/report/risk-matrix?capacity_mw={cap / 1000}&technology=wind",
                "method": "GET",
                "payload": {},
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

    elif intent == "dc_colocation":
        load_mw = cap / 1000
        actions = [
            {
                "label": "Score Site (15D Extended)",
                "endpoint": f"/api/dc/score-extended?lat={lat}&lon={lon}&capacity_mw={load_mw}&profile=google_hyperscale",
                "method": "POST",
                "payload": {},
            },
            {
                "label": "Score Site (9D Standard)",
                "endpoint": f"/api/dc/score?lat={lat}&lon={lon}&capacity_mw={load_mw}&profile=colocation",
                "method": "POST",
                "payload": {},
            },
            {
                "label": "Check 24/7 CFE%",
                "endpoint": f"/api/dc/cfe?lat={lat}&lon={lon}&capacity_mw={load_mw}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Cooling Analysis",
                "endpoint": f"/api/dc/cooling?lat={lat}&lon={lon}&capacity_mw={load_mw}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Check Constraints",
                "endpoint": f"/api/dc/constraints?lat={lat}&lon={lon}",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Scan Region for DC Sites",
                "endpoint": f"/api/dc/scan?profile=google_hyperscale&capacity_mw={load_mw}&limit=10",
                "method": "POST",
                "payload": {},
            },
            {
                "label": "View DC Infrastructure",
                "endpoint": f"/api/dc/infrastructure?lat={lat}&lon={lon}&radius_km=20",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Generate DC Report",
                "endpoint": f"/api/dc/report?lat={lat}&lon={lon}&capacity_mw={load_mw}&profile=google_hyperscale",
                "method": "POST",
                "payload": {},
            },
        ]

    elif intent == "dc_comparison":
        load_mw = cap / 1000
        actions = [
            {
                "label": "Score Google UK Sites",
                "endpoint": f"/api/dc/google-sites?capacity_mw={load_mw}&profile=google_hyperscale",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Compare Sites",
                "endpoint": "/api/dc/compare",
                "method": "POST",
                "payload": {
                    "sites": [
                        {"name": "Waltham Cross", "lat": 51.6945, "lon": -0.0334},
                        {"name": "Teesside", "lat": 54.5973, "lon": -1.0737},
                    ],
                    "capacity_mw": load_mw,
                    "profile": "google_hyperscale",
                },
            },
        ]

    elif intent == "dc_prospecting":
        load_mw = cap / 1000
        actions = [
            {
                "label": "AI Site Discovery",
                "endpoint": "/api/dc/prospect",
                "method": "POST",
                "payload": {
                    "query": f"Find sites with >{load_mw}MW headroom near good fibre",
                    "capacity_mw": load_mw,
                    "profile": "google_hyperscale",
                    "min_headroom_mw": load_mw * 0.5,
                    "limit": 20,
                },
            },
            {
                "label": "View DC Capacity Map",
                "endpoint": f"/api/dc/capacity-map?profile=google_hyperscale&min_headroom_mw={load_mw * 0.5}",
                "method": "GET",
                "payload": {},
            },
        ]

    if intent == "site_layout":
        tech = (ctx.get("technology") or "bess").lower()
        cap_mw = ctx.get("capacity_mw") or (cap / 1000)
        actions = [
            {
                "label": "Open Design Canvas",
                "action": "open_panel",
                "panel": "design_canvas",
                "payload": {"technology": tech, "capacity_mw": cap_mw},
            },
            {
                "label": "Run Cable Routing",
                "endpoint": "/api/cable-routing/route",
                "method": "POST",
                "payload": {"lat": lat, "lon": lon, "capacity_mw": cap_mw},
            },
            {
                "label": "Nearby Planning Precedent",
                "endpoint": f"/api/planning-ml/nearby-precedent?lat={lat}&lon={lon}&tech={tech}&radius_km=25",
                "method": "GET",
                "payload": {},
            },
            {
                "label": "Verify Grid Headroom",
                "endpoint": f"/api/grid/nearest-substation?lat={lat}&lon={lon}",
                "method": "GET",
                "payload": {},
            },
        ]

    # Add energy data actions to financial, feasibility, and environmental intents
    if intent in ("feasibility", "financial", "environmental"):
        actions.append({
            "label": "Carbon Intensity (Live)",
            "endpoint": "/api/energy-data/carbon-intensity",
            "method": "GET",
            "payload": {},
        })
        actions.append({
            "label": "Generation Fuel Mix",
            "endpoint": "/api/energy-data/generation-mix",
            "method": "GET",
            "payload": {},
        })
    if intent == "financial":
        actions.append({
            "label": "Wholesale Prices",
            "endpoint": "/api/energy-data/wholesale-prices?year=2025",
            "method": "GET",
            "payload": {},
        })
        actions.append({
            "label": "PV Capacity Factors",
            "endpoint": f"/api/energy-data/renewables-ninja?lat={lat}&lon={lon}&type=pv",
            "method": "GET",
            "payload": {},
        })
    if intent == "environmental":
        actions.append({
            "label": "Marginal Emissions",
            "endpoint": "/api/energy-data/emissions?year=2025",
            "method": "GET",
            "payload": {},
        })
        actions.append({
            "label": "Carbon Intensity Forecast",
            "endpoint": "/api/energy-data/carbon-intensity/forecast",
            "method": "GET",
            "payload": {},
        })

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


def enrich_context_with_energy_data(context: dict, intent: str) -> dict:
    """Inject live energy market data for financial/environmental/feasibility intents."""
    if intent not in ("feasibility", "financial", "environmental"):
        return context

    enriched = {**context}

    try:
        from utils.carbon_intensity import get_current_intensity, get_generation_mix
        ci = get_current_intensity()
        if ci and "error" not in ci:
            enriched["carbon_intensity"] = ci
        mix = get_generation_mix()
        if mix and not (len(mix) == 1 and "error" in mix[0]):
            enriched["generation_mix"] = mix
    except Exception as e:
        log.debug("Carbon intensity enrichment failed: %s", e)

    if intent in ("financial", "environmental"):
        try:
            from utils.carbon_prices import get_carbon_summary
            summary = get_carbon_summary()
            if summary and "error" not in summary.get("emissions", {}):
                enriched["carbon_price_summary"] = summary
        except Exception as e:
            log.debug("Carbon price enrichment failed: %s", e)

    return enriched
