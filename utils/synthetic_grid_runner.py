"""
Synthetic Grid Runner — Princeps PowerGridSynth substitute (Task #19).

PowerGridSynth (TU Delft) is not published openly, so Princeps synthesises
its own realistic UK distribution-network topologies on demand. We build
a pure-Python topology (132/33/11kV ring-fed network with UK cable
parameters) which can be serialised to CGMES (IEC 61970-552) and is
shaped to be replayable through pandapower for power-flow studies in
the .venv-grid worker process when one is available.

Originally designed as a subprocess script (pandapower needed Python
≤3.12), but pandapower is now an OPTIONAL dependency — when missing we
just skip the power-flow sanity check. This means the runner works on
the main Python 3.14 backend on Fly without requiring .venv-grid.
"""

from __future__ import annotations

import json
import math
import random
import sys
import traceback
import uuid
from typing import Any


# UK distribution cable parameters (R, X ohm/km; nominal current kA)
CABLE_PARAMS = {
    11:  {"r_ohm_per_km": 0.411, "x_ohm_per_km": 0.101, "c_nf_per_km": 240, "max_i_ka": 0.300},
    33:  {"r_ohm_per_km": 0.130, "x_ohm_per_km": 0.115, "c_nf_per_km": 180, "max_i_ka": 0.490},
    66:  {"r_ohm_per_km": 0.060, "x_ohm_per_km": 0.110, "c_nf_per_km": 160, "max_i_ka": 0.650},
    132: {"r_ohm_per_km": 0.035, "x_ohm_per_km": 0.105, "c_nf_per_km": 140, "max_i_ka": 0.850},
}

# Typical UK transformer S-ratings by voltage (MVA)
TRAFO_MVA = {(132, 33): 60.0, (132, 11): 30.0, (33, 11): 20.0}


def _offset(centre: dict, dx_km: float, dy_km: float) -> tuple[float, float]:
    """Project (dx, dy) in km from the WGS84 centre."""
    lat = centre["lat"] + dy_km / 111.0
    lon = centre["lon"] + dx_km / (111.0 * max(math.cos(math.radians(centre["lat"])), 0.1))
    return lat, lon


def synthesise(params: dict[str, Any]) -> dict[str, Any]:
    """Build a realistic UK distribution network topology — pure Python,
    no external solver dependencies. Returns a JSON-serialisable dict
    describing buses, lines, transformers, and a pandapower-compatible
    network JSON (which can be imported via pp.from_json when pandapower
    is later available).
    """
    name = params.get("name") or f"synth-{uuid.uuid4().hex[:8]}"
    dno_proxy = params.get("dno_proxy", "NGED")
    primary_kv = int(params.get("voltage_kv") or 33)
    n_primary = max(2, int(params.get("n_primary_busbars") or 6))
    n_secondary = max(1, int(params.get("n_secondary_per_primary") or 3))
    capacity_mw = float(params.get("target_capacity_mw") or 60)
    diversity = float(params.get("load_diversity") or 0.7)
    seed = int(params.get("seed") or 42)
    centre = params.get("centre") or {"lat": 52.0, "lon": -1.5}

    rng = random.Random(seed)

    buses: list[dict] = []
    lines: list[dict] = []
    trafos: list[dict] = []
    loads: list[dict] = []
    bus_id = 0

    def add_bus(kv: int, name_: str, lat: float, lon: float, kind: str) -> int:
        nonlocal bus_id
        buses.append({"id": bus_id, "name": name_, "voltage_kv": kv,
                       "lat": lat, "lon": lon, "kind": kind})
        bus_id += 1
        return bus_id - 1

    def add_line(from_id: int, to_id: int, kv: int, length_km: float, name_: str) -> None:
        cp = CABLE_PARAMS.get(kv, CABLE_PARAMS[33])
        lines.append({
            "from": from_id, "to": to_id, "voltage_kv": kv,
            "length_km": round(length_km, 3),
            "r_ohm_per_km": cp["r_ohm_per_km"],
            "x_ohm_per_km": cp["x_ohm_per_km"],
            "c_nf_per_km": cp["c_nf_per_km"],
            "max_i_ka": cp["max_i_ka"],
            "name": name_,
        })

    def add_trafo(hv_id: int, lv_id: int, hv_kv: int, lv_kv: int, name_: str) -> None:
        sn = TRAFO_MVA.get((hv_kv, lv_kv), 20.0)
        vk = 12.0 if hv_kv >= 132 else 8.0
        trafos.append({
            "hv_bus": hv_id, "lv_bus": lv_id,
            "hv_kv": hv_kv, "lv_kv": lv_kv,
            "sn_mva": sn, "vk_percent": vk, "vkr_percent": 0.5,
            "name": name_,
        })

    # GSP at 132kV (source)
    gsp_lat, gsp_lon = _offset(centre, 0, 0)
    gsp = add_bus(132, f"{name}-GSP-132kV", gsp_lat, gsp_lon, "gsp")

    # BSP at primary kV
    bsp_lat, bsp_lon = _offset(centre, 0, 1)
    bsp = add_bus(primary_kv, f"{name}-BSP-{primary_kv}kV", bsp_lat, bsp_lon, "bsp")
    add_trafo(gsp, bsp, 132, primary_kv, f"{name}-T1")

    # Ring of primary busbars
    primary_buses: list[int] = []
    for i in range(n_primary):
        angle = 2 * math.pi * i / n_primary
        lat, lon = _offset(centre, 2.5 * math.cos(angle), 2.5 * math.sin(angle) + 2)
        p = add_bus(primary_kv, f"{name}-Primary-{i+1}-{primary_kv}kV", lat, lon, "primary")
        primary_buses.append(p)
        add_line(bsp, p, primary_kv, 1.0 + rng.uniform(0.5, 2.0), f"{name}-Feeder-{i+1}")

    # Close the ring (N-1 redundancy)
    for i in range(n_primary):
        nxt = (i + 1) % n_primary
        add_line(primary_buses[i], primary_buses[nxt], primary_kv,
                  1.0 + rng.uniform(0.3, 1.5), f"{name}-Ring-{i+1}-{nxt+1}")

    # 11kV secondaries with loads
    per_load_mw = (capacity_mw * diversity) / max(1, n_primary * n_secondary)
    for i, pb in enumerate(primary_buses):
        for j in range(n_secondary):
            base_lat = buses[2 + i]["lat"]
            base_lon = buses[2 + i]["lon"]
            sec_lat = base_lat + (j - n_secondary / 2) * 0.005
            sec_lon = base_lon + (j - n_secondary / 2) * 0.005
            sb = add_bus(11, f"{name}-Sec-{i+1}.{j+1}-11kV", sec_lat, sec_lon, "secondary")
            add_trafo(pb, sb, primary_kv, 11, f"{name}-T{i+1}.{j+1}")
            loads.append({
                "bus": sb, "p_mw": round(per_load_mw, 3),
                "q_mvar": round(per_load_mw * 0.33, 3),
                "name": f"{name}-Load-{i+1}.{j+1}",
            })

    summary = {
        "name": name, "dno_proxy": dno_proxy,
        "voltage_levels_kv": sorted({132, primary_kv, 11}),
        "n_buses": len(buses), "n_lines": len(lines),
        "n_trafos": len(trafos), "n_loads": len(loads),
        "n_primary_busbars": n_primary, "n_secondary_per_primary": n_secondary,
        "target_capacity_mw": capacity_mw, "load_diversity": diversity,
        "ring_topology": True, "n_minus_1_capable": True,
    }

    # Optional power flow sanity check via pandapower if available
    pf_result, pp_json = _try_pandapower(name, buses, lines, trafos, loads, gsp, summary)

    return {
        "success": True, "name": name,
        "n_buses": len(buses),
        "summary": summary,
        "topology": {"buses": buses, "lines": lines, "trafos": trafos, "loads": loads},
        "pandapower_json": pp_json,           # may be None if pandapower unavailable
        "power_flow":     pf_result,         # may be None if pandapower unavailable
    }


def _try_pandapower(name: str, buses: list[dict], lines: list[dict],
                    trafos: list[dict], loads: list[dict], gsp_id: int,
                    summary: dict) -> tuple[dict | None, str | None]:
    """Run a pandapower power flow if pandapower is importable; return
    (power_flow_summary, pandapower_json) — or (None, None) if not."""
    try:
        import pandapower as pp
    except ImportError:
        return None, None

    try:
        net = pp.create_empty_network(name=name)
        bus_map: dict[int, int] = {}
        for b in buses:
            idx = pp.create_bus(net, vn_kv=float(b["voltage_kv"]),
                                 name=b["name"], geodata=(b["lon"], b["lat"]))
            bus_map[b["id"]] = idx
        pp.create_ext_grid(net, bus_map[gsp_id], vm_pu=1.02, name=f"{name}-Source")
        for ln in lines:
            pp.create_line_from_parameters(
                net, bus_map[ln["from"]], bus_map[ln["to"]],
                length_km=ln["length_km"],
                r_ohm_per_km=ln["r_ohm_per_km"], x_ohm_per_km=ln["x_ohm_per_km"],
                c_nf_per_km=ln["c_nf_per_km"], max_i_ka=ln["max_i_ka"],
                name=ln["name"],
            )
        for tf in trafos:
            pp.create_transformer_from_parameters(
                net, hv_bus=bus_map[tf["hv_bus"]], lv_bus=bus_map[tf["lv_bus"]],
                sn_mva=tf["sn_mva"], vn_hv_kv=float(tf["hv_kv"]),
                vn_lv_kv=float(tf["lv_kv"]),
                vkr_percent=tf["vkr_percent"], vk_percent=tf["vk_percent"],
                pfe_kw=10.0, i0_percent=0.1, shift_degree=30.0, name=tf["name"],
            )
        for ld in loads:
            pp.create_load(net, bus_map[ld["bus"]], p_mw=ld["p_mw"],
                            q_mvar=ld["q_mvar"], name=ld["name"])
        pp.runpp(net, algorithm="nr", calculate_voltage_angles=True)
        return ({
            "converged": True,
            "max_vm_pu": float(net.res_bus["vm_pu"].max()),
            "min_vm_pu": float(net.res_bus["vm_pu"].min()),
            "max_line_loading_pct": float(net.res_line["loading_percent"].max() or 0),
        }, pp.to_json(net))
    except Exception as exc:  # noqa: BLE001
        return ({"converged": False, "error": str(exc)}, None)


if __name__ == "__main__":
    try:
        params = json.loads(sys.stdin.read() or "{}")
        print(json.dumps(synthesise(params), default=str))
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)
