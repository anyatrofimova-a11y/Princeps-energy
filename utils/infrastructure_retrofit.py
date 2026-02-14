"""
Infrastructure Retrofitting with Energy Storage Module.

Models retrofitting obsolete infrastructure (dams, power plants, mines,
industrial sites, fossil fuel infra) with energy storage technologies.
Covers cost-effectiveness, circularity, grid flexibility, environmental
and social sustainability, and secure-by-design compliance.

Aligned with EU Horizon Europe call HORIZON-CL5-2027-07-D3-27 and the
BRIDGE initiative.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

# ── Infrastructure Types ─────────────────────────────────────────────────

INFRASTRUCTURE_TYPES: dict[str, dict] = {
    "hydropower_dam": {
        "category": "energy",
        "typical_age_range": (40, 100),
        "structural_elements": ["dam_wall", "spillway", "penstock", "turbine_hall", "tailrace"],
        "repurpose_potential": 95,
        "eu_priority": True,
    },
    "coal_power_plant": {
        "category": "energy",
        "typical_age_range": (30, 60),
        "structural_elements": ["turbine_hall", "boiler_house", "cooling_towers", "chimney", "coal_yard", "grid_connection"],
        "repurpose_potential": 80,
        "eu_priority": True,
    },
    "gas_power_plant": {
        "category": "energy",
        "typical_age_range": (20, 40),
        "structural_elements": ["turbine_hall", "gas_supply", "cooling_system", "control_room", "grid_connection"],
        "repurpose_potential": 75,
        "eu_priority": True,
    },
    "industrial_facility": {
        "category": "industrial",
        "typical_age_range": (25, 80),
        "structural_elements": ["factory_floor", "warehousing", "heavy_foundations", "cranes", "rail_siding"],
        "repurpose_potential": 70,
        "eu_priority": False,
    },
    "coal_mine": {
        "category": "mining",
        "typical_age_range": (50, 150),
        "structural_elements": ["shaft", "tunnels", "headframe", "processing_plant", "spoil_heap"],
        "repurpose_potential": 65,
        "eu_priority": True,
    },
    "oil_gas_infrastructure": {
        "category": "fossil_fuel",
        "typical_age_range": (20, 50),
        "structural_elements": ["wells", "pipelines", "processing", "storage_tanks", "compressors"],
        "repurpose_potential": 60,
        "eu_priority": True,
    },
    "old_substation": {
        "category": "grid",
        "typical_age_range": (30, 60),
        "structural_elements": ["transformers", "switchgear", "busbars", "control_building", "perimeter"],
        "repurpose_potential": 85,
        "eu_priority": False,
    },
    "decommissioned_wind_farm": {
        "category": "energy",
        "typical_age_range": (20, 30),
        "structural_elements": ["foundations", "access_tracks", "substation", "cable_routes", "crane_pads"],
        "repurpose_potential": 90,
        "eu_priority": False,
    },
    "quarry": {
        "category": "mining",
        "typical_age_range": (30, 100),
        "structural_elements": ["pit", "benches", "haul_roads", "processing_plant", "settling_ponds"],
        "repurpose_potential": 75,
        "eu_priority": False,
    },
    "military_base": {
        "category": "government",
        "typical_age_range": (30, 80),
        "structural_elements": ["hardstandings", "bunkers", "perimeter_fence", "buildings", "access_roads"],
        "repurpose_potential": 70,
        "eu_priority": False,
    },
}

# ── Storage Technologies ─────────────────────────────────────────────────

STORAGE_TECHNOLOGIES: dict[str, dict] = {
    "pumped_hydro": {
        "power_range_mw": (10, 2000),
        "duration_hours": (6, 24),
        "round_trip_efficiency_pct": 78,
        "design_life_years": 60,
        "capex_gbp_per_kwh": 50,
        "capex_gbp_per_kw": 1200,
        "recyclability_pct": 90,
        "response_time_seconds": 60,
        "trl": 9,
        "co2_lifecycle_kg_per_mwh": 4,
        "grid_services": ["frequency_response", "capacity_firming", "arbitrage", "black_start"],
    },
    "compressed_air": {
        "power_range_mw": (5, 500),
        "duration_hours": (4, 24),
        "round_trip_efficiency_pct": 65,
        "design_life_years": 40,
        "capex_gbp_per_kwh": 40,
        "capex_gbp_per_kw": 900,
        "recyclability_pct": 85,
        "response_time_seconds": 120,
        "trl": 7,
        "co2_lifecycle_kg_per_mwh": 12,
        "grid_services": ["capacity_firming", "arbitrage", "peak_shaving"],
    },
    "gravity_storage": {
        "power_range_mw": (1, 100),
        "duration_hours": (4, 12),
        "round_trip_efficiency_pct": 80,
        "design_life_years": 50,
        "capex_gbp_per_kwh": 120,
        "capex_gbp_per_kw": 1500,
        "recyclability_pct": 95,
        "response_time_seconds": 10,
        "trl": 6,
        "co2_lifecycle_kg_per_mwh": 6,
        "grid_services": ["frequency_response", "capacity_firming", "arbitrage"],
    },
    "li_ion_bess": {
        "power_range_mw": (0.5, 500),
        "duration_hours": (1, 4),
        "round_trip_efficiency_pct": 90,
        "design_life_years": 15,
        "capex_gbp_per_kwh": 180,
        "capex_gbp_per_kw": 450,
        "recyclability_pct": 70,
        "response_time_seconds": 0.5,
        "trl": 9,
        "co2_lifecycle_kg_per_mwh": 45,
        "grid_services": ["frequency_response", "capacity_firming", "arbitrage", "peak_shaving", "voltage_support"],
    },
    "flow_battery": {
        "power_range_mw": (0.5, 200),
        "duration_hours": (4, 12),
        "round_trip_efficiency_pct": 72,
        "design_life_years": 25,
        "capex_gbp_per_kwh": 250,
        "capex_gbp_per_kw": 1100,
        "recyclability_pct": 80,
        "response_time_seconds": 1,
        "trl": 7,
        "co2_lifecycle_kg_per_mwh": 20,
        "grid_services": ["capacity_firming", "arbitrage", "peak_shaving"],
    },
    "thermal_storage": {
        "power_range_mw": (1, 200),
        "duration_hours": (6, 72),
        "round_trip_efficiency_pct": 55,
        "design_life_years": 30,
        "capex_gbp_per_kwh": 25,
        "capex_gbp_per_kw": 800,
        "recyclability_pct": 90,
        "response_time_seconds": 300,
        "trl": 7,
        "co2_lifecycle_kg_per_mwh": 8,
        "grid_services": ["capacity_firming", "heat_supply", "industrial_process"],
    },
    "hydrogen": {
        "power_range_mw": (1, 1000),
        "duration_hours": (24, 720),
        "round_trip_efficiency_pct": 35,
        "design_life_years": 25,
        "capex_gbp_per_kwh": 15,
        "capex_gbp_per_kw": 2500,
        "recyclability_pct": 75,
        "response_time_seconds": 600,
        "trl": 6,
        "co2_lifecycle_kg_per_mwh": 25,
        "grid_services": ["seasonal_storage", "capacity_firming", "sector_coupling"],
    },
    "flywheel": {
        "power_range_mw": (0.1, 20),
        "duration_hours": (0.1, 0.5),
        "round_trip_efficiency_pct": 92,
        "design_life_years": 20,
        "capex_gbp_per_kwh": 3000,
        "capex_gbp_per_kw": 300,
        "recyclability_pct": 95,
        "response_time_seconds": 0.01,
        "trl": 9,
        "co2_lifecycle_kg_per_mwh": 10,
        "grid_services": ["frequency_response", "voltage_support", "power_quality"],
    },
}

# ── Compatibility Matrix ─────────────────────────────────────────────────

INFRASTRUCTURE_STORAGE_COMPATIBILITY: dict[str, dict[str, dict]] = {
    "hydropower_dam": {
        "pumped_hydro": {"score": 95, "rationale": "Existing reservoir and penstock infrastructure directly reusable"},
        "gravity_storage": {"score": 50, "rationale": "Dam structure adaptable for gravity weights but suboptimal"},
        "hydrogen": {"score": 40, "rationale": "Water supply available; power-to-gas conversion possible"},
    },
    "coal_power_plant": {
        "li_ion_bess": {"score": 85, "rationale": "Existing grid connection, flat hardstanding, control room reusable"},
        "flow_battery": {"score": 75, "rationale": "Large footprint available, existing cooling water, grid connection"},
        "thermal_storage": {"score": 70, "rationale": "Boiler halls adaptable for molten salt/rock storage"},
        "hydrogen": {"score": 65, "rationale": "Grid connection + water supply; turbine hall for electrolysers"},
        "compressed_air": {"score": 45, "rationale": "Grid connection reusable but no underground cavern"},
    },
    "gas_power_plant": {
        "li_ion_bess": {"score": 90, "rationale": "Excellent grid connection, modern control systems, flat site"},
        "flow_battery": {"score": 75, "rationale": "Good footprint and grid, cooling water often available"},
        "hydrogen": {"score": 80, "rationale": "Gas infrastructure partially reusable for H2; strong grid"},
        "thermal_storage": {"score": 60, "rationale": "Turbine hall space available, existing heat management"},
        "flywheel": {"score": 55, "rationale": "High-quality grid connection ideal for fast response"},
    },
    "industrial_facility": {
        "li_ion_bess": {"score": 75, "rationale": "Heavy-duty foundations and power supply often available"},
        "thermal_storage": {"score": 80, "rationale": "Industrial heat demand nearby; existing infrastructure"},
        "flow_battery": {"score": 65, "rationale": "Large floor space, chemical handling experience"},
        "hydrogen": {"score": 55, "rationale": "Industrial gas handling capability may exist"},
    },
    "coal_mine": {
        "compressed_air": {"score": 90, "rationale": "Underground voids ideal for CAES; proven geology"},
        "gravity_storage": {"score": 85, "rationale": "Mine shafts directly usable for gravity weight systems"},
        "pumped_hydro": {"score": 60, "rationale": "Underground cavities for lower reservoir if sealed"},
        "thermal_storage": {"score": 45, "rationale": "Underground thermal mass available"},
    },
    "oil_gas_infrastructure": {
        "hydrogen": {"score": 85, "rationale": "Pipelines, compression, and storage directly reusable for H2"},
        "compressed_air": {"score": 80, "rationale": "Depleted reservoirs and compressor infrastructure"},
        "li_ion_bess": {"score": 60, "rationale": "Site remediation needed but grid connection available"},
        "thermal_storage": {"score": 50, "rationale": "Tank farm adaptable for thermal media"},
    },
    "old_substation": {
        "li_ion_bess": {"score": 95, "rationale": "Existing grid connection at correct voltage; minimal civil works"},
        "flow_battery": {"score": 80, "rationale": "Grid connection ideal; may need footprint expansion"},
        "flywheel": {"score": 85, "rationale": "Grid connection perfect for fast-response frequency services"},
    },
    "decommissioned_wind_farm": {
        "li_ion_bess": {"score": 90, "rationale": "Grid connection, substation, access tracks all reusable"},
        "flow_battery": {"score": 70, "rationale": "Good grid and access; cable routes reusable"},
        "gravity_storage": {"score": 55, "rationale": "Foundations and crane pads provide some infrastructure"},
    },
    "quarry": {
        "pumped_hydro": {"score": 80, "rationale": "Deep pit as lower reservoir; rock faces for dam"},
        "gravity_storage": {"score": 75, "rationale": "Quarry walls for crane-based gravity system"},
        "compressed_air": {"score": 70, "rationale": "Rock cavities potentially suitable for CAES"},
        "li_ion_bess": {"score": 50, "rationale": "Level areas available but limited grid connection"},
    },
    "military_base": {
        "li_ion_bess": {"score": 80, "rationale": "Secure perimeter, hardstandings, often good grid connection"},
        "hydrogen": {"score": 60, "rationale": "Fuel handling experience, secure storage, restricted area"},
        "flywheel": {"score": 65, "rationale": "Bunkers suitable for flywheel containment"},
        "flow_battery": {"score": 55, "rationale": "Buildings and security infrastructure reusable"},
    },
}

# ── Retrofit Cost Benchmarks ─────────────────────────────────────────────

RETROFIT_COST_BENCHMARKS: dict[tuple[str, str], dict] = {
    ("coal_power_plant", "li_ion_bess"): {"retrofit_gbp_per_kw": 320, "greenfield_gbp_per_kw": 450, "saving_pct": 29},
    ("coal_power_plant", "flow_battery"): {"retrofit_gbp_per_kw": 850, "greenfield_gbp_per_kw": 1100, "saving_pct": 23},
    ("coal_power_plant", "thermal_storage"): {"retrofit_gbp_per_kw": 550, "greenfield_gbp_per_kw": 800, "saving_pct": 31},
    ("gas_power_plant", "li_ion_bess"): {"retrofit_gbp_per_kw": 300, "greenfield_gbp_per_kw": 450, "saving_pct": 33},
    ("gas_power_plant", "hydrogen"): {"retrofit_gbp_per_kw": 1800, "greenfield_gbp_per_kw": 2500, "saving_pct": 28},
    ("coal_mine", "compressed_air"): {"retrofit_gbp_per_kw": 600, "greenfield_gbp_per_kw": 900, "saving_pct": 33},
    ("coal_mine", "gravity_storage"): {"retrofit_gbp_per_kw": 1100, "greenfield_gbp_per_kw": 1500, "saving_pct": 27},
    ("hydropower_dam", "pumped_hydro"): {"retrofit_gbp_per_kw": 700, "greenfield_gbp_per_kw": 1200, "saving_pct": 42},
    ("oil_gas_infrastructure", "hydrogen"): {"retrofit_gbp_per_kw": 1600, "greenfield_gbp_per_kw": 2500, "saving_pct": 36},
    ("oil_gas_infrastructure", "compressed_air"): {"retrofit_gbp_per_kw": 550, "greenfield_gbp_per_kw": 900, "saving_pct": 39},
    ("old_substation", "li_ion_bess"): {"retrofit_gbp_per_kw": 280, "greenfield_gbp_per_kw": 450, "saving_pct": 38},
    ("old_substation", "flywheel"): {"retrofit_gbp_per_kw": 220, "greenfield_gbp_per_kw": 300, "saving_pct": 27},
    ("decommissioned_wind_farm", "li_ion_bess"): {"retrofit_gbp_per_kw": 310, "greenfield_gbp_per_kw": 450, "saving_pct": 31},
    ("quarry", "pumped_hydro"): {"retrofit_gbp_per_kw": 850, "greenfield_gbp_per_kw": 1200, "saving_pct": 29},
    ("quarry", "gravity_storage"): {"retrofit_gbp_per_kw": 1000, "greenfield_gbp_per_kw": 1500, "saving_pct": 33},
    ("military_base", "li_ion_bess"): {"retrofit_gbp_per_kw": 350, "greenfield_gbp_per_kw": 450, "saving_pct": 22},
}

# ── Disruption Profiles ──────────────────────────────────────────────────

DISRUPTION_PROFILES: dict[str, dict] = {
    "pumped_hydro": {"months_base": 36, "months_per_100mw": 6, "operational_disruption_pct": 15},
    "compressed_air": {"months_base": 24, "months_per_100mw": 4, "operational_disruption_pct": 20},
    "gravity_storage": {"months_base": 18, "months_per_100mw": 3, "operational_disruption_pct": 10},
    "li_ion_bess": {"months_base": 9, "months_per_100mw": 2, "operational_disruption_pct": 5},
    "flow_battery": {"months_base": 12, "months_per_100mw": 3, "operational_disruption_pct": 8},
    "thermal_storage": {"months_base": 15, "months_per_100mw": 3, "operational_disruption_pct": 12},
    "hydrogen": {"months_base": 24, "months_per_100mw": 5, "operational_disruption_pct": 18},
    "flywheel": {"months_base": 6, "months_per_100mw": 1, "operational_disruption_pct": 3},
}

# ── Circularity Metrics ──────────────────────────────────────────────────

CIRCULARITY_METRICS: dict[str, dict] = {
    "pumped_hydro": {"material_reuse_pct": 85, "recyclability_pct": 90, "co2_vs_greenfield_saving_pct": 45, "critical_minerals": []},
    "compressed_air": {"material_reuse_pct": 70, "recyclability_pct": 85, "co2_vs_greenfield_saving_pct": 40, "critical_minerals": []},
    "gravity_storage": {"material_reuse_pct": 90, "recyclability_pct": 95, "co2_vs_greenfield_saving_pct": 50, "critical_minerals": []},
    "li_ion_bess": {"material_reuse_pct": 30, "recyclability_pct": 70, "co2_vs_greenfield_saving_pct": 25, "critical_minerals": ["lithium", "cobalt", "nickel", "manganese"]},
    "flow_battery": {"material_reuse_pct": 40, "recyclability_pct": 80, "co2_vs_greenfield_saving_pct": 30, "critical_minerals": ["vanadium"]},
    "thermal_storage": {"material_reuse_pct": 80, "recyclability_pct": 90, "co2_vs_greenfield_saving_pct": 55, "critical_minerals": []},
    "hydrogen": {"material_reuse_pct": 50, "recyclability_pct": 75, "co2_vs_greenfield_saving_pct": 35, "critical_minerals": ["platinum", "iridium"]},
    "flywheel": {"material_reuse_pct": 60, "recyclability_pct": 95, "co2_vs_greenfield_saving_pct": 20, "critical_minerals": []},
}

# ── EU Regulatory Context ────────────────────────────────────────────────

EU_REGULATORY_CONTEXT: dict[str, Any] = {
    "bridge_initiative": {
        "ref": "BRIDGE – Cooperation of Horizon Europe Smart Grid and Energy Storage Projects",
        "kpis": [
            "System flexibility increase (%)",
            "Renewable curtailment reduction (%)",
            "Consumer engagement metrics",
            "Cross-border balancing contribution (MW)",
        ],
    },
    "eu_taxonomy_4_10": {
        "ref": "EU Taxonomy Delegated Act – Activity 4.10: Storage of electricity",
        "criteria": [
            "Life-cycle GHG emissions below 100g CO2e/kWh",
            "Compliance with EU Battery Regulation 2023/1542",
            "Do No Significant Harm (DNSH) assessment",
        ],
    },
    "battery_regulation_2023": {
        "ref": "Regulation (EU) 2023/1542 on batteries and waste batteries",
        "requirements": [
            "Carbon footprint declaration (from Feb 2025)",
            "Minimum recycled content (Co 16%, Li 6%, Ni 6% from 2031)",
            "Collection and recycling targets (70% by 2030)",
            "Battery passport with QR code (from Feb 2027)",
            "Due diligence for raw material sourcing",
        ],
    },
    "nis2_directive": {
        "ref": "Directive (EU) 2022/2555 – NIS2 (Network and Information Security)",
        "requirements": [
            "Energy sector classified as essential entity",
            "Risk management and incident reporting",
            "Supply chain security assessment",
            "Business continuity and crisis management",
            "Encryption and access control policies",
        ],
    },
}


# ── Analysis Functions ───────────────────────────────────────────────────

def match_storage_technologies(
    infrastructure_type: str,
    capacity_mw: float = 50,
    duration_hours: float = 4,
    grid_connection_kv: float = 132,
    site_area_m2: float = 50000,
    structural_condition_score: float = 70,
) -> list[dict]:
    """
    Return ranked list of compatible storage technologies for a given
    infrastructure type, with scores, rationale, and CAPEX estimates.
    """
    compat = INFRASTRUCTURE_STORAGE_COMPATIBILITY.get(infrastructure_type, {})
    if not compat:
        return []

    results = []
    for tech_key, match in compat.items():
        tech = STORAGE_TECHNOLOGIES.get(tech_key)
        if not tech:
            continue

        # Base compatibility score
        base_score = match["score"]

        # Adjust for capacity fit
        pmin, pmax = tech["power_range_mw"]
        if capacity_mw < pmin or capacity_mw > pmax:
            base_score -= 20
        elif capacity_mw > pmax * 0.8:
            base_score -= 5

        # Adjust for duration fit
        dmin, dmax = tech["duration_hours"]
        if duration_hours < dmin or duration_hours > dmax:
            base_score -= 15

        # Adjust for structural condition
        if structural_condition_score < 40:
            base_score -= 15
        elif structural_condition_score < 60:
            base_score -= 5

        base_score = max(0, min(100, base_score))

        # CAPEX estimate
        energy_mwh = capacity_mw * duration_hours
        capex_power = tech["capex_gbp_per_kw"] * capacity_mw * 1000
        capex_energy = tech["capex_gbp_per_kwh"] * energy_mwh * 1000
        capex_total = max(capex_power, capex_energy)

        # Check for retrofit benchmark
        benchmark = RETROFIT_COST_BENCHMARKS.get((infrastructure_type, tech_key))
        if benchmark:
            retrofit_capex = benchmark["retrofit_gbp_per_kw"] * capacity_mw * 1000
            greenfield_capex = benchmark["greenfield_gbp_per_kw"] * capacity_mw * 1000
            saving_pct = benchmark["saving_pct"]
        else:
            retrofit_capex = capex_total * 0.7
            greenfield_capex = capex_total
            saving_pct = 30

        results.append({
            "storage_technology": tech_key,
            "compatibility_score": base_score,
            "rationale": match["rationale"],
            "trl": tech["trl"],
            "round_trip_efficiency_pct": tech["round_trip_efficiency_pct"],
            "design_life_years": tech["design_life_years"],
            "response_time_seconds": tech["response_time_seconds"],
            "grid_services": tech["grid_services"],
            "capex_estimate": {
                "retrofit_gbp": round(retrofit_capex),
                "greenfield_gbp": round(greenfield_capex),
                "saving_pct": saving_pct,
                "gbp_per_kw": round(retrofit_capex / (capacity_mw * 1000), 1) if capacity_mw > 0 else 0,
                "gbp_per_kwh": round(retrofit_capex / (energy_mwh * 1000), 1) if energy_mwh > 0 else 0,
            },
        })

    results.sort(key=lambda r: r["compatibility_score"], reverse=True)
    return results


def assess_retrofit_feasibility(
    infrastructure_type: str,
    storage_technology: str,
    capacity_mw: float = 50,
    duration_hours: float = 4,
    structural_condition_score: float = 70,
    grid_connection_kv: float = 132,
    grid_headroom_mw: float = 30,
    distance_to_grid_km: float = 1.0,
    environmental_overlays: list[str] | None = None,
    site_area_m2: float = 50000,
    existing_remediation: bool = False,
    lat: float = 52.5,
    lon: float = -1.5,
) -> dict[str, Any]:
    """
    Comprehensive retrofit feasibility assessment with composite 0-100 score.

    Returns 6-component breakdown, verdict, cost estimates, grid flexibility,
    circularity detail, socioeconomic impact, security assessment, BRIDGE
    compatibility, and recommendations.
    """
    environmental_overlays = environmental_overlays or []
    infra = INFRASTRUCTURE_TYPES.get(infrastructure_type)
    tech = STORAGE_TECHNOLOGIES.get(storage_technology)
    if not infra or not tech:
        return {"error": "Unknown infrastructure_type or storage_technology"}

    # Component scores
    struct_score, struct_issues = _score_structural_integrity(
        infrastructure_type, structural_condition_score, storage_technology, site_area_m2
    )
    cap_score, cap_issues = _score_storage_capacity(
        storage_technology, capacity_mw, duration_hours, site_area_m2
    )
    grid_score, grid_issues = _score_grid_connection(
        grid_connection_kv, grid_headroom_mw, distance_to_grid_km,
        capacity_mw, storage_technology
    )
    env_score, env_issues = _score_environmental(
        environmental_overlays, existing_remediation, infrastructure_type
    )
    disrupt_score, disrupt_issues = _score_disruption(
        storage_technology, capacity_mw, infrastructure_type
    )
    circ_score, circ_issues = _score_circularity_component(
        storage_technology, infrastructure_type
    )

    total = struct_score + cap_score + grid_score + env_score + disrupt_score + circ_score
    all_issues = struct_issues + cap_issues + grid_issues + env_issues + disrupt_issues + circ_issues

    if total >= 70:
        verdict = "GO"
    elif total >= 45:
        verdict = "CAUTION"
    else:
        verdict = "NO-GO"

    # Cost estimate
    energy_mwh = capacity_mw * duration_hours
    benchmark = RETROFIT_COST_BENCHMARKS.get((infrastructure_type, storage_technology))
    if benchmark:
        retrofit_cost = benchmark["retrofit_gbp_per_kw"] * capacity_mw * 1000
        greenfield_cost = benchmark["greenfield_gbp_per_kw"] * capacity_mw * 1000
        saving_pct = benchmark["saving_pct"]
    else:
        greenfield_cost = tech["capex_gbp_per_kw"] * capacity_mw * 1000
        retrofit_cost = greenfield_cost * 0.7
        saving_pct = 30

    cost_estimate = {
        "retrofit_total_gbp": round(retrofit_cost),
        "greenfield_total_gbp": round(greenfield_cost),
        "saving_gbp": round(greenfield_cost - retrofit_cost),
        "saving_pct": saving_pct,
        "gbp_per_kw": round(retrofit_cost / (capacity_mw * 1000), 1) if capacity_mw > 0 else 0,
        "gbp_per_kwh": round(retrofit_cost / (energy_mwh * 1000), 1) if energy_mwh > 0 else 0,
    }

    # Sub-assessments
    grid_flex = assess_grid_flexibility(storage_technology, capacity_mw, duration_hours)
    circularity = assess_circularity(infrastructure_type, storage_technology, capacity_mw)
    socioeconomic = assess_socioeconomic_impact(infrastructure_type, storage_technology, capacity_mw)
    security = assess_security(storage_technology, capacity_mw)

    # BRIDGE compatibility
    bridge = {
        "compatible": True,
        "kpis_addressed": EU_REGULATORY_CONTEXT["bridge_initiative"]["kpis"],
        "flexibility_contribution_mw": round(capacity_mw * tech["round_trip_efficiency_pct"] / 100, 1),
    }

    # Recommendations
    recommendations = _generate_recommendations(
        verdict, all_issues, infrastructure_type, storage_technology,
        capacity_mw, structural_condition_score
    )

    return {
        "infrastructure_type": infrastructure_type,
        "storage_technology": storage_technology,
        "capacity_mw": capacity_mw,
        "duration_hours": duration_hours,
        "total_score": round(total, 1),
        "verdict": verdict,
        "scores": {
            "structural_integrity": {"score": struct_score, "max": 20, "issues": struct_issues},
            "storage_capacity": {"score": cap_score, "max": 20, "issues": cap_issues},
            "grid_connection": {"score": grid_score, "max": 20, "issues": grid_issues},
            "environmental_impact": {"score": env_score, "max": 15, "issues": env_issues},
            "disruption_level": {"score": disrupt_score, "max": 10, "issues": disrupt_issues},
            "circularity": {"score": circ_score, "max": 15, "issues": circ_issues},
        },
        "cost_estimate": cost_estimate,
        "grid_flexibility": grid_flex,
        "circularity_detail": circularity,
        "socioeconomic": socioeconomic,
        "security": security,
        "bridge_compatibility": bridge,
        "recommendations": recommendations,
        "location": {"lat": lat, "lon": lon},
    }


def _score_structural_integrity(
    infra_type: str, condition: float, storage_tech: str, area_m2: float,
) -> tuple[float, list[str]]:
    """Score structural integrity (0-20)."""
    score = 20.0
    issues = []
    infra = INFRASTRUCTURE_TYPES.get(infra_type, {})

    # Condition penalty
    if condition < 30:
        score -= 12
        issues.append(f"Poor structural condition ({condition}/100) — major remediation needed")
    elif condition < 50:
        score -= 7
        issues.append(f"Below-average condition ({condition}/100) — reinforcement required")
    elif condition < 70:
        score -= 3
        issues.append(f"Moderate condition ({condition}/100) — some repair needed")

    # Repurpose potential bonus
    rp = infra.get("repurpose_potential", 50)
    if rp >= 85:
        score += 2
    elif rp < 60:
        score -= 3
        issues.append("Low repurpose potential for this infrastructure type")

    # Area check — heavy tech needs more space
    heavy_tech = {"pumped_hydro", "compressed_air", "hydrogen", "thermal_storage"}
    if storage_tech in heavy_tech and area_m2 < 20000:
        score -= 4
        issues.append("Site area may be insufficient for selected technology")

    return max(0, min(20, round(score, 1))), issues


def _score_storage_capacity(
    storage_tech: str, capacity_mw: float, duration_hours: float, area_m2: float,
) -> tuple[float, list[str]]:
    """Score storage capacity fit (0-20)."""
    tech = STORAGE_TECHNOLOGIES.get(storage_tech, {})
    score = 20.0
    issues = []

    pmin, pmax = tech.get("power_range_mw", (1, 100))
    dmin, dmax = tech.get("duration_hours", (1, 8))

    if capacity_mw < pmin:
        score -= 10
        issues.append(f"Capacity {capacity_mw} MW below technology minimum ({pmin} MW)")
    elif capacity_mw > pmax:
        score -= 12
        issues.append(f"Capacity {capacity_mw} MW exceeds technology maximum ({pmax} MW)")

    if duration_hours < dmin:
        score -= 6
        issues.append(f"Duration {duration_hours}h below technology minimum ({dmin}h)")
    elif duration_hours > dmax:
        score -= 8
        issues.append(f"Duration {duration_hours}h exceeds technology maximum ({dmax}h)")

    # Efficiency penalty for low-efficiency tech at large scale
    eff = tech.get("round_trip_efficiency_pct", 80)
    if eff < 50 and capacity_mw > 100:
        score -= 3
        issues.append(f"Low round-trip efficiency ({eff}%) at large scale increases losses")

    return max(0, min(20, round(score, 1))), issues


def _score_grid_connection(
    kv: float, headroom_mw: float, distance_km: float,
    capacity_mw: float, storage_tech: str,
) -> tuple[float, list[str]]:
    """Score grid connection suitability (0-20)."""
    score = 20.0
    issues = []

    # Voltage level vs capacity
    if capacity_mw > 100 and kv < 132:
        score -= 8
        issues.append(f"Grid voltage ({kv} kV) may be insufficient for {capacity_mw} MW")
    elif capacity_mw > 50 and kv < 33:
        score -= 10
        issues.append(f"Grid voltage ({kv} kV) too low — reinforcement needed")
    elif capacity_mw > 10 and kv < 11:
        score -= 12
        issues.append(f"Grid voltage ({kv} kV) inadequate for {capacity_mw} MW")

    # Headroom
    if headroom_mw < capacity_mw * 0.5:
        score -= 8
        issues.append(f"Grid headroom ({headroom_mw} MW) below 50% of capacity — reinforcement likely")
    elif headroom_mw < capacity_mw:
        score -= 4
        issues.append(f"Grid headroom ({headroom_mw} MW) below capacity — constraint management needed")

    # Distance penalty
    if distance_km > 10:
        score -= 8
        issues.append(f"Grid distance ({distance_km} km) — significant new cable route required")
    elif distance_km > 5:
        score -= 4
        issues.append(f"Grid distance ({distance_km} km) — moderate cable extension needed")
    elif distance_km > 2:
        score -= 2

    return max(0, min(20, round(score, 1))), issues


def _score_environmental(
    overlays: list[str], existing_remediation: bool, infra_type: str,
) -> tuple[float, list[str]]:
    """Score environmental impact (0-15)."""
    score = 15.0
    issues = []
    overlay_set = {o.lower() for o in overlays}

    if any("natura2000" in o or "sac" in o or "spa" in o for o in overlay_set):
        score -= 8
        issues.append("Natura 2000 / SAC / SPA designation — Habitats Directive applies")
    if any("sssi" in o for o in overlay_set):
        score -= 5
        issues.append("SSSI designation — statutory consultation required")
    if any("flood" in o for o in overlay_set):
        score -= 3
        issues.append("Flood zone — sequential test and flood risk assessment needed")
    if any("aonb" in o or "national_park" in o for o in overlay_set):
        score -= 4
        issues.append("AONB / National Park — heightened landscape sensitivity")

    # Brownfield bonus
    brownfield_types = {"coal_power_plant", "gas_power_plant", "industrial_facility",
                        "coal_mine", "oil_gas_infrastructure", "military_base"}
    if infra_type in brownfield_types:
        score += 3
        if not existing_remediation:
            issues.append("Brownfield site — contamination assessment recommended before works")

    return max(0, min(15, round(score, 1))), issues


def _score_disruption(
    storage_tech: str, capacity_mw: float, infra_type: str,
) -> tuple[float, list[str]]:
    """Score disruption level (0-10, higher = less disruption)."""
    profile = DISRUPTION_PROFILES.get(storage_tech, {"months_base": 12, "months_per_100mw": 3, "operational_disruption_pct": 10})
    issues = []

    total_months = profile["months_base"] + profile["months_per_100mw"] * capacity_mw / 100
    disruption_pct = profile["operational_disruption_pct"]

    # Score inversely to disruption
    score = 10.0
    if total_months > 36:
        score -= 5
        issues.append(f"Estimated {round(total_months)} month construction — significant disruption")
    elif total_months > 18:
        score -= 3
        issues.append(f"Estimated {round(total_months)} month construction — moderate disruption")
    elif total_months > 12:
        score -= 1

    if disruption_pct > 15:
        score -= 3
        issues.append(f"Operational disruption ~{disruption_pct}% during construction")
    elif disruption_pct > 8:
        score -= 1

    return max(0, min(10, round(score, 1))), issues


def _score_circularity_component(
    storage_tech: str, infra_type: str,
) -> tuple[float, list[str]]:
    """Score circularity (0-15)."""
    circ = CIRCULARITY_METRICS.get(storage_tech, {})
    issues = []
    score = 15.0

    reuse = circ.get("material_reuse_pct", 50)
    recyclability = circ.get("recyclability_pct", 70)
    minerals = circ.get("critical_minerals", [])

    if reuse < 40:
        score -= 4
        issues.append(f"Low material reuse ({reuse}%) — limited circular economy benefit")
    elif reuse < 60:
        score -= 2

    if recyclability < 70:
        score -= 3
        issues.append(f"Below-target recyclability ({recyclability}%) vs EU Battery Regulation")

    if minerals:
        score -= 2
        issues.append(f"Critical mineral dependency: {', '.join(minerals)}")

    # Bonus for infra reuse
    infra = INFRASTRUCTURE_TYPES.get(infra_type, {})
    if infra.get("repurpose_potential", 50) >= 80:
        score += 2

    return max(0, min(15, round(score, 1))), issues


def assess_grid_flexibility(
    storage_tech: str,
    capacity_mw: float = 50,
    duration_hours: float = 4,
) -> dict[str, Any]:
    """
    Assess grid flexibility contribution: dispatch profiles,
    frequency response, capacity firming, arbitrage revenue.
    """
    tech = STORAGE_TECHNOLOGIES.get(storage_tech, {})
    eff = tech.get("round_trip_efficiency_pct", 80) / 100
    energy_mwh = capacity_mw * duration_hours
    response_s = tech.get("response_time_seconds", 60)
    services = tech.get("grid_services", [])

    # Frequency response
    freq_response = None
    if "frequency_response" in services:
        if response_s < 1:
            freq_class = "Dynamic Containment (DC)"
            freq_revenue_gbp_mw_yr = 45000
        elif response_s < 10:
            freq_class = "Dynamic Moderation (DM)"
            freq_revenue_gbp_mw_yr = 30000
        else:
            freq_class = "Dynamic Regulation (DR)"
            freq_revenue_gbp_mw_yr = 18000
        freq_response = {
            "class": freq_class,
            "response_time_s": response_s,
            "eligible_capacity_mw": capacity_mw,
            "estimated_revenue_gbp_yr": round(freq_revenue_gbp_mw_yr * capacity_mw),
        }

    # Capacity firming
    capacity_firming = None
    if "capacity_firming" in services:
        cm_rate = 28000  # GBP/MW/year (UK Capacity Market approximate)
        capacity_firming = {
            "eligible_capacity_mw": round(capacity_mw * eff, 1),
            "capacity_market_revenue_gbp_yr": round(cm_rate * capacity_mw * eff),
        }

    # Arbitrage
    arbitrage = None
    if "arbitrage" in services:
        cycles_per_year = min(365, 300 if duration_hours <= 4 else 200)
        spread_gbp_mwh = 40  # approximate UK wholesale spread
        arb_revenue = cycles_per_year * energy_mwh * spread_gbp_mwh * eff
        arbitrage = {
            "cycles_per_year": cycles_per_year,
            "spread_gbp_per_mwh": spread_gbp_mwh,
            "estimated_revenue_gbp_yr": round(arb_revenue),
        }

    # Dispatch profiles
    dispatch = {
        "daily_cycles": 2 if duration_hours <= 4 else 1,
        "charge_hours": f"00:00-{int(duration_hours):02d}:00 / 13:00-{13+int(duration_hours):02d}:00" if duration_hours <= 4 else f"00:00-{int(duration_hours):02d}:00",
        "discharge_hours": "07:00-09:00 / 16:00-19:00" if duration_hours <= 4 else "16:00-22:00",
        "availability_pct": 95 if tech.get("trl", 5) >= 8 else 90,
    }

    # Total estimated revenue
    total_revenue = 0
    if freq_response:
        total_revenue += freq_response["estimated_revenue_gbp_yr"]
    if capacity_firming:
        total_revenue += capacity_firming["capacity_market_revenue_gbp_yr"]
    if arbitrage:
        total_revenue += arbitrage["estimated_revenue_gbp_yr"]

    flexibility_score = min(100, round(
        (30 if freq_response else 0)
        + (25 if capacity_firming else 0)
        + (25 if arbitrage else 0)
        + (10 if "black_start" in services else 0)
        + (10 if "voltage_support" in services else 0)
    ))

    return {
        "storage_technology": storage_tech,
        "capacity_mw": capacity_mw,
        "energy_mwh": energy_mwh,
        "round_trip_efficiency_pct": tech.get("round_trip_efficiency_pct", 80),
        "flexibility_score": flexibility_score,
        "dispatch_profile": dispatch,
        "frequency_response": freq_response,
        "capacity_firming": capacity_firming,
        "arbitrage": arbitrage,
        "grid_services": services,
        "total_estimated_revenue_gbp_yr": round(total_revenue),
    }


def assess_circularity(
    infra_type: str,
    storage_tech: str,
    capacity_mw: float = 50,
) -> dict[str, Any]:
    """
    Assess circularity: material reuse, recyclability, CO2 savings,
    EU Battery Regulation compliance.
    """
    circ = CIRCULARITY_METRICS.get(storage_tech, {})
    tech = STORAGE_TECHNOLOGIES.get(storage_tech, {})
    infra = INFRASTRUCTURE_TYPES.get(infra_type, {})

    material_reuse = circ.get("material_reuse_pct", 50)
    recyclability = circ.get("recyclability_pct", 70)
    co2_saving = circ.get("co2_vs_greenfield_saving_pct", 30)
    minerals = circ.get("critical_minerals", [])

    # CO2 lifecycle
    co2_per_mwh = tech.get("co2_lifecycle_kg_per_mwh", 20)
    energy_mwh = capacity_mw * 4  # assume 4h for annual calc basis
    annual_cycles = 300
    annual_co2_t = co2_per_mwh * energy_mwh * annual_cycles / 1000

    # EU Battery Regulation compliance
    battery_reg_applies = storage_tech in ("li_ion_bess", "flow_battery")
    battery_reg = {
        "applies": battery_reg_applies,
        "carbon_footprint_declaration": battery_reg_applies,
        "recycled_content_targets": battery_reg_applies,
        "battery_passport_required": battery_reg_applies,
        "collection_target_met": recyclability >= 70,
    } if battery_reg_applies else {"applies": False}

    # EU Taxonomy 4.10
    taxonomy_aligned = co2_per_mwh < 100

    # Infrastructure reuse detail
    structural_elements = infra.get("structural_elements", [])
    reusable_elements = structural_elements[:max(1, int(len(structural_elements) * material_reuse / 100))]

    circularity_score = min(100, round(
        material_reuse * 0.3
        + recyclability * 0.3
        + co2_saving * 0.2
        + (20 if not minerals else 10)
    ))

    return {
        "circularity_score": circularity_score,
        "material_reuse_pct": material_reuse,
        "recyclability_pct": recyclability,
        "co2_vs_greenfield_saving_pct": co2_saving,
        "co2_lifecycle_kg_per_mwh": co2_per_mwh,
        "annual_co2_t": round(annual_co2_t, 1),
        "critical_minerals": minerals,
        "reusable_structural_elements": reusable_elements,
        "eu_battery_regulation": battery_reg,
        "eu_taxonomy_4_10_aligned": taxonomy_aligned,
        "infrastructure_repurpose_potential": infra.get("repurpose_potential", 50),
    }


def generate_disruption_plan(
    infra_type: str,
    storage_tech: str,
    capacity_mw: float = 50,
    phased: bool = True,
) -> dict[str, Any]:
    """
    Generate a 6-phase retrofit timeline with activities,
    durations, impacts, and mitigation measures.
    """
    profile = DISRUPTION_PROFILES.get(storage_tech, {"months_base": 12, "months_per_100mw": 3, "operational_disruption_pct": 10})
    total_months = profile["months_base"] + profile["months_per_100mw"] * capacity_mw / 100

    # Phase distribution (pct of total duration)
    phase_pcts = [0.08, 0.12, 0.25, 0.30, 0.15, 0.10]
    phase_names = [
        "Site Assessment & Planning",
        "Remediation & Preparation",
        "Civil Engineering Works",
        "Equipment Installation",
        "Commissioning & Testing",
        "Validation & Handover",
    ]
    phase_activities = [
        ["Structural survey", "Environmental baseline", "Grid studies", "Planning applications", "Stakeholder consultation"],
        ["Contamination remediation", "Asbestos removal", "Foundation preparation", "Utility diversions", "Access improvements"],
        ["Foundation construction", "Cable trenching", "Transformer pad", "Control building", "Drainage and earthworks"],
        ["Storage system delivery", "Electrical installation", "SCADA integration", "Protection systems", "Fire suppression"],
        ["Energisation testing", "Grid compliance (G99)", "Performance verification", "BESS cycling tests", "Safety certification"],
        ["Performance acceptance", "Training and handover", "Documentation", "BRIDGE KPI baseline", "Operational readiness"],
    ]
    phase_impacts = [
        "Minimal — survey and desk-based activities",
        "Moderate — heavy plant, noise, dust, traffic",
        "High — major construction, heavy vehicles, noise",
        "Moderate — specialist plant, oversized loads",
        "Low — controlled testing, intermittent grid interaction",
        "Minimal — administrative and documentation",
    ]

    phases = []
    cumulative_months = 0
    for i, name in enumerate(phase_names):
        dur = max(1, round(total_months * phase_pcts[i]))
        phases.append({
            "phase": i + 1,
            "name": name,
            "duration_months": dur,
            "start_month": round(cumulative_months),
            "activities": phase_activities[i],
            "impact": phase_impacts[i],
        })
        cumulative_months += dur

    # Mitigation measures
    mitigations = [
        "Phased construction to maintain partial site operation",
        "Construction traffic management plan (CTMP)",
        "Noise and dust monitoring with trigger levels",
        "Ecological watching brief during ground works",
        "Community liaison officer and regular updates",
        "Emergency response plan throughout construction",
    ]
    if capacity_mw > 50:
        mitigations.append("Grid outage coordination with DNO/ESO")
    if infra_type in ("coal_mine", "oil_gas_infrastructure"):
        mitigations.append("Contaminated land management protocol (CLR11)")

    # Disruption score (0-100, lower = less disruption)
    disruption_score = min(100, round(
        profile["operational_disruption_pct"] * 2
        + total_months * 1.5
        + (10 if capacity_mw > 100 else 0)
    ))

    return {
        "infrastructure_type": infra_type,
        "storage_technology": storage_tech,
        "capacity_mw": capacity_mw,
        "phased": phased,
        "total_duration_months": round(total_months),
        "phases": phases,
        "mitigation_measures": mitigations,
        "disruption_score": disruption_score,
        "operational_disruption_pct": profile["operational_disruption_pct"],
    }


def assess_socioeconomic_impact(
    infra_type: str,
    storage_tech: str,
    capacity_mw: float = 50,
    region: str = "midlands",
) -> dict[str, Any]:
    """
    Assess socioeconomic impact: jobs, community benefit,
    brownfield remediation, just transition alignment.
    """
    # Construction jobs (per MW, varies by tech)
    construction_jobs_per_mw = {
        "pumped_hydro": 8, "compressed_air": 5, "gravity_storage": 6,
        "li_ion_bess": 3, "flow_battery": 4, "thermal_storage": 5,
        "hydrogen": 6, "flywheel": 2,
    }
    permanent_jobs_per_mw = {
        "pumped_hydro": 1.5, "compressed_air": 0.8, "gravity_storage": 0.5,
        "li_ion_bess": 0.3, "flow_battery": 0.4, "thermal_storage": 0.6,
        "hydrogen": 1.0, "flywheel": 0.2,
    }

    construction = round(construction_jobs_per_mw.get(storage_tech, 4) * capacity_mw)
    permanent = round(permanent_jobs_per_mw.get(storage_tech, 0.5) * capacity_mw)

    # Community benefit fund (typical £1000-2000/MW/year)
    cbf_per_mw = 1500
    annual_cbf = round(cbf_per_mw * capacity_mw)

    # Brownfield remediation value
    brownfield_types = {"coal_power_plant", "gas_power_plant", "industrial_facility",
                        "coal_mine", "oil_gas_infrastructure"}
    is_brownfield = infra_type in brownfield_types
    remediation_value = round(capacity_mw * 15000) if is_brownfield else 0

    # Just Transition alignment
    fossil_fuel_types = {"coal_power_plant", "gas_power_plant", "coal_mine", "oil_gas_infrastructure"}
    just_transition = infra_type in fossil_fuel_types

    return {
        "construction_jobs": construction,
        "permanent_jobs": permanent,
        "community_benefit_fund_gbp_yr": annual_cbf,
        "brownfield_remediation": is_brownfield,
        "remediation_value_gbp": remediation_value,
        "just_transition_aligned": just_transition,
        "skills_transfer": [
            "Heavy engineering → storage construction",
            "Electrical systems → grid integration",
            "Process control → SCADA operation",
            "Safety management → operational compliance",
        ] if just_transition else [],
        "region": region,
    }


def assess_security(
    storage_tech: str,
    capacity_mw: float = 50,
) -> dict[str, Any]:
    """
    Assess security posture: NIS2 compliance, physical security,
    cyber security, supply chain security.
    """
    # NIS2 threshold — energy storage >10MW is essential entity
    is_essential = capacity_mw >= 10

    nis2 = {
        "essential_entity": is_essential,
        "risk_management_required": is_essential,
        "incident_reporting_required": is_essential,
        "supply_chain_assessment_required": is_essential,
    }

    # Physical security
    physical = {
        "perimeter_security": "Required — CCTV, intruder detection, fencing",
        "access_control": "Biometric or card access for critical areas",
        "fire_suppression": "Required" if storage_tech in ("li_ion_bess", "flow_battery") else "Standard",
        "flood_protection": "Site-specific assessment required",
    }

    # Cyber security
    cyber = {
        "scada_security": "IEC 62351 encryption and authentication",
        "network_segmentation": "OT/IT separation with DMZ",
        "patch_management": "Critical systems on 30-day patch cycle",
        "audit_logging": "All access and control actions logged (12-month retention)",
        "penetration_testing": "Annual third-party testing required" if is_essential else "Recommended",
    }

    # Supply chain
    tech_data = STORAGE_TECHNOLOGIES.get(storage_tech, {})
    minerals = CIRCULARITY_METRICS.get(storage_tech, {}).get("critical_minerals", [])
    supply_chain = {
        "critical_mineral_dependency": minerals,
        "single_source_risk": len(minerals) > 2,
        "eu_sourcing_preference": True,
        "due_diligence_required": len(minerals) > 0,
    }

    security_score = min(100, round(
        (30 if is_essential else 20)
        + 25  # physical baseline
        + 25  # cyber baseline
        + (20 if not minerals else 10)
    ))

    return {
        "security_score": security_score,
        "nis2_compliance": nis2,
        "physical_security": physical,
        "cyber_security": cyber,
        "supply_chain": supply_chain,
    }


def _generate_recommendations(
    verdict: str,
    issues: list[str],
    infra_type: str,
    storage_tech: str,
    capacity_mw: float,
    condition: float,
) -> list[str]:
    """Generate actionable recommendations based on assessment results."""
    recs = []

    if verdict == "NO-GO":
        recs.append("Consider alternative infrastructure sites or storage technologies")
        if condition < 40:
            recs.append("Structural remediation required before any retrofit — commission detailed survey")
    elif verdict == "CAUTION":
        recs.append("Proceed with detailed engineering study to address identified issues")

    if condition < 60:
        recs.append(f"Commission structural assessment of {infra_type.replace('_', ' ')}")

    infra = INFRASTRUCTURE_TYPES.get(infra_type, {})
    if infra.get("eu_priority"):
        recs.append("Site eligible for EU HORIZON-CL5-2027 priority funding consideration")

    tech = STORAGE_TECHNOLOGIES.get(storage_tech, {})
    if tech.get("trl", 9) < 8:
        recs.append(f"Technology TRL {tech.get('trl')} — pilot demonstration recommended before full-scale")

    if capacity_mw > 10:
        recs.append("NIS2 essential entity — initiate security compliance programme")

    recs.append("Engage with local community on brownfield regeneration benefits")
    recs.append("Register with BRIDGE initiative for knowledge sharing and KPI reporting")

    return recs


# ── DB Helpers ───────────────────────────────────────────────────────────

async def setup_retrofit_table(conn) -> None:
    """Create the retrofit_assessments table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS retrofit_assessments (
            assessment_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            parcel_id           UUID,
            infrastructure_type TEXT NOT NULL,
            storage_technology  TEXT NOT NULL,
            capacity_mw         DOUBLE PRECISION DEFAULT 50,
            duration_hours      DOUBLE PRECISION DEFAULT 4,
            total_score         DOUBLE PRECISION,
            verdict             TEXT,
            scores              JSONB DEFAULT '{}',
            cost_estimate       JSONB DEFAULT '{}',
            disruption_plan     JSONB DEFAULT '{}',
            circularity         JSONB DEFAULT '{}',
            grid_flexibility    JSONB DEFAULT '{}',
            metadata            JSONB DEFAULT '{}',
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            geometry            GEOMETRY(Point, 27700)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_retrofit_assessments_geom
        ON retrofit_assessments USING GIST (geometry)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_retrofit_assessments_type
        ON retrofit_assessments (infrastructure_type)
    """)


async def seed_sample_retrofit_sites(conn) -> None:
    """Seed sample UK infrastructure sites for demo purposes."""
    count = await conn.fetchval("SELECT count(*) FROM retrofit_assessments")
    if count > 0:
        return

    from datetime import date as _date

    samples = [
        # (name, infra_type, storage_tech, capacity_mw, lat, lon)
        ("Drax Power Station", "coal_power_plant", "li_ion_bess", 200, 53.7360, -0.9959),
        ("Ferrybridge C", "coal_power_plant", "thermal_storage", 100, 53.7190, -1.2680),
        ("Dinorwig Pump Storage", "hydropower_dam", "pumped_hydro", 1728, 53.1200, -4.1140),
        ("Boulby Mine", "coal_mine", "compressed_air", 50, 54.5620, -0.8200),
        ("Fawley Refinery", "oil_gas_infrastructure", "hydrogen", 100, 50.8220, -1.3280),
        ("Robin Rigg (decom)", "decommissioned_wind_farm", "li_ion_bess", 174, 54.7530, -3.7200),
        ("Mountsorrel Quarry", "quarry", "gravity_storage", 20, 52.7270, -1.1520),
    ]

    for name, itype, stech, cap, lat, lon in samples:
        result = assess_retrofit_feasibility(
            infrastructure_type=itype,
            storage_technology=stech,
            capacity_mw=cap,
            lat=lat,
            lon=lon,
        )
        import json as _json
        await conn.execute("""
            INSERT INTO retrofit_assessments
                (infrastructure_type, storage_technology, capacity_mw, duration_hours,
                 total_score, verdict, scores, cost_estimate, disruption_plan,
                 circularity, grid_flexibility, metadata, geometry)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9::jsonb,
                    $10::jsonb, $11::jsonb, $12::jsonb,
                    ST_Transform(ST_SetSRID(ST_MakePoint($13, $14), 4326), 27700))
            ON CONFLICT DO NOTHING
        """,
            itype, stech, float(cap), 4.0,
            result["total_score"], result["verdict"],
            _json.dumps(result["scores"]),
            _json.dumps(result["cost_estimate"]),
            _json.dumps(generate_disruption_plan(itype, stech, cap)),
            _json.dumps(result["circularity_detail"]),
            _json.dumps(result["grid_flexibility"]),
            _json.dumps({"name": name}),
            lon, lat,
        )
