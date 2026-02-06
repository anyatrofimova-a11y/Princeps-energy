"""
Solar Elements Inventory

Adapted from Amr-Namora/Solar-System-Repositories-management.
Provides a solar component catalogue, site BOM (bill of materials) generation,
and inventory tracking across repositories/workshops for map overlay display.

Each solar site gets a generated BOM based on its capacity, area, and conditions.
Components can be visualised as overlays showing what's needed vs available.
"""

from __future__ import annotations

import math
import random

# ============================================================================
# Solar Component Catalogue
# ============================================================================

# Component specs: {id, name, category, unit, unit_cost_gbp, weight_kg, area_m2 (per unit if applicable)}
SOLAR_CATALOGUE = [
    # Panels
    {"id": "PNL-MONO-400", "name": "Monocrystalline 400W Panel", "category": "panel",
     "watts": 400, "unit": "unit", "unit_cost_gbp": 145, "weight_kg": 21.5,
     "area_m2": 1.92, "efficiency": 0.207, "brand": "JA Solar"},
    {"id": "PNL-MONO-550", "name": "Monocrystalline 550W Panel", "category": "panel",
     "watts": 550, "unit": "unit", "unit_cost_gbp": 185, "weight_kg": 28.6,
     "area_m2": 2.58, "efficiency": 0.213, "brand": "Trina Solar"},
    {"id": "PNL-BIFACIAL-600", "name": "Bifacial 600W Panel", "category": "panel",
     "watts": 600, "unit": "unit", "unit_cost_gbp": 220, "weight_kg": 32.0,
     "area_m2": 2.80, "efficiency": 0.221, "brand": "LONGi"},
    {"id": "PNL-THIN-320", "name": "Thin-Film 320W Panel", "category": "panel",
     "watts": 320, "unit": "unit", "unit_cost_gbp": 95, "weight_kg": 18.0,
     "area_m2": 2.47, "efficiency": 0.130, "brand": "First Solar"},

    # Inverters
    {"id": "INV-STRING-50", "name": "String Inverter 50kW", "category": "inverter",
     "watts": 50000, "unit": "unit", "unit_cost_gbp": 3200, "weight_kg": 52,
     "efficiency": 0.985, "type": "string"},
    {"id": "INV-STRING-100", "name": "String Inverter 100kW", "category": "inverter",
     "watts": 100000, "unit": "unit", "unit_cost_gbp": 5800, "weight_kg": 78,
     "efficiency": 0.987, "type": "string"},
    {"id": "INV-CENTRAL-500", "name": "Central Inverter 500kW", "category": "inverter",
     "watts": 500000, "unit": "unit", "unit_cost_gbp": 22000, "weight_kg": 1200,
     "efficiency": 0.989, "type": "central"},
    {"id": "INV-CENTRAL-2500", "name": "Central Inverter 2.5MW", "category": "inverter",
     "watts": 2500000, "unit": "unit", "unit_cost_gbp": 85000, "weight_kg": 3800,
     "efficiency": 0.990, "type": "central"},
    {"id": "INV-MICRO-400", "name": "Micro Inverter 400W", "category": "inverter",
     "watts": 400, "unit": "unit", "unit_cost_gbp": 120, "weight_kg": 1.2,
     "efficiency": 0.970, "type": "micro"},

    # Battery Storage
    {"id": "BAT-LFP-100", "name": "LFP Battery 100kWh", "category": "battery",
     "kwh": 100, "unit": "unit", "unit_cost_gbp": 28000, "weight_kg": 1200,
     "cycles": 6000, "chemistry": "LiFePO4"},
    {"id": "BAT-LFP-500", "name": "LFP Battery 500kWh Container", "category": "battery",
     "kwh": 500, "unit": "unit", "unit_cost_gbp": 120000, "weight_kg": 5500,
     "cycles": 6000, "chemistry": "LiFePO4"},
    {"id": "BAT-NMC-50", "name": "NMC Battery 50kWh", "category": "battery",
     "kwh": 50, "unit": "unit", "unit_cost_gbp": 16000, "weight_kg": 450,
     "cycles": 4000, "chemistry": "NMC"},

    # Mounting & Structure
    {"id": "MNT-GROUND-FX", "name": "Ground-Mount Fixed Racking (per kW)", "category": "mounting",
     "unit": "kW", "unit_cost_gbp": 85, "weight_kg": 18},
    {"id": "MNT-GROUND-TRK", "name": "Single-Axis Tracker (per kW)", "category": "mounting",
     "unit": "kW", "unit_cost_gbp": 140, "weight_kg": 28},
    {"id": "MNT-ROOF-FLAT", "name": "Flat Roof Ballasted Mount (per kW)", "category": "mounting",
     "unit": "kW", "unit_cost_gbp": 65, "weight_kg": 22},
    {"id": "MNT-ROOF-PITCH", "name": "Pitched Roof Rail Mount (per kW)", "category": "mounting",
     "unit": "kW", "unit_cost_gbp": 55, "weight_kg": 8},

    # Cables & Wiring
    {"id": "CBL-DC-6MM", "name": "DC Solar Cable 6mm² (per m)", "category": "cable",
     "unit": "m", "unit_cost_gbp": 1.80, "weight_kg": 0.09},
    {"id": "CBL-DC-10MM", "name": "DC Solar Cable 10mm² (per m)", "category": "cable",
     "unit": "m", "unit_cost_gbp": 2.90, "weight_kg": 0.15},
    {"id": "CBL-AC-3PH", "name": "AC 3-Phase Cable 25mm² (per m)", "category": "cable",
     "unit": "m", "unit_cost_gbp": 8.50, "weight_kg": 0.65},
    {"id": "CBL-AC-HV", "name": "HV Cable 11kV (per m)", "category": "cable",
     "unit": "m", "unit_cost_gbp": 35.00, "weight_kg": 3.2},

    # Transformers
    {"id": "TRF-PAD-500", "name": "Pad-Mount Transformer 500kVA", "category": "transformer",
     "unit": "unit", "unit_cost_gbp": 18000, "weight_kg": 1500, "kva": 500},
    {"id": "TRF-PAD-1000", "name": "Pad-Mount Transformer 1000kVA", "category": "transformer",
     "unit": "unit", "unit_cost_gbp": 28000, "weight_kg": 2800, "kva": 1000},
    {"id": "TRF-PAD-2500", "name": "Pad-Mount Transformer 2500kVA", "category": "transformer",
     "unit": "unit", "unit_cost_gbp": 52000, "weight_kg": 5200, "kva": 2500},

    # Monitoring & Controls
    {"id": "MON-WEATHER", "name": "Weather Station (pyranometer + anemometer)", "category": "monitoring",
     "unit": "unit", "unit_cost_gbp": 2800, "weight_kg": 8},
    {"id": "MON-METER", "name": "Smart Revenue Meter", "category": "monitoring",
     "unit": "unit", "unit_cost_gbp": 1500, "weight_kg": 3},
    {"id": "MON-SCADA", "name": "SCADA Controller + Gateway", "category": "monitoring",
     "unit": "unit", "unit_cost_gbp": 6500, "weight_kg": 12},
    {"id": "MON-CCTV", "name": "CCTV Security Camera (per unit)", "category": "monitoring",
     "unit": "unit", "unit_cost_gbp": 350, "weight_kg": 2},

    # Balance of System
    {"id": "BOS-COMBINER", "name": "DC Combiner Box (16-string)", "category": "bos",
     "unit": "unit", "unit_cost_gbp": 450, "weight_kg": 15, "strings": 16},
    {"id": "BOS-FUSE", "name": "DC Fuse 15A (per string)", "category": "bos",
     "unit": "unit", "unit_cost_gbp": 8, "weight_kg": 0.05},
    {"id": "BOS-SPD", "name": "Surge Protection Device", "category": "bos",
     "unit": "unit", "unit_cost_gbp": 85, "weight_kg": 0.4},
    {"id": "BOS-EARTHING", "name": "Earthing Kit (per MW)", "category": "bos",
     "unit": "MW", "unit_cost_gbp": 3500, "weight_kg": 120},
    {"id": "BOS-FENCE", "name": "Security Fencing (per m)", "category": "fencing",
     "unit": "m", "unit_cost_gbp": 28, "weight_kg": 5.5},
]

# Simulated regional repositories / warehouses
REPOSITORIES = [
    {"id": "REP-SOUTH", "name": "Southern England Depot", "location": "Southampton",
     "lat": 50.9097, "lon": -1.4044, "is_working": True},
    {"id": "REP-MIDLANDS", "name": "Midlands Distribution Centre", "location": "Birmingham",
     "lat": 52.4862, "lon": -1.8904, "is_working": True},
    {"id": "REP-NORTH", "name": "Northern Hub Warehouse", "location": "Leeds",
     "lat": 53.8008, "lon": -1.5491, "is_working": True},
    {"id": "REP-EAST", "name": "Eastern Region Store", "location": "Norwich",
     "lat": 52.6309, "lon": 1.2974, "is_working": True},
    {"id": "REP-WALES", "name": "Wales & SW Depot", "location": "Cardiff",
     "lat": 51.4816, "lon": -3.1791, "is_working": True},
    {"id": "REP-SCOTLAND", "name": "Scotland Distribution", "location": "Glasgow",
     "lat": 55.8642, "lon": -4.2518, "is_working": True},
]


# ============================================================================
# Database setup
# ============================================================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS solar_inventory (
    id SERIAL PRIMARY KEY,
    component_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'available',
    repository_id TEXT,
    parcel_id UUID,
    unit_cost_gbp REAL,
    total_cost_gbp REAL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_solar_inv_parcel ON solar_inventory(parcel_id);
CREATE INDEX IF NOT EXISTS idx_solar_inv_category ON solar_inventory(category);
CREATE INDEX IF NOT EXISTS idx_solar_inv_repo ON solar_inventory(repository_id);
"""


async def setup_inventory_table(conn) -> None:
    """Create solar_inventory table if it doesn't exist."""
    await conn.execute(CREATE_TABLE_SQL)


# ============================================================================
# BOM Generation — auto-size components for a site
# ============================================================================

def generate_site_bom(
    capacity_kw: float,
    area_m2: float | None = None,
    mount_type: str = "ground_fixed",
    include_battery: bool = False,
    battery_hours: float = 2.0,
) -> dict:
    """
    Generate a Bill of Materials for a solar site.

    Args:
        capacity_kw: Site capacity in kW
        area_m2: Available area (if None, estimated from capacity)
        mount_type: ground_fixed, ground_tracker, roof_flat, roof_pitched
        include_battery: Whether to include battery storage
        battery_hours: Hours of storage at rated capacity

    Returns:
        Dict with categorised components, quantities, costs, and totals.
    """
    capacity_mw = capacity_kw / 1000

    # Select panel type based on capacity
    if capacity_kw >= 1000:
        panel = next(c for c in SOLAR_CATALOGUE if c["id"] == "PNL-BIFACIAL-600")
    elif capacity_kw >= 200:
        panel = next(c for c in SOLAR_CATALOGUE if c["id"] == "PNL-MONO-550")
    else:
        panel = next(c for c in SOLAR_CATALOGUE if c["id"] == "PNL-MONO-400")

    panel_watts = panel["watts"]
    num_panels = math.ceil(capacity_kw * 1000 / panel_watts)

    # Estimate area if not provided
    if area_m2 is None:
        # Ground-mount needs ~2x panel area for spacing
        area_m2 = num_panels * panel["area_m2"] * 2.2

    # Select inverter
    if capacity_kw >= 2500:
        inv = next(c for c in SOLAR_CATALOGUE if c["id"] == "INV-CENTRAL-2500")
    elif capacity_kw >= 500:
        inv = next(c for c in SOLAR_CATALOGUE if c["id"] == "INV-CENTRAL-500")
    elif capacity_kw >= 100:
        inv = next(c for c in SOLAR_CATALOGUE if c["id"] == "INV-STRING-100")
    elif capacity_kw >= 30:
        inv = next(c for c in SOLAR_CATALOGUE if c["id"] == "INV-STRING-50")
    else:
        inv = next(c for c in SOLAR_CATALOGUE if c["id"] == "INV-MICRO-400")

    if inv["type"] == "micro":
        num_inverters = num_panels
    else:
        num_inverters = math.ceil(capacity_kw * 1000 / inv["watts"])

    # Mounting
    mount_map = {
        "ground_fixed": "MNT-GROUND-FX",
        "ground_tracker": "MNT-GROUND-TRK",
        "roof_flat": "MNT-ROOF-FLAT",
        "roof_pitched": "MNT-ROOF-PITCH",
    }
    mount_id = mount_map.get(mount_type, "MNT-GROUND-FX")
    mount = next(c for c in SOLAR_CATALOGUE if c["id"] == mount_id)

    # Cables: estimate DC cable = 15m per panel, AC cable = 50m per inverter + HV run
    dc_cable_m = num_panels * 15
    ac_cable_m = num_inverters * 50 + 100  # plus trunk run
    hv_cable_m = max(50, int(capacity_mw * 200))  # HV to grid connection

    dc_cable = next(c for c in SOLAR_CATALOGUE if c["id"] == ("CBL-DC-10MM" if capacity_kw >= 200 else "CBL-DC-6MM"))
    ac_cable = next(c for c in SOLAR_CATALOGUE if c["id"] == "CBL-AC-3PH")
    hv_cable = next(c for c in SOLAR_CATALOGUE if c["id"] == "CBL-AC-HV")

    # Transformer
    kva_needed = capacity_kw * 1.1  # 10% oversize
    if kva_needed >= 2000:
        trf = next(c for c in SOLAR_CATALOGUE if c["id"] == "TRF-PAD-2500")
    elif kva_needed >= 800:
        trf = next(c for c in SOLAR_CATALOGUE if c["id"] == "TRF-PAD-1000")
    else:
        trf = next(c for c in SOLAR_CATALOGUE if c["id"] == "TRF-PAD-500")
    num_transformers = math.ceil(kva_needed / trf["kva"])

    # Combiners & fuses
    strings_per_panel = 1  # simplified
    panels_per_string = 20 if panel_watts >= 500 else 15
    num_strings = math.ceil(num_panels / panels_per_string)
    combiner = next(c for c in SOLAR_CATALOGUE if c["id"] == "BOS-COMBINER")
    num_combiners = math.ceil(num_strings / combiner["strings"])
    num_fuses = num_strings

    # Monitoring
    weather = next(c for c in SOLAR_CATALOGUE if c["id"] == "MON-WEATHER")
    meter = next(c for c in SOLAR_CATALOGUE if c["id"] == "MON-METER")
    scada = next(c for c in SOLAR_CATALOGUE if c["id"] == "MON-SCADA")
    cctv = next(c for c in SOLAR_CATALOGUE if c["id"] == "MON-CCTV")
    num_cctv = max(2, int(math.sqrt(area_m2) / 50))

    # Earthing & fencing
    earthing = next(c for c in SOLAR_CATALOGUE if c["id"] == "BOS-EARTHING")
    spd = next(c for c in SOLAR_CATALOGUE if c["id"] == "BOS-SPD")
    fence = next(c for c in SOLAR_CATALOGUE if c["id"] == "BOS-FENCE")
    perimeter_m = 4 * math.sqrt(area_m2)  # approximate square perimeter

    # Build BOM lines
    bom = []

    def add(component, qty, note=""):
        cost = round(component["unit_cost_gbp"] * qty, 2)
        weight = round(component.get("weight_kg", 0) * qty, 1)
        bom.append({
            "component_id": component["id"],
            "name": component["name"],
            "category": component["category"],
            "quantity": qty,
            "unit": component["unit"],
            "unit_cost_gbp": component["unit_cost_gbp"],
            "total_cost_gbp": cost,
            "total_weight_kg": weight,
            "note": note,
        })

    add(panel, num_panels, f"{num_panels} x {panel_watts}W = {capacity_kw:.0f} kW")
    add(inv, num_inverters, f"{inv['type']} inverter")
    add(mount, int(capacity_kw), f"{mount_type.replace('_', ' ')} for {capacity_kw:.0f} kW")
    add(dc_cable, dc_cable_m, f"~{dc_cable_m}m DC wiring")
    add(ac_cable, ac_cable_m, f"~{ac_cable_m}m AC distribution")
    if capacity_kw >= 100:
        add(hv_cable, hv_cable_m, f"~{hv_cable_m}m HV to grid")
    add(trf, num_transformers)
    add(combiner, num_combiners, f"{num_strings} strings")
    fuse_comp = next(c for c in SOLAR_CATALOGUE if c["id"] == "BOS-FUSE")
    add(fuse_comp, num_fuses)
    add(spd, max(1, num_inverters))
    add(earthing, max(1, round(capacity_mw, 1)))
    add(weather, 1)
    add(meter, 1)
    if capacity_kw >= 100:
        add(scada, 1)
    add(cctv, num_cctv)
    add(fence, int(perimeter_m))

    # Battery (optional)
    if include_battery:
        storage_kwh = capacity_kw * battery_hours
        if storage_kwh >= 400:
            bat = next(c for c in SOLAR_CATALOGUE if c["id"] == "BAT-LFP-500")
            num_bat = math.ceil(storage_kwh / bat["kwh"])
        elif storage_kwh >= 80:
            bat = next(c for c in SOLAR_CATALOGUE if c["id"] == "BAT-LFP-100")
            num_bat = math.ceil(storage_kwh / bat["kwh"])
        else:
            bat = next(c for c in SOLAR_CATALOGUE if c["id"] == "BAT-NMC-50")
            num_bat = math.ceil(storage_kwh / bat["kwh"])
        add(bat, num_bat, f"{storage_kwh:.0f} kWh ({battery_hours}h)")

    # Totals
    total_cost = sum(item["total_cost_gbp"] for item in bom)
    total_weight = sum(item["total_weight_kg"] for item in bom)
    cost_per_kw = total_cost / capacity_kw if capacity_kw > 0 else 0

    # Group by category
    categories = {}
    for item in bom:
        cat = item["category"]
        if cat not in categories:
            categories[cat] = {"items": [], "subtotal_gbp": 0, "subtotal_weight_kg": 0}
        categories[cat]["items"].append(item)
        categories[cat]["subtotal_gbp"] += item["total_cost_gbp"]
        categories[cat]["subtotal_weight_kg"] += item["total_weight_kg"]

    # Round subtotals
    for cat in categories.values():
        cat["subtotal_gbp"] = round(cat["subtotal_gbp"], 2)
        cat["subtotal_weight_kg"] = round(cat["subtotal_weight_kg"], 1)

    return {
        "capacity_kw": capacity_kw,
        "area_m2": round(area_m2, 0),
        "mount_type": mount_type,
        "include_battery": include_battery,
        "panel_type": panel["name"],
        "num_panels": num_panels,
        "inverter_type": inv["name"],
        "num_inverters": num_inverters,
        "num_strings": num_strings,
        "bom": bom,
        "categories": categories,
        "totals": {
            "total_cost_gbp": round(total_cost, 2),
            "total_weight_kg": round(total_weight, 1),
            "cost_per_kw_gbp": round(cost_per_kw, 2),
            "component_count": len(bom),
        },
    }


# ============================================================================
# Inventory stock levels (simulated from regional repos)
# ============================================================================

def repository_stock(parcel_lat: float = 52.0, parcel_lon: float = -1.5) -> list[dict]:
    """
    Simulated stock availability across UK regional repositories.
    Nearest repository is prioritised. Stock levels are deterministic
    based on lat/lon hash for reproducibility.
    """
    rng = random.Random(int(parcel_lat * 1000) + int(parcel_lon * 1000))

    # Sort repos by distance to parcel
    def dist(repo):
        return math.sqrt((repo["lat"] - parcel_lat) ** 2 + (repo["lon"] - parcel_lon) ** 2)

    sorted_repos = sorted(REPOSITORIES, key=dist)

    result = []
    for repo in sorted_repos:
        d = dist(repo)
        stock = []
        for comp in SOLAR_CATALOGUE:
            # Higher stock at larger depots, less at distant ones
            base = rng.randint(5, 200)
            if comp["category"] in ("panel", "cable", "bos"):
                base *= 5  # bulk items
            availability = max(0, int(base * (1 - d * 0.05)))
            status = "available" if availability > 0 else "out_of_stock"
            stock.append({
                "component_id": comp["id"],
                "name": comp["name"],
                "category": comp["category"],
                "quantity_available": availability,
                "status": status,
                "unit_cost_gbp": comp["unit_cost_gbp"],
            })
        result.append({
            "repository_id": repo["id"],
            "name": repo["name"],
            "location": repo["location"],
            "lat": repo["lat"],
            "lon": repo["lon"],
            "distance_km": round(d * 111, 1),  # rough degree->km
            "stock": stock,
            "total_items_available": sum(s["quantity_available"] for s in stock),
        })

    return result


def check_bom_availability(bom: list[dict], stock: list[dict]) -> dict:
    """
    Check BOM against available stock across all repositories.
    Returns availability status per component and fulfilment summary.
    """
    availability = []
    fully_available = 0
    partially_available = 0
    unavailable = 0

    for item in bom:
        needed = item["quantity"]
        total_stock = 0
        sources = []

        for repo in stock:
            for s in repo["stock"]:
                if s["component_id"] == item["component_id"] and s["quantity_available"] > 0:
                    total_stock += s["quantity_available"]
                    sources.append({
                        "repository": repo["name"],
                        "available": s["quantity_available"],
                        "distance_km": repo["distance_km"],
                    })

        if total_stock >= needed:
            status = "available"
            fully_available += 1
        elif total_stock > 0:
            status = "partial"
            partially_available += 1
        else:
            status = "unavailable"
            unavailable += 1

        availability.append({
            "component_id": item["component_id"],
            "name": item["name"],
            "category": item["category"],
            "needed": needed,
            "total_available": total_stock,
            "deficit": max(0, needed - total_stock),
            "status": status,
            "sources": sources[:3],  # top 3 nearest sources
        })

    return {
        "components": availability,
        "summary": {
            "total_items": len(bom),
            "fully_available": fully_available,
            "partially_available": partially_available,
            "unavailable": unavailable,
            "fulfilment_pct": round(fully_available / len(bom) * 100, 1) if bom else 0,
        },
    }


def catalogue_summary() -> dict:
    """Return the full component catalogue grouped by category."""
    categories = {}
    for comp in SOLAR_CATALOGUE:
        cat = comp["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(comp)
    return {
        "total_components": len(SOLAR_CATALOGUE),
        "categories": categories,
        "repositories": REPOSITORIES,
    }
