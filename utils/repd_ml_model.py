"""
REPD Planning Outcome ML Model — predicts approval probability.

Trained on 13,995 real UK renewable energy planning applications from the
Renewable Energy Planning Database (REPD).

Features: technology, capacity, region, proximity to constraints,
nearby project density, local approval rate.

Uses scikit-learn GradientBoostingClassifier.
Model is trained lazily on first API call and cached to disk.
"""

from __future__ import annotations

import logging
import math
import os
import pickle
import time
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("princeps.repd_ml")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_CACHE_PATH = Path("/tmp/princeps_repd_model.pkl")

# ---------------------------------------------------------------------------
# Status classification — maps dev_status to binary outcome
# ---------------------------------------------------------------------------
APPROVED_STATUSES = {
    "Planning Permission Granted",
    "planning permission Granted",        # case variant in data
    "Planning permission Granted",
    "planning permission granted",
    "Operational",
    "Under Construction",
    "Appeal Granted",
    "Secretary of State - Granted",
    "No Application Required",
}

REFUSED_STATUSES = {
    "Planning Permission Refused",
    "Planning Application Withdrawn",
    "Appeal Refused",
    "Abandoned",
    "Secretary of State - Refusal",
}

# Excluded (indeterminate): Planning Application Submitted, Revised,
# Planning Permission Expired, Appeal Lodged, Appeal Withdrawn, Decommissioned

# ---------------------------------------------------------------------------
# Technology grouping
# ---------------------------------------------------------------------------
_TECH_MAP = {
    "Solar Photovoltaics": "solar",
    "Wind Onshore": "wind_onshore",
    "Wind Offshore": "wind_offshore",
    "Battery": "battery",
    "Anaerobic Digestion": "biomass",
    "Landfill Gas": "biomass",
    "Biomass (dedicated)": "biomass",
    "Biomass (co-firing)": "biomass",
    "EfW Incineration": "efw",
    "Small Hydro": "hydro",
    "Large Hydro": "hydro",
    "Hydrogen": "hydrogen",
    "Advanced Conversion Technologies": "efw",
    "Tidal Stream": "marine",
    "Pumped Storage Hydroelectricity": "hydro",
    "Sewage Sludge Digestion": "biomass",
    "Shoreline Wave": "marine",
    "Geothermal": "geothermal",
    "Liquid Air Energy Storage": "battery",
    "Fuel Cell (Hydrogen)": "hydrogen",
    "Hot Dry Rocks (HDR)": "geothermal",
    "Compressed Air Energy Storage": "battery",
    "Tidal Lagoon": "marine",
    "Flywheels": "battery",
}

# ---------------------------------------------------------------------------
# Singleton model holder
# ---------------------------------------------------------------------------
_model_data: dict | None = None


def _normalise_tech(raw: str) -> str:
    """Map raw technology_type to a grouped category."""
    return _TECH_MAP.get(raw, "other")


def _capacity_bin(mw: float) -> int:
    """0=small(<5), 1=medium(5-50), 2=large(>50)."""
    if mw < 5:
        return 0
    elif mw <= 50:
        return 1
    return 2


# ═══════════════════════════════════════════════════════════════════════════
#  Training
# ═══════════════════════════════════════════════════════════════════════════

async def train_model(pool) -> dict:
    """Train GradientBoostingClassifier on all REPD projects.

    Queries PostGIS for spatial features (nearby project counts, local
    approval rate). Returns accuracy metrics and feature importances.
    """
    global _model_data

    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import (
        accuracy_score, roc_auc_score, classification_report,
        confusion_matrix,
    )

    t0 = time.time()
    log.info("Training REPD planning ML model on real outcomes...")

    async with pool.acquire() as conn:
        # ── 1. Fetch all labelled projects ────────────────────────────
        rows = await conn.fetch("""
            SELECT
                ref_id,
                technology_type,
                installed_capacity_mw,
                dev_status,
                dev_status_short,
                region,
                county,
                planning_authority,
                ST_Y(geometry) AS lat,
                ST_X(geometry) AS lon,
                planning_submitted,
                planning_granted
            FROM repd_project
            WHERE geometry IS NOT NULL
              AND installed_capacity_mw IS NOT NULL
              AND installed_capacity_mw > 0
              AND dev_status IS NOT NULL
        """)

        # ── 2. Pre-compute nearby counts per project (5km radius) ────
        # Using SRID 4326 geometry with ST_DWithin in degrees (~0.045 ≈ 5km)
        nearby_rows = await conn.fetch("""
            SELECT
                a.ref_id,
                COUNT(*) FILTER (WHERE b.dev_status IN (
                    'Planning Permission Granted', 'Operational',
                    'Under Construction', 'Appeal Granted',
                    'Secretary of State - Granted', 'No Application Required',
                    'planning permission Granted', 'Planning permission Granted',
                    'planning permission granted'
                )) AS nearby_approved,
                COUNT(*) FILTER (WHERE b.dev_status IN (
                    'Planning Permission Refused', 'Planning Application Withdrawn',
                    'Appeal Refused', 'Abandoned', 'Secretary of State - Refusal'
                )) AS nearby_refused
            FROM repd_project a
            LEFT JOIN repd_project b
                ON ST_DWithin(a.geometry::geography, b.geometry::geography, 5000)
                AND a.ref_id != b.ref_id
            WHERE a.geometry IS NOT NULL
            GROUP BY a.ref_id
        """)

        # ── 3. Authority approval rates (10km local rate) ────────────
        authority_rates = await conn.fetch("""
            SELECT
                planning_authority,
                COUNT(*) FILTER (WHERE dev_status IN (
                    'Planning Permission Granted', 'Operational',
                    'Under Construction', 'Appeal Granted',
                    'Secretary of State - Granted', 'No Application Required',
                    'planning permission Granted', 'Planning permission Granted',
                    'planning permission granted'
                )) AS approved,
                COUNT(*) FILTER (WHERE dev_status IN (
                    'Planning Permission Refused', 'Planning Application Withdrawn',
                    'Appeal Refused', 'Abandoned', 'Secretary of State - Refusal'
                )) AS refused,
                COUNT(*) AS total
            FROM repd_project
            WHERE planning_authority IS NOT NULL
            GROUP BY planning_authority
        """)

    # Build authority lookup
    auth_lookup: dict[str, dict] = {}
    for ar in authority_rates:
        name = ar["planning_authority"]
        approved = ar["approved"] or 0
        refused = ar["refused"] or 0
        decided = approved + refused
        auth_lookup[name] = {
            "rate": approved / decided if decided > 0 else 0.5,
            "approved": approved,
            "refused": refused,
            "total": ar["total"],
        }

    # Build nearby lookup
    nearby_lookup = {r["ref_id"]: r for r in nearby_rows}

    # ── 4. Feature engineering ────────────────────────────────────────
    features = []
    labels = []
    ref_ids = []

    for row in rows:
        status = row["dev_status"]
        if status in APPROVED_STATUSES:
            label = 1
        elif status in REFUSED_STATUSES:
            label = 0
        else:
            continue  # skip indeterminate

        tech = _normalise_tech(row["technology_type"] or "")
        capacity = float(row["installed_capacity_mw"])
        region = (row["region"] or "Unknown").strip()
        county = (row["county"] or "Unknown").strip()
        lat = float(row["lat"]) if row["lat"] else 52.0
        lon = float(row["lon"]) if row["lon"] else -1.0
        authority = row["planning_authority"] or ""

        nb = nearby_lookup.get(row["ref_id"], {})
        nearby_approved = int(nb.get("nearby_approved", 0) or 0)
        nearby_refused = int(nb.get("nearby_refused", 0) or 0)
        nearby_total = nearby_approved + nearby_refused

        auth_info = auth_lookup.get(authority, {"rate": 0.5})
        local_approval_rate = auth_info["rate"]

        features.append({
            "tech": tech,
            "capacity_mw_log": math.log1p(capacity),
            "capacity_bin": _capacity_bin(capacity),
            "lat": lat,
            "lon": lon,
            "region": region,
            "nearby_approved": nearby_approved,
            "nearby_refused": nearby_refused,
            "local_approval_rate": local_approval_rate,
            "nearby_ratio": nearby_approved / max(nearby_total, 1),
        })
        labels.append(label)
        ref_ids.append(row["ref_id"])

    n_approved = sum(labels)
    n_refused = len(labels) - n_approved
    log.info("Labelled dataset: %d projects (%d approved, %d refused)",
             len(labels), n_approved, n_refused)

    # ── 5. One-hot encoding ──────────────────────────────────────────
    tech_categories = sorted({f["tech"] for f in features})
    region_categories = sorted({f["region"] for f in features})

    feature_names = [
        "capacity_mw_log", "capacity_bin", "latitude", "longitude",
        "nearby_approved_5km", "nearby_refused_5km",
        "local_approval_rate", "nearby_ratio",
    ]
    feature_names += [f"tech_{t}" for t in tech_categories]
    feature_names += [f"region_{r}" for r in region_categories]

    X = []
    for f in features:
        row_vec = [
            f["capacity_mw_log"],
            f["capacity_bin"],
            f["lat"],
            f["lon"],
            f["nearby_approved"],
            f["nearby_refused"],
            f["local_approval_rate"],
            f["nearby_ratio"],
        ]
        for t in tech_categories:
            row_vec.append(1.0 if f["tech"] == t else 0.0)
        for r in region_categories:
            row_vec.append(1.0 if f["region"] == r else 0.0)
        X.append(row_vec)

    X = np.array(X, dtype=np.float64)
    y = np.array(labels, dtype=np.int32)

    # ── 6. Train / test split ────────────────────────────────────────
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y,
    )

    model = GradientBoostingClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.1,
        subsample=0.8,
        min_samples_leaf=20,
        random_state=42,
    )
    model.fit(X_train, y_train)

    # ── 7. Evaluate ──────────────────────────────────────────────────
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]
    accuracy = accuracy_score(y_test, y_pred)
    auc = roc_auc_score(y_test, y_proba)
    cm = confusion_matrix(y_test, y_pred).tolist()
    report = classification_report(y_test, y_pred, output_dict=True)

    # Feature importances
    importances = model.feature_importances_
    feat_imp = sorted(
        zip(feature_names, importances.tolist()),
        key=lambda x: x[1], reverse=True,
    )

    elapsed = time.time() - t0
    log.info("REPD model trained in %.1fs — accuracy=%.3f AUC=%.3f (%d features)",
             elapsed, accuracy, auc, len(feature_names))

    # ── 8. Cache ─────────────────────────────────────────────────────
    _model_data = {
        "model": model,
        "feature_names": feature_names,
        "tech_categories": tech_categories,
        "region_categories": region_categories,
        "auth_lookup": auth_lookup,
        "accuracy": accuracy,
        "auc": auc,
        "confusion_matrix": cm,
        "feature_importances": feat_imp,
        "training_samples": len(labels),
        "approved_count": n_approved,
        "refused_count": n_refused,
        "trained_at": time.time(),
    }

    try:
        with open(_CACHE_PATH, "wb") as fh:
            pickle.dump(_model_data, fh)
        log.info("Model cached to %s", _CACHE_PATH)
    except Exception as e:
        log.warning("Failed to cache model: %s", e)

    return {
        "accuracy": round(accuracy, 4),
        "auc": round(auc, 4),
        "confusion_matrix": cm,
        "feature_importances": feat_imp[:15],
        "training_samples": len(labels),
        "approved_count": n_approved,
        "refused_count": n_refused,
        "training_time_s": round(elapsed, 1),
        "feature_count": len(feature_names),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Load cached model
# ═══════════════════════════════════════════════════════════════════════════

def _load_cached() -> bool:
    """Load model from disk cache. Returns True if successful."""
    global _model_data
    if _model_data is not None:
        return True
    if not _CACHE_PATH.exists():
        return False
    try:
        with open(_CACHE_PATH, "rb") as fh:
            _model_data = pickle.load(fh)
        log.info("Loaded cached REPD model (accuracy=%.3f, %d samples)",
                 _model_data["accuracy"], _model_data["training_samples"])
        return True
    except Exception as e:
        log.warning("Failed to load cached model: %s", e)
        return False


async def _ensure_model(pool) -> dict:
    """Ensure model is loaded — train if needed."""
    global _model_data
    if _model_data is not None:
        return _model_data
    if _load_cached():
        return _model_data
    await train_model(pool)
    return _model_data


# ═══════════════════════════════════════════════════════════════════════════
#  Prediction
# ═══════════════════════════════════════════════════════════════════════════

async def predict_approval(
    pool,
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str,
) -> dict[str, Any]:
    """Predict planning approval probability for a proposed site.

    Queries PostGIS for nearby REPD projects and local approval rate,
    then runs the trained GradientBoosting model.

    Returns approval_probability, verdict, confidence, feature_contributions,
    comparable_projects, risk_factors, and model_stats.
    """
    md = await _ensure_model(pool)
    model = md["model"]
    feature_names = md["feature_names"]
    tech_categories = md["tech_categories"]
    region_categories = md["region_categories"]
    auth_lookup = md["auth_lookup"]

    tech = _normalise_tech(technology) if technology in _TECH_MAP else technology.lower()
    # Handle common aliases
    tech_alias = {
        "solar": "solar", "pv": "solar", "solar photovoltaics": "solar",
        "wind": "wind_onshore", "onshore wind": "wind_onshore",
        "bess": "battery", "storage": "battery", "battery": "battery",
        "biomass": "biomass", "hydrogen": "hydrogen",
        "dc": "battery", "hybrid": "solar",
    }
    tech = tech_alias.get(tech, tech)

    async with pool.acquire() as conn:
        # Nearby projects within 5km (using geography for metres)
        nearby = await conn.fetch("""
            SELECT ref_id, dev_status, technology_type, installed_capacity_mw,
                   site_name, planning_authority,
                   ST_Distance(geometry::geography,
                               ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                   ) / 1000.0 AS distance_km
            FROM repd_project
            WHERE geometry IS NOT NULL
              AND ST_DWithin(geometry::geography,
                             ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                             5000)
            ORDER BY distance_km
        """, lon, lat)

        # Nearest project to determine region and authority
        nearest = await conn.fetchrow("""
            SELECT region, county, planning_authority
            FROM repd_project
            WHERE geometry IS NOT NULL
            ORDER BY geometry <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
            LIMIT 1
        """, lon, lat)

        # Comparable projects (5 approved + 5 refused, same tech, within 30km)
        comparables = await conn.fetch("""
            SELECT ref_id, site_name, technology_type, installed_capacity_mw,
                   dev_status, dev_status_short, region, planning_authority,
                   ST_Y(geometry) AS lat, ST_X(geometry) AS lon,
                   ST_Distance(geometry::geography,
                               ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                   ) / 1000.0 AS distance_km,
                   planning_submitted, planning_granted
            FROM repd_project
            WHERE geometry IS NOT NULL
              AND ST_DWithin(geometry::geography,
                             ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                             30000)
              AND dev_status IN (
                  'Planning Permission Granted', 'Operational',
                  'Under Construction', 'Appeal Granted',
                  'Secretary of State - Granted',
                  'Planning Permission Refused', 'Planning Application Withdrawn',
                  'Appeal Refused', 'Abandoned', 'Secretary of State - Refusal'
              )
            ORDER BY
                ABS(installed_capacity_mw - $3) ASC,
                ST_Distance(geometry::geography,
                            ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography) ASC
            LIMIT 20
        """, lon, lat, capacity_mw)

    # Count nearby outcomes
    nearby_approved = sum(
        1 for r in nearby if r["dev_status"] in APPROVED_STATUSES
    )
    nearby_refused = sum(
        1 for r in nearby if r["dev_status"] in REFUSED_STATUSES
    )

    region = (nearest["region"] if nearest else "Unknown") or "Unknown"
    authority = (nearest["planning_authority"] if nearest else "") or ""
    auth_info = auth_lookup.get(authority, {"rate": 0.5, "total": 0, "approved": 0, "refused": 0})
    local_approval_rate = auth_info["rate"]

    # Build feature vector
    nearby_total = nearby_approved + nearby_refused
    row_vec = [
        math.log1p(capacity_mw),
        _capacity_bin(capacity_mw),
        lat,
        lon,
        nearby_approved,
        nearby_refused,
        local_approval_rate,
        nearby_approved / max(nearby_total, 1),
    ]
    for t in tech_categories:
        row_vec.append(1.0 if tech == t else 0.0)
    for r in region_categories:
        row_vec.append(1.0 if region == r else 0.0)

    X = np.array([row_vec], dtype=np.float64)
    proba = model.predict_proba(X)[0]
    approval_prob = float(proba[1])

    # Confidence based on local data density
    if auth_info.get("total", 0) > 10 and len(nearby) > 5:
        confidence = round(min(0.95, 0.7 + len(nearby) * 0.01 + auth_info["total"] * 0.002), 2)
    elif auth_info.get("total", 0) > 3:
        confidence = 0.65
    else:
        confidence = 0.45

    # Verdict
    if approval_prob >= 0.75:
        verdict = "LIKELY APPROVED"
    elif approval_prob >= 0.5:
        verdict = "LEANING APPROVED"
    elif approval_prob >= 0.35:
        verdict = "UNCERTAIN"
    else:
        verdict = "LIKELY REFUSED"

    # Feature contributions (approximate via importance * feature value direction)
    importances = model.feature_importances_
    feat_contrib = {}
    for i, fname in enumerate(feature_names):
        imp = float(importances[i])
        if imp > 0.01:  # Only significant features
            feat_contrib[fname] = round(imp, 4)

    # Risk factors
    risk_factors = []
    if local_approval_rate < 0.6:
        risk_factors.append({
            "factor": "low_authority_approval_rate",
            "detail": f"{authority} has {local_approval_rate:.0%} historical approval rate",
            "severity": "high" if local_approval_rate < 0.4 else "medium",
        })
    if nearby_refused > nearby_approved and nearby_refused > 2:
        risk_factors.append({
            "factor": "high_local_refusal_density",
            "detail": f"{nearby_refused} refused vs {nearby_approved} approved within 5km",
            "severity": "high",
        })
    if capacity_mw >= 50:
        risk_factors.append({
            "factor": "nsip_threshold",
            "detail": ">=50MW triggers NSIP regime (Secretary of State decision)",
            "severity": "medium",
        })
    if tech == "wind_onshore" and lat < 52:
        risk_factors.append({
            "factor": "southern_wind",
            "detail": "Onshore wind in southern England faces higher opposition",
            "severity": "medium",
        })

    # Build comparable projects list
    comparable_approved = []
    comparable_refused = []
    for c in comparables:
        proj = {
            "ref_id": c["ref_id"],
            "site_name": c["site_name"],
            "technology": c["technology_type"],
            "capacity_mw": float(c["installed_capacity_mw"]) if c["installed_capacity_mw"] else None,
            "status": c["dev_status"],
            "region": c["region"],
            "planning_authority": c["planning_authority"],
            "lat": round(float(c["lat"]), 5) if c["lat"] else None,
            "lon": round(float(c["lon"]), 5) if c["lon"] else None,
            "distance_km": round(float(c["distance_km"]), 1),
        }
        if c["planning_submitted"] and c["planning_granted"]:
            delta = c["planning_granted"] - c["planning_submitted"]
            proj["months_to_decision"] = round(delta.days / 30.44, 1)

        if c["dev_status"] in APPROVED_STATUSES:
            comparable_approved.append(proj)
        else:
            comparable_refused.append(proj)

    return {
        "approval_probability": round(approval_prob, 4),
        "verdict": verdict,
        "confidence": confidence,
        "feature_contributions": feat_contrib,
        "risk_factors": risk_factors,
        "nearby_projects": {
            "within_5km": len(nearby),
            "approved": nearby_approved,
            "refused": nearby_refused,
        },
        "planning_authority": authority,
        "authority_approval_rate": round(local_approval_rate, 4),
        "region": region,
        "comparable_projects": {
            "approved": comparable_approved[:5],
            "refused": comparable_refused[:5],
        },
        "model_stats": {
            "accuracy": round(md["accuracy"], 4),
            "auc": round(md["auc"], 4),
            "training_samples": md["training_samples"],
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Comparable projects query
# ═══════════════════════════════════════════════════════════════════════════

async def get_comparable_projects(
    pool,
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str,
    limit: int = 10,
) -> list[dict]:
    """Find most similar REPD projects by features and location."""
    tech_raw = technology
    # Map common names back to REPD technology_type values
    tech_filter_map = {
        "solar": "Solar Photovoltaics",
        "wind": "Wind Onshore",
        "wind_onshore": "Wind Onshore",
        "battery": "Battery",
        "bess": "Battery",
        "biomass": "Anaerobic Digestion",
        "hydrogen": "Hydrogen",
    }
    tech_db = tech_filter_map.get(technology.lower(), technology)

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT ref_id, site_name, technology_type, installed_capacity_mw,
                   dev_status, dev_status_short, region, county, planning_authority,
                   ST_Y(geometry) AS lat, ST_X(geometry) AS lon,
                   ST_Distance(geometry::geography,
                               ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                   ) / 1000.0 AS distance_km,
                   planning_submitted, planning_granted
            FROM repd_project
            WHERE geometry IS NOT NULL
              AND ST_DWithin(geometry::geography,
                             ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                             50000)
              AND dev_status NOT IN ('Planning Application Submitted', 'Revised')
            ORDER BY
                CASE WHEN technology_type = $3 THEN 0 ELSE 1 END,
                ABS(installed_capacity_mw - $4) ASC,
                ST_Distance(geometry::geography,
                            ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography) ASC
            LIMIT $5
        """, lon, lat, tech_db, capacity_mw, limit)

    results = []
    for r in rows:
        outcome = "approved" if r["dev_status"] in APPROVED_STATUSES else \
                  "refused" if r["dev_status"] in REFUSED_STATUSES else "other"
        proj = {
            "ref_id": r["ref_id"],
            "site_name": r["site_name"],
            "technology": r["technology_type"],
            "capacity_mw": float(r["installed_capacity_mw"]) if r["installed_capacity_mw"] else None,
            "status": r["dev_status"],
            "status_short": r["dev_status_short"],
            "outcome": outcome,
            "region": r["region"],
            "county": r["county"],
            "planning_authority": r["planning_authority"],
            "lat": round(float(r["lat"]), 5) if r["lat"] else None,
            "lon": round(float(r["lon"]), 5) if r["lon"] else None,
            "distance_km": round(float(r["distance_km"]), 1),
        }
        if r["planning_submitted"] and r["planning_granted"]:
            delta = r["planning_granted"] - r["planning_submitted"]
            proj["months_to_decision"] = round(delta.days / 30.44, 1)
        results.append(proj)

    return results


# ═══════════════════════════════════════════════════════════════════════════
#  Model stats
# ═══════════════════════════════════════════════════════════════════════════

async def get_model_stats(pool) -> dict:
    """Return model accuracy, feature importances, training info."""
    md = await _ensure_model(pool)
    return {
        "trained": True,
        "accuracy": round(md["accuracy"], 4),
        "auc": round(md["auc"], 4),
        "confusion_matrix": md["confusion_matrix"],
        "feature_importances": md["feature_importances"][:20],
        "training_samples": md["training_samples"],
        "approved_count": md["approved_count"],
        "refused_count": md["refused_count"],
        "feature_count": len(md["feature_names"]),
        "features": md["feature_names"],
        "cached_at": _CACHE_PATH.stat().st_mtime if _CACHE_PATH.exists() else None,
    }
