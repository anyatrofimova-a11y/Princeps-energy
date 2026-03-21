"""Terrain analysis endpoints — LiDAR, viewshed/ZTV, hydrology."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

log = logging.getLogger("princeps.terrain")
router = APIRouter(prefix="/api/terrain", tags=["terrain"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class TerrainRequest(BaseModel):
    lat: float
    lon: float
    radius_m: float = 500
    resolution_m: float = 2


class ViewshedRequest(BaseModel):
    lat: float
    lon: float
    target_height_m: float = 3.0
    radius_m: float = 2000
    observer_height_m: float = 1.6


class HydrologyRequest(BaseModel):
    lat: float
    lon: float
    radius_m: float = 500


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/lidar")
async def lidar_terrain(req: TerrainRequest):
    """Fetch EA LiDAR 1m terrain data for a site.

    Returns high-resolution heightmap, elevation statistics,
    slope/aspect analysis. Falls back to NASADEM 30m outside England.
    """
    from utils.lidar_terrain import fetch_lidar_terrain

    result = await fetch_lidar_terrain(
        req.lat, req.lon,
        radius_m=req.radius_m,
        resolution_m=req.resolution_m,
    )
    return result


@router.post("/analyse")
async def terrain_analysis(req: TerrainRequest):
    """Full terrain suitability assessment for energy development.

    Includes slope classification, aspect suitability, flatness score,
    cut/fill estimation, and surface roughness for wind assessment.
    """
    from utils.lidar_terrain import analyse_terrain

    result = await analyse_terrain(
        req.lat, req.lon,
        radius_m=req.radius_m,
    )
    return result


@router.post("/viewshed")
async def viewshed(req: ViewshedRequest):
    """Calculate Zone of Theoretical Visibility (ZTV).

    Standard UK planning methodology. Uses WhiteboxTools if installed,
    otherwise falls back to numpy ray-casting.

    Returns visible area percentage, GeoJSON polygon for map overlay,
    visual impact classification, and receptor count estimate.
    """
    from utils.viewshed_analyser import calculate_viewshed

    result = await calculate_viewshed(
        req.lat, req.lon,
        target_height_m=req.target_height_m,
        radius_m=req.radius_m,
        observer_height_m=req.observer_height_m,
    )
    return result


@router.post("/hydrology")
async def hydrology(req: HydrologyRequest):
    """Hydrological analysis — TWI, drainage, waterlogging risk.

    Computes Topographic Wetness Index, flow accumulation,
    depression detection, and drainage path GeoJSON.
    """
    from utils.viewshed_analyser import calculate_hydrology

    result = await calculate_hydrology(
        req.lat, req.lon,
        radius_m=req.radius_m,
    )
    return result
