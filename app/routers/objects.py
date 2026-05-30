"""Object Page generator — typed object detail + list endpoints.

Surfaces ontology objects (Project, Substation, Entity, REPD, NSIP, TEC) as
Foundry-style typed objects with properties + links + actions + history.

  GET /api/objects/{type}                 — list with optional filters
  GET /api/objects/{type}/{id}            — detail for one object
  GET /api/objects/{type}/{id}/links      — typed links out
  GET /api/objects/{type}/{id}/history    — ontology_action_log for this rid

Drives the /v2/object/:type[/:id] frontend route.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_pool as _raw_pool  # noqa: F401  (back-compat re-export)
from app.middleware.tenant_jwt import get_tenant_pool as get_pool

log = logging.getLogger("princeps.objects")
router = APIRouter(prefix="/api/objects", tags=["objects"])
# Separate router so `/api/object-geo/{type}` can't collide with the
# parameterised `/api/objects/{type}/{id}` detail route during FastAPI's
# in-order match. We add this second router to the same module so it ships
# alongside.
geo_router = APIRouter(prefix="/api/object-geo", tags=["objects"])


# ── Type registry ───────────────────────────────────────────────────────────
# Each type declares its canonical table, primary key column, display label
# field, and a links() resolver that yields typed edges.

def _project_loader(row):
    return {
        "type": "Project",
        "id": str(row["project_id"]),
        "rid": f"rid.princeps.project.{row['project_id']}",
        "label": row["name"],
        "properties": {
            "stage": row["stage"],
            "verdict": row["verdict"],
            "technology": row["technology"],
            "capacity_mw": row["capacity_mw"],
            "status": row["status"],
            "blocker": row["blocker"],
            "lat": row["lat"],
            "lon": row["lon"],
            "repd_id": row["repd_id"],
            "stage_entered_at": row["stage_entered_at"].isoformat() if row.get("stage_entered_at") else None,
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        },
        "provenance": {
            "table": "projects",
            "primary_key": "project_id",
            "ontology_class": "dtmi:com:princeps:Project;1",
        },
    }


def _substation_loader(row):
    return {
        "type": "Substation",
        "id": str(row["id"]),
        "rid": f"rid.princeps.substation.{row['id']}",
        "label": row["name"],
        "properties": {
            "voltage_kv": float(row["voltage_kv"]) if row.get("voltage_kv") is not None else None,
            "dno": row["dno"],
            "external_id": row["external_id"],
            "site_type": row.get("site_type"),
        },
        "provenance": {
            "table": "grid_substations",
            "primary_key": "id",
            "ontology_class": "dtmi:com:princeps:Substation;1",
        },
    }


def _repd_loader(row):
    return {
        "type": "REPDProject",
        "id": row["repd_id"],
        "rid": f"rid.princeps.repd.{row['repd_id']}",
        "label": row["site_name"],
        "properties": {
            "technology": row["tech_category"] or row["technology"],
            "capacity_mw": row["capacity_mw"],
            "status": row["status"],
            "developer": row["developer"],
            "operator": row["operator"],
            "planning_authority": row["planning_authority"],
            "planning_ref": row["planning_ref"],
            "date_submitted": row["date_submitted"].isoformat() if row.get("date_submitted") else None,
            "date_decided": row["date_decided"].isoformat() if row.get("date_decided") else None,
            "date_operational": row["date_operational"].isoformat() if row.get("date_operational") else None,
        },
        "provenance": {
            "table": "repd_projects",
            "primary_key": "repd_id",
            "ontology_class": "dtmi:com:princeps:RepdProject;1",
        },
    }


def _nsip_loader(row):
    return {
        "type": "NSIPProject",
        "id": row["case_ref"],
        "rid": f"rid.princeps.nsip.{row['case_ref']}",
        "label": row["title"],
        "properties": {
            "sector": row["sector"],
            "status": row["status"],
            "promoter": row["promoter"],
            "region": row["region"],
            "applied_date": row["applied_date"].isoformat() if row.get("applied_date") else None,
            "decision_date": row["decision_date"].isoformat() if row.get("decision_date") else None,
            "capacity_mw": float(row["capacity_mw"]) if row.get("capacity_mw") is not None else None,
            "source_url": row["source_url"],
        },
        "provenance": {
            "table": "pins_nsip_dco",
            "primary_key": "case_ref",
            "ontology_class": "dtmi:com:princeps:NsipProject;1",
        },
    }


def _tec_loader(row):
    return {
        "type": "TecQueueEntry",
        "id": row["tec_id"],
        "rid": f"rid.princeps.tec.{row['tec_id']}",
        "label": row["customer_name"] or row["connection_site"] or f"TEC {row['tec_id']}",
        "properties": {
            "customer_name": row["customer_name"],
            "connection_site": row["connection_site"],
            "fuel_type": row["fuel_type"],
            "tech_category": row["tech_category"],
            "tec_mw": row["tec_mw"],
            "status": row["status"],
            "voltage_kv": float(row["voltage_kv"]) if row.get("voltage_kv") is not None else None,
            "queue_position": row["queue_position"],
            "connection_date": row["connection_date"].isoformat() if row.get("connection_date") else None,
        },
        "provenance": {
            "table": "eso_tec_register",
            "primary_key": "tec_id",
            "ontology_class": "dtmi:com:princeps:TecQueueEntry;1",
        },
    }


def _entity_loader_from_relationships(row):
    """Entity loader — uses the entities table if present, else synthesises
    from entity_relationships.from_rid/to_rid. We accept name OR rid as id."""
    return {
        "type": "Entity",
        "id": row["id"],
        "rid": row["rid"],
        "label": row["label"],
        "properties": row.get("properties") or {},
        "provenance": {
            "table": row["table"],
            "primary_key": row["primary_key"],
            "ontology_class": "dtmi:com:princeps:Entity;1",
        },
    }


# Each entry: (table, pk_col, label_col, select_cols, loader)
TYPE_REGISTRY: dict[str, dict[str, Any]] = {
    "Project": {
        "table": "projects",
        "pk_col": "project_id",
        "pk_cast": "uuid",
        "label_col": "name",
        "loader": _project_loader,
    },
    "Substation": {
        "table": "grid_substations",
        "pk_col": "id",
        "pk_cast": "integer",
        "label_col": "name",
        "loader": _substation_loader,
    },
    "REPDProject": {
        "table": "repd_projects",
        "pk_col": "repd_id",
        "pk_cast": "text",
        "label_col": "site_name",
        "loader": _repd_loader,
    },
    "NSIPProject": {
        "table": "pins_nsip_dco",
        "pk_col": "case_ref",
        "pk_cast": "text",
        "label_col": "title",
        "loader": _nsip_loader,
    },
    "TecQueueEntry": {
        "table": "eso_tec_register",
        "pk_col": "tec_id",
        "pk_cast": "text",
        "label_col": "customer_name",
        "loader": _tec_loader,
    },
}


# ── List endpoint ───────────────────────────────────────────────────────────
@router.get("/{obj_type}")
async def list_objects(
    obj_type: str,
    stage: str | None = Query(None),
    status: str | None = Query(None),
    technology: str | None = Query(None),
    sector: str | None = Query(None),
    voltage_min: float | None = Query(None, ge=0, le=800),
    capacity_min: float | None = Query(None, ge=0),
    q: str | None = Query(None, description="Free-text search on label"),
    limit: int = Query(100, ge=1, le=500),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List objects of a given type with type-aware filters."""
    if obj_type == "Entity":
        return await _list_entities(pool, q=q, limit=limit)

    if obj_type not in TYPE_REGISTRY:
        raise HTTPException(404, f"unknown object type: {obj_type}")

    cfg = TYPE_REGISTRY[obj_type]
    table = cfg["table"]
    label_col = cfg["label_col"]
    where = []
    params: list[Any] = []

    def _bind(val):
        params.append(val)
        return f"${len(params)}"

    if obj_type == "Project":
        if stage: where.append(f"stage = {_bind(stage)}")
        if status: where.append(f"status = {_bind(status)}")
        if technology: where.append(f"technology = {_bind(technology)}")
        if capacity_min is not None: where.append(f"capacity_mw >= {_bind(capacity_min)}")
    elif obj_type == "Substation":
        if voltage_min is not None: where.append(f"voltage_kv >= {_bind(voltage_min)}")
    elif obj_type == "REPDProject":
        if status: where.append(f"status ILIKE '%' || {_bind(status)} || '%'")
        if technology: where.append(f"tech_category ILIKE '%' || {_bind(technology)} || '%'")
        if capacity_min is not None: where.append(f"capacity_mw >= {_bind(capacity_min)}")
    elif obj_type == "NSIPProject":
        if status: where.append(f"status ILIKE '%' || {_bind(status)} || '%'")
        if sector: where.append(f"sector ILIKE '%' || {_bind(sector)} || '%'")
    elif obj_type == "TecQueueEntry":
        if status: where.append(f"status ILIKE '%' || {_bind(status)} || '%'")
        if voltage_min is not None: where.append(f"voltage_kv >= {_bind(voltage_min)}")

    if q and label_col:
        where.append(f"{label_col} ILIKE '%' || {_bind(q)} || '%'")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"SELECT * FROM {table} {where_sql} LIMIT {int(limit)}"

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
    except asyncpg.exceptions.UndefinedTableError:
        return {
            "type": obj_type,
            "filters": {
                "stage": stage, "status": status, "technology": technology,
                "sector": sector, "voltage_min": voltage_min,
                "capacity_min": capacity_min, "q": q,
            },
            "count": 0,
            "items": [],
            "source": "table_not_seeded",
            "warning": f"table '{table}' not present in this database",
        }
    except asyncpg.exceptions.UndefinedColumnError as exc:
        return {
            "type": obj_type, "count": 0, "items": [],
            "source": "schema_drift",
            "warning": f"column missing: {exc}",
        }

    items = [cfg["loader"](r) for r in rows]
    return {
        "type": obj_type,
        "filters": {
            "stage": stage, "status": status, "technology": technology,
            "sector": sector, "voltage_min": voltage_min,
            "capacity_min": capacity_min, "q": q,
        },
        "count": len(items),
        "items": items,
    }


async def _list_entities(pool, q, limit):
    """Entities list — synthesised from CCOD + REPD developer + TEC customer.
    Returns deduped owner names with capacity totals."""
    sql = """
        WITH owners AS (
          SELECT proprietor_name_1 AS name, NULL::numeric AS cap, 'CCOD' AS src
            FROM hm_land_registry_ccod WHERE proprietor_name_1 IS NOT NULL
          UNION ALL
          SELECT developer, capacity_mw, 'REPD' FROM repd_projects WHERE developer IS NOT NULL
          UNION ALL
          SELECT operator, capacity_mw, 'REPD' FROM repd_projects WHERE operator IS NOT NULL
          UNION ALL
          SELECT customer_name, tec_mw, 'TEC'  FROM eso_tec_register WHERE customer_name IS NOT NULL
        )
        SELECT
          name,
          SUM(COALESCE(cap, 0)) AS total_capacity_mw,
          COUNT(*) AS n_records,
          ARRAY_AGG(DISTINCT src) AS sources
        FROM owners
        WHERE ($1::text IS NULL OR name ILIKE '%' || $1 || '%')
        GROUP BY name
        ORDER BY total_capacity_mw DESC NULLS LAST
        LIMIT $2
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, q, limit)
    items = [{
        "type": "Entity",
        "id": r["name"],
        "rid": f"rid.princeps.entity.{r['name']}",
        "label": r["name"],
        "properties": {
            "total_capacity_mw": float(r["total_capacity_mw"]) if r["total_capacity_mw"] is not None else None,
            "n_records": r["n_records"],
            "sources": list(r["sources"]),
        },
        "provenance": {
            "table": "(union of CCOD + REPD + TEC)",
            "primary_key": "name",
            "ontology_class": "dtmi:com:princeps:Entity;1",
        },
    } for r in rows]
    return {
        "type": "Entity",
        "filters": {"q": q},
        "count": len(items),
        "items": items,
    }


# ── Detail endpoint ─────────────────────────────────────────────────────────
@router.get("/{obj_type}/{obj_id}")
async def get_object(
    obj_type: str,
    obj_id: str,
    as_of: str | None = Query(None, description="ISO timestamp or YYYY-MM-DD — return the version active at that moment"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return a single typed object with header, properties, links, history,
    and available actions. When ``as_of`` is set, time-travel into
    ``object_versions`` and return the snapshot active at that instant.
    """
    if obj_type == "Entity":
        return await _get_entity(pool, obj_id)

    if obj_type not in TYPE_REGISTRY:
        raise HTTPException(404, f"unknown object type: {obj_type}")

    # Time-travel branch — short-circuit using object_versions
    if as_of:
        return await _get_object_as_of(pool, obj_type, obj_id, as_of)

    cfg = TYPE_REGISTRY[obj_type]
    pk_cast = cfg["pk_cast"]

    # Coerce the id to the right type
    coerced: Any = obj_id
    if pk_cast == "uuid":
        try:
            coerced = UUID(obj_id)
        except (ValueError, TypeError):
            raise HTTPException(400, f"invalid uuid for {obj_type}: {obj_id}")
    elif pk_cast == "integer":
        try:
            coerced = int(obj_id)
        except (ValueError, TypeError):
            raise HTTPException(400, f"invalid id for {obj_type}: {obj_id}")

    sql = f"SELECT * FROM {cfg['table']} WHERE {cfg['pk_col']} = $1"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, coerced)
    if not row:
        raise HTTPException(404, f"{obj_type}:{obj_id} not found")

    obj = cfg["loader"](row)
    rid = obj["rid"]

    # Fetch links + history + actions in parallel-ish (sequential acquires fine)
    async with pool.acquire() as conn:
        links = await _resolve_links(conn, obj_type, obj_id, rid, row)
        history = await _action_history(conn, rid, limit=10)
    actions = _available_actions_for(obj_type, obj)

    obj["links"] = links
    obj["history"] = history
    obj["actions_available"] = actions
    return obj


async def _get_entity(pool, name):
    """Synthesise an entity record + outbound ownership relationships."""
    sql = """
        WITH owner AS (
          SELECT * FROM hm_land_registry_ccod WHERE proprietor_name_1 = $1 LIMIT 1
        ),
        repd AS (
          SELECT repd_id, site_name, capacity_mw, status
          FROM repd_projects WHERE developer = $1 OR operator = $1 LIMIT 50
        ),
        tec AS (
          SELECT tec_id, connection_site, tec_mw, status
          FROM eso_tec_register WHERE customer_name = $1 LIMIT 50
        )
        SELECT
          (SELECT to_jsonb(owner) FROM owner) AS owner,
          (SELECT jsonb_agg(repd) FROM repd) AS repd_projects,
          (SELECT jsonb_agg(tec) FROM tec) AS tec_entries
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, name)

    def _decode(v):
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    repd_arr = _decode(row["repd_projects"]) or []
    tec_arr = _decode(row["tec_entries"]) or []
    owner_props = _decode(row["owner"]) or {}

    repd_links = []
    for r in repd_arr:
        repd_links.append({
            "rel": "developsOrOperates",
            "target_type": "REPDProject",
            "target_id": r["repd_id"],
            "target_label": r["site_name"],
            "target_summary": f"{r.get('capacity_mw')} MW · {r.get('status')}",
        })
    tec_links = []
    for r in tec_arr:
        tec_links.append({
            "rel": "queuedAt",
            "target_type": "TecQueueEntry",
            "target_id": r["tec_id"],
            "target_label": r["connection_site"] or f"TEC {r['tec_id']}",
            "target_summary": f"{r.get('tec_mw')} MW · {r.get('status')}",
        })
    return {
        "type": "Entity",
        "id": name,
        "rid": f"rid.princeps.entity.{name}",
        "label": name,
        "properties": {
            "company_registration_no": owner_props.get("company_registration_no_1"),
            "country_incorporated": owner_props.get("country_incorporated_1"),
            "proprietor_address": owner_props.get("proprietor_address_1") or owner_props.get("property_address"),
            "n_repd": len(repd_links),
            "n_tec": len(tec_links),
        },
        "provenance": {
            "table": "(union of CCOD + REPD + TEC)",
            "primary_key": "name",
            "ontology_class": "dtmi:com:princeps:Entity;1",
        },
        "links": repd_links + tec_links,
        "history": [],
        "actions_available": [
            {"id": "screen_counterparty", "label": "Screen counterparty"},
            {"id": "refresh_industrial_base", "label": "Refresh industrial base"},
        ],
    }


async def _resolve_links(conn, obj_type, obj_id, rid, source_row):
    """Return typed outbound edges for this object."""
    out: list[dict] = []

    if obj_type == "Project":
        # Project → REPD (via repd_id), Project → linked Site (via project_sites if exists)
        repd_id = source_row.get("repd_id")
        if repd_id:
            r = await conn.fetchrow(
                "SELECT site_name FROM repd_projects WHERE repd_id = $1",
                repd_id,
            )
            if r:
                out.append({
                    "rel": "anchoredOn",
                    "target_type": "REPDProject",
                    "target_id": repd_id,
                    "target_label": r["site_name"],
                })

    elif obj_type == "REPDProject":
        # REPD → Entity (developer) + nearest substation
        if source_row.get("developer"):
            out.append({
                "rel": "developedBy",
                "target_type": "Entity",
                "target_id": source_row["developer"],
                "target_label": source_row["developer"],
            })
        if source_row.get("operator") and source_row["operator"] != source_row.get("developer"):
            out.append({
                "rel": "operatedBy",
                "target_type": "Entity",
                "target_id": source_row["operator"],
                "target_label": source_row["operator"],
            })

    elif obj_type == "Substation":
        # Substation → ECR (incoming connections)
        rows = await conn.fetch(
            "SELECT id, site_name, capacity_mw FROM grid_ecr WHERE substation_id = $1 LIMIT 20",
            source_row["id"],
        )
        for r in rows:
            out.append({
                "rel": "hostsConnection",
                "target_type": "EcrConnection",
                "target_id": str(r["id"]),
                "target_label": r["site_name"] or f"ECR {r['id']}",
                "target_summary": f"{r['capacity_mw']} MW" if r.get("capacity_mw") else None,
            })

    elif obj_type == "TecQueueEntry":
        if source_row.get("customer_name"):
            out.append({
                "rel": "submittedBy",
                "target_type": "Entity",
                "target_id": source_row["customer_name"],
                "target_label": source_row["customer_name"],
            })

    return out


async def _action_history(conn, rid, limit=10):
    """Recent ontology_action_log rows for this rid."""
    try:
        rows = await conn.fetch(
            """
            SELECT log_id, action, actor, ok, started_utc, completed_utc, error
            FROM ontology_action_log
            WHERE object_id = $1
            ORDER BY started_utc DESC
            LIMIT $2
            """,
            rid, limit,
        )
        return [{
            "log_id": str(r["log_id"]),
            "action": r["action"],
            "actor": r["actor"],
            "ok": r["ok"],
            "started_utc": r["started_utc"].isoformat() if r["started_utc"] else None,
            "completed_utc": r["completed_utc"].isoformat() if r["completed_utc"] else None,
            "error": r["error"],
        } for r in rows]
    except Exception as exc:
        log.warning("action_history failed for rid=%s: %s", rid, exc)
        return []


def _available_actions_for(obj_type, obj):
    """Return the action types that are bound to this object class."""
    by_type = {
        "Project": [
            {"id": "advance_stage", "label": "Advance stage"},
            {"id": "set_verdict", "label": "Set verdict"},
            {"id": "run_feasibility", "label": "Run feasibility"},
            {"id": "lock_site_design", "label": "Lock site design"},
            {"id": "archive", "label": "Archive"},
        ],
        "Substation": [
            {"id": "watch", "label": "Watch substation"},
            {"id": "headroom", "label": "Run headroom analysis"},
            {"id": "connection_cost", "label": "Estimate connection cost"},
        ],
        "REPDProject": [
            {"id": "screen_counterparty", "label": "Screen developer"},
        ],
        "NSIPProject": [
            {"id": "screen_counterparty", "label": "Screen promoter"},
        ],
        "TecQueueEntry": [
            {"id": "screen_counterparty", "label": "Screen customer"},
            {"id": "send_dno_engagement", "label": "Send DNO engagement"},
        ],
        "Entity": [
            {"id": "screen_counterparty", "label": "Screen counterparty"},
            {"id": "refresh_industrial_base", "label": "Refresh industrial base"},
        ],
    }
    return by_type.get(obj_type, [])


# ── Spatial GeoJSON endpoint for typed object lists ─────────────────────────
# Map type → (table, geom_expr) where geom_expr is a SQL fragment that
# yields a Point geometry in EPSG:4326. Types not in this map have no
# geo surface and the endpoint will 404.
_GEO_SOURCES = {
    "REPDProject": {
        "table": "repd_projects",
        "geom_4326_sql": "ST_Transform(geometry, 4326)",
        "id_col": "repd_id",
        "label_col": "site_name",
        "extra_cols": "tech_category, capacity_mw, status",
    },
    "Substation": {
        "table": "grid_substations",
        "geom_4326_sql": "ST_Transform(geom, 4326)",
        "id_col": "id",
        "label_col": "name",
        "extra_cols": "voltage_kv, dno",
    },
    "NSIPProject": {
        "table": "pins_nsip_dco",
        # NSIP uses lat/lng columns rather than a geometry — synthesise a Point
        "geom_4326_sql": "ST_SetSRID(ST_MakePoint(location_lng::float, location_lat::float), 4326)",
        "id_col": "case_ref",
        "label_col": "title",
        "extra_cols": "sector, status, capacity_mw",
        "where_extra": "location_lat IS NOT NULL AND location_lng IS NOT NULL",
    },
}


@geo_router.get("/{obj_type}")
async def list_objects_geo(
    obj_type: str,
    bbox: str | None = Query(None, description="minLng,minLat,maxLng,maxLat (EPSG:4326)"),
    status: str | None = Query(None),
    technology: str | None = Query(None),
    voltage_min: float | None = Query(None, ge=0, le=800),
    capacity_min: float | None = Query(None, ge=0),
    limit: int = Query(2000, ge=1, le=5000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return GeoJSON FeatureCollection for spatial object types so the
    frontend ObjectList can render a Mapbox layer alongside the table."""
    cfg = _GEO_SOURCES.get(obj_type)
    if not cfg:
        raise HTTPException(404, f"{obj_type} has no geo surface")

    where: list[str] = []
    params: list[Any] = []
    def _bind(v):
        params.append(v)
        return f"${len(params)}"

    if cfg.get("where_extra"):
        where.append(cfg["where_extra"])

    if bbox:
        try:
            mlng, mlat, xlng, xlat = (float(x) for x in bbox.split(","))
        except (ValueError, AttributeError):
            raise HTTPException(400, "invalid bbox")
        # Convert bbox to source SRID for index hit; use ST_Intersects
        where.append(
            f"ST_Intersects({cfg['geom_4326_sql']}, "
            f"ST_MakeEnvelope({_bind(mlng)},{_bind(mlat)},{_bind(xlng)},{_bind(xlat)}, 4326))"
        )

    # Type-specific filters
    if obj_type == "REPDProject":
        if status: where.append(f"status ILIKE '%' || {_bind(status)} || '%'")
        if technology: where.append(f"tech_category ILIKE '%' || {_bind(technology)} || '%'")
        if capacity_min is not None: where.append(f"capacity_mw >= {_bind(capacity_min)}")
    elif obj_type == "Substation":
        if voltage_min is not None: where.append(f"voltage_kv >= {_bind(voltage_min)}")
    elif obj_type == "NSIPProject":
        if status: where.append(f"status ILIKE '%' || {_bind(status)} || '%'")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT {cfg['id_col']} AS id,
               {cfg['label_col']} AS label,
               {cfg['extra_cols']},
               ST_AsGeoJSON({cfg['geom_4326_sql']})::jsonb AS geom_json
        FROM {cfg['table']}
        {where_sql}
        LIMIT {int(limit)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    features = []
    for r in rows:
        gj = r["geom_json"]
        if isinstance(gj, str):
            gj = json.loads(gj)
        if not gj:
            continue
        props = {k: r[k] for k in r.keys() if k not in ("geom_json",)}
        # Decimals → floats / strings → ISO
        cleaned = {}
        for k, v in props.items():
            if v is None:
                cleaned[k] = None
            elif hasattr(v, "isoformat"):
                cleaned[k] = v.isoformat()
            elif hasattr(v, "__float__"):
                try: cleaned[k] = float(v)
                except (ValueError, TypeError): cleaned[k] = str(v)
            else:
                cleaned[k] = v
        features.append({
            "type": "Feature",
            "geometry": gj,
            "id": str(cleaned.get("id") or ""),
            "properties": {
                **cleaned,
                "object_type": obj_type,
                "feature_id": f"{obj_type}:{cleaned.get('id')}",
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "object_type": obj_type,
            "feature_count": len(features),
            "filters": {"bbox": bbox, "status": status, "technology": technology,
                        "voltage_min": voltage_min, "capacity_min": capacity_min},
        },
    }


# ── Time-travel helpers ─────────────────────────────────────────────────────
async def _get_object_as_of(pool, obj_type, obj_id, as_of):
    """Return the version of an object that was active at ``as_of``.

    Reads from ``object_versions`` (populated by the AGE auto-emit
    trigger). Returns the same shape as ``get_object`` so the frontend
    detail view can render either path uniformly.
    """
    from datetime import datetime
    # Accept either YYYY-MM-DD or full ISO; normalise.
    try:
        if len(as_of) <= 10:
            ts = datetime.fromisoformat(as_of + "T23:59:59")
        else:
            ts = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"invalid as_of timestamp: {as_of}")

    rid = f"rid.princeps.{obj_type.lower()}.{obj_id}"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT op, props, valid_from, valid_to, label, diff
            FROM object_versions
            WHERE rid = $1
              AND valid_from <= $2
              AND (valid_to IS NULL OR valid_to > $2)
            ORDER BY valid_from DESC
            LIMIT 1
            """,
            rid, ts,
        )
        if not row:
            raise HTTPException(
                404,
                f"no version of {obj_type}:{obj_id} active at {as_of} "
                "(object may not have been versioned yet)",
            )

        # Pull a small history slice for the timeline panel
        history_rows = await conn.fetch(
            """
            SELECT op, props, valid_from, valid_to, diff
            FROM object_versions
            WHERE rid = $1
            ORDER BY valid_from DESC
            LIMIT 30
            """,
            rid,
        )

    props = json.loads(row["props"]) if isinstance(row["props"], str) else row["props"]
    return {
        "type": obj_type,
        "id": obj_id,
        "rid": rid,
        "label": props.get("name") or obj_id,
        "as_of": ts.isoformat(),
        "as_of_op": row["op"],
        "valid_from": row["valid_from"].isoformat() if row["valid_from"] else None,
        "valid_to": row["valid_to"].isoformat() if row["valid_to"] else None,
        "properties": props,
        "diff_from_previous": json.loads(row["diff"]) if isinstance(row["diff"], str) else row["diff"],
        "provenance": {
            "table": "object_versions",
            "primary_key": "rid",
            "ontology_class": f"dtmi:com:princeps:{row['label']};1",
            "time_travel": True,
        },
        "version_history": [
            {
                "op": h["op"],
                "valid_from": h["valid_from"].isoformat() if h["valid_from"] else None,
                "valid_to": h["valid_to"].isoformat() if h["valid_to"] else None,
                "diff": json.loads(h["diff"]) if isinstance(h["diff"], str) else h["diff"],
            }
            for h in history_rows
        ],
        "links": [],
        "history": [],
        "actions_available": [],
    }


@router.get("/{obj_type}/{obj_id}/versions")
async def list_object_versions(
    obj_type: str,
    obj_id: str,
    limit: int = Query(50, ge=1, le=500),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return the full version timeline for one object, newest first."""
    rid = f"rid.princeps.{obj_type.lower()}.{obj_id}"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT op, label, props, valid_from, valid_to, diff, actor
            FROM object_versions
            WHERE rid = $1
            ORDER BY valid_from DESC
            LIMIT $2
            """,
            rid, limit,
        )
    versions = []
    for r in rows:
        versions.append({
            "op": r["op"],
            "label": r["label"],
            "valid_from": r["valid_from"].isoformat() if r["valid_from"] else None,
            "valid_to": r["valid_to"].isoformat() if r["valid_to"] else None,
            "diff": json.loads(r["diff"]) if isinstance(r["diff"], str) else r["diff"],
            "actor": r["actor"],
            "props": json.loads(r["props"]) if isinstance(r["props"], str) else r["props"],
        })
    return {
        "rid": rid,
        "type": obj_type,
        "id": obj_id,
        "count": len(versions),
        "versions": versions,
    }


# ── Object-type catalogue (drives the type picker UI) ──────────────────────
@router.get("")
async def list_object_types():
    """Return the registered object types."""
    items = []
    for name, cfg in TYPE_REGISTRY.items():
        items.append({
            "type": name,
            "table": cfg["table"],
            "label_col": cfg["label_col"],
        })
    items.append({"type": "Entity", "table": "(union of CCOD + REPD + TEC)", "label_col": "name"})
    return {"types": items, "count": len(items)}
