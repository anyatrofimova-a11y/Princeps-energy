"""Substation Tracker router — canonical UK substation project list.

Endpoints
---------
    GET  /api/tracker/substations                list + filters
    GET  /api/tracker/substations/{project_id}   one full 30-field record
    GET  /api/tracker/substations/geojson        GeoJSON for map rendering
    GET  /api/tracker/substations.csv            CSV export
    GET  /api/tracker/stats                      summary aggregates
    POST /api/tracker/refresh                    (admin) trigger pipeline run

The router is thin — all heavy lifting lives in `utils/substation_tracker/`.
"""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, Response

from utils.substation_tracker.pipeline import (
    run_pipeline,
    list_rows,
    get_row,
    get_geojson,
    get_stats,
    ensure_subscription_schema,
)

log = logging.getLogger("princeps.substation_tracker.router")

router = APIRouter(prefix="/api/tracker", tags=["substation-tracker"])


# ---------------------------------------------------------------------------
# GET /api/tracker/substations
# ---------------------------------------------------------------------------
@router.get("/substations")
async def list_substations(
    request: Request,
    region: str | None = Query(None, description="Licence area or TO zone substring"),
    voltage: float | None = Query(None, description="Primary voltage kV exact match"),
    status: str | None = Query(None, description="construction_status value"),
    developer: str | None = Query(None, description="Licensee code e.g. UKPN"),
    year: int | None = Query(None, description="Construction or operation year"),
    limit: int = Query(1000, ge=1, le=10000),
):
    """List substation projects with optional filters.

    Returns a list of canonical rows. Each row contains the full 30-field
    `row_data` JSON + resolver metadata (match_reasons, member source types).
    """
    pool = request.app.state.pool
    rows = await list_rows(
        pool,
        region=region,
        voltage_kv=voltage,
        status=status,
        developer=developer,
        year=year,
        limit=limit,
    )
    return {"count": len(rows), "rows": rows}


# ---------------------------------------------------------------------------
# GET /api/tracker/substations/geojson
# ---------------------------------------------------------------------------
@router.get("/substations/geojson")
async def substations_geojson(
    request: Request,
    region: str | None = Query(None),
    voltage: float | None = Query(None),
    status: str | None = Query(None),
    developer: str | None = Query(None),
    year: int | None = Query(None),
    limit: int = Query(5000, ge=1, le=10000),
):
    """Return substations as a GeoJSON FeatureCollection for map rendering."""
    pool = request.app.state.pool
    return await get_geojson(
        pool,
        region=region,
        voltage_kv=voltage,
        status=status,
        developer=developer,
        year=year,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /api/tracker/substations.csv
# ---------------------------------------------------------------------------
@router.get("/substations.csv")
async def substations_csv(
    request: Request,
    region: str | None = Query(None),
    voltage: float | None = Query(None),
    status: str | None = Query(None),
    developer: str | None = Query(None),
    year: int | None = Query(None),
    limit: int = Query(10000, ge=1, le=50000),
):
    """CSV download — flat 30-field + provenance columns."""
    pool = request.app.state.pool
    rows = await list_rows(
        pool,
        region=region,
        voltage_kv=voltage,
        status=status,
        developer=developer,
        year=year,
        limit=limit,
    )

    # Build a flat CSV — one column per schema field plus resolver metadata.
    buf = io.StringIO()
    fieldnames = [
        "project_id", "substation_name", "station_type", "developer", "parent_company",
        "parent_project", "project_description", "upgrade_or_new",
        "region", "lpa", "county", "country",
        "geom_wkt", "osgb_easting", "osgb_northing",
        "voltage_kv_primary", "voltage_kv_secondary", "voltage_description",
        "equipment_description", "equipment_capacity_mva",
        "construction_year", "construction_date_detail", "construction_status",
        "operation_year", "operation_date_detail",
        "capex_gbp_millions", "capex_description", "capex_price_base_year",
        "financial_description",
        "source_type", "source_docket_id", "docket_profile_url", "capex_source_link",
        "source_links", "external_ids",
        "last_updated", "confidence", "sme_reviewed",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        rd = dict(r.get("row_data") or {})
        # Lists/dicts need to be JSON-serialised for CSV.
        rd["source_links"] = ";".join(rd.get("source_links") or [])
        rd["external_ids"] = ";".join(f"{k}={v}" for k, v in (rd.get("external_ids") or {}).items())
        writer.writerow(rd)

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="substations.csv"'},
    )


# ---------------------------------------------------------------------------
# GET /api/tracker/substations/{project_id}
# ---------------------------------------------------------------------------
@router.get("/substations/{project_id}")
async def substation_detail(request: Request, project_id: str):
    """Return the full 30-field record for one canonical project."""
    pool = request.app.state.pool
    row = await get_row(pool, project_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"project_id {project_id} not found")
    return row


# ---------------------------------------------------------------------------
# GET /api/tracker/stats
# ---------------------------------------------------------------------------
@router.get("/stats")
async def stats(request: Request):
    """Summary aggregates — count by region, voltage, status, developer."""
    pool = request.app.state.pool
    return await get_stats(pool)


# ---------------------------------------------------------------------------
# POST /api/tracker/refresh  (admin)
# ---------------------------------------------------------------------------
@router.post("/refresh")
async def refresh(
    request: Request,
    background_tasks: BackgroundTasks,
    include_ukpn: bool = Query(True),
    include_riio: bool = Query(False),
    include_noa: bool = Query(False),
    wait: bool = Query(False, description="Run synchronously and return full summary"),
):
    """Trigger a pipeline run.

    By default the refresh runs as a background task and returns immediately.
    Pass `wait=true` to block (useful for ad-hoc admin runs).

    TODO: gate this behind admin auth — the project's `app/auth.py` has the
    `require_admin` dep we should add here once the settings router ships
    the role mapping.
    """
    pool = request.app.state.pool
    await ensure_subscription_schema(pool)

    async def _run():
        try:
            await run_pipeline(
                pool,
                include_ukpn=include_ukpn,
                include_riio=include_riio,
                include_noa=include_noa,
            )
        except Exception:
            log.exception("Substation Tracker refresh failed")

    if wait:
        summary = await run_pipeline(
            pool,
            include_ukpn=include_ukpn,
            include_riio=include_riio,
            include_noa=include_noa,
        )
        return summary

    background_tasks.add_task(_run)
    return {
        "status": "started",
        "include_ukpn": include_ukpn,
        "include_riio": include_riio,
        "include_noa": include_noa,
    }
