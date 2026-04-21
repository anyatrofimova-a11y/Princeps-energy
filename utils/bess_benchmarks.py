"""BESS engineering-math benchmarks — single source of truth.

All Princeps BESS revenue, CapEx and OpEx assumptions MUST import from this
module instead of using magic numbers. Sourced from Modo Energy GB BESS
index, Mar 2026.

Values are deliberately duration-keyed (1h/2h/4h/8h) because blended
revenue per MW/yr does not scale linearly with duration — a 4h battery
earns ~36% more than a 2h on the same MW nameplate because of capacity-
market, wholesale arbitrage depth, and T-SO balancing premiums.

Usage:
    from utils.bess_benchmarks import (
        bess_revenue_mid, bess_revenue_range,
        bess_capex_per_kwh, ffr_dynamic_gbp_mw_yr,
        capacity_market_gbp_mw_yr, arbitrage_only_gbp_mw_yr,
        cite,
    )

    rev_2h = bess_revenue_mid(2)           # 110_000
    low, mid, high = bess_revenue_range(2) # (85_000, 110_000, 135_000)
    print(cite(2))  # "Modo Energy GB BESS index, Mar 2026 (range £85k–£135k)"
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Blended revenue per MW/yr, keyed by duration_h
# Source: Modo Energy GB BESS index, March 2026
# Keys follow P10 (low), P50 (mid), P90 (high) convention
# ---------------------------------------------------------------------------

BESS_REVENUE_GBP_MW_YR: dict[int, dict[str, int]] = {
    1: {"low":  50_000, "mid":  65_000, "high":  80_000},
    2: {"low":  85_000, "mid": 110_000, "high": 135_000},
    4: {"low": 115_000, "mid": 150_000, "high": 185_000},
    8: {"low": 140_000, "mid": 175_000, "high": 215_000},
}

# CapEx all-in £/kWh, 2026 prices (down from £330/kWh in 2024)
BESS_CAPEX_GBP_PER_KWH: dict[str, int] = {
    "low":  280,
    "mid":  310,
    "high": 370,
}

# Individual revenue stream benchmarks (Mar 2026 clearing levels)
FFR_DYNAMIC_GBP_MW_YR: int = 45_000          # softened since 2024 peak
CAPACITY_MARKET_GBP_MW_YR: int = 28_000      # T-4 2028 auction average
ARBITRAGE_ONLY_GBP_MW_YR: int = 38_000       # 2h merchant-only wholesale

# Fixed OpEx £/MW/yr (scales with power, not energy)
BESS_FIXED_OPEX_GBP_MW_YR: int = 8_000

# Blended grid export price used for rough revenue-today estimates (£/MWh)
BESS_BLENDED_PRICE_GBP_MWH: float = 55.0     # up from £45 pre-2026


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nearest_duration_key(duration_h: float) -> int:
    """Snap a continuous duration (h) to the nearest benchmark bucket."""
    if duration_h <= 1.5:
        return 1
    if duration_h <= 3.0:
        return 2
    if duration_h <= 6.0:
        return 4
    return 8


def bess_revenue_mid(duration_h: float) -> int:
    """Blended P50 revenue £/MW/yr for the given duration."""
    return BESS_REVENUE_GBP_MW_YR[_nearest_duration_key(duration_h)]["mid"]


def bess_revenue_low(duration_h: float) -> int:
    """P10 (low-case) blended revenue £/MW/yr."""
    return BESS_REVENUE_GBP_MW_YR[_nearest_duration_key(duration_h)]["low"]


def bess_revenue_high(duration_h: float) -> int:
    """P90 (high-case) blended revenue £/MW/yr."""
    return BESS_REVENUE_GBP_MW_YR[_nearest_duration_key(duration_h)]["high"]


def bess_revenue_range(duration_h: float) -> tuple[int, int, int]:
    """Return (low, mid, high) blended revenue £/MW/yr."""
    bucket = BESS_REVENUE_GBP_MW_YR[_nearest_duration_key(duration_h)]
    return bucket["low"], bucket["mid"], bucket["high"]


def bess_capex_per_kwh(case: str = "mid") -> int:
    """All-in CapEx £/kWh installed (case in {'low','mid','high'})."""
    return BESS_CAPEX_GBP_PER_KWH.get(case, BESS_CAPEX_GBP_PER_KWH["mid"])


def ffr_dynamic_gbp_mw_yr() -> int:
    """FFR Dynamic clearing level £/MW/yr (Mar 2026)."""
    return FFR_DYNAMIC_GBP_MW_YR


def capacity_market_gbp_mw_yr() -> int:
    """Capacity Market £/MW/yr, T-4 2028 average."""
    return CAPACITY_MARKET_GBP_MW_YR


def arbitrage_only_gbp_mw_yr() -> int:
    """Merchant wholesale arbitrage only, 2h battery, £/MW/yr."""
    return ARBITRAGE_ONLY_GBP_MW_YR


def bess_fixed_opex_gbp_mw_yr() -> int:
    """Fixed O&M £/MW/yr."""
    return BESS_FIXED_OPEX_GBP_MW_YR


def bess_blended_price_gbp_mwh() -> float:
    """Blended £/MWh price used for indicative revenue-today estimates."""
    return BESS_BLENDED_PRICE_GBP_MWH


def cite(duration_h: float | None = None) -> str:
    """Return a citation string for the benchmark in use."""
    base = "Modo Energy GB BESS index, Mar 2026"
    if duration_h is None:
        return base
    low, _, high = bess_revenue_range(duration_h)
    return f"{base} (range £{low // 1000}k–£{high // 1000}k)"
