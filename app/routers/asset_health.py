"""Asset Health Score per RID.

Computes a single weighted 0-100 health score for any typed object in the
Princeps ontology (Project, Substation, REPDProject, NSIPProject,
TecQueueEntry, Entity) with full provenance per driver.

Drivers + weights:
  1. data_freshness   (40%) — age of underlying record. 0d=100, 30d=50, 90d+=0
  2. connector_health (20%) — princeps_datasets.health_status for source table
  3. verdict          (15%) — Project.verdict (GO=100, CAUTION=60, NO-GO=20)
  4. action_error_rate(15%) — last 30 ontology_action_log rows for the rid
  5. audit_volume     (10%) — sigmoid over recent action count

Permissive by design: unknown / missing inputs degrade gracefully to a
neutral 50 rather than 4xx. Every numeric output carries (name, weight,
score, value, source) so the UI popover can show provenance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.deps import get_pool as _raw_pool  # noqa: F401
from app.middleware.tenant_jwt import get_tenant_pool as get_pool

log = logging.getLogger("princeps.asset_health")
router = APIRouter(prefix="/api/asset-health", tags=["asset-health"])


# ── Type → table map (mirrors objects._TABLE_FOR_RESOLVE) ────────────────────
# Each entry: (table, pk_col, updated_col_or_None)
# ``updated_col`` is the freshness signal — None ⇒ skip freshness lookup.
_TYPE_TABLE: dict[str, tuple[str, str, str | None]] = {
    "project":    ("projects",          "project_id", "updated_at"),
    "substation": ("grid_substations",  "id",         None),
    "repd":       ("repd_projects",     "repd_id",    "date_decided"),
    "nsip":       ("pins_nsip_dco",     "case_ref",   "decision_date"),
    "tec":        ("eso_tec_register",  "tec_id",     None),
    "entity":     (None,                None,         None),  # synthetic
}

# Connector status → score
_CONNECTOR_SCORE = {"green": 100, "yellow": 60, "red": 20, "unknown": 50}

# Verdict → score
_VERDICT_SCORE = {"GO": 100, "CAUTION": 60, "NO-GO": 20, "NO_GO": 20, "NOGO": 20}

# Driver weights (must sum to 1.0)
_WEIGHTS = {
    "data_freshness":    0.40,
    "connector_health":  0.20,
    "verdict":           0.15,
    "action_error_rate": 0.15,
    "audit_volume":      0.10,
}

_NEUTRAL = 50  # default score when input is missing / unknown


def _parse_rid(rid: str) -> tuple[str | None, str | None]:
    """Split ``rid.princeps.<type>.<id>`` → (type_key, id). Returns
    (None, None) on malformed input — caller handles permissively."""
    if not rid or not isinstance(rid, str):
        return None, None
    parts = rid.split(".", 3)
    if len(parts) < 4 or parts[0] != "rid" or parts[1] != "princeps":
        return None, None
    return parts[2].lower(), parts[3]


def _grade(score: int) -> str:
    if score > 85: return "A"
    if score >= 70: return "B"
    if score >= 55: return "C"
    if score >= 40: return "D"
    return "F"


def _freshness_score(updated_at: datetime | None) -> tuple[int, str]:
    """Linear decay: 0d=100, 30d=50, 90d+=0."""
    if updated_at is None:
        return _NEUTRAL, "missing"
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - updated_at).total_seconds() / 86400.0
    if age_days <= 0:
        return 100, f"{age_days:.1f}d"
    if age_days >= 90:
        return 0, f"{age_days:.0f}d"
    if age_days <= 30:
        # 0..30d → 100..50
        s = 100 - (age_days / 30.0) * 50
    else:
        # 30..90d → 50..0
        s = 50 - ((age_days - 30) / 60.0) * 50
    return max(0, min(100, int(round(s)))), f"{age_days:.0f}d"


def _audit_sigmoid(n: int) -> int:
    """Sigmoid: 0 audits → 50; ramps up so ~10 audits ≈ 80, plateau ~95.

    score = 50 + 50 * (n / (n + k))   with k=4 → smooth saturation.
    Special case: n==0 → exactly 50 (neutral, no signal)."""
    if n <= 0:
        return _NEUTRAL
    k = 4.0
    s = 50.0 + 50.0 * (n / (n + k))
    return max(0, min(100, int(round(s))))


async def _fetch_freshness(conn, type_key: str, obj_id: str) -> tuple[int, str, str]:
    """Returns (score, value_str, source_str)."""
    cfg = _TYPE_TABLE.get(type_key)
    if not cfg:
        return _NEUTRAL, "unknown type", "default"
    table, pk_col, updated_col = cfg
    if not table or not updated_col:
        return _NEUTRAL, "no updated_at column", f"{table or '?'}"
    try:
        row = await conn.fetchrow(
            f"SELECT {updated_col} AS ts FROM {table} WHERE {pk_col}::text = $1",
            obj_id,
        )
    except Exception as exc:
        log.warning("freshness lookup failed for %s/%s: %s", type_key, obj_id, exc)
        return _NEUTRAL, "lookup error", f"{table}.{updated_col}"
    if not row or row["ts"] is None:
        return _NEUTRAL, "no record", f"{table}.{updated_col}"
    score, age = _freshness_score(row["ts"])
    return score, age, f"{table}.{updated_col}"


async def _fetch_connector_health(conn, type_key: str) -> tuple[int, str, str]:
    cfg = _TYPE_TABLE.get(type_key)
    if not cfg or not cfg[0]:
        return _NEUTRAL, "no source table", "default"
    table = cfg[0]
    try:
        row = await conn.fetchrow(
            "SELECT slug, health_status FROM princeps_datasets "
            "WHERE table_name = $1 ORDER BY updated_at DESC NULLS LAST LIMIT 1",
            table,
        )
    except Exception as exc:
        log.warning("connector lookup failed for %s: %s", table, exc)
        return _NEUTRAL, "lookup error", "princeps_datasets"
    if not row:
        return _NEUTRAL, "unregistered", f"princeps_datasets(table={table})"
    status = (row["health_status"] or "unknown").lower()
    score = _CONNECTOR_SCORE.get(status, _NEUTRAL)
    return score, status, f"princeps_datasets.slug={row['slug']}"


async def _fetch_verdict(conn, type_key: str, obj_id: str) -> tuple[int, str, str]:
    """Only meaningful for Project — others get neutral."""
    if type_key != "project":
        return _NEUTRAL, "n/a (non-Project)", "default"
    try:
        row = await conn.fetchrow(
            "SELECT verdict FROM projects WHERE project_id::text = $1", obj_id,
        )
    except Exception as exc:
        log.warning("verdict lookup failed for %s: %s", obj_id, exc)
        return _NEUTRAL, "lookup error", "projects.verdict"
    if not row or not row["verdict"]:
        return _NEUTRAL, "missing", "projects.verdict"
    v = str(row["verdict"]).upper()
    score = _VERDICT_SCORE.get(v, _NEUTRAL)
    return score, v, "projects.verdict"


async def _fetch_error_rate(conn, rid: str) -> tuple[int, str, str]:
    """(1 - error_rate) * 100 over last 30 ontology_action_log rows for rid."""
    try:
        rows = await conn.fetch(
            "SELECT ok FROM ontology_action_log "
            "WHERE object_id = $1 ORDER BY started_utc DESC LIMIT 30",
            rid,
        )
    except Exception as exc:
        log.warning("error_rate lookup failed for %s: %s", rid, exc)
        return _NEUTRAL, "lookup error", "ontology_action_log"
    if not rows:
        return _NEUTRAL, "no actions", "ontology_action_log"
    total = len(rows)
    errors = sum(1 for r in rows if not r["ok"])
    err_rate = errors / total
    score = int(round((1.0 - err_rate) * 100))
    return max(0, min(100, score)), f"{errors}/{total} failed", "ontology_action_log(last 30)"


async def _fetch_audit_volume(conn, rid: str) -> tuple[int, str, str]:
    """Sigmoid on action count in the last 30 days for this rid."""
    try:
        n = await conn.fetchval(
            "SELECT COUNT(*) FROM ontology_action_log "
            "WHERE object_id = $1 AND started_utc > NOW() - INTERVAL '30 days'",
            rid,
        )
    except Exception as exc:
        log.warning("audit_volume lookup failed for %s: %s", rid, exc)
        return _NEUTRAL, "lookup error", "ontology_action_log"
    n = int(n or 0)
    return _audit_sigmoid(n), f"{n} in 30d", "ontology_action_log(30d)"


async def _compute_one(conn, rid: str) -> dict[str, Any]:
    """Compute the score + drivers for a single rid. Permissive: a malformed
    or unknown rid still returns a populated payload with neutral defaults."""
    type_key, obj_id = _parse_rid(rid)

    if type_key is None or obj_id is None:
        # Malformed RID — return all-neutral payload (don't 4xx).
        drivers = [
            {"name": k, "weight": w, "score": _NEUTRAL,
             "value": "invalid rid", "source": "default"}
            for k, w in _WEIGHTS.items()
        ]
        return {
            "rid": rid,
            "score": _NEUTRAL,
            "grade": _grade(_NEUTRAL),
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "drivers": drivers,
        }

    fresh = await _fetch_freshness(conn, type_key, obj_id)
    conn_h = await _fetch_connector_health(conn, type_key)
    verdict = await _fetch_verdict(conn, type_key, obj_id)
    err = await _fetch_error_rate(conn, rid)
    vol = await _fetch_audit_volume(conn, rid)

    drivers = [
        {"name": "data_freshness",    "weight": _WEIGHTS["data_freshness"],
         "score": fresh[0],   "value": fresh[1],   "source": fresh[2]},
        {"name": "connector_health",  "weight": _WEIGHTS["connector_health"],
         "score": conn_h[0],  "value": conn_h[1],  "source": conn_h[2]},
        {"name": "verdict",           "weight": _WEIGHTS["verdict"],
         "score": verdict[0], "value": verdict[1], "source": verdict[2]},
        {"name": "action_error_rate", "weight": _WEIGHTS["action_error_rate"],
         "score": err[0],     "value": err[1],     "source": err[2]},
        {"name": "audit_volume",      "weight": _WEIGHTS["audit_volume"],
         "score": vol[0],     "value": vol[1],     "source": vol[2]},
    ]

    weighted = sum(d["score"] * d["weight"] for d in drivers)
    score = max(0, min(100, int(round(weighted))))

    return {
        "rid": rid,
        "score": score,
        "grade": _grade(score),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "drivers": drivers,
    }


# ── Endpoints ────────────────────────────────────────────────────────────────
@router.get("/batch")
async def batch_health(
    rid: list[str] = Query(default=[], description="repeated rid query param"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Compute scores for multiple RIDs in one round-trip. Limit 50 to keep
    the response bounded; callers needing more should page."""
    rids = (rid or [])[:50]
    if not rids:
        return {"scores": []}
    async with pool.acquire() as conn:
        results = []
        for r in rids:
            try:
                payload = await _compute_one(conn, r)
                results.append({"rid": payload["rid"], "score": payload["score"],
                                "grade": payload["grade"]})
            except Exception as exc:
                log.warning("batch compute failed for %s: %s", r, exc)
                results.append({"rid": r, "score": _NEUTRAL,
                                "grade": _grade(_NEUTRAL), "error": str(exc)})
    return {"scores": results}


@router.get("/{rid}")
async def get_health(
    rid: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Compute and return the asset health score for one RID with full
    per-driver provenance. Always 200 — invalid / unknown RIDs return a
    neutral payload so the UI badge never breaks."""
    async with pool.acquire() as conn:
        try:
            return await _compute_one(conn, rid)
        except Exception as exc:
            log.exception("asset-health compute failed for %s", rid)
            # Hard fallback so the badge endpoint never 5xxs the UI.
            drivers = [
                {"name": k, "weight": w, "score": _NEUTRAL,
                 "value": "compute error", "source": str(exc)[:80]}
                for k, w in _WEIGHTS.items()
            ]
            return {
                "rid": rid,
                "score": _NEUTRAL,
                "grade": _grade(_NEUTRAL),
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "drivers": drivers,
            }
