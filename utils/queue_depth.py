"""
Per-substation queue-depth rewrite.

Replaces the previous stub that just counted ECR rows. Strategy:

 1. If the grid_ecr table is populated for the substation, use it
    (it is what DNOs publish and is already normalised).
 2. Else pull TEC entries from eso_tec_register whose connection_site
    matches the substation name.
 3. Else, as a last resort, call the live NESO CKAN TEC register. If that
    fails we return a synthetic_fallback result (never raise).

Computed metrics per substation:

 - queued_mw             — total MW in the queue (accepted + offered)
 - ahead_in_queue_count  — number of projects ahead of a theoretical new
                           applicant (i.e. active, not withdrawn/connected)
 - free_headroom_mw      — max(0, gen_headroom_mw − queued_mw)
 - queue_depth_ratio     — queued_mw / gen_headroom_mw (None if no headroom)
 - earliest_viable_year  — when the next slot opens, assuming a linear
                           clearance rate of CLEARANCE_MW_PER_YEAR
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from utils.grid_provenance import (
    SRC_DB_SNAPSHOT, SRC_NESO_LIVE, SRC_SYNTHETIC, make_provenance,
)

log = logging.getLogger("princeps.queue_depth")

NESO_BASE = "https://api.neso.energy"
NESO_TEC_RESOURCE = "17becbab-e3e8-473f-b303-3806f43a6a10"
NESO_TIMEOUT = 20

# Rough UK-wide clearance rate (MW/yr) derived from NESO reform baseline.
# Used only for earliest_viable_year estimation.
CLEARANCE_MW_PER_YEAR = 3500.0

ACTIVE_TEC_STATUSES = {
    "accepted", "offer made", "contracted", "in progress",
    "under construction", "queued", "application in progress",
}
WITHDRAWN_TEC_STATUSES = {
    "terminated", "withdrawn", "lapsed", "refused", "cancelled",
}


async def _fetch_substation(conn, substation_id: int) -> dict | None:
    row = await conn.fetchrow("""
        SELECT id, name, dno, voltage_kv,
               demand_headroom_mw, gen_headroom_mw,
               updated_at,
               ST_X(ST_Transform(geom, 4326)) AS lon,
               ST_Y(ST_Transform(geom, 4326)) AS lat
        FROM grid_substations
        WHERE id = $1
    """, substation_id)
    return dict(row) if row else None


async def _queue_from_ecr(conn, substation_id: int) -> tuple[list[dict], datetime | None]:
    rows = await conn.fetch("""
        SELECT id, site_name, technology, capacity_mw, voltage_kv, status,
               connection_date, updated_at
        FROM grid_ecr
        WHERE substation_id = $1
    """, substation_id)
    latest = None
    out = []
    for r in rows:
        d = dict(r)
        out.append(d)
        if d.get("updated_at") and (latest is None or d["updated_at"] > latest):
            latest = d["updated_at"]
    return out, latest


async def _queue_from_tec_db(conn, substation_name: str) -> tuple[list[dict], datetime | None]:
    rows = await conn.fetch("""
        SELECT tec_id, customer_name, tech_category, tec_mw, status,
               effective_from, connection_date, updated_at
        FROM eso_tec_register
        WHERE connection_site ILIKE $1
    """, f"%{substation_name}%")
    latest = None
    out = []
    for r in rows:
        d = dict(r)
        out.append(d)
        if d.get("updated_at") and (latest is None or d["updated_at"] > latest):
            latest = d["updated_at"]
    return out, latest


async def _queue_from_neso_live(substation_name: str) -> tuple[list[dict], datetime | None, str | None]:
    """Hit NESO CKAN TEC register directly. Returns (rows, refreshed, error_reason)."""
    url = f"{NESO_BASE}/api/3/action/datastore_search"
    params = {
        "resource_id": NESO_TEC_RESOURCE,
        "q": substation_name,
        "limit": 500,
    }
    try:
        async with httpx.AsyncClient(
            timeout=NESO_TIMEOUT,
            headers={"User-Agent": "Princeps/1.0 queue-depth"},
            follow_redirects=True,
        ) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        return [], None, f"NESO TEC register request failed: {e.__class__.__name__}"
    except Exception as e:
        return [], None, f"NESO TEC register unexpected error: {e.__class__.__name__}"

    result = (data or {}).get("result") or {}
    records = result.get("records") or []
    out = []
    for row in records:
        out.append({
            "tec_id": row.get("TEC Project No") or row.get("_id"),
            "customer_name": row.get("Customer Name"),
            "tech_category": row.get("Plant Type"),
            "tec_mw": _num(row.get("MW Connected") or row.get("Cumulative Total Capacity (MW)") or row.get("MW")),
            "status": row.get("Project Status") or row.get("Status"),
            "effective_from": row.get("Agreement Effective From"),
            "connection_date": row.get("MW Effective From") or row.get("Connection Date"),
        })
    # CKAN doesn't expose a per-row timestamp; use now() as the refresh.
    return out, datetime.now(timezone.utc), None


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _is_active(status: Any) -> bool:
    if not status:
        return True  # unknown assumed active
    s = str(status).strip().lower()
    if any(w in s for w in WITHDRAWN_TEC_STATUSES):
        return False
    if "connected" in s and "to be connected" not in s:
        return False
    return True


def _earliest_viable_year(ahead_mw: float) -> int | None:
    if ahead_mw <= 0:
        return datetime.now(timezone.utc).year
    years_ahead = ahead_mw / CLEARANCE_MW_PER_YEAR
    if years_ahead > 50:
        return None
    return datetime.now(timezone.utc).year + int(round(years_ahead))


def _summarise(rows: list[dict]) -> dict[str, Any]:
    active_mw = 0.0
    active_count = 0
    total_mw = 0.0
    for r in rows:
        mw = _num(r.get("capacity_mw") or r.get("tec_mw")) or 0.0
        total_mw += mw
        if _is_active(r.get("status")):
            active_mw += mw
            active_count += 1
    return {
        "queue_total_count": len(rows),
        "queue_total_mw": round(total_mw, 1),
        "ahead_in_queue_count": active_count,
        "ahead_in_queue_mw": round(active_mw, 1),
    }


async def queue_depth_for_substation(conn, substation_id: int) -> dict[str, Any]:
    """
    Public entry point. Always returns a 200-style dict with a provenance block.
    """
    sub = await _fetch_substation(conn, substation_id)
    if not sub:
        return {
            "substation_id": substation_id,
            "error": "substation_not_found",
            **make_provenance(SRC_SYNTHETIC, reason="substation id not found in DB"),
        }

    # 1. grid_ecr (DNO-published queue)
    rows, latest = await _queue_from_ecr(conn, substation_id)
    source = None
    reason: str | None = None
    refreshed: datetime | None = None
    if rows:
        source = SRC_DB_SNAPSHOT
        refreshed = latest or sub.get("updated_at")
    else:
        # 2. TEC register in DB
        tec_rows, tec_latest = await _queue_from_tec_db(conn, sub["name"])
        if tec_rows:
            rows = tec_rows
            source = SRC_DB_SNAPSHOT
            refreshed = tec_latest or sub.get("updated_at")
            reason = "grid_ecr empty for this substation; used eso_tec_register DB snapshot"
        else:
            # 3. Live NESO CKAN
            live_rows, live_refreshed, err = await _queue_from_neso_live(sub["name"])
            if live_rows:
                rows = live_rows
                source = SRC_NESO_LIVE
                refreshed = live_refreshed
                reason = "grid_ecr and TEC DB empty; pulled live from NESO CKAN"
            else:
                rows = []
                source = SRC_SYNTHETIC
                refreshed = None
                reason = (
                    err
                    or "no ECR rows, no TEC rows, and NESO live returned nothing for this substation"
                )

    summary = _summarise(rows)
    gen_headroom = _num(sub.get("gen_headroom_mw"))
    queued_mw = summary["queue_total_mw"]
    ahead_mw = summary["ahead_in_queue_mw"]

    free_headroom: float | None
    depth_ratio: float | None
    if gen_headroom is None:
        free_headroom = None
        depth_ratio = None
    else:
        free_headroom = max(0.0, round(gen_headroom - ahead_mw, 1))
        depth_ratio = round(ahead_mw / gen_headroom, 3) if gen_headroom > 0 else None

    viable_year = _earliest_viable_year(
        max(0.0, ahead_mw - (gen_headroom or 0.0))
    )

    return {
        "substation_id": substation_id,
        "substation_name": sub["name"],
        "dno": sub.get("dno"),
        "voltage_kv": _num(sub.get("voltage_kv")),
        "location": {"lat": sub.get("lat"), "lon": sub.get("lon")},
        "gen_headroom_mw": gen_headroom,
        "demand_headroom_mw": _num(sub.get("demand_headroom_mw")),
        "free_headroom_mw": free_headroom,
        "queue_depth_ratio": depth_ratio,
        "earliest_viable_year": viable_year,
        **summary,
        "queued_mw": queued_mw,
        "entries": [
            {
                "id": r.get("tec_id") or r.get("id"),
                "name": r.get("site_name") or r.get("customer_name"),
                "technology": r.get("technology") or r.get("tech_category"),
                "capacity_mw": _num(r.get("capacity_mw") or r.get("tec_mw")),
                "status": r.get("status"),
                "connection_date": _date_to_str(r.get("connection_date")),
                "effective_from": _date_to_str(r.get("effective_from")),
            }
            for r in rows[:100]
        ],
        **make_provenance(source, refreshed, reason=reason),
    }


def _date_to_str(v: Any) -> str | None:
    if v is None:
        return None
    try:
        return v.isoformat() if hasattr(v, "isoformat") else str(v)
    except Exception:
        return str(v)
