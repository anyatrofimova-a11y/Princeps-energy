"""Electrical Single-Line Diagram generator — turns a design layout doc
into a directed graph (nodes + edges) that ReactFlow can render.

Workload-aware: BESS wires each pad → PCS → transformer → busbar → MV line
→ grid; Solar chains modules → strings → inverters → LV panel → transformer
→ busbar → grid; DC routes HV in → transformers → UPS → PDUs → server halls.

Output format matches the ReactFlow node/edge schema so the frontend can
feed it straight into <ReactFlow /> with no munging.
"""

from __future__ import annotations

from typing import Any


NODE_TYPES = {
    "grid":        {"icon": "🏭", "color": "#4B5563"},
    "busbar":      {"icon": "═",  "color": "#1F2937"},
    "transformer": {"icon": "⚡", "color": "#F59E0B"},
    "pcs":         {"icon": "▥",  "color": "#2563EB"},
    "inverter":    {"icon": "▨",  "color": "#2563EB"},
    "battery":     {"icon": "🔋", "color": "#16A34A"},
    "pv_array":    {"icon": "☀", "color": "#F5B731"},
    "server_hall": {"icon": "🏢", "color": "#6B7280"},
    "ups":         {"icon": "⏻",  "color": "#7C3AED"},
    "pdu":         {"icon": "⫽",  "color": "#0891B2"},
}


def _node(id_, type_, label, **kwargs):
    return {
        "id": id_,
        "type": "default",
        "data": {"label": label, "kind": type_,
                 "icon": NODE_TYPES.get(type_, {}).get("icon", "◻"),
                 "color": NODE_TYPES.get(type_, {}).get("color", "#111"),
                 **kwargs},
        "position": kwargs.get("_pos", {"x": 0, "y": 0}),
    }


def _edge(src, dst, label=None, kind="power"):
    return {
        "id": f"{src}→{dst}",
        "source": src, "target": dst,
        "label": label,
        "data": {"kind": kind},
        "type": "smoothstep",
    }


def build_sld(doc: dict) -> dict[str, Any]:
    workload = (doc.get("workload") or "bess").lower()
    params = doc.get("params", {})
    kpis = doc.get("kpis", {})
    sub = doc.get("substation") or {}
    cap = float(kpis.get("effective_capacity_mw") or params.get("capacity_mw") or 0)
    voltage = "132 kV" if cap >= 30 else "33 kV"

    nodes: list[dict] = []
    edges: list[dict] = []

    # Grid + busbar always present
    nodes.append(_node("grid", "grid",
                       f"Grid · {sub.get('name') or 'DNO'}",
                       voltage=voltage,
                       _pos={"x": 600, "y": 40}))
    nodes.append(_node("bus_hv", "busbar", f"HV busbar {voltage}",
                       _pos={"x": 600, "y": 140}))
    edges.append(_edge("grid", "bus_hv", voltage))

    if workload == "bess":
        pads = max(1, int(round(cap / 10)))
        for i in range(pads):
            x = 80 + i * 180
            tx = f"tx_{i}"; pcs = f"pcs_{i}"; bat = f"bat_{i}"
            nodes.append(_node(tx, "transformer", f"TX-{i+1} · 10 MVA", _pos={"x": x, "y": 240}))
            nodes.append(_node(pcs, "pcs",         f"PCS-{i+1} · 10 MW", _pos={"x": x, "y": 340}))
            nodes.append(_node(bat, "battery",     f"BESS-{i+1} · 10 MW / {params.get('duration_h', 2) * 10:g} MWh",
                               _pos={"x": x, "y": 440}))
            edges += [
                _edge("bus_hv", tx, voltage),
                _edge(tx, pcs, "LV"),
                _edge(pcs, bat, "DC"),
            ]
    elif workload == "solar":
        # Represent as arrays → inverters → transformer
        arrays = max(1, int(round(cap / 2.5)))
        for i in range(arrays):
            x = 80 + i * 200
            arr = f"arr_{i}"; inv = f"inv_{i}"; tx = f"tx_{i}"
            nodes.append(_node(arr, "pv_array", f"Array {i+1} · 2.5 MWdc",
                               _pos={"x": x, "y": 440}))
            nodes.append(_node(inv, "inverter",  f"INV-{i+1} · 2500 kVA",
                               _pos={"x": x, "y": 340}))
            nodes.append(_node(tx, "transformer", f"TX-{i+1} · 2500 kVA",
                               _pos={"x": x, "y": 240}))
            edges += [
                _edge(arr, inv, "DC"),
                _edge(inv, tx, "LV"),
                _edge(tx, "bus_hv", voltage),
            ]
    elif workload == "dc":
        pue = float(params.get("pue_target") or 1.2)
        total_mw = cap * pue
        halls = max(1, int(round(cap / 10)))
        nodes.append(_node("hv_tx", "transformer", f"HV TX · {total_mw:.1f} MVA",
                           _pos={"x": 600, "y": 240}))
        nodes.append(_node("bus_lv", "busbar", "LV busbar 11 kV",
                           _pos={"x": 600, "y": 340}))
        edges += [_edge("bus_hv", "hv_tx", voltage), _edge("hv_tx", "bus_lv", "11 kV")]
        for i in range(halls):
            x = 120 + i * 240
            ups = f"ups_{i}"; pdu = f"pdu_{i}"; hall = f"hall_{i}"
            nodes.append(_node(ups, "ups", f"UPS-{i+1} · 10 MW", _pos={"x": x, "y": 440}))
            nodes.append(_node(pdu, "pdu", f"PDU-{i+1}",         _pos={"x": x, "y": 540}))
            nodes.append(_node(hall, "server_hall", f"Hall {i+1} · 10 MW IT",
                               _pos={"x": x, "y": 640}))
            edges += [
                _edge("bus_lv", ups, "LV"),
                _edge(ups, pdu, "UPS"),
                _edge(pdu, hall, "IT"),
            ]

    return {"nodes": nodes, "edges": edges,
            "workload": workload, "capacity_mw": cap, "voltage": voltage}
