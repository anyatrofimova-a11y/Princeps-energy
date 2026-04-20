"""Bill of Materials — aggregate module / inverter / transformer / cable
counts + indicative £ totals from a design layout doc.

Keeps unit-cost assumptions in one place so the same BOM feeds:
  - /api/design/bom (JSON for DesignCanvas BOM tab)
  - /api/design/export (PDF / DWG — reads the BOM block)
  - COA matrix (per-site CAPEX roll-up)

UK-specific benchmarks (2026 Q1). Adjust ``UNIT_COSTS`` when prices move.
"""

from __future__ import annotations

from typing import Any

UNIT_COSTS = {
    # BESS — all-in £/kWh at pad scale (module + BoS + EPC)
    "bess_container_10mw_20mwh_lfp":   ("unit", 3_300_000, "LFP container, 10 MW / 20 MWh, Tier-1 supplier"),
    "bess_container_10mw_40mwh_lfp":   ("unit", 5_800_000, "LFP container, 10 MW / 40 MWh"),
    "bess_transformer_10mva":          ("unit",   180_000, "10 MVA oil-filled transformer"),
    "bess_pcs_10mw":                   ("unit",   420_000, "10 MW power conversion system"),
    "bess_switchgear_33kv":            ("unit",    75_000, "33 kV switchgear cubicle"),

    # Solar PV — per-unit or per-MW rates
    "pv_module_550w":                  ("unit",        70, "Longi Himo6 550 W or equivalent"),
    "pv_inverter_2500kw_central":      ("unit",   155_000, "Central inverter, 2500 kVA"),
    "pv_inverter_125kw_string":        ("unit",    11_500, "String inverter, 125 kW"),
    "pv_transformer_2500kva":          ("unit",    92_000, "Pad-mounted transformer 2500 kVA"),
    "pv_mounting_per_mw":              ("per_mw", 120_000, "Fixed-tilt mounting steel"),
    "pv_cable_dc_per_mw":              ("per_mw",  45_000, "DC cable + combiner"),
    "pv_cable_ac_per_mw":              ("per_mw",  28_000, "AC cable + trenching"),
    "pv_epc_per_mw":                   ("per_mw",  90_000, "EPC + commissioning"),

    # DC — broad indicative £/MW IT-load
    "dc_shell_per_mw":                 ("per_mw", 3_500_000, "Building shell + fit-out"),
    "dc_cooling_per_mw":               ("per_mw", 1_800_000, "Cooling plant (air + water)"),
    "dc_mep_per_mw":                   ("per_mw", 2_200_000, "MEP + UPS + generators"),
    "dc_transformer_per_mw":           ("per_mw",   320_000, "HV/LV transformers"),

    # Shared
    "hv_cable_132kv_per_km":           ("per_km", 500_000, "132 kV underground cable"),
    "hv_cable_33kv_per_km":            ("per_km", 150_000, "33 kV underground cable"),
    "access_road_per_km":              ("per_km",  80_000, "Gravel access road + drainage"),
    "boundary_fence_per_km":           ("per_km",  35_000, "2.4 m chain-link + CCTV"),
    "grid_connection_lump":            ("unit",   250_000, "DNO charges + commissioning"),
}


def _mk(code: str, qty: float, extra: dict | None = None) -> dict:
    meta = UNIT_COSTS.get(code)
    if not meta:
        return {"code": code, "qty": qty, "unit_cost_gbp": None, "total_gbp": None,
                "description": code, "warning": "no benchmark"}
    basis, rate, desc = meta
    total = rate * qty
    row = {
        "code": code, "description": desc, "basis": basis,
        "qty": round(qty, 2), "unit_cost_gbp": rate,
        "total_gbp": round(total, 0),
    }
    if extra:
        row.update(extra)
    return row


def build_bom(doc: dict) -> dict[str, Any]:
    """Given a design doc from /api/design/generate, return a BOM dict."""
    workload = (doc.get("workload") or "bess").lower()
    params = doc.get("params", {})
    kpis = doc.get("kpis", {})
    substation = doc.get("substation") or {}
    cap = float(kpis.get("effective_capacity_mw") or params.get("capacity_mw") or 0)
    duration_h = float(params.get("duration_h") or 2.0)
    mwh = cap * duration_h
    dist_km = float(substation.get("distance_km") or 1.0)

    rows: list[dict] = []

    if workload == "bess":
        # Containers sized to duration
        container_code = ("bess_container_10mw_40mwh_lfp" if duration_h >= 3
                          else "bess_container_10mw_20mwh_lfp")
        pads = max(1, int(round(cap / 10)))
        rows.append(_mk(container_code, pads))
        rows.append(_mk("bess_transformer_10mva", pads))
        rows.append(_mk("bess_pcs_10mw", pads))
        rows.append(_mk("bess_switchgear_33kv", pads))
    elif workload == "solar":
        # 550W modules, ~1.82 kW per module
        modules = int(round(cap * 1_000 / 0.55))
        rows.append(_mk("pv_module_550w", modules))
        # Use central inverters above 5 MW, string below
        if cap >= 5:
            rows.append(_mk("pv_inverter_2500kw_central", max(1, int(cap / 2.5))))
        else:
            rows.append(_mk("pv_inverter_125kw_string", max(1, int(cap * 1000 / 125))))
        rows.append(_mk("pv_transformer_2500kva", max(1, int(cap / 2.5))))
        rows.append(_mk("pv_mounting_per_mw", cap))
        rows.append(_mk("pv_cable_dc_per_mw", cap))
        rows.append(_mk("pv_cable_ac_per_mw", cap))
        rows.append(_mk("pv_epc_per_mw", cap))
    elif workload == "dc":
        rows.append(_mk("dc_shell_per_mw", cap))
        rows.append(_mk("dc_cooling_per_mw", cap))
        rows.append(_mk("dc_mep_per_mw", cap))
        rows.append(_mk("dc_transformer_per_mw", cap))

    # Shared: HV cable to substation, access road, fencing, grid connection
    voltage = "132kv" if cap >= 30 else "33kv"
    rows.append(_mk(f"hv_cable_{voltage}_per_km", dist_km))
    rows.append(_mk("access_road_per_km", max(0.2, dist_km * 0.5)))
    # fencing perimeter: estimate from area (rough sqrt)
    area_ha = (doc.get("layout", {}).get("meta") or {}).get("area_ha") or (cap * 0.1)
    perimeter_km = 4 * (area_ha * 0.01) ** 0.5 if area_ha else 0.5
    rows.append(_mk("boundary_fence_per_km", round(perimeter_km, 2)))
    rows.append(_mk("grid_connection_lump", 1))

    subtotal = sum(r.get("total_gbp") or 0 for r in rows)
    contingency = subtotal * 0.10
    total = subtotal + contingency

    return {
        "workload": workload,
        "capacity_mw": cap,
        "rows": rows,
        "subtotal_gbp": round(subtotal, 0),
        "contingency_pct": 10.0,
        "contingency_gbp": round(contingency, 0),
        "total_gbp": round(total, 0),
        "total_gbp_per_mw": round(total / max(0.01, cap), 0),
        "notes": "UK 2026 Q1 benchmarks; 10% contingency included. Exclude VAT + developer fees.",
    }
