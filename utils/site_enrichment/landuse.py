"""Land use via GEE DynamicWorld.

Dispatches ``utils/geeflow_runner.py --mode land_use`` in the ``.venv-geeflow``
Python.  Because GEE calls are slow (~1-3 s), the top-level enricher applies
its own 800 ms timeout and this sub-enricher will typically be listed under
``errors[]`` for interactive use.  When the enricher is invoked with a longer
budget (e.g. nightly pre-warm) the result lands in the payload.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("princeps.site_enrichment.landuse")

_GEE_PYTHON = os.environ.get(
    "GEEFLOW_PYTHON",
    str(Path(__file__).resolve().parent.parent.parent / ".venv-geeflow" / "bin" / "python"),
)
_RUNNER = str(Path(__file__).resolve().parent.parent / "geeflow_runner.py")
_GEE_PROJECT = os.environ.get("GEE_PROJECT", "hopeful-subject-486905-e5")


_CLASSES = [
    "water", "trees", "grass", "flooded_vegetation", "crops",
    "shrub_and_scrub", "built", "bare", "snow_and_ice",
]


async def lookup(
    lat: float,
    lon: float,
    *,
    radius_km: float = 0.1,
    year: Optional[int] = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    """Dominant DynamicWorld class at the point (10 m pixel)."""
    if not Path(_GEE_PYTHON).is_file():
        return {
            "dominant": None,
            "confidence": None,
            "class_distribution": {},
            "todo": f"GEE python at {_GEE_PYTHON} not found. Create .venv-geeflow and pip install earthengine-api.",
        }

    from datetime import datetime as _dt
    yr = year or (_dt.utcnow().year - 1)

    cmd = [
        _GEE_PYTHON, _RUNNER,
        "--mode", "land_use",
        "--lat", str(lat),
        "--lon", str(lon),
        "--radius_km", str(radius_km),
        "--year", str(yr),
        "--gee_project", _GEE_PROJECT,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise ValueError(f"landuse: GEE subprocess timed out after {timeout_s}s") from exc
    except (OSError, ValueError) as exc:
        raise ValueError(f"landuse: subprocess launch failed: {exc}") from exc

    if proc.returncode != 0:
        msg = (stderr.decode(errors="replace") if stderr else "unknown").splitlines()[-1:]
        raise ValueError(f"landuse: runner failed: {msg[0] if msg else 'no stderr'}")

    try:
        payload = json.loads(stdout.decode())
    except json.JSONDecodeError as exc:
        raise ValueError(f"landuse: invalid JSON from runner: {exc}") from exc

    # geeflow_runner output shape: {"class_percentages": {...}, "dominant_class": "...", ...}
    dist = payload.get("class_percentages") or payload.get("class_pcts") or {}
    dominant = payload.get("dominant_class") or (max(dist.items(), key=lambda kv: kv[1])[0] if dist else None)
    conf = dist.get(dominant) if dominant else None

    return {
        "dominant": dominant,
        "confidence": round(float(conf), 3) if conf is not None else None,
        "class_distribution": {k: round(float(v), 4) for k, v in dist.items() if k in _CLASSES},
    }
