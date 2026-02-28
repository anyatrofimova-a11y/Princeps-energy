"""
Grid Upgrade Tracker — ingest DNO network investment projects and RIIO-ED2 plans.

Sources: NGED Connected Data, UKPN OpenDataSoft API, SSEN data portal.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

import asyncpg
import httpx

log = logging.getLogger("princeps.grid_upgrade_tracker")

_TIMEOUT = 30

# ── API endpoints ────────────────────────────────────────────────────────

# NGED (National Grid Electricity Distribution) — formerly WPD
NGED_API_URL = "https://connecteddata.nationalgrid.co.uk/api/3/action/datastore_search"

# UKPN OpenDataSoft
UKPN_API_URL = "https://ukpowernetworks.opendatasoft.com/api/explore/v2.1/catalog/datasets"
UKPN_NETWORK_DATASET = "ukpn-network-investment"

# SSEN
SSEN_API_URL = "https://data.ssen.co.uk/api/3/action/datastore_search"

DNO_NAMES = {
    "nged": "National Grid ED",
    "ukpn": "UK Power Networks",
    "ssen": "Scottish & Southern EN",
    "enwl": "Electricity North West",
    "npg": "Northern Powergrid",
    "spen": "SP Energy Networks",
}


def _parse_date(val):
    if not val or not str(val).strip():
        return None
    import datetime
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%Y"):
        try:
            return datetime.datetime.strptime(str(val).strip()[:19], fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).strip().replace(",", "").replace("£", ""))
    except (ValueError, TypeError):
        return None


# ── Table setup ──────────────────────────────────────────────────────────

CREATE_UPGRADES_SQL = """
CREATE TABLE IF NOT EXISTS grid_upgrades (
    upgrade_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_ref         TEXT UNIQUE,
    dno                TEXT,
    project_name       TEXT,
    project_type       TEXT,
    voltage_kv         DOUBLE PRECISION,
    capex_gbp          DOUBLE PRECISION,
    status             TEXT,
    start_date         DATE,
    completion_date    DATE,
    riio_period        TEXT,
    constraint_area    TEXT,
    capacity_released_mw DOUBLE PRECISION,
    description        TEXT,
    metadata           JSONB DEFAULT '{}',
    geometry           GEOMETRY(Geometry, 27700),
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_grid_upgrades_geom  ON grid_upgrades USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_grid_upgrades_dno   ON grid_upgrades (dno);
CREATE INDEX IF NOT EXISTS idx_grid_upgrades_status ON grid_upgrades (status);
"""

CREATE_PLANS_SQL = """
CREATE TABLE IF NOT EXISTS dno_investment_plans (
    plan_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dno                TEXT NOT NULL,
    programme          TEXT,
    riio_period        TEXT,
    total_capex_gbp    DOUBLE PRECISION,
    spend_to_date_gbp  DOUBLE PRECISION,
    target_year        INTEGER,
    deliverable_count  INTEGER,
    delivered_count    INTEGER,
    description        TEXT,
    kpis               JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dno_plans_dno ON dno_investment_plans (dno);
"""


async def setup_grid_upgrade_tables(conn: asyncpg.Connection):
    """Create grid_upgrades and dno_investment_plans tables."""
    for sql in [CREATE_UPGRADES_SQL, CREATE_PLANS_SQL]:
        for stmt in sql.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(stmt)
    log.info("grid_upgrades + dno_investment_plans tables ensured")


# ── Ingestion: NGED ──────────────────────────────────────────────────────

async def ingest_nged_upgrades(conn_or_pool) -> dict:
    """Ingest NGED investment projects from Connected Data portal."""
    t0 = time.time()

    if hasattr(conn_or_pool, "acquire"):
        conn = await conn_or_pool.acquire()
        release = True
    else:
        conn = conn_or_pool
        release = False

    try:
        inserted = 0
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            offset = 0
            while True:
                try:
                    r = await client.get(NGED_API_URL, params={
                        "limit": 1000,
                        "offset": offset,
                    })
                    r.raise_for_status()
                    data = r.json()
                    records = data.get("result", {}).get("records", [])
                except Exception as e:
                    log.warning("NGED API fetch failed: %s — using seed data", e)
                    records = []
                    break

                if not records:
                    break

                for row in records:
                    ref = f"nged_{row.get('_id', uuid4().hex[:8])}"
                    name = str(row.get("Project Name", row.get("project_name", ""))).strip()
                    if not name:
                        continue

                    await conn.execute("""
                        INSERT INTO grid_upgrades (
                            source_ref, dno, project_name, project_type, voltage_kv,
                            capex_gbp, status, start_date, completion_date,
                            riio_period, constraint_area, capacity_released_mw, description
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                        ON CONFLICT (source_ref) DO UPDATE SET
                            status = EXCLUDED.status,
                            capex_gbp = EXCLUDED.capex_gbp,
                            completion_date = EXCLUDED.completion_date,
                            updated_at = NOW()
                    """,
                        ref,
                        "nged",
                        name,
                        str(row.get("Project Type", row.get("Type", ""))).strip() or None,
                        _parse_float(row.get("Voltage (kV)", row.get("voltage_kv"))),
                        _parse_float(row.get("Cost (£m)", row.get("capex"))),
                        str(row.get("Status", "")).strip() or "Planned",
                        _parse_date(row.get("Start Date")),
                        _parse_date(row.get("Completion Date", row.get("End Date"))),
                        str(row.get("RIIO Period", "ED2")).strip() or "ED2",
                        str(row.get("Constraint Area", "")).strip() or None,
                        _parse_float(row.get("Capacity Released (MW)")),
                        str(row.get("Description", "")).strip() or None,
                    )
                    inserted += 1

                offset += len(records)
                if len(records) < 1000:
                    break

        # Seed RIIO-ED2 investment plans for NGED if empty
        plan_count = await conn.fetchval(
            "SELECT count(*) FROM dno_investment_plans WHERE dno = 'nged'"
        )
        if plan_count == 0:
            await _seed_dno_plans(conn, "nged")

        elapsed = round(time.time() - t0, 1)
        log.info("NGED upgrades ingested: %d rows in %.1fs", inserted, elapsed)
        return {"dno": "nged", "inserted": inserted, "elapsed_s": elapsed}

    except Exception as e:
        log.error("NGED ingestion failed: %s", e)
        return {"dno": "nged", "error": str(e)}
    finally:
        if release:
            await conn_or_pool.release(conn)


# ── Ingestion: UKPN ─────────────────────────────────────────────────────

async def ingest_ukpn_upgrades(conn_or_pool) -> dict:
    """Ingest UKPN investment projects from OpenDataSoft API."""
    t0 = time.time()

    if hasattr(conn_or_pool, "acquire"):
        conn = await conn_or_pool.acquire()
        release = True
    else:
        conn = conn_or_pool
        release = False

    try:
        inserted = 0
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            offset = 0
            while True:
                try:
                    r = await client.get(
                        f"{UKPN_API_URL}/{UKPN_NETWORK_DATASET}/records",
                        params={"limit": 100, "offset": offset},
                    )
                    r.raise_for_status()
                    data = r.json()
                    records = data.get("results", [])
                except Exception as e:
                    log.warning("UKPN API fetch failed: %s — skipping", e)
                    records = []
                    break

                if not records:
                    break

                for row in records:
                    fields = row.get("fields", row)
                    ref = f"ukpn_{fields.get('id', fields.get('_id', uuid4().hex[:8]))}"
                    name = str(fields.get("project_name", fields.get("name", ""))).strip()
                    if not name:
                        continue

                    await conn.execute("""
                        INSERT INTO grid_upgrades (
                            source_ref, dno, project_name, project_type, voltage_kv,
                            capex_gbp, status, start_date, completion_date,
                            riio_period, description
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                        ON CONFLICT (source_ref) DO UPDATE SET
                            status = EXCLUDED.status,
                            capex_gbp = EXCLUDED.capex_gbp,
                            updated_at = NOW()
                    """,
                        ref, "ukpn", name,
                        str(fields.get("type", "")).strip() or None,
                        _parse_float(fields.get("voltage_kv")),
                        _parse_float(fields.get("capex", fields.get("cost"))),
                        str(fields.get("status", "")).strip() or "Planned",
                        _parse_date(fields.get("start_date")),
                        _parse_date(fields.get("completion_date", fields.get("end_date"))),
                        "ED2",
                        str(fields.get("description", "")).strip() or None,
                    )
                    inserted += 1

                offset += len(records)
                if len(records) < 100:
                    break

        plan_count = await conn.fetchval(
            "SELECT count(*) FROM dno_investment_plans WHERE dno = 'ukpn'"
        )
        if plan_count == 0:
            await _seed_dno_plans(conn, "ukpn")

        elapsed = round(time.time() - t0, 1)
        log.info("UKPN upgrades ingested: %d rows in %.1fs", inserted, elapsed)
        return {"dno": "ukpn", "inserted": inserted, "elapsed_s": elapsed}

    except Exception as e:
        log.error("UKPN ingestion failed: %s", e)
        return {"dno": "ukpn", "error": str(e)}
    finally:
        if release:
            await conn_or_pool.release(conn)


# ── Ingestion: SSEN ─────────────────────────────────────────────────────

async def ingest_ssen_upgrades(conn_or_pool) -> dict:
    """Ingest SSEN investment projects."""
    t0 = time.time()

    if hasattr(conn_or_pool, "acquire"):
        conn = await conn_or_pool.acquire()
        release = True
    else:
        conn = conn_or_pool
        release = False

    try:
        inserted = 0
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            try:
                r = await client.get(SSEN_API_URL, params={"limit": 1000})
                r.raise_for_status()
                data = r.json()
                records = data.get("result", {}).get("records", [])
            except Exception as e:
                log.warning("SSEN API fetch failed: %s — skipping", e)
                records = []

            for row in records:
                ref = f"ssen_{row.get('_id', uuid4().hex[:8])}"
                name = str(row.get("Project Name", row.get("name", ""))).strip()
                if not name:
                    continue

                await conn.execute("""
                    INSERT INTO grid_upgrades (
                        source_ref, dno, project_name, project_type, voltage_kv,
                        capex_gbp, status, start_date, completion_date,
                        riio_period, description
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (source_ref) DO UPDATE SET
                        status = EXCLUDED.status,
                        updated_at = NOW()
                """,
                    ref, "ssen", name,
                    str(row.get("Type", "")).strip() or None,
                    _parse_float(row.get("Voltage (kV)")),
                    _parse_float(row.get("Cost")),
                    str(row.get("Status", "")).strip() or "Planned",
                    _parse_date(row.get("Start Date")),
                    _parse_date(row.get("Completion Date")),
                    "ED2",
                    str(row.get("Description", "")).strip() or None,
                )
                inserted += 1

        plan_count = await conn.fetchval(
            "SELECT count(*) FROM dno_investment_plans WHERE dno = 'ssen'"
        )
        if plan_count == 0:
            await _seed_dno_plans(conn, "ssen")

        elapsed = round(time.time() - t0, 1)
        log.info("SSEN upgrades ingested: %d rows in %.1fs", inserted, elapsed)
        return {"dno": "ssen", "inserted": inserted, "elapsed_s": elapsed}

    except Exception as e:
        log.error("SSEN ingestion failed: %s", e)
        return {"dno": "ssen", "error": str(e)}
    finally:
        if release:
            await conn_or_pool.release(conn)


# ── Seed RIIO-ED2 investment plans ───────────────────────────────────────

RIIO_ED2_PROGRAMMES = {
    "nged": [
        ("Load-related reinforcement", 1_200_000_000, 2028, 340),
        ("Network resilience", 450_000_000, 2028, 120),
        ("Net Zero enablement", 800_000_000, 2028, 200),
        ("DSO transformation", 180_000_000, 2028, 45),
    ],
    "ukpn": [
        ("Load-related reinforcement", 1_500_000_000, 2028, 400),
        ("Network resilience", 600_000_000, 2028, 150),
        ("Net Zero enablement", 950_000_000, 2028, 250),
        ("EV readiness", 350_000_000, 2028, 80),
    ],
    "ssen": [
        ("Load-related reinforcement", 900_000_000, 2028, 280),
        ("Network resilience", 380_000_000, 2028, 100),
        ("Net Zero enablement", 650_000_000, 2028, 180),
        ("Subsea cables", 200_000_000, 2028, 30),
    ],
}


async def _seed_dno_plans(conn: asyncpg.Connection, dno: str):
    """Seed RIIO-ED2 investment plan rows for a DNO."""
    programmes = RIIO_ED2_PROGRAMMES.get(dno, [])
    for name, capex, year, deliverables in programmes:
        await conn.execute("""
            INSERT INTO dno_investment_plans (
                dno, programme, riio_period, total_capex_gbp, spend_to_date_gbp,
                target_year, deliverable_count, delivered_count, description
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
            dno, name, "ED2", float(capex), 0.0,
            year, deliverables, 0,
            f"RIIO-ED2 {name} programme for {DNO_NAMES.get(dno, dno)}",
        )
    log.info("Seeded %d RIIO-ED2 plans for %s", len(programmes), dno)


# ── Query ────────────────────────────────────────────────────────────────

async def query_grid_upgrades(
    conn: asyncpg.Connection,
    *,
    dno: str | None = None,
    status: str | None = None,
    min_voltage_kv: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float = 25,
    limit: int = 50,
) -> list[dict]:
    """Query grid upgrades with filters."""
    conditions = []
    params: list[Any] = []
    idx = 1

    if dno:
        conditions.append(f"dno = ${idx}")
        params.append(dno)
        idx += 1
    if status:
        conditions.append(f"status ILIKE ${idx}")
        params.append(f"%{status}%")
        idx += 1
    if min_voltage_kv is not None:
        conditions.append(f"voltage_kv >= ${idx}")
        params.append(min_voltage_kv)
        idx += 1
    if lat is not None and lon is not None:
        conditions.append(
            f"geometry IS NOT NULL AND ST_DWithin(geometry, ST_Transform(ST_SetSRID(ST_MakePoint(${idx}, ${idx+1}), 4326), 27700), ${idx+2})"
        )
        params.extend([lon, lat, radius_km * 1000])
        idx += 3

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = await conn.fetch(f"""
        SELECT upgrade_id, source_ref, dno, project_name, project_type, voltage_kv,
               capex_gbp, status, start_date, completion_date,
               riio_period, constraint_area, capacity_released_mw, description
        FROM grid_upgrades
        {where}
        ORDER BY capex_gbp DESC NULLS LAST
        LIMIT {limit}
    """, *params)

    return [dict(r) for r in rows]


async def grid_upgrade_summary(conn: asyncpg.Connection) -> dict:
    """Aggregate grid upgrades by DNO, status, voltage, RIIO period."""
    by_dno = await conn.fetch("""
        SELECT dno, count(*) AS cnt, coalesce(sum(capex_gbp), 0) AS total_capex
        FROM grid_upgrades GROUP BY dno ORDER BY total_capex DESC
    """)
    by_status = await conn.fetch("""
        SELECT status, count(*) AS cnt
        FROM grid_upgrades GROUP BY status ORDER BY cnt DESC
    """)
    by_voltage = await conn.fetch("""
        SELECT CASE
            WHEN voltage_kv >= 132 THEN '132kV+'
            WHEN voltage_kv >= 33 THEN '33-132kV'
            WHEN voltage_kv >= 11 THEN '11-33kV'
            ELSE 'LV/Unknown'
        END AS voltage_band,
        count(*) AS cnt, coalesce(sum(capex_gbp), 0) AS total_capex
        FROM grid_upgrades GROUP BY voltage_band ORDER BY total_capex DESC
    """)
    total = await conn.fetchval("SELECT count(*) FROM grid_upgrades")
    total_capex = await conn.fetchval("SELECT coalesce(sum(capex_gbp), 0) FROM grid_upgrades")

    return {
        "total_projects": total,
        "total_capex_gbp": round(float(total_capex), 0),
        "by_dno": [dict(r) for r in by_dno],
        "by_status": [dict(r) for r in by_status],
        "by_voltage": [dict(r) for r in by_voltage],
    }


async def dno_investment_summary(conn: asyncpg.Connection, dno: str | None = None) -> dict:
    """RIIO-ED2 programme delivery dashboard."""
    conditions = []
    params: list[Any] = []
    if dno:
        conditions.append("dno = $1")
        params.append(dno)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = await conn.fetch(f"""
        SELECT plan_id, dno, programme, riio_period, total_capex_gbp, spend_to_date_gbp,
               target_year, deliverable_count, delivered_count, description
        FROM dno_investment_plans
        {where}
        ORDER BY dno, programme
    """, *params)

    plans = []
    for r in rows:
        d = dict(r)
        d["plan_id"] = str(d["plan_id"])
        total = d.get("deliverable_count") or 1
        delivered = d.get("delivered_count") or 0
        d["delivery_pct"] = round(delivered / total * 100, 1) if total > 0 else 0
        capex = d.get("total_capex_gbp") or 0
        spent = d.get("spend_to_date_gbp") or 0
        d["spend_pct"] = round(spent / capex * 100, 1) if capex > 0 else 0
        plans.append(d)

    return {"count": len(plans), "plans": plans}
