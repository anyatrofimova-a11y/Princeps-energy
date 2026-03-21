"""
UK Energy System Assumptions — Princeps Reference Library.

Adapted from samvanstroud/UK-Energy-Modelling (CCC Carbon Budget 7).
All parameters sourced from:
  - CCC Seventh Carbon Budget (2024)
  - BEIS/DESNZ Electricity Generation Costs (2023)
  - NESO Future Energy Scenarios (2024)
  - DUKES 2024

Used throughout Princeps for:
  - LCOE calculations in EnergyFlowPanel
  - Financial modelling (IRR, NPV, payback)
  - Capacity factor benchmarks
  - Grid connection cost validation
  - System-level curtailment estimates

No pint dependency — plain floats with units in docstrings.
"""

# ═══════════════════════════════════════════════════════════════
#  ECONOMIC PARAMETERS
# ═══════════════════════════════════════════════════════════════

DISCOUNT_RATE = 0.05                      # Real discount rate
GBP_TO_USD = 1.35                         # 2024 avg
GBP_TO_EUR = 1.18
INFLATION_RATE = 0.025                    # Long-run CPI assumption


def annualised_cost_gbp_per_kw(capex_gbp_kw, opex_frac, lifetime_years, discount_rate=DISCOUNT_RATE):
    """Annualised cost (CAPEX + OPEX) in £/kW/yr."""
    if discount_rate == 0:
        annuity = 1.0 / lifetime_years
    else:
        annuity = discount_rate / (1 - (1 + discount_rate) ** -lifetime_years)
    return capex_gbp_kw * annuity + capex_gbp_kw * opex_frac


# ═══════════════════════════════════════════════════════════════
#  DEMAND & EMISSIONS TARGETS (CCC CB7)
# ═══════════════════════════════════════════════════════════════

CB7_ENERGY_DEMAND_2050_TWH = 692          # Total UK energy demand target
CB7_BUILDINGS_DEMAND_TWH = 355.44         # Buildings sector
CB7_HEAT_FRACTION_BUILDINGS = 0.597       # Heating share of buildings
CO2_EMISSIONS_2050_MT = 59                # Max emissions
CARBON_BUDGET_1990_2050_MT = 26626        # Cumulative cap


# ═══════════════════════════════════════════════════════════════
#  POWER SYSTEM
# ═══════════════════════════════════════════════════════════════

TRANSMISSION_LOSSES = 0.113               # Total T&D losses (CB7 ratio)
# FES 2025: transmission ~3% by 2050; DUKES 2024: total ~9% today


# ═══════════════════════════════════════════════════════════════
#  RENEWABLE ENERGY — LCOE, Capacity Factors, Costs
# ═══════════════════════════════════════════════════════════════

RENEWABLES = {
    "solar": {
        "lcoe_gbp_mwh": 30.0,            # CB7 Table 7.5.1: 27 £/MWh
        "capacity_factor": 0.108,          # UK average (Renewables.ninja / ERA5)
        "capex_gbp_kw": 450,              # Utility-scale ground-mount
        "opex_frac": 0.015,               # 1.5% of CAPEX/yr
        "lifetime_years": 30,
        "degradation_pct_yr": 0.5,        # Annual degradation
        "cb7_mix_ratio": 0.40,            # CB7 portfolio share
        "land_ha_per_mw": 2.0,            # UK typical
    },
    "offshore_wind": {
        "lcoe_gbp_mwh": 41.0,            # CB7 Table 7.5.1: 31 £/MWh
        "capacity_factor": 0.383,          # DESNZ: 61% (some sources)
        "capex_gbp_kw": 1800,
        "opex_frac": 0.02,
        "lifetime_years": 25,
        "degradation_pct_yr": 0.2,
        "cb7_mix_ratio": 0.45,
        "land_ha_per_mw": None,           # Offshore — no land use
    },
    "onshore_wind": {
        "lcoe_gbp_mwh": 36.0,
        "capacity_factor": 0.293,          # DESNZ: 45% (some sources)
        "capex_gbp_kw": 1100,
        "opex_frac": 0.015,
        "lifetime_years": 25,
        "degradation_pct_yr": 0.3,
        "cb7_mix_ratio": 0.15,
        "land_ha_per_mw": 6.0,            # Including buffer zones
    },
}

# Weighted average LCOE across CB7 mix
AVERAGE_LCOE_GBP_MWH = sum(
    r["lcoe_gbp_mwh"] * r["cb7_mix_ratio"] for r in RENEWABLES.values()
)  # ≈ £35.95/MWh

AVERAGE_CAPACITY_FACTOR = sum(
    r["capacity_factor"] * r["cb7_mix_ratio"] for r in RENEWABLES.values()
)  # ≈ 0.259


# ═══════════════════════════════════════════════════════════════
#  BATTERY ENERGY STORAGE (BESS)
# ═══════════════════════════════════════════════════════════════

BESS = {
    "capex_gbp_kwh": 180,                # 2024 UK utility-scale Li-ion
    "capex_gbp_kw": 120,                 # Power conversion system
    "opex_frac": 0.015,
    "lifetime_years": 15,
    "round_trip_efficiency": 0.87,        # DC-DC
    "degradation_pct_yr": 2.0,           # Calendar + cycle degradation
    "typical_duration_hrs": 4,            # 4hr duration standard
    "cycles_per_year": 365,              # 1 cycle/day
    "lcoe_gbp_mwh": 100,                # Placeholder — highly dispatch-dependent
    "revenue_streams": {
        "wholesale_arbitrage_gbp_mwh": 25,
        "frequency_response_gbp_mw_yr": 45000,
        "capacity_market_gbp_kw_yr": 35,
        "tnuos_avoidance_gbp_kw_yr": 15,
    },
}


# ═══════════════════════════════════════════════════════════════
#  MEDIUM-TERM STORAGE (CB7: pumped hydro, compressed air, etc.)
# ═══════════════════════════════════════════════════════════════

MEDIUM_STORAGE = {
    "power_gw": 7,                        # CB7 Table 7.5.1
    "capacity_twh": 0.433,
    "round_trip_efficiency": 0.70,
    "lcoe_gbp_mwh": 100,                 # Placeholder
}


# ═══════════════════════════════════════════════════════════════
#  HYDROGEN STORAGE (CB7)
# ═══════════════════════════════════════════════════════════════

HYDROGEN = {
    "electrolysis": {
        "power_gw": 40,
        "efficiency": 0.74,               # Electrical → H2
        "capex_gbp_kw": 450 / GBP_TO_USD, # ≈ £333/kW (IEA via RS report)
        "opex_frac": 0.015,
        "lifetime_years": 30,
    },
    "cavern_storage": {
        "capacity_twh": 50,               # CB7: 5-9 TWh; FES 2025: 12 TWh
        "capex_gbp_mwh": 400,             # H21 NOE estimate
        "opex_frac": 0.015,
        "lifetime_years": 30,
    },
    "generation": {
        "power_gw": 100,                  # FES 2025: 16.5 GW
        "efficiency": 0.55,               # H2 → electricity
        "capex_gbp_kw": 425 / GBP_TO_USD, # ≈ £315/kW
        "opex_frac": 0.015,
        "lifetime_years": 30,
    },
    "round_trip_efficiency": 0.74 * 0.55, # ≈ 0.407
}


# ═══════════════════════════════════════════════════════════════
#  NUCLEAR (CB7)
# ═══════════════════════════════════════════════════════════════

NUCLEAR = {
    "capacity_gw": 12,
    "capacity_factor": 0.9,
    "lcoe_existing_gbp_mwh": 130,         # Hinkley Point C
    "lcoe_large_gbp_mwh": 80,
    "lcoe_smr_gbp_mwh": 60,              # Small modular reactors
    "average_lcoe_gbp_mwh": 76,           # Weighted: 0.2×130 + 0.2×80 + 0.6×60
}


# ═══════════════════════════════════════════════════════════════
#  GAS CCS (CB7)
# ═══════════════════════════════════════════════════════════════

GAS_CCS = {
    "capacity_gw": 18,                    # CB7 Table 7.5.1
    "lcoe_gbp_mwh": 180,                 # 165-194 £/MWh range
}


# ═══════════════════════════════════════════════════════════════
#  INTERCONNECTORS (CB7)
# ═══════════════════════════════════════════════════════════════

INTERCONNECTORS = {
    "France":       {"capacity_gw": 10, "lcoe_gbp_mwh": 10},
    "Ireland":      {"capacity_gw": 2,  "lcoe_gbp_mwh": 15},
    "Netherlands":  {"capacity_gw": 3,  "lcoe_gbp_mwh": 20},
    "Germany":      {"capacity_gw": 3,  "lcoe_gbp_mwh": 25},
    "Belgium":      {"capacity_gw": 3,  "lcoe_gbp_mwh": 30},
    "Denmark":      {"capacity_gw": 2,  "lcoe_gbp_mwh": 35},
    "Norway":       {"capacity_gw": 2,  "lcoe_gbp_mwh": 40},
}

TOTAL_INTERCONNECTOR_GW = sum(ic["capacity_gw"] for ic in INTERCONNECTORS.values())  # 25 GW


# ═══════════════════════════════════════════════════════════════
#  GRID CONNECTION COSTS (UK typical, validated against CB7)
# ═══════════════════════════════════════════════════════════════

GRID_CONNECTION_COSTS_GBP_KM = {
    "11kv":  80_000,
    "33kv":  150_000,
    "66kv":  300_000,
    "132kv": 500_000,
    "275kv": 800_000,
    "400kv": 1_200_000,
}

# Additional fixed costs per connection
GRID_CONNECTION_FIXED = {
    "switchgear_11kv_gbp": 25_000,
    "switchgear_33kv_gbp": 80_000,
    "transformer_33_11kv_gbp": 150_000,
    "transformer_132_33kv_gbp": 500_000,
    "metering_gbp": 15_000,
    "design_fees_pct": 0.10,              # 10% of total
}


# ═══════════════════════════════════════════════════════════════
#  FINANCIAL MODEL DEFAULTS
# ═══════════════════════════════════════════════════════════════

FINANCIAL_DEFAULTS = {
    "project_lifetime_years": 35,
    "construction_months": 18,            # Solar utility-scale
    "discount_rate": DISCOUNT_RATE,
    "debt_ratio": 0.70,                   # 70% debt / 30% equity
    "cost_of_debt": 0.045,               # 4.5%
    "cost_of_equity": 0.10,              # 10%
    "wacc": 0.70 * 0.045 + 0.30 * 0.10,  # ≈ 6.15%
    "tax_rate": 0.25,                    # UK corporation tax
    "depreciation_years": 25,
    "ppa_price_gbp_mwh": 55,            # Current UK PPA range: £45-65/MWh
    "merchant_price_gbp_mwh": 60,        # Day-ahead baseload
    "cfd_strike_gbp_mwh": 47,           # AR6 solar strike price
    "tnuos_gbp_kw_yr": 50,              # Transmission use of system
    "bsuos_gbp_mwh": 5,                 # Balancing services
}


# ═══════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def lcoe(technology: str) -> float:
    """Get LCOE in £/MWh for a technology. Accepts 'solar', 'bess', 'nuclear', etc."""
    if technology in RENEWABLES:
        return RENEWABLES[technology]["lcoe_gbp_mwh"]
    if technology == "bess":
        return BESS["lcoe_gbp_mwh"]
    if technology == "nuclear":
        return NUCLEAR["average_lcoe_gbp_mwh"]
    if technology == "gas_ccs":
        return GAS_CCS["lcoe_gbp_mwh"]
    return AVERAGE_LCOE_GBP_MWH


def capacity_factor(technology: str) -> float:
    """Get capacity factor for a technology."""
    if technology in RENEWABLES:
        return RENEWABLES[technology]["capacity_factor"]
    if technology == "nuclear":
        return NUCLEAR["capacity_factor"]
    return AVERAGE_CAPACITY_FACTOR


def annual_yield_mwh(capacity_mw: float, technology: str) -> float:
    """Estimate annual yield in MWh for given capacity and technology."""
    cf = capacity_factor(technology)
    return capacity_mw * cf * 8760


def simple_lcoe(capex_gbp_kw: float, opex_frac: float, lifetime: int,
                cf: float, discount_rate: float = DISCOUNT_RATE) -> float:
    """Calculate LCOE from first principles in £/MWh."""
    ann = annualised_cost_gbp_per_kw(capex_gbp_kw, opex_frac, lifetime, discount_rate)
    annual_gen_mwh_per_kw = cf * 8.76  # 8760 hours / 1000 (kW→MW)
    if annual_gen_mwh_per_kw == 0:
        return float("inf")
    return ann / annual_gen_mwh_per_kw


def project_npv(capacity_mw: float, technology: str = "solar",
                ppa_price: float = None, lifetime: int = None) -> dict:
    """Quick NPV estimate for a project.

    Returns dict with annual_revenue, annual_cost, npv_25yr, irr_estimate, payback_years.
    """
    tech = RENEWABLES.get(technology, RENEWABLES["solar"])
    ppa = ppa_price or FINANCIAL_DEFAULTS["ppa_price_gbp_mwh"]
    life = lifetime or tech["lifetime_years"]
    cf = tech["capacity_factor"]
    capex_kw = tech["capex_gbp_kw"]
    opex_frac = tech["opex_frac"]

    annual_mwh = capacity_mw * cf * 8760
    annual_revenue = annual_mwh * ppa
    total_capex = capacity_mw * 1000 * capex_kw
    annual_opex = total_capex * opex_frac
    annual_profit = annual_revenue - annual_opex

    wacc = FINANCIAL_DEFAULTS["wacc"]

    # NPV
    npv = -total_capex + sum(
        annual_profit / (1 + wacc) ** yr
        for yr in range(1, life + 1)
    )

    # Simple payback
    payback = total_capex / annual_profit if annual_profit > 0 else float("inf")

    # IRR estimate (Newton's method, 5 iterations)
    irr = 0.08
    for _ in range(10):
        f = -total_capex + sum(annual_profit / (1 + irr) ** yr for yr in range(1, life + 1))
        fp = sum(-yr * annual_profit / (1 + irr) ** (yr + 1) for yr in range(1, life + 1))
        if abs(fp) > 0:
            irr -= f / fp

    return {
        "capacity_mw": capacity_mw,
        "technology": technology,
        "capacity_factor_pct": round(cf * 100, 1),
        "annual_yield_mwh": round(annual_mwh),
        "annual_revenue_gbp": round(annual_revenue),
        "total_capex_gbp": round(total_capex),
        "annual_opex_gbp": round(annual_opex),
        "npv_gbp": round(npv),
        "irr_pct": round(irr * 100, 2),
        "payback_years": round(payback, 1),
        "lcoe_gbp_mwh": round(simple_lcoe(capex_kw, opex_frac, life, cf), 2),
        "ppa_price_gbp_mwh": ppa,
        "lifetime_years": life,
    }


def technology_comparison(capacity_mw: float = 50) -> list[dict]:
    """Compare all technologies at a given capacity."""
    results = []
    for tech_id, tech in RENEWABLES.items():
        r = project_npv(capacity_mw, tech_id)
        r["technology_label"] = tech_id.replace("_", " ").title()
        results.append(r)
    return sorted(results, key=lambda x: x["lcoe_gbp_mwh"])
