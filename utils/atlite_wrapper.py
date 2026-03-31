"""
atlite wrapper — calls atlite_runner.py via subprocess in .venv-atlite/.

Follows the same subprocess bridge pattern as grid_power_flow.py / sam_runner.py.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent
ATLITE_PYTHON = os.environ.get(
    "ATLITE_PYTHON",
    str(_BASE / ".venv-atlite" / "bin" / "python"),
)
ATLITE_RUNNER = str(_BASE / "utils" / "atlite_runner.py")


async def compute_capacity_map(
    lon_min: float,
    lat_min: float,
    lon_max: float,
    lat_max: float,
    year: int = 2023,
    technology: str = "pv",
    turbine: str | None = None,
    timeout: int = 300,
) -> dict:
    """
    Run atlite capacity factor computation in a subprocess.

    Returns dict with gridded capacity factors, mean/P50/P90, GeoJSON.
    """
    payload = {
        "bounds": [lon_min, lat_min, lon_max, lat_max],
        "year": year,
        "technology": technology,
    }
    if turbine:
        payload["turbine"] = turbine

    raw_in = json.dumps(payload).encode()

    proc = await asyncio.create_subprocess_exec(
        ATLITE_PYTHON, ATLITE_RUNNER,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(raw_in), timeout=timeout)

    if proc.returncode != 0:
        err = stderr.decode()[:500] if stderr else "Unknown error"
        log.error("atlite subprocess failed: %s", err)
        return {"ok": False, "error": f"atlite computation failed: {err}"}

    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Failed to parse atlite output: {e}"}
