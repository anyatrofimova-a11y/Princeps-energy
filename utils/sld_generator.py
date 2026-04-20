"""Single Line Diagram (SLD) generator for Princeps.

Produces clean SVG single line diagrams with standard IEC electrical symbols
for solar + BESS installations.  Left-to-right flow:
Generation -> Conversion -> Transformation -> Protection -> Grid.

Usage:
    result = generate_sld(assets, capacity_kw=5000, voltage_kv=33)
    svg_string = result["svg"]
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIEW_W, VIEW_H = 800, 400
STROKE = "#1a1a1a"
STROKE_W = "1.5"
FILL_NONE = "none"
FONT = "Consolas, 'Courier New', monospace"
FONT_SIZE = "9"
LABEL_SIZE = "8"

# Stage x-centres (left to right)
X_GEN = 80       # PV / BESS generation
X_COMBINER = 200 # DC combiner
X_INVERTER = 320 # inverter
X_XFMR = 480    # step-up transformer
X_BREAKER = 590  # circuit breaker + meter
X_GRID = 720     # grid bus bar / POC

STAGE_Y_START = 60
STRING_SPACING = 70

# Cable sizing lookup (A rating -> mm2)
CABLE_SIZING = [
    (25, 4), (32, 6), (45, 10), (60, 16), (80, 25),
    (105, 35), (130, 50), (165, 70), (200, 95), (245, 120),
    (290, 150), (340, 185), (395, 240), (455, 300), (530, 400),
]


# ---------------------------------------------------------------------------
# SVG symbol primitives (IEC-style)
# ---------------------------------------------------------------------------

def _svg_pv_cell(parent: ET.Element, cx: float, cy: float, label: str = "") -> None:
    """PV cell symbol: rectangle with diagonal arrow (sunlight)."""
    w, h = 30, 22
    x0, y0 = cx - w / 2, cy - h / 2
    ET.SubElement(parent, "rect", x=f"{x0}", y=f"{y0}", width=f"{w}", height=f"{h}",
                  stroke=STROKE, fill=FILL_NONE, **{"stroke-width": STROKE_W})
    # diagonal line inside (diode)
    ET.SubElement(parent, "line", x1=f"{x0 + 4}", y1=f"{y0 + h - 4}",
                  x2=f"{x0 + w - 4}", y2=f"{y0 + 4}",
                  stroke=STROKE, **{"stroke-width": "1"})
    # sunlight arrow
    ax, ay = x0 - 6, y0 - 6
    ET.SubElement(parent, "line", x1=f"{ax}", y1=f"{ay}",
                  x2=f"{ax + 10}", y2=f"{ay + 10}",
                  stroke=STROKE, **{"stroke-width": "1"})
    ET.SubElement(parent, "polygon",
                  points=f"{ax + 10},{ay + 10} {ax + 6},{ay + 7} {ax + 7},{ay + 6}",
                  fill=STROKE)
    if label:
        _label(parent, cx, cy + h / 2 + 11, label)


def _svg_bess(parent: ET.Element, cx: float, cy: float, label: str = "") -> None:
    """Battery symbol: two plates (one thick, one thin)."""
    gap = 4
    ET.SubElement(parent, "line", x1=f"{cx - 10}", y1=f"{cy - gap}",
                  x2=f"{cx + 10}", y2=f"{cy - gap}",
                  stroke=STROKE, **{"stroke-width": "3"})
    ET.SubElement(parent, "line", x1=f"{cx - 6}", y1=f"{cy + gap}",
                  x2=f"{cx + 6}", y2=f"{cy + gap}",
                  stroke=STROKE, **{"stroke-width": "1.5"})
    # terminals
    ET.SubElement(parent, "line", x1=f"{cx}", y1=f"{cy - gap - 8}",
                  x2=f"{cx}", y2=f"{cy - gap}",
                  stroke=STROKE, **{"stroke-width": STROKE_W})
    ET.SubElement(parent, "line", x1=f"{cx}", y1=f"{cy + gap}",
                  x2=f"{cx}", y2=f"{cy + gap + 8}",
                  stroke=STROKE, **{"stroke-width": STROKE_W})
    # +/- labels
    _label(parent, cx + 14, cy - gap + 1, "+", size="7")
    _label(parent, cx + 14, cy + gap + 1, "-", size="7")
    if label:
        _label(parent, cx, cy + gap + 22, label)


def _svg_combiner(parent: ET.Element, cx: float, cy: float, n_in: int = 2) -> None:
    """DC combiner box: small rectangle with label."""
    w, h = 24, 18
    x0, y0 = cx - w / 2, cy - h / 2
    ET.SubElement(parent, "rect", x=f"{x0}", y=f"{y0}", width=f"{w}", height=f"{h}",
                  stroke=STROKE, fill=FILL_NONE, **{"stroke-width": STROKE_W}, rx="2")
    _label(parent, cx, cy + 3, "CB", size="7", bold=True)
    _label(parent, cx, cy + h / 2 + 10, f"{n_in}-in")


def _svg_inverter(parent: ET.Element, cx: float, cy: float, label: str = "") -> None:
    """Inverter / rectifier symbol: square with ~ and = signs."""
    s = 26
    x0, y0 = cx - s / 2, cy - s / 2
    ET.SubElement(parent, "rect", x=f"{x0}", y=f"{y0}", width=f"{s}", height=f"{s}",
                  stroke=STROKE, fill=FILL_NONE, **{"stroke-width": STROKE_W})
    # diagonal divider
    ET.SubElement(parent, "line", x1=f"{x0}", y1=f"{y0 + s}",
                  x2=f"{x0 + s}", y2=f"{y0}",
                  stroke=STROKE, **{"stroke-width": "0.8"})
    # DC side (=)
    _label(parent, cx - 5, cy + 6, "=", size="10", bold=True)
    # AC side (~)
    _label(parent, cx + 5, cy - 3, "~", size="10", bold=True)
    if label:
        _label(parent, cx, cy + s / 2 + 11, label)


def _svg_transformer(parent: ET.Element, cx: float, cy: float,
                     v_primary: str = "", v_secondary: str = "") -> None:
    """Two-coil transformer symbol (IEC)."""
    r = 11
    gap = 4
    # primary coil (left)
    ET.SubElement(parent, "circle", cx=f"{cx - gap}", cy=f"{cy}", r=f"{r}",
                  stroke=STROKE, fill=FILL_NONE, **{"stroke-width": STROKE_W})
    # secondary coil (right)
    ET.SubElement(parent, "circle", cx=f"{cx + gap}", cy=f"{cy}", r=f"{r}",
                  stroke=STROKE, fill=FILL_NONE, **{"stroke-width": STROKE_W})
    if v_primary:
        _label(parent, cx - gap, cy + r + 12, v_primary)
    if v_secondary:
        _label(parent, cx + gap, cy - r - 5, v_secondary)


def _svg_breaker(parent: ET.Element, cx: float, cy: float) -> None:
    """Circuit breaker symbol: X in a square."""
    s = 14
    x0, y0 = cx - s / 2, cy - s / 2
    ET.SubElement(parent, "rect", x=f"{x0}", y=f"{y0}", width=f"{s}", height=f"{s}",
                  stroke=STROKE, fill=FILL_NONE, **{"stroke-width": STROKE_W})
    ET.SubElement(parent, "line", x1=f"{x0}", y1=f"{y0}",
                  x2=f"{x0 + s}", y2=f"{y0 + s}",
                  stroke=STROKE, **{"stroke-width": "1"})
    ET.SubElement(parent, "line", x1=f"{x0 + s}", y1=f"{y0}",
                  x2=f"{x0}", y2=f"{y0 + s}",
                  stroke=STROKE, **{"stroke-width": "1"})
    _label(parent, cx, cy + s / 2 + 10, "CB")


def _svg_meter(parent: ET.Element, cx: float, cy: float) -> None:
    """Meter symbol: circle with M inside."""
    r = 10
    ET.SubElement(parent, "circle", cx=f"{cx}", cy=f"{cy}", r=f"{r}",
                  stroke=STROKE, fill=FILL_NONE, **{"stroke-width": STROKE_W})
    _label(parent, cx, cy + 3.5, "M", size="9", bold=True)


def _svg_bus_bar(parent: ET.Element, cx: float, y_top: float, y_bot: float,
                 label: str = "") -> None:
    """Vertical bus bar (thick line)."""
    ET.SubElement(parent, "line", x1=f"{cx}", y1=f"{y_top}",
                  x2=f"{cx}", y2=f"{y_bot}",
                  stroke=STROKE, **{"stroke-width": "3"})
    if label:
        _label(parent, cx, y_top - 8, label, size="8", bold=True)


def _svg_grid_symbol(parent: ET.Element, cx: float, cy: float) -> None:
    """Grid / utility connection: circle with lightning bolt."""
    r = 14
    ET.SubElement(parent, "circle", cx=f"{cx}", cy=f"{cy}", r=f"{r}",
                  stroke=STROKE, fill=FILL_NONE, **{"stroke-width": "2"})
    # simplified lightning bolt
    bolt = (f"M {cx - 3},{cy - 8} L {cx + 1},{cy - 1} L {cx - 2},{cy - 1} "
            f"L {cx + 3},{cy + 8} L {cx - 1},{cy + 1} L {cx + 2},{cy + 1} Z")
    ET.SubElement(parent, "path", d=bolt, fill=STROKE, stroke="none")


def _wire(parent: ET.Element, x1: float, y1: float, x2: float, y2: float,
          dashed: bool = False) -> None:
    """Draw a wire (line) between two points."""
    attrib: dict[str, str] = {
        "x1": f"{x1}", "y1": f"{y1}", "x2": f"{x2}", "y2": f"{y2}",
        "stroke": STROKE, "stroke-width": STROKE_W,
    }
    if dashed:
        attrib["stroke-dasharray"] = "4,3"
    ET.SubElement(parent, "line", **attrib)


def _label(parent: ET.Element, x: float, y: float, text: str,
           size: str = LABEL_SIZE, bold: bool = False, anchor: str = "middle") -> None:
    """Place a text label."""
    attrib: dict[str, str] = {
        "x": f"{x}", "y": f"{y}",
        "font-family": FONT, "font-size": size,
        "fill": STROKE, "text-anchor": anchor,
    }
    if bold:
        attrib["font-weight"] = "bold"
    el = ET.SubElement(parent, "text", **attrib)
    el.text = text


def _voltage_tag(parent: ET.Element, x: float, y: float, v_text: str) -> None:
    """Small voltage annotation with background."""
    # background rect
    tw = len(v_text) * 5 + 6
    ET.SubElement(parent, "rect", x=f"{x - tw / 2}", y=f"{y - 8}",
                  width=f"{tw}", height="12", fill="white",
                  stroke="#cccccc", **{"stroke-width": "0.5"}, rx="2")
    _label(parent, x, y + 1, v_text, size="7", bold=True)


# ---------------------------------------------------------------------------
# Cable sizing helper
# ---------------------------------------------------------------------------

def _size_cable(current_a: float) -> int:
    """Return cable cross-section (mm2) for given current rating."""
    for rating, mm2 in CABLE_SIZING:
        if current_a <= rating:
            return mm2
    return 400  # max


def _calc_string_voltage(modules_per_string: int = 20, vmp: float = 40.0) -> float:
    return modules_per_string * vmp


# ---------------------------------------------------------------------------
# Asset parsing and normalisation
# ---------------------------------------------------------------------------

def _parse_assets(assets: list[dict], capacity_kw: float) -> dict[str, Any]:
    """Normalise incoming asset list into structured SLD inputs."""
    solar_arrays = []
    bess_units = []
    inverters = []
    transformers = []

    for a in assets:
        atype = (a.get("type") or a.get("asset_type") or "").lower()
        cap = a.get("capacity_kw") or a.get("capacity_kWp") or a.get("capacity", 0)
        name = a.get("name") or a.get("label") or atype
        if "solar" in atype or "pv" in atype or "array" in atype:
            solar_arrays.append({"name": name, "capacity_kw": float(cap)})
        elif "bess" in atype or "battery" in atype or "storage" in atype:
            bess_units.append({"name": name, "capacity_kw": float(cap),
                               "capacity_kwh": float(a.get("capacity_kwh", cap * 2))})
        elif "inverter" in atype:
            inverters.append({"name": name, "capacity_kw": float(cap)})
        elif "transformer" in atype or "xfmr" in atype:
            transformers.append({"name": name, "capacity_kva": float(a.get("capacity_kva", cap))})

    # Defaults if nothing provided
    if not solar_arrays:
        n_arrays = max(1, min(6, int(math.ceil(capacity_kw / 1000))))
        per = capacity_kw / n_arrays
        solar_arrays = [{"name": f"PV Array {i + 1}", "capacity_kw": per}
                        for i in range(n_arrays)]

    if not inverters:
        inverters = [{"name": "Central Inverter", "capacity_kw": capacity_kw}]

    if not transformers:
        transformers = [{"name": "Step-up Xfmr", "capacity_kva": capacity_kw * 1.1}]

    return {
        "solar": solar_arrays,
        "bess": bess_units,
        "inverters": inverters,
        "transformers": transformers,
    }


# ---------------------------------------------------------------------------
# Cable schedule builder
# ---------------------------------------------------------------------------

def _build_cable_schedule(parsed: dict, capacity_kw: float,
                          voltage_kv: float) -> list[dict]:
    """Generate cable schedule from asset topology."""
    schedule: list[dict] = []
    n_strings = len(parsed["solar"]) + len(parsed["bess"])

    # DC string cables (each PV array -> combiner)
    string_v = _calc_string_voltage()
    for arr in parsed["solar"]:
        i_dc = (arr["capacity_kw"] * 1000) / string_v if string_v else 0
        mm2 = _size_cable(i_dc)
        schedule.append({
            "segment": f"{arr['name']} -> DC Combiner",
            "voltage": f"{string_v:.0f} V DC",
            "current_a": round(i_dc, 1),
            "cable_mm2": mm2,
            "type": "DC",
        })

    # BESS DC cables
    for b in parsed["bess"]:
        i_dc = (b["capacity_kw"] * 1000) / 800 if b["capacity_kw"] else 0
        mm2 = _size_cable(i_dc)
        schedule.append({
            "segment": f"{b['name']} -> DC Combiner",
            "voltage": "800 V DC",
            "current_a": round(i_dc, 1),
            "cable_mm2": mm2,
            "type": "DC",
        })

    # DC combiner -> inverter
    total_dc_current = sum(c["current_a"] for c in schedule)
    mm2 = _size_cable(total_dc_current)
    schedule.append({
        "segment": "DC Combiner -> Inverter",
        "voltage": f"{string_v:.0f} V DC",
        "current_a": round(total_dc_current, 1),
        "cable_mm2": mm2,
        "type": "DC",
    })

    # Inverter AC output (400V 3-phase)
    ac_v = 400
    i_ac = (capacity_kw * 1000) / (ac_v * math.sqrt(3)) if ac_v else 0
    mm2 = _size_cable(i_ac)
    schedule.append({
        "segment": "Inverter -> AC Board",
        "voltage": "400 V AC",
        "current_a": round(i_ac, 1),
        "cable_mm2": mm2,
        "type": "AC LV",
    })

    # AC Board -> Transformer
    schedule.append({
        "segment": "AC Board -> Transformer",
        "voltage": "400 V AC",
        "current_a": round(i_ac, 1),
        "cable_mm2": mm2,
        "type": "AC LV",
    })

    # Transformer MV output -> switchgear
    mv_v = voltage_kv * 1000
    i_mv = (capacity_kw * 1000) / (mv_v * math.sqrt(3)) if mv_v else 0
    mm2_mv = _size_cable(i_mv)
    schedule.append({
        "segment": "Transformer -> Circuit Breaker",
        "voltage": f"{voltage_kv:.0f} kV AC",
        "current_a": round(i_mv, 1),
        "cable_mm2": mm2_mv,
        "type": "AC MV",
    })

    # Switchgear -> POC
    schedule.append({
        "segment": "Circuit Breaker -> Grid POC",
        "voltage": f"{voltage_kv:.0f} kV AC",
        "current_a": round(i_mv, 1),
        "cable_mm2": mm2_mv,
        "type": "AC MV",
    })

    return schedule


# ---------------------------------------------------------------------------
# SVG renderer
# ---------------------------------------------------------------------------

def _render_svg(parsed: dict, capacity_kw: float, voltage_kv: float,
                cable_schedule: list[dict]) -> str:
    """Build the full SVG single line diagram."""

    svg = ET.Element("svg", xmlns="http://www.w3.org/2000/svg",
                     width="800", height="400",
                     viewBox=f"0 0 {VIEW_W} {VIEW_H}")

    # white background
    ET.SubElement(svg, "rect", width=f"{VIEW_W}", height=f"{VIEW_H}", fill="white")

    # title
    _label(svg, VIEW_W / 2, 22, f"Single Line Diagram  |  {capacity_kw:.0f} kW  |  {voltage_kv:.0f} kV POC",
           size="11", bold=True)

    # Defs for reuse
    defs = ET.SubElement(svg, "defs")
    # arrowhead marker
    marker = ET.SubElement(defs, "marker", id="arrow", markerWidth="6", markerHeight="4",
                           refX="5", refY="2", orient="auto")
    ET.SubElement(marker, "polygon", points="0,0 6,2 0,4", fill=STROKE)

    gen_sources = parsed["solar"] + parsed["bess"]
    n_strings = len(gen_sources)
    # Limit to 6 visible strings max (else diagram gets too tall)
    show_strings = min(n_strings, 5)
    total_height = STAGE_Y_START + show_strings * STRING_SPACING + 40
    mid_y = STAGE_Y_START + (show_strings - 1) * STRING_SPACING / 2

    # ---- Stage labels ----
    for sx, sl in [(X_GEN, "GENERATION"), (X_COMBINER, "COMBINER"),
                   (X_INVERTER, "INVERTER"), (X_XFMR, "TRANSFORMER"),
                   (X_BREAKER, "PROTECTION"), (X_GRID, "GRID")]:
        _label(svg, sx, VIEW_H - 8, sl, size="7", bold=True)

    # ---- Draw each generation string ----
    combiner_y_points: list[float] = []
    string_v = _calc_string_voltage()

    for i in range(show_strings):
        src = gen_sources[i]
        cy = STAGE_Y_START + i * STRING_SPACING
        combiner_y_points.append(cy)

        is_bess = "bess" in src.get("name", "").lower() or "battery" in src.get("name", "").lower()

        if is_bess:
            _svg_bess(svg, X_GEN, cy, label=f"{src['name']}\n{src['capacity_kw']:.0f} kW")
        else:
            _svg_pv_cell(svg, X_GEN, cy, label=f"{src['name']}\n{src['capacity_kw']:.0f} kWp")

        # Wire: source -> combiner
        _wire(svg, X_GEN + 18, cy, X_COMBINER - 14, cy)
        # voltage tag on DC string
        _voltage_tag(svg, (X_GEN + X_COMBINER) / 2, cy - 10, f"{string_v:.0f}V DC")

    if n_strings > show_strings:
        dots_y = STAGE_Y_START + show_strings * STRING_SPACING - 20
        _label(svg, X_GEN, dots_y, f"... +{n_strings - show_strings} more", size="7")

    # ---- DC Combiner ----
    _svg_combiner(svg, X_COMBINER, mid_y, n_in=n_strings)
    # vertical bus at combiner connecting all strings
    if len(combiner_y_points) > 1:
        _svg_bus_bar(svg, X_COMBINER, combiner_y_points[0] - 5,
                     combiner_y_points[-1] + 5)

    # ---- Wire: combiner -> inverter ----
    _wire(svg, X_COMBINER + 14, mid_y, X_INVERTER - 16, mid_y)
    _voltage_tag(svg, (X_COMBINER + X_INVERTER) / 2, mid_y - 10, f"{string_v:.0f}V DC")

    # ---- Inverter ----
    inv = parsed["inverters"][0]
    _svg_inverter(svg, X_INVERTER, mid_y,
                  label=f"{inv['name']}\n{inv['capacity_kw']:.0f} kW")

    # ---- Wire: inverter -> transformer (AC LV) ----
    _wire(svg, X_INVERTER + 16, mid_y, X_XFMR - 18, mid_y)
    _voltage_tag(svg, (X_INVERTER + X_XFMR) / 2, mid_y - 10, "400V AC")

    # ---- Transformer ----
    xfmr = parsed["transformers"][0]
    _svg_transformer(svg, X_XFMR, mid_y,
                     v_primary="0.4 kV", v_secondary=f"{voltage_kv:.0f} kV")

    # ---- Wire: transformer -> breaker ----
    _wire(svg, X_XFMR + 18, mid_y, X_BREAKER - 20, mid_y)
    _voltage_tag(svg, (X_XFMR + X_BREAKER) / 2, mid_y - 10, f"{voltage_kv:.0f}kV AC")

    # ---- Circuit breaker ----
    _svg_breaker(svg, X_BREAKER - 10, mid_y)

    # ---- Meter ----
    _svg_meter(svg, X_BREAKER + 20, mid_y)

    # ---- Wire: meter -> grid ----
    _wire(svg, X_BREAKER + 32, mid_y, X_GRID - 18, mid_y)

    # ---- Grid POC ----
    _svg_grid_symbol(svg, X_GRID, mid_y)
    _label(svg, X_GRID, mid_y + 24, "Grid POC", size="8", bold=True)
    _label(svg, X_GRID, mid_y + 34, f"{voltage_kv:.0f} kV", size="7")

    # ---- Legend box (bottom-left) ----
    lx, ly = 10, VIEW_H - 55
    ET.SubElement(svg, "rect", x=f"{lx}", y=f"{ly}", width="180", height="45",
                  stroke="#cccccc", fill="#fafafa", **{"stroke-width": "0.5"}, rx="3")
    _label(svg, lx + 5, ly + 12, f"Total capacity: {capacity_kw:.0f} kW", size="7", anchor="start")
    _label(svg, lx + 5, ly + 22, f"Strings: {n_strings}  |  Inverters: {len(parsed['inverters'])}", size="7", anchor="start")
    _label(svg, lx + 5, ly + 32, f"Grid voltage: {voltage_kv:.0f} kV  |  BESS: {len(parsed['bess'])}", size="7", anchor="start")
    _label(svg, lx + 5, ly + 42, "Princeps Auto-SLD", size="6", anchor="start")

    return ET.tostring(svg, encoding="unicode", xml_declaration=False)


# ---------------------------------------------------------------------------
# Component list builder
# ---------------------------------------------------------------------------

def _build_components(parsed: dict, capacity_kw: float,
                      voltage_kv: float) -> list[dict]:
    """Return structured list of all SLD components."""
    comps: list[dict] = []

    for arr in parsed["solar"]:
        comps.append({
            "type": "solar_array", "name": arr["name"],
            "capacity_kw": arr["capacity_kw"],
            "voltage": f"{_calc_string_voltage():.0f}V DC",
            "stage": "generation",
        })

    for b in parsed["bess"]:
        comps.append({
            "type": "bess", "name": b["name"],
            "capacity_kw": b["capacity_kw"],
            "capacity_kwh": b.get("capacity_kwh", b["capacity_kw"] * 2),
            "voltage": "800V DC",
            "stage": "generation",
        })

    n_strings = len(parsed["solar"]) + len(parsed["bess"])
    comps.append({
        "type": "dc_combiner", "name": "DC Combiner Box",
        "inputs": n_strings, "stage": "combination",
    })

    for inv in parsed["inverters"]:
        comps.append({
            "type": "inverter", "name": inv["name"],
            "capacity_kw": inv["capacity_kw"],
            "input_voltage": f"{_calc_string_voltage():.0f}V DC",
            "output_voltage": "400V AC",
            "stage": "conversion",
        })

    for xfmr in parsed["transformers"]:
        comps.append({
            "type": "transformer", "name": xfmr["name"],
            "capacity_kva": xfmr["capacity_kva"],
            "primary_voltage": "0.4 kV",
            "secondary_voltage": f"{voltage_kv:.0f} kV",
            "stage": "transformation",
        })

    comps.append({
        "type": "circuit_breaker", "name": "MV Circuit Breaker",
        "voltage": f"{voltage_kv:.0f} kV",
        "stage": "protection",
    })

    comps.append({
        "type": "meter", "name": "Revenue Meter",
        "voltage": f"{voltage_kv:.0f} kV",
        "stage": "metering",
    })

    comps.append({
        "type": "grid_connection", "name": "Grid POC",
        "voltage": f"{voltage_kv:.0f} kV",
        "stage": "grid",
    })

    return comps


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_sld(assets: list[dict], capacity_kw: float,
                 voltage_kv: float = 33) -> dict:
    """Generate a Single Line Diagram for a solar/BESS installation.

    Args:
        assets: List of placed assets with type, capacity, name fields.
        capacity_kw: Total site generation capacity in kW.
        voltage_kv: Grid connection voltage in kV (default 33).

    Returns:
        {
            "svg": str,              # Complete SVG markup
            "components": list,      # Structured component list
            "cable_schedule": list,   # Cable sizing schedule
        }
    """
    parsed = _parse_assets(assets, capacity_kw)
    cable_schedule = _build_cable_schedule(parsed, capacity_kw, voltage_kv)
    svg = _render_svg(parsed, capacity_kw, voltage_kv, cable_schedule)
    components = _build_components(parsed, capacity_kw, voltage_kv)

    return {
        "svg": svg,
        "components": components,
        "cable_schedule": cable_schedule,
    }


# ===========================================================================
# Matplotlib-based pragmatic SLD (SVG + PNG) — used by the Grid Connection
# Report. Renders a grid-source to site topology with breaker symbols, suitable
# for inclusion in a G99 pack or a DNO submission.
# ===========================================================================

def _draw_breaker(ax, x: float, y: float, size: float = 0.35) -> None:
    """Draw a circuit-breaker symbol — square with internal X."""
    import matplotlib.patches as mpatches
    s = size
    ax.add_patch(mpatches.Rectangle((x - s / 2, y - s / 2), s, s,
                                     fill=False, lw=1.6, edgecolor="#111"))
    ax.plot([x - s / 2, x + s / 2], [y - s / 2, y + s / 2],
             color="#111", lw=1.0)
    ax.plot([x + s / 2, x - s / 2], [y - s / 2, y + s / 2],
             color="#111", lw=1.0)


def _draw_transformer(ax, x: float, y: float, v_primary: str, v_secondary: str,
                       rating: str | None = None) -> None:
    """Draw a two-coil transformer symbol."""
    import matplotlib.patches as mpatches
    r = 0.25
    ax.add_patch(mpatches.Circle((x - 0.12, y), r, fill=False, lw=1.6,
                                   edgecolor="#111"))
    ax.add_patch(mpatches.Circle((x + 0.12, y), r, fill=False, lw=1.6,
                                   edgecolor="#111"))
    ax.text(x, y + r + 0.18, v_primary, ha="center", va="bottom", fontsize=8)
    ax.text(x, y - r - 0.10, v_secondary, ha="center", va="top", fontsize=8)
    if rating:
        ax.text(x, y - r - 0.28, rating, ha="center", va="top",
                 fontsize=7, color="#555", style="italic")


def _draw_busbar(ax, x_start: float, x_end: float, y: float,
                  label: str | None = None) -> None:
    """Draw a horizontal busbar (thick line)."""
    ax.plot([x_start, x_end], [y, y], color="#111", lw=3.2, solid_capstyle="butt")
    if label:
        ax.text((x_start + x_end) / 2, y + 0.15, label,
                 ha="center", va="bottom", fontsize=8, fontweight="bold")


def _draw_grid_source(ax, x: float, y: float, voltage_kv: float,
                       fault_level_ka: float | None) -> None:
    """Draw the DNO grid source symbol — circle with lightning bolt."""
    import matplotlib.patches as mpatches
    ax.add_patch(mpatches.Circle((x, y), 0.38, fill=False, lw=2, edgecolor="#111"))
    ax.text(x, y, "\u26A1", ha="center", va="center", fontsize=18)
    label = f"DNO Grid  {voltage_kv:.0f} kV"
    ax.text(x, y + 0.6, label, ha="center", va="bottom",
             fontsize=9, fontweight="bold")
    if fault_level_ka:
        ax.text(x, y - 0.55, f"Fault level: {fault_level_ka:.1f} kA",
                 ha="center", va="top", fontsize=7, color="#555")


def _draw_feeder(ax, x: float, y_top: float, y_bot: float, kind: str,
                  rating_kw: float, label: str) -> None:
    """Draw a vertical feeder with breaker + termination symbol."""
    import matplotlib.patches as mpatches
    # Wire from busbar
    ax.plot([x, x], [y_top, y_top - 0.35], color="#111", lw=1.3)
    # Breaker
    _draw_breaker(ax, x, y_top - 0.55, size=0.28)
    # Wire down to symbol
    ax.plot([x, x], [y_top - 0.69, y_bot + 0.35], color="#111", lw=1.3)
    # Terminal symbol
    if kind == "pv":
        ax.add_patch(mpatches.Rectangle((x - 0.24, y_bot - 0.10), 0.48, 0.32,
                                         fill=False, lw=1.4, edgecolor="#111"))
        ax.plot([x - 0.18, x + 0.18], [y_bot + 0.06, y_bot + 0.16],
                 color="#111", lw=1.0)
        ax.annotate("", xy=(x - 0.28, y_bot - 0.20), xytext=(x - 0.42, y_bot - 0.36),
                     arrowprops=dict(arrowstyle="->", color="#d4a018", lw=1.2))
        ax.text(x, y_bot - 0.35, f"PV\n{rating_kw:.0f} kW",
                 ha="center", va="top", fontsize=7, fontweight="bold")
    elif kind == "bess":
        ax.plot([x - 0.22, x + 0.22], [y_bot + 0.10, y_bot + 0.10],
                 color="#111", lw=3.0)
        ax.plot([x - 0.14, x + 0.14], [y_bot + 0.00, y_bot + 0.00],
                 color="#111", lw=1.5)
        ax.text(x, y_bot - 0.20, f"BESS\n{rating_kw:.0f} kW",
                 ha="center", va="top", fontsize=7, fontweight="bold")
    elif kind == "dc_load":
        ax.add_patch(mpatches.FancyBboxPatch(
            (x - 0.30, y_bot - 0.08), 0.60, 0.28,
            boxstyle="round,pad=0.02", fill=True,
            facecolor="#1a1a2e", edgecolor="#111", lw=1.2))
        ax.text(x, y_bot + 0.06, "DC LOAD", ha="center", va="center",
                 fontsize=7, color="#d4a018", fontweight="bold")
        ax.text(x, y_bot - 0.22, f"{rating_kw:.0f} kW",
                 ha="center", va="top", fontsize=7, fontweight="bold")
    else:
        ax.add_patch(mpatches.Circle((x, y_bot + 0.05), 0.16,
                                       fill=False, lw=1.4, edgecolor="#111"))
        ax.text(x, y_bot - 0.22, label, ha="center", va="top", fontsize=7)


def _render_grid_sld_matplotlib(
    *,
    site_voltage_kv: float,
    poc_voltage_kv: float,
    poc_name: str,
    fault_level_ka: float | None,
    feeders: list[dict],
    site_name: str | None = None,
) -> tuple[str, bytes]:
    """Pragmatic grid-connection SLD rendered with matplotlib.

    Topology (left → right):
        DNO grid source → POC CB → step-down/up xfmr → LV busbar →
        [PV | BESS | DC LOAD] feeders each with their own breaker.

    Returns:
        (svg_string, png_bytes)
    """
    import io

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Canvas sizing — one column per feeder plus header
    n_feed = max(1, len(feeders))
    fig_w = 2.4 + n_feed * 1.1
    fig_w = max(8.5, min(fig_w, 14.0))
    fig, ax = plt.subplots(figsize=(fig_w, 5.6), dpi=150)
    ax.set_xlim(0, fig_w)
    ax.set_ylim(0, 6)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.patch.set_facecolor("white")

    # Title
    title = site_name or "Grid Connection Single Line Diagram"
    ax.text(fig_w / 2, 5.65,
             f"{title}  |  {poc_voltage_kv:.0f} kV POC at {poc_name}",
             ha="center", va="center", fontsize=11, fontweight="bold")

    # Grid source (top-left)
    x_grid = 1.1
    y_grid = 4.6
    _draw_grid_source(ax, x_grid, y_grid, poc_voltage_kv, fault_level_ka)

    # POC breaker
    x_poc = x_grid + 1.1
    _draw_breaker(ax, x_poc, y_grid, size=0.3)
    ax.text(x_poc, y_grid + 0.35, "POC\nCB", ha="center", va="bottom", fontsize=7)
    ax.plot([x_grid + 0.38, x_poc - 0.15], [y_grid, y_grid],
             color="#111", lw=1.4)
    ax.plot([x_poc + 0.15, x_poc + 0.80], [y_grid, y_grid],
             color="#111", lw=1.4)

    # DNO substation bar
    x_sub_l = x_poc + 0.80
    x_sub_r = x_sub_l + 1.1
    _draw_busbar(ax, x_sub_l, x_sub_r, y_grid,
                  label=f"DNO {poc_voltage_kv:.0f} kV Bus")

    # Step-down transformer (to LV busbar)
    x_xfmr = (x_sub_l + x_sub_r) / 2
    ax.plot([x_xfmr, x_xfmr], [y_grid, y_grid - 0.7],
             color="#111", lw=1.4)
    _draw_transformer(ax, x_xfmr, y_grid - 1.05,
                      v_primary=f"{poc_voltage_kv:.0f} kV",
                      v_secondary=f"{site_voltage_kv:.2f} kV",
                      rating="Step-down")
    ax.plot([x_xfmr, x_xfmr], [y_grid - 1.55, y_grid - 2.1],
             color="#111", lw=1.4)

    # Site LV/MV busbar
    y_bus = y_grid - 2.2
    x_bus_l = 1.4
    x_bus_r = fig_w - 0.6
    _draw_busbar(ax, x_bus_l, x_bus_r, y_bus,
                  label=f"Site {site_voltage_kv:.2f} kV Busbar")

    # Feeders
    if feeders:
        span = x_bus_r - x_bus_l - 0.8
        step = span / max(1, n_feed - 1) if n_feed > 1 else 0
        x0 = x_bus_l + 0.4
        y_bot = y_bus - 1.3
        for i, fd in enumerate(feeders):
            xf = x0 + i * step if n_feed > 1 else (x_bus_l + x_bus_r) / 2
            _draw_feeder(ax, xf, y_bus, y_bot,
                          kind=fd.get("kind", "pv"),
                          rating_kw=float(fd.get("rating_kw", 0.0)),
                          label=fd.get("label", ""))

    # Footer annotations
    ax.text(0.2, 0.4,
             "Princeps auto-SLD  |  per ENA EREC G99 Issue 1 Amdt 11",
             fontsize=7, color="#555")
    ax.text(fig_w - 0.2, 0.4,
             "Symbols: IEC 60617 / BS 3939",
             ha="right", fontsize=7, color="#555")

    # Emit SVG + PNG
    svg_buf = io.StringIO()
    fig.savefig(svg_buf, format="svg", bbox_inches="tight",
                 facecolor="white", edgecolor="none")
    png_buf = io.BytesIO()
    fig.savefig(png_buf, format="png", dpi=150, bbox_inches="tight",
                 facecolor="white", edgecolor="none")
    plt.close(fig)

    return svg_buf.getvalue(), png_buf.getvalue()


def generate_grid_connection_sld(
    *,
    site_voltage_kv: float = 0.4,
    poc_voltage_kv: float = 33.0,
    poc_name: str = "DNO Primary",
    fault_level_ka: float | None = None,
    feeders: list[dict] | None = None,
    capacity_kw: float = 5000.0,
    site_name: str | None = None,
) -> dict:
    """Generate a pragmatic grid-connection SLD (SVG + PNG + base64 PNG).

    Topology: DNO grid source → POC breaker → DNO substation bar →
    step-down transformer → site busbar → [PV | BESS | DC load] feeders.

    Args:
        site_voltage_kv:   Site-side (secondary) voltage (e.g. 0.4 kV).
        poc_voltage_kv:    Point of connection voltage (e.g. 33 kV).
        poc_name:          Substation / POC name for labelling.
        fault_level_ka:    Optional DNO fault level at POC.
        feeders:           List of {kind: 'pv'|'bess'|'dc_load', rating_kw, label}.
                           If None, a single PV feeder of `capacity_kw` is shown.
        capacity_kw:       Default total capacity if feeders is None.
        site_name:         Optional project / site name for the title.

    Returns:
        {
            'svg':        str,    # full SVG markup
            'png_bytes':  bytes,  # raw PNG
            'png_base64': str,    # base64 PNG for HTML embedding
            'feeders':    list,   # echoed feeder list
            'meta':       dict,   # topology summary
        }
    """
    import base64

    if feeders is None:
        feeders = [{"kind": "pv", "rating_kw": capacity_kw, "label": "PV Site"}]

    svg, png_bytes = _render_grid_sld_matplotlib(
        site_voltage_kv=site_voltage_kv,
        poc_voltage_kv=poc_voltage_kv,
        poc_name=poc_name,
        fault_level_ka=fault_level_ka,
        feeders=feeders,
        site_name=site_name,
    )

    return {
        "svg": svg,
        "png_bytes": png_bytes,
        "png_base64": base64.b64encode(png_bytes).decode("ascii"),
        "feeders": feeders,
        "meta": {
            "site_voltage_kv": site_voltage_kv,
            "poc_voltage_kv": poc_voltage_kv,
            "poc_name": poc_name,
            "fault_level_ka": fault_level_ka,
            "renderer": "matplotlib",
        },
    }
