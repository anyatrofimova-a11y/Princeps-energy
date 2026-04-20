"""Finance & strategy router — unified API for all financial utilities.

Exposes investment appraisal, PPA modelling, route-to-market analysis,
curtailment estimation, flexible connection modelling, reinforcement cost,
due diligence, and dispatch scheduling as POST/GET endpoints.

All utilities are subprocess bridge scripts (stdin JSON -> stdout JSON).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("princeps.finance")

# ── Subprocess script paths ───────────────────────────────────────────────
_UTILS = Path(__file__).resolve().parent.parent.parent / "utils"

_APPRAISAL = str(_UTILS / "investment_appraisal.py")
_PPA = str(_UTILS / "ppa_modeller.py")
_ROUTE = str(_UTILS / "route_to_market.py")
_CURTAILMENT = str(_UTILS / "curtailment_estimator.py")
_FLEXIBLE = str(_UTILS / "flexible_connection.py")
_REINFORCEMENT = str(_UTILS / "reinforcement_cost.py")
_DD = str(_UTILS / "due_diligence.py")
_DISPATCH = str(_UTILS / "dispatch_scheduler.py")
_PROJECT_FINANCE = str(_UTILS / "project_finance.py")


# ── Subprocess runner ─────────────────────────────────────────────────────

async def _run_subprocess(script_path: str, command: dict, timeout: float = 120) -> dict:
    """Run a utility subprocess, sending JSON on stdin and reading JSON from stdout."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, script_path,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(json.dumps(command).encode()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(504, f"Subprocess timed out after {timeout}s")

    if proc.returncode != 0:
        err_msg = stderr.decode()[:500] if stderr else "unknown error"
        log.error("Subprocess %s failed (rc=%d): %s", script_path, proc.returncode, err_msg)
        raise HTTPException(500, f"Subprocess failed: {err_msg[:200]}")

    try:
        result = json.loads(stdout.decode())
    except json.JSONDecodeError:
        raise HTTPException(500, "Subprocess returned invalid JSON")

    if isinstance(result, dict) and "error" in result:
        raise HTTPException(422, result["error"])

    return result


# ── Enums ─────────────────────────────────────────────────────────────────

class Technology(str, Enum):
    wind = "wind"
    solar = "solar"
    bess = "bess"
    offshore_wind = "offshore_wind"


class PPAStructure(str, Enum):
    fixed = "fixed"
    indexed = "indexed"
    floor_cap = "floor_cap"
    baseload = "baseload"
    shaped = "shaped"
    synthetic = "synthetic"


class CreditTier(str, Enum):
    investment_grade = "investment_grade"
    sub_investment = "sub_investment"
    unrated = "unrated"


class ConnectionType(str, Enum):
    firm = "firm"
    non_firm = "non_firm"
    anm = "anm"
    flexible = "flexible"
    timed = "timed"


class Terrain(str, Enum):
    urban = "urban"
    suburban = "suburban"
    rural = "rural"
    upland = "upland"
    coastal = "coastal"
    crossing_river = "crossing_river"
    crossing_rail = "crossing_rail"
    crossing_motorway = "crossing_motorway"


class CableType(str, Enum):
    cable = "cable"
    overhead = "overhead"


class Route(str, Enum):
    merchant = "merchant"
    cfd = "cfd"
    corporate_ppa = "corporate_ppa"
    sleeved_ppa = "sleeved_ppa"
    synthetic_ppa = "synthetic_ppa"
    private_wire = "private_wire"


class ResourceQuality(str, Enum):
    bankable = "bankable"
    indicative = "indicative"
    desktop = "desktop"


class OEMTier(str, Enum):
    tier_1 = "tier_1"
    tier_2 = "tier_2"
    tier_3 = "tier_3"


# ── Request models ────────────────────────────────────────────────────────

class ProjectFinanceRequest(BaseModel):
    """Project finance DCF model parameters."""
    capacity_mw: float = Field(50, gt=0, description="Installed capacity in MW")
    technology: Technology = Technology.wind
    region: str = Field("Scotland", description="UK region")
    ppa_price: float = Field(55.0, gt=0, description="PPA strike price GBP/MWh")
    discount_rate: float = Field(0.08, ge=0, le=0.25, description="Discount rate for NPV")


class DebtStructureRequest(BaseModel):
    """Debt sizing and sculpted repayment parameters."""
    capacity_mw: float = Field(50, gt=0)
    technology: Technology = Technology.wind
    target_dscr: float = Field(1.3, ge=1.0, le=3.0, description="Target debt service coverage ratio")
    gearing: float = Field(0.7, ge=0.1, le=0.95, description="Debt-to-total-capital ratio")
    ppa_price: float = Field(55.0, gt=0)


class EquityReturnsRequest(BaseModel):
    """Equity return analysis parameters."""
    capacity_mw: float = Field(50, gt=0)
    technology: Technology = Technology.wind
    gearing: float = Field(0.7, ge=0.1, le=0.95)
    ppa_price: float = Field(55.0, gt=0)
    tax_rate: float = Field(0.25, ge=0, le=0.5, description="Corporation tax rate")


class PPAPriceRequest(BaseModel):
    """PPA pricing engine parameters."""
    capacity_mw: float = Field(50, gt=0)
    technology: Technology = Technology.wind
    region: str = "Scotland"
    structure: PPAStructure = PPAStructure.fixed
    term_years: int = Field(15, ge=1, le=30)
    credit_tier: CreditTier = CreditTier.investment_grade


class PPATermAnalysisRequest(BaseModel):
    """PPA term analysis parameters."""
    capacity_mw: float = Field(50, gt=0)
    technology: Technology = Technology.solar
    region: str = "Midlands"
    structure: PPAStructure = PPAStructure.fixed


class PPAStructureComparisonRequest(BaseModel):
    """PPA structure comparison parameters."""
    capacity_mw: float = Field(50, gt=0)
    technology: Technology = Technology.wind
    region: str = "Scotland"
    term_years: int = Field(15, ge=1, le=30)


class RouteToMarketRequest(BaseModel):
    """Route-to-market comparison parameters."""
    capacity_mw: float = Field(50, gt=0)
    technology: Technology = Technology.wind
    region: str = "Scotland"
    project_life_years: int = Field(25, ge=5, le=40)
    command: str = Field("compare_routes", description="One of: compare_routes, route_detail, bankability_score")
    route: Optional[str] = Field(None, description="Route ID for route_detail or bankability_score")


class CurtailmentRequest(BaseModel):
    """Curtailment estimation parameters."""
    capacity_mw: float = Field(50, gt=0)
    voltage_kv: int = Field(132, description="Connection voltage in kV")
    region: str = "Midlands"
    technology: Technology = Technology.solar
    connection_type: ConnectionType = ConnectionType.firm
    queue_depth: int = Field(0, ge=0, description="Number of projects ahead in connection queue")
    command: str = Field(
        "estimate_annual",
        description="One of: estimate_annual, monthly_profile, revenue_impact",
    )
    wholesale_price_mwh: float = Field(55, gt=0, description="Wholesale price for revenue_impact")
    cfd_price_mwh: float = Field(0, ge=0, description="CfD top-up for revenue_impact")
    roc_value_mwh: float = Field(0, ge=0, description="ROC value for revenue_impact")
    years: int = Field(25, ge=1, le=40, description="Project life for revenue_impact")


class FlexibleConnectionRequest(BaseModel):
    """Flexible connection comparison parameters."""
    capacity_mw: float = Field(50, gt=0)
    headroom_mw: float = Field(30, gt=0, description="Available network headroom in MW")
    region: str = "Midlands"
    technology: Technology = Technology.solar
    voltage_kv: int = Field(132)
    command: str = Field("compare", description="One of: compare, anm_profile, optimal_sizing")
    target_curtailment_pct: float = Field(5, ge=0, le=50, description="Target for optimal_sizing")


class ReinforcementCostRequest(BaseModel):
    """Reinforcement cost estimation parameters."""
    distance_km: float = Field(5, gt=0, description="Circuit distance in km")
    voltage_kv: int = Field(132)
    capacity_mw: float = Field(50, gt=0)
    headroom_mw: float = Field(0, ge=0)
    terrain: Terrain = Terrain.rural
    connection_type: CableType = CableType.cable
    command: str = Field("estimate", description="One of: estimate, benchmarks")


class DueDiligenceRequest(BaseModel):
    """Due diligence scoring parameters."""
    capacity_mw: float = Field(50, gt=0)
    technology: Technology = Technology.wind
    region: str = "Scotland"
    command: str = Field("dd_checklist", description="One of: dd_checklist, technical_dd, commercial_dd")
    resource_quality: ResourceQuality = ResourceQuality.indicative
    oem_tier: OEMTier = OEMTier.tier_1
    has_ppa: bool = True
    has_planning: bool = False
    grid_offer: bool = False
    ppa_price: float = Field(55.0, gt=0)


class DispatchRequest(BaseModel):
    """Dispatch scheduling parameters."""
    capacity_mw: float = Field(50, gt=0)
    technology: Technology = Technology.solar
    region: str = "Midlands"
    connection_type: ConnectionType = ConnectionType.anm
    headroom_mw: float = Field(30, gt=0)
    hours_ahead: int = Field(24, ge=1, le=168, description="Schedule horizon in hours")
    month: int = Field(1, ge=1, le=12)
    command: str = Field("schedule", description="One of: schedule, bess_schedule, revenue_comparison")
    # BESS-specific fields
    power_mw: float = Field(25, gt=0, description="BESS rated power for bess_schedule")
    energy_mwh: float = Field(50, gt=0, description="BESS energy capacity for bess_schedule")
    soc_pct: float = Field(50, ge=0, le=100, description="Initial state of charge for bess_schedule")


class SubsidyType(str, Enum):
    none = "none"
    roc = "roc"
    cfd = "cfd"


class ProjectModelCommand(str, Enum):
    project_model = "project_model"
    sensitivity = "sensitivity"
    summary = "summary"


class ProjectModelRequest(BaseModel):
    """Comprehensive project finance DCF model — replaces Excel lender models.

    All CAPEX/OPEX fields are optional; UK benchmarks are used as defaults.
    Provide grid_connection_cost in absolute £ (from Princeps grid assessment).
    """
    command: ProjectModelCommand = ProjectModelCommand.project_model
    capacity_kwp: float = Field(50000, gt=0, description="Installed capacity in kWp (50000 = 50 MW)")
    technology: Technology = Technology.solar

    # ── Revenue ──
    ppa_price_mwh: float = Field(55.0, gt=0, description="PPA strike price £/MWh")
    ppa_term_years: int = Field(15, ge=1, le=30, description="PPA contract term")
    merchant_price_mwh: float = Field(45.0, gt=0, description="Post-PPA merchant price £/MWh")
    merchant_escalation: float = Field(0.02, ge=0, le=0.10, description="Annual merchant price escalation")
    subsidy_type: SubsidyType = SubsidyType.none
    subsidy_value: float = Field(0.0, ge=0, description="ROC buyout or CfD strike £/MWh")
    capacity_market_rev: float = Field(0.0, ge=0, description="Capacity market revenue £/MW/yr (BESS)")
    ancillary_rev: float = Field(0.0, ge=0, description="Ancillary services revenue £/MW/yr (BESS)")

    # ── Financial structure ──
    discount_rate: float = Field(0.08, ge=0.01, le=0.25, description="Nominal WACC / discount rate")
    gearing: float = Field(0.70, ge=0.0, le=0.95, description="Debt-to-total-capital ratio")
    senior_interest: float = Field(0.055, ge=0.01, le=0.15, description="Senior debt interest rate")
    debt_term_years: int = Field(18, ge=5, le=30, description="Senior debt tenor")
    target_dscr: float = Field(1.30, ge=1.0, le=3.0, description="Target DSCR for sculpted repayment")
    corporation_tax: float = Field(0.25, ge=0, le=0.5, description="Corporation tax rate")
    project_life_years: int = Field(25, ge=10, le=40, description="Total project operating life")
    construction_months: Optional[int] = Field(None, ge=3, le=60, description="Construction period (months)")
    degradation_rate: float = Field(0.005, ge=0, le=0.03, description="Annual output degradation")
    cpi_escalation: float = Field(0.025, ge=0, le=0.10, description="CPI escalation rate")

    # ── CAPEX overrides (£/kW or kWp) ──
    capex_modules_per_kw: Optional[float] = Field(None, ge=0, description="Module cost £/kWp override")
    capex_inverters_per_kw: Optional[float] = Field(None, ge=0, description="Inverter cost £/kW override")
    capex_mounting_per_kw: Optional[float] = Field(None, ge=0, description="Mounting/racking £/kWp override")
    capex_electrical_per_kw: Optional[float] = Field(None, ge=0, description="Electrical BOS £/kWp override")
    capex_civil_per_kw: Optional[float] = Field(None, ge=0, description="Civil works £/kWp override")
    capex_development_per_kw: Optional[float] = Field(None, ge=0, description="Development costs £/kWp override")
    grid_connection_cost: float = Field(0, ge=0, description="Grid connection cost in absolute £")
    contingency_pct: Optional[float] = Field(None, ge=0, le=25, description="Contingency % override")

    # ── OPEX overrides ──
    opex_om_per_kw: Optional[float] = Field(None, ge=0, description="O&M contract £/kW/yr override")
    opex_land_rent_per_ha: Optional[float] = Field(None, ge=0, description="Land rent £/ha/yr override")
    opex_insurance_pct: Optional[float] = Field(None, ge=0, le=2.0, description="Insurance % of CAPEX override")
    opex_business_rates_per_mw: Optional[float] = Field(None, ge=0, description="Business rates £/MW/yr override")
    opex_grid_charges_per_mw: Optional[float] = Field(None, ge=0, description="Grid charges £/MW/yr override")
    opex_management_per_mw: Optional[float] = Field(None, ge=0, description="Management/admin £/MW/yr override")

    # ── Tax depreciation ──
    tax_depreciation_rate: float = Field(0.18, ge=0, le=1.0, description="Capital allowance rate")
    tax_depreciation_type: str = Field("reducing_balance", description="reducing_balance or straight_line")


# ── Router ────────────────────────────────────────────────────────────────

router = APIRouter(tags=["finance"])


# ── 1. Investment Appraisal ───────────────────────────────────────────────

@router.post("/api/finance/project-finance")
async def api_project_finance(req: ProjectFinanceRequest):
    """25-year project finance DCF model with IRR, NPV, LCOE, and payback."""
    return await _run_subprocess(_APPRAISAL, {
        "command": "project_finance",
        "capacity_mw": req.capacity_mw,
        "technology": req.technology.value,
        "region": req.region,
        "ppa_price": req.ppa_price,
        "discount_rate": req.discount_rate,
    })


@router.post("/api/finance/debt-structure")
async def api_debt_structure(req: DebtStructureRequest):
    """Senior debt sizing with sculpted repayment and DSCR covenant analysis."""
    return await _run_subprocess(_APPRAISAL, {
        "command": "debt_structure",
        "capacity_mw": req.capacity_mw,
        "technology": req.technology.value,
        "target_dscr": req.target_dscr,
        "gearing": req.gearing,
        "ppa_price": req.ppa_price,
    })


@router.post("/api/finance/equity-returns")
async def api_equity_returns(req: EquityReturnsRequest):
    """Pre/post-tax equity IRR, cash-on-cash yield, and dividend waterfall."""
    return await _run_subprocess(_APPRAISAL, {
        "command": "equity_returns",
        "capacity_mw": req.capacity_mw,
        "technology": req.technology.value,
        "gearing": req.gearing,
        "ppa_price": req.ppa_price,
        "tax_rate": req.tax_rate,
    })


# ── 2. PPA Modelling ─────────────────────────────────────────────────────

@router.post("/api/finance/ppa-price")
async def api_ppa_price(req: PPAPriceRequest):
    """Calculate PPA price for a given structure, term, and credit tier."""
    return await _run_subprocess(_PPA, {
        "command": "ppa_price",
        "capacity_mw": req.capacity_mw,
        "technology": req.technology.value,
        "region": req.region,
        "structure": req.structure.value,
        "term_years": req.term_years,
        "credit_tier": req.credit_tier.value,
    })


@router.post("/api/finance/ppa-term-analysis")
async def api_ppa_term_analysis(req: PPATermAnalysisRequest):
    """Analyse PPA value across different term lengths (5-25 years)."""
    return await _run_subprocess(_PPA, {
        "command": "term_analysis",
        "capacity_mw": req.capacity_mw,
        "technology": req.technology.value,
        "region": req.region,
        "structure": req.structure.value,
    })


@router.post("/api/finance/ppa-structures")
async def api_ppa_structures(req: PPAStructureComparisonRequest):
    """Compare all PPA structures side-by-side with seasonal shaping."""
    return await _run_subprocess(_PPA, {
        "command": "structure_comparison",
        "capacity_mw": req.capacity_mw,
        "technology": req.technology.value,
        "region": req.region,
        "term_years": req.term_years,
    })


# ── 3. Route to Market ───────────────────────────────────────────────────

@router.get("/api/finance/route-to-market")
async def api_route_to_market(
    capacity_mw: float = 50,
    technology: str = "wind",
    region: str = "Scotland",
    project_life_years: int = 25,
    command: str = "compare_routes",
    route: Optional[str] = None,
):
    """Compare market routes (merchant, CfD, corporate PPA, sleeved, synthetic, private wire).

    Commands:
    - compare_routes: side-by-side comparison of all viable routes
    - route_detail: detailed analysis for a specific route (pass route= parameter)
    - bankability_score: bankability/debt serviceability for a route
    """
    payload: dict = {
        "command": command,
        "capacity_mw": capacity_mw,
        "technology": technology,
        "region": region,
        "project_life_years": project_life_years,
    }
    if route:
        payload["route"] = route
    return await _run_subprocess(_ROUTE, payload)


# ── 4. Curtailment ───────────────────────────────────────────────────────

@router.post("/api/finance/curtailment")
async def api_curtailment(req: CurtailmentRequest):
    """Estimate annual curtailment (Monte Carlo P10/P50/P90) and revenue impact.

    Commands:
    - estimate_annual: full Monte Carlo curtailment estimate
    - monthly_profile: monthly curtailment percentage profile
    - revenue_impact: lifetime revenue lost to curtailment
    """
    payload: dict = {
        "command": req.command,
        "capacity_mw": req.capacity_mw,
        "voltage_kv": req.voltage_kv,
        "region": req.region,
        "technology": req.technology.value,
        "connection_type": req.connection_type.value,
        "queue_depth": req.queue_depth,
    }
    if req.command == "revenue_impact":
        payload.update({
            "wholesale_price_mwh": req.wholesale_price_mwh,
            "cfd_price_mwh": req.cfd_price_mwh,
            "roc_value_mwh": req.roc_value_mwh,
            "years": req.years,
        })
    return await _run_subprocess(_CURTAILMENT, payload)


# ── 5. Flexible Connection ───────────────────────────────────────────────

@router.post("/api/finance/flexible-connection")
async def api_flexible_connection(req: FlexibleConnectionRequest):
    """Compare firm vs ANM vs timed export connection options.

    Commands:
    - compare: side-by-side comparison of all connection types
    - anm_profile: 24-hour ANM export profile with curtailment windows
    - optimal_sizing: find optimal plant capacity for given headroom
    """
    payload: dict = {
        "command": req.command,
        "capacity_mw": req.capacity_mw,
        "headroom_mw": req.headroom_mw,
        "region": req.region,
        "technology": req.technology.value,
        "voltage_kv": req.voltage_kv,
    }
    if req.command == "optimal_sizing":
        payload["target_curtailment_pct"] = req.target_curtailment_pct
    return await _run_subprocess(_FLEXIBLE, payload)


# ── 6. Reinforcement Cost ────────────────────────────────────────────────

@router.post("/api/finance/reinforcement-cost")
async def api_reinforcement_cost(req: ReinforcementCostRequest):
    """Monte Carlo reinforcement cost estimate (P10/P50/P90) with component breakdown.

    Commands:
    - estimate: full probabilistic cost estimate
    - benchmarks: return UK DNO cost benchmark tables
    """
    payload: dict = {
        "command": req.command,
        "distance_km": req.distance_km,
        "voltage_kv": req.voltage_kv,
        "capacity_mw": req.capacity_mw,
        "headroom_mw": req.headroom_mw,
        "terrain": req.terrain.value,
        "connection_type": req.connection_type.value,
    }
    return await _run_subprocess(_REINFORCEMENT, payload)


# ── 7. Due Diligence ─────────────────────────────────────────────────────

@router.post("/api/finance/due-diligence")
async def api_due_diligence(req: DueDiligenceRequest):
    """Automated due diligence scoring — 4-pillar checklist, technical DD, commercial DD.

    Commands:
    - dd_checklist: full 4-pillar RAG scoring (technical, commercial, legal, financial)
    - technical_dd: deep-dive technical due diligence
    - commercial_dd: revenue certainty, market exposure, insurance, O&M
    """
    payload: dict = {
        "command": req.command,
        "capacity_mw": req.capacity_mw,
        "technology": req.technology.value,
        "region": req.region,
    }
    if req.command == "dd_checklist":
        payload.update({
            "resource_quality": req.resource_quality.value,
            "oem_tier": req.oem_tier.value,
            "has_ppa": req.has_ppa,
            "has_planning": req.has_planning,
            "grid_offer": req.grid_offer,
        })
    elif req.command == "technical_dd":
        payload.update({
            "resource_quality": req.resource_quality.value,
            "oem_tier": req.oem_tier.value,
            "grid_offer": req.grid_offer,
        })
    elif req.command == "commercial_dd":
        payload.update({
            "ppa_price": req.ppa_price,
            "has_ppa": req.has_ppa,
        })
    return await _run_subprocess(_DD, payload)


# ── 8. Dispatch Scheduling ───────────────────────────────────────────────

@router.post("/api/finance/dispatch")
async def api_dispatch(req: DispatchRequest):
    """Optimal dispatch schedule for generation or BESS sites.

    Commands:
    - schedule: generation site dispatch (considers constraints, wholesale prices)
    - bess_schedule: BESS arbitrage + frequency response schedule
    - revenue_comparison: compare revenue across connection types and seasons
    """
    if req.command == "bess_schedule":
        payload = {
            "command": "bess_schedule",
            "power_mw": req.power_mw,
            "energy_mwh": req.energy_mwh,
            "soc_pct": req.soc_pct,
            "region": req.region,
            "hours_ahead": req.hours_ahead,
            "month": req.month,
        }
    elif req.command == "revenue_comparison":
        payload = {
            "command": "revenue_comparison",
            "capacity_mw": req.capacity_mw,
            "technology": req.technology.value,
            "region": req.region,
        }
    else:
        payload = {
            "command": "schedule",
            "capacity_mw": req.capacity_mw,
            "technology": req.technology.value,
            "region": req.region,
            "connection_type": req.connection_type.value,
            "headroom_mw": req.headroom_mw,
            "hours_ahead": req.hours_ahead,
            "month": req.month,
        }
    return await _run_subprocess(_DISPATCH, payload)


# ── 9. Project Finance Engine (comprehensive DCF) ────────────────────────

@router.post("/api/finance/project-model")
async def api_project_model(req: ProjectModelRequest):
    """Comprehensive 25-year DCF project finance model — DNV GL / lender standard.

    Replaces Excel-based financial models with full CAPEX breakdown, itemised OPEX,
    multi-stream revenue (PPA + merchant tail + subsidy + BESS), sculpted debt
    repayment, tax shield with capital allowances, and sensitivity/tornado analysis.

    Commands:
    - project_model: full 25-year cashflow with CAPEX/OPEX/debt/returns
    - sensitivity: tornado analysis varying PPA ±20%, CAPEX ±15%, yield ±10%, etc.
    - summary: condensed output with GO/CAUTION/NO-GO verdict
    """
    # Build payload — strip None values so subprocess uses its own defaults
    payload = {"command": req.command.value}
    for field_name, field_val in req.model_dump().items():
        if field_name == "command":
            continue
        if field_val is not None:
            # Convert enums to their string value
            if isinstance(field_val, str):
                payload[field_name] = field_val
            else:
                payload[field_name] = field_val

    return await _run_subprocess(_PROJECT_FINANCE, payload, timeout=180)


# ─── Godmode-v2 #2 — Monte Carlo financial engine ──────────────────────────

from pydantic import BaseModel as _MCBM


class _MCVar(_MCBM):
    mean: float
    stdev: float = 0.0
    dist: str = "normal"  # "normal" | "lognormal" | "triangular"
    low: float | None = None
    high: float | None = None


class _MCRequest(_MCBM):
    capex_gbp: _MCVar
    opex_gbp_yr: _MCVar
    revenue_gbp_yr: _MCVar
    curtailment_pct: _MCVar | None = None
    timeline_months: _MCVar | None = None
    discount_rate_pct: float = 8.0
    project_life_yr: int = 20
    n_runs: int = 1000
    correlation_capex_timeline: float = 0.35
    correlation_revenue_curtailment: float = -0.55


@router.post("/api/finance/monte-carlo")
async def monte_carlo(body: _MCRequest):
    """Monte Carlo sampling over correlated inputs → P10/P50/P90 IRR, DSCR,
    and NPV distributions, plus a tornado of single-variable sensitivities.

    MVP: pure-Python (no scipy dep) so it ships without extra installs.
    Full correlated-copula sampling is sprint-2 polish.
    """
    import random as _r
    import math as _m

    def sample(var: _MCVar) -> float:
        if var is None:
            return 0.0
        d = (var.dist or "normal").lower()
        if d == "lognormal":
            sigma = max(1e-6, abs(var.stdev / max(1e-6, var.mean)))
            return var.mean * _m.exp(_r.gauss(0, sigma))
        if d == "triangular" and var.low is not None and var.high is not None:
            return _r.triangular(var.low, var.high, var.mean)
        return _r.gauss(var.mean, max(1e-6, var.stdev))

    def irr_of(capex, rev_yr, opex_yr, life, discount):
        lo, hi, mid = -0.2, 0.6, 0.0
        for _ in range(48):
            mid = (lo + hi) / 2
            npv = -capex + sum((rev_yr - opex_yr) / ((1 + mid) ** t) for t in range(1, life + 1))
            if npv > 0:
                lo = mid
            else:
                hi = mid
        return mid

    runs = []
    for _ in range(max(100, min(5000, body.n_runs))):
        capex = sample(body.capex_gbp)
        opex = sample(body.opex_gbp_yr)
        rev = sample(body.revenue_gbp_yr)
        curt = sample(body.curtailment_pct) if body.curtailment_pct else 0.0
        rev *= (1 - max(0, min(0.5, curt / 100)) * abs(body.correlation_revenue_curtailment))
        tl = sample(body.timeline_months) if body.timeline_months else 0
        capex *= (1 + max(-0.3, min(0.3, tl / 36)) * body.correlation_capex_timeline)
        irr = irr_of(capex, rev, opex, body.project_life_yr, body.discount_rate_pct / 100)
        dscr = max(0.0, (rev - opex) / max(1, capex * 0.07))
        npv = -capex + sum((rev - opex) / ((1 + body.discount_rate_pct / 100) ** t)
                           for t in range(1, body.project_life_yr + 1))
        runs.append({"irr": irr, "dscr": dscr, "npv": npv})

    def pct_of(vals, p):
        s = sorted(vals)
        idx = max(0, min(len(s) - 1, int(len(s) * p)))
        return s[idx]

    irrs = [r["irr"] for r in runs]
    dscrs = [r["dscr"] for r in runs]
    npvs = [r["npv"] for r in runs]

    base_irr = irr_of(body.capex_gbp.mean, body.revenue_gbp_yr.mean, body.opex_gbp_yr.mean,
                      body.project_life_yr, body.discount_rate_pct / 100)
    tornado = []
    for label, var, applyf in [
        ("CAPEX",   body.capex_gbp,       lambda v: irr_of(v, body.revenue_gbp_yr.mean, body.opex_gbp_yr.mean, body.project_life_yr, body.discount_rate_pct / 100)),
        ("Revenue", body.revenue_gbp_yr,  lambda v: irr_of(body.capex_gbp.mean, v, body.opex_gbp_yr.mean, body.project_life_yr, body.discount_rate_pct / 100)),
        ("OPEX",    body.opex_gbp_yr,     lambda v: irr_of(body.capex_gbp.mean, body.revenue_gbp_yr.mean, v, body.project_life_yr, body.discount_rate_pct / 100)),
    ]:
        if var is None:
            continue
        d_lo = applyf(var.mean * 0.8) - base_irr
        d_hi = applyf(var.mean * 1.2) - base_irr
        tornado.append({"label": label, "low_delta_irr": round(d_lo, 4), "high_delta_irr": round(d_hi, 4)})
    tornado.sort(key=lambda t: abs(t["high_delta_irr"] - t["low_delta_irr"]), reverse=True)

    return {
        "n_runs": len(runs),
        "base_irr": round(base_irr, 4),
        "irr":  {"p10": round(pct_of(irrs,  0.1), 4), "p50": round(pct_of(irrs,  0.5), 4), "p90": round(pct_of(irrs,  0.9), 4)},
        "dscr": {"p10": round(pct_of(dscrs, 0.1), 3), "p50": round(pct_of(dscrs, 0.5), 3), "p90": round(pct_of(dscrs, 0.9), 3)},
        "npv_gbp": {"p10": round(pct_of(npvs, 0.1), 0), "p50": round(pct_of(npvs, 0.5), 0), "p90": round(pct_of(npvs, 0.9), 0)},
        "tornado": tornado,
        "histogram_irr": [round(r, 4) for r in sorted(irrs)][::max(1, len(irrs) // 40)],
    }
