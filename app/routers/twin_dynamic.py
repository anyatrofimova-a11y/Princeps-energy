"""Twin dynamic-layer proxies — BOT-EE.

Proxies that back the time-aware / live deck.gl layers in
`feasi-frontend/src/twin/layers/dyn_*.js`. Every endpoint must be
cheap and cacheable; poll budget per layer is 1 req / 30 s.

Endpoints:
  GET /api/twin/carbon/regional   — NESO Carbon Intensity, cached 5 min
  GET /api/twin/live-flow         — grid line flows (WS already exists, this
                                    is the REST fallback + power-flow stub)
  GET /api/twin/weather/era5      — ERA5 hourly point; stub uses UK climatology
                                    when CDS_API_KEY absent
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import random
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Query

log = logging.getLogger("princeps.twin_dynamic")
router = APIRouter(prefix="/api/twin", tags=["twin-dynamic"])

_TIMEOUT = 8
_UA = "Princeps-Twin/1.0"
_CARBON_URL = "https://api.carbonintensity.org.uk/regional"

# ── In-process 5-min cache for NESO carbon ─────────────────────────────────
_carbon_cache: dict[str, tuple[float, dict]] = {}
_CARBON_TTL = 300  # 5 minutes


async def _fetch_carbon_regional() -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as cli:
        r = await cli.get(_CARBON_URL)
        r.raise_for_status()
        return r.json()


@router.get("/carbon/regional")
async def carbon_regional(force: bool = Query(False)):
    """Proxy to api.carbonintensity.org.uk/regional with 5-min cache.

    Returns the same shape as upstream plus `cached_at` / `ttl_s` metadata
    so the frontend can show staleness.
    """
    now = time.time()
    hit = _carbon_cache.get("regional")
    if hit and not force and (now - hit[0]) < _CARBON_TTL:
        body = dict(hit[1])
        body["cached_at"] = datetime.fromtimestamp(hit[0], tz=timezone.utc).isoformat()
        body["ttl_s"] = int(_CARBON_TTL - (now - hit[0]))
        body["cache_hit"] = True
        return body

    try:
        upstream = await _fetch_carbon_regional()
    except Exception as exc:  # noqa: BLE001
        log.warning("carbon regional fetch failed: %s", exc)
        # serve stale if we have it
        if hit:
            body = dict(hit[1])
            body["cache_hit"] = True
            body["stale"] = True
            return body
        return {"data": [], "error": "upstream_unavailable"}

    _carbon_cache["regional"] = (now, upstream)
    body = dict(upstream)
    body["cached_at"] = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    body["ttl_s"] = _CARBON_TTL
    body["cache_hit"] = False
    return body


# ── Live flow (REST fallback, complements /ws/grid-twin) ───────────────────
@router.get("/live-flow")
async def live_flow(bbox: str | None = Query(None)):
    """Return current power flow per grid_line for dyn_flow_arrows.

    Proxies the existing `/api/grid-twin/state` endpoint where possible
    (that already scales flow by live BMRS). If unavailable returns an
    interpolated stub based on the current UTC hour so the layer renders.
    """
    try:
        # Best effort in-process call — avoid import loops by delaying
        from app.routers.grid import api_grid_twin_state  # noqa: WPS433
        from app.deps import get_pool  # noqa: WPS433

        pool_gen = get_pool()
        if hasattr(pool_gen, "__anext__"):
            pool = await pool_gen.__anext__()
        else:
            pool = pool_gen

        state = await api_grid_twin_state(pool=pool, limit=120)  # type: ignore[arg-type]
        lines = state.get("lines", []) if isinstance(state, dict) else []
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "grid_twin_state",
            "lines": [
                {
                    "from": ln.get("from"),
                    "to": ln.get("to"),
                    "from_coords": ln.get("from_coords"),
                    "to_coords": ln.get("to_coords"),
                    "voltage_kv": ln.get("voltage_kv"),
                    "rating_mw": ln.get("rating_mw"),
                    "flow_mw": ln.get("flow_mw"),
                    "loading_pct": ln.get("loading_pct"),
                    "congested": ln.get("congested"),
                }
                for ln in lines
            ],
        }
    except Exception as exc:  # noqa: BLE001
        log.info("live-flow proxy falling back to stub: %s", exc)

    # Stub: diurnal flow swing on a handful of canonical inter-zone links.
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60.0
    phase = math.sin(2 * math.pi * (hour - 18) / 24)  # peak ~18:00
    canonical = [
        ("BRWA", "BEDD", [-1.06, 51.33], [-0.13, 51.37], 400, 1200),
        ("EDIN", "KEAD", [-3.19, 55.92], [-0.75, 53.60], 275, 800),
        ("MANN", "BRWA", [-2.25, 53.45], [-1.06, 51.33], 400, 1200),
        ("KEAD", "NORW", [-0.75, 53.60], [1.30, 52.62], 275, 800),
        ("NORW", "CAMA", [1.30, 52.62], [0.14, 52.19], 132, 400),
    ]
    lines = []
    for (a, b, ca, cb, kv, rating) in canonical:
        flow = round(rating * 0.55 * phase + random.gauss(0, rating * 0.04), 1)
        lines.append({
            "from": a, "to": b, "from_coords": ca, "to_coords": cb,
            "voltage_kv": kv, "rating_mw": rating, "flow_mw": flow,
            "loading_pct": round(abs(flow) / rating * 100, 1),
            "congested": abs(flow) / rating > 0.8,
        })
    return {"timestamp": now.isoformat(), "source": "stub_interpolated", "lines": lines}


# ── ERA5 (stub: UK monthly climatology if no CDS key) ──────────────────────
_UK_MONTHLY_CLIM = {
    # month: (mean_ghi_W/m², mean_wind_10m_m/s)
    1:  (55,  6.2), 2:  (95,  6.0), 3:  (150, 5.6), 4:  (210, 5.1),
    5:  (260, 4.7), 6:  (280, 4.4), 7:  (265, 4.3), 8:  (230, 4.5),
    9:  (175, 4.9), 10: (110, 5.4), 11: (65,  5.9), 12: (45,  6.2),
}


def _synth_era5(lat: float, lon: float, ts: datetime) -> dict:
    ghi_m, ws_m = _UK_MONTHLY_CLIM[ts.month]
    # Diurnal GHI curve — only non-zero between sunrise/sunset (simple cosine)
    hour = ts.hour + ts.minute / 60.0
    sun_factor = max(0.0, math.cos((hour - 12.0) * math.pi / 14.0))
    ghi = round(ghi_m * 2.2 * sun_factor, 1)  # scale so noon ~2.2× monthly mean
    # Wind: mild diurnal — stronger at night offshore, weaker onshore afternoon
    ws = round(ws_m + 0.6 * math.sin((hour - 3) * math.pi / 12.0), 2)
    # Lat penalty north of 56°N for GHI
    if lat > 56:
        ghi *= 0.85
    return {
        "lat": lat, "lon": lon, "ts": ts.isoformat(),
        "ghi_wm2": round(ghi, 1), "wind_10m_ms": round(ws, 2),
        "source": "uk_climatology_synth", "month": ts.month,
    }


@router.get("/weather/era5")
async def weather_era5(
    lat: float = Query(...),
    lon: float = Query(...),
    ts: str | None = Query(None, description="ISO-8601 UTC, default=now"),
):
    """Hourly irradiance + wind at a point.

    Uses CDS ERA5 if `CDS_API_KEY` is set; otherwise returns a deterministic
    synthesised value from UK monthly climatology. No polling required — the
    frontend tiles the bbox client-side.
    """
    when = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    if os.getenv("CDS_API_KEY"):
        # Placeholder — real CDS fetch would go here. Intentionally not
        # implemented in this commit; see BOT-EE follow-up ticket.
        return {**_synth_era5(lat, lon, when), "note": "cds_api_key_present_but_unimplemented"}

    return _synth_era5(lat, lon, when)


# ── Weather grid (lightweight tile for heatmap) ────────────────────────────
@router.get("/weather/grid")
async def weather_grid(
    west: float = Query(-8.5), south: float = Query(49.9),
    east: float = Query(1.8), north: float = Query(60.9),
    cols: int = Query(14, ge=4, le=32),
    rows: int = Query(20, ge=4, le=48),
    ts: str | None = Query(None),
    var: str = Query("ghi", pattern="^(ghi|wind)$"),
):
    """Return a `cols × rows` grid of irradiance or wind for a GB bbox."""
    when = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    dx = (east - west) / cols
    dy = (north - south) / rows
    points = []
    for j in range(rows):
        for i in range(cols):
            lon = west + (i + 0.5) * dx
            lat = south + (j + 0.5) * dy
            pt = _synth_era5(lat, lon, when)
            points.append({
                "lon": lon, "lat": lat,
                "value": pt["ghi_wm2"] if var == "ghi" else pt["wind_10m_ms"],
            })
    return {
        "ts": when.isoformat(), "var": var,
        "bbox": [west, south, east, north], "cols": cols, "rows": rows,
        "cell_dx": dx, "cell_dy": dy, "points": points,
        "source": "uk_climatology_synth",
    }
