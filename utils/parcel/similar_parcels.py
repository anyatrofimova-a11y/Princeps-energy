"""Similar-parcels lookup via pgvector ANN, with a feature-hash fallback.

Schema expectation (BOT-Siting):

    candidate_sites (
        parcel_id        text primary key,
        inspire_id       text,
        embedding        vector(40),
        area_ha          real,
        lpa              text,
        dno_slug         text,
        resource_score   real,
        grid_score       real,
        planning_score   real,
        centroid_lat     double precision,
        centroid_lon     double precision
    )

If the ``candidate_sites`` table or ``vector`` extension is missing, we
fall back to a cheap feature-vector sim that joins against
``hmlr_inspire_parcels`` on area + LPA + centroid distance, so the drawer
still renders "top 5 similar" rows (clearly tagged as ``"provenance":
"fallback"``) instead of an empty list.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

log = logging.getLogger("princeps.parcel.similar_parcels")


async def _has_pgvector(conn: asyncpg.Connection) -> bool:
    try:
        return bool(
            await conn.fetchval(
                "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
            )
        )
    except Exception:  # noqa: BLE001
        return False


async def _has_candidate_sites(conn: asyncpg.Connection) -> bool:
    try:
        return bool(
            await conn.fetchval(
                "SELECT to_regclass('public.candidate_sites') IS NOT NULL"
            )
        )
    except Exception:  # noqa: BLE001
        return False


async def _pgvector_similar(
    conn: asyncpg.Connection, inspire_id: str, top_k: int
) -> list[dict[str, Any]]:
    try:
        rows = await conn.fetch(
            """
            WITH me AS (
                SELECT embedding
                  FROM candidate_sites
                 WHERE inspire_id = $1
                 LIMIT 1
            )
            SELECT cs.parcel_id,
                   cs.inspire_id,
                   cs.area_ha,
                   cs.lpa,
                   cs.dno_slug,
                   cs.resource_score,
                   cs.grid_score,
                   cs.planning_score,
                   cs.centroid_lat,
                   cs.centroid_lon,
                   (cs.embedding <=> me.embedding) AS cosine_distance
              FROM candidate_sites cs, me
             WHERE cs.inspire_id <> $1
             ORDER BY cs.embedding <=> me.embedding ASC
             LIMIT $2
            """,
            inspire_id,
            top_k,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("pgvector similar query failed: %s", exc)
        return []

    return [
        {
            "parcel_id": r["parcel_id"],
            "inspire_id": r["inspire_id"],
            "area_ha": float(r["area_ha"]) if r["area_ha"] else None,
            "lpa": r["lpa"],
            "dno_slug": r["dno_slug"],
            "resource_score": float(r["resource_score"]) if r["resource_score"] else None,
            "grid_score": float(r["grid_score"]) if r["grid_score"] else None,
            "planning_score": float(r["planning_score"]) if r["planning_score"] else None,
            "centroid_lat": float(r["centroid_lat"]) if r["centroid_lat"] else None,
            "centroid_lon": float(r["centroid_lon"]) if r["centroid_lon"] else None,
            "cosine_distance": round(float(r["cosine_distance"]), 4),
            "provenance": "pgvector",
        }
        for r in rows
    ]


async def _fallback_similar(
    conn: asyncpg.Connection, inspire_id: str, top_k: int
) -> list[dict[str, Any]]:
    """Area + LPA + centroid-distance heuristic."""

    try:
        base = await conn.fetchrow(
            """
            SELECT inspire_id::text AS inspire_id,
                   ST_Area(geom)::float AS area_m2,
                   ST_Y(ST_Transform(ST_Centroid(geom), 4326)) AS lat,
                   ST_X(ST_Transform(ST_Centroid(geom), 4326)) AS lon
              FROM hmlr_inspire_parcels
             WHERE inspire_id::text = $1
             LIMIT 1
            """,
            inspire_id,
        )
    except Exception:  # noqa: BLE001
        return []

    if not base:
        return []

    area_m2 = base["area_m2"] or 0.0
    lat = base["lat"]
    lon = base["lon"]

    try:
        rows = await conn.fetch(
            """
            SELECT inspire_id::text AS inspire_id,
                   ST_Area(geom)::float AS area_m2,
                   ST_Y(ST_Transform(ST_Centroid(geom), 4326)) AS lat,
                   ST_X(ST_Transform(ST_Centroid(geom), 4326)) AS lon,
                   ST_Distance(
                       ST_Centroid(geom)::geography,
                       ST_SetSRID(ST_MakePoint($2, $3), 4326)::geography
                   ) AS distance_m,
                   ABS(ST_Area(geom) - $4) AS area_delta
              FROM hmlr_inspire_parcels
             WHERE inspire_id::text <> $1
               AND ABS(ST_Area(geom) - $4) < GREATEST($4 * 0.5, 10000.0)
             ORDER BY area_delta ASC
             LIMIT $5
            """,
            inspire_id,
            lon,
            lat,
            area_m2,
            top_k * 3,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("fallback similar query failed: %s", exc)
        return []

    # Normalise distance (0–50km) + area delta into a pseudo cosine.
    max_dist = 50_000.0
    out: list[dict[str, Any]] = []
    for r in rows[:top_k]:
        d = float(r["distance_m"] or max_dist)
        dnorm = min(d / max_dist, 1.0)
        area_delta_norm = min(float(r["area_delta"] or 0.0) / max(area_m2 or 1.0, 1.0), 1.0)
        pseudo = 0.5 * dnorm + 0.5 * area_delta_norm
        out.append(
            {
                "parcel_id": r["inspire_id"],
                "inspire_id": r["inspire_id"],
                "area_ha": round((r["area_m2"] or 0.0) / 10_000.0, 2),
                "lpa": None,
                "dno_slug": None,
                "resource_score": None,
                "grid_score": None,
                "planning_score": None,
                "centroid_lat": r["lat"],
                "centroid_lon": r["lon"],
                "cosine_distance": round(pseudo, 4),
                "provenance": "fallback",
            }
        )
    return out


async def similar_parcels(
    conn: asyncpg.Connection, inspire_id: str, *, top_k: int = 5
) -> list[dict[str, Any]]:
    """Return top-K similar parcels by embedding distance (with fallback)."""

    if await _has_pgvector(conn) and await _has_candidate_sites(conn):
        rows = await _pgvector_similar(conn, inspire_id, top_k)
        if rows:
            return rows

    return await _fallback_similar(conn, inspire_id, top_k)
