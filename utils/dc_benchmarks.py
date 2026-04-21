"""
dc_benchmarks.py — Single source of truth for UK Data Centre engineering-math.

All CapEx, OpEx, PUE, WUE, lease/colocation rate benchmarks used by Princeps
DC planning / design / finance / feasibility paths **must** defer to the
functions in this module. Do not repeat these numbers inline elsewhere —
they will drift out of sync with market data within weeks.

References (2026-04)
--------------------
- Cushman & Wakefield "UK & Ireland Data Centre Market" H1 2025:
    Tier 3 all-in CapEx £3.5–5.0 M/MW IT  (midpoint £4.2 M/MW).
    Tier 4 adds ~25% (2N electrical + mechanical).
    Tier 2 colo retrofit £2.8–3.8 M/MW IT.
    Wholesale hyperscaler lease £2.4–3.2 M/MW/yr (London I/O — 2026).
    Colo retail rack-fee-equivalent £4–8 M/MW/yr (London retail).
- CBRE "Global Data Centre Trends" H1 2025:
    OpEx ex-power for UK hyperscale £325–380 k/MW IT/yr (2025);
    2026 uplift to ~£350 k/MW IT/yr (staff £80k, maintenance £160k,
    property/rates £80k, other £30k). The previous £250k figure was
    2022 vintage and understated today's cost base.
- Uptime Institute "Global Data Center Survey 2024":
    PUE target ranges: 1.18 cold-climate optimised, 1.25 UK hyperscale
    median, 1.35 colo legacy, 1.45 retrofit / high-density conversion.
- JLL "Global Data Center Outlook 2026" — confirms CapEx band and
    adds WUE categories (0 / 0.3 / 1.2 L/kWh for dry / hybrid / evap).
- HMT / DLUHC Freeport business-rates relief scheme:
    £275k / 5-yr anchor for a ~2 MW pilot scales roughly linearly,
    +£550k / 5-yr per additional 10 MW IT load on site.
- UK Ofgem industrial electricity price path 2026:
    £90–130 /MWh PPA base, £160–210 /MWh unhedged merchant peaks.
    We use £110 /MWh as 2026 PPA-mid default for modelling.

Conventions
-----------
All functions return plain floats (or ints where counts are sensible) in
£ (GBP), kW, MWh, L, etc. No side-effects. No DB. Safe to import from any
module. Callers should *not* cache these values — this module is designed
to be re-read on every invocation so benchmarks can be updated centrally.
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# Enums / literals
# ---------------------------------------------------------------------------

Tier = Literal[1, 2, 3, 4]
Redundancy = Literal["N", "N+1", "2N", "2N+1"]
WorkloadType = Literal["hyperscale", "colo", "edge", "ai_training"]
CoolingTopology = Literal["dry", "hybrid", "evap"]

# ---------------------------------------------------------------------------
# CapEx — £M per MW IT (all-in: shell, power, cooling, fit-out, soft costs)
# ---------------------------------------------------------------------------

# Tier midpoints (H1 2025 Cushman & Wakefield + CBRE).
# The *range* matters for scenario bands — P10 / P50 / P90 planning.
CAPEX_PER_MW_M = {
    1: {"lo": 2.2, "mid": 2.6, "hi": 3.0},   # lightly redundant (rare in UK new-build)
    2: {"lo": 2.8, "mid": 3.3, "hi": 3.8},   # colo / retrofit
    3: {"lo": 3.5, "mid": 4.2, "hi": 5.0},   # modern hyperscale concurrent-maintainable
    4: {"lo": 4.5, "mid": 5.3, "hi": 6.2},   # 2N fault-tolerant / mission-critical
}

# Workload-type multiplier on CapEx/MW.
# Hyperscale benefits from scale (-5%); AI training racks need higher
# density + liquid cooling readiness (+18%). Edge sites pay a site-overhead
# premium because shell costs amortise across a smaller load (+12%).
WORKLOAD_CAPEX_MULT = {
    "hyperscale":  0.95,
    "colo":        1.00,
    "edge":        1.12,
    "ai_training": 1.18,
}

# Redundancy multiplier on CapEx/MW for distribution + mechanical trains.
# 2N doubles the electrical distribution cost but not the shell. The net
# uplift over N+1 is ~20%, not 100%.
REDUNDANCY_CAPEX_MULT = {
    "N":    0.92,
    "N+1":  1.00,
    "2N":   1.20,
    "2N+1": 1.28,
}


def capex_per_mw_m(
    tier: Tier = 3,
    redundancy: Redundancy = "N+1",
    workload_type: WorkloadType = "colo",
    band: Literal["lo", "mid", "hi"] = "mid",
) -> float:
    """Return all-in CapEx in £M per MW IT for the given configuration.

    Example:
        >>> capex_per_mw_m(tier=3, redundancy="N+1", workload_type="hyperscale")
        3.99  # £3.99 M/MW IT

    Combine with ``capex_per_mw_m(tier=3, band='lo')`` / ``band='hi'`` for
    a P10 / P90 scenario band (Uptime + JLL confirm ±20% around midpoint is
    the realistic market spread for Tier 3 in UK 2026).
    """
    base = CAPEX_PER_MW_M[int(tier)][band]
    mult_w = WORKLOAD_CAPEX_MULT.get(workload_type, 1.0)
    mult_r = REDUNDANCY_CAPEX_MULT.get(redundancy, 1.0)
    return round(base * mult_w * mult_r, 2)


def capex_total_gbp(
    it_load_mw: float,
    tier: Tier = 3,
    redundancy: Redundancy = "N+1",
    workload_type: WorkloadType = "colo",
    band: Literal["lo", "mid", "hi"] = "mid",
) -> float:
    """Return total CapEx in £ (not £M) for a site."""
    return it_load_mw * capex_per_mw_m(tier, redundancy, workload_type, band) * 1_000_000


# ---------------------------------------------------------------------------
# OpEx — £ per MW IT per year (ex-power; power is modelled separately)
# ---------------------------------------------------------------------------

# CBRE 2025 breakdown, 2026 uplifted:
#   Staff          £80 k / MW IT / yr
#   Maintenance    £160 k / MW IT / yr  (3-4% of CapEx spread)
#   Property/rates £80 k / MW IT / yr
#   Other          £30 k / MW IT / yr
#   -----------
#   Ex-power       £350 k / MW IT / yr   (was £250 k before 2026-04 audit)
OPEX_EX_POWER_PER_MW_YR = {
    "staff":        80_000,
    "maintenance":  160_000,
    "property":     80_000,
    "other":        30_000,
}

OPEX_EX_POWER_PER_MW_YR_TOTAL = sum(OPEX_EX_POWER_PER_MW_YR.values())  # 350_000


def opex_per_mw_yr(
    tier: Tier = 3,
    workload_type: WorkloadType = "colo",
) -> float:
    """Return ex-power OpEx in £ per MW IT per year.

    Tier 4 carries ~15% staffing + maintenance premium (dual-train
    maintenance windows + more SMEs). Edge sites pay a ~10% overhead
    because the fixed ops team cost is thinly spread.
    """
    base = OPEX_EX_POWER_PER_MW_YR_TOTAL
    tier_mult = {1: 0.85, 2: 0.92, 3: 1.00, 4: 1.15}.get(int(tier), 1.0)
    wl_mult = {"hyperscale": 0.93, "colo": 1.00, "edge": 1.10, "ai_training": 1.05}.get(
        workload_type, 1.0
    )
    return base * tier_mult * wl_mult


def opex_total_gbp_yr(
    it_load_mw: float,
    pue: float | None = None,
    tier: Tier = 3,
    workload_type: WorkloadType = "colo",
    power_price_gbp_mwh: float = 110.0,
    utilisation: float = 0.85,
) -> dict:
    """Return a full annual OpEx breakdown in £ for a site.

    Power cost uses facility energy = IT load × PUE × utilisation × 8760.

    Parameters
    ----------
    pue : float or None
        If None, uses :func:`pue_target`.
    power_price_gbp_mwh : float
        £/MWh — default £110 is 2026 UK industrial PPA mid.
    utilisation : float
        Fraction of nameplate IT load actually drawn. UK colo typical 0.85,
        hyperscale 0.90, AI training 0.78 (bursty).
    """
    if pue is None:
        pue = pue_target(tier=tier, workload_type=workload_type)

    it_load_kw = it_load_mw * 1000
    facility_kw = it_load_kw * pue
    annual_mwh = facility_kw * 8760 * utilisation / 1000

    power_cost = annual_mwh * power_price_gbp_mwh
    ex_power = opex_per_mw_yr(tier=tier, workload_type=workload_type) * it_load_mw

    return {
        "power_gbp": round(power_cost),
        "staff_gbp": round(OPEX_EX_POWER_PER_MW_YR["staff"] * it_load_mw),
        "maintenance_gbp": round(OPEX_EX_POWER_PER_MW_YR["maintenance"] * it_load_mw),
        "property_gbp": round(OPEX_EX_POWER_PER_MW_YR["property"] * it_load_mw),
        "other_gbp": round(OPEX_EX_POWER_PER_MW_YR["other"] * it_load_mw),
        "total_gbp": round(power_cost + ex_power),
        "total_ex_power_gbp": round(ex_power),
        "annual_mwh_facility": round(annual_mwh),
        "power_price_gbp_mwh": power_price_gbp_mwh,
        "pue": pue,
        "utilisation": utilisation,
    }


# ---------------------------------------------------------------------------
# PUE / WUE
# ---------------------------------------------------------------------------

# Uptime Institute 2024 + JLL 2026 targets.
# Cold-climate optimised (Nordic-style free cooling, UK Scotland/North-East)
# sits at 1.18; UK hyperscale median 1.25; colo legacy 1.35; retrofit 1.45.
PUE_TARGETS = {
    "cold_climate":   1.18,
    "uk_hyperscale":  1.25,
    "colo_modern":    1.30,
    "colo_legacy":    1.35,
    "retrofit":       1.45,
}


def pue_target(
    tier: Tier = 3,
    workload_type: WorkloadType = "colo",
    cooling_topology: CoolingTopology = "hybrid",
    lat: float = 52.0,
) -> float:
    """Return a sensible design-target PUE for the configuration.

    Latitude > 54°N (Scotland / north-east England) shaves ~0.04 off the
    hyperscale target thanks to longer free-cooling hours. Evaporative
    cooling shaves another 0.02. Dry (air-only) adds 0.03.
    """
    # Base by workload
    base = {
        "hyperscale":  1.25,
        "colo":        1.30,
        "edge":        1.35,
        "ai_training": 1.20,  # liquid-ready => lower PUE
    }.get(workload_type, 1.30)

    # Tier correction — Tier 4 2N mechanical adds a small overhead
    tier_delta = {1: 0.05, 2: 0.02, 3: 0.0, 4: 0.03}.get(int(tier), 0.0)

    # Climate / topology correction
    climate_delta = -0.04 if lat >= 54.0 else 0.0
    topology_delta = {"dry": 0.03, "hybrid": 0.0, "evap": -0.02}.get(cooling_topology, 0.0)

    return round(base + tier_delta + climate_delta + topology_delta, 3)


# Water Usage Effectiveness (L per kWh of IT load).
# JLL 2026: 0 (fully dry / closed-loop), 0.3 (hybrid / adiabatic trim),
# 1.2 (full evaporative). UK 2025 median colo ~0.8 L/kWh.
WUE_L_PER_KWH = {
    "dry":    0.0,
    "hybrid": 0.3,
    "evap":   1.2,
}


def wue_l_per_kwh(cooling_topology: CoolingTopology = "hybrid") -> float:
    return WUE_L_PER_KWH.get(cooling_topology, 0.3)


# ---------------------------------------------------------------------------
# Lease / colocation revenue
# ---------------------------------------------------------------------------

# 2026 UK wholesale hyperscaler lease (M/MW/yr IT). Source: Cushman H1 2025.
# London I/O commands the premium; Manchester / Edinburgh / Cambridge trade
# at ~85% of London; edge regional at ~70%.
WHOLESALE_LEASE_GBP_M_MW_YR = {
    "lo":  2.4,
    "mid": 2.8,
    "hi":  3.2,
}

# Colo retail (racks + cross-connects + remote hands) — broader band because
# price depends heavily on SKU mix.
COLO_RETAIL_GBP_M_MW_YR = {
    "lo":  4.0,
    "mid": 6.0,
    "hi":  8.0,
}


def lease_revenue_gbp_mw_yr(
    workload_type: WorkloadType = "colo",
    band: Literal["lo", "mid", "hi"] = "mid",
) -> float:
    """Return £/MW/yr revenue per the 2026 UK benchmarks."""
    if workload_type in ("hyperscale", "ai_training"):
        return WHOLESALE_LEASE_GBP_M_MW_YR[band] * 1_000_000
    if workload_type == "edge":
        return COLO_RETAIL_GBP_M_MW_YR[band] * 0.85 * 1_000_000
    return COLO_RETAIL_GBP_M_MW_YR[band] * 1_000_000


def revenue_gbp_yr(
    it_load_mw: float,
    workload_type: WorkloadType = "colo",
    band: Literal["lo", "mid", "hi"] = "mid",
    occupancy: float = 0.85,
) -> float:
    """Return total annual revenue £ at a given occupancy."""
    return lease_revenue_gbp_mw_yr(workload_type, band) * it_load_mw * occupancy


# ---------------------------------------------------------------------------
# Business-rates / freeport relief scaling
# ---------------------------------------------------------------------------

# HMT Freeport Scheme 2023/24 onwards: 5-year 100% business-rates relief on
# qualifying plant & machinery in a Freeport tax site. The anchor figure of
# £275k / 5-yr is roughly a 2 MW IT load site. For larger loads the relief
# scales linearly, capped at the full UK standard rate for a multiplier of
# ~£55k / MW IT / yr (DC-specific rateable valuation 2024 VOA data).

RATES_RELIEF_ANCHOR_MW = 2.0
RATES_RELIEF_ANCHOR_GBP_5YR = 275_000  # per 2 MW pilot
RATES_RELIEF_PER_ADDITIONAL_10MW_5YR = 550_000
RATES_PER_MW_YR = 55_000  # DC rateable value mid-UK 2024 VOA


def rates_relief_5yr_gbp(
    it_load_mw: float,
    zone_type: str = "freeport",
) -> int:
    """Return freeport / enterprise-zone business-rates relief over 5 years.

    Linear scaling from the 2 MW anchor:
        2 MW  → £275 k
        12 MW → £275 k + 1 × £550 k  = £825 k
        52 MW → £275 k + 5 × £550 k  = £3,025 k
        102 MW → £275 k + 10 × £550 k = £5,775 k

    Investment / Enterprise zones get a flat £150 k / £275 k at the anchor
    and do NOT scale (non-freeport relief is capped by DLUHC designation).
    """
    if zone_type == "freeport" or zone_type == "freeport_ai_zone":
        extra_mw = max(0.0, it_load_mw - RATES_RELIEF_ANCHOR_MW)
        extra_units = extra_mw / 10.0
        relief = RATES_RELIEF_ANCHOR_GBP_5YR + int(extra_units * RATES_RELIEF_PER_ADDITIONAL_10MW_5YR)
        # Cap at the gross liability — can't get more relief than the rates
        gross_5yr = int(RATES_PER_MW_YR * it_load_mw * 5)
        return min(relief, gross_5yr)
    if zone_type == "investment_zone":
        return 150_000
    if zone_type == "enterprise_zone":
        return 275_000
    return 0


# ---------------------------------------------------------------------------
# Construction cost sanity-bands (for legacy dc_planner CAPEX sense-check)
# ---------------------------------------------------------------------------

def sanity_check_capex(
    it_load_mw: float,
    capex_gbp: float,
    tier: Tier = 3,
) -> dict:
    """Return whether a computed CapEx falls within the 2026 UK market band.

    Returns a dict with 'ok' boolean + diagnostic deltas. Useful in tests +
    report generation to flag obvious misconfigurations.
    """
    lo = capex_total_gbp(it_load_mw, tier=tier, band="lo") * 0.9   # -10% floor
    hi = capex_total_gbp(it_load_mw, tier=tier, band="hi") * 1.1   # +10% ceiling
    mid = capex_total_gbp(it_load_mw, tier=tier, band="mid")
    return {
        "ok": lo <= capex_gbp <= hi,
        "computed_gbp": capex_gbp,
        "benchmark_mid_gbp": mid,
        "floor_gbp": lo,
        "ceiling_gbp": hi,
        "delta_vs_mid_pct": round((capex_gbp / mid - 1) * 100, 1) if mid else 0.0,
    }


# ---------------------------------------------------------------------------
# Provenance / citation string
# ---------------------------------------------------------------------------

def cite() -> str:
    """Human-readable citation string for report footnotes."""
    return (
        "Cushman & Wakefield UK & Ireland DC Market H1 2025; "
        "CBRE Global Data Centre Trends H1 2025; "
        "Uptime Institute Global DC Survey 2024; "
        "JLL Global Data Center Outlook 2026."
    )
