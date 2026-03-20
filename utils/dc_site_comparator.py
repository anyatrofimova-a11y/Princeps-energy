"""
dc_site_comparator.py — Multi-site comparison engine for data centre site selection.

Combines the original 9-dimension DC scorer with 6 new dimensions (CFE, cooling,
constraints, water stress, incentives, regulatory) into a unified 15-dimension
framework.  Supports profile-weighted scoring, multi-site ranking, sensitivity
analysis, and pre-scored Google UK sites.

Part of the Princeps platform.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import asyncpg

from utils.dc_colocation_scorer import score_dc_site, FACILITY_PROFILES
from utils.dc_cfe_scorer import score_cfe
from utils.dc_cooling_analyser import analyse_cooling
from utils.dc_constraint_overlay import check_constraints
from utils.dc_water_stress import assess_water_stress
from utils.dc_incentives import score_incentives
from utils.dc_regulatory_intel import assess_regulatory

log = logging.getLogger("princeps.dc_comparator")

# ---------------------------------------------------------------------------
# Extended profiles — weights must sum to 100
# ---------------------------------------------------------------------------
EXTENDED_PROFILES: dict[str, dict[str, Any]] = {
    "google_hyperscale": {
        "label": "Google Hyperscale",
        "capacity_range": "100-500+ MW",
        "description": (
            "Google-class hyperscale data centres requiring bulk power, "
            "24/7 CFE, and water-positive operations"
        ),
        "weights": {
            "power_capacity": 15, "grid_headroom": 15, "cfe_score": 15,
            "cooling_climate": 10, "constraint_clear": 10, "water_stress": 5,
            "fibre_proximity": 5, "ixp_proximity": 5, "latency": 5,
            "land_planning": 5, "resilience": 5, "connection_speed": 2,
            "incentives": 2, "regulatory_pathway": 1,
        },
        "gates": {
            "min_headroom_mw": 50,
            "constraint_clear": True,
            "min_cfe_pct": 60,
        },
    },
    "hyperscale_extended": {
        "label": "Hyperscale (Extended)",
        "capacity_range": "30-200+ MW",
        "description": "Large-scale cloud / AI compute with full sustainability overlay",
        "weights": {
            "power_capacity": 15, "grid_headroom": 15, "cfe_score": 10,
            "cooling_climate": 10, "constraint_clear": 8, "water_stress": 5,
            "fibre_proximity": 8, "ixp_proximity": 5, "latency": 5,
            "land_planning": 5, "resilience": 8, "connection_speed": 3,
            "incentives": 2, "regulatory_pathway": 1,
        },
        "gates": {
            "min_headroom_mw": 20,
            "constraint_clear": True,
        },
    },
    "colocation_extended": {
        "label": "Colocation (Extended)",
        "capacity_range": "5-30 MW",
        "description": "Multi-tenant carrier-neutral DC with sustainability scoring",
        "weights": {
            "fibre_proximity": 12, "latency": 12, "power_capacity": 10,
            "grid_headroom": 10, "cfe_score": 8, "cooling_climate": 8,
            "constraint_clear": 5, "water_stress": 3, "ixp_proximity": 8,
            "land_planning": 8, "resilience": 8, "connection_speed": 5,
            "incentives": 2, "regulatory_pathway": 1,
        },
        "gates": {
            "min_headroom_mw": 5,
        },
    },
}

# Merge original profiles (for fallback lookup)
_ALL_PROFILES = {**FACILITY_PROFILES, **EXTENDED_PROFILES}

# ---------------------------------------------------------------------------
# Google pre-scored UK sites
# ---------------------------------------------------------------------------
GOOGLE_UK_SITES: list[dict[str, Any]] = [
    {
        "name": "Waltham Cross",
        "lat": 51.6945,
        "lon": -0.0334,
        "status": "operational",
        "capacity_mw": 33,
    },
    {
        "name": "North Weald",
        "lat": 51.7246,
        "lon": 0.1544,
        "status": "approved",
        "capacity_mw": 200,
    },
    {
        "name": "Purfleet",
        "lat": 51.4810,
        "lon": 0.2310,
        "status": "acquired",
        "capacity_mw": 150,
    },
    {
        "name": "Teesside",
        "lat": 54.5973,
        "lon": -1.0737,
        "status": "negotiation",
        "capacity_mw": 500,
    },
]

# ---------------------------------------------------------------------------
# Dimension name mappings (original 9 -> extended 15)
# ---------------------------------------------------------------------------
ORIGINAL_DIMENSIONS = [
    "power_capacity", "grid_headroom", "fibre_proximity", "ixp_proximity",
    "water_cooling", "latency", "land_planning", "resilience", "connection_speed",
]
NEW_DIMENSIONS = [
    "cfe_score", "cooling_climate", "constraint_clear",
    "water_stress", "incentives", "regulatory_pathway",
]
ALL_DIMENSIONS = ORIGINAL_DIMENSIONS + NEW_DIMENSIONS

# Mapping from new dimension name to the key in its scorer's output
_NEW_DIM_SCORE_KEY = {
    "cfe_score": "cfe_score",
    "cooling_climate": "cooling_score",
    "constraint_clear": "constraint_score",
    "water_stress": "water_score",
    "incentives": "incentive_score",
    "regulatory_pathway": "regulatory_score",
}


# ---------------------------------------------------------------------------
# Extended gate check
# ---------------------------------------------------------------------------
def _check_extended_gates(
    profile_gates: dict[str, Any],
    scores: dict[str, dict],
    cfe_result: dict | None,
    constraint_result: dict | None,
) -> dict[str, dict]:
    """Check hard gate thresholds for extended profiles.

    Returns a dict of gate name -> {passed, value, threshold}.
    """
    results: dict[str, dict] = {}

    # --- min_headroom_mw ---
    if "min_headroom_mw" in profile_gates:
        headroom = scores.get("grid_headroom", {}).get("detail", {}).get("headroom_mw")
        threshold = profile_gates["min_headroom_mw"]
        results["min_headroom_mw"] = {
            "passed": headroom is not None and headroom >= threshold,
            "value": headroom,
            "threshold": threshold,
        }

    # --- constraint_clear ---
    if profile_gates.get("constraint_clear"):
        # A constraint gate means the site must NOT be blocked by any hard constraint
        if constraint_result is not None:
            clear = constraint_result.get("all_clear", True)
            results["constraint_clear"] = {
                "passed": bool(clear),
                "value": clear,
                "threshold": True,
            }
        else:
            # No constraint data — assume pass (be lenient)
            results["constraint_clear"] = {
                "passed": True,
                "value": None,
                "threshold": True,
            }

    # --- min_cfe_pct ---
    if "min_cfe_pct" in profile_gates:
        threshold = profile_gates["min_cfe_pct"]
        achievable = None
        if cfe_result is not None:
            achievable = cfe_result.get("achievable_cfe_pct")
        results["min_cfe_pct"] = {
            "passed": achievable is not None and achievable >= threshold,
            "value": achievable,
            "threshold": threshold,
        }

    return results


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------
def _derive_verdict(dc_score: float, gates_passed: bool) -> tuple[str, float]:
    """Return (verdict, confidence) from composite score and gate status."""
    if dc_score >= 70 and gates_passed:
        verdict = "GO"
        confidence = min(0.95, 0.6 + dc_score / 300)
    elif dc_score >= 45 or (dc_score >= 35 and gates_passed):
        verdict = "CAUTION"
        confidence = 0.5 + dc_score / 400
    else:
        verdict = "NO-GO"
        confidence = max(0.3, 0.7 - dc_score / 200)
    return verdict, round(confidence, 2)


# ---------------------------------------------------------------------------
# Extended single-site scorer
# ---------------------------------------------------------------------------
async def score_dc_site_extended(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    capacity_mw: float = 100,
    profile: str = "google_hyperscale",
    custom_weights: dict | None = None,
) -> dict:
    """Run full 15-dimension scoring on a single site.

    Calls the original 9-dimension ``score_dc_site()`` plus all six new
    scorers, merges the results into a unified breakdown, applies the
    profile weights, checks gates, and returns a combined result dict.
    """
    log.info(
        "Extended scoring site lat=%.4f lon=%.4f capacity=%sMW profile=%s",
        lat, lon, capacity_mw, profile,
    )

    # Resolve profile weights
    prof = EXTENDED_PROFILES.get(profile) or _ALL_PROFILES.get(profile)
    if prof is None:
        prof = EXTENDED_PROFILES["google_hyperscale"]
        log.warning("Unknown profile '%s'; falling back to google_hyperscale", profile)

    weights: dict[str, float] = dict(prof["weights"])
    if custom_weights:
        weights.update(custom_weights)
        total_w = sum(weights.values())
        if total_w > 0 and total_w != 100:
            weights = {k: v * 100 / total_w for k, v in weights.items()}

    # Map the 9-dimension profile name for the base scorer.  If the extended
    # profile has no counterpart in the original profiles, use "hyperscale".
    base_profile = profile if profile in FACILITY_PROFILES else "hyperscale"

    # --- Run base + new scorers concurrently ---
    base_task = score_dc_site(
        conn, lat, lon, capacity_mw=capacity_mw, profile=base_profile,
    )
    cfe_task = _safe_call(score_cfe, conn, lat, lon, capacity_mw=capacity_mw)
    cooling_task = _safe_call(analyse_cooling, conn, lat, lon, capacity_mw=capacity_mw)
    constraint_task = _safe_call(check_constraints, conn, lat, lon)
    water_task = _safe_call(assess_water_stress, conn, lat, lon, capacity_mw=capacity_mw)
    incentive_task = _safe_call(score_incentives, conn, lat, lon, capacity_mw=capacity_mw)
    regulatory_task = _safe_call(assess_regulatory, conn, lat, lon, capacity_mw=capacity_mw)

    (
        base_result,
        cfe_result,
        cooling_result,
        constraint_result,
        water_result,
        incentive_result,
        regulatory_result,
    ) = await asyncio.gather(
        base_task,
        cfe_task,
        cooling_task,
        constraint_task,
        water_task,
        incentive_task,
        regulatory_task,
    )

    # --- Merge scores ---
    # Start from the original 9 dimensions (already scored)
    merged_scores: dict[str, dict] = dict(base_result.get("scores", {}))

    # Extract new dimension scores
    new_raw: dict[str, tuple[float, dict]] = {
        "cfe_score": _extract_dim(cfe_result, "cfe_score"),
        "cooling_climate": _extract_dim(cooling_result, "cooling_score"),
        "constraint_clear": _extract_dim(constraint_result, "constraint_score"),
        "water_stress": _extract_dim(water_result, "water_score"),
        "incentives": _extract_dim(incentive_result, "incentive_score"),
        "regulatory_pathway": _extract_dim(regulatory_result, "regulatory_score"),
    }

    for dim, (score_val, detail) in new_raw.items():
        merged_scores[dim] = {"score": round(score_val, 1), "detail": detail}

    # --- Weighted composite ---
    dc_score = 0.0
    for dim, w in weights.items():
        s = merged_scores.get(dim, {}).get("score", 0)
        dc_score += s * w / 100.0
    dc_score = round(min(100, max(0, dc_score)), 1)

    # --- Gates ---
    profile_gates = prof.get("gates", {})
    gates = _check_extended_gates(
        profile_gates, merged_scores, cfe_result, constraint_result,
    )
    gates_passed = all(g["passed"] for g in gates.values()) if gates else True

    # --- Verdict ---
    verdict, confidence = _derive_verdict(dc_score, gates_passed)

    # --- Risks & opportunities (extend base) ---
    risks: list[str] = list(base_result.get("risks", []))
    opportunities: list[str] = list(base_result.get("opportunities", []))

    if cfe_result:
        ach = cfe_result.get("achievable_cfe_pct", 0)
        if ach >= 90:
            opportunities.append(f"High CFE achievable: {ach:.0f}% — on track for 24/7 clean energy")
        elif ach < 60:
            risks.append(f"Low CFE potential: {ach:.0f}% — significant PPA procurement needed")

    if cooling_result:
        pue = cooling_result.get("pue_estimate", 0)
        if pue and pue <= 1.2:
            opportunities.append(f"Excellent PUE {pue:.2f} — strong free-cooling climate")
        elif pue and pue > 1.5:
            risks.append(f"High PUE {pue:.2f} — limited free cooling, mechanical dependency")

    if water_result:
        if water_result.get("demand_exceeds_limit"):
            risks.append("Water demand exceeds EA catchment abstraction limit")
        if water_result.get("google_water_positive"):
            opportunities.append("Water-positive compatible under recommended cooling strategy")

    if constraint_result and not constraint_result.get("all_clear", True):
        failed = constraint_result.get("failed_constraints", [])
        if failed:
            risks.append(f"Site constraint(s): {', '.join(str(c) for c in failed[:3])}")

    # --- Radar chart data ---
    radar_data = [
        {"dimension": dim, "score": merged_scores.get(dim, {}).get("score", 0)}
        for dim in ALL_DIMENSIONS
        if dim in weights
    ]

    return {
        "dc_score": dc_score,
        "verdict": verdict,
        "confidence": confidence,
        "profile": profile,
        "capacity_mw": capacity_mw,
        "lat": lat,
        "lon": lon,
        "scores": merged_scores,
        "weights": weights,
        "radar_data": radar_data,
        "gates": gates,
        "gates_all_passed": gates_passed,
        "grid_connection": base_result.get("grid_connection", {}),
        "proximity": base_result.get("proximity", {}),
        "cfe_detail": cfe_result,
        "cooling_detail": cooling_result,
        "constraint_detail": constraint_result,
        "water_detail": water_result,
        "incentive_detail": incentive_result,
        "regulatory_detail": regulatory_result,
        "risks": risks,
        "opportunities": opportunities,
    }


# ---------------------------------------------------------------------------
# Multi-site comparison
# ---------------------------------------------------------------------------
async def compare_dc_sites(
    conn: asyncpg.Connection,
    sites: list[dict],
    capacity_mw: float = 100,
    profile: str = "google_hyperscale",
    custom_weights: dict | None = None,
) -> dict:
    """Compare N candidate sites with full 15-dimension scoring.

    Parameters
    ----------
    conn : asyncpg.Connection
        Active DB connection.
    sites : list[dict]
        Each dict must have ``lat``, ``lon``, and ``name``.
    capacity_mw : float
        Default IT load for all sites (individual sites may override).
    profile : str
        Scoring profile name.
    custom_weights : dict | None
        Optional weight overrides.

    Returns
    -------
    dict with ranked sites, dimension winners, comparison matrix,
    and a textual recommendation.
    """
    log.info(
        "Comparing %d DC sites, profile=%s, capacity=%sMW",
        len(sites), profile, capacity_mw,
    )

    # Score all sites concurrently
    tasks = []
    for site in sites:
        site_cap = site.get("capacity_mw", capacity_mw)
        tasks.append(
            _safe_score_extended(
                conn,
                lat=site["lat"],
                lon=site["lon"],
                capacity_mw=site_cap,
                profile=profile,
                custom_weights=custom_weights,
                name=site.get("name", f"{site['lat']:.4f},{site['lon']:.4f}"),
            )
        )

    scored = await asyncio.gather(*tasks)

    # Remove None results (failed scoring)
    results: list[dict] = [r for r in scored if r is not None]

    # Sort by dc_score descending
    results.sort(key=lambda r: r["dc_score"], reverse=True)

    # Assign rank
    for i, r in enumerate(results):
        r["rank"] = i + 1

    # Dimension winners
    dimension_winners: dict[str, dict] = {}
    comparison_matrix: dict[str, dict[str, float]] = {}
    prof = EXTENDED_PROFILES.get(profile) or _ALL_PROFILES.get(profile, {})
    weight_keys = list(prof.get("weights", {}).keys())

    for dim in weight_keys:
        comparison_matrix[dim] = {}
        best_name: str | None = None
        best_score: float = -1
        for r in results:
            name = r.get("name", "Unknown")
            s = r.get("scores", {}).get(dim, {}).get("score", 0)
            comparison_matrix[dim][name] = s
            if s > best_score:
                best_score = s
                best_name = name
        if best_name is not None:
            dimension_winners[dim] = {"winner": best_name, "score": round(best_score, 1)}

    # Ranking summary
    ranking = [
        {"name": r.get("name", "Unknown"), "dc_score": r["dc_score"], "verdict": r["verdict"]}
        for r in results
    ]

    # Recommendation
    recommendation = _build_recommendation(results, profile)

    return {
        "profile": profile,
        "capacity_mw": capacity_mw,
        "site_count": len(results),
        "sites": results,
        "ranking": ranking,
        "dimension_winners": dimension_winners,
        "comparison_matrix": comparison_matrix,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Sensitivity analysis
# ---------------------------------------------------------------------------
_DEFAULT_SCENARIOS: dict[str, dict[str, float]] = {
    "power_first": {
        "power_capacity": 2.0,
        "grid_headroom": 2.0,
    },
    "sustainability_first": {
        "cfe_score": 2.0,
        "water_stress": 2.0,
        "constraint_clear": 2.0,
    },
    "cost_first": {
        "incentives": 2.0,
        "connection_speed": 2.0,
        "regulatory_pathway": 2.0,
    },
}


async def sensitivity_analysis(
    conn: asyncpg.Connection,
    sites: list[dict],
    capacity_mw: float = 100,
    weight_variations: list[dict] | None = None,
) -> dict:
    """Vary weights to see how ranking changes across scenarios.

    Parameters
    ----------
    conn : asyncpg.Connection
        Active DB connection.
    sites : list[dict]
        Site dicts with ``lat``, ``lon``, ``name``.
    capacity_mw : float
        IT load capacity.
    weight_variations : list[dict] | None
        Each dict has ``name`` (str) and ``multipliers`` (dim -> multiplier).
        If None, three default scenarios are generated.

    Returns
    -------
    dict with per-scenario rankings and a stability summary.
    """
    if weight_variations is None:
        weight_variations = [
            {"name": name, "multipliers": mults}
            for name, mults in _DEFAULT_SCENARIOS.items()
        ]

    base_profile = EXTENDED_PROFILES.get("google_hyperscale", {})
    base_weights = dict(base_profile.get("weights", {}))

    # Run baseline comparison
    baseline = await compare_dc_sites(conn, sites, capacity_mw=capacity_mw)

    scenario_results: list[dict] = []
    for variation in weight_variations:
        scenario_name = variation.get("name", "unnamed")
        multipliers: dict[str, float] = variation.get("multipliers", {})

        # Apply multipliers to base weights
        adjusted = dict(base_weights)
        for dim, mult in multipliers.items():
            if dim in adjusted:
                adjusted[dim] = adjusted[dim] * mult

        # Normalise to sum=100
        total_w = sum(adjusted.values())
        if total_w > 0 and total_w != 100:
            adjusted = {k: v * 100 / total_w for k, v in adjusted.items()}

        result = await compare_dc_sites(
            conn, sites, capacity_mw=capacity_mw,
            profile="google_hyperscale", custom_weights=adjusted,
        )

        scenario_results.append({
            "scenario": scenario_name,
            "weights": adjusted,
            "ranking": result["ranking"],
            "winner": result["ranking"][0]["name"] if result["ranking"] else None,
        })

    # Stability: check if the same site wins in every scenario
    all_winners = [baseline["ranking"][0]["name"]] if baseline["ranking"] else []
    for sr in scenario_results:
        if sr.get("winner"):
            all_winners.append(sr["winner"])

    unique_winners = set(all_winners)
    if len(unique_winners) == 1:
        stability = "stable"
        stability_note = f"{all_winners[0]} ranks first in all scenarios — robust choice."
    elif len(unique_winners) == 2:
        stability = "moderate"
        stability_note = (
            f"Ranking varies between {' and '.join(unique_winners)}; "
            f"weight assumptions matter."
        )
    else:
        stability = "volatile"
        stability_note = (
            f"Ranking changes across scenarios ({', '.join(unique_winners)}); "
            f"no dominant site — align on strategic priorities first."
        )

    return {
        "baseline_ranking": baseline["ranking"],
        "scenarios": scenario_results,
        "stability": stability,
        "stability_note": stability_note,
        "unique_winners": sorted(unique_winners),
        "site_count": len(sites),
    }


# ---------------------------------------------------------------------------
# Google pre-scored sites
# ---------------------------------------------------------------------------
async def score_google_sites(
    conn: asyncpg.Connection,
    capacity_mw: float = 100,
    profile: str = "google_hyperscale",
) -> dict:
    """Pre-score all known Google UK sites.

    Returns a comparison result for every site in ``GOOGLE_UK_SITES``,
    using each site's own ``capacity_mw`` if available (falls back to
    the *capacity_mw* parameter).
    """
    log.info("Scoring %d Google UK sites", len(GOOGLE_UK_SITES))

    sites_input = [
        {
            "name": s["name"],
            "lat": s["lat"],
            "lon": s["lon"],
            "capacity_mw": s.get("capacity_mw", capacity_mw),
            "status": s.get("status"),
        }
        for s in GOOGLE_UK_SITES
    ]

    result = await compare_dc_sites(
        conn, sites_input, capacity_mw=capacity_mw, profile=profile,
    )

    # Attach operational status metadata to each scored site
    status_map = {s["name"]: s.get("status") for s in GOOGLE_UK_SITES}
    for site in result.get("sites", []):
        site["google_status"] = status_map.get(site.get("name"))

    result["google_sites_metadata"] = GOOGLE_UK_SITES
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_extended_profiles() -> dict:
    """Return all available extended profiles."""
    return EXTENDED_PROFILES


async def _safe_call(fn, *args, **kwargs) -> dict | None:
    """Call an async scorer, returning None on any failure."""
    try:
        return await fn(*args, **kwargs)
    except Exception as exc:
        log.warning("Scorer %s failed: %s", fn.__name__, exc)
        return None


async def _safe_score_extended(
    conn: asyncpg.Connection,
    *,
    lat: float,
    lon: float,
    capacity_mw: float,
    profile: str,
    custom_weights: dict | None,
    name: str,
) -> dict | None:
    """Score a single site, attaching the site name; return None on failure."""
    try:
        result = await score_dc_site_extended(
            conn, lat, lon,
            capacity_mw=capacity_mw,
            profile=profile,
            custom_weights=custom_weights,
        )
        result["name"] = name
        return result
    except Exception as exc:
        log.warning("Extended scoring failed for %s: %s", name, exc)
        return None


def _extract_dim(result: dict | None, key: str) -> tuple[float, dict]:
    """Pull (score, detail_dict) from a scorer result, with fallback."""
    if result is None:
        return 30.0, {"source": "unavailable"}
    score = result.get(key, 30.0)
    if isinstance(score, dict):
        score = score.get("score", 30.0)
    detail = {k: v for k, v in result.items() if k != key}
    return float(score), detail


def _build_recommendation(results: list[dict], profile: str) -> str:
    """Generate a textual recommendation from ranked results."""
    if not results:
        return "No sites could be scored."

    top = results[0]
    name = top.get("name", "Top site")
    score = top["dc_score"]
    verdict = top["verdict"]

    parts: list[str] = []

    if len(results) == 1:
        parts.append(f"{name} scores {score}/100 ({verdict}).")
    else:
        runner = results[1]
        gap = round(score - runner["dc_score"], 1)
        parts.append(
            f"{name} leads with {score}/100 ({verdict}), "
            f"{gap} points ahead of {runner.get('name', 'runner-up')}."
        )

    # Note any gate failures on the top site
    if not top.get("gates_all_passed"):
        failed_gates = [
            g_name for g_name, g_val in top.get("gates", {}).items()
            if not g_val.get("passed")
        ]
        parts.append(
            f"However, {name} fails gate(s): {', '.join(failed_gates)}. "
            f"These must be resolved before proceeding."
        )

    # Highlight strongest dimension for top site
    best_dim: str | None = None
    best_dim_score: float = 0
    for dim, data in top.get("scores", {}).items():
        s = data.get("score", 0)
        if s > best_dim_score:
            best_dim_score = s
            best_dim = dim
    if best_dim:
        parts.append(f"Strongest dimension: {best_dim} ({best_dim_score}/100).")

    # Note any GO verdicts
    go_sites = [r.get("name") for r in results if r.get("verdict") == "GO"]
    if len(go_sites) > 1:
        parts.append(f"Multiple GO sites: {', '.join(go_sites)}.")
    elif len(go_sites) == 0:
        parts.append("No site achieves GO status — further de-risking recommended for all candidates.")

    return " ".join(parts)
