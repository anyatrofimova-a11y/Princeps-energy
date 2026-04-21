"""
reports_fva — NPPF Financial Viability Assessment (FVA) PDF endpoint.

This is the planning-side FVA pack, NOT the investor DCF. The investor
DCF lives in `/api/reports/financial` (handled by `app/routers/reports.py`
via `utils/report_financial.py`) — both packs coexist deliberately per
COUNCIL-1 Rework #9 (FVA owned by BOT-X, DCF owned by BOT-M).

Route:
    POST /api/reports/nppf-fva?project_id=<uuid>
        &premium_band=central
        &profit_basis=gdv
        &profit_band=central
        &ppa_price=55

Returns: application/pdf (StreamingResponse)

Author: BOT-X · 2026-04-19
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.deps import get_pool
from utils.rics_fvp import FVAInputs, compute_fva, result_as_context
from utils.report_grid_connection import html_to_pdf
from utils.finance_benchmarks import ppa_price_merchant as _bench_ppa

log = logging.getLogger("princeps.reports_fva")
router = APIRouter(tags=["reports", "fva"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates" / "report"

_JINJA = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html",), default=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _region_from_latlon(lat: float | None, lon: float | None) -> str:
    """Very rough GB region bucketing, matches project_actions.py usage."""
    if lat is None:
        return "South"
    if lat >= 55.5:
        return "Scotland"
    if lat >= 53.5:
        return "North"
    if lat >= 52.5:
        return "Midlands"
    return "South"


def _existing_use_default(technology: str) -> str:
    """Sensible default existing-use for common UK energy site types."""
    tech = (technology or "").lower()
    if tech in ("solar", "bess"):
        return "arable"
    if tech in ("wind", "offshore_wind"):
        return "pasture"
    if tech == "dc":
        return "brownfield"
    return "arable"


async def _load_project(conn, project_id: UUID) -> dict:
    """Load project + optional site_boundaries/parcel — returns flat dict.

    Mirrors the pattern used by `project_actions._load_project_summary` but
    also pulls area from `site_boundaries` (preferred) and falls back to
    `parcels` via `project_sites`.
    """
    row = await conn.fetchrow(
        """SELECT project_id, name, technology, capacity_mw, lat, lon, metadata
           FROM projects WHERE project_id = $1""",
        project_id,
    )
    if not row:
        raise HTTPException(404, f"Project {project_id} not found")

    # Prefer site_boundaries (most accurate when the user has drawn a red-line)
    boundary = await conn.fetchrow(
        """SELECT area_ha, area_m2, centroid_lat, centroid_lon
           FROM site_boundaries
           WHERE project_id = $1 AND area_ha IS NOT NULL
           ORDER BY area_ha DESC LIMIT 1""",
        project_id,
    )

    # Fallback — first linked parcel via project_sites
    parcel = None
    if boundary is None:
        parcel = await conn.fetchrow(
            """SELECT ST_Y(ST_Transform(p.centroid, 4326)) AS lat,
                      ST_X(ST_Transform(p.centroid, 4326)) AS lon,
                      p.area_m2
               FROM project_sites ps
               LEFT JOIN parcels p ON p.parcel_id = ps.parcel_id
               WHERE ps.project_id = $1 LIMIT 1""",
            project_id,
        )

    area_ha: float | None = None
    if boundary and boundary["area_ha"]:
        area_ha = float(boundary["area_ha"])
    elif boundary and boundary["area_m2"]:
        area_ha = float(boundary["area_m2"]) / 10_000.0
    elif parcel and parcel["area_m2"]:
        area_ha = float(parcel["area_m2"]) / 10_000.0

    # Metadata may carry an LPA string under 'lpa' or 'planning.lpa'.
    # asyncpg returns jsonb as a str → json.loads, or a dict if the decoder
    # has been registered — handle both.
    import json as _json
    raw_meta = row["metadata"]
    if isinstance(raw_meta, str):
        try:
            meta = _json.loads(raw_meta) or {}
        except Exception:
            meta = {}
    elif isinstance(raw_meta, dict):
        meta = raw_meta
    else:
        meta = {}
    lpa = meta.get("lpa")
    if not lpa and isinstance(meta.get("planning"), dict):
        lpa = meta["planning"].get("lpa")

    return {
        "project_id": str(row["project_id"]),
        "name":        row["name"] or "Untitled Project",
        "technology":  (row["technology"] or "solar").lower(),
        "capacity_mw": float(row["capacity_mw"]) if row["capacity_mw"] else 50.0,
        "lat":         float(row["lat"]) if row["lat"] is not None else None,
        "lon":         float(row["lon"]) if row["lon"] is not None else None,
        "area_ha":     area_ha,
        "lpa":         lpa or "",
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.post("/api/reports/nppf-fva")
async def nppf_fva_report(
    project_id: str = Query(..., description="Project UUID"),
    existing_use: str | None = Query(
        None,
        description=(
            "Existing-use key (arable, pasture, rough_grazing, orchard, nursery, "
            "woodland, brownfield, amenity, mixed). Defaults per technology."
        ),
    ),
    premium_band: str = Query(
        "central",
        pattern="^(low|central|high)$",
        description="Landowner premium band (RICS FVP 2021 §3.5)",
    ),
    profit_basis: str = Query(
        "gdv",
        pattern="^(gdv|cost)$",
        description="Developer profit basis (RICS FVP 2021 §4.6)",
    ),
    profit_band: str = Query(
        "central",
        pattern="^(low|central|high)$",
        description="Developer profit band within basis",
    ),
    ppa_price: float = Query(_bench_ppa("solar"), ge=1.0, le=500.0, description="PPA £/MWh (default: finance_benchmarks solar merchant midpoint)"),
    ppa_term_yr: int = Query(15, ge=5, le=25, description="PPA term (years)"),
    exit_yield: float = Query(0.075, ge=0.04, le=0.12, description="Capitalisation yield"),
    capex_m_override: float | None = Query(
        None, description="Override CAPEX (£m). If omitted, uses benchmark £/MW."
    ),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate an NPPF Financial Viability Assessment PDF.

    Follows the RICS Professional Standard "Financial Viability in Planning:
    Conduct and Reporting" 2nd ed. (2021) residual-appraisal method. Output is
    suitable for submission with a planning application, s73 variation, or
    s106 renegotiation.
    """
    try:
        pid = UUID(project_id)
    except ValueError:
        raise HTTPException(422, "project_id must be a valid UUID")

    async with pool.acquire() as conn:
        proj = await _load_project(conn, pid)

        # Optional: pull comparable-transaction evidence for BLV stress-test
        market_blv_per_ha: float | None = None
        try:
            from utils.precedent_transactions import find_precedent_transactions
            region = _region_from_latlon(proj.get("lat"), proj.get("lon"))
            precedents = await find_precedent_transactions(
                conn,
                technology=proj["technology"],
                capacity_mw=proj["capacity_mw"],
                region=region,
                year=datetime.utcnow().year,
                top_n=5,
            )
            # Best-effort: if precedents include a per-ha land value, pick median
            per_ha_values = [
                float(p["land_value_per_ha"])
                for p in precedents
                if p.get("land_value_per_ha")
            ]
            if per_ha_values:
                per_ha_values.sort()
                market_blv_per_ha = per_ha_values[len(per_ha_values) // 2]
        except Exception as exc:
            log.info("nppf-fva: no comparable land-value evidence (%s)", exc)

    # Build inputs
    inp = FVAInputs(
        project_id=proj["project_id"],
        site_name=proj["name"],
        technology=proj["technology"],
        capacity_mw=proj["capacity_mw"],
        area_ha=proj["area_ha"] or (proj["capacity_mw"] * 2.0),  # 2 ha/MW rule-of-thumb
        existing_use=(existing_use or _existing_use_default(proj["technology"])).lower(),
        lpa=proj["lpa"],
        region=_region_from_latlon(proj.get("lat"), proj.get("lon")),
        ppa_price=ppa_price,
        ppa_term_yr=ppa_term_yr,
        exit_yield=exit_yield,
        premium_band=premium_band,
        profit_basis=profit_basis,
        profit_band=profit_band,
        market_blv_per_ha=market_blv_per_ha,
        capex_m_override=capex_m_override,
    )

    # Compute
    try:
        result = compute_fva(inp)
    except Exception as exc:
        log.exception("FVA compute failed")
        raise HTTPException(500, f"FVA compute failed: {exc}")

    # Render
    ctx = result_as_context(inp, result)
    ctx["generated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    # Document reference code per spec §h (PROJ-PACK-REV)
    proj_code = (proj["name"].upper().replace(" ", "-")[:8]) or "SITE"
    ctx["doc_ref"] = f"{proj_code}-FVA-P01"

    try:
        tmpl = _JINJA.get_template("nppf_fva.html")
        html = tmpl.render(**ctx)
    except Exception as exc:
        log.exception("FVA template render failed")
        raise HTTPException(500, f"FVA template render failed: {exc}")

    try:
        pdf_bytes = await html_to_pdf(html)
    except Exception as exc:
        log.exception("FVA PDF render failed")
        raise HTTPException(500, f"FVA PDF render failed: {exc}")

    # Filename: {ProjectName}-FVA-{Rev}-{ISO-date}.pdf per spec §h
    safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in proj["name"])[:60] or "site"
    filename = f"{safe_name}-FVA-P01-{datetime.utcnow().strftime('%Y%m%d')}.pdf"

    log.info(
        "nppf-fva: project=%s rlv=£%.2fm blv=£%.2fm verdict=%s pdf_kb=%.0f",
        project_id, result.rlv / 1e6, result.blv / 1e6,
        result.verdict, len(pdf_bytes) / 1024,
    )

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Princeps-FVA-Verdict": result.verdict,
            "X-Princeps-FVA-RLV-M": f"{result.rlv/1e6:.2f}",
            "X-Princeps-FVA-BLV-M": f"{result.blv/1e6:.2f}",
        },
    )
