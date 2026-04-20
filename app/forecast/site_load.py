"""forecast_site_load — main entry point.

Composes typology + behind-meter overlays into a median forecast, then (best
effort) wraps Prophet/TFT uncertainty from utils/demand_forecaster.py around
the median. If the subprocess is unavailable we fall back to analytical P10/P90
bands derived from typology variance + horizon-scaled uncertainty growth.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.forecast.types import (
    ForecastResult,
    Horizon,
    Interval,
    Scenario,
    HORIZON_CONFIG,
)
from app.forecast.sic_typology import (
    Typology,
    get_typology,
    gross_profile,
    DEFAULT_TYPOLOGY_KEY,
    SIC_TYPOLOGIES,
)
from app.forecast.behind_meter import BehindMeterAssets, apply_behind_meter


# ---------------------------------------------------------------------------
# Subprocess bridge (best-effort call to utils/demand_forecaster.py)
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[2]
_FORECAST_PY = str(_ROOT / ".venv-forecast" / "bin" / "python")
_FORECAST_SCRIPT = str(_ROOT / "utils" / "demand_forecaster.py")


async def _call_forecast_subprocess(payload: dict, timeout: float = 30.0) -> dict:
    """Best-effort: call the Prophet/TFT subprocess. Returns {} on failure."""
    if not os.path.exists(_FORECAST_PY) or not os.path.exists(_FORECAST_SCRIPT):
        return {}
    try:
        proc = await asyncio.create_subprocess_exec(
            _FORECAST_PY, _FORECAST_SCRIPT,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        raw = json.dumps(payload).encode()
        stdout, _stderr = await asyncio.wait_for(
            proc.communicate(raw), timeout=timeout,
        )
        if proc.returncode != 0 or not stdout:
            return {}
        return json.loads(stdout.decode())
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _interval_minutes(interval: Interval) -> int:
    return {
        Interval.HALF_HOURLY: 30,
        Interval.HOURLY: 60,
        Interval.DAILY: 1440,
        Interval.ANNUAL: 0,   # sentinel — handled separately
    }[interval]


def _analytical_bands(median: list[float], typology_lf: float,
                      horizon_hours: int) -> tuple[list[float], list[float]]:
    """Horizon-scaled analytical P10/P90 bands.

    Uncertainty grows with √horizon and is inversely proportional to load
    factor (peakier → more uncertain)."""
    base = 0.07 + (1.0 - typology_lf) * 0.18
    # horizon uplift: 6h → 1.0, 168h → ~1.5, 8760h → ~3.5
    h_scale = (horizon_hours / 24.0) ** 0.3
    band = base * h_scale
    p10 = [round(v * max(0.0, 1.0 - band), 3) for v in median]
    p90 = [round(v * (1.0 + band), 3) for v in median]
    return p10, p90


def _scenario_multiplier(typ: Typology, scenario: Scenario,
                         years_out: float) -> float:
    """Annual-growth multiplier at `years_out` years from now."""
    g = typ.pathway_growth.get(scenario.value, typ.base_growth_pa)
    return (1.0 + g) ** years_out


def _generate_timestamps(steps: int, interval_min: int,
                          start: datetime, long_term: bool = False) -> list[str]:
    if long_term:
        return [str(start.year + i) for i in range(steps)]
    out = []
    for i in range(steps):
        t = start + timedelta(minutes=interval_min * i)
        out.append(t.replace(microsecond=0).isoformat())
    return out


def _long_term_annual(typ: Typology, peak_mw: float, scenario: Scenario,
                      years: int = 26) -> tuple[list[float], list[float], list[float], list[str]]:
    """Annual projection 2024..2050 (default 26 years)."""
    g = typ.pathway_growth.get(scenario.value, typ.base_growth_pa)
    # annual energy MWh assuming LF
    base_mwh = peak_mw * typ.load_factor * 8760
    p50 = [base_mwh * ((1.0 + g) ** i) for i in range(years)]
    # wider bands further out
    p10 = [v * (1.0 - 0.08 - 0.01 * i) for i, v in enumerate(p50)]
    p90 = [v * (1.0 + 0.08 + 0.012 * i) for i, v in enumerate(p50)]
    start_year = datetime.now(timezone.utc).year
    labels = [str(start_year + i) for i in range(years)]
    return (
        [round(v, 1) for v in p10],
        [round(v, 1) for v in p50],
        [round(v, 1) for v in p90],
        labels,
    )


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

async def forecast_site_load(
    site_id: str,
    horizon: str | Horizon = Horizon.DAY_AHEAD,
    scenario: str | Scenario = Scenario.CENTRAL,
    typology: str | None = None,
    peak_mw: float | None = None,
    behind_meter: BehindMeterAssets | None = None,
    use_subprocess: bool = True,
) -> ForecastResult:
    """Produce a ForecastResult for a site.

    Arguments are permissive: typology can be SIC code or slug; missing peak_mw
    defaults to 1.0 MW; missing behind-meter yields pure typology output.
    Always returns a ForecastResult — never raises for data issues.
    """
    # Normalise inputs --------------------------------------------------------
    if isinstance(horizon, str):
        try:
            horizon = Horizon(horizon)
        except ValueError:
            horizon = Horizon.DAY_AHEAD
    if isinstance(scenario, str):
        try:
            scenario = Scenario(scenario)
        except ValueError:
            scenario = Scenario.CENTRAL

    typ = get_typology(typology or DEFAULT_TYPOLOGY_KEY)
    peak_mw = float(peak_mw) if peak_mw is not None else 1.0
    if peak_mw <= 0:
        peak_mw = 1.0
    bm = behind_meter or BehindMeterAssets()
    notes: list[str] = []

    # Long-term branch --------------------------------------------------------
    if horizon == Horizon.LONG_TERM:
        years = 26
        p10, p50, p90, labels = _long_term_annual(typ, peak_mw, scenario, years)
        expl = (
            f"Annual energy projection {labels[0]}-{labels[-1]} under "
            f"NESO FES pathway '{scenario.value}' for typology "
            f"'{typ.name}' at {peak_mw:.1f} MW peak."
        )
        return ForecastResult(
            site_id=site_id,
            typology=typ.key,
            horizon=horizon.value,
            interval=Interval.ANNUAL.value,
            scenario=scenario.value,
            series_p10=p10, series_p50=p50, series_p90=p90,
            timestamps=labels,
            peak_mw_p50=round(peak_mw * typ.load_factor, 3),
            energy_mwh_p50=round(sum(p50), 1),
            confidence=0.55,
            explanation=expl[:399],
            provenance={
                "typology_source": "SIC_TYPOLOGIES",
                "pathway": scenario.value,
                "growth_pa": typ.pathway_growth.get(scenario.value, typ.base_growth_pa),
                "model": "analytical_annual",
                "notes": ["Long-term = annual energy MWh, not MW."],
            },
        )

    # Short/medium horizons ---------------------------------------------------
    horizon_hours, interval = HORIZON_CONFIG[horizon]
    interval_min = _interval_minutes(interval)
    steps = int(horizon_hours * 60 / interval_min)

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_hh_offset = (now.hour * 2) + (now.minute // 30)
    weekday_factor = 1.0 if now.weekday() < 5 else (1.0 / typ.weekday_weekend_ratio)

    # Gross typology load
    gross = gross_profile(
        typ, peak_mw=peak_mw, interval_min=interval_min,
        steps=steps, start_hh_offset=start_hh_offset,
        weekday_factor=weekday_factor,
    )

    # Behind-the-meter overlays
    net, bm_detail = apply_behind_meter(
        gross_load_mw=gross, assets=bm,
        interval_min=interval_min, start_hh_offset=start_hh_offset,
        peak_mw=peak_mw,
    )

    # Scenario scaling (short-horizon: small effect ~ fraction of year)
    years_out = horizon_hours / 8760.0
    mult = _scenario_multiplier(typ, scenario, years_out)
    median = [round(v * mult, 3) for v in net]

    # Try to wrap uncertainty via subprocess (Prophet quick_forecast)
    subprocess_ok = False
    upstream_model = "analytical"
    p10_band: list[float] | None = None
    p90_band: list[float] | None = None
    if use_subprocess and horizon_hours <= 720:
        sub_payload = {
            "command": "quick_forecast",
            "gsp_id": site_id,
            "peak_mw": peak_mw,
            "min_mw": peak_mw * typ.load_factor * 0.4,
            "capacity_mw": peak_mw * 1.2,
            "horizon_hours": int(horizon_hours),
        }
        sub_out = await _call_forecast_subprocess(sub_payload, timeout=25.0)
        if sub_out and sub_out.get("forecasts"):
            subprocess_ok = True
            upstream_model = sub_out.get("model", "analytical")
            fc = sub_out["forecasts"][: len(median)]
            if fc:
                # derive band fractions (p10/p50, p90/p50) from subprocess,
                # then apply to our typology median
                bands = []
                for row in fc:
                    p50 = row.get("p50_mw") or 1.0
                    if p50 <= 0:
                        bands.append((0.9, 1.1))
                    else:
                        lo = row.get("p10_mw", p50 * 0.9) / p50
                        hi = row.get("p90_mw", p50 * 1.1) / p50
                        bands.append((lo, hi))
                # stretch/shrink bands to match horizon length
                if len(bands) < len(median):
                    last = bands[-1]
                    bands = bands + [last] * (len(median) - len(bands))
                p10_band = [round(median[i] * bands[i][0], 3) for i in range(len(median))]
                p90_band = [round(median[i] * bands[i][1], 3) for i in range(len(median))]
                notes.append(f"Prophet bands via subprocess (n={len(fc)})")
        else:
            notes.append("Forecast subprocess unavailable; analytical bands used.")

    if p10_band is None or p90_band is None:
        p10_band, p90_band = _analytical_bands(median, typ.load_factor, horizon_hours)

    timestamps = _generate_timestamps(len(median), interval_min, now)

    peak_p50 = max(median) if median else 0.0
    energy_mwh = sum(median) * interval_min / 60.0

    # Confidence: higher for short horizons + subprocess + defined typology
    confidence = 0.45
    if subprocess_ok:
        confidence += 0.25
    if horizon_hours <= 168:
        confidence += 0.10
    if typology and typology.lower() in SIC_TYPOLOGIES:
        confidence += 0.10
    if bm.pv_mw == 0 and bm.bess_mw == 0 and bm.ev_penetration == 0 and bm.hp_penetration == 0:
        notes.append("No behind-meter assets supplied.")
    confidence = min(0.95, round(confidence, 2))

    explanation = (
        f"{typ.name} site ({peak_mw:.1f} MW peak) — "
        f"{horizon.value} forecast under '{scenario.value}'. "
        f"Peak P50 {peak_p50:.2f} MW, energy {energy_mwh:.1f} MWh. "
        f"Behind-meter: PV {bm.pv_mw} MW, BESS {bm.bess_mw} MW, "
        f"EV pen {bm.ev_penetration:.0%}, HP pen {bm.hp_penetration:.0%}."
    )

    provenance = {
        "typology_source": "SIC_TYPOLOGIES",
        "typology_key": typ.key,
        "upstream_model": upstream_model,
        "subprocess_ok": subprocess_ok,
        "scenario": scenario.value,
        "pathway_growth_pa": typ.pathway_growth.get(scenario.value, typ.base_growth_pa),
        "horizon_hours": horizon_hours,
        "interval_min": interval_min,
        "start_hh_offset": start_hh_offset,
        "weekday_factor": weekday_factor,
        "behind_meter": bm_detail,
        "notes": notes,
    }

    return ForecastResult(
        site_id=site_id,
        typology=typ.key,
        horizon=horizon.value,
        interval=interval.value,
        scenario=scenario.value,
        series_p10=p10_band,
        series_p50=median,
        series_p90=p90_band,
        timestamps=timestamps,
        peak_mw_p50=round(peak_p50, 3),
        energy_mwh_p50=round(energy_mwh, 2),
        confidence=confidence,
        explanation=explanation[:399],
        provenance=provenance,
    )
