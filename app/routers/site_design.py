"""Site design — placed assets CRUD, real-time validation, BOM linking, pipeline integration."""

from __future__ import annotations

import json
import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import asyncpg

from app.deps import get_pool, get_optional_user

router = APIRouter(prefix="/api/v1/design", tags=["design"])

# ─── Asset type definitions (mirrors frontend AssetDock) ──────────────────────

ASSET_TYPES = {
    "solar_array":   {"label": "Solar Array",  "color": "#D4A018", "category": "generation",     "default_mw": 50,  "width_m": 120, "depth_m": 80,  "height_m": 3},
    "wind_turbine":  {"label": "Wind Turbine", "color": "#00b0ff", "category": "generation",     "default_mw": 5,   "width_m": 6,   "depth_m": 6,   "height_m": 80},
    "bess":          {"label": "BESS",         "color": "#16a34a", "category": "storage",        "default_mw": 50,  "width_m": 40,  "depth_m": 20,  "height_m": 8},
    "transformer":   {"label": "Transformer",  "color": "#0891b2", "category": "infrastructure", "default_mw": 0,   "width_m": 8,   "depth_m": 6,   "height_m": 12},
    "substation":    {"label": "Substation",   "color": "#78909c", "category": "infrastructure", "default_mw": 0,   "width_m": 30,  "depth_m": 25,  "height_m": 10},
    "inverter":      {"label": "Inverter",     "color": "#ff9800", "category": "infrastructure", "default_mw": 0,   "width_m": 4,   "depth_m": 3,   "height_m": 3},
    "data_centre":   {"label": "Data Centre",  "color": "#7c3aed", "category": "infrastructure", "default_mw": 0,   "width_m": 60,  "depth_m": 40,  "height_m": 15},
    "cable_33kv":    {"label": "Cable 33kV",   "color": "#607d8b", "category": "infrastructure", "default_mw": 0,   "width_m": 2,   "depth_m": 2,   "height_m": 1},
    "meter":         {"label": "Meter",        "color": "#e91e63", "category": "monitoring",     "default_mw": 0,   "width_m": 2,   "depth_m": 1,   "height_m": 2},
}


# ─── Pydantic models ─────────────────────────────────────────────────────────

class AssetCreateRequest(BaseModel):
    asset_type: str
    lat: float
    lon: float
    capacity_mw: float = 0
    label: str | None = None
    color: str | None = None
    rotation_deg: float = 0
    width_m: float | None = None
    depth_m: float | None = None
    height_m: float | None = None
    bom_item_id: str | None = None
    bom_spec: dict | None = None
    sort_order: int = 0


class AssetUpdateRequest(BaseModel):
    lat: float | None = None
    lon: float | None = None
    capacity_mw: float | None = None
    label: str | None = None
    rotation_deg: float | None = None
    width_m: float | None = None
    depth_m: float | None = None
    height_m: float | None = None
    bom_item_id: str | None = None
    bom_spec: dict | None = None
    sort_order: int | None = None


class AssetBulkRequest(BaseModel):
    assets: list[AssetCreateRequest]


class FinalizeRequest(BaseModel):
    project_name: str | None = None
    technology: str | None = None
    description: str | None = None


def _asset_row(r) -> dict:
    return {
        "asset_id": str(r["asset_id"]),
        "project_id": str(r["project_id"]) if r["project_id"] else None,
        "parcel_id": str(r["parcel_id"]) if r["parcel_id"] else None,
        "asset_type": r["asset_type"],
        "label": r["label"],
        "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] else 0,
        "lat": float(r["lat"]),
        "lon": float(r["lon"]),
        "rotation_deg": float(r["rotation_deg"]) if r["rotation_deg"] else 0,
        "width_m": float(r["width_m"]) if r["width_m"] else None,
        "depth_m": float(r["depth_m"]) if r["depth_m"] else None,
        "height_m": float(r["height_m"]) if r["height_m"] else None,
        "color": r["color"],
        "bom_item_id": r["bom_item_id"],
        "bom_spec": json.loads(r["bom_spec"]) if r["bom_spec"] else {},
        "validation": json.loads(r["validation"]) if r["validation"] else {},
        "sort_order": r["sort_order"] or 0,
        "created_at": r["created_at"].isoformat(),
    }


# ─── Feature 2: Asset CRUD ──────────────────────────────────────────────────

@router.get("/asset-types")
async def list_asset_types():
    """Available asset types with default dimensions and colors."""
    return ASSET_TYPES


@router.post("/projects/{project_id}/assets")
async def create_asset(
    project_id: str, body: AssetCreateRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Place a single asset on the map for a project."""
    pid = UUID(project_id)
    defaults = ASSET_TYPES.get(body.asset_type, {})

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO placed_assets
                   (project_id, asset_type, label, capacity_mw, lat, lon,
                    rotation_deg, width_m, depth_m, height_m, color,
                    bom_item_id, bom_spec, sort_order)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
               RETURNING *""",
            pid, body.asset_type,
            body.label or defaults.get("label", body.asset_type),
            body.capacity_mw or defaults.get("default_mw", 0),
            body.lat, body.lon, body.rotation_deg,
            body.width_m or defaults.get("width_m"),
            body.depth_m or defaults.get("depth_m"),
            body.height_m or defaults.get("height_m"),
            body.color or defaults.get("color"),
            body.bom_item_id,
            json.dumps(body.bom_spec) if body.bom_spec else "{}",
            body.sort_order,
        )
    return _asset_row(row)


@router.post("/projects/{project_id}/assets/bulk")
async def create_assets_bulk(
    project_id: str, body: AssetBulkRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Save all placed assets for a project (replaces existing)."""
    pid = UUID(project_id)

    async with pool.acquire() as conn:
        # Clear existing
        await conn.execute("DELETE FROM placed_assets WHERE project_id = $1", pid)

        results = []
        for i, a in enumerate(body.assets):
            defaults = ASSET_TYPES.get(a.asset_type, {})
            row = await conn.fetchrow(
                """INSERT INTO placed_assets
                       (project_id, asset_type, label, capacity_mw, lat, lon,
                        rotation_deg, width_m, depth_m, height_m, color,
                        bom_item_id, bom_spec, sort_order)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                   RETURNING *""",
                pid, a.asset_type,
                a.label or defaults.get("label", a.asset_type),
                a.capacity_mw or defaults.get("default_mw", 0),
                a.lat, a.lon, a.rotation_deg,
                a.width_m or defaults.get("width_m"),
                a.depth_m or defaults.get("depth_m"),
                a.height_m or defaults.get("height_m"),
                a.color or defaults.get("color"),
                a.bom_item_id,
                json.dumps(a.bom_spec) if a.bom_spec else "{}",
                a.sort_order or i,
            )
            results.append(_asset_row(row))

    return {"saved": len(results), "assets": results}


@router.get("/projects/{project_id}/assets")
async def list_assets(project_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Load all placed assets for a project."""
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM placed_assets WHERE project_id = $1 ORDER BY sort_order, created_at",
            pid,
        )
    return [_asset_row(r) for r in rows]


@router.patch("/assets/{asset_id}")
async def update_asset(
    asset_id: str, body: AssetUpdateRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Update a placed asset (position, capacity, BOM link, etc.)."""
    aid = UUID(asset_id)

    updates = {}
    if body.lat is not None: updates["lat"] = body.lat
    if body.lon is not None: updates["lon"] = body.lon
    if body.capacity_mw is not None: updates["capacity_mw"] = body.capacity_mw
    if body.label is not None: updates["label"] = body.label
    if body.rotation_deg is not None: updates["rotation_deg"] = body.rotation_deg
    if body.width_m is not None: updates["width_m"] = body.width_m
    if body.depth_m is not None: updates["depth_m"] = body.depth_m
    if body.height_m is not None: updates["height_m"] = body.height_m
    if body.bom_item_id is not None: updates["bom_item_id"] = body.bom_item_id
    if body.bom_spec is not None: updates["bom_spec"] = json.dumps(body.bom_spec)
    if body.sort_order is not None: updates["sort_order"] = body.sort_order

    if not updates:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM placed_assets WHERE asset_id = $1", aid)
            if not row: raise HTTPException(404, "Asset not found")
            return _asset_row(row)

    set_parts, params, idx = [], [], 1
    for col, val in updates.items():
        set_parts.append(f"{col} = ${idx}")
        params.append(val)
        idx += 1
    set_parts.append("updated_at = NOW()")
    params.append(aid)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE placed_assets SET {', '.join(set_parts)} WHERE asset_id = ${idx} RETURNING *",
            *params,
        )
    if not row: raise HTTPException(404, "Asset not found")
    return _asset_row(row)


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Remove a placed asset."""
    aid = UUID(asset_id)
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM placed_assets WHERE asset_id = $1 RETURNING asset_id", aid
        )
    if not deleted: raise HTTPException(404, "Asset not found")
    return {"deleted": True, "asset_id": asset_id}


# ─── Feature 3: Real-time validation ─────────────────────────────────────────

def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


@router.get("/validate")
async def validate_placement(
    lat: float = Query(...), lon: float = Query(...),
    asset_type: str = Query("solar_array"),
    capacity_mw: float = Query(50),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Real-time validation for an asset placement.
    Returns terrain, grid distance, land-use, cable cost, and constraint checks.
    """
    checks = []
    warnings = []
    costs = {}

    async with pool.acquire() as conn:
        # 1. Nearest substation + distance
        sub = await conn.fetchrow(
            """SELECT sub_id, name, capacity_kw,
                      ST_Y(ST_Transform(geometry, 4326)) AS sub_lat,
                      ST_X(ST_Transform(geometry, 4326)) AS sub_lon
               FROM dno_substations
               ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
               LIMIT 1""",
            lon, lat,
        )
        if sub:
            dist_km = _haversine_km(lat, lon, float(sub["sub_lat"]), float(sub["sub_lon"]))
            headroom_mw = (float(sub["capacity_kw"]) / 1000) - capacity_mw if sub["capacity_kw"] else None

            # Cable cost estimate by voltage
            if capacity_mw <= 5:
                voltage_kv, cost_per_km = 11, 80_000
            elif capacity_mw <= 50:
                voltage_kv, cost_per_km = 33, 150_000
            else:
                voltage_kv, cost_per_km = 132, 500_000

            cable_cost = round(dist_km * cost_per_km)
            costs["cable_cost_gbp"] = cable_cost
            costs["cable_voltage_kv"] = voltage_kv
            costs["cable_distance_km"] = round(dist_km, 2)

            checks.append({
                "check": "grid_distance",
                "status": "pass" if dist_km < 10 else "warning" if dist_km < 25 else "fail",
                "message": f"{dist_km:.1f} km to {sub['name']} ({voltage_kv}kV)",
                "detail": {
                    "substation": sub["name"], "sub_id": sub["sub_id"],
                    "distance_km": round(dist_km, 2),
                    "sub_capacity_mw": round(float(sub["capacity_kw"]) / 1000, 1) if sub["capacity_kw"] else None,
                    "headroom_mw": round(headroom_mw, 1) if headroom_mw is not None else None,
                },
            })

            if headroom_mw is not None and headroom_mw < 0:
                warnings.append(f"Substation capacity exceeded by {abs(headroom_mw):.1f} MW — reinforcement needed")

        # 2. Constraint check (SSSI, AONB, Green Belt, Flood Zone)
        constraint_count = 0
        try:
            constraints_nearby = await conn.fetch(
                """SELECT zone_type, zone_name
                   FROM dc_constraint_zones
                   WHERE ST_DWithin(
                       geometry,
                       ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                       1000
                   )
                   LIMIT 5""",
                lon, lat,
            )
            for c in constraints_nearby:
                constraint_count += 1
                severity = "fail" if c["zone_type"] in ("sssi", "sac", "spa") else "warning"
                checks.append({
                    "check": f"constraint_{c['zone_type']}",
                    "status": severity,
                    "message": f"{c['zone_type'].upper()}: {c['zone_name']}",
                })
        except Exception:
            pass  # Table may not exist

        if constraint_count == 0:
            checks.append({"check": "constraints", "status": "pass", "message": "No environmental constraints within 1km"})

        # 3. Terrain slope check
        try:
            parcel = await conn.fetchrow(
                """SELECT slope_avg_deg
                   FROM parcels
                   WHERE centroid IS NOT NULL
                   AND ST_DWithin(
                       centroid,
                       ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                       500
                   )
                   ORDER BY centroid <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                   LIMIT 1""",
                lon, lat,
            )
            if parcel and parcel.get("slope_avg_deg"):
                slope = float(parcel["slope_avg_deg"])
                if asset_type == "solar_array":
                    status = "pass" if slope < 5 else "warning" if slope < 15 else "fail"
                    checks.append({"check": "terrain_slope", "status": status, "message": f"Terrain slope: {slope:.1f}°"})
                elif asset_type == "wind_turbine":
                    checks.append({"check": "terrain_slope", "status": "pass", "message": f"Terrain slope: {slope:.1f}° (acceptable for wind)"})
            else:
                checks.append({"check": "terrain_slope", "status": "info", "message": "Terrain data not available — run GeeFlow analysis"})
        except Exception:
            checks.append({"check": "terrain_slope", "status": "info", "message": "Terrain data not available"})

        # 4. Land use check (from geeflow_extractions)
        geeflow = await conn.fetchrow(
            """SELECT result_data
               FROM geeflow_extractions
               WHERE mode = 'land_use'
               AND ST_DWithin(
                   geometry,
                   ST_SetSRID(ST_MakePoint($1, $2), 4326),
                   0.05
               )
               ORDER BY created_at DESC LIMIT 1""",
            lon, lat,
        )
        if geeflow and geeflow["result_data"]:
            lu_data = json.loads(geeflow["result_data"]) if isinstance(geeflow["result_data"], str) else geeflow["result_data"]
            dominant = lu_data.get("dominant_class", "")
            if dominant in ("trees", "water", "snow_and_ice"):
                checks.append({"check": "land_use", "status": "fail", "message": f"Land use: {dominant} — unsuitable for development"})
                warnings.append(f"Site is classified as '{dominant}' — likely protected or unsuitable")
            elif dominant in ("built", "crops"):
                checks.append({"check": "land_use", "status": "warning", "message": f"Land use: {dominant} — planning sensitivity"})
            else:
                checks.append({"check": "land_use", "status": "pass", "message": f"Land use: {dominant}"})
        else:
            checks.append({"check": "land_use", "status": "info", "message": "Land use data not available — run GeeFlow analysis"})

    # 5. Overall verdict
    statuses = [c["status"] for c in checks]
    if "fail" in statuses:
        verdict = "NO-GO"
    elif "warning" in statuses:
        verdict = "CAUTION"
    else:
        verdict = "GO"

    return {
        "verdict": verdict,
        "checks": checks,
        "warnings": warnings,
        "costs": costs,
        "asset_type": asset_type,
        "capacity_mw": capacity_mw,
    }


# ─── Feature 3b: Validate all assets in a project ────────────────────────────

@router.post("/projects/{project_id}/validate")
async def validate_project_assets(
    project_id: str, pool: asyncpg.Pool = Depends(get_pool),
):
    """Run validation on all placed assets in a project."""
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        assets = await conn.fetch(
            "SELECT * FROM placed_assets WHERE project_id = $1 ORDER BY sort_order", pid
        )

    results = []
    for asset in assets:
        # Call validate_placement for each asset
        from starlette.datastructures import QueryParams
        val = await validate_placement(
            lat=float(asset["lat"]), lon=float(asset["lon"]),
            asset_type=asset["asset_type"],
            capacity_mw=float(asset["capacity_mw"]) if asset["capacity_mw"] else 0,
            pool=pool,
        )

        # Persist validation result
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE placed_assets SET validation = $1, updated_at = NOW() WHERE asset_id = $2",
                json.dumps(val), asset["asset_id"],
            )

        results.append({
            "asset_id": str(asset["asset_id"]),
            "asset_type": asset["asset_type"],
            "label": asset["label"],
            "validation": val,
        })

    # Overall project verdict
    all_verdicts = [r["validation"]["verdict"] for r in results]
    if "NO-GO" in all_verdicts:
        project_verdict = "NO-GO"
    elif "CAUTION" in all_verdicts:
        project_verdict = "CAUTION"
    elif all_verdicts:
        project_verdict = "GO"
    else:
        project_verdict = None

    total_mw = sum(float(a["capacity_mw"]) for a in assets if a["capacity_mw"])
    total_cable_cost = sum(r["validation"].get("costs", {}).get("cable_cost_gbp", 0) for r in results)

    return {
        "project_id": project_id,
        "asset_count": len(results),
        "total_mw": round(total_mw, 1),
        "total_cable_cost_gbp": total_cable_cost,
        "project_verdict": project_verdict,
        "assets": results,
    }


# ─── Feature 4: BOM catalogue linking ────────────────────────────────────────

@router.get("/bom/match")
async def match_bom_items(
    asset_type: str = Query("solar_array"),
    capacity_mw: float = Query(50),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Suggest BOM catalogue items matching an asset type and capacity."""
    # Map asset types to inventory categories
    category_map = {
        "solar_array": "panel",
        "bess": "battery",
        "inverter": "inverter",
        "transformer": "transformer",
        "wind_turbine": "panel",  # fallback
        "cable_33kv": "cable",
        "meter": "monitoring",
    }
    category = category_map.get(asset_type, "panel")

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT component_id, name, category, unit_cost_gbp
               FROM solar_inventory
               WHERE category = $1
               ORDER BY unit_cost_gbp ASC NULLS LAST
               LIMIT 10""",
            category,
        )

    items = []
    for r in rows:
        unit_cost = float(r["unit_cost_gbp"]) if r["unit_cost_gbp"] else 0
        # Rough capacity estimate per unit based on category
        unit_kw = {"panel": 0.6, "battery": 50, "inverter": 100, "transformer": 500, "cable": 0, "monitoring": 0}.get(category, 1)
        qty_needed = int(math.ceil(capacity_mw * 1000 / unit_kw)) if unit_kw > 0 else 1
        total_cost = unit_cost * qty_needed

        items.append({
            "item_id": r["component_id"],
            "name": r["name"],
            "category": r["category"],
            "unit_cost_gbp": unit_cost if unit_cost else None,
            "qty_needed": qty_needed,
            "total_cost_gbp": round(total_cost, 2),
        })

    return {"asset_type": asset_type, "capacity_mw": capacity_mw, "items": items}


@router.patch("/assets/{asset_id}/link-bom")
async def link_bom_to_asset(
    asset_id: str,
    bom_item_id: str = Query(...),
    qty: int = Query(1),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Link a BOM catalogue item to a placed asset."""
    aid = UUID(asset_id)

    async with pool.acquire() as conn:
        # Fetch BOM item specs
        bom = await conn.fetchrow(
            "SELECT component_id, name, unit_cost_gbp FROM solar_inventory WHERE component_id = $1",
            bom_item_id,
        )
        if not bom:
            raise HTTPException(404, f"BOM item {bom_item_id} not found")

        bom_spec = {
            "item_id": bom["component_id"],
            "name": bom["name"],
            "unit_cost_gbp": float(bom["unit_cost_gbp"]) if bom["unit_cost_gbp"] else None,
            "qty": qty,
            "total_cost_gbp": round(float(bom["unit_cost_gbp"] or 0) * qty, 2),
        }

        row = await conn.fetchrow(
            """UPDATE placed_assets
               SET bom_item_id = $1, bom_spec = $2, updated_at = NOW()
               WHERE asset_id = $3 RETURNING *""",
            bom_item_id, json.dumps(bom_spec), aid,
        )
    if not row:
        raise HTTPException(404, "Asset not found")
    return _asset_row(row)


# ─── Feature 5: Finalize design → create pipeline project ────────────────────

@router.post("/projects/{project_id}/finalize")
async def finalize_design(
    project_id: str, body: FinalizeRequest = None,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """
    Finalize a site design — validates all assets, computes totals,
    advances project to 'screened' stage, and returns summary.
    """
    pid = UUID(project_id)
    user_id = user["user_id"] if user else None

    async with pool.acquire() as conn:
        project = await conn.fetchrow("SELECT * FROM projects WHERE project_id = $1", pid)
        if not project:
            raise HTTPException(404, "Project not found")

        assets = await conn.fetch(
            "SELECT * FROM placed_assets WHERE project_id = $1 ORDER BY sort_order", pid
        )
        if not assets:
            raise HTTPException(400, "No assets placed — design is empty")

    # Run validation on all assets
    validation = await validate_project_assets(project_id, pool=pool)

    # Compute design summary
    gen_mw = sum(float(a["capacity_mw"]) for a in assets if a["asset_type"] in ("solar_array", "wind_turbine") and a["capacity_mw"])
    storage_mw = sum(float(a["capacity_mw"]) for a in assets if a["asset_type"] == "bess" and a["capacity_mw"])
    total_bom_cost = 0
    for a in assets:
        bom = json.loads(a["bom_spec"]) if a["bom_spec"] else {}
        total_bom_cost += bom.get("total_cost_gbp", 0)

    total_cable_cost = validation.get("total_cable_cost_gbp", 0)
    total_cost = total_bom_cost + total_cable_cost

    # Update project with design data
    async with pool.acquire() as conn:
        capacity = gen_mw + storage_mw
        tech = "hybrid" if gen_mw > 0 and storage_mw > 0 else "solar" if any(a["asset_type"] == "solar_array" for a in assets) else "bess" if storage_mw > 0 else "wind"

        await conn.execute(
            """UPDATE projects
               SET capacity_mw = $1, technology = $2, verdict = $3,
                   stage = CASE WHEN stage = 'prospect' THEN 'screened' ELSE stage END,
                   stage_entered_at = CASE WHEN stage = 'prospect' THEN NOW() ELSE stage_entered_at END,
                   metadata = jsonb_set(COALESCE(metadata, '{}'), '{design_summary}', $4::jsonb),
                   updated_at = NOW()
               WHERE project_id = $5""",
            capacity,
            (body.technology if body and body.technology else tech),
            validation.get("project_verdict"),
            json.dumps({
                "generation_mw": round(gen_mw, 1),
                "storage_mw": round(storage_mw, 1),
                "asset_count": len(assets),
                "total_bom_cost_gbp": round(total_bom_cost),
                "total_cable_cost_gbp": round(total_cable_cost),
                "total_cost_gbp": round(total_cost),
                "finalized_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            }),
            pid,
        )

        # Record stage transition if moved to screened
        if project["stage"] == "prospect":
            await conn.execute(
                """INSERT INTO project_stage_history (project_id, from_stage, to_stage, changed_by, notes)
                   VALUES ($1, 'prospect', 'screened', $2, $3)""",
                pid, user_id,
                f"Design finalized — {len(assets)} assets, {gen_mw:.0f} MW generation, {storage_mw:.0f} MW storage",
            )

    return {
        "project_id": project_id,
        "stage": "screened" if project["stage"] == "prospect" else project["stage"],
        "verdict": validation.get("project_verdict"),
        "design_summary": {
            "generation_mw": round(gen_mw, 1),
            "storage_mw": round(storage_mw, 1),
            "asset_count": len(assets),
            "total_bom_cost_gbp": round(total_bom_cost),
            "total_cable_cost_gbp": round(total_cable_cost),
            "total_cost_gbp": round(total_cost),
        },
        "validation": validation,
    }
