"""
Natural England MAGIC + Historic England NHLE + BNG Register — ingesters.

Six MAGIC designation layers (AONB, SSSI, SAC, SPA, Ramsar, Ancient Woodland)
share a single ``magic_designations`` table. NHLE listed buildings / scheduled
monuments land in ``nhle_heritage_entries``. BNG Register sites in
``bng_register_sites``.

All data is OGL v3. Statutory basis cited in migration ``0014``.

WFS endpoints discovered at:
    https://environment.data.gov.uk/spatialdata/
    https://historicengland.org.uk/listing/the-list/

Usage
-----

CLI::

    python -m utils.substrate.nature_heritage_ingester aonb -0.3,51.3,0.3,51.7
    python -m utils.substrate.nature_heritage_ingester all  -0.3,51.3,0.3,51.7

Library::

    from utils.substrate.nature_heritage_ingester import ingest_layer_bbox
    await ingest_layer_bbox(pool, "aonb", bbox)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

import httpx

log = logging.getLogger("princeps.nature_heritage")

SOURCE = "nature_heritage"

# Defra Spatial Data WFS base — per-dataset path, version 2.0.0, GeoJSON out.
_MAGIC_URLS = {
    "aonb":             "https://environment.data.gov.uk/spatialdata/areas-of-outstanding-natural-beauty-england/wfs",
    "sssi":             "https://environment.data.gov.uk/spatialdata/sites-of-special-scientific-interest-england/wfs",
    "sac":              "https://environment.data.gov.uk/spatialdata/special-areas-of-conservation-england/wfs",
    "spa":              "https://environment.data.gov.uk/spatialdata/special-protection-areas-england/wfs",
    "ramsar":           "https://environment.data.gov.uk/spatialdata/ramsar-sites-england/wfs",
    "ancient_woodland": "https://environment.data.gov.uk/spatialdata/ancient-woodland-england/wfs",
}

_NHLE_URL = "https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services/NHLE_listed_entries/FeatureServer/0/query"
_BNG_URL  = "https://environment.data.gov.uk/biodiversity-net-gain-register/api/register/sites"


async def fetch_magic_layer(
    layer: str, bbox: tuple[float, float, float, float],
    *, client: httpx.AsyncClient | None = None, timeout_s: float = 90.0,
) -> list[dict[str, Any]]:
    """Fetch a MAGIC designation layer inside a bbox."""
    if layer not in _MAGIC_URLS:
        raise ValueError(f"unknown MAGIC layer {layer!r}; known: {list(_MAGIC_URLS)}")
    url = _MAGIC_URLS[layer]
    min_lon, min_lat, max_lon, max_lat = bbox
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "outputFormat": "application/json", "srsName": "EPSG:4326",
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat},EPSG:4326",
    }
    owns = client is None
    if owns:
        client = httpx.AsyncClient(timeout=timeout_s, headers={
            "User-Agent": "Princeps nature-heritage ingester (contact@princeps.energy)",
            "Accept": "application/json",
        })
    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        log.warning("MAGIC %s fetch failed: %s", layer, e)
        return []
    finally:
        if owns:
            await client.aclose()
    features = payload.get("features") or []
    log.info("MAGIC %s: %d features", layer, len(features))
    return features


async def upsert_magic_features(
    pool, layer: str, features: list[dict[str, Any]],
) -> dict[str, int]:
    """Upsert MAGIC features into the shared ``magic_designations`` table."""
    if not features:
        return {"inserted": 0, "updated": 0}

    sql = """
        INSERT INTO magic_designations
            (layer, feature_id, name, area_ha, designated_date, condition,
             statutory_basis, source_updated_at, geom, raw)
        VALUES ($1, $2, $3, $4, $5::date, $6, $7, now(),
                ST_GeomFromGeoJSON($8)::geography, $9::jsonb)
        ON CONFLICT (layer, feature_id) DO UPDATE SET
            name = EXCLUDED.name,
            area_ha = EXCLUDED.area_ha,
            condition = EXCLUDED.condition,
            source_updated_at = EXCLUDED.source_updated_at,
            geom = EXCLUDED.geom,
            raw = EXCLUDED.raw
        RETURNING (xmax = 0) AS inserted
    """
    statutory_basis_by_layer = {
        "aonb":             "CRoW Act 2000; NPPF Dec 2024 para 182",
        "sssi":             "Wildlife & Countryside Act 1981",
        "sac":              "Habitats Regulations 2017 (amended 2019)",
        "spa":              "Conservation of Habitats and Species Regulations 2017",
        "ramsar":           "Ramsar Convention (UK signatory); SPA-equivalent",
        "ancient_woodland": "NPPF Dec 2024 para 187(c) — irreplaceable habitat",
    }
    basis = statutory_basis_by_layer.get(layer, "")

    inserted = updated = 0
    async with pool.acquire() as conn:
        for feat in features:
            props = feat.get("properties") or {}
            fid = str(feat.get("id") or props.get("OBJECTID") or props.get("FID") or "")
            if not fid:
                continue
            geom = feat.get("geometry")
            if not geom:
                continue
            name = props.get("NAME") or props.get("name") or props.get("SITE_NAME")
            area_ha = props.get("AREA_HA") or props.get("area_ha") or props.get("AREA")
            desig = props.get("DATE_DESIGNATED") or props.get("designated_date")
            condition = props.get("CONDITION") or props.get("condition") or props.get("OVERALL_CONDITION")
            try:
                row = await conn.fetchrow(
                    sql, layer, fid, name,
                    float(area_ha) if area_ha else None,
                    desig if desig else None,
                    condition,
                    basis,
                    json.dumps(geom),
                    json.dumps(props),
                )
                if row and row["inserted"]:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                log.warning("upsert MAGIC %s fid=%s failed: %s", layer, fid, e)
    return {"inserted": inserted, "updated": updated}


async def fetch_nhle_features(
    bbox: tuple[float, float, float, float],
    *, client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Fetch NHLE listed entries via HE ArcGIS FeatureServer."""
    min_lon, min_lat, max_lon, max_lat = bbox
    params = {
        "where": "1=1",
        "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outSR": "4326",
        "outFields": "*",
        "f": "geojson",
        "resultRecordCount": "5000",
    }
    owns = client is None
    if owns:
        client = httpx.AsyncClient(timeout=60.0, headers={
            "User-Agent": "Princeps nature-heritage ingester (contact@princeps.energy)",
        })
    try:
        resp = await client.get(_NHLE_URL, params=params)
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        log.warning("NHLE fetch failed: %s", e)
        return []
    finally:
        if owns:
            await client.aclose()
    features = payload.get("features") or []
    log.info("NHLE: %d features", len(features))
    return features


async def upsert_nhle_features(pool, features: list[dict[str, Any]]) -> dict[str, int]:
    """Upsert NHLE entries into ``nhle_heritage_entries``."""
    if not features:
        return {"inserted": 0, "updated": 0}

    sql = """
        INSERT INTO nhle_heritage_entries
            (list_entry_id, entry_class, name, grade, designated_date,
             local_planning_authority, source_updated_at, geom, raw)
        VALUES ($1, $2, $3, $4, $5::date, $6, now(),
                ST_GeomFromGeoJSON($7)::geography, $8::jsonb)
        ON CONFLICT (list_entry_id) DO UPDATE SET
            entry_class = EXCLUDED.entry_class,
            name = EXCLUDED.name,
            grade = EXCLUDED.grade,
            local_planning_authority = EXCLUDED.local_planning_authority,
            source_updated_at = EXCLUDED.source_updated_at,
            geom = EXCLUDED.geom,
            raw = EXCLUDED.raw
        RETURNING (xmax = 0) AS inserted
    """
    inserted = updated = 0
    async with pool.acquire() as conn:
        for feat in features:
            props = feat.get("properties") or {}
            list_id = str(props.get("ListEntry") or props.get("LISTENTRY") or props.get("OBJECTID") or "")
            if not list_id:
                continue
            geom = feat.get("geometry")
            if not geom:
                continue
            try:
                row = await conn.fetchrow(
                    sql,
                    list_id,
                    props.get("entry_class") or props.get("HeritageCategory") or "listed_building",
                    props.get("Name") or props.get("name"),
                    props.get("Grade") or props.get("grade"),
                    props.get("date_designated") or None,
                    props.get("lpa") or props.get("LocalPlanningAuthority"),
                    json.dumps(geom),
                    json.dumps(props),
                )
                if row and row["inserted"]:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                log.warning("upsert NHLE list_id=%s failed: %s", list_id, e)
    return {"inserted": inserted, "updated": updated}


async def fetch_bng_sites(*, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    """Fetch full BNG Register (paged). No bbox filter — the register is nationwide."""
    owns = client is None
    if owns:
        client = httpx.AsyncClient(timeout=60.0, headers={
            "User-Agent": "Princeps BNG register ingester (contact@princeps.energy)",
            "Accept": "application/json",
        })
    sites: list[dict[str, Any]] = []
    page = 1
    try:
        while True:
            resp = await client.get(_BNG_URL, params={"page": page, "limit": 100})
            resp.raise_for_status()
            payload = resp.json()
            batch = payload.get("sites") or payload.get("items") or []
            if not batch:
                break
            sites.extend(batch)
            if len(batch) < 100:
                break
            page += 1
            if page > 200:  # safety: cap at 20k sites
                break
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        log.warning("BNG register fetch failed on page %d: %s", page, e)
    finally:
        if owns:
            await client.aclose()
    log.info("BNG register: %d sites", len(sites))
    return sites


async def upsert_bng_sites(pool, sites: list[dict[str, Any]]) -> dict[str, int]:
    if not sites:
        return {"inserted": 0, "updated": 0}
    sql = """
        INSERT INTO bng_register_sites
            (register_reference, site_name, responsible_body, landowner,
             habitat_baseline_units, habitat_enhanced_units,
             hedgerow_units, watercourse_units, units_available_for_sale,
             management_start, management_end, lpa_code, status,
             source_updated_at, geom, raw)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::date, $11::date,
                $12, $13, now(), ST_GeomFromGeoJSON($14)::geography, $15::jsonb)
        ON CONFLICT (register_reference) DO UPDATE SET
            site_name = EXCLUDED.site_name,
            habitat_baseline_units = EXCLUDED.habitat_baseline_units,
            habitat_enhanced_units = EXCLUDED.habitat_enhanced_units,
            units_available_for_sale = EXCLUDED.units_available_for_sale,
            status = EXCLUDED.status,
            source_updated_at = EXCLUDED.source_updated_at,
            geom = EXCLUDED.geom,
            raw = EXCLUDED.raw
        RETURNING (xmax = 0) AS inserted
    """
    inserted = updated = 0
    async with pool.acquire() as conn:
        for s in sites:
            ref = s.get("register_reference") or s.get("reference") or s.get("id")
            if not ref:
                continue
            geom = s.get("geometry") or s.get("geom")
            try:
                row = await conn.fetchrow(
                    sql,
                    str(ref),
                    s.get("site_name") or s.get("name"),
                    s.get("responsible_body"),
                    s.get("landowner"),
                    _nfloat(s.get("habitat_baseline_units")),
                    _nfloat(s.get("habitat_enhanced_units")),
                    _nfloat(s.get("hedgerow_units")),
                    _nfloat(s.get("watercourse_units")),
                    _nfloat(s.get("units_available_for_sale")),
                    s.get("management_start"),
                    s.get("management_end"),
                    s.get("lpa_code") or s.get("lpa"),
                    s.get("status") or "registered",
                    json.dumps(geom) if geom else json.dumps({"type": "Point", "coordinates": [0, 0]}),
                    json.dumps(s),
                )
                if row and row["inserted"]:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                log.warning("upsert BNG ref=%s failed: %s", ref, e)
    return {"inserted": inserted, "updated": updated}


def _nfloat(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


async def ingest_layer_bbox(
    pool, layer: str, bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    """Ingest one layer. ``layer`` is a MAGIC slug, ``nhle``, or ``bng``.
    ``bbox`` is required for MAGIC + NHLE; ignored for BNG (full register)."""
    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            "INSERT INTO nature_heritage_ingest_log (layer, bbox, started_at) "
            "VALUES ($1, $2::jsonb, now()) RETURNING id",
            layer, json.dumps(list(bbox)) if bbox else None,
        )

    try:
        async with httpx.AsyncClient(timeout=90.0, headers={
            "User-Agent": "Princeps nature-heritage ingester (contact@princeps.energy)",
        }) as client:
            if layer in _MAGIC_URLS:
                if not bbox:
                    raise ValueError("MAGIC layers require bbox")
                feats = await fetch_magic_layer(layer, bbox, client=client)
                counts = await upsert_magic_features(pool, layer, feats)
            elif layer == "nhle":
                if not bbox:
                    raise ValueError("NHLE requires bbox")
                feats = await fetch_nhle_features(bbox, client=client)
                counts = await upsert_nhle_features(pool, feats)
            elif layer == "bng":
                sites = await fetch_bng_sites(client=client)
                counts = await upsert_bng_sites(pool, sites)
            else:
                raise ValueError(f"unknown layer {layer!r}")
    except Exception as e:
        log.exception("ingest layer=%s failed", layer)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE nature_heritage_ingest_log SET finished_at=now(), status='failed', "
                "error_message=$1 WHERE id=$2", str(e), run_id,
            )
        return {"layer": layer, "error": str(e)}

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE nature_heritage_ingest_log SET finished_at=now(), status='ok', "
            "rows_inserted=$1, rows_updated=$2 WHERE id=$3",
            counts["inserted"], counts["updated"], run_id,
        )
    return {"layer": layer, "bbox": bbox, **counts}


async def ingest_all_layers_bbox(pool, bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    """Run all MAGIC + NHLE for a bbox + full BNG register."""
    result: dict[str, Any] = {}
    for layer in list(_MAGIC_URLS.keys()) + ["nhle"]:
        result[layer] = await ingest_layer_bbox(pool, layer, bbox)
    result["bng"] = await ingest_layer_bbox(pool, "bng", None)
    return result


def _parse_bbox(s: str) -> tuple[float, float, float, float]:
    parts = [float(p) for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError(f"bbox must be minLon,minLat,maxLon,maxLat — got {s!r}")
    return tuple(parts)  # type: ignore[return-value]


async def _cli():
    if len(sys.argv) < 2:
        print("usage: python -m utils.substrate.nature_heritage_ingester <layer|all> [bbox]")
        print("  layer: aonb | sssi | sac | spa | ramsar | ancient_woodland | nhle | bng | all")
        sys.exit(2)

    layer = sys.argv[1]
    bbox = _parse_bbox(sys.argv[2]) if len(sys.argv) > 2 else None

    from app.deps import get_pool
    pool = await get_pool()
    try:
        if layer == "all":
            if not bbox:
                print("error: 'all' requires bbox")
                sys.exit(2)
            result = await ingest_all_layers_bbox(pool, bbox)
        else:
            result = await ingest_layer_bbox(pool, layer, bbox)
        print(json.dumps(result, indent=2, default=str))
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_cli())
