"""Finance engineering-math benchmarks — single source of truth.

All Princeps finance code (IRR/NPV/DSCR, project finance, DCF, Monte Carlo,
lender packs, reports) MUST import from this module instead of using magic
numbers for WACC, debt:equity, tax rates, inflation, PPA defaults, CfD
strike, or EGL thresholds.

Complements (NOT replaces) the technology-specific benchmark modules:
    - utils.solar_benchmarks      (solar CapEx/OpEx/CF/PPA by tech)
    - utils.bess_benchmarks       (BESS revenue stacks, duration-keyed)
    - utils.dc_finance            (DC tier contracts)

Sources (2026-04):
    - Greencoat / Octopus / FRV capital structure disclosures Q4 2025
    - BoE Monetary Policy Report Feb 2026            (CPI long-run 2.4%)
    - UK Gov HMT DMO SONIA curve mid-Apr 2026        (debt reference)
    - HMRC Corporation Tax rates 2025-26             (25% mainline)
    - Electricity Generator Levy (EGL) — Spring Budget 2023 + 2025 CPI uplift
    - LCCC AR7 Pot 1 clearing results Jan 2026       (CfD strike 2026 prices)
    - Cornwall Insight UK PPA Tracker Q1 2026        (merchant tiers)
    - Modo Energy GB BESS blended revenue Mar 2026   (BESS PPA proxy)

Usage:
    from utils.finance_benchmarks import (
        wacc, debt_to_equity, tax_rate_total, cpi_long_run,
        ppa_price_merchant, cfd_strike_2026, egl_threshold_gbp_mwh,
        egl_applies_to,
        senior_debt_all_in_rate, debt_tenor_years,
        cite,
    )

    r  = wacc("solar", "stabilised")       # 0.09
    de = debt_to_equity("solar")            # (0.65, 0.35)
    pp = ppa_price_merchant("solar")        # 48
    cf = cfd_strike_2026()                  # 67.0
    eg = egl_threshold_gbp_mwh()            # 75.0
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Discount / WACC bands by technology and lifecycle stage, 2026 GBP nominal
# Sourced from Greencoat/Octopus/JLEN/FRV 2025 annual reports + DESNZ 2024
# ---------------------------------------------------------------------------

WACC_BANDS: dict[str, dict[str, float]] = {
    "solar":   {"stabilised": 0.085, "greenfield": 0.120, "merchant": 0.140},
    "wind":    {"stabilised": 0.090, "greenfield": 0.130, "merchant": 0.150},
    "offshore_wind": {"stabilised": 0.100, "greenfield": 0.140, "merchant": 0.170},
    "bess":    {"stabilised": 0.120, "greenfield": 0.150, "merchant": 0.170},
    "dc":      {"stabilised": 0.090, "greenfield": 0.110, "merchant": 0.130},
}

# Pan-tech fallbacks
WACC_DEFAULT_STABILISED: float = 0.090
WACC_DEFAULT_GREENFIELD: float = 0.130
WACC_DEFAULT_MERCHANT:   float = 0.160


# ---------------------------------------------------------------------------
# Capital structure — UK renewables + BESS 2026
# Greencoat 65:35, Octopus Renewables 60:40, BESS merchant 50:50
# ---------------------------------------------------------------------------

DEBT_EQUITY_RATIO: dict[str, tuple[float, float]] = {
    "solar":         (0.65, 0.35),
    "wind":          (0.65, 0.35),
    "offshore_wind": (0.55, 0.45),
    "bess":          (0.50, 0.50),
    "dc":            (0.60, 0.40),
}


# ---------------------------------------------------------------------------
# Debt tenor (years) — senior secured UK renewables 2026
# ---------------------------------------------------------------------------

DEBT_TENOR_YEARS: dict[str, int] = {
    "solar":         18,   # 15yr term + 3yr mini-perm
    "wind":          18,
    "offshore_wind": 15,
    "bess":           9,   # 7-10yr window, shorter due to merchant risk
    "dc":            12,
}


# ---------------------------------------------------------------------------
# Interest rates — SONIA-indexed margins Apr 2026
# SONIA ~4.75% (Apr 2026 BoE); senior secured renewables margin 200-275bp
# ---------------------------------------------------------------------------

SONIA_REFERENCE_PCT: float = 4.75

DEBT_MARGIN_BPS: dict[str, int] = {
    "solar":         250,
    "wind":          250,
    "offshore_wind": 275,
    "bess":          325,
    "dc":            225,
}


# ---------------------------------------------------------------------------
# Tax rates (UK 2025-26)
# ---------------------------------------------------------------------------

CORPORATION_TAX_RATE: float = 0.25

# Electricity Generator Levy — Spring Budget 2023, CPI-uplifted 2025:
# 35% temporary windfall on generation revenue ABOVE benchmark £75/MWh
# (up from £75 since baseline; reverses when wholesale reverts).
EGL_RATE: float = 0.35
EGL_THRESHOLD_GBP_MWH_2025: float = 75.0
# EGL applies only to "in scope" generators: wind, solar, nuclear, biomass,
# hydro. Explicitly excludes BESS, DC workloads, merchant gas, and pre-1990
# hydro. Also excludes CfD generators (already clawed back via CfD mechanism).
EGL_TECH_IN_SCOPE: set[str] = {"solar", "wind", "offshore_wind", "biomass", "nuclear"}


# ---------------------------------------------------------------------------
# Inflation (long-run) — BoE MPR Feb 2026 forward CPI 2yr/5yr
# ---------------------------------------------------------------------------

CPI_LONG_RUN: float = 0.024
CPI_SHORT_TERM: float = 0.032   # 2026-27 higher due to SONIA passthrough


# ---------------------------------------------------------------------------
# Merchant PPA by tech, 2026 GBP/MWh (Cornwall Insight Q1 2026)
# ---------------------------------------------------------------------------

PPA_MERCHANT_BY_TECH_GBP_MWH: dict[str, dict[str, float]] = {
    "solar":   {"low": 40.0, "mid": 48.0, "high": 55.0},
    "wind":    {"low": 42.0, "mid": 52.0, "high": 60.0},
    "offshore_wind": {"low": 50.0, "mid": 60.0, "high": 72.0},
    "bess":    {"low": 60.0, "mid": 68.0, "high": 75.0},   # Modo blended proxy
    "dc":      {"low": 65.0, "mid": 75.0, "high": 90.0},   # hyperscaler corp PPA
}


# ---------------------------------------------------------------------------
# CfD AR7 Pot 1 (Jan 2026) — solar & onshore wind clearing (2012 prices)
# HMT GDP deflator to 2026: ×1.34
# ---------------------------------------------------------------------------

CFD_AR7_STRIKE_GBP_MWH_2012: float = 50.07
CFD_AR7_STRIKE_GBP_MWH_2026: float = 67.0

# Pot 2 (offshore wind) strike Jan 2026 results
CFD_AR7_OFFSHORE_STRIKE_GBP_MWH_2026: float = 85.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wacc(technology: str = "solar", stage: str = "stabilised") -> float:
    """Nominal post-tax WACC for a tech+stage combination.

    Parameters
    ----------
    technology : solar | wind | offshore_wind | bess | dc (fallback: solar)
    stage      : stabilised | greenfield | merchant (fallback: stabilised)
    """
    tech = (technology or "solar").lower()
    stg = (stage or "stabilised").lower()
    bucket = WACC_BANDS.get(tech, WACC_BANDS["solar"])
    return bucket.get(stg, bucket["stabilised"])


def discount_rate(technology: str = "solar", stage: str = "stabilised") -> float:
    """Alias for wacc(). Use inside DCF / NPV calculations."""
    return wacc(technology, stage)


def debt_to_equity(technology: str = "solar") -> tuple[float, float]:
    """Return (debt_frac, equity_frac) capital structure for UK 2026 market."""
    return DEBT_EQUITY_RATIO.get((technology or "solar").lower(),
                                 DEBT_EQUITY_RATIO["solar"])


def gearing_pct(technology: str = "solar") -> float:
    """Debt as fraction of total capital — convenience alias."""
    return debt_to_equity(technology)[0]


def debt_tenor_years(technology: str = "solar") -> int:
    """Senior debt tenor in years for UK project finance 2026."""
    return DEBT_TENOR_YEARS.get((technology or "solar").lower(),
                                DEBT_TENOR_YEARS["solar"])


def senior_debt_margin_bps(technology: str = "solar") -> int:
    """Senior secured margin over SONIA in basis points, 2026."""
    return DEBT_MARGIN_BPS.get((technology or "solar").lower(),
                               DEBT_MARGIN_BPS["solar"])


def senior_debt_all_in_rate(technology: str = "solar") -> float:
    """Senior debt all-in rate (SONIA + margin), expressed as decimal.

    e.g. solar → SONIA 4.75% + 250bp = 7.25% → returns 0.0725.
    """
    margin = senior_debt_margin_bps(technology) / 10_000.0  # bps -> decimal
    return round(SONIA_REFERENCE_PCT / 100.0 + margin, 4)


def tax_rate_total(technology: str = "solar", apply_egl: bool = False) -> float:
    """Combined UK effective tax rate.

    Returns corporation_tax (25%) + EGL (35%) when apply_egl=True AND the
    technology is in-scope. Otherwise just corporation_tax.
    """
    base = CORPORATION_TAX_RATE
    if apply_egl and (technology or "").lower() in EGL_TECH_IN_SCOPE:
        return base + EGL_RATE
    return base


def corporation_tax_rate() -> float:
    """UK corporation tax mainline rate (2025-26)."""
    return CORPORATION_TAX_RATE


def egl_applies_to(technology: str) -> bool:
    """True iff the Electricity Generator Levy windfall applies to this tech."""
    return (technology or "").lower() in EGL_TECH_IN_SCOPE


def egl_threshold_gbp_mwh() -> float:
    """EGL benchmark price in 2025-26 £/MWh — levy applies only above this.
    CPI-uplifted annually by HMRC.
    """
    return EGL_THRESHOLD_GBP_MWH_2025


def egl_rate() -> float:
    """EGL marginal rate (35%)."""
    return EGL_RATE


def cpi_long_run() -> float:
    """BoE long-run CPI target (2.4% mid-2026 forward curve)."""
    return CPI_LONG_RUN


def ppa_price_merchant(technology: str = "solar", case: str = "mid") -> float:
    """Merchant-PPA £/MWh for UK 2026, keyed by technology.

    Parameters
    ----------
    technology : solar | wind | offshore_wind | bess | dc (default solar)
    case       : low | mid | high (default mid)
    """
    tech = (technology or "solar").lower()
    c = (case or "mid").lower()
    bucket = PPA_MERCHANT_BY_TECH_GBP_MWH.get(
        tech, PPA_MERCHANT_BY_TECH_GBP_MWH["solar"]
    )
    return bucket.get(c, bucket["mid"])


def ppa_price_merchant_range(technology: str = "solar") -> tuple[float, float, float]:
    """(low, mid, high) merchant PPA £/MWh for the given technology."""
    tech = (technology or "solar").lower()
    p = PPA_MERCHANT_BY_TECH_GBP_MWH.get(tech,
                                         PPA_MERCHANT_BY_TECH_GBP_MWH["solar"])
    return p["low"], p["mid"], p["high"]


def cfd_strike_2026(pot: int = 1) -> float:
    """AR7 CfD strike in 2026 prices.

    pot=1 → solar/onshore (£67/MWh). pot=2 → offshore wind (£85/MWh).
    """
    if pot == 2:
        return CFD_AR7_OFFSHORE_STRIKE_GBP_MWH_2026
    return CFD_AR7_STRIKE_GBP_MWH_2026


def cite() -> str:
    """Citation string for finance benchmarks used here."""
    return (
        "Greencoat/Octopus 2025 AR + BoE MPR Feb 2026 + "
        "HMRC CT 25-26 + LCCC AR7 Jan 2026 + Cornwall Insight Q1 2026 + "
        "Modo Energy Mar 2026 + HMT EGL (S.B.2023, CPI-uplifted 2025)"
    )


def as_dict() -> dict:
    """Return the full benchmark set as a JSON-serialisable dict."""
    return {
        "wacc_bands": WACC_BANDS,
        "wacc_default_stabilised": WACC_DEFAULT_STABILISED,
        "wacc_default_greenfield": WACC_DEFAULT_GREENFIELD,
        "wacc_default_merchant":   WACC_DEFAULT_MERCHANT,
        "debt_equity_ratio": {k: {"debt": v[0], "equity": v[1]}
                              for k, v in DEBT_EQUITY_RATIO.items()},
        "debt_tenor_years": DEBT_TENOR_YEARS,
        "sonia_reference_pct": SONIA_REFERENCE_PCT,
        "debt_margin_bps": DEBT_MARGIN_BPS,
        "corporation_tax_rate": CORPORATION_TAX_RATE,
        "egl_rate": EGL_RATE,
        "egl_threshold_gbp_mwh": EGL_THRESHOLD_GBP_MWH_2025,
        "egl_tech_in_scope": sorted(EGL_TECH_IN_SCOPE),
        "cpi_long_run": CPI_LONG_RUN,
        "cpi_short_term": CPI_SHORT_TERM,
        "ppa_merchant_gbp_mwh": PPA_MERCHANT_BY_TECH_GBP_MWH,
        "cfd_ar7_strike_gbp_mwh_2026": CFD_AR7_STRIKE_GBP_MWH_2026,
        "cfd_ar7_offshore_strike_gbp_mwh_2026": CFD_AR7_OFFSHORE_STRIKE_GBP_MWH_2026,
        "citation": cite(),
    }
