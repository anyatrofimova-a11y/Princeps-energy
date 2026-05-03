"""Prithvi (NASA-IBM) Earth-observation foundation model runner.

Apache-2.0 weights — registered in app/license_guard/licenses.yaml as
'prithvi_weights'. Commercial-safe.

Two heads supported:
  • burn_scars  — segment burn scar / fire damage from HLS imagery
  • crop_class  — multi-temporal crop type classification

Subprocess pattern: keep heavy torch + transformers in .venv-forecast (or
a dedicated .venv-prithvi if torch versions clash). Caller pipes JSON in
on stdin → JSON out on stdout.

Request:
  {
    "action": "infer" | "list",
    "head":   "burn_scars" | "crop_class",
    "input":  "<path-to-hls-tile-stack.tif>",
    "patch_size": 224
  }

Response:
  {"head": ..., "shape": [...], "logits_path": "...", "elapsed_s": ...}
or
  {"error": "...", "type": "...", "trace": "..."}
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

ARTIFACT_ID = "prithvi_weights"

WEIGHTS_DIR = Path(__file__).parent / "prithvi_models"
HEADS = {
    "burn_scars": "ibm-nasa-geospatial/Prithvi-100M-burn-scar",
    "crop_class": "ibm-nasa-geospatial/Prithvi-100M-multi-temporal-crop-classification",
}


def _list(_req):
    return {"available_heads": list(HEADS), "weights_dir": str(WEIGHTS_DIR)}


def _infer(req):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.license_guard import assert_commercial_safe  # noqa: WPS433
    assert_commercial_safe(ARTIFACT_ID)

    from transformers import AutoModelForImageSegmentation, AutoImageProcessor  # lazy
    import torch  # lazy
    import rasterio  # lazy
    import numpy as np  # lazy

    head = req["head"]
    if head not in HEADS:
        raise ValueError(f"Unknown head {head!r}. Available: {list(HEADS)}")

    repo = HEADS[head]
    proc = AutoImageProcessor.from_pretrained(repo, trust_remote_code=True)
    model = AutoModelForImageSegmentation.from_pretrained(repo, trust_remote_code=True).eval()

    with rasterio.open(req["input"]) as src:
        img = src.read()
    pixel_values = proc(images=np.transpose(img, (1, 2, 0)), return_tensors="pt")["pixel_values"]

    t0 = time.time()
    with torch.no_grad():
        out = model(pixel_values=pixel_values)
    elapsed = time.time() - t0

    logits = out.logits.cpu().numpy()
    logits_path = str(Path(req["input"]).with_suffix(".prithvi.npy"))
    np.save(logits_path, logits)
    return {"head": head, "shape": list(logits.shape), "logits_path": logits_path, "elapsed_s": elapsed}


HANDLERS = {"infer": _infer, "list": _list}


def main():
    try:
        req = json.loads(sys.stdin.read() or "{}")
        action = req.get("action") or "list"
        if action not in HANDLERS:
            raise ValueError(f"Unknown action: {action!r}")
        sys.stdout.write(json.dumps(HANDLERS[action](req), default=str))
        sys.exit(0)
    except Exception as exc:
        sys.stdout.write(json.dumps({
            "error": str(exc), "type": type(exc).__name__, "trace": traceback.format_exc(),
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
