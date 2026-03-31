"""
Renewables.ninja API wrapper — Princeps energy data integration.
Provides hourly PV and wind capacity factors from the Renewables.ninja API.
Caches results as JSON files keyed by parameter hash.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

API_BASE = "https://www.renewables.ninja/api/data"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "renewables_ninja_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_last_request_time = 0.0


def _token() -> str:
    return os.environ.get("RENEWABLES_NINJA_TOKEN", "")


def _cache_key(params: dict) -> str:
    raw = json.dumps(params, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _get_cached(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def _set_cached(key: str, data: dict):
    path = CACHE_DIR / f"{key}.json"
    path.write_text(json.dumps(data))


def _rate_limit():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_request_time = time.time()


def get_pv_capacity_factors(
    lat: float,
    lon: float,
    date_from: str,
    date_to: str,
    capacity: float = 1,
    system_loss: float = 0.1,
    tracking: int = 0,
    tilt: float = 35,
    azim: float = 180,
) -> list[dict]:
    """Return hourly PV capacity factors as list of {timestamp, electricity}."""
    params = {
        "type": "pv", "lat": lat, "lon": lon,
        "date_from": date_from, "date_to": date_to,
        "capacity": capacity, "system_loss": system_loss,
        "tracking": tracking, "tilt": tilt, "azim": azim,
    }
    key = _cache_key(params)
    cached = _get_cached(key)
    if cached:
        return cached.get("data", [])

    token = _token()
    if not token:
        return [{"error": "RENEWABLES_NINJA_TOKEN not set"}]

    _rate_limit()
    url = (
        f"{API_BASE}/pv?lat={lat}&lon={lon}"
        f"&date_from={date_from}&date_to={date_to}"
        f"&capacity={capacity}&system_loss={system_loss}"
        f"&tracking={tracking}&tilt={tilt}&azim={azim}"
        f"&format=json"
    )
    try:
        req = Request(url, headers={
            "Authorization": f"Token {token}",
            "Accept": "application/json",
        })
        with urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read())
        data = _parse_ninja_response(raw)
        _set_cached(key, {"params": params, "data": data})
        return data
    except (URLError, json.JSONDecodeError, KeyError) as e:
        return [{"error": f"Renewables.ninja PV request failed: {e}"}]


def get_wind_capacity_factors(
    lat: float,
    lon: float,
    date_from: str,
    date_to: str,
    capacity: float = 1,
    hub_height: float = 80,
    turbine: str = "Vestas V80 2000",
) -> list[dict]:
    """Return hourly wind capacity factors as list of {timestamp, electricity}."""
    params = {
        "type": "wind", "lat": lat, "lon": lon,
        "date_from": date_from, "date_to": date_to,
        "capacity": capacity, "hub_height": hub_height, "turbine": turbine,
    }
    key = _cache_key(params)
    cached = _get_cached(key)
    if cached:
        return cached.get("data", [])

    token = _token()
    if not token:
        return [{"error": "RENEWABLES_NINJA_TOKEN not set"}]

    _rate_limit()
    url = (
        f"{API_BASE}/wind?lat={lat}&lon={lon}"
        f"&date_from={date_from}&date_to={date_to}"
        f"&capacity={capacity}&height={hub_height}"
        f"&turbine={turbine.replace(' ', '%20')}"
        f"&format=json"
    )
    try:
        req = Request(url, headers={
            "Authorization": f"Token {token}",
            "Accept": "application/json",
        })
        with urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read())
        data = _parse_ninja_response(raw)
        _set_cached(key, {"params": params, "data": data})
        return data
    except (URLError, json.JSONDecodeError, KeyError) as e:
        return [{"error": f"Renewables.ninja wind request failed: {e}"}]


def get_annual_summary(lat: float, lon: float) -> dict:
    """Return P50 annual capacity factor for PV and wind at a location."""
    # Use a recent full year
    date_from = "2023-01-01"
    date_to = "2023-12-31"

    pv_data = get_pv_capacity_factors(lat, lon, date_from, date_to)
    wind_data = get_wind_capacity_factors(lat, lon, date_from, date_to)

    def _mean_cf(data: list[dict]) -> float | None:
        vals = [d["electricity"] for d in data if "electricity" in d]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 4)

    return {
        "lat": lat,
        "lon": lon,
        "year": 2023,
        "pv_capacity_factor": _mean_cf(pv_data),
        "wind_capacity_factor": _mean_cf(wind_data),
        "pv_hours": len([d for d in pv_data if "electricity" in d]),
        "wind_hours": len([d for d in wind_data if "electricity" in d]),
    }


def _parse_ninja_response(raw: dict) -> list[dict]:
    """Parse Renewables.ninja JSON response into flat list."""
    # API returns {"data": {"timestamp": {"electricity": val}, ...}} or list
    data = raw.get("data", raw)
    if isinstance(data, dict):
        return [
            {"timestamp": ts, "electricity": vals.get("electricity", vals) if isinstance(vals, dict) else vals}
            for ts, vals in data.items()
        ]
    if isinstance(data, list):
        return data
    return []
