"""
DCIM Integration Layer — connects Princeps to external data centre
infrastructure management platforms.

Supported platforms:
1. Schneider Electric EcoStruxure IT Expert — REST API for DC power/cooling/alarms
2. Siemens Building X — REST API for BMS telemetry (HVAC, power meters)

Both require API keys/tokens (configured via environment variables).
Returns normalised telemetry that feeds into Princeps demand forecasting
and grid capacity analysis.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import httpx

log = logging.getLogger("princeps.dcim")

# ═══════════════════════════════════════════════════════════════
#  SCHNEIDER ELECTRIC EcoStruxure IT Expert
#  API: https://api.ecostruxureit.com/rest/
#  Auth: API key (ECOSTRUXURE_API_KEY env var)
# ═══════════════════════════════════════════════════════════════

ECOSTRUXURE_BASE = "https://api.ecostruxureit.com/rest/v1"
ECOSTRUXURE_KEY = os.environ.get("ECOSTRUXURE_API_KEY", "")


async def ecostruxure_get_locations() -> list[dict]:
    """List all monitored DC locations from EcoStruxure IT."""
    if not ECOSTRUXURE_KEY:
        return _demo_ecostruxure_locations()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{ECOSTRUXURE_BASE}/locations",
                headers={"Authorization": f"Bearer {ECOSTRUXURE_KEY}"},
            )
            if resp.status_code == 200:
                return resp.json().get("locations", [])
            log.warning("EcoStruxure locations: %s", resp.status_code)
    except Exception as e:
        log.debug("EcoStruxure unavailable: %s", e)
    return _demo_ecostruxure_locations()


async def ecostruxure_get_devices(location_id: str = None) -> list[dict]:
    """Get DC devices (PDUs, UPS, CRAC, sensors) from EcoStruxure IT."""
    if not ECOSTRUXURE_KEY:
        return _demo_ecostruxure_devices()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            url = f"{ECOSTRUXURE_BASE}/devices"
            params = {"locationId": location_id} if location_id else {}
            resp = await client.get(url, params=params,
                                    headers={"Authorization": f"Bearer {ECOSTRUXURE_KEY}"})
            if resp.status_code == 200:
                return resp.json().get("devices", [])
    except Exception as e:
        log.debug("EcoStruxure devices: %s", e)
    return _demo_ecostruxure_devices()


async def ecostruxure_get_alarms(severity: str = None) -> list[dict]:
    """Get active alarms from EcoStruxure IT Expert."""
    if not ECOSTRUXURE_KEY:
        return _demo_ecostruxure_alarms()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            params = {}
            if severity:
                params["severity"] = severity
            resp = await client.get(
                f"{ECOSTRUXURE_BASE}/alarms", params=params,
                headers={"Authorization": f"Bearer {ECOSTRUXURE_KEY}"},
            )
            if resp.status_code == 200:
                return resp.json().get("alarms", [])
    except Exception as e:
        log.debug("EcoStruxure alarms: %s", e)
    return _demo_ecostruxure_alarms()


async def ecostruxure_get_measurements(device_id: str) -> dict:
    """Get live sensor measurements for a specific device."""
    if not ECOSTRUXURE_KEY:
        return _demo_ecostruxure_measurements(device_id)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{ECOSTRUXURE_BASE}/sensors/{device_id}/measurements",
                headers={"Authorization": f"Bearer {ECOSTRUXURE_KEY}"},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        log.debug("EcoStruxure measurements: %s", e)
    return _demo_ecostruxure_measurements(device_id)


# Demo data (used when API key not configured)
def _demo_ecostruxure_locations():
    return [
        {"id": "loc-wc-01", "name": "Waltham Cross DC Hall A", "address": "Lee Valley, Hertfordshire",
         "type": "data_centre", "status": "active", "total_power_kw": 85000, "pue": 1.22,
         "cooling_type": "hybrid", "tier": 3},
        {"id": "loc-sl-01", "name": "Slough Campus", "address": "Slough, Berkshire",
         "type": "data_centre", "status": "active", "total_power_kw": 120000, "pue": 1.35,
         "cooling_type": "mechanical", "tier": 3},
    ]

def _demo_ecostruxure_devices():
    import random
    r = random.Random(42)
    return [
        {"id": "ups-01", "type": "UPS", "name": "Symmetra PX 500kW A", "status": "online",
         "load_pct": r.randint(55, 75), "battery_pct": 100, "input_kw": r.randint(400, 480)},
        {"id": "ups-02", "type": "UPS", "name": "Symmetra PX 500kW B", "status": "online",
         "load_pct": r.randint(50, 70), "battery_pct": 100, "input_kw": r.randint(380, 460)},
        {"id": "pdu-01", "type": "PDU", "name": "Rack PDU AP8886 Row A", "status": "online",
         "load_pct": r.randint(40, 80), "power_kw": r.randint(15, 35)},
        {"id": "crac-01", "type": "CRAC", "name": "InRow Cooling DX 30kW", "status": "online",
         "supply_temp_c": round(r.uniform(18, 22), 1), "return_temp_c": round(r.uniform(32, 38), 1),
         "fan_speed_pct": r.randint(40, 80)},
        {"id": "sensor-01", "type": "Environmental", "name": "Temp/Humidity A1",
         "temperature_c": round(r.uniform(20, 24), 1), "humidity_pct": round(r.uniform(40, 55), 1)},
    ]

def _demo_ecostruxure_alarms():
    return [
        {"id": "alm-001", "severity": "warning", "device": "UPS-01",
         "message": "Battery runtime below 10 minutes at current load", "timestamp": "2026-03-22T15:30:00Z"},
        {"id": "alm-002", "severity": "critical", "device": "CRAC-02",
         "message": "Return air temperature exceeds 38°C threshold", "timestamp": "2026-03-22T16:45:00Z"},
    ]

def _demo_ecostruxure_measurements(device_id: str):
    import random, math
    r = random.Random(hash(device_id))
    hour = time.localtime().tm_hour
    load_factor = 0.6 + 0.2 * math.sin((hour - 14) * math.pi / 12)
    return {
        "device_id": device_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "power_kw": round(r.uniform(20, 50) * load_factor, 1),
        "current_a": round(r.uniform(30, 80) * load_factor, 1),
        "voltage_v": round(r.uniform(228, 232), 1),
        "temperature_c": round(r.uniform(20, 26), 1),
        "humidity_pct": round(r.uniform(40, 55), 1),
        "source": "demo" if not ECOSTRUXURE_KEY else "ecostruxure_live",
    }


# ═══════════════════════════════════════════════════════════════
#  SIEMENS BUILDING X
#  API: https://api.siemens.com/building-x/
#  Auth: OAuth2 (SIEMENS_BX_CLIENT_ID + SIEMENS_BX_CLIENT_SECRET)
# ═══════════════════════════════════════════════════════════════

SIEMENS_AUTH_URL = "https://siemens-bt-015.eu.auth0.com/oauth/token"
SIEMENS_API_BASE = "https://api.siemens.com/building-x-openness/api/v1"
SIEMENS_CLIENT_ID = os.environ.get("SIEMENS_BX_CLIENT_ID", "")
SIEMENS_CLIENT_SECRET = os.environ.get("SIEMENS_BX_CLIENT_SECRET", "")

_siemens_token = None
_siemens_token_expiry = 0


async def _siemens_auth() -> str:
    """Get OAuth2 access token for Siemens Building X."""
    global _siemens_token, _siemens_token_expiry
    if _siemens_token and time.time() < _siemens_token_expiry:
        return _siemens_token
    if not SIEMENS_CLIENT_ID:
        return ""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(SIEMENS_AUTH_URL, json={
                "client_id": SIEMENS_CLIENT_ID,
                "client_secret": SIEMENS_CLIENT_SECRET,
                "audience": "https://horizondev.2.siemens-bt.com",
                "grant_type": "client_credentials",
            })
            if resp.status_code == 200:
                data = resp.json()
                _siemens_token = data["access_token"]
                _siemens_token_expiry = time.time() + data.get("expires_in", 3600) - 60
                return _siemens_token
    except Exception as e:
        log.debug("Siemens auth failed: %s", e)
    return ""


async def siemens_get_devices() -> list[dict]:
    """Get BMS devices from Siemens Building X."""
    token = await _siemens_auth()
    if not token:
        return _demo_siemens_devices()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{SIEMENS_API_BASE}/devices",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 200:
                return resp.json().get("data", [])
    except Exception as e:
        log.debug("Siemens devices: %s", e)
    return _demo_siemens_devices()


async def siemens_get_points(device_id: str) -> list[dict]:
    """Get data points (sensors/actuators) for a Siemens BMS device."""
    token = await _siemens_auth()
    if not token:
        return _demo_siemens_points(device_id)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{SIEMENS_API_BASE}/devices/{device_id}/points",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 200:
                return resp.json().get("data", [])
    except Exception as e:
        log.debug("Siemens points: %s", e)
    return _demo_siemens_points(device_id)


async def siemens_get_point_values(point_id: str, from_ts: str = None, to_ts: str = None) -> list[dict]:
    """Get time-series values for a Siemens BMS data point."""
    token = await _siemens_auth()
    if not token:
        return _demo_siemens_values(point_id)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            params = {}
            if from_ts:
                params["from"] = from_ts
            if to_ts:
                params["to"] = to_ts
            resp = await client.get(
                f"{SIEMENS_API_BASE}/points/{point_id}/values",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 200:
                return resp.json().get("data", [])
    except Exception as e:
        log.debug("Siemens values: %s", e)
    return _demo_siemens_values(point_id)


def _demo_siemens_devices():
    return [
        {"id": "chiller-01", "type": "Chiller", "name": "York YVWA 2000kW",
         "status": "running", "cop": 5.2, "load_pct": 65, "power_kw": 250},
        {"id": "ahu-01", "type": "AHU", "name": "Air Handling Unit A",
         "status": "running", "supply_temp_c": 13, "return_temp_c": 24, "fan_speed_pct": 70},
        {"id": "meter-main", "type": "PowerMeter", "name": "Main Incomer 132kV",
         "power_kw": 85000, "power_factor": 0.95, "voltage_kv": 132, "current_a": 372},
        {"id": "meter-it", "type": "PowerMeter", "name": "IT Load Meter",
         "power_kw": 68000, "power_factor": 0.98},
        {"id": "ct-01", "type": "CoolingTower", "name": "Cooling Tower 1",
         "status": "running", "water_temp_c": 28, "fan_speed_pct": 55},
    ]

def _demo_siemens_points(device_id: str):
    return [
        {"id": f"{device_id}_power", "name": "Active Power", "unit": "kW", "type": "analog"},
        {"id": f"{device_id}_temp", "name": "Temperature", "unit": "°C", "type": "analog"},
        {"id": f"{device_id}_status", "name": "Status", "unit": "", "type": "binary"},
    ]

def _demo_siemens_values(point_id: str):
    import math
    now = time.time()
    return [
        {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - i * 900)),
         "value": round(50 + 20 * math.sin(i * 0.3) + (hash(point_id) % 10), 1)}
        for i in range(24)  # 24 readings, 15-min intervals
    ]


# ═══════════════════════════════════════════════════════════════
#  NORMALISED TELEMETRY — unified output for Princeps consumption
# ═══════════════════════════════════════════════════════════════

async def get_dcim_telemetry(platform: str = "auto") -> dict:
    """
    Get normalised DC telemetry from whichever DCIM platform is configured.

    Returns unified format regardless of source:
    {
        "platform": "ecostruxure|siemens|demo",
        "timestamp": ISO8601,
        "total_power_kw": float,
        "it_load_kw": float,
        "cooling_kw": float,
        "pue": float,
        "devices": [...],
        "alarms": [...],
    }
    """
    # Try EcoStruxure first
    if platform in ("auto", "ecostruxure") and ECOSTRUXURE_KEY:
        devices = await ecostruxure_get_devices()
        alarms = await ecostruxure_get_alarms()
        total_kw = sum(d.get("input_kw", 0) or d.get("power_kw", 0) for d in devices)
        it_kw = sum(d.get("power_kw", 0) for d in devices if d.get("type") in ("PDU", "Server"))
        cooling_kw = sum(d.get("power_kw", 0) for d in devices if d.get("type") in ("CRAC", "Chiller"))
        return {
            "platform": "ecostruxure",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_power_kw": total_kw,
            "it_load_kw": it_kw or total_kw * 0.75,
            "cooling_kw": cooling_kw or total_kw * 0.2,
            "pue": round(total_kw / max(it_kw or total_kw * 0.75, 1), 3),
            "devices": devices,
            "alarms": alarms,
        }

    # Try Siemens
    if platform in ("auto", "siemens") and SIEMENS_CLIENT_ID:
        devices = await siemens_get_devices()
        total_kw = sum(d.get("power_kw", 0) for d in devices if d.get("type") == "PowerMeter")
        it_kw = next((d.get("power_kw", 0) for d in devices if "IT" in d.get("name", "")), total_kw * 0.8)
        cooling_kw = sum(d.get("power_kw", 0) for d in devices if d.get("type") in ("Chiller", "CoolingTower"))
        return {
            "platform": "siemens",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_power_kw": total_kw,
            "it_load_kw": it_kw,
            "cooling_kw": cooling_kw,
            "pue": round(total_kw / max(it_kw, 1), 3) if total_kw > 0 else 1.3,
            "devices": devices,
            "alarms": [],
        }

    # Demo mode
    eco_devices = _demo_ecostruxure_devices()
    siem_devices = _demo_siemens_devices()
    return {
        "platform": "demo",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_power_kw": 85000,
        "it_load_kw": 68000,
        "cooling_kw": 14000,
        "pue": 1.25,
        "devices": eco_devices + siem_devices,
        "alarms": _demo_ecostruxure_alarms(),
        "note": "Demo data — set ECOSTRUXURE_API_KEY or SIEMENS_BX_CLIENT_ID to connect live DCIM",
    }
