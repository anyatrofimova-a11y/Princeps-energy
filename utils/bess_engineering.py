"""
utils/bess_engineering.py — Best-in-class BESS engineering designer.

Inputs a high-level brief (capacity_mw, duration_h, vendor preference, climate,
augmentation strategy, point of connection) and produces a complete engineering
package: container counts and placements with NFPA 855 / BS 8629 / IFC 1207
setbacks, PCS cascade, transformer ladder, MV ring topology, low-voltage
conductor schedule with IEC 60364 voltage-drop checks, single-line diagram,
augmentation schedule with cycle-life and round-trip-efficiency curves, full
bill of quantities, regional CapEx model, levelised cost of storage, and
parasitic thermal load.

Public API
----------
    design(brief: BessBrief) -> BessDesign

Everything else is private. Callers in ``utils.asset_layout_engine`` and
``app.routers.twin`` consume ``BessDesign`` and project it onto the existing
``LayoutResponse`` shape (placed_assets + cable_runs + fence + engineering).

Reference standards
-------------------
    IEC 62933-5-2          BESS safety / hazards
    NFPA 855 (2023)        Stationary energy storage installations
    BS 8629                UK BESS firefighting access (8 containers/row max)
    IFC 1207               International Fire Code battery storage
    IEC 60364-5-52         LV cable sizing & voltage drop
    IEC 60076              Power transformers
    ENA EREC G99 Issue 2   UK grid code (PoC compliance)
    ENA EREC P28/P29       UK voltage regulation envelopes
    BS 7671                UK wiring regulations
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Literal, Sequence

# ---------------------------------------------------------------------------
# Vendor catalogue — real product specs as of 2026
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BatteryVendor:
    """Container-level battery product."""
    id: str
    label: str
    chemistry: Literal["LFP", "NMC"]
    energy_kwh: float           # nameplate at BoL
    power_kw: float             # rated continuous
    length_m: float
    width_m: float
    height_m: float
    weight_t: float
    rte_bol: float              # round-trip efficiency, beginning of life (DC-DC, 0..1)
    rte_eol: float              # at end of design life
    cycle_life_to_80pct: int    # cycles to 80% SoH at 1C, 25 °C
    parasitic_kw: float         # HVAC + BMS draw at idle, per container
    capex_usd_per_kwh: float    # 2026 ex-works EU pricing
    fire_class: Literal["Class A", "Class B", "Class C"]


VENDORS: dict[str, BatteryVendor] = {
    v.id: v for v in [
        BatteryVendor(
            id="tesla.megapack_2xl",
            label="Tesla Megapack 2 XL",
            chemistry="LFP",
            energy_kwh=3916.0, power_kw=1927.0,
            length_m=8.99, width_m=1.66, height_m=2.89, weight_t=38.6,
            rte_bol=0.918, rte_eol=0.860,
            cycle_life_to_80pct=6000,
            parasitic_kw=4.2,
            capex_usd_per_kwh=298.0,
            fire_class="Class A",
        ),
        BatteryVendor(
            id="sungrow.power_titan_2",
            label="Sungrow PowerTitan 2.0 (5 MWh)",
            chemistry="LFP",
            energy_kwh=5016.0, power_kw=2500.0,
            length_m=6.06, width_m=2.44, height_m=2.90, weight_t=42.0,
            rte_bol=0.910, rte_eol=0.852,
            cycle_life_to_80pct=8000,
            parasitic_kw=5.5,
            capex_usd_per_kwh=265.0,
            fire_class="Class A",
        ),
        BatteryVendor(
            id="byd.cube_t28",
            label="BYD Cube Pro T28",
            chemistry="LFP",
            energy_kwh=2810.0, power_kw=1430.0,
            length_m=6.06, width_m=1.30, height_m=2.59, weight_t=24.5,
            rte_bol=0.905, rte_eol=0.844,
            cycle_life_to_80pct=8000,
            parasitic_kw=3.6,
            capex_usd_per_kwh=272.0,
            fire_class="Class A",
        ),
        BatteryVendor(
            id="catl.enerc_plus",
            label="CATL EnerC+ 6.25",
            chemistry="LFP",
            energy_kwh=6250.0, power_kw=3125.0,
            length_m=6.10, width_m=2.44, height_m=2.90, weight_t=43.0,
            rte_bol=0.916, rte_eol=0.857,
            cycle_life_to_80pct=10000,
            parasitic_kw=5.2,
            capex_usd_per_kwh=255.0,
            fire_class="Class A",
        ),
        BatteryVendor(
            id="wartsila.quantum_2",
            label="Wärtsilä Quantum2 (5.3 MWh)",
            chemistry="LFP",
            energy_kwh=5300.0, power_kw=2650.0,
            length_m=6.60, width_m=2.40, height_m=2.90, weight_t=44.0,
            rte_bol=0.908, rte_eol=0.848,
            cycle_life_to_80pct=7000,
            parasitic_kw=5.0,
            capex_usd_per_kwh=288.0,
            fire_class="Class A",
        ),
    ]
}


@dataclass(frozen=True)
class PcsProduct:
    """MV-coupled string inverter / PCS skid."""
    id: str
    label: str
    rating_kva: float
    rating_kw: float
    length_m: float
    width_m: float
    height_m: float
    efficiency: float           # AC-AC at rated power
    capex_usd_per_kw: float


PCS_CATALOGUE: dict[str, PcsProduct] = {
    p.id: p for p in [
        PcsProduct("sungrow.sc4400_uds", "Sungrow SC4400-UD-MV", 4400, 4400, 12.19, 2.44, 2.90, 0.989, 78.0),
        PcsProduct("power_electronics.fs3425k", "Power Electronics FS3425K", 4400, 4400, 12.19, 2.44, 2.90, 0.987, 80.0),
        PcsProduct("sungrow.sc2000ud", "Sungrow SC2000UD-MV", 2200, 2200, 6.10, 2.44, 2.75, 0.988, 82.0),
        PcsProduct("emerson.csk_1500", "Emerson CSK-1500", 1500, 1500, 4.50, 2.20, 2.60, 0.985, 86.0),
    ]
}


@dataclass(frozen=True)
class TransformerProduct:
    id: str
    label: str
    rating_mva: float
    primary_kv: float
    secondary_kv: float
    no_load_loss_kw: float      # core (iron) loss
    load_loss_kw: float         # copper loss at rated MVA
    length_m: float
    width_m: float
    height_m: float
    capex_usd_per_mva: float
    cooling: Literal["ONAN", "ONAF", "OFAF"]


TX_CATALOGUE: dict[str, TransformerProduct] = {
    t.id: t for t in [
        # LV-MV pad-mount step-up next to PCS
        TransformerProduct("hitachi.padmount_4400", "LV-MV pad-mount 4.4 MVA 0.69/33 kV",
                           4.4, 33.0, 0.69, 4.5, 38.0, 5.50, 2.20, 2.40, 22000, "ONAN"),
        # Main step-up MV-HV
        TransformerProduct("hitachi.main_60mva", "Main step-up 60 MVA 33/132 kV ONAF",
                           60.0, 132.0, 33.0, 38.0, 270.0, 7.50, 4.50, 5.20, 14500, "ONAF"),
        TransformerProduct("hitachi.main_120mva", "Main step-up 120 MVA 33/132 kV OFAF",
                           120.0, 132.0, 33.0, 62.0, 460.0, 9.00, 5.20, 6.10, 12200, "OFAF"),
        TransformerProduct("hitachi.aux_500", "Aux 500 kVA 33/0.4 kV",
                           0.5, 33.0, 0.4, 1.1, 6.5, 2.20, 1.60, 2.00, 38000, "ONAN"),
    ]
}


# ---------------------------------------------------------------------------
# Brief + design dataclasses
# ---------------------------------------------------------------------------
@dataclass
class BessBrief:
    """User-facing inputs to the designer."""
    capacity_mw: float = 50.0
    duration_h: float = 2.0
    vendor_id: str = "tesla.megapack_2xl"
    pcs_id: str = "sungrow.sc4400_uds"
    main_tx_id: str = "hitachi.main_60mva"
    grid_voltage_kv: float = 132.0
    augmentation: Literal["none", "annual", "biennial", "year_5_only"] = "annual"
    project_life_y: int = 20
    target_dod: float = 0.95            # depth of discharge per cycle
    cycles_per_year: int = 365          # one full cycle/day = single-cycle merchant
    climate_zone: Literal["uk_temperate", "uk_north", "med", "tropical"] = "uk_temperate"
    cni_grade: Literal["B3", "C5", "SR1"] = "C5"
    fence_setback_m: float = 25.0       # to property line per IFC 1207
    region_factor: float = 1.18          # UK CapEx uplift over EU mean
    discount_rate: float = 0.08
    poc_distance_m: float = 250.0       # POC to GIS bay run length


@dataclass
class PlacedItem:
    primitive_id: str
    xyz: tuple[float, float, float]
    rotation_deg: float = 0.0
    role: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class CableRun:
    """Discrete cable segment between two engineered nodes."""
    from_role: str
    to_role: str
    voltage_kv: float
    current_a: float
    length_m: float
    conductor_mm2: int
    conductor_type: str          # Cu / Al
    voltage_drop_pct: float
    polyline_xy: list[tuple[float, float]]


@dataclass
class SingleLineNode:
    id: str
    label: str
    role: str                    # battery / pcs / lvmv_tx / mv_bus / hv_tx / poc
    voltage_kv: float


@dataclass
class SingleLineEdge:
    from_id: str
    to_id: str
    voltage_kv: float
    rating_mva: float
    role: Literal["dc_string", "lv_ac", "mv_ring", "hv_tie"]


@dataclass
class BomLine:
    code: str
    label: str
    qty: float
    unit: str
    unit_cost_usd: float
    total_usd: float
    category: Literal[
        "battery", "pcs", "transformer", "switchgear", "civil",
        "cabling", "fire", "scada", "balance_of_plant", "epc", "interconnect",
    ]


@dataclass
class AugmentationStep:
    year: int
    soh_before_pct: float
    units_added: int
    energy_added_mwh: float
    capex_usd: float
    note: str


@dataclass
class BessDesign:
    brief: BessBrief
    summary: dict
    placed_assets: list[PlacedItem]
    cable_runs: list[CableRun]
    fence_polygon_xy: list[tuple[float, float]]
    access_road_xy: list[tuple[float, float]]
    single_line_nodes: list[SingleLineNode]
    single_line_edges: list[SingleLineEdge]
    bom: list[BomLine]
    augmentation_schedule: list[AugmentationStep]
    capex_breakdown: dict
    lcos_usd_per_mwh: float
    rte_curve: list[tuple[int, float]]   # (year, RTE fraction)
    soh_curve: list[tuple[int, float]]   # (year, state-of-health %)
    parasitic_kw_total: float
    notes: list[str]


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------
def _size_battery_array(brief: BessBrief, vendor: BatteryVendor) -> tuple[int, float, float]:
    """Return (n_containers_BoL, mwh_BoL, mw_at_PCS)."""
    target_mwh = brief.capacity_mw * brief.duration_h
    # containers must deliver target_mwh at usable DoD; oversize by augmentation reserve
    usable_factor = brief.target_dod
    n_units = math.ceil(target_mwh / (vendor.energy_kwh * usable_factor / 1000.0))
    return n_units, n_units * vendor.energy_kwh / 1000.0, brief.capacity_mw


def _size_pcs(brief: BessBrief, pcs: PcsProduct) -> int:
    # 5 % uplift to absorb augmentation creep + harmonic margin
    return math.ceil(brief.capacity_mw * 1000.0 * 1.05 / pcs.rating_kw)


def _size_main_tx(brief: BessBrief, main_tx: TransformerProduct) -> int:
    # 1.05 × MW for reactive capability + 5 % overload margin
    target_mva = brief.capacity_mw * 1.05 / 0.95   # at 0.95 lagging PF
    return max(1, math.ceil(target_mva / main_tx.rating_mva))


# ---------------------------------------------------------------------------
# Container packing — NFPA 855 + BS 8629 + IFC 1207
# ---------------------------------------------------------------------------
def _pack_containers(brief: BessBrief, vendor: BatteryVendor, n_units: int):
    """Pack containers in rows respecting:
        * BS 8629 max 8 containers/row before mandatory firebreak
        * NFPA 855 §15.2.5 — 3 ft (0.9 m) between BESS units
        * IFC 1207 — 10 ft (3.0 m) from non-BESS structures, 25 ft (7.6 m) to property line
    Returns (placements, geometry_meta).
    """
    row_max = 8
    pitch_x = vendor.length_m + 2.0          # 2 m intra-row corridor (NFPA 855 + BS 8629 floor)
    row_width = vendor.width_m
    firebreak_y = 8.0                         # BS 8629 inter-row firefighter access

    n_rows = math.ceil(n_units / row_max)
    per_full_row = min(row_max, n_units)
    block_w = per_full_row * pitch_x
    block_d = n_rows * row_width + (n_rows - 1) * firebreak_y if n_rows > 1 else row_width

    placements: list[PlacedItem] = []
    container_centres: list[tuple[int, int, float, float]] = []  # row, col, x, y
    for r in range(n_rows):
        units_in_row = per_full_row if r < n_rows - 1 else (n_units - r * per_full_row)
        row_y = - block_d / 2.0 + r * (row_width + firebreak_y) + row_width / 2.0
        for c in range(units_in_row):
            x = -block_w / 2.0 + c * pitch_x + pitch_x / 2.0
            container_centres.append((r, c, x, row_y))
            placements.append(PlacedItem(
                primitive_id="bess.megapack_2xl" if "tesla" in vendor.id else "bess.catl_energy_tensor",
                xyz=(x, row_y, 0.0),
                role="container",
                metadata={"row": r, "col": c, "vendor": vendor.id},
            ))
    return placements, {
        "block_w": block_w, "block_d": block_d,
        "row_max": row_max, "n_rows": n_rows,
        "container_centres": container_centres,
        "pitch_x": pitch_x, "firebreak_y": firebreak_y,
        "row_width": row_width,
    }


# ---------------------------------------------------------------------------
# Transformer + PCS placement
# ---------------------------------------------------------------------------
def _place_pcs_and_lvmv(brief: BessBrief, pcs: PcsProduct, lvmv_tx: TransformerProduct,
                        n_pcs: int, geo: dict) -> tuple[list[PlacedItem], list[tuple[float, float]]]:
    """One PCS + paired pad-mount LV-MV transformer per ~4 MVA block.
    Place along the south edge of the container block.
    """
    placements: list[PlacedItem] = []
    pcs_positions: list[tuple[float, float]] = []
    pcs_pitch = pcs.length_m + 2.0
    pcs_y = - geo["block_d"] / 2.0 - 6.0
    block_w = max(geo["block_w"], n_pcs * pcs_pitch)
    for i in range(n_pcs):
        x = - block_w / 2.0 + i * pcs_pitch + pcs_pitch / 2.0
        placements.append(PlacedItem("bess.pcs_2mva_skid", (x, pcs_y, 0.0),
                                     role="pcs", metadata={"index": i}))
        # pad-mount LV-MV TX 3 m south of PCS skid
        placements.append(PlacedItem("bess.auxiliary_transformer",
                                     (x, pcs_y - 4.0, 0.0),
                                     role="lvmv_tx", metadata={"index": i, "rating_mva": lvmv_tx.rating_mva}))
        pcs_positions.append((x, pcs_y))
    return placements, pcs_positions


def _place_main_compound(brief: BessBrief, main_tx: TransformerProduct,
                         n_main: int, geo: dict) -> tuple[list[PlacedItem], tuple[float, float]]:
    """Main HV step-up + GIS bay south of the PCS row."""
    placements: list[PlacedItem] = []
    compound_y = - geo["block_d"] / 2.0 - 22.0
    spacing = main_tx.length_m + 8.0
    for i in range(n_main):
        x = -((n_main - 1) * spacing) / 2.0 + i * spacing
        placements.append(PlacedItem("bess.hv_transformer", (x, compound_y, 0.0),
                                     role="main_tx", metadata={"index": i, "mva": main_tx.rating_mva}))
    # GIS bay east of TX
    gis_x = (n_main - 1) * spacing / 2.0 + spacing / 2.0 + 6.0
    gis_y = compound_y
    placements.append(PlacedItem("bess.gis_132kv_bay", (gis_x, gis_y, 0.0),
                                 role="gis_hv", metadata={"voltage_kv": brief.grid_voltage_kv}))
    return placements, (gis_x, gis_y)


def _place_ancillaries(brief: BessBrief, vendor: BatteryVendor, n_units: int,
                       geo: dict) -> list[PlacedItem]:
    """Control building, fire tanks, aux cabinets, weather mast."""
    placements: list[PlacedItem] = []
    block_w = geo["block_w"]
    block_d = geo["block_d"]
    # Control building west of containers
    placements.append(PlacedItem("bess.control_building",
                                 (-block_w / 2.0 - 12.0, 0.0, 0.0),
                                 role="control_room"))
    # Two fire tanks at NW and NE corners (BS 8629 firefighting water)
    n_tanks = max(2, math.ceil(n_units / 30))
    for t in range(n_tanks):
        if t % 2 == 0:
            x = - block_w / 2.0 - 6.0
            y = block_d / 2.0 + 6.0 + (t // 2) * 10.0
        else:
            x = block_w / 2.0 + 6.0
            y = block_d / 2.0 + 6.0 + (t // 2) * 10.0
        placements.append(PlacedItem("bess.fire_tank", (x, y, 0.0),
                                     role="fire_tank", metadata={"capacity_m3": 50}))
    # Aux cabinets along the east edge of every other row
    for r in range(0, geo["n_rows"], 2):
        y = - block_d / 2.0 + r * (geo["row_width"] + geo["firebreak_y"]) + geo["row_width"] / 2.0
        placements.append(PlacedItem("bess.auxiliary_cabinet",
                                     (block_w / 2.0 + 3.0, y, 0.0),
                                     role="bms_cabinet", metadata={"row": r}))
    return placements


# ---------------------------------------------------------------------------
# Cabling — IEC 60364-5-52 conductor sizing with voltage drop
# ---------------------------------------------------------------------------
_STD_CU_MM2 = [25, 35, 50, 70, 95, 120, 150, 185, 240, 300, 400, 500, 630, 800, 1000]

# Approximate ampacity in air, single-core, 30 °C ambient — IEC 60364-5-52 method E.
_AMPACITY_CU = {25: 130, 35: 160, 50: 195, 70: 245, 95: 295, 120: 340, 150: 390,
                185: 440, 240: 520, 300: 600, 400: 720, 500: 830, 630: 950,
                800: 1080, 1000: 1230}
# Approximate AC resistance + reactance per metre (mΩ/m, single-core Cu).
_R_PER_M = {25: 0.727, 35: 0.524, 50: 0.387, 70: 0.268, 95: 0.193, 120: 0.153,
            150: 0.124, 185: 0.0991, 240: 0.0754, 300: 0.0601, 400: 0.0470,
            500: 0.0366, 630: 0.0283, 800: 0.0221, 1000: 0.0176}
_X_PER_M = 0.08  # generic mΩ/m at LV, single-core touching


def _size_conductor(current_a: float, voltage_kv: float, length_m: float,
                    target_vd_pct: float = 3.0) -> tuple[int, float]:
    """Select smallest standard CSA whose ampacity ≥ current AND VD ≤ target."""
    for csa in _STD_CU_MM2:
        if _AMPACITY_CU[csa] < current_a:
            continue
        r = _R_PER_M[csa] / 1000.0     # Ω/m
        # Three-phase VD in V: √3 × I × (R cosφ + X sinφ) × L; use cosφ=0.95.
        vd_v = math.sqrt(3) * current_a * (r * 0.95 + _X_PER_M / 1000.0 * 0.312) * length_m
        vd_pct = vd_v / (voltage_kv * 1000.0) * 100.0
        if vd_pct <= target_vd_pct:
            return csa, vd_pct
    return _STD_CU_MM2[-1], 99.0


def _route_cables(brief: BessBrief, geo: dict, pcs_positions: list[tuple[float, float]],
                  main_compound_xy: tuple[float, float], pcs: PcsProduct,
                  lvmv_tx: TransformerProduct, main_tx: TransformerProduct,
                  n_main: int) -> list[CableRun]:
    """Route LV string → PCS, MV ring (PCS pad → main TX), HV tie (main TX → GIS → POC)."""
    runs: list[CableRun] = []

    # LV strings: every container row terminates at the nearest PCS skid.
    n_per_pcs = max(1, math.ceil(len(geo["container_centres"]) / max(len(pcs_positions), 1)))
    pcs_lv_kv = 0.69
    for i, (px, py) in enumerate(pcs_positions):
        # connect each container in this PCS's group with one polyline LV trunk
        group = geo["container_centres"][i * n_per_pcs:(i + 1) * n_per_pcs]
        for (_, _, cx, cy) in group:
            length = math.hypot(cx - px, cy - py) + 5.0   # add trench bend allowance
            current = pcs.rating_kw / (math.sqrt(3) * pcs_lv_kv)
            csa, vd = _size_conductor(current, pcs_lv_kv, length, target_vd_pct=2.5)
            runs.append(CableRun(
                from_role=f"container_{i}", to_role=f"pcs_{i}",
                voltage_kv=pcs_lv_kv, current_a=round(current, 1),
                length_m=round(length, 1), conductor_mm2=csa,
                conductor_type="Cu (XLPE/SWA/PVC)",
                voltage_drop_pct=round(vd, 2),
                polyline_xy=[(cx, cy), (px, py)],
            ))

    # MV ring 33 kV: every PCS pad-mount TX HV-side connects to main compound bus.
    mv_kv = lvmv_tx.primary_kv
    for i, (px, py) in enumerate(pcs_positions):
        length = math.hypot(px - main_compound_xy[0], py - main_compound_xy[1]) + 8.0
        # current at MV side: rating / √3·U
        i_mv = lvmv_tx.rating_mva * 1000.0 / (math.sqrt(3) * mv_kv)
        csa, vd = _size_conductor(i_mv, mv_kv, length, target_vd_pct=2.0)
        runs.append(CableRun(
            from_role=f"lvmv_tx_{i}", to_role="mv_bus",
            voltage_kv=mv_kv, current_a=round(i_mv, 1),
            length_m=round(length, 1), conductor_mm2=csa,
            conductor_type="Al (XLPE triplex)",
            voltage_drop_pct=round(vd, 2),
            polyline_xy=[(px, py - 4.0), main_compound_xy],
        ))

    # HV tie: GIS → POC (length from brief)
    hv_kv = brief.grid_voltage_kv
    i_hv = brief.capacity_mw * 1000.0 / (math.sqrt(3) * hv_kv) * 1.05
    csa_hv, vd_hv = _size_conductor(i_hv, hv_kv, brief.poc_distance_m, target_vd_pct=1.5)
    runs.append(CableRun(
        from_role="gis_hv", to_role="poc",
        voltage_kv=hv_kv, current_a=round(i_hv, 1),
        length_m=brief.poc_distance_m,
        conductor_mm2=csa_hv,
        conductor_type=f"{int(hv_kv)} kV XLPE single-core",
        voltage_drop_pct=round(vd_hv, 2),
        polyline_xy=[main_compound_xy, (main_compound_xy[0] + brief.poc_distance_m, main_compound_xy[1])],
    ))
    return runs


# ---------------------------------------------------------------------------
# Single-line diagram
# ---------------------------------------------------------------------------
def _build_single_line(brief: BessBrief, n_pcs: int, n_main: int,
                       pcs: PcsProduct, lvmv_tx: TransformerProduct,
                       main_tx: TransformerProduct):
    nodes: list[SingleLineNode] = []
    edges: list[SingleLineEdge] = []
    nodes.append(SingleLineNode("poc", "Point of Connection", "poc", brief.grid_voltage_kv))
    nodes.append(SingleLineNode("gis", "GIS Bay", "switchgear", brief.grid_voltage_kv))
    edges.append(SingleLineEdge("gis", "poc", brief.grid_voltage_kv,
                                main_tx.rating_mva * n_main, "hv_tie"))
    for i in range(n_main):
        nid = f"main_tx_{i}"
        nodes.append(SingleLineNode(nid, f"Main TX {i+1} {main_tx.label}", "hv_tx",
                                    main_tx.primary_kv))
        edges.append(SingleLineEdge(nid, "gis", main_tx.primary_kv,
                                    main_tx.rating_mva, "hv_tie"))
    nodes.append(SingleLineNode("mv_bus", "33 kV MV Switchboard", "mv_bus", lvmv_tx.primary_kv))
    for i in range(n_main):
        edges.append(SingleLineEdge("mv_bus", f"main_tx_{i}", lvmv_tx.primary_kv,
                                    main_tx.rating_mva, "mv_ring"))
    for i in range(n_pcs):
        tx_id = f"lvmv_tx_{i}"
        pcs_id = f"pcs_{i}"
        bat_id = f"battery_{i}"
        nodes.append(SingleLineNode(tx_id, f"LV-MV TX {i+1}", "lvmv_tx", lvmv_tx.primary_kv))
        nodes.append(SingleLineNode(pcs_id, f"PCS {i+1} {pcs.label}", "pcs", lvmv_tx.secondary_kv))
        nodes.append(SingleLineNode(bat_id, f"Battery Block {i+1}", "battery", 0.69))
        edges.append(SingleLineEdge(tx_id, "mv_bus", lvmv_tx.primary_kv,
                                    lvmv_tx.rating_mva, "mv_ring"))
        edges.append(SingleLineEdge(pcs_id, tx_id, lvmv_tx.secondary_kv,
                                    pcs.rating_kva / 1000.0, "lv_ac"))
        edges.append(SingleLineEdge(bat_id, pcs_id, 0.69,
                                    pcs.rating_kw / 1000.0, "dc_string"))
    return nodes, edges


# ---------------------------------------------------------------------------
# Augmentation + RTE / SoH curves
# ---------------------------------------------------------------------------
def _soh_curve(vendor: BatteryVendor, brief: BessBrief) -> list[tuple[int, float]]:
    """Linearised cycle-driven SoH from BoL down to EoL trigger."""
    cycles_per_year = brief.cycles_per_year
    deg_per_cycle = (1.0 - 0.80) / vendor.cycle_life_to_80pct  # SoH frac per cycle
    pts = []
    soh = 1.0
    for y in range(0, brief.project_life_y + 1):
        if y > 0:
            soh -= deg_per_cycle * cycles_per_year * brief.target_dod
            soh = max(soh, 0.70)
        pts.append((y, round(soh * 100.0, 2)))
    return pts


def _rte_curve(vendor: BatteryVendor, brief: BessBrief) -> list[tuple[int, float]]:
    """Linear interpolation of RTE from BoL to EoL across project life."""
    pts = []
    for y in range(0, brief.project_life_y + 1):
        frac = y / max(brief.project_life_y, 1)
        rte = vendor.rte_bol + (vendor.rte_eol - vendor.rte_bol) * frac
        pts.append((y, round(rte, 4)))
    return pts


def _augmentation_schedule(vendor: BatteryVendor, brief: BessBrief,
                           soh: list[tuple[int, float]],
                           initial_units: int) -> list[AugmentationStep]:
    """Plan augmentation deliveries to maintain rated MWh.
    Strategy 'annual' tops up lost capacity each year after year 2.
    """
    if brief.augmentation == "none":
        return []
    nameplate_mwh = initial_units * vendor.energy_kwh / 1000.0
    schedule: list[AugmentationStep] = []
    if brief.augmentation == "year_5_only":
        # one big lump at year 5
        target = brief.capacity_mw * brief.duration_h
        soh_y5 = next((s for (y, s) in soh if y == 5), 90.0)
        deficit = target - nameplate_mwh * soh_y5 / 100.0
        if deficit > 0:
            adds = math.ceil(deficit / (vendor.energy_kwh / 1000.0))
            schedule.append(AugmentationStep(
                year=5, soh_before_pct=soh_y5, units_added=adds,
                energy_added_mwh=adds * vendor.energy_kwh / 1000.0,
                capex_usd=adds * vendor.energy_kwh * vendor.capex_usd_per_kwh * brief.region_factor,
                note="single-shot augmentation at year 5",
            ))
        return schedule
    interval = 1 if brief.augmentation == "annual" else 2
    target = brief.capacity_mw * brief.duration_h
    for y in range(2, brief.project_life_y, interval):
        soh_y = next((s for (yy, s) in soh if yy == y), 95.0)
        retained = nameplate_mwh * soh_y / 100.0
        deficit = max(0.0, target - retained)
        if deficit < 0.5:    # within 0.5 MWh tolerance
            continue
        adds = math.ceil(deficit / (vendor.energy_kwh / 1000.0))
        schedule.append(AugmentationStep(
            year=y, soh_before_pct=soh_y, units_added=adds,
            energy_added_mwh=adds * vendor.energy_kwh / 1000.0,
            capex_usd=adds * vendor.energy_kwh * (vendor.capex_usd_per_kwh * 0.85)
                     * brief.region_factor,    # forward price decline
            note=f"{brief.augmentation} top-up",
        ))
    return schedule


# ---------------------------------------------------------------------------
# Bill of quantities + CapEx
# ---------------------------------------------------------------------------
def _bom(brief: BessBrief, vendor: BatteryVendor, pcs: PcsProduct,
         lvmv_tx: TransformerProduct, main_tx: TransformerProduct,
         n_units: int, n_pcs: int, n_main: int,
         cable_runs: Sequence[CableRun], geo: dict) -> list[BomLine]:
    lines: list[BomLine] = []
    rf = brief.region_factor

    # Battery containers
    bat_total = n_units * vendor.energy_kwh * vendor.capex_usd_per_kwh * rf
    lines.append(BomLine("BAT-001", f"{vendor.label} container", n_units, "ea",
                         vendor.energy_kwh * vendor.capex_usd_per_kwh * rf,
                         bat_total, "battery"))

    # PCS
    pcs_total = n_pcs * pcs.rating_kw * pcs.capex_usd_per_kw * rf
    lines.append(BomLine("PCS-001", f"{pcs.label} 2-quadrant skid", n_pcs, "ea",
                         pcs.rating_kw * pcs.capex_usd_per_kw * rf,
                         pcs_total, "pcs"))

    # LV-MV transformers (one per PCS)
    lvmv_total = n_pcs * lvmv_tx.rating_mva * lvmv_tx.capex_usd_per_mva * rf
    lines.append(BomLine("TX-001", f"{lvmv_tx.label}", n_pcs, "ea",
                         lvmv_tx.rating_mva * lvmv_tx.capex_usd_per_mva * rf,
                         lvmv_total, "transformer"))

    # Main TX
    main_total = n_main * main_tx.rating_mva * main_tx.capex_usd_per_mva * rf
    lines.append(BomLine("TX-002", f"{main_tx.label}", n_main, "ea",
                         main_tx.rating_mva * main_tx.capex_usd_per_mva * rf,
                         main_total, "transformer"))

    # GIS bay
    gis_cost = 1_400_000 * rf
    lines.append(BomLine("SW-001", f"{int(brief.grid_voltage_kv)} kV GIS bay (Hitachi EXK-1)",
                         1, "ea", gis_cost, gis_cost, "switchgear"))

    # 33 kV MV switchboard
    mv_panels = n_pcs + n_main + 2     # incomers + outgoing + spare + bus-tie
    mv_cost = mv_panels * 95_000 * rf
    lines.append(BomLine("SW-002", "33 kV indoor switchboard (ABB UniGear ZS1)",
                         mv_panels, "panel", 95_000 * rf, mv_cost, "switchgear"))

    # Cabling — sum by voltage
    lv_m = sum(c.length_m for c in cable_runs if c.voltage_kv < 1.0)
    mv_m = sum(c.length_m for c in cable_runs if 1.0 <= c.voltage_kv < 100.0)
    hv_m = sum(c.length_m for c in cable_runs if c.voltage_kv >= 100.0)
    lines.append(BomLine("CB-001", "LV power cable (XLPE/SWA Cu)", round(lv_m), "m",
                         180.0 * rf, lv_m * 180.0 * rf, "cabling"))
    lines.append(BomLine("CB-002", "33 kV MV cable (Al triplex XLPE)", round(mv_m), "m",
                         260.0 * rf, mv_m * 260.0 * rf, "cabling"))
    lines.append(BomLine("CB-003", f"{int(brief.grid_voltage_kv)} kV HV single-core cable", round(hv_m), "m",
                         920.0 * rf, hv_m * 920.0 * rf, "cabling"))
    lines.append(BomLine("CB-004", "Cable trench excavation + bedding", round(lv_m + mv_m + hv_m), "m",
                         95.0 * rf, (lv_m + mv_m + hv_m) * 95.0 * rf, "civil"))

    # Earthing grid (8 kg Cu per kVA fault contribution, simplified)
    earth_cu_kg = max(2000, int(brief.capacity_mw * 1000 * 0.4))
    lines.append(BomLine("EA-001", "Earthing grid (bare Cu 70 mm² + rods)",
                         earth_cu_kg, "kg", 28.0 * rf, earth_cu_kg * 28.0 * rf, "civil"))

    # Civil works
    pad_area = geo["block_w"] * geo["block_d"] * 1.4
    lines.append(BomLine("CV-001", "Reinforced concrete container plinth", round(pad_area), "m²",
                         420.0 * rf, pad_area * 420.0 * rf, "civil"))
    lines.append(BomLine("CV-002", "Site fence (CPNI 2.4 m palisade)",
                         round(2 * (geo["block_w"] + 50) + 2 * (geo["block_d"] + 50)),
                         "m", 320.0 * rf,
                         (2 * (geo["block_w"] + 50) + 2 * (geo["block_d"] + 50)) * 320.0 * rf,
                         "civil"))
    lines.append(BomLine("CV-003", "Internal access road (3 m wide tarmac)",
                         round(geo["block_w"] + 80), "m",
                         185.0 * rf, (geo["block_w"] + 80) * 185.0 * rf, "civil"))

    # Fire system
    n_tanks = max(2, math.ceil(n_units / 30))
    lines.append(BomLine("FR-001", "Fire-fighting water tank (50 m³)", n_tanks, "ea",
                         92_000.0 * rf, n_tanks * 92_000.0 * rf, "fire"))
    lines.append(BomLine("FR-002", "Aerosol fire suppression per container",
                         n_units, "ea", 8_500.0 * rf, n_units * 8_500.0 * rf, "fire"))

    # SCADA + control
    lines.append(BomLine("SC-001", "SCADA/EMS package + cyber-secure gateway",
                         1, "ls", 220_000.0 * rf, 220_000.0 * rf, "scada"))
    lines.append(BomLine("SC-002", "Control & SCADA building (12 m × 6 m)",
                         1, "ea", 380_000.0 * rf, 380_000.0 * rf, "balance_of_plant"))

    # Auxiliary loads
    lines.append(BomLine("AUX-001", "Aux 500 kVA TX + LV switchboard",
                         1, "ea", 75_000.0 * rf, 75_000.0 * rf, "balance_of_plant"))

    # Interconnect / DNO
    lines.append(BomLine("IC-001", f"{int(brief.grid_voltage_kv)} kV grid connection works (DNO contestable)",
                         1, "ls", 1_650_000.0 * rf, 1_650_000.0 * rf, "interconnect"))

    # EPC margin + design + permitting
    direct = sum(l.total_usd for l in lines)
    lines.append(BomLine("EPC-001", "EPC contractor margin (8 %)",
                         1, "ls", direct * 0.08, direct * 0.08, "epc"))
    lines.append(BomLine("EPC-002", "Owner's engineer + permitting + insurance (4 %)",
                         1, "ls", direct * 0.04, direct * 0.04, "epc"))
    return lines


def _capex_breakdown(bom: list[BomLine]) -> dict:
    out: dict[str, float] = {}
    total = 0.0
    for l in bom:
        out[l.category] = out.get(l.category, 0.0) + l.total_usd
        total += l.total_usd
    out["total_usd"] = total
    return out


def _lcos(brief: BessBrief, capex_total: float, augment_capex: float,
          rte_curve: list[tuple[int, float]], parasitic_kw: float) -> float:
    """Discounted LCOS in $/MWh delivered.
    Approximation: discharged MWh per year ≈ capacity_mw × duration_h × cycles × DoD.
    Annual O&M assumed 1.5 % of CapEx; parasitic energy paid at retail proxy 80 $/MWh.
    """
    annual_mwh_out = brief.capacity_mw * brief.duration_h * brief.cycles_per_year * brief.target_dod
    annual_om = capex_total * 0.015
    parasitic_kwh = parasitic_kw * 8760.0
    parasitic_cost = parasitic_kwh / 1000.0 * 80.0
    pv_mwh = 0.0
    pv_cost = capex_total + augment_capex
    for y in range(1, brief.project_life_y + 1):
        rte_y = next((r for (yy, r) in rte_curve if yy == y), 0.88)
        delivered = annual_mwh_out * rte_y
        discount = (1.0 + brief.discount_rate) ** y
        pv_mwh += delivered / discount
        pv_cost += (annual_om + parasitic_cost) / discount
    return round(pv_cost / max(pv_mwh, 1.0), 2)


# ---------------------------------------------------------------------------
# Site polygons (fence + access road)
# ---------------------------------------------------------------------------
def _fence_polygon(geo: dict, setback: float) -> list[tuple[float, float]]:
    half_w = geo["block_w"] / 2.0 + setback
    half_d = geo["block_d"] / 2.0 + setback + 14.0   # extra room south for compound
    return [(-half_w, -half_d - 30.0), (half_w, -half_d - 30.0),
            (half_w, half_d), (-half_w, half_d),
            (-half_w, -half_d - 30.0)]


def _access_road(geo: dict) -> list[tuple[float, float]]:
    half_w = geo["block_w"] / 2.0
    return [(half_w + 40.0, -geo["block_d"] / 2.0 - 30.0),
            (half_w + 12.0, -geo["block_d"] / 2.0 - 8.0),
            (half_w + 4.0, geo["block_d"] / 2.0 + 4.0)]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def design(brief: BessBrief) -> BessDesign:
    vendor = VENDORS.get(brief.vendor_id) or VENDORS["tesla.megapack_2xl"]
    pcs = PCS_CATALOGUE.get(brief.pcs_id) or PCS_CATALOGUE["sungrow.sc4400_uds"]
    main_tx = TX_CATALOGUE.get(brief.main_tx_id) or TX_CATALOGUE["hitachi.main_60mva"]
    lvmv_tx = TX_CATALOGUE["hitachi.padmount_4400"]

    n_units, mwh_bol, mw_at_pcs = _size_battery_array(brief, vendor)
    n_pcs = _size_pcs(brief, pcs)
    n_main = _size_main_tx(brief, main_tx)

    placements_c, geo = _pack_containers(brief, vendor, n_units)
    placements_p, pcs_xy = _place_pcs_and_lvmv(brief, pcs, lvmv_tx, n_pcs, geo)
    placements_m, main_xy = _place_main_compound(brief, main_tx, n_main, geo)
    placements_a = _place_ancillaries(brief, vendor, n_units, geo)
    placed = placements_c + placements_p + placements_m + placements_a

    cable_runs = _route_cables(brief, geo, pcs_xy, main_xy,
                               pcs, lvmv_tx, main_tx, n_main)
    fence = _fence_polygon(geo, brief.fence_setback_m)
    road = _access_road(geo)
    sl_nodes, sl_edges = _build_single_line(brief, n_pcs, n_main,
                                            pcs, lvmv_tx, main_tx)

    soh = _soh_curve(vendor, brief)
    rte = _rte_curve(vendor, brief)
    aug = _augmentation_schedule(vendor, brief, soh, n_units)

    bom = _bom(brief, vendor, pcs, lvmv_tx, main_tx,
               n_units, n_pcs, n_main, cable_runs, geo)
    capex = _capex_breakdown(bom)
    augment_total = sum(a.capex_usd for a in aug)
    parasitic = n_units * vendor.parasitic_kw

    lcos = _lcos(brief, capex["total_usd"], augment_total, rte, parasitic)

    notes: list[str] = [
        f"BESS {brief.capacity_mw:g} MW / {brief.duration_h:g} h "
        f"using {n_units} × {vendor.label} (BoL {mwh_bol:.1f} MWh, "
        f"DoD {brief.target_dod:.0%}).",
        f"NFPA 855 + BS 8629 compliant block: {geo['n_rows']} rows × ≤8 containers "
        f"(2 m intra-row corridor, 8 m firebreaks).",
        f"Power conversion: {n_pcs} × {pcs.label}; "
        f"main step-up: {n_main} × {main_tx.label}.",
        f"HV interconnect: {brief.grid_voltage_kv:g} kV GIS bay → POC "
        f"({brief.poc_distance_m:.0f} m).",
        f"Augmentation strategy '{brief.augmentation}': "
        f"{len(aug)} top-up event(s), {sum(a.units_added for a in aug)} containers added "
        f"over {brief.project_life_y} y.",
        f"CapEx (EPC turn-key, region factor {brief.region_factor:.2f}): "
        f"${capex['total_usd']/1e6:,.2f} M direct + ${augment_total/1e6:,.2f} M augmentation.",
        f"Round-trip efficiency BoL {vendor.rte_bol:.1%} → EoL {vendor.rte_eol:.1%}.",
        f"Parasitic load: {parasitic:.1f} kW continuous "
        f"({parasitic*8.76:.0f} MWh/y @ 100 % uptime).",
        f"LCOS (discount {brief.discount_rate:.0%}): "
        f"${lcos:.0f}/MWh delivered.",
    ]

    summary = {
        "capacity_mw": brief.capacity_mw,
        "duration_h": brief.duration_h,
        "energy_mwh_bol": round(mwh_bol, 1),
        "vendor": {
            "id": vendor.id, "label": vendor.label,
            "chemistry": vendor.chemistry,
            "energy_kwh": vendor.energy_kwh, "power_kw": vendor.power_kw,
            "rte_bol": vendor.rte_bol, "rte_eol": vendor.rte_eol,
            "cycle_life_to_80pct": vendor.cycle_life_to_80pct,
        },
        "pcs": {"id": pcs.id, "label": pcs.label, "count": n_pcs,
                "rating_kw": pcs.rating_kw},
        "main_tx": {"id": main_tx.id, "label": main_tx.label, "count": n_main,
                    "rating_mva": main_tx.rating_mva,
                    "primary_kv": main_tx.primary_kv,
                    "secondary_kv": main_tx.secondary_kv},
        "n_containers": n_units,
        "block_dimensions_m": {"w": round(geo["block_w"], 1),
                               "d": round(geo["block_d"], 1)},
        "fence_setback_m": brief.fence_setback_m,
        "capex_total_usd": round(capex["total_usd"], 0),
        "capex_per_kwh_usd": round(capex["total_usd"] / max(mwh_bol * 1000.0, 1.0), 1),
        "augmentation_total_usd": round(augment_total, 0),
        "lcos_usd_per_mwh": lcos,
        "parasitic_kw": round(parasitic, 1),
        "standards": ["IEC 62933-5-2", "NFPA 855 (2023)", "BS 8629",
                      "IFC 1207", "IEC 60364-5-52", "ENA EREC G99 Issue 2"],
    }

    return BessDesign(
        brief=brief,
        summary=summary,
        placed_assets=placed,
        cable_runs=cable_runs,
        fence_polygon_xy=fence,
        access_road_xy=road,
        single_line_nodes=sl_nodes,
        single_line_edges=sl_edges,
        bom=bom,
        augmentation_schedule=aug,
        capex_breakdown=capex,
        lcos_usd_per_mwh=lcos,
        rte_curve=rte,
        soh_curve=soh,
        parasitic_kw_total=round(parasitic, 1),
        notes=notes,
    )


def design_to_dict(d: BessDesign) -> dict:
    """Serialise BessDesign for JSON transport (preserves dataclass nesting)."""
    return {
        "brief": asdict(d.brief),
        "summary": d.summary,
        "placed_assets": [asdict(p) for p in d.placed_assets],
        "cable_runs": [asdict(c) for c in d.cable_runs],
        "fence_polygon_xy": [list(p) for p in d.fence_polygon_xy],
        "access_road_xy": [list(p) for p in d.access_road_xy],
        "single_line": {
            "nodes": [asdict(n) for n in d.single_line_nodes],
            "edges": [asdict(e) for e in d.single_line_edges],
        },
        "bom": [asdict(l) for l in d.bom],
        "augmentation_schedule": [asdict(a) for a in d.augmentation_schedule],
        "capex_breakdown": d.capex_breakdown,
        "lcos_usd_per_mwh": d.lcos_usd_per_mwh,
        "rte_curve": [list(p) for p in d.rte_curve],
        "soh_curve": [list(p) for p in d.soh_curve],
        "parasitic_kw_total": d.parasitic_kw_total,
        "notes": d.notes,
    }
