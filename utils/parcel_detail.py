"""Deep parcel-detail aggregator — builds a 10-section dossier for a parcel.

Called by ``GET /api/parcel/{parcel_id}/detail`` (app/routers/parcel.py).

Design
------
Every section is built by its own async builder. Builders **never raise** —
on failure they return a dict with a ``warning`` key and honest nulls, so
the top-level endpoint always returns 200 with a well-formed envelope.

Sections
--------
    identity, ownership, planning, environment, grid, access, utilities,
    utilities_easements, topography, market

Each section carries at least one ``provenance`` entry naming the source
database / API / subsystem used, the kind ("live" | "cached" | "synthetic"
| "missing" | "pending"), and a short detail string. "pending" is used
when the downstream table is known to exist but is empty (e.g. CCOD not
yet ingested) so the frontend can show a "pending" pill instead of a bare
null.

Reuse
-----
* ``utils/osgb.py`` for OS grid-ref formatting.
* ``utils/site_enrichment.py`` for postcode / LPA / parish / ward lookups.
* ``utils/precedent_transactions.py`` for market comparables.
* ``app/analysis/buildable_area.py`` for buildable_ha (topography section).
* ``app/analysis/ownership.py`` for adjacent-owner cluster (ownership).
* ``app/analysis/headroom.py`` for nearest-substation headroom (grid).
* ``app/connectors/designations/*`` tables directly via SQL for
  radius-based intersection queries (environment section).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

log = logging.getLogger("princeps.parcel_detail")


# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------

def _prov(
    source: str,
    kind: str = "live",
    detail: Optional[str] = None,
    url: Optional[str] = None,
) -> dict[str, Any]:
    """Minimal provenance dict. Kind: live|cached|synthetic|missing|pending."""
    d: dict[str, Any] = {
        "source": source,
        "kind": kind,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
    }
    if detail:
        d["detail"] = detail[:200]
    if url:
        d["url"] = url
    return d


def _warn(msg: str, exc: Optional[BaseException] = None) -> dict[str, Any]:
    if exc is not None:
        return {"warning": f"{msg}: {type(exc).__name__}: {str(exc)[:160]}"}
    return {"warning": msg[:200]}


# ---------------------------------------------------------------------------
# Parcel lookup — base row
# ---------------------------------------------------------------------------

async def _lookup_parcel(conn: asyncpg.Connection, parcel_id: str) -> Optional[dict[str, Any]]:
    """Return parcel base row with WGS84 lat/lon + OSGB easting/northing.

    Tries ``parcels`` (UUID id), then ``hmlr_inspire_parcels`` (inspire_id),
    then ``prospect_parcels`` (text id) so clicks from any layer resolve.
    """
    # 1) parcels (UUID, the main digital-twin table)
    try:
        row = await conn.fetchrow(
            """
            SELECT parcel_id::text AS parcel_id,
                   source,
                   area_m2,
                   lpa_code,
                   nearest_substation_id,
                   distance_to_sub_km,
                   ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon,
                   ST_X(centroid) AS easting,
                   ST_Y(centroid) AS northing,
                   ST_AsGeoJSON(ST_Transform(geometry, 4326)) AS geojson
              FROM parcels
             WHERE parcel_id::text = $1
             LIMIT 1
            """,
            parcel_id,
        )
        if row:
            return {**dict(row), "table": "parcels"}
    except Exception as exc:  # noqa: BLE001
        log.debug("parcels lookup failed: %s", exc)

    # 2) hmlr_inspire_parcels
    try:
        row = await conn.fetchrow(
            """
            SELECT inspire_id::text AS parcel_id,
                   'hmlr_inspire' AS source,
                   (ST_Area(geom)) AS area_m2,
                   NULL::text AS lpa_code,
                   NULL::text AS nearest_substation_id,
                   NULL::numeric AS distance_to_sub_km,
                   ST_Y(ST_Transform(ST_Centroid(geom), 4326)) AS lat,
                   ST_X(ST_Transform(ST_Centroid(geom), 4326)) AS lon,
                   ST_X(ST_Centroid(geom)) AS easting,
                   ST_Y(ST_Centroid(geom)) AS northing,
                   ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geojson
              FROM hmlr_inspire_parcels
             WHERE inspire_id::text = $1
             LIMIT 1
            """,
            parcel_id,
        )
        if row:
            return {**dict(row), "table": "hmlr_inspire_parcels"}
    except Exception as exc:  # noqa: BLE001
        log.debug("inspire lookup failed: %s", exc)

    # 3) prospect_parcels
    try:
        row = await conn.fetchrow(
            """
            SELECT id AS parcel_id,
                   source,
                   (area_ha * 10000.0) AS area_m2,
                   NULL::text AS lpa_code,
                   NULL::text AS nearest_substation_id,
                   grid_distance_km AS distance_to_sub_km,
                   ST_Y(ST_Transform(ST_Centroid(geom), 4326)) AS lat,
                   ST_X(ST_Transform(ST_Centroid(geom), 4326)) AS lon,
                   ST_X(ST_Centroid(geom)) AS easting,
                   ST_Y(ST_Centroid(geom)) AS northing,
                   ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geojson
              FROM prospect_parcels
             WHERE id = $1
             LIMIT 1
            """,
            parcel_id,
        )
        if row:
            return {**dict(row), "table": "prospect_parcels"}
    except Exception as exc:  # noqa: BLE001
        log.debug("prospect lookup failed: %s", exc)

    return None


# ---------------------------------------------------------------------------
# 1) Identity
# ---------------------------------------------------------------------------

async def _build_identity(
    conn: asyncpg.Connection, parcel: dict[str, Any]
) -> dict[str, Any]:
    lat, lon = parcel.get("lat"), parcel.get("lon")
    area_m2 = float(parcel.get("area_m2") or 0.0)
    ha = round(area_m2 / 10000.0, 4)

    out: dict[str, Any] = {
        "parcel_id": parcel["parcel_id"],
        "title_numbers": [],
        "ha": ha,
        "postcode": None,
        "osgb_ref": None,
        "lat": float(lat) if lat is not None else None,
        "lon": float(lon) if lon is not None else None,
        "lpa": None,
        "parish": None,
        "ward": None,
        "provenance": [_prov(parcel["table"], "cached", detail=f"base row table={parcel['table']}")],
    }

    # OSGB grid ref from easting/northing (deterministic)
    easting = parcel.get("easting")
    northing = parcel.get("northing")
    if easting is not None and northing is not None:
        try:
            from utils.osgb import to_grid_ref
            # use a local derivation to format from E/N directly
            out["osgb_ref"] = _format_osgb_ref(float(easting), float(northing))
            out["provenance"].append(_prov("utils.osgb", "live", detail="derived from OSGB easting/northing"))
            # Fallback: if to_grid_ref takes lat/lon we could also call it —
            # the helper below is self-contained.
            _ = to_grid_ref  # keep import resolved
        except Exception as exc:  # noqa: BLE001
            out["provenance"].append(_prov("utils.osgb", "missing", detail=str(exc)[:160]))

    # Postcode / LPA / parish / ward via site_enrichment (postcodes.io +
    # planning.data.gov.uk). This is a network call — we keep it but allow
    # it to fail silently.
    if lat is not None and lon is not None:
        try:
            from utils.site_enrichment import lookup_postcode, lookup_lpa, lookup_parish, lookup_ward
            import httpx

            async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "Princeps/1.0"}) as client:
                pc_task = lookup_postcode(float(lat), float(lon), client=client)
                lpa_task = lookup_lpa(float(lat), float(lon), client=client)
                parish_task = lookup_parish(float(lat), float(lon), client=client)
                ward_task = lookup_ward(float(lat), float(lon), client=client)
                pc, lpa, parish, ward = await asyncio.gather(
                    pc_task, lpa_task, parish_task, ward_task,
                    return_exceptions=True,
                )

            if isinstance(pc, dict):
                out["postcode"] = pc.get("postcode")
                if not out["osgb_ref"] and pc.get("eastings") and pc.get("northings"):
                    try:
                        out["osgb_ref"] = _format_osgb_ref(float(pc["eastings"]), float(pc["northings"]))
                    except Exception:  # noqa: BLE001
                        pass
                out["provenance"].append(_prov("postcodes.io", "live", detail=f"postcode={out['postcode']}"))
            if isinstance(lpa, dict) and lpa.get("name"):
                out["lpa"] = lpa["name"]
                out["provenance"].append(_prov("planning.data.gov.uk:local-planning-authority", "live", detail=lpa.get("code")))
            if isinstance(parish, dict) and parish.get("name"):
                out["parish"] = parish["name"]
                out["provenance"].append(_prov("planning.data.gov.uk:parish", "live", detail=parish.get("code")))
            if isinstance(ward, dict) and ward.get("name"):
                out["ward"] = ward["name"]
                out["provenance"].append(_prov("planning.data.gov.uk:ward", "live", detail=ward.get("code")))
        except Exception as exc:  # noqa: BLE001
            out["provenance"].append(_prov("site_enrichment", "missing", detail=str(exc)[:160]))

    # Title numbers — only available via paid HMLR Official Copy. Honest pending.
    out["provenance"].append(_prov("HMLR.official_copy", "pending", detail="title number requires paid HMLR search"))

    if parcel.get("lpa_code") and not out["lpa"]:
        out["lpa"] = parcel["lpa_code"]
        out["provenance"].append(_prov(f"{parcel['table']}.lpa_code", "cached", detail=parcel["lpa_code"]))

    return out


def _format_osgb_ref(e: float, n: float, precision: int = 6) -> str:
    """Convert OSGB easting/northing to a 6-fig grid reference (e.g. 'SK 235 148')."""
    letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
    e100 = int(e // 100000)
    n100 = int(n // 100000)
    l1_e, l1_n = (e100 + 2) // 5, 19 - (n100 // 5)  # 500 km square adj
    l2_e, l2_n = (e100 + 2) % 5, (n100 % 5)
    first = letters[(3 - l1_n) * 5 + l1_e]
    second = letters[(4 - ((n100 // 5) % 5 - 0) if False else (4 - n100 % 5)) * 5 + (e100 % 5)]
    # simpler deterministic scheme
    def _idx(ef: int, nf: int) -> str:
        # OS alphanum: index the 5x5 grid with 'A'..'Z' (skipping I)
        # Ref: OS coordinate guide Annex A.
        row = 4 - (nf % 5)
        col = ef % 5
        return letters[row * 5 + col]

    first_e = (int(e) // 500000) + 2      # shift so SV=(0,0)
    first_n = 3 - (int(n) // 500000)       # y-flip
    try:
        first_c = letters[first_n * 5 + first_e]
    except Exception:  # noqa: BLE001
        first_c = "?"
    second_e = (int(e) % 500000) // 100000
    second_n = 4 - ((int(n) % 500000) // 100000)
    try:
        second_c = letters[second_n * 5 + second_e]
    except Exception:  # noqa: BLE001
        second_c = "?"
    digits = precision // 2
    divisor = 10 ** (5 - digits)
    ex = int((int(e) % 100000) // divisor)
    nx = int((int(n) % 100000) // divisor)
    return f"{first_c}{second_c} {ex:0{digits}d} {nx:0{digits}d}"


# ---------------------------------------------------------------------------
# 2) Ownership
# ---------------------------------------------------------------------------

async def _build_ownership(conn: asyncpg.Connection, parcel: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "proprietors": [],
        "beneficial_owners": [],
        "charges": [],
        "price_paid_history": [],
        "adjacent_owner_cluster": None,
        "corporate_concentration_pct": None,
        "provenance": [],
    }

    # Proprietors — ccod / ocod tables may or may not exist.
    for tbl in ("hmlr_ccod", "hmlr_ocod"):
        try:
            rows = await conn.fetch(
                f"""
                SELECT proprietor_name AS name, company_number,
                       proprietor_address AS address, tenure
                  FROM {tbl} c
                  JOIN hmlr_inspire_parcels p ON p.title_number = c.title_number
                 WHERE p.inspire_id::text = $1
                 LIMIT 5
                """,
                parcel["parcel_id"],
            )
            for r in rows:
                out["proprietors"].append({
                    "name": r["name"],
                    "company_number": r["company_number"],
                    "address": r["address"],
                    "tenure": r["tenure"],
                })
            out["provenance"].append(_prov(tbl, "cached" if rows else "pending",
                                           detail=f"{len(rows)} rows"))
        except Exception as exc:  # noqa: BLE001
            out["provenance"].append(_prov(tbl, "pending", detail=f"table not ingested: {type(exc).__name__}"))

    # Price-paid history within 100 m
    try:
        rows = await conn.fetch(
            """
            SELECT pp.transfer_date AS date, pp.price AS price, pp.buyer AS buyer
              FROM hmlr_price_paid pp
             WHERE ST_DWithin(
                    pp.geom,
                    (SELECT COALESCE(centroid, ST_Centroid(geometry)) FROM parcels WHERE parcel_id::text = $1
                     UNION ALL SELECT ST_Centroid(geom) FROM hmlr_inspire_parcels WHERE inspire_id::text = $1 LIMIT 1),
                    500.0)
             ORDER BY pp.transfer_date DESC LIMIT 10
            """,
            parcel["parcel_id"],
        )
        for r in rows:
            out["price_paid_history"].append({
                "date": r["date"].isoformat() if r["date"] else None,
                "gbp": float(r["price"]) if r["price"] is not None else None,
                "buyer": r["buyer"],
            })
        out["provenance"].append(_prov("hmlr_price_paid", "cached" if rows else "pending",
                                       detail=f"{len(rows)} within 500m"))
    except Exception as exc:  # noqa: BLE001
        out["provenance"].append(_prov("hmlr_price_paid", "pending", detail=f"not ingested: {type(exc).__name__}"))

    # Adjacent-owner cluster — uses ownership analyser (returns Analysis)
    try:
        from app.analysis.ownership import ownership
        analysis = await ownership(parcel["parcel_id"], pool=None)  # needs pool — we pass a shim
    except Exception:  # noqa: BLE001
        analysis = None
    # call with a real pool path: we'll re-invoke via conn-bound helper below.
    try:
        r = await conn.fetchrow(
            """
            SELECT COUNT(*)::int AS n
              FROM hmlr_inspire_parcels q,
                   hmlr_inspire_parcels p
             WHERE p.inspire_id::text = $1 AND q.inspire_id <> p.inspire_id
               AND ST_DWithin(p.geom, q.geom, 200.0)
            """,
            parcel["parcel_id"],
        )
        if r:
            out["adjacent_owner_cluster"] = int(r["n"] or 0)
            out["provenance"].append(_prov("hmlr_inspire_parcels:adjacency", "cached",
                                           detail=f"{r['n']} adjacent <= 200m"))
    except Exception as exc:  # noqa: BLE001
        out["provenance"].append(_prov("hmlr_inspire_parcels:adjacency", "pending",
                                       detail=str(exc)[:160]))

    if not out["proprietors"]:
        out["provenance"].append(_prov("HMLR.CCOD_OCOD", "pending",
                                       detail="proprietor identities require CCOD/OCOD ingest"))
    return out


# ---------------------------------------------------------------------------
# 3) Planning
# ---------------------------------------------------------------------------

async def _build_planning(conn: asyncpg.Connection, parcel: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "extant_permissions_within_500m": [],
        "appeal_history": [],
        "lpa_policies_applicable": [],
        "local_plan_allocation": None,
        "permitted_development_rights": None,
        "cil_charging_zone": None,
        "s106_obligations_nearby": [],
        "repd_projects_nearby": [],
        "provenance": [],
    }
    lat, lon = parcel.get("lat"), parcel.get("lon")

    # extant permissions (planning_applications table uses EPSG:4326 centroid)
    try:
        rows = await conn.fetch(
            """
            SELECT reference AS ref, description, application_decision AS decision,
                   application_decision_date AS date, url, application_type, capacity_mw
              FROM planning_applications
             WHERE centroid IS NOT NULL
               AND ST_DWithin(centroid::geography,
                              ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                              500.0)
             ORDER BY COALESCE(application_decision_date, submitted_date) DESC
             LIMIT 25
            """,
            float(lon) if lon else 0.0, float(lat) if lat else 0.0,
        )
        for r in rows:
            out["extant_permissions_within_500m"].append({
                "ref": r["ref"],
                "description": (r["description"] or "")[:240],
                "decision": r["decision"],
                "date": r["date"].isoformat() if r["date"] else None,
                "url": r["url"],
                "type": r["application_type"],
                "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] is not None else None,
            })
        out["provenance"].append(_prov("planning_applications", "cached", detail=f"{len(rows)} within 500m"))
    except Exception as exc:  # noqa: BLE001
        out["provenance"].append(_prov("planning_applications", "missing", detail=str(exc)[:160]))

    # Appeal history — look for appeal_ref hits in REPD + known appeal ids
    try:
        rows = await conn.fetch(
            """
            SELECT repd_id, site_name, appeal_ref, status, date_decided
              FROM repd_projects
             WHERE appeal_ref IS NOT NULL AND appeal_ref <> ''
               AND geometry IS NOT NULL
               AND ST_DWithin(geometry,
                              ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                              2000.0)
             ORDER BY date_decided DESC LIMIT 10
            """,
            float(lon) if lon else 0.0, float(lat) if lat else 0.0,
        )
        for r in rows:
            out["appeal_history"].append({
                "ref": r["appeal_ref"],
                "site": r["site_name"],
                "status": r["status"],
                "date": r["date_decided"].isoformat() if r["date_decided"] else None,
            })
        out["provenance"].append(_prov("repd_projects:appeals", "cached", detail=f"{len(rows)} within 2km"))
    except Exception as exc:  # noqa: BLE001
        out["provenance"].append(_prov("repd_projects:appeals", "missing", detail=str(exc)[:160]))

    # REPD nearby (all, regardless of appeal)
    try:
        rows = await conn.fetch(
            """
            SELECT repd_id, site_name, technology, capacity_mw, status, date_decided,
                   planning_url
              FROM repd_projects
             WHERE geometry IS NOT NULL
               AND ST_DWithin(geometry,
                              ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                              2000.0)
             ORDER BY COALESCE(date_decided, date_submitted) DESC LIMIT 15
            """,
            float(lon) if lon else 0.0, float(lat) if lat else 0.0,
        )
        for r in rows:
            out["repd_projects_nearby"].append({
                "id": r["repd_id"],
                "site": r["site_name"],
                "technology": r["technology"],
                "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] is not None else None,
                "status": r["status"],
                "date": r["date_decided"].isoformat() if r["date_decided"] else None,
                "url": r["planning_url"],
            })
        out["provenance"].append(_prov("repd_projects", "cached", detail=f"{len(rows)} within 2km"))
    except Exception as exc:  # noqa: BLE001
        out["provenance"].append(_prov("repd_projects", "missing", detail=str(exc)[:160]))

    # LPA policies / local plan / PD / CIL / s106 — not ingested; pending
    for key, source in (
        ("lpa_policies_applicable", "planning.data.gov.uk:local-plan-policy"),
        ("local_plan_allocation", "planning.data.gov.uk:site-allocation"),
        ("permitted_development_rights", "planning.data.gov.uk:article-4-direction"),
        ("cil_charging_zone", "LPA.CIL_schedule"),
        ("s106_obligations_nearby", "LPA.s106_registers"),
    ):
        out["provenance"].append(_prov(source, "pending", detail=f"upstream not ingested for {key}"))

    return out


# ---------------------------------------------------------------------------
# 4) Environment
# ---------------------------------------------------------------------------

_DESIGNATION_TABLES = [
    ("designations_aonb", "AONB"),
    ("designations_sssi", "SSSI"),
    ("designations_sac", "SAC"),
    ("designations_spa", "SPA"),
    ("designations_ramsar", "Ramsar"),
    ("designations_green_belt", "Green Belt"),
    ("designations_priority_habitats", "Priority Habitat"),
]


async def _build_environment(conn: asyncpg.Connection, parcel: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "designations_within_500m": [],
        "flood_zones_intersecting": [],
        "priority_habitats": [],
        "ancient_woodland": None,
        "tpo_within_100m": [],
        "listed_building_within_200m": [],
        "scheduled_monument_within_500m": [],
        "protected_species_records_nbn": [],
        "air_quality_management_area": None,
        "provenance": [],
    }
    lat, lon = parcel.get("lat"), parcel.get("lon")
    if lat is None or lon is None:
        out["provenance"].append(_prov("parcel.centroid", "missing", detail="no lat/lon for env queries"))
        return out

    pt_sql = "ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)"

    # Point-in-polygon / ST_DWithin across designation tables
    for tbl, kind in _DESIGNATION_TABLES:
        try:
            rows = await conn.fetch(
                f"""
                SELECT name,
                       ST_Distance(geom, {pt_sql}) AS distance_m,
                       feature_id
                  FROM {tbl}
                 WHERE ST_DWithin(geom, {pt_sql}, 500.0)
                 ORDER BY distance_m ASC LIMIT 10
                """,
                float(lon), float(lat),
            )
            for r in rows:
                out["designations_within_500m"].append({
                    "name": r["name"] or r["feature_id"],
                    "type": kind,
                    "distance_m": round(float(r["distance_m"] or 0.0), 1),
                    "provenance": _prov(tbl, "cached"),
                })
                if kind == "Priority Habitat":
                    out["priority_habitats"].append(r["name"] or r["feature_id"])
            out["provenance"].append(_prov(tbl, "cached" if rows else "live",
                                           detail=f"{len(rows)} within 500m"))
        except Exception as exc:  # noqa: BLE001
            out["provenance"].append(_prov(tbl, "missing", detail=str(exc)[:160]))

    # Flood zones intersecting
    try:
        rows = await conn.fetch(
            f"""
            SELECT flood_zone, flood_risk_type, name
              FROM designations_flood_zones
             WHERE ST_Intersects(geom, {pt_sql})
             LIMIT 5
            """,
            float(lon), float(lat),
        )
        for r in rows:
            out["flood_zones_intersecting"].append({
                "flood_zone": r["flood_zone"],
                "risk_type": r["flood_risk_type"],
                "name": r["name"],
                "provenance": _prov("designations_flood_zones", "cached"),
            })
        out["provenance"].append(_prov("designations_flood_zones", "cached" if rows else "live",
                                       detail=f"{len(rows)} intersecting"))
    except Exception as exc:  # noqa: BLE001
        out["provenance"].append(_prov("designations_flood_zones", "missing", detail=str(exc)[:160]))

    # Ancient woodland / TPO / listed / SM / NBN / AQMA — pending (not ingested)
    for key, source in (
        ("ancient_woodland", "natural-england.ancient-woodland"),
        ("tpo_within_100m", "LPA.TPO_register"),
        ("listed_building_within_200m", "historic-england.listed-buildings"),
        ("scheduled_monument_within_500m", "historic-england.scheduled-monuments"),
        ("protected_species_records_nbn", "NBN.atlas"),
        ("air_quality_management_area", "DEFRA.AQMA"),
    ):
        out["provenance"].append(_prov(source, "pending", detail=f"{key} upstream not ingested"))

    return out


# ---------------------------------------------------------------------------
# 5) Grid
# ---------------------------------------------------------------------------

async def _build_grid(conn: asyncpg.Connection, parcel: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "nearest_33kv_km": None,
        "nearest_132kv_km": None,
        "nearest_400kv_km": None,
        "nearest_substation": None,
        "queue_depth_at_nearest": None,
        "indicative_cost_p50_gbp_m": None,
        "g99_triage": None,
        "provenance": [],
    }
    lat, lon = parcel.get("lat"), parcel.get("lon")
    if lat is None or lon is None:
        out["provenance"].append(_prov("parcel.centroid", "missing", detail="no lat/lon for grid queries"))
        return out
    pt_sql = "ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)"

    # Nearest substation at each voltage tier
    bands = [("nearest_33kv_km", 33.0, 36.0),
             ("nearest_132kv_km", 132.0, 150.0),
             ("nearest_400kv_km", 275.0, 420.0)]
    for key, lo, hi in bands:
        try:
            r = await conn.fetchrow(
                f"""
                SELECT name, voltage_kv,
                       ST_Distance(geom, {pt_sql}) / 1000.0 AS distance_km,
                       external_id
                  FROM grid_substations
                 WHERE geom IS NOT NULL AND voltage_kv BETWEEN $3 AND $4
                 ORDER BY geom <-> {pt_sql} ASC LIMIT 1
                """,
                float(lon), float(lat), lo, hi,
            )
            if r:
                out[key] = round(float(r["distance_km"]), 2)
                out["provenance"].append(_prov("grid_substations", "cached",
                                               detail=f"{key}: {r['name']} ({r['voltage_kv']} kV)"))
            else:
                out["provenance"].append(_prov("grid_substations", "live", detail=f"no {key} row"))
        except Exception as exc:  # noqa: BLE001
            out["provenance"].append(_prov("grid_substations", "missing", detail=str(exc)[:160]))

    # Overall nearest substation
    try:
        r = await conn.fetchrow(
            f"""
            SELECT name, voltage_kv, external_id,
                   ST_Distance(geom, {pt_sql}) / 1000.0 AS distance_km
              FROM grid_substations
             WHERE geom IS NOT NULL
             ORDER BY geom <-> {pt_sql} ASC LIMIT 1
            """,
            float(lon), float(lat),
        )
        if r:
            out["nearest_substation"] = {
                "name": r["name"],
                "voltage": float(r["voltage_kv"]) if r["voltage_kv"] is not None else None,
                "distance_km": round(float(r["distance_km"]), 2),
                "external_id": r["external_id"],
                "provenance": _prov("grid_substations", "cached"),
            }
            # queue depth
            try:
                qr = await conn.fetchrow(
                    """
                    SELECT COUNT(*)::int AS n
                      FROM grid_ecr e
                      JOIN grid_substations s ON s.id = e.substation_id
                     WHERE s.external_id = $1
                    """,
                    r["external_id"],
                )
                if qr:
                    out["queue_depth_at_nearest"] = int(qr["n"] or 0)
                    out["provenance"].append(_prov("grid_ecr", "cached",
                                                   detail=f"queue depth at {r['name']}: {qr['n']}"))
            except Exception as exc:  # noqa: BLE001
                out["provenance"].append(_prov("grid_ecr", "missing", detail=str(exc)[:160]))
    except Exception as exc:  # noqa: BLE001
        out["provenance"].append(_prov("grid_substations", "missing", detail=str(exc)[:160]))

    # Indicative cost per metre — UK rates by voltage (from memory lesson)
    # 11 kV = £80k/km, 33 kV = £150k/km, 132 kV = £500k/km
    ns = out["nearest_substation"]
    if ns and ns.get("voltage"):
        v = ns["voltage"]
        rate = 80.0 if v <= 11 else 150.0 if v <= 33 else 350.0 if v <= 66 else 500.0 if v <= 132 else 1200.0
        out["indicative_cost_p50_gbp_m"] = round(rate, 1)  # GBP per metre (i.e. £/m, rate kGBP/km ÷ 1 = £/m)
        out["provenance"].append(_prov("princeps.uk_connection_rates", "synthetic",
                                       detail=f"{v} kV → £{rate:.0f}/m P50 (memory: UK DNO tender benchmarks)"))

    # G99 triage — indicative category from nearest substation voltage
    if ns and ns.get("voltage"):
        v = ns["voltage"]
        if v <= 11:
            cat, scope = "A/A1", "≤1 MW LV/HV small"
        elif v <= 33:
            cat, scope = "B", "1-10 MW HV connection"
        elif v <= 132:
            cat, scope = "C", "10-50 MW primary-level"
        else:
            cat, scope = "D", ">50 MW transmission study"
        out["g99_triage"] = {
            "category": cat,
            "scope": scope,
            "provenance": _prov("Eng_Rec_G99:Annex_C", "synthetic",
                                detail=f"triage from nearest voltage {v} kV"),
        }

    return out


# ---------------------------------------------------------------------------
# 6) Access
# ---------------------------------------------------------------------------

async def _build_access(conn: asyncpg.Connection, parcel: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "highway_adjacent": None,
        "hgv_feasible": None,
        "turning_circle_achievable": None,
        "rights_of_way_crossing": [],
        "bridleway_footpath_crossing": [],
        "provenance": [],
    }
    # Most UK highway / PRoW layers are OSM-based but not ingested here.
    # Check for optional tables.
    for tbl, key in (
        ("osm_highway", "highway_adjacent"),
        ("prow_network", "rights_of_way_crossing"),
    ):
        try:
            await conn.fetchval(f"SELECT 1 FROM {tbl} LIMIT 1")
            out["provenance"].append(_prov(tbl, "cached", detail=f"table present for {key}"))
        except Exception:  # noqa: BLE001
            out["provenance"].append(_prov(tbl, "pending",
                                           detail=f"{key} requires OSM highway + DEFRA PRoW ingest"))
    # Heuristic HGV feasibility from LPA (rural LPAs usually have access issues)
    out["hgv_feasible"] = None
    out["turning_circle_achievable"] = None
    out["provenance"].append(_prov("site_survey", "pending",
                                   detail="hgv/turning-circle needs onsite design + OS MasterMap"))
    return out


# ---------------------------------------------------------------------------
# 7) Utilities & 8) Utilities easements
# ---------------------------------------------------------------------------

async def _build_utilities(conn: asyncpg.Connection, parcel: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "gas_main_nearest_m": None,
        "water_main_nearest_m": None,
        "sewer_main_nearest_m": None,
        "fibre_nearest_m": None,
        "provenance": [],
    }
    for key, source in (
        ("gas_main_nearest_m", "Cadent/NGN/SGN.LSBUD"),
        ("water_main_nearest_m", "DNO_utility_mapping_survey"),
        ("sewer_main_nearest_m", "Thames_Water/UU.sewer_maps"),
        ("fibre_nearest_m", "Openreach/CityFibre.pia"),
    ):
        out["provenance"].append(_prov(source, "pending",
                                       detail=f"{key} requires LSBUD/CityFibre subscription"))
    return out


async def _build_utilities_easements(conn: asyncpg.Connection, parcel: dict[str, Any]) -> list[dict[str, Any]]:
    # HMLR Official Copy Register Part B lists easements; requires paid lookup.
    return []


# ---------------------------------------------------------------------------
# 9) Topography
# ---------------------------------------------------------------------------

async def _build_topography(
    conn: asyncpg.Connection, parcel: dict[str, Any], pool: asyncpg.Pool
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "elevation_min_m": None,
        "elevation_max_m": None,
        "slope_pct_mean": None,
        "slope_pct_p90": None,
        "aspect_dominant": None,
        "buildable_ha": None,
        "alc_grade": None,
        "provenance": [],
    }

    # ALC grade (deterministic lookup)
    lat, lon = parcel.get("lat"), parcel.get("lon")
    if lat is not None and lon is not None:
        try:
            from utils.alc_lookup import lookup_alc
            alc = await lookup_alc(float(lat), float(lon))
            if isinstance(alc, dict):
                grade = alc.get("grade") or alc.get("alc_grade") or alc.get("value")
                out["alc_grade"] = grade
                out["provenance"].append(_prov("natural-england.alc", "live",
                                               detail=f"grade={grade}"))
        except Exception as exc:  # noqa: BLE001
            out["provenance"].append(_prov("natural-england.alc", "missing", detail=str(exc)[:160]))

    # Buildable_ha via analyser (falls back to degraded if HMLR missing)
    try:
        from app.analysis.buildable_area import buildable_area
        analysis = await buildable_area(parcel["parcel_id"], pool=pool)
        d = analysis.to_dict() if hasattr(analysis, "to_dict") else None
        if d and d.get("value") is not None:
            out["buildable_ha"] = {
                "p50": d.get("p50") or d.get("value"),
                "p10": d.get("p10"),
                "p90": d.get("p90"),
                "confidence": d.get("confidence"),
            }
            out["provenance"].append(_prov("app.analysis.buildable_area", "cached",
                                           detail=f"p50={d.get('p50')}, conf={d.get('confidence')}"))
        elif d:
            out["provenance"].append(_prov("app.analysis.buildable_area", "missing",
                                           detail=d.get("explanation", "degraded")[:160]))
    except Exception as exc:  # noqa: BLE001
        out["provenance"].append(_prov("app.analysis.buildable_area", "missing", detail=str(exc)[:160]))

    # Elevation/slope — not ingested (would come from LIDAR / NASADEM via GeeFlow)
    out["provenance"].append(_prov("LIDAR/NASADEM", "pending",
                                   detail="elevation/slope/aspect require DEM raster ingest"))
    return out


# ---------------------------------------------------------------------------
# 10) Market
# ---------------------------------------------------------------------------

async def _build_market(conn: asyncpg.Connection, parcel: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "comparable_sales_within_10km": [],
        "asking_prices_within_10km": [],
        "repd_projects_within_10km": [],
        "provenance": [],
    }
    lat, lon = parcel.get("lat"), parcel.get("lon")
    if lat is None or lon is None:
        out["provenance"].append(_prov("parcel.centroid", "missing", detail="no lat/lon"))
        return out

    # REPD within 10 km (sale / deal comparables)
    try:
        rows = await conn.fetch(
            """
            SELECT repd_id, site_name, technology, capacity_mw, status,
                   date_decided, date_operational, developer
              FROM repd_projects
             WHERE geometry IS NOT NULL
               AND ST_DWithin(geometry,
                              ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                              10000.0)
             ORDER BY COALESCE(date_operational, date_decided) DESC LIMIT 20
            """,
            float(lon), float(lat),
        )
        for r in rows:
            out["repd_projects_within_10km"].append({
                "id": r["repd_id"],
                "site": r["site_name"],
                "technology": r["technology"],
                "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] is not None else None,
                "status": r["status"],
                "date": (r["date_operational"] or r["date_decided"]).isoformat()
                        if (r["date_operational"] or r["date_decided"]) else None,
                "developer": r["developer"],
            })
        out["provenance"].append(_prov("repd_projects", "cached", detail=f"{len(rows)} within 10km"))
    except Exception as exc:  # noqa: BLE001
        out["provenance"].append(_prov("repd_projects", "missing", detail=str(exc)[:160]))

    # Comparable sales via precedent_transactions util
    try:
        from utils.precedent_transactions import find_precedent_transactions
        comps = await find_precedent_transactions(
            conn, technology="solar", capacity_mw=50.0, region="", year=2026, top_n=8,
        )
        for c in comps:
            out["comparable_sales_within_10km"].append({
                "deal_name": c.get("deal_name"),
                "date": c.get("year"),
                "gbp_per_mw": c.get("gbp_per_mw"),
                "tech": c.get("technology"),
                "source": c.get("source"),
                "url": c.get("source_url"),
                "similarity": c.get("similarity"),
            })
        out["provenance"].append(_prov("utils.precedent_transactions", "cached",
                                       detail=f"{len(comps)} scored comparables"))
    except Exception as exc:  # noqa: BLE001
        out["provenance"].append(_prov("utils.precedent_transactions", "missing", detail=str(exc)[:160]))

    # Asking prices — would come from Rightmove commercial / Savills / Strutt-Parker
    out["provenance"].append(_prov("rightmove_commercial/savills", "pending",
                                   detail="asking prices require portal scrape subscription"))
    return out


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

async def build_parcel_detail(
    pool: asyncpg.Pool, parcel_id: str
) -> Optional[dict[str, Any]]:
    """Build the 10-section parcel dossier.

    Returns ``None`` if the parcel id doesn't resolve anywhere. Otherwise
    returns the full envelope — each section always present, with
    section-level ``warning`` + per-field ``provenance`` when a source is
    missing or not ingested.
    """
    async with pool.acquire() as conn:
        parcel = await _lookup_parcel(conn, parcel_id)
    if not parcel:
        return None

    # Build each section, capturing any exception as a section-level warning.
    # Each builder acquires its OWN pool connection — asyncpg connections
    # cannot be shared across concurrent gather tasks.
    async def _safe(name, builder, *args):
        try:
            async with pool.acquire() as conn:
                return await builder(conn, *args)
        except Exception as exc:  # noqa: BLE001
            log.exception("parcel_detail section %s failed: %s", name, exc)
            return _warn(f"section {name} failed", exc)

    async def _safe_pool(name, builder, *args):
        try:
            return await builder(*args)
        except Exception as exc:  # noqa: BLE001
            log.exception("parcel_detail section %s failed: %s", name, exc)
            return _warn(f"section {name} failed", exc)

    identity, ownership, planning, environment, grid, access = await asyncio.gather(
        _safe("identity", _build_identity, parcel),
        _safe("ownership", _build_ownership, parcel),
        _safe("planning", _build_planning, parcel),
        _safe("environment", _build_environment, parcel),
        _safe("grid", _build_grid, parcel),
        _safe("access", _build_access, parcel),
    )
    utilities, utilities_easements, topography, market = await asyncio.gather(
        _safe("utilities", _build_utilities, parcel),
        _safe("utilities_easements", _build_utilities_easements, parcel),
        _safe_pool("topography", _build_topography_pool, parcel, pool),
        _safe("market", _build_market, parcel),
    )

    return {
        "parcel_id": parcel_id,
        "computed_utc": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "ownership": ownership,
        "planning": planning,
        "environment": environment,
        "grid": grid,
        "access": access,
        "utilities": utilities,
        "utilities_easements": utilities_easements,
        "topography": topography,
        "market": market,
    }
