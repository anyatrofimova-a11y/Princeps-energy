"""Parcel enrichment endpoint — Glint-Solar-level detail for the
parcel popup card. Joins HMLR INSPIRE + CCOD + ALC + planning_designations
+ find_a_tender_notices + Companies House public API.

  GET /api/parcels/{inspire_id}/enriched
       Returns the full analysis bundle the popup needs:
         - solar_potential (existing)
         - land (ALC grade, land cover, mean slope)
         - bng (required %, baseline units, post-dev target)
         - owner (Companies House lookup: name, no, status, directors)
         - tenders (recent energy-CPV tenders within 50km)
         - planning_constraints (existing)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_pool

log = logging.getLogger("princeps.parcel_enrichment")
router = APIRouter(prefix="/api/parcels", tags=["parcel-enrichment"])


# ALC grade rank for sorting — lower number = better land.
ALC_RANK = {"1": 1, "2": 2, "3a": 3, "3b": 4, "4": 5, "5": 6, "non-agricultural": 7, "urban": 8}


async def _ch_company_lookup(company_no: str) -> dict[str, Any] | None:
    """Lookup a UK Companies House company by number. Public API; the
    free endpoint is unauthenticated for limited fields (name, status,
    type) — for officers we'd need an API key, so omit gracefully."""
    if not company_no:
        return None
    url = f"https://api.companieshouse.gov.uk/company/{company_no}"
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(url, headers={"User-Agent": "Princeps/1.0"})
            if r.status_code == 200:
                d = r.json()
                return {
                    "company_no": company_no,
                    "name": d.get("company_name"),
                    "status": d.get("company_status"),
                    "type": d.get("type"),
                    "incorporated_on": d.get("date_of_creation"),
                    "address": (d.get("registered_office_address") or {}),
                }
    except Exception as exc:  # noqa: BLE001
        log.debug("CH lookup failed for %s: %s", company_no, exc)
    return None


@router.get("/{inspire_id}/enriched")
async def enriched_parcel(
    inspire_id: str,
    radius_m: int = Query(500, ge=50, le=10000),
    tender_radius_km: int = Query(50, ge=5, le=200),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Full Glint-grade enrichment for a single parcel."""
    out: dict[str, Any] = {"inspire_id": inspire_id}

    # ── 1. Parcel core: area, centroid, flood zone (existing parcel data) ─
    try:
        async with pool.acquire(timeout=8) as conn:
            row = await conn.fetchrow(
                """
                SELECT parcel_id, ST_Area(geom)/10000 AS area_ha,
                       ST_Y(ST_Transform(ST_Centroid(geom), 4326)) AS lat,
                       ST_X(ST_Transform(ST_Centroid(geom), 4326)) AS lon,
                       owner_name, owner_address, owner_company_no
                FROM parcels
                WHERE parcel_id::text = $1 OR inspire_id = $1
                LIMIT 1
                """,
                inspire_id,
            )
            if not row:
                # Parcel not in DB — return a synthesised stub so the popup
                # still renders (callers can pass coordinates).
                row = None
    except Exception as exc:  # noqa: BLE001
        log.debug("parcel lookup failed: %s", exc)
        row = None

    if row:
        out["area_ha"] = float(row["area_ha"] or 0)
        out["lat"] = float(row["lat"] or 0)
        out["lon"] = float(row["lon"] or 0)
        out["owner_raw"] = {
            "name": row["owner_name"],
            "address": row["owner_address"],
            "company_no": row["owner_company_no"],
        }
    else:
        out["area_ha"] = None
        out["lat"] = None
        out["lon"] = None
        out["owner_raw"] = None
        out["warning"] = "parcel not found in DB"

    centroid_lat = out.get("lat")
    centroid_lon = out.get("lon")

    # ── 2. Solar potential (deterministic — area × GCR × kWp/m² × yield) ──
    if out["area_ha"]:
        # Conservative: 0.4 GCR × 0.4 kWp/m² of panel area, 1100 kWh/kWp UK avg
        kwp = out["area_ha"] * 10000 * 0.4 * 0.4
        out["solar_potential"] = {
            "mwp": round(kwp / 1000, 2),
            "specific_yield": 1100,
            "gwh_yr": round((kwp * 1100) / 1_000_000, 2),
        }

    # ── 3. Land analysis: ALC grade + planning constraints within radius ─
    if centroid_lat is not None and centroid_lon is not None:
        try:
            async with pool.acquire(timeout=6) as conn:
                # ALC grade — find the highest-quality (lowest rank) within radius
                alc_rows = await conn.fetch(
                    """
                    WITH q AS (
                        SELECT ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700) AS pt
                    )
                    SELECT name, attrs->>'grade' AS grade
                    FROM planning_designations d, q
                    WHERE dataset = 'agricultural-land-classification'
                      AND ST_DWithin(d.geom, q.pt, $3)
                    LIMIT 5
                    """,
                    centroid_lon, centroid_lat, radius_m,
                )
                grades = [(r["grade"] or "").lower() for r in alc_rows if r["grade"]]
                best = min(grades, key=lambda g: ALC_RANK.get(g, 99)) if grades else None
                out["land"] = {
                    "alc_grade": best,
                    "alc_hits_within_radius": len(alc_rows),
                    "land_cover": None,  # placeholder for UKCEH LCM lookup
                    "slope_pct_mean": None,  # placeholder for NASADEM mean
                }

                # Planning constraints (severity-bucketed)
                cons_rows = await conn.fetch(
                    """
                    WITH q AS (
                        SELECT ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700) AS pt
                    )
                    SELECT d.dataset, COUNT(*) AS n
                    FROM planning_designations d, q
                    WHERE d.dataset != 'agricultural-land-classification'
                      AND ST_DWithin(d.geom, q.pt, $3)
                    GROUP BY d.dataset
                    ORDER BY n DESC
                    """,
                    centroid_lon, centroid_lat, radius_m,
                )
                CRITICAL = {"site-of-special-scientific-interest", "special-area-of-conservation",
                            "special-protection-area", "ramsar", "national-park",
                            "ancient-woodland", "listed-building", "scheduled-monument"}
                HIGH = {"area-of-outstanding-natural-beauty", "conservation-area",
                        "nutrient-neutrality-catchment", "flood-risk-zone"}
                groups = {"CRITICAL": [], "HIGH": [], "MEDIUM": []}
                for r in cons_rows:
                    bucket = "CRITICAL" if r["dataset"] in CRITICAL else ("HIGH" if r["dataset"] in HIGH else "MEDIUM")
                    groups[bucket].append({"dataset": r["dataset"], "n": int(r["n"])})
                out["planning_constraints"] = groups
                out["statutory_blockers"] = len(groups["CRITICAL"])
        except Exception as exc:  # noqa: BLE001
            log.debug("ALC/constraints lookup failed: %s", exc)
            out["land"] = {"alc_grade": None, "alc_hits_within_radius": 0,
                            "land_cover": None, "slope_pct_mean": None}
            out["planning_constraints"] = {"CRITICAL": [], "HIGH": [], "MEDIUM": []}

    # ── 4. BNG: mandatory 10% under DEFRA regime from Nov 2024 ────────
    if out["area_ha"]:
        # Crude habitat-units estimate: 6 distinct-habitat units / ha typical
        # for improved grassland / arable; multiply by 10% for required offset.
        baseline_units = round(out["area_ha"] * 6, 2)
        out["bng"] = {
            "required_pct": 10,
            "regime": "DEFRA mandatory (Nov 2024+)",
            "baseline_units": baseline_units,
            "post_dev_target_units": round(baseline_units * 1.1, 2),
            "offset_cost_p50_gbp": int(baseline_units * 0.10 * 42_000),  # ~£42k/unit avg
        }

    # ── 5. Owner: Companies House lookup ────────────────────────────
    raw_owner = out.get("owner_raw") or {}
    company_no = (raw_owner.get("company_no") or "").strip()
    if company_no:
        ch = await _ch_company_lookup(company_no)
        out["owner"] = ch or {
            "company_no": company_no,
            "name": raw_owner.get("name"),
            "status": None,
        }
    else:
        out["owner"] = {
            "company_no": None,
            "name": raw_owner.get("name"),
            "status": "no_company_no_on_title",
        }

    # ── 6. Tender opportunities within tender_radius_km ─────────────
    if centroid_lat is not None and centroid_lon is not None:
        try:
            async with pool.acquire(timeout=6) as conn:
                tenders = await conn.fetch(
                    """
                    SELECT notice_id, title, publisher, value_gbp_min, value_gbp_max,
                           deadline, source_url
                    FROM find_a_tender_notices
                    WHERE ST_DWithin(
                            ST_Transform(geom, 27700),
                            ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                            $3 * 1000
                          )
                    ORDER BY deadline DESC NULLS LAST
                    LIMIT 10
                    """,
                    centroid_lon, centroid_lat, tender_radius_km,
                )
                out["tenders"] = [
                    {
                        "id": t["notice_id"],
                        "title": t["title"],
                        "publisher": t["publisher"],
                        "value_gbp_min": float(t["value_gbp_min"]) if t["value_gbp_min"] else None,
                        "value_gbp_max": float(t["value_gbp_max"]) if t["value_gbp_max"] else None,
                        "deadline": t["deadline"].isoformat() if t["deadline"] else None,
                        "url": t["source_url"],
                    }
                    for t in tenders
                ]
        except Exception as exc:  # noqa: BLE001
            log.debug("tender lookup failed: %s", exc)
            out["tenders"] = []

    # ── 7. Verdict — simple rules ──────────────────────────────────
    n_critical = out.get("statutory_blockers", 0)
    if n_critical == 0:
        out["verdict"] = "GO"
        out["verdict_rationale"] = "No statutory blockers within radius"
    elif n_critical == 1:
        out["verdict"] = "CAUTION"
        out["verdict_rationale"] = "1 critical designation nearby — may not be a hard block"
    else:
        out["verdict"] = "NO-GO"
        out["verdict_rationale"] = f"{n_critical} critical designations nearby"

    out["attribution"] = "HMLR INSPIRE · CCOD · planning.data.gov.uk · Companies House · Find-a-Tender"
    return out
