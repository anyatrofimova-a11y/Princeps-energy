"""
UK Energy System 2050 Scenario Analysis

Extracts key parameters and cost computations from samvanstroud/UK-Energy-Modelling
to provide national-scale energy system context for site-level feasibility analysis.

Source: CCC Seventh Carbon Budget, BEIS, IEA, FES 2025
"""

from __future__ import annotations

import math

# ============================================================================
# Constants (extracted from UK-Energy-Modelling/src/assumptions.py)
# ============================================================================

HOURS_PER_YEAR = 24 * 365.25  # 8766

# 2050 demand & emissions targets
CB7_ENERGY_DEMAND_TWH = 692.0
CB7_BUILDINGS_DEMAND_TWH = 355.44
CB7_HEAT_FRACTION_BUILDINGS = 0.597
CO2_EMISSIONS_2050_MT = 59.0
TOTAL_CO2_BUDGET_1990_2100_MT = 29636.0
NET_NEGATIVE_REMOVALS_MT_YR = 592.72

# Economic
DISCOUNT_RATE = 0.05
GBP_TO_USD = 1.35

# System losses
SYSTEM_LOSSES = 0.113

# Technology parameters: {name: (capacity_GW, capacity_factor, lcoe_gbp_per_mwh)}
TECHNOLOGIES = {
    "solar": {
        "mix_ratio": 0.40,
        "capacity_factor": 0.108,
        "lcoe": 30.0,
    },
    "offshore_wind": {
        "mix_ratio": 0.45,
        "capacity_factor": 0.383,
        "lcoe": 41.0,
    },
    "onshore_wind": {
        "mix_ratio": 0.15,
        "capacity_factor": 0.293,
        "lcoe": 36.0,
    },
}

NUCLEAR = {
    "capacity_gw": 12.0,
    "capacity_factor": 0.90,
    "lcoe_existing": 130.0,
    "lcoe_large": 80.0,
    "lcoe_smr": 60.0,
    "mix_existing": 0.20,
    "mix_large": 0.20,
    "mix_smr": 0.60,
}

GAS_CCS = {
    "capacity_gw": 18.0,
    "lcoe": 180.0,
}

INTERCONNECTORS = {
    "France": {"capacity_gw": 10, "lcoe": 10},
    "Ireland": {"capacity_gw": 2, "lcoe": 15},
    "Netherlands": {"capacity_gw": 3, "lcoe": 20},
    "Germany": {"capacity_gw": 3, "lcoe": 25},
    "Belgium": {"capacity_gw": 3, "lcoe": 30},
    "Denmark": {"capacity_gw": 2, "lcoe": 35},
    "Norway": {"capacity_gw": 2, "lcoe": 40},
}

HYDROGEN_STORAGE = {
    "electrolyser_gw": 40.0,
    "electrolyser_efficiency": 0.74,
    "electrolyser_capex_gbp_kw": 450 / GBP_TO_USD,
    "cavern_capacity_twh": 50.0,
    "cavern_efficiency_roundtrip": 0.407,
    "cavern_capex_gbp_mwh": 400.0,
    "generation_gw": 100.0,
    "generation_efficiency": 0.55,
    "generation_capex_gbp_kw": 425 / GBP_TO_USD,
    "lifetime_years": 30,
}

MEDIUM_STORAGE = {
    "power_gw": 7.0,
    "capacity_twh": 0.433,
    "roundtrip_efficiency": 0.70,
    "lcoe": 100.0,
}

DAC = {
    "capacity_gw": 1.1,
    "carbon_storage_gbp_per_tonne": 7.5,
    "energy_cost_low_kwh_per_tco2": 271.5,   # 43 kJ/mol -> TWh/Mt
    "energy_cost_med_kwh_per_tco2": 637.7,
    "energy_cost_high_kwh_per_tco2": 1023.0,
}

ADDITIONAL_COSTS_GBP_PER_MWH = 4.0


# ============================================================================
# Calculation functions
# ============================================================================

def _annualised_cost(capex: float, opex_fraction: float, lifetime: int, discount_rate: float) -> float:
    """Annualised cost per unit (GBP/kW or GBP/MWh)."""
    opex = capex * opex_fraction
    if discount_rate == 0:
        annuity = lifetime
    else:
        annuity = (1 - (1 + discount_rate) ** -lifetime) / discount_rate
    return capex / annuity + opex


def weighted_renewable_cf() -> float:
    """Weighted average capacity factor across renewable technologies."""
    return sum(t["capacity_factor"] * t["mix_ratio"] for t in TECHNOLOGIES.values())


def weighted_renewable_lcoe() -> float:
    """Weighted average LCOE (GBP/MWh) across renewable technologies."""
    return sum(t["lcoe"] * t["mix_ratio"] for t in TECHNOLOGIES.values())


def nuclear_avg_lcoe() -> float:
    """Weighted average nuclear LCOE."""
    n = NUCLEAR
    return (n["lcoe_existing"] * n["mix_existing"]
            + n["lcoe_large"] * n["mix_large"]
            + n["lcoe_smr"] * n["mix_smr"])


def interconnector_total_gw() -> float:
    return sum(ic["capacity_gw"] for ic in INTERCONNECTORS.values())


def yearly_generation_cost(capacity_gw: float, cf: float, lcoe: float) -> float:
    """Annual cost in GBP billions for a generation source."""
    energy_twh = capacity_gw * cf * HOURS_PER_YEAR / 1000  # GW * h -> GWh -> TWh
    cost_bn = energy_twh * lcoe * 1e6 / 1e9  # TWh * GBP/MWh -> GBP -> GBP bn
    return cost_bn


def hydrogen_storage_annual_cost() -> float:
    """Annualised hydrogen storage system cost in GBP billions."""
    h = HYDROGEN_STORAGE
    elec_ann = _annualised_cost(h["electrolyser_capex_gbp_kw"], 0.015, h["lifetime_years"], DISCOUNT_RATE)
    elec_total = elec_ann * h["electrolyser_gw"] * 1e6  # GW -> kW, * GBP/kW
    cav_ann = _annualised_cost(h["cavern_capex_gbp_mwh"], 0.015, h["lifetime_years"], DISCOUNT_RATE)
    cav_total = cav_ann * h["cavern_capacity_twh"] * 1e6  # TWh -> MWh, * GBP/MWh
    gen_ann = _annualised_cost(h["generation_capex_gbp_kw"], 0.015, h["lifetime_years"], DISCOUNT_RATE)
    gen_total = gen_ann * h["generation_gw"] * 1e6  # GW -> kW
    return (elec_total + cav_total + gen_total) / 1e9  # -> GBP bn


def system_scenario(renewable_capacity_gw: float) -> dict:
    """
    Compute full 2050 energy system scenario for a given renewable capacity.

    Returns dict with generation mix, costs, storage, and carbon metrics.
    """
    cf = weighted_renewable_cf()
    lcoe = weighted_renewable_lcoe()
    n_lcoe = nuclear_avg_lcoe()

    # Generation (TWh/yr)
    renewable_gen = renewable_capacity_gw * cf * HOURS_PER_YEAR / 1000
    nuclear_gen = NUCLEAR["capacity_gw"] * NUCLEAR["capacity_factor"] * HOURS_PER_YEAR / 1000
    total_gen = renewable_gen + nuclear_gen

    # Costs (GBP bn/yr)
    ren_cost = yearly_generation_cost(renewable_capacity_gw, cf, lcoe)
    nuc_cost = yearly_generation_cost(NUCLEAR["capacity_gw"], NUCLEAR["capacity_factor"], n_lcoe)
    h2_cost = hydrogen_storage_annual_cost()
    additional = ADDITIONAL_COSTS_GBP_PER_MWH * CB7_ENERGY_DEMAND_TWH * 1e6 / 1e9  # TWh * GBP/MWh -> bn
    total_cost = ren_cost + nuc_cost + h2_cost + additional

    # System LCOE
    system_lcoe = total_cost * 1e9 / (CB7_ENERGY_DEMAND_TWH * 1e6)  # GBP bn -> GBP / (TWh -> MWh)

    # Overbuild ratio
    overbuild = total_gen / CB7_ENERGY_DEMAND_TWH if CB7_ENERGY_DEMAND_TWH > 0 else 0

    # Capacity breakdown by technology
    tech_breakdown = {}
    for name, tech in TECHNOLOGIES.items():
        cap = renewable_capacity_gw * tech["mix_ratio"]
        gen = cap * tech["capacity_factor"] * HOURS_PER_YEAR / 1000
        cost = yearly_generation_cost(cap, tech["capacity_factor"], tech["lcoe"])
        tech_breakdown[name] = {
            "capacity_gw": round(cap, 1),
            "generation_twh": round(gen, 1),
            "annual_cost_bn": round(cost, 2),
            "lcoe": tech["lcoe"],
            "capacity_factor": tech["capacity_factor"],
        }

    return {
        "renewable_capacity_gw": round(renewable_capacity_gw, 1),
        "demand_twh": CB7_ENERGY_DEMAND_TWH,
        "generation": {
            "renewable_twh": round(renewable_gen, 1),
            "nuclear_twh": round(nuclear_gen, 1),
            "total_twh": round(total_gen, 1),
            "overbuild_ratio": round(overbuild, 2),
        },
        "costs": {
            "renewable_bn": round(ren_cost, 2),
            "nuclear_bn": round(nuc_cost, 2),
            "hydrogen_storage_bn": round(h2_cost, 2),
            "additional_bn": round(additional, 2),
            "total_bn": round(total_cost, 2),
            "system_lcoe_gbp_mwh": round(system_lcoe, 1),
        },
        "technologies": tech_breakdown,
        "nuclear": {
            "capacity_gw": NUCLEAR["capacity_gw"],
            "capacity_factor": NUCLEAR["capacity_factor"],
            "avg_lcoe": round(n_lcoe, 1),
            "generation_twh": round(nuclear_gen, 1),
        },
        "storage": {
            "hydrogen_capacity_twh": HYDROGEN_STORAGE["cavern_capacity_twh"],
            "hydrogen_roundtrip_eff": HYDROGEN_STORAGE["cavern_efficiency_roundtrip"],
            "electrolyser_gw": HYDROGEN_STORAGE["electrolyser_gw"],
            "h2_generation_gw": HYDROGEN_STORAGE["generation_gw"],
            "medium_term_twh": MEDIUM_STORAGE["capacity_twh"],
            "medium_term_gw": MEDIUM_STORAGE["power_gw"],
            "medium_term_eff": MEDIUM_STORAGE["roundtrip_efficiency"],
        },
        "interconnectors": {
            "total_gw": interconnector_total_gw(),
            "countries": {k: v["capacity_gw"] for k, v in INTERCONNECTORS.items()},
        },
        "carbon": {
            "target_emissions_mt": CO2_EMISSIONS_2050_MT,
            "budget_1990_2100_mt": TOTAL_CO2_BUDGET_1990_2100_MT,
            "net_negative_removals_mt_yr": NET_NEGATIVE_REMOVALS_MT_YR,
            "dac_capacity_gw": DAC["capacity_gw"],
        },
        "system_losses": SYSTEM_LOSSES,
    }


def site_in_national_context(
    site_capacity_kw: float,
    site_cf: float = 0.108,
    renewable_capacity_gw: float = 200.0,
) -> dict:
    """
    Place a single solar site in the context of the national 2050 energy system.

    Returns metrics showing the site's contribution to national targets.
    """
    scenario = system_scenario(renewable_capacity_gw)

    site_capacity_mw = site_capacity_kw / 1000
    site_capacity_gw = site_capacity_mw / 1000
    site_gen_mwh = site_capacity_mw * site_cf * HOURS_PER_YEAR
    site_gen_gwh = site_gen_mwh / 1000

    # Fraction of national demand
    demand_mwh = CB7_ENERGY_DEMAND_TWH * 1e6
    fraction_of_demand = site_gen_mwh / demand_mwh if demand_mwh > 0 else 0

    # Fraction of national solar capacity
    national_solar_gw = renewable_capacity_gw * TECHNOLOGIES["solar"]["mix_ratio"]
    fraction_of_solar = site_capacity_gw / national_solar_gw if national_solar_gw > 0 else 0

    # Homes powered (UK avg ~3.5 MWh/yr electricity, but 2050 electrified ~5 MWh/yr)
    homes_powered = site_gen_mwh / 5000

    # Revenue at system LCOE
    system_lcoe = scenario["costs"]["system_lcoe_gbp_mwh"]
    annual_revenue_gbp = site_gen_mwh * system_lcoe

    # CO2 avoided (UK grid carbon intensity target ~20 gCO2/kWh by 2050,
    # but displacing gas CCS at ~100 gCO2/kWh equivalent)
    co2_avoided_tonnes = site_gen_mwh * 0.02  # 20 gCO2/kWh residual grid

    # LCOE comparison
    solar_lcoe = TECHNOLOGIES["solar"]["lcoe"]

    return {
        "site": {
            "capacity_kw": site_capacity_kw,
            "capacity_factor": site_cf,
            "annual_generation_mwh": round(site_gen_mwh, 1),
            "annual_generation_gwh": round(site_gen_gwh, 3),
        },
        "national_context": {
            "fraction_of_demand_pct": round(fraction_of_demand * 100, 6),
            "fraction_of_solar_capacity_pct": round(fraction_of_solar * 100, 6),
            "homes_powered": round(homes_powered, 1),
            "co2_avoided_tonnes_yr": round(co2_avoided_tonnes, 2),
        },
        "economics": {
            "solar_lcoe_gbp_mwh": solar_lcoe,
            "system_lcoe_gbp_mwh": system_lcoe,
            "annual_value_at_system_lcoe_gbp": round(annual_revenue_gbp, 0),
            "solar_vs_system_lcoe_pct": round((solar_lcoe / system_lcoe) * 100, 1) if system_lcoe > 0 else None,
        },
        "scenario_summary": {
            "renewable_capacity_gw": scenario["renewable_capacity_gw"],
            "demand_twh": scenario["demand_twh"],
            "total_generation_twh": scenario["generation"]["total_twh"],
            "total_cost_bn": scenario["costs"]["total_bn"],
        },
    }


def capacity_sweep(min_gw: float = 100, max_gw: float = 400, step_gw: float = 50) -> list[dict]:
    """
    Sweep renewable capacity to show cost-generation trade-off curves.
    Returns list of scenario summaries at each capacity level.
    """
    results = []
    for cap in range(int(min_gw), int(max_gw) + 1, int(step_gw)):
        s = system_scenario(float(cap))
        results.append({
            "renewable_gw": cap,
            "total_gen_twh": s["generation"]["total_twh"],
            "overbuild": s["generation"]["overbuild_ratio"],
            "total_cost_bn": s["costs"]["total_bn"],
            "system_lcoe": s["costs"]["system_lcoe_gbp_mwh"],
            "renewable_cost_bn": s["costs"]["renewable_bn"],
        })
    return results
