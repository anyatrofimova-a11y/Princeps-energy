"""
ISO 9613-2 noise propagation model for energy developments.

Mandatory for UK planning applications involving:
- Wind turbines (source: 103-107 dBA at hub)
- BESS inverters/cooling (source: 65-75 dBA at 1m)
- Transformers (source: 60-70 dBA at 1m)

UK planning limits: typically 35-40 dB LA90 at nearest receptor.
Tonal penalty: +5dB if tonal components detected.

ISO 9613-2 formula:
  Lp = Lw - 20*log10(d) - 11 - A_atm - A_ground - A_barrier
  where:
    Lw = source sound power level (dBA)
    d = distance to receptor (m)
    A_atm = atmospheric absorption (dB) = alpha * d / 1000
    A_ground = ground absorption (typically 3-6 dB for soft ground)
    A_barrier = barrier attenuation (0 for open sites)
    alpha = atmospheric absorption coefficient (~0.005 dB/m at 500Hz)
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

log = logging.getLogger("princeps.noise")

# ─── Default source power levels (dBA) ──────────────────────────────────────

DEFAULT_SOURCE_LEVELS: dict[str, float] = {
    "wind_turbine": 105.0,
    "bess_inverter": 70.0,
    "bess_cooling": 72.0,
    "transformer": 65.0,
    "substation": 68.0,
}

# Atmospheric absorption coefficient at 500 Hz, 15°C, 70% RH (dB/km)
ALPHA_500HZ = 3.7

# Ground absorption factor: 0 = hard (concrete), 1 = soft (grass/earth)
GROUND_FACTOR_SOFT = 0.7

# UK compliance limits
UK_NOISE_LIMIT_RURAL_DBA = 35.0
UK_NOISE_LIMIT_SUBURBAN_DBA = 40.0
UK_NOISE_LIMIT_DEFAULT_DBA = 40.0

# Contour levels and colours
CONTOUR_LEVELS = [35, 40, 45, 50, 55]
CONTOUR_COLOURS = {
    35: "#4caf50",   # green — compliance boundary
    40: "#ffeb3b",   # yellow — suburban limit
    45: "#ff9800",   # orange — moderate
    50: "#f44336",   # red — high
    55: "#9c27b0",   # purple — very high
}


# ─── Coordinate helpers ──────────────────────────────────────────────────────

def _latlon_to_metres(lat: float, lon: float, ref_lat: float, ref_lon: float) -> tuple[float, float]:
    """Convert lat/lon offset to approximate metres (Mercator)."""
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(ref_lat))
    return (lon - ref_lon) * m_per_deg_lon, (lat - ref_lat) * m_per_deg_lat


def _metres_to_latlon(x_m: float, y_m: float, ref_lat: float, ref_lon: float) -> tuple[float, float]:
    """Convert metre offsets back to lat/lon."""
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(ref_lat))
    return ref_lat + y_m / m_per_deg_lat, ref_lon + x_m / m_per_deg_lon


# ─── ISO 9613-2 core ────────────────────────────────────────────────────────

def _iso9613_attenuation(
    distance_m: float,
    source_height_m: float = 2.0,
    receiver_height_m: float = 1.5,
    ground_factor: float = GROUND_FACTOR_SOFT,
    alpha_db_km: float = ALPHA_500HZ,
) -> float:
    """
    Calculate total attenuation (dB) per ISO 9613-2.

    Returns the total attenuation to subtract from Lw to get Lp:
        A_total = A_div + A_atm + A_ground + A_barrier
    where A_div = 20*log10(d) + 11  (geometric divergence for point source)
    """
    if distance_m < 1.0:
        distance_m = 1.0

    # Geometric divergence (spherical spreading)
    a_div = 20.0 * math.log10(distance_m) + 11.0

    # Atmospheric absorption
    a_atm = alpha_db_km * distance_m / 1000.0

    # Ground effect (ISO 9613-2 simplified)
    # For mixed ground, attenuation depends on source/receiver height and distance
    d_p = max(distance_m, 1.0)
    h_s = source_height_m
    h_r = receiver_height_m
    # Mean height factor
    h_mean = (h_s + h_r) / 2.0
    # Ground absorption: roughly 3-6 dB for soft ground at medium distances
    if ground_factor > 0 and d_p > 10:
        # Simplified ground absorption per ISO 9613-2 Annex A
        a_ground = 4.8 - (2.0 * h_mean / d_p) * (17.0 + 300.0 / d_p)
        a_ground = max(0.0, min(a_ground, 6.0)) * ground_factor
    else:
        a_ground = 0.0

    # Barrier attenuation (assume open site — no barriers)
    a_barrier = 0.0

    return a_div + a_atm + a_ground + a_barrier


def _sound_pressure_level(
    lw_dba: float,
    distance_m: float,
    source_height_m: float = 2.0,
    receiver_height_m: float = 1.5,
    ground_factor: float = GROUND_FACTOR_SOFT,
) -> float:
    """Calculate received sound pressure level (dBA) from a single source."""
    if distance_m < 1.0:
        distance_m = 1.0
    attenuation = _iso9613_attenuation(
        distance_m, source_height_m, receiver_height_m, ground_factor
    )
    return lw_dba - attenuation


def _logarithmic_sum(levels: list[float]) -> float:
    """Sum sound levels logarithmically: 10*log10(sum(10^(Li/10)))."""
    if not levels:
        return 0.0
    total = sum(10.0 ** (lev / 10.0) for lev in levels)
    if total <= 0:
        return 0.0
    return 10.0 * math.log10(total)


# ─── Marching squares for contour extraction ─────────────────────────────────

def _marching_squares_contour(
    grid: np.ndarray,
    threshold: float,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
) -> list[list[tuple[float, float]]]:
    """
    Extract contour lines at `threshold` from a 2D grid using marching squares.

    Returns a list of polylines, each a list of (x, y) coordinate tuples.
    """
    rows, cols = grid.shape
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []

    binary = (grid >= threshold).astype(int)

    for r in range(rows - 1):
        for c in range(cols - 1):
            # 4 corners: TL, TR, BR, BL
            tl = binary[r, c]
            tr = binary[r, c + 1]
            br = binary[r + 1, c + 1]
            bl = binary[r + 1, c]
            case_idx = tl * 8 + tr * 4 + br * 2 + bl

            if case_idx == 0 or case_idx == 15:
                continue

            # Corner coordinates
            x0, x1 = x_coords[c], x_coords[c + 1]
            y0, y1 = y_coords[r], y_coords[r + 1]

            # Corner values
            v_tl = grid[r, c]
            v_tr = grid[r, c + 1]
            v_br = grid[r + 1, c + 1]
            v_bl = grid[r + 1, c]

            def _interp(va, vb, ca, cb):
                if abs(va - vb) < 1e-10:
                    return (ca + cb) / 2.0
                t = (threshold - va) / (vb - va)
                return ca + t * (cb - ca)

            # Edge midpoints (interpolated)
            top = (_interp(v_tl, v_tr, x0, x1), y0)
            right = (x1, _interp(v_tr, v_br, y0, y1))
            bottom = (_interp(v_bl, v_br, x0, x1), y1)
            left = (x0, _interp(v_tl, v_bl, y0, y1))

            # Standard marching squares lookup
            edge_pairs = {
                1:  [(left, bottom)],
                2:  [(bottom, right)],
                3:  [(left, right)],
                4:  [(right, top)],
                5:  [(left, top), (bottom, right)],  # saddle
                6:  [(bottom, top)],
                7:  [(left, top)],
                8:  [(top, left)],
                9:  [(top, bottom)],
                10: [(top, right), (left, bottom)],  # saddle
                11: [(top, right)],
                12: [(right, left)],
                13: [(right, bottom)],
                14: [(bottom, left)],
            }

            if case_idx in edge_pairs:
                for seg in edge_pairs[case_idx]:
                    segments.append(seg)

    # Chain segments into polylines
    if not segments:
        return []

    polylines = _chain_segments(segments)
    return polylines


def _chain_segments(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    tol: float = 1e-6,
) -> list[list[tuple[float, float]]]:
    """Chain line segments into polylines by matching endpoints."""
    if not segments:
        return []

    remaining = list(segments)
    chains: list[list[tuple[float, float]]] = []

    while remaining:
        seg = remaining.pop(0)
        chain = [seg[0], seg[1]]

        changed = True
        while changed:
            changed = False
            for i, s in enumerate(remaining):
                # Try to extend the chain at the end
                if _pt_close(chain[-1], s[0], tol):
                    chain.append(s[1])
                    remaining.pop(i)
                    changed = True
                    break
                elif _pt_close(chain[-1], s[1], tol):
                    chain.append(s[0])
                    remaining.pop(i)
                    changed = True
                    break
                # Try to extend at the beginning
                elif _pt_close(chain[0], s[1], tol):
                    chain.insert(0, s[0])
                    remaining.pop(i)
                    changed = True
                    break
                elif _pt_close(chain[0], s[0], tol):
                    chain.insert(0, s[1])
                    remaining.pop(i)
                    changed = True
                    break

        chains.append(chain)

    return chains


def _pt_close(a: tuple[float, float], b: tuple[float, float], tol: float) -> bool:
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


# ─── Contour to GeoJSON polygon ─────────────────────────────────────────────

def _contour_to_polygon(
    polylines: list[list[tuple[float, float]]],
    ref_lat: float,
    ref_lon: float,
) -> dict | None:
    """Convert contour polylines (in metres) to a GeoJSON Polygon in lat/lon."""
    if not polylines:
        return None

    # Use the longest polyline as the exterior ring
    longest = max(polylines, key=len)
    if len(longest) < 3:
        return None

    coords = []
    for x_m, y_m in longest:
        lat, lon = _metres_to_latlon(x_m, y_m, ref_lat, ref_lon)
        coords.append([round(lon, 7), round(lat, 7)])

    # Close the ring
    if coords[0] != coords[-1]:
        coords.append(coords[0])

    return {
        "type": "Polygon",
        "coordinates": [coords],
    }


# ─── Main public function ────────────────────────────────────────────────────

def calculate_noise_contours(
    sources: list[dict[str, Any]],
    receptor_grid_size_m: float = 10.0,
    study_radius_m: float = 2000.0,
    compliance_limit_dba: float = UK_NOISE_LIMIT_DEFAULT_DBA,
    receptors: list[dict[str, Any]] | None = None,
    tonal_penalty: bool = False,
) -> dict[str, Any]:
    """
    Calculate ISO 9613-2 noise contours from energy infrastructure sources.

    Parameters
    ----------
    sources : list of dict
        Each source must have: type, lat, lon.
        Optional: hub_height_m/height_m, power_level_dba.
    receptor_grid_size_m : float
        Grid cell size for contour computation (metres).
    study_radius_m : float
        Radius around source centroid for the study area.
    compliance_limit_dba : float
        Noise limit for compliance check (default 40 dB).
    receptors : list of dict, optional
        Specific receptor locations to check [{lat, lon, name}].
    tonal_penalty : bool
        If True, apply +5dB tonal penalty.

    Returns
    -------
    dict with contours_geojson, max_at_nearest_receptor_dba, compliant, etc.
    """
    if not sources:
        return {
            "contours_geojson": {"type": "FeatureCollection", "features": []},
            "max_at_nearest_receptor_dba": 0.0,
            "compliant": True,
            "compliance_limit_dba": compliance_limit_dba,
            "tonal_penalty_applied": False,
            "error": "No sources provided",
        }

    # Parse sources
    parsed_sources = []
    for s in sources:
        stype = s.get("type", "transformer")
        lw = s.get("power_level_dba", DEFAULT_SOURCE_LEVELS.get(stype, 70.0))
        height = s.get("hub_height_m") or s.get("height_m", 2.0)
        parsed_sources.append({
            "type": stype,
            "lat": s["lat"],
            "lon": s["lon"],
            "lw_dba": lw,
            "height_m": height,
        })

    # Reference point (centroid of all sources)
    ref_lat = sum(s["lat"] for s in parsed_sources) / len(parsed_sources)
    ref_lon = sum(s["lon"] for s in parsed_sources) / len(parsed_sources)

    # Convert source positions to metres
    source_positions = []
    for s in parsed_sources:
        x, y = _latlon_to_metres(s["lat"], s["lon"], ref_lat, ref_lon)
        source_positions.append({**s, "x_m": x, "y_m": y})

    # Build receptor grid
    half = study_radius_m
    n_cells = int(2 * half / receptor_grid_size_m) + 1
    # Cap grid size to prevent memory issues
    if n_cells > 400:
        receptor_grid_size_m = 2 * half / 400
        n_cells = 401

    x_coords = np.linspace(-half, half, n_cells)
    y_coords = np.linspace(-half, half, n_cells)

    # Calculate noise level at every grid point
    noise_grid = np.zeros((n_cells, n_cells), dtype=np.float64)

    for src in source_positions:
        sx, sy = src["x_m"], src["y_m"]
        lw = src["lw_dba"]
        h_src = src["height_m"]

        for ri, y in enumerate(y_coords):
            for ci, x in enumerate(x_coords):
                dist = math.sqrt((x - sx) ** 2 + (y - sy) ** 2)
                if dist < 1.0:
                    dist = 1.0
                spl = _sound_pressure_level(lw, dist, source_height_m=h_src)
                # Logarithmic addition to existing level
                existing = noise_grid[ri, ci]
                if existing > 0:
                    noise_grid[ri, ci] = _logarithmic_sum([existing, spl])
                else:
                    noise_grid[ri, ci] = spl

    # Apply tonal penalty
    penalty = 5.0 if tonal_penalty else 0.0
    if penalty > 0:
        noise_grid += penalty

    # Extract contours
    features = []
    for level in CONTOUR_LEVELS:
        polylines = _marching_squares_contour(noise_grid, level, x_coords, y_coords)
        geom = _contour_to_polygon(polylines, ref_lat, ref_lon)
        if geom:
            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "level_dba": level,
                    "color": CONTOUR_COLOURS.get(level, "#888888"),
                    "label": f"{level} dB(A)",
                },
            })

    contours_geojson = {"type": "FeatureCollection", "features": features}

    # Evaluate specific receptors
    receptor_results = []
    max_receptor_level = 0.0

    if receptors:
        for rec in receptors:
            rx, ry = _latlon_to_metres(rec["lat"], rec["lon"], ref_lat, ref_lon)
            levels = []
            for src in source_positions:
                dist = math.sqrt((rx - src["x_m"]) ** 2 + (ry - src["y_m"]) ** 2)
                spl = _sound_pressure_level(src["lw_dba"], dist, source_height_m=src["height_m"])
                levels.append(spl)
            total = _logarithmic_sum(levels) + penalty
            receptor_results.append({
                "name": rec.get("name", "Receptor"),
                "lat": rec["lat"],
                "lon": rec["lon"],
                "predicted_level_dba": round(total, 1),
                "compliant": total <= compliance_limit_dba,
            })
            max_receptor_level = max(max_receptor_level, total)
    else:
        # Use grid maximum at study boundary (proxy for nearest receptor)
        # Check edges of grid as worst-case receptor
        edge_levels = []
        edge_levels.extend(noise_grid[0, :].tolist())
        edge_levels.extend(noise_grid[-1, :].tolist())
        edge_levels.extend(noise_grid[:, 0].tolist())
        edge_levels.extend(noise_grid[:, -1].tolist())
        max_receptor_level = max(edge_levels) if edge_levels else 0.0

    # Source summary
    source_summary = []
    for src in source_positions:
        source_summary.append({
            "type": src["type"],
            "lat": src["lat"],
            "lon": src["lon"],
            "power_level_dba": src["lw_dba"],
            "height_m": src["height_m"],
            "level_at_100m": round(
                _sound_pressure_level(src["lw_dba"], 100.0, source_height_m=src["height_m"]),
                1,
            ),
            "level_at_500m": round(
                _sound_pressure_level(src["lw_dba"], 500.0, source_height_m=src["height_m"]),
                1,
            ),
        })

    return {
        "contours_geojson": contours_geojson,
        "max_at_nearest_receptor_dba": round(max_receptor_level, 1),
        "compliant": max_receptor_level <= compliance_limit_dba,
        "compliance_limit_dba": compliance_limit_dba,
        "tonal_penalty_applied": tonal_penalty,
        "tonal_penalty_db": penalty,
        "sources": source_summary,
        "receptors": receptor_results if receptors else None,
        "study_radius_m": study_radius_m,
        "grid_resolution_m": receptor_grid_size_m,
        "methodology": "ISO 9613-2:1996",
        "assumptions": {
            "atmospheric_absorption_db_km": ALPHA_500HZ,
            "ground_factor": GROUND_FACTOR_SOFT,
            "receiver_height_m": 1.5,
            "temperature_c": 15,
            "humidity_pct": 70,
        },
    }
