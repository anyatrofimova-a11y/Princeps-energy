"""
DC Advanced Design — capabilities that surpass Ramboll's offering.

Modules:
  1. Heat reuse & district heating revenue model
  2. Liquid/immersion cooling design
  3. Biodiversity Net Gain (BNG) cost estimation
  4. Community sentiment predictor
  5. CFD-lite thermal field model

All functions are synchronous (no DB needed) — called directly from FastAPI.
"""

import math
import random
from typing import Optional

from app.regulatory.versions import nppf_para as _nppf_para

# ═══════════════════════════════════════════════════════════════════════════════
#  1. HEAT REUSE & DISTRICT HEATING REVENUE
# ═══════════════════════════════════════════════════════════════════════════════

# UK district heat network pricing (2025 benchmarks)
HEAT_PRICE_GBP_MWH = 45  # £/MWh thermal — typical UK heat network tariff
HEAT_PUMP_COP = 3.5       # Upgrade from 30-40°C DC reject heat to 70-80°C
HEAT_PUMP_CAPEX_PER_MW = 350_000  # £/MW thermal capacity
PIPE_COST_PER_KM = 800_000  # £/km for pre-insulated district heating pipe (DN200)
CARBON_FACTOR_GAS_KG_MWH = 183  # kg CO2/MWh displaced gas heating


def heat_reuse_assessment(
    it_load_kw: float = 10_000,
    pue: float = 1.3,
    cooling_type: str = "hybrid",
    lat: float = 52.0,
    nearest_heat_network_km: float = 2.0,
    district_heat_demand_mw: float = 5.0,
) -> dict:
    """
    Model waste heat recovery potential and district heating revenue.

    DC waste heat at 30-60°C is upgraded via heat pump to 70-80°C for
    district heating networks. UK Heat Network Zoning (2025) mandates
    zones where DCs must consider heat offtake.
    """
    total_power_kw = it_load_kw * pue
    cooling_load_kw = total_power_kw - it_load_kw  # Heat rejected
    # IT equipment also produces heat — total reject ≈ IT load + cooling overhead
    total_reject_kw = it_load_kw * 0.95 + cooling_load_kw * 0.85

    # Recoverable heat depends on cooling type
    recovery_factors = {
        "mechanical": 0.70,  # Chilled water — good for heat pump
        "hybrid": 0.60,
        "free_cooling": 0.45,  # Lower temp differential
        "evaporative": 0.35,  # Harder to recover
        "immersion": 0.85,   # Excellent — high-grade reject heat (50-60°C)
        "liquid": 0.80,      # Direct-to-chip — 45-55°C
    }
    recovery_pct = recovery_factors.get(cooling_type, 0.5)
    recoverable_kw = total_reject_kw * recovery_pct

    # Heat pump upgrade: COP means 1 kW electrical → COP kW thermal
    # Input: recoverable heat + electricity → upgraded thermal output
    heat_pump_thermal_kw = recoverable_kw * (1 + 1 / HEAT_PUMP_COP)
    heat_pump_electrical_kw = recoverable_kw / HEAT_PUMP_COP

    # Cap at district demand
    deliverable_mw = min(heat_pump_thermal_kw / 1000, district_heat_demand_mw)
    deliverable_kw = deliverable_mw * 1000

    # Revenue (annual, assuming 5,500 heating hours — UK average)
    heating_hours = 5500
    annual_heat_mwh = deliverable_kw / 1000 * heating_hours
    annual_revenue_gbp = annual_heat_mwh * HEAT_PRICE_GBP_MWH

    # Carbon savings — displacing gas boilers
    annual_carbon_saved_tonnes = annual_heat_mwh * CARBON_FACTOR_GAS_KG_MWH / 1000

    # CapEx
    heat_pump_capex = deliverable_mw * HEAT_PUMP_CAPEX_PER_MW
    pipe_capex = nearest_heat_network_km * PIPE_COST_PER_KM
    total_capex = heat_pump_capex + pipe_capex
    # Heat exchanger, controls, metering
    ancillary_capex = total_capex * 0.15
    total_capex += ancillary_capex

    # Payback
    payback_years = total_capex / max(annual_revenue_gbp, 1)

    # PUE benefit — heat reuse effectively reduces "wasted" energy
    pue_credit = deliverable_kw / max(total_power_kw, 1) * 0.08
    effective_pue = pue - pue_credit

    return {
        "total_reject_heat_kw": round(total_reject_kw),
        "recoverable_heat_kw": round(recoverable_kw),
        "recovery_efficiency_pct": round(recovery_pct * 100, 1),
        "heat_pump_output_kw": round(heat_pump_thermal_kw),
        "heat_pump_electrical_kw": round(heat_pump_electrical_kw),
        "deliverable_thermal_mw": round(deliverable_mw, 2),
        "annual_heat_output_mwh": round(annual_heat_mwh),
        "annual_revenue_gbp": round(annual_revenue_gbp),
        "annual_carbon_saved_tonnes": round(annual_carbon_saved_tonnes),
        "capex_heat_pump_gbp": round(heat_pump_capex),
        "capex_pipework_gbp": round(pipe_capex),
        "capex_total_gbp": round(total_capex),
        "payback_years": round(payback_years, 1),
        "effective_pue_with_reuse": round(effective_pue, 3),
        "reject_temperature_c": 35 if cooling_type in ("immersion", "liquid") else 30,
        "supply_temperature_c": 75,  # After heat pump upgrade
        "heat_network_distance_km": nearest_heat_network_km,
        "uk_heat_zoning_eligible": it_load_kw >= 1000,  # >1MW threshold
        "recommendation": (
            "Excellent heat reuse opportunity" if payback_years < 5
            else "Viable with subsidy support" if payback_years < 10
            else "Marginal — consider alternative uses"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  2. LIQUID / IMMERSION COOLING DESIGN
# ═══════════════════════════════════════════════════════════════════════════════

COOLING_TECHNOLOGIES = {
    "air_crac": {
        "name": "Traditional Air (CRAC/CRAH)",
        "pue_range": [1.35, 1.55],
        "max_rack_kw": 15,
        "water_usage": "low",
        "wue_l_kwh": 0.1,
        "capex_per_kw": 320,
        "maturity": "established",
        "heat_grade_c": 25,
    },
    "free_cooling": {
        "name": "Free Cooling (Economiser)",
        "pue_range": [1.15, 1.25],
        "max_rack_kw": 20,
        "water_usage": "none",
        "wue_l_kwh": 0,
        "capex_per_kw": 280,
        "maturity": "established",
        "heat_grade_c": 28,
    },
    "evaporative": {
        "name": "Evaporative Cooling",
        "pue_range": [1.10, 1.20],
        "max_rack_kw": 25,
        "water_usage": "high",
        "wue_l_kwh": 1.8,
        "capex_per_kw": 250,
        "maturity": "established",
        "heat_grade_c": 30,
    },
    "rear_door": {
        "name": "Rear-Door Heat Exchanger (RDHx)",
        "pue_range": [1.08, 1.18],
        "max_rack_kw": 40,
        "water_usage": "none",
        "wue_l_kwh": 0,
        "capex_per_kw": 420,
        "maturity": "growing",
        "heat_grade_c": 40,
    },
    "cold_plate": {
        "name": "Direct-to-Chip (Cold Plate)",
        "pue_range": [1.03, 1.12],
        "max_rack_kw": 80,
        "water_usage": "none",
        "wue_l_kwh": 0,
        "capex_per_kw": 500,
        "maturity": "growing",
        "heat_grade_c": 50,
    },
    "single_phase_immersion": {
        "name": "Single-Phase Immersion",
        "pue_range": [1.02, 1.08],
        "max_rack_kw": 100,
        "water_usage": "none",
        "wue_l_kwh": 0,
        "capex_per_kw": 650,
        "maturity": "emerging",
        "heat_grade_c": 55,
    },
    "two_phase_immersion": {
        "name": "Two-Phase Immersion",
        "pue_range": [1.01, 1.06],
        "max_rack_kw": 150,
        "water_usage": "none",
        "wue_l_kwh": 0,
        "capex_per_kw": 850,
        "maturity": "emerging",
        "heat_grade_c": 60,
    },
}


def liquid_cooling_comparison(
    it_load_kw: float = 10_000,
    target_rack_kw: float = 40,
    lat: float = 52.0,
) -> dict:
    """
    Compare all cooling technologies including liquid/immersion options.

    Returns side-by-side comparison with PUE, rack density, water usage,
    CapEx, heat reuse potential, and readiness assessment.
    """
    # Free-cooling hours based on latitude (UK)
    base_free_hours = 3500 + (lat - 50) * 800  # ~4200 south, ~6500 north
    base_free_hours = max(3000, min(7000, base_free_hours))

    results = []
    for tech_id, tech in COOLING_TECHNOLOGIES.items():
        pue = (tech["pue_range"][0] + tech["pue_range"][1]) / 2
        total_power = it_load_kw * pue
        cooling_power = total_power - it_load_kw

        # Rack count based on density
        rack_kw = min(target_rack_kw, tech["max_rack_kw"])
        rack_count = math.ceil(it_load_kw / rack_kw)

        # Floor area (m² per rack: 3m² for air, 2.5 for liquid, 2 for immersion)
        m2_per_rack = 3.0 if tech_id in ("air_crac", "free_cooling", "evaporative") else 2.5 if tech_id in ("rear_door", "cold_plate") else 2.0
        whitespace_m2 = rack_count * m2_per_rack

        # Annual energy
        annual_kwh = total_power * 8760
        annual_cooling_kwh = cooling_power * 8760

        # Annual water
        annual_water_m3 = tech["wue_l_kwh"] * annual_kwh / 1000

        # CapEx
        cooling_capex = it_load_kw * tech["capex_per_kw"]

        # Can it handle the target density?
        density_capable = tech["max_rack_kw"] >= target_rack_kw

        # Heat reuse potential
        heat_reuse_grade = "excellent" if tech["heat_grade_c"] >= 50 else "good" if tech["heat_grade_c"] >= 35 else "moderate"

        # Annual OpEx (electricity only, UK industrial rate ~£0.20/kWh)
        annual_elec_opex = annual_cooling_kwh * 0.20

        results.append({
            "technology": tech_id,
            "name": tech["name"],
            "pue": round(pue, 3),
            "max_rack_kw": tech["max_rack_kw"],
            "achievable_rack_kw": rack_kw,
            "rack_count": rack_count,
            "whitespace_m2": round(whitespace_m2),
            "total_power_kw": round(total_power),
            "cooling_power_kw": round(cooling_power),
            "annual_energy_mwh": round(annual_kwh / 1000),
            "annual_cooling_mwh": round(annual_cooling_kwh / 1000),
            "annual_water_m3": round(annual_water_m3),
            "wue_l_kwh": tech["wue_l_kwh"],
            "cooling_capex_gbp": round(cooling_capex),
            "annual_cooling_opex_gbp": round(annual_elec_opex),
            "density_capable": density_capable,
            "heat_reuse_grade": heat_reuse_grade,
            "reject_temp_c": tech["heat_grade_c"],
            "maturity": tech["maturity"],
            "water_free": tech["wue_l_kwh"] == 0,
        })

    # Sort by PUE
    results.sort(key=lambda r: r["pue"])

    # Recommendation
    capable = [r for r in results if r["density_capable"]]
    best = capable[0] if capable else results[0]

    return {
        "it_load_kw": it_load_kw,
        "target_rack_kw": target_rack_kw,
        "technologies": results,
        "recommended": best["technology"],
        "recommendation_reason": (
            f"{best['name']} achieves PUE {best['pue']:.3f}, "
            f"supports {best['max_rack_kw']} kW/rack, "
            f"{'zero water' if best['water_free'] else str(best['annual_water_m3']) + ' m³/yr water'}, "
            f"{best['heat_reuse_grade']} heat reuse potential"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  3. BIODIVERSITY NET GAIN (BNG) COST ESTIMATION
# ═══════════════════════════════════════════════════════════════════════════════

# Statutory Biodiversity Metric v1.0 — simplified habitat unit values (unchanged from Metric 4.0)
HABITAT_UNITS_PER_HA = {
    "cropland": 2.0,
    "improved_grassland": 4.0,
    "modified_grassland": 4.0,
    "poor_semi_natural_grassland": 6.0,
    "neutral_grassland": 8.0,
    "mixed_scrub": 6.0,
    "woodland_plantation": 5.0,
    "woodland_broadleaf": 12.0,
    "urban": 0.5,
    "brownfield": 1.0,
    "hardstanding": 0.2,
}

# UK BNG credit costs (2025, £/biodiversity unit)
BNG_CREDIT_COST = {
    "statutory_credits": 42_000,   # DEFRA statutory credit — last resort
    "habitat_bank": 25_000,        # Private habitat banks — typical
    "on_site_creation": 15_000,    # Creating habitat on development site
    "off_site_enhancement": 20_000, # Enhancing nearby degraded land
}


def bng_assessment(
    site_area_ha: float = 5.0,
    existing_habitat: str = "improved_grassland",
    development_footprint_pct: float = 80,
    on_site_habitat_pct: float = 10,
) -> dict:
    """
    Estimate Biodiversity Net Gain obligation and cost.

    UK Environment Act 2021 mandates 10% BNG for all developments.
    Estimates habitat units lost, required gain, and cost of offsetting.
    """
    # Baseline habitat units
    units_per_ha = HABITAT_UNITS_PER_HA.get(existing_habitat, 4.0)
    baseline_units = site_area_ha * units_per_ha

    # Development footprint destroys habitat
    development_ha = site_area_ha * development_footprint_pct / 100
    remaining_ha = site_area_ha - development_ha
    units_lost = development_ha * units_per_ha

    # Remaining habitat retains value (with 20% condition discount from construction)
    units_retained = remaining_ha * units_per_ha * 0.8

    # On-site habitat creation (e.g., green roof, SuDS, wildflower meadow)
    on_site_creation_ha = site_area_ha * on_site_habitat_pct / 100
    on_site_units = on_site_creation_ha * 6.0  # New habitat lower value than mature

    # Post-development total
    post_dev_units = units_retained + on_site_units

    # 10% net gain requirement
    target_units = baseline_units * 1.10
    deficit_units = max(0, target_units - post_dev_units)

    # Cost scenarios
    costs = {}
    for method, cost_per_unit in BNG_CREDIT_COST.items():
        costs[method] = {
            "cost_per_unit": cost_per_unit,
            "total_cost_gbp": round(deficit_units * cost_per_unit),
            "units_purchased": round(deficit_units, 2),
        }

    # Cheapest viable option
    if deficit_units == 0:
        cheapest_method = "none_required"
        cheapest_cost = 0
    else:
        cheapest = min(costs.items(), key=lambda x: x[1]["total_cost_gbp"])
        cheapest_method = cheapest[0]
        cheapest_cost = cheapest[1]["total_cost_gbp"]

    return {
        "site_area_ha": site_area_ha,
        "existing_habitat": existing_habitat,
        "baseline_units": round(baseline_units, 2),
        "units_lost": round(units_lost, 2),
        "units_retained": round(units_retained, 2),
        "on_site_creation_units": round(on_site_units, 2),
        "post_development_units": round(post_dev_units, 2),
        "target_units_110pct": round(target_units, 2),
        "deficit_units": round(deficit_units, 2),
        "net_gain_achieved": deficit_units <= 0,
        "offset_options": costs,
        "recommended_method": cheapest_method,
        "recommended_cost_gbp": cheapest_cost,
        "cost_per_ha_gbp": round(cheapest_cost / max(site_area_ha, 0.01)),
        "on_site_recommendations": [
            "Wildflower meadow on retained land (6 units/ha)",
            "Green/brown roof on buildings (2 units/ha equivalent)",
            "SuDS with marginal planting (4 units/ha)",
            "Native hedgerow planting (3 units per 100m)",
            "Tree planting — broadleaf mix (8 units/ha at 30yr maturity)",
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  4. COMMUNITY SENTIMENT PREDICTOR
# ═══════════════════════════════════════════════════════════════════════════════

def community_sentiment_assessment(
    lat: float = 52.0,
    lon: float = -1.0,
    it_load_mw: float = 30,
    site_area_ha: float = 5.0,
    nearest_residential_m: float = 500,
    nearest_school_m: float = 1000,
    existing_industrial: bool = False,
    height_m: float = 15,
    backup_generators: int = 10,
    construction_months: int = 24,
) -> dict:
    """
    Predict community objection risk for a data centre development.

    Based on UK planning decision analysis patterns — proximity to sensitive
    receptors, visual impact, noise, traffic, and local authority attitude.
    """
    risk_score = 0
    risk_factors = []
    mitigations = []

    # ── Proximity to residential ──
    if nearest_residential_m < 200:
        risk_score += 30
        risk_factors.append({
            "factor": "Residential proximity",
            "impact": "HIGH",
            "detail": f"Dwellings within {nearest_residential_m}m — likely noise/visual objections",
        })
        mitigations.append("Acoustic barrier (3m bund or close-board fence)")
        mitigations.append("Landscape screening with 3m+ evergreen planting")
    elif nearest_residential_m < 500:
        risk_score += 15
        risk_factors.append({
            "factor": "Residential proximity",
            "impact": "MEDIUM",
            "detail": f"Dwellings within {nearest_residential_m}m",
        })
        mitigations.append("Noise impact assessment (BS4142)")
    else:
        risk_factors.append({
            "factor": "Residential proximity",
            "impact": "LOW",
            "detail": f"Nearest residential {nearest_residential_m}m — good separation",
        })

    # ── School/hospital proximity ──
    if nearest_school_m < 500:
        risk_score += 20
        risk_factors.append({
            "factor": "Sensitive receptor (school/hospital)",
            "impact": "HIGH",
            "detail": f"Within {nearest_school_m}m — heightened scrutiny",
        })
        mitigations.append("Pre-application community consultation")
        mitigations.append("Construction management plan (restricted hours)")

    # ── Scale and visual impact ──
    if it_load_mw >= 50:
        risk_score += 15
        risk_factors.append({
            "factor": "Scale (NSIP threshold)",
            "impact": "MEDIUM",
            "detail": f"{it_load_mw}MW exceeds 50MW NSIP threshold — DCO required",
        })
    if height_m > 15:
        risk_score += 10
        risk_factors.append({
            "factor": "Building height",
            "impact": "MEDIUM",
            "detail": f"{height_m}m height — visible from distance",
        })
        mitigations.append("LVIA (Landscape & Visual Impact Assessment)")
        mitigations.append("Recessed building design, green wall cladding")

    # ── Noise (generators + cooling) ──
    if backup_generators >= 10:
        risk_score += 12
        risk_factors.append({
            "factor": "Generator noise",
            "impact": "MEDIUM",
            "detail": f"{backup_generators} diesel generators — testing noise concern",
        })
        mitigations.append("Acoustic enclosures for all generators")
        mitigations.append("Testing restricted to weekday daytime hours")

    # ── Traffic during construction ──
    if construction_months > 18 and site_area_ha > 3:
        risk_score += 10
        risk_factors.append({
            "factor": "Construction traffic",
            "impact": "MEDIUM",
            "detail": f"{construction_months} months construction on {site_area_ha}ha site",
        })
        mitigations.append("Construction Traffic Management Plan (CTMP)")
        mitigations.append("Wheel-washing facility, agreed delivery hours")

    # ── Existing industrial context ──
    if existing_industrial:
        risk_score -= 15
        risk_factors.append({
            "factor": "Industrial context",
            "impact": "POSITIVE",
            "detail": "Site within/adjacent to existing industrial area — precedent helps",
        })

    # ── Water and environmental concern ──
    if it_load_mw >= 20:
        risk_score += 8
        risk_factors.append({
            "factor": "Water consumption concern",
            "impact": "LOW",
            "detail": "Public awareness of DC water usage increasing (media coverage)",
        })
        mitigations.append("Publish water strategy — air-cooled or closed-loop preferred")
        mitigations.append("Community benefit fund (£X per MW per year)")

    risk_score = max(0, min(100, risk_score))

    # Verdict
    if risk_score >= 60:
        verdict = "HIGH_RISK"
        verdict_text = "Significant objection risk — extensive community engagement required"
    elif risk_score >= 30:
        verdict = "MODERATE_RISK"
        verdict_text = "Some objection likely — standard mitigation should suffice"
    else:
        verdict = "LOW_RISK"
        verdict_text = "Low objection risk — proceed with standard pre-app process"

    return {
        "risk_score": risk_score,
        "verdict": verdict,
        "verdict_text": verdict_text,
        "risk_factors": risk_factors,
        "mitigations": mitigations,
        "engagement_strategy": [
            f"Pre-application consultation ({_nppf_para('PRE_APP_CONSULTATION')})",
            "Community exhibition with 3D visualisations",
            "Parish/ward councillor briefing",
            "Noise and traffic FAQ leaflet to nearest 200 addresses",
            "Community liaison officer during construction",
        ] if risk_score >= 30 else [
            "Standard pre-application with LPA",
            "Design & Access Statement with landscape strategy",
        ],
        "estimated_objections": max(0, risk_score // 5),
        "approval_probability_pct": max(40, min(95, 95 - risk_score * 0.6)),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  5. CFD-LITE THERMAL FIELD MODEL
# ═══════════════════════════════════════════════════════════════════════════════

def thermal_field_model(
    rack_count: int = 50,
    rack_kw: float = 15,
    rows: int = 5,
    cooling_type: str = "air_crac",
    crac_count: int = 4,
    containment: str = "hot_aisle",  # hot_aisle, cold_aisle, none
    supply_temp_c: float = 18,
    ambient_temp_c: float = 22,
) -> dict:
    """
    Simplified 2D thermal field model for a DC hall.

    Computes rack inlet temperatures across the floor plan based on
    airflow mixing, CRAC placement, and containment strategy.
    Not full CFD (no Navier-Stokes) but captures bypass airflow
    and hotspot formation patterns.

    Returns a 2D temperature grid suitable for heatmap rendering.
    """
    racks_per_row = rack_count // max(rows, 1)
    grid_x = racks_per_row
    grid_y = rows * 2  # Each row has hot and cold side

    # Initialize temperature field
    field = [[supply_temp_c for _ in range(grid_x)] for _ in range(grid_y)]

    # Heat generation per rack position
    heat_per_rack = rack_kw  # kW → temperature rise

    # Containment efficiency
    containment_factors = {
        "hot_aisle": 0.85,   # 85% of heat captured — good
        "cold_aisle": 0.80,  # 80% — slightly less efficient
        "none": 0.50,        # 50% — significant bypass
    }
    containment_eff = containment_factors.get(containment, 0.5)

    # CRAC cooling capacity per unit (kW)
    total_cooling_kw = rack_count * rack_kw
    crac_capacity_kw = total_cooling_kw / max(crac_count, 1) * 1.1  # 10% margin

    # CRAC positions (distributed along the hall edges)
    crac_positions = []
    for i in range(crac_count):
        cx = int(grid_x * (i + 0.5) / crac_count)
        crac_positions.append(cx)

    # Compute temperature at each position
    hotspots = []
    max_temp = supply_temp_c
    min_temp = supply_temp_c

    for row in range(rows):
        for col in range(racks_per_row):
            # Distance to nearest CRAC
            min_crac_dist = min(abs(col - cp) for cp in crac_positions)
            dist_factor = 1 + min_crac_dist * 0.08  # Further from CRAC = warmer

            # Heat rise through rack (delta-T)
            # Typical: 10-15°C rise for air-cooled, 5-8°C for liquid
            if cooling_type in ("cold_plate", "single_phase_immersion", "two_phase_immersion"):
                base_delta_t = rack_kw * 0.08  # Much lower rise
            else:
                base_delta_t = rack_kw * 0.7  # Air cooling: ~10-15°C

            # Bypass air mixing (reduces containment)
            bypass_penalty = (1 - containment_eff) * base_delta_t * 0.3
            recirculation = dist_factor * 0.5  # Hot air recirculation near edges

            # Cold aisle (inlet) temperature
            cold_y = row * 2
            inlet_temp = supply_temp_c + bypass_penalty + recirculation
            # Add slight randomness for natural variation
            inlet_temp += (hash((row, col)) % 100) / 100 * 1.5
            field[cold_y][col] = round(inlet_temp, 1)

            # Hot aisle (exhaust) temperature
            hot_y = row * 2 + 1
            exhaust_temp = inlet_temp + base_delta_t
            field[hot_y][col] = round(exhaust_temp, 1)

            max_temp = max(max_temp, inlet_temp)
            min_temp = min(min_temp, inlet_temp)

            # Flag hotspots (inlet > ASHRAE A1 limit of 32°C)
            if inlet_temp > 32:
                hotspots.append({
                    "row": row, "col": col,
                    "inlet_temp_c": round(inlet_temp, 1),
                    "severity": "CRITICAL" if inlet_temp > 35 else "WARNING",
                })
            elif inlet_temp > 27:
                hotspots.append({
                    "row": row, "col": col,
                    "inlet_temp_c": round(inlet_temp, 1),
                    "severity": "CAUTION",
                })

    # ASHRAE compliance
    if max_temp <= 27:
        ashrae_class = "Recommended (18-27°C)"
        ashrae_compliant = True
    elif max_temp <= 32:
        ashrae_class = "A1 Allowable (15-32°C)"
        ashrae_compliant = True
    elif max_temp <= 35:
        ashrae_class = "A2 Allowable (10-35°C)"
        ashrae_compliant = True
    else:
        ashrae_class = "OUT OF SPEC (>35°C)"
        ashrae_compliant = False

    return {
        "grid": field,
        "grid_x": grid_x,
        "grid_y": grid_y,
        "rows": rows,
        "racks_per_row": racks_per_row,
        "supply_temp_c": supply_temp_c,
        "max_inlet_temp_c": round(max_temp, 1),
        "min_inlet_temp_c": round(min_temp, 1),
        "avg_inlet_temp_c": round((max_temp + min_temp) / 2, 1),
        "delta_t_c": round(max_temp - supply_temp_c, 1),
        "hotspot_count": len(hotspots),
        "hotspots": hotspots[:20],
        "containment": containment,
        "containment_efficiency_pct": round(containment_eff * 100),
        "ashrae_class": ashrae_class,
        "ashrae_compliant": ashrae_compliant,
        "crac_positions": crac_positions,
        "recommendations": (
            ["All inlet temperatures within ASHRAE Recommended envelope — excellent"]
            if max_temp <= 27 else
            [
                f"{len(hotspots)} positions exceed 27°C — consider:",
                "Add CRAC units near hotspot zones" if len(crac_positions) < rows else "",
                "Improve containment (blanking panels, end-of-row doors)" if containment == "none" else "",
                "Reduce rack density in affected rows" if rack_kw > 20 else "",
                "Consider liquid cooling for high-density positions" if rack_kw > 15 else "",
            ]
        ),
    }
