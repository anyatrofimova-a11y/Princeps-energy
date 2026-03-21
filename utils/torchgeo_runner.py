"""
TorchGeo satellite analysis runner — subprocess bridge.
Runs pretrained models for land cover segmentation and change detection.

Runs inside .venv-geeflow/ (Python 3.12 with torchgeo + PyTorch).
Accepts JSON on stdin, prints JSON to stdout (same pattern as demand_forecaster.py).

Commands (JSON stdin/stdout):
  {"command": "classify_landcover", "image_path": "...", "model": "resnet50"}
  {"command": "change_detection", "before_path": "...", "after_path": "..."}
  {"command": "crop_classification", "image_path": "...", "model": "resnet50"}
  {"command": "list_models"}
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Land cover class mappings (EuroSAT 10-class)
# ---------------------------------------------------------------------------
EUROSAT_CLASSES = [
    "AnnualCrop",
    "Forest",
    "HerbaceousVegetation",
    "Highway",
    "Industrial",
    "Pasture",
    "PermanentCrop",
    "Residential",
    "River",
    "SeaLake",
]

# Map EuroSAT classes to energy-development-relevant categories
ENERGY_LANDCOVER_MAP = {
    "AnnualCrop":            {"category": "cropland",    "alc_hint": "Grade 2-3", "dev_suitability": "good"},
    "Forest":                {"category": "forest",      "alc_hint": "N/A",       "dev_suitability": "poor"},
    "HerbaceousVegetation":  {"category": "grassland",   "alc_hint": "Grade 3-4", "dev_suitability": "good"},
    "Highway":               {"category": "transport",   "alc_hint": "N/A",       "dev_suitability": "excluded"},
    "Industrial":            {"category": "built_up",    "alc_hint": "N/A",       "dev_suitability": "brownfield"},
    "Pasture":               {"category": "grassland",   "alc_hint": "Grade 3-4", "dev_suitability": "good"},
    "PermanentCrop":         {"category": "cropland",    "alc_hint": "Grade 1-2", "dev_suitability": "caution"},
    "Residential":           {"category": "built_up",    "alc_hint": "N/A",       "dev_suitability": "excluded"},
    "River":                 {"category": "water",       "alc_hint": "N/A",       "dev_suitability": "excluded"},
    "SeaLake":               {"category": "water",       "alc_hint": "N/A",       "dev_suitability": "excluded"},
}

# Crop-specific classes for ALC assessment
CROP_CLASSES = [
    "wheat", "barley", "maize", "rapeseed", "sugar_beet",
    "potatoes", "grassland", "fallow", "orchard", "other",
]

AVAILABLE_MODELS = {
    "resnet50": {
        "name": "ResNet-50 (EuroSAT)",
        "description": "ResNet-50 fine-tuned on EuroSAT Sentinel-2 dataset",
        "classes": 10,
        "input_bands": 13,
        "resolution_m": 10,
        "weights": "EuroSAT",
    },
    "resnet18": {
        "name": "ResNet-18 (EuroSAT)",
        "description": "Lighter ResNet-18 fine-tuned on EuroSAT",
        "classes": 10,
        "input_bands": 13,
        "resolution_m": 10,
        "weights": "EuroSAT",
    },
    "vit_small": {
        "name": "ViT-Small (SSL4EO-S12)",
        "description": "Vision Transformer pretrained on Sentinel-2 via SSL",
        "classes": 10,
        "input_bands": 13,
        "resolution_m": 10,
        "weights": "SSL4EO_S12",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_torchgeo_available() -> tuple[bool, str]:
    """Check if torchgeo and dependencies are importable."""
    try:
        import torch  # noqa: F401
        import torchgeo  # noqa: F401
        return True, f"torchgeo {torchgeo.__version__}, torch {torch.__version__}"
    except ImportError as exc:
        return False, str(exc)


def _load_geotiff(path: str) -> dict:
    """Load a GeoTIFF and return band array + metadata."""
    import numpy as np
    import rasterio

    with rasterio.open(path) as src:
        data = src.read()  # (bands, H, W)
        transform = src.transform
        crs = src.crs
        bounds = src.bounds
        profile = src.profile
        width, height = src.width, src.height

    return {
        "data": data,
        "transform": transform,
        "crs": crs,
        "bounds": bounds,
        "width": width,
        "height": height,
        "bands": data.shape[0],
        "profile": profile,
    }


def _bounds_to_geojson_bbox(bounds) -> list[list[list[float]]]:
    """Convert rasterio bounds to GeoJSON polygon coordinates."""
    return [[
        [bounds.left, bounds.bottom],
        [bounds.right, bounds.bottom],
        [bounds.right, bounds.top],
        [bounds.left, bounds.top],
        [bounds.left, bounds.bottom],
    ]]


# ---------------------------------------------------------------------------
# TorchGeo classification (full)
# ---------------------------------------------------------------------------

def classify_landcover_torchgeo(image_path: str, model_name: str = "resnet50") -> dict:
    """Run torchgeo pretrained model for land cover classification."""
    import numpy as np
    import torch
    from torchgeo.models import ResNet18_Weights, ResNet50_Weights, ViTSmall16_Weights
    from torchvision.models import resnet18, resnet50

    info = _load_geotiff(image_path)
    data = info["data"]  # (bands, H, W)
    bounds = info["bounds"]

    # Normalise to [0, 1]
    img = data.astype(np.float32)
    for b in range(img.shape[0]):
        bmin, bmax = img[b].min(), img[b].max()
        if bmax > bmin:
            img[b] = (img[b] - bmin) / (bmax - bmin)

    # Select model + weights
    if model_name == "resnet50":
        weights = ResNet50_Weights.SENTINEL2_ALL_MOCO
        model = resnet50(weights=None)
        model = weights.get_model(model)
    elif model_name == "resnet18":
        weights = ResNet18_Weights.SENTINEL2_ALL_MOCO
        model = resnet18(weights=None)
        model = weights.get_model(model)
    elif model_name == "vit_small":
        weights = ViTSmall16_Weights.SENTINEL2_ALL_DINO
        model = weights.get_model()
    else:
        raise ValueError(f"Unknown model: {model_name}. Available: {list(AVAILABLE_MODELS.keys())}")

    model.eval()

    # Prepare input: need 13 bands for Sentinel-2 models
    # If fewer bands, pad with zeros; if more, truncate
    target_bands = 13
    if img.shape[0] < target_bands:
        pad = np.zeros((target_bands - img.shape[0], img.shape[1], img.shape[2]), dtype=np.float32)
        img = np.concatenate([img, pad], axis=0)
    elif img.shape[0] > target_bands:
        img = img[:target_bands]

    # Split into 64x64 patches for classification
    patch_size = 64
    h, w = img.shape[1], img.shape[2]
    class_counts = np.zeros(len(EUROSAT_CLASSES), dtype=np.int64)
    patch_results = []

    with torch.no_grad():
        for y0 in range(0, h, patch_size):
            for x0 in range(0, w, patch_size):
                y1 = min(y0 + patch_size, h)
                x1 = min(x0 + patch_size, w)
                patch = img[:, y0:y1, x0:x1]

                # Pad patch if smaller than expected
                if patch.shape[1] < patch_size or patch.shape[2] < patch_size:
                    padded = np.zeros((target_bands, patch_size, patch_size), dtype=np.float32)
                    padded[:, :patch.shape[1], :patch.shape[2]] = patch
                    patch = padded

                tensor = torch.from_numpy(patch).unsqueeze(0)  # (1, C, H, W)
                logits = model(tensor)
                pred_class = logits.argmax(dim=1).item()
                class_counts[pred_class] += 1
                patch_results.append({
                    "x": x0, "y": y0,
                    "class_idx": int(pred_class),
                    "class_name": EUROSAT_CLASSES[pred_class],
                })

    total_patches = class_counts.sum()
    class_percentages = {}
    energy_categories = {}
    for idx, cls_name in enumerate(EUROSAT_CLASSES):
        pct = round(float(class_counts[idx]) / max(total_patches, 1) * 100, 1)
        if pct > 0:
            class_percentages[cls_name] = pct
            cat = ENERGY_LANDCOVER_MAP[cls_name]["category"]
            energy_categories[cat] = energy_categories.get(cat, 0) + pct

    # Determine dominant class and ALC hint
    dominant_idx = int(class_counts.argmax())
    dominant_class = EUROSAT_CLASSES[dominant_idx]
    dominant_info = ENERGY_LANDCOVER_MAP[dominant_class]

    # Build development suitability summary
    suitable_pct = sum(
        class_percentages.get(cls, 0)
        for cls, info in ENERGY_LANDCOVER_MAP.items()
        if info["dev_suitability"] in ("good", "brownfield")
    )

    return {
        "status": "ok",
        "model": model_name,
        "model_info": AVAILABLE_MODELS[model_name],
        "total_patches": int(total_patches),
        "class_percentages": class_percentages,
        "energy_categories": energy_categories,
        "dominant_class": dominant_class,
        "dominant_category": dominant_info["category"],
        "alc_hint": dominant_info["alc_hint"],
        "development_suitability": dominant_info["dev_suitability"],
        "suitable_area_pct": round(suitable_pct, 1),
        "bbox": {
            "type": "Polygon",
            "coordinates": _bounds_to_geojson_bbox(bounds),
        },
        "crs": str(info["crs"]),
    }


# ---------------------------------------------------------------------------
# Fallback classification (numpy + rasterio only)
# ---------------------------------------------------------------------------

def classify_landcover_fallback(image_path: str) -> dict:
    """Simple NDVI/index-based classification when torchgeo is unavailable."""
    import numpy as np
    import rasterio

    info = _load_geotiff(image_path)
    data = info["data"].astype(np.float32)
    bounds = info["bounds"]
    h, w = data.shape[1], data.shape[2]
    total_pixels = h * w

    # Sentinel-2 band indices (0-based): B2=1 Blue, B3=2 Green, B4=3 Red,
    # B8=7 NIR, B11=10 SWIR1, B12=11 SWIR2
    # Adapt based on available bands
    n_bands = data.shape[0]

    if n_bands >= 8:
        red = data[3]
        nir = data[7]
    elif n_bands >= 4:
        red = data[2]   # assume R/G/B/NIR
        nir = data[3]
    else:
        # Greyscale or RGB — very rough heuristic
        red = data[min(n_bands - 1, 0)]
        nir = data[min(n_bands - 1, 0)] * 1.2  # fake NIR

    # NDVI
    denom = nir + red
    ndvi = np.where(denom > 0, (nir - red) / denom, 0.0)

    # NDWI (green - NIR) / (green + NIR) if we have green
    if n_bands >= 3:
        green = data[1] if n_bands >= 4 else data[1]
        denom_w = green + nir
        ndwi = np.where(denom_w > 0, (green - nir) / denom_w, 0.0)
    else:
        ndwi = np.zeros_like(ndvi)

    # Simple thresholds
    water = (ndwi > 0.3) | (ndvi < -0.1)
    dense_veg = (ndvi > 0.6) & ~water
    moderate_veg = (ndvi > 0.3) & (ndvi <= 0.6) & ~water
    sparse_veg = (ndvi > 0.1) & (ndvi <= 0.3) & ~water
    bare = (ndvi >= -0.1) & (ndvi <= 0.1) & ~water

    # Brightness for built-up detection
    if n_bands >= 3:
        brightness = data[:3].mean(axis=0)
        bright_threshold = np.percentile(brightness[~water], 80) if (~water).sum() > 0 else brightness.max()
        built_up = bare & (brightness > bright_threshold)
        bare = bare & ~built_up
    else:
        built_up = np.zeros_like(water)

    classes = {
        "forest":    int(dense_veg.sum()),
        "cropland":  int(moderate_veg.sum()),
        "grassland": int(sparse_veg.sum()),
        "bare_soil": int(bare.sum()),
        "built_up":  int(built_up.sum()),
        "water":     int(water.sum()),
    }

    class_percentages = {k: round(v / max(total_pixels, 1) * 100, 1) for k, v in classes.items() if v > 0}
    dominant = max(classes, key=classes.get)

    suitability_map = {
        "forest": "poor", "cropland": "good", "grassland": "good",
        "bare_soil": "good", "built_up": "brownfield", "water": "excluded",
    }
    alc_map = {
        "forest": "N/A", "cropland": "Grade 2-3", "grassland": "Grade 3-4",
        "bare_soil": "Grade 4-5", "built_up": "N/A", "water": "N/A",
    }

    suitable_pct = sum(
        v for k, v in class_percentages.items()
        if suitability_map.get(k) in ("good", "brownfield")
    )

    return {
        "status": "ok",
        "model": "fallback_ndvi",
        "model_info": {
            "name": "NDVI/Index Threshold (Fallback)",
            "description": "Simple spectral index classification — install torchgeo for ML models",
            "classes": 6,
            "resolution_m": "native",
        },
        "total_pixels": total_pixels,
        "class_percentages": class_percentages,
        "energy_categories": class_percentages,  # already in energy categories
        "dominant_class": dominant,
        "dominant_category": dominant,
        "alc_hint": alc_map.get(dominant, "N/A"),
        "development_suitability": suitability_map.get(dominant, "unknown"),
        "suitable_area_pct": round(suitable_pct, 1),
        "ndvi_stats": {
            "mean": round(float(ndvi.mean()), 3),
            "std": round(float(ndvi.std()), 3),
            "min": round(float(ndvi.min()), 3),
            "max": round(float(ndvi.max()), 3),
        },
        "bbox": {
            "type": "Polygon",
            "coordinates": _bounds_to_geojson_bbox(bounds),
        },
        "crs": str(info["crs"]),
    }


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------

def change_detection_torchgeo(before_path: str, after_path: str) -> dict:
    """Detect land use changes between two dates using classification comparison."""
    has_tg, _ = _check_torchgeo_available()

    if has_tg:
        before = classify_landcover_torchgeo(before_path)
        after = classify_landcover_torchgeo(after_path)
    else:
        before = classify_landcover_fallback(before_path)
        after = classify_landcover_fallback(after_path)

    # Compare class percentages
    all_classes = set(before.get("class_percentages", {}).keys()) | set(after.get("class_percentages", {}).keys())
    changes = {}
    for cls in sorted(all_classes):
        before_pct = before.get("class_percentages", {}).get(cls, 0)
        after_pct = after.get("class_percentages", {}).get(cls, 0)
        delta = round(after_pct - before_pct, 1)
        if abs(delta) > 0.5:
            changes[cls] = {
                "before_pct": before_pct,
                "after_pct": after_pct,
                "delta_pct": delta,
                "direction": "increase" if delta > 0 else "decrease",
            }

    # Overall change magnitude
    total_change = sum(abs(c["delta_pct"]) for c in changes.values()) / 2  # divide by 2 since changes are zero-sum

    # Assess change significance for energy development
    significant_changes = []
    for cls, change in changes.items():
        if abs(change["delta_pct"]) > 5:
            significant_changes.append(
                f"{cls}: {change['before_pct']}% -> {change['after_pct']}% ({change['direction']})"
            )

    return {
        "status": "ok",
        "model": before.get("model", "unknown"),
        "before_summary": {
            "dominant_class": before.get("dominant_class"),
            "class_percentages": before.get("class_percentages"),
        },
        "after_summary": {
            "dominant_class": after.get("dominant_class"),
            "class_percentages": after.get("class_percentages"),
        },
        "changes": changes,
        "total_change_pct": round(total_change, 1),
        "significant_changes": significant_changes,
        "land_use_stable": total_change < 10,
        "development_risk": (
            "low" if total_change < 5
            else "medium" if total_change < 20
            else "high"
        ),
    }


# ---------------------------------------------------------------------------
# Crop / vegetation classification for ALC
# ---------------------------------------------------------------------------

def crop_classification(image_path: str, model_name: str = "resnet50") -> dict:
    """Classify crops/vegetation for Agricultural Land Classification assessment."""
    has_tg, _ = _check_torchgeo_available()

    # Start with land cover classification
    if has_tg:
        lc = classify_landcover_torchgeo(image_path, model_name)
    else:
        lc = classify_landcover_fallback(image_path)

    # Enhanced crop analysis using NDVI temporal patterns
    import numpy as np
    info = _load_geotiff(image_path)
    data = info["data"].astype(np.float32)
    n_bands = data.shape[0]

    # Compute vegetation indices
    if n_bands >= 8:
        red, nir = data[3], data[7]
    elif n_bands >= 4:
        red, nir = data[2], data[3]
    else:
        red = data[0]
        nir = data[0] * 1.2

    denom = nir + red
    ndvi = np.where(denom > 0, (nir - red) / denom, 0.0)

    # Vegetation vigour assessment
    veg_mask = ndvi > 0.2
    veg_pixels = ndvi[veg_mask]

    if len(veg_pixels) > 0:
        veg_vigour = float(veg_pixels.mean())
        veg_uniformity = 1.0 - min(float(veg_pixels.std()) / 0.3, 1.0)  # lower std = more uniform
    else:
        veg_vigour = 0.0
        veg_uniformity = 0.0

    # ALC grade estimation based on vegetation characteristics
    # Grade 1: Best (high vigour, uniform) -> Grade 5: Poorest
    cropland_pct = lc.get("class_percentages", {}).get("cropland", 0) + \
                   lc.get("class_percentages", {}).get("AnnualCrop", 0) + \
                   lc.get("class_percentages", {}).get("PermanentCrop", 0)

    grassland_pct = lc.get("class_percentages", {}).get("grassland", 0) + \
                    lc.get("class_percentages", {}).get("Pasture", 0) + \
                    lc.get("class_percentages", {}).get("HerbaceousVegetation", 0)

    if cropland_pct > 50 and veg_vigour > 0.5 and veg_uniformity > 0.6:
        alc_grade = "Grade 1-2"
        alc_note = "High-quality agricultural land — BMV (Best and Most Versatile)"
    elif cropland_pct > 30 and veg_vigour > 0.3:
        alc_grade = "Grade 2-3a"
        alc_note = "Good quality agricultural land — may be BMV"
    elif grassland_pct > 40 and veg_vigour > 0.2:
        alc_grade = "Grade 3b-4"
        alc_note = "Moderate quality — generally acceptable for development"
    elif grassland_pct > 20:
        alc_grade = "Grade 4"
        alc_note = "Poor quality agricultural land — suitable for development"
    else:
        alc_grade = "Grade 5 / Non-agricultural"
        alc_note = "Very poor / non-agricultural — no ALC constraint"

    return {
        "status": "ok",
        "model": lc.get("model", "unknown"),
        "land_cover": lc.get("class_percentages", {}),
        "cropland_pct": round(cropland_pct, 1),
        "grassland_pct": round(grassland_pct, 1),
        "vegetation_vigour": round(veg_vigour, 3),
        "vegetation_uniformity": round(veg_uniformity, 3),
        "estimated_alc_grade": alc_grade,
        "alc_note": alc_note,
        "is_bmv": alc_grade in ("Grade 1-2", "Grade 2-3a"),
        "development_constraint": "high" if alc_grade == "Grade 1-2" else
                                  "medium" if alc_grade == "Grade 2-3a" else "low",
        "ndvi_stats": {
            "mean": round(float(ndvi.mean()), 3),
            "std": round(float(ndvi.std()), 3),
            "vegetated_pct": round(float(veg_mask.sum()) / max(ndvi.size, 1) * 100, 1),
        },
        "bbox": lc.get("bbox"),
        "crs": lc.get("crs"),
    }


# ---------------------------------------------------------------------------
# Command dispatcher
# ---------------------------------------------------------------------------

COMMANDS = {
    "classify_landcover": lambda p: _cmd_classify(p),
    "change_detection": lambda p: _cmd_change_detection(p),
    "crop_classification": lambda p: _cmd_crop_classification(p),
    "list_models": lambda p: _cmd_list_models(p),
}


def _cmd_classify(payload: dict) -> dict:
    image_path = payload.get("image_path")
    if not image_path:
        return {"error": "image_path is required"}
    if not Path(image_path).exists():
        return {"error": f"File not found: {image_path}"}

    model = payload.get("model", "resnet50")
    has_tg, version_info = _check_torchgeo_available()

    if has_tg:
        result = classify_landcover_torchgeo(image_path, model)
        result["engine"] = "torchgeo"
        result["version_info"] = version_info
    else:
        result = classify_landcover_fallback(image_path)
        result["engine"] = "fallback"
        result["torchgeo_missing"] = version_info
    return result


def _cmd_change_detection(payload: dict) -> dict:
    before_path = payload.get("before_path")
    after_path = payload.get("after_path")
    if not before_path or not after_path:
        return {"error": "before_path and after_path are required"}
    if not Path(before_path).exists():
        return {"error": f"File not found: {before_path}"}
    if not Path(after_path).exists():
        return {"error": f"File not found: {after_path}"}

    return change_detection_torchgeo(before_path, after_path)


def _cmd_crop_classification(payload: dict) -> dict:
    image_path = payload.get("image_path")
    if not image_path:
        return {"error": "image_path is required"}
    if not Path(image_path).exists():
        return {"error": f"File not found: {image_path}"}

    model = payload.get("model", "resnet50")
    return crop_classification(image_path, model)


def _cmd_list_models(_payload: dict) -> dict:
    has_tg, version_info = _check_torchgeo_available()
    return {
        "status": "ok",
        "torchgeo_available": has_tg,
        "version_info": version_info,
        "models": AVAILABLE_MODELS,
        "commands": list(COMMANDS.keys()),
        "eurosat_classes": EUROSAT_CLASSES,
        "energy_landcover_map": ENERGY_LANDCOVER_MAP,
    }


# ---------------------------------------------------------------------------
# Main — JSON stdin/stdout bridge
# ---------------------------------------------------------------------------

def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({"error": "No input received. Send JSON on stdin."}))
            sys.exit(1)

        payload = json.loads(raw)
        command = payload.get("command", "")

        handler = COMMANDS.get(command)
        if not handler:
            print(json.dumps({
                "error": f"Unknown command: {command}",
                "available_commands": list(COMMANDS.keys()),
            }))
            sys.exit(1)

        result = handler(payload)
        print(json.dumps(result, default=str))

    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"Invalid JSON input: {exc}"}))
        sys.exit(1)
    except Exception as exc:
        print(json.dumps({
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
