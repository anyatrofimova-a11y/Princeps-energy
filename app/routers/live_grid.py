"""Live grid data — real-time BMRS + National Grid ESO + Carbon Intensity feeds."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Query

from utils.bmrs_wholesale import (
    fetch_system_prices,
    fetch_day_ahead_prices,
    current_wholesale_price,
)

log = logging.getLogger("princeps.live_grid")
router = APIRouter(prefix="/api/live", tags=["live-grid"])

_TIMEOUT = 10
_UA = "Princeps/1.0"
_BMRS = "https://data.elexon.co.uk/bmrs/api/v1"
_CARBON = "https://api.carbonintensity.org.uk"


async def _get(client: httpx.AsyncClient, url: str, params: dict = None) -> dict | list | None:
    try:
        resp = await client.get(url, params={**(params or {}), "format": "json"})
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        log.debug("API call failed: %s — %s", url, e)
    return None


@router.get("/snapshot")
async def live_snapshot():
    """
    Real-time GB electricity system snapshot from BMRS + Carbon Intensity API.
    Returns demand, generation by fuel, wind/solar forecasts, system price,
    frequency, carbon intensity — all from live public APIs.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        # Fire all requests concurrently
        results = await asyncio.gather(
            _get(client, f"{_BMRS}/demand/outturn"),
            _get(client, f"{_BMRS}/generation/outturn/summary"),
            _get(client, f"{_BMRS}/forecast/demand/day-ahead"),
            _get(client, f"{_BMRS}/forecast/generation/wind"),
            _get(client, f"{_BMRS}/system/frequency"),
            _get(client, f"{_BMRS}/balancing/pricing/market-index", {
                "from": (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"),
                "to": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }),
            _get(client, f"{_CARBON}/intensity"),
            _get(client, f"{_CARBON}/generation"),
            return_exceptions=True,
        )

        demand_raw, gen_raw, demand_fc, wind_fc, freq_raw, price_raw, carbon_raw, gen_mix_raw = [
            r if not isinstance(r, Exception) else None for r in results
        ]

    snapshot = {"timestamp": datetime.now(timezone.utc).isoformat(), "sources": []}

    # Demand outturn
    if demand_raw:
        records = demand_raw if isinstance(demand_raw, list) else demand_raw.get("data", [])
        if records:
            latest = records[-1] if isinstance(records[-1], dict) else {}
            snapshot["demand"] = {
                "current_mw": latest.get("initialTransmissionSystemDemandOutturn") or latest.get("initialDemandOutturn") or latest.get("demand"),
                "settlement_period": latest.get("settlementPeriod"),
                "settlement_date": latest.get("settlementDate"),
            }
            snapshot["sources"].append("bmrs_demand")

    # Generation by fuel type
    if gen_raw:
        fuels = gen_raw if isinstance(gen_raw, list) else gen_raw.get("data", [])
        gen_summary = {}
        for f in fuels:
            fuel = f.get("fuelType") or f.get("psrType", "unknown")
            mw = f.get("currentMW") or f.get("quantity") or 0
            if fuel and mw:
                gen_summary[fuel] = round(float(mw))
        if gen_summary:
            total = sum(gen_summary.values())
            renewable_types = {"WIND", "SOLAR", "HYDRO", "BIOMASS", "OTHER"}
            renewable_mw = sum(v for k, v in gen_summary.items() if any(r in k.upper() for r in renewable_types))
            snapshot["generation"] = {
                "by_fuel": gen_summary,
                "total_mw": total,
                "renewable_mw": renewable_mw,
                "renewable_pct": round(renewable_mw / total * 100, 1) if total > 0 else 0,
            }
            snapshot["sources"].append("bmrs_generation")

    # Day-ahead demand forecast
    if demand_fc:
        records = demand_fc if isinstance(demand_fc, list) else demand_fc.get("data", [])
        if records:
            forecast_points = []
            for r in records[:48]:  # next 24 hours (half-hourly)
                forecast_points.append({
                    "settlement_period": r.get("settlementPeriod"),
                    "demand_mw": r.get("transmissionSystemDemand"),
                    "date": r.get("settlementDate"),
                })
            snapshot["demand_forecast"] = {
                "source": "BMRS_NDF",
                "horizon": "day_ahead",
                "points": len(forecast_points),
                "data": forecast_points,
            }
            snapshot["sources"].append("bmrs_demand_forecast")

    # Wind forecast
    if wind_fc:
        records = wind_fc if isinstance(wind_fc, list) else wind_fc.get("data", [])
        if records:
            wind_points = []
            for r in records[:48]:
                wind_points.append({
                    "time": r.get("startTime"),
                    "generation_mw": r.get("generation"),
                    "capacity_mw": r.get("capacity"),
                })
            latest_wind = records[0] if records else {}
            snapshot["wind"] = {
                "current_mw": latest_wind.get("generation"),
                "capacity_mw": latest_wind.get("capacity"),
                "forecast_points": len(wind_points),
                "forecast": wind_points,
            }
            snapshot["sources"].append("bmrs_wind_forecast")

    # System frequency
    if freq_raw:
        records = freq_raw if isinstance(freq_raw, list) else freq_raw.get("data", [])
        if records:
            latest = records[0] if isinstance(records[0], dict) else {}
            snapshot["frequency"] = {
                "hz": latest.get("frequency"),
                "timestamp": latest.get("reportSnapshotTime"),
            }
            snapshot["sources"].append("bmrs_frequency")

    # Market index price
    if price_raw:
        records = price_raw if isinstance(price_raw, list) else price_raw.get("data", [])
        if records:
            latest = records[-1] if isinstance(records[-1], dict) else {}
            snapshot["price"] = {
                "market_index_gbp_mwh": latest.get("price"),
                "volume_mwh": latest.get("volume"),
                "settlement_period": latest.get("settlementPeriod"),
                "data_provider": latest.get("dataProvider"),
            }
            snapshot["sources"].append("bmrs_price")

    # Carbon intensity
    if carbon_raw:
        data = carbon_raw.get("data", [{}])
        if data:
            intensity = data[0].get("intensity", {}) if isinstance(data[0], dict) else {}
            snapshot["carbon"] = {
                "actual_gco2_kwh": intensity.get("actual"),
                "forecast_gco2_kwh": intensity.get("forecast"),
                "index": intensity.get("index"),
            }
            snapshot["sources"].append("carbon_intensity_api")

    # Generation mix from Carbon Intensity API
    if gen_mix_raw:
        data = gen_mix_raw.get("data", {})
        if isinstance(data, dict):
            mix = data.get("generationmix", [])
            snapshot["generation_mix"] = [
                {"fuel": g.get("fuel"), "perc": g.get("perc")}
                for g in mix
            ]
            snapshot["sources"].append("carbon_intensity_genmix")

    return snapshot


@router.get("/demand-forecast")
async def live_demand_forecast(
    hours_ahead: int = Query(48, ge=1, le=168),
):
    """Day-ahead and 2-day-ahead demand forecast from BMRS NDF/TSDF."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        day_after = (now + timedelta(days=2)).strftime("%Y-%m-%d")

        ndf, tsdf = await asyncio.gather(
            _get(client, f"{_BMRS}/forecast/demand/day-ahead"),
            _get(client, f"{_BMRS}/forecast/demand/day-ahead", {"settlementDate": day_after}),
        )

    points = []
    for src in [ndf, tsdf]:
        if src:
            records = src if isinstance(src, list) else src.get("data", [])
            for r in records:
                points.append({
                    "date": r.get("settlementDate"),
                    "settlement_period": r.get("settlementPeriod"),
                    "demand_mw": r.get("transmissionSystemDemand"),
                })

    return {
        "source": "BMRS_NDF",
        "points": len(points),
        "data": points[:hours_ahead * 2],  # half-hourly
    }


@router.get("/wind-solar-forecast")
async def live_wind_solar_forecast():
    """BMRS wind and solar generation forecast for next 48 hours."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        wind, solar = await asyncio.gather(
            _get(client, f"{_BMRS}/forecast/generation/wind"),
            _get(client, f"{_BMRS}/forecast/generation/solar"),
        )

    result = {}
    for name, data in [("wind", wind), ("solar", solar)]:
        if data:
            records = data if isinstance(data, list) else data.get("data", [])
            result[name] = [
                {
                    "time": r.get("startTime"),
                    "generation_mw": r.get("generation"),
                    "capacity_mw": r.get("capacity"),
                }
                for r in records[:96]
            ]

    return result


@router.get("/generation-mix")
async def live_generation_mix():
    """Current GB generation mix by fuel type from BMRS + Carbon Intensity API."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        bmrs, carbon = await asyncio.gather(
            _get(client, f"{_BMRS}/generation/outturn/summary"),
            _get(client, f"{_CARBON}/generation"),
        )

    result = {"timestamp": datetime.now(timezone.utc).isoformat()}

    # BMRS generation
    if bmrs:
        fuels = bmrs if isinstance(bmrs, list) else bmrs.get("data", [])
        result["bmrs"] = {}
        for f in fuels:
            fuel = f.get("fuelType") or f.get("psrType")
            mw = f.get("currentMW") or f.get("quantity")
            if fuel and mw:
                result["bmrs"][fuel] = round(float(mw))

    # Carbon Intensity API generation mix (cleaner data)
    if carbon:
        data = carbon.get("data", {})
        if isinstance(data, dict):
            result["mix"] = data.get("generationmix", [])
            result["from"] = data.get("from")
            result["to"] = data.get("to")

    return result


@router.get("/system-price")
async def live_system_price():
    """BMRS system buy/sell prices and market index for current settlement period."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        market, system = await asyncio.gather(
            _get(client, f"{_BMRS}/balancing/pricing/market-index"),
            _get(client, f"{_BMRS}/balancing/pricing/system-price"),
        )

    result = {"timestamp": datetime.now(timezone.utc).isoformat()}

    if market:
        records = market if isinstance(market, list) else market.get("data", [])
        if records:
            result["market_index"] = [
                {
                    "price_gbp_mwh": r.get("price"),
                    "volume_mwh": r.get("volume"),
                    "settlement_period": r.get("settlementPeriod"),
                    "provider": r.get("dataProvider"),
                }
                for r in records[-10:]
            ]

    if system:
        records = system if isinstance(system, list) else system.get("data", [])
        if records:
            result["system_price"] = [
                {
                    "sell_price_gbp_mwh": r.get("systemSellPrice"),
                    "buy_price_gbp_mwh": r.get("systemBuyPrice"),
                    "settlement_period": r.get("settlementPeriod"),
                    "date": r.get("settlementDate"),
                }
                for r in records[-10:]
            ]

    return result


@router.get("/carbon-regional")
async def live_carbon_regional():
    """Regional carbon intensity across all 17 UK regions."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        resp = await _get(client, f"{_CARBON}/regional")

    if not resp:
        return {"error": "Carbon Intensity API unavailable"}

    data = resp.get("data", [])
    regions = []
    if data and isinstance(data[0], dict):
        for region in data[0].get("regions", []):
            intensity = region.get("intensity", {})
            gen_mix = region.get("generationmix", [])
            regions.append({
                "region_id": region.get("regionid"),
                "shortname": region.get("shortname"),
                "dnoregion": region.get("dnoregion"),
                "intensity_forecast": intensity.get("forecast"),
                "intensity_index": intensity.get("index"),
                "generation_mix": {g["fuel"]: g["perc"] for g in gen_mix} if gen_mix else {},
            })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "regions": sorted(regions, key=lambda r: r.get("intensity_forecast") or 999),
    }


# ── Wholesale price endpoints (real BMRS data) ──────────────────────


@router.get("/wholesale-prices")
async def live_wholesale_prices(days: int = Query(7, ge=1, le=30)):
    """Historical system buy/sell prices from BMRS DETSYSPRICES."""
    return await fetch_system_prices(days_back=days)


@router.get("/day-ahead-prices")
async def live_day_ahead_prices(date: str = Query(None)):
    """Today's (or specified date's) day-ahead market index prices."""
    return await fetch_day_ahead_prices(date=date)


@router.get("/current-price")
async def live_current_price():
    """Single latest wholesale price for revenue calculations."""
    return await current_wholesale_price()
