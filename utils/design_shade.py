"""Shade analysis — project sun-cast shadows from building + vegetation
heights onto a site boundary at a user-chosen time-of-day / time-of-year.

Sun position uses the simplified NOAA solar algorithm (accurate to <0.1°
for any GB latitude). Shadows are computed as displacement polygons from
each obstruction column in the DEM, projected along the anti-solar vector
and clipped to ground level. Results are merged into a single shadow
MultiPolygon feature and returned as GeoJSON the frontend can render.

Inputs:
  dem   — DEMResult from utils.lidar_uk.fetch_dem (DSM for building heights)
  when  — ISO timestamp in UTC
Returns:
  GeoJSON FeatureCollection of shadow polygons + solar metadata
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def solar_position(lat: float, lon: float, when: datetime) -> tuple[float, float]:
    """Return (azimuth_deg, altitude_deg) for given lat/lon/UTC timestamp.
    Azimuth is 0° = north, clockwise. Altitude is 0° = horizon, 90° = zenith.
    Reference: NOAA Solar Position Algorithm."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    utc = when.astimezone(timezone.utc)
    # Julian day
    y, m, d = utc.year, utc.month, utc.day
    h = utc.hour + utc.minute / 60 + utc.second / 3600
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    jd = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5 + h / 24
    n = jd - 2451545.0  # days from J2000

    L = (280.460 + 0.9856474 * n) % 360          # mean longitude
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.0000004 * n)
    alpha = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360
    delta = math.degrees(math.asin(math.sin(eps) * math.sin(lam)))
    gmst = (18.697374558 + 24.06570982441908 * n) % 24
    lst = (gmst + lon / 15) % 24
    ha = (lst * 15 - alpha + 180) % 360 - 180
    har = math.radians(ha)
    lr = math.radians(lat)
    dr = math.radians(delta)
    alt = math.degrees(math.asin(math.sin(lr) * math.sin(dr) + math.cos(lr) * math.cos(dr) * math.cos(har)))
    az = math.degrees(math.atan2(-math.sin(har), math.tan(dr) * math.cos(lr) - math.sin(lr) * math.cos(har))) % 360
    return az, alt


def compute_shadows(dem, when: datetime, ground_threshold_m: float = 1.0) -> dict[str, Any]:
    """Project shadows from every DEM cell taller than ``ground_threshold_m``
    above the local terrain minimum. Returns a GeoJSON FeatureCollection."""
    west, south, east, north = dem.bbox
    lat_c = (south + north) / 2
    lon_c = (west + east) / 2
    az, alt = solar_position(lat_c, lon_c, when)
    if alt <= 0:
        return {
            "type": "FeatureCollection",
            "features": [],
            "meta": {
                "sun_azimuth_deg": az, "sun_altitude_deg": alt,
                "note": "Sun below horizon — no shadows to render.",
                "timestamp": when.isoformat(),
            },
        }

    # Anti-solar direction in map coords: shadow extends away from the sun
    # (azimuth + 180 mod 360), length = obstruction_height / tan(altitude).
    shadow_az = (az + 180) % 360
    az_rad = math.radians(shadow_az)
    dx_unit = math.sin(az_rad)
    dy_unit = math.cos(az_rad)

    rows, cols = dem.rows, dem.cols
    # Rough metres→degrees at this latitude
    m_per_deg_lat = 111_320
    m_per_deg_lon = 111_320 * math.cos(math.radians(lat_c))
    cell_w = (east - west) / max(1, cols - 1)
    cell_h = (north - south) / max(1, rows - 1)

    # Find local minimum (ground reference)
    ground = min(min(r) for r in dem.elevations) if dem.elevations else 0
    features = []
    tan_alt = math.tan(math.radians(alt))
    for i in range(rows):
        for j in range(cols):
            h = dem.elevations[i][j] - ground
            if h <= ground_threshold_m:
                continue
            # Obstruction cell footprint in lon/lat
            x0 = west + j * cell_w
            y0 = north - i * cell_h
            x1 = x0 + cell_w
            y1 = y0 - cell_h
            # Shadow displacement
            length_m = h / max(0.1, tan_alt)
            d_lon = (length_m / m_per_deg_lon) * dx_unit
            d_lat = (length_m / m_per_deg_lat) * dy_unit
            # Project the far edges of the cell along (d_lon, d_lat)
            ring = [
                [x0, y0],
                [x1, y0],
                [x1 + d_lon, y0 + d_lat],
                [x0 + d_lon, y0 + d_lat],
                [x0, y0],
            ]
            features.append({
                "type": "Feature",
                "properties": {"height_m": round(h, 1)},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            })

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "sun_azimuth_deg": round(az, 2),
            "sun_altitude_deg": round(alt, 2),
            "shadow_azimuth_deg": round(shadow_az, 2),
            "dem_source": dem.source,
            "dem_resolution_m": dem.resolution_m,
            "timestamp": when.isoformat(),
        },
    }
