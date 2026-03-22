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
CACHE_TTL = 60  # 1 minute — faster refresh for real-time feeds


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

        # Fetch generation mix (percentages from Carbon Intensity API)
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

        # ── FUELINST — instantaneous generation by fuel type (MW) ──
        # Each record is one fuel type: {fuelType: "WIND", generation: 3088}
        try:
            resp = await client.get(
                "https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELINST",
                params={"format": "json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                records = data if isinstance(data, list) else data.get("data", [])
                if records:
                    # Group by latest settlement period
                    latest_sp = max(r.get("settlementPeriod", 0) for r in records)
                    latest_records = [r for r in records if r.get("settlementPeriod") == latest_sp]

                    fuel_inst = {}
                    for r in latest_records:
                        fuel = (r.get("fuelType") or "").upper()
                        gen = r.get("generation")
                        if fuel and gen is not None:
                            fuel_inst[fuel] = round(float(gen), 1)

                    interconnectors = ["INTFR", "INTIRL", "INTNED", "INTEW", "INTNEM", "INTELEC", "INTIFA2", "INTNSL"]
                    total_gen = sum(v for k, v in fuel_inst.items() if v > 0 and k not in interconnectors)
                    net_imports = sum(fuel_inst.get(k, 0) for k in interconnectors)

                    result["fuel_inst_mw"] = fuel_inst
                    result["total_generation_mw"] = round(total_gen, 1)
                    result["net_imports_mw"] = round(net_imports, 1)
                    result["fuel_inst_timestamp"] = latest_records[0].get("startTime") if latest_records else None
        except Exception as e:
            log.debug("FUELINST fetch failed: %s", e)

        # ── FREQ — system frequency (should be ~50.00 Hz) ──
        # Record format: {dataset: "FREQ", measurementTime: "...", frequency: 50.106}
        try:
            resp = await client.get(
                "https://data.elexon.co.uk/bmrs/api/v1/datasets/FREQ",
                params={"format": "json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                records = data if isinstance(data, list) else data.get("data", [])
                if records:
                    latest = records[-1] if isinstance(records, list) else records
                    freq = latest.get("frequency")
                    if freq is not None:
                        result["frequency_hz"] = round(float(freq), 3)
                        result["freq_timestamp"] = latest.get("measurementTime")
        except Exception as e:
            log.debug("FREQ fetch failed: %s", e)

    _cache = result
    _cache_ts = now
    return result


# ─── System Buy/Sell Prices (DETSYSPRICES) ──────────────────────────────────

_price_cache: dict[str, Any] = {}
_price_cache_ts: float = 0
PRICE_CACHE_TTL = 30  # 30 seconds — settlement period is 30 min


async def get_system_prices() -> dict:
    """Fetch real-time system buy/sell prices from BMRS DETSYSPRICES.

    These are the ACTUAL wholesale prices generators receive — not retail
    tariffs like Octopus Agile. System Buy Price (SBP) is what the system
    pays generators; System Sell Price (SSP) is what generators pay the
    system when short.

    Returns:
        Dict with sell_price_gbp_mwh, buy_price_gbp_mwh, spread_gbp_mwh,
        settlement_period, settlement_date, timestamp.
    """
    global _price_cache, _price_cache_ts

    now = time.time()
    if _price_cache and (now - _price_cache_ts) < PRICE_CACHE_TTL:
        return _price_cache

    result: dict[str, Any] = {
        "sell_price_gbp_mwh": None,
        "buy_price_gbp_mwh": None,
        "spread_gbp_mwh": None,
        "settlement_period": None,
        "settlement_date": None,
        "timestamp": None,
        "source": None,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                "https://data.elexon.co.uk/bmrs/api/v1/datasets/DETSYSPRICES",
                params={"format": "json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                records = data if isinstance(data, list) else data.get("data", [])
                if records:
                    # Take the most recent record
                    latest = records[-1] if isinstance(records, list) else records
                    sell = latest.get("systemSellPrice")
                    buy = latest.get("systemBuyPrice")
                    result["sell_price_gbp_mwh"] = round(float(sell), 2) if sell is not None else None
                    result["buy_price_gbp_mwh"] = round(float(buy), 2) if buy is not None else None
                    if sell is not None and buy is not None:
                        result["spread_gbp_mwh"] = round(float(buy) - float(sell), 2)
                    result["settlement_period"] = latest.get("settlementPeriod")
                    result["settlement_date"] = latest.get("settlementDate")
                    result["timestamp"] = latest.get("createdDateTime") or latest.get("settlementDate")
                    result["source"] = "bmrs_detsysprices"
        except Exception as e:
            log.debug("DETSYSPRICES fetch failed: %s", e)

    _price_cache = result
    _price_cache_ts = now
    return result
