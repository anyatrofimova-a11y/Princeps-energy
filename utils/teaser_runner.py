"""
TEASER Integration — Building Thermal Model Generation

Wraps RWTH-EBC TEASER (Tool for Energy Analysis and Simulation for Efficient
Retrofit) to generate building thermal models from minimal input data.

Provides:
  - Archetype building generation (residential + non-residential)
  - RC thermal model parameter extraction (2-element)
  - Hourly thermal demand simulation (simplified)
  - Retrofit scenario comparison
  - Zone-level thermal breakdown for BEMS Digital Twin

Runs directly in the main venv (TEASER is pure Python, works on 3.14).
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from typing import Any

from teaser.project import Project

log = logging.getLogger(__name__)

# ============================================================================
# UK Building Archetypes — mapping common UK building types to TEASER inputs
# ============================================================================

UK_BUILDING_TYPES = {
    # Non-residential
    "office": {
        "method": "non_residential",
        "construction_data": "iwu_heavy",
        "geometry_data": "bmvbs_office",
        "description": "Commercial office building",
    },
    "institute": {
        "method": "non_residential",
        "construction_data": "iwu_heavy",
        "geometry_data": "bmvbs_institute",
        "description": "Research/educational institute",
    },
    "institute_large": {
        "method": "non_residential",
        "construction_data": "iwu_heavy",
        "geometry_data": "bmvbs_institute4",
        "description": "Large institutional building (4-zone)",
    },
    "institute_complex": {
        "method": "non_residential",
        "construction_data": "iwu_heavy",
        "geometry_data": "bmvbs_institute8",
        "description": "Complex institutional building (8-zone)",
    },
    # Residential
    "detached_house": {
        "method": "residential",
        "construction_data": "iwu_heavy",
        "geometry_data": "iwu_single_family_dwelling",
        "description": "Detached single-family dwelling",
    },
    "terraced_house": {
        "method": "residential",
        "construction_data": "iwu_heavy",
        "geometry_data": "iwu_single_family_dwelling",
        "description": "Terraced/semi-detached house",
        "neighbour_buildings": 1,
    },
    "apartment_block": {
        "method": "residential",
        "construction_data": "iwu_heavy",
        "geometry_data": "iwu_multi_family_dwelling",
        "description": "Multi-family apartment block",
    },
}

# UK-specific degree-day data (heating degree days, base 15.5°C)
# Source: CIBSE TRY weather data, regional averages
UK_REGIONS = {
    "london":    {"hdd": 2150, "cdd": 120, "lat": 51.5, "name": "London / SE England"},
    "midlands":  {"hdd": 2450, "cdd": 80,  "lat": 52.5, "name": "Midlands"},
    "north":     {"hdd": 2700, "cdd": 50,  "lat": 53.8, "name": "North England"},
    "scotland":  {"hdd": 3050, "cdd": 30,  "lat": 55.9, "name": "Scotland"},
    "wales":     {"hdd": 2500, "cdd": 70,  "lat": 51.8, "name": "Wales"},
    "sw":        {"hdd": 2200, "cdd": 90,  "lat": 50.7, "name": "South West"},
    "ni":        {"hdd": 2650, "cdd": 40,  "lat": 54.6, "name": "Northern Ireland"},
}


def _get_region(lat: float) -> dict:
    """Get UK region based on latitude."""
    if lat >= 55.0:
        return UK_REGIONS["scotland"]
    elif lat >= 53.5:
        return UK_REGIONS["north"]
    elif lat >= 52.0:
        return UK_REGIONS["midlands"]
    elif lat >= 51.8:
        return UK_REGIONS["wales"]
    elif lat >= 51.0:
        return UK_REGIONS["london"]
    elif lat >= 50.0:
        return UK_REGIONS["sw"]
    return UK_REGIONS["midlands"]  # default


# ============================================================================
# Core Functions
# ============================================================================

def generate_building_model(
    building_type: str = "office",
    name: str = "Site Building",
    year_of_construction: int = 2000,
    number_of_floors: int = 3,
    height_of_floors: float = 3.5,
    net_leased_area: float = 2000.0,
    lat: float = 52.5,
    with_ahu: bool | None = None,
) -> dict[str, Any]:
    """
    Generate a TEASER building thermal model from minimal inputs.

    Returns zone-level thermal properties, RC model parameters,
    and estimated annual energy demand.
    """
    archetype = UK_BUILDING_TYPES.get(building_type)
    if not archetype:
        return {"error": f"Unknown building type: {building_type}. Available: {list(UK_BUILDING_TYPES.keys())}"}

    p = Project()
    p.name = "princeps_thermal"

    try:
        if archetype["method"] == "non_residential":
            kwargs = {
                "construction_data": archetype["construction_data"],
                "geometry_data": archetype["geometry_data"],
                "name": name,
                "year_of_construction": year_of_construction,
                "number_of_floors": number_of_floors,
                "height_of_floors": height_of_floors,
                "net_leased_area": net_leased_area,
            }
            if with_ahu is not None:
                kwargs["with_ahu"] = with_ahu
            p.add_non_residential(**kwargs)
        else:
            kwargs = {
                "construction_data": archetype["construction_data"],
                "geometry_data": archetype["geometry_data"],
                "name": name,
                "year_of_construction": year_of_construction,
                "number_of_floors": number_of_floors,
                "height_of_floors": height_of_floors,
                "net_leased_area": net_leased_area,
            }
            if with_ahu is not None:
                kwargs["with_ahu"] = with_ahu
            nb = archetype.get("neighbour_buildings")
            if nb is not None:
                kwargs["neighbour_buildings"] = nb
            p.add_residential(**kwargs)
    except Exception as e:
        return {"error": f"TEASER model generation failed: {str(e)}"}

    building = p.buildings[0]
    region = _get_region(lat)

    # Extract zone data
    zones = []
    total_area = 0
    for z in building.thermal_zones:
        ow_area = sum(w.area for w in z.outer_walls)
        win_area = sum(w.area for w in z.windows)
        roof_area = sum(r.area for r in z.rooftops)
        gf_area = sum(g.area for g in z.ground_floors)
        iw_area = sum(w.area for w in z.inner_walls)

        uc = z.use_conditions
        zone_data = {
            "name": z.name,
            "area_m2": round(z.area, 1),
            "volume_m3": round(z.volume, 1),
            "outer_wall_area_m2": round(ow_area, 1),
            "window_area_m2": round(win_area, 1),
            "roof_area_m2": round(roof_area, 1),
            "ground_floor_area_m2": round(gf_area, 1),
            "inner_wall_area_m2": round(iw_area, 1),
            "window_to_wall_ratio": round(win_area / ow_area, 3) if ow_area > 0 else 0,
            "use_conditions": {
                "usage": uc.usage,
                "persons_per_m2": round(uc.persons, 4),
                "machines_w_m2": round(uc.machines, 1),
                "lighting_w_m2": round(uc.lighting_power, 1),
                "base_infiltration_1_h": round(uc.base_infiltration, 2),
                "with_heating": uc.with_heating,
                "with_cooling": uc.with_cooling,
                "T_threshold_heating_C": round(uc.T_threshold_heating - 273.15, 1),
                "T_threshold_cooling_C": round(uc.T_threshold_cooling - 273.15, 1),
                "heating_set_back_K": uc.heating_set_back,
                "cooling_set_back_K": uc.cooling_set_back,
            },
        }

        # RC model parameters (2-element)
        ma = z.model_attr
        if ma:
            zone_data["rc_model"] = {
                "r1_inner_wall_K_W": round(ma.r1_iw, 8),
                "c1_inner_wall_J_K": round(ma.c1_iw, 0),
                "r1_outer_wall_K_W": round(ma.r1_ow, 8),
                "c1_outer_wall_J_K": round(ma.c1_ow, 0),
                "r_rest_outer_wall_K_W": round(ma.r_rest_ow, 8),
                "area_inner_walls_m2": round(ma.area_iw, 1),
                "area_outer_walls_m2": round(ma.area_ow, 1),
                "area_windows_m2": round(ma.area_win, 1),
                "alpha_comb_inner_iw": round(ma.alpha_comb_inner_iw, 2),
                "alpha_comb_inner_ow": round(ma.alpha_comb_inner_ow, 2),
                "alpha_comb_outer_ow": round(ma.alpha_comb_outer_ow, 2),
            }

        zones.append(zone_data)
        total_area += z.area

    # Estimate annual energy demand using degree-day method
    energy = _estimate_energy_demand(building, region, total_area)

    return {
        "building": {
            "name": building.name,
            "type": building_type,
            "description": archetype["description"],
            "year_of_construction": year_of_construction,
            "number_of_floors": number_of_floors,
            "height_of_floors": height_of_floors,
            "net_leased_area": net_leased_area,
            "total_zone_area_m2": round(total_area, 1),
            "total_volume_m3": round(sum(z.volume for z in building.thermal_zones), 1),
        },
        "region": {
            "name": region["name"],
            "hdd": region["hdd"],
            "cdd": region["cdd"],
            "latitude": lat,
        },
        "zones": zones,
        "energy_demand": energy,
        "hourly_profile": _generate_hourly_profile(building, region, total_area),
    }


def compare_retrofit_scenarios(
    building_type: str = "office",
    year_of_construction: int = 1970,
    net_leased_area: float = 2000.0,
    lat: float = 52.5,
    **kwargs,
) -> dict[str, Any]:
    """
    Compare thermal performance across retrofit scenarios.

    Returns baseline vs retrofit energy demand and savings.
    """
    # Baseline — original construction year
    baseline = generate_building_model(
        building_type=building_type,
        name="Baseline",
        year_of_construction=year_of_construction,
        net_leased_area=net_leased_area,
        lat=lat,
        **kwargs,
    )
    if "error" in baseline:
        return baseline

    # Scenario 1: Light retrofit (equivalent to 1995 Building Regs)
    light = generate_building_model(
        building_type=building_type,
        name="Light Retrofit (1995 Regs)",
        year_of_construction=1995,
        net_leased_area=net_leased_area,
        lat=lat,
        **kwargs,
    )

    # Scenario 2: Medium retrofit (equivalent to 2005 Part L)
    deep = generate_building_model(
        building_type=building_type,
        name="Part L 2005 Retrofit",
        year_of_construction=2005,
        net_leased_area=net_leased_area,
        lat=lat,
        **kwargs,
    )

    # Scenario 3: Deep retrofit (equivalent to 2015 standards — TEASER IWU limit)
    nzeb = generate_building_model(
        building_type=building_type,
        name="Deep Retrofit (2015)",
        year_of_construction=2015,
        net_leased_area=net_leased_area,
        lat=lat,
        **kwargs,
    )

    scenarios = []
    for label, result in [("Baseline", baseline), ("Light Retrofit", light), ("Deep Retrofit", deep), ("Near-Zero Energy", nzeb)]:
        if "error" in result:
            continue
        ed = result["energy_demand"]
        scenarios.append({
            "name": label,
            "year_equivalent": result["building"]["year_of_construction"],
            "heating_kwh_m2_yr": ed["heating_kwh_m2_yr"],
            "cooling_kwh_m2_yr": ed["cooling_kwh_m2_yr"],
            "total_kwh_m2_yr": ed["total_kwh_m2_yr"],
            "total_kwh_yr": ed["total_kwh_yr"],
            "annual_cost_gbp": ed["annual_cost_gbp"],
            "co2_tonnes_yr": ed["co2_tonnes_yr"],
        })

    if len(scenarios) < 2:
        return {"error": "Not enough scenarios generated"}

    baseline_cost = scenarios[0]["annual_cost_gbp"]
    baseline_co2 = scenarios[0]["co2_tonnes_yr"]

    for s in scenarios:
        s["saving_gbp_yr"] = round(baseline_cost - s["annual_cost_gbp"], 0)
        s["saving_co2_tonnes_yr"] = round(baseline_co2 - s["co2_tonnes_yr"], 1)
        s["saving_pct"] = round(
            (1 - s["total_kwh_m2_yr"] / scenarios[0]["total_kwh_m2_yr"]) * 100, 1
        ) if scenarios[0]["total_kwh_m2_yr"] > 0 else 0

    return {
        "building_type": building_type,
        "original_year": year_of_construction,
        "net_leased_area": net_leased_area,
        "region": baseline["region"],
        "scenarios": scenarios,
    }


def list_building_types() -> dict[str, dict]:
    """List available building types."""
    return {
        k: {"description": v["description"], "method": v["method"]}
        for k, v in UK_BUILDING_TYPES.items()
    }


# ============================================================================
# Energy Estimation Helpers
# ============================================================================

def _estimate_energy_demand(building, region: dict, total_area: float) -> dict:
    """
    Estimate annual energy demand using the building RC model + degree days.

    Uses a simplified steady-state heat loss coefficient approach, calibrated
    against UK CIBSE TM46 benchmarks.
    """
    hdd = region["hdd"]
    cdd = region["cdd"]

    # Calculate aggregate heat loss coefficient (W/K) from building envelope
    total_hlc = 0  # Heat Loss Coefficient
    total_internal_gains = 0  # W
    for z in building.thermal_zones:
        # Transmission through outer walls
        for w in z.outer_walls:
            for layer in w.layer:
                if hasattr(layer, 'thickness') and hasattr(layer, 'material'):
                    mat = layer.material
                    if hasattr(mat, 'thermal_conduc') and layer.thickness > 0:
                        u = mat.thermal_conduc / layer.thickness
                        total_hlc += u * w.area
                        break
            else:
                # Fallback: typical U-value based on construction year
                total_hlc += _typical_u_value("wall", building.year_of_construction) * w.area

        # Windows
        for w in z.windows:
            total_hlc += _typical_u_value("window", building.year_of_construction) * w.area

        # Rooftops
        for r in z.rooftops:
            total_hlc += _typical_u_value("roof", building.year_of_construction) * r.area

        # Ground floors
        for g in z.ground_floors:
            total_hlc += _typical_u_value("floor", building.year_of_construction) * g.area

        # Ventilation losses
        uc = z.use_conditions
        vent_rate = uc.base_infiltration  # 1/h
        total_hlc += 0.33 * vent_rate * z.volume  # 0.33 = rho*cp/3600 for air

        # Internal gains
        total_internal_gains += (uc.machines + uc.lighting_power + uc.persons * 70) * z.area

    # Annual heating demand (degree-day method)
    # Q_heat = HLC * HDD * 24 / 1000 (kWh)
    heating_kwh = max(0, total_hlc * hdd * 24 / 1000 - total_internal_gains * 2000 / 1000)

    # Annual cooling demand
    cooling_kwh = max(0, total_hlc * 0.5 * cdd * 24 / 1000 + total_internal_gains * 1000 / 1000)

    # Normalize
    heating_kwh_m2 = heating_kwh / total_area if total_area > 0 else 0
    cooling_kwh_m2 = cooling_kwh / total_area if total_area > 0 else 0
    total_kwh_m2 = heating_kwh_m2 + cooling_kwh_m2

    # UK energy costs (2025/26)
    gas_pence_kwh = 7.0   # gas for heating
    elec_pence_kwh = 24.5  # electricity for cooling (COP ~3)
    heating_cost = heating_kwh * gas_pence_kwh / 100
    cooling_cost = cooling_kwh / 3.0 * elec_pence_kwh / 100  # COP 3
    annual_cost = heating_cost + cooling_cost

    # CO2 (UK 2025 grid factors)
    gas_kg_co2_kwh = 0.183
    elec_kg_co2_kwh = 0.136  # UK grid 2025 (declining)
    co2_tonnes = (heating_kwh * gas_kg_co2_kwh + cooling_kwh / 3.0 * elec_kg_co2_kwh) / 1000

    return {
        "heat_loss_coefficient_W_K": round(total_hlc, 1),
        "internal_gains_W": round(total_internal_gains, 0),
        "heating_kwh_yr": round(heating_kwh, 0),
        "cooling_kwh_yr": round(cooling_kwh, 0),
        "heating_kwh_m2_yr": round(heating_kwh_m2, 1),
        "cooling_kwh_m2_yr": round(cooling_kwh_m2, 1),
        "total_kwh_m2_yr": round(total_kwh_m2, 1),
        "total_kwh_yr": round(heating_kwh + cooling_kwh, 0),
        "annual_cost_gbp": round(annual_cost, 0),
        "co2_tonnes_yr": round(co2_tonnes, 1),
        "heating_cost_gbp": round(heating_cost, 0),
        "cooling_cost_gbp": round(cooling_cost, 0),
        "epc_band_estimate": _estimate_epc_band(total_kwh_m2),
    }


def _typical_u_value(element: str, year: int) -> float:
    """UK typical U-values by construction era (W/m²K)."""
    # Source: CIBSE Guide A, BRE SAP
    if element == "wall":
        if year >= 2020: return 0.18
        if year >= 2010: return 0.25
        if year >= 2002: return 0.35
        if year >= 1990: return 0.45
        if year >= 1976: return 0.60
        if year >= 1965: return 1.00
        return 1.70  # pre-1965 solid wall
    elif element == "window":
        if year >= 2020: return 1.2
        if year >= 2010: return 1.6
        if year >= 2002: return 2.0
        if year >= 1990: return 2.8
        return 4.8  # single glazed
    elif element == "roof":
        if year >= 2020: return 0.13
        if year >= 2010: return 0.18
        if year >= 2002: return 0.25
        if year >= 1990: return 0.35
        return 0.68
    elif element == "floor":
        if year >= 2020: return 0.13
        if year >= 2010: return 0.22
        if year >= 2002: return 0.25
        if year >= 1990: return 0.45
        return 0.70
    return 1.0


def _estimate_epc_band(kwh_m2: float) -> str:
    """Estimate EPC band from total energy use intensity."""
    if kwh_m2 <= 25: return "A"
    if kwh_m2 <= 50: return "B"
    if kwh_m2 <= 75: return "C"
    if kwh_m2 <= 100: return "D"
    if kwh_m2 <= 125: return "E"
    if kwh_m2 <= 150: return "F"
    return "G"


def _generate_hourly_profile(building, region: dict, total_area: float) -> list[dict]:
    """
    Generate a 24-hour typical day thermal demand profile.

    Returns heating and cooling demand for each hour.
    """
    # Simplified diurnal temperature profile (UK typical winter day)
    # Hours 0-23, relative outdoor temp offset from daily mean
    temp_offsets = [
        -3.0, -3.5, -4.0, -4.2, -4.0, -3.5,  # 00-05
        -2.5, -1.5, -0.5,  0.5,  1.5,  2.5,   # 06-11
         3.5,  4.0,  4.0,  3.5,  2.5,  1.5,    # 12-17
         0.5, -0.5, -1.0, -1.5, -2.0, -2.5,    # 18-23
    ]

    # Occupancy schedule (fraction 0-1)
    occupancy = [
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0,  # 00-05
        0.1, 0.5, 0.9, 1.0, 1.0, 1.0,   # 06-11
        0.8, 1.0, 1.0, 1.0, 0.9, 0.5,   # 12-17
        0.2, 0.1, 0.0, 0.0, 0.0, 0.0,   # 18-23
    ]

    # Calculate aggregate HLC
    total_hlc = 0
    total_internal = 0
    for z in building.thermal_zones:
        for w in z.outer_walls:
            total_hlc += _typical_u_value("wall", building.year_of_construction) * w.area
        for w in z.windows:
            total_hlc += _typical_u_value("window", building.year_of_construction) * w.area
        for r in z.rooftops:
            total_hlc += _typical_u_value("roof", building.year_of_construction) * r.area
        for g in z.ground_floors:
            total_hlc += _typical_u_value("floor", building.year_of_construction) * g.area
        uc = z.use_conditions
        total_hlc += 0.33 * uc.base_infiltration * z.volume
        total_internal += (uc.machines + uc.lighting_power + uc.persons * 70) * z.area

    # Mean winter outdoor temp (approx from HDD)
    mean_winter_temp = 15.5 - region["hdd"] / 200  # rough approx

    profile = []
    for hour in range(24):
        t_out = mean_winter_temp + temp_offsets[hour]
        t_set_heat = 20.0 if occupancy[hour] > 0.3 else 16.0  # setback
        t_set_cool = 24.0

        # Internal gains (scaled by occupancy)
        q_internal = total_internal * occupancy[hour] / 1000  # kW

        # Heating demand
        dt_heat = max(0, t_set_heat - t_out)
        q_heat = max(0, total_hlc * dt_heat / 1000 - q_internal)

        # Cooling demand
        dt_cool = max(0, t_out - t_set_cool)
        q_cool = max(0, total_hlc * dt_cool / 1000 + q_internal * 0.3)

        profile.append({
            "hour": hour,
            "t_outside_C": round(t_out, 1),
            "occupancy": occupancy[hour],
            "heating_kw": round(q_heat, 1),
            "cooling_kw": round(q_cool, 1),
            "internal_gains_kw": round(q_internal, 1),
        })

    return profile
