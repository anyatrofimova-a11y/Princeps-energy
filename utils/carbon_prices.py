"""
elmada wrapper — marginal emissions and wholesale electricity prices.
Caches DataFrames as parquet in data/elmada_cache/.
"""

import json
import os
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "elmada_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(prefix: str, year: int, country: str) -> Path:
    return CACHE_DIR / f"{prefix}_{country}_{year}.parquet"


def get_marginal_emissions(year: int = 2025, country: str = "GB") -> list[dict]:
    """Return hourly marginal emission factors (gCO2/kWh) using elmada MEF method."""
    cache = _cache_path("emissions", year, country)
    try:
        import pandas as pd
        if cache.exists():
            df = pd.read_parquet(cache)
        else:
            import elmada
            df = elmada.get_emissions(year, country=country, method="MEF")
            if isinstance(df, pd.Series):
                df = df.to_frame(name="marginal_emissions_gCO2_kWh")
            df.to_parquet(cache)
        records = []
        for idx, row in df.iterrows():
            val = row.iloc[0] if hasattr(row, "iloc") else row
            records.append({
                "timestamp": str(idx),
                "marginal_emissions_gCO2_kWh": float(val),
            })
        return records
    except ImportError:
        return [{"error": "elmada not installed — pip install elmada"}]
    except Exception as e:
        return [{"error": f"elmada emissions failed: {e}"}]


def get_wholesale_prices(year: int = 2025, country: str = "GB") -> list[dict]:
    """Return hourly wholesale electricity prices (EUR/MWh) using elmada."""
    cache = _cache_path("prices", year, country)
    try:
        import pandas as pd
        if cache.exists():
            df = pd.read_parquet(cache)
        else:
            import elmada
            df = elmada.get_prices(year, country=country)
            if isinstance(df, pd.Series):
                df = df.to_frame(name="price_eur_mwh")
            df.to_parquet(cache)
        records = []
        for idx, row in df.iterrows():
            val = row.iloc[0] if hasattr(row, "iloc") else row
            records.append({
                "timestamp": str(idx),
                "price_eur_mwh": float(val),
            })
        return records
    except ImportError:
        return [{"error": "elmada not installed — pip install elmada"}]
    except Exception as e:
        return [{"error": f"elmada prices failed: {e}"}]


def get_carbon_summary(year: int = 2025) -> dict:
    """Return summary stats for both emissions and prices."""
    emissions = get_marginal_emissions(year)
    prices = get_wholesale_prices(year)

    def _stats(data: list[dict], key: str) -> dict:
        vals = [d[key] for d in data if key in d]
        if not vals:
            return {"error": "no data"}
        vals_sorted = sorted(vals)
        n = len(vals)
        return {
            "count": n,
            "mean": round(sum(vals) / n, 2),
            "min": round(vals_sorted[0], 2),
            "max": round(vals_sorted[-1], 2),
            "median": round(vals_sorted[n // 2], 2),
        }

    return {
        "year": year,
        "country": "GB",
        "emissions": _stats(emissions, "marginal_emissions_gCO2_kWh"),
        "prices": _stats(prices, "price_eur_mwh"),
    }
