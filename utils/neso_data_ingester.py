"""
NESO (National Energy System Operator) data ingester.

Integrates:
  - Carbon Intensity API (api.carbonintensity.org.uk) — gCO2/kWh national + regional
  - BMRS / Elexon — demand outturn, generation mix, system prices
  - NESO CKAN — TEC register, connection queue analysis

All endpoints are public — no API keys required.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger("princeps.neso_ingester")

_TIMEOUT = 15
_UA = "Princeps/1.0"
_BMRS = "https://data.elexon.co.uk/bmrs/api/v1"
_CARBON = "https://api.carbonintensity.org.uk"
_NESO_CKAN = "https://api.neso.energy/api/3/action"

# TEC Register resource ID on NESO CKAN
_TEC_RESOURCE = "17becbab-e3e8-473f-b303-3806f43a6a10"


async def _get(client: httpx.AsyncClient, url: str, params: dict = None) -> dict | list | None:
    try:
        resp = await client.get(url, params={**(params or {}), "format": "json"})
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        log.debug("NESO API call failed: %s — %s", url, e)
    return None


# ─── Carbon Intensity ─────────────────────────────────────────────────────────

async def fetch_carbon_intensity(
    from_dt: str | None = None,
    to_dt: str | None = None,
    regional: bool = False,
) -> dict:
    """Fetch carbon intensity — current, time range, or regional."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        if regional:
            data = await _get(client, f"{_CARBON}/regional")
            regions = []
            if data and "data" in data:
                for item in data["data"]:
                    for r in item.get("regions", []):
                        regions.append({
                            "region_id": r.get("regionid"),
                            "shortname": r.get("shortname"),
                            "intensity_forecast": r.get("intensity", {}).get("forecast"),
                            "intensity_index": r.get("intensity", {}).get("index"),
                            "generation_mix": r.get("generationmix", []),
                        })
            return {"regional": regions, "count": len(regions)}

        if from_dt and to_dt:
            data = await _get(client, f"{_CARBON}/intensity/{from_dt}/{to_dt}")
        else:
            data = await _get(client, f"{_CARBON}/intensity")

        if not data or "data" not in data:
            return {"error": "No carbon intensity data available"}

        items = data["data"]
        if isinstance(items, list):
            return {
                "records": [
                    {
                        "from": r.get("from"),
                        "to": r.get("to"),
                        "forecast": r.get("intensity", {}).get("forecast"),
                        "actual": r.get("intensity", {}).get("actual"),
                        "index": r.get("intensity", {}).get("index"),
                    }
                    for r in items
                ],
                "count": len(items),
            }
        return {
            "current": {
                "forecast": items.get("intensity", {}).get("forecast"),
                "actual": items.get("intensity", {}).get("actual"),
                "index": items.get("intensity", {}).get("index"),
            }
        }


# ─── Demand Outturn ───────────────────────────────────────────────────────────

async def fetch_demand_outturn(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Fetch half-hourly national demand from BMRS."""
    now = datetime.now(timezone.utc)
    end = datetime.fromisoformat(end_date) if end_date else now
    start = datetime.fromisoformat(start_date) if start_date else (now - timedelta(days=1))

    records = []
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        # BMRS allows ~7 day windows
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(chunk_start + timedelta(days=7), end)
            params = {
                "from": chunk_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": chunk_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            data = await _get(client, f"{_BMRS}/demand/outturn", params)
            if data:
                items = data if isinstance(data, list) else data.get("data", [])
                for item in items:
                    records.append({
                        "settlement_date": item.get("settlementDate"),
                        "settlement_period": item.get("settlementPeriod"),
                        "demand_mw": item.get("initialTransmissionSystemDemandOutturn")
                            or item.get("initialDemandOutturn")
                            or item.get("demand"),
                    })
            chunk_start = chunk_end

    return {
        "records": records,
        "count": len(records),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


# ─── Generation Mix ───────────────────────────────────────────────────────────

async def fetch_generation_mix(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Fetch generation by fuel type from BMRS FUELINST."""
    now = datetime.now(timezone.utc)
    end_str = end_date or now.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_str = start_date or (now - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        data = await _get(client, f"{_BMRS}/datasets/FUELINST", {
            "publishDateTimeFrom": start_str,
            "publishDateTimeTo": end_str,
        })

    if not data or "data" not in data:
        return {"error": "No generation data available"}

    items = data["data"]
    fuel_map = {
        "CCGT": "gas", "OCGT": "gas", "OIL": "oil", "COAL": "coal",
        "BIOMASS": "biomass", "NUCLEAR": "nuclear", "WIND": "wind",
        "PS": "pumped", "NPSHYD": "hydro", "OTHER": "other",
    }

    # Aggregate by fuel
    by_fuel = {}
    for item in items:
        fuel_raw = item.get("fuelType", "OTHER")
        fuel = fuel_map.get(fuel_raw, fuel_raw.lower())
        mw = item.get("generation") or item.get("quantity") or 0
        by_fuel.setdefault(fuel, []).append(float(mw))

    summary = {}
    for fuel, vals in by_fuel.items():
        summary[fuel] = round(sum(vals) / len(vals)) if vals else 0

    total = sum(summary.values())
    renewable = sum(v for k, v in summary.items() if k in {"wind", "solar", "hydro", "biomass"})

    return {
        "by_fuel": summary,
        "total_mw": total,
        "renewable_mw": renewable,
        "renewable_pct": round(renewable / total * 100, 1) if total else 0,
        "record_count": len(items),
    }


# ─── TEC Register (Connection Queue) ─────────────────────────────────────────

async def fetch_tec_register(
    connection_site: str | None = None,
    technology: str | None = None,
    min_capacity_mw: float | None = None,
    status: str | None = None,
    limit: int = 5000,
) -> dict:
    """Fetch TEC register from NESO CKAN — all projects holding Transmission Entry Capacity."""
    records = []
    offset = 0

    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": _UA}) as client:
        while True:
            params = {
                "resource_id": _TEC_RESOURCE,
                "limit": limit,
                "offset": offset,
            }
            # Build filters
            filters = {}
            if connection_site:
                filters["Connection Site"] = connection_site
            if technology:
                filters["Fuel Type"] = technology
            if status:
                filters["Status"] = status
            if filters:
                import json
                params["filters"] = json.dumps(filters)

            data = await _get(client, f"{_NESO_CKAN}/datastore_search", params)
            if not data or "result" not in data:
                break

            result = data["result"]
            batch = result.get("records", [])
            for r in batch:
                capacity = r.get("TEC (MW)") or r.get("Capacity (MW)") or 0
                try:
                    capacity = float(capacity)
                except (ValueError, TypeError):
                    capacity = 0

                if min_capacity_mw and capacity < min_capacity_mw:
                    continue

                records.append({
                    "customer": r.get("Customer Name") or r.get("Developer"),
                    "connection_site": r.get("Connection Site") or r.get("Connection Point"),
                    "fuel_type": r.get("Fuel Type") or r.get("Technology"),
                    "capacity_mw": capacity,
                    "status": r.get("Status"),
                    "connection_date": r.get("Connection Date") or r.get("Energisation Date"),
                    "tec_mw": capacity,
                })

            if len(batch) < limit:
                break
            offset += limit

    return {
        "records": records,
        "count": len(records),
        "total_capacity_mw": round(sum(r["capacity_mw"] for r in records), 1),
    }


# ─── System Prices ────────────────────────────────────────────────────────────

async def fetch_system_prices(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Fetch system buy/sell prices from BMRS."""
    now = datetime.now(timezone.utc)
    params = {
        "from": start_date or (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        "to": end_date or now.strftime("%Y-%m-%d"),
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        data = await _get(client, f"{_BMRS}/balancing/settlement/system-prices", params)

    if not data:
        return {"error": "No system price data available"}

    items = data if isinstance(data, list) else data.get("data", [])
    records = []
    for item in items:
        buy = item.get("systemSellPrice") or item.get("sellPrice") or 0
        sell = item.get("systemBuyPrice") or item.get("buyPrice") or 0
        try:
            buy, sell = float(buy), float(sell)
        except (ValueError, TypeError):
            buy, sell = 0, 0
        records.append({
            "settlement_date": item.get("settlementDate"),
            "settlement_period": item.get("settlementPeriod"),
            "buy_price": buy,
            "sell_price": sell,
            "spread": round(abs(buy - sell), 2),
        })

    if records:
        prices = [r["buy_price"] for r in records if r["buy_price"]]
        return {
            "records": records,
            "count": len(records),
            "stats": {
                "mean": round(sum(prices) / len(prices), 2) if prices else 0,
                "min": round(min(prices), 2) if prices else 0,
                "max": round(max(prices), 2) if prices else 0,
            },
        }
    return {"records": [], "count": 0}


# ─── Connection Queue Analysis ────────────────────────────────────────────────

async def fetch_connection_queue(location: str | None = None) -> dict:
    """Higher-level queue analysis — groups TEC register by connection site."""
    tec = await fetch_tec_register(connection_site=location)
    records = tec.get("records", [])

    # Group by connection site
    sites = {}
    for r in records:
        site = r.get("connection_site", "Unknown")
        if site not in sites:
            sites[site] = {"total_mw": 0, "projects": 0, "by_fuel": {}}
        sites[site]["total_mw"] += r["capacity_mw"]
        sites[site]["projects"] += 1
        fuel = r.get("fuel_type", "Other")
        sites[site]["by_fuel"][fuel] = sites[site]["by_fuel"].get(fuel, 0) + r["capacity_mw"]

    # Score congestion (0-100) — based on queued MW relative to typical substation capacity
    TYPICAL_CAPACITY_MW = 500  # typical 400kV substation
    queue_analysis = []
    for site_name, data in sorted(sites.items(), key=lambda x: -x[1]["total_mw"]):
        congestion = min(100, round(data["total_mw"] / TYPICAL_CAPACITY_MW * 100))
        queue_analysis.append({
            "connection_site": site_name,
            "queued_mw": round(data["total_mw"], 1),
            "project_count": data["projects"],
            "congestion_score": congestion,
            "congestion_level": "critical" if congestion > 80 else "high" if congestion > 60 else "moderate" if congestion > 30 else "low",
            "by_fuel": data["by_fuel"],
            "estimated_wait_years": round(congestion * 0.08, 1),  # rough heuristic
        })

    return {
        "sites": queue_analysis[:50],  # top 50 most congested
        "total_sites": len(queue_analysis),
        "total_queued_mw": round(sum(s["queued_mw"] for s in queue_analysis), 1),
    }


# ─── DB Table Setup ───────────────────────────────────────────────────────────

async def setup_neso_tables(pool) -> None:
    """Create NESO-specific tables if they don't exist."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS neso_tec_register (
                id SERIAL PRIMARY KEY,
                customer TEXT,
                connection_site TEXT,
                fuel_type TEXT,
                capacity_mw REAL,
                status TEXT,
                connection_date TEXT,
                ingested_at TIMESTAMPTZ DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_neso_tec_site ON neso_tec_register(connection_site);
            CREATE INDEX IF NOT EXISTS idx_neso_tec_fuel ON neso_tec_register(fuel_type);

            CREATE TABLE IF NOT EXISTS neso_system_prices (
                id SERIAL PRIMARY KEY,
                settlement_date TEXT,
                settlement_period INT,
                buy_price REAL,
                sell_price REAL,
                spread REAL,
                ingested_at TIMESTAMPTZ DEFAULT now()
            );
        """)
    log.info("NESO tables ensured")


# ─── Batch Ingest ─────────────────────────────────────────────────────────────

async def ingest_all(pool=None) -> dict:
    """Run all NESO fetchers concurrently. Optionally persist to DB."""
    results = await asyncio.gather(
        fetch_carbon_intensity(),
        fetch_demand_outturn(),
        fetch_generation_mix(),
        fetch_tec_register(),
        fetch_system_prices(),
        return_exceptions=True,
    )

    keys = ["carbon_intensity", "demand", "generation_mix", "tec_register", "system_prices"]
    summary = {}
    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            summary[key] = {"status": "error", "error": str(result)}
        else:
            count = result.get("count", 0) if isinstance(result, dict) else 0
            summary[key] = {"status": "ok", "count": count}

    # Persist TEC register if pool available
    if pool and isinstance(results[3], dict):
        records = results[3].get("records", [])
        if records:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM neso_tec_register")
                await conn.executemany(
                    """INSERT INTO neso_tec_register
                       (customer, connection_site, fuel_type, capacity_mw, status, connection_date)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    [
                        (r["customer"], r["connection_site"], r["fuel_type"],
                         r["capacity_mw"], r["status"], r["connection_date"])
                        for r in records
                    ],
                )
                summary["tec_register"]["persisted"] = len(records)

    return summary
