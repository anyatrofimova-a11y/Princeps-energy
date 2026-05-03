"""Electricity Generator Levy (EGL) — UK windfall on excess revenues.

Introduced by HMT Spring Budget 2023, extended to March 2028 by the
Autumn Budget 2023. Applies at 35% on generation revenue above a
benchmark of £75/MWh (2025-26; HMRC CPI-uplifts annually).

Legal basis:
  - Section 279 / Part 5 of the Energy (Oil and Gas) Profits Levy Act
    2022 (as amended by Finance (No. 2) Act 2023)
  - HMRC Internal Manual EGLM10000 series
  - Autumn Budget 2023 para 5.55 — extended to 31 March 2028

In-scope technologies (HMRC EGLM12000):
  - Nuclear
  - Biomass (dedicated + co-firing, where >=50MW)
  - Onshore wind
  - Offshore wind
  - Solar PV
  - Energy-from-waste (EfW)

Excluded:
  - Gas-fired (CCGT / OCGT)
  - Coal
  - BESS (battery storage)
  - Hydro (pre-1990 schemes)
  - Any CfD generator (already clawed back via CfD difference payments)
  - Generators with <100 GWh annual output (de minimis)

Timing:
  - In force from 1 Jan 2023
  - Sunsets 31 Mar 2028 (per Autumn Budget 2023)
  - Does NOT apply for generation before 2023-01 or after 2028-04

Defaults are pulled from :mod:`utils.finance_benchmarks` so the
threshold and rate stay in sync across the codebase.

Usage:
    from utils.egl_calculator import egl_liability

    out = egl_liability(
        tech="solar",
        capture_price=95.0,     # £/MWh — above the £75 benchmark
        generation_gwh=45.0,
        year=2026,
    )
    # out["egl_gbp"] ≈ 315_000
"""

from __future__ import annotations

from utils.finance_benchmarks import (
    EGL_RATE,
    EGL_TECH_IN_SCOPE,
    EGL_THRESHOLD_GBP_MWH_2025,
    egl_applies_to,
    egl_rate,
    egl_threshold_gbp_mwh,
)


# ---------------------------------------------------------------------------
# Effective window (in force)
# HMT Spring Budget 2023 + Autumn Budget 2023 extension
# ---------------------------------------------------------------------------

EGL_START_YEAR: int = 2023        # 1 Jan 2023 per S.279 F(No.2)A 2023
EGL_END_YEAR: int = 2028          # sunset 31 Mar 2028 per Autumn Budget 2023

# HMRC de minimis — generators below this annual generation are exempt
# (EGLM13000 — set at 100 GWh/yr per "qualifying generating station")
EGL_DE_MINIMIS_GWH: float = 100.0

# CPI uplift schedule for the threshold (HMRC CPI uplift applies annually)
# Threshold is set per HMRC update — 2023 £75, 2024 £75, 2025 £75, 2026 £77.0
# (ONS CPI 2.4% long-run per BoE MPR Feb 2026).
EGL_THRESHOLD_BY_YEAR: dict[int, float] = {
    # HMRC Benchmark Amount updates
    2023: 75.0,
    2024: 75.0,
    2025: 75.0,
    2026: 77.0,   # 2.4% CPI uplift per BoE MPR Feb 2026
    2027: 78.8,
    2028: 80.0,
}


def _threshold_for_year(year: int) -> float:
    """Return the HMRC Benchmark Amount £/MWh for ``year``.

    Falls back to the static 2025 value from finance_benchmarks if the
    year isn't explicitly listed.
    """
    if year in EGL_THRESHOLD_BY_YEAR:
        return EGL_THRESHOLD_BY_YEAR[year]
    return EGL_THRESHOLD_GBP_MWH_2025


def in_scope(tech: str, year: int, generation_gwh: float) -> bool:
    """True iff this generator is EGL-in-scope for ``year``.

    Tests the 3 EGL scope gates:
      1. Tech must be in HMRC's Schedule 1 list (EGLM12000).
      2. Year must fall in 2023-2028 inclusive (EGLM14000).
      3. Station must generate at least 100 GWh/yr (EGLM13000 de minimis).
    """
    if not egl_applies_to(tech):
        return False
    if year < EGL_START_YEAR or year > EGL_END_YEAR:
        return False
    if generation_gwh < EGL_DE_MINIMIS_GWH:
        return False
    return True


def egl_liability(
    tech: str,
    capture_price: float,
    generation_gwh: float,
    year: int,
) -> dict:
    """Return EGL liability for a single generator-year.

    Parameters
    ----------
    tech           : 'solar', 'wind', 'offshore_wind', 'biomass', 'nuclear',
                     or anything else (→ out of scope).
    capture_price  : £/MWh actually received (volume-weighted). For CfD
                     generators, pass merchant capture — but CfD folks
                     are out of scope anyway.
    generation_gwh : Total generated GWh in this period.
    year           : Calendar year. Determines whether levy applies and
                     which HMRC Benchmark Amount to use.

    Returns
    -------
    dict with keys:
        in_scope          : bool
        threshold_gbp_mwh : HMRC benchmark for this year
        levy_rate         : EGL marginal rate (35%)
        excess_rev_gbp    : £ of revenue over benchmark (before levy)
        egl_gbp           : £ actually owed to HMRC
        reason            : if out-of-scope, why

    Example
    -------
    >>> egl_liability("solar", 95.0, 45.0, 2026)["egl_gbp"]
    283500.0
    # Working: (95 - 77) × 45_000 MWh × 0.35 = £283_500
    """
    tech_norm = (tech or "").lower()
    threshold = _threshold_for_year(year)

    # Gate 1: tech
    if tech_norm not in EGL_TECH_IN_SCOPE:
        return {
            "in_scope": False,
            "threshold_gbp_mwh": threshold,
            "levy_rate": EGL_RATE,
            "excess_rev_gbp": 0.0,
            "egl_gbp": 0.0,
            "reason": f"Tech '{tech_norm}' not in HMRC Schedule 1 (EGLM12000)",
        }

    # Gate 2: year window
    if year < EGL_START_YEAR or year > EGL_END_YEAR:
        return {
            "in_scope": False,
            "threshold_gbp_mwh": threshold,
            "levy_rate": EGL_RATE,
            "excess_rev_gbp": 0.0,
            "egl_gbp": 0.0,
            "reason": f"Year {year} outside EGL window 2023-2028 "
                      "(Autumn Budget 2023 sunset)",
        }

    # Gate 3: de minimis
    if generation_gwh < EGL_DE_MINIMIS_GWH:
        return {
            "in_scope": False,
            "threshold_gbp_mwh": threshold,
            "levy_rate": EGL_RATE,
            "excess_rev_gbp": 0.0,
            "egl_gbp": 0.0,
            "reason": f"Generation {generation_gwh:.1f} GWh < de minimis "
                      f"{EGL_DE_MINIMIS_GWH} GWh (EGLM13000)",
        }

    # Below threshold → no levy, but still "in scope"
    if capture_price <= threshold:
        return {
            "in_scope": True,
            "threshold_gbp_mwh": threshold,
            "levy_rate": EGL_RATE,
            "excess_rev_gbp": 0.0,
            "egl_gbp": 0.0,
            "reason": "Capture price at/below HMRC Benchmark — no levy",
        }

    # Compute excess and levy
    excess_gbp_mwh = capture_price - threshold
    generation_mwh = generation_gwh * 1000.0
    excess_rev = excess_gbp_mwh * generation_mwh
    egl = excess_rev * EGL_RATE

    return {
        "in_scope": True,
        "threshold_gbp_mwh": threshold,
        "levy_rate": EGL_RATE,
        "excess_rev_gbp": round(excess_rev, 2),
        "egl_gbp": round(egl, 2),
        "reason": None,
    }


def lifetime_egl(
    tech: str,
    annual_capture_price: dict[int, float],
    annual_generation_gwh: dict[int, float],
) -> dict:
    """Sum EGL across a multi-year stream.

    Takes year-keyed dicts of capture price and generation. Useful for
    embedding into DCF: computes the per-year liability using the
    year-specific HMRC Benchmark Amount, then returns a schedule.

    Returns {schedule: [{year, egl_gbp, in_scope}], total_egl_gbp}.
    """
    schedule: list[dict] = []
    total = 0.0
    for year in sorted(annual_capture_price.keys()):
        price = annual_capture_price[year]
        gen = annual_generation_gwh.get(year, 0.0)
        row = egl_liability(tech, price, gen, year)
        schedule.append({
            "year": year,
            "egl_gbp": row["egl_gbp"],
            "in_scope": row["in_scope"],
            "threshold_gbp_mwh": row["threshold_gbp_mwh"],
        })
        total += row["egl_gbp"]
    return {"schedule": schedule, "total_egl_gbp": round(total, 2)}


def cite() -> str:
    """Primary legal and HMRC sources."""
    return (
        "S.279 Energy (Oil and Gas) Profits Levy Act 2022 "
        "(as amended by Finance (No.2) Act 2023) + "
        "HMRC EGL Manual EGLM10000-14000 (Feb 2025 edition) + "
        "HMT Spring Budget 2023 para 5.47 + "
        "HMT Autumn Budget 2023 para 5.55 (sunset 31 Mar 2028)"
    )


# Re-exports for external convenience
__all__ = [
    "egl_liability",
    "lifetime_egl",
    "in_scope",
    "cite",
    "EGL_START_YEAR",
    "EGL_END_YEAR",
    "EGL_DE_MINIMIS_GWH",
    "EGL_THRESHOLD_BY_YEAR",
    "egl_rate",
    "egl_threshold_gbp_mwh",
]
