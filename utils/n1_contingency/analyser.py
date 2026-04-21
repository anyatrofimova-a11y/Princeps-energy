"""Per-substation N-1 contingency analyser.

For one target substation we:

    1. Gather the **local subnetwork** — every substation within 2 electrical
       hops on the `grid_lines` table, plus every connecting line.
    2. Hand that subnetwork to the pandapower subprocess
       (`utils/grid_power_flow.py`) **with** `options.contingency = true`,
       which runs an N-1 sweep on every line and transformer.
    3. Parse the returned per-outage results: we flag overloads > 100%,
       attribute them to downstream feeders, and estimate the restoration
       path + BSC P2/7 downtime.
    4. Build one `N1Contingency` record.

Why 2 hops? A primary substation's reliability is dominated by its upstream
BSP/GSP transformer + the incoming feeder pair. Going further out increases
runtime super-linearly and adds noise — 3-hop adjacency starts catching
unrelated meshed-network outages that don't actually supply the target.

The subprocess call is **timeout-bounded** (default 120 s) and any non-zero
exit code degrades the record to a failed_outages=1 event rather than
raising — the batch runner has tens of thousands of calls to make and one
pathological network must not poison the whole run.

Usage
-----
    from utils.n1_contingency.analyser import run_substation_n1
    record = await run_substation_n1(substation_id=42, pool=pool)
    print(record.reliability_score_0_100, record.worst_case_overload_pct)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

import asyncpg

from .schema import (
    MODEL_VERSION,
    N1Contingency,
    N1Event,
    derive_downtime_hours,
    derive_reliability_score,
    derive_restoration_path,
)

log = logging.getLogger("princeps.n1_contingency.analyser")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# UUID5 namespace so the same integer substation id always maps to the same
# UUID across batch runs (lets us upsert on PRIMARY KEY cleanly).
PRINCEPS_NAMESPACE = uuid.UUID("1f5b8c3d-1a0c-4a7f-9e7a-9e7a0c3b5f00")

# Path to the pandapower subprocess bridge.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_GRID_POWER_FLOW = _REPO_ROOT / "utils" / "grid_power_flow.py"

# Python interpreter in the .venv-grid env (pandapower-compatible Python 3.12).
# Matches the existing `GRID_PYTHON` env-var contract used elsewhere in the
# backend; we fall back to system python as a last resort for tests.
GRID_PYTHON_ENV = "GRID_PYTHON"
_DEFAULT_GRID_PYTHON = _REPO_ROOT / ".venv-grid" / "bin" / "python"

# Subprocess timeout — a single N-1 sweep over ~20 upstream assets on a
# 50-bus pandapower network runs in 2-20 s; 120 s is a generous ceiling.
SUBPROCESS_TIMEOUT_SEC = 120

# Hop radius for upstream asset gathering.
ELECTRICAL_HOPS = 2


# ---------------------------------------------------------------------------
# UUID derivation
# ---------------------------------------------------------------------------
def substation_uuid(db_id: int) -> uuid.UUID:
    """Deterministic UUID5 from `grid_substations.id` (SERIAL int)."""
    return uuid.uuid5(PRINCEPS_NAMESPACE, f"grid_substations:{db_id}")


# ---------------------------------------------------------------------------
# Upstream topology walk
# ---------------------------------------------------------------------------
async def gather_upstream_assets(
    conn: asyncpg.Connection,
    substation_id: int,
    hops: int = ELECTRICAL_HOPS,
) -> dict[str, Any]:
    """Return a dict of {substations, lines} describing the local subnetwork.

    Walks `grid_lines` starting from the target substation up to `hops`
    electrical hops. Uses a simple BFS because the DNO line graph is small
    (max ~50 neighbours at 2 hops for a primary).
    """
    visited: set[int] = {substation_id}
    frontier: set[int] = {substation_id}
    line_ids: set[int] = set()

    for _ in range(hops):
        if not frontier:
            break
        rows = await conn.fetch(
            """
            SELECT id, from_sub_id, to_sub_id, voltage_kv, circuits, length_km, osm_id, operator
              FROM grid_lines
             WHERE (from_sub_id = ANY($1::int[]) OR to_sub_id = ANY($1::int[]))
            """,
            list(frontier),
        )
        next_frontier: set[int] = set()
        for r in rows:
            line_ids.add(r["id"])
            for side in (r["from_sub_id"], r["to_sub_id"]):
                if side is not None and side not in visited:
                    visited.add(side)
                    next_frontier.add(side)
        frontier = next_frontier

    # Pull every visited substation's full record.
    sub_rows = await conn.fetch(
        """
        SELECT id, name, dno, voltage_kv, demand_mw, generation_mw,
               transformer_rating_mva, fault_level_ka,
               ST_Y(ST_Transform(geom, 4326)) AS lat,
               ST_X(ST_Transform(geom, 4326)) AS lon
          FROM grid_substations
         WHERE id = ANY($1::int[])
        """,
        list(visited),
    )
    substations = [
        {
            "id": int(r["id"]),
            "name": r["name"] or f"sub_{r['id']}",
            "dno": r["dno"],
            "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] is not None else 33.0,
            "demand_mw": float(r["demand_mw"]) if r["demand_mw"] is not None else 0.0,
            "generation_mw": float(r["generation_mw"]) if r["generation_mw"] is not None else 0.0,
            "transformer_rating_mva": (
                float(r["transformer_rating_mva"]) if r["transformer_rating_mva"] is not None else None
            ),
            "fault_level_ka": (
                float(r["fault_level_ka"]) if r["fault_level_ka"] is not None else None
            ),
            "lat": float(r["lat"]) if r["lat"] is not None else None,
            "lon": float(r["lon"]) if r["lon"] is not None else None,
        }
        for r in sub_rows
    ]

    line_rows = await conn.fetch(
        """
        SELECT id, from_sub_id, to_sub_id, voltage_kv, circuits, length_km, operator
          FROM grid_lines
         WHERE id = ANY($1::int[])
        """,
        list(line_ids),
    )
    lines = [
        {
            "id": int(r["id"]),
            "from_id": int(r["from_sub_id"]) if r["from_sub_id"] else None,
            "to_id": int(r["to_sub_id"]) if r["to_sub_id"] else None,
            "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] is not None else 33.0,
            "circuits": int(r["circuits"]) if r["circuits"] else 1,
            "length_km": float(r["length_km"]) if r["length_km"] is not None else 1.0,
            "operator": r["operator"],
        }
        for r in line_rows
        if r["from_sub_id"] and r["to_sub_id"]
    ]

    return {"substations": substations, "lines": lines}


# ---------------------------------------------------------------------------
# pandapower subprocess driver
# ---------------------------------------------------------------------------
def _grid_python_path() -> str:
    candidate = os.environ.get(GRID_PYTHON_ENV) or str(_DEFAULT_GRID_PYTHON)
    return candidate


def _call_power_flow(payload: dict[str, Any]) -> dict[str, Any]:
    """Run `utils/grid_power_flow.py` as a subprocess with contingency enabled.

    Returns the parsed JSON response. On timeout / non-zero exit / parse
    error, returns a structured error dict (never raises).
    """
    python = _grid_python_path()
    if not Path(python).exists() and python != sys.executable:
        # Fall back to the current interpreter for unit tests without .venv-grid.
        python = sys.executable

    try:
        proc = subprocess.run(
            [python, str(_GRID_POWER_FLOW)],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            timeout=SUBPROCESS_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "pandapower subprocess timed out"}
    except FileNotFoundError as exc:
        return {"success": False, "error": f"grid python missing: {exc}"}

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or b"").decode("utf-8", errors="replace")[-800:]
        return {
            "success": False,
            "error": f"subprocess exit {proc.returncode}",
            "stderr": stderr_tail,
        }

    raw = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    if not raw:
        return {"success": False, "error": "empty subprocess stdout"}
    try:
        return json.loads(raw.splitlines()[-1])  # last line = JSON payload
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"bad JSON from subprocess: {exc}", "raw_tail": raw[-400:]}


# ---------------------------------------------------------------------------
# Parse contingency results into N1Event list
# ---------------------------------------------------------------------------
def _urban_heuristic(voltage_kv: float, demand_mw: float) -> bool:
    """BSC P2/7 urban vs rural classification.

    Proxy rule: high-demand 11 kV primaries and 33 kV BSPs in built-up areas
    hit peak loads >20 MW. No SMD population data here yet, so we use demand
    as the proxy. This is tuned against the UKPN LPN (urban) vs SSEN South
    (rural) distributions.
    """
    if voltage_kv >= 66:
        return True  # BSP / GSP — always urban-SLA by default
    return demand_mw >= 20.0


def parse_contingency(
    target: dict[str, Any],
    subnet: dict[str, Any],
    pf_result: dict[str, Any],
) -> tuple[list[N1Event], int]:
    """Turn a pandapower contingency payload into a list of `N1Event`.

    Returns (events, failed_outage_count). The first element of `pf_result`
    is the base-case power flow; per-outage details are in `contingency`.
    """
    events: list[N1Event] = []
    failed = 0

    contingency = pf_result.get("contingency") or {}
    raw_events = contingency.get("results") or []
    if not raw_events:
        return events, 0

    voltage_kv = float(target.get("voltage_kv") or 33.0)
    demand_mw = float(target.get("demand_mw") or 0.0)
    is_urban = _urban_heuristic(voltage_kv, demand_mw)

    # Map pandapower element names back to grid_lines / grid_substations ids.
    line_name_to_id: dict[str, int] = {}
    for l in subnet.get("lines", []):
        # `grid_power_flow.build_network` generates names `line_{from}_{to}_c{n}`
        # for each circuit; match by prefix.
        base = f"line_{l['from_id']}_{l['to_id']}"
        line_name_to_id[base] = l["id"]
        line_name_to_id[f"line_{l['to_id']}_{l['from_id']}"] = l["id"]

    affected_mw_total = sum(float(s.get("demand_mw") or 0) for s in subnet.get("substations", []))
    has_redundancy = len(subnet.get("lines", [])) >= 2

    for r in raw_events:
        element = str(r.get("element", ""))
        converged = bool(r.get("converged", False))

        # Skip degenerate elements
        if not element:
            continue

        # Classify outage asset type
        if element.startswith("line_line_"):
            outage_type = "line"
        elif element.startswith("line_trafo_"):
            outage_type = "transformer"
        elif element.startswith("trafo_"):
            outage_type = "transformer"
        else:
            outage_type = "line"

        # Strip double prefix — contingency engine emits 'line_line_X_Y_c0' etc.
        stripped = element
        if stripped.startswith("line_line_"):
            stripped = stripped[len("line_"):]
        elif stripped.startswith("line_trafo_"):
            stripped = stripped[len("line_"):]

        # Best-effort DB id lookup
        asset_id = "unknown"
        key = stripped.rsplit("_c", 1)[0]
        if key in line_name_to_id:
            asset_id = f"line:{line_name_to_id[key]}"
        elif outage_type == "transformer":
            asset_id = f"trafo:{stripped}"
        else:
            asset_id = f"line:{stripped}"

        if not converged:
            failed += 1
            events.append(
                N1Event(
                    outage_asset_id=asset_id,
                    outage_asset_type=outage_type,
                    outage_asset_name=stripped,
                    overload_pct=999.0,  # flag as catastrophic / islanded
                    affected_feeders=[stripped],
                    affected_mw=affected_mw_total,
                    est_downtime_hours=derive_downtime_hours(999.0, is_urban),
                    restoration_path="repair_required",
                    converged=False,
                )
            )
            continue

        max_loading = float(r.get("max_loading_pct") or 0.0)
        affected_feeders: list[str] = []
        # If the contingency returned post-fault line loadings, the base
        # result has them too — but the worst case is the one we care about.
        if max_loading > 100:
            affected_feeders.append(stripped)

        # Scale affected MW roughly by overload severity: everything above
        # 100% is "at risk" — if nothing overloads, no demand is at risk.
        affected_mw = affected_mw_total if max_loading > 100 else 0.0

        events.append(
            N1Event(
                outage_asset_id=asset_id,
                outage_asset_type=outage_type,
                outage_asset_name=stripped,
                overload_pct=round(max_loading, 2),
                affected_feeders=affected_feeders,
                affected_mw=round(affected_mw, 2),
                est_downtime_hours=derive_downtime_hours(max_loading, is_urban),
                restoration_path=derive_restoration_path(max_loading, has_redundancy),
                converged=True,
            )
        )

    # Sort worst-first so the top of the list is the most-worrying outage.
    events.sort(key=lambda e: (-e.overload_pct, -e.affected_mw))
    return events, failed


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
async def run_substation_n1(
    substation_id: int,
    pool: asyncpg.Pool,
    hops: int = ELECTRICAL_HOPS,
) -> Optional[N1Contingency]:
    """Run the full N-1 sweep for one substation and return an `N1Contingency`.

    Returns None if the target substation doesn't exist.
    """
    async with pool.acquire() as conn:
        target = await conn.fetchrow(
            """
            SELECT id, name, dno, voltage_kv, demand_mw, generation_mw,
                   ST_Y(ST_Transform(geom, 4326)) AS lat,
                   ST_X(ST_Transform(geom, 4326)) AS lon
              FROM grid_substations
             WHERE id = $1
            """,
            substation_id,
        )
        if not target:
            log.warning("substation_id=%s not found in grid_substations", substation_id)
            return None

        subnet = await gather_upstream_assets(conn, substation_id, hops=hops)

    # If we couldn't find any connecting lines, we can't run a contingency —
    # emit a record with reliability=100 and a note.
    if len(subnet["substations"]) < 2 or not subnet["lines"]:
        return N1Contingency(
            substation_id=substation_uuid(int(target["id"])),
            substation_name=target["name"] or f"sub_{target['id']}",
            voltage_kv=float(target["voltage_kv"] or 33.0),
            dno=target["dno"],
            n1_outage_events=[],
            worst_case_overload_pct=0.0,
            worst_case_affected_mw=0.0,
            reliability_score_0_100=100.0,
            lat=float(target["lat"]) if target["lat"] is not None else None,
            lon=float(target["lon"]) if target["lon"] is not None else None,
            upstream_assets_scanned=0,
            failed_outages=0,
            notes=["No upstream lines within 2 hops — N-1 not applicable or topology data incomplete."],
        )

    target_dict = {
        "id": int(target["id"]),
        "name": target["name"] or f"sub_{target['id']}",
        "voltage_kv": float(target["voltage_kv"] or 33.0),
        "demand_mw": float(target["demand_mw"] or 0.0),
    }

    # Offload the blocking subprocess call to a thread so the asyncio loop
    # stays free for other tasks (the batch runner spawns many in parallel).
    payload = {
        "substations": subnet["substations"],
        "lines": subnet["lines"],
        "proposed": {"capacity_mw": 0, "connection_substation_id": None},
        "options": {
            "contingency": True,
            "max_loading_pct": 100,
            "voltage_limits": [0.94, 1.06],
        },
    }
    pf_result = await asyncio.to_thread(_call_power_flow, payload)

    notes: list[str] = []
    if not pf_result.get("success", True) or not pf_result.get("converged", True):
        err = pf_result.get("error") or "power flow did not converge"
        notes.append(f"Base-case power flow failed: {err}")
        # Emit a best-effort record with score 0 so worst-case maps flag it.
        return N1Contingency(
            substation_id=substation_uuid(int(target["id"])),
            substation_name=target_dict["name"],
            voltage_kv=target_dict["voltage_kv"],
            dno=target["dno"],
            n1_outage_events=[],
            worst_case_overload_pct=0.0,
            worst_case_affected_mw=0.0,
            reliability_score_0_100=0.0,
            lat=float(target["lat"]) if target["lat"] is not None else None,
            lon=float(target["lon"]) if target["lon"] is not None else None,
            upstream_assets_scanned=len(subnet["lines"]),
            failed_outages=len(subnet["lines"]),
            notes=notes,
        )

    events, failed = parse_contingency(target_dict, subnet, pf_result)

    worst_overload = max((e.overload_pct for e in events), default=0.0)
    worst_mw = max((e.affected_mw for e in events), default=0.0)

    score = derive_reliability_score(events)
    if failed > 0:
        notes.append(f"{failed} of {len(events)} contingencies failed to converge.")

    return N1Contingency(
        substation_id=substation_uuid(int(target["id"])),
        substation_name=target_dict["name"],
        voltage_kv=target_dict["voltage_kv"],
        dno=target["dno"],
        n1_outage_events=events,
        worst_case_overload_pct=worst_overload,
        worst_case_affected_mw=worst_mw,
        reliability_score_0_100=score,
        lat=float(target["lat"]) if target["lat"] is not None else None,
        lon=float(target["lon"]) if target["lon"] is not None else None,
        upstream_assets_scanned=len(events),
        failed_outages=failed,
        notes=notes,
        model_version=MODEL_VERSION,
    )
