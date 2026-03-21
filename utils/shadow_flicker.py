"""
Shadow flicker & glint-glare calculator.

Shadow flicker:
- Models rotating blade shadow patterns on receptor locations
- Uses sun position (solar geometry), turbine specs, receptor distance
- UK planning threshold: max 30 hours/year, max 30 minutes/day

Glint-glare:
- Models specular reflection from solar panels towards receptor locations
- Uses sun position, panel tilt/azimuth, receptor geometry
- Determines if reflected beam intersects receptor viewpoints

Both use simplified solar geometry consistent with _compute_sun_paths in helpers.py.
"""

from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("princeps.shadow_flicker")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEG2RAD = math.pi / 180.0
RAD2DEG = 180.0 / math.pi

# UK planning guidance thresholds
FLICKER_MAX_ANNUAL_HOURS = 30
FLICKER_MAX_DAILY_MINUTES = 30

# Glint-glare acceptance cone half-angle (degrees)
GLINT_CONE_HALF_DEG = 2.0

# Earth radius for distance calculations (metres)
EARTH_RADIUS_M = 6_371_000


# ---------------------------------------------------------------------------
# Solar geometry
# ---------------------------------------------------------------------------

def _sun_position(lat: float, lon: float, day_of_year: int, hour_utc: float) -> tuple[float, float]:
    """
    Calculate solar altitude and azimuth for a given location and time.

    Returns (altitude_deg, azimuth_deg) where azimuth is measured clockwise
    from north (0=N, 90=E, 180=S, 270=W).  Altitude < 0 means sun is below
    horizon.
    """
    # Solar declination (Spencer, 1971 simplified)
    decl = 23.45 * math.sin(DEG2RAD * (360.0 / 365.0 * (day_of_year - 81)))

    # Equation of time (minutes) — Spencer approximation
    B = DEG2RAD * (360.0 / 365.0 * (day_of_year - 81))
    eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)

    # Solar time
    solar_time = hour_utc + lon / 15.0 + eot / 60.0
    hour_angle = 15.0 * (solar_time - 12.0)

    lat_r = lat * DEG2RAD
    decl_r = decl * DEG2RAD
    ha_r = hour_angle * DEG2RAD

    sin_alt = (math.sin(lat_r) * math.sin(decl_r) +
               math.cos(lat_r) * math.cos(decl_r) * math.cos(ha_r))
    sin_alt = max(-1.0, min(1.0, sin_alt))
    altitude = math.asin(sin_alt) * RAD2DEG

    # Azimuth
    cos_alt = math.cos(altitude * DEG2RAD)
    if cos_alt < 1e-6:
        azimuth = 180.0
    else:
        cos_az = (math.sin(decl_r) - math.sin(lat_r) * sin_alt) / (
            math.cos(lat_r) * cos_alt
        )
        cos_az = max(-1.0, min(1.0, cos_az))
        azimuth = math.acos(cos_az) * RAD2DEG
        if hour_angle > 0:
            azimuth = 360.0 - azimuth

    return altitude, azimuth


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    dlat = (lat2 - lat1) * DEG2RAD
    dlon = (lon2 - lon1) * DEG2RAD
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1 * DEG2RAD) * math.cos(lat2 * DEG2RAD) *
         math.sin(dlon / 2) ** 2)
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing (degrees clockwise from north) from point 1 to point 2."""
    lat1_r, lat2_r = lat1 * DEG2RAD, lat2 * DEG2RAD
    dlon_r = (lon2 - lon1) * DEG2RAD
    x = math.sin(dlon_r) * math.cos(lat2_r)
    y = (math.cos(lat1_r) * math.sin(lat2_r) -
         math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dlon_r))
    brng = math.atan2(x, y) * RAD2DEG
    return brng % 360.0


# ---------------------------------------------------------------------------
# Shadow flicker
# ---------------------------------------------------------------------------

def _shadow_hits_receptor(
    sun_alt: float,
    sun_az: float,
    turbine_lat: float,
    turbine_lon: float,
    receptor_lat: float,
    receptor_lon: float,
    hub_height_m: float,
    rotor_diameter_m: float,
    receptor_height_m: float,
) -> bool:
    """
    Check whether the shadow of a turbine blade can reach the receptor at
    the given sun position.

    The shadow tip distance from the turbine base is approximately:
        shadow_length = hub_height / tan(sun_altitude)

    The shadow sweeps an arc whose angular width at the shadow tip is:
        arc_half_angle = atan(rotor_radius / shadow_length)

    The receptor is affected if:
      1. It lies at a distance ≤ shadow_length from the turbine
      2. The bearing from turbine→receptor is within the shadow sweep arc
         (shadow is cast in the direction opposite the sun azimuth)
    """
    if sun_alt <= 0:
        return False  # sun below horizon

    tan_alt = math.tan(sun_alt * DEG2RAD)
    if tan_alt < 1e-6:
        return False  # sun too low, shadow infinitely long (unrealistic)

    # Maximum shadow length from hub
    shadow_length = hub_height_m / tan_alt

    # Distance from turbine to receptor
    dist_m = _haversine_m(turbine_lat, turbine_lon, receptor_lat, receptor_lon)

    # Shadow must reach receptor — account for receptor height reducing
    # effective shadow length needed
    effective_shadow_needed = dist_m  # ground distance
    # Receptor height reduces the required shadow length slightly
    height_diff = hub_height_m - receptor_height_m
    if height_diff <= 0:
        return False  # receptor taller than hub — blade shadow goes above
    effective_shadow_length = height_diff / tan_alt

    if dist_m > effective_shadow_length:
        return False

    # Shadow direction is opposite to sun azimuth
    shadow_az = (sun_az + 180.0) % 360.0

    # Bearing from turbine to receptor
    bearing = _bearing_deg(turbine_lat, turbine_lon, receptor_lat, receptor_lon)

    # Angular half-width of shadow sweep at receptor distance
    rotor_radius = rotor_diameter_m / 2.0
    if dist_m < 1.0:
        arc_half = 90.0  # receptor at base of turbine
    else:
        arc_half = math.atan(rotor_radius / dist_m) * RAD2DEG

    # Ensure minimum sweep angle (blade rotation covers full rotor disc)
    arc_half = max(arc_half, 1.0)

    # Check if bearing falls within shadow sweep arc
    angle_diff = abs(bearing - shadow_az)
    if angle_diff > 180:
        angle_diff = 360 - angle_diff

    return angle_diff <= arc_half


async def calculate_shadow_flicker(
    lat: float,
    lon: float,
    turbine_specs: dict,
    receptors: list[dict],
    pool=None,
) -> dict:
    """
    Calculate annual shadow flicker exposure for each receptor.

    Parameters
    ----------
    lat, lon : float
        Site centre (used for auto-detect if no receptors provided).
    turbine_specs : dict
        hub_height_m, rotor_diameter_m, count, positions [{lat, lon}]
    receptors : list[dict]
        [{lat, lon, name, height_m}] — if empty, auto-detect from DB.
    pool : asyncpg.Pool, optional
        Database pool for auto-detecting receptors.

    Returns
    -------
    dict with receptors results and summary.
    """
    hub_height = turbine_specs.get("hub_height_m", 80)
    rotor_diam = turbine_specs.get("rotor_diameter_m", 100)
    positions = turbine_specs.get("positions", [])

    if not positions:
        # Default: single turbine at site centre
        positions = [{"lat": lat, "lon": lon}]

    # Auto-detect receptors if none provided
    if not receptors and pool:
        receptors = await auto_detect_receptors(pool, lat, lon, radius_m=1500)
    if not receptors:
        return {
            "receptors": [],
            "summary": {
                "max_annual_hours": 0,
                "compliant": True,
                "threshold_hours": FLICKER_MAX_ANNUAL_HOURS,
                "threshold_daily_min": FLICKER_MAX_DAILY_MINUTES,
                "note": "No receptors found within assessment radius",
            },
        }

    # Hourly simulation for 365 days (8760 hours)
    receptor_results = []
    for rec in receptors:
        r_lat = rec["lat"]
        r_lon = rec["lon"]
        r_name = rec.get("name", f"Receptor ({r_lat:.4f}, {r_lon:.4f})")
        r_height = rec.get("height_m", 6.0)

        daily_minutes = [0.0] * 365
        monthly_hours = [0.0] * 12

        for doy in range(1, 366):
            month_idx = _doy_to_month(doy)
            for h_frac_10 in range(40, 220):  # 4.0 to 22.0 in 0.1-hour steps
                hour_utc = h_frac_10 / 10.0
                sun_alt, sun_az = _sun_position(lat, lon, doy, hour_utc)
                if sun_alt <= 0:
                    continue

                for tpos in positions:
                    if _shadow_hits_receptor(
                        sun_alt, sun_az,
                        tpos["lat"], tpos["lon"],
                        r_lat, r_lon,
                        hub_height, rotor_diam, r_height,
                    ):
                        # 6-minute interval (0.1 hour)
                        daily_minutes[doy - 1] += 6.0
                        monthly_hours[month_idx] += 0.1
                        break  # only count once per timestep even if multiple turbines

        annual_hours = sum(monthly_hours)
        max_daily_min = max(daily_minutes)
        worst_month_idx = monthly_hours.index(max(monthly_hours))
        worst_month = _MONTH_NAMES[worst_month_idx]
        compliant = (annual_hours <= FLICKER_MAX_ANNUAL_HOURS and
                     max_daily_min <= FLICKER_MAX_DAILY_MINUTES)

        receptor_results.append({
            "name": r_name,
            "lat": r_lat,
            "lon": r_lon,
            "annual_hours": round(annual_hours, 1),
            "max_daily_minutes": round(max_daily_min, 1),
            "worst_month": worst_month,
            "monthly_hours": [round(m, 1) for m in monthly_hours],
            "compliant": compliant,
        })

    max_annual = max(r["annual_hours"] for r in receptor_results)
    max_daily = max(r["max_daily_minutes"] for r in receptor_results)
    all_compliant = all(r["compliant"] for r in receptor_results)

    return {
        "receptors": receptor_results,
        "turbine_count": len(positions),
        "hub_height_m": hub_height,
        "rotor_diameter_m": rotor_diam,
        "summary": {
            "max_annual_hours": round(max_annual, 1),
            "max_daily_minutes": round(max_daily, 1),
            "compliant": all_compliant,
            "threshold_hours": FLICKER_MAX_ANNUAL_HOURS,
            "threshold_daily_min": FLICKER_MAX_DAILY_MINUTES,
            "receptor_count": len(receptor_results),
            "non_compliant_count": sum(1 for r in receptor_results if not r["compliant"]),
        },
    }


# ---------------------------------------------------------------------------
# Glint-glare
# ---------------------------------------------------------------------------

def _reflection_hits_receptor(
    sun_alt: float,
    sun_az: float,
    panel_tilt: float,
    panel_azimuth: float,
    panel_lat: float,
    panel_lon: float,
    receptor_lat: float,
    receptor_lon: float,
    receptor_height_m: float,
    cone_half_deg: float = GLINT_CONE_HALF_DEG,
) -> bool:
    """
    Check whether specular reflection from a tilted panel reaches a receptor.

    The panel normal vector is computed from tilt and azimuth. The sun vector
    is reflected off the panel surface. If the reflected ray direction points
    within cone_half_deg of the receptor direction, glint occurs.
    """
    if sun_alt <= 0:
        return False

    # Sun direction vector (towards the sun, in local ENU-like frame)
    #   x = East, y = North, z = Up
    sun_el_r = sun_alt * DEG2RAD
    sun_az_r = sun_az * DEG2RAD
    sun_x = math.cos(sun_el_r) * math.sin(sun_az_r)
    sun_y = math.cos(sun_el_r) * math.cos(sun_az_r)
    sun_z = math.sin(sun_el_r)

    # Panel normal vector (tilt from horizontal, azimuth = direction panel faces)
    tilt_r = panel_tilt * DEG2RAD
    paz_r = panel_azimuth * DEG2RAD
    n_x = math.sin(tilt_r) * math.sin(paz_r)
    n_y = math.sin(tilt_r) * math.cos(paz_r)
    n_z = math.cos(tilt_r)

    # Incidence angle: cos(theta_i) = dot(sun, normal)
    cos_inc = sun_x * n_x + sun_y * n_y + sun_z * n_z
    if cos_inc <= 0:
        return False  # sun is behind the panel

    # Reflected ray: R = 2*(S.N)*N - S
    ref_x = 2 * cos_inc * n_x - sun_x
    ref_y = 2 * cos_inc * n_y - sun_y
    ref_z = 2 * cos_inc * n_z - sun_z

    # Direction from panel to receptor (horizontal)
    bearing = _bearing_deg(panel_lat, panel_lon, receptor_lat, receptor_lon)
    dist_m = _haversine_m(panel_lat, panel_lon, receptor_lat, receptor_lon)
    if dist_m < 1.0:
        return False

    # Receptor direction vector (from panel to receptor)
    # Elevation angle towards receptor (receptor_height above ground at distance)
    elev_to_receptor = math.atan2(receptor_height_m, dist_m)
    brng_r = bearing * DEG2RAD
    rec_x = math.cos(elev_to_receptor) * math.sin(brng_r)
    rec_y = math.cos(elev_to_receptor) * math.cos(brng_r)
    rec_z = math.sin(elev_to_receptor)

    # Angle between reflected ray and receptor direction
    ref_mag = math.sqrt(ref_x**2 + ref_y**2 + ref_z**2)
    if ref_mag < 1e-9:
        return False
    dot = (ref_x * rec_x + ref_y * rec_y + ref_z * rec_z) / ref_mag
    dot = max(-1.0, min(1.0, dot))
    angle = math.acos(dot) * RAD2DEG

    return angle <= cone_half_deg


async def calculate_glint_glare(
    lat: float,
    lon: float,
    panel_specs: dict,
    receptors: list[dict],
    pool=None,
) -> dict:
    """
    Calculate annual glint-glare exposure for each receptor from a solar array.

    Parameters
    ----------
    lat, lon : float
        Site centre.
    panel_specs : dict
        tilt_deg, azimuth_deg, width_m, height_m, area_ha, reflectivity
    receptors : list[dict]
        [{lat, lon, name, height_m}]
    pool : asyncpg.Pool, optional

    Returns
    -------
    dict with per-receptor results and summary.
    """
    tilt = panel_specs.get("tilt_deg", 25)
    azimuth = panel_specs.get("azimuth_deg", 180)
    reflectivity = panel_specs.get("reflectivity", 0.05)
    area_ha = panel_specs.get("area_ha", 1.0)

    # Auto-detect receptors if none provided
    if not receptors and pool:
        receptors = await auto_detect_receptors(pool, lat, lon, radius_m=1000)
    if not receptors:
        return {
            "receptors": [],
            "summary": {
                "max_annual_minutes": 0,
                "aviation_risk": False,
                "note": "No receptors found within assessment radius",
            },
        }

    # For large arrays, model reflections from array centroid (conservative)
    # A more detailed model would sample multiple points across the array.
    panel_lat, panel_lon = lat, lon

    receptor_results = []
    for rec in receptors:
        r_lat = rec["lat"]
        r_lon = rec["lon"]
        r_name = rec.get("name", f"Receptor ({r_lat:.4f}, {r_lon:.4f})")
        r_height = rec.get("height_m", 6.0)
        is_aviation = rec.get("is_aviation", False)

        daily_minutes = [0.0] * 365
        monthly_minutes = [0.0] * 12

        for doy in range(1, 366):
            month_idx = _doy_to_month(doy)
            for h_frac_10 in range(40, 220):  # 4.0 to 22.0
                hour_utc = h_frac_10 / 10.0
                sun_alt, sun_az = _sun_position(lat, lon, doy, hour_utc)
                if sun_alt <= 0:
                    continue

                if _reflection_hits_receptor(
                    sun_alt, sun_az,
                    tilt, azimuth,
                    panel_lat, panel_lon,
                    r_lat, r_lon,
                    r_height,
                ):
                    daily_minutes[doy - 1] += 6.0  # 6-minute interval
                    monthly_minutes[month_idx] += 6.0

        annual_minutes = sum(monthly_minutes)
        worst_month_idx = monthly_minutes.index(max(monthly_minutes))
        worst_month = _MONTH_NAMES[worst_month_idx]

        # Determine intensity based on annual exposure
        if annual_minutes < 60:
            intensity = "low"
        elif annual_minutes < 300:
            intensity = "medium"
        else:
            intensity = "high"

        # Find worst period (consecutive hours of glint)
        worst_daily = max(daily_minutes)
        worst_doy = daily_minutes.index(worst_daily) + 1 if worst_daily > 0 else None
        worst_period = None
        if worst_doy:
            worst_period = f"Day {worst_doy} ({_doy_to_date_str(worst_doy)}), {worst_daily:.0f} min"

        receptor_results.append({
            "name": r_name,
            "lat": r_lat,
            "lon": r_lon,
            "annual_minutes": round(annual_minutes, 1),
            "max_daily_minutes": round(worst_daily, 1),
            "worst_month": worst_month,
            "worst_period": worst_period,
            "monthly_minutes": [round(m, 1) for m in monthly_minutes],
            "intensity": intensity,
            "is_aviation": is_aviation,
        })

    max_annual = max(r["annual_minutes"] for r in receptor_results)
    aviation_risk = any(
        r["is_aviation"] and r["annual_minutes"] > 0
        for r in receptor_results
    )

    return {
        "receptors": receptor_results,
        "panel_tilt_deg": tilt,
        "panel_azimuth_deg": azimuth,
        "reflectivity": reflectivity,
        "area_ha": area_ha,
        "summary": {
            "max_annual_minutes": round(max_annual, 1),
            "aviation_risk": aviation_risk,
            "receptor_count": len(receptor_results),
            "high_intensity_count": sum(1 for r in receptor_results if r["intensity"] == "high"),
            "medium_intensity_count": sum(1 for r in receptor_results if r["intensity"] == "medium"),
        },
    }


# ---------------------------------------------------------------------------
# Auto-detect receptors from DB
# ---------------------------------------------------------------------------

async def auto_detect_receptors(pool, lat: float, lon: float, radius_m: float = 1000) -> list[dict]:
    """
    Auto-detect potential sensitive receptors near a site using PostGIS data.

    Queries:
      - osm_power_substations (as proxy for nearby structures in the DB)
      - Known buildings from Open Buildings / vision analyses
      - Generates cardinal-direction synthetic receptors as fallback
    """
    receptors: list[dict] = []

    if pool is not None:
        try:
            async with pool.acquire() as conn:
                # 1. Try OSM buildings / substations within radius
                #    (osm_power_substation table stores nearby infrastructure)
                try:
                    rows = await conn.fetch("""
                        SELECT name,
                               ST_Y(geometry) AS lat,
                               ST_X(geometry) AS lon
                        FROM osm_power_substation
                        WHERE ST_DWithin(
                            geometry,
                            ST_SetSRID(ST_MakePoint($1, $2), 4326),
                            $3
                        )
                        LIMIT 20
                    """, lon, lat, radius_m / 111320.0)  # approximate degrees
                    for r in rows:
                        receptors.append({
                            "lat": float(r["lat"]),
                            "lon": float(r["lon"]),
                            "name": r["name"] or "Infrastructure",
                            "height_m": 10.0,
                        })
                except Exception:
                    pass  # table may not exist

                # 2. Try REPD projects nearby (existing installations)
                try:
                    rows = await conn.fetch("""
                        SELECT site_name,
                               ST_Y(geometry) AS lat,
                               ST_X(geometry) AS lon
                        FROM repd_projects
                        WHERE geometry IS NOT NULL
                          AND ST_DWithin(
                            geometry,
                            ST_SetSRID(ST_MakePoint($1, $2), 4326),
                            $3
                          )
                        LIMIT 10
                    """, lon, lat, radius_m / 111320.0)
                    for r in rows:
                        receptors.append({
                            "lat": float(r["lat"]),
                            "lon": float(r["lon"]),
                            "name": r["site_name"] or "REPD Installation",
                            "height_m": 8.0,
                        })
                except Exception:
                    pass
        except Exception as e:
            log.debug("Auto-detect DB query failed: %s", e)

    # Fallback: generate synthetic receptors at cardinal directions
    if not receptors:
        log.info("No DB receptors found — generating synthetic receptors at %dm", int(radius_m))
        offsets = [
            ("North dwelling", 0),
            ("East dwelling", 90),
            ("South dwelling", 180),
            ("West dwelling", 270),
            ("NE dwelling", 45),
            ("SE dwelling", 135),
            ("SW dwelling", 225),
            ("NW dwelling", 315),
        ]
        for name, bearing in offsets:
            r_lat, r_lon = _offset_point(lat, lon, radius_m * 0.8, bearing)
            receptors.append({
                "lat": r_lat,
                "lon": r_lon,
                "name": name,
                "height_m": 6.0,
            })

    return receptors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Cumulative days at start of each month (non-leap)
_MONTH_START_DOY = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]


def _doy_to_month(doy: int) -> int:
    """Convert day-of-year (1-365) to month index (0-11)."""
    for i in range(11, -1, -1):
        if doy >= _MONTH_START_DOY[i]:
            return i
    return 0


def _doy_to_date_str(doy: int) -> str:
    """Convert day-of-year to approximate date string."""
    month = _doy_to_month(doy)
    day = doy - _MONTH_START_DOY[month] + 1
    return f"{day} {_MONTH_NAMES[month][:3]}"


def _offset_point(lat: float, lon: float, distance_m: float, bearing_deg: float) -> tuple[float, float]:
    """Offset a lat/lon point by distance and bearing."""
    d = distance_m / EARTH_RADIUS_M
    brng = bearing_deg * DEG2RAD
    lat_r = lat * DEG2RAD
    lon_r = lon * DEG2RAD

    new_lat = math.asin(
        math.sin(lat_r) * math.cos(d) +
        math.cos(lat_r) * math.sin(d) * math.cos(brng)
    )
    new_lon = lon_r + math.atan2(
        math.sin(brng) * math.sin(d) * math.cos(lat_r),
        math.cos(d) - math.sin(lat_r) * math.sin(new_lat),
    )
    return new_lat * RAD2DEG, new_lon * RAD2DEG
