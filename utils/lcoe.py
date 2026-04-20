"""Levelised Cost of Electricity (LCOE) with sensitivity table.

LCOE = Σ((CAPEX_t + OPEX_t) / (1+r)^t) / Σ(E_t / (1+r)^t)

References:
  - IEA Projected Costs of Generating Electricity (2020)
  - BEIS Electricity Generation Costs (2023)
  - NREL ATB 2024
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field


@dataclass
class LCOEResult:
    inputs_echo: dict
    outputs: dict
    assumptions: list[str]
    provenance: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _present_value(cashflows: list[float], discount_rate: float) -> float:
    return sum(cf / (1.0 + discount_rate) ** t for t, cf in enumerate(cashflows))


def _pad_or_trim(series: list[float], length: int, fill: float = 0.0) -> list[float]:
    if len(series) >= length:
        return series[:length]
    return list(series) + [fill] * (length - len(series))


def compute_lcoe(
    capex_gbp: float,
    opex_schedule_gbp: list[float],
    annual_generation_mwh: float | list[float],
    discount_rate: float,
    lifetime_years: int,
    capex_schedule_gbp: list[float] | None = None,
    degradation_pct_per_yr: float = 0.5,
    residual_value_gbp: float = 0.0,
) -> LCOEResult:
    """LCOE in £/MWh plus sensitivity table.

    `opex_schedule_gbp` is a list aligned with project years (year 0 → N-1).
    `annual_generation_mwh` may be a scalar (flat, with optional degradation)
    or a list of per-year values. If `capex_schedule_gbp` is None, full
    capex is assumed in year 0.
    """
    if lifetime_years <= 0:
        raise ValueError("lifetime_years > 0")
    if capex_gbp < 0:
        raise ValueError("capex_gbp >= 0")
    if not (-0.2 < discount_rate < 1.0):
        raise ValueError("discount_rate in (-0.2, 1.0)")

    # Capex schedule
    if capex_schedule_gbp is None:
        capex_series = [capex_gbp] + [0.0] * (lifetime_years - 1)
    else:
        capex_series = _pad_or_trim(capex_schedule_gbp, lifetime_years, 0.0)
        if sum(capex_series) < 0:
            raise ValueError("capex schedule sums to negative")

    # Opex series
    opex_series = _pad_or_trim(opex_schedule_gbp, lifetime_years, 0.0)

    # Generation series
    if isinstance(annual_generation_mwh, (list, tuple)):
        gen_series = _pad_or_trim(list(annual_generation_mwh), lifetime_years, 0.0)
    else:
        gen_series = [
            annual_generation_mwh * (1.0 - degradation_pct_per_yr / 100.0) ** t
            for t in range(lifetime_years)
        ]

    # Residual value as negative cashflow at terminal year
    cost_series = [c + o for c, o in zip(capex_series, opex_series)]
    if residual_value_gbp:
        cost_series[-1] -= residual_value_gbp

    pv_cost = _present_value(cost_series, discount_rate)
    pv_gen = _present_value(gen_series, discount_rate)

    if pv_gen <= 0:
        raise ValueError("discounted generation is zero/negative")

    lcoe = pv_cost / pv_gen  # £/MWh

    # Sensitivity table — ±10%, ±20% on capex, opex, generation
    def _sens(capex_mult: float, opex_mult: float, gen_mult: float) -> float:
        cs = [c * capex_mult + o * opex_mult for c, o in zip(capex_series, opex_series)]
        gs = [g * gen_mult for g in gen_series]
        return _present_value(cs, discount_rate) / _present_value(gs, discount_rate)

    sensitivity = {}
    for dim, (c_m, o_m, g_m) in [
        ("capex_-20", (0.8, 1.0, 1.0)),
        ("capex_-10", (0.9, 1.0, 1.0)),
        ("capex_+10", (1.1, 1.0, 1.0)),
        ("capex_+20", (1.2, 1.0, 1.0)),
        ("opex_-20", (1.0, 0.8, 1.0)),
        ("opex_-10", (1.0, 0.9, 1.0)),
        ("opex_+10", (1.0, 1.1, 1.0)),
        ("opex_+20", (1.0, 1.2, 1.0)),
        ("output_-20", (1.0, 1.0, 0.8)),
        ("output_-10", (1.0, 1.0, 0.9)),
        ("output_+10", (1.0, 1.0, 1.1)),
        ("output_+20", (1.0, 1.0, 1.2)),
    ]:
        sensitivity[dim] = round(_sens(c_m, o_m, g_m), 2)

    # Tornado ordering
    mid = {k: v for k, v in sensitivity.items() if k.endswith("10")}
    ranges = {}
    for dim in ("capex", "opex", "output"):
        lo = sensitivity[f"{dim}_-10"]
        hi = sensitivity[f"{dim}_+10"]
        ranges[dim] = round(abs(hi - lo), 2)

    warnings = []
    if lcoe <= 0:
        warnings.append("negative LCOE — check capex/residual inputs")
    if discount_rate < 0.04:
        warnings.append("discount rate < 4% — implausible for project finance")

    return LCOEResult(
        inputs_echo={
            "capex_gbp": capex_gbp,
            "opex_years": len(opex_schedule_gbp),
            "annual_generation_mwh_avg": sum(gen_series) / len(gen_series),
            "discount_rate": discount_rate,
            "lifetime_years": lifetime_years,
            "degradation_pct_per_yr": degradation_pct_per_yr,
            "residual_value_gbp": residual_value_gbp,
        },
        outputs={
            "lcoe_gbp_per_mwh": round(lcoe, 2),
            "pv_cost_gbp": round(pv_cost, 0),
            "pv_generation_mwh": round(pv_gen, 0),
            "undiscounted_total_cost_gbp": round(sum(cost_series), 0),
            "undiscounted_total_generation_mwh": round(sum(gen_series), 0),
            "sensitivity_lcoe_gbp_per_mwh": sensitivity,
            "tornado_range_gbp_per_mwh": ranges,
        },
        assumptions=[
            "Nominal discounting — all values in real £ unless otherwise stated",
            f"Linear generation degradation {degradation_pct_per_yr}%/yr (if scalar gen supplied)",
            "Residual value netted against terminal-year cashflow",
            "No tax/allowance modelling (pre-tax real LCOE)",
        ],
        provenance="IEA 2020 / BEIS 2023 / NREL ATB 2024 methodology",
        warnings=warnings,
    )
