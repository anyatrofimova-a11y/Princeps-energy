"""Civil earthworks — cut/fill estimates from DTM slope statistics, access-road checks.

Two paths:
  1. LiDAR-backed — DTM raster supplied as a 2D numpy array → full cut/fill.
  2. Analytic fallback — slope mean/std + area → estimate volume from RMS.

References:
  - UK Highways England DMRB CD 523 — earthwork cut/fill design.
  - DMRB CD 109 — highway design, maximum longitudinal grade (6% HGV, 8% car).
  - Eurocode 7 Part 1 (BS EN 1997-1) — geotechnical design.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from typing import Any

try:
    import numpy as np
    _HAS_NP = True
except ImportError:  # pragma: no cover
    _HAS_NP = False


# Cost benchmarks (GBP/m3, UK 2024)
COST_CUT_PER_M3 = 8.5         # excavate + haul + compact
COST_FILL_PER_M3 = 14.0       # import fill is premium
COST_DISPOSE_PER_M3 = 18.0    # off-site disposal of surplus

# Access-road standards (DMRB CD 109 / AGEC)
MAX_GRADE_HGV_PCT = 6.0
MAX_GRADE_CAR_PCT = 8.0
MAX_GRADE_EMERGENCY_PCT = 10.0


@dataclass
class EarthworksResult:
    inputs_echo: dict
    outputs: dict
    assumptions: list[str]
    provenance: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# DTM path
# ---------------------------------------------------------------------------
def cut_fill_from_dtm(
    dtm: list[list[float]],
    target_grade_m: list[list[float]] | None,
    cell_size_m: float,
) -> tuple[float, float, dict]:
    """Compute cut/fill volumes vs a target grade surface.

    If `target_grade_m` is None, target = cell-wise mean of DTM (i.e. level
    cut to mean elevation).
    """
    if not _HAS_NP:
        raise RuntimeError("numpy required for DTM-backed cut/fill")
    dtm_a = np.asarray(dtm, dtype=float)
    if dtm_a.ndim != 2:
        raise ValueError("dtm must be 2D")
    if target_grade_m is None:
        target = np.full_like(dtm_a, float(np.nanmean(dtm_a)))
    else:
        target = np.asarray(target_grade_m, dtype=float)
        if target.shape != dtm_a.shape:
            raise ValueError("target_grade_m shape must match dtm")

    delta = dtm_a - target  # positive → cut, negative → fill
    cell_area = cell_size_m * cell_size_m
    cut_m3 = float(np.nansum(np.maximum(delta, 0)) * cell_area)
    fill_m3 = float(np.nansum(np.maximum(-delta, 0)) * cell_area)
    stats = {
        "elevation_min_m": float(np.nanmin(dtm_a)),
        "elevation_max_m": float(np.nanmax(dtm_a)),
        "elevation_mean_m": float(np.nanmean(dtm_a)),
        "elevation_std_m": float(np.nanstd(dtm_a)),
        "n_cells": int(dtm_a.size),
    }
    return cut_m3, fill_m3, stats


# ---------------------------------------------------------------------------
# Analytic path (no LiDAR)
# ---------------------------------------------------------------------------
def cut_fill_analytic(
    area_m2: float,
    mean_slope_pct: float,
    slope_std_pct: float,
    platform_target: str = "level",
) -> tuple[float, float]:
    """Estimate cut/fill from slope statistics alone (screening level)."""
    if area_m2 <= 0:
        raise ValueError("area_m2 > 0")
    # Characteristic length of square footprint
    side_m = math.sqrt(area_m2)

    # Expected elevation RMS across site = (slope/100) * side * normalisation
    rms_m = (mean_slope_pct / 100.0) * side_m / 2.0
    rms_m += (slope_std_pct / 100.0) * side_m / 4.0  # std contribution

    # For a gaussian elevation surface around a level target, cut≈fill≈0.4·RMS·A
    base_vol = 0.4 * rms_m * area_m2
    if platform_target == "level":
        return base_vol, base_vol
    elif platform_target == "graded":
        # Graded to follow slope — much less volume
        return 0.25 * base_vol, 0.25 * base_vol
    else:
        return base_vol, base_vol


# ---------------------------------------------------------------------------
# Public facade
# ---------------------------------------------------------------------------
def estimate_earthworks(
    area_m2: float,
    mean_slope_pct: float = 3.0,
    slope_std_pct: float = 1.5,
    platform_target: str = "level",
    dtm: list[list[float]] | None = None,
    target_grade_m: list[list[float]] | None = None,
    cell_size_m: float = 5.0,
) -> EarthworksResult:
    """Top-level earthworks estimator with both code paths."""
    if area_m2 <= 0:
        raise ValueError("area_m2 > 0")
    warnings = []
    stats: dict[str, Any] = {}

    if dtm is not None and _HAS_NP:
        cut, fill, stats = cut_fill_from_dtm(dtm, target_grade_m, cell_size_m)
        source = "dtm"
    else:
        if dtm is not None and not _HAS_NP:
            warnings.append("numpy unavailable — fell back to analytic")
        cut, fill = cut_fill_analytic(area_m2, mean_slope_pct, slope_std_pct, platform_target)
        source = "analytic"

    surplus = abs(cut - fill)
    mass_haul_m3 = min(cut, fill)   # balanced on-site haul
    import_or_export_m3 = surplus   # net surplus → export; net deficit → import

    cost_cut = cut * COST_CUT_PER_M3
    cost_fill = (fill if cut >= fill else fill) * COST_FILL_PER_M3
    cost_dispose = (cut - fill) * COST_DISPOSE_PER_M3 if cut > fill else 0.0
    cost_import = (fill - cut) * COST_FILL_PER_M3 if fill > cut else 0.0
    total_cost = cost_cut + cost_fill + cost_dispose + cost_import

    if mean_slope_pct > 10:
        warnings.append(f"mean slope {mean_slope_pct}% — significant grading, retaining structures likely")
    if surplus / max(1.0, max(cut, fill)) > 0.4:
        warnings.append("cut/fill imbalance > 40% — consider re-grading to reduce import/export cost")

    return EarthworksResult(
        inputs_echo={
            "area_m2": area_m2, "mean_slope_pct": mean_slope_pct,
            "slope_std_pct": slope_std_pct,
            "platform_target": platform_target,
            "dtm_provided": dtm is not None,
            "cell_size_m": cell_size_m,
        },
        outputs={
            "cut_m3": round(cut, 1),
            "fill_m3": round(fill, 1),
            "balanced_haul_m3": round(mass_haul_m3, 1),
            "net_import_export_m3": round(import_or_export_m3, 1),
            "cost_gbp": round(total_cost, 0),
            "cost_breakdown_gbp": {
                "cut": round(cost_cut, 0),
                "fill": round(cost_fill, 0),
                "dispose_surplus": round(cost_dispose, 0),
                "import_deficit": round(cost_import, 0),
            },
            "dtm_stats": stats,
            "method": source,
        },
        assumptions=[
            f"Cut £{COST_CUT_PER_M3}/m³, fill £{COST_FILL_PER_M3}/m³, dispose £{COST_DISPOSE_PER_M3}/m³",
            "Gaussian elevation prior for analytic fallback",
            "DMRB CD 523 earthwork rates (UK 2024)",
        ],
        provenance="Highways England DMRB CD 523; Eurocode 7 BS EN 1997-1",
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Access road grade/length check
# ---------------------------------------------------------------------------
def access_road_check(
    start_elev_m: float,
    end_elev_m: float,
    road_length_m: float,
    vehicle_class: str = "HGV",
) -> EarthworksResult:
    """Check longitudinal grade against DMRB CD 109 class limits."""
    if road_length_m <= 0:
        raise ValueError("road_length_m > 0")

    rise = end_elev_m - start_elev_m
    grade_pct = 100.0 * rise / road_length_m

    limit = {
        "HGV": MAX_GRADE_HGV_PCT,
        "car": MAX_GRADE_CAR_PCT,
        "emergency": MAX_GRADE_EMERGENCY_PCT,
    }.get(vehicle_class, MAX_GRADE_HGV_PCT)

    compliant = abs(grade_pct) <= limit
    # If non-compliant, compute additional length needed
    min_length_m = abs(rise) * 100.0 / limit if not compliant else road_length_m
    additional_m = max(0.0, min_length_m - road_length_m)

    warnings = []
    if not compliant:
        warnings.append(
            f"grade {grade_pct:.1f}% > {vehicle_class} limit {limit}% — extend by {additional_m:.0f} m"
        )
    if abs(grade_pct) > MAX_GRADE_EMERGENCY_PCT:
        warnings.append("grade exceeds emergency-vehicle limit — fire brigade objection likely")

    return EarthworksResult(
        inputs_echo={
            "start_elev_m": start_elev_m, "end_elev_m": end_elev_m,
            "road_length_m": road_length_m, "vehicle_class": vehicle_class,
        },
        outputs={
            "grade_pct": round(grade_pct, 2),
            "grade_limit_pct": limit,
            "compliant": compliant,
            "min_required_length_m": round(min_length_m, 0),
            "additional_length_m": round(additional_m, 0),
        },
        assumptions=[
            "Single constant-grade segment",
            f"Limits per DMRB CD 109 for {vehicle_class}",
        ],
        provenance="Highways England DMRB CD 109",
        warnings=warnings,
    )
