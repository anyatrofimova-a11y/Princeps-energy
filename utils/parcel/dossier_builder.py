"""ParcelDossier builder — composes the single-page dossier for a parcel.

Runs 10 sub-queries concurrently via ``asyncio.gather`` against the
asyncpg pool. Any sub-query that fails is caught and surfaced as a
``warning`` key on that section — the endpoint NEVER 500s on partial
infra.

Output envelope (``ParcelDossier``)
-----------------------------------
    {
      "inspire_id": "...",
      "source": "db" | "mock",
      "geometry": {...GeoJSON...},
      "area_ha": 21.6,
      "centroid": { "lat": ..., "lon": ... },
      "lpa": "Maldon",
      "parish": "...",
      "county": "Essex",
      "dno_slug": "ukpn",
      "to_slug": "nget-east",
      "hmlr_title_number": "EX123456" | None,
      "hmlr_proprietor": None,          # paid tier — TODO note below
      "hmlr_proprietor_note": "Paid tier — CCOD/OCOD ingestion not wired",
      "charges": [ { "date":"...", "form":"MR01", "lender":"..." }, ... ],
      "epc_certs_within_250m": [ ... up to 50 ... ],
      "planning_history_5y": [ ... ],
      "repd_overlap_projects": [ ... ],
      "constraints": { "aonb": {...}, "sssi": {...}, ... },
      "nearest_poc_substation": { "id":"...","name":"...","voltage":132,
                                   "distance_m":890,"firm_headroom_mw":12.4 },
      "buildable_mask_result": { "buildable_ha":18.2,
                                  "excluded_ha":3.4,
                                  "reason_codes":["flood_z3","aonb_buffer"] },
      "similar_parcels": [ ... top 5 ... ],
      "built_utc": "...",
      "partial": bool,                  # true if any section warned
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from .planning_history import planning_history
from .repd_overlap import repd_overlap
from .similar_parcels import similar_parcels

log = logging.getLogger("princeps.parcel.dossier")


# ---------------------------------------------------------------------------
# Constraint catalogue — the 11 flags the drawer renders
# ---------------------------------------------------------------------------

_CONSTRAINT_TABLES: dict[str, tuple[str, int]] = {
    # flag_key: (postgis table name, distance_m threshold for "near")
    "aonb":             ("designation_aonb",            500),
    "sssi":             ("designation_sssi",            500),
    "ramsar":           ("designation_ramsar",         1000),
    "sac":              ("designation_sac",            1000),
    "spa":              ("designation_spa",            1000),
    "flood_zone_2":     ("env_flood_zone_2",              0),
    "flood_zone_3":     ("env_flood_zone_3",              0),
    "alc_grade_1_2":    ("alc_grades_1_2",                0),
    "ancient_woodland": ("ancient_woodland_inventory",  250),
    "listed_buildings": ("listed_buildings",            500),
    "scheduled_monument": ("scheduled_monuments",       500),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _warning_section(section: str, exc: BaseException | str) -> dict[str, Any]:
    msg = exc if isinstance(exc, str) else f"{type(exc).__name__}: {str(exc)[:160]}"
    log.debug("parcel dossier section %s degraded: %s", section, msg)
    return {"warning": msg[:240], "_partial": True}


async def _safe(name: str, coro):  # noqa: ANN001
    """Await coro; return either the value or a warning dict."""
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001
        return _warning_section(name, exc)


# ---------------------------------------------------------------------------
# Core parcel lookup
# ---------------------------------------------------------------------------


async def _lookup_parcel(
    conn: asyncpg.Connection, inspire_id: str
) -> Optional[dict[str, Any]]:
    try:
        exists = await conn.fetchval(
            "SELECT to_regclass('public.hmlr_inspire_parcels') IS NOT NULL"
        )
    except Exception:  # noqa: BLE001
        return None
    if not exists:
        return None

    try:
        row = await conn.fetchrow(
            """
            SELECT inspire_id::text AS inspire_id,
                   ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geojson,
                   ST_Area(geom)::float AS area_m2,
                   ST_Y(ST_Transform(ST_Centroid(geom), 4326)) AS lat,
                   ST_X(ST_Transform(ST_Centroid(geom), 4326)) AS lon
              FROM hmlr_inspire_parcels
             WHERE inspire_id::text = $1
             LIMIT 1
            """,
            inspire_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("_lookup_parcel failed for %s: %s", inspire_id, exc)
        return None

    if not row:
        return None

    return {
        "inspire_id": row["inspire_id"],
        "geojson": json.loads(row["geojson"]) if row["geojson"] else None,
        "area_m2": float(row["area_m2"]) if row["area_m2"] else None,
        "lat": float(row["lat"]) if row["lat"] is not None else None,
        "lon": float(row["lon"]) if row["lon"] is not None else None,
    }


# ---------------------------------------------------------------------------
# Individual section builders
# ---------------------------------------------------------------------------


async def _admin_lookup(conn: asyncpg.Connection, lat: float, lon: float) -> dict[str, Any]:
    """LPA / parish / county from admin polygons."""
    out: dict[str, Any] = {"lpa": None, "parish": None, "county": None}

    # Try individual admin tables. Each try is isolated.
    async def _hit(table: str, col: str) -> Optional[str]:
        try:
            val = await conn.fetchval(
                f"""
                SELECT {col}
                  FROM {table}
                 WHERE ST_Contains(
                           geom,
                           ST_SetSRID(ST_MakePoint($1, $2), 4326)
                       )
                 LIMIT 1
                """,
                lon,
                lat,
            )
            return val
        except Exception:  # noqa: BLE001
            return None

    out["lpa"] = await _hit("lpa_boundaries", "lpa_name") or await _hit("boundaries_lpa", "name")
    out["parish"] = await _hit("parish_boundaries", "parish_name") or await _hit("boundaries_parish", "name")
    out["county"] = await _hit("county_boundaries", "county_name") or await _hit("boundaries_county", "name")
    return out


async def _dno_to_lookup(conn: asyncpg.Connection, lat: float, lon: float) -> dict[str, Any]:
    """DNO + TO slug from licence-area polygons."""
    out: dict[str, Optional[str]] = {"dno_slug": None, "to_slug": None}

    for table, col, key in [
        ("grid_dno_boundaries", "dno_slug", "dno_slug"),
        ("dno_licence_areas", "slug", "dno_slug"),
        ("dno_boundaries", "slug", "dno_slug"),
    ]:
        try:
            val = await conn.fetchval(
                f"""
                SELECT {col}
                  FROM {table}
                 WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326))
                 LIMIT 1
                """,
                lon,
                lat,
            )
            if val:
                out[key] = val
                break
        except Exception:  # noqa: BLE001
            continue

    for table, col in [
        ("to_licence_areas", "slug"),
        ("nget_boundaries", "zone"),
    ]:
        try:
            val = await conn.fetchval(
                f"""
                SELECT {col}
                  FROM {table}
                 WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326))
                 LIMIT 1
                """,
                lon,
                lat,
            )
            if val:
                out["to_slug"] = val
                break
        except Exception:  # noqa: BLE001
            continue

    return out


async def _hmlr_title_lookup(
    conn: asyncpg.Connection, inspire_id: str
) -> dict[str, Any]:
    try:
        exists = await conn.fetchval(
            "SELECT to_regclass('public.hmlr_title_index') IS NOT NULL"
        )
    except Exception:  # noqa: BLE001
        exists = False

    if not exists:
        return {
            "hmlr_title_number": None,
            "hmlr_proprietor": None,
            "hmlr_proprietor_note": (
                "Paid tier — HMLR CCOD/OCOD ingestion not wired. TODO: hook up "
                "registered-proprietors feed (≈£30/mo) and re-run this query."
            ),
        }

    try:
        row = await conn.fetchrow(
            """
            SELECT title_number, proprietor_name
              FROM hmlr_title_index
             WHERE inspire_id = $1
             LIMIT 1
            """,
            inspire_id,
        )
    except Exception:  # noqa: BLE001
        row = None

    return {
        "hmlr_title_number": row["title_number"] if row else None,
        # Proprietor is the paid tier — keep null unless the column actually exists
        # and is populated.
        "hmlr_proprietor": row["proprietor_name"] if row and row["proprietor_name"] else None,
        "hmlr_proprietor_note": (
            "Paid tier (CCOD/OCOD). Return null unless CCOD ingestion is wired."
        ),
    }


async def _charges_lookup(
    conn: asyncpg.Connection, proprietor_name: Optional[str]
) -> list[dict[str, Any]]:
    if not proprietor_name:
        return []
    try:
        exists = await conn.fetchval(
            "SELECT to_regclass('public.companies_house_charges') IS NOT NULL"
        )
    except Exception:  # noqa: BLE001
        exists = False
    if not exists:
        return []

    try:
        rows = await conn.fetch(
            """
            SELECT filed_date, form_type, lender, status, amount
              FROM companies_house_charges
             WHERE company_name ILIKE $1
               AND form_type IN ('MR01','MR02','MR04','MR05')
             ORDER BY filed_date DESC
             LIMIT 25
            """,
            f"%{proprietor_name}%",
        )
    except Exception:  # noqa: BLE001
        return []

    return [
        {
            "date": r["filed_date"].isoformat() if r["filed_date"] else None,
            "form": r["form_type"],
            "lender": r["lender"],
            "status": r["status"],
            "amount": float(r["amount"]) if r["amount"] is not None else None,
        }
        for r in rows
    ]


async def _epc_within_250m(
    conn: asyncpg.Connection, lat: float, lon: float
) -> list[dict[str, Any]]:
    for table in ("epc_certificates", "epc_domestic", "epc"):
        try:
            exists = await conn.fetchval(
                f"SELECT to_regclass('public.{table}') IS NOT NULL"
            )
        except Exception:  # noqa: BLE001
            exists = False
        if not exists:
            continue

        try:
            rows = await conn.fetch(
                f"""
                SELECT address,
                       current_rating AS rating,
                       property_type,
                       inspection_date,
                       ST_Distance(
                           geom::geography,
                           ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                       ) AS distance_m
                  FROM {table}
                 WHERE ST_DWithin(
                           geom::geography,
                           ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                           250
                       )
                 ORDER BY distance_m ASC
                 LIMIT 50
                """,
                lon,
                lat,
            )
        except Exception:  # noqa: BLE001
            continue

        return [
            {
                "address": r["address"],
                "rating": r["rating"],
                "property_type": r["property_type"],
                "inspection_date": (
                    r["inspection_date"].isoformat() if r["inspection_date"] else None
                ),
                "distance_m": round(float(r["distance_m"]), 1) if r["distance_m"] else None,
            }
            for r in rows
        ]

    return []


async def _constraint_flag(
    conn: asyncpg.Connection,
    key: str,
    table: str,
    near_m: int,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    try:
        exists = await conn.fetchval(
            f"SELECT to_regclass('public.{table}') IS NOT NULL"
        )
    except Exception:  # noqa: BLE001
        exists = False
    if not exists:
        return {"triggered": False, "distance_m": None, "status": "dataset_missing"}

    try:
        row = await conn.fetchrow(
            f"""
            SELECT ST_Distance(
                       geom::geography,
                       ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                   ) AS distance_m
              FROM {table}
             ORDER BY geom <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
             LIMIT 1
            """,
            lon,
            lat,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("constraint %s query failed: %s", key, exc)
        return {"triggered": False, "distance_m": None, "status": "query_failed"}

    if row is None or row["distance_m"] is None:
        return {"triggered": False, "distance_m": None, "status": "no_features"}

    dist = float(row["distance_m"])
    triggered = dist <= near_m
    return {
        "triggered": triggered,
        "distance_m": round(dist, 1),
        "status": "intersects" if dist == 0.0 else ("within_buffer" if triggered else "clear"),
        "threshold_m": near_m,
    }


async def _constraints_section(
    conn: asyncpg.Connection, lat: float, lon: float
) -> dict[str, Any]:
    tasks = {
        key: _constraint_flag(conn, key, table, near_m, lat, lon)
        for key, (table, near_m) in _CONSTRAINT_TABLES.items()
    }
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    out: dict[str, Any] = {}
    for (k, _), r in zip(tasks.items(), results):
        if isinstance(r, Exception):
            out[k] = {"triggered": False, "distance_m": None, "status": "error"}
        else:
            out[k] = r
    return out


async def _nearest_substation(
    conn: asyncpg.Connection, lat: float, lon: float
) -> dict[str, Any]:
    try:
        exists = await conn.fetchval(
            "SELECT to_regclass('public.grid_substations') IS NOT NULL"
        )
    except Exception:  # noqa: BLE001
        exists = False
    if not exists:
        return {
            "id": None,
            "name": None,
            "voltage_kv": None,
            "distance_m": None,
            "firm_headroom_mw": None,
            "status": "dataset_missing",
        }

    try:
        row = await conn.fetchrow(
            """
            SELECT substation_id::text AS id,
                   name,
                   COALESCE(voltage_kv, NULL) AS voltage_kv,
                   COALESCE(firm_headroom_mw, NULL) AS firm_headroom_mw,
                   ST_Distance(
                       geom::geography,
                       ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                   ) AS distance_m
              FROM grid_substations
             ORDER BY geom <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
             LIMIT 1
            """,
            lon,
            lat,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "id": None,
            "name": None,
            "voltage_kv": None,
            "distance_m": None,
            "firm_headroom_mw": None,
            "status": f"query_failed: {type(exc).__name__}",
        }

    if not row:
        return {
            "id": None,
            "name": None,
            "voltage_kv": None,
            "distance_m": None,
            "firm_headroom_mw": None,
            "status": "no_substation_found",
        }

    return {
        "id": row["id"],
        "name": row["name"],
        "voltage_kv": int(row["voltage_kv"]) if row["voltage_kv"] else None,
        "distance_m": round(float(row["distance_m"]), 1) if row["distance_m"] else None,
        "firm_headroom_mw": (
            float(row["firm_headroom_mw"]) if row["firm_headroom_mw"] is not None else None
        ),
        "status": "ok",
    }


async def _buildable_mask_result(
    conn: asyncpg.Connection, inspire_id: str, area_ha: float
) -> dict[str, Any]:
    """Compute buildable_ha after deterministic exclusion masks.

    Preferred source: ``utils.buildable_area`` if it exposes an async
    parcel-level API. Fallback: inline PostGIS joins against the same
    constraint tables used by the constraints section.
    """
    # Inline fallback — works without buildable_area being wired.
    try:
        parcel_row = await conn.fetchrow(
            """
            SELECT geom, ST_Area(geom)::float AS area_m2
              FROM hmlr_inspire_parcels
             WHERE inspire_id::text = $1
             LIMIT 1
            """,
            inspire_id,
        )
    except Exception:  # noqa: BLE001
        parcel_row = None

    if not parcel_row:
        return {
            "buildable_ha": None,
            "excluded_ha": None,
            "buildable_fraction": None,
            "reason_codes": [],
            "status": "parcel_missing",
        }

    # Accumulate union of exclusion polygons, one table at a time.
    exclusion_tables = [
        ("flood_z3",         "env_flood_zone_3"),
        ("alc_grade_1_2",    "alc_grades_1_2"),
        ("aonb",             "designation_aonb"),
        ("sssi",             "designation_sssi"),
        ("ancient_wood",     "ancient_woodland_inventory"),
    ]

    reasons: list[str] = []
    excluded_m2_total = 0.0

    for code, table in exclusion_tables:
        try:
            exists = await conn.fetchval(
                f"SELECT to_regclass('public.{table}') IS NOT NULL"
            )
            if not exists:
                continue
            overlap = await conn.fetchval(
                f"""
                SELECT COALESCE(
                    SUM(
                        ST_Area(ST_Intersection(p.geom, e.geom))
                    ),
                    0
                )::float
                  FROM hmlr_inspire_parcels p,
                       {table} e
                 WHERE p.inspire_id::text = $1
                   AND ST_Intersects(p.geom, e.geom)
                """,
                inspire_id,
            )
            if overlap and overlap > 0:
                excluded_m2_total += float(overlap)
                reasons.append(code)
        except Exception:  # noqa: BLE001
            continue

    total_m2 = float(parcel_row["area_m2"] or 0.0)
    buildable_m2 = max(total_m2 - excluded_m2_total, 0.0)
    frac = (buildable_m2 / total_m2) if total_m2 > 0 else None

    return {
        "buildable_ha": round(buildable_m2 / 10_000.0, 2),
        "excluded_ha": round(excluded_m2_total / 10_000.0, 2),
        "buildable_fraction": round(frac, 3) if frac is not None else None,
        "reason_codes": reasons,
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------


async def build_dossier(
    pool: asyncpg.Pool, inspire_id: str, *, user: Optional[dict] = None
) -> dict[str, Any]:
    """Build a full ParcelDossier. Never raises."""

    async with pool.acquire() as conn:
        parcel = await _lookup_parcel(conn, inspire_id)
        if not parcel:
            return mock_dossier(inspire_id, reason="not_found_in_db")

        lat = parcel["lat"]
        lon = parcel["lon"]
        area_ha = round((parcel["area_m2"] or 0) / 10_000.0, 2)

        # Kick off the 10 sub-queries concurrently.
        admin_t = _safe("admin", _admin_lookup(conn, lat, lon))
        dno_t = _safe("dno", _dno_to_lookup(conn, lat, lon))
        hmlr_t = _safe("hmlr", _hmlr_title_lookup(conn, inspire_id))
        epc_t = _safe("epc", _epc_within_250m(conn, lat, lon))
        planning_t = _safe("planning", planning_history(conn, lat, lon))
        repd_t = _safe("repd", repd_overlap(conn, inspire_id))
        constraints_t = _safe("constraints", _constraints_section(conn, lat, lon))
        substation_t = _safe("substation", _nearest_substation(conn, lat, lon))
        buildable_t = _safe("buildable", _buildable_mask_result(conn, inspire_id, area_ha))
        similar_t = _safe("similar", similar_parcels(conn, inspire_id, top_k=5))

        (
            admin,
            dno_to,
            hmlr,
            epc,
            planning,
            repd,
            constraints,
            substation,
            buildable,
            similar,
        ) = await asyncio.gather(
            admin_t,
            dno_t,
            hmlr_t,
            epc_t,
            planning_t,
            repd_t,
            constraints_t,
            substation_t,
            buildable_t,
            similar_t,
        )

        # Charges depend on proprietor — run last & cheap.
        proprietor = hmlr.get("hmlr_proprietor") if isinstance(hmlr, dict) else None
        charges = await _safe("charges", _charges_lookup(conn, proprietor))

    def _has_warning(section: Any) -> bool:
        return isinstance(section, dict) and section.get("_partial") is True

    partial = any(
        _has_warning(s)
        for s in (
            admin,
            dno_to,
            hmlr,
            epc,
            planning,
            repd,
            constraints,
            substation,
            buildable,
            similar,
            charges,
        )
    )

    return {
        "inspire_id": inspire_id,
        "source": "db",
        "geometry": parcel["geojson"],
        "area_ha": area_ha,
        "centroid": {"lat": lat, "lon": lon},
        "lpa": (admin or {}).get("lpa"),
        "parish": (admin or {}).get("parish"),
        "county": (admin or {}).get("county"),
        "dno_slug": (dno_to or {}).get("dno_slug"),
        "to_slug": (dno_to or {}).get("to_slug"),
        "hmlr_title_number": (hmlr or {}).get("hmlr_title_number"),
        "hmlr_proprietor": (hmlr or {}).get("hmlr_proprietor"),
        "hmlr_proprietor_note": (hmlr or {}).get(
            "hmlr_proprietor_note",
            "Paid tier (CCOD/OCOD). TODO: wire registered-proprietor ingest.",
        ),
        "charges": charges if isinstance(charges, list) else [],
        "epc_certs_within_250m": epc if isinstance(epc, list) else [],
        "planning_history_5y": planning if isinstance(planning, list) else [],
        "repd_overlap_projects": repd if isinstance(repd, list) else [],
        "constraints": constraints if isinstance(constraints, dict) else {},
        "nearest_poc_substation": substation if isinstance(substation, dict) else {},
        "buildable_mask_result": buildable if isinstance(buildable, dict) else {},
        "similar_parcels": similar if isinstance(similar, list) else [],
        "built_utc": _utc_now(),
        "partial": partial,
    }


# ---------------------------------------------------------------------------
# Mock dossier — used when the parcel isn't in the DB or DB is unavailable.
# ---------------------------------------------------------------------------


_MOCK_PARCELS: dict[str, dict[str, Any]] = {
    # Realistic shapes, not real ownership data.
    "GB-INSPIRE-0000000001": {
        "lpa": "Maldon",
        "parish": "Great Totham",
        "county": "Essex",
        "dno_slug": "ukpn",
        "to_slug": "nget-east",
        "centroid": {"lat": 51.757, "lon": 0.717},
        "area_ha": 21.6,
        "hmlr_title_number": "EX345678",
    },
    "GB-INSPIRE-0000000002": {
        "lpa": "North Kesteven",
        "parish": "Branston",
        "county": "Lincolnshire",
        "dno_slug": "nged-eastmids",
        "to_slug": "nget-east",
        "centroid": {"lat": 53.133, "lon": -0.466},
        "area_ha": 38.4,
        "hmlr_title_number": "LL987654",
    },
    "GB-INSPIRE-0000000003": {
        "lpa": "South Oxfordshire",
        "parish": "Didcot",
        "county": "Oxfordshire",
        "dno_slug": "ssen-southern",
        "to_slug": "nget-south",
        "centroid": {"lat": 51.606, "lon": -1.242},
        "area_ha": 14.2,
        "hmlr_title_number": "ON112233",
    },
    "GB-INSPIRE-0000000004": {
        "lpa": "Carmarthenshire",
        "parish": "Llanelli Rural",
        "county": "Carmarthenshire",
        "dno_slug": "nged-swales",
        "to_slug": "sphn-west",
        "centroid": {"lat": 51.694, "lon": -4.160},
        "area_ha": 57.9,
        "hmlr_title_number": "WA556677",
    },
}


def _mock_geom(lat: float, lon: float, area_ha: float) -> dict[str, Any]:
    """Square polygon centred on (lat, lon) matching area_ha."""
    # 1 deg lat ≈ 111_000 m
    side_m = (area_ha * 10_000.0) ** 0.5
    d_lat = side_m / 2.0 / 111_000.0
    d_lon = side_m / 2.0 / (111_000.0 * max(abs(lat) / 90.0 * 0.6 + 0.4, 0.4))
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - d_lon, lat - d_lat],
                [lon + d_lon, lat - d_lat],
                [lon + d_lon, lat + d_lat],
                [lon - d_lon, lat + d_lat],
                [lon - d_lon, lat - d_lat],
            ]
        ],
    }


def mock_dossier(inspire_id: str, *, reason: str = "mock") -> dict[str, Any]:
    """Return a synthetic but realistic dossier (used as fallback & in tests)."""

    base = _MOCK_PARCELS.get(inspire_id) or _MOCK_PARCELS["GB-INSPIRE-0000000001"]
    lat = base["centroid"]["lat"]
    lon = base["centroid"]["lon"]
    area_ha = base["area_ha"]

    return {
        "inspire_id": inspire_id,
        "source": "mock",
        "mock_reason": reason,
        "geometry": _mock_geom(lat, lon, area_ha),
        "area_ha": area_ha,
        "centroid": base["centroid"],
        "lpa": base["lpa"],
        "parish": base["parish"],
        "county": base["county"],
        "dno_slug": base["dno_slug"],
        "to_slug": base["to_slug"],
        "hmlr_title_number": base["hmlr_title_number"],
        "hmlr_proprietor": None,
        "hmlr_proprietor_note": (
            "Paid tier (CCOD/OCOD). TODO: wire registered-proprietor ingest."
        ),
        "charges": [
            {
                "date": "2022-11-14",
                "form": "MR01",
                "lender": "Lloyds Bank plc",
                "status": "outstanding",
                "amount": None,
            }
        ],
        "epc_certs_within_250m": [
            {"address": "Farm Cottage", "rating": "D", "property_type": "Dwelling",
             "inspection_date": "2023-04-10", "distance_m": 134.2},
            {"address": "The Old Barn", "rating": "E", "property_type": "Dwelling",
             "inspection_date": "2021-09-27", "distance_m": 212.7},
        ],
        "planning_history_5y": [
            {
                "ref": "24/00412/FUL",
                "address": "Land adjacent to the parcel",
                "description": "Erection of 18 MW solar PV array with BESS",
                "status": "pending",
                "decision_date": None,
                "officer_report_url": "https://planning.example.gov.uk/24-00412-FUL",
                "distance_m": 340.5,
                "applicant": "Greenfield Energy Ltd",
                "source": "mock",
            }
        ],
        "repd_overlap_projects": [
            {
                "ref_id": "REPD-2019-0456",
                "site_name": "Park Farm Solar",
                "technology": "Solar Photovoltaics",
                "capacity_mw": 22.0,
                "status": "Application Refused",
                "operator": "Park Farm Energy",
                "planning_authority": base["lpa"],
                "decision_date": "2020-06-18",
                "overlap_ha": 3.2,
                "distance_m": 0.0,
            }
        ],
        "constraints": {
            "aonb":              {"triggered": False, "distance_m": 4820, "status": "clear"},
            "sssi":              {"triggered": False, "distance_m": 1350, "status": "clear"},
            "ramsar":            {"triggered": False, "distance_m": 7600, "status": "clear"},
            "sac":               {"triggered": False, "distance_m": 5200, "status": "clear"},
            "spa":               {"triggered": False, "distance_m": 4800, "status": "clear"},
            "flood_zone_2":      {"triggered": True,  "distance_m": 0,    "status": "intersects"},
            "flood_zone_3":      {"triggered": False, "distance_m": 210,  "status": "clear"},
            "alc_grade_1_2":     {"triggered": True,  "distance_m": 0,    "status": "intersects"},
            "ancient_woodland":  {"triggered": False, "distance_m": 410,  "status": "clear"},
            "listed_buildings":  {"triggered": False, "distance_m": 630,  "status": "clear"},
            "scheduled_monument":{"triggered": False, "distance_m": 2200, "status": "clear"},
        },
        "nearest_poc_substation": {
            "id": "SUB-MALDON-132",
            "name": "Maldon 132kV",
            "voltage_kv": 132,
            "distance_m": 890,
            "firm_headroom_mw": 12.4,
            "status": "ok",
        },
        "buildable_mask_result": {
            "buildable_ha": round(area_ha * 0.76, 2),
            "excluded_ha": round(area_ha * 0.24, 2),
            "buildable_fraction": 0.76,
            "reason_codes": ["flood_z3", "alc_grade_1_2"],
            "status": "ok",
        },
        "similar_parcels": [
            {
                "parcel_id": "GB-INSPIRE-MOCK-S1",
                "inspire_id": "GB-INSPIRE-MOCK-S1",
                "area_ha": round(area_ha * 0.92, 2),
                "lpa": base["lpa"],
                "dno_slug": base["dno_slug"],
                "resource_score": 0.81,
                "grid_score": 0.77,
                "planning_score": 0.64,
                "centroid_lat": lat + 0.04,
                "centroid_lon": lon - 0.05,
                "cosine_distance": 0.118,
                "provenance": "mock",
            },
            {
                "parcel_id": "GB-INSPIRE-MOCK-S2",
                "inspire_id": "GB-INSPIRE-MOCK-S2",
                "area_ha": round(area_ha * 1.08, 2),
                "lpa": base["lpa"],
                "dno_slug": base["dno_slug"],
                "resource_score": 0.78,
                "grid_score": 0.82,
                "planning_score": 0.71,
                "centroid_lat": lat - 0.03,
                "centroid_lon": lon + 0.07,
                "cosine_distance": 0.142,
                "provenance": "mock",
            },
            {
                "parcel_id": "GB-INSPIRE-MOCK-S3",
                "inspire_id": "GB-INSPIRE-MOCK-S3",
                "area_ha": round(area_ha * 0.84, 2),
                "lpa": base["lpa"],
                "dno_slug": base["dno_slug"],
                "resource_score": 0.74,
                "grid_score": 0.68,
                "planning_score": 0.58,
                "centroid_lat": lat + 0.06,
                "centroid_lon": lon + 0.03,
                "cosine_distance": 0.171,
                "provenance": "mock",
            },
            {
                "parcel_id": "GB-INSPIRE-MOCK-S4",
                "inspire_id": "GB-INSPIRE-MOCK-S4",
                "area_ha": round(area_ha * 1.14, 2),
                "lpa": base["lpa"],
                "dno_slug": base["dno_slug"],
                "resource_score": 0.85,
                "grid_score": 0.60,
                "planning_score": 0.74,
                "centroid_lat": lat - 0.08,
                "centroid_lon": lon + 0.01,
                "cosine_distance": 0.194,
                "provenance": "mock",
            },
            {
                "parcel_id": "GB-INSPIRE-MOCK-S5",
                "inspire_id": "GB-INSPIRE-MOCK-S5",
                "area_ha": round(area_ha * 0.98, 2),
                "lpa": base["lpa"],
                "dno_slug": base["dno_slug"],
                "resource_score": 0.79,
                "grid_score": 0.73,
                "planning_score": 0.62,
                "centroid_lat": lat + 0.11,
                "centroid_lon": lon - 0.02,
                "cosine_distance": 0.221,
                "provenance": "mock",
            },
        ],
        "built_utc": _utc_now(),
        "partial": False,
    }
