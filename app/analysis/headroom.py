"""Headroom analysis — available MW at a substation or GSP."""

from __future__ import annotations

import logging
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

log = logging.getLogger("princeps.analysis.headroom")

POWER_FACTOR = 0.95
HORIZON_BAND_PCT = {
    Horizon.DAY_AHEAD: 0.05,
    Horizon.WEEK: 0.08,
    Horizon.MONTH: 0.12,
    Horizon.YEAR: 0.18,
    Horizon.DECADE: 0.30,
}


async def headroom(
    substation: Any,
    horizon: str | Horizon = Horizon.DAY_AHEAD,
    scenario: str | Scenario = Scenario.CENTRAL,
    *,
    pool=None,
) -> Analysis:
    """Headroom MW for a substation or GSP.

    ``substation`` accepts an ontology Object with ``.id`` / ``.key()`` or a
    bare string id. A ``gsp:`` prefix routes to the GSP table.
    """

    target_id = _extract_id(substation)
    horizon_e = coerce_horizon(horizon)
    scenario_e = coerce_scenario(scenario)
    target_key = f"gsp:{target_id.removeprefix('gsp:')}" if target_id.startswith("gsp:") else f"substation:{target_id}"

    if pool is None:
        return degraded("headroom", target_key, "no db pool", units="MW")

    prov: list[ProvenanceEntry] = []
    try:
        async with pool.acquire() as conn:
            cap_row, name, is_gsp = await _load_capacity(conn, target_id, prov)
            if cap_row is None:
                return degraded("headroom", target_key, "target not found", units="MW", provenance=prov)

            capacity_mva = float(cap_row or 0.0)
            accepted_mw = await _load_accepted_queue(conn, target_id, is_gsp, prov)
            forecast_mw, forecast_band = await _load_demand_forecast(
                conn, target_id, is_gsp, horizon_e, scenario_e, prov,
            )

        usable_mw = capacity_mva * POWER_FACTOR
        p50 = max(0.0, usable_mw - forecast_mw - accepted_mw)
        band_pct = HORIZON_BAND_PCT.get(horizon_e, 0.15)
        band = max(p50 * band_pct, forecast_band)
        p10 = max(0.0, p50 - band)
        p90 = p50 + band

        have_capacity = capacity_mva > 0
        have_forecast = forecast_mw > 0
        confidence = 0.85 if (have_capacity and have_forecast) else 0.55 if have_capacity else 0.2

        explanation = truncate(
            f"{name or target_id}: capacity {capacity_mva:.1f} MVA * pf {POWER_FACTOR} "
            f"= {usable_mw:.1f} MW usable; minus forecast demand {forecast_mw:.1f} MW "
            f"({scenario_e.value}/{horizon_e.value}) and accepted queue {accepted_mw:.1f} MW; "
            f"headroom p50 {p50:.1f} MW (band +/- {band:.1f} MW)."
        )

        return Analysis(
            value=p50,
            p10=p10,
            p50=p50,
            p90=p90,
            confidence=confidence,
            explanation=explanation,
            provenance=prov,
            computed_utc=utcnow(),
            kind="headroom",
            target_key=target_key,
            units="MW",
        )
    except Exception as e:  # noqa: BLE001
        log.exception("headroom failed: %s", e)
        prov.append(ProvenanceEntry(source="headroom", kind="missing", detail=f"{type(e).__name__}: {e}"))
        return degraded("headroom", target_key, f"error {type(e).__name__}", units="MW", provenance=prov)


# Backwards-compatible alias for callers importing ``analyse_headroom``.
async def analyse_headroom(
    target_id: str,
    horizon: str = "day_ahead",
    scenario: str = "central",
    *,
    pool=None,
) -> Analysis:
    return await headroom(target_id, horizon, scenario, pool=pool)


# ── internals ────────────────────────────────────────────────────────────

def _extract_id(substation: Any) -> str:
    if isinstance(substation, str):
        return substation
    for attr in ("external_id", "id"):
        v = getattr(substation, attr, None)
        if v:
            return str(v)
    key = getattr(substation, "key", None)
    if callable(key):
        k = key()
        if isinstance(k, str) and ":" in k:
            return k.split(":", 1)[1]
    data = getattr(substation, "data", None)
    if isinstance(data, dict):
        for k in ("external_id", "substation_id", "id"):
            if data.get(k):
                return str(data[k])
    raise ValueError("cannot extract substation id")


async def _load_capacity(conn, target_id: str, prov: list[ProvenanceEntry]):
    if target_id.startswith("gsp:"):
        gsp = target_id.removeprefix("gsp:")
        row = await conn.fetchrow(
            "SELECT peak_demand_mw AS cap, name FROM gsp_profiles WHERE gsp_id = $1",
            gsp,
        )
        if row:
            prov.append(ProvenanceEntry(source="gsp_profiles", kind="cached", detail=f"gsp={gsp}"))
            return row["cap"], row["name"], True
        prov.append(ProvenanceEntry(source="gsp_profiles", kind="missing", detail=f"gsp={gsp}"))
        return None, None, True

    row = await conn.fetchrow(
        """SELECT transformer_rating_mva AS cap, name, updated_at
           FROM grid_substations WHERE external_id = $1""",
        target_id,
    )
    if row:
        age = None
        if row.get("updated_at"):
            age = (utcnow() - row["updated_at"]).total_seconds()
        prov.append(ProvenanceEntry(source="grid_substations", kind="cached", age_s=age, detail=target_id))
        return row["cap"], row["name"], False
    prov.append(ProvenanceEntry(source="grid_substations", kind="missing", detail=target_id))
    return None, None, False


async def _load_accepted_queue(conn, target_id: str, is_gsp: bool, prov: list[ProvenanceEntry]) -> float:
    if is_gsp:
        return 0.0
    try:
        row = await conn.fetchrow(
            """SELECT COALESCE(SUM(e.capacity_mw), 0)::float AS mw
               FROM grid_ecr e
               JOIN grid_substations s ON s.id = e.substation_id
               WHERE s.external_id = $1 AND e.status = 'accepted'""",
            target_id,
        )
        mw = float(row["mw"] or 0.0) if row else 0.0
        prov.append(ProvenanceEntry(source="grid_ecr", kind="cached", detail=f"accepted={mw:.1f}MW"))
        return mw
    except Exception as e:  # noqa: BLE001
        prov.append(ProvenanceEntry(source="grid_ecr", kind="missing", detail=str(e)[:80]))
        return 0.0


async def _load_demand_forecast(
    conn, target_id: str, is_gsp: bool, horizon: Horizon, scenario: Scenario,
    prov: list[ProvenanceEntry],
) -> tuple[float, float]:
    gsp = target_id.removeprefix("gsp:") if is_gsp else target_id
    try:
        row = await conn.fetchrow(
            """SELECT p10_mw, p50_mw, p90_mw, timestamp_utc
               FROM demand_forecasts
               WHERE gsp_id = $1 AND scenario = $2
               ORDER BY timestamp_utc DESC LIMIT 1""",
            gsp, scenario.value,
        )
        if row and row["p50_mw"] is not None:
            p50 = float(row["p50_mw"])
            band = max(abs(p50 - float(row["p10_mw"] or p50)), abs(float(row["p90_mw"] or p50) - p50))
            age = (utcnow() - row["timestamp_utc"]).total_seconds() if row.get("timestamp_utc") else None
            prov.append(ProvenanceEntry(
                source="demand_forecasts", kind="cached", age_s=age,
                detail=f"scenario={scenario.value} p50={p50:.1f}MW",
            ))
            return p50, band
    except Exception as e:  # noqa: BLE001
        prov.append(ProvenanceEntry(source="demand_forecasts", kind="missing", detail=str(e)[:80]))
    prov.append(ProvenanceEntry(source="demand_forecasts", kind="missing", detail="no forecast row"))
    return 0.0, 0.0
