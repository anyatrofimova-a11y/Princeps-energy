"""Substation Tracker pipeline — fetch → parse → resolve → persist.

End-to-end orchestrator that ties together:
  * `ltds_excel_parser` (6 DNOs — UKPN wired, others stubbed)
  * `riio_cv_extractor` (9 licensees — scaffold only, no sample data yet)
  * `noa_ingester` (NESO NOA + CSNP — scaffold with CKAN fetch)
  * `entity_resolver` (rapidfuzz + geo clustering)

Writes to the shared `data_subscriptions` / `data_subscription_rows` tables.
These are shipped by a separate schema-agent — we import its Pydantic model
if available (`app.models.intelligence.DataSubscription`, .DataSubscriptionRow)
and otherwise scaffold against the documented spec.

Spec we're compiling against (from Phase 7a data_subscriptions task)
-------------------------------------------------------------------
CREATE TABLE data_subscriptions (
    id UUID PRIMARY KEY,
    product_name TEXT NOT NULL,        -- 'substation_tracker'
    product_version TEXT NOT NULL,     -- 'v1', 'v1.1', ...
    source_types TEXT[],               -- ['LTDS', 'NOA', ...]
    last_refreshed TIMESTAMPTZ,
    row_count INTEGER,
    refresh_cadence TEXT,              -- 'monthly', 'annual'
    metadata JSONB
);

CREATE TABLE data_subscription_rows (
    id UUID PRIMARY KEY,
    subscription_id UUID REFERENCES data_subscriptions(id) ON DELETE CASCADE,
    row_key TEXT NOT NULL,             -- our SubstationProject.project_id
    row_data JSONB NOT NULL,           -- full 30-field record
    confidence REAL,
    sme_reviewed BOOLEAN DEFAULT false,
    geom GEOMETRY(POINT, 27700),       -- for PostGIS map queries
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (subscription_id, row_key)
);
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import asyncpg

from .schema import SubstationProject
from .entity_resolver import EntityResolver, ResolvedMatch

log = logging.getLogger("princeps.substation_tracker.pipeline")


# ---------------------------------------------------------------------------
# Subscription model import (with scaffold fallback)
# ---------------------------------------------------------------------------
try:
    # Other agent ships this module; we import if present.
    from app.models.intelligence import (  # type: ignore
        DataSubscription,
        DataSubscriptionRow,
    )
    _SUBSCRIPTION_MODELS_AVAILABLE = True
except Exception:  # pragma: no cover - scaffold path
    _SUBSCRIPTION_MODELS_AVAILABLE = False
    log.warning(
        "app.models.intelligence.DataSubscription not yet shipped — "
        "pipeline will write rows using inline dict schema; update this "
        "import when the schema agent ships its module."
    )


PRODUCT_NAME = "substation_tracker"
PRODUCT_VERSION = "v1"
REFRESH_CADENCE = "monthly"


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------
async def run_pipeline(
    pool: asyncpg.Pool,
    *,
    include_ukpn: bool = True,
    include_riio: bool = False,        # RIIO is scaffold-only, default off
    include_noa: bool = False,         # NOA is scaffold-only, default off
    ltds_download_dir: Path = Path("/Users/anyatrofimova/Downloads/ltds"),
    riio_download_dir: Path = Path("/Users/anyatrofimova/Downloads/riio"),
    noa_download_dir: Path = Path("/Users/anyatrofimova/Downloads/noa"),
) -> dict[str, Any]:
    """Run the full fetch → parse → resolve → persist pipeline.

    Returns a summary dict the router can surface to the admin UI.
    """
    await ensure_subscription_schema(pool)

    all_records: list[SubstationProject] = []
    per_source: dict[str, int] = {}
    errors: list[dict[str, str]] = []

    # ----- LTDS Excel ----------------------------------------------------
    if include_ukpn:
        try:
            from .ltds_excel_parser import fetch_ukpn_ods_records, parse_ukpn_workbook
            ukpn_records = await fetch_ukpn_ods_records()
            ukpn_projects = parse_ukpn_workbook(records=ukpn_records)
            all_records.extend(ukpn_projects)
            per_source["UKPN_LTDS"] = len(ukpn_projects)
        except Exception as exc:
            log.exception("UKPN LTDS fetch failed")
            errors.append({"stage": "ltds_ukpn", "error": str(exc)})

        # Other DNOs — scan for local workbooks and dispatch.
        try:
            from .ltds_excel_parser import DNO_DISPATCHERS
            for dno, fn in DNO_DISPATCHERS.items():
                if dno == "UKPN":
                    continue
                pattern = f"*{dno.lower()}*.xlsx"
                for path in ltds_download_dir.glob(pattern):
                    try:
                        rows = fn(path=path)
                        all_records.extend(rows)
                        per_source[f"{dno}_LTDS"] = per_source.get(f"{dno}_LTDS", 0) + len(rows)
                    except Exception as exc:
                        errors.append({"stage": f"ltds_{dno}", "error": str(exc)})
        except Exception as exc:
            errors.append({"stage": "ltds_dispatch", "error": str(exc)})

    # ----- RIIO CV -------------------------------------------------------
    if include_riio:
        try:
            from .riio_cv_extractor import extract_from_riio_cv
            for path in riio_download_dir.glob("*.xlsx"):
                developer = _infer_developer_from_filename(path.name)
                rows = extract_from_riio_cv(path, developer=developer)
                all_records.extend(rows)
                per_source[f"{developer}_RIIO_CV"] = per_source.get(f"{developer}_RIIO_CV", 0) + len(rows)
        except Exception as exc:
            errors.append({"stage": "riio_cv", "error": str(exc)})

    # ----- NESO NOA / CSNP ----------------------------------------------
    if include_noa:
        try:
            from .noa_ingester import ingest_noa
            noa_records = await ingest_noa(download_dir=noa_download_dir)
            all_records.extend(noa_records)
            per_source["NESO_NOA_CSNP"] = len(noa_records)
        except Exception as exc:
            errors.append({"stage": "noa", "error": str(exc)})

    # ----- Resolve --------------------------------------------------------
    resolver = EntityResolver()
    await resolver.hydrate_from_pool(pool, (r.substation_name for r in all_records))
    matches: list[ResolvedMatch] = resolver.resolve(all_records)

    # ----- Persist --------------------------------------------------------
    sub_id = await upsert_subscription(
        pool,
        source_types=sorted({r.source_type for r in all_records}),
        row_count=len(matches),
    )
    row_count = await upsert_rows(pool, sub_id, matches)

    summary = {
        "ok": True,
        "subscription_id": str(sub_id),
        "product": f"{PRODUCT_NAME}:{PRODUCT_VERSION}",
        "records_ingested": len(all_records),
        "canonical_rows": len(matches),
        "rows_written": row_count,
        "per_source": per_source,
        "errors": errors,
        "last_refreshed": datetime.utcnow().isoformat() + "Z",
    }
    log.info("Substation Tracker pipeline complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Subscription schema
# ---------------------------------------------------------------------------
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS data_subscriptions (
    id UUID PRIMARY KEY,
    product_name TEXT NOT NULL,
    product_version TEXT NOT NULL,
    source_types TEXT[],
    last_refreshed TIMESTAMPTZ,
    row_count INTEGER,
    refresh_cadence TEXT,
    metadata JSONB,
    UNIQUE (product_name, product_version)
);

CREATE TABLE IF NOT EXISTS data_subscription_rows (
    id UUID PRIMARY KEY,
    subscription_id UUID NOT NULL REFERENCES data_subscriptions(id) ON DELETE CASCADE,
    row_key TEXT NOT NULL,
    row_data JSONB NOT NULL,
    confidence REAL,
    sme_reviewed BOOLEAN DEFAULT false,
    geom GEOMETRY(POINT, 27700),
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (subscription_id, row_key)
);

CREATE INDEX IF NOT EXISTS idx_data_subscription_rows_subscription
    ON data_subscription_rows (subscription_id);
CREATE INDEX IF NOT EXISTS idx_data_subscription_rows_row_data
    ON data_subscription_rows USING GIN (row_data);
CREATE INDEX IF NOT EXISTS idx_data_subscription_rows_geom
    ON data_subscription_rows USING GIST (geom);
"""


async def ensure_subscription_schema(pool: asyncpg.Pool) -> None:
    """Create the data_subscriptions tables if they don't exist.

    This is a defensive scaffold — the `app.db_setup` agent is shipping the
    canonical migration, but we want the pipeline to succeed standalone.
    """
    async with pool.acquire() as conn:
        for stmt in _SCHEMA_SQL.split(";"):
            s = stmt.strip()
            if s:
                try:
                    await conn.execute(s)
                except asyncpg.exceptions.PostgresError as exc:
                    # PostGIS geometry type may not be installed — degrade.
                    log.warning("schema statement skipped: %s (%s)", s[:60], exc)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
async def upsert_subscription(
    pool: asyncpg.Pool,
    *,
    source_types: list[str],
    row_count: int,
) -> uuid.UUID:
    """Insert or update the subscription row for this product/version."""
    sub_id = uuid.uuid4()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM data_subscriptions WHERE product_name = $1 AND product_version = $2",
            PRODUCT_NAME, PRODUCT_VERSION,
        )
        if existing:
            sub_id = existing["id"]
            await conn.execute(
                """
                UPDATE data_subscriptions
                SET source_types = $2,
                    last_refreshed = NOW(),
                    row_count = $3,
                    refresh_cadence = $4
                WHERE id = $1
                """,
                sub_id, source_types, row_count, REFRESH_CADENCE,
            )
        else:
            await conn.execute(
                """
                INSERT INTO data_subscriptions
                    (id, product_name, product_version, source_types,
                     last_refreshed, row_count, refresh_cadence, metadata)
                VALUES ($1, $2, $3, $4, NOW(), $5, $6, $7)
                """,
                sub_id, PRODUCT_NAME, PRODUCT_VERSION, source_types,
                row_count, REFRESH_CADENCE,
                json.dumps({"canonical_parity": True, "fields": 30}),
            )
    return sub_id


async def upsert_rows(
    pool: asyncpg.Pool,
    subscription_id: uuid.UUID,
    matches: Iterable[ResolvedMatch],
) -> int:
    """Upsert one row per canonical ResolvedMatch."""
    count = 0
    async with pool.acquire() as conn:
        for match in matches:
            row_data = match.canonical.model_dump(mode="json")
            # Attach the member count + source types for downstream filtering.
            row_data["_members"] = [m.source_type for m in match.members]
            row_data["_member_ids"] = [m.project_id for m in match.members]
            row_data["_match_reasons"] = match.match_reasons

            # Geometry — prefer canonical's OSGB, else convert from WGS84 WKT.
            east = match.canonical.osgb_easting
            north = match.canonical.osgb_northing
            wkt = match.canonical.geom_wkt

            try:
                if east is not None and north is not None:
                    await conn.execute(
                        """
                        INSERT INTO data_subscription_rows
                            (id, subscription_id, row_key, row_data, confidence,
                             sme_reviewed, geom, last_updated)
                        VALUES ($1, $2, $3, $4::jsonb, $5, $6,
                                ST_SetSRID(ST_MakePoint($7, $8), 27700), NOW())
                        ON CONFLICT (subscription_id, row_key) DO UPDATE SET
                            row_data = EXCLUDED.row_data,
                            confidence = EXCLUDED.confidence,
                            sme_reviewed = EXCLUDED.sme_reviewed,
                            geom = EXCLUDED.geom,
                            last_updated = NOW()
                        """,
                        uuid.uuid4(), subscription_id, match.project_id,
                        json.dumps(row_data),
                        match.confidence, match.canonical.sme_reviewed,
                        east, north,
                    )
                elif wkt:
                    await conn.execute(
                        """
                        INSERT INTO data_subscription_rows
                            (id, subscription_id, row_key, row_data, confidence,
                             sme_reviewed, geom, last_updated)
                        VALUES ($1, $2, $3, $4::jsonb, $5, $6,
                                ST_Transform(ST_GeomFromText($7, 4326), 27700), NOW())
                        ON CONFLICT (subscription_id, row_key) DO UPDATE SET
                            row_data = EXCLUDED.row_data,
                            confidence = EXCLUDED.confidence,
                            sme_reviewed = EXCLUDED.sme_reviewed,
                            geom = EXCLUDED.geom,
                            last_updated = NOW()
                        """,
                        uuid.uuid4(), subscription_id, match.project_id,
                        json.dumps(row_data),
                        match.confidence, match.canonical.sme_reviewed,
                        wkt,
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO data_subscription_rows
                            (id, subscription_id, row_key, row_data, confidence,
                             sme_reviewed, last_updated)
                        VALUES ($1, $2, $3, $4::jsonb, $5, $6, NOW())
                        ON CONFLICT (subscription_id, row_key) DO UPDATE SET
                            row_data = EXCLUDED.row_data,
                            confidence = EXCLUDED.confidence,
                            sme_reviewed = EXCLUDED.sme_reviewed,
                            last_updated = NOW()
                        """,
                        uuid.uuid4(), subscription_id, match.project_id,
                        json.dumps(row_data),
                        match.confidence, match.canonical.sme_reviewed,
                    )
                count += 1
            except Exception as exc:
                log.warning("row upsert failed for %s: %s", match.project_id, exc)
    return count


# ---------------------------------------------------------------------------
# Read helpers consumed by the router
# ---------------------------------------------------------------------------
async def get_active_subscription_id(pool: asyncpg.Pool) -> uuid.UUID | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM data_subscriptions "
            "WHERE product_name = $1 AND product_version = $2",
            PRODUCT_NAME, PRODUCT_VERSION,
        )
    return row["id"] if row else None


async def list_rows(
    pool: asyncpg.Pool,
    *,
    region: str | None = None,
    voltage_kv: float | None = None,
    status: str | None = None,
    developer: str | None = None,
    year: int | None = None,
    limit: int = 1000,
) -> list[dict]:
    """Filtered list query over data_subscription_rows."""
    sub_id = await get_active_subscription_id(pool)
    if not sub_id:
        return []

    clauses = ["subscription_id = $1"]
    params: list[Any] = [sub_id]

    def _p(val):
        params.append(val)
        return f"${len(params)}"

    if region:
        clauses.append(f"row_data->>'region' ILIKE {_p(f'%{region}%')}")
    if developer:
        clauses.append(f"row_data->>'developer' = {_p(developer.upper())}")
    if status:
        clauses.append(f"row_data->>'construction_status' = {_p(status)}")
    if voltage_kv is not None:
        clauses.append(f"(row_data->>'voltage_kv_primary')::float = {_p(voltage_kv)}")
    if year is not None:
        clauses.append(
            f"((row_data->>'operation_year')::int = {_p(year)} "
            f"OR (row_data->>'construction_year')::int = ${len(params)})"
        )

    sql = f"""
        SELECT row_key, row_data, confidence, sme_reviewed, last_updated,
               CASE WHEN geom IS NOT NULL THEN ST_X(ST_Transform(geom, 4326)) END AS lon,
               CASE WHEN geom IS NOT NULL THEN ST_Y(ST_Transform(geom, 4326)) END AS lat
        FROM data_subscription_rows
        WHERE {' AND '.join(clauses)}
        ORDER BY confidence DESC NULLS LAST
        LIMIT {int(limit)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    out = []
    for r in rows:
        d = dict(r)
        rd = d.pop("row_data")
        if isinstance(rd, str):
            rd = json.loads(rd)
        d["row_data"] = rd
        out.append(d)
    return out


async def get_row(pool: asyncpg.Pool, project_id: str) -> dict | None:
    sub_id = await get_active_subscription_id(pool)
    if not sub_id:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT row_key, row_data, confidence, sme_reviewed, last_updated,
                   CASE WHEN geom IS NOT NULL THEN ST_X(ST_Transform(geom, 4326)) END AS lon,
                   CASE WHEN geom IS NOT NULL THEN ST_Y(ST_Transform(geom, 4326)) END AS lat
            FROM data_subscription_rows
            WHERE subscription_id = $1 AND row_key = $2
            """,
            sub_id, project_id,
        )
    if not row:
        return None
    d = dict(row)
    rd = d.pop("row_data")
    if isinstance(rd, str):
        rd = json.loads(rd)
    d["row_data"] = rd
    return d


async def get_geojson(pool: asyncpg.Pool, **filters) -> dict:
    rows = await list_rows(pool, limit=filters.pop("limit", 5000), **filters)
    features = []
    for r in rows:
        if r.get("lat") is None or r.get("lon") is None:
            continue
        rd = r["row_data"]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "project_id": r["row_key"],
                "name": rd.get("substation_name"),
                "developer": rd.get("developer"),
                "region": rd.get("region"),
                "voltage_kv_primary": rd.get("voltage_kv_primary"),
                "construction_status": rd.get("construction_status"),
                "operation_year": rd.get("operation_year"),
                "capex_gbp_millions": rd.get("capex_gbp_millions"),
                "confidence": r.get("confidence"),
                "source_type": rd.get("source_type"),
            },
        })
    return {"type": "FeatureCollection", "features": features, "count": len(features)}


async def get_stats(pool: asyncpg.Pool) -> dict:
    sub_id = await get_active_subscription_id(pool)
    if not sub_id:
        return {"total": 0, "by_region": [], "by_voltage": [], "by_status": []}

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM data_subscription_rows WHERE subscription_id = $1",
            sub_id,
        )
        by_region = await conn.fetch(
            """
            SELECT row_data->>'region' AS region, COUNT(*) AS n
            FROM data_subscription_rows
            WHERE subscription_id = $1
            GROUP BY row_data->>'region'
            ORDER BY n DESC
            """,
            sub_id,
        )
        by_voltage = await conn.fetch(
            """
            SELECT (row_data->>'voltage_kv_primary')::float AS voltage_kv, COUNT(*) AS n
            FROM data_subscription_rows
            WHERE subscription_id = $1 AND row_data->>'voltage_kv_primary' IS NOT NULL
            GROUP BY voltage_kv
            ORDER BY voltage_kv DESC
            """,
            sub_id,
        )
        by_status = await conn.fetch(
            """
            SELECT row_data->>'construction_status' AS status, COUNT(*) AS n
            FROM data_subscription_rows
            WHERE subscription_id = $1
            GROUP BY status
            ORDER BY n DESC
            """,
            sub_id,
        )
        by_developer = await conn.fetch(
            """
            SELECT row_data->>'developer' AS developer, COUNT(*) AS n
            FROM data_subscription_rows
            WHERE subscription_id = $1
            GROUP BY developer
            ORDER BY n DESC
            """,
            sub_id,
        )
    return {
        "total": int(total or 0),
        "by_region":    [dict(r) for r in by_region],
        "by_voltage":   [dict(r) for r in by_voltage],
        "by_status":    [dict(r) for r in by_status],
        "by_developer": [dict(r) for r in by_developer],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_FN_DEV_RE = re.compile(r"(nget|spt|she-?t|ukpn|ssen|spen|nged|npg|enwl)", re.I)


def _infer_developer_from_filename(name: str) -> str:
    m = _FN_DEV_RE.search(name)
    return m.group(0).upper().replace("SHET", "SHE-T") if m else "NGET"
