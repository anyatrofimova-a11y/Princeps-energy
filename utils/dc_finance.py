"""DC-native finance model — tenant contracts, capacity + energy charges,
utilisation ramp, take-or-pay floors, pass-through PPAs.

Distinct from PV/BESS finance: DC revenue is primarily a B2B contracted
capacity sale (rent-like), with energy as a pass-through + margin, plus
committed MW ramp-up curves that dominate the first 3-5 years.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from utils.dcf_evaluator import DCFEvaluator, build_amortising_debt

log = logging.getLogger("princeps.dc_finance")


# UK 2026 DC benchmarks per tenant-tier.
TIER_CONTRACTS = {
    "hyperscale": {
        "capacity_charge_gbp_mw_mo":     13_500,   # £13.5k/MW/month
        "energy_markup_gbp_mwh":              2.5, # thin passthrough margin
        "take_or_pay_pct":                   0.85,
        "contract_years":                      15,
        "escalation_pct_yr":                 2.5,
        "tenant_concentration":             "1-2", # very few tenants
    },
    "enterprise": {
        "capacity_charge_gbp_mw_mo":     17_800,
        "energy_markup_gbp_mwh":              8.0,
        "take_or_pay_pct":                   0.65,
        "contract_years":                      7,
        "escalation_pct_yr":                 3.0,
        "tenant_concentration":             "5-15",
    },
    "colocation": {
        "capacity_charge_gbp_mw_mo":     21_000,   # smaller footprints, higher £/MW
        "energy_markup_gbp_mwh":             14.0,
        "take_or_pay_pct":                   0.55,
        "contract_years":                      3,
        "escalation_pct_yr":                 3.5,
        "tenant_concentration":             "20+",
    },
}

BUILD_COSTS = {
    "shell_gbp_per_mw":       3_500_000,
    "mep_gbp_per_mw":         2_800_000,
    "cooling_gbp_per_mw":     1_800_000,
    "grid_connection_lump":     450_000,   # + per-km HV cable
    "commissioning_gbp_pct":       0.06,
}

OPEX = {
    "staff_per_mw_yr":         85_000,
    "maintenance_per_mw_yr":   60_000,
    "insurance_pct_capex_yr":      0.005,
    "rates_per_mw_yr":         38_000,
    "software_per_mw_yr":      12_000,
}


@dataclass
class RampEntry:
    year: int
    mw_online: float
    utilisation_pct: float


def default_ramp(it_load_mw: float, tier: str = "hyperscale") -> list[RampEntry]:
    """Sensible default ramp schedule per tier."""
    if tier == "hyperscale":
        years = [(1, 0.30, 50), (2, 0.70, 75), (3, 1.00, 92), (4, 1.00, 95), (5, 1.00, 96)]
    elif tier == "enterprise":
        years = [(1, 0.25, 45), (2, 0.55, 65), (3, 0.80, 75), (4, 0.95, 82), (5, 1.00, 85)]
    else:
        years = [(1, 0.20, 40), (2, 0.45, 55), (3, 0.70, 68), (4, 0.90, 75), (5, 1.00, 80)]
    return [RampEntry(y, round(it_load_mw * f, 2), u) for (y, f, u) in years]


def dc_financial_model(
    it_load_mw: float,
    pue_target: float = 1.2,
    tier: str = "hyperscale",
    contract_years: int | None = None,
    grid_connection_km: float = 3.0,
    discount_rate_pct: float = 8.5,
    ppa_gbp_mwh: float = 75.0,
    equity_pct: float = 0.40,
    debt_rate_pct: float = 6.5,
    ramp: list[RampEntry] | None = None,
    custom_capacity_charge: float | None = None,
) -> dict[str, Any]:
    """Full DC P&L → IRR / DSCR / lifetime revenue / payback."""
    tc = TIER_CONTRACTS.get(tier, TIER_CONTRACTS["hyperscale"])
    years = contract_years or tc["contract_years"]
    total_mw = it_load_mw * pue_target
    ramp = ramp or default_ramp(it_load_mw, tier)

    # CAPEX
    capex = (
        it_load_mw * BUILD_COSTS["shell_gbp_per_mw"]
        + it_load_mw * BUILD_COSTS["mep_gbp_per_mw"]
        + it_load_mw * BUILD_COSTS["cooling_gbp_per_mw"]
        + BUILD_COSTS["grid_connection_lump"]
        + grid_connection_km * 500_000  # 132kV cable
    )
    capex *= 1 + BUILD_COSTS["commissioning_gbp_pct"]

    # Annual cashflows
    cashflows = []
    cap_charge = custom_capacity_charge or tc["capacity_charge_gbp_mw_mo"]
    energy_markup = tc["energy_markup_gbp_mwh"]
    take_or_pay = tc["take_or_pay_pct"]
    esc = tc["escalation_pct_yr"] / 100

    for year in range(1, years + 1):
        ramp_entry = next((r for r in ramp if r.year == year), ramp[-1])
        mw_effective = max(ramp_entry.mw_online, it_load_mw * take_or_pay)
        utilisation = ramp_entry.utilisation_pct / 100

        # Capacity revenue (contracted, take-or-pay floor)
        cap_rev = mw_effective * cap_charge * 12 * ((1 + esc) ** (year - 1))

        # Energy pass-through — IT consumes at PUE × utilisation
        annual_mwh = total_mw * 8760 * utilisation
        energy_rev = annual_mwh * energy_markup

        revenue = cap_rev + energy_rev

        # Opex
        opex = it_load_mw * (
            OPEX["staff_per_mw_yr"] + OPEX["maintenance_per_mw_yr"]
            + OPEX["rates_per_mw_yr"] + OPEX["software_per_mw_yr"]
        ) + capex * OPEX["insurance_pct_capex_yr"]
        # Power cost at PPA price (passed through, so just cost side)
        power_cost = annual_mwh * ppa_gbp_mwh

        ebitda = revenue - opex - power_cost
        cashflows.append({
            "year": year,
            "mw_online": ramp_entry.mw_online,
            "utilisation_pct": ramp_entry.utilisation_pct,
            "capacity_rev_gbp": round(cap_rev, 0),
            "energy_rev_gbp": round(energy_rev, 0),
            "power_cost_gbp": round(power_cost, 0),
            "opex_gbp": round(opex, 0),
            "ebitda_gbp": round(ebitda, 0),
        })

    # IRR via bisect
    def _npv(r):
        return -capex + sum(cf["ebitda_gbp"] / ((1 + r) ** cf["year"]) for cf in cashflows)
    lo, hi = -0.2, 0.5
    for _ in range(60):
        mid = (lo + hi) / 2
        if _npv(mid) > 0: lo = mid
        else: hi = mid
    irr = (lo + hi) / 2
    r = discount_rate_pct / 100
    npv = _npv(r)

    # DSCR — senior debt 60%, term 15y, interest debt_rate_pct
    debt = capex * (1 - equity_pct)
    debt_rate = debt_rate_pct / 100
    n = min(years, 15)
    annuity = debt * debt_rate / (1 - (1 + debt_rate) ** -n) if debt_rate else 0
    # Steady-state DSCR — use the worst of the late-life EBITDA where
    # utilisation has genuinely plateaued (≥90% or last 3 years), not the
    # first year the project crosses 80% (the old behaviour overstated
    # credit strength ~20-30% by testing during ramp-up).
    ss_years = [cf for cf in cashflows if cf["utilisation_pct"] >= 90]
    if len(ss_years) < 3:
        ss_years = cashflows[-3:] if len(cashflows) >= 3 else cashflows
    ebitdas = [cf["ebitda_gbp"] for cf in ss_years] or [cashflows[-1]["ebitda_gbp"]]
    steady_ebitda = sum(ebitdas) / len(ebitdas)
    worst_ebitda = min(ebitdas)
    dscr = steady_ebitda / annuity if annuity else 0
    dscr_worst = worst_ebitda / annuity if annuity else 0

    # Payback
    cumulative = -capex
    payback_year = None
    for cf in cashflows:
        cumulative += cf["ebitda_gbp"]
        if cumulative >= 0 and payback_year is None:
            payback_year = cf["year"]
    # ── Lender covenants via DCFEvaluator ───────────────────────────
    revenue_sched = [cf["capacity_rev_gbp"] + cf["energy_rev_gbp"] for cf in cashflows]
    opex_sched = [cf["opex_gbp"] + cf["power_cost_gbp"] for cf in cashflows]
    debt_schedule = build_amortising_debt(principal=debt, rate=debt_rate, term_years=n, life_years=years)
    try:
        dcf = DCFEvaluator(
            capex=capex,
            revenue_schedule=revenue_sched,
            opex_schedule=opex_sched,
            tax_rate=0.25,
            wacc=r,
            cost_of_equity=max(r + 0.04, 0.10),
            terminal_growth=0.02,
            debt_schedule=debt_schedule,
            equity=capex * equity_pct,
        ).to_dict()
        covenant_table = dcf["covenants"]
        covenant_summary = dcf["summary"]
    except Exception as _e:
        log.warning("DCFEvaluator failed: %s", _e)
        covenant_table = []
        covenant_summary = {}

    return {
        "tier": tier,
        "it_load_mw": it_load_mw,
        "pue_target": pue_target,
        "total_facility_mw": round(total_mw, 2),
        "contract_years": years,
        "capex_gbp_m": round(capex / 1_000_000, 2),
        "annual_revenue_steady_state_gbp_m": round(
            max((cf["capacity_rev_gbp"] + cf["energy_rev_gbp"]) for cf in cashflows) / 1_000_000, 2
        ),
        "lifetime_revenue_gbp_m": round(
            sum(cf["capacity_rev_gbp"] + cf["energy_rev_gbp"] for cf in cashflows) / 1_000_000, 2
        ),
        "irr_pct": round(irr * 100, 2),
        "npv_gbp_m": round(npv / 1_000_000, 2),
        "dscr": round(dscr, 3),
        "dscr_worst": round(dscr_worst, 3),
        "payback_years": payback_year,
        "ramp_schedule": [{"year": r.year, "mw_online": r.mw_online, "utilisation_pct": r.utilisation_pct} for r in ramp],
        "cashflows": cashflows,
        "covenants": covenant_table,
        "covenant_summary": covenant_summary,
        "contract_assumptions": {
            "capacity_charge_gbp_mw_mo": cap_charge,
            "energy_markup_gbp_mwh": energy_markup,
            "take_or_pay_pct": take_or_pay,
            "escalation_pct_yr": tc["escalation_pct_yr"],
        },
    }
