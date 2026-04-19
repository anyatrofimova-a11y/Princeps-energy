#!/usr/bin/env python3
"""
Demand data ingester — Princeps Phase 5
Fetches historical demand from Elexon BMRS + synthetic GSP profiles.
Runs as subprocess via JSON stdin/stdout bridge (same pattern as SAM/grid).

Commands:
  {"command": "fetch_national", "start_date": "2024-01-01", "end_date": "2024-12-31"}
  {"command": "fetch_gsp", "gsp_id": "ABHA", "start_date": ..., "end_date": ...}
  {"command": "generate_synthetic", "n_gsps": 20, "days": 365}
  {"command": "list_gsps"}
"""

import json
import sys
import math
import random
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

# ─── BMRS API (Elexon Insights v2, no auth needed for demand) ───────────────

BMRS_BASE = "https://data.elexon.co.uk/bmrs/api/v1"

def fetch_national_demand(start_date: str, end_date: str) -> list[dict]:
    """Fetch half-hourly national demand from BMRS Insights API."""
    records = []
    # BMRS demand endpoint: /demand/outturn/summary
    # Limited to ~7 days per request, so paginate
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    current = start

    while current < end:
        chunk_end = min(current + timedelta(days=7), end)
        url = (
            f"{BMRS_BASE}/demand/outturn/summary"
            f"?from={current.strftime('%Y-%m-%dT00:00:00Z')}"
            f"&to={chunk_end.strftime('%Y-%m-%dT23:59:59Z')}"
            f"&format=json"
        )
        try:
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())

            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("data", data.get("results", []))
            else:
                items = []

            for item in items:
                ts = item.get("startTime") or item.get("settlementDate")
                demand = item.get("demand") or item.get("initialDemandOutturn") or item.get("transmissionSystemDemand")
                if ts and demand is not None:
                    records.append({
                        "gsp_id": "national",
                        "gsp_name": "GB National",
                        "timestamp_utc": ts,
                        "demand_mw": float(demand),
                        "source": "bmrs",
                    })
        except (URLError, json.JSONDecodeError, KeyError) as e:
            # Log but continue — partial data is fine
            records.append({
                "warning": f"BMRS fetch failed for {current.date()}-{chunk_end.date()}: {e}"
            })

        current = chunk_end + timedelta(days=1)

    return records


# ─── Synthetic GSP profiles (realistic UK demand patterns) ──────────────────

# Representative UK GSPs with realistic parameters
UK_GSPS = [
    {"gsp_id": "ABHA", "gsp_name": "Abham", "dno": "ukpn", "region": "South East",
     "peak_mw": 285, "min_mw": 95, "capacity_mw": 360, "lat": 51.35, "lon": 0.55},
    {"gsp_id": "BAGU", "gsp_name": "Baglan Bay", "dno": "nged", "region": "South Wales",
     "peak_mw": 180, "min_mw": 55, "capacity_mw": 240, "lat": 51.62, "lon": -3.82},
    {"gsp_id": "BAIN", "gsp_name": "Bainbridge", "dno": "npg", "region": "North East",
     "peak_mw": 42, "min_mw": 12, "capacity_mw": 60, "lat": 54.31, "lon": -2.16},
    {"gsp_id": "BEDD", "gsp_name": "Beddington", "dno": "ukpn", "region": "London",
     "peak_mw": 420, "min_mw": 180, "capacity_mw": 500, "lat": 51.37, "lon": -0.13},
    {"gsp_id": "BOLN", "gsp_name": "Bolney", "dno": "ukpn", "region": "South East",
     "peak_mw": 310, "min_mw": 105, "capacity_mw": 400, "lat": 50.98, "lon": -0.23},
    {"gsp_id": "BRWA", "gsp_name": "Bramley", "dno": "ssen", "region": "South",
     "peak_mw": 520, "min_mw": 210, "capacity_mw": 640, "lat": 51.33, "lon": -1.06},
    {"gsp_id": "CAMA", "gsp_name": "Cambridge Main", "dno": "ukpn", "region": "East",
     "peak_mw": 195, "min_mw": 62, "capacity_mw": 250, "lat": 52.19, "lon": 0.14},
    {"gsp_id": "CELL", "gsp_name": "Cellarhead", "dno": "nged", "region": "Midlands",
     "peak_mw": 240, "min_mw": 80, "capacity_mw": 300, "lat": 53.00, "lon": -2.02},
    {"gsp_id": "DEES", "gsp_name": "Deeside", "dno": "spen", "region": "North Wales",
     "peak_mw": 350, "min_mw": 120, "capacity_mw": 450, "lat": 53.22, "lon": -3.04},
    {"gsp_id": "EDIN", "gsp_name": "Edinburgh South", "dno": "spen", "region": "Scotland",
     "peak_mw": 280, "min_mw": 90, "capacity_mw": 360, "lat": 55.92, "lon": -3.19},
    {"gsp_id": "EXET", "gsp_name": "Exeter Main", "dno": "nged", "region": "South West",
     "peak_mw": 160, "min_mw": 48, "capacity_mw": 200, "lat": 50.72, "lon": -3.53},
    {"gsp_id": "FLEE", "gsp_name": "Fleet", "dno": "ssen", "region": "South",
     "peak_mw": 225, "min_mw": 72, "capacity_mw": 280, "lat": 51.28, "lon": -0.83},
    {"gsp_id": "GRBY", "gsp_name": "Grimsby West", "dno": "npg", "region": "North East",
     "peak_mw": 155, "min_mw": 45, "capacity_mw": 200, "lat": 53.56, "lon": -0.11},
    {"gsp_id": "HAYW", "gsp_name": "Haywards Heath", "dno": "ukpn", "region": "South East",
     "peak_mw": 185, "min_mw": 58, "capacity_mw": 240, "lat": 51.00, "lon": -0.10},
    {"gsp_id": "INDQ", "gsp_name": "Indian Queens", "dno": "nged", "region": "South West",
     "peak_mw": 130, "min_mw": 38, "capacity_mw": 160, "lat": 50.39, "lon": -4.95},
    {"gsp_id": "KEAD", "gsp_name": "Keadby", "dno": "npg", "region": "Yorkshire",
     "peak_mw": 290, "min_mw": 95, "capacity_mw": 360, "lat": 53.60, "lon": -0.75},
    {"gsp_id": "LOVE", "gsp_name": "Lovedon", "dno": "ssen", "region": "South",
     "peak_mw": 200, "min_mw": 65, "capacity_mw": 260, "lat": 51.08, "lon": -1.20},
    {"gsp_id": "MANN", "gsp_name": "Manchester South", "dno": "enwl", "region": "North West",
     "peak_mw": 480, "min_mw": 195, "capacity_mw": 600, "lat": 53.45, "lon": -2.25},
    {"gsp_id": "NORW", "gsp_name": "Norwich Main", "dno": "ukpn", "region": "East",
     "peak_mw": 210, "min_mw": 68, "capacity_mw": 280, "lat": 52.62, "lon": 1.30},
    {"gsp_id": "PYLE", "gsp_name": "Pyle", "dno": "nged", "region": "South Wales",
     "peak_mw": 165, "min_mw": 50, "capacity_mw": 210, "lat": 51.53, "lon": -3.70},
]


def _demand_profile(hour: float, day_of_year: int, peak_mw: float, min_mw: float,
                    embedded_solar_mw: float = 0) -> float:
    """Generate realistic UK half-hourly demand from diurnal + seasonal patterns."""
    # Diurnal pattern: two peaks (morning ~8-9, evening ~17-19), trough ~3-5am
    morning_peak = math.exp(-0.5 * ((hour - 8.5) / 1.8) ** 2) * 0.85
    evening_peak = math.exp(-0.5 * ((hour - 17.5) / 2.0) ** 2) * 1.0
    night_trough = 0.35 + 0.15 * math.cos(2 * math.pi * (hour - 3) / 24)
    diurnal = max(night_trough, morning_peak, evening_peak)

    # Seasonal pattern: winter peak, summer trough (UK heating demand)
    seasonal = 0.7 + 0.3 * math.cos(2 * math.pi * (day_of_year - 15) / 365)

    # Weekend reduction (~10-15%)
    # day_of_year % 7 gives approximate weekday (not exact but good enough for synthetic)
    weekend_factor = 0.88 if (day_of_year % 7) in (5, 6) else 1.0

    base = min_mw + (peak_mw - min_mw) * diurnal * seasonal * weekend_factor

    # Subtract embedded solar (peaks midday in summer)
    if embedded_solar_mw > 0:
        solar_hour = max(0, math.sin(math.pi * max(0, min(1, (hour - 6) / 12))))
        solar_seasonal = max(0.1, math.sin(math.pi * (day_of_year - 80) / 365))
        solar_output = embedded_solar_mw * solar_hour * solar_seasonal
        base -= solar_output

    # Add noise (±3%)
    base *= 1 + random.gauss(0, 0.03)

    return round(max(min_mw * 0.3, base), 1)


def generate_synthetic_demand(n_gsps: int = 20, days: int = 365,
                              start_date: str = "2024-01-01") -> dict:
    """Generate synthetic half-hourly demand for n_gsps over specified days."""
    gsps = UK_GSPS[:n_gsps]
    start = datetime.fromisoformat(start_date)
    records = []
    profiles = []

    for gsp in gsps:
        embedded_solar = gsp["peak_mw"] * random.uniform(0.05, 0.15)

        profiles.append({
            "gsp_id": gsp["gsp_id"],
            "gsp_name": gsp["gsp_name"],
            "dno": gsp["dno"],
            "region": gsp["region"],
            "peak_demand_mw": gsp["peak_mw"],
            "min_demand_mw": gsp["min_mw"],
            "capacity_mw": gsp["capacity_mw"],
            "embedded_gen_mw": round(embedded_solar, 1),
            "lat": gsp["lat"],
            "lon": gsp["lon"],
        })

        for day in range(days):
            day_of_year = (start + timedelta(days=day)).timetuple().tm_yday
            dt_base = start + timedelta(days=day)

            for hh in range(48):  # 48 half-hours
                hour = hh / 2.0
                demand = _demand_profile(hour, day_of_year, gsp["peak_mw"],
                                         gsp["min_mw"], embedded_solar)
                ts = dt_base + timedelta(minutes=30 * hh)
                net = demand  # net_demand = demand - embedded_gen (already subtracted)

                records.append({
                    "gsp_id": gsp["gsp_id"],
                    "gsp_name": gsp["gsp_name"],
                    "timestamp_utc": ts.isoformat() + "Z",
                    "demand_mw": round(demand + embedded_solar, 1),  # gross
                    "generation_mw": round(embedded_solar * max(0, math.sin(math.pi * max(0, min(1, (hour - 6) / 12)))) * max(0.1, math.sin(math.pi * (day_of_year - 80) / 365)), 1),
                    "net_demand_mw": round(net, 1),
                    "source": "synthetic",
                })

    return {
        "profiles": profiles,
        "records_count": len(records),
        "gsps": len(gsps),
        "days": days,
        "records": records,
    }


def generate_compact_synthetic(n_gsps: int = 20, days: int = 30,
                               start_date: str = "2024-06-01") -> dict:
    """Generate compact summary: daily peak/min/mean per GSP (for quick loading)."""
    gsps = UK_GSPS[:n_gsps]
    start = datetime.fromisoformat(start_date)
    daily_summaries = []
    profiles = []

    for gsp in gsps:
        embedded_solar = gsp["peak_mw"] * random.uniform(0.05, 0.15)
        profiles.append({
            "gsp_id": gsp["gsp_id"],
            "gsp_name": gsp["gsp_name"],
            "dno": gsp["dno"],
            "region": gsp["region"],
            "peak_demand_mw": gsp["peak_mw"],
            "min_demand_mw": gsp["min_mw"],
            "capacity_mw": gsp["capacity_mw"],
            "embedded_gen_mw": round(embedded_solar, 1),
            "lat": gsp["lat"],
            "lon": gsp["lon"],
        })

        for day in range(days):
            day_of_year = (start + timedelta(days=day)).timetuple().tm_yday
            dt_base = start + timedelta(days=day)

            hh_values = []
            for hh in range(48):
                hour = hh / 2.0
                d = _demand_profile(hour, day_of_year, gsp["peak_mw"],
                                    gsp["min_mw"], embedded_solar)
                hh_values.append(d)

            daily_summaries.append({
                "gsp_id": gsp["gsp_id"],
                "date": dt_base.strftime("%Y-%m-%d"),
                "peak_mw": round(max(hh_values), 1),
                "min_mw": round(min(hh_values), 1),
                "mean_mw": round(sum(hh_values) / len(hh_values), 1),
                "capacity_mw": gsp["capacity_mw"],
            })

    return {
        "profiles": profiles,
        "daily_summaries": daily_summaries,
        "gsps": len(gsps),
        "days": days,
    }


def list_gsps() -> list[dict]:
    """Return metadata for all available GSPs."""
    return [
        {
            "gsp_id": g["gsp_id"],
            "gsp_name": g["gsp_name"],
            "dno": g["dno"],
            "region": g["region"],
            "peak_demand_mw": g["peak_mw"],
            "min_demand_mw": g["min_mw"],
            "capacity_mw": g["capacity_mw"],
            "lat": g["lat"],
            "lon": g["lon"],
        }
        for g in UK_GSPS
    ]


# ─── Async helper for IngestionAgent ────────────────────────────────────────

async def refresh_recent(pool, *, lookback_days: int = 2) -> int:
    """Fetch the last ``lookback_days`` of BMRS national demand and upsert
    into ``demand_historical``.

    Called by ``app.agents.ingestion.IngestionAgent`` with an asyncpg pool.
    Returns the number of rows written (0 if BMRS returned nothing).

    The BMRS fetch is synchronous (urllib); we run it off the event loop via
    ``asyncio.to_thread`` so the worker doesn't block on network IO.
    """
    import asyncio
    from datetime import datetime, timezone, timedelta

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(1, lookback_days))

    records = await asyncio.to_thread(
        fetch_national_demand,
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
    )

    # Filter out warning dicts emitted by fetch_national_demand on partial
    # failures — only keep rows with a usable timestamp + demand value.
    rows = [
        (
            r["gsp_id"],
            r.get("gsp_name"),
            r["timestamp_utc"],
            float(r["demand_mw"]),
            r.get("source", "bmrs"),
        )
        for r in records
        if r.get("gsp_id") and r.get("timestamp_utc") and r.get("demand_mw") is not None
    ]
    if not rows:
        return 0

    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO demand_historical
                (gsp_id, gsp_name, timestamp_utc, demand_mw, source)
            VALUES ($1, $2, $3::timestamptz, $4, $5)
            ON CONFLICT (gsp_id, timestamp_utc) DO UPDATE SET
                demand_mw = EXCLUDED.demand_mw,
                gsp_name  = COALESCE(EXCLUDED.gsp_name, demand_historical.gsp_name)
            """,
            rows,
        )
    return len(rows)


# ─── Subprocess bridge ──────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    cmd = req.get("command", "")
    try:
        if cmd == "fetch_national":
            result = fetch_national_demand(
                req.get("start_date", "2024-01-01"),
                req.get("end_date", "2024-01-07"),
            )
            json.dump({"ok": True, "records": result, "count": len(result)}, sys.stdout)

        elif cmd == "generate_synthetic":
            result = generate_synthetic_demand(
                n_gsps=req.get("n_gsps", 20),
                days=req.get("days", 30),
                start_date=req.get("start_date", "2024-01-01"),
            )
            # Don't send raw records over subprocess (too large), send summary
            json.dump({
                "ok": True,
                "profiles": result["profiles"],
                "records_count": result["records_count"],
                "gsps": result["gsps"],
                "days": result["days"],
                # Send compact daily summaries instead of HH data
                "daily_summaries": generate_compact_synthetic(
                    n_gsps=req.get("n_gsps", 20),
                    days=req.get("days", 30),
                    start_date=req.get("start_date", "2024-01-01"),
                )["daily_summaries"],
            }, sys.stdout)

        elif cmd == "generate_compact":
            result = generate_compact_synthetic(
                n_gsps=req.get("n_gsps", 20),
                days=req.get("days", 30),
                start_date=req.get("start_date", "2024-06-01"),
            )
            json.dump({"ok": True, **result}, sys.stdout)

        elif cmd == "list_gsps":
            json.dump({"ok": True, "gsps": list_gsps()}, sys.stdout)

        elif cmd == "fetch_gsp":
            # For now, generate synthetic for a specific GSP
            gsp_id = req.get("gsp_id", "ABHA")
            gsp = next((g for g in UK_GSPS if g["gsp_id"] == gsp_id), None)
            if not gsp:
                json.dump({"error": f"Unknown GSP: {gsp_id}"}, sys.stdout)
                return
            result = generate_compact_synthetic(n_gsps=1, days=req.get("days", 30))
            json.dump({"ok": True, **result}, sys.stdout)

        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)

    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
