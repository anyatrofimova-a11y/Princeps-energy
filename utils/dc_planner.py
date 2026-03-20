"""
DC Planner — Data Centre Capacity Planning, PUE Modelling & Monitoring

Provides:
  - Rack/hall layout sizing from IT load
  - Power distribution chain (UPS, PDU, switchgear, transformer) with redundancy
  - Cooling load estimation with PUE model (mechanical, free-cooling, evaporative)
  - Cost model (CapEx + OpEx) for UK data centres
  - Anomaly detection engine for operational monitoring
  - Real-time PUE calculator from telemetry
"""

from __future__ import annotations

import math
import random
import logging
from typing import Any

log = logging.getLogger("princeps.dc_planner")

# ============================================================================
# UK Data Centre Cost Benchmarks (2025-26, £/unit)
# ============================================================================

COST_BENCHMARKS = {
    "rack": {"unit_cost": 2500, "description": "42U server rack with cable management"},
    "pdu_a": {"unit_cost": 1800, "description": "Intelligent PDU, 32A 3-phase, per-outlet metering"},
    "pdu_b": {"unit_cost": 1800, "description": "Redundant B-feed PDU"},
    "ups_modular_kw": {"unit_cost": 350, "description": "Modular UPS per kW (Schneider Galaxy VL)"},
    "ups_static_kw": {"unit_cost": 250, "description": "Static UPS per kW (Eaton 93PM)"},
    "generator_kw": {"unit_cost": 180, "description": "Diesel generator per kW (MTU/Caterpillar)"},
    "switchgear_11kv": {"unit_cost": 85000, "description": "11kV RMU panel"},
    "switchgear_33kv": {"unit_cost": 220000, "description": "33kV GIS panel"},
    "transformer_mva": {"unit_cost": 65000, "description": "Dry-type transformer per MVA"},
    "crac_kw": {"unit_cost": 280, "description": "CRAC/CRAH unit per kW cooling"},
    "chiller_kw": {"unit_cost": 320, "description": "Chiller per kW (Carrier/Trane)"},
    "free_cooling_kw": {"unit_cost": 180, "description": "Economiser/free-cooling per kW"},
    "raised_floor_m2": {"unit_cost": 120, "description": "600mm raised floor per m²"},
    "fire_suppression_m2": {"unit_cost": 85, "description": "Novec 1230 fire suppression per m²"},
    "bms_per_rack": {"unit_cost": 450, "description": "BMS/DCIM sensors per rack"},
    "cabling_per_rack": {"unit_cost": 800, "description": "Structured cabling per rack (fibre + copper)"},
    "civil_per_m2": {"unit_cost": 1800, "description": "Shell & core civil works per m²"},
}

# UK electricity price for DC (typically on PPA or direct)
UK_ELEC_PENCE_KWH = 18.0  # Large industrial / PPA rate

# ============================================================================
# Rack Layout Sizing
# ============================================================================

def plan_facility(
    it_load_kw: float = 10000,
    redundancy: str = "N+1",  # N, N+1, 2N, 2N+1
    cooling_type: str = "hybrid",  # mechanical, free_cooling, hybrid, evaporative
    rack_density_kw: float = 8.0,  # kW per rack average
    target_pue: float = 1.3,
    tier: int = 3,  # Uptime Institute Tier 1-4
    lat: float = 52.5,
) -> dict[str, Any]:
    """
    Generate a complete DC facility plan from IT load.

    Returns rack layout, power chain, cooling system, and cost model.
    """
    it_load_mw = it_load_kw / 1000

    # ── Rack Layout ──
    rack_count = math.ceil(it_load_kw / rack_density_kw)
    racks_per_row = 20  # typical hot/cold aisle
    rows = math.ceil(rack_count / (racks_per_row * 2))  # double-sided rows
    halls = max(1, math.ceil(rack_count / 200))  # ~200 racks per hall

    # Floor area: 2.5m² per rack (including aisles)
    whitespace_m2 = rack_count * 2.5
    # Support space (UPS, cooling, switchgear): ~40% of whitespace
    support_m2 = whitespace_m2 * 0.4
    total_m2 = whitespace_m2 + support_m2

    # ── Power Chain ──
    redundancy_factor = _redundancy_factor(redundancy)

    ups_kw = it_load_kw * redundancy_factor
    generator_kw = it_load_kw * redundancy_factor * 1.1  # 10% headroom
    pdu_count = rack_count * (2 if redundancy in ("2N", "2N+1") else 1)

    # Transformer sizing: IT + cooling + losses
    total_facility_kw = it_load_kw * target_pue
    transformer_mva = total_facility_kw / 1000 * redundancy_factor / 0.95  # 95% PF
    transformer_count = math.ceil(transformer_mva / 2.5)  # 2.5 MVA units typical

    # Switchgear
    voltage_kv = 11 if it_load_mw < 20 else 33
    switchgear_panels = math.ceil(transformer_count * 1.5)

    power_chain = {
        "it_load_kw": it_load_kw,
        "it_load_mw": round(it_load_mw, 1),
        "total_facility_kw": round(total_facility_kw, 0),
        "total_facility_mw": round(total_facility_kw / 1000, 1),
        "redundancy": redundancy,
        "redundancy_factor": redundancy_factor,
        "ups_capacity_kw": round(ups_kw, 0),
        "ups_modules": math.ceil(ups_kw / 250),  # 250kW modules
        "generator_capacity_kw": round(generator_kw, 0),
        "generator_sets": math.ceil(generator_kw / 2000),  # 2MW gensets
        "pdu_count": pdu_count,
        "transformer_mva": round(transformer_mva, 1),
        "transformer_count": transformer_count,
        "voltage_kv": voltage_kv,
        "switchgear_panels": switchgear_panels,
    }

    # ── Cooling System ──
    cooling = _plan_cooling(it_load_kw, cooling_type, target_pue, lat, redundancy_factor)

    # ── PUE Model ──
    pue = _calculate_pue(it_load_kw, cooling, power_chain)

    # ── Cost Model ──
    costs = _calculate_costs(
        rack_count, pdu_count, power_chain, cooling,
        total_m2, redundancy, tier,
    )

    # ── Rack Layout for 3D Twin ──
    rack_layout = _generate_rack_layout(rack_count, halls, racks_per_row)

    return {
        "layout": {
            "rack_count": rack_count,
            "rack_density_kw": rack_density_kw,
            "racks_per_row": racks_per_row,
            "rows": rows,
            "halls": halls,
            "whitespace_m2": round(whitespace_m2, 0),
            "support_m2": round(support_m2, 0),
            "total_m2": round(total_m2, 0),
            "total_sqft": round(total_m2 * 10.764, 0),
        },
        "power": power_chain,
        "cooling": cooling,
        "pue": pue,
        "costs": costs,
        "rack_layout": rack_layout,
        "tier": {
            "level": tier,
            "label": f"Tier {tier}",
            "availability": _tier_availability(tier),
            "concurrent_maintainable": tier >= 3,
            "fault_tolerant": tier >= 4,
        },
    }


def simulate_telemetry(
    it_load_kw: float = 10000,
    rack_count: int = 100,
    cooling_type: str = "hybrid",
) -> dict[str, Any]:
    """
    Generate simulated real-time telemetry for DC monitoring.

    Returns per-rack metrics, cooling status, power draw, PUE, and anomalies.
    """
    hour = random.randint(0, 23)
    # Diurnal load pattern (data centres are relatively flat but not perfectly)
    load_factor = 0.85 + 0.15 * math.sin(math.pi * (hour - 6) / 12) if 6 <= hour <= 18 else 0.82

    racks = []
    total_it_power = 0
    anomalies = []

    for i in range(min(rack_count, 100)):  # Cap for performance
        rack_load = random.gauss(it_load_kw / rack_count * load_factor, it_load_kw / rack_count * 0.1)
        rack_load = max(0, rack_load)
        inlet_temp = random.gauss(22.0, 1.5)  # ASHRAE A1: 18-27°C
        outlet_temp = inlet_temp + rack_load * 0.003  # ~3°C per kW
        humidity = random.gauss(45, 5)

        # Anomaly detection
        rack_anomaly = None
        if inlet_temp > 27:
            rack_anomaly = {"type": "thermal", "severity": "warning", "msg": f"Rack {i+1} inlet {inlet_temp:.1f}°C exceeds ASHRAE A1"}
        elif inlet_temp > 32:
            rack_anomaly = {"type": "thermal", "severity": "critical", "msg": f"Rack {i+1} inlet {inlet_temp:.1f}°C CRITICAL"}
        if rack_load > it_load_kw / rack_count * 1.3:
            rack_anomaly = {"type": "power", "severity": "warning", "msg": f"Rack {i+1} load {rack_load:.0f}W exceeds 130% average"}

        if rack_anomaly:
            anomalies.append(rack_anomaly)

        racks.append({
            "id": i + 1,
            "row": i // 20 + 1,
            "position": i % 20 + 1,
            "it_load_kw": round(rack_load / 1000, 2),
            "inlet_temp_c": round(inlet_temp, 1),
            "outlet_temp_c": round(outlet_temp, 1),
            "humidity_pct": round(max(20, min(80, humidity)), 1),
            "status": "critical" if rack_anomaly and rack_anomaly["severity"] == "critical" else
                      "warning" if rack_anomaly else "normal",
        })
        total_it_power += rack_load

    total_it_kw = total_it_power / 1000

    # Cooling power
    cooling_kw = total_it_kw * (0.25 if cooling_type == "free_cooling" else 0.35 if cooling_type == "hybrid" else 0.45)
    # UPS/distribution losses
    losses_kw = total_it_kw * 0.08
    # Lighting + misc
    misc_kw = total_it_kw * 0.02

    total_facility_kw = total_it_kw + cooling_kw + losses_kw + misc_kw
    pue = total_facility_kw / total_it_kw if total_it_kw > 0 else 1.0

    return {
        "timestamp": f"{hour:02d}:00",
        "racks": racks,
        "metrics": {
            "it_load_kw": round(total_it_kw, 1),
            "cooling_kw": round(cooling_kw, 1),
            "ups_losses_kw": round(losses_kw, 1),
            "misc_kw": round(misc_kw, 1),
            "total_facility_kw": round(total_facility_kw, 1),
            "pue": round(pue, 3),
            "pue_target": 1.3,
            "wue": round(random.gauss(0.8, 0.1), 2),  # Water Usage Effectiveness L/kWh
            "avg_inlet_temp_c": round(sum(r["inlet_temp_c"] for r in racks) / len(racks), 1),
            "max_inlet_temp_c": round(max(r["inlet_temp_c"] for r in racks), 1),
            "utilisation_pct": round(total_it_kw / (it_load_kw / 1000) * 100, 1) if it_load_kw > 0 else 0,
        },
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
    }


# ============================================================================
# Internal helpers
# ============================================================================

def _redundancy_factor(scheme: str) -> float:
    return {"N": 1.0, "N+1": 1.15, "2N": 2.0, "2N+1": 2.15}.get(scheme, 1.15)


def _tier_availability(tier: int) -> str:
    return {1: "99.671%", 2: "99.741%", 3: "99.982%", 4: "99.995%"}.get(tier, "99.9%")


def _plan_cooling(
    it_load_kw: float,
    cooling_type: str,
    target_pue: float,
    lat: float,
    redundancy_factor: float,
) -> dict:
    cooling_load_kw = it_load_kw  # Cooling must remove all IT heat
    # Mechanical efficiency (COP)
    cop = {"mechanical": 3.5, "free_cooling": 12.0, "hybrid": 6.0, "evaporative": 8.0}.get(cooling_type, 4.0)
    # Free cooling hours (UK: latitude-dependent)
    free_cooling_hours = min(8760, max(2000, int(4000 + (lat - 50) * 300)))
    free_cooling_pct = free_cooling_hours / 8760 * 100

    cooling_electrical_kw = cooling_load_kw / cop
    cooling_capacity_kw = cooling_load_kw * redundancy_factor

    # Equipment counts
    crac_units = math.ceil(cooling_capacity_kw / 100)  # 100kW CRAC units
    chiller_count = math.ceil(cooling_capacity_kw / 500)  # 500kW chillers
    cooling_towers = math.ceil(cooling_capacity_kw / 1000) if cooling_type in ("hybrid", "evaporative") else 0

    return {
        "type": cooling_type,
        "cooling_load_kw": round(cooling_load_kw, 0),
        "cooling_electrical_kw": round(cooling_electrical_kw, 0),
        "cooling_capacity_kw": round(cooling_capacity_kw, 0),
        "cop": cop,
        "free_cooling_hours_yr": free_cooling_hours,
        "free_cooling_pct": round(free_cooling_pct, 1),
        "crac_units": crac_units,
        "chiller_count": chiller_count,
        "cooling_towers": cooling_towers,
        "water_consumption_m3_yr": round(cooling_load_kw * 0.002 * 8760 / 1000, 0) if cooling_type in ("hybrid", "evaporative") else 0,
    }


def _calculate_pue(it_load_kw: float, cooling: dict, power: dict) -> dict:
    cooling_kw = cooling["cooling_electrical_kw"]
    ups_losses_kw = it_load_kw * 0.04  # ~96% efficient
    distribution_losses_kw = it_load_kw * 0.02
    lighting_misc_kw = it_load_kw * 0.01

    total_facility_kw = it_load_kw + cooling_kw + ups_losses_kw + distribution_losses_kw + lighting_misc_kw
    pue = total_facility_kw / it_load_kw if it_load_kw > 0 else 1.0

    return {
        "pue": round(pue, 3),
        "breakdown": {
            "it_load_kw": round(it_load_kw, 0),
            "cooling_kw": round(cooling_kw, 0),
            "ups_losses_kw": round(ups_losses_kw, 0),
            "distribution_kw": round(distribution_losses_kw, 0),
            "lighting_misc_kw": round(lighting_misc_kw, 0),
            "total_facility_kw": round(total_facility_kw, 0),
        },
        "overhead_pct": round((pue - 1) * 100, 1),
        "annual_it_kwh": round(it_load_kw * 8760, 0),
        "annual_total_kwh": round(total_facility_kw * 8760, 0),
        "annual_waste_kwh": round((total_facility_kw - it_load_kw) * 8760, 0),
    }


def _calculate_costs(
    rack_count: int, pdu_count: int, power: dict, cooling: dict,
    total_m2: float, redundancy: str, tier: int,
) -> dict:
    cb = COST_BENCHMARKS
    # CapEx
    racks = rack_count * cb["rack"]["unit_cost"]
    pdus = pdu_count * cb["pdu_a"]["unit_cost"]
    ups = power["ups_capacity_kw"] * cb["ups_modular_kw"]["unit_cost"]
    generators = power["generator_capacity_kw"] * cb["generator_kw"]["unit_cost"]
    transformers = power["transformer_mva"] * cb["transformer_mva"]["unit_cost"]
    switchgear_key = f"switchgear_{power['voltage_kv']}kv"
    switchgear = power["switchgear_panels"] * cb.get(switchgear_key, cb["switchgear_11kv"])["unit_cost"]
    cooling_cost = cooling["cooling_capacity_kw"] * (cb["chiller_kw"]["unit_cost"] if cooling["type"] == "mechanical" else cb["free_cooling_kw"]["unit_cost"])
    crac = cooling["crac_units"] * cb["crac_kw"]["unit_cost"] * 100
    raised_floor = total_m2 * cb["raised_floor_m2"]["unit_cost"]
    fire = total_m2 * cb["fire_suppression_m2"]["unit_cost"]
    bms = rack_count * cb["bms_per_rack"]["unit_cost"]
    cabling = rack_count * cb["cabling_per_rack"]["unit_cost"]
    civil = total_m2 * cb["civil_per_m2"]["unit_cost"]

    total_capex = racks + pdus + ups + generators + transformers + switchgear + cooling_cost + crac + raised_floor + fire + bms + cabling + civil

    # Tier premium
    tier_multiplier = {1: 1.0, 2: 1.1, 3: 1.25, 4: 1.6}.get(tier, 1.0)
    total_capex *= tier_multiplier

    # OpEx (annual)
    annual_electricity = power["total_facility_kw"] * 8760 * UK_ELEC_PENCE_KWH / 100
    annual_maintenance = total_capex * 0.03  # 3% of CapEx
    annual_staffing = max(200000, rack_count * 1500)  # min 2 staff
    annual_insurance = total_capex * 0.005
    total_opex = annual_electricity + annual_maintenance + annual_staffing + annual_insurance

    return {
        "capex": {
            "racks": round(racks, 0),
            "pdus": round(pdus, 0),
            "ups": round(ups, 0),
            "generators": round(generators, 0),
            "transformers": round(transformers, 0),
            "switchgear": round(switchgear, 0),
            "cooling": round(cooling_cost + crac, 0),
            "raised_floor": round(raised_floor, 0),
            "fire_suppression": round(fire, 0),
            "bms_dcim": round(bms, 0),
            "cabling": round(cabling, 0),
            "civil_works": round(civil, 0),
            "tier_premium_pct": round((tier_multiplier - 1) * 100, 0),
            "total_gbp": round(total_capex, 0),
            "per_kw_gbp": round(total_capex / (power["it_load_kw"] or 1), 0),
            "per_rack_gbp": round(total_capex / (rack_count or 1), 0),
        },
        "opex": {
            "electricity_gbp": round(annual_electricity, 0),
            "maintenance_gbp": round(annual_maintenance, 0),
            "staffing_gbp": round(annual_staffing, 0),
            "insurance_gbp": round(annual_insurance, 0),
            "total_gbp": round(total_opex, 0),
            "per_kw_gbp": round(total_opex / (power["it_load_kw"] or 1), 0),
        },
    }


def estimate_carbon_footprint(
    it_load_kw: float = 10000,
    pue: float = 1.3,
    grid_intensity_gco2: float = 200,
    cfe_pct: float = 50,
    project_life_years: int = 25,
) -> dict:
    """Estimate Scope 1/2/3 carbon footprint for a DC facility."""
    total_facility_kw = it_load_kw * pue
    annual_kwh = total_facility_kw * 8760

    # Scope 2 — grid electricity (adjusted for CFE%)
    grid_fraction = 1.0 - cfe_pct / 100.0
    scope2_annual_tco2 = annual_kwh * grid_fraction * grid_intensity_gco2 / 1_000_000

    # Scope 1 — diesel generators (testing + outages, ~50 hrs/yr)
    diesel_kwh = it_load_kw * 50  # 50 hours generator runtime per year
    scope1_annual_tco2 = diesel_kwh * 0.25 / 1000  # 0.25 kgCO2/kWh diesel

    # Scope 3 — embodied carbon (servers, building, cooling equipment)
    # Approximate: 500 kgCO2/kW IT load embodied, amortised over project life
    embodied_tco2 = it_load_kw * 0.5 / 1000
    scope3_annual_tco2 = embodied_tco2 / project_life_years

    total_annual_tco2 = scope1_annual_tco2 + scope2_annual_tco2 + scope3_annual_tco2
    lifetime_tco2 = total_annual_tco2 * project_life_years

    return {
        "scope1_annual_tco2": round(scope1_annual_tco2, 1),
        "scope2_annual_tco2": round(scope2_annual_tco2, 1),
        "scope3_annual_tco2": round(scope3_annual_tco2, 1),
        "total_annual_tco2": round(total_annual_tco2, 1),
        "lifetime_tco2": round(lifetime_tco2, 0),
        "grid_intensity_gco2": grid_intensity_gco2,
        "cfe_pct": cfe_pct,
        "renewable_offset_annual_mwh": round(annual_kwh * cfe_pct / 100 / 1000, 0),
    }


def estimate_construction_timeline(
    it_load_mw: float = 10,
    tier: int = 3,
    nsip: bool = False,
) -> dict:
    """Estimate construction timeline for a DC facility."""
    # Planning phase
    planning_months = 18 if not nsip else 12  # NSIP can be faster for large schemes
    if tier >= 4:
        planning_months += 6

    # Design & procurement
    design_months = 6

    # Construction
    if it_load_mw <= 10:
        construction_months = 12
    elif it_load_mw <= 50:
        construction_months = 18
    elif it_load_mw <= 200:
        construction_months = 24
    else:
        construction_months = 36

    # Commissioning
    commissioning_months = 3 if tier <= 3 else 6

    total_months = planning_months + design_months + construction_months + commissioning_months

    return {
        "total_months": total_months,
        "phases": {
            "planning_months": planning_months,
            "design_months": design_months,
            "construction_months": construction_months,
            "commissioning_months": commissioning_months,
        },
        "nsip_pathway": nsip,
        "estimated_completion": f"{total_months} months from planning submission",
    }


def estimate_land_area(
    it_load_mw: float = 10,
    density_pct: float = 35,  # Google uses ~30-40% IT density
) -> dict:
    """Calculate land area from IT load and density assumptions."""
    # ~2.5m² per rack, 8kW/rack average → ~312 kW/m² whitespace
    # With 35% density: total land = whitespace / density_pct
    rack_count = math.ceil(it_load_mw * 1000 / 8)
    whitespace_m2 = rack_count * 2.5
    support_m2 = whitespace_m2 * 0.4
    building_m2 = whitespace_m2 + support_m2
    total_site_m2 = building_m2 / (density_pct / 100)

    return {
        "rack_count": rack_count,
        "building_m2": round(building_m2, 0),
        "building_sqft": round(building_m2 * 10.764, 0),
        "total_site_m2": round(total_site_m2, 0),
        "total_site_acres": round(total_site_m2 / 4047, 1),
        "total_site_hectares": round(total_site_m2 / 10000, 1),
        "density_pct": density_pct,
    }


def _generate_rack_layout(rack_count: int, halls: int, racks_per_row: int) -> list[dict]:
    """Generate 3D positions for rack visualization."""
    layout = []
    rack_id = 0
    for hall in range(halls):
        hall_racks = min(rack_count - rack_id, 200)
        rows_in_hall = math.ceil(hall_racks / (racks_per_row * 2))
        for row in range(rows_in_hall):
            for side in range(2):  # hot/cold aisle sides
                for pos in range(racks_per_row):
                    if rack_id >= rack_count:
                        break
                    layout.append({
                        "id": rack_id + 1,
                        "hall": hall + 1,
                        "row": row + 1,
                        "side": "A" if side == 0 else "B",
                        "position": pos + 1,
                        "x": hall * 30 + pos * 0.7,
                        "y": 0,
                        "z": row * 3.6 + side * 1.2,
                    })
                    rack_id += 1
    return layout
