"""Solar panel glint/glare screening (SGHAT-style).

Implements a lightweight analogue of the FAA Solar Glare Hazard Analysis Tool:
  - Sun position sampled across the year.
  - Specular reflection vector off the panel normal.
  - If reflection vector passes through a retinal-irradiance cone around
    the receptor line-of-sight, an event is logged.
  - Events are categorised as green (low), yellow (after-image), red
    (retinal burn) per FAA subjective ocular impact categories.

References:
  - Ho, Ghanbari, Diver, "Methodology to Assess Potential Glint and Glare
    Hazards From Concentrating Solar Power Plants," SolarPACES 2011
  - FAA Policy Letter, 2013 (AC 150/5300-15B)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field


# Retinal irradiance thresholds (W/cm^2) per Ho/Ghanbari 2011
RETINAL_THRESHOLD_GREEN = 0.0   # below = no impact
RETINAL_THRESHOLD_YELLOW = 4.0   # after-image possible
RETINAL_THRESHOLD_RED = 100.0    # permanent retinal damage

# Solar DNI at normal incidence, nominal clear-sky UK peak (W/m2)
SOLAR_DNI_PEAK_W_M2 = 900.0

# Reflectance of standard AR-coated crystalline silicon glass
PV_REFLECTANCE = 0.02

# Retinal spot radius for lens focusing (cm)
RETINAL_SPOT_RADIUS_CM = 0.01

# Pupil aperture area (cm^2) @ 5 mm
PUPIL_AREA_CM2 = 0.196


@dataclass
class GlareResult:
    inputs_echo: dict
    outputs: dict
    assumptions: list[str]
    provenance: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Solar geometry — NOAA-style algorithm (sufficient for screening)
# ---------------------------------------------------------------------------
def _sun_position(lat: float, lon: float, day_of_year: int, hour_utc: float) -> tuple[float, float]:
    """Return (azimuth_deg_from_N_cw, altitude_deg)."""
    # Solar declination (deg)
    decl = 23.45 * math.sin(math.radians(360.0 / 365.0 * (day_of_year - 81)))
    # Equation of time (min, Spencer 1971 short form)
    b = math.radians(360.0 / 365.0 * (day_of_year - 81))
    eqt_min = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    # Solar time correction
    time_correction_min = 4 * lon + eqt_min
    solar_time_hr = hour_utc + time_correction_min / 60.0
    hour_angle_deg = 15.0 * (solar_time_hr - 12.0)

    lat_r = math.radians(lat)
    decl_r = math.radians(decl)
    ha_r = math.radians(hour_angle_deg)

    sin_alt = math.sin(lat_r) * math.sin(decl_r) + math.cos(lat_r) * math.cos(decl_r) * math.cos(ha_r)
    alt = math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))

    cos_az = (math.sin(decl_r) - math.sin(math.radians(alt)) * math.sin(lat_r)) / (
        math.cos(math.radians(alt)) * math.cos(lat_r) + 1e-9
    )
    cos_az = max(-1.0, min(1.0, cos_az))
    az = math.degrees(math.acos(cos_az))
    if math.sin(ha_r) > 0:
        az = 360.0 - az
    return az, alt


def _panel_normal_vector(tilt_deg: float, azimuth_deg: float) -> tuple[float, float, float]:
    t = math.radians(tilt_deg)
    a = math.radians(azimuth_deg)
    return (math.sin(t) * math.sin(a), math.sin(t) * math.cos(a), math.cos(t))


def _sun_vector(azimuth_deg: float, altitude_deg: float) -> tuple[float, float, float]:
    az = math.radians(azimuth_deg)
    alt = math.radians(altitude_deg)
    return (math.cos(alt) * math.sin(az), math.cos(alt) * math.cos(az), math.sin(alt))


def _reflect(sun: tuple[float, float, float], n: tuple[float, float, float]):
    dot = sum(s * ni for s, ni in zip(sun, n))
    return tuple(2 * dot * ni - s for s, ni in zip(sun, n))


def _vector_to_receptor(
    panel_lat: float, panel_lon: float, panel_height_m: float,
    receptor_lat: float, receptor_lon: float, receptor_height_m: float,
) -> tuple[float, float, float]:
    # Flat-earth — acceptable for < 5 km
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = m_per_deg_lat * math.cos(math.radians(panel_lat))
    dx = (receptor_lon - panel_lon) * m_per_deg_lon
    dy = (receptor_lat - panel_lat) * m_per_deg_lat
    dz = receptor_height_m - panel_height_m
    mag = math.sqrt(dx * dx + dy * dy + dz * dz)
    if mag < 1e-6:
        return (0.0, 0.0, 0.0)
    return (dx / mag, dy / mag, dz / mag)


def _angle_between(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a < 1e-9 or mag_b < 1e-9:
        return 180.0
    cos_t = max(-1.0, min(1.0, dot / (mag_a * mag_b)))
    return math.degrees(math.acos(cos_t))


def _retinal_irradiance_w_cm2(dni_w_m2: float, reflectance: float, subtended_mrad: float) -> float:
    """Approx retinal irradiance via pupil + lens focus (Ho 2011)."""
    source_irradiance_w_cm2 = dni_w_m2 * reflectance / 10_000.0
    # Source power intercepted by pupil (W)
    power_w = source_irradiance_w_cm2 * PUPIL_AREA_CM2
    # Retinal spot area scales with angular subtense (mrad)
    spot_area_cm2 = math.pi * (max(0.005, subtended_mrad * 1.7e-3 / 2.0)) ** 2
    return power_w / max(spot_area_cm2, 1e-9)


def _category(retinal_w_cm2: float) -> str:
    if retinal_w_cm2 >= RETINAL_THRESHOLD_RED:
        return "red"
    if retinal_w_cm2 >= RETINAL_THRESHOLD_YELLOW:
        return "yellow"
    return "green"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def screen_glint_glare(
    panel_lat: float,
    panel_lon: float,
    panel_tilt_deg: float,
    panel_azimuth_deg: float,
    receptor_lat: float,
    receptor_lon: float,
    panel_height_m: float = 2.5,
    receptor_height_m: float = 1.7,
    panel_area_m2: float = 10.0,
    module_reflectance: float = PV_REFLECTANCE,
    samples_per_day_hours: list[int] | None = None,
    sample_days: int = 12,
    beam_half_angle_deg: float = 2.5,
) -> GlareResult:
    """Screen a panel array vs a single receptor for annual glare.

    Returns total event count by category and a monthly histogram.
    """
    if sample_days < 1:
        raise ValueError("sample_days >= 1")
    if not (0 <= panel_tilt_deg <= 90):
        raise ValueError("panel_tilt_deg in [0, 90]")

    sample_hours = samples_per_day_hours or list(range(5, 21))  # 05:00-20:00 UTC
    n = _panel_normal_vector(panel_tilt_deg, panel_azimuth_deg)
    los = _vector_to_receptor(
        panel_lat, panel_lon, panel_height_m,
        receptor_lat, receptor_lon, receptor_height_m,
    )

    # Distance (m) for subtended angle calc
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = m_per_deg_lat * math.cos(math.radians(panel_lat))
    dx = (receptor_lon - panel_lon) * m_per_deg_lon
    dy = (receptor_lat - panel_lat) * m_per_deg_lat
    distance_m = math.sqrt(dx * dx + dy * dy) + 1e-6

    panel_diam_m = math.sqrt(panel_area_m2)
    subtended_mrad = 1000.0 * panel_diam_m / distance_m

    counts = {"green": 0, "yellow": 0, "red": 0}
    monthly = {m: 0 for m in range(1, 13)}
    events: list[dict] = []
    days_sampled = []

    # Sample days evenly across year
    for i in range(sample_days):
        doy = int((i + 0.5) * 365.0 / sample_days)
        days_sampled.append(doy)
        month = min(12, max(1, math.ceil(doy / 30.5)))
        for hr in sample_hours:
            az, alt = _sun_position(panel_lat, panel_lon, doy, hr)
            if alt <= 0:  # sun below horizon
                continue
            sun = _sun_vector(az, alt)
            refl = _reflect(sun, n)
            # Reflection must go "up/outward" (positive z component)
            if refl[2] <= 0:
                continue
            angle = _angle_between(refl, los)
            if angle <= beam_half_angle_deg:
                retinal = _retinal_irradiance_w_cm2(
                    SOLAR_DNI_PEAK_W_M2, module_reflectance, subtended_mrad,
                )
                cat = _category(retinal)
                counts[cat] += 1
                monthly[month] += 1
                events.append({
                    "day_of_year": doy,
                    "hour_utc": hr,
                    "sun_az_deg": round(az, 1),
                    "sun_alt_deg": round(alt, 1),
                    "miss_angle_deg": round(angle, 3),
                    "retinal_w_cm2": round(retinal, 3),
                    "category": cat,
                })

    total = sum(counts.values())
    warnings = []
    if counts["red"] > 0:
        warnings.append(f"{counts['red']} red-category events — retinal burn risk; redesign azimuth/tilt")
    if counts["yellow"] > 10:
        warnings.append(f"{counts['yellow']} yellow-category events — after-image risk")

    return GlareResult(
        inputs_echo={
            "panel_lat": panel_lat, "panel_lon": panel_lon,
            "panel_tilt_deg": panel_tilt_deg,
            "panel_azimuth_deg": panel_azimuth_deg,
            "receptor_lat": receptor_lat, "receptor_lon": receptor_lon,
            "panel_area_m2": panel_area_m2,
            "module_reflectance": module_reflectance,
            "sample_days": sample_days,
            "beam_half_angle_deg": beam_half_angle_deg,
        },
        outputs={
            "total_events": total,
            "events_by_category": counts,
            "monthly_histogram": monthly,
            "distance_m": round(distance_m, 1),
            "subtended_mrad": round(subtended_mrad, 3),
            "sample_event_list": events[:25],
        },
        assumptions=[
            f"DNI peak {SOLAR_DNI_PEAK_W_M2} W/m2 (clear-sky UK)",
            f"Beam half-angle {beam_half_angle_deg}° (SGHAT default)",
            "Flat-earth geometry within ~5 km",
            f"Sampled {sample_days} days × {len(sample_hours)} hrs",
        ],
        provenance="Ho, Ghanbari & Diver 2011; FAA AC 150/5300-15B",
        warnings=warnings,
    )
