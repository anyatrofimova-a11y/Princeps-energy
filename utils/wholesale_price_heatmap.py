"""
Wholesale Price Heatmap — regional electricity pricing for UK DNO regions.

Sources: Octopus Agile API (14 regions), BMRS wholesale index.
Inspired by PVcase's LMP data and LandGate's nodal pricing.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)
TIMEOUT = 15

# ── UK DNO region codes and metadata ─────────────────────────────────────────

REGIONS = {
    "A": {"name": "Eastern England", "operator": "UKPN", "center": [0.9, 52.2]},
    "B": {"name": "East Midlands", "operator": "NGED", "center": [-1.1, 52.9]},
    "C": {"name": "London", "operator": "UKPN", "center": [-0.1, 51.5]},
    "D": {"name": "Merseyside & N Wales", "operator": "SPEN", "center": [-3.0, 53.4]},
    "E": {"name": "West Midlands", "operator": "NGED", "center": [-1.9, 52.5]},
    "F": {"name": "North East", "operator": "NPG", "center": [-1.6, 54.9]},
    "G": {"name": "North West", "operator": "ENWL", "center": [-2.5, 53.8]},
    "H": {"name": "Southern England", "operator": "SSEN", "center": [-1.3, 51.0]},
    "J": {"name": "South East", "operator": "UKPN", "center": [0.5, 51.2]},
    "K": {"name": "South Wales", "operator": "NGED", "center": [-3.5, 51.6]},
    "L": {"name": "South West", "operator": "NGED", "center": [-3.5, 50.7]},
    "M": {"name": "Yorkshire", "operator": "NPG", "center": [-1.5, 53.8]},
    "N": {"name": "South Scotland", "operator": "SPEN", "center": [-3.7, 55.9]},
    "P": {"name": "North Scotland", "operator": "SSEN", "center": [-4.2, 57.5]},
}

# Simplified region polygon boundaries (WGS84)
REGION_POLYGONS = {
    "A": [[-0.5, 51.8], [1.8, 51.8], [1.8, 53.0], [-0.5, 53.0]],
    "B": [[-1.8, 52.3], [-0.5, 52.3], [-0.5, 53.3], [-1.8, 53.3]],
    "C": [[-0.5, 51.3], [0.3, 51.3], [0.3, 51.7], [-0.5, 51.7]],
    "D": [[-4.0, 52.8], [-2.5, 52.8], [-2.5, 53.6], [-4.0, 53.6]],
    "E": [[-2.8, 52.0], [-1.8, 52.0], [-1.8, 52.8], [-2.8, 52.8]],
    "F": [[-2.5, 54.4], [-1.0, 54.4], [-1.0, 55.8], [-2.5, 55.8]],
    "G": [[-3.2, 53.2], [-2.0, 53.2], [-2.0, 54.4], [-3.2, 54.4]],
    "H": [[-2.0, 50.6], [-0.5, 50.6], [-0.5, 51.3], [-2.0, 51.3]],
    "J": [[-0.5, 50.8], [1.5, 50.8], [1.5, 51.5], [-0.5, 51.5]],
    "K": [[-5.3, 51.3], [-3.0, 51.3], [-3.0, 52.0], [-5.3, 52.0]],
    "L": [[-5.7, 49.9], [-2.5, 49.9], [-2.5, 51.3], [-5.7, 51.3]],
    "M": [[-2.0, 53.3], [-0.5, 53.3], [-0.5, 54.5], [-2.0, 54.5]],
    "N": [[-5.5, 55.0], [-2.5, 55.0], [-2.5, 56.5], [-5.5, 56.5]],
    "P": [[-7.5, 56.5], [-1.5, 56.5], [-1.5, 59.0], [-7.5, 59.0]],
}

# Transmission boundary constraint surcharges (approx £/MWh by region)
CONSTRAINT_SURCHARGES = {
    "A": 2.0, "B": 3.0, "C": 1.5, "D": 4.0, "E": 3.5,
    "F": 5.0, "G": 4.5, "H": 2.0, "J": 1.5, "K": 4.0,
    "L": 3.0, "M": 4.5, "N": 8.0, "P": 12.0,  # Scotland highest
}

AGILE_TARIFF = "AGILE-24-10-01"


async def _fetch_agile_prices(region: str, period_from: str = None, period_to: str = None) -> list:
    """Fetch Octopus Agile prices for a region."""
    tariff_code = f"E-1R-{AGILE_TARIFF}-{region}"
    url = f"https://api.octopus.energy/v1/products/{AGILE_TARIFF}/electricity-tariffs/{tariff_code}/standard-unit-rates/"
    params = {}
    if period_from:
        params["period_from"] = period_from
    if period_to:
        params["period_to"] = period_to
    params["page_size"] = 200

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(url, params=params)
            r.raise_for_status()
            return r.json().get("results", [])
    except Exception as e:
        log.warning("Agile fetch failed for region %s: %s", region, e)
        return []


async def fetch_regional_prices() -> dict:
    """Current Agile price for all 14 UK regions."""
    import asyncio
    now = datetime.now(timezone.utc)
    period_from = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%MZ")
    period_to = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%MZ")

    async def fetch_one(code):
        rates = await _fetch_agile_prices(code, period_from, period_to)
        current = rates[0] if rates else None
        return code, current

    results = await asyncio.gather(*[fetch_one(c) for c in REGIONS])

    prices = {}
    for code, rate in results:
        if rate:
            prices[code] = {
                "region": REGIONS[code]["name"],
                "operator": REGIONS[code]["operator"],
                "price_p_kwh": rate["value_inc_vat"],
                "price_gbp_mwh": round(rate["value_inc_vat"] * 10, 2),
                "valid_from": rate["valid_from"],
                "valid_to": rate["valid_to"],
            }
        else:
            prices[code] = {
                "region": REGIONS[code]["name"],
                "operator": REGIONS[code]["operator"],
                "price_p_kwh": None,
                "note": "No current price available",
            }

    return prices


async def fetch_price_timeseries(region: str = "C", hours: int = 48) -> list:
    """Historical half-hourly Agile prices for a region."""
    now = datetime.now(timezone.utc)
    period_from = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%MZ")
    rates = await _fetch_agile_prices(region, period_from)
    return [{
        "time": r["valid_from"],
        "price_p_kwh": r["value_inc_vat"],
        "price_gbp_mwh": round(r["value_inc_vat"] * 10, 2),
    } for r in sorted(rates, key=lambda x: x["valid_from"])]


async def price_heatmap_geojson() -> dict:
    """GeoJSON FeatureCollection of DNO regions colored by current price."""
    prices = await fetch_regional_prices()

    features = []
    for code, poly_coords in REGION_POLYGONS.items():
        info = prices.get(code, {})
        price = info.get("price_gbp_mwh")
        surcharge = CONSTRAINT_SURCHARGES.get(code, 0)
        effective = round(price + surcharge, 2) if price else None

        # Color: green (cheap) → amber → red (expensive)
        if effective is None:
            color = "#888888"
        elif effective < 40:
            color = "#16A34A"
        elif effective < 80:
            color = "#F5B731"
        elif effective < 120:
            color = "#E8A012"
        else:
            color = "#DC2626"

        # Close polygon
        ring = [list(c) for c in poly_coords] + [list(poly_coords[0])]

        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {
                "region_code": code,
                "region_name": REGIONS[code]["name"],
                "operator": REGIONS[code]["operator"],
                "price_gbp_mwh": price,
                "constraint_surcharge": surcharge,
                "effective_price": effective,
                "color": color,
                **{k: v for k, v in info.items() if k not in ("region", "operator")},
            },
        })

    return {"type": "FeatureCollection", "features": features}


async def optimal_dispatch_window(hours_ahead: int = 24, region: str = "C",
                                    window_hours: int = 2) -> dict:
    """Find cheapest and most expensive time windows for BESS dispatch."""
    ts = await fetch_price_timeseries(region, hours_ahead)
    if len(ts) < window_hours * 2:
        return {"error": "Insufficient price data", "data_points": len(ts)}

    # Sliding window for cheapest (charge) and most expensive (discharge)
    best_charge = {"avg_price": float("inf"), "start": None, "end": None}
    best_discharge = {"avg_price": float("-inf"), "start": None, "end": None}

    slots = window_hours * 2  # Half-hourly slots
    for i in range(len(ts) - slots + 1):
        window = ts[i:i + slots]
        avg = sum(p["price_gbp_mwh"] for p in window) / slots

        if avg < best_charge["avg_price"]:
            best_charge = {"avg_price": round(avg, 2), "start": window[0]["time"], "end": window[-1]["time"]}
        if avg > best_discharge["avg_price"]:
            best_discharge = {"avg_price": round(avg, 2), "start": window[0]["time"], "end": window[-1]["time"]}

    spread = best_discharge["avg_price"] - best_charge["avg_price"]
    # Revenue for 1 MWh battery over one cycle
    revenue_per_mwh = spread * 0.85  # 85% round-trip efficiency

    return {
        "region": region,
        "window_hours": window_hours,
        "charge_window": best_charge,
        "discharge_window": best_discharge,
        "spread_gbp_mwh": round(spread, 2),
        "revenue_per_mwh_cycle": round(revenue_per_mwh, 2),
        "estimated_daily_revenue_100mw": round(revenue_per_mwh * 100 * 2, 0),  # 2 cycles/day
    }


async def annual_price_statistics(region: str = "C") -> dict:
    """Price statistics from recent data (up to 30 days)."""
    ts = await fetch_price_timeseries(region, hours=720)
    if not ts:
        return {"error": "No price data available"}

    prices = [p["price_gbp_mwh"] for p in ts if p["price_gbp_mwh"] is not None]
    if not prices:
        return {"error": "No valid prices"}

    prices.sort()
    n = len(prices)
    return {
        "region": region,
        "data_points": n,
        "mean_gbp_mwh": round(sum(prices) / n, 2),
        "p10": round(prices[int(n * 0.1)], 2),
        "p50": round(prices[int(n * 0.5)], 2),
        "p90": round(prices[int(n * 0.9)], 2),
        "min": round(prices[0], 2),
        "max": round(prices[-1], 2),
        "volatility": round((prices[-1] - prices[0]) / max(sum(prices) / n, 1) * 100, 1),
        "negative_periods_pct": round(sum(1 for p in prices if p < 0) / n * 100, 1),
    }
