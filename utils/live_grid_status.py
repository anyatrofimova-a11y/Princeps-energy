"""
Live grid status — fetches real-time UK grid metrics.
BMRS demand outturn + carbon intensity from public APIs.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

log = logging.getLogger("princeps.live_grid_status")

# Simple in-memory cache
_cache: dict[str, Any] = {}
_cache_ts: float = 0
CACHE_TTL = 300  # 5 minutes


async def get_live_status() -> dict:
    """Return current UK grid status from public APIs."""
    global _cache, _cache_ts

    now = time.time()
    if _cache and (now - _cache_ts) < CACHE_TTL:
        return _cache

    result = {
        "demand_gw": None,
        "carbon_intensity_gco2_kwh": None,
        "carbon_index": None,
        "generation_mix": {},
        "timestamp": None,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        # Fetch BMRS demand outturn
        try:
            resp = await client.get(
                "https://data.elexon.co.uk/bmrs/api/v1/datasets/INDO",
                params={"format": "json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                records = data if isinstance(data, list) else data.get("data", [])
                if records:
                    latest = records[-1] if isinstance(records, list) else records
                    demand_mw = latest.get("demand") or latest.get("initialDemandOutturn") or latest.get("quantity")
                    if demand_mw is not None:
                        result["demand_gw"] = round(float(demand_mw) / 1000, 1)
                        result["timestamp"] = latest.get("startTime") or latest.get("settlementDate")
        except Exception as e:
            log.debug("BMRS fetch failed: %s", e)

        # Fetch carbon intensity
        try:
            resp = await client.get("https://api.carbonintensity.org.uk/intensity")
            if resp.status_code == 200:
                data = resp.json()
                current = data.get("data", [{}])[0] if data.get("data") else {}
                intensity = current.get("intensity", {})
                result["carbon_intensity_gco2_kwh"] = intensity.get("actual") or intensity.get("forecast")
                result["carbon_index"] = intensity.get("index")  # very low, low, moderate, high, very high
        except Exception as e:
            log.debug("Carbon intensity fetch failed: %s", e)

        # Fetch generation mix
        try:
            resp = await client.get("https://api.carbonintensity.org.uk/generation")
            if resp.status_code == 200:
                data = resp.json()
                gen_mix = data.get("data", {}).get("generationmix", [])
                mix = {}
                for item in gen_mix:
                    fuel = item.get("fuel", "")
                    perc = item.get("perc", 0)
                    if fuel == "wind":
                        mix["wind_pct"] = perc
                    elif fuel == "solar":
                        mix["solar_pct"] = perc
                    elif fuel == "gas":
                        mix["gas_pct"] = perc
                    elif fuel == "nuclear":
                        mix["nuclear_pct"] = perc
                    elif fuel == "biomass":
                        mix["biomass_pct"] = perc
                    elif fuel == "imports":
                        mix["imports_pct"] = perc
                result["generation_mix"] = mix
        except Exception as e:
            log.debug("Generation mix fetch failed: %s", e)

    _cache = result
    _cache_ts = now
    return result
