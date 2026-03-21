"""Vision AI router -- image upload, Claude Vision analysis, deep GeoAI pipeline."""

from __future__ import annotations

import base64
import json
import logging
import math
from io import BytesIO
from uuid import UUID, uuid4

import anthropic
import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.deps import get_pool, get_claude
from app.helpers import (
    CLAUDE_MODEL, MAPBOX_TOKEN,
    run_geoai_subprocess, run_torchgeo_subprocess, run_geeflow_subprocess,
    run_clay_subprocess,
    _aggregate_deep_findings, _compute_sun_paths, _compute_satellite_tile,
)
import jobs

log = logging.getLogger("princeps.vision")

router = APIRouter(tags=["vision"])

# ---------------------------------------------------------------------------
# In-memory upload store
# ---------------------------------------------------------------------------
_vision_uploads: dict[str, dict] = {}

_VISION_ALLOWED = {"image/jpeg", "image/png", "image/tiff", "image/webp"}

VISION_PROMPT = """\
You are an expert site suitability analyst. Analyse this image of a potential \
energy infrastructure site and return ONLY a JSON object with these exact fields:

{
  "terrain_flatness": 0-100,
  "shading_risk": 0-100,
  "access_routes": 0-100,
  "flood_indicators": 0-100,
  "vegetation_density": 0-100,
  "existing_infrastructure": 0-100,
  "usable_area_pct": 0-100,
  "exclusion_zones": [{"type": "string", "reason": "string"}],
  "suitability_score": 0-100,
  "verdict": "GO" | "CAUTION" | "NO-GO",
  "confidence": 0.0-1.0,
  "summary": "2-3 sentence assessment",
  "domain_contributions": {
    "terrain": {"adjustment": -10 to +10, "note": "string"},
    "environmental": {"adjustment": -10 to +10, "note": "string"},
    "planning": {"adjustment": -10 to +10, "note": "string"},
    "grid": {"adjustment": -10 to +10, "note": "string"}
  }
}

Score meanings: terrain_flatness 100=perfectly flat, shading_risk 100=heavily shaded, \
access_routes 100=excellent access, flood_indicators 100=high flood risk, \
vegetation_density 100=dense vegetation, existing_infrastructure 100=significant structures present.
Only output valid JSON -- no markdown, no explanation text.
"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/vision/upload")
async def vision_upload(
    file: UploadFile,
    lat: float = Query(None),
    lon: float = Query(None),
    parcel_id: str = Query(None),
):
    """Upload an image for Vision AI analysis."""
    content_type = file.content_type or ""
    if content_type not in _VISION_ALLOWED:
        raise HTTPException(status_code=400, detail=f"Unsupported type {content_type}. Accepted: JPEG, PNG, TIFF, WebP")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    upload_id = uuid4().hex[:16]
    filename = file.filename or "image"

    # Extract dimensions via PIL if available
    dims = {"w": 0, "h": 0}
    geo_meta = {"lat": lat, "lon": lon, "altitude_m": None}
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS, GPSTAGS
        img = Image.open(BytesIO(content))
        dims = {"w": img.width, "h": img.height}
        # Extract EXIF GPS
        exif = img._getexif() or {}
        gps_info = {}
        for tag_id, val in exif.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == "GPSInfo":
                for gps_tag_id, gps_val in val.items():
                    gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                    gps_info[gps_tag] = gps_val
        if "GPSLatitude" in gps_info and "GPSLongitude" in gps_info:
            def _dms_to_dd(dms, ref):
                d, m, s = [float(x) for x in dms]
                dd = d + m / 60 + s / 3600
                return -dd if ref in ("S", "W") else dd
            exif_lat = _dms_to_dd(gps_info["GPSLatitude"], gps_info.get("GPSLatitudeRef", "N"))
            exif_lon = _dms_to_dd(gps_info["GPSLongitude"], gps_info.get("GPSLongitudeRef", "E"))
            if geo_meta["lat"] is None:
                geo_meta["lat"] = exif_lat
            if geo_meta["lon"] is None:
                geo_meta["lon"] = exif_lon
        if "GPSAltitude" in gps_info:
            geo_meta["altitude_m"] = float(gps_info["GPSAltitude"])
    except Exception:
        pass

    _vision_uploads[upload_id] = {
        "bytes": content,
        "filename": filename,
        "content_type": content_type,
        "dims": dims,
        "geo_metadata": geo_meta,
        "parcel_id": parcel_id,
    }

    return {
        "upload_id": upload_id,
        "filename": filename,
        "size_bytes": len(content),
        "content_type": content_type,
        "dimensions": dims,
        "geo_metadata": geo_meta,
    }


class VisionInstantRequest(BaseModel):
    upload_id: str
    lat: float | None = None
    lon: float | None = None
    parcel_id: str | None = None
    image_type: str = "satellite"  # drone, satellite, street_level, aerial


@router.post("/vision/analyse/instant")
async def vision_analyse_instant(
    body: VisionInstantRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    claude: anthropic.AsyncAnthropic = Depends(get_claude),
):
    """Run Claude Vision instant analysis on an uploaded image (~10s)."""
    upload = _vision_uploads.get(body.upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found -- upload image first via /vision/upload")

    img_bytes = upload["bytes"]
    ct = upload["content_type"]
    media_type = ct if ct in ("image/jpeg", "image/png", "image/webp") else "image/jpeg"
    b64 = base64.b64encode(img_bytes).decode()

    lat = body.lat or (upload["geo_metadata"] or {}).get("lat")
    lon = body.lon or (upload["geo_metadata"] or {}).get("lon")

    user_context = f"Image type: {body.image_type}."
    if lat and lon:
        user_context += f" Location: {lat:.5f}, {lon:.5f}."

    try:
        msg = await claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1200,
            temperature=0.0,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": f"{VISION_PROMPT}\n\n{user_context}"},
                ],
            }],
        )
        raw = msg.content[0].text
        # Parse JSON from response
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("No JSON object in Vision response")
        findings = json.loads(raw[start:end])
    except (anthropic.APIError, json.JSONDecodeError, ValueError) as exc:
        log.warning("Claude Vision instant analysis failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Vision analysis failed: {exc}")

    # Store in DB
    pid = body.parcel_id or upload.get("parcel_id")
    analysis_id = None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO vision_analyses
                    (parcel_id, upload_id, lat, lon, image_type, source, analysis_tier,
                     suitability_score, verdict, findings, domain_contributions, image_metadata, geometry)
                VALUES ($1, $2, $3, $4, $5, $6, 'instant', $7, $8, $9, $10, $11,
                        CASE WHEN $3 IS NOT NULL AND $4 IS NOT NULL
                             THEN ST_SetSRID(ST_MakePoint($4, $3), 4326) END)
                RETURNING analysis_id
            """,
                UUID(pid) if pid else None,
                body.upload_id,
                lat, lon,
                body.image_type,
                "upload",
                findings.get("suitability_score"),
                findings.get("verdict"),
                json.dumps(findings),
                json.dumps(findings.get("domain_contributions", {})),
                json.dumps(upload.get("geo_metadata", {})),
            )
            analysis_id = str(row["analysis_id"]) if row else None
    except Exception as exc:
        log.warning("Failed to store vision analysis: %s", exc)

    return {
        "analysis_id": analysis_id,
        "upload_id": body.upload_id,
        "tier": "instant",
        "suitability_score": findings.get("suitability_score"),
        "verdict": findings.get("verdict"),
        "confidence": findings.get("confidence"),
        "summary": findings.get("summary"),
        "findings": findings,
        "domain_contributions": findings.get("domain_contributions", {}),
    }


@router.get("/vision/site/{parcel_id}/analyses")
async def vision_list_analyses(
    parcel_id: str,
    limit: int = Query(20, le=100),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List vision analyses for a parcel."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid parcel_id")

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT analysis_id, upload_id, image_type, source, analysis_tier,
                   suitability_score, verdict, findings, domain_contributions,
                   deep_results, created_at
            FROM vision_analyses
            WHERE parcel_id = $1
            ORDER BY created_at DESC
            LIMIT $2
        """, pid, limit)

    return [
        {
            "analysis_id": str(r["analysis_id"]),
            "upload_id": r["upload_id"],
            "image_type": r["image_type"],
            "source": r["source"],
            "tier": r["analysis_tier"],
            "suitability_score": r["suitability_score"],
            "verdict": r["verdict"],
            "findings": json.loads(r["findings"]) if r["findings"] else None,
            "domain_contributions": json.loads(r["domain_contributions"]) if r["domain_contributions"] else None,
            "deep_results": json.loads(r["deep_results"]) if r["deep_results"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


class SatelliteFetchRequest(BaseModel):
    lat: float
    lon: float
    radius_km: float = 2.0


@router.post("/vision/fetch/satellite")
async def vision_fetch_satellite(body: SatelliteFetchRequest):
    """Fetch Mapbox satellite screenshots for a location."""
    if not MAPBOX_TOKEN:
        raise HTTPException(status_code=503, detail="MAPBOX_TOKEN not configured")

    upload_ids = []
    async with httpx.AsyncClient(timeout=30) as hx:
        for zoom in (16, 13):
            url = (
                f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/"
                f"{body.lon},{body.lat},{zoom},0/1280x1280@2x"
                f"?access_token={MAPBOX_TOKEN}"
            )
            try:
                resp = await hx.get(url)
                resp.raise_for_status()
                img_bytes = resp.content
                uid = uuid4().hex[:16]
                _vision_uploads[uid] = {
                    "bytes": img_bytes,
                    "filename": f"satellite_z{zoom}_{body.lat:.4f}_{body.lon:.4f}.jpg",
                    "content_type": "image/jpeg",
                    "dims": {"w": 2560, "h": 2560},
                    "geo_metadata": {"lat": body.lat, "lon": body.lon, "altitude_m": None},
                    "parcel_id": None,
                }
                upload_ids.append(uid)
            except Exception as exc:
                log.warning("Satellite fetch failed at zoom %d: %s", zoom, exc)

    return {"upload_ids": upload_ids, "lat": body.lat, "lon": body.lon}


class DeepAnalysisRequest(BaseModel):
    upload_id: str | None = None
    lat: float
    lon: float
    parcel_id: str | None = None
    modes: list[str] = ["building_footprints", "land_cover", "canopy_height", "infrastructure_detect"]


@router.post("/vision/analyse/deep")
async def vision_analyse_deep(
    body: DeepAnalysisRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Submit a deep GeoAI analysis as a background job."""

    async def _run_deep_vision(lat: float, lon: float, parcel_id: str | None, modes: list[str], upload_id: str | None):
        results = {}
        for mode in modes:
            try:
                r = await run_geoai_subprocess(mode, lat, lon, radius_km=2.0)
                results[mode] = r
            except Exception as exc:
                log.warning("Deep vision GeoAI mode %s failed: %s", mode, exc)
                results[mode] = {"error": str(exc)}

        # Aggregate into domain findings
        aggregated = _aggregate_deep_findings(results)

        # Store in DB
        try:
            pid = UUID(parcel_id) if parcel_id else None
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO vision_analyses
                        (parcel_id, upload_id, lat, lon, image_type, source, analysis_tier,
                         suitability_score, verdict, findings, deep_results, geometry)
                    VALUES ($1, $2, $3, $4, 'satellite', 'geoai', 'deep',
                            $5, $6, $7, $8,
                            ST_SetSRID(ST_MakePoint($4, $3), 4326))
                """,
                    pid, upload_id, lat, lon,
                    aggregated.get("suitability_score"),
                    aggregated.get("verdict"),
                    json.dumps(aggregated),
                    json.dumps(results),
                )
        except Exception as exc:
            log.warning("Failed to store deep vision results: %s", exc)

        return {"aggregated": aggregated, "mode_results": results}

    job = await jobs.submit(
        "deep_vision",
        _run_deep_vision,
        body.lat, body.lon, body.parcel_id, body.modes, body.upload_id,
    )
    return {"job_id": job.id, "status": "pending", "modes": body.modes}


class StreetViewRequest(BaseModel):
    lat: float
    lon: float


@router.post("/vision/fetch/street_view")
async def vision_fetch_street_view(body: StreetViewRequest):
    """Street-level imagery -- placeholder for future Mapillary integration."""
    return {
        "status": "not_yet_available",
        "providers": ["mapillary", "google_street_view"],
        "lat": body.lat,
        "lon": body.lon,
    }


@router.get("/vision/twin/{parcel_id}")
async def vision_twin_data(
    parcel_id: str,
    radius_m: float = Query(500, ge=100, le=2000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Assemble 3D digital twin data for a parcel."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid parcel_id")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon
            FROM parcels WHERE parcel_id = $1
        """, pid)
        if not row:
            raise HTTPException(status_code=404, detail="Parcel not found")
        lat, lon = float(row["lat"]), float(row["lon"])

        # Heightmap from DEM elevation raster (actual grid, not slope stats)
        hm_size = 64
        geojson_row = await conn.fetchrow(
            "SELECT ST_AsGeoJSON(geometry) AS geojson FROM parcels WHERE parcel_id = $1", pid
        )
        geojson = geojson_row["geojson"] if geojson_row else None
        heightmap = None
        if geojson:
            try:
                hm_result = await conn.fetchrow("""
                    WITH geom AS (
                        SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 27700) AS g
                    ),
                    clipped AS (
                        SELECT ST_Union(ST_Clip(d.rast, geom.g)) AS rast
                        FROM dem_elev d, geom
                        WHERE ST_Intersects(d.rast, geom.g)
                    ),
                    resized AS (
                        SELECT ST_Resize(rast, $2, $2) AS rast FROM clipped
                        WHERE rast IS NOT NULL
                    )
                    SELECT (ST_DumpValues(rast, 1)).valarray AS vals,
                           ST_Width(rast) AS width,
                           ST_Height(rast) AS height
                    FROM resized
                """, geojson, hm_size)
                if hm_result and hm_result["vals"] is not None:
                    heightmap = {
                        "width": hm_result["width"],
                        "height": hm_result["height"],
                        "values": hm_result["vals"],
                    }
            except Exception:
                pass
        # Fallback: synthetic heightmap when no DEM raster
        if heightmap is None:
            import random as _rng_mod
            rng = _rng_mod.Random(hash(parcel_id))
            base_elev = rng.uniform(20, 150)
            sx, sy = rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3)
            vals = []
            for r in range(hm_size):
                row_vals = []
                for c in range(hm_size):
                    e = base_elev + sx * (c - hm_size / 2) + sy * (r - hm_size / 2) + rng.gauss(0, 1.5)
                    row_vals.append(round(e, 1))
                vals.append(row_vals)
            heightmap = {"width": hm_size, "height": hm_size, "values": vals}

        # Solar layout
        layout_row = await conn.fetchrow(
            "SELECT layout_data FROM site_layouts WHERE parcel_id = $1", pid
        )
        solar_layout = json.loads(layout_row["layout_data"]) if layout_row else None

        # Latest vision detections
        vision_row = await conn.fetchrow("""
            SELECT findings, deep_results
            FROM vision_analyses
            WHERE parcel_id = $1
            ORDER BY created_at DESC LIMIT 1
        """, pid)
        vision_detections = None
        if vision_row:
            vision_detections = {
                "findings": json.loads(vision_row["findings"]) if vision_row["findings"] else None,
                "deep_results": json.loads(vision_row["deep_results"]) if vision_row["deep_results"] else None,
            }

        # Building footprints from latest deep analysis or empty
        buildings = None
        if vision_row and vision_row["deep_results"]:
            dr = json.loads(vision_row["deep_results"])
            bf = dr.get("building_footprints", {})
            if isinstance(bf, dict) and bf.get("geojson"):
                buildings = bf["geojson"]

        # Home retrofit geometry from latest assessment
        retrofit_geometry = None
        retro_row = await conn.fetchrow(
            """
            SELECT retrofit_geometry FROM home_retrofit_assessments
            WHERE parcel_id = $1 ORDER BY created_at DESC LIMIT 1
            """,
            pid,
        )
        if retro_row and retro_row["retrofit_geometry"]:
            rg = retro_row["retrofit_geometry"]
            retrofit_geometry = json.loads(rg) if isinstance(rg, str) else rg

    # Sun path calculation (simplified solar geometry)
    sun_path = _compute_sun_paths(lat, lon)

    # Satellite imagery tile URL for terrain texture
    satellite_tile = _compute_satellite_tile(lat, lon)

    return {
        "parcel_id": parcel_id,
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
        "heightmap": heightmap,
        "buildings": buildings,
        "solar_layout": solar_layout,
        "vision_detections": vision_detections,
        "retrofit_geometry": retrofit_geometry,
        "sun_path": sun_path,
        "satellite_tile": satellite_tile,
    }


# ---------------------------------------------------------------------------
# Google Open Buildings
# ---------------------------------------------------------------------------

@router.get("/api/vision/buildings")
async def get_buildings(
    lat: float = Query(52.5),
    lon: float = Query(-1.5),
    radius_m: float = Query(500, ge=50, le=5000),
):
    """
    Google Open Buildings footprints near a location.

    Returns GeoJSON FeatureCollection of building polygons with
    area_m2, confidence, and estimated height. Uses GEE subprocess.
    """
    from utils.open_buildings import get_building_footprints
    return await get_building_footprints(lat, lon, radius_m)


@router.get("/api/vision/buildings/summary")
async def get_buildings_summary(
    lat: float = Query(52.5),
    lon: float = Query(-1.5),
    radius_m: float = Query(1000, ge=100, le=10000),
):
    """
    Building density summary for planning constraint assessment.

    Returns classification (urban/suburban/rural), density,
    planning risk level, and rooftop solar potential estimate.
    """
    from utils.open_buildings import get_building_summary
    return await get_building_summary(lat, lon, radius_m)


@router.get("/vision/layers/{parcel_id}")
async def vision_layers(
    parcel_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Convert vision analysis results to map-injectable GeoJSON layers."""
    try:
        pid = UUID(parcel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid parcel_id")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT findings, deep_results, lat, lon
            FROM vision_analyses
            WHERE parcel_id = $1
            ORDER BY created_at DESC LIMIT 1
        """, pid)

    if not row:
        return {"layers": []}

    layers = []
    lat, lon = row["lat"] or 0, row["lon"] or 0

    # Deep results -> building footprints, exclusion zones
    if row["deep_results"]:
        dr = json.loads(row["deep_results"])
        bf = dr.get("building_footprints", {})
        if isinstance(bf, dict) and bf.get("geojson"):
            layers.append({
                "id": f"vision-buildings-{parcel_id[:8]}",
                "layer_type": "fill",
                "color": "#78909c",
                "geojson": bf["geojson"],
            })

    # Instant findings -> exclusion zones + usable area as point markers
    if row["findings"]:
        findings = json.loads(row["findings"])
        exclusions = findings.get("exclusion_zones", [])
        if exclusions and lat and lon:
            features = []
            for i, ez in enumerate(exclusions):
                # Create small polygon around point for exclusion zone
                offset = 0.001 * (i + 1)
                features.append({
                    "type": "Feature",
                    "properties": {"type": ez.get("type", "exclusion"), "reason": ez.get("reason", "")},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [lon - offset, lat - offset], [lon + offset, lat - offset],
                            [lon + offset, lat + offset], [lon - offset, lat + offset],
                            [lon - offset, lat - offset],
                        ]],
                    },
                })
            if features:
                layers.append({
                    "id": f"vision-exclusions-{parcel_id[:8]}",
                    "layer_type": "fill",
                    "color": "#da1e28",
                    "geojson": {"type": "FeatureCollection", "features": features},
                })

    return {"layers": layers}


# ---------------------------------------------------------------------------
# TorchGeo — pretrained satellite classification endpoints
# ---------------------------------------------------------------------------

class TorchGeoClassifyRequest(BaseModel):
    lat: float
    lon: float
    radius_m: float = 500
    model: str = "resnet50"
    year: int = 2024


@router.post("/api/vision/torchgeo-classify")
async def torchgeo_classify(body: TorchGeoClassifyRequest):
    """Run torchgeo land cover classification on Sentinel-2 imagery.

    1. Downloads a Sentinel-2 composite via GEE (reuses geeflow subprocess).
    2. Runs torchgeo pretrained model classification.
    3. Returns land cover percentages, ALC hint, and development suitability.
    """
    import tempfile
    import os

    radius_km = body.radius_m / 1000.0

    # Step 1: Download Sentinel-2 GeoTIFF via GEE
    try:
        gee_result = await run_geeflow_subprocess(
            mode="vegetation",  # gets Sentinel-2 NDVI which includes the raw bands
            lat=body.lat,
            lon=body.lon,
            radius_km=radius_km,
            year=body.year,
            timeout=120,
        )
    except Exception as exc:
        log.warning("GEE fetch for torchgeo failed: %s", exc)
        gee_result = None

    # Step 2: If GEE returned a GeoTIFF path, use it; otherwise check for cached file
    image_path = None
    if gee_result and isinstance(gee_result, dict):
        image_path = gee_result.get("geotiff_path") or gee_result.get("image_path")

    # Step 3: Run torchgeo classification
    if image_path and os.path.exists(image_path):
        result = await run_torchgeo_subprocess({
            "command": "classify_landcover",
            "image_path": image_path,
            "model": body.model,
        })
    else:
        # No GeoTIFF available — run list_models to confirm torchgeo status
        # and return GEE-derived land cover if available
        tg_status = await run_torchgeo_subprocess({"command": "list_models"})

        # Fall back to GEE DynamicWorld land cover (already available)
        try:
            dw_result = await run_geeflow_subprocess(
                mode="land_use",
                lat=body.lat,
                lon=body.lon,
                radius_km=radius_km,
                year=body.year,
                timeout=120,
            )
        except Exception:
            dw_result = None

        result = {
            "status": "fallback_gee",
            "note": "No local GeoTIFF available — using GEE DynamicWorld classification",
            "torchgeo_available": tg_status.get("torchgeo_available", False),
            "gee_land_cover": dw_result,
            "lat": body.lat,
            "lon": body.lon,
            "radius_m": body.radius_m,
        }

    result["lat"] = body.lat
    result["lon"] = body.lon
    result["radius_m"] = body.radius_m
    return result


class TorchGeoChangeRequest(BaseModel):
    lat: float
    lon: float
    radius_m: float = 500
    year_before: int = 2020
    year_after: int = 2024


@router.post("/api/vision/torchgeo-change")
async def torchgeo_change_detection(body: TorchGeoChangeRequest):
    """Run change detection comparing two time periods on Sentinel-2 imagery."""
    radius_km = body.radius_m / 1000.0

    # Download before/after imagery via GEE
    before_result = None
    after_result = None
    try:
        before_result = await run_geeflow_subprocess(
            mode="vegetation", lat=body.lat, lon=body.lon,
            radius_km=radius_km, year=body.year_before, timeout=120,
        )
        after_result = await run_geeflow_subprocess(
            mode="vegetation", lat=body.lat, lon=body.lon,
            radius_km=radius_km, year=body.year_after, timeout=120,
        )
    except Exception as exc:
        log.warning("GEE fetch for change detection failed: %s", exc)

    import os
    before_path = before_result.get("geotiff_path") if before_result else None
    after_path = after_result.get("geotiff_path") if after_result else None

    if before_path and after_path and os.path.exists(before_path) and os.path.exists(after_path):
        result = await run_torchgeo_subprocess({
            "command": "change_detection",
            "before_path": before_path,
            "after_path": after_path,
        })
    else:
        # Fall back to GEE DynamicWorld comparison
        try:
            dw_before = await run_geeflow_subprocess(
                mode="land_use", lat=body.lat, lon=body.lon,
                radius_km=radius_km, year=body.year_before, timeout=120,
            )
            dw_after = await run_geeflow_subprocess(
                mode="land_use", lat=body.lat, lon=body.lon,
                radius_km=radius_km, year=body.year_after, timeout=120,
            )
        except Exception:
            dw_before, dw_after = None, None

        # Compute changes from GEE DynamicWorld results
        changes = {}
        if dw_before and dw_after:
            before_pcts = dw_before.get("class_percentages", {})
            after_pcts = dw_after.get("class_percentages", {})
            all_cls = set(before_pcts.keys()) | set(after_pcts.keys())
            for cls in sorted(all_cls):
                bp = before_pcts.get(cls, 0)
                ap = after_pcts.get(cls, 0)
                delta = round(ap - bp, 1)
                if abs(delta) > 0.5:
                    changes[cls] = {"before_pct": bp, "after_pct": ap, "delta_pct": delta}

        result = {
            "status": "fallback_gee",
            "note": "No local GeoTIFFs — using GEE DynamicWorld comparison",
            "year_before": body.year_before,
            "year_after": body.year_after,
            "before_land_cover": dw_before,
            "after_land_cover": dw_after,
            "changes": changes,
        }

    result["lat"] = body.lat
    result["lon"] = body.lon
    result["radius_m"] = body.radius_m
    return result


class TorchGeoCropRequest(BaseModel):
    lat: float
    lon: float
    radius_m: float = 500
    model: str = "resnet50"
    year: int = 2024


@router.post("/api/vision/torchgeo-crop")
async def torchgeo_crop_classification(body: TorchGeoCropRequest):
    """Classify crops/vegetation for Agricultural Land Classification (ALC) assessment."""
    import os

    radius_km = body.radius_m / 1000.0

    # Fetch imagery
    try:
        gee_result = await run_geeflow_subprocess(
            mode="vegetation", lat=body.lat, lon=body.lon,
            radius_km=radius_km, year=body.year, timeout=120,
        )
    except Exception as exc:
        log.warning("GEE fetch for crop classification failed: %s", exc)
        gee_result = None

    image_path = gee_result.get("geotiff_path") if gee_result else None

    if image_path and os.path.exists(image_path):
        result = await run_torchgeo_subprocess({
            "command": "crop_classification",
            "image_path": image_path,
            "model": body.model,
        })
    else:
        # Fall back: use GEE vegetation data for ALC estimation
        try:
            veg = await run_geeflow_subprocess(
                mode="vegetation", lat=body.lat, lon=body.lon,
                radius_km=radius_km, year=body.year, timeout=120,
            )
            lc = await run_geeflow_subprocess(
                mode="land_use", lat=body.lat, lon=body.lon,
                radius_km=radius_km, year=body.year, timeout=120,
            )
        except Exception:
            veg, lc = None, None

        ndvi_mean = 0.0
        if veg and "ndvi_stats" in veg:
            ndvi_mean = veg["ndvi_stats"].get("mean", 0)

        cropland_pct = 0.0
        if lc and "class_percentages" in lc:
            cp = lc["class_percentages"]
            cropland_pct = cp.get("crops", 0) + cp.get("grass", 0)

        # Simple ALC estimation
        if cropland_pct > 50 and ndvi_mean > 0.5:
            alc_grade = "Grade 1-2"
            alc_note = "High-quality agricultural land (BMV)"
        elif cropland_pct > 30 and ndvi_mean > 0.3:
            alc_grade = "Grade 2-3a"
            alc_note = "Good quality agricultural land"
        elif cropland_pct > 15:
            alc_grade = "Grade 3b-4"
            alc_note = "Moderate quality — generally acceptable for development"
        else:
            alc_grade = "Grade 4-5"
            alc_note = "Poor / non-agricultural — no ALC constraint"

        result = {
            "status": "fallback_gee",
            "note": "No local GeoTIFF — using GEE-derived ALC estimation",
            "estimated_alc_grade": alc_grade,
            "alc_note": alc_note,
            "is_bmv": alc_grade in ("Grade 1-2", "Grade 2-3a"),
            "cropland_pct": round(cropland_pct, 1),
            "ndvi_mean": round(ndvi_mean, 3),
            "gee_vegetation": veg,
            "gee_land_cover": lc,
        }

    result["lat"] = body.lat
    result["lon"] = body.lon
    result["radius_m"] = body.radius_m
    return result


@router.get("/api/vision/torchgeo-models")
async def torchgeo_list_models():
    """List available torchgeo models and check installation status."""
    return await run_torchgeo_subprocess({"command": "list_models"})


# ---------------------------------------------------------------------------
# Clay Foundation Model — spectral analysis & embeddings
# ---------------------------------------------------------------------------

class ClayAnalyseRequest(BaseModel):
    lat: float
    lon: float
    radius_m: float = 500


@router.post("/api/vision/clay-analyse")
async def clay_analyse(
    body: ClayAnalyseRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Clay Foundation Model analysis — embeddings, suitability, similarity.

    Runs spectral analysis on Sentinel-2 imagery via GEE to produce:
    - Land suitability score (0-100) with component breakdown
    - Spectral feature embedding for similarity search
    - Development recommendations
    """
    lat, lon, radius_m = body.lat, body.lon, body.radius_m

    # Run suitability scoring via subprocess
    try:
        suitability = await run_clay_subprocess("suitability", lat, lon, radius_m)
    except Exception as exc:
        log.warning("Clay suitability subprocess failed: %s", exc)
        suitability = {"error": str(exc)}

    # Run embedding extraction via subprocess
    try:
        embedding_result = await run_clay_subprocess("embedding", lat, lon, radius_m)
    except Exception as exc:
        log.warning("Clay embedding subprocess failed: %s", exc)
        embedding_result = {"error": str(exc)}

    embedding = embedding_result.get("embedding")

    # Similarity search: find sites with stored embeddings
    similar_sites = []
    if embedding and not embedding_result.get("error"):
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT lat, lon, clay_embedding, suitability_score, verdict
                    FROM clay_site_analyses
                    WHERE clay_embedding IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 200
                """)
                pool_data = []
                for r in rows:
                    emb = r["clay_embedding"]
                    if emb:
                        try:
                            stored_emb = json.loads(emb) if isinstance(emb, str) else emb
                            pool_data.append({
                                "lat": float(r["lat"]),
                                "lon": float(r["lon"]),
                                "embedding": stored_emb,
                                "suitability_score": r["suitability_score"],
                                "verdict": r["verdict"],
                            })
                        except (json.JSONDecodeError, TypeError):
                            pass

                if pool_data:
                    from utils.clay_model import find_similar_sites_by_embedding
                    similar_sites = find_similar_sites_by_embedding(
                        embedding, pool_data, limit=10
                    )
        except Exception as exc:
            log.debug("Clay similarity search skipped (table may not exist): %s", exc)

    # Persist analysis result
    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO clay_site_analyses
                    (lat, lon, radius_m, suitability_score, verdict,
                     components, spectral_indices, clay_embedding, source, geometry)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                        ST_SetSRID(ST_MakePoint($2, $1), 4326))
            """,
                lat, lon, radius_m,
                suitability.get("suitability_score"),
                suitability.get("verdict"),
                json.dumps(suitability.get("components", {})),
                json.dumps(suitability.get("spectral_indices", {})),
                json.dumps(embedding) if embedding else None,
                suitability.get("source", "clay_spectral_fallback_v1"),
            )
    except Exception as exc:
        log.warning("Failed to persist Clay analysis: %s", exc)

    return {
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
        "suitability": suitability,
        "embedding": {
            "vector": embedding,
            "dim": len(embedding) if embedding else 0,
            "model": embedding_result.get("model", "clay_fallback_v1"),
        } if not embedding_result.get("error") else {"error": embedding_result["error"]},
        "similar_sites": similar_sites,
    }
