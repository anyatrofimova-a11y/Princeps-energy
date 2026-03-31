"""
NREL reV wrapper — calls rev_runner.py via subprocess in .venv-rev/.

Follows the same subprocess bridge pattern as grid_power_flow.py / sam_runner.py.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent
REV_PYTHON = os.environ.get(
    "REV_PYTHON",
    str(_BASE / ".venv-rev" / "bin" / "python"),
)
REV_RUNNER = str(_BASE / "utils" / "rev_runner.py")


async def compute_supply_curve(
    lon_min: float,
    lat_min: float,
    lon_max: float,
    lat_max: float,
    technology: str = "pv",
    exclusion_layers: list | None = None,
    timeout: int = 300,
) -> dict:
    """
    Run supply curve computation in a subprocess.

    Returns dict with supply curve data, site rankings, exclusion maps.
    """
    payload = {
        "bounds": [lon_min, lat_min, lon_max, lat_max],
        "technology": technology,
    }
    if exclusion_layers:
        payload["exclusion_layers"] = exclusion_layers

    raw_in = json.dumps(payload).encode()

    proc = await asyncio.create_subprocess_exec(
        REV_PYTHON, REV_RUNNER,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(raw_in), timeout=timeout)

    if proc.returncode != 0:
        err = stderr.decode()[:500] if stderr else "Unknown error"
        log.error("reV subprocess failed: %s", err)
        return {"ok": False, "error": f"Supply curve computation failed: {err}"}

    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Failed to parse reV output: {e}"}
