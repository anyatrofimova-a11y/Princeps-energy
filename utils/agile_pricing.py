"""
Octopus Agile electricity pricing fetcher.

Fetches half-hourly Agile tariff prices from the public Octopus Energy API.
No API key required. Based on pufferfish-tech/octopus-agile-pi-prices.

Provides:
  - Current and next-day half-hourly prices (p/kWh inc VAT)
  - Regional pricing (14 UK DNO regions)
  - Price heatmap data (48 slots × 7 days)
  - Cheapest/most expensive windows for storage optimization
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 10

# Current Agile tariff code — update when Octopus changes it
DEFAULT_TARIFF = "24-10-01"

# DNO region codes
REGIONS = {
    "A": "East England",
    "B": "East Midlands",
    "C": "London",
    "D": "North Wales & Merseyside",
    "E": "West Midlands",
    "F": "North East England",
    "G": "North West England",
    "H": "Southern England",
    "J": "South East England",
    "K": "South Wales",
    "L": "South West England",
    "M": "Yorkshire",
    "N": "South & Central Scotland",
    "P": "North Scotland",
}

# Representative coordinates for each DNO region (for map heatmap)
REGION_COORDS = {
    "A": {"lat": 52.20, "lon": 0.70, "label": "East England"},
    "B": {"lat": 52.95, "lon": -1.15, "label": "East Midlands"},
    "C": {"lat": 51.51, "lon": -0.13, "label": "London"},
    "D": {"lat": 53.25, "lon": -3.00, "label": "North Wales & Merseyside"},
    "E": {"lat": 52.48, "lon": -1.90, "label": "West Midlands"},
    "F": {"lat": 54.97, "lon": -1.61, "label": "North East England"},
    "G": {"lat": 53.48, "lon": -2.24, "label": "North West England"},
    "H": {"lat": 50.90, "lon": -1.40, "label": "Southern England"},
    "J": {"lat": 51.27, "lon": 0.52, "label": "South East England"},
    "K": {"lat": 51.62, "lon": -3.45, "label": "South Wales"},
    "L": {"lat": 50.72, "lon": -3.53, "label": "South West England"},
    "M": {"lat": 53.80, "lon": -1.55, "label": "Yorkshire"},
    "N": {"lat": 55.95, "lon": -3.19, "label": "South & Central Scotland"},
    "P": {"lat": 57.48, "lon": -4.22, "label": "North Scotland"},
}


def _build_url(tariff: str, region: str) -> str:
    """Build Octopus Agile API URL."""
    return (
        f"https://api.octopus.energy/v1/products/AGILE-{tariff}/"
        f"electricity-tariffs/E-1R-AGILE-{tariff}-{region}/standard-unit-rates/"
    )


async def fetch_agile_prices(
    region: str = "C",
    tariff: str = DEFAULT_TARIFF,
    period_from: str | None = None,
    period_to: str | None = None,
) -> list[dict] | None:
    """Fetch half-hourly Agile prices from Octopus API.

    Returns list of {valid_from, valid_to, price_pence} sorted by time.
    """
    url = _build_url(tariff, region)
    params = {}
    if period_from:
        params["period_from"] = period_from
    if period_to:
        params["period_to"] = period_to

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("Octopus Agile fetch failed (region=%s): %s", region, e)
        return None

    results = data.get("results", [])
    if not results:
        return None

    prices = []
    for item in results:
        try:
            prices.append({
                "valid_from": item["valid_from"],
                "valid_to": item["valid_to"],
                "price_pence": round(item["value_inc_vat"], 2),
            })
        except (KeyError, TypeError):
            continue

    # Sort chronologically (API returns newest first)
    prices.sort(key=lambda x: x["valid_from"])
    return prices


async def fetch_all_regions_current(tariff: str = DEFAULT_TARIFF) -> dict | None:
    """Fetch current prices for all 14 DNO regions.

    Returns dict mapping region code to current price (p/kWh).
    Used for the regional price heatmap.
    """
    import asyncio

    now = datetime.now(timezone.utc)
    period_from = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    period_to = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async def _fetch_one(region: str):
        prices = await fetch_agile_prices(
            region=region, tariff=tariff,
            period_from=period_from, period_to=period_to,
        )
        if prices:
            # Find the price slot that covers 'now'
            for p in prices:
                pf = datetime.fromisoformat(p["valid_from"].replace("Z", "+00:00"))
                pt = datetime.fromisoformat(p["valid_to"].replace("Z", "+00:00"))
                if pf <= now < pt:
                    return region, p["price_pence"]
            # Fallback: latest price
            return region, prices[-1]["price_pence"]
        return region, None

    tasks = [_fetch_one(r) for r in REGIONS]
    results = await asyncio.gather(*tasks)
    return {r: p for r, p in results if p is not None}


def prices_to_heatmap(prices: list[dict]) -> dict:
    """Convert price list to heatmap-ready structure.

    Groups prices by date and half-hour slot.
    Returns {dates: [...], slots: [0..47], grid: [[price, ...], ...]}
    """
    by_date = {}
    for p in prices:
        try:
            dt = datetime.fromisoformat(p["valid_from"].replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
            slot = dt.hour * 2 + (1 if dt.minute >= 30 else 0)
            if date_str not in by_date:
                by_date[date_str] = [None] * 48
            by_date[date_str][slot] = p["price_pence"]
        except (ValueError, AttributeError):
            continue

    dates = sorted(by_date.keys())
    grid = [by_date[d] for d in dates]

    return {
        "dates": dates,
        "slots": list(range(48)),
        "grid": grid,
    }


def find_cheapest_windows(prices: list[dict], window_hours: float = 2) -> list[dict]:
    """Find the cheapest consecutive time windows for storage charging.

    Returns top-5 cheapest windows of the given duration.
    """
    slots_needed = int(window_hours * 2)  # half-hourly slots
    if len(prices) < slots_needed:
        return []

    windows = []
    for i in range(len(prices) - slots_needed + 1):
        window = prices[i:i + slots_needed]
        avg_price = sum(p["price_pence"] for p in window) / slots_needed
        windows.append({
            "start": window[0]["valid_from"],
            "end": window[-1]["valid_to"],
            "avg_price_pence": round(avg_price, 2),
            "total_cost_pence_per_kwh": round(avg_price, 2),
        })

    windows.sort(key=lambda w: w["avg_price_pence"])
    return windows[:5]


def find_peak_windows(prices: list[dict], window_hours: float = 2) -> list[dict]:
    """Find the most expensive windows — best for exporting stored energy."""
    slots_needed = int(window_hours * 2)
    if len(prices) < slots_needed:
        return []

    windows = []
    for i in range(len(prices) - slots_needed + 1):
        window = prices[i:i + slots_needed]
        avg_price = sum(p["price_pence"] for p in window) / slots_needed
        windows.append({
            "start": window[0]["valid_from"],
            "end": window[-1]["valid_to"],
            "avg_price_pence": round(avg_price, 2),
        })

    windows.sort(key=lambda w: w["avg_price_pence"], reverse=True)
    return windows[:5]


def regional_prices_to_geojson(region_prices: dict) -> dict:
    """Convert regional prices to GeoJSON for map overlay.

    Returns a FeatureCollection of Points with price properties.
    """
    features = []
    for region, price in region_prices.items():
        coords = REGION_COORDS.get(region)
        if not coords:
            continue
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [coords["lon"], coords["lat"]],
            },
            "properties": {
                "region": region,
                "label": coords["label"],
                "price_pence": price,
                "price_category": (
                    "negative" if price < 0
                    else "cheap" if price < 15
                    else "moderate" if price < 30
                    else "expensive" if price < 50
                    else "peak"
                ),
            },
        })

    return {"type": "FeatureCollection", "features": features}


async def get_pricing_overview(region: str = "C", tariff: str = DEFAULT_TARIFF) -> dict:
    """Full pricing analysis for API response.

    Returns current prices, heatmap, cheapest/peak windows, and regional map data.
    """
    import asyncio

    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    tomorrow_end = (now + timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")

    # Fetch prices for selected region (yesterday through tomorrow)
    prices_task = asyncio.create_task(
        fetch_agile_prices(region=region, tariff=tariff,
                           period_from=yesterday, period_to=tomorrow_end)
    )
    # Fetch all regions for heatmap
    regions_task = asyncio.create_task(fetch_all_regions_current(tariff=tariff))

    prices = await prices_task
    region_prices = await regions_task

    if not prices:
        return {"error": "No price data available", "region": region}

    # Current price
    current_price = None
    for p in prices:
        pf = datetime.fromisoformat(p["valid_from"].replace("Z", "+00:00"))
        pt = datetime.fromisoformat(p["valid_to"].replace("Z", "+00:00"))
        if pf <= now < pt:
            current_price = p["price_pence"]
            break

    # Stats
    all_prices = [p["price_pence"] for p in prices]
    avg_price = round(sum(all_prices) / len(all_prices), 2)
    min_price = min(all_prices)
    max_price = max(all_prices)

    return {
        "region": region,
        "region_name": REGIONS.get(region, region),
        "tariff": tariff,
        "current_price_pence": current_price,
        "stats": {
            "avg_pence": avg_price,
            "min_pence": min_price,
            "max_pence": max_price,
            "spread_pence": round(max_price - min_price, 2),
            "periods": len(prices),
        },
        "heatmap": prices_to_heatmap(prices),
        "cheapest_windows": find_cheapest_windows(prices),
        "peak_windows": find_peak_windows(prices),
        "prices": prices,
        "regional_map": regional_prices_to_geojson(region_prices or {}),
        "all_regions": REGIONS,
    }
