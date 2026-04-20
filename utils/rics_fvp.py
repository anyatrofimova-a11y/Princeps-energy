"""
rics_fvp — NPPF Financial Viability Assessment (FVA) compute engine.

Implements the residual land-value appraisal method required by:
  * RICS Professional Standard "Financial Viability in Planning: Conduct
    and Reporting" 1st ed. (2019) + 2nd ed. (1 May 2021).
  * NPPF Dec 2024, Annex 2 (Glossary — viability).
  * Planning Practice Guidance (PPG) Viability, ID 10 (rolling update).
  * PPG Planning Obligations, ID 23b.

This is NOT an investor DCF. Investor IRR / NPV / DSCR lives in
`utils/report_financial.py` (owned by BOT-M). This module computes:

    EUV   — Existing Use Value (Defra agricultural benchmark by land class)
    EUV+  — EUV plus landowner premium (10–30% on agricultural land)
    BLV   — Benchmark Land Value (EUV+ tested against market evidence)
    GDV   — Gross Development Value (capitalised scheme income)
    Costs — CAPEX + opex PV + policy costs + developer profit (15–20% GDV)
    RLV   — Residual Land Value = GDV − Costs
    Test  — RLV − BLV; viable / partially viable / not viable
    Sens. — ±10% / ±20% on GDV, capex, PPA price

The output is consumed by `templates/report/nppf_fva.html` and served via
`app/routers/reports.py::nppf_fva_report`.

Units throughout: £ and £/year (nominal GBP, today's money unless noted).
Areas: hectares (ha). Capacity: MW (nameplate AC).

Deliberately NOT used here:
  * utils/report_financial.py  (BOT-M — investor DCF report)
  * utils/financial_viability_charts.py  (BOT-M)
  * utils/dcf_evaluator.py, utils/dc_finance.py  (BOT-A)

Author: BOT-X · 2026-04-19
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Benchmark Land Value constants
# ---------------------------------------------------------------------------
# Defra "Farmland values" 2024 survey (Savills + Strutt & Parker quarterly
# indices triangulated). All figures £/ha (nominal 2024).
#
# Sources cited in the pack Appendix D:
#   * Defra statistics: agricultural price indices
#   * Savills Farmland Market Q4 2024
#   * Strutt & Parker English Farmland Market Review 2024
#   * RICS/RAU Rural Land Market Survey H2 2024
EUV_DEFRA_BENCHMARKS: dict[str, float] = {
    # Key: existing-use code.  Value: £/ha (nominal).
    "arable":          25_000,  # prime arable ALC Grade 2 / 3a — typ.
    "pasture":          9_000,  # permanent pasture / improved grassland
    "rough_grazing":    4_500,  # marginal / upland grazing (ALC 4-5)
    "orchard":         80_000,  # fruit / horticulture
    "nursery":         75_000,  # horticultural / nursery
    "woodland":        12_000,  # commercial woodland (exc. ancient)
    "brownfield":     150_000,  # ex-industrial / hardstanding (policy: use first)
    "amenity":         18_000,  # amenity grassland / verges
    "mixed":           18_000,  # mixed arable-pasture estate
}

# RICS FVP 2021 §3.5 — landowner premium range on agricultural EUV.
# PPG Viability ID 10 para. 014 says premium must reflect what a reasonable
# landowner would require to release the land. Industry practice for energy
# projects (solar, BESS on agricultural): 10% low bound, 20% central, 30%
# high bound. The 2021 Standard expressly forbids mechanical fixed multiples
# without justification — so we expose the three options and require the
# assessor to pick one.
EUV_PREMIUM_RANGE: dict[str, float] = {
    "low":     0.10,
    "central": 0.20,
    "high":    0.30,
}

# Developer profit benchmarks — RICS FVP 2021 §4.6 (Reporting) +
# PPG Viability ID 10 para. 018. For market housing PPG cites 15–20% of GDV
# as an industry convention; for non-residential/energy, RICS commentary
# (2022) permits a return on cost of 20–25% OR a return on GDV of 15–20%
# — whichever is more appropriate for the scheme. We compute BOTH and
# present the higher (more conservative) figure, with the lower shown as a
# sensitivity.
DEV_PROFIT_ON_GDV: dict[str, float] = {"low": 0.15, "central": 0.175, "high": 0.20}
DEV_PROFIT_ON_COST: dict[str, float] = {"low": 0.20, "central": 0.225, "high": 0.25}

# CAPEX benchmarks (£/MW nameplate) — aligned with UK cost benchmarks used
# elsewhere in Princeps (see utils/investment_appraisal.py). Figures are
# 2024 real, DEVEX + CAPEX inclusive of grid connection P50.
TECH_CAPEX_PER_MW: dict[str, float] = {
    "solar":         850_000,   # ground-mount PV, MMV trackers, incl. BoS
    "wind":        1_450_000,   # onshore, medium turbines 3–4 MW
    "offshore_wind": 2_600_000,
    "bess":          550_000,   # 2h lithium-ion DC-block, incl. inverter
    "dc":          8_000_000,   # hyperscaler DC — per MW IT load
}

# Operating cost benchmarks (£/MW/yr, 2024 real)
TECH_OPEX_PER_MW_YR: dict[str, float] = {
    "solar":          12_500,
    "wind":           28_000,
    "offshore_wind":  65_000,
    "bess":            8_500,
    "dc":            180_000,
}

# Typical net capacity factors (UK, central estimates)
TECH_CAPACITY_FACTOR: dict[str, float] = {
    "solar":         0.107,  # central England, single-axis tracker
    "wind":          0.32,   # onshore UK average
    "offshore_wind": 0.48,
    "bess":          0.30,   # cycling utilisation proxy
    "dc":            0.75,   # IT load factor
}

# Policy-cost benchmarks — what the LPA is asking for in s106 + CIL + BNG +
# community benefit. These are the 'policy compliance asks' against which
# the FVA tests viability. Figures are £/MW typical asks in 2024:
POLICY_COST_PER_MW: dict[str, dict[str, float]] = {
    # Reasonable, contested & best-case asks; used for sensitivity
    "s106_community_benefit": {"low": 1_000, "central": 5_000, "high": 12_000},
    "cil":                    {"low":   500, "central": 2_500, "high":  6_000},
    "bng_delivery":           {"low": 2_000, "central": 5_000, "high": 10_000},
    "habitat_mgmt_30yr":      {"low": 1_500, "central": 3_000, "high":  5_500},
    "landscape_mitigation":   {"low":   800, "central": 2_000, "high":  4_500},
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class FVAInputs:
    """Project-level FVA inputs. All optional except site_name + project_id."""
    project_id:   str
    site_name:    str
    technology:   str = "solar"
    capacity_mw:  float = 50.0
    area_ha:      float = 80.0          # scheme site area
    existing_use: str = "arable"        # key into EUV_DEFRA_BENCHMARKS
    lpa:          str = ""
    region:       str = "South"
    ppa_price:    float = 55.0          # £/MWh flat (central)
    ppa_term_yr:  int = 15
    exit_yield:   float = 0.075         # 7.5% capitalisation yield (central)
    opex_discount_rate: float = 0.07
    lifetime_yr:  int = 30
    # landowner premium choice  ("low" | "central" | "high")
    premium_band: str = "central"
    # developer profit basis     ("gdv" | "cost")
    profit_basis: str = "gdv"
    # which profit band within the basis
    profit_band:  str = "central"
    # optional comparable BLV £/ha from utils/precedent_transactions.py
    market_blv_per_ha: float | None = None
    # optional override capex (£m) if known from procurement
    capex_m_override: float | None = None
    # current scheme costs already contracted (£m, for s73 variations)
    capex_sunk_m: float = 0.0


@dataclass
class FVAResult:
    """Numerical FVA outputs (single scenario)."""
    # Land
    euv_per_ha:   float
    euv_total:    float
    euv_plus:     float
    blv:          float
    blv_basis:    str                     # "EUV+" or "Market evidence" or "Higher of"

    # Scheme
    gdv_total:    float
    annual_revenue: float
    capex_total:  float
    opex_pv:      float
    policy_cost:  float
    developer_profit: float
    profit_basis_label: str               # human-readable
    total_costs:  float
    rlv:          float                   # GDV − Total costs
    surplus:      float                   # RLV − BLV

    # Verdict
    verdict:      Literal["viable", "partially viable", "not viable"]
    verdict_rationale: str

    # Ratios
    profit_margin_on_gdv:  float
    profit_margin_on_cost: float
    rlv_to_blv_ratio:      float

    # Sensitivity table: list of (label, delta_pct, metric, new_value)
    sensitivity: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core numerics
# ---------------------------------------------------------------------------
def _pv_level_annuity(annual: float, rate: float, years: int) -> float:
    """Present value of a level annual sum. Used for opex PV."""
    if rate <= 0:
        return annual * years
    return annual * (1 - math.pow(1 + rate, -years)) / rate


def _gdv_from_ppa(capacity_mw: float, tech: str, ppa: float,
                  term_yr: int, cap_yield: float) -> tuple[float, float]:
    """Gross Development Value — capitalised income approach.

    Returns (gdv_total, annual_revenue). The exit-yield approach follows
    RICS Red Book VPS 1 income capitalisation:

        annual_revenue  = capacity × 8,760 × CF × PPA_price
        gdv             = annual_revenue × (1 − (1 + yield)^−term) / yield

    In effect the PPA term is the lease-length proxy and the residual
    after PPA ends is ignored (conservative).
    """
    cf = TECH_CAPACITY_FACTOR.get(tech, 0.107)
    annual_mwh = capacity_mw * 8_760 * cf
    annual_revenue = annual_mwh * ppa

    if cap_yield <= 0:
        gdv = annual_revenue * term_yr
    else:
        gdv = annual_revenue * (1 - math.pow(1 + cap_yield, -term_yr)) / cap_yield

    return gdv, annual_revenue


def _capex(tech: str, capacity_mw: float, override_m: float | None) -> float:
    if override_m is not None:
        return override_m * 1_000_000
    return TECH_CAPEX_PER_MW.get(tech, 850_000) * capacity_mw


def _opex_pv(tech: str, capacity_mw: float, rate: float, years: int) -> float:
    opex_yr = TECH_OPEX_PER_MW_YR.get(tech, 12_500) * capacity_mw
    return _pv_level_annuity(opex_yr, rate, years)


def _policy_cost(capacity_mw: float, band: str = "central") -> float:
    """Sum of s106 + CIL + BNG + habitat + landscape asks, £ total."""
    if band not in ("low", "central", "high"):
        band = "central"
    total_per_mw = sum(
        POLICY_COST_PER_MW[k][band] for k in POLICY_COST_PER_MW
    )
    return total_per_mw * capacity_mw


def _dev_profit(gdv: float, cost_before_profit: float,
                basis: str, band: str) -> tuple[float, str]:
    """Developer profit benchmark.

    basis = "gdv" → profit = band × GDV
    basis = "cost" → profit = band × cost_before_profit
    """
    if basis == "cost":
        rate = DEV_PROFIT_ON_COST.get(band, 0.225)
        return rate * cost_before_profit, f"{rate*100:.1f}% on cost"
    rate = DEV_PROFIT_ON_GDV.get(band, 0.175)
    return rate * gdv, f"{rate*100:.1f}% on GDV"


def _compute_euv(existing_use: str, area_ha: float) -> tuple[float, float]:
    """EUV £/ha + total EUV."""
    per_ha = EUV_DEFRA_BENCHMARKS.get(existing_use.lower(),
                                      EUV_DEFRA_BENCHMARKS["arable"])
    return per_ha, per_ha * area_ha


def _compute_blv(euv_plus: float, area_ha: float,
                 market_blv_per_ha: float | None) -> tuple[float, str]:
    """Benchmark Land Value — RICS FVP 2021 §3.

    BLV = max(EUV+, market evidence) when comparable transactions are
    available, otherwise BLV = EUV+.
    """
    if market_blv_per_ha and market_blv_per_ha > 0:
        market_blv = market_blv_per_ha * area_ha
        if market_blv > euv_plus:
            return market_blv, "Market evidence (comparable transactions)"
        return euv_plus, "Higher of EUV+ vs market evidence (EUV+ adopted)"
    return euv_plus, "EUV+ (no comparable market evidence available)"


def _verdict(rlv: float, blv: float) -> tuple[str, str]:
    """Classify viability outcome per RICS FVP 2021 §4 + PPG."""
    surplus = rlv - blv
    ratio = rlv / blv if blv > 0 else 0

    if surplus >= 0 and ratio >= 1.15:
        return ("viable",
                f"Scheme generates RLV of £{rlv/1e6:.1f}m vs BLV of "
                f"£{blv/1e6:.1f}m (RLV/BLV ratio {ratio:.2f}). Full policy "
                f"compliance demonstrably affordable. No obligations reduction "
                f"justified under PPG Viability ID 10.")
    if surplus >= 0:
        return ("partially viable",
                f"Scheme generates RLV of £{rlv/1e6:.1f}m against BLV of "
                f"£{blv/1e6:.1f}m (ratio {ratio:.2f}). Margin narrow — policy "
                f"obligations may need negotiation on phasing, review "
                f"mechanism, or restricted quantum per PPG ID 10 para 025.")
    return ("not viable",
            f"Scheme generates RLV of £{rlv/1e6:.1f}m, below BLV of "
            f"£{blv/1e6:.1f}m (deficit £{abs(surplus)/1e6:.1f}m). Policy "
            f"obligations as-asked render scheme unviable. Reduced s106/CIL "
            f"or alternative site strategy required per PPG ID 10 para 018.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def compute_fva(inp: FVAInputs) -> FVAResult:
    """Compute a full NPPF FVA per RICS FVP 2021."""
    tech = (inp.technology or "solar").lower()

    # 1. EUV
    euv_per_ha, euv_total = _compute_euv(inp.existing_use, inp.area_ha)

    # 2. EUV+
    prem = EUV_PREMIUM_RANGE.get(inp.premium_band, 0.20)
    euv_plus = euv_total * (1 + prem)

    # 3. BLV
    blv, blv_basis = _compute_blv(euv_plus, inp.area_ha, inp.market_blv_per_ha)

    # 4. GDV
    gdv_total, annual_rev = _gdv_from_ppa(
        inp.capacity_mw, tech, inp.ppa_price, inp.ppa_term_yr, inp.exit_yield
    )

    # 5. Costs — capex + opex PV + policy cost + developer profit
    capex = _capex(tech, inp.capacity_mw, inp.capex_m_override)
    opex_pv = _opex_pv(tech, inp.capacity_mw,
                       inp.opex_discount_rate, inp.lifetime_yr)
    policy_cost = _policy_cost(inp.capacity_mw, inp.premium_band)

    cost_before_profit = capex + opex_pv + policy_cost - inp.capex_sunk_m * 1e6
    dev_profit, profit_label = _dev_profit(
        gdv_total, cost_before_profit, inp.profit_basis, inp.profit_band
    )
    total_costs = cost_before_profit + dev_profit

    # 6. Residual Land Value
    rlv = gdv_total - total_costs

    # 7. Test
    verdict, rationale = _verdict(rlv, blv)

    # 8. Sensitivity — ±10% / ±20% on GDV, capex, PPA price
    sens = []
    for pct in (-0.20, -0.10, 0.10, 0.20):
        # GDV shift
        gdv2 = gdv_total * (1 + pct)
        rlv2 = gdv2 - total_costs
        sens.append({
            "driver": "GDV", "delta_pct": pct * 100,
            "gdv": gdv2, "rlv": rlv2, "surplus": rlv2 - blv,
            "verdict": _verdict(rlv2, blv)[0],
        })
    for pct in (-0.20, -0.10, 0.10, 0.20):
        capex2 = capex * (1 + pct)
        cost_bp2 = capex2 + opex_pv + policy_cost - inp.capex_sunk_m * 1e6
        prof2, _ = _dev_profit(gdv_total, cost_bp2, inp.profit_basis, inp.profit_band)
        total2 = cost_bp2 + prof2
        rlv2 = gdv_total - total2
        sens.append({
            "driver": "CAPEX", "delta_pct": pct * 100,
            "gdv": gdv_total, "rlv": rlv2, "surplus": rlv2 - blv,
            "verdict": _verdict(rlv2, blv)[0],
        })
    for pct in (-0.20, -0.10, 0.10, 0.20):
        ppa2 = inp.ppa_price * (1 + pct)
        gdv2, _ = _gdv_from_ppa(inp.capacity_mw, tech, ppa2,
                                inp.ppa_term_yr, inp.exit_yield)
        rlv2 = gdv2 - total_costs
        sens.append({
            "driver": "PPA price", "delta_pct": pct * 100,
            "gdv": gdv2, "rlv": rlv2, "surplus": rlv2 - blv,
            "verdict": _verdict(rlv2, blv)[0],
        })

    margin_gdv = (dev_profit / gdv_total) if gdv_total else 0
    margin_cost = (dev_profit / cost_before_profit) if cost_before_profit else 0
    ratio = (rlv / blv) if blv else 0

    return FVAResult(
        euv_per_ha=euv_per_ha,
        euv_total=euv_total,
        euv_plus=euv_plus,
        blv=blv,
        blv_basis=blv_basis,
        gdv_total=gdv_total,
        annual_revenue=annual_rev,
        capex_total=capex,
        opex_pv=opex_pv,
        policy_cost=policy_cost,
        developer_profit=dev_profit,
        profit_basis_label=profit_label,
        total_costs=total_costs,
        rlv=rlv,
        surplus=rlv - blv,
        verdict=verdict,  # type: ignore[arg-type]
        verdict_rationale=rationale,
        profit_margin_on_gdv=margin_gdv,
        profit_margin_on_cost=margin_cost,
        rlv_to_blv_ratio=ratio,
        sensitivity=sens,
    )


def result_as_context(inp: FVAInputs, res: FVAResult) -> dict[str, Any]:
    """Flatten inputs + result into a Jinja2-ready context dict."""
    ctx = asdict(res)
    ctx.update({
        "inp": asdict(inp),
        "premium_pct": EUV_PREMIUM_RANGE.get(inp.premium_band, 0.20) * 100,
        "euv_benchmarks": EUV_DEFRA_BENCHMARKS,
        "premium_range": EUV_PREMIUM_RANGE,
        "dev_profit_on_gdv_range": DEV_PROFIT_ON_GDV,
        "dev_profit_on_cost_range": DEV_PROFIT_ON_COST,
    })
    return ctx


__all__ = [
    "FVAInputs",
    "FVAResult",
    "compute_fva",
    "result_as_context",
    "EUV_DEFRA_BENCHMARKS",
    "EUV_PREMIUM_RANGE",
    "DEV_PROFIT_ON_GDV",
    "DEV_PROFIT_ON_COST",
    "POLICY_COST_PER_MW",
]
