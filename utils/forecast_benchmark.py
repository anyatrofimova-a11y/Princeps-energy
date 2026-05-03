"""Demand-forecast benchmark: TimesFM (Apache weights) vs Prophet baseline
vs Darts TFT, on UK GSP demand pulled from the demand_historical table.

Run inside .venv-forecast (Python 3.12) — Prophet + Darts + TimesFM all live
there.

Outputs JSON to stdout:
  {
    "gsp_id": "...",
    "horizon": 48,
    "metrics": {
      "timesfm":   {"mape": ..., "rmse": ..., "p10_coverage": ..., "p90_coverage": ...},
      "prophet":   {"mape": ..., "rmse": ..., ...},
      "darts_tft": {"mape": ..., "rmse": ..., ...}
    },
    "winner": "timesfm" | ...
  }

Usage:
  .venv-forecast/bin/python utils/forecast_benchmark.py --gsp ACAS_1 --horizon 48
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
from dataclasses import dataclass

log = logging.getLogger("princeps.forecast_benchmark")


@dataclass
class Series:
    train: list[float]
    test: list[float]


# ────────────────────────── Data loading ──────────────────────────


async def load_gsp_series(gsp_id: str, horizon: int = 48, context: int = 512) -> Series:
    import asyncpg  # lazy
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT settlement_date, settlement_period, demand_mw
            FROM demand_historical
            WHERE gsp_id = $1
            ORDER BY settlement_date DESC, settlement_period DESC
            LIMIT $2
            """,
            gsp_id, context + horizon,
        )
    finally:
        await conn.close()

    series = list(reversed([float(r["demand_mw"]) for r in rows if r["demand_mw"] is not None]))
    if len(series) < context + horizon:
        raise RuntimeError(f"not enough history for {gsp_id}: have {len(series)}, need {context + horizon}")
    return Series(train=series[:-horizon], test=series[-horizon:])


# ────────────────────────── Forecasters ──────────────────────────


def forecast_timesfm(series: Series, horizon: int) -> dict:
    from utils.timesfm_forecaster import get_forecaster  # lazy
    return get_forecaster().forecast(series.train, horizon=horizon)


def forecast_chronos(series: Series, horizon: int) -> dict:
    from utils.chronos_forecaster import get_forecaster  # lazy
    return get_forecaster().forecast(series.train, horizon=horizon)


def forecast_prophet(series: Series, horizon: int) -> dict:
    from prophet import Prophet  # lazy
    import pandas as pd
    df = pd.DataFrame({"ds": pd.date_range("2020-01-01", periods=len(series.train), freq="30min"),
                       "y": series.train})
    m = Prophet(interval_width=0.8)
    m.fit(df)
    future = m.make_future_dataframe(periods=horizon, freq="30min")
    fcst = m.predict(future).tail(horizon)
    return {"forecast": fcst["yhat"].tolist(),
            "p10": fcst["yhat_lower"].tolist(),
            "p90": fcst["yhat_upper"].tolist(),
            "p50": fcst["yhat"].tolist()}


def forecast_darts_tft(series: Series, horizon: int) -> dict:
    from darts import TimeSeries  # lazy
    from darts.models import TFTModel
    import pandas as pd
    ts = TimeSeries.from_times_and_values(
        pd.date_range("2020-01-01", periods=len(series.train), freq="30min"),
        series.train,
    )
    model = TFTModel(input_chunk_length=128, output_chunk_length=horizon, n_epochs=20,
                     likelihood=None, random_state=42)
    model.fit(ts)
    forecast = model.predict(horizon)
    pts = forecast.values().squeeze().tolist()
    return {"forecast": pts, "p50": pts, "p10": pts, "p90": pts}


# ────────────────────────── Metrics ──────────────────────────


def mape(actual: list[float], pred: list[float]) -> float:
    pairs = [(a, p) for a, p in zip(actual, pred) if a != 0]
    return 100.0 * sum(abs(a - p) / abs(a) for a, p in pairs) / max(1, len(pairs))


def rmse(actual: list[float], pred: list[float]) -> float:
    return math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, pred)) / max(1, len(actual)))


def coverage(actual: list[float], lower: list[float], upper: list[float]) -> float:
    if not lower or not upper:
        return float("nan")
    inside = sum(1 for a, lo, hi in zip(actual, lower, upper) if lo <= a <= hi)
    return 100.0 * inside / max(1, len(actual))


def evaluate(actual: list[float], result: dict) -> dict:
    pred = result.get("p50") or result.get("forecast") or []
    return {
        "mape": mape(actual, pred),
        "rmse": rmse(actual, pred),
        "p80_coverage": coverage(actual, result.get("p10") or [], result.get("p90") or []),
    }


# ────────────────────────── CLI ──────────────────────────


async def main_async(gsp_id: str, horizon: int) -> dict:
    series = await load_gsp_series(gsp_id, horizon=horizon)

    metrics = {}
    for name, fn in (
        ("chronos", forecast_chronos),
        ("timesfm", forecast_timesfm),
        ("prophet", forecast_prophet),
        ("darts_tft", forecast_darts_tft),
    ):
        try:
            result = fn(series, horizon)
            metrics[name] = evaluate(series.test, result)
        except Exception as e:
            log.exception("%s failed", name)
            metrics[name] = {"error": f"{type(e).__name__}: {e}"}

    valid = {k: v for k, v in metrics.items() if "mape" in v}
    winner = min(valid, key=lambda k: valid[k]["mape"]) if valid else None
    return {"gsp_id": gsp_id, "horizon": horizon, "metrics": metrics, "winner": winner}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gsp", default="ACAS_1")
    parser.add_argument("--horizon", type=int, default=48)
    args = parser.parse_args()
    out = asyncio.run(main_async(args.gsp, args.horizon))
    print(json.dumps(out, indent=2))
