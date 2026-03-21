"""Pull real REPD, OSM power, grid substations, and ESO TEC data near a location.

Used by the 3D Digital Twin to overlay real infrastructure on site visualisations.
All spatial queries use PostGIS ST_DWithin with appropriate SRID transforms.

Table schemas (verified from DB):
  repd_project:         geometry(Point,4326)   — ref_id, site_name, technology_type, installed_capacity_mw, dev_status, dev_status_short, operator, region, county, mounting_type, num_turbines
  osm_power_generator:  geometry(Point,4326)   — osm_id, source, output_kw, name, operator
  osm_power_substation: geometry(Point,4326)   — osm_id, voltage_kv, substation_type, name, operator, ref
  osm_power_line:       geometry(LineString,4326) — osm_id, voltage_kv, line_type, name, operator, cables, circuits
  grid_substations:     geom(Point,27700)      — id, name, dno, voltage_kv, demand_mw, generation_mw, demand_headroom_mw, gen_headroom_mw, site_type, transformer_rating_mva, rag_demand, rag_generation
  eso_tec_project:      geometry(Point,4326)   — id, project_name, customer_name, connection_site, mw_connected, cumulative_capacity_mw, plant_type, project_status, host_to, gate
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

log = logging.getLogger("princeps.real_site_context")


async def get_real_site_context(
    pool: asyncpg.Pool,
    lat: float,
    lon: float,
    radius_km: float = 5,
) -> dict[str, Any]:
    """Pull all real data near a location for 3D twin enrichment."""
    radius_m = radius_km * 1000

    async with pool.acquire() as conn:
        # ── REPD renewable projects (geometry is EPSG:4326) ──────────────
        nearby_renewables = []
        try:
            rows = await conn.fetch(
                """
                SELECT ref_id, site_name, technology_type, installed_capacity_mw,
                       dev_status, dev_status_short, operator, region, county,
                       mounting_type, num_turbines,
                       ST_Y(geometry) AS lat, ST_X(geometry) AS lon
                FROM repd_project
                WHERE geometry IS NOT NULL
                  AND ST_DWithin(
                        geometry::geography,
                        ST_SetSRID(ST_Point($1, $2), 4326)::geography,
                        $3
                      )
                ORDER BY installed_capacity_mw DESC NULLS LAST
                LIMIT 50
                """,
                lon, lat, radius_m,
            )
            for r in rows:
                nearby_renewables.append({
                    "ref_id": r["ref_id"],
                    "name": r["site_name"],
                    "technology": r["technology_type"],
                    "capacity_mw": float(r["installed_capacity_mw"]) if r["installed_capacity_mw"] else None,
                    "status": r["dev_status_short"] or r["dev_status"],
                    "operator": r["operator"],
                    "region": r["region"],
                    "county": r["county"],
                    "mounting_type": r["mounting_type"],
                    "num_turbines": r["num_turbines"],
                    "lat": float(r["lat"]),
                    "lon": float(r["lon"]),
                })
        except asyncpg.PostgresError as exc:
            log.warning("REPD query failed: %s", exc)

        # ── OSM power generators (geometry is EPSG:4326) ─────────────────
        osm_generators = []
        try:
            rows = await conn.fetch(
                """
                SELECT osm_id, source, output_kw, name, operator,
                       ST_Y(geometry) AS lat, ST_X(geometry) AS lon
                FROM osm_power_generator
                WHERE geometry IS NOT NULL
                  AND ST_DWithin(
                        geometry::geography,
                        ST_SetSRID(ST_Point($1, $2), 4326)::geography,
                        $3
                      )
                ORDER BY output_kw DESC NULLS LAST
                LIMIT 100
                """,
                lon, lat, radius_m,
            )
            for r in rows:
                osm_generators.append({
                    "osm_id": r["osm_id"],
                    "source": r["source"],
                    "output_kw": float(r["output_kw"]) if r["output_kw"] else None,
                    "name": r["name"],
                    "operator": r["operator"],
                    "lat": float(r["lat"]),
                    "lon": float(r["lon"]),
                })
        except asyncpg.PostgresError as exc:
            log.warning("OSM generators query failed: %s", exc)

        # ── OSM power substations (geometry is EPSG:4326) ────────────────
        osm_substations = []
        try:
            rows = await conn.fetch(
                """
                SELECT osm_id, voltage_kv, substation_type, name, operator, ref,
                       ST_Y(geometry) AS lat, ST_X(geometry) AS lon
                FROM osm_power_substation
                WHERE geometry IS NOT NULL
                  AND ST_DWithin(
                        geometry::geography,
                        ST_SetSRID(ST_Point($1, $2), 4326)::geography,
                        $3
                      )
                ORDER BY voltage_kv DESC NULLS LAST
                LIMIT 50
                """,
                lon, lat, radius_m,
            )
            for r in rows:
                osm_substations.append({
                    "osm_id": r["osm_id"],
                    "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
                    "substation_type": r["substation_type"],
                    "name": r["name"],
                    "operator": r["operator"],
                    "ref": r["ref"],
                    "lat": float(r["lat"]),
                    "lon": float(r["lon"]),
                })
        except asyncpg.PostgresError as exc:
            log.warning("OSM substations query failed: %s", exc)

        # ── OSM power lines as GeoJSON (geometry is EPSG:4326 LineString) ─
        osm_lines = []
        try:
            rows = await conn.fetch(
                """
                SELECT osm_id, voltage_kv, line_type, name, operator, cables, circuits,
                       ST_AsGeoJSON(geometry) AS geojson
                FROM osm_power_line
                WHERE geometry IS NOT NULL
                  AND ST_DWithin(
                        geometry::geography,
                        ST_SetSRID(ST_Point($1, $2), 4326)::geography,
                        $3
                      )
                ORDER BY voltage_kv DESC NULLS LAST
                LIMIT 100
                """,
                lon, lat, radius_m,
            )
            for r in rows:
                osm_lines.append({
                    "osm_id": r["osm_id"],
                    "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
                    "line_type": r["line_type"],
                    "name": r["name"],
                    "operator": r["operator"],
                    "cables": r["cables"],
                    "circuits": r["circuits"],
                    "geometry": json.loads(r["geojson"]) if r["geojson"] else None,
                })
        except asyncpg.PostgresError as exc:
            log.warning("OSM lines query failed: %s", exc)

        # ── Grid substations (geom is EPSG:27700) ───────────────────────
        grid_subs = []
        try:
            rows = await conn.fetch(
                """
                SELECT id, name, dno, voltage_kv, demand_mw, generation_mw,
                       demand_headroom_mw, gen_headroom_mw, site_type,
                       transformer_rating_mva, rag_demand, rag_generation,
                       ST_Y(ST_Transform(geom, 4326)) AS lat,
                       ST_X(ST_Transform(geom, 4326)) AS lon
                FROM grid_substations
                WHERE geom IS NOT NULL
                  AND ST_DWithin(
                        geom,
                        ST_Transform(ST_SetSRID(ST_Point($1, $2), 4326), 27700),
                        $3
                      )
                ORDER BY voltage_kv DESC NULLS LAST
                LIMIT 30
                """,
                lon, lat, radius_m,
            )
            for r in rows:
                grid_subs.append({
                    "id": r["id"],
                    "name": r["name"],
                    "dno": r["dno"],
                    "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] is not None else None,
                    "demand_mw": float(r["demand_mw"]) if r["demand_mw"] is not None else None,
                    "generation_mw": float(r["generation_mw"]) if r["generation_mw"] is not None else None,
                    "demand_headroom_mw": float(r["demand_headroom_mw"]) if r["demand_headroom_mw"] is not None else None,
                    "gen_headroom_mw": float(r["gen_headroom_mw"]) if r["gen_headroom_mw"] is not None else None,
                    "site_type": r["site_type"],
                    "transformer_rating_mva": float(r["transformer_rating_mva"]) if r["transformer_rating_mva"] is not None else None,
                    "rag_demand": r["rag_demand"],
                    "rag_generation": r["rag_generation"],
                    "lat": float(r["lat"]),
                    "lon": float(r["lon"]),
                })
        except asyncpg.PostgresError as exc:
            log.warning("Grid substations query failed: %s", exc)

        # ── ESO TEC queue (geometry is EPSG:4326) ───────────────────────
        tec_queue = []
        try:
            rows = await conn.fetch(
                """
                SELECT id, project_name, customer_name, connection_site,
                       mw_connected, cumulative_capacity_mw, plant_type,
                       project_status, host_to, gate,
                       ST_Y(geometry) AS lat, ST_X(geometry) AS lon
                FROM eso_tec_project
                WHERE geometry IS NOT NULL
                  AND ST_DWithin(
                        geometry::geography,
                        ST_SetSRID(ST_Point($1, $2), 4326)::geography,
                        $3
                      )
                ORDER BY cumulative_capacity_mw DESC NULLS LAST
                LIMIT 30
                """,
                lon, lat, radius_m,
            )
            for r in rows:
                tec_queue.append({
                    "id": r["id"],
                    "project_name": r["project_name"],
                    "customer_name": r["customer_name"],
                    "connection_site": r["connection_site"],
                    "mw_connected": float(r["mw_connected"]) if r["mw_connected"] else None,
                    "capacity_mw": float(r["cumulative_capacity_mw"]) if r["cumulative_capacity_mw"] else None,
                    "plant_type": r["plant_type"],
                    "status": r["project_status"],
                    "host_to": r["host_to"],
                    "gate": r["gate"],
                    "lat": float(r["lat"]),
                    "lon": float(r["lon"]),
                })
        except asyncpg.PostgresError as exc:
            log.warning("ESO TEC query failed: %s", exc)

    # ── Aggregations ────────────────────────────────────────────────────
    total_renewable_mw = sum(
        r["capacity_mw"] for r in nearby_renewables if r["capacity_mw"]
    )

    technology_mix: dict[str, float] = {}
    for r in nearby_renewables:
        tech = (r["technology"] or "Unknown").strip()
        technology_mix[tech] = technology_mix.get(tech, 0) + (r["capacity_mw"] or 0)

    return {
        "nearby_renewables": nearby_renewables,
        "osm_generators": osm_generators,
        "osm_substations": osm_substations,
        "osm_lines": osm_lines,
        "grid_substations": grid_subs,
        "tec_queue": tec_queue,
        "total_renewable_mw": round(total_renewable_mw, 2),
        "technology_mix": {k: round(v, 2) for k, v in technology_mix.items()},
        "radius_km": radius_km,
        "centre": {"lat": lat, "lon": lon},
    }
