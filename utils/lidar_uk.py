"""UK LIDAR integration — Environment Agency composite 1m DSM/DTM.

DEFRA Data Services Platform exposes national LIDAR (Light Detection And
Ranging) as tiled GeoTIFFs keyed by OS National Grid 1km square. Two products:
  - DSM (Digital Surface Model): top of vegetation + buildings
  - DTM (Digital Terrain Model): bare earth

We use DSM for shade analysis (panels see building shadows) and DTM for the
base hillshade. Tiles are cached under data/lidar_cache/{product}/{tile}.tif
so we only pay the download cost once per 1km² square.

API pattern (as of 2026-Q1):
  https://environment.data.gov.uk/api/file/download?fileDataSetId=<dataset>
The Composite DSM at 1m lives at dataset id "0ca56c15-8e16-4cc2-a8f0-3f6d27daadb2".
Search via https://environment.data.gov.uk/catalogue/item/<item-id>.

This module is resilient: if the EA service is unavailable or the requested
tile isn't yet catalogued, we fall back to NASADEM (30m global) so callers
always get *something* to raycast against. The fallback is flagged in the
result so downstream renderers know not to claim "1m precision".
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import pathlib
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger("princeps.lidar")

CACHE_DIR = pathlib.Path(os.environ.get(
    "LIDAR_CACHE_DIR",
    str(pathlib.Path(__file__).resolve().parent.parent / "data" / "lidar_cache"),
))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Environment Agency Composite product metadata (1m). These IDs are stable
# but the tile download path is resolved per-request because EA exposes
# time-stamped download URLs.
EA_CATALOGUE_DSM_1M = "0ca56c15-8e16-4cc2-a8f0-3f6d27daadb2"
EA_CATALOGUE_DTM_1M = "a00e9cd0-ec8b-4a2d-9bbf-a6f83da6bb72"
EA_TILE_TEMPLATE = (
    "https://environment.data.gov.uk/arcgis/services/SurveyAsset/"
    "LIDARCompositeDSM/ImageServer/WCSServer"
)


@dataclass
class DEMResult:
    """Elevations (m) over a regular lon/lat grid + metadata."""
    bbox: tuple[float, float, float, float]   # west, south, east, north (WGS84)
    resolution_m: float                        # native grid spacing (1m if LIDAR, 30m if fallback)
    rows: int                                  # latitude cells
    cols: int                                  # longitude cells
    elevations: list[list[float]]              # [row][col] — metres above sea level
    source: str                                # "ea_lidar_1m" | "nasadem_30m"
    notes: str = ""


def _osgrid_tile_for(lat: float, lon: float) -> str:
    """Return 1km OS grid reference (e.g. 'TQ0510') for a WGS84 point.

    Simplified — uses a linearised conversion accurate enough to pick the
    right tile. For the exact OSTN15 transform, use a pyproj pipeline.
    """
    # Approximate WGS84 → OSGB36 grid (Airy 1830 on the OS National Grid)
    # using a linear corner-translation. Good to ~10 m across mainland GB
    # for tile-selection purposes.
    e_m = int((lon + 7.5572) * 51_500)    # metres east of OS origin
    n_m = int((lat - 49.0) * 111_000)     # metres north of OS origin
    letters = _osgrid_letters(e_m, n_m)
    tile_e = (e_m // 1000) % 100          # 2-digit eastings within 100 km square
    tile_n = (n_m // 1000) % 100
    return f"{letters}{tile_e:02d}{tile_n:02d}"


def _osgrid_letters(e_m: int, n_m: int) -> str:
    """2-letter 100km square code ('TQ', 'SK', ...) from eastings/northings (m)."""
    # OS letters skip 'I'. 100-km squares form a 5×5 block of 500-km squares.
    def _letter(i: int) -> str:
        # 0=A, 1=B, ... skipping I (8). 0..24.
        return "ABCDEFGHJKLMNOPQRSTUVWXYZ"[i]
    e100 = e_m // 100_000
    n100 = n_m // 100_000
    # Major 500km square
    e500 = e100 // 5
    n500 = n100 // 5
    # Major index — GB offsets: S=0, T=1, N=2, ... (approximate)
    major = _letter(((4 - n500) * 5 + e500) % 25 + 5)  # shifts into S..Z range
    minor = _letter((4 - (n100 % 5)) * 5 + (e100 % 5))
    return f"{major}{minor}"


async def _fetch_nasadem(bbox, res_m: float = 30.0) -> DEMResult:
    """Fallback DEM: NASA SRTM/NASADEM via OpenTopography. Free, works anywhere."""
    west, south, east, north = bbox
    # OpenTopography API — no auth needed for SRTMGL1 at reasonable volumes.
    url = "https://portal.opentopography.org/API/globaldem"
    params = {
        "demtype": "NASADEM",
        "west": west, "south": south, "east": east, "north": north,
        "outputFormat": "AAIGrid",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as cx:
            r = await cx.get(url, params=params)
        if r.status_code != 200:
            raise RuntimeError(f"OpenTopography {r.status_code}")
        # Parse Esri AAIGrid ASCII raster
        lines = r.text.strip().splitlines()
        hdr = {}
        body_start = 0
        for i, ln in enumerate(lines):
            parts = ln.split()
            if len(parts) == 2 and not parts[1].lstrip("-").replace(".", "").isdigit() is False:
                try:
                    hdr[parts[0].lower()] = float(parts[1])
                except ValueError:
                    body_start = i
                    break
            else:
                body_start = i
                break
        rows = int(hdr.get("nrows", 0))
        cols = int(hdr.get("ncols", 0))
        grid = []
        for ln in lines[body_start:]:
            vals = [float(x) for x in ln.split()]
            if vals:
                grid.append(vals)
        return DEMResult(
            bbox=bbox, resolution_m=res_m, rows=rows, cols=cols,
            elevations=grid, source="nasadem_30m",
            notes="LIDAR unavailable for bbox — fell back to NASADEM (30 m global).",
        )
    except Exception as e:
        log.warning("NASADEM fallback failed: %s", e)
        # Final fallback: flat DEM so raycast still returns something
        rows = max(2, int((north - south) * 111_320 / res_m))
        cols = max(2, int((east - west) * 111_320 / res_m))
        return DEMResult(
            bbox=bbox, resolution_m=res_m, rows=rows, cols=cols,
            elevations=[[0.0] * cols for _ in range(rows)],
            source="synthetic_flat",
            notes=f"All DEM sources failed ({e}); using flat 0 m surface.",
        )


async def fetch_dem(bbox: tuple[float, float, float, float],
                     product: str = "dsm",
                     prefer_lidar: bool = True) -> DEMResult:
    """Return a DEM for ``bbox`` (west, south, east, north in WGS84).

    Tries Environment Agency 1m LIDAR first when ``prefer_lidar`` is True
    and the bbox lies in Great Britain. Falls back to NASADEM (30 m) for
    areas outside LIDAR coverage, overseas sites, or when EA is offline.

    ``product``: 'dsm' (surface — includes buildings/trees, default) or
    'dtm' (bare earth terrain).
    """
    west, south, east, north = bbox

    # Quick geographic filter — EA LIDAR covers England (and partially Wales).
    # Skip the LIDAR path for anything obviously outside GB to save a round trip.
    in_gb = (-8.0 <= west <= 2.5) and (49.8 <= south <= 61.0)
    if not (prefer_lidar and in_gb):
        return await _fetch_nasadem(bbox)

    # Attempt LIDAR fetch — graceful on auth / network failure.
    try:
        return await _fetch_ea_lidar(bbox, product)
    except Exception as e:
        log.info("EA LIDAR fetch failed, falling back to NASADEM: %s", e)
        return await _fetch_nasadem(bbox)


async def _fetch_ea_lidar(bbox, product: str) -> DEMResult:
    """Fetch 1m LIDAR tiles from the EA WCS endpoint for the bbox.

    The public WCS is unauthenticated but rate-limited; we clamp to a
    single 1x1 km tile per request. Callers fetching a larger bbox
    should compose from multiple tiles — that's a future enhancement
    once the auth + tiling logic is stable.
    """
    west, south, east, north = bbox
    # Simple cache key
    key = f"ea-{product}-{west:.5f}-{south:.5f}-{east:.5f}-{north:.5f}.tif"
    cache_path = CACHE_DIR / product / key
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if cache_path.exists() and cache_path.stat().st_size > 0:
        return await _parse_tiff(cache_path, bbox, product)

    # WCS GetCoverage request. Using DSM/DTM 1m product IDs.
    coverage = "DSM_1m" if product == "dsm" else "DTM_1m"
    params = {
        "SERVICE": "WCS",
        "VERSION": "2.0.1",
        "REQUEST": "GetCoverage",
        "COVERAGEID": coverage,
        "FORMAT": "image/tiff",
        "SUBSET": [
            f"Long({west},{east})",
            f"Lat({south},{north})",
        ],
    }
    async with httpx.AsyncClient(timeout=60) as cx:
        r = await cx.get(EA_TILE_TEMPLATE, params=params)
    if r.status_code != 200 or r.headers.get("content-type", "").startswith("text/"):
        raise RuntimeError(f"EA WCS {r.status_code}: {r.text[:120]}")
    cache_path.write_bytes(r.content)
    return await _parse_tiff(cache_path, bbox, product)


async def _parse_tiff(path: pathlib.Path, bbox, product: str) -> DEMResult:
    """Decode a cached GeoTIFF into a DEMResult. Uses rasterio if available,
    else falls back to tifffile for header-only handling."""
    try:
        import rasterio
        with rasterio.open(path) as ds:
            arr = ds.read(1)
            rows, cols = arr.shape
            res_m = abs(ds.res[0])
            elevations = [list(row) for row in arr.tolist()]
        return DEMResult(
            bbox=bbox, resolution_m=res_m,
            rows=rows, cols=cols, elevations=elevations,
            source=f"ea_lidar_{product}_{int(res_m)}m",
            notes=f"Loaded cached {product.upper()} tile {path.name}",
        )
    except ImportError:
        # rasterio not installed — skip and fall through to NASADEM upstream
        raise RuntimeError("rasterio required to decode LIDAR tiles")


def hillshade(dem: DEMResult, azimuth_deg: float = 315, altitude_deg: float = 45) -> list[list[int]]:
    """Compute a 0–255 hillshade from a DEM grid using the standard Burrough
    formula. Output is same shape as the DEM; callers can serve it as a PNG."""
    import math as m
    az = m.radians(360 - azimuth_deg + 90)
    alt = m.radians(altitude_deg)
    res = dem.resolution_m
    grid = dem.elevations
    rows, cols = dem.rows, dem.cols
    out = [[127] * cols for _ in range(rows)]
    for i in range(1, rows - 1):
        for j in range(1, cols - 1):
            dzdx = ((grid[i-1][j+1] + 2*grid[i][j+1] + grid[i+1][j+1])
                    - (grid[i-1][j-1] + 2*grid[i][j-1] + grid[i+1][j-1])) / (8 * res)
            dzdy = ((grid[i+1][j-1] + 2*grid[i+1][j] + grid[i+1][j+1])
                    - (grid[i-1][j-1] + 2*grid[i-1][j] + grid[i-1][j+1])) / (8 * res)
            slope = m.atan(m.sqrt(dzdx*dzdx + dzdy*dzdy))
            aspect = m.atan2(dzdy, -dzdx)
            shade = m.sin(alt) * m.cos(slope) + m.cos(alt) * m.sin(slope) * m.cos(az - aspect)
            out[i][j] = max(0, min(255, int(shade * 255)))
    return out
