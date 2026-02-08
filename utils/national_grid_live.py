"""
Live UK National Grid data fetcher.

Uses the same public APIs as HA-NationalGrid (JRascagneres):
  - BMRS / Elexon: generation mix, interconnectors, frequency, price
  - NESO: embedded wind/solar, demand
  - Carbon Intensity API: gCO2/kWh by region

No API keys required — all endpoints are public.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 12  # seconds

# ── Known geographic coordinates for map visualisation ──

# Interconnector landing points (approx WGS84)
INTERCONNECTOR_COORDS = {
    "france":      {"from": [-1.14, 51.10], "to": [1.85, 50.96], "label": "France (IFA/IFA2/ElecLink)"},
    "ireland":     {"from": [-3.45, 54.85], "to": [-5.75, 54.60], "label": "Ireland (Moyle/EWIC/GreenLink)"},
    "netherlands": {"from": [1.75, 51.95], "to": [3.60, 51.90], "label": "Netherlands (BritNed)"},
    "belgium":     {"from": [1.40, 51.35], "to": [2.90, 51.30], "label": "Belgium (Nemo)"},
    "norway":      {"from": [1.40, 54.65], "to": [6.50, 58.30], "label": "Norway (NSL)"},
    "denmark":     {"from": [1.30, 53.70], "to": [8.10, 55.50], "label": "Denmark (Viking Link)"},
}

# Generation type representative locations (spread across GB)
GENERATION_COORDS = {
    "nuclear":   [-3.41, 54.03, "Nuclear (Heysham, Torness, Sizewell, Hinkley)"],
    "gas":       [-1.20, 53.60, "Gas (CCGT)"],
    "wind":      [-1.80, 55.60, "Wind (Onshore + Offshore)"],
    "solar":     [-0.90, 51.50, "Solar PV (Embedded)"],
    "biomass":   [-0.95, 53.75, "Biomass (Drax)"],
    "coal":      [-1.30, 53.20, "Coal"],
    "hydro":     [-4.80, 56.85, "Hydro"],
    "pumped":    [-3.95, 53.00, "Pumped Storage (Dinorwig, Ffestiniog)"],
    "other":     [-2.50, 52.00, "Other"],
}


async def fetch_generation_mix() -> dict | None:
    """Fetch current generation mix from BMRS FUELINST."""
    now = datetime.now(timezone.utc)
    ten_min_ago = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (
        f"https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELINST"
        f"?publishDateTimeFrom={ten_min_ago}&publishDateTimeTo={now_str}&format=json"
    )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url)
            r.raise_for_status()
            items = r.json().get("data", [])
    except Exception as e:
        log.warning("BMRS generation fetch failed: %s", e)
        return None

    if not items:
        return None

    # Find latest timestamp
    latest_time = max(item["startTime"] for item in items)

    gen = {}
    fuel_map = {
        "CCGT": "gas", "OCGT": "gas", "OIL": "oil", "COAL": "coal",
        "BIOMASS": "biomass", "NUCLEAR": "nuclear", "WIND": "wind",
        "PS": "pumped", "NPSHYD": "hydro", "OTHER": "other",
        "INTFR": "france", "INTELEC": "france", "INTIFA2": "france",
        "INTIRL": "ireland", "INTEW": "ireland", "INTGRNL": "ireland",
        "INTNED": "netherlands", "INTNEM": "belgium",
        "INTNSL": "norway", "INTVKL": "denmark",
    }
    for item in items:
        if item["startTime"] != latest_time:
            continue
        key = fuel_map.get(item["fuelType"])
        if key:
            gen[key] = gen.get(key, 0) + int(item["generation"])

    # Get embedded solar + wind from NESO CSV
    try:
        embedded = await _fetch_embedded_generation()
        if embedded:
            gen["solar"] = embedded.get("solar", 0)
            gen["wind"] = gen.get("wind", 0) + embedded.get("wind", 0)
            gen["embedded_wind"] = embedded.get("wind", 0)
            gen["embedded_solar"] = embedded.get("solar", 0)
    except Exception as e:
        log.warning("Embedded gen fetch failed: %s", e)

    total_gen = sum(v for k, v in gen.items()
                    if k not in ("france", "ireland", "netherlands", "belgium", "norway", "denmark",
                                 "pumped", "embedded_wind", "embedded_solar"))
    gen["total_generation_mw"] = total_gen
    gen["timestamp"] = latest_time
    return gen


async def _fetch_embedded_generation() -> dict | None:
    """Fetch embedded wind/solar from NESO demand CSV."""
    url = ("https://api.neso.energy/dataset/7a12172a-939c-404c-b581-a6128b74f588/"
           "resource/177f6fa4-ae49-4182-81ea-0c6b35f26ca6/download/demanddataupdate.csv")
    now = datetime.now(timezone.utc)
    settlement_period = (now.hour * 60 + now.minute) // 30 + 1
    today_str = now.strftime("%Y-%m-%d")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url)
            r.raise_for_status()
    except Exception:
        return None

    import csv
    import io
    reader = csv.DictReader(io.StringIO(r.text))
    for row in reader:
        try:
            row_date = row.get("SETTLEMENT_DATE", "")[:10]
            if row_date == today_str and int(row["SETTLEMENT_PERIOD"]) == settlement_period:
                return {
                    "wind": int(row.get("EMBEDDED_WIND_GENERATION", 0)),
                    "solar": int(row.get("EMBEDDED_SOLAR_GENERATION", 0)),
                }
        except (ValueError, KeyError):
            continue
    return None


async def fetch_carbon_intensity() -> dict | None:
    """Fetch current national carbon intensity."""
    now = datetime.now(timezone.utc)
    url = f"https://api.carbonintensity.org.uk/intensity/{now.strftime('%Y-%m-%dT%H:%MZ')}/pt24h"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("Carbon intensity fetch failed: %s", e)
        return None

    for item in reversed(data.get("data", [])):
        actual = item.get("intensity", {}).get("actual")
        if actual is not None:
            return {"intensity_gco2": int(actual), "index": item["intensity"].get("index", "moderate")}
    return None


async def fetch_grid_frequency() -> float | None:
    """Fetch current grid frequency (Hz)."""
    now = datetime.now(timezone.utc)
    from_t = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_t = (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = f"https://data.elexon.co.uk/bmrs/api/v1/system/frequency?format=json&from={from_t}&to={to_t}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url)
            r.raise_for_status()
            items = r.json().get("data", [])
            if items:
                return float(items[-1]["frequency"])
    except Exception as e:
        log.warning("Grid frequency fetch failed: %s", e)
    return None


async def fetch_sell_price() -> float | None:
    """Fetch current grid sell price (GBP/MWh)."""
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    url = (
        f"https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index"
        f"?from={yesterday}&to={today}"
        f"&settlementPeriodFrom=1&settlementPeriodTo=50&dataProviders=APXMIDP&format=json"
    )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url)
            r.raise_for_status()
            items = r.json().get("data", [])
            if items:
                return round(float(items[0]["price"]), 2)
    except Exception as e:
        log.warning("Sell price fetch failed: %s", e)
    return None


async def fetch_all_live() -> dict:
    """Fetch all live grid data and return as map-ready structure.

    Returns dict with:
      generation: {type: mw, ...}
      interconnectors: {country: mw, ...}  (positive = import)
      carbon: {intensity_gco2, index}
      frequency_hz: float
      sell_price_gbp_mwh: float
      timestamp: str
    """
    import asyncio
    gen_task = asyncio.create_task(fetch_generation_mix())
    carbon_task = asyncio.create_task(fetch_carbon_intensity())
    freq_task = asyncio.create_task(fetch_grid_frequency())
    price_task = asyncio.create_task(fetch_sell_price())

    gen = await gen_task
    carbon = await carbon_task
    freq = await freq_task
    price = await price_task

    if gen is None:
        gen = {}

    # Separate interconnectors from generation
    interconnectors = {}
    for country in ("france", "ireland", "netherlands", "belgium", "norway", "denmark"):
        interconnectors[country] = gen.pop(country, 0)

    return {
        "generation": gen,
        "interconnectors": interconnectors,
        "carbon": carbon,
        "frequency_hz": freq,
        "sell_price_gbp_mwh": price,
        "timestamp": gen.get("timestamp"),
    }


def live_data_to_geojson(data: dict) -> dict:
    """Convert live grid data to GeoJSON FeatureCollections for map display.

    Returns:
      {
        interconnectors: FeatureCollection of LineString flows,
        generation: FeatureCollection of Point generation sources,
        summary: {total_mw, renewable_pct, carbon, frequency, price}
      }
    """
    gen = data.get("generation", {})
    ics = data.get("interconnectors", {})

    # ── Interconnector flow lines ──
    ic_features = []
    for country, mw in ics.items():
        if country not in INTERCONNECTOR_COORDS:
            continue
        coords = INTERCONNECTOR_COORDS[country]
        # Positive MW = import to GB, negative = export
        # Line always from UK to foreign — but we annotate direction
        direction = "import" if mw >= 0 else "export"
        ic_features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [coords["from"], coords["to"]],
            },
            "properties": {
                "country": country,
                "label": coords["label"],
                "flow_mw": mw,
                "abs_flow_mw": abs(mw),
                "direction": direction,
            },
        })

    # ── Generation source points ──
    gen_features = []
    for gtype, (lon, lat, label) in GENERATION_COORDS.items():
        mw = gen.get(gtype, 0)
        gen_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "type": gtype,
                "label": label,
                "generation_mw": mw,
            },
        })

    # ── Summary ──
    total = gen.get("total_generation_mw", 0) or 1
    renewable_mw = gen.get("wind", 0) + gen.get("solar", 0) + gen.get("hydro", 0)
    renewable_pct = round(renewable_mw / total * 100, 1) if total else 0

    return {
        "interconnectors": {"type": "FeatureCollection", "features": ic_features},
        "generation": {"type": "FeatureCollection", "features": gen_features},
        "summary": {
            "total_generation_mw": total,
            "renewable_pct": renewable_pct,
            "fossil_pct": round((gen.get("gas", 0) + gen.get("oil", 0) + gen.get("coal", 0)) / total * 100, 1) if total else 0,
            "nuclear_mw": gen.get("nuclear", 0),
            "wind_mw": gen.get("wind", 0),
            "solar_mw": gen.get("solar", 0),
            "carbon": data.get("carbon"),
            "frequency_hz": data.get("frequency_hz"),
            "sell_price_gbp_mwh": data.get("sell_price_gbp_mwh"),
            "timestamp": data.get("timestamp"),
        },
    }
