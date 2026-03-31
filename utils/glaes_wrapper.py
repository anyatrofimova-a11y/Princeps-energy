"""
GLAES wrapper — calls glaes_runner.py via subprocess in .venv-atlite/.

Follows the same subprocess bridge pattern as grid_power_flow.py / sam_runner.py.
Uses the atlite venv since glaes shares similar geospatial dependencies.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent
# GLAES can share the atlite venv or use its own
GLAES_PYTHON = os.environ.get(
    "GLAES_PYTHON",
    os.environ.get("ATLITE_PYTHON", str(_BASE / ".venv-atlite" / "bin" / "python")),
)
GLAES_RUNNER = str(_BASE / "utils" / "glaes_runner.py")


async def compute_land_eligibility(
    lon_min: float,
    lat_min: float,
    lon_max: float,
    lat_max: float,
    technology: str = "solar",
    country_code: str = "GB",
    timeout: int = 120,
) -> dict:
    """
    Run land eligibility computation in a subprocess.

    Returns dict with eligible area, exclusion breakdown, GeoJSON.
    """
    payload = {
        "bounds": [lon_min, lat_min, lon_max, lat_max],
        "technology": technology,
        "country_code": country_code,
    }

    raw_in = json.dumps(payload).encode()

    proc = await asyncio.create_subprocess_exec(
        GLAES_PYTHON, GLAES_RUNNER,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(raw_in), timeout=timeout)

    if proc.returncode != 0:
        err = stderr.decode()[:500] if stderr else "Unknown error"
        log.error("GLAES subprocess failed: %s", err)
        return {"ok": False, "error": f"Land eligibility analysis failed: {err}"}

    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Failed to parse GLAES output: {e}"}
