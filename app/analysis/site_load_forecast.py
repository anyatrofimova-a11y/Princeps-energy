"""Site-load forecast wrapper.

Delegates to BOT-L's ``app.forecast.site_load`` if present; otherwise falls
back to an analytical estimate keyed by site typology (solar / bess / dc).
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Any

from app.analysis.types import (
    Analysis,
    Horizon,
    ProvenanceEntry,
    Scenario,
    coerce_horizon,
    coerce_scenario,
    degraded,
    truncate,
    utcnow,
)

log = logging.getLogger("princeps.analysis.site_load_forecast")

# Analytical fallback: per-MW annual load factor by typology
TYPOLOGY_LOAD_FACTOR = {
    "dc": 0.85,        # datacentre: near-flat
    "data_centre": 0.85,
    "datacentre": 0.85,
    "bess": 0.25,      # battery: cycling
    "solar": 0.12,     # UK central solar capacity factor ~11-12%
    "wind": 0.28,
    "hybrid": 0.35,
    "default": 0.30,
}

HOURS_PER_YEAR = 8760.0


async def site_load_forecast(
    site: Any,
    horizon: str | Horizon = Horizon.YEAR,
    scenario: str | Scenario = Scenario.CENTRAL,
    *,
    pool=None,
) -> Analysis:
    """Forecast site net load in MW (mean) with P10/P90 band."""

    site_id = _extract_id(site)
    target_key = f"site:{site_id}"
    horizon_e = coerce_horizon(horizon)
    scenario_e = coerce_scenario(scenario)

    mod = _load_bot_l_module()
    if mod is not None and hasattr(mod, "forecast"):
        try:
            result = await _call_bot_l(mod, site, horizon_e, scenario_e, pool)
            if isinstance(result, Analysis):
                return result
            if isinstance(result, dict):
                return _dict_to_analysis(result, target_key, horizon_e, scenario_e)
        except Exception as e:  # noqa: BLE001
            log.exception("BOT-L site_load forecast failed, falling back: %s", e)

    return _analytical_fallback(site, target_key, horizon_e, scenario_e)


# ── BOT-L detection ─────────────────────────────────────────────────────

_MODULE_PATH = os.path.join(os.path.dirname(__file__), "..", "forecast", "site_load.py")


def _load_bot_l_module():
    if not os.path.exists(os.path.abspath(_MODULE_PATH)):
        return None
    try:
        return importlib.import_module("app.forecast.site_load")
    except Exception as e:  # noqa: BLE001
        log.warning("app.forecast.site_load present but import failed: %s", e)
        return None


async def _call_bot_l(mod, site, horizon: Horizon, scenario: Scenario, pool):
    fn = getattr(mod, "forecast")
    import inspect
    if inspect.iscoroutinefunction(fn):
        return await fn(site, horizon=horizon.value, scenario=scenario.value, pool=pool)
    return fn(site, horizon=horizon.value, scenario=scenario.value, pool=pool)


def _dict_to_analysis(d: dict, target_key: str, horizon: Horizon, scenario: Scenario) -> Analysis:
    prov_raw = d.get("provenance") or []
    prov: list[ProvenanceEntry] = []
    for p in prov_raw:
        if isinstance(p, ProvenanceEntry):
            prov.append(p)
        elif isinstance(p, dict):
            prov.append(ProvenanceEntry(
                source=p.get("source", "bot-l"),
                kind=p.get("kind", "live"),
                age_s=p.get("age_s"),
                detail=p.get("detail"),
            ))
    return Analysis(
        value=d.get("value"),
        p10=d.get("p10"),
        p50=d.get("p50", d.get("value")),
        p90=d.get("p90"),
        confidence=float(d.get("confidence", 0.5)),
        explanation=truncate(d.get("explanation", "bot-l forecast")),
        provenance=prov or [ProvenanceEntry(source="app.forecast.site_load", kind="live", detail="bot-l")],
        computed_utc=utcnow(),
        kind="site_load_forecast",
        target_key=target_key,
        units=d.get("units", "MW"),
    )


# ── Analytical fallback ─────────────────────────────────────────────────

def _analytical_fallback(site: Any, target_key: str, horizon: Horizon, scenario: Scenario) -> Analysis:
    typology, capacity_mw = _extract_typology_capacity(site)
    if capacity_mw is None or capacity_mw <= 0:
        return degraded(
            "site_load_forecast", target_key,
            "no capacity_mw on site object; cannot fall back analytically",
            units="MW",
        )

    lf = TYPOLOGY_LOAD_FACTOR.get(typology, TYPOLOGY_LOAD_FACTOR["default"])
    # Scenario skew: +/- 10% around central for pathway stretch
    skew = {
        Scenario.LEADING_THE_WAY: 1.10,
        Scenario.CONSUMER_TRANSFORMATION: 1.05,
        Scenario.SYSTEM_TRANSFORMATION: 1.03,
        Scenario.FALLING_SHORT: 0.92,
    }.get(scenario, 1.0)

    p50 = capacity_mw * lf * skew
    band = p50 * (0.15 if horizon == Horizon.YEAR else 0.10 if horizon == Horizon.MONTH else 0.08)

    explanation = truncate(
        f"Analytical fallback (BOT-L module absent). {typology} @ {capacity_mw:.1f} MW "
        f"* load factor {lf:.2f} * scenario skew {skew:.2f} = {p50:.2f} MW mean "
        f"({horizon.value}, {scenario.value})."
    )

    return Analysis(
        value=p50,
        p10=max(0.0, p50 - band),
        p50=p50,
        p90=p50 + band,
        confidence=0.45,
        explanation=explanation,
        provenance=[ProvenanceEntry(
            source="analytical_fallback", kind="synthetic",
            detail=f"typology={typology} lf={lf} skew={skew}",
        )],
        computed_utc=utcnow(),
        kind="site_load_forecast",
        target_key=target_key,
        units="MW",
    )


def _extract_id(site: Any) -> str:
    if isinstance(site, str):
        return site
    for attr in ("id", "site_id", "external_id"):
        v = getattr(site, attr, None)
        if v:
            return str(v)
    data = getattr(site, "data", None)
    if isinstance(data, dict):
        for k in ("id", "site_id"):
            if data.get(k):
                return str(data[k])
    raise ValueError("cannot extract site id")


def _extract_typology_capacity(site: Any) -> tuple[str, float | None]:
    typology = "default"
    capacity = None
    data = getattr(site, "data", None) if not isinstance(site, (str, dict)) else (site if isinstance(site, dict) else {})
    for src in (data, getattr(site, "__dict__", None)):
        if not isinstance(src, dict):
            continue
        t = src.get("typology") or src.get("site_type") or src.get("technology")
        if t:
            typology = str(t).lower()
        for k in ("capacity_mw", "design_capacity_mw", "peak_mw", "it_load_mw"):
            if src.get(k) is not None:
                try:
                    capacity = float(src[k])
                    break
                except (TypeError, ValueError):
                    pass
        if capacity is not None:
            break
    return typology, capacity
