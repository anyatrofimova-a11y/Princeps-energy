"""Land management — site boundaries, land options, investment property tracking."""

from __future__ import annotations

import json
import math
from uuid import UUID
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import asyncpg

from app.deps import get_pool, get_optional_user

router = APIRouter(prefix="/api/v1/land", tags=["land-management"])


# ─── Models ───────────────────────────────────────────────────────────────────

class BoundaryCreateRequest(BaseModel):
    project_id: str | None = None
    name: str | None = None
    boundary_type: str = "site"  # site, exclusion, access, cable_route, substation_compound
    geojson: dict  # GeoJSON Feature or Polygon geometry
    metadata: dict | None = None


class BoundaryUpdateRequest(BaseModel):
    name: str | None = None
    boundary_type: str | None = None
    geojson: dict | None = None
    metadata: dict | None = None


class LandOptionRequest(BaseModel):
    project_id: str
    boundary_id: str | None = None
    landowner: str | None = None
    landowner_contact: str | None = None
    option_type: str = "option"  # option, lease, freehold, wayleave, easement
    status: str = "prospect"  # prospect, negotiating, heads_of_terms, exchanged, completed, expired, withdrawn
    option_fee_gbp: float | None = None
    annual_rent_gbp_ha: float | None = None
    term_years: int | None = None
    start_date: str | None = None
    expiry_date: str | None = None
    break_clause: str | None = None
    solicitor: str | None = None
    title_number: str | None = None
    tenure: str | None = None
    alc_grade: str | None = None
    notes: str | None = None
    metadata: dict | None = None


class LandOptionUpdateRequest(BaseModel):
    landowner: str | None = None
    landowner_contact: str | None = None
    status: str | None = None
    option_fee_gbp: float | None = None
    annual_rent_gbp_ha: float | None = None
    term_years: int | None = None
    start_date: str | None = None
    expiry_date: str | None = None
    break_clause: str | None = None
    solicitor: str | None = None
    title_number: str | None = None
    tenure: str | None = None
    alc_grade: str | None = None
    notes: str | None = None
    metadata: dict | None = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _extract_polygon_coords(geojson: dict) -> list:
    """Extract polygon coordinates from GeoJSON Feature or Geometry."""
    if geojson.get("type") == "Feature":
        geom = geojson.get("geometry", {})
    else:
        geom = geojson
    if geom.get("type") == "Polygon":
        return geom["coordinates"]
    return []


def _compute_area_m2(coords: list) -> float:
    """Compute polygon area from GeoJSON coordinates using Shoelace formula."""
    if not coords or not coords[0]:
        return 0
    ring = coords[0]
    n = len(ring)
    if n < 3:
        return 0
    # Earth radius at UK latitude (~52°N)
    lat_mid = sum(c[1] for c in ring) / n
    m_per_deg_lat = 111320
    m_per_deg_lon = 111320 * math.cos(math.radians(lat_mid))
    area = 0
    for i in range(n):
        j = (i + 1) % n
        x_i = ring[i][0] * m_per_deg_lon
        y_i = ring[i][1] * m_per_deg_lat
        x_j = ring[j][0] * m_per_deg_lon
        y_j = ring[j][1] * m_per_deg_lat
        area += x_i * y_j - x_j * y_i
    return abs(area) / 2


def _compute_perimeter_m(coords: list) -> float:
    """Compute polygon perimeter using haversine."""
    if not coords or not coords[0]:
        return 0
    ring = coords[0]
    total = 0
    R = 6371000
    for i in range(len(ring) - 1):
        lat1, lon1 = math.radians(ring[i][1]), math.radians(ring[i][0])
        lat2, lon2 = math.radians(ring[i+1][1]), math.radians(ring[i+1][0])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        total += R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return total


def _centroid(coords: list) -> tuple[float, float]:
    """Compute polygon centroid."""
    if not coords or not coords[0]:
        return 0, 0
    ring = coords[0]
    n = len(ring)
    lat = sum(c[1] for c in ring) / n
    lon = sum(c[0] for c in ring) / n
    return lat, lon


def _boundary_row(r) -> dict:
    return {
        "boundary_id": str(r["boundary_id"]),
        "project_id": str(r["project_id"]) if r["project_id"] else None,
        "parcel_id": str(r["parcel_id"]) if r["parcel_id"] else None,
        "name": r["name"],
        "boundary_type": r["boundary_type"],
        "area_m2": float(r["area_m2"]) if r["area_m2"] else None,
        "area_ha": float(r["area_ha"]) if r["area_ha"] else None,
        "perimeter_m": float(r["perimeter_m"]) if r["perimeter_m"] else None,
        "centroid_lat": float(r["centroid_lat"]) if r["centroid_lat"] else None,
        "centroid_lon": float(r["centroid_lon"]) if r["centroid_lon"] else None,
        "geojson": json.loads(r["geojson"]) if isinstance(r["geojson"], str) else r["geojson"],
        "metadata": json.loads(r["metadata"]) if r["metadata"] and isinstance(r["metadata"], str) else (r["metadata"] or {}),
        "created_at": r["created_at"].isoformat(),
    }


def _option_row(r) -> dict:
    return {
        "option_id": str(r["option_id"]),
        "project_id": str(r["project_id"]) if r["project_id"] else None,
        "boundary_id": str(r["boundary_id"]) if r["boundary_id"] else None,
        "landowner": r["landowner"],
        "landowner_contact": r["landowner_contact"],
        "option_type": r["option_type"],
        "status": r["status"],
        "option_fee_gbp": float(r["option_fee_gbp"]) if r["option_fee_gbp"] else None,
        "annual_rent_gbp_ha": float(r["annual_rent_gbp_ha"]) if r["annual_rent_gbp_ha"] else None,
        "term_years": r["term_years"],
        "start_date": r["start_date"].isoformat() if r["start_date"] else None,
        "expiry_date": r["expiry_date"].isoformat() if r["expiry_date"] else None,
        "break_clause": r["break_clause"],
        "solicitor": r["solicitor"],
        "title_number": r["title_number"],
        "tenure": r["tenure"],
        "alc_grade": r["alc_grade"],
        "notes": r["notes"],
        "created_at": r["created_at"].isoformat(),
    }


# ─── Boundary CRUD ────────────────────────────────────────────────────────────

BOUNDARY_TYPES = ["site", "exclusion", "access", "cable_route", "substation_compound", "laydown", "screening"]


@router.post("/boundaries")
async def create_boundary(body: BoundaryCreateRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """Save a drawn boundary polygon with computed area/perimeter."""
    coords = _extract_polygon_coords(body.geojson)
    area_m2 = _compute_area_m2(coords)
    area_ha = round(area_m2 / 10000, 2)
    perimeter_m = _compute_perimeter_m(coords)
    centroid_lat, centroid_lon = _centroid(coords)

    # Build PostGIS geometry from GeoJSON
    geom = body.geojson.get("geometry", body.geojson) if body.geojson.get("type") == "Feature" else body.geojson
    geojson_str = json.dumps(geom)

    project_id = UUID(body.project_id) if body.project_id else None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO site_boundaries
                   (project_id, name, boundary_type, geojson, area_m2, area_ha,
                    perimeter_m, centroid_lat, centroid_lon, geometry, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                       ST_SetSRID(ST_GeomFromGeoJSON($10), 4326), $11)
               RETURNING *""",
            project_id,
            body.name or f"{body.boundary_type.replace('_', ' ').title()} ({area_ha} ha)",
            body.boundary_type,
            json.dumps(body.geojson),
            area_m2, area_ha, round(perimeter_m, 1),
            centroid_lat, centroid_lon,
            geojson_str,
            json.dumps(body.metadata) if body.metadata else "{}",
        )
    return _boundary_row(row)


@router.get("/boundaries")
async def list_boundaries(
    project_id: str | None = Query(None),
    boundary_type: str | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List boundaries, optionally filtered by project and type."""
    conditions, params, idx = [], [], 1
    if project_id:
        conditions.append(f"project_id = ${idx}")
        params.append(UUID(project_id))
        idx += 1
    if boundary_type:
        conditions.append(f"boundary_type = ${idx}")
        params.append(boundary_type)
        idx += 1
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM site_boundaries {where} ORDER BY created_at DESC", *params
        )
    return [_boundary_row(r) for r in rows]


@router.get("/boundaries/{boundary_id}")
async def get_boundary(boundary_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Get a single boundary with full GeoJSON."""
    bid = UUID(boundary_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM site_boundaries WHERE boundary_id = $1", bid)
    if not row:
        raise HTTPException(404, "Boundary not found")
    return _boundary_row(row)


@router.patch("/boundaries/{boundary_id}")
async def update_boundary(
    boundary_id: str, body: BoundaryUpdateRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Update boundary geometry or metadata."""
    bid = UUID(boundary_id)
    updates, params, idx = [], [], 1

    if body.name is not None:
        updates.append(f"name = ${idx}"); params.append(body.name); idx += 1
    if body.boundary_type is not None:
        updates.append(f"boundary_type = ${idx}"); params.append(body.boundary_type); idx += 1
    if body.metadata is not None:
        updates.append(f"metadata = ${idx}"); params.append(json.dumps(body.metadata)); idx += 1

    if body.geojson is not None:
        coords = _extract_polygon_coords(body.geojson)
        area_m2 = _compute_area_m2(coords)
        area_ha = round(area_m2 / 10000, 2)
        perimeter_m = _compute_perimeter_m(coords)
        centroid_lat, centroid_lon = _centroid(coords)
        geom = body.geojson.get("geometry", body.geojson) if body.geojson.get("type") == "Feature" else body.geojson

        updates.append(f"geojson = ${idx}"); params.append(json.dumps(body.geojson)); idx += 1
        updates.append(f"area_m2 = ${idx}"); params.append(area_m2); idx += 1
        updates.append(f"area_ha = ${idx}"); params.append(area_ha); idx += 1
        updates.append(f"perimeter_m = ${idx}"); params.append(round(perimeter_m, 1)); idx += 1
        updates.append(f"centroid_lat = ${idx}"); params.append(centroid_lat); idx += 1
        updates.append(f"centroid_lon = ${idx}"); params.append(centroid_lon); idx += 1
        updates.append(f"geometry = ST_SetSRID(ST_GeomFromGeoJSON(${idx}), 4326)")
        params.append(json.dumps(geom)); idx += 1

    if not updates:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM site_boundaries WHERE boundary_id = $1", bid)
        if not row: raise HTTPException(404)
        return _boundary_row(row)

    updates.append("updated_at = NOW()")
    params.append(bid)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE site_boundaries SET {', '.join(updates)} WHERE boundary_id = ${idx} RETURNING *",
            *params,
        )
    if not row: raise HTTPException(404, "Boundary not found")
    return _boundary_row(row)


@router.delete("/boundaries/{boundary_id}")
async def delete_boundary(boundary_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Delete a boundary."""
    bid = UUID(boundary_id)
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM site_boundaries WHERE boundary_id = $1 RETURNING boundary_id", bid
        )
    if not deleted: raise HTTPException(404)
    return {"deleted": True, "boundary_id": boundary_id}


@router.get("/boundaries/{boundary_id}/analysis")
async def analyse_boundary(boundary_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Analyse a boundary — capacity estimate, land use, constraints, costs."""
    bid = UUID(boundary_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM site_boundaries WHERE boundary_id = $1", bid)
    if not row:
        raise HTTPException(404)

    area_ha = float(row["area_ha"]) if row["area_ha"] else 0
    lat = float(row["centroid_lat"]) if row["centroid_lat"] else 0
    lon = float(row["centroid_lon"]) if row["centroid_lon"] else 0

    # Capacity estimates by technology
    solar_mw = round(area_ha * 0.5, 1)  # ~2 ha/MW for UK ground-mount
    wind_mw = round(area_ha * 0.1, 1)   # ~10 ha/MW for onshore wind
    bess_mw = round(area_ha * 5, 1)     # ~0.2 ha/MW for BESS

    # Cost estimates
    solar_capex = round(solar_mw * 550_000)
    wind_capex = round(wind_mw * 1_250_000)
    bess_capex = round(bess_mw * 600_000)

    # Land cost estimate
    land_cost_ha = 30_000 if area_ha > 20 else 50_000  # bulk vs small
    total_land_cost = round(area_ha * land_cost_ha)

    # Annual rent benchmarks
    solar_rent = round(area_ha * 1_200)  # ~£1,200/ha/yr typical UK solar lease
    wind_rent = round(area_ha * 600)

    return {
        "boundary_id": boundary_id,
        "area_ha": area_ha,
        "area_acres": round(area_ha * 2.471, 1),
        "perimeter_m": float(row["perimeter_m"]) if row["perimeter_m"] else None,
        "centroid": {"lat": lat, "lon": lon},
        "capacity_estimates": {
            "solar_mw": solar_mw,
            "wind_mw": wind_mw,
            "bess_mw": bess_mw,
        },
        "capex_estimates": {
            "solar_gbp": solar_capex,
            "wind_gbp": wind_capex,
            "bess_gbp": bess_capex,
        },
        "land_costs": {
            "estimated_purchase_gbp": total_land_cost,
            "price_per_ha_gbp": land_cost_ha,
            "annual_rent_solar_gbp": solar_rent,
            "annual_rent_wind_gbp": wind_rent,
        },
        "development_density": {
            "solar_ha_per_mw": 2.0,
            "wind_ha_per_mw": 10.0,
            "bess_ha_per_mw": 0.2,
        },
    }


# ─── Land Options CRUD ───────────────────────────────────────────────────────

OPTION_TYPES = ["option", "lease", "freehold", "wayleave", "easement", "licence"]
OPTION_STATUSES = ["prospect", "negotiating", "heads_of_terms", "exchanged", "completed", "expired", "withdrawn"]


@router.post("/options")
async def create_land_option(body: LandOptionRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """Create a land option/lease record for a project."""
    pid = UUID(body.project_id)
    bid = UUID(body.boundary_id) if body.boundary_id else None
    start = date.fromisoformat(body.start_date) if body.start_date else None
    expiry = date.fromisoformat(body.expiry_date) if body.expiry_date else None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO land_options
                   (project_id, boundary_id, landowner, landowner_contact,
                    option_type, status, option_fee_gbp, annual_rent_gbp_ha,
                    term_years, start_date, expiry_date, break_clause,
                    solicitor, title_number, tenure, alc_grade, notes, metadata)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
               RETURNING *""",
            pid, bid, body.landowner, body.landowner_contact,
            body.option_type, body.status, body.option_fee_gbp,
            body.annual_rent_gbp_ha, body.term_years,
            start, expiry, body.break_clause,
            body.solicitor, body.title_number, body.tenure, body.alc_grade,
            body.notes, json.dumps(body.metadata) if body.metadata else "{}",
        )
    return _option_row(row)


@router.get("/options")
async def list_land_options(
    project_id: str | None = Query(None),
    status: str | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List land options, optionally filtered."""
    conditions, params, idx = [], [], 1
    if project_id:
        conditions.append(f"project_id = ${idx}")
        params.append(UUID(project_id))
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM land_options {where} ORDER BY created_at DESC", *params
        )
    return [_option_row(r) for r in rows]


@router.get("/options/{option_id}")
async def get_land_option(option_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Get a single land option."""
    oid = UUID(option_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM land_options WHERE option_id = $1", oid)
    if not row: raise HTTPException(404)
    return _option_row(row)


@router.patch("/options/{option_id}")
async def update_land_option(
    option_id: str, body: LandOptionUpdateRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Update a land option."""
    oid = UUID(option_id)
    updates, params, idx = [], [], 1

    for field in ["landowner", "landowner_contact", "status", "option_fee_gbp",
                  "annual_rent_gbp_ha", "term_years", "break_clause",
                  "solicitor", "title_number", "tenure", "alc_grade", "notes"]:
        val = getattr(body, field, None)
        if val is not None:
            updates.append(f"{field} = ${idx}")
            params.append(val)
            idx += 1

    if body.start_date is not None:
        updates.append(f"start_date = ${idx}")
        params.append(date.fromisoformat(body.start_date))
        idx += 1
    if body.expiry_date is not None:
        updates.append(f"expiry_date = ${idx}")
        params.append(date.fromisoformat(body.expiry_date))
        idx += 1
    if body.metadata is not None:
        updates.append(f"metadata = ${idx}")
        params.append(json.dumps(body.metadata))
        idx += 1

    if not updates:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM land_options WHERE option_id = $1", oid)
        if not row: raise HTTPException(404)
        return _option_row(row)

    updates.append("updated_at = NOW()")
    params.append(oid)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE land_options SET {', '.join(updates)} WHERE option_id = ${idx} RETURNING *",
            *params,
        )
    if not row: raise HTTPException(404)
    return _option_row(row)


@router.delete("/options/{option_id}")
async def delete_land_option(option_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Delete a land option."""
    oid = UUID(option_id)
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM land_options WHERE option_id = $1 RETURNING option_id", oid
        )
    if not deleted: raise HTTPException(404)
    return {"deleted": True, "option_id": option_id}


# ─── Project land summary ────────────────────────────────────────────────────

@router.get("/projects/{project_id}/summary")
async def project_land_summary(project_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Full land summary for a project — boundaries, options, costs, capacity."""
    pid = UUID(project_id)

    async with pool.acquire() as conn:
        boundaries = await conn.fetch(
            "SELECT * FROM site_boundaries WHERE project_id = $1 ORDER BY created_at", pid
        )
        options = await conn.fetch(
            "SELECT * FROM land_options WHERE project_id = $1 ORDER BY created_at", pid
        )

    total_area_ha = sum(float(b["area_ha"]) for b in boundaries if b["area_ha"])
    site_boundaries = [b for b in boundaries if b["boundary_type"] == "site"]
    exclusions = [b for b in boundaries if b["boundary_type"] == "exclusion"]
    exclusion_ha = sum(float(b["area_ha"]) for b in exclusions if b["area_ha"])
    developable_ha = total_area_ha - exclusion_ha

    total_option_fees = sum(float(o["option_fee_gbp"]) for o in options if o["option_fee_gbp"])
    total_annual_rent = sum(
        float(o["annual_rent_gbp_ha"]) * (float(b["area_ha"]) if b["area_ha"] else 0)
        for o in options
        for b in boundaries
        if o["boundary_id"] and str(o["boundary_id"]) == str(b["boundary_id"]) and o["annual_rent_gbp_ha"]
    )

    secured = sum(1 for o in options if o["status"] in ("exchanged", "completed"))
    negotiating = sum(1 for o in options if o["status"] in ("negotiating", "heads_of_terms"))

    return {
        "project_id": project_id,
        "boundaries": {
            "total": len(boundaries),
            "site": len(site_boundaries),
            "exclusions": len(exclusions),
            "total_area_ha": round(total_area_ha, 2),
            "exclusion_area_ha": round(exclusion_ha, 2),
            "developable_area_ha": round(developable_ha, 2),
        },
        "land_options": {
            "total": len(options),
            "secured": secured,
            "negotiating": negotiating,
            "total_option_fees_gbp": round(total_option_fees),
            "total_annual_rent_gbp": round(total_annual_rent),
        },
        "capacity_potential": {
            "solar_mw": round(developable_ha * 0.5, 1),
            "wind_mw": round(developable_ha * 0.1, 1),
            "bess_mw": round(developable_ha * 5, 1),
        },
        "boundaries_list": [_boundary_row(b) for b in boundaries],
        "options_list": [_option_row(o) for o in options],
    }
