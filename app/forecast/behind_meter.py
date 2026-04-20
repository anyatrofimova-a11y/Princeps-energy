"""Behind-the-meter asset overlays — PV, BESS, EV, heat pump penetration.

Takes a gross load curve (list[MW]) and applies:
- PV export: subtracts a solar generation profile (diurnal, clear-sky-weighted)
- BESS: shifts peak by charging off-peak, discharging at peak
- EV penetration: adds evening/overnight charging
- Heat pump penetration: adds winter-weighted morning+evening load

All functions pure — return new lists.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass
class BehindMeterAssets:
    pv_mw: float = 0.0
    pv_capacity_factor: float = 0.11    # UK average
    bess_mw: float = 0.0
    bess_duration_h: float = 2.0
    bess_round_trip: float = 0.88
    ev_penetration: float = 0.0         # 0..1
    hp_penetration: float = 0.0         # 0..1
    ambient_c: float = 10.0             # average ambient during horizon (controls PV + HP)
    month: int = 6                      # 1-12 for solar seasonality


def _pv_profile(interval_min: int, steps: int, start_hh_offset: int,
                month: int) -> list[float]:
    """Normalised PV generation 0-1, clear-sky approximation.

    Peaks at noon (hh index 24), width varies with season."""
    slots_per_day = 1440 // interval_min
    start_idx_day = int(start_hh_offset * 30 / interval_min) if interval_min != 30 else start_hh_offset
    # seasonal peak irradiance (relative) — UK summer peaks ~4x winter
    season_peak = 0.5 + 0.5 * math.cos((month - 6) / 12 * 2 * math.pi)
    season_peak = max(0.15, season_peak)
    noon_idx = slots_per_day // 2
    # daylight width in slots — winter ~16 slots of 30 min, summer ~32
    width = (10 + 10 * season_peak)  # in 30-min slots
    width = width * (30 / interval_min)

    out = []
    for i in range(steps):
        slot = (start_idx_day + i) % slots_per_day
        d = slot - noon_idx
        val = season_peak * math.exp(-(d * d) / (2 * width * width))
        if val < 0.01:
            val = 0.0
        out.append(val)
    return out


def _ev_overlay_profile(interval_min: int, steps: int, start_hh_offset: int) -> list[float]:
    """Normalised EV charging overlay 0-1, peaks 6pm-11pm (home charging)."""
    slots_per_day = 1440 // interval_min
    start_idx_day = int(start_hh_offset * 30 / interval_min) if interval_min != 30 else start_hh_offset
    evening_peak = int(40 * 30 / interval_min)  # 20:00
    overnight_plateau_start = int(44 * 30 / interval_min)  # 22:00
    out = []
    for i in range(steps):
        slot = (start_idx_day + i) % slots_per_day
        d_peak = min(abs(slot - evening_peak), slots_per_day - abs(slot - evening_peak))
        v = 0.4 * math.exp(-(d_peak * d_peak) / 12)
        # overnight trickle
        if slot >= overnight_plateau_start or slot < int(12 * 30 / interval_min):
            v = max(v, 0.15)
        out.append(v)
    m = max(out) or 1.0
    return [v / m for v in out]


def _hp_overlay_profile(interval_min: int, steps: int, start_hh_offset: int,
                         ambient_c: float) -> list[float]:
    """Normalised HP overlay 0-1, twin-peak morning+evening scaled by cold."""
    slots_per_day = 1440 // interval_min
    start_idx_day = int(start_hh_offset * 30 / interval_min) if interval_min != 30 else start_hh_offset
    morning_peak = int(14 * 30 / interval_min)  # 07:00
    evening_peak = int(38 * 30 / interval_min)  # 19:00
    # cold factor: zero above 15C, scales up below
    cold_factor = max(0.0, (15.0 - ambient_c) / 15.0)
    out = []
    for i in range(steps):
        slot = (start_idx_day + i) % slots_per_day
        dm = min(abs(slot - morning_peak), slots_per_day - abs(slot - morning_peak))
        de = min(abs(slot - evening_peak), slots_per_day - abs(slot - evening_peak))
        v = (math.exp(-(dm * dm) / 8) + 1.2 * math.exp(-(de * de) / 8))
        out.append(v * cold_factor)
    m = max(out) or 1.0
    return [v / m for v in out]


def _apply_bess(load: list[float], bess_mw: float, bess_duration_h: float,
                 round_trip: float, interval_min: int) -> tuple[list[float], dict]:
    """Simple peak-shaving BESS: charge lowest bess_duration_h slots, discharge highest.

    Returns (shaped_load, stats).
    """
    if bess_mw <= 0 or not load:
        return list(load), {"bess_active": False}

    slots_per_hour = 60 // interval_min
    charge_slots = max(1, int(bess_duration_h * slots_per_hour))
    # energy capacity (MWh)
    cap_mwh = bess_mw * bess_duration_h
    # rank slots
    idx_sorted = sorted(range(len(load)), key=lambda i: load[i])
    charge_idx = set(idx_sorted[:charge_slots])
    discharge_idx = set(idx_sorted[-charge_slots:])
    shaped = list(load)
    for i in charge_idx:
        shaped[i] += bess_mw * math.sqrt(round_trip)
    for i in discharge_idx:
        shaped[i] = max(0.0, shaped[i] - bess_mw * math.sqrt(round_trip))
    return (
        shaped,
        {
            "bess_active": True,
            "charge_slots": len(charge_idx),
            "discharge_slots": len(discharge_idx),
            "cap_mwh": cap_mwh,
            "round_trip": round_trip,
            "peak_reduction_mw": round(max(load) - max(shaped), 3),
        },
    )


def apply_behind_meter(
    gross_load_mw: list[float],
    assets: BehindMeterAssets,
    interval_min: int,
    start_hh_offset: int,
    peak_mw: float,
) -> tuple[list[float], dict]:
    """Apply PV/BESS/EV/HP overlays to a gross load curve.

    Returns (net_load_mw, detail) where detail lists each overlay's contribution.
    """
    steps = len(gross_load_mw)
    net = list(gross_load_mw)
    detail: dict = {}

    # PV export reduces net import
    if assets.pv_mw > 0:
        pv = _pv_profile(interval_min, steps, start_hh_offset, assets.month)
        pv_mw_series = [assets.pv_mw * p for p in pv]
        net = [max(0.0, net[i] - pv_mw_series[i]) for i in range(steps)]
        detail["pv"] = {
            "peak_mw": round(max(pv_mw_series), 3),
            "energy_mwh_est": round(sum(pv_mw_series) * interval_min / 60, 2),
            "capacity_factor": assets.pv_capacity_factor,
        }

    # EV penetration adds overlay scaled to typology and pen
    if assets.ev_penetration > 0:
        ev = _ev_overlay_profile(interval_min, steps, start_hh_offset)
        ev_peak_add = peak_mw * 0.35 * assets.ev_penetration
        ev_mw_series = [ev_peak_add * v for v in ev]
        net = [net[i] + ev_mw_series[i] for i in range(steps)]
        detail["ev"] = {
            "peak_add_mw": round(ev_peak_add, 3),
            "penetration": assets.ev_penetration,
        }

    # HP penetration — weather-dependent
    if assets.hp_penetration > 0:
        hp = _hp_overlay_profile(interval_min, steps, start_hh_offset, assets.ambient_c)
        hp_peak_add = peak_mw * 0.45 * assets.hp_penetration
        hp_mw_series = [hp_peak_add * v for v in hp]
        net = [net[i] + hp_mw_series[i] for i in range(steps)]
        detail["hp"] = {
            "peak_add_mw": round(hp_peak_add, 3),
            "penetration": assets.hp_penetration,
            "ambient_c": assets.ambient_c,
        }

    # BESS peak-shaving (last — shapes whatever the load looks like now)
    if assets.bess_mw > 0:
        net, bess_stats = _apply_bess(
            net, assets.bess_mw, assets.bess_duration_h,
            assets.bess_round_trip, interval_min,
        )
        detail["bess"] = bess_stats

    return net, detail
