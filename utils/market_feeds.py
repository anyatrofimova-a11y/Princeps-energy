"""Live UK electricity market feeds — cached 60s.

Wraps:
  - Elexon BMRS (no-auth): Imbalance price, demand, wind/solar live
  - NESO Data Portal: DC/DM/DR clearing, capacity market results
  - Carbon intensity API (already used in pulse/): CO₂ g/kWh
  - Ofgem reference: gas system price → spark/dark spread
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

log = logging.getLogger("princeps.market_feeds")

_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 60  # seconds


def _cache_get(key: str):
    if key not in _CACHE:
        return None
    ts, val = _CACHE[key]
    if time.time() - ts > _CACHE_TTL:
        return None
    return val


def _cache_set(key: str, val):
    _CACHE[key] = (time.time(), val)


async def fetch_wholesale_prices() -> dict[str, Any]:
    """Elexon BMRS day-ahead + imbalance (system sell/buy) prices."""
    cached = _cache_get("wholesale")
    if cached:
        return cached
    out = {
        "day_ahead_gbp_mwh": None,
        "imbalance_gbp_mwh": None,
        "peak_gbp_mwh": 78.0,    # fallback
        "offpeak_gbp_mwh": 42.0,
        "source": "benchmark",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    # System price endpoint
    try:
        now = datetime.now(timezone.utc)
        date = now.strftime("%Y-%m-%d")
        period = max(1, min(48, (now.hour * 2) + (1 if now.minute >= 30 else 0)))
        url = f"https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices/{date}/{period}"
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(url)
        if r.status_code == 200:
            j = r.json()
            items = j.get("data") or []
            if items:
                out["imbalance_gbp_mwh"] = round(float(items[0].get("systemSellPrice") or 0), 2)
                out["source"] = "elexon_live"
    except Exception as e:
        log.debug("Elexon imbalance fetch failed: %s", e)
    _cache_set("wholesale", out)
    return out


async def fetch_as_clearing() -> dict[str, Any]:
    """NESO ancillary service clearing prices (DC/DM/DR).
    Placeholder hits benchmark until we wire the DataPortal feed."""
    cached = _cache_get("as")
    if cached:
        return cached
    out = {
        "dc_gbp_mw_h": 15.2,
        "dm_gbp_mw_h": 6.4,
        "dr_gbp_mw_h": 4.1,
        "ffr_gbp_mw_h": 3.8,
        "source": "benchmark_2026q1",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_set("as", out)
    return out


async def fetch_cap_market() -> dict[str, Any]:
    """Capacity Market T-1 / T-4 auction reference prices."""
    cached = _cache_get("capm")
    if cached:
        return cached
    out = {
        "t4_2027_gbp_kw_yr": 45.0,
        "t1_2026_gbp_kw_yr": 63.0,
        "source": "benchmark_2025_auctions",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_set("capm", out)
    return out


async def fetch_carbon_intensity() -> dict[str, Any]:
    """National Grid ESO carbon intensity — g CO₂ / kWh, now + 30 min forecast."""
    cached = _cache_get("co2")
    if cached:
        return cached
    out = {
        "gco2_kwh": None,
        "band": None,
        "source": "carbonintensity.org.uk",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("https://api.carbonintensity.org.uk/intensity")
        if r.status_code == 200:
            j = r.json()
            row = (j.get("data") or [{}])[0]
            out["gco2_kwh"] = row.get("intensity", {}).get("actual") or row.get("intensity", {}).get("forecast")
            out["band"] = row.get("intensity", {}).get("index")
    except Exception as e:
        log.debug("carbon intensity fetch failed: %s", e)
    _cache_set("co2", out)
    return out


async def live_market_snapshot() -> dict[str, Any]:
    """Everything the MarketRibbon needs in one request."""
    ws, as_, cm, co2 = await asyncio.gather(
        fetch_wholesale_prices(), fetch_as_clearing(),
        fetch_cap_market(), fetch_carbon_intensity(),
        return_exceptions=True,
    )
    return {
        "wholesale": ws if not isinstance(ws, Exception) else None,
        "ancillary": as_ if not isinstance(as_, Exception) else None,
        "capacity_market": cm if not isinstance(cm, Exception) else None,
        "carbon": co2 if not isinstance(co2, Exception) else None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
