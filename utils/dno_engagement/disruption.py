"""
utils.dno_engagement.disruption — Monte Carlo disruption scenarios.

N = 1000 draws over four independent axes:
  1. Demand growth uncertainty ±15% (NESO FES 2024 spread).
  2. Weather extremes (once-in-10y heatwave / cold snap) scaling factor.
  3. Outage coincidence — probability a POC asset is out on peak day.
  4. Counterparty delays (DNO / TO reinforcement schedule slippage, months).

Outputs:
  - Worst-credible demand at POC (P99).
  - Probability of curtailment / firm breach per year.
  - Expected unserved energy (MWh/year) assuming pack's mitigation stack.

Cited:
  * NESO System Operability Framework 2024 §4 (event-class weather).
  * ENA EREC P2 Issue 7 §7 (credible contingency set).
  * Ofgem RIIO-ED2 incentive on interruptions (CI/CML).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


@dataclass
class DisruptionReport:
    project_id: str
    n_runs: int = 0

    # Input assumptions
    base_peak_mw: float = 0.0
    firm_capacity_mw: float = 0.0
    nameplate_mw: float = 0.0

    # Stats of P99 peak demand distribution
    p50_peak_mw: float = 0.0
    p90_peak_mw: float = 0.0
    p99_peak_mw: float = 0.0
    mean_peak_mw: float = 0.0
    stdev_peak_mw: float = 0.0

    # Probabilities / expectations
    prob_firm_breach: float = 0.0
    prob_any_curtailment: float = 0.0
    expected_unserved_energy_mwh: float = 0.0
    expected_curtailed_energy_mwh: float = 0.0

    # Axes summary
    demand_growth_range_pct: tuple[float, float] = (-15.0, 15.0)
    weather_extreme_factor: tuple[float, float] = (0.95, 1.18)
    outage_coincidence_prob: float = 0.08
    counterparty_delay_months: tuple[int, int] = (0, 18)

    # Top 10 worst runs
    worst_runs: list[dict[str, Any]] = field(default_factory=list)

    notes: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=lambda: [
        "NESO System Operability Framework 2024 §4 (weather event class)",
        "ENA EREC P2 Issue 7 §7 (credible contingency set)",
        "Ofgem RIIO-ED2 incentive on Customer Interruptions (CI/CML)",
    ])
    seed: int = 42
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _draw_once(rng: random.Random, base_peak_mw: float,
               firm_mw: float, nameplate_mw: float) -> dict[str, float]:
    """One Monte Carlo draw returning a single dict with all axes."""
    # Axis 1: demand growth — triangular ±15% centred on 0%.
    growth_pct = rng.triangular(-15.0, 15.0, 0.0)
    peak = base_peak_mw * (1.0 + growth_pct / 100.0)

    # Axis 2: weather extreme — lognormal ~1.00, 5% tail at 1.18 (heatwave).
    # rng.lognormvariate(mu, sigma): choose mu so median ≈ 1.0, sigma small.
    weather = rng.lognormvariate(0.0, 0.06)
    weather = max(0.9, min(1.25, weather))
    peak *= weather

    # Axis 3: asset outage coincidence. ~8% chance on peak day — derated capacity.
    outage = rng.random() < 0.08
    available_firm = firm_mw * 0.8 if outage else firm_mw

    # Axis 4: counterparty reinforcement delay (months).
    delay_months = int(rng.triangular(0, 18, 3))

    shortfall = max(0.0, peak - available_firm)

    # Unserved energy crude proxy: shortfall × 4 h/year stress window.
    unserved_mwh = shortfall * 4.0
    # Curtailed energy if generation (PV/wind/BESS export) — outage halves export
    # for delay-dependent weeks. Delay × 0.1% of nameplate annual energy.
    curtailed_mwh = nameplate_mw * 8760.0 * (delay_months / 12.0) * 0.001

    return {
        "growth_pct": round(growth_pct, 2),
        "weather_factor": round(weather, 3),
        "outage_coincidence": outage,
        "delay_months": delay_months,
        "peak_mw": round(peak, 3),
        "available_firm_mw": round(available_firm, 3),
        "shortfall_mw": round(shortfall, 3),
        "unserved_mwh": round(unserved_mwh, 3),
        "curtailed_mwh": round(curtailed_mwh, 3),
    }


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    k = max(0, min(n - 1, int(round((q / 100.0) * (n - 1)))))
    return float(sorted_vals[k])


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _stdev(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    var = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
    return math.sqrt(var)


def compute_disruption_scenarios(
    project_id: str,
    n: int = 1000,
    *,
    base_peak_mw: float = 50.0,
    firm_capacity_mw: float | None = None,
    nameplate_mw: float | None = None,
    seed: int = 42,
) -> DisruptionReport:
    """
    Run the Monte Carlo disruption study.

    Parameters
    ----------
    project_id : str
        Princeps project UUID.
    n : int
        Number of MC runs (default 1000).
    base_peak_mw : float
        Starting peak demand (MW) before MC perturbation.
    firm_capacity_mw : float | None
        Firm capacity at POC (MW). Defaults to base_peak × 1.05.
    nameplate_mw : float | None
        Proposed nameplate at POC (MW). Defaults to base_peak_mw.
    seed : int
        RNG seed — reproducibility.

    Returns
    -------
    DisruptionReport
    """
    rng = random.Random(int(seed))
    firm = float(firm_capacity_mw if firm_capacity_mw is not None
                 else base_peak_mw * 1.05)
    nameplate = float(nameplate_mw if nameplate_mw is not None
                      else base_peak_mw)

    runs = [_draw_once(rng, base_peak_mw, firm, nameplate) for _ in range(int(n))]

    peaks = sorted(r["peak_mw"] for r in runs)
    shortfalls = [r["shortfall_mw"] for r in runs]
    curtails = [r["curtailed_mwh"] for r in runs]
    unserved = [r["unserved_mwh"] for r in runs]

    prob_breach = sum(1 for r in runs if r["shortfall_mw"] > 0) / max(len(runs), 1)
    prob_curtail = sum(
        1 for r in runs if r["curtailed_mwh"] > 0 or r["outage_coincidence"]
    ) / max(len(runs), 1)

    # Pick the 10 worst (highest shortfall) runs.
    top_worst = sorted(runs, key=lambda r: r["shortfall_mw"], reverse=True)[:10]

    notes = [
        f"Monte Carlo: N = {len(runs)} runs, seed = {seed}. "
        f"Growth ±15% (triangular, NESO FES spread).",
        "Weather factor lognormal μ=1.00 σ=0.06, clipped to [0.9, 1.25].",
        "Outage coincidence prob = 8% — derates firm capacity to 80% on that day.",
        "Reinforcement delay: triangular 0-18 months, mode 3 months.",
        "Unserved energy proxy: shortfall × 4 h/year stress window "
        "(P2/7 §7 credible extreme event).",
    ]
    if prob_breach > 0.05:
        notes.append(
            f"WARNING: prob(firm breach) = {prob_breach:.1%} exceeds 5% "
            "headline threshold — recommend mitigation stack escalation."
        )

    return DisruptionReport(
        project_id=str(project_id),
        n_runs=len(runs),
        base_peak_mw=base_peak_mw,
        firm_capacity_mw=firm,
        nameplate_mw=nameplate,
        p50_peak_mw=round(_percentile(peaks, 50), 3),
        p90_peak_mw=round(_percentile(peaks, 90), 3),
        p99_peak_mw=round(_percentile(peaks, 99), 3),
        mean_peak_mw=round(_mean(peaks), 3),
        stdev_peak_mw=round(_stdev(peaks), 3),
        prob_firm_breach=round(prob_breach, 4),
        prob_any_curtailment=round(prob_curtail, 4),
        expected_unserved_energy_mwh=round(_mean(unserved), 3),
        expected_curtailed_energy_mwh=round(_mean(curtails), 3),
        demand_growth_range_pct=(-15.0, 15.0),
        weather_extreme_factor=(0.9, 1.25),
        outage_coincidence_prob=0.08,
        counterparty_delay_months=(0, 18),
        worst_runs=top_worst,
        notes=notes,
        seed=int(seed),
        generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )
