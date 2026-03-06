"""CIM Asset Library API — CRUD, import/export, schema info.

IEC 61970 compliant endpoints for managing the Princeps asset library.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.deps import get_pool
from models.cim.profiles import CIMProfile, get_cgmes_profiles
from utils import cim_asset_store as store
from utils.cim_serializer import (
    _CIM_CLASS_MAP,
    from_jsonld,
    from_rdf_xml,
    to_jsonld,
    to_rdf_xml,
)

log = logging.getLogger("princeps.cim_api")

router = APIRouter(prefix="/api/cim", tags=["cim"])


# ═══════════════════════════════════════════════════════════════════════════
# Asset CRUD
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/assets")
async def list_assets(
    asset_type: str | None = None,
    source: str | None = None,
    search: str | None = None,
    min_lon: float | None = None,
    min_lat: float | None = None,
    max_lon: float | None = None,
    max_lat: float | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List/search CIM assets with optional type, source, bbox, and text filters."""
    bbox = None
    if all(v is not None for v in (min_lon, min_lat, max_lon, max_lat)):
        bbox = (min_lon, min_lat, max_lon, max_lat)

    async with pool.acquire() as conn:
        items = await store.list_assets(
            conn,
            asset_type=asset_type,
            source=source,
            bbox=bbox,
            search=search,
            limit=limit,
            offset=offset,
        )
    return {"assets": items, "count": len(items), "offset": offset, "limit": limit}


@router.get("/assets/stats")
async def asset_stats(pool: asyncpg.Pool = Depends(get_pool)):
    """Asset counts by type and source."""
    async with pool.acquire() as conn:
        return await store.count_assets(conn)


@router.get("/assets/{mrid}")
async def get_asset(mrid: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Get a single asset with its terminals."""
    async with pool.acquire() as conn:
        result = await store.get_asset_with_terminals(conn, mrid)
    if not result:
        raise HTTPException(404, f"Asset {mrid} not found")
    return result


@router.post("/assets")
async def create_asset(body: dict, pool: asyncpg.Pool = Depends(get_pool)):
    """Create or update a single CIM asset.

    Body must include `asset_type` (CIM class name) and all required fields.
    """
    asset_type = body.pop("asset_type", None)
    source = body.pop("source", "manual")
    source_region = body.pop("source_region", None)
    tags = body.pop("tags", [])

    if not asset_type:
        raise HTTPException(400, "asset_type is required")

    cls = _CIM_CLASS_MAP.get(asset_type)
    if cls is None:
        raise HTTPException(400, f"Unknown asset type: {asset_type}")

    try:
        asset = cls(**body)
    except Exception as exc:
        raise HTTPException(422, f"Validation error: {exc}")

    async with pool.acquire() as conn:
        mrid = await store.upsert_asset(
            conn, asset, source=source, source_region=source_region, tags=tags
        )
    return {"mrid": mrid, "asset_type": asset_type}


@router.delete("/assets/{mrid}")
async def delete_asset(mrid: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Delete an asset and its terminals."""
    async with pool.acquire() as conn:
        deleted = await store.delete_asset(conn, mrid)
    if not deleted:
        raise HTTPException(404, f"Asset {mrid} not found")
    return {"deleted": mrid}


# ═══════════════════════════════════════════════════════════════════════════
# Bulk operations
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/assets/bulk")
async def bulk_upsert(
    body: dict,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Bulk upsert assets. Body: { "assets": [...], "source": "...", "source_region": "..." }"""
    raw_assets = body.get("assets", [])
    source = body.get("source", "bulk")
    source_region = body.get("source_region")

    created = []
    errors = []
    for i, item in enumerate(raw_assets):
        asset_type = item.pop("asset_type", None)
        cls = _CIM_CLASS_MAP.get(asset_type or "")
        if cls is None:
            errors.append({"index": i, "error": f"Unknown type: {asset_type}"})
            continue
        try:
            asset = cls(**item)
            async with pool.acquire() as conn:
                await store.upsert_asset(conn, asset, source=source, source_region=source_region)
            created.append(asset.mrid)
        except Exception as exc:
            errors.append({"index": i, "error": str(exc)})

    return {"created": len(created), "errors": errors}


# ═══════════════════════════════════════════════════════════════════════════
# Export
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/export/rdf-xml")
async def export_rdf_xml(
    profile: str = Query("EQ"),
    model_id: str | None = None,
    asset_type: str | None = None,
    source: str | None = None,
    description: str = "Princeps CIM Export",
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Export CIM assets to IEC 61970-552 RDF/XML."""
    try:
        cim_profile = CIMProfile(profile) if profile in [p.name for p in CIMProfile] else CIMProfile[profile]
    except (KeyError, ValueError):
        raise HTTPException(400, f"Unknown profile: {profile}")

    async with pool.acquire() as conn:
        items = await store.list_assets(conn, asset_type=asset_type, source=source, limit=10000)

    models = _group_assets(items)
    mid = model_id or f"urn:uuid:{uuid.uuid4()}"
    xml_bytes = to_rdf_xml(models, profile=cim_profile, model_id=mid, description=description)

    # Log export
    async with pool.acquire() as conn:
        await store.log_export(conn, mid, profile, "rdf_xml", len(items), description)

    return Response(
        content=xml_bytes,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="princeps-{profile}.xml"'},
    )


@router.get("/export/jsonld")
async def export_jsonld(
    profile: str = Query("EQ"),
    model_id: str | None = None,
    asset_type: str | None = None,
    source: str | None = None,
    description: str = "Princeps CIM Export",
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Export CIM assets to IEC 61970-556 JSON-LD."""
    try:
        cim_profile = CIMProfile(profile) if profile in [p.name for p in CIMProfile] else CIMProfile[profile]
    except (KeyError, ValueError):
        raise HTTPException(400, f"Unknown profile: {profile}")

    async with pool.acquire() as conn:
        items = await store.list_assets(conn, asset_type=asset_type, source=source, limit=10000)

    models = _group_assets(items)
    mid = model_id or f"urn:uuid:{uuid.uuid4()}"
    jsonld = to_jsonld(models, profile=cim_profile, model_id=mid, description=description)

    async with pool.acquire() as conn:
        await store.log_export(conn, mid, profile, "jsonld", len(items), description)

    return Response(
        content=json.dumps(jsonld, indent=2),
        media_type="application/ld+json",
        headers={"Content-Disposition": f'attachment; filename="princeps-{profile}.jsonld"'},
    )


def _group_assets(items: list[dict]) -> dict[str, list]:
    """Group flat asset list by type, constructing Pydantic models."""
    from utils.cim_serializer import _pluralize

    groups: dict[str, list] = {}
    for item in items:
        cls = _CIM_CLASS_MAP.get(item["asset_type"])
        if cls is None:
            continue
        try:
            obj = cls(**item["data"])
            key = _pluralize(item["asset_type"])
            groups.setdefault(key, []).append(obj)
        except Exception:
            pass
    return groups


# ═══════════════════════════════════════════════════════════════════════════
# Import
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/import/rdf-xml")
async def import_rdf_xml(
    file: UploadFile = File(...),
    source: str = Query("import"),
    source_region: str | None = None,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Import CIM RDF/XML file into the asset library."""
    content = await file.read()
    try:
        parsed = from_rdf_xml(content)
    except Exception as exc:
        raise HTTPException(400, f"Failed to parse CIM RDF/XML: {exc}")

    total = 0
    async with pool.acquire() as conn:
        for _collection, items in parsed.items():
            total += await store.upsert_assets_bulk(
                conn, items, source=source, source_region=source_region
            )

    return {"imported": total, "collections": {k: len(v) for k, v in parsed.items()}}


@router.post("/import/jsonld")
async def import_jsonld(
    body: dict,
    source: str = Query("import"),
    source_region: str | None = None,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Import CIM JSON-LD into the asset library."""
    try:
        parsed = from_jsonld(body)
    except Exception as exc:
        raise HTTPException(400, f"Failed to parse CIM JSON-LD: {exc}")

    total = 0
    async with pool.acquire() as conn:
        for _collection, items in parsed.items():
            total += await store.upsert_assets_bulk(
                conn, items, source=source, source_region=source_region
            )

    return {"imported": total, "collections": {k: len(v) for k, v in parsed.items()}}


@router.post("/import/nged")
async def import_nged(pool: asyncpg.Pool = Depends(get_pool)):
    """Migrate existing NGED data from nged_* tables into the CIM asset library."""
    async with pool.acquire() as conn:
        count = await store.import_from_nged(conn)
    return {"migrated": count, "source": "nged"}


# ═══════════════════════════════════════════════════════════════════════════
# Models (asset grouping)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/models")
async def list_models(pool: asyncpg.Pool = Depends(get_pool)):
    """List all export models."""
    async with pool.acquire() as conn:
        models = await store.list_models(conn)
    return {"models": models}


@router.post("/models")
async def create_model(body: dict, pool: asyncpg.Pool = Depends(get_pool)):
    """Create a model (named group of assets for export).

    Body: { "model_id": "...", "description": "...", "asset_mrids": [...], "profile": "EQ" }
    """
    model_id = body.get("model_id", f"urn:uuid:{uuid.uuid4()}")
    description = body.get("description", "")
    asset_mrids = body.get("asset_mrids", [])
    profile = body.get("profile", "EQ")

    if not asset_mrids:
        raise HTTPException(400, "asset_mrids list required")

    async with pool.acquire() as conn:
        await store.create_model(conn, model_id, description, asset_mrids, profile)
    return {"model_id": model_id, "asset_count": len(asset_mrids)}


@router.get("/models/{model_id}/export")
async def export_model(
    model_id: str,
    format: str = Query("rdf_xml"),
    profile: str = Query("EQ"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Export a specific model's assets."""
    async with pool.acquire() as conn:
        items = await store.get_model_assets(conn, model_id)

    if not items:
        raise HTTPException(404, f"Model {model_id} not found or empty")

    models = _group_assets(items)

    try:
        cim_profile = CIMProfile[profile]
    except KeyError:
        raise HTTPException(400, f"Unknown profile: {profile}")

    if format == "jsonld":
        jsonld = to_jsonld(models, profile=cim_profile, model_id=model_id)
        return Response(
            content=json.dumps(jsonld, indent=2),
            media_type="application/ld+json",
        )
    else:
        xml_bytes = to_rdf_xml(models, profile=cim_profile, model_id=model_id)
        return Response(content=xml_bytes, media_type="application/xml")


# ═══════════════════════════════════════════════════════════════════════════
# Schema info
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/schema/profiles")
async def schema_profiles():
    """List available CGMES profiles and their model classes."""
    profiles = get_cgmes_profiles()
    return {
        "profiles": [
            {
                "name": p.name,
                "value": p.value,
                "class_count": len(classes),
                "classes": [c.__name__ for c in classes],
            }
            for p, classes in profiles.items()
        ]
    }


@router.get("/schema/types")
async def schema_types():
    """List all supported CIM types with their fields."""
    result = []
    for name, cls in _CIM_CLASS_MAP.items():
        fields = {}
        for fname, finfo in cls.model_fields.items():
            fields[fname] = {
                "type": str(finfo.annotation),
                "required": finfo.is_required(),
                "default": finfo.default if not finfo.is_required() else None,
            }
        result.append({"type": name, "fields": fields})
    return {"types": result}
