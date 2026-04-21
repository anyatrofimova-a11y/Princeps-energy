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

# Component specs: real product data, UK delivered prices (ex-VAT), 2025-26 market
SOLAR_CATALOGUE = [
    # ── Panels ──
    # JA Solar DeepBlue 4.0 Pro JAM54D40-420/LB — 108-cell half-cut TOPCon
    {"id": "PNL-MONO-400", "name": "JA Solar DeepBlue 4.0 Pro 420W", "category": "panel",
     "watts": 420, "unit": "unit", "unit_cost_gbp": 82, "weight_kg": 21.5,
     "length_m": 1.722, "width_m": 1.134, "area_m2": 1.95, "efficiency": 0.215,
     "brand": "JA Solar", "model": "JAM54D40-420/LB", "voc": 37.98, "isc": 14.03,
     "vmp": 31.77, "imp": 13.22, "temp_coeff_pmax": -0.0029},
    # Trina Vertex S+ TSM-NEG9R.28 — 144-cell TOPCon
    {"id": "PNL-MONO-550", "name": "Trina Vertex S+ 580W", "category": "panel",
     "watts": 580, "unit": "unit", "unit_cost_gbp": 112, "weight_kg": 27.4,
     "length_m": 2.278, "width_m": 1.134, "area_m2": 2.58, "efficiency": 0.225,
     "brand": "Trina Solar", "model": "TSM-NEG9R.28", "voc": 46.50, "isc": 16.22,
     "vmp": 39.20, "imp": 14.80, "temp_coeff_pmax": -0.0029},
    # LONGi Hi-MO X6 LR5-72HBD — bifacial TOPCon, 144 half-cell
    {"id": "PNL-BIFACIAL-600", "name": "LONGi Hi-MO X6 600W Bifacial", "category": "panel",
     "watts": 600, "unit": "unit", "unit_cost_gbp": 128, "weight_kg": 30.8,
     "length_m": 2.278, "width_m": 1.134, "area_m2": 2.58, "efficiency": 0.233,
     "brand": "LONGi", "model": "LR5-72HBD-600M", "voc": 46.30, "isc": 16.80,
     "vmp": 39.40, "imp": 15.23, "temp_coeff_pmax": -0.0029, "bifacial_gain": 0.10},
    # First Solar Series 7 — CdTe thin-film, large format
    {"id": "PNL-THIN-320", "name": "First Solar Series 7 545W", "category": "panel",
     "watts": 545, "unit": "unit", "unit_cost_gbp": 135, "weight_kg": 35.4,
     "length_m": 2.509, "width_m": 1.245, "area_m2": 3.12, "efficiency": 0.175,
     "brand": "First Solar", "model": "FS-7545", "voc": 230.4, "isc": 2.93,
     "vmp": 195.5, "imp": 2.79, "temp_coeff_pmax": -0.0028},

    # ── Inverters ──
    # Huawei SUN2000-50KTL-M3 — 3-phase string, 6 MPPT
    {"id": "INV-STRING-50", "name": "Huawei SUN2000-50KTL-M3", "category": "inverter",
     "watts": 50000, "unit": "unit", "unit_cost_gbp": 2450, "weight_kg": 46,
     "efficiency": 0.987, "type": "string", "brand": "Huawei",
     "mppt": 6, "max_input_v": 1100, "dimensions": "670x430x225mm", "ip_rating": "IP66"},
    # Huawei SUN2000-100KTL-M2 — 3-phase string, 10 MPPT
    {"id": "INV-STRING-100", "name": "Huawei SUN2000-100KTL-M2", "category": "inverter",
     "watts": 100000, "unit": "unit", "unit_cost_gbp": 4200, "weight_kg": 72,
     "efficiency": 0.989, "type": "string", "brand": "Huawei",
     "mppt": 10, "max_input_v": 1100, "dimensions": "1035x600x300mm", "ip_rating": "IP66"},
    # SMA Sunny Central UP 500 — utility-scale central
    {"id": "INV-CENTRAL-500", "name": "SMA Sunny Central UP 500", "category": "inverter",
     "watts": 500000, "unit": "unit", "unit_cost_gbp": 15500, "weight_kg": 780,
     "efficiency": 0.987, "type": "central", "brand": "SMA",
     "max_input_v": 1500, "dimensions": "2262x2440x956mm", "ip_rating": "IP54"},
    # Sungrow SG3150U-MV — 3.15MW utility-scale string inverter
    {"id": "INV-CENTRAL-2500", "name": "Sungrow SG3150U-MV 3.15MW", "category": "inverter",
     "watts": 3150000, "unit": "unit", "unit_cost_gbp": 54000, "weight_kg": 3100,
     "efficiency": 0.990, "type": "central", "brand": "Sungrow",
     "max_input_v": 1500, "dimensions": "2995x2540x1560mm", "ip_rating": "IP55"},
    # Enphase IQ8AC Micro Inverter — 366W AC
    {"id": "INV-MICRO-400", "name": "Enphase IQ8AC-72-M-US", "category": "inverter",
     "watts": 366, "unit": "unit", "unit_cost_gbp": 135, "weight_kg": 1.08,
     "efficiency": 0.975, "type": "micro", "brand": "Enphase",
     "max_input_v": 60, "dimensions": "212x175x30mm", "ip_rating": "IP67"},

    # ── Battery Storage ──
    # BYD Battery-Box Premium HVS/HVM — modular LFP, wall/floor-mount
    {"id": "BAT-LFP-100", "name": "BYD HVM 102.4kWh System", "category": "battery",
     "kwh": 102.4, "unit": "unit", "unit_cost_gbp": 15400, "weight_kg": 1094,
     "cycles": 6000, "chemistry": "LiFePO4", "brand": "BYD",
     "voltage": "307.2V", "max_charge_kw": 50, "dimensions": "8 towers, 585x298x1520mm each"},
    # CATL EnerC containerised BESS — 20ft container, LFP
    {"id": "BAT-LFP-500", "name": "CATL EnerC 500kWh Container", "category": "battery",
     "kwh": 500, "unit": "unit", "unit_cost_gbp": 68000, "weight_kg": 5200,
     "cycles": 8000, "chemistry": "LiFePO4", "brand": "CATL",
     "voltage": "1024V", "max_charge_kw": 250, "dimensions": "6058x2438x2896mm (20ft ISO)"},
    # Pylontech Force H2 — stackable LFP, residential/C&I
    {"id": "BAT-NMC-50", "name": "Pylontech Force H2 48.0kWh", "category": "battery",
     "kwh": 48, "unit": "unit", "unit_cost_gbp": 8400, "weight_kg": 432,
     "cycles": 6000, "chemistry": "LiFePO4", "brand": "Pylontech",
     "voltage": "192V", "max_charge_kw": 25, "dimensions": "8 modules, 442x420x132mm each"},

    # ── Mounting & Structure ──
    # Schletter PvMax — galvanised steel ground-mount, portrait orientation
    {"id": "MNT-GROUND-FX", "name": "Schletter PvMax Fixed Racking", "category": "mounting",
     "unit": "kW", "unit_cost_gbp": 52, "weight_kg": 16, "brand": "Schletter",
     "tilt_range": "15-30 deg", "wind_load": "up to 160 km/h", "material": "Hot-dip galvanised steel"},
    # Nextracker NX Horizon — single-axis tracker, 1P config
    {"id": "MNT-GROUND-TRK", "name": "Nextracker NX Horizon Tracker", "category": "mounting",
     "unit": "kW", "unit_cost_gbp": 98, "weight_kg": 24, "brand": "Nextracker",
     "tracking_range": "+/- 60 deg", "wind_load": "stow at 120 km/h", "material": "Galvanised steel"},
    # K2 Systems D-Dome — ballasted flat-roof
    {"id": "MNT-ROOF-FLAT", "name": "K2 Systems D-Dome Flat Roof", "category": "mounting",
     "unit": "kW", "unit_cost_gbp": 44, "weight_kg": 20, "brand": "K2 Systems",
     "tilt_range": "10-15 deg", "ballast_kg_per_kw": 12, "material": "Aluminium + concrete ballast"},
    # Renusol VS+ — pitched roof rail system
    {"id": "MNT-ROOF-PITCH", "name": "Renusol VS+ Pitched Roof Rail", "category": "mounting",
     "unit": "kW", "unit_cost_gbp": 38, "weight_kg": 7.5, "brand": "Renusol",
     "roof_types": "tile, slate, metal", "material": "Anodised aluminium"},

    # ── Cables & Wiring ──
    # Lapp Solar H1Z2Z2-K — TUV-certified DC solar cable
    {"id": "CBL-DC-6MM", "name": "Lapp H1Z2Z2-K DC 6mm²", "category": "cable",
     "unit": "m", "unit_cost_gbp": 1.65, "weight_kg": 0.085, "brand": "Lapp",
     "voltage_rating": "1.5kV DC", "current_rating": "70A", "material": "Tinned copper, XLPO insulation"},
    {"id": "CBL-DC-10MM", "name": "Lapp H1Z2Z2-K DC 10mm²", "category": "cable",
     "unit": "m", "unit_cost_gbp": 2.70, "weight_kg": 0.14, "brand": "Lapp",
     "voltage_rating": "1.5kV DC", "current_rating": "98A", "material": "Tinned copper, XLPO insulation"},
    # Prysmian FP Plus — 3-phase AC armoured
    {"id": "CBL-AC-3PH", "name": "Prysmian 3C+E 25mm² SWA", "category": "cable",
     "unit": "m", "unit_cost_gbp": 7.80, "weight_kg": 0.58, "brand": "Prysmian",
     "voltage_rating": "0.6/1kV", "current_rating": "114A (buried)", "material": "Copper, XLPE, steel wire armour"},
    # Prysmian 11kV XLPE single-core
    {"id": "CBL-AC-HV", "name": "Prysmian 11kV 95mm² XLPE", "category": "cable",
     "unit": "m", "unit_cost_gbp": 32.00, "weight_kg": 2.9, "brand": "Prysmian",
     "voltage_rating": "11kV", "current_rating": "300A (buried)", "material": "Copper, XLPE, copper wire screen"},

    # ── Transformers ──
    # Wilson Power Solutions — UK-manufactured oil-immersed
    {"id": "TRF-PAD-500", "name": "Wilson 500kVA Pad-Mount", "category": "transformer",
     "unit": "unit", "unit_cost_gbp": 14500, "weight_kg": 1450, "kva": 500,
     "brand": "Wilson", "voltage": "11kV/400V", "cooling": "ONAN", "losses": "Eco-design Tier 2"},
    {"id": "TRF-PAD-1000", "name": "Wilson 1000kVA Pad-Mount", "category": "transformer",
     "unit": "unit", "unit_cost_gbp": 23000, "weight_kg": 2650, "kva": 1000,
     "brand": "Wilson", "voltage": "11kV/400V", "cooling": "ONAN", "losses": "Eco-design Tier 2"},
    {"id": "TRF-PAD-2500", "name": "Wilson 2500kVA Pad-Mount", "category": "transformer",
     "unit": "unit", "unit_cost_gbp": 45000, "weight_kg": 4800, "kva": 2500,
     "brand": "Wilson", "voltage": "33kV/400V", "cooling": "ONAN", "losses": "Eco-design Tier 2"},

    # ── Monitoring & Controls ──
    # Kipp & Zonen SMP10 + Vaisala WXT536
    {"id": "MON-WEATHER", "name": "Kipp & Zonen SMP10 + Vaisala WXT536", "category": "monitoring",
     "unit": "unit", "unit_cost_gbp": 3200, "weight_kg": 7.5, "brand": "Kipp & Zonen / Vaisala",
     "includes": "Secondary-standard pyranometer, multi-weather sensor, data logger, mast"},
    # Elster A1700 CT-rated meter (MID-approved)
    {"id": "MON-METER", "name": "Elster A1700 Revenue Meter", "category": "monitoring",
     "unit": "unit", "unit_cost_gbp": 1200, "weight_kg": 2.5, "brand": "Honeywell Elster",
     "accuracy": "Class 0.5S", "comms": "RS485, Modbus, optical"},
    # ABB Ability SCADA/EMS
    {"id": "MON-SCADA", "name": "ABB Ability SCADA Gateway", "category": "monitoring",
     "unit": "unit", "unit_cost_gbp": 5800, "weight_kg": 10, "brand": "ABB",
     "includes": "RTU, cellular modem, 12-month cloud license"},
    # Hikvision DS-2CD2047G2 — 4MP ColorVu IP67
    {"id": "MON-CCTV", "name": "Hikvision ColorVu 4MP IP Camera", "category": "monitoring",
     "unit": "unit", "unit_cost_gbp": 285, "weight_kg": 1.8, "brand": "Hikvision",
     "model": "DS-2CD2047G2", "resolution": "4MP", "ip_rating": "IP67"},

    # ── Balance of System ──
    {"id": "BOS-COMBINER", "name": "ABB CMB-16 DC Combiner Box", "category": "bos",
     "unit": "unit", "unit_cost_gbp": 380, "weight_kg": 14, "strings": 16,
     "brand": "ABB", "voltage_rating": "1500V DC"},
    {"id": "BOS-FUSE", "name": "Mersen HelioProtection 15A gPV Fuse", "category": "bos",
     "unit": "unit", "unit_cost_gbp": 6.50, "weight_kg": 0.04, "brand": "Mersen",
     "voltage_rating": "1500V DC", "breaking_capacity": "50kA"},
    {"id": "BOS-SPD", "name": "Dehn DEHNguard YPV SCI 1000 SPD", "category": "bos",
     "unit": "unit", "unit_cost_gbp": 78, "weight_kg": 0.35, "brand": "Dehn",
     "type": "Type 2 DC SPD", "max_voltage": "1000V DC"},
    {"id": "BOS-EARTHING", "name": "Earthing Kit (copper tape + rods)", "category": "bos",
     "unit": "MW", "unit_cost_gbp": 3200, "weight_kg": 110},
    {"id": "BOS-FENCE", "name": "Zaun Duo8 Mesh Security Fencing", "category": "fencing",
     "unit": "m", "unit_cost_gbp": 32, "weight_kg": 5.8, "brand": "Zaun",
     "height": "2.4m", "material": "Galvanised + polyester-coated steel mesh"},
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

    # Cross-check BOM roll-up against the UK 2026 all-in £/kWp benchmark.
    # Component catalogue tracks hardware only — dev, EPC, grid-side works
    # and contingency push all-in CapEx higher. Benchmark comes from
    # Solar Media Q4 2025 (see utils.solar_benchmarks).
    try:
        from utils import solar_benchmarks as _sb
        benchmark_kw = _sb.solar_capex_per_kw()
        benchmark_range = (
            _sb.solar_capex_per_kw("low"),
            _sb.solar_capex_per_kw("high"),
        )
        benchmark_citation = _sb.cite()
    except Exception:
        benchmark_kw = None
        benchmark_range = None
        benchmark_citation = None

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
        "benchmark": {
            "all_in_capex_gbp_per_kw_mid": benchmark_kw,
            "all_in_capex_gbp_per_kw_range": benchmark_range,
            "source": benchmark_citation,
            "note": "Hardware-only BOM; all-in benchmark includes dev, EPC, grid works.",
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
