# pipeline.py
import os
import subprocess
import logging
from pathlib import Path
import requests

log = logging.getLogger(__name__)

def fetch_vibe_raster(layer_name: str, bbox, out_tif: str, srs="EPSG:27700", vibe_base="https://vibe.ornl.gov"):
    """
    Download a VIBE raster layer clipped to bbox (bbox in target SRS).
    - layer_name: string (e.g. "DEM", "solar_ghi")
    - bbox: [minx, miny, maxx, maxy] (numbers)
    - out_tif: output filepath
    NOTE: adapt URL/params to the actual VIBE API. This is a generic example.
    """
    params = {
        "layer": layer_name,
        "bbox": ",".join(map(str, bbox)),
        "srs": srs,
        "format": "GTiff"
    }
    url = f"{vibe_base}/api/export"  # replace with actual VIBE endpoint if different
    log.info("Requesting VIBE raster %s bbox=%s -> %s", layer_name, bbox, out_tif)
    with requests.get(url, params=params, stream=True, timeout=120) as r:
        r.raise_for_status()
        Path(out_tif).parent.mkdir(parents=True, exist_ok=True)
        with open(out_tif, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
    return out_tif

def clip_and_reproject(in_tif: str, out_tif: str, bbox, target_srs="EPSG:27700", res=2.0):
    """
    Use gdalwarp to clip, reproject and set resolution.
    bbox is in target_srs coordinates [minx,miny,maxx,maxy]
    """
    cmd = [
        "gdalwarp",
        "-t_srs", target_srs,
        "-te", str(bbox[0]), str(bbox[1]), str(bbox[2]), str(bbox[3]),
        "-tr", str(res), str(res),
        "-r", "bilinear",
        "-of", "GTiff",
        in_tif, out_tif
    ]
    log.info("Running gdalwarp: %s", " ".join(cmd))
    subprocess.check_call(cmd)
    return out_tif

def compute_slope(dem_tif: str, slope_out_tif: str, compute_format="percent"):
    """
    Compute slope raster from DEM (use gdaldem slope).
    compute_format = 'degree' or 'percent'
    """
    cmd = ["gdaldem", "slope", dem_tif, slope_out_tif, "-p"]
    if compute_format == "degree":
        cmd = ["gdaldem", "slope", dem_tif, slope_out_tif, "-p", "-compute_edges"]
    log.info("Running gdaldem slope: %s", " ".join(cmd))
    subprocess.check_call(cmd)
    return slope_out_tif

def generate_tiles(input_tif: str, out_tiles_dir: str):
    """
    Generate raster tiles (XYZ) for map display. Use gdal2tiles.py (simple).
    Produces a folder structure out_tiles_dir/{z}/{x}/{y}.png
    """
    Path(out_tiles_dir).mkdir(parents=True, exist_ok=True)
    cmd = ["gdal2tiles.py", "-z", "0-16", "-r", "bilinear", input_tif, out_tiles_dir]
    log.info("Running gdal2tiles: %s", " ".join(cmd))
    subprocess.check_call(cmd)
    return out_tiles_dir
