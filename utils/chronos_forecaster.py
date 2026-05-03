"""Chronos (Amazon) demand forecaster — Apache-2.0 weights, replaces TimesFM
on stacks where TimesFM 1.x's paxml/lingvo dep chain doesn't install.

Why Chronos:
  • Apache-2.0 model weights (registered as 'chronos_weights' in
    app/license_guard/licenses.yaml). Commercial-safe.
  • Clean install on Python 3.12 — single line.
  • Same use-case fit (zero-shot time-series forecast).

Install:
  /path/to/.venv-forecast/bin/pip install chronos-forecasting

Run with:
  from utils.chronos_forecaster import get_forecaster
  fc = get_forecaster()
  fc.forecast(history, horizon=48)
"""

from __future__ import annotations

import logging
from typing import Sequence

from app.license_guard import assert_commercial_safe, record_artifact_use

log = logging.getLogger("princeps.chronos")

ARTIFACT_ID = "chronos_weights"
HORIZON_DEFAULT = 48
DEFAULT_REPO = "amazon/chronos-t5-large"


class ChronosForecaster:
    def __init__(self, *, repo_id: str = DEFAULT_REPO):
        assert_commercial_safe(ARTIFACT_ID)
        self.repo_id = repo_id
        self._pipeline = None

    def _ensure_loaded(self):
        if self._pipeline is not None:
            return
        try:
            import torch  # type: ignore  # noqa: F401
            from chronos import ChronosPipeline  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "chronos-forecasting not installed. Run:\n"
                "  pip install chronos-forecasting"
            ) from e
        log.info("loading Chronos: %s", self.repo_id)
        import torch  # type: ignore
        device = "cpu"  # bump to "mps" or "cuda" once we benchmark
        self._pipeline = ChronosPipeline.from_pretrained(
            self.repo_id, device_map=device, torch_dtype=torch.float32,
        )

    def forecast(
        self,
        history: Sequence[float],
        *,
        horizon: int = HORIZON_DEFAULT,
        num_samples: int = 20,
        request=None,
    ) -> dict:
        if request is not None:
            record_artifact_use(request, ARTIFACT_ID)
        if len(history) < 16:
            raise ValueError("history too short for Chronos (need >= 16 points)")
        self._ensure_loaded()

        import numpy as np   # lazy
        import torch         # lazy

        ctx = torch.tensor(list(map(float, history)))
        # Chronos returns shape (num_samples, prediction_length)
        forecast = self._pipeline.predict(
            context=ctx, prediction_length=horizon, num_samples=num_samples,
        )
        # forecast can be a tensor of shape (1, num_samples, horizon)
        arr = forecast.numpy() if hasattr(forecast, "numpy") else np.asarray(forecast)
        if arr.ndim == 3:
            arr = arr[0]  # drop batch dim
        p10 = np.quantile(arr, 0.1, axis=0).tolist()
        p50 = np.quantile(arr, 0.5, axis=0).tolist()
        p90 = np.quantile(arr, 0.9, axis=0).tolist()
        return {
            "model": self.repo_id,
            "artifact_id": ARTIFACT_ID,
            "horizon": horizon,
            "forecast": p50,
            "p10": p10,
            "p50": p50,
            "p90": p90,
        }


_singleton: ChronosForecaster | None = None


def get_forecaster() -> ChronosForecaster:
    global _singleton
    if _singleton is None:
        _singleton = ChronosForecaster()
    return _singleton
