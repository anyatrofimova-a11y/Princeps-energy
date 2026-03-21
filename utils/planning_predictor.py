"""
Planning Approval Predictor — ML model trained on real REPD data.

Uses scikit-learn GradientBoostingClassifier trained on 13,995 UK renewable
energy projects from the Renewable Energy Planning Database (REPD).

Features:
  - technology (one-hot)
  - capacity_mw (log-scaled)
  - latitude (proxy for solar resource / region)
  - region (one-hot)
  - nearby_approved_count (REPD density within 20 km)
  - nearby_refused_count
  - authority_approval_rate (historical LPA approval rate)
  - capacity_bucket (small/medium/large/nsip)

Target: binary — approved (1) vs refused (0).
  approved  = Operational, Under Construction, Approved, Secretary of State - Granted
  refused   = Planning Permission Refused, Planning Application Withdrawn,
              Appeal Refused, Secretary of State - Refusal, Abandoned

Subprocess-safe: can run standalone or imported into FastAPI.
"""

from __future__ import annotations

import logging
import os
import math
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("princeps.planning_predictor")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_MODEL_PATH = _DATA_DIR / "planning_predictor.joblib"

# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------
APPROVED_STATUSES = {
    "Operational",
    "Under Construction",
    "Approved",
    "Secretary of State - Granted",
}
REFUSED_STATUSES = {
    "Planning Permission Refused",
    "Planning Application Withdrawn",
    "Appeal Refused",
    "Secretary of State - Refusal",
    "Abandoned",
}

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_predictor: PlanningPredictor | None = None


class PlanningPredictor:
    """Trains and caches a planning approval model from REPD data."""

    def __init__(self):
        self.model = None
        self.label_encoders: dict = {}
        self.feature_names: list[str] = []
        self._trained = False
        self._authority_rates: dict[str, dict] = {}
        self._region_list: list[str] = []
        self._tech_list: list[str] = []

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    async def train(self, pool) -> dict:
        """Train model from REPD data in the database."""
        import joblib
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score, roc_auc_score, classification_report

        log.info("Training planning predictor from REPD data...")

        async with pool.acquire() as conn:
            # ── Fetch labelled projects ──────────────────────────────
            rows = await conn.fetch("""
                SELECT
                    repd_id, technology, tech_category, capacity_mw,
                    status, planning_authority, region,
                    ST_Y(ST_Transform(geometry, 4326)) AS lat,
                    ST_X(ST_Transform(geometry, 4326)) AS lon,
                    date_submitted, date_decided
                FROM repd_projects
                WHERE geometry IS NOT NULL
                  AND status IS NOT NULL
                  AND capacity_mw IS NOT NULL
                  AND capacity_mw > 0
            """)

            # ── Authority approval rates ─────────────────────────────
            auth_rows = await conn.fetch("""
                SELECT planning_authority,
                       COUNT(*) FILTER (WHERE status IN ('Operational','Under Construction','Approved','Secretary of State - Granted')) AS approved,
                       COUNT(*) FILTER (WHERE status IN ('Planning Permission Refused','Planning Application Withdrawn','Appeal Refused','Secretary of State - Refusal','Abandoned')) AS refused
                FROM repd_projects
                WHERE planning_authority IS NOT NULL
                GROUP BY planning_authority
            """)

            # ── Nearby project counts (pre-computed per project) ─────
            # Use a 20 km buffer in SRID 27700 (metres)
            nearby_rows = await conn.fetch("""
                SELECT
                    a.repd_id,
                    COUNT(*) FILTER (WHERE b.status IN ('Operational','Under Construction','Approved','Secretary of State - Granted')) AS nearby_approved,
                    COUNT(*) FILTER (WHERE b.status IN ('Planning Permission Refused','Planning Application Withdrawn','Appeal Refused','Secretary of State - Refusal','Abandoned')) AS nearby_refused
                FROM repd_projects a
                LEFT JOIN repd_projects b
                    ON ST_DWithin(a.geometry, b.geometry, 20000)
                    AND a.repd_id != b.repd_id
                WHERE a.geometry IS NOT NULL
                GROUP BY a.repd_id
            """)

        # ── Build authority rate lookup ───────────────────────────
        self._authority_rates = {}
        for r in auth_rows:
            name = r["planning_authority"]
            total = (r["approved"] or 0) + (r["refused"] or 0)
            rate = (r["approved"] or 0) / total if total > 0 else 0.5
            self._authority_rates[name] = {
                "rate": rate,
                "total": total,
                "approved": r["approved"] or 0,
                "refused": r["refused"] or 0,
            }

        nearby_lookup = {r["repd_id"]: r for r in nearby_rows}

        # ── Build feature matrix ─────────────────────────────────
        features = []
        labels = []
        meta = []  # for diagnostics

        for row in rows:
            status = row["status"]
            if status in APPROVED_STATUSES:
                label = 1
            elif status in REFUSED_STATUSES:
                label = 0
            else:
                continue  # skip Submitted, Appeal, Revised, etc.

            tech = (row["tech_category"] or "other").lower()
            region = (row["region"] or "Unknown").strip()
            capacity = row["capacity_mw"]
            lat = row["lat"]
            auth = row["planning_authority"] or ""
            auth_rate = self._authority_rates.get(auth, {}).get("rate", 0.5)

            nb = nearby_lookup.get(row["repd_id"], {})
            nearby_approved = nb.get("nearby_approved", 0) or 0
            nearby_refused = nb.get("nearby_refused", 0) or 0

            # Capacity bucket
            if capacity < 1:
                cap_bucket = 0  # small
            elif capacity < 10:
                cap_bucket = 1  # medium
            elif capacity < 50:
                cap_bucket = 2  # large
            else:
                cap_bucket = 3  # NSIP-scale

            # Decision time in months
            months = None
            if row["date_submitted"] and row["date_decided"]:
                delta = row["date_decided"] - row["date_submitted"]
                months = max(delta.days / 30.44, 0)

            features.append({
                "tech": tech,
                "region": region,
                "capacity_mw_log": math.log1p(capacity),
                "lat": lat,
                "authority_approval_rate": auth_rate,
                "nearby_approved": nearby_approved,
                "nearby_refused": nearby_refused,
                "nearby_ratio": nearby_approved / max(nearby_approved + nearby_refused, 1),
                "cap_bucket": cap_bucket,
            })
            labels.append(label)
            meta.append({"repd_id": row["repd_id"], "months": months})

        log.info("Training set: %d projects (%d approved, %d refused)",
                 len(labels), sum(labels), len(labels) - sum(labels))

        # ── One-hot encode categoricals ──────────────────────────
        self._tech_list = sorted({f["tech"] for f in features})
        self._region_list = sorted({f["region"] for f in features})

        X = []
        for f in features:
            row_vec = [
                f["capacity_mw_log"],
                f["lat"],
                f["authority_approval_rate"],
                f["nearby_approved"],
                f["nearby_refused"],
                f["nearby_ratio"],
                f["cap_bucket"],
            ]
            # One-hot tech
            for t in self._tech_list:
                row_vec.append(1.0 if f["tech"] == t else 0.0)
            # One-hot region
            for r in self._region_list:
                row_vec.append(1.0 if f["region"] == r else 0.0)
            X.append(row_vec)

        self.feature_names = [
            "capacity_mw_log", "latitude", "authority_approval_rate",
            "nearby_approved", "nearby_refused", "nearby_ratio", "cap_bucket",
        ] + [f"tech_{t}" for t in self._tech_list] + [f"region_{r}" for r in self._region_list]

        X = np.array(X, dtype=np.float64)
        y = np.array(labels, dtype=np.int32)

        # ── Train / test split ───────────────────────────────────
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y,
        )

        self.model = GradientBoostingClassifier(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.1,
            subsample=0.8,
            min_samples_leaf=20,
            random_state=42,
        )
        self.model.fit(X_train, y_train)

        # ── Evaluate ─────────────────────────────────────────────
        y_pred = self.model.predict(X_test)
        y_proba = self.model.predict_proba(X_test)[:, 1]
        acc = accuracy_score(y_test, y_pred)
        auc = roc_auc_score(y_test, y_proba)
        report = classification_report(y_test, y_pred, output_dict=True)

        log.info("Model accuracy=%.3f  AUC=%.3f", acc, auc)

        # ── Compute median decision months by tech ───────────────
        self._decision_months = {}
        for m, f in zip(meta, features):
            if m["months"] is not None and m["months"] < 120:
                tech = f["tech"]
                self._decision_months.setdefault(tech, []).append(m["months"])
        for tech in self._decision_months:
            vals = sorted(self._decision_months[tech])
            self._decision_months[tech] = vals[len(vals) // 2]  # median

        # ── Save model ───────────────────────────────────────────
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "model": self.model,
            "feature_names": self.feature_names,
            "tech_list": self._tech_list,
            "region_list": self._region_list,
            "authority_rates": self._authority_rates,
            "decision_months": self._decision_months,
        }, _MODEL_PATH)
        log.info("Model saved to %s", _MODEL_PATH)

        self._trained = True
        return {
            "samples": len(labels),
            "approved": int(sum(labels)),
            "refused": len(labels) - int(sum(labels)),
            "accuracy": round(acc, 4),
            "auc": round(auc, 4),
            "report": report,
        }

    # ------------------------------------------------------------------
    # Load cached model
    # ------------------------------------------------------------------
    def load_cached(self) -> bool:
        """Load a previously trained model from disk."""
        if not _MODEL_PATH.exists():
            return False
        try:
            import joblib
            data = joblib.load(_MODEL_PATH)
            self.model = data["model"]
            self.feature_names = data["feature_names"]
            self._tech_list = data["tech_list"]
            self._region_list = data["region_list"]
            self._authority_rates = data["authority_rates"]
            self._decision_months = data.get("decision_months", {})
            self._trained = True
            log.info("Loaded cached planning predictor from %s", _MODEL_PATH)
            return True
        except Exception as exc:
            log.warning("Failed to load cached model: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Feature vector construction
    # ------------------------------------------------------------------
    def _build_feature_vector(
        self,
        technology: str,
        capacity_mw: float,
        lat: float,
        region: str,
        authority_approval_rate: float,
        nearby_approved: int,
        nearby_refused: int,
    ) -> np.ndarray:
        tech = technology.lower()
        if tech in ("solar", "pv", "solar photovoltaics"):
            tech = "solar"
        elif tech in ("wind", "onshore wind"):
            tech = "wind"
        elif tech in ("bess", "battery", "storage"):
            tech = "bess"

        if capacity_mw < 1:
            cap_bucket = 0
        elif capacity_mw < 10:
            cap_bucket = 1
        elif capacity_mw < 50:
            cap_bucket = 2
        else:
            cap_bucket = 3

        nearby_total = nearby_approved + nearby_refused
        nearby_ratio = nearby_approved / max(nearby_total, 1)

        row = [
            math.log1p(capacity_mw),
            lat,
            authority_approval_rate,
            nearby_approved,
            nearby_refused,
            nearby_ratio,
            cap_bucket,
        ]
        for t in self._tech_list:
            row.append(1.0 if tech == t else 0.0)
        for r in self._region_list:
            row.append(1.0 if region == r else 0.0)

        return np.array([row], dtype=np.float64)

    # ------------------------------------------------------------------
    # Predict
    # ------------------------------------------------------------------
    async def predict(
        self,
        pool,
        lat: float,
        lon: float,
        technology: str,
        capacity_mw: float,
    ) -> dict[str, Any]:
        """Predict approval probability for a proposed project."""
        if not self._trained:
            raise RuntimeError("Model not trained — call train() first")

        async with pool.acquire() as conn:
            # ── Find nearby REPD projects (20 km in SRID 27700) ──
            nearby = await conn.fetch("""
                SELECT status
                FROM repd_projects
                WHERE ST_DWithin(
                    geometry,
                    ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                    20000
                )
            """, lon, lat)

            nearby_approved = sum(1 for r in nearby if r["status"] in APPROVED_STATUSES)
            nearby_refused = sum(1 for r in nearby if r["status"] in REFUSED_STATUSES)

            # ── Find planning authority ──────────────────────────
            auth_row = await conn.fetchrow("""
                SELECT planning_authority, region
                FROM repd_projects
                WHERE geometry IS NOT NULL
                ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                LIMIT 1
            """, lon, lat)

        authority = auth_row["planning_authority"] if auth_row else ""
        region = (auth_row["region"] if auth_row else "Unknown") or "Unknown"
        auth_rate_info = self._authority_rates.get(authority, {"rate": 0.5, "total": 0})
        auth_rate = auth_rate_info["rate"] if isinstance(auth_rate_info, dict) else auth_rate_info

        X = self._build_feature_vector(
            technology, capacity_mw, lat, region,
            auth_rate, nearby_approved, nearby_refused,
        )

        proba = self.model.predict_proba(X)[0]
        approval_prob = float(proba[1])

        # ── Feature importances for risk factors ─────────────────
        importances = self.model.feature_importances_
        feat_contrib = sorted(
            zip(self.feature_names, importances),
            key=lambda x: x[1], reverse=True,
        )

        risk_factors = []
        if auth_rate < 0.6:
            risk_factors.append({
                "factor": "low_authority_approval_rate",
                "detail": f"{authority} has {auth_rate:.0%} approval rate",
                "severity": "high" if auth_rate < 0.4 else "medium",
            })
        if nearby_refused > nearby_approved and nearby_refused > 3:
            risk_factors.append({
                "factor": "high_local_refusal_rate",
                "detail": f"{nearby_refused} refused vs {nearby_approved} approved within 20 km",
                "severity": "high",
            })
        if capacity_mw >= 50:
            risk_factors.append({
                "factor": "nsip_threshold",
                "detail": "Project >= 50 MW triggers NSIP (Nationally Significant Infrastructure Project) regime",
                "severity": "medium",
            })
        if lat > 55:
            risk_factors.append({
                "factor": "northern_location",
                "detail": "Higher latitude — lower solar resource may affect financial viability assessment",
                "severity": "low" if technology != "solar" else "medium",
            })

        # Predicted decision time
        tech_key = technology.lower()
        if tech_key in ("solar", "pv"):
            tech_key = "solar"
        elif tech_key in ("wind",):
            tech_key = "wind"
        median_months = self._decision_months.get(tech_key, 12)

        # Confidence based on training data density
        confidence = "high" if auth_rate_info.get("total", 0) > 10 and len(nearby) > 5 else \
                     "medium" if auth_rate_info.get("total", 0) > 3 else "low"

        return {
            "approval_probability": round(approval_prob, 4),
            "predicted_months_to_decision": round(median_months, 1),
            "confidence": confidence,
            "verdict": "LIKELY APPROVED" if approval_prob >= 0.7 else
                       "UNCERTAIN" if approval_prob >= 0.4 else "LIKELY REFUSED",
            "planning_authority": authority,
            "authority_approval_rate": round(auth_rate, 4),
            "region": region,
            "nearby_projects": {
                "total": len(nearby),
                "approved": nearby_approved,
                "refused": nearby_refused,
            },
            "risk_factors": risk_factors,
            "top_model_features": [
                {"feature": f, "importance": round(float(imp), 4)}
                for f, imp in feat_contrib[:10]
            ],
        }

    # ------------------------------------------------------------------
    # Comparable projects
    # ------------------------------------------------------------------
    async def find_comparable(
        self,
        pool,
        lat: float,
        lon: float,
        technology: str,
        capacity_mw: float,
        radius_km: float = 20,
        limit: int = 15,
    ) -> list[dict]:
        """Find similar REPD projects nearby with their outcomes."""
        tech = technology.lower()
        if tech in ("solar", "pv"):
            tech = "solar"
        elif tech in ("bess", "battery"):
            tech = "bess"

        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    repd_id, site_name, tech_category, capacity_mw, status,
                    planning_authority, developer,
                    ST_Y(ST_Transform(geometry, 4326)) AS lat,
                    ST_X(ST_Transform(geometry, 4326)) AS lon,
                    ST_Distance(
                        geometry,
                        ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                    ) / 1000.0 AS distance_km,
                    date_submitted, date_decided
                FROM repd_projects
                WHERE geometry IS NOT NULL
                  AND ST_DWithin(
                        geometry,
                        ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                        $3
                  )
                  AND tech_category = $4
                  AND status NOT IN ('Planning Application Submitted', 'Revised', 'No Application Required')
                ORDER BY
                    ABS(capacity_mw - $5) ASC,
                    ST_Distance(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) ASC
                LIMIT $6
            """, lon, lat, radius_km * 1000, tech, capacity_mw, limit)

        results = []
        for r in rows:
            outcome = "approved" if r["status"] in APPROVED_STATUSES else \
                      "refused" if r["status"] in REFUSED_STATUSES else "other"
            months = None
            if r["date_submitted"] and r["date_decided"]:
                delta = r["date_decided"] - r["date_submitted"]
                months = round(delta.days / 30.44, 1)

            results.append({
                "repd_id": r["repd_id"],
                "site_name": r["site_name"],
                "technology": r["tech_category"],
                "capacity_mw": r["capacity_mw"],
                "status": r["status"],
                "outcome": outcome,
                "planning_authority": r["planning_authority"],
                "developer": r["developer"],
                "lat": round(r["lat"], 5) if r["lat"] else None,
                "lon": round(r["lon"], 5) if r["lon"] else None,
                "distance_km": round(r["distance_km"], 2),
                "months_to_decision": months,
            })

        return results

    # ------------------------------------------------------------------
    # Authority stats
    # ------------------------------------------------------------------
    async def authority_stats(self, pool, planning_authority: str) -> dict:
        """Get detailed stats for a planning authority."""
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    status, tech_category, capacity_mw,
                    date_submitted, date_decided
                FROM repd_projects
                WHERE planning_authority = $1
            """, planning_authority)

            # Year breakdown
            yearly = await conn.fetch("""
                SELECT
                    EXTRACT(YEAR FROM date_decided)::int AS year,
                    COUNT(*) FILTER (WHERE status IN ('Operational','Under Construction','Approved','Secretary of State - Granted')) AS approved,
                    COUNT(*) FILTER (WHERE status IN ('Planning Permission Refused','Planning Application Withdrawn','Appeal Refused','Secretary of State - Refusal','Abandoned')) AS refused
                FROM repd_projects
                WHERE planning_authority = $1
                  AND date_decided IS NOT NULL
                GROUP BY year
                ORDER BY year
            """, planning_authority)

        if not rows:
            return {"error": f"No REPD projects found for authority '{planning_authority}'"}

        total = len(rows)
        approved = sum(1 for r in rows if r["status"] in APPROVED_STATUSES)
        refused = sum(1 for r in rows if r["status"] in REFUSED_STATUSES)
        decided = approved + refused

        # Decision times
        decision_months = []
        for r in rows:
            if r["date_submitted"] and r["date_decided"]:
                delta = r["date_decided"] - r["date_submitted"]
                m = delta.days / 30.44
                if 0 < m < 120:
                    decision_months.append(m)

        # By technology
        by_tech = {}
        for r in rows:
            tech = r["tech_category"] or "other"
            if tech not in by_tech:
                by_tech[tech] = {"total": 0, "approved": 0, "refused": 0, "total_mw": 0}
            by_tech[tech]["total"] += 1
            by_tech[tech]["total_mw"] += r["capacity_mw"] or 0
            if r["status"] in APPROVED_STATUSES:
                by_tech[tech]["approved"] += 1
            elif r["status"] in REFUSED_STATUSES:
                by_tech[tech]["refused"] += 1

        for tech in by_tech:
            d = by_tech[tech]["approved"] + by_tech[tech]["refused"]
            by_tech[tech]["approval_rate"] = round(by_tech[tech]["approved"] / d, 4) if d > 0 else None
            by_tech[tech]["total_mw"] = round(by_tech[tech]["total_mw"], 1)

        return {
            "planning_authority": planning_authority,
            "total_projects": total,
            "decided": decided,
            "approved": approved,
            "refused": refused,
            "approval_rate": round(approved / decided, 4) if decided > 0 else None,
            "avg_months_to_decision": round(sum(decision_months) / len(decision_months), 1) if decision_months else None,
            "median_months_to_decision": round(sorted(decision_months)[len(decision_months) // 2], 1) if decision_months else None,
            "by_technology": by_tech,
            "by_year": [
                {
                    "year": r["year"],
                    "approved": r["approved"] or 0,
                    "refused": r["refused"] or 0,
                    "rate": round((r["approved"] or 0) / max((r["approved"] or 0) + (r["refused"] or 0), 1), 4),
                }
                for r in yearly if r["year"]
            ],
        }


# ---------------------------------------------------------------------------
# Module-level accessor
# ---------------------------------------------------------------------------
async def get_predictor(pool=None) -> PlanningPredictor:
    """Get or create the singleton predictor. Trains on first call if no cache."""
    global _predictor
    if _predictor is None:
        _predictor = PlanningPredictor()

    if not _predictor._trained:
        if _predictor.load_cached():
            return _predictor
        if pool is None:
            raise RuntimeError("No cached model and no DB pool — cannot train")
        await _predictor.train(pool)

    return _predictor


async def retrain(pool) -> dict:
    """Force retrain the model."""
    global _predictor
    _predictor = PlanningPredictor()
    return await _predictor.train(pool)
