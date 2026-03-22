"""Data centre layout engine — auto-generate campus layout from boundary + parameters."""

from __future__ import annotations

import math
import json
from typing import Any

# Standard DC building dimensions (metres)
DC_MODULES = {
    "server_hall": {
        "width_m": 60, "depth_m": 30, "height_m": 12,
        "power_density_mw": 6,  # per hall
        "color": "#1a1a2e",
        "label": "Server Hall",
    },
    "cooling_plant": {
        "width_m": 40, "depth_m": 25, "height_m": 8,
        "color": "#0891b2",
        "label": "Cooling Plant",
    },
    "power_building": {
        "width_m": 30, "depth_m": 20, "height_m": 6,
        "color": "#f59e0b",
        "label": "Power / UPS / Genset",
    },
    "substation": {
        "width_m": 25, "depth_m": 20, "height_m": 5,
        "color": "#78909c",
        "label": "HV Substation",
    },
    "office": {
        "width_m": 25, "depth_m": 15, "height_m": 4,
        "color": "#e0e0e0",
        "label": "NOC / Office",
    },
    "security_gatehouse": {
        "width_m": 8, "depth_m": 6, "height_m": 3,
        "color": "#ef4444",
        "label": "Security",
    },
    "generator_yard": {
        "width_m": 35, "depth_m": 15, "height_m": 4,
        "color": "#6b7280",
        "label": "Generator Yard",
    },
    "water_tank": {
        "width_m": 10, "depth_m": 10, "height_m": 8,
        "color": "#3b82f6",
        "label": "Water Storage",
    },
    "parking": {
        "width_m": 40, "depth_m": 30, "height_m": 0.3,
        "color": "#4b5563",
        "label": "Parking",
    },
}

# Tier specifications (Uptime Institute)
TIER_SPECS = {
    1: {"redundancy": "N", "uptime": 99.671, "generators": 0, "ups": "N", "cooling": "N", "description": "Basic — single path, no redundancy"},
    2: {"redundancy": "N+1", "uptime": 99.741, "generators": 1, "ups": "N+1", "cooling": "N+1", "description": "Redundant components — single distribution path"},
    3: {"redundancy": "N+1", "uptime": 99.982, "generators": 2, "ups": "N+1", "cooling": "N+1", "description": "Concurrently maintainable — dual distribution, single active path"},
    4: {"redundancy": "2N", "uptime": 99.995, "generators": 4, "ups": "2N", "cooling": "2N", "description": "Fault tolerant — dual active paths, full redundancy"},
}


def boundary_from_point(lat: float, lon: float, site_area_ha: float = 5.0) -> list:
    """Create a rectangular boundary polygon from a centre point + area.

    Returns [[lon, lat], ...] ring (5 points, closed).
    """
    side_m = math.sqrt(site_area_ha * 10000)
    m_per_deg_lat = 111320
    m_per_deg_lon = 111320 * math.cos(math.radians(lat))
    half_lon = (side_m / 2) / m_per_deg_lon
    half_lat = (side_m / 2) / m_per_deg_lat
    return [
        [lon - half_lon, lat - half_lat],
        [lon + half_lon, lat - half_lat],
        [lon + half_lon, lat + half_lat],
        [lon - half_lon, lat + half_lat],
        [lon - half_lon, lat - half_lat],  # close ring
    ]


def generate_dc_layout(
    boundary_coords: list,  # [[lon, lat], ...] polygon ring
    it_load_mw: float = 10,
    tier: int = 3,
    cooling_type: str = "hybrid",  # mechanical, free_cooling, hybrid, evaporative
    pue_target: float = 1.3,
) -> dict:
    """Auto-generate a data centre campus layout within a boundary polygon.

    Returns GeoJSON FeatureCollection of building footprints + metadata.
    """
    # Calculate boundary centroid and dimensions
    lats = [c[1] for c in boundary_coords]
    lons = [c[0] for c in boundary_coords]
    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)

    # Approximate boundary dimensions in metres
    m_per_deg_lat = 111320
    m_per_deg_lon = 111320 * math.cos(math.radians(center_lat))

    site_width_m = (max(lons) - min(lons)) * m_per_deg_lon
    site_depth_m = (max(lats) - min(lats)) * m_per_deg_lat
    site_area_m2 = site_width_m * site_depth_m
    site_area_ha = site_area_m2 / 10000

    tier_spec = TIER_SPECS.get(tier, TIER_SPECS[3])

    # Calculate number of server halls needed
    halls_needed = max(1, math.ceil(it_load_mw / DC_MODULES["server_hall"]["power_density_mw"]))

    # Total power (IT + cooling + distribution losses)
    total_power_mw = it_load_mw * pue_target
    cooling_mw = total_power_mw - it_load_mw

    # Number of each building type
    n_cooling = max(1, math.ceil(halls_needed / 2))  # 1 cooling plant per 2 halls
    n_power = max(1, math.ceil(halls_needed / 2))  # power building per 2 halls
    n_generators = tier_spec["generators"] if tier >= 3 else max(1, math.ceil(total_power_mw / 2))
    n_substations = max(1, math.ceil(total_power_mw / 30))  # 1 per ~30MW
    n_water = 1 if cooling_type in ("hybrid", "evaporative") else 0

    # Place buildings on a grid within the boundary
    buildings: list[dict] = []
    cursor_x = min(lons) + 0.0002  # ~20m setback from boundary
    cursor_y = max(lats) - 0.0002
    row_height = 0

    def place(module_type: str, count: int = 1) -> list[dict]:
        nonlocal cursor_x, cursor_y, row_height
        mod = DC_MODULES[module_type]
        placed: list[dict] = []
        for i in range(count):
            w_deg = mod["width_m"] / m_per_deg_lon
            d_deg = mod["depth_m"] / m_per_deg_lat

            # Check if we need a new row
            if cursor_x + w_deg > max(lons) - 0.0001:
                cursor_x = min(lons) + 0.0002
                cursor_y -= (row_height / m_per_deg_lat) + 0.00015  # ~15m gap
                row_height = 0

            # Create building polygon
            bld = {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [cursor_x, cursor_y],
                        [cursor_x + w_deg, cursor_y],
                        [cursor_x + w_deg, cursor_y - d_deg],
                        [cursor_x, cursor_y - d_deg],
                        [cursor_x, cursor_y],
                    ]],
                },
                "properties": {
                    "building_type": module_type,
                    "label": f"{mod['label']} {i + 1}" if count > 1 else mod["label"],
                    "color": mod["color"],
                    "height": mod["height_m"],
                    "width_m": mod["width_m"],
                    "depth_m": mod["depth_m"],
                    "index": i,
                },
            }
            placed.append(bld)
            cursor_x += w_deg + 0.00015  # ~15m gap between buildings
            row_height = max(row_height, mod["depth_m"])
        return placed

    # Place in priority order
    buildings.extend(place("substation", n_substations))
    buildings.extend(place("power_building", n_power))
    buildings.extend(place("server_hall", halls_needed))
    buildings.extend(place("cooling_plant", n_cooling))
    if n_generators > 0:
        buildings.extend(place("generator_yard", min(n_generators, 4)))
    if n_water > 0:
        buildings.extend(place("water_tank", 1))
    buildings.extend(place("office", 1))
    buildings.extend(place("security_gatehouse", 1))
    buildings.extend(place("parking", 1))

    # Calculate costs
    capex_per_mw = {1: 6_000_000, 2: 8_000_000, 3: 10_000_000, 4: 14_000_000}[tier]
    total_capex = round(it_load_mw * capex_per_mw)
    opex_per_mw_yr = {1: 400_000, 2: 500_000, 3: 600_000, 4: 800_000}[tier]
    total_opex = round(it_load_mw * opex_per_mw_yr)

    # Calculate PUE breakdown
    pue_breakdown = {
        "it_load_mw": round(it_load_mw, 1),
        "cooling_mw": round(cooling_mw, 1),
        "ups_losses_mw": round(it_load_mw * 0.04, 2),  # ~4% UPS losses
        "distribution_mw": round(it_load_mw * 0.02, 2),  # ~2% distribution
        "lighting_misc_mw": round(it_load_mw * 0.01, 2),
        "total_facility_mw": round(total_power_mw, 1),
        "pue": round(pue_target, 2),
    }

    # Rack calculations
    kw_per_rack = 8  # average rack density
    total_racks = math.ceil(it_load_mw * 1000 / kw_per_rack)
    racks_per_hall = math.ceil(total_racks / halls_needed)

    return {
        "layout": {
            "type": "FeatureCollection",
            "features": buildings,
        },
        "summary": {
            "it_load_mw": it_load_mw,
            "total_power_mw": round(total_power_mw, 1),
            "tier": tier,
            "tier_description": tier_spec["description"],
            "uptime_pct": tier_spec["uptime"],
            "redundancy": tier_spec["redundancy"],
            "cooling_type": cooling_type,
            "pue": round(pue_target, 2),
            "server_halls": halls_needed,
            "total_racks": total_racks,
            "racks_per_hall": racks_per_hall,
            "kw_per_rack": kw_per_rack,
            "building_count": len(buildings),
        },
        "site": {
            "area_m2": round(site_area_m2),
            "area_ha": round(site_area_ha, 2),
            "area_acres": round(site_area_ha * 2.471, 1),
            "center_lat": center_lat,
            "center_lon": center_lon,
            "width_m": round(site_width_m),
            "depth_m": round(site_depth_m),
        },
        "power": pue_breakdown,
        "costs": {
            "capex_total_gbp": total_capex,
            "capex_per_mw_gbp": capex_per_mw,
            "opex_annual_gbp": total_opex,
            "opex_per_mw_yr_gbp": opex_per_mw_yr,
        },
        "buildings": {
            bt: {
                "count": sum(1 for b in buildings if b["properties"]["building_type"] == bt),
                "total_area_m2": sum(
                    DC_MODULES[bt]["width_m"] * DC_MODULES[bt]["depth_m"]
                    for b in buildings
                    if b["properties"]["building_type"] == bt
                ),
            }
            for bt in set(b["properties"]["building_type"] for b in buildings)
        },
    }
