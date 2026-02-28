"""
Home Retrofit Engine — Case-Based Reasoning for UK residential retrofit design.

Generates retrofit options (extensions, insulation, solar PV, heat pumps) for UK
housing stock using exemplar matching. Separate from infrastructure_retrofit which
handles industrial sites.

Pure Python — runs in-process (no subprocess needed).
"""

from __future__ import annotations

import json
import logging
import math
import random
import uuid
from datetime import date, datetime, timezone
from typing import Any

log = logging.getLogger("princeps.home_retrofit")

# ---------------------------------------------------------------------------
# UK House Archetypes — 12 types with baseline characteristics
# ---------------------------------------------------------------------------

UK_HOUSE_ARCHETYPES: dict[str, dict] = {
    "victorian_terrace_mid": {
        "label": "Victorian Mid-Terrace",
        "era": "1850-1914",
        "era_midpoint": 1885,
        "form": "terrace",
        "storeys": 2,
        "typical_plot_width_m": 5.0,
        "typical_plot_depth_m": 20.0,
        "typical_gfa_m2": 85,
        "wall_construction": "solid_brick_9in",
        "wall_u": 2.1,
        "roof_u": 2.3,
        "floor_u": 1.2,
        "window_u": 4.8,
        "typical_sap": 38,
        "typical_epc": "E",
        "typical_heating": "gas_boiler",
        "loft_type": "pitched",
        "pd_extension_depth_m": 3.0,
    },
    "victorian_terrace_end": {
        "label": "Victorian End-Terrace",
        "era": "1850-1914",
        "era_midpoint": 1885,
        "form": "end_terrace",
        "storeys": 2,
        "typical_plot_width_m": 6.0,
        "typical_plot_depth_m": 20.0,
        "typical_gfa_m2": 95,
        "wall_construction": "solid_brick_9in",
        "wall_u": 2.1,
        "roof_u": 2.3,
        "floor_u": 1.2,
        "window_u": 4.8,
        "typical_sap": 36,
        "typical_epc": "E",
        "typical_heating": "gas_boiler",
        "loft_type": "pitched",
        "pd_extension_depth_m": 3.0,
    },
    "edwardian_semi": {
        "label": "Edwardian Semi-Detached",
        "era": "1900-1919",
        "era_midpoint": 1910,
        "form": "semi",
        "storeys": 2,
        "typical_plot_width_m": 7.5,
        "typical_plot_depth_m": 25.0,
        "typical_gfa_m2": 110,
        "wall_construction": "solid_brick_9in",
        "wall_u": 2.0,
        "roof_u": 2.2,
        "floor_u": 1.1,
        "window_u": 4.8,
        "typical_sap": 40,
        "typical_epc": "E",
        "typical_heating": "gas_boiler",
        "loft_type": "pitched",
        "pd_extension_depth_m": 3.0,
    },
    "1930s_semi": {
        "label": "1930s Semi-Detached",
        "era": "1920-1939",
        "era_midpoint": 1932,
        "form": "semi",
        "storeys": 2,
        "typical_plot_width_m": 8.0,
        "typical_plot_depth_m": 25.0,
        "typical_gfa_m2": 100,
        "wall_construction": "cavity_unfilled",
        "wall_u": 1.6,
        "roof_u": 2.2,
        "floor_u": 1.0,
        "window_u": 4.8,
        "typical_sap": 45,
        "typical_epc": "D",
        "typical_heating": "gas_boiler",
        "loft_type": "pitched",
        "pd_extension_depth_m": 4.0,
    },
    "1930s_detached": {
        "label": "1930s Detached",
        "era": "1920-1939",
        "era_midpoint": 1932,
        "form": "detached",
        "storeys": 2,
        "typical_plot_width_m": 12.0,
        "typical_plot_depth_m": 30.0,
        "typical_gfa_m2": 140,
        "wall_construction": "cavity_unfilled",
        "wall_u": 1.6,
        "roof_u": 2.2,
        "floor_u": 1.0,
        "window_u": 4.8,
        "typical_sap": 42,
        "typical_epc": "D",
        "typical_heating": "gas_boiler",
        "loft_type": "pitched",
        "pd_extension_depth_m": 4.0,
    },
    "1950s_semi": {
        "label": "1950s Semi-Detached",
        "era": "1940-1959",
        "era_midpoint": 1953,
        "form": "semi",
        "storeys": 2,
        "typical_plot_width_m": 7.5,
        "typical_plot_depth_m": 22.0,
        "typical_gfa_m2": 90,
        "wall_construction": "cavity_unfilled",
        "wall_u": 1.5,
        "roof_u": 2.0,
        "floor_u": 1.0,
        "window_u": 4.8,
        "typical_sap": 48,
        "typical_epc": "D",
        "typical_heating": "gas_boiler",
        "loft_type": "pitched",
        "pd_extension_depth_m": 4.0,
    },
    "1960s_detached": {
        "label": "1960s Detached",
        "era": "1960-1979",
        "era_midpoint": 1968,
        "form": "detached",
        "storeys": 2,
        "typical_plot_width_m": 12.0,
        "typical_plot_depth_m": 28.0,
        "typical_gfa_m2": 130,
        "wall_construction": "cavity_unfilled",
        "wall_u": 1.4,
        "roof_u": 1.8,
        "floor_u": 0.9,
        "window_u": 4.8,
        "typical_sap": 50,
        "typical_epc": "D",
        "typical_heating": "gas_boiler",
        "loft_type": "pitched",
        "pd_extension_depth_m": 4.0,
    },
    "1970s_bungalow": {
        "label": "1970s Bungalow",
        "era": "1960-1979",
        "era_midpoint": 1973,
        "form": "bungalow",
        "storeys": 1,
        "typical_plot_width_m": 15.0,
        "typical_plot_depth_m": 25.0,
        "typical_gfa_m2": 90,
        "wall_construction": "cavity_unfilled",
        "wall_u": 1.4,
        "roof_u": 1.5,
        "floor_u": 0.9,
        "window_u": 4.8,
        "typical_sap": 52,
        "typical_epc": "D",
        "typical_heating": "gas_boiler",
        "loft_type": "pitched_low",
        "pd_extension_depth_m": 4.0,
    },
    "1980s_semi": {
        "label": "1980s Semi-Detached",
        "era": "1980-1999",
        "era_midpoint": 1988,
        "form": "semi",
        "storeys": 2,
        "typical_plot_width_m": 7.0,
        "typical_plot_depth_m": 20.0,
        "typical_gfa_m2": 85,
        "wall_construction": "cavity_partial",
        "wall_u": 0.8,
        "roof_u": 0.6,
        "floor_u": 0.7,
        "window_u": 3.1,
        "typical_sap": 58,
        "typical_epc": "D",
        "typical_heating": "gas_boiler",
        "loft_type": "pitched",
        "pd_extension_depth_m": 4.0,
    },
    "1990s_detached": {
        "label": "1990s Detached",
        "era": "1980-1999",
        "era_midpoint": 1995,
        "form": "detached",
        "storeys": 2,
        "typical_plot_width_m": 10.0,
        "typical_plot_depth_m": 22.0,
        "typical_gfa_m2": 120,
        "wall_construction": "cavity_filled",
        "wall_u": 0.5,
        "roof_u": 0.4,
        "floor_u": 0.5,
        "window_u": 2.8,
        "typical_sap": 65,
        "typical_epc": "C",
        "typical_heating": "gas_combi",
        "loft_type": "pitched",
        "pd_extension_depth_m": 4.0,
    },
    "2000s_townhouse": {
        "label": "2000s Townhouse",
        "era": "2000-2012",
        "era_midpoint": 2005,
        "form": "terrace",
        "storeys": 3,
        "typical_plot_width_m": 5.5,
        "typical_plot_depth_m": 12.0,
        "typical_gfa_m2": 95,
        "wall_construction": "cavity_filled",
        "wall_u": 0.35,
        "roof_u": 0.25,
        "floor_u": 0.25,
        "window_u": 2.0,
        "typical_sap": 72,
        "typical_epc": "C",
        "typical_heating": "gas_combi",
        "loft_type": "flat_or_room",
        "pd_extension_depth_m": 3.0,
    },
    "modern_newbuild": {
        "label": "Modern New-Build (post-2013)",
        "era": "2013+",
        "era_midpoint": 2018,
        "form": "detached",
        "storeys": 2,
        "typical_plot_width_m": 9.0,
        "typical_plot_depth_m": 18.0,
        "typical_gfa_m2": 100,
        "wall_construction": "cavity_filled",
        "wall_u": 0.18,
        "roof_u": 0.13,
        "floor_u": 0.15,
        "window_u": 1.4,
        "typical_sap": 82,
        "typical_epc": "B",
        "typical_heating": "gas_combi",
        "loft_type": "pitched",
        "pd_extension_depth_m": 4.0,
    },
}

# ---------------------------------------------------------------------------
# Retrofit Interventions — 15+ options with cost/planning data
# ---------------------------------------------------------------------------

RETROFIT_INTERVENTIONS: dict[str, dict] = {
    "rear_extension_single": {
        "label": "Single-Storey Rear Extension",
        "category": "extension",
        "typical_depth_m": 4.0,
        "max_pd_depth_m": {"semi": 4.0, "detached": 8.0, "end_terrace": 4.0, "terrace": 3.0, "bungalow": 4.0},
        "max_height_m": 4.0,
        "planning_route": "permitted_development",
        "pd_conditions": "Must not exceed 50% of garden area. Max eaves 3m, max height 4m. Not forward of principal elevation.",
        "gfa_gain_factor": 1.0,  # depth_m * width_m
    },
    "rear_extension_double": {
        "label": "Two-Storey Rear Extension",
        "category": "extension",
        "typical_depth_m": 3.0,
        "max_pd_depth_m": {"semi": 3.0, "detached": 3.0, "end_terrace": 3.0, "terrace": 3.0, "bungalow": 0},
        "max_height_m": 7.0,
        "planning_route": "permitted_development",
        "pd_conditions": "Max depth 3m from original rear wall. Must be 7m from rear boundary. Matching materials.",
        "gfa_gain_factor": 2.0,  # 2 storeys
    },
    "side_extension": {
        "label": "Side Extension",
        "category": "extension",
        "typical_depth_m": 3.0,
        "max_pd_depth_m": {},
        "max_height_m": 4.0,
        "planning_route": "full_planning",
        "pd_conditions": "Usually requires planning permission. Must be subordinate to main dwelling.",
        "gfa_gain_factor": 1.0,
    },
    "loft_dormer": {
        "label": "Loft Dormer Conversion",
        "category": "extension",
        "planning_route": "permitted_development",
        "pd_conditions": "Max 40m³ additional volume (terrace) or 50m³ (other). Not higher than existing ridge. Dormer not to front.",
        "gfa_gain_m2": 25,
    },
    "loft_velux": {
        "label": "Loft Velux Conversion",
        "category": "extension",
        "planning_route": "permitted_development",
        "pd_conditions": "Rooflights only, no dormer. Minimal volume addition.",
        "gfa_gain_m2": 20,
    },
    "ewi": {
        "label": "External Wall Insulation (EWI)",
        "category": "insulation",
        "new_u_value": 0.22,
        "thickness_mm": 100,
        "planning_route": "permitted_development",
        "pd_conditions": "Generally PD unless listed building, conservation area, or alters front elevation significantly.",
        "applicable_walls": ["solid_brick_9in", "solid_brick_13in", "cavity_unfilled"],
    },
    "iwi": {
        "label": "Internal Wall Insulation (IWI)",
        "category": "insulation",
        "new_u_value": 0.30,
        "thickness_mm": 60,
        "planning_route": "none_required",
        "pd_conditions": "Internal works — no planning permission required. Building regs approval needed.",
        "applicable_walls": ["solid_brick_9in", "solid_brick_13in", "cavity_unfilled"],
    },
    "cavity_wall": {
        "label": "Cavity Wall Insulation",
        "category": "insulation",
        "new_u_value": 0.40,
        "thickness_mm": 0,
        "planning_route": "none_required",
        "pd_conditions": "No planning permission required. Quick install (1-2 days).",
        "applicable_walls": ["cavity_unfilled"],
    },
    "loft_insulation": {
        "label": "Loft Insulation (270mm)",
        "category": "insulation",
        "new_u_value": 0.16,
        "planning_route": "none_required",
    },
    "floor_insulation": {
        "label": "Floor Insulation",
        "category": "insulation",
        "new_u_value": 0.25,
        "planning_route": "none_required",
    },
    "solar_pv": {
        "label": "Solar PV (Roof-Mounted)",
        "category": "energy",
        "typical_kw_per_m2": 0.18,
        "planning_route": "permitted_development",
        "pd_conditions": "PD if: not higher than roof slope, not protrude >200mm, not on listed/conservation front elevation.",
    },
    "ashp": {
        "label": "Air Source Heat Pump (ASHP)",
        "category": "energy",
        "typical_cop": 3.2,
        "noise_db": 42,
        "planning_route": "permitted_development",
        "pd_conditions": "PD if: 1 per property, MCS certified, 42dB limit at 1m from neighbour. Not in conservation area front.",
    },
    "gshp": {
        "label": "Ground Source Heat Pump (GSHP)",
        "category": "energy",
        "typical_cop": 4.0,
        "min_garden_m2": 100,
        "planning_route": "permitted_development",
        "pd_conditions": "PD for boreholes. Open-loop may need EA permit.",
    },
    "triple_glazing": {
        "label": "Triple Glazing",
        "category": "insulation",
        "new_u_value": 0.8,
        "planning_route": "none_required",
        "pd_conditions": "Building regs only. Match style in conservation area.",
    },
    "smart_controls": {
        "label": "Smart Heating Controls",
        "category": "energy",
        "energy_saving_pct": 0.12,
        "planning_route": "none_required",
    },
}

# ---------------------------------------------------------------------------
# UK Retrofit Costs (2024/25) — low / mid / high
# ---------------------------------------------------------------------------

UK_RETROFIT_COSTS: dict[str, dict] = {
    "rear_extension_single": {"low": 1400, "mid": 2000, "high": 2800, "unit": "per_m2", "typical_m2": 16},
    "rear_extension_double": {"low": 1600, "mid": 2200, "high": 3200, "unit": "per_m2", "typical_m2": 24},
    "side_extension": {"low": 1500, "mid": 2100, "high": 3000, "unit": "per_m2", "typical_m2": 15},
    "loft_dormer": {"low": 35000, "mid": 50000, "high": 70000, "unit": "fixed"},
    "loft_velux": {"low": 20000, "mid": 30000, "high": 45000, "unit": "fixed"},
    "ewi": {"low": 8000, "mid": 12000, "high": 18000, "unit": "fixed"},
    "iwi": {"low": 5000, "mid": 8000, "high": 12000, "unit": "fixed"},
    "cavity_wall": {"low": 700, "mid": 1200, "high": 2000, "unit": "fixed"},
    "loft_insulation": {"low": 300, "mid": 600, "high": 1200, "unit": "fixed"},
    "floor_insulation": {"low": 1500, "mid": 3000, "high": 5000, "unit": "fixed"},
    "solar_pv": {"low": 5000, "mid": 7500, "high": 10000, "unit": "per_kw", "typical_kw": 4},
    "ashp": {"low": 8000, "mid": 12000, "high": 16000, "unit": "fixed"},
    "gshp": {"low": 15000, "mid": 22000, "high": 30000, "unit": "fixed"},
    "triple_glazing": {"low": 8000, "mid": 12000, "high": 18000, "unit": "fixed"},
    "smart_controls": {"low": 200, "mid": 400, "high": 800, "unit": "fixed"},
}

# ---------------------------------------------------------------------------
# Form encoding — maps form strings to numeric codes
# ---------------------------------------------------------------------------

_FORM_CODES = {
    "terrace": 0, "end_terrace": 1, "semi": 2,
    "detached": 3, "bungalow": 4, "flat": 5,
}
_HEATING_CODES = {
    "gas_boiler": 0, "gas_combi": 1, "oil_boiler": 2,
    "electric_storage": 3, "ashp": 4, "gshp": 5, "lpg": 6,
}
_EPC_SCORES = {"A": 92, "B": 81, "C": 69, "D": 55, "E": 39, "F": 21, "G": 10}

# CBR feature weights (14 dimensions)
_CBR_WEIGHTS = [
    3.0,  # 0: form
    2.5,  # 1: era
    1.5,  # 2: storeys
    2.0,  # 3: plot_area
    1.5,  # 4: GFA
    1.0,  # 5: aspect_ratio (plot W/D)
    2.0,  # 6: EPC score
    1.5,  # 7: wall U-value
    1.0,  # 8: roof U-value
    1.0,  # 9: heating type
    2.0,  # 10: constraint code (conservation/listed)
    0.5,  # 11: lat
    0.5,  # 12: lon
    1.5,  # 13: heating efficiency
]

# Normalisation ranges for each feature
_CBR_RANGES = [
    (0, 5),      # form code
    (1850, 2025),  # era midpoint
    (1, 4),      # storeys
    (50, 1000),  # plot area m2
    (40, 300),   # GFA
    (0.15, 1.5),  # aspect ratio
    (1, 100),    # EPC score
    (0.1, 2.5),  # wall U
    (0.1, 2.5),  # roof U
    (0, 6),      # heating code
    (0, 3),      # constraint code (0=none, 1=conservation, 2=listed_II, 3=listed_I)
    (49, 61),    # lat (UK range)
    (-8, 2),     # lon (UK range)
    (0.5, 4.5),  # heating efficiency (COP/efficiency)
]


# ---------------------------------------------------------------------------
# CBR Encoding
# ---------------------------------------------------------------------------

def encode_property(
    house_type: str,
    plot_width_m: float,
    plot_depth_m: float,
    storeys: int = 2,
    epc_rating: str = "D",
    wall_u: float | None = None,
    roof_u: float | None = None,
    heating: str = "gas_boiler",
    conservation: bool = False,
    listed: str | None = None,
    lat: float = 52.5,
    lon: float = -1.5,
    gfa_m2: float | None = None,
) -> list[float]:
    """Encode a property into a 14-dimensional normalised feature vector."""
    arch = UK_HOUSE_ARCHETYPES.get(house_type)
    if not arch:
        arch = UK_HOUSE_ARCHETYPES["1930s_semi"]

    form_code = _FORM_CODES.get(arch["form"], 2)
    era_mid = arch["era_midpoint"]
    plot_area = plot_width_m * plot_depth_m
    gfa = gfa_m2 if gfa_m2 else arch["typical_gfa_m2"]
    aspect = plot_width_m / max(plot_depth_m, 0.1)
    epc_score = _EPC_SCORES.get(epc_rating.upper(), 55)
    wu = wall_u if wall_u is not None else arch["wall_u"]
    ru = roof_u if roof_u is not None else arch["roof_u"]
    heat_code = _HEATING_CODES.get(heating, 0)

    constraint_code = 0
    if listed == "I" or listed == "I*":
        constraint_code = 3
    elif listed == "II" or listed == "II*":
        constraint_code = 2
    elif conservation:
        constraint_code = 1

    heat_eff = 0.9 if heating.startswith("gas") else 1.0
    if heating == "oil_boiler":
        heat_eff = 0.85
    elif heating == "ashp":
        heat_eff = 3.2
    elif heating == "gshp":
        heat_eff = 4.0
    elif heating == "electric_storage":
        heat_eff = 1.0

    raw = [form_code, era_mid, storeys, plot_area, gfa, aspect, epc_score,
           wu, ru, heat_code, constraint_code, lat, lon, heat_eff]

    # Normalise to 0-1
    normalised = []
    for i, val in enumerate(raw):
        lo, hi = _CBR_RANGES[i]
        norm = (val - lo) / max(hi - lo, 0.001)
        normalised.append(max(0.0, min(1.0, norm)))

    return normalised


# ---------------------------------------------------------------------------
# CBR Matching
# ---------------------------------------------------------------------------

def match_similar_cases(
    encoding: list[float],
    case_library: list[dict],
    top_k: int = 5,
) -> list[dict]:
    """Find top-k most similar cases using weighted Euclidean distance."""
    if not case_library:
        return []

    scored = []
    for case in case_library:
        case_enc = case.get("property_encoding", [])
        if len(case_enc) != len(encoding):
            continue
        dist = 0.0
        for i in range(len(encoding)):
            w = _CBR_WEIGHTS[i] if i < len(_CBR_WEIGHTS) else 1.0
            diff = encoding[i] - case_enc[i]
            dist += w * diff * diff
        dist = math.sqrt(dist)
        similarity = max(0.0, 1.0 - dist / 10.0)
        scored.append({**case, "distance": round(dist, 4), "similarity": round(similarity, 4)})

    scored.sort(key=lambda x: x["distance"])
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Planning route classification
# ---------------------------------------------------------------------------

def classify_planning_route(
    interventions: list[str],
    form: str,
    conservation: bool = False,
    listed: str | None = None,
) -> dict:
    """Classify planning route for a set of interventions under GPDO 2015."""
    if listed:
        return {
            "route": "listed_building_consent",
            "description": f"Listed building ({listed}) — all external works require Listed Building Consent in addition to any planning permission.",
            "risk": "high",
            "notes": "Consult conservation officer early. Heritage Impact Assessment required.",
        }

    routes = []
    for intv_id in interventions:
        intv = RETROFIT_INTERVENTIONS.get(intv_id)
        if not intv:
            continue
        route = intv.get("planning_route", "none_required")
        if conservation and route == "permitted_development":
            if intv["category"] == "extension":
                route = "full_planning"
        routes.append(route)

    if "full_planning" in routes:
        return {
            "route": "full_planning",
            "description": "At least one intervention requires full planning permission.",
            "risk": "medium",
            "notes": "Pre-application advised. 8-13 week determination. ~£206 householder fee.",
        }
    if "prior_approval" in routes:
        return {
            "route": "prior_approval",
            "description": "Larger home extension via prior approval (Class A GPDO 2015).",
            "risk": "low-medium",
            "notes": "42-day neighbour consultation. ~£96 fee.",
        }
    if "permitted_development" in routes:
        return {
            "route": "permitted_development",
            "description": "All interventions fall within Permitted Development rights (GPDO 2015).",
            "risk": "low",
            "notes": "Consider applying for Lawful Development Certificate (£103) for certainty.",
        }
    return {
        "route": "none_required",
        "description": "No planning permission required — internal works and minor improvements only.",
        "risk": "none",
        "notes": "Building Regulations approval may still be needed.",
    }


# ---------------------------------------------------------------------------
# Simplified energy model (SAP-lite)
# ---------------------------------------------------------------------------

def estimate_energy_improvement(
    house_type: str,
    interventions: list[str],
    gfa_m2: float | None = None,
    storeys: int | None = None,
    existing_wall_u: float | None = None,
    existing_roof_u: float | None = None,
    existing_floor_u: float | None = None,
    existing_window_u: float | None = None,
    existing_heating: str = "gas_boiler",
    lat: float = 52.5,
) -> dict:
    """Simplified SAP model: fabric loss + ventilation + solar gains → annual kWh, CO2, EPC band."""
    arch = UK_HOUSE_ARCHETYPES.get(house_type, UK_HOUSE_ARCHETYPES["1930s_semi"])
    gfa = gfa_m2 or arch["typical_gfa_m2"]
    st = storeys or arch["storeys"]
    storey_height = 2.5

    # Current U-values
    wall_u = existing_wall_u or arch["wall_u"]
    roof_u = existing_roof_u or arch["roof_u"]
    floor_u = existing_floor_u or arch["floor_u"]
    window_u = existing_window_u or arch["window_u"]
    heating = existing_heating

    # Estimated areas
    floor_area_per_storey = gfa / st
    perimeter = 2 * math.sqrt(floor_area_per_storey * 4)  # rough square

    # Party wall correction — shared walls have zero heat loss
    form = arch.get("form", "detached")
    exposed_wall_fraction = {
        "detached": 1.0, "semi": 0.75, "end_terrace": 0.75,
        "terrace": 0.5, "bungalow": 1.0, "flat": 0.3,
    }.get(form, 1.0)

    wall_area = perimeter * storey_height * st * exposed_wall_fraction
    window_pct = 0.15
    window_area = wall_area * window_pct
    net_wall_area = wall_area * (1 - window_pct)
    roof_area = floor_area_per_storey  # top storey only
    floor_area = floor_area_per_storey  # ground floor only

    # Degree days (UK average ~2200 heating degree days)
    hdd = 2200
    # Adjust for latitude (more HDD further north)
    hdd += (lat - 52.5) * 100

    # Fabric heat loss coefficient (W/K)
    def calc_heat_loss():
        return (net_wall_area * wall_u +
                window_area * window_u +
                roof_area * roof_u +
                floor_area * floor_u)

    # Ventilation heat loss (W/K) — 0.33 * volume * ACH
    volume = gfa * storey_height
    ach = 0.7  # air changes per hour (typical UK)
    vent_loss = 0.33 * volume * ach

    # Before
    fabric_loss_before = calc_heat_loss()
    total_loss_before = fabric_loss_before + vent_loss
    annual_heat_demand_before = total_loss_before * hdd * 24 / 1000  # kWh

    # Heating efficiency
    heat_eff = {"gas_boiler": 0.85, "gas_combi": 0.90, "oil_boiler": 0.82,
                "electric_storage": 1.0, "ashp": 3.2, "gshp": 4.0, "lpg": 0.85}
    eff_before = heat_eff.get(heating, 0.85)
    energy_before = annual_heat_demand_before / eff_before

    # Solar gains (south-facing, UK annual average ~900 kWh/m² GHI)
    ghi = 900 + (52.5 - lat) * 30
    solar_gain_factor = 0.04  # ~4% of floor area as solar aperture
    solar_gains = gfa * solar_gain_factor * ghi * 0.5 / 1000  # rough kWh saving

    energy_before -= solar_gains
    energy_before = max(energy_before, gfa * 30)  # minimum realistic

    # Hot water (~3000 kWh/yr for typical UK home)
    hot_water = 3000
    total_energy_before = energy_before + hot_water

    # Apply interventions
    gfa_after = gfa
    new_wall_u = wall_u
    new_roof_u = roof_u
    new_floor_u = floor_u
    new_window_u = window_u
    new_heating = heating
    solar_kw = 0.0
    smart_saving = 0.0

    for intv_id in interventions:
        intv = RETROFIT_INTERVENTIONS.get(intv_id)
        if not intv:
            continue
        cat = intv.get("category")

        if cat == "extension":
            gain = intv.get("gfa_gain_m2", 0)
            if not gain and "gfa_gain_factor" in intv:
                depth = intv.get("typical_depth_m", 3.0)
                width = math.sqrt(floor_area_per_storey) * 0.7  # ~70% of house width
                gain = depth * width * intv["gfa_gain_factor"]
            gfa_after += gain

        elif cat == "insulation":
            new_u = intv.get("new_u_value")
            if not new_u:
                continue
            if intv_id in ("ewi", "iwi", "cavity_wall"):
                new_wall_u = min(new_wall_u, new_u)
            elif intv_id == "loft_insulation":
                new_roof_u = min(new_roof_u, new_u)
            elif intv_id == "floor_insulation":
                new_floor_u = min(new_floor_u, new_u)
            elif intv_id == "triple_glazing":
                new_window_u = min(new_window_u, new_u)

        elif cat == "energy":
            if intv_id == "solar_pv":
                kw_per_m2 = intv.get("typical_kw_per_m2", 0.18)
                usable_roof = roof_area * 0.4  # 40% usable
                solar_kw = usable_roof * kw_per_m2
            elif intv_id in ("ashp", "gshp"):
                new_heating = intv_id
            elif intv_id == "smart_controls":
                smart_saving = intv.get("energy_saving_pct", 0.12)

    # After U-values
    net_wall_after = net_wall_area * new_wall_u
    window_after = window_area * new_window_u
    roof_after = roof_area * new_roof_u
    floor_after = floor_area * new_floor_u
    fabric_loss_after = net_wall_after + window_after + roof_after + floor_after

    total_loss_after = fabric_loss_after + vent_loss
    annual_heat_demand_after = total_loss_after * hdd * 24 / 1000

    eff_after = heat_eff.get(new_heating, 0.85)
    energy_after = annual_heat_demand_after / eff_after
    energy_after -= solar_gains
    energy_after = max(energy_after, gfa_after * 15)

    # Smart controls reduce heating demand
    energy_after *= (1 - smart_saving)

    # Solar PV generation (UK ~950 kWh/kWp/yr)
    solar_gen = solar_kw * 950 if solar_kw > 0 else 0

    total_energy_after = energy_after + hot_water - solar_gen
    total_energy_after = max(total_energy_after, 0)

    # CO2 factors (kg CO2/kWh)
    co2_factor = {"gas_boiler": 0.203, "gas_combi": 0.203, "oil_boiler": 0.245,
                  "electric_storage": 0.136, "ashp": 0.136, "gshp": 0.136, "lpg": 0.214}
    # Grid electricity for heat pumps, gas for gas heating
    co2_before = total_energy_before * co2_factor.get(heating, 0.203)
    co2_after = total_energy_after * co2_factor.get(new_heating, 0.136)

    # SAP score estimate — piecewise linear calibrated to UK EPC distribution
    # Reference: SAP 2012 methodology, Table 14
    def energy_to_sap(kwh, area):
        per_m2 = kwh / max(area, 1)
        # Interpolation points: (kWh/m², SAP score)
        points = [
            (0, 100), (30, 92), (60, 81), (100, 69),
            (150, 55), (250, 39), (350, 21), (500, 1),
        ]
        if per_m2 <= points[0][0]:
            return points[0][1]
        for i in range(1, len(points)):
            if per_m2 <= points[i][0]:
                x0, y0 = points[i - 1]
                x1, y1 = points[i]
                t = (per_m2 - x0) / (x1 - x0)
                return round(y0 + t * (y1 - y0))
        return 1

    sap_before = energy_to_sap(total_energy_before, gfa)
    sap_after = energy_to_sap(total_energy_after, gfa_after)

    def sap_to_epc(sap):
        if sap >= 92: return "A"
        if sap >= 81: return "B"
        if sap >= 69: return "C"
        if sap >= 55: return "D"
        if sap >= 39: return "E"
        if sap >= 21: return "F"
        return "G"

    return {
        "gfa_before_m2": round(gfa, 1),
        "gfa_after_m2": round(gfa_after, 1),
        "energy_before_kwh": round(total_energy_before),
        "energy_after_kwh": round(total_energy_after),
        "energy_saving_kwh": round(total_energy_before - total_energy_after),
        "energy_saving_pct": round((1 - total_energy_after / max(total_energy_before, 1)) * 100, 1),
        "co2_before_kg": round(co2_before),
        "co2_after_kg": round(co2_after),
        "co2_saving_kg": round(co2_before - co2_after),
        "sap_before": round(sap_before),
        "sap_after": round(sap_after),
        "epc_before": sap_to_epc(sap_before),
        "epc_after": sap_to_epc(sap_after),
        "solar_pv_kw": round(solar_kw, 2) if solar_kw else None,
        "solar_annual_kwh": round(solar_gen) if solar_gen else None,
        "heating_before": heating,
        "heating_after": new_heating,
    }


# ---------------------------------------------------------------------------
# Extension geometry generation
# ---------------------------------------------------------------------------

def generate_extension_geometry(
    footprint_geojson: dict | None,
    extension_type: str,
    depth_m: float,
    width_m: float,
    height_m: float = 3.0,
    side: str = "rear",
) -> dict:
    """Generate GeoJSON polygon for a proposed extension.

    If no building footprint is provided, creates a simple rectangle
    relative to an assumed house position at origin.
    """
    if footprint_geojson and footprint_geojson.get("coordinates"):
        coords = footprint_geojson["coordinates"]
        if footprint_geojson["type"] == "Polygon":
            ring = coords[0]
        elif footprint_geojson["type"] == "MultiPolygon":
            ring = coords[0][0]
        else:
            ring = [[0, 0], [10, 0], [10, 8], [0, 8], [0, 0]]

        # Find the rear edge (southernmost / largest-y edge for rear)
        # Simplified: use bounding box
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        house_width = max_x - min_x
        house_depth = max_y - min_y

        if side == "rear":
            cx = (min_x + max_x) / 2
            ext_half_w = min(width_m / 2, house_width / 2)
            ext_coords = [
                [cx - ext_half_w, min_y - depth_m],
                [cx + ext_half_w, min_y - depth_m],
                [cx + ext_half_w, min_y],
                [cx - ext_half_w, min_y],
                [cx - ext_half_w, min_y - depth_m],
            ]
        elif side == "left":
            ext_coords = [
                [min_x - depth_m, min_y],
                [min_x, min_y],
                [min_x, min_y + width_m],
                [min_x - depth_m, min_y + width_m],
                [min_x - depth_m, min_y],
            ]
        else:  # right
            ext_coords = [
                [max_x, min_y],
                [max_x + depth_m, min_y],
                [max_x + depth_m, min_y + width_m],
                [max_x, min_y + width_m],
                [max_x, min_y],
            ]
    else:
        # No footprint — generate relative to assumed 8m x 10m house at 0,0
        if side == "rear":
            ext_coords = [
                [-width_m / 2, -depth_m],
                [width_m / 2, -depth_m],
                [width_m / 2, 0],
                [-width_m / 2, 0],
                [-width_m / 2, -depth_m],
            ]
        elif side == "left":
            ext_coords = [
                [-depth_m - 4, 0],
                [-4, 0],
                [-4, width_m],
                [-depth_m - 4, width_m],
                [-depth_m - 4, 0],
            ]
        else:
            ext_coords = [
                [4, 0],
                [4 + depth_m, 0],
                [4 + depth_m, width_m],
                [4, width_m],
                [4, 0],
            ]

    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [ext_coords],
        },
        "properties": {
            "type": extension_type,
            "depth_m": depth_m,
            "width_m": width_m,
            "height_m": height_m,
            "side": side,
            "area_m2": round(depth_m * width_m, 1),
        },
    }


# ---------------------------------------------------------------------------
# Solar potential assessment
# ---------------------------------------------------------------------------

def estimate_solar_potential(
    roof_area_m2: float,
    orientation: str = "south",
    lat: float = 52.5,
    lon: float = -1.5,
    tilt_deg: float = 35.0,
) -> dict:
    """Estimate rooftop solar PV potential."""
    # Orientation factor (1.0 = south, reduced for other)
    orientation_factors = {
        "south": 1.0, "sse": 0.97, "ssw": 0.97,
        "se": 0.93, "sw": 0.93, "east": 0.82, "west": 0.82,
        "ne": 0.68, "nw": 0.68, "north": 0.55,
    }
    orient_factor = orientation_factors.get(orientation.lower(), 0.85)

    # Tilt factor (optimal ~35° for UK)
    tilt_factor = 1.0 - abs(tilt_deg - 35) * 0.005

    # UK base irradiance ~950-1050 kWh/m²/yr
    base_irradiance = 1000 + (52.5 - lat) * 20  # less up north

    # Usable area (exclude chimneys, vents, shading)
    usable_area = roof_area_m2 * 0.4

    # Panel efficiency ~20% (modern monocrystalline)
    panel_efficiency = 0.20
    system_losses = 0.85  # inverter, wiring, degradation

    capacity_kw = usable_area * panel_efficiency
    annual_kwh = (usable_area * base_irradiance * panel_efficiency *
                  orient_factor * tilt_factor * system_losses)

    # Financial
    export_rate = 0.055  # SEG rate £/kWh
    self_consumption_pct = 0.40
    import_rate = 0.245  # avg electricity price £/kWh

    annual_saving = (annual_kwh * self_consumption_pct * import_rate +
                     annual_kwh * (1 - self_consumption_pct) * export_rate)

    install_cost = capacity_kw * 1500  # £/kW installed
    payback_years = install_cost / max(annual_saving, 1)

    return {
        "capacity_kw": round(capacity_kw, 2),
        "annual_kwh": round(annual_kwh),
        "usable_roof_m2": round(usable_area, 1),
        "orientation": orientation,
        "orientation_factor": orient_factor,
        "tilt_deg": tilt_deg,
        "annual_saving_gbp": round(annual_saving),
        "install_cost_gbp": round(install_cost),
        "payback_years": round(payback_years, 1),
        "co2_saving_kg_yr": round(annual_kwh * 0.136),
    }


# ---------------------------------------------------------------------------
# Heat pump suitability
# ---------------------------------------------------------------------------

def assess_heat_pump_suitability(
    form: str,
    gfa_m2: float,
    wall_u: float,
    heating: str,
    garden_m2: float | None = None,
) -> dict:
    """Assess ASHP/GSHP viability for a property."""
    results = {}

    # ASHP assessment
    ashp_suitable = True
    ashp_notes = []
    if form == "flat":
        ashp_suitable = False
        ashp_notes.append("Flats generally unsuitable for ASHP (no outdoor space, noise constraints)")
    if form == "terrace":
        ashp_notes.append("Mid-terrace: limited outdoor space for unit placement. Side/rear access needed.")

    # Fabric efficiency check
    if wall_u > 1.5:
        ashp_notes.append("High wall U-value (>1.5) — insulation recommended before ASHP for efficient low-temperature heating")
    if wall_u > 2.0:
        ashp_notes.append("WARNING: Very poor insulation. ASHP will struggle to maintain comfort. Fabric-first approach essential.")

    # Design heat loss for sizing
    design_temp_diff = 21 - (-3)  # 21°C indoor, -3°C design outdoor
    storey_height = 2.5
    volume = gfa_m2 * storey_height
    heat_loss_approx = (gfa_m2 * wall_u * 0.4 + gfa_m2 * 0.3) * design_temp_diff / 1000  # rough kW
    ashp_size_kw = max(4, min(16, heat_loss_approx * 1.2))

    running_cost_gas = gfa_m2 * 100 * 0.07 / 0.85  # rough annual gas cost
    running_cost_ashp = gfa_m2 * 100 * 0.245 / 3.2  # electricity / COP
    annual_saving = running_cost_gas - running_cost_ashp

    results["ashp"] = {
        "suitable": ashp_suitable,
        "recommended_kw": round(ashp_size_kw, 1),
        "estimated_cop": 3.2,
        "install_cost_gbp": round(ashp_size_kw * 1000 + 5000),
        "annual_running_cost_gbp": round(running_cost_ashp),
        "annual_saving_vs_gas_gbp": round(annual_saving),
        "bus_grant_eligible": True,
        "bus_grant_gbp": 7500,
        "net_cost_gbp": round(max(0, ashp_size_kw * 1000 + 5000 - 7500)),
        "notes": ashp_notes,
    }

    # GSHP assessment
    gshp_suitable = True
    gshp_notes = []
    garden = garden_m2 or 0
    if garden < 100:
        gshp_suitable = False
        gshp_notes.append(f"Garden area ({garden}m²) too small for ground loops (need ~100m² minimum)")
    else:
        gshp_notes.append(f"Garden area ({garden}m²) sufficient for horizontal ground loops")

    if form in ("terrace", "flat"):
        gshp_suitable = False
        gshp_notes.append("Access constraints for drilling/trenching in terrace/flat settings")

    running_cost_gshp = gfa_m2 * 100 * 0.245 / 4.0
    results["gshp"] = {
        "suitable": gshp_suitable,
        "recommended_kw": round(ashp_size_kw * 0.9, 1),
        "estimated_cop": 4.0,
        "install_cost_gbp": round(ashp_size_kw * 2000 + 8000),
        "annual_running_cost_gbp": round(running_cost_gshp),
        "annual_saving_vs_gas_gbp": round(running_cost_gas - running_cost_gshp),
        "bus_grant_eligible": True,
        "bus_grant_gbp": 7500,
        "notes": gshp_notes,
    }

    results["recommendation"] = "ashp" if ashp_suitable else ("gshp" if gshp_suitable else "none")
    return results


# ---------------------------------------------------------------------------
# Intervention cost estimation
# ---------------------------------------------------------------------------

def estimate_intervention_cost(
    intervention_id: str,
    plot_width_m: float = 8.0,
    depth_m: float | None = None,
    tier: str = "mid",
) -> dict:
    """Estimate cost for a single intervention."""
    costs = UK_RETROFIT_COSTS.get(intervention_id)
    intv = RETROFIT_INTERVENTIONS.get(intervention_id)
    if not costs or not intv:
        return {"error": f"Unknown intervention: {intervention_id}"}

    unit_cost = costs.get(tier, costs["mid"])
    unit = costs["unit"]

    if unit == "per_m2":
        ext_depth = depth_m or intv.get("typical_depth_m", 3.0)
        ext_width = plot_width_m * 0.7
        area = ext_depth * ext_width
        total = unit_cost * area
        return {
            "intervention": intervention_id,
            "label": intv["label"],
            "tier": tier,
            "unit_cost_gbp": unit_cost,
            "area_m2": round(area, 1),
            "total_cost_gbp": round(total),
        }
    elif unit == "per_kw":
        kw = costs.get("typical_kw", 4)
        total = unit_cost * kw
        return {
            "intervention": intervention_id,
            "label": intv["label"],
            "tier": tier,
            "unit_cost_gbp": unit_cost,
            "capacity_kw": kw,
            "total_cost_gbp": round(total),
        }
    else:
        return {
            "intervention": intervention_id,
            "label": intv["label"],
            "tier": tier,
            "total_cost_gbp": unit_cost,
        }


# ---------------------------------------------------------------------------
# Option package generation
# ---------------------------------------------------------------------------

def generate_retrofit_options(
    encoding: list[float],
    matched_cases: list[dict],
    house_type: str,
    plot_width_m: float,
    plot_depth_m: float,
    storeys: int = 2,
    epc_rating: str = "D",
    heating: str = "gas_boiler",
    conservation: bool = False,
    listed: str | None = None,
    budget_gbp: float | None = None,
    gfa_m2: float | None = None,
    lat: float = 52.5,
    lon: float = -1.5,
) -> list[dict]:
    """Generate 3-5 ranked retrofit option packages."""
    arch = UK_HOUSE_ARCHETYPES.get(house_type, UK_HOUSE_ARCHETYPES["1930s_semi"])
    form = arch["form"]
    wall_u = arch["wall_u"]
    wall_const = arch["wall_construction"]

    packages = []

    # --- Package 1: Quick Wins (insulation only) ---
    quick_wins = ["loft_insulation", "smart_controls"]
    if wall_const == "cavity_unfilled":
        quick_wins.insert(0, "cavity_wall")
    if wall_u > 1.0:
        quick_wins.append("floor_insulation")

    qw_cost = sum(UK_RETROFIT_COSTS[i]["mid"] for i in quick_wins if i in UK_RETROFIT_COSTS)
    qw_energy = estimate_energy_improvement(
        house_type, quick_wins, gfa_m2, storeys, lat=lat,
        existing_heating=heating,
    )
    packages.append({
        "name": "Quick Wins",
        "description": "Low-cost insulation improvements for immediate energy savings",
        "interventions": quick_wins,
        "total_cost_gbp": qw_cost,
        "cost_range": {"low": int(qw_cost * 0.7), "high": int(qw_cost * 1.4)},
        "energy": qw_energy,
        "planning": classify_planning_route(quick_wins, form, conservation, listed),
        "provenance": _find_provenance(matched_cases, quick_wins),
    })

    # --- Package 2: Fabric First ---
    fabric_first = ["loft_insulation"]
    if wall_const in ("solid_brick_9in", "solid_brick_13in", "cavity_unfilled"):
        if wall_const == "cavity_unfilled":
            fabric_first.append("cavity_wall")
        elif conservation:
            fabric_first.append("iwi")
        else:
            fabric_first.append("ewi")
    fabric_first.extend(["floor_insulation", "triple_glazing", "smart_controls"])

    ff_cost = sum(UK_RETROFIT_COSTS[i]["mid"] for i in fabric_first if i in UK_RETROFIT_COSTS)
    ff_energy = estimate_energy_improvement(
        house_type, fabric_first, gfa_m2, storeys, lat=lat,
        existing_heating=heating,
    )
    packages.append({
        "name": "Fabric First",
        "description": "Comprehensive insulation upgrade — maximise fabric efficiency before energy systems",
        "interventions": fabric_first,
        "total_cost_gbp": ff_cost,
        "cost_range": {"low": int(ff_cost * 0.7), "high": int(ff_cost * 1.4)},
        "energy": ff_energy,
        "planning": classify_planning_route(fabric_first, form, conservation, listed),
        "provenance": _find_provenance(matched_cases, fabric_first),
    })

    # --- Package 3: Extension + Energy ---
    ext_energy = list(fabric_first)
    if form != "flat" and not listed:
        if form in ("detached", "semi", "end_terrace", "bungalow"):
            ext_energy.insert(0, "rear_extension_single")
        elif form == "terrace":
            ext_energy.insert(0, "rear_extension_single")
    ext_energy.append("solar_pv")
    ext_energy.append("ashp")

    ee_cost = 0
    for intv_id in ext_energy:
        c = UK_RETROFIT_COSTS.get(intv_id)
        if not c:
            continue
        if c["unit"] == "per_m2":
            depth = RETROFIT_INTERVENTIONS[intv_id].get("typical_depth_m", 3.0)
            width = plot_width_m * 0.7
            ee_cost += int(c["mid"] * depth * width)
        elif c["unit"] == "per_kw":
            ee_cost += int(c["mid"] * c.get("typical_kw", 4))
        else:
            ee_cost += c["mid"]

    ee_energy = estimate_energy_improvement(
        house_type, ext_energy, gfa_m2, storeys, lat=lat,
        existing_heating=heating,
    )
    packages.append({
        "name": "Extension + Energy",
        "description": "Rear extension with solar PV and heat pump — maximise space and sustainability",
        "interventions": ext_energy,
        "total_cost_gbp": ee_cost,
        "cost_range": {"low": int(ee_cost * 0.7), "high": int(ee_cost * 1.4)},
        "energy": ee_energy,
        "planning": classify_planning_route(ext_energy, form, conservation, listed),
        "provenance": _find_provenance(matched_cases, ext_energy),
    })

    # --- Package 4: Full Retrofit ---
    full = list(ext_energy)
    if "loft_dormer" not in full and form not in ("bungalow", "flat") and not listed:
        full.append("loft_dormer")

    full_cost = 0
    for intv_id in full:
        c = UK_RETROFIT_COSTS.get(intv_id)
        if not c:
            continue
        if c["unit"] == "per_m2":
            depth = RETROFIT_INTERVENTIONS[intv_id].get("typical_depth_m", 3.0)
            width = plot_width_m * 0.7
            full_cost += int(c["mid"] * depth * width)
        elif c["unit"] == "per_kw":
            full_cost += int(c["mid"] * c.get("typical_kw", 4))
        else:
            full_cost += c["mid"]

    full_energy = estimate_energy_improvement(
        house_type, full, gfa_m2, storeys, lat=lat,
        existing_heating=heating,
    )
    packages.append({
        "name": "Full Retrofit",
        "description": "Maximum transformation — extension, loft, insulation, solar, heat pump",
        "interventions": full,
        "total_cost_gbp": full_cost,
        "cost_range": {"low": int(full_cost * 0.7), "high": int(full_cost * 1.4)},
        "energy": full_energy,
        "planning": classify_planning_route(full, form, conservation, listed),
        "provenance": _find_provenance(matched_cases, full),
    })

    # --- Package 5: Budget Option (if budget specified) ---
    if budget_gbp:
        budget_items = []
        running_cost = 0
        # Sort by cost-effectiveness
        candidates = []
        for intv_id in ["cavity_wall", "loft_insulation", "smart_controls", "floor_insulation",
                        "iwi", "ewi", "triple_glazing", "solar_pv", "ashp"]:
            c = UK_RETROFIT_COSTS.get(intv_id)
            if not c:
                continue
            if c["unit"] == "per_m2":
                cost = int(c["mid"] * 4 * plot_width_m * 0.7)
            elif c["unit"] == "per_kw":
                cost = int(c["mid"] * c.get("typical_kw", 4))
            else:
                cost = c["mid"]
            candidates.append((intv_id, cost))

        candidates.sort(key=lambda x: x[1])
        for intv_id, cost in candidates:
            if running_cost + cost <= budget_gbp:
                # Check applicability
                intv = RETROFIT_INTERVENTIONS.get(intv_id, {})
                applicable_walls = intv.get("applicable_walls", [])
                if applicable_walls and wall_const not in applicable_walls:
                    continue
                budget_items.append(intv_id)
                running_cost += cost

        if budget_items:
            bud_energy = estimate_energy_improvement(
                house_type, budget_items, gfa_m2, storeys, lat=lat,
                existing_heating=heating,
            )
            packages.append({
                "name": "Budget Option",
                "description": f"Best value within £{budget_gbp:,.0f} budget",
                "interventions": budget_items,
                "total_cost_gbp": running_cost,
                "cost_range": {"low": int(running_cost * 0.7), "high": int(running_cost * 1.4)},
                "energy": bud_energy,
                "planning": classify_planning_route(budget_items, form, conservation, listed),
                "provenance": _find_provenance(matched_cases, budget_items),
            })

    return packages


def _find_provenance(matched_cases: list[dict], interventions: list[str]) -> list[dict]:
    """Find planning provenance from matched cases for given interventions."""
    provenance = []
    intv_set = set(interventions)
    for case in matched_cases:
        case_intvs = set()
        ci = case.get("interventions", [])
        if isinstance(ci, list):
            case_intvs = set(ci)
        elif isinstance(ci, dict):
            case_intvs = set(ci.keys())
        overlap = intv_set & case_intvs
        if overlap:
            provenance.append({
                "case_ref": case.get("case_ref", ""),
                "house_type": case.get("house_type", ""),
                "planning_ref": case.get("planning_ref", ""),
                "planning_authority": case.get("planning_authority", ""),
                "planning_outcome": case.get("planning_outcome", ""),
                "similarity": case.get("similarity", 0),
                "matching_interventions": sorted(overlap),
            })
    return provenance[:3]


# ---------------------------------------------------------------------------
# Full CBR assessment (orchestrator)
# ---------------------------------------------------------------------------

def run_assessment(
    house_type: str,
    plot_width_m: float,
    plot_depth_m: float,
    storeys: int = 2,
    epc_rating: str = "D",
    heating: str = "gas_boiler",
    conservation: bool = False,
    listed: str | None = None,
    budget_gbp: float | None = None,
    lat: float = 52.5,
    lon: float = -1.5,
    gfa_m2: float | None = None,
    case_library: list[dict] | None = None,
) -> dict:
    """Run a complete home retrofit CBR assessment."""
    encoding = encode_property(
        house_type, plot_width_m, plot_depth_m, storeys, epc_rating,
        heating=heating, conservation=conservation, listed=listed,
        lat=lat, lon=lon, gfa_m2=gfa_m2,
    )

    matched = match_similar_cases(encoding, case_library or [], top_k=5)

    options = generate_retrofit_options(
        encoding, matched, house_type, plot_width_m, plot_depth_m,
        storeys, epc_rating, heating, conservation, listed, budget_gbp,
        gfa_m2, lat, lon,
    )

    arch = UK_HOUSE_ARCHETYPES.get(house_type, UK_HOUSE_ARCHETYPES["1930s_semi"])

    # Generate extension geometries for packages that include extensions
    for pkg in options:
        geometries = []
        for intv_id in pkg["interventions"]:
            intv = RETROFIT_INTERVENTIONS.get(intv_id)
            if not intv or intv.get("category") != "extension":
                continue
            if intv_id in ("loft_dormer", "loft_velux"):
                continue
            depth = intv.get("typical_depth_m", 3.0)
            width = plot_width_m * 0.7
            height = intv.get("max_height_m", 3.0)
            side = "right" if intv_id == "side_extension" else "rear"
            geom = generate_extension_geometry(None, intv_id, depth, width, height, side)
            geometries.append(geom)
        pkg["geometries"] = geometries

    # Solar potential
    roof_area = (gfa_m2 or arch["typical_gfa_m2"]) / storeys
    solar = estimate_solar_potential(roof_area, lat=lat, lon=lon)

    # Heat pump suitability
    garden_m2 = (plot_width_m * plot_depth_m) - (gfa_m2 or arch["typical_gfa_m2"]) / storeys
    heat_pump = assess_heat_pump_suitability(
        arch["form"], gfa_m2 or arch["typical_gfa_m2"],
        arch["wall_u"], heating, garden_m2,
    )

    return {
        "house_type": house_type,
        "archetype": arch["label"],
        "property_encoding": encoding,
        "matched_cases": [{k: v for k, v in c.items() if k != "property_encoding"}
                         for c in matched],
        "options": options,
        "solar_potential": solar,
        "heat_pump_assessment": heat_pump,
        "summary": {
            "best_value_package": options[0]["name"] if options else None,
            "deepest_retrofit_package": options[-1]["name"] if options else None,
            "max_epc_improvement": (
                f"{options[0]['energy']['epc_before']} → {options[-1]['energy']['epc_after']}"
                if options else None
            ),
        },
    }


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def setup_home_retrofit_tables(conn) -> None:
    """Create home_retrofit_cases and home_retrofit_assessments tables."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS home_retrofit_cases (
            case_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_ref             TEXT,
            house_type           TEXT NOT NULL,
            house_form           TEXT,
            era                  TEXT,
            storeys              INTEGER DEFAULT 2,
            plot_width_m         DOUBLE PRECISION,
            plot_depth_m         DOUBLE PRECISION,
            gfa_before_m2        DOUBLE PRECISION,
            gfa_after_m2         DOUBLE PRECISION,
            epc_before           TEXT,
            epc_after            TEXT,
            sap_before           INTEGER,
            sap_after            INTEGER,
            interventions        JSONB,
            cost_actual_gbp      INTEGER,
            energy_saving_kwh_yr INTEGER,
            co2_saving_kg_yr     INTEGER,
            planning_ref         TEXT,
            planning_route       TEXT,
            planning_authority   TEXT,
            planning_outcome     TEXT,
            planning_date        DATE,
            property_encoding    JSONB,
            lat                  DOUBLE PRECISION DEFAULT 52.5,
            lon                  DOUBLE PRECISION DEFAULT -1.5,
            geometry             GEOMETRY(Point, 27700),
            created_at           TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_home_retrofit_cases_type
        ON home_retrofit_cases (house_type)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_home_retrofit_cases_geom
        ON home_retrofit_cases USING GIST (geometry)
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS home_retrofit_assessments (
            assessment_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            parcel_id            UUID,
            house_type           TEXT,
            property_encoding    JSONB,
            matched_cases        JSONB,
            options              JSONB,
            selected_option      TEXT,
            total_cost_gbp       INTEGER,
            energy_saving_kwh_yr INTEGER,
            co2_saving_kg_yr     INTEGER,
            epc_before           TEXT,
            epc_after            TEXT,
            planning_route       TEXT,
            retrofit_geometry    JSONB,
            lat                  DOUBLE PRECISION,
            lon                  DOUBLE PRECISION,
            geometry             GEOMETRY(Point, 27700),
            created_at           TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_home_retrofit_assessments_geom
        ON home_retrofit_assessments USING GIST (geometry)
    """)
    log.info("Home retrofit tables created/verified")


async def seed_exemplar_cases(conn) -> None:
    """Seed 80-100 realistic UK exemplar cases across all archetypes."""
    existing = await conn.fetchval("SELECT count(*) FROM home_retrofit_cases")
    if existing > 0:
        log.info("Home retrofit cases already seeded (%d rows)", existing)
        return

    rng = random.Random(42)

    # UK planning authorities
    authorities = [
        "Bristol City Council", "Bath & NE Somerset", "South Gloucestershire",
        "Birmingham City Council", "Leeds City Council", "Manchester City Council",
        "Sheffield City Council", "Liverpool City Council", "Camden LBC",
        "Hackney LBC", "Islington LBC", "Southwark LBC", "Lambeth LBC",
        "Wandsworth LBC", "Nottingham City Council", "Leicester City Council",
        "Oxford City Council", "Cambridge City Council", "Brighton & Hove CC",
        "Southampton CC",
    ]

    # Intervention combos typical for each archetype era
    era_interventions = {
        "victorian": [
            ["ewi", "loft_insulation", "smart_controls"],
            ["iwi", "loft_insulation", "floor_insulation"],
            ["rear_extension_single", "ewi", "solar_pv"],
            ["loft_dormer", "iwi", "triple_glazing"],
            ["rear_extension_single", "loft_dormer", "ewi", "ashp", "solar_pv"],
        ],
        "edwardian": [
            ["ewi", "loft_insulation", "floor_insulation"],
            ["rear_extension_single", "ewi", "solar_pv", "ashp"],
            ["iwi", "triple_glazing", "smart_controls"],
            ["loft_dormer", "ewi", "floor_insulation"],
        ],
        "1930s": [
            ["cavity_wall", "loft_insulation", "smart_controls"],
            ["cavity_wall", "floor_insulation", "triple_glazing"],
            ["rear_extension_single", "cavity_wall", "solar_pv"],
            ["rear_extension_double", "cavity_wall", "ashp", "solar_pv"],
            ["loft_dormer", "cavity_wall", "ewi", "ashp"],
        ],
        "postwar": [
            ["cavity_wall", "loft_insulation", "smart_controls"],
            ["rear_extension_single", "cavity_wall", "solar_pv"],
            ["ewi", "floor_insulation", "triple_glazing", "ashp"],
        ],
        "1960s70s": [
            ["cavity_wall", "loft_insulation"],
            ["rear_extension_single", "cavity_wall", "solar_pv"],
            ["ewi", "triple_glazing", "ashp", "solar_pv"],
            ["side_extension", "loft_dormer", "cavity_wall"],
        ],
        "1980s": [
            ["loft_insulation", "smart_controls"],
            ["rear_extension_single", "solar_pv"],
            ["solar_pv", "ashp", "smart_controls"],
            ["rear_extension_double", "solar_pv", "ashp"],
        ],
        "1990s": [
            ["solar_pv", "smart_controls"],
            ["rear_extension_single", "solar_pv", "ashp"],
            ["loft_dormer", "solar_pv"],
        ],
        "modern": [
            ["solar_pv", "ashp"],
            ["rear_extension_single", "solar_pv"],
            ["smart_controls"],
        ],
    }

    archetype_eras = {
        "victorian_terrace_mid": "victorian",
        "victorian_terrace_end": "victorian",
        "edwardian_semi": "edwardian",
        "1930s_semi": "1930s",
        "1930s_detached": "1930s",
        "1950s_semi": "postwar",
        "1960s_detached": "1960s70s",
        "1970s_bungalow": "1960s70s",
        "1980s_semi": "1980s",
        "1990s_detached": "1990s",
        "2000s_townhouse": "modern",
        "modern_newbuild": "modern",
    }

    # UK locations (lat, lon) spread
    uk_locations = [
        (51.45, -2.59), (51.38, -2.36), (51.52, -0.13), (51.51, -0.08),
        (51.48, -0.18), (51.46, -0.02), (51.50, -0.17), (53.48, -2.24),
        (53.38, -1.47), (53.80, -1.55), (52.48, -1.90), (52.95, -1.15),
        (52.63, -1.13), (51.75, -1.26), (52.21, 0.12), (50.83, -0.14),
        (50.91, -1.40), (51.88, -2.08), (53.41, -2.98), (54.97, -1.61),
    ]

    cases = []
    case_num = 0
    for house_type, arch in UK_HOUSE_ARCHETYPES.items():
        era_key = archetype_eras.get(house_type, "1930s")
        intv_options = era_interventions.get(era_key, era_interventions["1930s"])

        n_cases = rng.randint(6, 10)
        for _ in range(n_cases):
            interventions = rng.choice(intv_options)
            lat_base, lon_base = rng.choice(uk_locations)
            lat = lat_base + rng.uniform(-0.1, 0.1)
            lon = lon_base + rng.uniform(-0.1, 0.1)

            pw = arch["typical_plot_width_m"] * rng.uniform(0.85, 1.2)
            pd = arch["typical_plot_depth_m"] * rng.uniform(0.85, 1.2)
            gfa = arch["typical_gfa_m2"] * rng.uniform(0.85, 1.2)

            # Energy assessment
            energy = estimate_energy_improvement(
                house_type, interventions, gfa, arch["storeys"],
                lat=lat, existing_heating=arch["typical_heating"],
            )

            # Cost
            total_cost = 0
            for intv_id in interventions:
                c = UK_RETROFIT_COSTS.get(intv_id)
                if not c:
                    continue
                if c["unit"] == "per_m2":
                    d = RETROFIT_INTERVENTIONS[intv_id].get("typical_depth_m", 3.0)
                    w = pw * 0.7
                    total_cost += int(c["mid"] * d * w * rng.uniform(0.8, 1.3))
                elif c["unit"] == "per_kw":
                    total_cost += int(c["mid"] * c.get("typical_kw", 4) * rng.uniform(0.8, 1.3))
                else:
                    total_cost += int(c["mid"] * rng.uniform(0.8, 1.3))

            encoding = encode_property(
                house_type, pw, pd, arch["storeys"],
                energy["epc_before"], heating=arch["typical_heating"],
                lat=lat, lon=lon, gfa_m2=gfa,
            )

            case_num += 1
            authority = rng.choice(authorities)
            plan_route = classify_planning_route(interventions, arch["form"])["route"]
            outcome = rng.choices(
                ["approved", "approved_with_conditions", "refused"],
                weights=[0.7, 0.25, 0.05],
            )[0]
            plan_year = rng.randint(2019, 2024)
            plan_ref = f"{authority[:3].upper()}/{plan_year}/{rng.randint(1000, 9999)}"

            cases.append({
                "case_ref": f"HRC-{case_num:04d}",
                "house_type": house_type,
                "house_form": arch["form"],
                "era": arch["era"],
                "storeys": arch["storeys"],
                "plot_width_m": round(pw, 1),
                "plot_depth_m": round(pd, 1),
                "gfa_before": round(gfa, 1),
                "gfa_after": round(energy["gfa_after_m2"], 1),
                "epc_before": energy["epc_before"],
                "epc_after": energy["epc_after"],
                "sap_before": energy["sap_before"],
                "sap_after": energy["sap_after"],
                "interventions": interventions,
                "cost": total_cost,
                "energy_saving": energy["energy_saving_kwh"],
                "co2_saving": energy["co2_saving_kg"],
                "planning_ref": plan_ref,
                "planning_route": plan_route,
                "planning_authority": authority,
                "planning_outcome": outcome,
                "plan_year": plan_year,
                "encoding": encoding,
                "lat": round(lat, 5),
                "lon": round(lon, 5),
            })

    for c in cases:
        plan_date = date(c["plan_year"], rng.randint(1, 12), rng.randint(1, 28))
        await conn.execute(
            """
            INSERT INTO home_retrofit_cases
                (case_ref, house_type, house_form, era, storeys,
                 plot_width_m, plot_depth_m, gfa_before_m2, gfa_after_m2,
                 epc_before, epc_after, sap_before, sap_after,
                 interventions, cost_actual_gbp, energy_saving_kwh_yr, co2_saving_kg_yr,
                 planning_ref, planning_route, planning_authority, planning_outcome, planning_date,
                 property_encoding, lat, lon, geometry)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb,
                    $15,$16,$17,$18,$19,$20,$21,$22,$23::jsonb,$24,$25,
                    ST_Transform(ST_SetSRID(ST_MakePoint($26, $27), 4326), 27700))
            """,
            c["case_ref"], c["house_type"], c["house_form"], c["era"], c["storeys"],
            c["plot_width_m"], c["plot_depth_m"], c["gfa_before"], c["gfa_after"],
            c["epc_before"], c["epc_after"], c["sap_before"], c["sap_after"],
            json.dumps(c["interventions"]), c["cost"], c["energy_saving"], c["co2_saving"],
            c["planning_ref"], c["planning_route"], c["planning_authority"],
            c["planning_outcome"], plan_date,
            json.dumps(c["encoding"]), c["lat"], c["lon"],
            c["lon"], c["lat"],
        )

    log.info("Seeded %d home retrofit exemplar cases", len(cases))


def build_case_library_from_rows(rows) -> list[dict]:
    """Build in-memory case library from database rows."""
    cases = []
    for r in rows:
        encoding = r["property_encoding"]
        if isinstance(encoding, str):
            encoding = json.loads(encoding)
        interventions = r["interventions"]
        if isinstance(interventions, str):
            interventions = json.loads(interventions)
        cases.append({
            "case_id": str(r["case_id"]),
            "case_ref": r["case_ref"],
            "house_type": r["house_type"],
            "house_form": r.get("house_form"),
            "era": r.get("era"),
            "storeys": r.get("storeys"),
            "plot_width_m": r.get("plot_width_m"),
            "plot_depth_m": r.get("plot_depth_m"),
            "gfa_before_m2": r.get("gfa_before_m2"),
            "gfa_after_m2": r.get("gfa_after_m2"),
            "epc_before": r.get("epc_before"),
            "epc_after": r.get("epc_after"),
            "interventions": interventions,
            "cost_actual_gbp": r.get("cost_actual_gbp"),
            "energy_saving_kwh_yr": r.get("energy_saving_kwh_yr"),
            "co2_saving_kg_yr": r.get("co2_saving_kg_yr"),
            "planning_ref": r.get("planning_ref"),
            "planning_route": r.get("planning_route"),
            "planning_authority": r.get("planning_authority"),
            "planning_outcome": r.get("planning_outcome"),
            "property_encoding": encoding,
            "lat": r.get("lat"),
            "lon": r.get("lon"),
        })
    return cases
