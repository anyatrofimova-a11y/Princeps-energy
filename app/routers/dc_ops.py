"""DC Ops router — noise contours, glint cones, live DC telemetry.

Replaces the three client-side simulators in ``feasi-frontend/src/api/dcOps.js``:

- GET  /api/dc/noise-contours   ISO 9613-2 GeoJSON polygons around DC point sources
- GET  /api/dc/glint-screen     Solstice-noon glint cones around a cooling plant
- GET  /api/dc/ops              Deterministic diurnal telemetry snapshot
- WS   /ws/dc-ops/{project_id}  Pushes the same telemetry payload every 5 s
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from utils.glint_glare import _sun_position
from utils.noise_propagation import (
    DEFAULT_SOURCE_LEVELS,
    calculate_noise_contours,
)

router = APIRouter(tags=["dc-ops"])


# ─── Noise contours ─────────────────────────────────────────────────────────

# Typical data-centre point-source power levels (Lw, dBA)
# Values come from manufacturer envelopes (Cummins QSK60 genset, Trane CDHG
# water-cooled chiller, Eaton 2500 kVA transformer, dry-cooler fans).
DC_SOURCE_LIBRARY: dict[str, dict[str, float]] = {
    "genset":      {"lw_dba": 112.0, "height_m": 3.0, "offset_m": 60.0},
    "chiller":     {"lw_dba":  98.0, "height_m": 4.0, "offset_m": 30.0},
    "drycooler":   {"lw_dba":  92.0, "height_m": 8.0, "offset_m": 20.0},
    "transformer": {"lw_dba":  78.0, "height_m": 2.0, "offset_m": 15.0},
    "cooling":     {"lw_dba":  95.0, "height_m": 4.0, "offset_m": 25.0},  # alias
    "ups":         {"lw_dba":  82.0, "height_m": 2.0, "offset_m": 10.0},
}

# Contours requested explicitly by BOT-DX — 55 dB (planning threshold) + 65 dB (exceedance).
DC_CONTOUR_LEVELS = (55, 65)
DC_CONTOUR_COLOURS = {55: "#f5b731", 65: "#ef4444"}


def _offset_latlon(lat: float, lon: float, bearing_deg: float, dist_m: float) -> tuple[float, float]:
    """Offset a lat/lon by `dist_m` along a compass bearing (flat-earth)."""
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = m_per_deg_lat * math.cos(math.radians(lat))
    br = math.radians(bearing_deg)
    dy = dist_m * math.cos(br)
    dx = dist_m * math.sin(br)
    return lat + dy / m_per_deg_lat, lon + dx / m_per_deg_lon


@router.get("/api/dc/noise-contours")
async def api_dc_noise_contours(
    lat: float = Query(..., description="Site centroid latitude (WGS84)"),
    lon: float = Query(..., description="Site centroid longitude (WGS84)"),
    sources: str = Query(
        "genset,chiller",
        description="Comma-separated source types: genset, chiller, drycooler, transformer, ups",
    ),
    mw: float = Query(50.0, ge=0.1, le=1000.0, description="IT load in MW — scales source count"),
    study_radius_m: float = Query(1500.0, ge=100.0, le=5000.0),
    grid_m: float = Query(15.0, ge=5.0, le=100.0),
):
    """ISO 9613-2 noise contour polygons (55 dB + 65 dB) for a DC point-source set.

    Sources are placed on a circle around the centroid using the offset from the
    source library; count scales with IT load (1 unit per 20 MW, minimum 1).
    Returns a GeoJSON FeatureCollection of polygon rings suitable for Mapbox.
    """
    requested = [s.strip().lower() for s in sources.split(",") if s.strip()]
    if not requested:
        requested = ["genset", "chiller"]

    # Scale source count with IT load — 1 per 20 MW, min 1, cap at 8 per type
    n_per_type = max(1, min(8, int(round(mw / 20.0))))

    placed: list[dict[str, Any]] = []
    for idx, stype in enumerate(requested):
        spec = DC_SOURCE_LIBRARY.get(stype)
        if not spec:
            # Fall back to noise_propagation defaults if unknown type
            spec = {
                "lw_dba": DEFAULT_SOURCE_LEVELS.get(stype, 75.0),
                "height_m": 2.0,
                "offset_m": 25.0,
            }
        # Distribute copies evenly around a circle, offset bearing per type group
        base_bearing = (idx * 360.0 / max(1, len(requested))) + 15.0
        for k in range(n_per_type):
            bearing = base_bearing + (k * 360.0 / n_per_type) / max(1, len(requested))
            s_lat, s_lon = _offset_latlon(lat, lon, bearing, spec["offset_m"])
            placed.append({
                "type": stype,
                "lat": s_lat,
                "lon": s_lon,
                "power_level_dba": spec["lw_dba"],
                "height_m": spec["height_m"],
            })

    result = calculate_noise_contours(
        sources=placed,
        receptor_grid_size_m=grid_m,
        study_radius_m=study_radius_m,
        compliance_limit_dba=55.0,
        contour_levels=list(DC_CONTOUR_LEVELS),
    )

    # Recolour for DC-ops palette.
    fc = result.get("contours_geojson", {"type": "FeatureCollection", "features": []})
    filtered = []
    for feat in fc.get("features", []):
        lvl = feat.get("properties", {}).get("level_dba")
        if lvl in DC_CONTOUR_LEVELS:
            feat["properties"]["color"] = DC_CONTOUR_COLOURS[lvl]
            feat["properties"]["label"] = f"{int(lvl)} dB(A)"
            filtered.append(feat)

    # Emitter summary for the client (same shape as the mock it replaces)
    emitters = []
    for stype in requested:
        spec = DC_SOURCE_LIBRARY.get(stype, {"lw_dba": 75.0, "offset_m": 25.0})
        e_lat, e_lon = _offset_latlon(lat, lon, (requested.index(stype) * 360.0 / len(requested)) + 15.0, spec["offset_m"])
        emitters.append({
            "lat": e_lat,
            "lon": e_lon,
            "source_db": spec["lw_dba"],
            "label": stype.capitalize(),
            "count": n_per_type,
        })

    return {
        "type": "FeatureCollection",
        "features": filtered,
        "emitters": emitters,
        "thresholds": [
            {"db": 55, "color": DC_CONTOUR_COLOURS[55]},
            {"db": 65, "color": DC_CONTOUR_COLOURS[65]},
        ],
        "max_at_nearest_receptor_dba": result.get("max_at_nearest_receptor_dba"),
        "compliant": result.get("compliant"),
        "methodology": result.get("methodology"),
        "source_count": len(placed),
        "it_load_mw": mw,
        "_source": "backend/iso9613-2",
    }


# ─── Glint cones ────────────────────────────────────────────────────────────

def _parse_extent(raw: str | None) -> list[tuple[float, float]]:
    """Parse cooling_plant_extent as either a ``lat,lon`` centroid or JSON polygon.

    Accepts:
      - ``"51.5,-0.6"`` single point
      - ``"51.5,-0.6;51.5,-0.59;..."`` semicolon-separated ring
      - JSON ``[[lon,lat], ...]``
    """
    if not raw:
        return []
    raw = raw.strip()
    # Try JSON first
    if raw.startswith("["):
        try:
            coords = json.loads(raw)
            pts = []
            for c in coords:
                if isinstance(c, (list, tuple)) and len(c) >= 2:
                    # Heuristic: if |c[0]|>90, it's lon,lat; else lat,lon
                    if abs(c[0]) > 90:
                        pts.append((float(c[1]), float(c[0])))
                    else:
                        pts.append((float(c[0]), float(c[1])))
            return pts
        except Exception:
            return []
    # Semicolon or single lat,lon
    out: list[tuple[float, float]] = []
    for part in raw.split(";"):
        bits = [b.strip() for b in part.split(",") if b.strip()]
        if len(bits) >= 2:
            try:
                out.append((float(bits[0]), float(bits[1])))
            except ValueError:
                continue
    return out


def _solar_noon_azimuth(lat: float, lon: float, doy: int) -> float:
    """Solar azimuth at local solar noon, degrees from N clockwise.

    In UK (51.5°N) sun is due south at noon: az ≈ 180°. We reuse the glint_glare
    sun-position algorithm at UTC 12:00 minus the longitude correction.
    """
    hour_utc = 12.0 - lon / 15.0  # approximate solar noon UTC
    az, _alt = _sun_position(lat, lon, doy, hour_utc)
    return az


def _cone_polygon(
    origin_lat: float,
    origin_lon: float,
    bearing_deg: float,
    spread_deg: float,
    length_m: float,
    n_segments: int = 16,
) -> list[list[float]]:
    """Build a GeoJSON polygon ring [lon,lat] for a cone from origin."""
    coords: list[list[float]] = []
    # Sweep arc edge
    for i in range(n_segments + 1):
        t = i / n_segments
        angle = bearing_deg - spread_deg + t * (2 * spread_deg)
        lat2, lon2 = _offset_latlon(origin_lat, origin_lon, angle, length_m)
        coords.append([round(lon2, 7), round(lat2, 7)])
    # Close back to origin
    coords.append([round(origin_lon, 7), round(origin_lat, 7)])
    coords.append(coords[0])
    return coords


@router.get("/api/dc/glint-screen")
async def api_dc_glint_screen(
    lat: float = Query(..., description="Site centroid latitude"),
    lon: float = Query(..., description="Site centroid longitude"),
    cooling_plant_extent: str | None = Query(
        None,
        description="Cooling plant extent: 'lat,lon' point, 'lat,lon;lat,lon;...' ring, or JSON polygon",
    ),
    length_summer_m: float = Query(250.0, ge=50.0, le=5000.0),
    length_winter_m: float = Query(950.0, ge=50.0, le=5000.0),
    spread_deg: float = Query(12.0, ge=2.0, le=45.0),
):
    """Solstice-noon glint cones emanating from a cooling-plant reflective surface.

    UK sun altitude at solar noon:
      - Summer solstice (doy 172):  ~62° at 51.5°N
      - Winter solstice (doy 355):  ~15° at 51.5°N
    Reflected beam bearing at noon is the sun's azimuth + 180° (mirror across
    panel normal pointing up/south). In UK that resolves to northward.
    """
    extent = _parse_extent(cooling_plant_extent)
    if not extent:
        extent = [(lat, lon)]

    # Centroid of extent
    c_lat = sum(p[0] for p in extent) / len(extent)
    c_lon = sum(p[1] for p in extent) / len(extent)

    # Solar positions
    summer_doy, winter_doy = 172, 355
    summer_az = _solar_noon_azimuth(c_lat, c_lon, summer_doy)
    winter_az = _solar_noon_azimuth(c_lat, c_lon, winter_doy)
    # UK-specific solstice-noon altitudes (parameterised by latitude)
    summer_alt = 90.0 - c_lat + 23.45
    winter_alt = max(1.0, 90.0 - c_lat - 23.45)

    # Reflected beam points opposite the sun in azimuth (for horizontal-ish panels)
    summer_bearing = (summer_az + 180.0) % 360.0
    winter_bearing = (winter_az + 180.0) % 360.0

    def _cone_feature(season: str, bearing: float, length_m: float, sun_alt: float) -> dict[str, Any]:
        ring = _cone_polygon(c_lat, c_lon, bearing, spread_deg, length_m)
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {
                "season": season,
                "sun_alt_deg": round(sun_alt, 1),
                "bearing_deg": round(bearing, 1),
                "spread_deg": spread_deg,
                "length_m": length_m,
                "color": "#f59e0b" if season == "summer" else "#6366f1",
                "label": f"{season.capitalize()} solstice-noon glint cone",
            },
        }

    features = [
        _cone_feature("summer", summer_bearing, length_summer_m, summer_alt),
        _cone_feature("winter", winter_bearing, length_winter_m, winter_alt),
    ]

    return {
        "type": "FeatureCollection",
        "features": features,
        "surfaces": [
            {
                "lat": c_lat,
                "lon": c_lon,
                "azimuth_deg": 180.0,
                "tilt_deg": 10.0,
                "label": "Cooling plant (dry coolers)",
            }
        ],
        "cones": [
            {
                "surface": "Cooling plant (dry coolers)",
                "lat": c_lat,
                "lon": c_lon,
                "season": "summer",
                "sun_alt_deg": round(summer_alt, 1),
                "bearing_deg": round(summer_bearing, 1),
                "spread_deg": spread_deg,
                "length_m": length_summer_m,
            },
            {
                "surface": "Cooling plant (dry coolers)",
                "lat": c_lat,
                "lon": c_lon,
                "season": "winter",
                "sun_alt_deg": round(winter_alt, 1),
                "bearing_deg": round(winter_bearing, 1),
                "spread_deg": spread_deg,
                "length_m": length_winter_m,
            },
        ],
        "receptor_hits": [],
        "methodology": "SGHAT-style specular reflection, solstice-noon sampling",
        "provenance": "FAA AC 150/5300-15B; Ho/Ghanbari/Diver 2011",
        "_source": "backend/glint-glare",
    }


# ─── Live DC ops telemetry ──────────────────────────────────────────────────

def _diurnal_snapshot(project_id: str, it_load_mw: float = 50.0) -> dict[str, Any]:
    """Deterministic diurnal telemetry payload keyed on local wall-clock.

    IT utilisation peaks at 14:00 local via a sine curve; PUE inversely tracks
    utilisation (idle → worse PUE). Values are stable within a minute so repeat
    GETs look consistent but WS ticks still show evolution.
    """
    now = datetime.now()
    hour = now.hour + now.minute / 60.0 + now.second / 3600.0
    # Sine curve peaking at 14:00 — shift by 14h so 14h→peak.
    # cos(((hour-14)/24)*2π) peaks at hour=14.
    diurnal = 0.72 + 0.22 * math.cos(((hour - 14.0) / 24.0) * 2.0 * math.pi)
    # Deterministic per-second jitter from project_id hash + second
    seed = (abs(hash(project_id)) % 1000) / 1000.0
    jitter = 0.02 * math.sin(now.minute * 0.4 + now.second * 0.17 + seed * math.tau)
    it_pct = max(0.40, min(0.98, diurnal + jitter))

    cooling_mw = it_load_mw * it_pct * 0.32      # ~32% of IT kW ends up as cooling plant load
    pue = 1.18 + 0.08 * (1.0 - it_pct) + 0.005 * math.sin(now.second * 0.21)
    water_lpm = cooling_mw * 1.8 + 2.0 * math.sin(now.minute * 0.3)  # adiabatic make-up

    return {
        "project_id": project_id,
        "pue": round(pue, 3),
        "it_load_pct": round(it_pct * 100.0, 1),
        "it_load_mw": round(it_load_mw * it_pct, 2),
        "cooling_mw": round(cooling_mw, 2),
        "water_lpm": round(max(0.0, water_lpm), 1),
        "it_pct": round(it_pct, 4),                # keep raw fraction for charts
        "hour_local": round(hour, 3),
        "ts": int(time.time() * 1000),
        "_source": "backend/diurnal",
    }


@router.get("/api/dc/ops")
async def api_dc_ops(
    project_id: str = Query("demo", description="Project UUID or slug"),
    it_load_mw: float = Query(50.0, ge=0.1, le=1000.0),
):
    """Snapshot of DC live-ops telemetry (PUE, IT%, cooling MW, water make-up)."""
    return _diurnal_snapshot(project_id, it_load_mw)


@router.websocket("/ws/dc-ops/{project_id}")
async def ws_dc_ops(websocket: WebSocket, project_id: str):
    """Stream diurnal DC telemetry every 5 s. v1 broadcast-on-tick."""
    await websocket.accept()
    try:
        # Optional IT load from query string
        try:
            it_mw = float(websocket.query_params.get("it_load_mw", "50"))
        except (TypeError, ValueError):
            it_mw = 50.0
        while True:
            payload = _diurnal_snapshot(project_id, it_mw)
            await websocket.send_json(payload)
            await asyncio.sleep(5.0)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
