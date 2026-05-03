"""TimesFM (Google Research) demand forecaster — Apache-2.0 weights.

Replaces the Prophet baseline in utils/demand_forecaster.py for zero-shot
forecasting on UK GSP demand. Foundation model — no per-GSP training.

Model: google/timesfm-1.0-200m on Hugging Face (Apache-2.0 weights).
Install: pip install timesfm  (in main .venv)

Commercial-safe: registered in app/license_guard/licenses.yaml as
artifact id 'timesfm_weights'. The forecast() entry point calls the
license guard so any commercial endpoint is auto-cleared.
"""

from __future__ import annotations

import logging
from typing import Sequence

from app.license_guard import assert_commercial_safe, record_artifact_use

log = logging.getLogger("princeps.timesfm")

ARTIFACT_ID = "timesfm_weights"
HORIZON_DEFAULT = 48          # half-hourly steps = 24 h
CONTEXT_LEN_DEFAULT = 512     # half-hourly context = ~10 d


class TimesFmForecaster:
    """Lazy-loading wrapper around TimesFM. Loads the model on first
    forecast() call so import-time stays cheap.
    """

    def __init__(self, *, repo_id: str = "google/timesfm-1.0-200m"):
        # Fail early if licence registry is misconfigured.
        assert_commercial_safe(ARTIFACT_ID)
        self.repo_id = repo_id
        self._model = None

    def _ensure_loaded(self):
        if self._model is not None:
            return
        try:
            import timesfm  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "timesfm not installed in the active venv. Run:\n"
                "  pip install timesfm"
            ) from e
        log.info("loading TimesFM weights: %s", self.repo_id)
        self._model = timesfm.TimesFm(
            hparams=timesfm.TimesFmHparams(
                backend="cpu",
                per_core_batch_size=32,
                horizon_len=HORIZON_DEFAULT,
                context_len=CONTEXT_LEN_DEFAULT,
            ),
            checkpoint=timesfm.TimesFmCheckpoint(huggingface_repo_id=self.repo_id),
        )

    def forecast(
        self,
        history: Sequence[float],
        *,
        horizon: int = HORIZON_DEFAULT,
        request=None,
    ) -> dict:
        """Zero-shot forecast.

        Args:
            history: half-hourly demand series (most-recent-first NOT required;
                pass in time order, oldest first). At least 64 points recommended.
            horizon: number of half-hourly steps to forecast (default 48 = 24 h).
            request: FastAPI Request — when provided, we tag this artifact as
                used so LicenseGuardMiddleware can audit on the way out.

        Returns:
            {model, artifact_id, horizon, forecast, p10, p50, p90}
        """
        if request is not None:
            record_artifact_use(request, ARTIFACT_ID)
        if len(history) < 16:
            raise ValueError("history too short for TimesFM (need >= 16 points)")
        self._ensure_loaded()
        # frequency 0 = high-frequency (≤ 1 h). UK half-hourly fits here.
        point, quantile = self._model.forecast(
            inputs=[list(map(float, history))], freq=[0],
        )
        forecast = point[0][:horizon].tolist()
        # quantile shape: (1, horizon, 10) — 10 quantile bands.
        q = quantile[0]
        return {
            "model": self.repo_id,
            "artifact_id": ARTIFACT_ID,
            "horizon": horizon,
            "forecast": forecast,
            "p10": q[:horizon, 1].tolist(),
            "p50": q[:horizon, 5].tolist(),
            "p90": q[:horizon, 9].tolist(),
        }


_singleton: TimesFmForecaster | None = None


def get_forecaster() -> TimesFmForecaster:
    global _singleton
    if _singleton is None:
        _singleton = TimesFmForecaster()
    return _singleton
