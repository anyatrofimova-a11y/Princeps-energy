"""
BESS Live Revenue Cron — hourly recompute job.

Each tick:
  1. Pull last 30d of BMRS settlement-period demand (proxy for wholesale
     volatility — we don't ingest day-ahead prices yet, but demand
     turning-points are a clean leading indicator for arbitrage spread).
  2. For each registered BESS site (technology in {bess, battery, hybrid}
     in the projects table), run bess_revenue_stacker.stack_revenues for
     the rolling 30d window with a volatility-modulated noise factor
     (BMRS-derived) and write a snapshot row.
  3. Postgres trigger on insert -> NOTIFY 'bess_live_revenue' -> WS pushes
     the row to connected clients.

Smoke fallback: if no projects match, writes a single 'demo-bess-50mw-2h'
row so the dashboard widget renders out of the box.

Cited prior art:
  - utils/bess_revenue_stacker.py:267 (stack_revenues)
  - utils/demand_data_ingester.py:26 (BMRS endpoint pattern)
  - app/routers/grid.py:1759 (WS pattern that this cron feeds)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import asyncpg

from utils.bess_revenue_stacker import (
    MODO_BENCHMARKS,
    REVENUE_STREAMS,
    _duration_key,
    stack_revenues,
)

log = logging.getLogger("princeps.bess_cron")

# Default cron period — hourly. Override via env for tests / demos.
CRON_INTERVAL_S = int(os.getenv("BESS_REVENUE_CRON_INTERVAL_S", "3600"))
# After app boot, do a first tick this many seconds in so the dashboard
# has data within seconds of the page opening.
FIRST_TICK_DELAY_S = int(os.getenv("BESS_REVENUE_CRON_FIRST_TICK_S", "5"))

BMRS_BASE = "https://data.elexon.co.uk/bmrs/api/v1"

# Demo fallback site — used when no real BESS projects are seeded yet.
DEMO_SITE = {
    "rid": "demo-bess-50mw-2h",
    "name": "Demo BESS — Midlands 50MW/2h",
    "power_mw": 50.0,
    "duration_hours": 2.0,
    "region": "Midlands",
}

# UK region inference from project lat — coarse but adequate for the
# regional benchmark factor in bess_revenue_stacker.
def _region_from_latlon(lat: float | None, lon: float | None) -> str:
    if lat is None:
        return "Midlands"
    if lat >= 55.0:
        return "Scotland"
    if lat >= 53.5:
        return "North"
    if lat >= 52.3:
        return "Midlands"
    if lon is not None and lon < -3.5:
        return "Wales"
    return "South"


# ───────────────────────────────────────────────────────────────────────────
# BMRS volatility proxy — pulls the last 24h of national demand and computes
# the half-hourly demand swing as a normalised volatility factor (0.85 .. 1.15).
# Used to perturb the deterministic stacker output so each cron tick produces
# a fresh row that reflects current market conditions without us needing to
# stand up a full price-data ingestion path right now.
# ───────────────────────────────────────────────────────────────────────────
def _fetch_bmrs_volatility() -> float:
    """Return a multiplier in roughly [0.85, 1.15] derived from recent
    BMRS demand swings. Falls back to 1.0 on any network error.

    Synchronous urllib (matches utils/demand_data_ingester.py:19); cron
    invokes via asyncio.to_thread to keep the event loop free.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=1)
    url = (
        f"{BMRS_BASE}/demand/outturn/summary"
        f"?from={start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        f"&to={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        f"&format=json"
    )
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        items = data if isinstance(data, list) else data.get("data") or data.get("results") or []
        demands: list[float] = []
        for item in items:
            d = item.get("demand") or item.get("initialDemandOutturn") or item.get("transmissionSystemDemand")
            if d is not None:
                demands.append(float(d))
        if len(demands) < 4:
            return 1.0
        # Half-hourly first-difference, normalised by mean demand.
        diffs = [abs(demands[i] - demands[i - 1]) for i in range(1, len(demands))]
        mean_d = sum(demands) / len(demands)
        if mean_d <= 0:
            return 1.0
        norm_swing = (sum(diffs) / len(diffs)) / mean_d  # typically 0.02..0.08
        # Map roughly [0.02, 0.08] -> [0.92, 1.10]; clamp to [0.85, 1.15].
        factor = 0.92 + (norm_swing - 0.02) * (0.18 / 0.06)
        return max(0.85, min(1.15, factor))
    except (URLError, json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        log.debug("BMRS volatility fetch fell back to 1.0: %s", e)
        return 1.0


# ───────────────────────────────────────────────────────────────────────────
# Modo Energy forward curve overlay — STUBBED.
# Modo Energy doesn't expose a free public API; their commercial feed is
# behind a paywall. We anchor against MODO_BENCHMARKS (their published
# annual £/MW/yr ranges from utils/bess_revenue_stacker.py) plus a small
# seasonal sinusoid so the dashed overlay on the chart has shape, not just
# a flat line. Replace with real Modo feed once procurement lands.
# TODO: replace with utils/modo_feed.py once Modo API contract is signed.
# ───────────────────────────────────────────────────────────────────────────
def _modo_p50_forecast_gbp(power_mw: float, duration_hours: float, ts: datetime) -> float:
    dkey = _duration_key(duration_hours)
    yr = str(ts.year)
    modo = MODO_BENCHMARKS.get(yr, MODO_BENCHMARKS["2026"])
    band = modo.get(dkey, modo["2h"])
    annual_per_mw = band["mid"]
    # Daily share of annual run-rate.
    daily = annual_per_mw * power_mw / 365.0
    # Light seasonal shape: peaks in Jan, troughs in Aug.
    day_of_year = ts.timetuple().tm_yday
    seasonal = 1.0 + 0.12 * math.cos(2 * math.pi * (day_of_year - 15) / 365)
    return daily * seasonal


# ───────────────────────────────────────────────────────────────────────────
# Per-site snapshot computation.
# ───────────────────────────────────────────────────────────────────────────
def _compute_snapshot(
    site: dict[str, Any],
    volatility: float,
    ts: datetime,
) -> dict[str, Any]:
    """Run the stacker, package a 30d-equivalent snapshot row.

    Returns a dict matching the bess_live_revenue_snapshots column shape.
    """
    base = stack_revenues(
        power_mw=site["power_mw"],
        duration_hours=site["duration_hours"],
        region=site.get("region", "Midlands"),
        year=str(ts.year),
        strategy="balanced",
    )
    # The stacker returns annual £; convert to a 30d window equivalent and
    # apply the BMRS volatility modulation.
    annual_total = float(base["total_revenue_gbp"])
    window_days = 30
    p50_window = annual_total * (window_days / 365.0) * volatility

    # P10/P90 spread — wider when volatility is high.
    spread = 0.18 + 0.10 * abs(volatility - 1.0) * 5.0  # 0.18..~0.28
    spread = min(spread, 0.35)
    p10 = p50_window * (1 - spread)
    p90 = p50_window * (1 + spread)

    # Stack breakdown — annualise per stream then take 30d slice.
    breakdown: dict[str, float] = {}
    for s in base.get("streams", []):
        stream_name = s.get("stream") or s.get("name") or "unknown"
        annual_stream = float(s.get("revenue_gbp", 0))
        breakdown[stream_name] = round(
            annual_stream * (window_days / 365.0) * volatility, 2
        )

    modo_p50 = _modo_p50_forecast_gbp(
        site["power_mw"], site["duration_hours"], ts
    ) * window_days

    return {
        "rid": site["rid"],
        "ts": ts,
        "p10_rev_gbp": round(p10, 2),
        "p50_rev_gbp": round(p50_window, 2),
        "p90_rev_gbp": round(p90, 2),
        "stack_breakdown": {
            "streams": breakdown,
            "site_name": site.get("name"),
            "power_mw": site["power_mw"],
            "duration_hours": site["duration_hours"],
            "region": site.get("region"),
            "volatility_factor": round(volatility, 4),
            "annual_total_gbp": round(annual_total, 2),
            "window_days": window_days,
        },
        "modo_p50_forecast": round(modo_p50, 2),
        "source": "cron-stacker-v1",
    }


async def _load_sites(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    """Pull registered BESS sites from the projects table.

    Maps technology in {bess, battery, hybrid} (lowercase) to the spec's
    expected ``rid`` (we use project_id::text). Falls back to a single
    demo site if nothing matches.
    """
    sites: list[dict[str, Any]] = []
    try:
        async with pool.acquire(timeout=10) as conn:
            rows = await conn.fetch(
                """
                SELECT project_id::text AS rid, name, technology, capacity_mw,
                       lat, lon
                FROM projects
                WHERE LOWER(technology) IN ('bess','battery','hybrid')
                  AND capacity_mw IS NOT NULL AND capacity_mw > 0
                ORDER BY capacity_mw DESC NULLS LAST
                LIMIT 50
                """
            )
        for r in rows:
            mw = float(r["capacity_mw"])
            # Heuristic duration from MW: large project -> 2h default,
            # 4h when name mentions 'long duration', 1h for tiny. Most
            # UK BESS lands at 2h (capacity-market sweet spot).
            name = (r["name"] or "").lower()
            if "4h" in name or "long duration" in name:
                duration = 4.0
            elif mw < 10:
                duration = 1.0
            else:
                duration = 2.0
            sites.append({
                "rid": r["rid"],
                "name": r["name"] or f"BESS {r['rid'][:8]}",
                "power_mw": mw,
                "duration_hours": duration,
                "region": _region_from_latlon(r["lat"], r["lon"]),
            })
    except Exception as e:
        log.warning("BESS site load failed (will use demo fallback): %s", e)

    if not sites:
        sites.append(dict(DEMO_SITE))
    return sites


async def _write_snapshot(pool: asyncpg.Pool, snap: dict[str, Any]) -> int | None:
    """Insert a snapshot row; trigger emits NOTIFY to the WS handler."""
    try:
        async with pool.acquire(timeout=10) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO bess_live_revenue_snapshots
                    (rid, ts, p10_rev_gbp, p50_rev_gbp, p90_rev_gbp,
                     stack_breakdown, modo_p50_forecast, source)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
                RETURNING snapshot_id
                """,
                snap["rid"], snap["ts"],
                snap["p10_rev_gbp"], snap["p50_rev_gbp"], snap["p90_rev_gbp"],
                json.dumps(snap["stack_breakdown"]),
                snap["modo_p50_forecast"], snap["source"],
            )
        return row["snapshot_id"] if row else None
    except Exception as e:
        log.warning("BESS snapshot write failed for rid=%s: %s", snap["rid"], e)
        return None


async def run_one_tick(pool: asyncpg.Pool) -> int:
    """Execute a single cron tick. Returns rows written.

    Public so tests / smoke scripts can invoke directly without waiting
    for the loop's first-tick delay.
    """
    ts = datetime.now(timezone.utc)
    volatility = await asyncio.to_thread(_fetch_bmrs_volatility)
    sites = await _load_sites(pool)
    written = 0
    for site in sites:
        snap = _compute_snapshot(site, volatility, ts)
        sid = await _write_snapshot(pool, snap)
        if sid is not None:
            written += 1
    log.info(
        "BESS revenue cron tick: %d sites -> %d rows (volatility=%.3f)",
        len(sites), written, volatility,
    )
    return written


async def start(pool: asyncpg.Pool) -> None:
    """Long-running cron loop. Launched via asyncio.create_task in startup."""
    # Stagger so we don't hammer BMRS the moment the app boots.
    await asyncio.sleep(FIRST_TICK_DELAY_S)
    while True:
        try:
            await run_one_tick(pool)
        except Exception as e:
            log.warning("BESS revenue cron tick failed: %s", e)
        try:
            await asyncio.sleep(CRON_INTERVAL_S)
        except asyncio.CancelledError:
            log.info("BESS revenue cron stopping (cancelled)")
            return
