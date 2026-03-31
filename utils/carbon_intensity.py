"""
Carbon Intensity API wrapper — https://api.carbonintensity.org.uk
Real-time UK carbon intensity data. No auth required.
"""

import json
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

API_BASE = "https://api.carbonintensity.org.uk"


def _get(path: str) -> dict | None:
    """GET request to Carbon Intensity API."""
    url = f"{API_BASE}{path}"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (URLError, json.JSONDecodeError) as e:
        return {"error": f"Carbon Intensity API failed: {e}"}


def get_current_intensity() -> dict:
    """Return current national carbon intensity (gCO2/kWh)."""
    data = _get("/intensity")
    if not data or "error" in data:
        return data or {"error": "no response"}
    items = data.get("data", [])
    if items:
        item = items[0]
        return {
            "from": item.get("from"),
            "to": item.get("to"),
            "forecast": item.get("intensity", {}).get("forecast"),
            "actual": item.get("intensity", {}).get("actual"),
            "index": item.get("intensity", {}).get("index"),
        }
    return {"error": "no intensity data"}


def get_regional_intensity(postcode: str | None = None) -> dict:
    """Return regional carbon intensity, optionally filtered by postcode."""
    if postcode:
        data = _get(f"/regional/postcode/{postcode}")
    else:
        data = _get("/regional")
    if not data or "error" in data:
        return data or {"error": "no response"}

    raw = data.get("data", data)
    # Regional endpoint returns nested structure
    if isinstance(raw, list) and raw:
        raw = raw[0]
    regions = raw.get("data", raw.get("regions", []))
    if isinstance(regions, list):
        return {
            "postcode": postcode,
            "regions": [
                {
                    "shortname": r.get("shortname"),
                    "dnoregion": r.get("dnoregion"),
                    "intensity": r.get("intensity", {}),
                    "generation_mix": r.get("generationmix", []),
                }
                for r in regions
            ],
        }
    # Single region for postcode
    return {
        "postcode": postcode,
        "region": raw,
    }


def get_intensity_forecast(hours: int = 48) -> list[dict]:
    """Return carbon intensity forecast for next N hours."""
    now = datetime.utcnow()
    to = now + timedelta(hours=hours)
    path = f"/intensity/{now.strftime('%Y-%m-%dT%H:%MZ')}/fw{hours}h"
    data = _get(path)
    if not data or "error" in data:
        return [data or {"error": "no response"}]
    items = data.get("data", [])
    return [
        {
            "from": item.get("from"),
            "to": item.get("to"),
            "forecast": item.get("intensity", {}).get("forecast"),
            "index": item.get("intensity", {}).get("index"),
        }
        for item in items
    ]


def get_generation_mix() -> list[dict]:
    """Return current national generation fuel mix percentages."""
    data = _get("/generation")
    if not data or "error" in data:
        return [data or {"error": "no response"}]
    raw = data.get("data", data)
    if isinstance(raw, dict):
        return raw.get("generationmix", [])
    if isinstance(raw, list) and raw:
        return raw[0].get("generationmix", raw)
    return []
