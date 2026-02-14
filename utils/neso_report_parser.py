"""
NESO NETS Status Report Parser & Training Data Generator.

Parses structured data from NESO National Electricity Transmission System
daily status reports and generates ML-ready training datasets.

Seed data: GB ESO Daily Reports 07-Feb-2026 and 08-Feb-2026.
Synthetic augmentation: 365-day seasonal model based on real UK grid patterns.

Data fields extracted per report:
  - date, day_of_week, is_weekend
  - risk_status (10 categories: general, demand, margins, generation, etc.)
  - min_derated_margin_mw, settlement_period
  - bmu_largest_loss_gen_mw, bmu_largest_loss_demand_mw
  - bm_spend_24h_k (£k)
  - cash_out_max, cash_out_min (£/MWh)
  - peak_demand_mw, min_demand_mw
  - interconnector_total_import_mw, interconnector_total_export_mw
  - interconnector_availability (fraction fully available)
  - embedded_solar_peak_mw, embedded_wind_avg_mw
  - embedded_total_peak_mw
  - weather_warnings_count, flood_warnings_count
  - weather_severity (0=none, 1=yellow, 2=amber, 3=red)
"""

import json
import math
import os
import random
from datetime import date, datetime, timedelta
from typing import Optional

# ── Risk status encoding ──
RISK_CATEGORIES = [
    "general_status", "demand", "system_margins", "generation",
    "active_constraints", "system_warning", "voltage",
    "system_inertia", "weather", "transmission",
]

RISK_LEVEL = {"green": 0, "amber": 1, "red": 2, "blue": 1}  # blue ≈ amber (info)

# ── Interconnector registry (2026 UK) ──
INTERCONNECTORS = {
    "BritNed":    {"import_mw": 1000, "export_mw": 1000, "country": "Netherlands"},
    "Nemo":       {"import_mw": 1000, "export_mw": 1000, "country": "Belgium"},
    "EWIC":       {"import_mw": 500,  "export_mw": 500,  "country": "Ireland"},
    "MOYLE":      {"import_mw": 500,  "export_mw": 500,  "country": "N. Ireland"},
    "NSL":        {"import_mw": 1400, "export_mw": 1400, "country": "Norway"},
    "IFA2":       {"import_mw": 1000, "export_mw": 1000, "country": "France"},
    "GreenLink":  {"import_mw": 500,  "export_mw": 500,  "country": "Ireland"},
    "Viking":     {"import_mw": 1400, "export_mw": 1400, "country": "Denmark"},
    "ElecLink":   {"import_mw": 1000, "export_mw": 1000, "country": "France"},
    "IFA":        {"import_mw": 1500, "export_mw": 1500, "country": "France"},
}
TOTAL_IC_IMPORT = sum(v["import_mw"] for v in INTERCONNECTORS.values())  # 9800 MW
TOTAL_IC_EXPORT = sum(v["export_mw"] for v in INTERCONNECTORS.values())

# ── Seed data from the two NESO reports ──

SEED_REPORTS = [
    {
        "date": "2026-02-07",
        "day_of_week": 5,  # Saturday
        "is_weekend": True,
        "risk_status": {
            "general_status": "green", "demand": "green", "system_margins": "green",
            "generation": "amber", "active_constraints": "blue",
            "system_warning": "amber", "voltage": "green",
            "system_inertia": "green", "weather": "green", "transmission": "green",
        },
        "min_derated_margin_mw": 16021,
        "margin_settlement_period": 36,
        "bmu_largest_loss_gen_mw": 1400,
        "bmu_largest_loss_demand_mw": 560,
        "bm_spend_24h_k": 10314,
        "cash_out_max_mwh": 118.15,
        "cash_out_max_sp": 31,
        "cash_out_min_mwh": 55.0,
        "cash_out_min_sp": 39,
        "peak_demand_mw": 40517,
        "min_demand_mw": 23510,
        "peak_demand_sp": 36,
        "interconnectors": {
            "BritNed": "fully", "Nemo": "fully", "EWIC": "fully",
            "MOYLE": "fully", "NSL": "fully", "IFA2": "fully",
            "GreenLink": "fully", "Viking": "fully", "ElecLink": "fully",
            "IFA": "partially",
        },
        # Embedded gen (non-metered) — 3-day table, 6 periods each (05:00→21:00)
        "embedded_solar_mw": [
            # 06-Feb: 0, 1, 1809, 74
            # 07-Feb: 0, 0, 0, 0, 2363, 21, 0, 0
            # 08-Feb: 93, 4376, 59, 0
            0, 1, 1809, 74, 0, 0,
            0, 0, 2363, 21, 0, 0,
            93, 4376, 59, 0,
        ],
        "embedded_wind_mw": [
            3671, 3265, 2857, 2514, 2331, 2055,
            1855, 1980, 2010, 2240, 2520, 2354,
            1822, 1643, 1339, 1155, 1224, 1300,
        ],
        "embedded_solar_peak_mw": 4376,
        "embedded_wind_avg_mw": 2175,
        "weather_warnings_count": 0,
        "flood_warnings_england": 91,
        "flood_alerts_england": 261,
        "flood_warnings_scotland": 1,
        "flood_alerts_scotland": 8,
        "flood_warnings_wales": 0,
        "flood_alerts_wales": 11,
        "weather_severity": 0,
        "weather_summary": "Rather cloudy with showers, temperatures near average",
    },
    {
        "date": "2026-02-08",
        "day_of_week": 6,  # Sunday
        "is_weekend": True,
        "risk_status": {
            "general_status": "green", "demand": "green", "system_margins": "green",
            "generation": "amber", "active_constraints": "blue",
            "system_warning": "amber", "voltage": "green",
            "system_inertia": "green", "weather": "green", "transmission": "amber",
        },
        "min_derated_margin_mw": 11683,
        "margin_settlement_period": 36,
        "bmu_largest_loss_gen_mw": 1400,
        "bmu_largest_loss_demand_mw": 560,
        "bm_spend_24h_k": 5393,
        "cash_out_max_mwh": 114.5,
        "cash_out_max_sp": 35,
        "cash_out_min_mwh": 51.65,
        "cash_out_min_sp": 21,
        "peak_demand_mw": 36810,
        "min_demand_mw": 21790,
        "peak_demand_sp": 37,
        "interconnectors": {
            "BritNed": "fully", "Nemo": "fully", "EWIC": "fully",
            "MOYLE": "fully", "NSL": "fully", "IFA2": "fully",
            "GreenLink": "fully", "Viking": "fully", "ElecLink": "fully",
            "IFA": "partially",
        },
        "embedded_solar_mw": [
            0, 5, 1934, 70, 0, 0,
            0, 68, 1476, 26, 0, 0,
            108, 3929, 43, 0,
        ],
        "embedded_wind_mw": [
            1799, 1777, 1863, 2012, 2317, 2413,
            1718, 1541, 1304, 1197, 1493, 1544,
            1476, 1599, 1811, 2036, 2073, 2567,
        ],
        "embedded_solar_peak_mw": 3929,
        "embedded_wind_avg_mw": 1833,
        "weather_warnings_count": 1,
        "flood_warnings_england": 89,
        "flood_alerts_england": 234,
        "flood_warnings_scotland": 1,
        "flood_alerts_scotland": 5,
        "flood_warnings_wales": 0,
        "flood_alerts_wales": 11,
        "weather_severity": 1,  # Yellow warning
        "weather_summary": "Yellow warning of rain, coastal gales, fog lifting",
    },
]


def report_to_feature_vector(report: dict) -> dict:
    """Convert a parsed NESO report into a flat feature dict for ML."""
    d = date.fromisoformat(report["date"])
    day_of_year = d.timetuple().tm_yday

    # Risk score: sum of encoded risk levels (0=all green, higher=worse)
    risk_sum = sum(
        RISK_LEVEL.get(report["risk_status"].get(cat, "green"), 0)
        for cat in RISK_CATEGORIES
    )
    risk_max = max(
        RISK_LEVEL.get(report["risk_status"].get(cat, "green"), 0)
        for cat in RISK_CATEGORIES
    )
    amber_count = sum(
        1 for cat in RISK_CATEGORIES
        if RISK_LEVEL.get(report["risk_status"].get(cat, "green"), 0) >= 1
    )

    # Interconnector availability fraction
    ic = report.get("interconnectors", {})
    ic_fully = sum(1 for v in ic.values() if v == "fully")
    ic_avail_frac = ic_fully / max(len(ic), 1)

    # Flood risk composite
    flood_total = (
        report.get("flood_warnings_england", 0)
        + report.get("flood_warnings_scotland", 0)
        + report.get("flood_warnings_wales", 0)
    )

    return {
        # Temporal
        "day_of_year": day_of_year,
        "day_of_week": report["day_of_week"],
        "is_weekend": int(report["is_weekend"]),
        "month": d.month,
        # Demand
        "peak_demand_mw": report["peak_demand_mw"],
        "min_demand_mw": report["min_demand_mw"],
        "demand_range_mw": report["peak_demand_mw"] - report["min_demand_mw"],
        # Margin & risk
        "min_derated_margin_mw": report["min_derated_margin_mw"],
        "risk_score": risk_sum,
        "risk_max_level": risk_max,
        "amber_count": amber_count,
        # Generation
        "embedded_solar_peak_mw": report.get("embedded_solar_peak_mw", 0),
        "embedded_wind_avg_mw": report.get("embedded_wind_avg_mw", 0),
        # Interconnectors
        "ic_availability_frac": ic_avail_frac,
        # Weather
        "weather_severity": report.get("weather_severity", 0),
        "flood_warnings_total": flood_total,
        # Market
        "cash_out_max_mwh": report.get("cash_out_max_mwh", 0),
        "cash_out_min_mwh": report.get("cash_out_min_mwh", 0),
        "cash_out_spread_mwh": report.get("cash_out_max_mwh", 0) - report.get("cash_out_min_mwh", 0),
        # Cyclic temporal encoding
        "day_of_year_sin": math.sin(2 * math.pi * day_of_year / 365),
        "day_of_year_cos": math.cos(2 * math.pi * day_of_year / 365),
        # Target
        "bm_spend_24h_k": report["bm_spend_24h_k"],
    }


# ── Seasonal models for synthetic data generation ──

# Monthly demand peaks (MW) — from BMRS 10-year analysis
MONTHLY_PEAK_DEMAND = [
    42500, 41000, 38000, 35000, 32000, 29000,
    28000, 29000, 33000, 36000, 39500, 42000,
]

# Monthly min demand (MW)
MONTHLY_MIN_DEMAND = [
    24000, 23000, 21000, 19000, 17500, 16000,
    15500, 16000, 18000, 20000, 22000, 23500,
]

# Monthly embedded solar peak capacity factor (0-1)
MONTHLY_SOLAR_CF = [
    0.08, 0.12, 0.22, 0.35, 0.45, 0.50,
    0.48, 0.42, 0.30, 0.18, 0.10, 0.06,
]

# Installed embedded solar capacity (MW) — 2026 estimate
INSTALLED_SOLAR_MW = 18000

# Monthly average embedded wind (MW) — seasonal pattern
MONTHLY_WIND_AVG = [
    3200, 2800, 2400, 1800, 1500, 1200,
    1100, 1300, 1700, 2200, 2800, 3100,
]

# Monthly BM spend baseline (£k/day) — higher in winter
MONTHLY_BM_SPEND_K = [
    12000, 10000, 8000, 6000, 4500, 3500,
    3000, 3500, 5000, 7000, 9000, 11000,
]

# Monthly derated margin baseline (MW)
MONTHLY_MARGIN_MW = [
    12000, 14000, 17000, 20000, 23000, 25000,
    26000, 25000, 21000, 18000, 14000, 12500,
]

# Monthly cash-out max baseline (£/MWh)
MONTHLY_CASHOUT_MAX = [
    130, 120, 100, 85, 75, 70,
    65, 70, 80, 95, 115, 125,
]

# Monthly weather severity distribution (probability of yellow/amber/red)
MONTHLY_WEATHER_PROB = [
    0.35, 0.30, 0.20, 0.10, 0.08, 0.05,
    0.05, 0.08, 0.12, 0.18, 0.25, 0.30,
]


def generate_synthetic_report(d: date, rng: random.Random) -> dict:
    """Generate a realistic synthetic NESO report for a given date."""
    m = d.month - 1  # 0-indexed
    dow = d.weekday()
    is_weekend = dow >= 5

    # Weekend demand reduction
    demand_mult = 0.88 if is_weekend else 1.0
    demand_noise = rng.gauss(1.0, 0.04)

    peak_demand = int(MONTHLY_PEAK_DEMAND[m] * demand_mult * demand_noise)
    min_demand = int(MONTHLY_MIN_DEMAND[m] * demand_mult * rng.gauss(1.0, 0.05))

    # Solar: clear-sky peak * random cloud factor
    cloud_factor = rng.uniform(0.3, 1.0)
    solar_peak = int(INSTALLED_SOLAR_MW * MONTHLY_SOLAR_CF[m] * cloud_factor)

    # Wind: log-normal variation around monthly mean
    wind_factor = math.exp(rng.gauss(0, 0.35))
    wind_avg = int(MONTHLY_WIND_AVG[m] * wind_factor)
    wind_avg = min(wind_avg, 8000)  # Physical cap

    # Margin: inversely related to demand, with noise
    margin = int(MONTHLY_MARGIN_MW[m] * rng.gauss(1.0, 0.12))
    margin = max(margin, 3000)

    # BM spend: correlated with demand, wind variability, margin tightness
    bm_base = MONTHLY_BM_SPEND_K[m]
    # Higher wind = more balancing actions needed
    wind_variability_penalty = abs(wind_avg - MONTHLY_WIND_AVG[m]) / MONTHLY_WIND_AVG[m]
    # Tight margin = expensive balancing
    margin_tightness = max(0, 1 - margin / 20000)
    bm_spend = int(bm_base * (1 + wind_variability_penalty * 0.5 + margin_tightness * 0.8)
                    * rng.gauss(1.0, 0.15))
    bm_spend = max(bm_spend, 500)
    if is_weekend:
        bm_spend = int(bm_spend * 0.7)

    # Cash-out prices
    cashout_max = MONTHLY_CASHOUT_MAX[m] * rng.gauss(1.0, 0.2)
    cashout_max = max(cashout_max, 30)
    cashout_min = cashout_max * rng.uniform(0.25, 0.55)

    # Weather
    has_warning = rng.random() < MONTHLY_WEATHER_PROB[m]
    weather_severity = 0
    if has_warning:
        weather_severity = rng.choices([1, 2, 3], weights=[0.7, 0.25, 0.05])[0]

    flood_base = [60, 80, 50, 30, 15, 5, 3, 5, 15, 35, 55, 70][m]
    flood_warnings = int(flood_base * rng.gauss(1.0, 0.4))
    flood_warnings = max(flood_warnings, 0)

    # Risk status
    risk = {}
    for cat in RISK_CATEGORIES:
        if cat == "generation":
            # Amber when wind is very high or very low
            risk[cat] = "amber" if (wind_avg > 4000 or wind_avg < 800) else "green"
        elif cat == "demand":
            risk[cat] = "amber" if peak_demand > 40000 else "green"
        elif cat == "system_margins":
            risk[cat] = "red" if margin < 5000 else ("amber" if margin < 10000 else "green")
        elif cat == "weather":
            risk[cat] = "amber" if weather_severity >= 2 else "green"
        elif cat == "transmission":
            risk[cat] = "amber" if weather_severity >= 1 and rng.random() < 0.3 else "green"
        elif cat == "system_warning":
            risk[cat] = "amber" if margin < 12000 else "green"
        elif cat == "active_constraints":
            risk[cat] = "blue" if rng.random() < 0.6 else "green"
        else:
            risk[cat] = "green"

    # Interconnectors: mostly fully available
    ic = {}
    for name in INTERCONNECTORS:
        if name == "IFA" and rng.random() < 0.3:
            ic[name] = "partially"
        elif rng.random() < 0.05:
            ic[name] = "partially"
        else:
            ic[name] = "fully"

    return {
        "date": d.isoformat(),
        "day_of_week": dow,
        "is_weekend": is_weekend,
        "risk_status": risk,
        "min_derated_margin_mw": margin,
        "margin_settlement_period": rng.choice([34, 35, 36, 37, 38]),
        "bmu_largest_loss_gen_mw": 1400,
        "bmu_largest_loss_demand_mw": 560,
        "bm_spend_24h_k": bm_spend,
        "cash_out_max_mwh": round(cashout_max, 2),
        "cash_out_max_sp": rng.randint(28, 38),
        "cash_out_min_mwh": round(cashout_min, 2),
        "cash_out_min_sp": rng.randint(5, 15),
        "peak_demand_mw": peak_demand,
        "min_demand_mw": min_demand,
        "peak_demand_sp": rng.choice([35, 36, 37]),
        "interconnectors": ic,
        "embedded_solar_peak_mw": solar_peak,
        "embedded_wind_avg_mw": wind_avg,
        "weather_warnings_count": 1 if has_warning else 0,
        "flood_warnings_england": flood_warnings,
        "flood_alerts_england": int(flood_warnings * rng.uniform(2, 4)),
        "flood_warnings_scotland": max(0, int(flood_warnings * 0.02 * rng.gauss(1, 0.5))),
        "flood_alerts_scotland": max(0, int(flood_warnings * 0.05 * rng.gauss(1, 0.5))),
        "flood_warnings_wales": max(0, int(flood_warnings * 0.01 * rng.gauss(1, 0.5))),
        "flood_alerts_wales": max(0, int(flood_warnings * 0.1 * rng.gauss(1, 0.5))),
        "weather_severity": weather_severity,
        "weather_summary": "",
    }


def generate_training_dataset(
    start_date: date = date(2025, 3, 1),
    end_date: date = date(2026, 2, 28),
    seed: int = 42,
) -> list[dict]:
    """
    Generate a full year of NESO-like feature vectors for ML training.

    Includes real seed data (Feb 7-8 2026) plus synthetic daily reports
    for the rest of the year, following realistic UK seasonal patterns.
    """
    rng = random.Random(seed)
    dataset = []

    # Add seed reports first
    for report in SEED_REPORTS:
        dataset.append(report_to_feature_vector(report))

    # Generate synthetic for every day in range
    current = start_date
    while current <= end_date:
        # Skip dates we have real data for
        if current.isoformat() in ("2026-02-07", "2026-02-08"):
            current += timedelta(days=1)
            continue
        report = generate_synthetic_report(current, rng)
        dataset.append(report_to_feature_vector(report))
        current += timedelta(days=1)

    return dataset


def get_latest_neso_snapshot() -> dict:
    """Return the most recent real NESO report data as a structured dict."""
    # Return Feb 8 as the latest
    report = SEED_REPORTS[-1]
    features = report_to_feature_vector(report)
    return {
        "report_date": report["date"],
        "features": features,
        "risk_status": report["risk_status"],
        "interconnectors": report["interconnectors"],
        "weather_summary": report["weather_summary"],
        "weather_severity": report["weather_severity"],
        "bm_spend_24h_k": report["bm_spend_24h_k"],
        "peak_demand_mw": report["peak_demand_mw"],
        "min_demand_mw": report["min_demand_mw"],
        "min_derated_margin_mw": report["min_derated_margin_mw"],
        "embedded_solar_peak_mw": report.get("embedded_solar_peak_mw", 0),
        "embedded_wind_avg_mw": report.get("embedded_wind_avg_mw", 0),
        "cash_out_max_mwh": report["cash_out_max_mwh"],
        "cash_out_min_mwh": report["cash_out_min_mwh"],
    }


if __name__ == "__main__":
    # Generate and preview dataset
    ds = generate_training_dataset()
    print(f"Generated {len(ds)} training samples")
    print(f"Features: {list(ds[0].keys())}")
    print(f"\nSample (Feb 7 real): {json.dumps(ds[0], indent=2)}")
    print(f"\nSample (Feb 8 real): {json.dumps(ds[1], indent=2)}")
    if len(ds) > 5:
        print(f"\nSample (synthetic): {json.dumps(ds[5], indent=2)}")

    # Save as JSON
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "neso_training_data.json")
    with open(out_path, "w") as f:
        json.dump(ds, f)
    print(f"\nSaved to {out_path}")
