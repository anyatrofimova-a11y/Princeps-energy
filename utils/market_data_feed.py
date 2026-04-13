"""
Real-time market data feed.

Aggregates:
  - BMRS / Elexon: demand, generation, frequency, prices
  - Carbon Intensity API: gCO2/kWh
  - Capacity market reference data

All endpoints are public — no API keys required.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger("princeps.market_feed")

_TIMEOUT = 12
_UA = "Princeps/1.0"
_BMRS = "https://data.elexon.co.uk/bmrs/api/v1"
_CARBON = "https://api.carbonintensity.org.uk"

# Simple in-memory cache (60s TTL)
_cache = {}
_CACHE_TTL = 60


def _cached(key):
    entry = _cache.get(key)
    if entry and (time.time() - entry["t"]) < _CACHE_TTL:
        return entry["v"]
    return None


def _set_cache(key, val):
    _cache[key] = {"v": val, "t": time.time()}


async def _get(client: httpx.AsyncClient, url: str, params: dict = None) -> dict | list | None:
    try:
        resp = await client.get(url, params={**(params or {}), "format": "json"})
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        log.debug("Market API call failed: %s — %s", url, e)
    return None


# ─── Live Snapshot ────────────────────────────────────────────────────────────

async def fetch_live_snapshot() -> dict:
    """Concurrent BMRS + Carbon calls for real-time system snapshot."""
    cached = _cached("live_snapshot")
    if cached:
        return cached

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        results = await asyncio.gather(
            _get(client, f"{_BMRS}/demand/outturn"),
            _get(client, f"{_BMRS}/generation/outturn/summary"),
            _get(client, f"{_BMRS}/system/frequency"),
            _get(client, f"{_BMRS}/balancing/pricing/market-index", {
                "from": (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"),
                "to": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }),
            _get(client, f"{_BMRS}/balancing/settlement/system-prices", {
                "from": (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"),
                "to": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }),
            _get(client, f"{_CARBON}/intensity"),
            return_exceptions=True,
        )

        demand_raw, gen_raw, freq_raw, price_raw, sys_price_raw, carbon_raw = [
            r if not isinstance(r, Exception) else None for r in results
        ]

    snapshot = {"timestamp": datetime.now(timezone.utc).isoformat()}

    # Demand
    if demand_raw:
        records = demand_raw if isinstance(demand_raw, list) else demand_raw.get("data", [])
        if records:
            latest = records[-1] if isinstance(records[-1], dict) else {}
            demand_mw = latest.get("initialTransmissionSystemDemandOutturn") or latest.get("demand") or 0
            snapshot["demand_gw"] = round(float(demand_mw) / 1000, 2) if demand_mw else None
            # Sparkline: last 48 settlement periods
            snapshot["demand_sparkline"] = [
                round(float(r.get("initialTransmissionSystemDemandOutturn") or r.get("demand") or 0) / 1000, 2)
                for r in records[-48:]
            ]

    # Generation by fuel
    if gen_raw:
        fuels = gen_raw if isinstance(gen_raw, list) else gen_raw.get("data", [])
        by_fuel = {}
        for f in fuels:
            fuel = f.get("fuelType") or f.get("psrType", "unknown")
            mw = f.get("currentMW") or f.get("quantity") or 0
            if fuel and mw:
                by_fuel[fuel] = round(float(mw))
        total = sum(by_fuel.values())
        wind_mw = sum(v for k, v in by_fuel.items() if "WIND" in k.upper())
        solar_mw = sum(v for k, v in by_fuel.items() if "SOLAR" in k.upper())
        snapshot["generation"] = {
            "by_fuel": by_fuel,
            "total_mw": total,
            "wind_gw": round(wind_mw / 1000, 2),
            "solar_gw": round(solar_mw / 1000, 2),
            "renewable_pct": round((wind_mw + solar_mw) / total * 100, 1) if total else 0,
        }

    # Frequency
    if freq_raw:
        freq_data = freq_raw if isinstance(freq_raw, list) else freq_raw.get("data", [])
        if freq_data:
            latest = freq_data[-1] if isinstance(freq_data[-1], dict) else {}
            snapshot["frequency_hz"] = latest.get("frequency") or latest.get("systemFrequency")

    # Market price
    if price_raw:
        prices = price_raw if isinstance(price_raw, list) else price_raw.get("data", [])
        if prices:
            latest = prices[-1] if isinstance(prices[-1], dict) else {}
            snapshot["price_gbp_mwh"] = latest.get("dataProviderPrice") or latest.get("price")
            snapshot["price_sparkline"] = [
                round(float(p.get("dataProviderPrice") or p.get("price") or 0), 2)
                for p in prices[-48:]
            ]

    # System buy/sell
    if sys_price_raw:
        sp = sys_price_raw if isinstance(sys_price_raw, list) else sys_price_raw.get("data", [])
        if sp:
            latest = sp[-1] if isinstance(sp[-1], dict) else {}
            snapshot["system_price"] = {
                "buy": latest.get("systemBuyPrice"),
                "sell": latest.get("systemSellPrice"),
            }

    # Carbon intensity
    if carbon_raw and "data" in carbon_raw:
        ci = carbon_raw["data"]
        if isinstance(ci, list) and ci:
            ci = ci[0]
        snapshot["carbon_intensity"] = ci.get("intensity", {}).get("actual") or ci.get("intensity", {}).get("forecast")

    _set_cache("live_snapshot", snapshot)
    return snapshot


# ─── Day-Ahead Prices ─────────────────────────────────────────────────────────

async def fetch_day_ahead_prices(date: str | None = None) -> dict:
    """Half-hourly N2EX/EPEX day-ahead prices via BMRS market index."""
    target = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        data = await _get(client, f"{_BMRS}/balancing/pricing/market-index", {
            "from": target,
            "to": target,
        })

    if not data:
        return {"error": "No day-ahead price data", "date": target}

    items = data if isinstance(data, list) else data.get("data", [])
    prices = []
    for item in items:
        p = item.get("dataProviderPrice") or item.get("price") or 0
        try:
            p = float(p)
        except (ValueError, TypeError):
            p = 0
        sp = item.get("settlementPeriod", 0)
        hour = ((sp - 1) * 30) // 60
        minute = ((sp - 1) * 30) % 60
        prices.append({
            "settlement_period": sp,
            "time": f"{hour:02d}:{minute:02d}",
            "price_gbp_mwh": round(p, 2),
        })

    vals = [p["price_gbp_mwh"] for p in prices if p["price_gbp_mwh"]]
    return {
        "date": target,
        "prices": prices,
        "count": len(prices),
        "stats": {
            "mean": round(sum(vals) / len(vals), 2) if vals else 0,
            "min": round(min(vals), 2) if vals else 0,
            "max": round(max(vals), 2) if vals else 0,
            "spread": round(max(vals) - min(vals), 2) if vals else 0,
        },
    }


# ─── Generation Mix (Historical) ─────────────────────────────────────────────

async def fetch_generation_mix(from_dt: str | None = None, to_dt: str | None = None) -> dict:
    """Historical generation by fuel type from BMRS."""
    now = datetime.now(timezone.utc)
    end_str = to_dt or now.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_str = from_dt or (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        data = await _get(client, f"{_BMRS}/datasets/FUELINST", {
            "publishDateTimeFrom": start_str,
            "publishDateTimeTo": end_str,
        })

    if not data or "data" not in data:
        return {"error": "No generation data"}

    items = data["data"]
    fuel_map = {
        "CCGT": "gas", "OCGT": "gas", "COAL": "coal",
        "NUCLEAR": "nuclear", "WIND": "wind", "BIOMASS": "biomass",
        "PS": "pumped_storage", "NPSHYD": "hydro", "OTHER": "other",
    }

    by_fuel = {}
    for item in items:
        fuel_raw = item.get("fuelType", "OTHER")
        fuel = fuel_map.get(fuel_raw, fuel_raw.lower())
        mw = float(item.get("generation") or item.get("quantity") or 0)
        by_fuel.setdefault(fuel, []).append(mw)

    summary = {k: round(sum(v) / len(v)) for k, v in by_fuel.items() if v}
    total = sum(summary.values())

    return {
        "by_fuel": summary,
        "total_mw": total,
        "record_count": len(items),
        "from": start_str,
        "to": end_str,
    }


# ─── Capacity Market Register ─────────────────────────────────────────────────

async def fetch_capacity_market_register() -> dict:
    """Reference data for Capacity Market — clearing prices and technology breakdown."""
    # Static reference — CM auction results are published annually
    return {
        "latest_auction": {
            "type": "T-4",
            "year": "2025/26",
            "clearing_price_kw_year": 28.50,
        },
        "technology_breakdown": {
            "ccgt": {"capacity_gw": 24.5, "share_pct": 38},
            "bess": {"capacity_gw": 8.2, "share_pct": 13, "revenue_example_mw_year": 42000},
            "nuclear": {"capacity_gw": 5.9, "share_pct": 9},
            "interconnector": {"capacity_gw": 6.8, "share_pct": 11},
            "demand_response": {"capacity_gw": 4.1, "share_pct": 6},
            "other": {"capacity_gw": 14.5, "share_pct": 23},
        },
        "de_rating_factors": {
            "bess_1h": 0.485,
            "bess_2h": 0.768,
            "bess_4h": 0.960,
            "solar": 0.034,
            "onshore_wind": 0.084,
            "offshore_wind": 0.107,
        },
        "note": "Source: EMR Delivery Body / NESO Capacity Market registers",
    }


# ─── Dashboard Summary ────────────────────────────────────────────────────────

async def get_market_summary() -> dict:
    """Aggregated market view for dashboard display."""
    live, prices, cm = await asyncio.gather(
        fetch_live_snapshot(),
        fetch_day_ahead_prices(),
        fetch_capacity_market_register(),
        return_exceptions=True,
    )

    summary = {"timestamp": datetime.now(timezone.utc).isoformat()}

    if not isinstance(live, Exception):
        summary["live"] = {
            "demand_gw": live.get("demand_gw"),
            "frequency_hz": live.get("frequency_hz"),
            "carbon_intensity": live.get("carbon_intensity"),
            "price_gbp_mwh": live.get("price_gbp_mwh"),
            "wind_gw": live.get("generation", {}).get("wind_gw"),
            "solar_gw": live.get("generation", {}).get("solar_gw"),
            "renewable_pct": live.get("generation", {}).get("renewable_pct"),
        }
        summary["sparklines"] = {
            "demand": live.get("demand_sparkline", []),
            "price": live.get("price_sparkline", []),
        }

    if not isinstance(prices, Exception):
        summary["day_ahead"] = prices.get("stats", {})

    if not isinstance(cm, Exception):
        summary["capacity_market"] = {
            "clearing_price": cm.get("latest_auction", {}).get("clearing_price_kw_year"),
            "bess_revenue": cm.get("technology_breakdown", {}).get("bess", {}).get("revenue_example_mw_year"),
        }

    return summary
