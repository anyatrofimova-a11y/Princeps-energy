# Adapted from TU Delft AI Energy Lab LLM-Electricity-Contracts (BSD-3-Clause).
# Wraps `utils/timeseries_connection_check.py` (24h AC time-series) and
# `utils/outage_window_feasibility.py` (outage window search) — both of which
# are ports of TU Delft scripts by Jochen L. Cremer (arXiv:2505.19551).
"""
24-hour AC time-series feasibility + outage-window feasibility.

Two endpoints, both pandapower-subprocess-backed:

    POST /api/grid/timeseries-feasibility
        body: {project_id, load_profile?, snapshot_hours: 24|8760}
        runs `utils/timeseries_connection_check.py` against the project's
        local grid topology (substations within 20 km + connecting lines).

    POST /api/grid/outage-window
        body: {project_id, asset_type, asset_id, outage_window: {start_hour, end_hour}}
        runs `utils/outage_window_feasibility.py` to test the requested window
        and propose alternative windows in the same horizon.

Both endpoints share the GRID_PYTHON env-var contract (defaults to
`<repo>/.venv-grid/bin/python`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import asyncpg

from app.deps import get_pool

log = logging.getLogger(__name__)

router = APIRouter(tags=["timeseries_feasibility"])


# ─── Subprocess wiring ─────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_GRID_PYTHON = _REPO_ROOT / ".venv-grid" / "bin" / "python"
_TIMESERIES_SCRIPT = _REPO_ROOT / "utils" / "timeseries_connection_check.py"
_OUTAGE_SCRIPT = _REPO_ROOT / "utils" / "outage_window_feasibility.py"

# 8760h run can take 60-180s on a 50-bus net; 24h runs in <2s. Cap at 5 min.
_SUBPROCESS_TIMEOUT_SEC = 300


def _grid_python() -> str:
    return os.environ.get("GRID_PYTHON") or str(_DEFAULT_GRID_PYTHON)


async def _run_grid_subprocess(script: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Spawn `<GRID_PYTHON> <script>` and pipe JSON. Returns parsed JSON."""
    python = _grid_python()
    if not Path(python).exists():
        return {
            "success": False,
            "error": f"grid python not found at {python} (set GRID_PYTHON env)",
        }
    if not script.exists():
        return {"success": False, "error": f"script not found: {script}"}

    try:
        proc = await asyncio.create_subprocess_exec(
            python, str(script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(json.dumps(payload).encode("utf-8")),
            timeout=_SUBPROCESS_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        return {"success": False, "error": "subprocess timed out"}
    except FileNotFoundError as exc:
        return {"success": False, "error": f"exec failed: {exc}"}

    if proc.returncode != 0:
        err_tail = (stderr or b"").decode("utf-8", errors="replace")[-800:]
        return {
            "success": False,
            "error": f"subprocess exit {proc.returncode}",
            "stderr_tail": err_tail,
        }

    try:
        return json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "success": False,
            "error": f"subprocess returned non-JSON: {exc}",
            "stdout_tail": stdout.decode("utf-8", errors="replace")[-800:],
        }


# ─── Topology fetcher ──────────────────────────────────────────────────
async def _load_project_topology(
    conn: asyncpg.Connection,
    project_id: UUID,
    radius_km: float = 20.0,
) -> dict[str, Any]:
    """Pull the project row + nearby substations + lines, return the
    payload shape the subprocess scripts expect."""
    proj = await conn.fetchrow(
        "SELECT project_id, name, lat, lon, capacity_mw, technology "
        "FROM projects WHERE project_id = $1",
        project_id,
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if proj["lat"] is None or proj["lon"] is None:
        raise HTTPException(status_code=400, detail="Project has no lat/lon")

    # Re-use the grid_connection_analyser helpers so topology stays
    # consistent with /api/grid/power-flow.
    from utils.grid_connection_analyser import (
        _find_nearest_substations,
        _fetch_grid_lines,
        _synthesise_lines,
    )

    substations = await _find_nearest_substations(
        conn, float(proj["lat"]), float(proj["lon"]), radius_km, 10
    )
    if not substations:
        raise HTTPException(
            status_code=422,
            detail=f"No substations within {radius_km} km of project",
        )

    sub_ids = [s["id"] for s in substations]
    lines = await _fetch_grid_lines(conn, sub_ids)
    if not lines:
        lines = _synthesise_lines(substations)

    # `updated_at` from DB row is a datetime — strip it (JSON not happy).
    for s in substations:
        s.pop("updated_at", None)
        s.pop("external_id", None)
        s.pop("region", None)
        s.pop("site_type", None)
        s.pop("rag_demand", None)
        s.pop("rag_generation", None)

    return {
        "project": {
            "id": str(proj["project_id"]),
            "name": proj["name"],
            "lat": float(proj["lat"]),
            "lon": float(proj["lon"]),
            "capacity_mw": float(proj["capacity_mw"]) if proj["capacity_mw"] else 5.0,
            "technology": proj["technology"] or "solar",
        },
        "substations": substations,
        "lines": lines,
    }


def _proposed_block(topology: dict[str, Any]) -> dict[str, Any]:
    """Build the `proposed` connection block from the project record."""
    proj = topology["project"]
    return {
        "capacity_mw": proj["capacity_mw"],
        "technology": proj["technology"],
        "connection_substation_id": topology["substations"][0]["id"],
        "power_factor": 0.95,
    }


# ─── Pydantic request bodies ───────────────────────────────────────────
class TimeseriesRequest(BaseModel):
    project_id: str
    load_profile: Optional[dict[str, Any]] = None
    snapshot_hours: int = Field(default=24, ge=1, le=8760)
    voltage_limits: Optional[list[float]] = None  # [low, high]
    loading_limits: Optional[list[float]] = None  # [low, high]


class OutageWindowSpec(BaseModel):
    start_hour: int = Field(ge=0, le=8760)
    end_hour: int = Field(ge=1, le=8760)


class OutageRequest(BaseModel):
    project_id: str
    asset_type: str = Field(pattern="^(generator|line)$")
    asset_id: str
    outage_window: OutageWindowSpec
    load_profile: Optional[dict[str, Any]] = None
    snapshot_hours: int = Field(default=168, ge=24, le=8760)


# ─── Endpoints ────────────────────────────────────────────────────────
@router.post("/api/grid/timeseries-feasibility")
async def post_timeseries_feasibility(
    body: TimeseriesRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """24-hour (or up to 8760-hour) AC time-series feasibility check.

    Returns per-hour voltage and loading series plus the structured
    feasibility verdict from `utils/timeseries_connection_check.py`.
    """
    try:
        project_id = UUID(body.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project_id UUID")

    async with pool.acquire() as conn:
        topology = await _load_project_topology(conn, project_id)

    options: dict[str, Any] = {"snapshot_hours": body.snapshot_hours}
    if body.voltage_limits and len(body.voltage_limits) == 2:
        options["voltage_limits"] = body.voltage_limits
    if body.loading_limits and len(body.loading_limits) == 2:
        options["loading_limits"] = body.loading_limits

    payload = {
        "substations": topology["substations"],
        "lines": topology["lines"],
        "proposed": _proposed_block(topology),
        "load_profile": body.load_profile,
        "options": options,
    }

    t0 = time.time()
    result = await _run_grid_subprocess(_TIMESERIES_SCRIPT, payload)
    result["elapsed_s"] = round(time.time() - t0, 2)
    result["project_id"] = str(project_id)
    result["network_size"] = {
        "substations": len(topology["substations"]),
        "lines": len(topology["lines"]),
    }
    return result


@router.post("/api/grid/outage-window")
async def post_outage_window(
    body: OutageRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Outage-window feasibility check.

    Tests whether the requested outage window violates voltage / thermal
    limits anywhere on the local network; if it does, returns up to 5
    alternative windows in the same horizon.
    """
    try:
        project_id = UUID(body.project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project_id UUID")

    if body.outage_window.end_hour <= body.outage_window.start_hour:
        raise HTTPException(
            status_code=400, detail="outage_window.end_hour must be > start_hour"
        )

    async with pool.acquire() as conn:
        topology = await _load_project_topology(conn, project_id)

    payload = {
        "substations": topology["substations"],
        "lines": topology["lines"],
        "proposed": _proposed_block(topology),
        "load_profile": body.load_profile,
        "outage": {
            "asset_type": body.asset_type,
            "asset_id": body.asset_id,
            "start_hour": body.outage_window.start_hour,
            "end_hour": body.outage_window.end_hour,
        },
        "options": {"snapshot_hours": body.snapshot_hours},
    }

    t0 = time.time()
    result = await _run_grid_subprocess(_OUTAGE_SCRIPT, payload)
    result["elapsed_s"] = round(time.time() - t0, 2)
    result["project_id"] = str(project_id)
    return result


@router.get("/api/grid/timeseries-feasibility/health")
async def health() -> dict[str, Any]:
    """Quick health check — does the GRID_PYTHON interpreter exist?"""
    python = _grid_python()
    return {
        "grid_python": python,
        "grid_python_exists": Path(python).exists(),
        "timeseries_script_exists": _TIMESERIES_SCRIPT.exists(),
        "outage_script_exists": _OUTAGE_SCRIPT.exists(),
    }
