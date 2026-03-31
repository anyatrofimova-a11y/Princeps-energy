"""
Elexon BMRS API client — system demand, generation, prices, balancing costs.
Uses raw requests to https://data.elexon.co.uk/bmrs/api/v1/ (no auth for most endpoints).
Caches responses as JSON in data/elexon_cache/.
"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

BMRS_BASE = "https://data.elexon.co.uk/bmrs/api/v1"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "elexon_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_key(endpoint: str, params: dict) -> str:
    raw = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _get_cached(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def _set_cached(key: str, data: dict):
    path = CACHE_DIR / f"{key}.json"
    path.write_text(json.dumps(data, default=str))


def _bmrs_get(path: str, params: dict | None = None) -> dict | list | None:
    """GET request to BMRS API with optional query params."""
    qs = ""
    if params:
        parts = [f"{k}={v}" for k, v in params.items() if v is not None]
        qs = "?" + "&".join(parts) if parts else ""
    url = f"{BMRS_BASE}{path}{qs}"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except (URLError, json.JSONDecodeError) as e:
        return {"error": f"BMRS request failed: {e}"}


def get_system_demand(
    date_from: str,
    date_to: str,
    settlement_period: int | None = None,
) -> list[dict]:
    """Fetch INDO/ITSDO demand outturn, paginating in 7-day chunks."""
    params = {"date_from": date_from, "date_to": date_to, "sp": settlement_period}
    key = _cache_key("demand", params)
    cached = _get_cached(key)
    if cached:
        return cached.get("data", [])

    records = []
    start = datetime.fromisoformat(date_from)
    end = datetime.fromisoformat(date_to)
    current = start

    while current < end:
        chunk_end = min(current + timedelta(days=7), end)
        data = _bmrs_get("/demand/outturn/summary", {
            "from": current.strftime("%Y-%m-%dT00:00:00Z"),
            "to": chunk_end.strftime("%Y-%m-%dT23:59:59Z"),
            "format": "json",
        })
        items = _extract_items(data)
        for item in items:
            ts = item.get("startTime") or item.get("settlementDate")
            demand = (
                item.get("demand")
                or item.get("initialDemandOutturn")
                or item.get("transmissionSystemDemand")
            )
            if ts and demand is not None:
                records.append({
                    "timestamp": ts,
                    "demand_mw": float(demand),
                    "settlement_period": item.get("settlementPeriod"),
                })
        current = chunk_end + timedelta(days=1)

    _set_cached(key, {"data": records})
    return records


def get_generation_by_fuel(date_from: str, date_to: str) -> list[dict]:
    """Fetch generation by fuel type."""
    params = {"date_from": date_from, "date_to": date_to}
    key = _cache_key("generation_fuel", params)
    cached = _get_cached(key)
    if cached:
        return cached.get("data", [])

    data = _bmrs_get("/generation/outturn/summary", {
        "from": f"{date_from}T00:00:00Z",
        "to": f"{date_to}T23:59:59Z",
        "format": "json",
    })
    items = _extract_items(data)
    records = []
    for item in items:
        records.append({
            "timestamp": item.get("startTime") or item.get("settlementDate"),
            "fuel_type": item.get("fuelType") or item.get("psrType"),
            "generation_mw": float(item.get("quantity", item.get("generation", 0))),
        })

    _set_cached(key, {"data": records})
    return records


def get_system_price(date_from: str, date_to: str) -> list[dict]:
    """Fetch system buy/sell prices."""
    params = {"date_from": date_from, "date_to": date_to}
    key = _cache_key("system_price", params)
    cached = _get_cached(key)
    if cached:
        return cached.get("data", [])

    data = _bmrs_get("/balancing/settlement/system-prices", {
        "from": f"{date_from}T00:00:00Z",
        "to": f"{date_to}T23:59:59Z",
        "format": "json",
    })
    items = _extract_items(data)
    records = []
    for item in items:
        records.append({
            "settlement_date": item.get("settlementDate"),
            "settlement_period": item.get("settlementPeriod"),
            "system_sell_price": item.get("systemSellPrice"),
            "system_buy_price": item.get("systemBuyPrice"),
        })

    _set_cached(key, {"data": records})
    return records


def get_balancing_costs(date_from: str, date_to: str) -> list[dict]:
    """Fetch balancing mechanism costs."""
    params = {"date_from": date_from, "date_to": date_to}
    key = _cache_key("balancing_costs", params)
    cached = _get_cached(key)
    if cached:
        return cached.get("data", [])

    data = _bmrs_get("/balancing/settlement/market-depth", {
        "from": f"{date_from}T00:00:00Z",
        "to": f"{date_to}T23:59:59Z",
        "format": "json",
    })
    items = _extract_items(data)
    records = []
    for item in items:
        records.append({
            "settlement_date": item.get("settlementDate"),
            "settlement_period": item.get("settlementPeriod"),
            "buy_volume_mwh": item.get("bidVolume") or item.get("buyVolume"),
            "sell_volume_mwh": item.get("offerVolume") or item.get("sellVolume"),
            "net_cost_gbp": item.get("netImbalanceVolume"),
        })

    _set_cached(key, {"data": records})
    return records


def _extract_items(data) -> list:
    """Extract list items from various BMRS response formats."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "error" in data:
            return []
        return data.get("data", data.get("results", data.get("items", [])))
    return []
