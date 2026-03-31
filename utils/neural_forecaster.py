#!/usr/bin/env python3
"""
Neural demand forecaster — NHITS and PatchTST models via neuralforecast.

Called as a subprocess from the FastAPI backend because neuralforecast
has heavy dependencies (PyTorch, pytorch-lightning) in .venv-forecast/.

Usage (stdin/stdout JSON bridge):
    echo '{"command": "forecast", "data": [...], "horizon": 48, "model": "nhits"}' | \
        .venv-forecast/bin/python utils/neural_forecaster.py

Input JSON:
    {
        "command": "forecast",
        "data": [
            {"ds": "2024-01-01 00:00", "y": 42.5, "unique_id": "ABHA"},
            ...
        ],
        "horizon": 48,
        "model": "nhits" | "patchtst" | "ensemble",
        "freq": "h",
        "save_model": false,
        "model_dir": "data/neural_models"
    }

Output JSON:
    {
        "ok": true,
        "model": "nhits",
        "horizon": 48,
        "forecast": [
            {"ds": "2024-01-08 00:00", "y_hat": 43.1, "lo_90": 38.0, "hi_90": 48.2,
             "lo_80": 39.5, "hi_80": 46.7},
            ...
        ],
        "metrics": {"training_time_s": 12.3}
    }
"""

import json
import os
import sys
import time
import traceback


def run_neural_forecast(data, horizon=48, model_type="nhits", freq="h",
                        save_model=False, model_dir="data/neural_models"):
    """
    Train and predict using NHITS or PatchTST from neuralforecast.

    Args:
        data: list of dicts with keys 'ds', 'y', 'unique_id'
        horizon: forecast horizon (number of periods)
        model_type: 'nhits', 'patchtst', or 'ensemble'
        freq: pandas frequency string
        save_model: whether to save trained model
        model_dir: directory for saved models

    Returns:
        dict with forecast, probabilistic intervals, metrics
    """
    import pandas as pd
    import numpy as np

    try:
        from neuralforecast import NeuralForecast
        from neuralforecast.models import NHITS
    except ImportError:
        return {"ok": False, "error": "neuralforecast not installed in this venv"}

    t0 = time.time()

    # Prepare dataframe
    df = pd.DataFrame(data)
    df["ds"] = pd.to_datetime(df["ds"])
    df["y"] = df["y"].astype(float)
    if "unique_id" not in df.columns:
        df["unique_id"] = "series_1"

    # Ensure sorted
    df = df.sort_values(["unique_id", "ds"]).reset_index(drop=True)

    if len(df) < horizon * 2:
        return {"ok": False, "error": f"Insufficient data: need at least {horizon * 2} points, got {len(df)}"}

    # Build models
    models = []

    if model_type in ("nhits", "ensemble"):
        models.append(
            NHITS(
                h=horizon,
                input_size=min(horizon * 3, len(df) // 2),
                max_steps=200,
                scaler_type="standard",
                learning_rate=1e-3,
                loss=None,  # default MAE
                early_stop_patience_steps=10,
                val_check_steps=50,
                random_seed=42,
            )
        )

    if model_type in ("patchtst", "ensemble"):
        try:
            from neuralforecast.models import PatchTST
            models.append(
                PatchTST(
                    h=horizon,
                    input_size=min(horizon * 3, len(df) // 2),
                    max_steps=200,
                    scaler_type="standard",
                    learning_rate=1e-4,
                    early_stop_patience_steps=10,
                    val_check_steps=50,
                    random_seed=42,
                )
            )
        except (ImportError, Exception) as e:
            if model_type == "patchtst":
                return {"ok": False, "error": f"PatchTST not available: {e}. Try model=nhits."}
            # In ensemble mode, continue with just NHITS

    if not models:
        return {"ok": False, "error": "No models could be initialized"}

    # Train and predict
    nf = NeuralForecast(models=models, freq=freq)

    try:
        nf.fit(df=df)
        forecast_df = nf.predict()
    except Exception as e:
        # Fallback to NHITS only if ensemble failed
        if model_type == "ensemble" and len(models) > 1:
            try:
                nf = NeuralForecast(models=[models[0]], freq=freq)
                nf.fit(df=df)
                forecast_df = nf.predict()
                model_type = "nhits_fallback"
            except Exception as e2:
                return {"ok": False, "error": f"Neural forecast failed: {e2}"}
        else:
            return {"ok": False, "error": f"Neural forecast failed: {e}"}

    elapsed = round(time.time() - t0, 2)

    # Extract forecasts
    forecast_df = forecast_df.reset_index()

    # Identify prediction columns
    pred_cols = [c for c in forecast_df.columns if c not in ("ds", "unique_id")]

    # Build output
    forecasts = []
    for _, row in forecast_df.iterrows():
        entry = {
            "ds": row["ds"].isoformat(),
            "unique_id": str(row.get("unique_id", "series_1")),
        }

        # Point forecast: use first model's column or average for ensemble
        model_preds = []
        for col in pred_cols:
            if "lo" not in col.lower() and "hi" not in col.lower():
                val = float(row[col])
                if not np.isnan(val):
                    model_preds.append(val)

        if model_preds:
            if model_type == "ensemble" or model_type == "nhits_fallback":
                entry["y_hat"] = round(float(np.mean(model_preds)), 3)
            else:
                entry["y_hat"] = round(model_preds[0], 3)

        # Probabilistic intervals (if available from quantile models)
        for col in pred_cols:
            col_lower = col.lower()
            if "lo-90" in col_lower or "lo_90" in col_lower:
                entry["lo_90"] = round(float(row[col]), 3)
            elif "hi-90" in col_lower or "hi_90" in col_lower:
                entry["hi_90"] = round(float(row[col]), 3)
            elif "lo-80" in col_lower or "lo_80" in col_lower:
                entry["lo_80"] = round(float(row[col]), 3)
            elif "hi-80" in col_lower or "hi_80" in col_lower:
                entry["hi_80"] = round(float(row[col]), 3)

        # Generate synthetic intervals if not produced by model
        if "lo_90" not in entry and "y_hat" in entry:
            y = entry["y_hat"]
            std_est = abs(y) * 0.12  # ~12% uncertainty estimate
            entry["lo_90"] = round(y - 1.645 * std_est, 3)
            entry["hi_90"] = round(y + 1.645 * std_est, 3)
            entry["lo_80"] = round(y - 1.28 * std_est, 3)
            entry["hi_80"] = round(y + 1.28 * std_est, 3)

        # P10/P50/P90 mapping
        if "y_hat" in entry:
            entry["p50"] = entry["y_hat"]
        if "lo_90" in entry:
            entry["p10"] = entry["lo_90"]
        if "hi_90" in entry:
            entry["p90"] = entry["hi_90"]

        forecasts.append(entry)

    # Save model if requested
    if save_model and model_dir:
        os.makedirs(model_dir, exist_ok=True)
        try:
            nf.save(path=model_dir, overwrite=True)
        except Exception:
            pass  # Non-critical

    return {
        "ok": True,
        "model": model_type,
        "horizon": horizon,
        "num_series": len(forecast_df["unique_id"].unique()) if "unique_id" in forecast_df.columns else 1,
        "forecast": forecasts,
        "metrics": {
            "training_time_s": elapsed,
            "data_points": len(df),
            "models_used": [type(m).__name__ for m in models],
        },
    }


def main():
    """Read JSON from stdin, run neural forecast, write JSON to stdout."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({"ok": False, "error": "Empty input"}))
            sys.exit(1)

        payload = json.loads(raw)
        command = payload.get("command", "forecast")

        if command == "forecast":
            data = payload.get("data", [])
            if not data:
                print(json.dumps({"ok": False, "error": "No data provided"}))
                sys.exit(1)

            result = run_neural_forecast(
                data=data,
                horizon=payload.get("horizon", 48),
                model_type=payload.get("model", "nhits"),
                freq=payload.get("freq", "h"),
                save_model=payload.get("save_model", False),
                model_dir=payload.get("model_dir", "data/neural_models"),
            )
        else:
            result = {"ok": False, "error": f"Unknown command: {command}"}

        print(json.dumps(result))

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "traceback": traceback.format_exc()}))
        sys.exit(1)


if __name__ == "__main__":
    main()
