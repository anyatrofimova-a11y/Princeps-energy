"""
grid_substations_refresh — unifies per-DNO + OSM substation tables into
the canonical ``grid_substations`` table queried by GridMonitorAgent.

Source tables (existing in production):

  * nged_substation        — NGED-ingested substations (West Midlands,
                             South West, South Wales, East Midlands)
  * osm_power_substation   — OSM Overpass dump of every UK power=substation
  * nged_transformer       — transformer MVA per nged substation
                             (SUM gives capacity)
  * dno_primary_transformers — cross-DNO primary transformer feed with
                             utilisation % (rated_mva + headroom derivation)
  * nged_gsp_limits        — per-GSP capacity / export limit (for headroom)

Policy
------
Each source row is projected into ``grid_substations`` with a
compound key ``<source>:<native-id>`` so overlapping physical sites from
different sources don't collide. The agent's "changes in last 25 hours"
query relies on ``updated_at`` being the *source* timestamp, not the
refresh time — so freshly ingested DNO data is the signal, not our
bookkeeping.

Companion refresher for ``grid_ecr`` unifies nged_ecr into the canonical
ECR table with best-effort substation matching.
"""

from __future__ import annotations

import logging

log = logging.getLogger("princeps.utils.grid_substations_refresh")


# ── Substations ─────────────────────────────────────────────────────────────

_REFRESH_SUBSTATIONS_SQL = r"""
INSERT INTO grid_substations (
    substation_id, name, dno, voltage_kv,
    capacity_mva, headroom_mw, geometry, source, updated_at
)
SELECT
    'nged:' || s.id                                AS substation_id,
    s.name,
    'nged'                                          AS dno,
    s.voltage_kv::numeric(6,1),
    COALESCE(SUM(t.rated_mva), 0)::numeric(10,2)    AS capacity_mva,
    NULL::numeric(10,2)                             AS headroom_mw,
    s.geometry,
    'nged_substation'                               AS source,
    GREATEST(
        s.created_at,
        COALESCE(MAX(t.created_at), s.created_at)
    )                                               AS updated_at
FROM nged_substation s
LEFT JOIN nged_transformer t ON t.substation_id = s.id
GROUP BY s.id, s.name, s.voltage_kv, s.geometry, s.created_at

UNION ALL

-- OSM substations only where NGED didn't already match them (avoid dupes
-- from osm_match_name matches inside nged_substation). OSM geometries
-- are stored in EPSG:4326 — transform to the canonical 27700 on read.
SELECT
    'osm:' || o.osm_id::text                        AS substation_id,
    COALESCE(NULLIF(o.name, ''), 'OSM-' || o.osm_id::text) AS name,
    NULLIF(o.operator, '')::text                    AS dno,
    o.voltage_kv::numeric(6,1),
    NULL::numeric(10,2)                             AS capacity_mva,
    NULL::numeric(10,2)                             AS headroom_mw,
    ST_Transform(
        CASE
            WHEN ST_GeometryType(o.geometry) = 'ST_Polygon'
            THEN ST_Centroid(o.geometry)
            ELSE o.geometry
        END,
        27700
    )                                               AS geometry,
    'osm_power_substation'                          AS source,
    o.fetched_at                                    AS updated_at
FROM osm_power_substation o
WHERE NOT EXISTS (
    SELECT 1 FROM nged_substation n
    WHERE n.osm_match_name = o.name AND n.osm_match_score > 0.85
)

UNION ALL

-- Cross-DNO primary transformers — carries real utilisation so we can
-- derive headroom. Asset IDs are DNO-issued, so prefix with dno.
SELECT
    d.dno || ':' || d.asset_id                      AS substation_id,
    d.site_name                                     AS name,
    d.dno,
    d.voltage_primary_kv::numeric(6,1),
    d.rated_mva::numeric(10,2)                      AS capacity_mva,
    CASE
        WHEN d.utilisation_pct IS NOT NULL AND d.rated_mva IS NOT NULL
        THEN (d.rated_mva * (1 - d.utilisation_pct / 100.0))::numeric(10,2)
        ELSE NULL
    END                                             AS headroom_mw,
    NULL::geometry                                  AS geometry,
    'dno_primary_transformers'                      AS source,
    d.updated_at
FROM dno_primary_transformers d
WHERE d.asset_id IS NOT NULL AND d.site_name IS NOT NULL

ON CONFLICT (substation_id) DO UPDATE SET
    name         = EXCLUDED.name,
    dno          = COALESCE(EXCLUDED.dno, grid_substations.dno),
    voltage_kv   = COALESCE(EXCLUDED.voltage_kv, grid_substations.voltage_kv),
    capacity_mva = COALESCE(EXCLUDED.capacity_mva, grid_substations.capacity_mva),
    headroom_mw  = COALESCE(EXCLUDED.headroom_mw, grid_substations.headroom_mw),
    geometry     = COALESCE(EXCLUDED.geometry, grid_substations.geometry),
    source       = EXCLUDED.source,
    updated_at   = GREATEST(EXCLUDED.updated_at, grid_substations.updated_at);
"""


# ── ECR ─────────────────────────────────────────────────────────────────────

_REFRESH_ECR_SQL = r"""
-- NGED ECR rows projected into the canonical grid_ecr table. Substation
-- matching is best-effort name-based — unmatched rows still get a row
-- with substation_id = NULL so the feed isn't lost.
INSERT INTO grid_ecr (
    substation_id, dno, customer, technology, capacity_mw,
    status, connection_date, data, updated_at
)
SELECT
    (
        SELECT gs.substation_id
          FROM grid_substations gs
         WHERE gs.dno = 'nged'
           AND gs.name ILIKE n.primary_substation
         LIMIT 1
    )                                               AS substation_id,
    'nged'                                          AS dno,
    n.customer_name                                 AS customer,
    COALESCE(n.conversion_tech_1, n.energy_source_1) AS technology,
    COALESCE(
        n.connected_reg_capacity_mw,
        n.accepted_reg_capacity_mw,
        n.reg_capacity_1_mw,
        0
    )::numeric(10,2)                                AS capacity_mw,
    n.connection_status                             AS status,
    n.date_connected                                AS connection_date,
    n.raw                                           AS data,
    COALESCE(
        n.last_updated::timestamptz,
        n.ingested_at
    )                                               AS updated_at
FROM nged_ecr n
WHERE n.reference IS NOT NULL

ON CONFLICT DO NOTHING;
"""


# ── Snapshots ───────────────────────────────────────────────────────────────
# Periodic capture of substation state for cross-run diffing. GridMonitor
# compares today's snapshot against yesterday's to decide which substations
# "changed" — without snapshots, it can only see ``updated_at`` freshness.

_WRITE_SNAPSHOT_SQL = r"""
INSERT INTO grid_snapshots (
    substation_id, capacity_mva, headroom_mw, queue_mw, voltage_kv, data
)
SELECT
    gs.substation_id,
    gs.capacity_mva,
    gs.headroom_mw,
    (
        SELECT COALESCE(SUM(e.capacity_mw), 0)
          FROM grid_ecr e
         WHERE e.substation_id = gs.substation_id
           AND e.status IN ('Accepted', 'In Queue', 'Offered')
    )                                               AS queue_mw,
    gs.voltage_kv,
    jsonb_build_object('source', gs.source, 'refreshed_at', now())
FROM grid_substations gs
WHERE gs.updated_at > now() - interval '30 days';
"""


# ── Public entry points ─────────────────────────────────────────────────────


async def refresh_substations(pool) -> int:
    """Populate ``grid_substations`` from NGED / OSM / DNO-primary feeds.

    Returns the row count of the canonical table after refresh.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(_REFRESH_SUBSTATIONS_SQL)
            row = await conn.fetchrow("SELECT COUNT(*)::int AS n FROM grid_substations")
    n = int(row["n"])
    log.info("grid_substations.refresh rows=%d", n)
    return n


async def refresh_ecr(pool) -> int:
    """Populate ``grid_ecr`` from nged_ecr with best-effort substation join."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(_REFRESH_ECR_SQL)
            row = await conn.fetchrow("SELECT COUNT(*)::int AS n FROM grid_ecr")
    n = int(row["n"])
    log.info("grid_ecr.refresh rows=%d", n)
    return n


async def write_snapshot(pool) -> int:
    """Write a row per active substation to ``grid_snapshots``.

    GridMonitorAgent uses this to diff headroom / queue between runs.
    """
    async with pool.acquire() as conn:
        result = await conn.execute(_WRITE_SNAPSHOT_SQL)
    # asyncpg returns a string like "INSERT 0 1234" — pull the last int.
    try:
        n = int(result.rsplit(" ", 1)[-1])
    except ValueError:
        n = 0
    log.info("grid_snapshots.write rows=%d", n)
    return n


async def refresh_all(pool) -> dict[str, int]:
    """Run the full canonical-grid refresh pipeline in order.

    Order matters:
      1. substations   (ECR match depends on grid_substations being fresh)
      2. ecr           (snapshot queue_mw depends on ecr being fresh)
      3. snapshot      (feeds the diff-based change detection)
    """
    subs = await refresh_substations(pool)
    ecr  = await refresh_ecr(pool)
    snap = await write_snapshot(pool)
    return {"substations": subs, "ecr": ecr, "snapshot": snap}
