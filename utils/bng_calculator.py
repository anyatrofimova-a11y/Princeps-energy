"""
Biodiversity Net Gain (BNG) calculator — pragmatic port of Natural
England's Statutory Biodiversity Metric using UKHab v2.0 habitat
classifications.

Background
----------
The Environment Act 2021 (s.98) made Biodiversity Net Gain a mandatory
condition of most Town & Country Planning Act permissions in England from
12 February 2024. Developments must demonstrate a minimum 10% net gain
in biodiversity units, calculated using Natural England's Statutory
Biodiversity Metric (v1.0, 29 November 2023; minor tooling update
July 2025). The Metric 4.0 lookup tables were preserved structurally
inside the statutory tool. The broad habitat taxonomy used here is UK
Habitat Classification (UKHab) v2.0 — the hierarchical classification
referenced by the Metric.

Calculation (baseline, per habitat parcel)
------------------------------------------
    biodiversity_units = area_ha
                       × distinctiveness_score
                       × condition_score
                       × strategic_significance_multiplier

Post-intervention (created / enhanced habitats) additionally apply:
    × temporal_multiplier (years-to-target)
    × difficulty_multiplier
    × spatial_risk_multiplier

The figures embedded below follow Statutory Biodiversity Metric (v1.0)
Technical Annex 1 tables (structurally unchanged from Metric 4.0).
They are a pragmatic port — not a substitute for the official spreadsheet
which an accredited ecologist must run for a submission. The site-pack
output makes that disclaimer explicit and cites the Metric version used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


# ─────────────────────────────────────────────────────────────────────────────
# UKHab v2.0 — broad habitat groups with Statutory Biodiversity Metric v1.0 distinctiveness bands
# ─────────────────────────────────────────────────────────────────────────────
# Distinctiveness: V.High=8, High=6, Medium=4, Low=2, V.Low=0 (Statutory Metric v1.0)
UKHAB_DISTINCTIVENESS: dict[str, dict] = {
    # UKHab code → default distinctiveness band + score + example habitat
    "cropland": {
        "code": "c",
        "label": "Cropland (arable, horticulture, intensive orchards)",
        "band": "Low",
        "score": 2,
    },
    "grassland": {
        "code": "g",
        "label": "Grassland (modified / semi-improved)",
        "band": "Medium",
        "score": 4,
    },
    "grassland_low": {
        "code": "g4",
        "label": "Modified grassland (improved / reseeded ley)",
        "band": "Low",
        "score": 2,
    },
    "grassland_high": {
        "code": "g3c",
        "label": "Other neutral / lowland meadow",
        "band": "High",
        "score": 6,
    },
    "woodland": {
        "code": "w",
        "label": "Woodland & forest (broadleaved / mixed / plantation)",
        "band": "High",
        "score": 6,
    },
    "woodland_ancient": {
        "code": "w1f",
        "label": "Lowland mixed deciduous woodland (ancient)",
        "band": "V.High",
        "score": 8,
    },
    "heathland": {
        "code": "h",
        "label": "Heathland & shrub (dry / wet heath, scrub)",
        "band": "High",
        "score": 6,
    },
    "wetland": {
        "code": "f",
        "label": "Wetland (fen, marsh, swamp, bog)",
        "band": "High",
        "score": 6,
    },
    "urban": {
        "code": "u",
        "label": "Urban / developed (buildings, hardstanding, gardens)",
        "band": "V.Low",
        "score": 0,
    },
    "urban_green": {
        "code": "u1b",
        "label": "Urban — amenity grass / introduced shrub",
        "band": "Low",
        "score": 2,
    },
    "sparsely_vegetated": {
        "code": "s",
        "label": "Sparsely vegetated land (rock, bare ground, scree)",
        "band": "Low",
        "score": 2,
    },
    "coastal": {
        "code": "t",
        "label": "Coastal (saltmarsh, dunes, shingle)",
        "band": "High",
        "score": 6,
    },
}

# Condition multiplier (Statutory Metric v1.0 Table 2)
CONDITION_SCORES: dict[str, float] = {
    "good": 3.0,
    "moderate": 2.0,
    "fairly_good": 2.5,       # wetlands / woodlands half-step
    "fairly_poor": 1.5,
    "poor": 1.0,
    "condition_assessment_not_required": 1.0,
    "n/a": 1.0,
}

# Strategic significance (Statutory Metric v1.0 Table 3)
STRATEGIC_SIGNIFICANCE: dict[str, float] = {
    "high": 1.15,   # formally identified in Local Nature Recovery Strategy
    "medium": 1.10, # local strategy / biodiversity priority
    "low": 1.00,    # area not identified
}

# Difficulty of creation / enhancement (Statutory Metric v1.0 Table 4, indicative)
DIFFICULTY_MULTIPLIER: dict[str, float] = {
    "very_high": 0.1,
    "high": 0.33,
    "medium": 0.67,
    "low": 1.00,
}

# Temporal multiplier lookup — years to target condition (Statutory Metric v1.0 Table 5)
# Figures here are representative; the tool gives habitat-specific values.
TEMPORAL_MULTIPLIER: dict[int, float] = {
    0: 1.000,
    5: 0.868,
    10: 0.756,
    15: 0.660,
    20: 0.577,
    25: 0.505,
    30: 0.442,
}

# Default Defra 10% net-gain threshold (Environment Act 2021 s.98, Sch. 7A)
NET_GAIN_THRESHOLD_PCT: float = 10.0

METRIC_VERSION: str = "Statutory Biodiversity Metric v1.0 (29 Nov 2023; minor tooling update Jul 2025)"
UKHAB_VERSION: str = "UK Habitat Classification v2.0"


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class HabitatParcel:
    """A baseline UKHab habitat parcel on the site."""
    habitat: str                              # key in UKHAB_DISTINCTIVENESS
    area_ha: float
    condition: str = "moderate"               # key in CONDITION_SCORES
    strategic_significance: str = "low"       # key in STRATEGIC_SIGNIFICANCE


@dataclass
class Intervention:
    """A post-development habitat (retained, created, enhanced, or lost)."""
    habitat: str
    area_ha: float
    condition: str = "moderate"
    strategic_significance: str = "low"
    action: str = "created"                   # created | enhanced | retained | lost
    years_to_target: int = 10
    difficulty: str = "medium"                # difficulty band
    spatial_risk: float = 1.0                 # 1.0 on-site, 0.5 off-site local, 0.3 strategic


@dataclass
class BNGResult:
    metric_version: str = METRIC_VERSION
    ukhab_version: str = UKHAB_VERSION
    threshold_pct: float = NET_GAIN_THRESHOLD_PCT
    baseline_units: float = 0.0
    post_units: float = 0.0
    units_lost: float = 0.0
    units_created: float = 0.0
    units_enhanced: float = 0.0
    net_change_units: float = 0.0
    net_change_pct: float = 0.0
    compliant: bool = False
    baseline_rows: list[dict] = field(default_factory=list)
    post_rows: list[dict] = field(default_factory=list)
    summary: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Core maths
# ─────────────────────────────────────────────────────────────────────────────
def _lookup(habitat: str) -> dict:
    """Resolve a habitat key, falling back to `grassland` if unknown."""
    return UKHAB_DISTINCTIVENESS.get(habitat) or UKHAB_DISTINCTIVENESS["grassland"]


def _baseline_units(parcel: HabitatParcel) -> float:
    """Baseline biodiversity units (Statutory Biodiversity Metric v1.0 baseline formula)."""
    h = _lookup(parcel.habitat)
    dist = float(h["score"])
    cond = float(CONDITION_SCORES.get(parcel.condition, 2.0))
    strat = float(STRATEGIC_SIGNIFICANCE.get(parcel.strategic_significance, 1.0))
    return float(parcel.area_ha) * dist * cond * strat


def _post_units(iv: Intervention) -> float:
    """Post-intervention units, including temporal / difficulty / risk multipliers."""
    h = _lookup(iv.habitat)
    dist = float(h["score"])
    cond = float(CONDITION_SCORES.get(iv.condition, 2.0))
    strat = float(STRATEGIC_SIGNIFICANCE.get(iv.strategic_significance, 1.0))
    # Temporal multiplier — interpolate between anchor years
    years = int(iv.years_to_target)
    anchors = sorted(TEMPORAL_MULTIPLIER.keys())
    if years <= anchors[0]:
        temporal = TEMPORAL_MULTIPLIER[anchors[0]]
    elif years >= anchors[-1]:
        temporal = TEMPORAL_MULTIPLIER[anchors[-1]]
    else:
        lo = max(a for a in anchors if a <= years)
        hi = min(a for a in anchors if a >= years)
        if lo == hi:
            temporal = TEMPORAL_MULTIPLIER[lo]
        else:
            t = (years - lo) / (hi - lo)
            temporal = TEMPORAL_MULTIPLIER[lo] + t * (TEMPORAL_MULTIPLIER[hi] - TEMPORAL_MULTIPLIER[lo])

    difficulty = float(DIFFICULTY_MULTIPLIER.get(iv.difficulty, 0.67))
    risk = float(iv.spatial_risk)
    base = float(iv.area_ha) * dist * cond * strat

    if iv.action == "retained":
        # Retained habitat keeps baseline units (no temporal / difficulty penalty)
        return base
    if iv.action == "lost":
        return 0.0
    # created / enhanced
    return base * temporal * difficulty * risk


def _row_baseline(parcel: HabitatParcel) -> dict:
    h = _lookup(parcel.habitat)
    units = _baseline_units(parcel)
    return {
        "habitat": h["label"],
        "ukhab_code": h["code"],
        "area_ha": round(float(parcel.area_ha), 3),
        "distinctiveness": h["band"],
        "distinctiveness_score": h["score"],
        "condition": parcel.condition,
        "condition_score": CONDITION_SCORES.get(parcel.condition, 2.0),
        "strategic": parcel.strategic_significance,
        "strategic_multiplier": STRATEGIC_SIGNIFICANCE.get(parcel.strategic_significance, 1.0),
        "units": round(units, 2),
    }


def _row_post(iv: Intervention) -> dict:
    h = _lookup(iv.habitat)
    units = _post_units(iv)
    return {
        "habitat": h["label"],
        "ukhab_code": h["code"],
        "area_ha": round(float(iv.area_ha), 3),
        "action": iv.action,
        "distinctiveness": h["band"],
        "condition": iv.condition,
        "years_to_target": iv.years_to_target,
        "difficulty": iv.difficulty,
        "spatial_risk": iv.spatial_risk,
        "units": round(units, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def calculate_bng(baseline: Iterable[HabitatParcel],
                  interventions: Iterable[Intervention],
                  threshold_pct: float = NET_GAIN_THRESHOLD_PCT) -> BNGResult:
    """Calculate baseline + post-intervention biodiversity units and compliance."""
    baseline_list = list(baseline)
    intervention_list = list(interventions)

    baseline_units = sum(_baseline_units(p) for p in baseline_list)
    post_units = sum(_post_units(iv) for iv in intervention_list)

    units_created = sum(_post_units(iv) for iv in intervention_list if iv.action == "created")
    units_enhanced = sum(_post_units(iv) for iv in intervention_list if iv.action == "enhanced")
    units_lost = sum(_baseline_units(HabitatParcel(iv.habitat, iv.area_ha, iv.condition, iv.strategic_significance))
                     for iv in intervention_list if iv.action == "lost")

    net_change_units = post_units - baseline_units
    net_change_pct = (net_change_units / baseline_units * 100.0) if baseline_units > 0 else 0.0
    compliant = net_change_pct >= threshold_pct

    summary = (
        f"Baseline {baseline_units:.2f} units → post-development {post_units:.2f} units "
        f"({net_change_pct:+.1f}% net change). "
        f"{'MEETS' if compliant else 'BELOW'} statutory {threshold_pct:.0f}% net-gain threshold."
    )

    return BNGResult(
        threshold_pct=threshold_pct,
        baseline_units=round(baseline_units, 2),
        post_units=round(post_units, 2),
        units_lost=round(units_lost, 2),
        units_created=round(units_created, 2),
        units_enhanced=round(units_enhanced, 2),
        net_change_units=round(net_change_units, 2),
        net_change_pct=round(net_change_pct, 2),
        compliant=compliant,
        baseline_rows=[_row_baseline(p) for p in baseline_list],
        post_rows=[_row_post(iv) for iv in intervention_list],
        summary=summary,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: derive a baseline + default solar-farm intervention plan from
# a land-use class percentage dict (as emitted by GeeFlow / DynamicWorld).
# ─────────────────────────────────────────────────────────────────────────────
DW_TO_UKHAB: dict[str, str] = {
    "crops": "cropland",
    "grass": "grassland_low",
    "trees": "woodland",
    "shrub_and_scrub": "heathland",
    "flooded_vegetation": "wetland",
    "water": "wetland",
    "built": "urban",
    "bare": "sparsely_vegetated",
    "snow_and_ice": "sparsely_vegetated",
}


def bng_from_land_use(land_use: dict, capacity_mw: float,
                      footprint_frac: float = 0.35,
                      tech: str = "solar") -> BNGResult:
    """Build a pragmatic BNG baseline + post-development scenario from a
    land-use class-percentage dict (DynamicWorld / GeeFlow style).

    Conservative intervention plan for a UK solar / BESS site:
        • Panel footprint occupies ``footprint_frac`` of total area —
          modelled as `urban_green` (amenity grass under panels, poor cond).
        • The remaining area is enhanced to `grassland_high`
          (meadow / species-rich mix) — solar farms' standard BNG route.
        • 5 % of the site is planted as `woodland` (native hedgerow / copse).
    """
    classes = (land_use or {}).get("class_percentages", {}) or {}
    # Rough site-area heuristic: 2 ha per MW for solar PV
    total_ha = max(float(capacity_mw) * 2.0, 1.0)

    baseline: list[HabitatParcel] = []
    for cls, pct in classes.items():
        if not pct:
            continue
        ha = total_ha * float(pct) / 100.0
        if ha <= 0:
            continue
        ukhab = DW_TO_UKHAB.get(cls, "grassland_low")
        # Agricultural land typically moderate condition; water/wetland fairly_good.
        cond = "moderate" if ukhab != "wetland" else "fairly_good"
        baseline.append(HabitatParcel(habitat=ukhab, area_ha=ha, condition=cond))

    # If land-use dict was empty, assume site is all `cropland` (UK default)
    if not baseline:
        baseline = [HabitatParcel(habitat="cropland", area_ha=total_ha, condition="moderate")]

    # ── Post-intervention plan (Statutory Metric v1.0 created / enhanced habitats) ──
    panel_ha = total_ha * float(footprint_frac)
    hedgerow_ha = total_ha * 0.05
    meadow_ha = max(total_ha - panel_ha - hedgerow_ha, 0.0)

    interventions: list[Intervention] = [
        Intervention(
            habitat="urban_green",
            area_ha=panel_ha,
            condition="poor",
            action="created",
            years_to_target=5,
            difficulty="low",
        ),
        Intervention(
            habitat="grassland_high",
            area_ha=meadow_ha,
            condition="moderate",
            strategic_significance="medium",
            action="enhanced",
            years_to_target=10,
            difficulty="medium",
        ),
        Intervention(
            habitat="woodland",
            area_ha=hedgerow_ha,
            condition="moderate",
            strategic_significance="medium",
            action="created",
            years_to_target=15,
            difficulty="medium",
        ),
    ]

    # Non-solar technologies (e.g. standalone BESS) have smaller enhancement
    # scope — suppress meadow enhancement if tech is BESS-only.
    if tech and "bess" in tech.lower() and "solar" not in tech.lower():
        interventions = [iv for iv in interventions if iv.habitat != "grassland_high"]

    return calculate_bng(baseline, interventions)


def bng_to_pack_dict(result: BNGResult) -> dict:
    """Serialise a BNGResult to the shape the report templates expect."""
    return {
        "metric_version": result.metric_version,
        "ukhab_version": result.ukhab_version,
        "threshold_pct": result.threshold_pct,
        "baseline_units": result.baseline_units,
        "post_units": result.post_units,
        "units_lost": result.units_lost,
        "units_created": result.units_created,
        "units_enhanced": result.units_enhanced,
        "net_change_units": result.net_change_units,
        "net_change_pct": result.net_change_pct,
        "compliant": result.compliant,
        "baseline_rows": result.baseline_rows,
        "post_rows": result.post_rows,
        "summary": result.summary,
    }


__all__ = [
    "HabitatParcel",
    "Intervention",
    "BNGResult",
    "UKHAB_DISTINCTIVENESS",
    "CONDITION_SCORES",
    "STRATEGIC_SIGNIFICANCE",
    "DIFFICULTY_MULTIPLIER",
    "TEMPORAL_MULTIPLIER",
    "NET_GAIN_THRESHOLD_PCT",
    "METRIC_VERSION",
    "UKHAB_VERSION",
    "calculate_bng",
    "bng_from_land_use",
    "bng_to_pack_dict",
]
