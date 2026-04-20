"""
OSGB conversion utility.

Converts between WGS84 (EPSG:4326) geographic coordinates and the British
National Grid (EPSG:27700), and formats/parses Ordnance Survey alphanumeric
grid references ("SK 2350 1480" etc.).

Primary implementation uses pyproj (installed in the Princeps `.venv/`). A
pure-Python fallback using the OS-published Helmert 7-parameter transform
plus Airy-1830 inverse (as described in OS "Guide to coordinate systems in
Great Britain" Annex B/C) is provided so this module stays usable when
pyproj is missing.

Public API
----------
    to_osgb(lat, lon)                 -> (easting, northing)        # metres
    to_grid_ref(lat, lon, precision)  -> "SK 2350 1480"             # precision 2/4/6/8/10
    from_grid_ref(gridref)            -> (lat, lon)                 # WGS84 decimal degrees

Precision reference
-------------------
    2-fig  -> 10 km    e.g. "SK 21"
    4-fig  -> 1 km     e.g. "SK 23 14"
    6-fig  -> 100 m    e.g. "SK 235 148"
    8-fig  -> 10 m     e.g. "SK 2350 1480"
    10-fig -> 1 m      e.g. "SK 23500 14800"
"""

from __future__ import annotations

import math
import re
from typing import Tuple


# ---------------------------------------------------------------------------
# pyproj backend (preferred)
# ---------------------------------------------------------------------------

try:  # pragma: no cover - exercised implicitly by to_osgb/from_grid_ref
    from pyproj import Transformer

    _TO_27700 = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
    _TO_4326 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    _HAS_PYPROJ = True
except Exception:  # pragma: no cover - fallback path
    _TO_27700 = None
    _TO_4326 = None
    _HAS_PYPROJ = False


# ---------------------------------------------------------------------------
# OS 100-km grid lettering
# ---------------------------------------------------------------------------
#
# The 2-letter prefix encodes the 100 km square. The first letter selects one
# of 25 x 25 = 625 squares (500 km blocks offset from the false origin); the
# second letter refines to 100 km. "I" is skipped in both letters.

_LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"  # 25 letters, no I


def _eastings_northings_to_letters(easting: float, northing: float) -> Tuple[str, float, float]:
    """Return ``(two_letter_prefix, e_within_100k, n_within_100k)``.

    Raises ValueError if the point is off the OSGB lettered grid.
    """
    # Shift to the false origin of the OS lettered grid (SV is at -1000000, -500000
    # relative to the true OSGB false origin).
    e = easting + 1_000_000
    n = northing + 500_000

    if e < 0 or n < 0 or e >= 2_500_000 or n >= 2_500_000:
        raise ValueError(
            f"Point E={easting:.0f}, N={northing:.0f} is outside the OSGB lettered grid"
        )

    first_idx = (4 - int(n // 500_000)) * 5 + int(e // 500_000)
    e %= 500_000
    n %= 500_000
    second_idx = (4 - int(n // 100_000)) * 5 + int(e // 100_000)

    prefix = _LETTERS[first_idx] + _LETTERS[second_idx]
    e_rem = e % 100_000
    n_rem = n % 100_000
    return prefix, e_rem, n_rem


def _letters_to_eastings_northings(prefix: str) -> Tuple[int, int]:
    """Inverse of :func:`_eastings_northings_to_letters` — return the SW corner
    eastings/northings of the 100 km square in true OSGB coordinates."""
    prefix = prefix.upper()
    if len(prefix) != 2 or any(c not in _LETTERS for c in prefix):
        raise ValueError(f"Invalid OS grid prefix: {prefix!r}")

    first = _LETTERS.index(prefix[0])
    second = _LETTERS.index(prefix[1])

    # Undo the quincunx: row 0 is the northernmost.
    e = (first % 5) * 500_000 + (second % 5) * 100_000
    n = (4 - first // 5) * 500_000 + (4 - second // 5) * 100_000

    # Remove the 1000/500 km false-origin offset.
    return e - 1_000_000, n - 500_000


# ---------------------------------------------------------------------------
# Public API: WGS84 <-> OSGB metres
# ---------------------------------------------------------------------------


def to_osgb(lat: float, lon: float) -> Tuple[float, float]:
    """Convert WGS84 lat/lon (decimal degrees) to OSGB EPSG:27700 easting/northing in metres."""
    if _HAS_PYPROJ:
        e, n = _TO_27700.transform(lon, lat)  # type: ignore[union-attr]
        return float(e), float(n)
    return _wgs84_to_osgb_pure(lat, lon)


def to_wgs84(easting: float, northing: float) -> Tuple[float, float]:
    """Convert OSGB EPSG:27700 easting/northing (metres) to WGS84 (lat, lon) decimal degrees."""
    if _HAS_PYPROJ:
        lon, lat = _TO_4326.transform(easting, northing)  # type: ignore[union-attr]
        return float(lat), float(lon)
    return _osgb_to_wgs84_pure(easting, northing)


# ---------------------------------------------------------------------------
# Public API: grid reference strings
# ---------------------------------------------------------------------------


_ALLOWED_PRECISION = {2, 4, 6, 8, 10}


def to_grid_ref(lat: float, lon: float, precision: int = 6) -> str:
    """Return an OS grid reference like ``"SK 2350 1480"`` for the given WGS84 point.

    Parameters
    ----------
    lat, lon   : WGS84 decimal degrees
    precision  : total number of digits (2, 4, 6, 8 or 10).

    Returns
    -------
    Formatted grid reference (2-letter prefix + space + easting digits +
    space + northing digits). If the point falls outside the OSGB lettered
    grid the function falls back to a decimal lat/lon string so callers
    always get something legible.
    """
    if precision not in _ALLOWED_PRECISION:
        raise ValueError(
            f"precision must be one of {sorted(_ALLOWED_PRECISION)}, got {precision}"
        )

    try:
        e, n = to_osgb(lat, lon)
        prefix, e_rem, n_rem = _eastings_northings_to_letters(e, n)
    except ValueError:
        # Outside lettered grid (e.g. offshore, Channel Islands, non-GB data).
        hemi_ns = "N" if lat >= 0 else "S"
        hemi_ew = "E" if lon >= 0 else "W"
        return f"{abs(lat):.4f}{hemi_ns}, {abs(lon):.4f}{hemi_ew}"

    digits = precision // 2
    divisor = 10 ** (5 - digits)  # 5 digits resolves to 1 m

    e_str = f"{int(e_rem // divisor):0{digits}d}"
    n_str = f"{int(n_rem // divisor):0{digits}d}"
    return f"{prefix} {e_str} {n_str}"


_GRIDREF_RE = re.compile(
    r"^\s*([A-Za-z]{2})\s*([0-9]+)\s*([0-9]+)\s*$"
)


def from_grid_ref(gridref: str) -> Tuple[float, float]:
    """Parse a grid reference (e.g. ``"SK 2350 1480"`` or ``"SK23501480"``) and
    return the WGS84 (lat, lon) of the SW corner of that square.

    Accepts precisions 2/4/6/8/10. Whitespace between the two number groups
    is optional — a solid block of digits is split in half.
    """
    if not isinstance(gridref, str):
        raise ValueError(f"grid reference must be a string, got {type(gridref).__name__}")

    m = _GRIDREF_RE.match(gridref)
    if not m:
        # Try the "SK12345678" form (no space between easting/northing).
        compact = re.match(r"^\s*([A-Za-z]{2})\s*([0-9]+)\s*$", gridref)
        if not compact:
            raise ValueError(f"Unrecognised OS grid reference: {gridref!r}")
        prefix = compact.group(1)
        digits = compact.group(2)
        if len(digits) % 2 != 0 or len(digits) // 2 not in {1, 2, 3, 4, 5}:
            raise ValueError(f"Invalid digit count in grid reference: {gridref!r}")
        half = len(digits) // 2
        e_str, n_str = digits[:half], digits[half:]
    else:
        prefix, e_str, n_str = m.group(1), m.group(2), m.group(3)

    if len(e_str) != len(n_str):
        raise ValueError(
            f"Easting and northing digit counts must match in {gridref!r}"
        )
    digits = len(e_str)
    if digits not in {1, 2, 3, 4, 5}:
        raise ValueError(f"Unsupported precision in {gridref!r}")

    multiplier = 10 ** (5 - digits)
    sw_e, sw_n = _letters_to_eastings_northings(prefix)
    e = sw_e + int(e_str) * multiplier
    n = sw_n + int(n_str) * multiplier

    return to_wgs84(e, n)


# ---------------------------------------------------------------------------
# Pure-Python OSGB conversion (fallback when pyproj is unavailable)
# ---------------------------------------------------------------------------
#
# References: OS "A Guide to coordinate systems in Great Britain", Annex B
# (Helmert transformation WGS84 -> OSGB36) and Annex C (transverse Mercator
# projection of OSGB36 latitude/longitude onto the National Grid using the
# Airy 1830 spheroid).

# Airy 1830 (used by OSGB36)
_AIRY_A = 6377563.396
_AIRY_B = 6356256.909
# GRS80 (WGS84 is effectively identical for this purpose)
_GRS80_A = 6378137.000
_GRS80_B = 6356752.3141

# National Grid projection parameters
_NG_F0 = 0.9996012717
_NG_LAT0 = math.radians(49.0)
_NG_LON0 = math.radians(-2.0)
_NG_E0 = 400_000.0
_NG_N0 = -100_000.0

# Helmert parameters: WGS84 -> OSGB36 (OS published, metres/ppm/seconds)
_H_TX = -446.448
_H_TY = +125.157
_H_TZ = -542.060
_H_S = 20.4894e-6  # scale factor
_H_RX = math.radians(-0.1502 / 3600.0)
_H_RY = math.radians(-0.2470 / 3600.0)
_H_RZ = math.radians(-0.8421 / 3600.0)


def _ecc_sq(a: float, b: float) -> float:
    return (a * a - b * b) / (a * a)


def _latlon_to_cartesian(lat: float, lon: float, a: float, b: float, h: float = 0.0) -> Tuple[float, float, float]:
    e2 = _ecc_sq(a, b)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    nu = a / math.sqrt(1 - e2 * sin_lat * sin_lat)
    x = (nu + h) * cos_lat * math.cos(lon)
    y = (nu + h) * cos_lat * math.sin(lon)
    z = ((1 - e2) * nu + h) * sin_lat
    return x, y, z


def _cartesian_to_latlon(x: float, y: float, z: float, a: float, b: float) -> Tuple[float, float, float]:
    e2 = _ecc_sq(a, b)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(10):
        sin_lat = math.sin(lat)
        nu = a / math.sqrt(1 - e2 * sin_lat * sin_lat)
        lat_new = math.atan2(z + e2 * nu * sin_lat, p)
        if abs(lat_new - lat) < 1e-12:
            lat = lat_new
            break
        lat = lat_new
    sin_lat = math.sin(lat)
    nu = a / math.sqrt(1 - e2 * sin_lat * sin_lat)
    h = p / math.cos(lat) - nu
    return lat, lon, h


def _helmert(x: float, y: float, z: float, tx: float, ty: float, tz: float,
             s: float, rx: float, ry: float, rz: float) -> Tuple[float, float, float]:
    x2 = tx + (1 + s) * x + (-rz) * y + ry * z
    y2 = ty + rz * x + (1 + s) * y + (-rx) * z
    z2 = tz + (-ry) * x + rx * y + (1 + s) * z
    return x2, y2, z2


def _wgs84_to_osgb_pure(lat_deg: float, lon_deg: float) -> Tuple[float, float]:
    """WGS84 (degrees) -> OSGB36 National Grid easting/northing (metres)."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)

    # 1. WGS84 geodetic -> WGS84 cartesian
    x, y, z = _latlon_to_cartesian(lat, lon, _GRS80_A, _GRS80_B)
    # 2. Helmert -> OSGB36 cartesian
    x, y, z = _helmert(x, y, z, _H_TX, _H_TY, _H_TZ, _H_S, _H_RX, _H_RY, _H_RZ)
    # 3. OSGB36 cartesian -> OSGB36 geodetic (Airy 1830)
    lat, lon, _ = _cartesian_to_latlon(x, y, z, _AIRY_A, _AIRY_B)
    # 4. OSGB36 geodetic -> National Grid TM projection
    return _latlon_to_ng(lat, lon)


def _osgb_to_wgs84_pure(easting: float, northing: float) -> Tuple[float, float]:
    """OSGB36 easting/northing (metres) -> WGS84 (lat, lon) degrees."""
    lat, lon = _ng_to_latlon(easting, northing)
    x, y, z = _latlon_to_cartesian(lat, lon, _AIRY_A, _AIRY_B)
    # Inverse Helmert (negate params is an acceptable first-order inverse for this precision).
    x, y, z = _helmert(x, y, z, -_H_TX, -_H_TY, -_H_TZ, -_H_S, -_H_RX, -_H_RY, -_H_RZ)
    lat, lon, _ = _cartesian_to_latlon(x, y, z, _GRS80_A, _GRS80_B)
    return math.degrees(lat), math.degrees(lon)


def _meridional_arc(a: float, b: float, lat: float) -> float:
    n = (a - b) / (a + b)
    n2 = n * n
    n3 = n2 * n
    dl = lat - _NG_LAT0
    sl = lat + _NG_LAT0
    return b * _NG_F0 * (
        (1 + n + 5 / 4 * n2 + 5 / 4 * n3) * dl
        - (3 * n + 3 * n2 + 21 / 8 * n3) * math.sin(dl) * math.cos(sl)
        + (15 / 8 * n2 + 15 / 8 * n3) * math.sin(2 * dl) * math.cos(2 * sl)
        - (35 / 24 * n3) * math.sin(3 * dl) * math.cos(3 * sl)
    )


def _latlon_to_ng(lat: float, lon: float) -> Tuple[float, float]:
    a, b = _AIRY_A, _AIRY_B
    e2 = _ecc_sq(a, b)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    tan_lat = math.tan(lat)

    nu = a * _NG_F0 / math.sqrt(1 - e2 * sin_lat * sin_lat)
    rho = a * _NG_F0 * (1 - e2) / (1 - e2 * sin_lat * sin_lat) ** 1.5
    eta2 = nu / rho - 1

    m = _meridional_arc(a, b, lat)

    cos3 = cos_lat ** 3
    cos5 = cos_lat ** 5
    tan2 = tan_lat ** 2
    tan4 = tan_lat ** 4

    I = m + _NG_N0
    II = (nu / 2) * sin_lat * cos_lat
    III = (nu / 24) * sin_lat * cos3 * (5 - tan2 + 9 * eta2)
    IIIA = (nu / 720) * sin_lat * cos5 * (61 - 58 * tan2 + tan4)
    IV = nu * cos_lat
    V = (nu / 6) * cos3 * (nu / rho - tan2)
    VI = (nu / 120) * cos5 * (5 - 18 * tan2 + tan4 + 14 * eta2 - 58 * tan2 * eta2)

    dlon = lon - _NG_LON0
    dlon2 = dlon * dlon
    northing = I + II * dlon2 + III * dlon2 ** 2 + IIIA * dlon2 ** 3
    easting = _NG_E0 + IV * dlon + V * dlon ** 3 + VI * dlon ** 5
    return easting, northing


def _ng_to_latlon(easting: float, northing: float) -> Tuple[float, float]:
    a, b = _AIRY_A, _AIRY_B
    e2 = _ecc_sq(a, b)

    lat = _NG_LAT0
    m = 0.0
    while True:
        lat = (northing - _NG_N0 - m) / (a * _NG_F0) + lat
        m = _meridional_arc(a, b, lat)
        if abs(northing - _NG_N0 - m) < 1e-5:
            break

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    tan_lat = math.tan(lat)

    nu = a * _NG_F0 / math.sqrt(1 - e2 * sin_lat * sin_lat)
    rho = a * _NG_F0 * (1 - e2) / (1 - e2 * sin_lat * sin_lat) ** 1.5
    eta2 = nu / rho - 1

    tan2 = tan_lat ** 2
    tan4 = tan_lat ** 4
    tan6 = tan_lat ** 6

    VII = tan_lat / (2 * rho * nu)
    VIII = tan_lat / (24 * rho * nu ** 3) * (5 + 3 * tan2 + eta2 - 9 * tan2 * eta2)
    IX = tan_lat / (720 * rho * nu ** 5) * (61 + 90 * tan2 + 45 * tan4)
    X = 1 / (cos_lat * nu)
    XI = 1 / (cos_lat * 6 * nu ** 3) * (nu / rho + 2 * tan2)
    XII = 1 / (cos_lat * 120 * nu ** 5) * (5 + 28 * tan2 + 24 * tan4)
    XIIA = 1 / (cos_lat * 5040 * nu ** 7) * (61 + 662 * tan2 + 1320 * tan4 + 720 * tan6)

    de = easting - _NG_E0
    de2 = de * de

    lat_out = lat - VII * de2 + VIII * de2 ** 2 - IX * de2 ** 3
    lon_out = _NG_LON0 + X * de - XI * de ** 3 + XII * de ** 5 - XIIA * de ** 7
    return lat_out, lon_out


# ---------------------------------------------------------------------------
# Round-trip self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Canary Wharf, London. Expected ~TQ 379 800 at 6-fig precision
    # (OS grid easting ~538000, northing ~180000).
    lat, lon = 51.5054, -0.0235
    e, n = to_osgb(lat, lon)
    print(f"Canary Wharf WGS84 ({lat}, {lon})")
    print(f"  -> OSGB metres (E, N)   = ({e:.2f}, {n:.2f})")
    for p in (2, 4, 6, 8, 10):
        print(f"  -> {p:2d}-fig grid ref       = {to_grid_ref(lat, lon, p)}")

    gridref_6 = to_grid_ref(lat, lon, 6)
    lat_back, lon_back = from_grid_ref(gridref_6)
    print(f"  round-trip from {gridref_6!r} = ({lat_back:.5f}, {lon_back:.5f})")

    # Additional sanity check: Ordnance Survey HQ, Southampton (SU 387 148)
    os_hq_lat, os_hq_lon = 50.93872, -1.47127
    print(
        f"OS HQ Southampton ({os_hq_lat}, {os_hq_lon}) -> "
        f"{to_grid_ref(os_hq_lat, os_hq_lon, 6)}"
    )

    # Ben Nevis summit (NN 166 712)
    ben_lat, ben_lon = 56.796849, -5.003508
    print(
        f"Ben Nevis       ({ben_lat}, {ben_lon}) -> "
        f"{to_grid_ref(ben_lat, ben_lon, 6)}"
    )

    print(f"backend: {'pyproj' if _HAS_PYPROJ else 'pure-python'}")
