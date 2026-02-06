# utils/rasters.py
import rasterio
import numpy as np

def slope_stats_from_tif(slope_tif):
    with rasterio.open(slope_tif) as src:
        arr = src.read(1, masked=True)
        # mask invalid values
        valid = arr.compressed() if hasattr(arr, "compressed") else arr[~np.isnan(arr)]
        if valid.size == 0:
            return {"mean": None, "std": None, "min": None, "max": None}
        return {
            "mean": float(np.mean(valid)),
            "std": float(np.std(valid)),
            "min": float(np.min(valid)),
            "max": float(np.max(valid))
        }
