"""
Cluster dependency graph — capability 1 of the Pulse suite.

Models the UK transmission connection queue as a live graph where every project
in a shared cluster study is linked to the network upgrades it has been
allocated costs for. Withdrawals propagate cost changes across siblings.

All functions are async and expect an asyncpg pool (see app/deps.py).
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

import asyncpg

log = logging.getLogger("princeps.cluster_graph")

_SCHEMA_PATH = Path(__file__).parent / "cluster_graph_schema.sql"


# ────────────────────────────────────────────────────────────────────────
# Schema
# ────────────────────────────────────────────────────────────────────────

async def setup_schema(conn: asyncpg.Connection) -> None:
    """Run the cluster-graph schema SQL idempotently."""
    sql = _SCHEMA_PATH.read_text()
    # Strip single-line comments before splitting (otherwise the first
    # statement inherits the file header comment and gets filtered).
    clean = "\n".join(
        line for line in sql.splitlines()
        if not line.lstrip().startswith("--")
    )
    for stmt in clean.split(";"):
        if stmt.strip():
            await conn.execute(stmt)


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Startup hook — ensure tables exist before other functions run."""
    async with pool.acquire() as conn:
        await setup_schema(conn)
    log.info("cluster_graph schema ready")


def _split_statements(sql: str) -> list[str]:
    """Split a multi-statement SQL file on ';' while preserving comments."""
    return [s for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]


# ────────────────────────────────────────────────────────────────────────
# Ingestion — link TEC register rows into cluster studies
# ────────────────────────────────────────────────────────────────────────

_DNO_BY_ZONE = {
    "A": "SPEN", "B": "SPEN",
    "C": "ENWL",
    "D": "NPG", "E": "NPG",
    "F": "UKPN", "G": "UKPN", "J": "UKPN",
    "H": "NGED", "K": "NGED", "L": "NGED", "M": "NGED",
    "N": "SSEN", "P": "SSEN",
}


async def ingest_from_tec_register(pool: asyncpg.Pool, dry_run: bool = False) -> dict:
    """Group TEC register rows into cluster studies and allocate upgrade costs."""
    summary = {
        "studies_created": 0,
        "upgrades_created": 0,
        "allocations_created": 0,
        "projects_linked": 0,
        "used_demo_data": False,
    }

    async with pool.acquire() as conn:
        # Does the TEC table have anything?
        tec_exists = await conn.fetchval(
            "SELECT to_regclass('public.eso_tec_register') IS NOT NULL"
        )
        tec_count = 0
        if tec_exists:
            tec_count = await conn.fetchval("SELECT COUNT(*) FROM eso_tec_register") or 0

        if tec_count == 0:
            # Fall back to synthetic demo clusters so the UI has something to render.
            await _seed_demo_clusters(conn, summary, dry_run=dry_run)
            summary["used_demo_data"] = True
            return summary

        # Group TEC rows by connection_site + voltage_kv to form implicit studies
        rows = await conn.fetch(
            """
            SELECT tec_id, customer_name, connection_site, tec_mw,
                   voltage_kv, zone, status
            FROM eso_tec_register
            WHERE connection_site IS NOT NULL
              AND tec_mw IS NOT NULL
              AND status IS NOT NULL
              AND status NOT IN ('Terminated', 'Withdrawn')
            """
        )
        clusters: dict[tuple[str, float], list] = {}
        for r in rows:
            key = (r["connection_site"], float(r["voltage_kv"] or 0.0))
            clusters.setdefault(key, []).append(r)

        # Only keep clusters with 3+ projects (true cluster studies)
        clusters = {k: v for k, v in clusters.items() if 3 <= len(v) <= 50}

        async with conn.transaction():
            for (site, voltage), projects in clusters.items():
                total_mw = sum((float(p["tec_mw"] or 0)) for p in projects)
                if total_mw <= 0:
                    continue

                zone = (projects[0]["zone"] or "")[:1].upper()
                dno = _DNO_BY_ZONE.get(zone, "ESO")
                study_id = f"STUDY-{_slug(site)[:24]}-{int(voltage)}kv"

                # Total cost scales with aggregate capacity: £5M base + £50k/MW
                total_cost = 5_000_000 + total_mw * 50_000

                if dry_run:
                    summary["studies_created"] += 1
                    summary["upgrades_created"] += 1
                    summary["allocations_created"] += len(projects)
                    summary["projects_linked"] += len(projects)
                    continue

                await conn.execute(
                    """
                    INSERT INTO cluster_studies
                        (study_id, dno, region, gsp_code, study_type, status, total_upgrade_cost_gbp, notes)
                    VALUES ($1, $2, $3, $4, 'group', 'active', $5, $6)
                    ON CONFLICT (study_id) DO UPDATE SET
                        total_upgrade_cost_gbp = EXCLUDED.total_upgrade_cost_gbp,
                        updated_at = now()
                    """,
                    study_id, dno, zone, site, total_cost,
                    f"Synthesised from {len(projects)} TEC rows at {site}",
                )
                summary["studies_created"] += 1

                # One "generic_reinforcement" upgrade per study
                upgrade_id = await conn.fetchval(
                    """
                    INSERT INTO network_upgrades
                        (study_id, upgrade_type, voltage_kv, description, estimated_cost_gbp, status)
                    VALUES ($1, 'generic', $2, $3, $4, 'planned')
                    RETURNING upgrade_id
                    """,
                    study_id, voltage,
                    f"Generic reinforcement bundle — {site} {int(voltage)}kV",
                    total_cost,
                )
                summary["upgrades_created"] += 1

                # Pro-rata-by-capacity allocation
                for p in projects:
                    mw = float(p["tec_mw"] or 0)
                    if mw <= 0:
                        continue
                    fraction = mw / total_mw
                    allocated = round(total_cost * fraction)
                    await conn.execute(
                        """
                        INSERT INTO project_upgrade_allocations
                            (project_id, upgrade_id, study_id, allocation_method,
                             allocation_fraction, allocated_cost_gbp, is_current)
                        VALUES ($1, $2, $3, 'pro_rata_capacity', $4, $5, TRUE)
                        """,
                        p["tec_id"], upgrade_id, study_id, fraction, allocated,
                    )
                    summary["allocations_created"] += 1
                    summary["projects_linked"] += 1

    return summary


async def _seed_demo_clusters(conn: asyncpg.Connection, summary: dict, dry_run: bool = False) -> None:
    """Seed a handful of synthetic clusters so the UI has something to show."""
    demo_studies = [
        ("STUDY-DEMO-BRAMFORD", "UKPN", "F", "Bramford", 400, 28_000_000, 6),
        ("STUDY-DEMO-SUNDON",   "NGED", "H", "Sundon",   275, 18_000_000, 5),
        ("STUDY-DEMO-KEADBY",   "NPG",  "D", "Keadby",   400, 42_000_000, 8),
        ("STUDY-DEMO-IRON-ACTON","NGED","H", "Iron Acton",275, 15_000_000, 4),
        ("STUDY-DEMO-HINKLEY",  "NGED", "H", "Hinkley",  400, 36_000_000, 7),
    ]
    for study_id, dno, zone, site, voltage, total_cost, n_projects in demo_studies:
        if dry_run:
            summary["studies_created"] += 1
            summary["upgrades_created"] += 1
            summary["allocations_created"] += n_projects
            summary["projects_linked"] += n_projects
            continue
        await conn.execute(
            """
            INSERT INTO cluster_studies
                (study_id, dno, region, gsp_code, study_type, status, total_upgrade_cost_gbp, notes)
            VALUES ($1, $2, $3, $4, 'group', 'demo', $5, 'Synthetic demo cluster')
            ON CONFLICT (study_id) DO NOTHING
            """,
            study_id, dno, zone, site, total_cost,
        )
        summary["studies_created"] += 1

        upgrade_id = await conn.fetchval(
            """
            INSERT INTO network_upgrades
                (study_id, upgrade_type, voltage_kv, description, estimated_cost_gbp, status)
            VALUES ($1, 'generic', $2, $3, $4, 'planned')
            RETURNING upgrade_id
            """,
            study_id, voltage,
            f"Demo reinforcement — {site} {voltage}kV",
            total_cost,
        )
        summary["upgrades_created"] += 1

        # Synthesise projects with varying capacity
        mws = [round(random.uniform(25, 150), 1) for _ in range(n_projects)]
        total_mw = sum(mws)
        for i, mw in enumerate(mws):
            proj_id = f"{study_id}-P{i+1}"
            fraction = mw / total_mw
            allocated = round(total_cost * fraction)
            await conn.execute(
                """
                INSERT INTO project_upgrade_allocations
                    (project_id, upgrade_id, study_id, allocation_method,
                     allocation_fraction, allocated_cost_gbp, is_current)
                VALUES ($1, $2, $3, 'pro_rata_capacity', $4, $5, TRUE)
                """,
                proj_id, upgrade_id, study_id, fraction, allocated,
            )
            summary["allocations_created"] += 1
            summary["projects_linked"] += 1


def _slug(text: str) -> str:
    """Cheap URL-safe slug."""
    return "".join(c if c.isalnum() else "-" for c in text.upper()).strip("-")


# ────────────────────────────────────────────────────────────────────────
# Dependency computation
# ────────────────────────────────────────────────────────────────────────

async def compute_dependencies(pool: asyncpg.Pool, study_id: str | None = None) -> int:
    """Rebuild cluster_dependencies edges from current allocations."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            if study_id:
                await conn.execute(
                    "DELETE FROM cluster_dependencies WHERE study_id = $1",
                    study_id,
                )
                where = "AND a.study_id = $1"
                params = [study_id]
            else:
                await conn.execute("DELETE FROM cluster_dependencies")
                where = ""
                params = []

            sql = f"""
                INSERT INTO cluster_dependencies
                    (from_project_id, to_project_id, shared_upgrade_id, study_id,
                     shared_cost_gbp, dependency_strength)
                SELECT
                    a.project_id,
                    b.project_id,
                    a.upgrade_id,
                    a.study_id,
                    LEAST(a.allocated_cost_gbp, b.allocated_cost_gbp),
                    CASE
                        WHEN GREATEST(a.allocated_cost_gbp, b.allocated_cost_gbp) = 0 THEN 0
                        ELSE LEAST(a.allocated_cost_gbp, b.allocated_cost_gbp)::NUMERIC
                             / GREATEST(a.allocated_cost_gbp, b.allocated_cost_gbp)::NUMERIC
                    END
                FROM project_upgrade_allocations a
                JOIN project_upgrade_allocations b
                  ON a.upgrade_id = b.upgrade_id
                 AND a.project_id < b.project_id
                WHERE a.is_current AND b.is_current
                {where}
            """
            result = await conn.execute(sql, *params)
            # asyncpg returns "INSERT 0 N"
            try:
                return int(result.split()[-1])
            except Exception:
                return 0


# ────────────────────────────────────────────────────────────────────────
# Withdraw — propagate cost reallocation across siblings
# ────────────────────────────────────────────────────────────────────────

async def withdraw_project(pool: asyncpg.Pool, project_id: str) -> dict:
    """Withdraw a project: redistribute its upgrade cost share across siblings.

    Returns a dict with affected projects, upgrades, per-project cost deltas,
    and a list of event dicts ready to hand to the grid_events subsystem.
    """
    result = {
        "project_id": project_id,
        "affected_projects": [],
        "upgrades_reallocated": [],
        "cost_delta_by_project": {},
        "events": [],
    }

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Fetch the current allocations for this project
            allocations = await conn.fetch(
                """
                SELECT allocation_id, upgrade_id, study_id,
                       allocation_fraction, allocated_cost_gbp
                FROM project_upgrade_allocations
                WHERE project_id = $1 AND is_current = TRUE
                """,
                project_id,
            )
            if not allocations:
                return result

            affected_study_ids = set()

            for alloc in allocations:
                upgrade_id = alloc["upgrade_id"]
                study_id = alloc["study_id"]
                withdrawn_fraction = float(alloc["allocation_fraction"] or 0)
                withdrawn_cost = float(alloc["allocated_cost_gbp"] or 0)
                affected_study_ids.add(study_id)

                # Mark this allocation invalid
                await conn.execute(
                    "UPDATE project_upgrade_allocations "
                    "SET is_current = FALSE, valid_until = now() "
                    "WHERE allocation_id = $1",
                    alloc["allocation_id"],
                )

                # Fetch siblings for this upgrade
                siblings = await conn.fetch(
                    """
                    SELECT allocation_id, project_id, allocation_fraction, allocated_cost_gbp
                    FROM project_upgrade_allocations
                    WHERE upgrade_id = $1
                      AND is_current = TRUE
                      AND project_id != $2
                    """,
                    upgrade_id, project_id,
                )
                if not siblings:
                    continue

                sibling_total = sum(float(s["allocation_fraction"] or 0) for s in siblings)
                if sibling_total <= 0:
                    continue

                # Redistribute withdrawn share pro-rata to remaining allocations
                for s in siblings:
                    share = float(s["allocation_fraction"] or 0) / sibling_total
                    extra_fraction = withdrawn_fraction * share
                    extra_cost = withdrawn_cost * share
                    new_fraction = float(s["allocation_fraction"] or 0) + extra_fraction
                    new_cost = float(s["allocated_cost_gbp"] or 0) + extra_cost

                    # Write a new current row
                    await conn.execute(
                        "UPDATE project_upgrade_allocations "
                        "SET is_current = FALSE, valid_until = now() "
                        "WHERE allocation_id = $1",
                        s["allocation_id"],
                    )
                    await conn.execute(
                        """
                        INSERT INTO project_upgrade_allocations
                            (project_id, upgrade_id, study_id, allocation_method,
                             allocation_fraction, allocated_cost_gbp, is_current)
                        VALUES ($1, $2, $3, 'pro_rata_capacity', $4, $5, TRUE)
                        """,
                        s["project_id"], upgrade_id, study_id,
                        new_fraction, new_cost,
                    )

                    sib_id = s["project_id"]
                    if sib_id not in result["affected_projects"]:
                        result["affected_projects"].append(sib_id)
                    result["cost_delta_by_project"][sib_id] = (
                        result["cost_delta_by_project"].get(sib_id, 0) + extra_cost
                    )
                    result["events"].append({
                        "event_type": "cost_reallocation",
                        "severity": "warn",
                        "project_id": sib_id,
                        "upgrade_id": upgrade_id,
                        "payload": {
                            "trigger": "withdrawal",
                            "withdrawn_project": project_id,
                            "old_cost_gbp": float(s["allocated_cost_gbp"] or 0),
                            "new_cost_gbp": new_cost,
                            "delta_gbp": extra_cost,
                            "study_id": study_id,
                        },
                        "source": "cluster_graph",
                    })

                if upgrade_id not in result["upgrades_reallocated"]:
                    result["upgrades_reallocated"].append(upgrade_id)

            result["events"].append({
                "event_type": "withdrawal",
                "severity": "critical",
                "project_id": project_id,
                "payload": {
                    "affected_siblings": len(result["affected_projects"]),
                    "upgrades_reallocated": len(result["upgrades_reallocated"]),
                },
                "source": "cluster_graph",
            })

        # Recompute dependencies for each affected study (outside write transaction)
        for sid in affected_study_ids:
            await compute_dependencies(pool, study_id=sid)

    return result


# ────────────────────────────────────────────────────────────────────────
# Read-side
# ────────────────────────────────────────────────────────────────────────

async def get_cluster_view(pool: asyncpg.Pool, project_id: str) -> dict:
    """Return the cluster neighbourhood for a single project."""
    async with pool.acquire() as conn:
        allocs = await conn.fetch(
            """
            SELECT a.upgrade_id, a.study_id, a.allocation_fraction, a.allocated_cost_gbp,
                   u.description, u.voltage_kv, u.upgrade_type
            FROM project_upgrade_allocations a
            JOIN network_upgrades u ON u.upgrade_id = a.upgrade_id
            WHERE a.project_id = $1 AND a.is_current = TRUE
            """,
            project_id,
        )
        if not allocs:
            return {"project_id": project_id, "siblings": [], "upgrades": [],
                    "total_exposure_gbp": 0, "last_recomputed_at": None}

        upgrade_ids = [r["upgrade_id"] for r in allocs]
        siblings_rows = await conn.fetch(
            """
            SELECT DISTINCT a.project_id,
                            SUM(a.allocated_cost_gbp) AS total_cost,
                            array_agg(DISTINCT a.upgrade_id) AS upgrade_ids
            FROM project_upgrade_allocations a
            WHERE a.upgrade_id = ANY($1::int[])
              AND a.is_current = TRUE
              AND a.project_id != $2
            GROUP BY a.project_id
            ORDER BY total_cost DESC
            """,
            upgrade_ids, project_id,
        )
        last = await conn.fetchval(
            "SELECT MAX(computed_at) FROM cluster_dependencies WHERE from_project_id = $1 OR to_project_id = $1",
            project_id,
        )

        return {
            "project_id": project_id,
            "siblings": [
                {
                    "project_id": s["project_id"],
                    "total_cost_gbp": float(s["total_cost"] or 0),
                    "shared_upgrade_ids": list(s["upgrade_ids"]) if s["upgrade_ids"] else [],
                } for s in siblings_rows
            ],
            "upgrades": [
                {
                    "upgrade_id": a["upgrade_id"],
                    "study_id": a["study_id"],
                    "allocation_fraction": float(a["allocation_fraction"] or 0),
                    "allocated_cost_gbp": float(a["allocated_cost_gbp"] or 0),
                    "description": a["description"],
                    "voltage_kv": float(a["voltage_kv"]) if a["voltage_kv"] else None,
                    "type": a["upgrade_type"],
                } for a in allocs
            ],
            "total_exposure_gbp": sum(float(a["allocated_cost_gbp"] or 0) for a in allocs),
            "last_recomputed_at": last.isoformat() if last else None,
        }


async def get_cluster_graph_geojson(pool: asyncpg.Pool, study_id: str) -> dict:
    """Return a GeoJSON FeatureCollection of the cluster graph (projects + upgrades + edges)."""
    async with pool.acquire() as conn:
        projects = await conn.fetch(
            """
            SELECT a.project_id,
                   SUM(a.allocated_cost_gbp) AS cost,
                   COUNT(DISTINCT a.upgrade_id) AS n_upgrades
            FROM project_upgrade_allocations a
            WHERE a.study_id = $1 AND a.is_current = TRUE
            GROUP BY a.project_id
            """,
            study_id,
        )
        upgrades = await conn.fetch(
            """
            SELECT upgrade_id, description, estimated_cost_gbp, voltage_kv,
                   ST_X(ST_Transform(location_geom, 4326)) AS lon,
                   ST_Y(ST_Transform(location_geom, 4326)) AS lat
            FROM network_upgrades
            WHERE study_id = $1
            """,
            study_id,
        )
        deps = await conn.fetch(
            """
            SELECT from_project_id, to_project_id, shared_cost_gbp, dependency_strength
            FROM cluster_dependencies
            WHERE study_id = $1
            """,
            study_id,
        )

    features = []
    for p in projects:
        features.append({
            "type": "Feature",
            "geometry": None,   # caller joins map positions from another source
            "properties": {
                "kind": "project",
                "project_id": p["project_id"],
                "allocated_cost_gbp": float(p["cost"] or 0),
                "upgrade_count": int(p["n_upgrades"] or 0),
            },
        })
    for u in upgrades:
        geom = None
        if u["lon"] is not None and u["lat"] is not None:
            geom = {"type": "Point", "coordinates": [float(u["lon"]), float(u["lat"])]}
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "kind": "upgrade",
                "upgrade_id": u["upgrade_id"],
                "description": u["description"],
                "cost_gbp": float(u["estimated_cost_gbp"] or 0),
                "voltage_kv": float(u["voltage_kv"]) if u["voltage_kv"] else None,
            },
        })
    for d in deps:
        features.append({
            "type": "Feature",
            "geometry": None,
            "properties": {
                "kind": "edge",
                "from": d["from_project_id"],
                "to": d["to_project_id"],
                "shared_cost_gbp": float(d["shared_cost_gbp"] or 0),
                "strength": float(d["dependency_strength"] or 0),
            },
        })
    return {"type": "FeatureCollection", "features": features, "study_id": study_id}


async def list_studies(pool: asyncpg.Pool) -> list[dict]:
    """List all cluster studies with project and upgrade counts."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.study_id, s.dno, s.region, s.gsp_code, s.study_type, s.status,
                   s.total_upgrade_cost_gbp, s.notes, s.created_at,
                   (SELECT COUNT(DISTINCT project_id)
                      FROM project_upgrade_allocations
                     WHERE study_id = s.study_id AND is_current) AS project_count,
                   (SELECT COUNT(*) FROM network_upgrades WHERE study_id = s.study_id) AS upgrade_count
            FROM cluster_studies s
            ORDER BY s.total_upgrade_cost_gbp DESC NULLS LAST
            """
        )
    return [
        {
            "study_id": r["study_id"],
            "dno": r["dno"],
            "region": r["region"],
            "gsp_code": r["gsp_code"],
            "study_type": r["study_type"],
            "status": r["status"],
            "total_upgrade_cost_gbp": float(r["total_upgrade_cost_gbp"] or 0),
            "project_count": int(r["project_count"] or 0),
            "upgrade_count": int(r["upgrade_count"] or 0),
            "notes": r["notes"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        } for r in rows
    ]


async def get_stats(pool: asyncpg.Pool) -> dict:
    """System-wide cluster graph statistics."""
    async with pool.acquire() as conn:
        study_count = await conn.fetchval("SELECT COUNT(*) FROM cluster_studies") or 0
        upgrade_count = await conn.fetchval("SELECT COUNT(*) FROM network_upgrades") or 0
        alloc_count = await conn.fetchval(
            "SELECT COUNT(*) FROM project_upgrade_allocations WHERE is_current"
        ) or 0
        dep_count = await conn.fetchval("SELECT COUNT(*) FROM cluster_dependencies") or 0
        top_exposures = await conn.fetch(
            """
            SELECT project_id, SUM(allocated_cost_gbp) AS exposure
            FROM project_upgrade_allocations
            WHERE is_current
            GROUP BY project_id
            ORDER BY exposure DESC NULLS LAST
            LIMIT 10
            """
        )
    return {
        "studies": int(study_count),
        "upgrades": int(upgrade_count),
        "allocations": int(alloc_count),
        "dependencies": int(dep_count),
        "top_exposures": [
            {"project_id": r["project_id"], "exposure_gbp": float(r["exposure"] or 0)}
            for r in top_exposures
        ],
    }
