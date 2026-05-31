"""UK grid + planning application templates router.

Endpoints
---------
GET    /api/applications/templates                 — full catalog
GET    /api/applications/templates/{id}            — single template spec
POST   /api/applications/prefill                   — agent pre-fill (returns
                                                     filled payload + render)
POST   /api/applications/filings                   — persist a draft filing
GET    /api/applications/filings                   — list (filter project)
GET    /api/applications/filings/{rid}             — single filing detail
GET    /api/applications/filings/{rid}/render      — HTML render
POST   /api/applications/filings/{rid}/submit      — mark as submitted

The pre-fill agent uses three data lakes:
  1. ``projects`` / ``candidate_sites`` for site coordinates + capacity
  2. ``grid_substations`` for nearest substation / DNO
  3. ``planning_designations`` for constraints

When the template has a ``generator_fn`` registered it imports it lazily
and calls it; otherwise the response is the structured spec + populated
fields (the client can render its own preview).
"""

from __future__ import annotations

import importlib
import json
import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.deps import get_pool

log = logging.getLogger("princeps.applications")
router = APIRouter(prefix="/api/applications", tags=["applications"])


# ── Catalog ─────────────────────────────────────────────────────────────────

@router.get("/templates")
async def list_templates(
    category: str | None = Query(None),
    authority: str | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    where = []
    params: list[Any] = []
    def _bind(v):
        params.append(v)
        return f"${len(params)}"
    if category:  where.append(f"category = {_bind(category)}")
    if authority: where.append(f"authority = {_bind(authority)}")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = await pool.fetch(
        f"""SELECT template_id, category, doc_type, title, authority,
                   legal_basis, applicable_when,
                   (generator_fn IS NOT NULL) AS auto_prefill_available,
                   required_fields, optional_fields, output_format,
                   evidence_list, estimated_pages, estimated_minutes
              FROM applications.templates {where_sql}
             ORDER BY category, title""",
        *params,
    )
    return {"items": [dict(r) for r in rows], "count": len(rows)}


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    row = await pool.fetchrow(
        "SELECT * FROM applications.templates WHERE template_id = $1",
        template_id,
    )
    if not row:
        raise HTTPException(404, f"template '{template_id}' not found")
    return dict(row)


@router.get("/categories")
async def list_categories(pool: asyncpg.Pool = Depends(get_pool)):
    rows = await pool.fetch(
        """SELECT category, authority, COUNT(*) AS template_count
             FROM applications.templates
            GROUP BY category, authority
            ORDER BY category, authority""",
    )
    return {"items": [dict(r) for r in rows]}


# ── Pre-fill agent ──────────────────────────────────────────────────────────

class PrefillRequest(BaseModel):
    template_id: str
    project_rid: str | None = None
    site_rid: str | None = None
    overrides: dict[str, Any] = {}
    render: bool = True


async def _gather_project_context(
    pool: asyncpg.Pool,
    project_rid: str | None,
    site_rid: str | None,
) -> dict[str, Any]:
    """Pull whatever project / site rows exist into a flat dict the
    template generators expect."""
    ctx: dict[str, Any] = {
        "site": {}, "capacity": {}, "grid": {},
        "technology": {}, "constraints": {}, "timeline": {},
    }
    if project_rid:
        try:
            row = await pool.fetchrow(
                "SELECT * FROM projects WHERE project_id::text = $1",
                project_rid,
            )
        except Exception:
            row = None
        if row:
            ctx["site"]["project_name"] = row["name"]
            ctx["site"]["lat"] = row.get("centroid_lat") if "centroid_lat" in row else None
            ctx["site"]["lon"] = row.get("centroid_lon") if "centroid_lon" in row else None
            cap = row.get("capacity_mw") if "capacity_mw" in row else None
            if cap:
                ctx["capacity"]["capacity_mw"] = float(cap)
                ctx["capacity"]["capacity_kw"] = float(cap) * 1000
            tech = row.get("technology") if "technology" in row else None
            if tech:
                ctx["technology"]["primary"] = tech
    if site_rid:
        try:
            row = await pool.fetchrow(
                "SELECT * FROM candidate_sites WHERE site_id::text = $1",
                site_rid,
            )
        except Exception:
            row = None
        if row:
            for k in ("address", "postcode", "uprn", "title_number"):
                if k in row and row[k] is not None:
                    ctx["site"][k] = row[k]
    # Nearest substation lookup if we have coords
    lat, lon = ctx["site"].get("lat"), ctx["site"].get("lon")
    if lat and lon:
        try:
            sub = await pool.fetchrow(
                """SELECT name, dno, voltage_kv,
                          ST_Distance(geom, ST_SetSRID(ST_MakePoint($1,$2),4326)::geography) AS dist_m
                     FROM grid_substations
                    WHERE geom IS NOT NULL
                    ORDER BY geom <-> ST_SetSRID(ST_MakePoint($1,$2),4326)
                    LIMIT 1""",
                float(lon), float(lat),
            )
            if sub:
                ctx["grid"]["nearest_substation"] = sub["name"]
                ctx["grid"]["dno"] = sub["dno"]
                ctx["grid"]["voltage_kv"] = float(sub["voltage_kv"]) if sub["voltage_kv"] else None
                ctx["grid"]["distance_m"] = round(float(sub["dist_m"]), 0)
        except Exception as exc:
            log.info("substation lookup failed: %s", exc)
    return ctx


@router.post("/prefill")
async def prefill(
    payload: PrefillRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    tmpl = await pool.fetchrow(
        "SELECT * FROM applications.templates WHERE template_id = $1",
        payload.template_id,
    )
    if not tmpl:
        raise HTTPException(404, f"template '{payload.template_id}' not found")

    ctx = await _gather_project_context(pool, payload.project_rid, payload.site_rid)
    # Deep-merge overrides on top of derived context
    for k, v in (payload.overrides or {}).items():
        if isinstance(v, dict) and isinstance(ctx.get(k), dict):
            ctx[k] = {**ctx[k], **v}
        else:
            ctx[k] = v

    response: dict[str, Any] = {
        "template_id": payload.template_id,
        "title": tmpl["title"],
        "authority": tmpl["authority"],
        "auto_prefill_available": tmpl["generator_fn"] is not None,
        "filled_payload": ctx,
        "missing_required": _check_missing(tmpl, ctx),
        "rendered": None,
    }

    if payload.render and tmpl["generator_fn"]:
        try:
            mod_path, fn_name = tmpl["generator_fn"].rsplit(".", 1)
            mod = importlib.import_module(mod_path)
            fn = getattr(mod, fn_name)
            generated = fn(**ctx) if _accepts_kwargs(fn) else fn(ctx)
            response["rendered"] = (
                generated.get("html") if isinstance(generated, dict) else generated
            )
            if isinstance(generated, dict):
                response["form"] = generated.get("form")
        except Exception as exc:
            log.warning("generator %s failed: %s", tmpl["generator_fn"], exc)
            response["render_error"] = f"{type(exc).__name__}: {exc}"
    return response


def _accepts_kwargs(fn) -> bool:
    import inspect
    sig = inspect.signature(fn)
    return any(
        p.kind in (p.VAR_KEYWORD,) or p.default is not p.empty
        for p in sig.parameters.values()
    )


def _check_missing(template_row, ctx: dict) -> list[str]:
    missing = []
    for f in (template_row.get("required_fields") or []):
        if isinstance(f, str):
            field_meta = json.loads(f)
        else:
            field_meta = f
        name = field_meta.get("name")
        if not name:
            continue
        v = ctx.get(name)
        if v is None or v == {} or v == "":
            missing.append(name)
    return missing


# ── Filings ────────────────────────────────────────────────────────────────

class FilingCreate(BaseModel):
    template_id: str
    project_rid: str | None = None
    site_rid: str | None = None
    payload: dict[str, Any]
    rendered_html: str | None = None
    status: str = "draft"


@router.post("/filings")
async def create_filing(
    payload: FilingCreate,
    pool: asyncpg.Pool = Depends(get_pool),
):
    rid = await pool.fetchval(
        """INSERT INTO applications.filings
              (template_id, project_rid, site_rid, payload, rendered_html, status)
           VALUES ($1, $2, $3, $4::jsonb, $5, $6)
           RETURNING filing_rid""",
        payload.template_id, payload.project_rid, payload.site_rid,
        json.dumps(payload.payload), payload.rendered_html, payload.status,
    )
    return {"filing_rid": rid}


@router.get("/filings")
async def list_filings(
    project_rid: str | None = Query(None),
    status: str | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    where = []
    params: list[Any] = []
    def _bind(v):
        params.append(v); return f"${len(params)}"
    if project_rid: where.append(f"f.project_rid = {_bind(project_rid)}")
    if status:      where.append(f"f.status = {_bind(status)}")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = await pool.fetch(
        f"""SELECT f.filing_rid, f.template_id, t.title AS template_title,
                   t.category, t.authority,
                   f.project_rid, f.site_rid, f.status,
                   f.submitted_at, f.reference_no, f.updated_at
              FROM applications.filings f
              JOIN applications.templates t ON f.template_id = t.template_id
            {where_sql}
            ORDER BY f.updated_at DESC LIMIT 200""",
        *params,
    )
    return {"items": [dict(r) for r in rows]}


@router.get("/filings/{filing_rid}")
async def get_filing(
    filing_rid: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    row = await pool.fetchrow(
        "SELECT * FROM applications.filings WHERE filing_rid = $1",
        filing_rid,
    )
    if not row:
        raise HTTPException(404, "filing not found")
    return dict(row)


@router.get("/filings/{filing_rid}/render")
async def render_filing(
    filing_rid: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    from fastapi.responses import HTMLResponse
    row = await pool.fetchrow(
        "SELECT rendered_html FROM applications.filings WHERE filing_rid = $1",
        filing_rid,
    )
    if not row or not row["rendered_html"]:
        raise HTTPException(404, "no rendered HTML for this filing")
    return HTMLResponse(row["rendered_html"])


class FilingSubmit(BaseModel):
    submitted_to: str | None = None
    reference_no: str | None = None


@router.post("/filings/{filing_rid}/submit")
async def submit_filing(
    filing_rid: str,
    payload: FilingSubmit,
    pool: asyncpg.Pool = Depends(get_pool),
):
    res = await pool.execute(
        """UPDATE applications.filings
              SET status = 'submitted',
                  submitted_at = now(),
                  submitted_to = COALESCE($2, submitted_to),
                  reference_no = COALESCE($3, reference_no),
                  updated_at = now()
            WHERE filing_rid = $1""",
        filing_rid, payload.submitted_to, payload.reference_no,
    )
    return {"updated": res.endswith("UPDATE 1")}
