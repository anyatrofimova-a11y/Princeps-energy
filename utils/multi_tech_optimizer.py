"""Multi-technology site optimization engine.

Given site characteristics, evaluates 8 technology scenarios (solar fixed,
solar tracker, solar+BESS, BESS-only, wind, solar+wind, solar+wind+BESS,
data-centre+solar+BESS) and ranks them by configurable objective.

No competitor does this: single-call comparison of ALL technology options
with UK-specific 2025 cost benchmarks and full financial appraisal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# UK 2025 cost benchmarks
# ---------------------------------------------------------------------------

COST_BENCHMARKS = {
    "solar_fixed_per_kw":       {"low": 450, "mid": 550, "high": 650},
    "solar_tracker_per_kw":     {"low": 550, "mid": 650, "high": 750},
    "bess_4hr_per_kwh":         {"low": 300, "mid": 400, "high": 500},
    "wind_onshore_per_kw":      {"low": 1200, "mid": 1500, "high": 1800},
    "grid_connection_per_km": {
        "11kv":  80_000,
        "33kv": 150_000,
        "66kv": 300_000,
        "132kv": 500_000,
    },
    "data_centre_per_mw":       {"low": 6_000_000, "mid": 8_000_000, "high": 10_000_000},
}

# OPEX (GBP/kW/yr)
OPEX = {
    "solar": 9.0,
    "bess":  12.0,
    "wind":  35.0,
    "data_centre_per_mw": 400_000,  # GBP/MW/yr
}

# UK grid carbon intensity (tCO2/MWh) — 2025 average
UK_GRID_CARBON_INTENSITY = 0.18

# Default financial assumptions
DEFAULT_PPA_PRICE = 55.0        # GBP/MWh
DEFAULT_BESS_REVENUE = 90_000   # GBP/MW/yr (stacked: FFR + DC + BM + wholesale arb)
DEFAULT_DISCOUNT_RATE = 0.07    # 7% WACC
DEFAULT_PROJECT_LIFE = 30       # years
DEFAULT_DEGRADATION = 0.005     # 0.5%/yr
DEFAULT_CPI = 0.025             # 2.5%/yr escalation

# Area density (MW per hectare)
DENSITY = {
    "solar_fixed":   0.8,   # ~0.8 MWp/ha (UK typical)
    "solar_tracker": 0.65,  # wider spacing
    "bess":          10.0,  # very compact
    "wind":          0.15,  # 6-7 MW turbine per ~40-50 ha
    "data_centre":   5.0,   # MW IT load per ha
}

# Capacity factors by resource
def _solar_cf(ghi: float, tracker: bool = False) -> float:
    """Estimate solar capacity factor from GHI (kWh/m2/yr).
    UK typical GHI 900-1100, CF 9-12%."""
    base = ghi / 8760 * 0.85  # PR ~0.85
    if tracker:
        base *= 1.15  # ~15% tracker gain
    return min(base, 0.25)

def _wind_cf(wind_speed: float) -> float:
    """Estimate wind capacity factor from mean wind speed (m/s).
    Rough Rayleigh-based approximation for modern onshore turbines."""
    if wind_speed < 4.0:
        return 0.0
    # Typical UK onshore: 5 m/s -> ~20%, 7 m/s -> ~30%, 9 m/s -> ~38%
    cf = 0.0
    if wind_speed >= 4.0:
        cf = 0.04 * wind_speed ** 1.3 / 100
        cf = min(max(cf * 10, 0.08), 0.45)
    # More realistic curve
    cf = 0.087 * wind_speed - 0.22
    cf = max(0.0, min(cf, 0.45))
    return cf


# ---------------------------------------------------------------------------
# Scenario evaluation
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    """Full appraisal of one technology scenario."""
    scenario_id: str
    scenario_name: str
    technology_mix: list[str]
    feasible: bool = True
    infeasibility_reason: str = ""

    # Capacity
    solar_mw: float = 0.0
    bess_mw: float = 0.0
    bess_mwh: float = 0.0
    wind_mw: float = 0.0
    dc_mw: float = 0.0  # data centre IT load
    total_generation_mw: float = 0.0
    area_used_ha: float = 0.0

    # Yield
    annual_yield_mwh: float = 0.0
    capacity_factor_pct: float = 0.0

    # Financials
    capex_total: float = 0.0
    capex_per_kw: float = 0.0
    opex_annual: float = 0.0
    annual_revenue: float = 0.0
    lcoe: float = 0.0
    irr_pct: float = 0.0
    npv: float = 0.0

    # Grid & carbon
    grid_connection_cost: float = 0.0
    grid_curtailment_risk_pct: float = 0.0
    carbon_displacement_tco2: float = 0.0

    # Planning
    planning_risk: str = "MEDIUM"

    # BESS-specific
    bess_annual_revenue: float = 0.0

    # Data centre
    dc_annual_revenue: float = 0.0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _grid_connection_cost(capacity_mw: float, distance_km: float) -> tuple[float, str]:
    """Estimate grid connection cost and voltage level."""
    if capacity_mw <= 1:
        voltage = "11kv"
    elif capacity_mw <= 20:
        voltage = "33kv"
    elif capacity_mw <= 80:
        voltage = "66kv"
    else:
        voltage = "132kv"

    rate = COST_BENCHMARKS["grid_connection_per_km"][voltage]
    # Base cost + per-km cost
    base = {
        "11kv": 50_000,
        "33kv": 200_000,
        "66kv": 800_000,
        "132kv": 2_000_000,
    }
    cost = base[voltage] + rate * distance_km
    return cost, voltage


def _compute_irr(cashflows: list[float], max_iter: int = 200, tol: float = 1e-6) -> float:
    """Newton-Raphson IRR solver."""
    if not cashflows or all(c == 0 for c in cashflows):
        return 0.0

    # Initial guess
    total_return = sum(cashflows[1:])
    if cashflows[0] == 0:
        return 0.0
    guess = (total_return / abs(cashflows[0])) ** (1 / max(len(cashflows) - 1, 1)) - 1
    guess = max(-0.5, min(guess, 2.0))
    rate = guess

    for _ in range(max_iter):
        npv = sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))
        dnpv = sum(-t * cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cashflows))
        if abs(dnpv) < 1e-12:
            break
        new_rate = rate - npv / dnpv
        if abs(new_rate - rate) < tol:
            rate = new_rate
            break
        rate = max(-0.99, min(new_rate, 5.0))

    return round(rate * 100, 2)


def _compute_npv(cashflows: list[float], rate: float) -> float:
    """Compute NPV at given discount rate."""
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))


def _curtailment_risk(generation_mw: float, grid_headroom_mw: float) -> float:
    """Estimate curtailment risk (%) based on generation vs grid headroom."""
    if grid_headroom_mw <= 0:
        return 80.0
    ratio = generation_mw / grid_headroom_mw
    if ratio <= 0.5:
        return 0.0
    elif ratio <= 0.8:
        return (ratio - 0.5) / 0.3 * 5.0
    elif ratio <= 1.0:
        return 5.0 + (ratio - 0.8) / 0.2 * 15.0
    else:
        # Over headroom — high curtailment
        return min(20.0 + (ratio - 1.0) * 40.0, 80.0)


def _planning_risk(technology_mix: list[str], area_ha: float, capacity_mw: float) -> str:
    """Heuristic planning risk assessment."""
    risk_score = 0
    if "wind" in technology_mix:
        risk_score += 3  # wind always harder to consent
    if "data_centre" in technology_mix:
        risk_score += 2  # industrial use class
    if area_ha > 50:
        risk_score += 1
    if capacity_mw > 50:
        risk_score += 1  # NSIP threshold
    if capacity_mw > 100:
        risk_score += 2  # definitely NSIP

    if risk_score >= 5:
        return "HIGH"
    elif risk_score >= 2:
        return "MEDIUM"
    return "LOW"


def _evaluate_scenario(
    scenario_id: str,
    scenario_name: str,
    technology_mix: list[str],
    area_ha: float,
    grid_headroom_mw: float,
    ghi: float,
    wind_speed: float,
    grid_distance_km: float,
    ppa_price: float,
    bess_revenue_per_mw: float,
    discount_rate: float,
    project_life: int,
    degradation: float,
    cpi: float,
    # Allocation fractions (how much area goes to each tech)
    solar_area_frac: float = 0.0,
    bess_area_frac: float = 0.0,
    wind_area_frac: float = 0.0,
    dc_area_frac: float = 0.0,
    tracker: bool = False,
    bess_hours: float = 4.0,
) -> ScenarioResult:
    """Evaluate a single technology scenario."""

    result = ScenarioResult(
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        technology_mix=technology_mix,
    )

    # --- Capacity sizing (constrained by area and grid headroom) ---
    solar_type = "solar_tracker" if tracker else "solar_fixed"

    solar_area = area_ha * solar_area_frac
    bess_area = area_ha * bess_area_frac
    wind_area = area_ha * wind_area_frac
    dc_area = area_ha * dc_area_frac

    # Unconstrained capacity from area
    solar_mw = solar_area * DENSITY[solar_type] if solar_area_frac > 0 else 0
    bess_mw = bess_area * DENSITY["bess"] if bess_area_frac > 0 else 0
    wind_mw = wind_area * DENSITY["wind"] if wind_area_frac > 0 else 0
    dc_mw = dc_area * DENSITY["data_centre"] if dc_area_frac > 0 else 0

    # Generation capacity (excludes BESS — storage, not generation)
    gen_mw = solar_mw + wind_mw

    # Constrain generation to grid headroom (BESS can co-locate behind meter)
    if gen_mw > grid_headroom_mw and grid_headroom_mw > 0:
        scale = grid_headroom_mw / gen_mw
        solar_mw *= scale
        wind_mw *= scale
        gen_mw = grid_headroom_mw

    # BESS sized to generation or grid headroom
    if bess_mw > 0:
        bess_mw = min(bess_mw, max(gen_mw, grid_headroom_mw))

    # Data centre IT load
    if dc_mw > 0:
        dc_mw = min(dc_mw, area_ha * dc_area_frac * DENSITY["data_centre"])

    result.solar_mw = round(solar_mw, 2)
    result.wind_mw = round(wind_mw, 2)
    result.bess_mw = round(bess_mw, 2)
    result.bess_mwh = round(bess_mw * bess_hours, 2)
    result.dc_mw = round(dc_mw, 2)
    result.total_generation_mw = round(gen_mw, 2)
    result.area_used_ha = round(solar_area + bess_area + wind_area + dc_area, 2)

    # Feasibility gate
    if gen_mw < 0.1 and bess_mw < 0.1 and dc_mw < 0.1:
        result.feasible = False
        result.infeasibility_reason = "Insufficient capacity from available area"
        return result

    if "wind" in technology_mix and wind_speed < 5.0:
        result.feasible = False
        result.infeasibility_reason = f"Wind speed {wind_speed} m/s below 5 m/s minimum"
        return result

    # --- Annual yield ---
    solar_cf = _solar_cf(ghi, tracker=tracker) if solar_mw > 0 else 0
    wind_cf_val = _wind_cf(wind_speed) if wind_mw > 0 else 0

    solar_yield = solar_mw * solar_cf * 8760
    wind_yield = wind_mw * wind_cf_val * 8760
    total_yield = solar_yield + wind_yield

    # Blended CF
    if gen_mw > 0:
        blended_cf = total_yield / (gen_mw * 8760)
    else:
        blended_cf = 0

    result.annual_yield_mwh = round(total_yield, 1)
    result.capacity_factor_pct = round(blended_cf * 100, 2)

    # --- CAPEX ---
    solar_bench = COST_BENCHMARKS["solar_tracker_per_kw" if tracker else "solar_fixed_per_kw"]
    solar_capex = solar_mw * 1000 * solar_bench["mid"]

    bess_capex = result.bess_mwh * 1000 * COST_BENCHMARKS["bess_4hr_per_kwh"]["mid"]

    wind_capex = wind_mw * 1000 * COST_BENCHMARKS["wind_onshore_per_kw"]["mid"]

    dc_capex = dc_mw * COST_BENCHMARKS["data_centre_per_mw"]["mid"]

    grid_cost, voltage = _grid_connection_cost(
        max(gen_mw, bess_mw), grid_distance_km,
    )
    result.grid_connection_cost = round(grid_cost, 0)

    total_capex = solar_capex + bess_capex + wind_capex + dc_capex + grid_cost
    result.capex_total = round(total_capex, 0)

    total_kw = (solar_mw + wind_mw + bess_mw + dc_mw) * 1000
    result.capex_per_kw = round(total_capex / max(total_kw, 1), 0)

    # --- OPEX ---
    annual_opex = (
        solar_mw * 1000 * OPEX["solar"]
        + bess_mw * 1000 * OPEX["bess"]
        + wind_mw * 1000 * OPEX["wind"]
        + dc_mw * OPEX["data_centre_per_mw"]
    )
    result.opex_annual = round(annual_opex, 0)

    # --- Revenue ---
    gen_revenue = total_yield * ppa_price  # generation PPA
    bess_rev = bess_mw * bess_revenue_per_mw  # BESS stacked revenue
    dc_rev = dc_mw * 600_000  # GBP/MW/yr (hosting/colocation revenue)

    result.annual_revenue = round(gen_revenue + bess_rev + dc_rev, 0)
    result.bess_annual_revenue = round(bess_rev, 0)
    result.dc_annual_revenue = round(dc_rev, 0)

    # --- Cashflows (for IRR/NPV) ---
    cashflows = [-total_capex]
    for yr in range(1, project_life + 1):
        deg = (1 - degradation) ** yr
        esc = (1 + cpi) ** yr

        yr_gen_rev = total_yield * deg * ppa_price * esc
        yr_bess_rev = bess_rev * esc  # BESS revenue escalates
        yr_dc_rev = dc_rev * esc
        yr_opex = annual_opex * esc

        net = yr_gen_rev + yr_bess_rev + yr_dc_rev - yr_opex
        cashflows.append(net)

    result.irr_pct = _compute_irr(cashflows)
    result.npv = round(_compute_npv(cashflows, discount_rate), 0)

    # --- LCOE ---
    if total_yield > 0:
        # Levelized cost: sum of discounted costs / sum of discounted energy
        total_disc_cost = total_capex
        total_disc_energy = 0.0
        for yr in range(1, project_life + 1):
            deg = (1 - degradation) ** yr
            esc = (1 + cpi) ** yr
            disc = (1 + discount_rate) ** yr
            total_disc_cost += (annual_opex * esc) / disc
            total_disc_energy += (total_yield * deg) / disc
        result.lcoe = round(total_disc_cost / max(total_disc_energy, 1), 2)
    else:
        result.lcoe = 0

    # --- Grid curtailment risk ---
    result.grid_curtailment_risk_pct = round(
        _curtailment_risk(gen_mw, grid_headroom_mw), 1,
    )

    # --- Carbon displacement ---
    result.carbon_displacement_tco2 = round(total_yield * UK_GRID_CARBON_INTENSITY, 1)

    # --- Planning risk ---
    result.planning_risk = _planning_risk(technology_mix, area_ha, gen_mw)

    return result


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

SCENARIOS = [
    {
        "id": "solar_fixed",
        "name": "Solar PV — Fixed Tilt",
        "mix": ["solar"],
        "solar_frac": 0.90, "bess_frac": 0.0, "wind_frac": 0.0, "dc_frac": 0.0,
        "tracker": False,
        "min_wind": 0,
    },
    {
        "id": "solar_tracker",
        "name": "Solar PV — Single-Axis Tracker",
        "mix": ["solar"],
        "solar_frac": 0.90, "bess_frac": 0.0, "wind_frac": 0.0, "dc_frac": 0.0,
        "tracker": True,
        "min_wind": 0,
    },
    {
        "id": "solar_bess",
        "name": "Solar + BESS (Co-located)",
        "mix": ["solar", "bess"],
        "solar_frac": 0.80, "bess_frac": 0.05, "wind_frac": 0.0, "dc_frac": 0.0,
        "tracker": False,
        "min_wind": 0,
    },
    {
        "id": "bess_only",
        "name": "BESS Only (Standalone)",
        "mix": ["bess"],
        "solar_frac": 0.0, "bess_frac": 0.15, "wind_frac": 0.0, "dc_frac": 0.0,
        "tracker": False,
        "min_wind": 0,
    },
    {
        "id": "wind_only",
        "name": "Wind Only (Onshore)",
        "mix": ["wind"],
        "solar_frac": 0.0, "bess_frac": 0.0, "wind_frac": 0.90, "dc_frac": 0.0,
        "tracker": False,
        "min_wind": 5.0,
    },
    {
        "id": "solar_wind",
        "name": "Solar + Wind Hybrid",
        "mix": ["solar", "wind"],
        "solar_frac": 0.50, "bess_frac": 0.0, "wind_frac": 0.45, "dc_frac": 0.0,
        "tracker": False,
        "min_wind": 5.0,
    },
    {
        "id": "solar_wind_bess",
        "name": "Solar + Wind + BESS",
        "mix": ["solar", "wind", "bess"],
        "solar_frac": 0.45, "bess_frac": 0.05, "wind_frac": 0.40, "dc_frac": 0.0,
        "tracker": False,
        "min_wind": 5.0,
    },
    {
        "id": "dc_solar_bess",
        "name": "Data Centre + Solar + BESS",
        "mix": ["data_centre", "solar", "bess"],
        "solar_frac": 0.50, "bess_frac": 0.05, "wind_frac": 0.0, "dc_frac": 0.15,
        "tracker": False,
        "min_wind": 0,
    },
]


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

ObjectiveType = Literal["maximize_irr", "minimize_lcoe", "maximize_carbon", "maximize_revenue"]

def _rank_scenarios(
    results: list[ScenarioResult],
    objective: ObjectiveType,
) -> list[ScenarioResult]:
    """Rank feasible scenarios by objective. Infeasible ones go to the end."""
    feasible = [r for r in results if r.feasible]
    infeasible = [r for r in results if not r.feasible]

    if objective == "maximize_irr":
        feasible.sort(key=lambda r: r.irr_pct, reverse=True)
    elif objective == "minimize_lcoe":
        feasible.sort(key=lambda r: r.lcoe if r.lcoe > 0 else 9999)
    elif objective == "maximize_carbon":
        feasible.sort(key=lambda r: r.carbon_displacement_tco2, reverse=True)
    elif objective == "maximize_revenue":
        feasible.sort(key=lambda r: r.annual_revenue, reverse=True)

    # Assign rank
    for i, r in enumerate(feasible):
        pass  # ordering is the rank

    return feasible + infeasible


def _generate_narrative(
    winner: ScenarioResult,
    runner_up: ScenarioResult | None,
    objective: ObjectiveType,
    site_params: dict,
) -> str:
    """Generate a plain-English recommendation narrative."""
    obj_labels = {
        "maximize_irr": "investor return (IRR)",
        "minimize_lcoe": "lowest cost of energy (LCOE)",
        "maximize_carbon": "maximum carbon displacement",
        "maximize_revenue": "maximum annual revenue",
    }

    parts = [
        f"The optimal technology configuration for this {site_params['area_ha']:.0f} ha "
        f"site is **{winner.scenario_name}**, selected to {obj_labels[objective]}.",
        "",
        f"This configuration delivers {winner.total_generation_mw:.1f} MW of generation capacity "
        f"with an estimated annual yield of {winner.annual_yield_mwh:,.0f} MWh "
        f"({winner.capacity_factor_pct:.1f}% capacity factor).",
        "",
        f"Financial summary: {winner.irr_pct:.1f}% IRR, "
        f"LCOE of {winner.lcoe:.1f} GBP/MWh, "
        f"NPV of GBP {winner.npv:,.0f} at {site_params.get('discount_rate', DEFAULT_DISCOUNT_RATE)*100:.0f}% discount rate.",
        "",
        f"Total CAPEX: GBP {winner.capex_total:,.0f} "
        f"(GBP {winner.capex_per_kw:,.0f}/kW). "
        f"Annual revenue: GBP {winner.annual_revenue:,.0f}.",
        "",
        f"Carbon displacement: {winner.carbon_displacement_tco2:,.0f} tCO2/yr. "
        f"Grid curtailment risk: {winner.grid_curtailment_risk_pct:.0f}%. "
        f"Planning risk: {winner.planning_risk}.",
    ]

    if runner_up and runner_up.feasible:
        parts.extend([
            "",
            f"Runner-up: **{runner_up.scenario_name}** "
            f"({runner_up.irr_pct:.1f}% IRR, {runner_up.lcoe:.1f} GBP/MWh LCOE, "
            f"GBP {runner_up.annual_revenue:,.0f}/yr revenue).",
        ])

    if winner.bess_mw > 0:
        parts.extend([
            "",
            f"BESS component: {winner.bess_mw:.1f} MW / {winner.bess_mwh:.1f} MWh, "
            f"contributing GBP {winner.bess_annual_revenue:,.0f}/yr from stacked revenue "
            f"(FFR, DC, BM, wholesale arbitrage).",
        ])

    if winner.dc_mw > 0:
        parts.extend([
            "",
            f"Data centre component: {winner.dc_mw:.1f} MW IT load, "
            f"contributing GBP {winner.dc_annual_revenue:,.0f}/yr from hosting revenue.",
        ])

    # Warnings
    if winner.grid_curtailment_risk_pct > 10:
        parts.extend([
            "",
            "WARNING: Significant grid curtailment risk. Consider flexible connection "
            "agreement (ANM) or adding BESS to absorb excess generation.",
        ])

    if winner.planning_risk == "HIGH":
        parts.extend([
            "",
            "WARNING: High planning risk. Early engagement with local planning authority "
            "and community consultation strongly recommended.",
        ])

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def optimize_site(
    lat: float,
    lon: float,
    area_ha: float,
    grid_headroom_mw: float,
    ghi: float = 1000.0,
    wind_speed: float = 5.5,
    grid_distance_km: float = 3.0,
    objective: ObjectiveType = "maximize_irr",
    ppa_price: float = DEFAULT_PPA_PRICE,
    bess_revenue_per_mw: float = DEFAULT_BESS_REVENUE,
    discount_rate: float = DEFAULT_DISCOUNT_RATE,
    project_life: int = DEFAULT_PROJECT_LIFE,
    degradation: float = DEFAULT_DEGRADATION,
    cpi: float = DEFAULT_CPI,
) -> dict:
    """Evaluate all technology scenarios for a site and return ranked results.

    Parameters
    ----------
    lat, lon : float
        Site coordinates (WGS84).
    area_ha : float
        Developable site area in hectares.
    grid_headroom_mw : float
        Available grid export capacity in MW.
    ghi : float
        Annual global horizontal irradiance (kWh/m2/yr). UK typical 900-1100.
    wind_speed : float
        Mean annual wind speed at hub height (m/s).
    grid_distance_km : float
        Distance to nearest grid connection point (km).
    objective : str
        Ranking objective: maximize_irr, minimize_lcoe, maximize_carbon,
        maximize_revenue.
    ppa_price : float
        Power purchase agreement price (GBP/MWh).
    bess_revenue_per_mw : float
        Annual BESS stacked revenue (GBP/MW/yr).
    discount_rate : float
        WACC / discount rate (decimal, e.g. 0.07).
    project_life : int
        Project lifetime in years.
    degradation : float
        Annual degradation rate (decimal, e.g. 0.005).
    cpi : float
        Annual CPI escalation (decimal, e.g. 0.025).

    Returns
    -------
    dict with keys:
        site: input parameters
        scenarios: list of scenario result dicts (ranked)
        winner: best scenario dict
        runner_up: second-best scenario dict or None
        recommendation: narrative string
        objective: ranking objective used
        feasible_count: number of feasible scenarios
        total_count: total scenarios evaluated
    """

    site_params = {
        "lat": lat,
        "lon": lon,
        "area_ha": area_ha,
        "grid_headroom_mw": grid_headroom_mw,
        "ghi": ghi,
        "wind_speed": wind_speed,
        "grid_distance_km": grid_distance_km,
        "ppa_price": ppa_price,
        "discount_rate": discount_rate,
        "project_life": project_life,
    }

    results: list[ScenarioResult] = []

    for sc in SCENARIOS:
        # Skip wind scenarios if wind speed below threshold
        if wind_speed < sc["min_wind"] and sc["min_wind"] > 0:
            r = ScenarioResult(
                scenario_id=sc["id"],
                scenario_name=sc["name"],
                technology_mix=sc["mix"],
                feasible=False,
                infeasibility_reason=f"Wind speed {wind_speed} m/s below {sc['min_wind']} m/s minimum for wind scenarios",
            )
            results.append(r)
            continue

        r = _evaluate_scenario(
            scenario_id=sc["id"],
            scenario_name=sc["name"],
            technology_mix=sc["mix"],
            area_ha=area_ha,
            grid_headroom_mw=grid_headroom_mw,
            ghi=ghi,
            wind_speed=wind_speed,
            grid_distance_km=grid_distance_km,
            ppa_price=ppa_price,
            bess_revenue_per_mw=bess_revenue_per_mw,
            discount_rate=discount_rate,
            project_life=project_life,
            degradation=degradation,
            cpi=cpi,
            solar_area_frac=sc["solar_frac"],
            bess_area_frac=sc["bess_frac"],
            wind_area_frac=sc["wind_frac"],
            dc_area_frac=sc["dc_frac"],
            tracker=sc["tracker"],
        )
        results.append(r)

    # Rank
    ranked = _rank_scenarios(results, objective)
    feasible = [r for r in ranked if r.feasible]
    winner = feasible[0] if feasible else None
    runner_up = feasible[1] if len(feasible) > 1 else None

    # Narrative
    narrative = ""
    if winner:
        narrative = _generate_narrative(winner, runner_up, objective, site_params)

    return {
        "site": site_params,
        "scenarios": [r.to_dict() for r in ranked],
        "winner": winner.to_dict() if winner else None,
        "runner_up": runner_up.to_dict() if runner_up else None,
        "recommendation": narrative,
        "objective": objective,
        "feasible_count": len(feasible),
        "total_count": len(ranked),
        "cost_benchmarks": COST_BENCHMARKS,
    }


# ---------------------------------------------------------------------------
# CLI for standalone testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    # If invoked with JSON on stdin (subprocess bridge pattern), use that
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            payload = json.loads(raw)
            result = optimize_site(**payload)
            print(json.dumps(result))
            sys.exit(0)

    # Default demo: 40 ha site near Oxford
    result = optimize_site(
        lat=51.75,
        lon=-1.25,
        area_ha=40,
        grid_headroom_mw=30,
        ghi=1020,
        wind_speed=6.2,
        grid_distance_km=2.5,
    )
    print(json.dumps(result, indent=2))
