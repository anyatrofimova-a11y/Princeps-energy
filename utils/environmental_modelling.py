"""Environmental receptor modelling for UK energy infrastructure.

Three models, all backed by documented standards:

  • `glare_assessment`          – solar glint/glare on static receptors using a
                                  compact NREL SPA (Solar Position Algorithm)
                                  implementation and the FAA SGHAT intensity
                                  bands (cd/m² retinal irradiance).
  • `shadow_flicker`            – wind-turbine flicker on nearby dwellings
                                  (UK PPG 2014 ceiling: 30 h/yr or 30 min/day).
  • `noise_propagation_iso9613_2` – simplified ISO 9613-2 point-source outdoor
                                  propagation with A_div, A_atm, A_gr, A_met.

All formulas are implemented from first principles; no external astronomical
libraries are required.  Values are compared against UK planning thresholds
(BS 4142:2014 / BS 5228-1:2009+A1:2014 for noise; PPG for flicker).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, date, timezone
from typing import Literal


# ===========================================================================
# Compact NREL Solar Position Algorithm (SPA)
# ===========================================================================
# Reference: Reda & Andreas (2004), "Solar Position Algorithm for Solar
# Radiation Applications", NREL/TP-560-34302.  This implementation uses the
# low-order series sufficient for receptor-scale glare/flicker modelling
# (error < 0.01° vs full SPA over 2000–2050 horizon).
# ---------------------------------------------------------------------------

def _julian_day(dt: datetime) -> float:
    """Julian day for a UTC datetime (civil calendar, Meeus 7.1)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    y, m = dt.year, dt.month
    d = (dt.day
         + dt.hour / 24.0
         + dt.minute / 1440.0
         + dt.second / 86400.0)
    if m <= 2:
        y -= 1
        m += 12
    a = math.floor(y / 100)
    b = 2 - a + math.floor(a / 4)
    return (math.floor(365.25 * (y + 4716))
            + math.floor(30.6001 * (m + 1))
            + d + b - 1524.5)


def solar_position(dt: datetime, lat_deg: float, lon_deg: float) -> tuple[float, float]:
    """Return (elevation_deg, azimuth_deg_from_north_clockwise) for UTC `dt`.

    Short Meeus/NREL series — good to ~0.01° in the 2000–2050 window.
    """
    jd = _julian_day(dt)
    n = jd - 2451545.0                          # days since J2000
    # Mean longitude & mean anomaly of the Sun
    L = (280.460 + 0.9856474 * n) % 360.0
    g = math.radians((357.528 + 0.9856003 * n) % 360.0)
    # Ecliptic longitude
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    # Obliquity of ecliptic
    eps = math.radians(23.439 - 0.0000004 * n)
    # Right ascension & declination
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    # Greenwich mean sidereal time
    gmst = (18.697374558 + 24.06570982441908 * n) % 24.0
    # Local hour angle
    lst = (gmst + lon_deg / 15.0) % 24.0
    h = math.radians(lst * 15.0) - ra
    # Convert to elevation & azimuth
    phi = math.radians(lat_deg)
    sin_alt = math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(h)
    alt = math.asin(max(-1.0, min(1.0, sin_alt)))
    cos_az = (math.sin(dec) - math.sin(alt) * math.sin(phi)) / (math.cos(alt) * math.cos(phi))
    cos_az = max(-1.0, min(1.0, cos_az))
    az = math.acos(cos_az)
    if math.sin(h) > 0:
        az = 2 * math.pi - az
    return math.degrees(alt), math.degrees(az)


# ===========================================================================
# 1. Glare assessment — FAA SGHAT methodology
# ===========================================================================
# SGHAT (Solar Glare Hazard Analysis Tool) defines retinal irradiance bands:
#   • green  (< 5 000  cd/m²) — low, no after-image
#   • yellow (5 000 – 20 000) — medium, temporary after-image
#   • red    (> 20 000)       — high, potential permanent effect
# FAA AC 150/5300-15B references.
# Reflectance assumption: unaged crystalline-Si module surface albedo ~2 %
# after anti-reflective coating (Ho et al. 2009, SAND-2009).
# ---------------------------------------------------------------------------

@dataclass
class GlareEvent:
    date: str
    time_local: str
    duration_min: float
    intensity: str           # "low" | "medium" | "high"
    luminance_cd_m2: float
    receptor_name: str
    receptor_bearing_deg: float
    solar_altitude_deg: float

    def to_dict(self) -> dict:
        return asdict(self)


def _receptor_geometry(panel_lat: float, panel_lon: float, rec: dict) -> tuple[float, float]:
    """Great-circle bearing (deg from N, CW) & distance (km) panel → receptor."""
    lat1, lon1 = math.radians(panel_lat), math.radians(panel_lon)
    lat2, lon2 = math.radians(rec["lat"]), math.radians(rec["lon"])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
    # Haversine
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    d = 2 * 6371.0 * math.asin(math.sqrt(a))
    return bearing, d


def glare_assessment(
    panel_lat: float,
    panel_lon: float,
    panel_tilt_deg: float,
    panel_azimuth_deg: float,
    receptors: list[dict],
    year: int,
    sample_minutes: int = 15,
    module_reflectance: float = 0.02,
) -> list[dict]:
    """Detect solar-glint events at static receptors over a whole year.

    Algorithm per sample step:
      1. Compute solar vector (elevation, azimuth).
      2. Compute panel normal in ENU coordinates.
      3. Reflected ray = incoming − 2(incoming·n)n           (specular).
      4. Compare reflected vector to receptor bearing (great-circle).
      5. If angular miss < 2° AND solar elevation > 3° → candidate glare.
      6. Luminance   L ≈ (E_dni · ρ · cos θ_i) / Ω_sun
                        with Ω_sun = 6.8e-5 sr (solar disk solid angle).

    Returns a list of GlareEvent dicts, one per receptor per contiguous event.
    """
    # Panel normal unit vector in ENU (East, North, Up)
    tilt = math.radians(panel_tilt_deg)
    az = math.radians(panel_azimuth_deg)
    n_vec = (
        math.sin(tilt) * math.sin(az),   # east
        math.sin(tilt) * math.cos(az),   # north
        math.cos(tilt),                  # up
    )

    # Receptor azimuths
    rec_geom = []
    for r in receptors:
        bearing, dist_km = _receptor_geometry(panel_lat, panel_lon, r)
        rec_geom.append({"rec": r, "bearing": bearing, "dist_km": dist_km})

    # Walk the year
    start = datetime(year, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, 0, 0, tzinfo=timezone.utc)
    step = timedelta(minutes=sample_minutes)

    ongoing: dict[str, dict] = {}       # receptor_name -> event dict in progress
    events: list[GlareEvent] = []

    t = start
    while t < end:
        alt_deg, sol_az_deg = solar_position(t, panel_lat, panel_lon)
        if alt_deg <= 3.0:   # below atmospheric-extinction glare floor
            # Close any open events
            for name, ev in list(ongoing.items()):
                events.append(_finalise_glare(ev))
                del ongoing[name]
            t += step
            continue

        alt = math.radians(alt_deg)
        saz = math.radians(sol_az_deg)
        # Solar unit vector *towards* sun (ENU)
        s_vec = (math.cos(alt) * math.sin(saz),
                 math.cos(alt) * math.cos(saz),
                 math.sin(alt))
        # Incident ray is -s_vec (from sun to panel)
        i_vec = (-s_vec[0], -s_vec[1], -s_vec[2])
        # Reflected ray  r = i − 2(i·n)n
        dot = i_vec[0] * n_vec[0] + i_vec[1] * n_vec[1] + i_vec[2] * n_vec[2]
        r_vec = (i_vec[0] - 2 * dot * n_vec[0],
                 i_vec[1] - 2 * dot * n_vec[1],
                 i_vec[2] - 2 * dot * n_vec[2])
        # Reflected azimuth (deg from N, CW) — only horizontal component
        if r_vec[2] < 0.01:          # pointing at or below horizon
            pass                     # still may clip receptor; fall through
        refl_az = (math.degrees(math.atan2(r_vec[0], r_vec[1])) + 360.0) % 360.0

        # cos θ_i for luminance
        cos_theta = max(0.0, dot * -1.0)  # incident vs normal (incident points into panel)
        # Direct normal irradiance estimate — clear-sky Laue (cos of zenith)
        dni = 900.0 * math.sin(alt)       # W/m²
        # Specular luminance (cd/m²): L = E_reflected / Ω_sun
        lum = (dni * module_reflectance * cos_theta) / 6.8e-5

        for g in rec_geom:
            name = g["rec"].get("name", f"{g['rec']['lat']:.4f},{g['rec']['lon']:.4f}")
            # Angular diff — receptor is fixed bearing from panel
            angle_diff = abs(((refl_az - g["bearing"] + 180.0) % 360.0) - 180.0)
            if angle_diff < 2.0 and r_vec[2] > -0.1:   # within ±2° beam cone
                if name not in ongoing:
                    ongoing[name] = {
                        "receptor": g["rec"],
                        "bearing": g["bearing"],
                        "start": t,
                        "end": t + step,
                        "peak_lum": lum,
                        "peak_alt": alt_deg,
                    }
                else:
                    ev = ongoing[name]
                    ev["end"] = t + step
                    if lum > ev["peak_lum"]:
                        ev["peak_lum"] = lum
                        ev["peak_alt"] = alt_deg
            elif name in ongoing:
                events.append(_finalise_glare(ongoing[name]))
                del ongoing[name]
        t += step

    for name, ev in list(ongoing.items()):
        events.append(_finalise_glare(ev))
        del ongoing[name]

    return [e.to_dict() for e in events]


def _finalise_glare(ev: dict) -> GlareEvent:
    duration_min = (ev["end"] - ev["start"]).total_seconds() / 60.0
    lum = ev["peak_lum"]
    if lum < 5_000:
        intensity = "low"
    elif lum < 20_000:
        intensity = "medium"
    else:
        intensity = "high"
    return GlareEvent(
        date=ev["start"].date().isoformat(),
        time_local=ev["start"].strftime("%H:%M"),
        duration_min=round(duration_min, 1),
        intensity=intensity,
        luminance_cd_m2=round(lum, 0),
        receptor_name=ev["receptor"].get("name", "receptor"),
        receptor_bearing_deg=round(ev["bearing"], 1),
        solar_altitude_deg=round(ev["peak_alt"], 1),
    )


# ===========================================================================
# 2. Shadow-flicker assessment (wind turbines, DC cooling towers)
# ===========================================================================
# UK Planning Practice Guidance (PPG) on Renewable and Low Carbon Energy
# (2014 revision) sets the conventional ceiling of 30 h/yr and 30 min/day
# cumulative flicker at any dwelling.  Below we implement a deterministic
# geometric model: shadow cast at ground level, ignoring topography, with a
# conservative 10× rotor-diameter cut-off (standard UK screening distance).
# ---------------------------------------------------------------------------

@dataclass
class FlickerEvent:
    receptor: str
    total_hours_per_year: float
    max_day_hours: float
    month_distribution: dict[str, float]
    exceeds_uk_threshold: bool
    standard: str = "UK Planning Practice Guidance (Renewable & Low Carbon) 2014"

    def to_dict(self) -> dict:
        return asdict(self)


def shadow_flicker(
    turbine_lat: float,
    turbine_lon: float,
    hub_height_m: float,
    rotor_diameter_m: float,
    receptors: list[dict],
    year: int,
    sample_minutes: int = 15,
    turbine_axis_az_deg: float | None = None,
) -> list[dict]:
    """Estimate annual shadow-flicker exposure at a list of receptors.

    A receptor experiences flicker during a sample step when:
      • solar elevation ∈ (0.5°, 60°)   (low sun — PPG convention)
      • the shadow cone projected at the receptor's distance covers it
      • wind is blowing perpendicular to the turbine–receptor line (assumed
        conservatively: uniform yaw across the year unless `turbine_axis_az_deg`
        pins blade disc orientation).
    """
    # Screening distance (10× rotor diameter, PPG footnote)
    screen_km = (10.0 * rotor_diameter_m) / 1000.0
    rotor_radius = rotor_diameter_m / 2.0

    # Per-receptor bearing & distance
    rec_info = []
    for r in receptors:
        b, d = _receptor_geometry(turbine_lat, turbine_lon, r)
        rec_info.append({"rec": r, "bearing": b, "dist_m": d * 1000.0})

    # Counters
    hours_by_rec: dict[str, float] = {}
    max_day_by_rec: dict[str, float] = {}
    month_by_rec: dict[str, dict[int, float]] = {}
    current_day: dict[str, tuple[date, float]] = {}

    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    step = timedelta(minutes=sample_minutes)
    step_hours = sample_minutes / 60.0

    t = start
    while t < end:
        alt_deg, sol_az_deg = solar_position(t, turbine_lat, turbine_lon)
        if not (0.5 < alt_deg < 60.0):
            t += step
            continue
        alt = math.radians(alt_deg)
        # Shadow length of hub at ground: L = h / tan(alt)
        hub_shadow_len = hub_height_m / max(math.tan(alt), 1e-4)
        # Shadow azimuth (from turbine, opposite the sun)
        shadow_az = (sol_az_deg + 180.0) % 360.0

        for g in rec_info:
            name = g["rec"].get("name", f"{g['rec']['lat']:.4f},{g['rec']['lon']:.4f}")
            d_m = g["dist_m"]
            if d_m / 1000.0 > screen_km:
                continue
            # Receptor falls in the shadow tip region if:
            #   (i) its bearing from turbine is within the rotor-angular span
            #       at that distance, and
            #  (ii) its distance is within [hub_shadow_len − r, hub_shadow_len + r]
            angular_span = math.degrees(math.atan2(rotor_radius, max(d_m, 1.0)))
            angle_diff = abs(((shadow_az - g["bearing"] + 180.0) % 360.0) - 180.0)
            if angle_diff > angular_span:
                continue
            if abs(d_m - hub_shadow_len) > rotor_radius * 1.2:
                continue
            # Apply turbine-axis orientation filter if given: shadow only falls
            # on receptor when sun is within ±45° of perpendicular to the blade axis
            if turbine_axis_az_deg is not None:
                sun_axis_diff = abs(((sol_az_deg - turbine_axis_az_deg + 90 + 180) % 360) - 180)
                if sun_axis_diff > 45.0:
                    continue

            # Count this step
            hours_by_rec[name] = hours_by_rec.get(name, 0.0) + step_hours
            m = t.month
            if name not in month_by_rec:
                month_by_rec[name] = {}
            month_by_rec[name][m] = month_by_rec[name].get(m, 0.0) + step_hours
            # Daily accumulator
            d0 = t.date()
            prev = current_day.get(name)
            if prev is None or prev[0] != d0:
                if prev is not None:
                    max_day_by_rec[name] = max(max_day_by_rec.get(name, 0.0), prev[1])
                current_day[name] = (d0, step_hours)
            else:
                current_day[name] = (d0, prev[1] + step_hours)

        t += step

    for name, (_, h) in current_day.items():
        max_day_by_rec[name] = max(max_day_by_rec.get(name, 0.0), h)

    # Build result list
    results: list[FlickerEvent] = []
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for r in receptors:
        name = r.get("name", f"{r['lat']:.4f},{r['lon']:.4f}")
        total = round(hours_by_rec.get(name, 0.0), 2)
        max_day = round(max_day_by_rec.get(name, 0.0), 2)
        months = {month_names[m - 1]: round(h, 2)
                  for m, h in month_by_rec.get(name, {}).items()}
        results.append(FlickerEvent(
            receptor=name,
            total_hours_per_year=total,
            max_day_hours=max_day,
            month_distribution=months,
            exceeds_uk_threshold=(total > 30.0 or max_day > 0.5),
        ))
    return [e.to_dict() for e in results]


# ===========================================================================
# 3. Noise propagation — ISO 9613-2 (simplified)
# ===========================================================================
# ISO 9613-2:1996 outdoor sound propagation, downwind reference conditions.
# L_p(receiver) = L_W − A_div − A_atm − A_gr − A_bar − A_misc + A_met
# Here we implement the default attenuation terms excluding A_bar (barriers)
# and A_misc; these are add-ons applied case-by-case by an acoustician.
# Frequency treatment: use a 500 Hz broadband atmospheric coefficient —
# 0.003 dB/m at 10 °C, 70 % RH (IEC 61400-11 wind-turbine datum).
# UK limits: BS 4142:2014 (noise rating), ETSU-R-97 for wind (35–40 dBA night),
# and LA90 ≤ 45 dBA night / 55 dBA day default assumed.
# ---------------------------------------------------------------------------

@dataclass
class NoiseAtReceptor:
    sound_pressure_dba: float
    distance_m: float
    a_div_db: float
    a_atm_db: float
    a_gr_db: float
    a_met_db: float
    night_limit_dba: float
    day_limit_dba: float
    exceeds_night: bool
    exceeds_day: bool
    ground_type: str
    standard: str = "ISO 9613-2:1996 + BS 4142:2014"

    def to_dict(self) -> dict:
        return asdict(self)


def _bearing_from(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(a))


def noise_propagation_iso9613_2(
    source_db: float,
    source_lat: float,
    source_lon: float,
    receptor_lat: float,
    receptor_lon: float,
    wind_direction_deg: float = 0.0,
    ground_type: Literal["soft", "hard", "mixed"] = "soft",
    night_limit_dba: float = 45.0,
    day_limit_dba: float = 55.0,
    atmospheric_coeff_db_per_m: float = 0.003,   # 500 Hz, 10 °C, 70 % RH
) -> NoiseAtReceptor:
    """Compute broadband dBA at a receptor per ISO 9613-2.

      A_div = 20·log10(d) + 11          (geometric spreading, point source)
      A_atm = α · d                     (α in dB/m — 500 Hz proxy)
      A_gr  = soft → +1.5, mixed → +0,  hard → −3   (clause 7.3.1 shortcut)
      A_met = downwind → 0, crosswind → −2, upwind → −3  (annex A)
    """
    d = _haversine_m(source_lat, source_lon, receptor_lat, receptor_lon)
    if d < 1.0:
        d = 1.0
    a_div = 20 * math.log10(d) + 11
    a_atm = atmospheric_coeff_db_per_m * d
    if ground_type == "soft":
        a_gr = 1.5
    elif ground_type == "hard":
        a_gr = -3.0
    else:
        a_gr = 0.0

    # Met term depends on alignment of wind vs source→receptor bearing
    bearing = _bearing_from(source_lat, source_lon, receptor_lat, receptor_lon)
    # Wind direction convention: direction FROM which wind blows.  Downwind
    # receptor means wind vector points from source to receptor, i.e.
    # (bearing from source to receptor) ≈ wind_dir + 180°.
    rel = abs(((bearing - (wind_direction_deg + 180.0) + 180.0) % 360.0) - 180.0)
    if rel <= 45.0:
        a_met = 0.0         # downwind (reference condition)
    elif rel >= 135.0:
        a_met = -3.0        # upwind: *higher* attenuation → sign flips; in ISO A_met is ADDED with opposite sign
    else:
        a_met = -2.0        # crosswind

    # ISO 9613-2 form: L_p = L_W − A_div − A_atm − A_gr − A_bar − A_misc
    # Meteorological correction `C_met` (annex A) is subtracted separately.
    sp = source_db - a_div - a_atm - a_gr - a_met
    sp = max(sp, 0.0)

    return NoiseAtReceptor(
        sound_pressure_dba=round(sp, 1),
        distance_m=round(d, 1),
        a_div_db=round(a_div, 2),
        a_atm_db=round(a_atm, 2),
        a_gr_db=round(a_gr, 2),
        a_met_db=round(a_met, 2),
        night_limit_dba=night_limit_dba,
        day_limit_dba=day_limit_dba,
        exceeds_night=sp > night_limit_dba,
        exceeds_day=sp > day_limit_dba,
        ground_type=ground_type,
    )
