"""
BMRS Dataset Integration — Elexon Insights API.

Fetches key datasets from data.elexon.co.uk for:
  - AGWS: Actual wind + solar generation (hourly CFE matching)
  - WINDFOR: Wind generation forecast (DC CFE planning)
  - SYSWARN: System warnings (constraint detection)
  - TEMP: Temperature data (ASHRAE/cooling models)
  - FREQ: System frequency (grid stability)
  - FUELINST: Instantaneous generation by fuel type

No API key required — all endpoints are public.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger("princeps.bmrs")

BASE = "https://data.elexon.co.uk/bmrs/api/v1"
_TIMEOUT = 15


async def _get(path: str, params: dict = None) -> dict | list | None:
    """GET request to Elexon BMRS API."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(f"{BASE}{path}", params=params or {})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.warning("BMRS %s failed: %s", path, e)
        return None


# ═══════════════════════════════════════════════════════════════
#  AGWS — Actual Wind & Solar Generation
# ═══════════════════════════════════════════════════════════════

async def fetch_wind_solar_actual(hours_back: int = 24) -> list[dict] | None:
    """Actual or estimated wind and solar power generation (AGWS/B1630).

    Returns hourly data points with:
      - settlementDate, settlementPeriod
      - powerSystemResourceType (wind_onshore, wind_offshore, solar)
      - quantity (MW)
    """
    now = datetime.now(timezone.utc)
    from_dt = (now - timedelta(hours=hours_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_dt = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    data = await _get("/datasets/AGWS", {
        "publishDateTimeFrom": from_dt,
        "publishDateTimeTo": to_dt,
        "format": "json",
    })
    if not data:
        return None

    records = data if isinstance(data, list) else data.get("data", [])
    results = []
    for r in records:
        results.append({
            "timestamp": r.get("startTime") or r.get("settlementDate"),
            "period": r.get("settlementPeriod"),
            "type": r.get("powerSystemResourceType", "").lower(),
            "mw": r.get("quantity", 0),
        })
    return results


async def wind_solar_summary() -> dict:
    """Current wind + solar generation summary."""
    records = await fetch_wind_solar_actual(hours_back=1)
    if not records:
        return {"wind_mw": 0, "solar_mw": 0, "total_renewable_mw": 0}

    wind = sum(r["mw"] for r in records if "wind" in r["type"])
    solar = sum(r["mw"] for r in records if "solar" in r["type"])
    # Deduplicate by taking latest period
    return {
        "wind_mw": round(wind, 1),
        "solar_mw": round(solar, 1),
        "total_renewable_mw": round(wind + solar, 1),
        "record_count": len(records),
    }


# ═══════════════════════════════════════════════════════════════
#  WINDFOR — Wind Generation Forecast
# ═══════════════════════════════════════════════════════════════

async def fetch_wind_forecast(hours_ahead: int = 48) -> list[dict] | None:
    """Wind generation forecast (WINDFOR).

    Returns forecast data points with MW by settlement period.
    Useful for DC CFE planning — predict how much wind will be available.
    """
    data = await _get("/forecast/generation/wind", {
        "format": "json",
    })
    if not data:
        return None

    records = data if isinstance(data, list) else data.get("data", [])
    results = []
    for r in records[:hours_ahead * 2]:  # 2 settlement periods per hour
        results.append({
            "timestamp": r.get("startTime"),
            "forecast_mw": r.get("generation", r.get("quantity", 0)),
            "period": r.get("settlementPeriod"),
        })
    return results


async def wind_forecast_24h() -> dict:
    """24-hour wind forecast aggregated by hour."""
    records = await fetch_wind_forecast(48)
    if not records:
        return {"hours": [], "avg_mw": 0, "peak_mw": 0}

    # Aggregate by hour (2 periods per hour)
    hourly = {}
    for r in records:
        ts = r.get("timestamp", "")
        hour = ts[:13] if ts else None
        if hour:
            if hour not in hourly:
                hourly[hour] = []
            hourly[hour].append(r["forecast_mw"])

    hours = []
    for h, vals in sorted(hourly.items())[:24]:
        avg = sum(vals) / len(vals) if vals else 0
        hours.append({"hour": h, "forecast_mw": round(avg, 1)})

    all_mw = [h["forecast_mw"] for h in hours]
    return {
        "hours": hours,
        "avg_mw": round(sum(all_mw) / len(all_mw), 1) if all_mw else 0,
        "peak_mw": round(max(all_mw), 1) if all_mw else 0,
        "min_mw": round(min(all_mw), 1) if all_mw else 0,
    }


# ═══════════════════════════════════════════════════════════════
#  SYSWARN — System Warnings
# ═══════════════════════════════════════════════════════════════

async def fetch_system_warnings() -> list[dict] | None:
    """Active system warnings (SYSWARN).

    Constraint alerts, demand control instructions, system events.
    """
    data = await _get("/system/warnings", {"format": "json"})
    if not data:
        return None

    records = data if isinstance(data, list) else data.get("data", [])
    results = []
    for r in records:
        results.append({
            "id": r.get("warningType", r.get("id")),
            "message": r.get("warningMessage", r.get("message", "")),
            "publish_time": r.get("publishTime", r.get("createdDateTime")),
            "severity": _classify_warning_severity(r.get("warningMessage", "")),
        })
    return results


def _classify_warning_severity(msg: str) -> str:
    """Classify warning severity from message text."""
    msg_lower = msg.lower()
    if any(w in msg_lower for w in ["emergency", "blackout", "disconnection", "loss of supply"]):
        return "critical"
    if any(w in msg_lower for w in ["constraint", "high demand", "low margin", "insufficient"]):
        return "high"
    if any(w in msg_lower for w in ["planned", "maintenance", "outage"]):
        return "medium"
    return "low"


# ═══════════════════════════════════════════════════════════════
#  TEMP — Temperature Data
# ═══════════════════════════════════════════════════════════════

async def fetch_temperature() -> list[dict] | None:
    """Daily temperature data (TEMP).

    Returns average and reference temperatures.
    Used for ASHRAE compliance and cooling design.
    """
    data = await _get("/temperature", {"format": "json"})
    if not data:
        return None

    records = data if isinstance(data, list) else data.get("data", [])
    results = []
    for r in records:
        results.append({
            "date": r.get("settlementDate", r.get("date")),
            "avg_temp_c": r.get("temperature", r.get("normalReferenceTemperature")),
            "high_temp_c": r.get("highReferenceTemperature"),
            "low_temp_c": r.get("lowReferenceTemperature"),
        })
    return results


# ═══════════════════════════════════════════════════════════════
#  FREQ — System Frequency (real-time)
# ═══════════════════════════════════════════════════════════════

async def fetch_frequency() -> dict | None:
    """Latest system frequency (FREQ). Target: 50.000 Hz."""
    data = await _get("/system/frequency", {"format": "json"})
    if not data:
        return None

    records = data if isinstance(data, list) else data.get("data", [])
    if not records:
        return None

    latest = records[-1] if records else {}
    return {
        "frequency_hz": latest.get("frequency", 50.0),
        "timestamp": latest.get("reportSnapshotTime", latest.get("publishTime")),
    }


# ═══════════════════════════════════════════════════════════════
#  Demand Control Instructions
# ═══════════════════════════════════════════════════════════════

async def fetch_demand_control() -> list[dict] | None:
    """Active demand control instructions (DCI)."""
    data = await _get("/system/demand-control-instructions", {"format": "json"})
    if not data:
        return None

    records = data if isinstance(data, list) else data.get("data", [])
    return [{
        "id": r.get("demandControlId"),
        "instruction": r.get("demandControlInstructionType"),
        "event_time": r.get("eventStartTime"),
        "end_time": r.get("eventEndTime"),
        "so_flag": r.get("soFlag"),
    } for r in records]


# ═══════════════════════════════════════════════════════════════
#  Generation Outturn (current snapshot)
# ═══════════════════════════════════════════════════════════════

async def fetch_generation_current() -> dict | None:
    """Current generation by fuel type (FUELINST)."""
    data = await _get("/generation/outturn/current", {"format": "json"})
    if not data:
        return None

    mix = {}
    total = 0
    for r in (data if isinstance(data, list) else data.get("data", [])):
        fuel = r.get("fuelType", "OTHER").lower()
        mw = r.get("currentUsage", r.get("generation", 0))
        mix[fuel] = round(mw, 1)
        total += mw

    return {
        "generation_mix": mix,
        "total_mw": round(total, 1),
        "renewable_mw": round(
            mix.get("wind", 0) + mix.get("solar", 0) +
            mix.get("hydro", 0) + mix.get("biomass", 0), 1
        ),
        "renewable_pct": round(
            (mix.get("wind", 0) + mix.get("solar", 0) +
             mix.get("hydro", 0) + mix.get("biomass", 0)) / max(total, 1) * 100, 1
        ),
    }


# ═══════════════════════════════════════════════════════════════
#  Combined: Full Grid Intelligence Snapshot
# ═══════════════════════════════════════════════════════════════

async def full_grid_snapshot() -> dict:
    """Comprehensive grid intelligence snapshot combining all BMRS feeds.

    Used by the LiveStatusStrip, Grid Intelligence panel, and DC CFE module.
    """
    import asyncio
    results = await asyncio.gather(
        fetch_generation_current(),
        wind_solar_summary(),
        fetch_frequency(),
        fetch_system_warnings(),
        fetch_temperature(),
        return_exceptions=True,
    )

    gen = results[0] if not isinstance(results[0], Exception) else None
    ws = results[1] if not isinstance(results[1], Exception) else None
    freq = results[2] if not isinstance(results[2], Exception) else None
    warnings = results[3] if not isinstance(results[3], Exception) else None
    temp = results[4] if not isinstance(results[4], Exception) else None

    return {
        "generation": gen,
        "wind_solar": ws,
        "frequency": freq,
        "warnings": warnings,
        "temperature": temp,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
#  Tender Intelligence — Find a Tender Service (FTS)
# ═══════════════════════════════════════════════════════════════

async def fetch_energy_tenders(keywords: list[str] = None, days_back: int = 30, limit: int = 50) -> list[dict]:
    """Fetch energy infrastructure tenders from Find a Tender Service.

    Queries the OCDS API for solar, wind, BESS, data centre, and grid tenders.
    No API key required for read access.
    """
    if keywords is None:
        keywords = ["solar", "battery storage", "BESS", "wind farm", "renewable energy",
                     "data centre", "grid connection", "substation", "EPC contractor"]

    from_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")

    tenders = []
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            # FTS OCDS endpoint
            r = await client.get(
                "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages",
                params={"updatedFrom": from_date, "stages": "tender", "limit": min(limit, 100)},
            )
            if r.status_code == 200:
                data = r.json()
                packages = data if isinstance(data, list) else data.get("releases", data.get("results", []))
                for pkg in packages:
                    release = pkg if isinstance(pkg, dict) else {}
                    tender_data = release.get("tender", {})
                    title = tender_data.get("title", release.get("title", ""))

                    # Filter by energy keywords
                    title_lower = title.lower()
                    if not any(kw.lower() in title_lower for kw in keywords):
                        continue

                    buyer = release.get("buyer", {})
                    tenders.append({
                        "id": release.get("id", release.get("ocid")),
                        "title": title,
                        "description": tender_data.get("description", "")[:200],
                        "value_gbp": tender_data.get("value", {}).get("amount"),
                        "currency": tender_data.get("value", {}).get("currency", "GBP"),
                        "buyer": buyer.get("name", ""),
                        "published": release.get("date"),
                        "deadline": tender_data.get("tenderPeriod", {}).get("endDate"),
                        "status": tender_data.get("status", "active"),
                        "url": f"https://www.find-tender.service.gov.uk/Notice/{release.get('id', '')}",
                    })
    except Exception as e:
        log.warning("FTS tender fetch failed: %s", e)

    # Also try Contracts Finder (no auth needed for search)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for kw in keywords[:3]:  # Limit queries
                r = await client.get(
                    "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search",
                    params={"queryString": kw, "limit": 10, "stage": "tender"},
                )
                if r.status_code == 200:
                    data = r.json()
                    for release in data.get("releases", []):
                        tender_data = release.get("tender", {})
                        tenders.append({
                            "id": release.get("ocid"),
                            "title": tender_data.get("title", ""),
                            "value_gbp": tender_data.get("value", {}).get("amount"),
                            "buyer": release.get("buyer", {}).get("name", ""),
                            "published": release.get("date"),
                            "status": "active",
                            "source": "contracts_finder",
                        })
    except Exception as e:
        log.warning("Contracts Finder fetch failed: %s", e)

    # Deduplicate by title
    seen = set()
    unique = []
    for t in tenders:
        key = t["title"][:50].lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)

    return sorted(unique, key=lambda x: x.get("published") or "", reverse=True)[:limit]
