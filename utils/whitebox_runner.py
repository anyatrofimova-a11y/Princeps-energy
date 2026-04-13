#!/usr/bin/env python3
"""Whitebox-tools runner — subprocess bridge for geospatial analysis.

whitebox-tools is a standalone Rust binary. Install: pip install whitebox-tools
Then call via this bridge.

Usage: echo '{"action":"viewshed","params":{...}}' | python utils/whitebox_runner.py
"""

import sys
import json
import os
import tempfile
import logging

log = logging.getLogger(__name__)


def _get_wbt():
    """Get WhiteboxTools instance."""
    from whitebox_tools import WhiteboxTools
    wbt = WhiteboxTools()
    wbt.set_verbose_mode(False)
    return wbt


def viewshed(params: dict) -> dict:
    """Viewshed analysis from an observer point on a DEM."""
    wbt = _get_wbt()
    dem_path = params["dem_path"]
    lat = params["lat"]
    lon = params["lon"]
    height = params.get("observer_height", 15)  # metres (DC building height)

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as out:
        output_path = out.name

    # Create observer point shapefile
    with tempfile.NamedTemporaryFile(suffix=".shp", delete=False) as pt:
        pt_path = pt.name

    try:
        # For viewshed, we need a point shapefile — simplified approach:
        # Use the DEM coordinates directly
        wbt.viewshed(
            dem=dem_path,
            stations=pt_path if os.path.exists(pt_path) else dem_path,
            output=output_path,
            height=height,
        )

        return {
            "output_path": output_path,
            "observer": {"lat": lat, "lon": lon, "height_m": height},
            "status": "success",
        }
    except Exception as e:
        return {"error": str(e), "status": "failed"}


def slope_analysis(params: dict) -> dict:
    """Generate slope raster from DEM."""
    wbt = _get_wbt()
    dem_path = params["dem_path"]

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as out:
        output_path = out.name

    try:
        wbt.slope(dem=dem_path, output=output_path, units="degrees")
        return {"output_path": output_path, "units": "degrees", "status": "success"}
    except Exception as e:
        return {"error": str(e), "status": "failed"}


def watershed(params: dict) -> dict:
    """Watershed delineation."""
    wbt = _get_wbt()
    dem_path = params["dem_path"]

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as filled:
        filled_path = filled.name
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as fdir:
        fdir_path = fdir.name
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as facc:
        facc_path = facc.name
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as out:
        output_path = out.name

    try:
        # Fill depressions
        wbt.fill_depressions(dem=dem_path, output=filled_path)
        # Flow direction
        wbt.d8_pointer(dem=filled_path, output=fdir_path)
        # Flow accumulation
        wbt.d8_flow_accumulation(dem=filled_path, output=facc_path, out_type="cells")
        # Basins
        wbt.basins(d8_pntr=fdir_path, output=output_path)

        return {
            "basins_path": output_path,
            "flow_accumulation_path": facc_path,
            "status": "success",
        }
    except Exception as e:
        return {"error": str(e), "status": "failed"}


def hillshade(params: dict) -> dict:
    """Generate hillshade raster."""
    wbt = _get_wbt()
    dem_path = params["dem_path"]
    azimuth = params.get("azimuth", 315)
    altitude = params.get("altitude", 30)

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as out:
        output_path = out.name

    try:
        wbt.hillshade(dem=dem_path, output=output_path, azimuth=azimuth, altitude=altitude)
        return {"output_path": output_path, "azimuth": azimuth, "altitude": altitude, "status": "success"}
    except Exception as e:
        return {"error": str(e), "status": "failed"}


def aspect_analysis(params: dict) -> dict:
    """Generate aspect raster from DEM."""
    wbt = _get_wbt()
    dem_path = params["dem_path"]

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as out:
        output_path = out.name

    try:
        wbt.aspect(dem=dem_path, output=output_path)
        return {"output_path": output_path, "units": "degrees", "status": "success"}
    except Exception as e:
        return {"error": str(e), "status": "failed"}


ACTIONS = {
    "viewshed": viewshed,
    "slope": slope_analysis,
    "watershed": watershed,
    "hillshade": hillshade,
    "aspect": aspect_analysis,
}


def main():
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    action = data.get("action")
    if action not in ACTIONS:
        json.dump({"error": f"Unknown action: {action}. Valid: {list(ACTIONS.keys())}"}, sys.stdout)
        return

    try:
        result = ACTIONS[action](data.get("params", {}))
        json.dump(result, sys.stdout, default=str)
    except Exception as e:
        json.dump({"error": str(e), "type": type(e).__name__}, sys.stdout)


if __name__ == "__main__":
    main()
