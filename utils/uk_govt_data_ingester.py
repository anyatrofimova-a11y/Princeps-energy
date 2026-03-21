"""
UK Government Open Data Ingester — pulls free datasets for planning constraint screening.

All sources are Open Government Licence (OGL), free, no auth required.

Datasets:
1. Green Belt boundaries — planning.data.gov.uk
2. Brownfield Land Register — planning.data.gov.uk
3. Conservation Areas — planning.data.gov.uk
4. National Parks — Natural England ArcGIS
5. AONB boundaries — Natural England ArcGIS
6. SSSI boundaries — Natural England ArcGIS
7. Ancient Woodland — Natural England ArcGIS
8. ALC Provisional — Natural England ArcGIS
9. Flood Zones — EA ArcGIS
10. Planning Applications (energy) — planning.data.gov.uk entity API
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

log = logging.getLogger("princeps.uk_data_ingester")

# Natural England ArcGIS REST base
NE_ARCGIS = "https://services.arcgis.com/JJzESW51TqeY9uj4/arcgis/rest/services"

# Historic England ArcGIS
HE_ARCGIS = "https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services"

# EA ArcGIS
EA_ARCGIS = "https://environment.data.gov.uk/arcgis/rest/services"

# Planning Data API
PLANNING_DATA = "https://www.planning.data.gov.uk"


async def ingest_all(pool) -> dict:
    """Run all ingesters and return summary."""
    results = {}
    for name, fn in [
        ("green_belt", ingest_green_belt),
        ("brownfield", ingest_brownfield),
        ("national_parks", ingest_national_parks),
        ("aonb", ingest_aonb),
        ("sssi", ingest_sssi),
        ("ancient_woodland", ingest_ancient_woodland),
        ("flood_zones", ingest_flood_zones),
        ("conservation_areas", ingest_conservation_areas),
        ("energy_planning_apps", ingest_energy_planning_apps),
    ]:
        try:
            count = await fn(pool)
            results[name] = {"status": "ok", "count": count}
            log.info("Ingested %s: %d records", name, count)
        except Exception as e:
            results[name] = {"status": "error", "error": str(e)}
            log.warning("Failed to ingest %s: %s", name, e)
    return results


async def _ensure_constraints_table(pool):
    """Create the environmental_constraints table if it doesn't exist."""
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS environmental_constraints (
            id SERIAL PRIMARY KEY,
            constraint_type TEXT NOT NULL,
            name TEXT,
            designation TEXT,
            reference_id TEXT,
            area_ha NUMERIC,
            metadata JSONB,
            geometry GEOMETRY(Geometry, 4326),
            ingested_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(constraint_type, reference_id)
        );
        CREATE INDEX IF NOT EXISTS idx_env_constraints_geom
            ON environmental_constraints USING GIST(geometry);
        CREATE INDEX IF NOT EXISTS idx_env_constraints_type
            ON environmental_constraints(constraint_type);
    """)


async def _fetch_arcgis_features(url: str, *, max_records: int = 5000, where: str = "1=1") -> list[dict]:
    """Fetch features from ArcGIS REST API with pagination."""
    features = []
    offset = 0
    batch_size = 1000

    async with httpx.AsyncClient(timeout=30) as client:
        while offset < max_records:
            params = {
                "where": where,
                "outFields": "*",
                "returnGeometry": "true",
                "f": "geojson",
                "resultOffset": str(offset),
                "resultRecordCount": str(batch_size),
            }
            try:
                resp = await client.get(f"{url}/query", params=params)
                if resp.status_code != 200:
                    log.debug("ArcGIS query returned %s for %s", resp.status_code, url)
                    break
                data = resp.json()
                batch = data.get("features", [])
                if not batch:
                    break
                features.extend(batch)
                offset += len(batch)
                if len(batch) < batch_size:
                    break
            except Exception as e:
                log.debug("ArcGIS fetch error at offset %d: %s", offset, e)
                break

    return features


async def _insert_constraints(pool, constraint_type: str, features: list[dict]) -> int:
    """Insert features into environmental_constraints table."""
    await _ensure_constraints_table(pool)
    count = 0

    async with pool.acquire() as conn:
        for f in features:
            props = f.get("properties", {})
            geom = f.get("geometry")
            if not geom:
                continue

            name = (props.get("NAME") or props.get("name") or
                    props.get("SITE_NAME") or props.get("site_name") or
                    props.get("designation") or "")
            ref_id = (props.get("REFERENCE") or props.get("reference") or
                      props.get("OBJECTID") or props.get("entity") or
                      str(props.get("FID", "")))

            try:
                await conn.execute("""
                    INSERT INTO environmental_constraints
                        (constraint_type, name, designation, reference_id, metadata, geometry)
                    VALUES ($1, $2, $3, $4, $5::jsonb, ST_SetSRID(ST_GeomFromGeoJSON($6), 4326))
                    ON CONFLICT (constraint_type, reference_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        metadata = EXCLUDED.metadata,
                        geometry = EXCLUDED.geometry,
                        ingested_at = NOW()
                """,
                    constraint_type, name, constraint_type, str(ref_id),
                    json.dumps(props, default=str),
                    json.dumps(geom),
                )
                count += 1
            except Exception as e:
                log.debug("Insert failed for %s/%s: %s", constraint_type, ref_id, e)

    return count


# ══════════════════════════════════════════════════════════
# Individual ingesters
# ══════════════════════════════════════════════════════════

async def ingest_green_belt(pool) -> int:
    """Green Belt boundaries from planning.data.gov.uk."""
    features = await _fetch_arcgis_features(
        f"{NE_ARCGIS}/Green_Belt_England/FeatureServer/0",
        max_records=500,
    )
    if not features:
        # Fallback: try planning.data.gov.uk dataset
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{PLANNING_DATA}/entity.json",
                    params={"dataset": "green-belt", "limit": 500, "field": "geometry"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    features = data.get("entities", [])
            except Exception:
                pass
    return await _insert_constraints(pool, "green_belt", features)


async def ingest_brownfield(pool) -> int:
    """Brownfield Land Register from planning.data.gov.uk."""
    features = []
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(
                f"{PLANNING_DATA}/entity.json",
                params={"dataset": "brownfield-land", "limit": 2000},
            )
            if resp.status_code == 200:
                data = resp.json()
                for entity in data.get("entities", []):
                    if entity.get("point"):
                        coords = entity["point"].replace("POINT(", "").replace(")", "").split()
                        if len(coords) == 2:
                            features.append({
                                "properties": {
                                    "name": entity.get("name", ""),
                                    "reference": entity.get("reference", ""),
                                    "entity": entity.get("entity", ""),
                                    "organisation": entity.get("organisation-entity", ""),
                                    "hectares": entity.get("hectares"),
                                    "notes": entity.get("notes", ""),
                                },
                                "geometry": {
                                    "type": "Point",
                                    "coordinates": [float(coords[0]), float(coords[1])],
                                },
                            })
        except Exception as e:
            log.debug("Brownfield fetch failed: %s", e)
    return await _insert_constraints(pool, "brownfield", features)


async def ingest_national_parks(pool) -> int:
    """National Parks from Natural England."""
    features = await _fetch_arcgis_features(
        f"{NE_ARCGIS}/National_Parks_England/FeatureServer/0",
        max_records=20,
    )
    return await _insert_constraints(pool, "national_park", features)


async def ingest_aonb(pool) -> int:
    """Areas of Outstanding Natural Beauty from Natural England."""
    features = await _fetch_arcgis_features(
        f"{NE_ARCGIS}/Areas_of_Outstanding_Natural_Beauty_England/FeatureServer/0",
        max_records=50,
    )
    return await _insert_constraints(pool, "aonb", features)


async def ingest_sssi(pool) -> int:
    """Sites of Special Scientific Interest from Natural England."""
    features = await _fetch_arcgis_features(
        f"{NE_ARCGIS}/Sites_of_Special_Scientific_Interest_England/FeatureServer/0",
        max_records=5000,
    )
    return await _insert_constraints(pool, "sssi", features)


async def ingest_ancient_woodland(pool) -> int:
    """Ancient Woodland from Natural England."""
    features = await _fetch_arcgis_features(
        f"{NE_ARCGIS}/Ancient_Woodland_England/FeatureServer/0",
        max_records=5000,
    )
    return await _insert_constraints(pool, "ancient_woodland", features)


async def ingest_flood_zones(pool) -> int:
    """Flood Zones 2 and 3 from Environment Agency."""
    # Flood Zone 3
    fz3 = await _fetch_arcgis_features(
        f"{EA_ARCGIS}/EA/FloodMapForPlanningRiversAndSeaFloodZone3/MapServer/0",
        max_records=2000,
    )
    count = await _insert_constraints(pool, "flood_zone_3", fz3)

    # Flood Zone 2
    fz2 = await _fetch_arcgis_features(
        f"{EA_ARCGIS}/EA/FloodMapForPlanningRiversAndSeaFloodZone2/MapServer/0",
        max_records=2000,
    )
    count += await _insert_constraints(pool, "flood_zone_2", fz2)
    return count


async def ingest_conservation_areas(pool) -> int:
    """Conservation Areas from Historic England."""
    features = await _fetch_arcgis_features(
        f"{HE_ARCGIS}/Conservation_Areas/FeatureServer/0",
        max_records=5000,
    )
    return await _insert_constraints(pool, "conservation_area", features)


async def ingest_energy_planning_apps(pool) -> int:
    """Energy-related planning applications from planning.data.gov.uk."""
    count = 0
    async with httpx.AsyncClient(timeout=30) as client:
        for search_term in ["solar farm", "battery storage", "wind farm", "solar park", "energy storage"]:
            try:
                resp = await client.get(
                    f"{PLANNING_DATA}/entity.json",
                    params={
                        "dataset": "planning-application",
                        "limit": 200,
                        "search": search_term,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    entities = data.get("entities", [])
                    for entity in entities:
                        if entity.get("point"):
                            coords = entity["point"].replace("POINT(", "").replace(")", "").split()
                            if len(coords) == 2:
                                try:
                                    await pool.execute("""
                                        INSERT INTO planning_applications
                                            (reference, description, status, lat, lon, geometry, metadata)
                                        VALUES ($1, $2, $3, $4, $5,
                                            ST_SetSRID(ST_Point($5, $4), 4326),
                                            $6::jsonb)
                                        ON CONFLICT DO NOTHING
                                    """,
                                        entity.get("reference", f"PD-{entity.get('entity','')}"),
                                        entity.get("name", search_term),
                                        entity.get("planning-decision", "unknown"),
                                        float(coords[1]), float(coords[0]),
                                        json.dumps({k: v for k, v in entity.items() if k not in ("point",)}, default=str),
                                    )
                                    count += 1
                                except Exception:
                                    pass
            except Exception as e:
                log.debug("Planning app fetch for '%s' failed: %s", search_term, e)

    return count
