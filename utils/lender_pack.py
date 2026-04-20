"""
Princeps Lender Information Pack generator.

Produces a 15-section institutional lender pack as A4 PDF. The pack is the
credit-paper-ready version of the existing Financial Viability report and
is the document on which a UK project-finance lender would actually base a
go / no-go credit decision.

Structure (COUNCIL-1 rewrite spec, 2026-04-19):
  1. Cover + reliance addressee
  2. Transaction summary
  3. Sources & Uses + capital stack waterfall
  4. Base-case model pack (FCFF, FCFE, waterfall, amortising debt — DCFEvaluator)
  5. Downside case (utilisation −20%, PPA −15%, capex +10%)
  6. Breakeven case (DSCR 1.20x floor bisection)
  7. Covenant package (DSCR, LLCR, PLCR, ICR, Gearing, DSRA) with cure rights
  8. Material Event List (MEL)
  9. Technical Due Diligence Review (TDDR)
 10. Conditions Precedent (CP) — from utils.cp_cs_schedule
 11. Conditions Subsequent (CS) — from utils.cp_cs_schedule
 12. Precedent transactions — from utils.precedent_transactions
 13. Security & account structure
 14. Model audit trail appendix
 15. Reliance, qualifications, signature block

Branding: canonical Princeps gold palette (D4A018) per
templates/report/institutional_base.html.

Regulatory citations — LMA Investment Grade Facility Agreement 2024
(covenant language), PRA SS31/15 (MEL / reverse stress), RICS Red Book
Global 2025 VPS 3 (reliance).

Pipeline: assemble context → run DCFEvaluator (base / downside / breakeven)
→ build 15 section dicts → Jinja render → Playwright PDF.

Back-compat: the old render_lender_pack_html(doc, ...) signature from the
legacy 167-line pack is preserved as a thin shim that forwards to the new
renderer with mapped inputs. app/routers/finance_extras.py still imports
it and must keep working.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

# BOT-A — DCF engine + covenant timeline
from utils.dcf_evaluator import DCFEvaluator, DCFResult, build_amortising_debt

# BOT-M — financial viability charts, amortising schedule flattening
from utils.financial_viability_charts import (
    generate_dcf_charts,
    build_amortising_schedule_rows,
)

# BOT-M — precedent transactions (imported lazily because it needs asyncpg.Pool)

# BOT-P — CP/CS schedule
try:
    from utils.cp_cs_schedule import generate_cp_cs_schedule
except Exception:  # pragma: no cover
    generate_cp_cs_schedule = None  # type: ignore

# BOT-R2 — OSGB + regulatory version helpers (may not exist yet)
try:
    from utils.osgb import wgs84_to_osgb36, bng_from_en  # type: ignore
except Exception:  # pragma: no cover
    wgs84_to_osgb36 = None  # type: ignore
    bng_from_en = None  # type: ignore

try:
    from app.regulatory.versions import regulatory_citations  # type: ignore
except Exception:  # pragma: no cover
    regulatory_citations = None  # type: ignore

# Sections
from utils.lender_pack_sections import (
    build_cover,
    build_transaction_summary,
    build_sources_uses,
    build_base_case,
    build_downside_case,
    build_breakeven_case,
    build_covenant_package,
    build_material_event_list,
    build_tddr,
    build_cp_schedule,
    build_cs_schedule,
    build_precedent_transactions,
    build_security_structure,
    build_model_audit,
    build_signature_block,
)

log = logging.getLogger("princeps.lender_pack")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "report"
_DD_SCRIPT = Path(__file__).resolve().parent / "due_diligence.py"

MODEL_VERSION = "LenderPack v2.0 (COUNCIL-1 rewrite, 2026-04-19)"

# Defaults — align with report_financial.py
DEFAULT_GEARING = 0.70
DEFAULT_INTEREST_RATE = 0.06
DEFAULT_DEBT_TERM_YEARS = 18
DEFAULT_WACC = 0.075
DEFAULT_TAX_RATE = 0.25
DEFAULT_MARGIN_BPS = 250
DEFAULT_TARGET_DSCR = 1.30
DEFAULT_TARGET_LLCR = 1.40

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
)


# ---------------------------------------------------------------------------
# Cashflow builders (shared with report_financial)
# ---------------------------------------------------------------------------

def _build_revenue_opex_schedules(
    capacity_mw: float,
    technology: str,
    ppa_price: float,
) -> tuple[list[float], list[float], float, float]:
    """Return (revenue_schedule, opex_schedule, total_capex, annual_opex_yr1)."""
    from utils.investment_appraisal import (
        CAPEX_PER_MW, OPEX_PER_MW, CAPACITY_FACTORS, REVENUE_PER_MW,
        DEGRADATION_RATE, INFLATION, PROJECT_LIFE,
    )
    capex_mw = CAPEX_PER_MW.get(technology, CAPEX_PER_MW.get("solar", 550_000))
    opex_mw = OPEX_PER_MW.get(technology, OPEX_PER_MW.get("solar", 12_000))
    cf = CAPACITY_FACTORS.get(technology, 0.11)
    is_bess = technology == "bess"
    annual_gen_mwh = capacity_mw * cf * 8760 if not is_bess else 0
    bess_revenue_base = REVENUE_PER_MW.get(technology, 0) * capacity_mw if is_bess else 0
    annual_opex = opex_mw * capacity_mw
    total_capex = capex_mw * capacity_mw

    revenue: list[float] = []
    opex: list[float] = []
    for y in range(1, PROJECT_LIFE + 1):
        if is_bess:
            rev = bess_revenue_base * (1 + INFLATION) ** y * (1 - DEGRADATION_RATE * 2) ** y
        else:
            deg_gen = annual_gen_mwh * (1 - DEGRADATION_RATE) ** y
            rev = deg_gen * ppa_price * (1 + INFLATION) ** y
        opx = annual_opex * (1 + INFLATION) ** y
        revenue.append(rev)
        opex.append(opx)
    return revenue, opex, total_capex, annual_opex


# ---------------------------------------------------------------------------
# DD subprocess bridges
# ---------------------------------------------------------------------------

def _run_dd(command: str, **kwargs) -> dict:
    """Run utils/due_diligence.py as subprocess; fall back to empty dict."""
    import json as _json
    python = os.environ.get("PYTHON", sys.executable)
    payload = {"command": command, **kwargs}
    try:
        res = subprocess.run(
            [python, str(_DD_SCRIPT)],
            input=_json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=20,
        )
        if res.returncode != 0:
            log.warning("DD subprocess failure (%s): %s", command, res.stderr[:200])
            return {}
        return _json.loads(res.stdout)
    except Exception as exc:  # pragma: no cover
        log.warning("DD subprocess exception (%s): %s", command, exc)
        return {}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def _assemble_context(
    *,
    project_id: str,
    project_name: str,
    sponsor: str,
    technology: str,
    capacity_mw: float,
    lat: float | None,
    lon: float | None,
    region: str,
    dno: str,
    poc_voltage_kv: float,
    ppa_price: float,
    bank_name: str,
    mla_names: list[str] | None,
    cod_target: str | None,
    has_grid_offer: bool,
    has_planning_consent: bool,
    has_ppa: bool,
    gearing_pct: float,
    interest_rate: float,
    debt_term_years: int,
    wacc: float,
    margin_bps: int,
    target_dscr: float,
    target_llcr: float,
    project_metadata: dict | None,
    pool: Any | None,
) -> dict[str, Any]:
    """Run all subprocess / model / DB calls and assemble the section dicts."""
    generated_at = datetime.utcnow()

    # 1. Build cashflow schedules + run DCF
    revenue, opex, total_capex, annual_opex_yr1 = _build_revenue_opex_schedules(
        capacity_mw, technology, ppa_price,
    )
    life = len(revenue)
    debt_principal = total_capex * gearing_pct
    debt_schedule = build_amortising_debt(
        principal=debt_principal,
        rate=interest_rate,
        term_years=debt_term_years,
        life_years=life,
    )
    evaluator = DCFEvaluator(
        capex=total_capex,
        revenue_schedule=revenue,
        opex_schedule=opex,
        tax_rate=DEFAULT_TAX_RATE,
        wacc=wacc,
        terminal_growth=0.0,
        debt_schedule=debt_schedule,
    )
    dcf_result: DCFResult = evaluator.evaluate()
    amortising_rows = build_amortising_schedule_rows(dcf_result)
    charts = generate_dcf_charts(dcf_result, wacc)

    # 2. Run downside + breakeven concurrently in thread-pool (CPU-bound)
    loop = asyncio.get_running_loop()

    downside_future = loop.run_in_executor(
        None,
        lambda: build_downside_case(
            base_capex=total_capex,
            base_revenue=revenue,
            base_opex=opex,
            wacc=wacc,
            gearing_pct=gearing_pct,
            interest_rate=interest_rate,
            debt_term_years=debt_term_years,
        ),
    )
    breakeven_future = loop.run_in_executor(
        None,
        lambda: build_breakeven_case(
            base_capex=total_capex,
            base_revenue=revenue,
            base_opex=opex,
            wacc=wacc,
            gearing_pct=gearing_pct,
            interest_rate=interest_rate,
            debt_term_years=debt_term_years,
        ),
    )

    # 3. DD checklist + technical_dd + commercial_dd
    dd_checklist_future = loop.run_in_executor(
        None,
        lambda: _run_dd(
            "dd_checklist",
            capacity_mw=capacity_mw,
            technology=technology if technology in {"solar", "wind", "bess", "offshore_wind"} else "solar",
            region=region,
            resource_quality="indicative",
            oem_tier="tier_1",
            has_ppa=has_ppa,
            has_planning=has_planning_consent,
            grid_offer=has_grid_offer,
        ),
    )
    technical_dd_future = loop.run_in_executor(
        None,
        lambda: _run_dd(
            "technical_dd",
            capacity_mw=capacity_mw,
            technology=technology if technology in {"solar", "wind", "bess", "offshore_wind"} else "solar",
            resource_quality="indicative",
            oem_tier="tier_1",
            grid_offer=has_grid_offer,
        ),
    )
    commercial_dd_future = loop.run_in_executor(
        None,
        lambda: _run_dd(
            "commercial_dd",
            capacity_mw=capacity_mw,
            technology=technology if technology in {"solar", "wind", "bess", "offshore_wind"} else "solar",
            ppa_price=ppa_price,
            has_ppa=has_ppa,
            region=region,
        ),
    )

    # 4. CP/CS schedule (BOT-P)
    cp_cs_future = None
    if generate_cp_cs_schedule is not None:
        cp_cs_future = loop.run_in_executor(
            None,
            lambda: generate_cp_cs_schedule(
                project_name=project_name,
                target_close_date=None,
                cod_date=cod_target,
                project_metadata=project_metadata,
                capacity_mw=capacity_mw,
                tech_type=technology,
                region=region,
            ),
        )

    # 5. Precedent transactions (BOT-M) — needs asyncpg pool
    precedent_rows: list[dict[str, Any]] | None = None
    if pool is not None:
        try:
            from utils.precedent_transactions import find_precedent_transactions
            async with pool.acquire() as conn:
                precedent_rows = await find_precedent_transactions(
                    conn=conn,
                    technology=technology,
                    capacity_mw=capacity_mw,
                    region=region,
                    year=generated_at.year,
                    top_n=5,
                )
        except Exception as exc:
            log.warning("Precedent transactions lookup failed: %s", exc)
            precedent_rows = None

    # 6. Await all futures
    downside = await downside_future
    breakeven = await breakeven_future
    dd_checklist = await dd_checklist_future
    technical_dd = await technical_dd_future
    commercial_dd = await commercial_dd_future
    cp_cs_output = await cp_cs_future if cp_cs_future else None

    # 7. Build section dicts
    sec_cover = build_cover(
        project_name=project_name,
        sponsor=sponsor,
        bank_name=bank_name,
        mla_names=mla_names,
        revision="P01",
        generated_at=generated_at,
    )
    sec_txn = build_transaction_summary(
        project_name=project_name,
        sponsor=sponsor,
        technology=technology,
        capacity_mw=capacity_mw,
        capex_gbp=total_capex,
        gearing_pct=gearing_pct,
        debt_term_years=debt_term_years,
        interest_rate_pct=interest_rate * 100,
        target_dscr=target_dscr,
        target_llcr=target_llcr,
        margin_bps=margin_bps,
        region=region,
        dno=dno,
        poc_voltage_kv=poc_voltage_kv,
        cod_target=cod_target,
    )
    sec_sources_uses = build_sources_uses(
        capex_gbp=total_capex,
        gearing_pct=gearing_pct,
        debt_principal_gbp=debt_principal,
        dsra_months=6,
        opex_gbp_yr1=annual_opex_yr1,
    )
    sec_base = build_base_case(
        dcf_result=dcf_result,
        amortising_rows=amortising_rows,
        wacc_pct=wacc * 100,
    )
    sec_downside = downside
    sec_breakeven = breakeven
    sec_covenants = build_covenant_package(
        base_case_summary=dcf_result.summary,
        downside_case_summary=downside.get("summary") if downside.get("available") else None,
    )
    sec_mel = build_material_event_list(
        technology=technology,
        capacity_mw=capacity_mw,
        has_grid_offer=has_grid_offer,
        has_planning_consent=has_planning_consent,
        has_ppa=has_ppa,
    )
    sec_tddr = build_tddr(
        technology=technology,
        capacity_mw=capacity_mw,
        dd_checklist=dd_checklist,
        technical_dd=technical_dd,
        commercial_dd=commercial_dd,
        has_grid_offer=has_grid_offer,
        has_planning_consent=has_planning_consent,
        has_ppa=has_ppa,
    )
    sec_cp = build_cp_schedule(cp_cs_output)
    sec_cs = build_cs_schedule(cp_cs_output)
    sec_precedents = build_precedent_transactions(
        precedent_rows=precedent_rows,
        technology=technology,
        capacity_mw=capacity_mw,
        region=region,
    )
    sec_security = build_security_structure()
    sec_audit = build_model_audit(
        generated_at=generated_at,
        model_version=MODEL_VERSION,
        dcf_params={
            "capex_gbp": total_capex,
            "gearing_pct": gearing_pct,
            "debt_principal_gbp": debt_principal,
            "interest_rate_pct": interest_rate * 100,
            "debt_term_years": debt_term_years,
            "wacc_pct": wacc * 100,
            "tax_rate_pct": DEFAULT_TAX_RATE * 100,
            "life_years": life,
            "ppa_price_gbp_mwh": ppa_price,
        },
    )
    sec_signature = build_signature_block(
        project_name=project_name,
        generated_at=generated_at,
    )

    # OSGB grid reference (fallback inline if osgb util not present)
    osgb_ref = _format_osgb(lat, lon)

    # Regulatory citations (fallback inline if versions module not available)
    reg_cites = _regulatory_citations_fallback()

    return {
        "project_id": project_id,
        "project_name": project_name,
        "sponsor": sponsor,
        "technology": technology,
        "technology_label": technology.upper(),
        "capacity_mw": capacity_mw,
        "lat": lat,
        "lon": lon,
        "osgb_grid_ref": osgb_ref,
        "region": region,
        "generated_at_display": generated_at.strftime("%d %b %Y %H:%M UTC"),
        "generated_at_iso": generated_at.isoformat() + "Z",
        "model_version": MODEL_VERSION,
        "sections": {
            "cover": sec_cover,
            "transaction": sec_txn,
            "sources_uses": sec_sources_uses,
            "base_case": sec_base,
            "downside": sec_downside,
            "breakeven": sec_breakeven,
            "covenants": sec_covenants,
            "mel": sec_mel,
            "tddr": sec_tddr,
            "cp": sec_cp,
            "cs": sec_cs,
            "precedents": sec_precedents,
            "security": sec_security,
            "model_audit": sec_audit,
            "signature": sec_signature,
        },
        "charts": charts,
        "regulatory_citations": reg_cites,
    }


def _format_osgb(lat: float | None, lon: float | None) -> str | None:
    if lat is None or lon is None:
        return None
    if wgs84_to_osgb36 is not None and bng_from_en is not None:
        try:
            easting, northing = wgs84_to_osgb36(lat, lon)
            return bng_from_en(easting, northing)
        except Exception:  # pragma: no cover
            pass
    # Inline fallback — linear approx, explicitly flagged as approximate.
    # TODO(BOT-R2): replace with pyproj OSGB36 transform when utils.osgb ships.
    try:
        # Very rough central UK approximation — do NOT use for submission.
        return f"Approx WGS84 {lat:.5f}°N, {lon:.5f}°E (OSGB36 requires utils.osgb)"
    except Exception:  # pragma: no cover
        return None


def _regulatory_citations_fallback() -> list[dict[str, str]]:
    if regulatory_citations is not None:
        try:
            return list(regulatory_citations(scope="lender_pack"))
        except Exception:  # pragma: no cover
            pass
    # Inline fallback list — pulled from paperwork_rewrite_spec.md
    # TODO(BOT-R2): replace with app.regulatory.versions.regulatory_citations().
    return [
        {"standard": "LMA Investment Grade Facility Agreement",
         "version": "English law, 2024 update",
         "url": "https://www.lma.eu.com/documents",
         "role": "Primary covenant + CP/CS framework"},
        {"standard": "PRA Supervisory Statement SS31/15",
         "version": "2015 (as updated)",
         "url": "https://www.bankofengland.co.uk/prudential-regulation/publication/2016/the-internal-capital-adequacy-assessment-process-icaap-and-the-supervisory-review-and-evaluation-process-srep-ss",
         "role": "ICAAP / risk register / reverse stress"},
        {"standard": "RICS Red Book Global Standards",
         "version": "Effective 31 Jan 2025",
         "url": "https://www.rics.org/profession-standards/rics-standards-and-guidance/sector-standards/valuation-standards",
         "role": "Reliance and liability (VPS 3)"},
        {"standard": "BVCA Investor Reporting Guidelines",
         "version": "2022",
         "url": "https://www.bvca.co.uk/Policy/Industry-guidelines-and-standards",
         "role": "IC memo cover-page format"},
        {"standard": "ENA EREC G99",
         "version": "Issue 2 (10 March 2025)",
         "url": "https://www.energynetworks.org/industry-hub/resource-library/ena-eng-rec-g99-issue-2.pdf",
         "role": "Grid connection technical compliance (cross-ref §9 TDDR)"},
        {"standard": "NESO Security of Supply Outlook Framework",
         "version": "2025",
         "url": "https://www.neso.energy/publications/security-of-supply",
         "role": "Market / capacity context"},
        {"standard": "CDM Regulations 2015 (SI 2015/51)",
         "version": "2015, HSE L153 ACoP",
         "url": "https://www.hse.gov.uk/construction/cdm/2015/",
         "role": "Construction-phase compliance (cross-ref §8 MEL construction row)"},
    ]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_html(context: dict[str, Any]) -> str:
    template = _jinja_env.get_template("lender_pack.html")
    return template.render(**context)


async def _html_to_pdf(html_string: str) -> bytes:
    """Convert HTML to PDF via Playwright Chromium."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright not installed. Run: pip install playwright && playwright install chromium"
        ) from exc

    tmp = tempfile.NamedTemporaryFile(
        suffix=".html", delete=False, mode="w", encoding="utf-8",
    )
    try:
        tmp.write(html_string)
        tmp.close()
        file_url = f"file://{tmp.name}"
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch()
            except Exception as exc:
                raise RuntimeError(
                    "Chromium not installed. Run: playwright install chromium"
                ) from exc
            page = await browser.new_page()
            await page.goto(file_url, wait_until="networkidle", timeout=90000)
            pdf_bytes = await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "18mm", "bottom": "18mm",
                        "left": "15mm", "right": "15mm"},
            )
            await browser.close()
            return pdf_bytes
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

async def generate_lender_pack_pdf(
    *,
    project_id: str,
    project_name: str,
    sponsor: str = "Sponsor TBC",
    technology: str = "solar",
    capacity_mw: float = 50.0,
    lat: float | None = None,
    lon: float | None = None,
    region: str = "South",
    dno: str = "TBC",
    poc_voltage_kv: float = 33.0,
    ppa_price: float = 55.0,
    bank_name: str = "Prospective Lender",
    mla_names: list[str] | None = None,
    cod_target: str | None = None,
    has_grid_offer: bool = False,
    has_planning_consent: bool = False,
    has_ppa: bool = True,
    gearing_pct: float = DEFAULT_GEARING,
    interest_rate: float = DEFAULT_INTEREST_RATE,
    debt_term_years: int = DEFAULT_DEBT_TERM_YEARS,
    wacc: float = DEFAULT_WACC,
    margin_bps: int = DEFAULT_MARGIN_BPS,
    target_dscr: float = DEFAULT_TARGET_DSCR,
    target_llcr: float = DEFAULT_TARGET_LLCR,
    project_metadata: dict | None = None,
    pool: Any | None = None,
) -> bytes:
    """Full pipeline: assemble → render → PDF. Returns PDF bytes."""
    log.info(
        "generate_lender_pack_pdf: %s (%.1f MW %s) → bank=%s",
        project_name, capacity_mw, technology, bank_name,
    )

    context = await _assemble_context(
        project_id=project_id,
        project_name=project_name,
        sponsor=sponsor,
        technology=technology,
        capacity_mw=capacity_mw,
        lat=lat,
        lon=lon,
        region=region,
        dno=dno,
        poc_voltage_kv=poc_voltage_kv,
        ppa_price=ppa_price,
        bank_name=bank_name,
        mla_names=mla_names,
        cod_target=cod_target,
        has_grid_offer=has_grid_offer,
        has_planning_consent=has_planning_consent,
        has_ppa=has_ppa,
        gearing_pct=gearing_pct,
        interest_rate=interest_rate,
        debt_term_years=debt_term_years,
        wacc=wacc,
        margin_bps=margin_bps,
        target_dscr=target_dscr,
        target_llcr=target_llcr,
        project_metadata=project_metadata,
        pool=pool,
    )

    html = _render_html(context)
    pdf_bytes = await _html_to_pdf(html)
    log.info("Lender pack PDF generated: %d bytes", len(pdf_bytes))
    return pdf_bytes


async def generate_lender_pack_html(
    *,
    project_id: str,
    project_name: str,
    sponsor: str = "Sponsor TBC",
    technology: str = "solar",
    capacity_mw: float = 50.0,
    lat: float | None = None,
    lon: float | None = None,
    region: str = "South",
    dno: str = "TBC",
    poc_voltage_kv: float = 33.0,
    ppa_price: float = 55.0,
    bank_name: str = "Prospective Lender",
    mla_names: list[str] | None = None,
    cod_target: str | None = None,
    has_grid_offer: bool = False,
    has_planning_consent: bool = False,
    has_ppa: bool = True,
    gearing_pct: float = DEFAULT_GEARING,
    interest_rate: float = DEFAULT_INTEREST_RATE,
    debt_term_years: int = DEFAULT_DEBT_TERM_YEARS,
    wacc: float = DEFAULT_WACC,
    margin_bps: int = DEFAULT_MARGIN_BPS,
    target_dscr: float = DEFAULT_TARGET_DSCR,
    target_llcr: float = DEFAULT_TARGET_LLCR,
    project_metadata: dict | None = None,
    pool: Any | None = None,
) -> str:
    """Convenience — return the HTML string only, no PDF render."""
    context = await _assemble_context(
        project_id=project_id,
        project_name=project_name,
        sponsor=sponsor,
        technology=technology,
        capacity_mw=capacity_mw,
        lat=lat,
        lon=lon,
        region=region,
        dno=dno,
        poc_voltage_kv=poc_voltage_kv,
        ppa_price=ppa_price,
        bank_name=bank_name,
        mla_names=mla_names,
        cod_target=cod_target,
        has_grid_offer=has_grid_offer,
        has_planning_consent=has_planning_consent,
        has_ppa=has_ppa,
        gearing_pct=gearing_pct,
        interest_rate=interest_rate,
        debt_term_years=debt_term_years,
        wacc=wacc,
        margin_bps=margin_bps,
        target_dscr=target_dscr,
        target_llcr=target_llcr,
        project_metadata=project_metadata,
        pool=pool,
    )
    return _render_html(context)


# ═══════════════════════════════════════════════════════════════════════════
# Legacy shim — keep finance_extras.py working
# ═══════════════════════════════════════════════════════════════════════════

def render_lender_pack_html(doc: dict, *, issuer: str = "Princeps", bank: str = "Lender") -> str:
    """Back-compat entry point for the legacy 8-section pack.

    The new pack is model-driven and normally invoked via
    generate_lender_pack_pdf(project_id=..., pool=...). This shim exists
    only so that app/routers/finance_extras.py (POST /api/finance/lender-pack)
    keeps rendering without needing a migration in the same bot slot.

    It synchronously builds a minimal, stripped-down HTML from the `doc`
    payload so the HTML response contract is preserved. Callers that want
    the full lender pack should call generate_lender_pack_pdf instead.
    """
    p = doc.get("project", {}) or {}
    kpis = doc.get("kpis", {}) or {}

    # Build a fake context that the full template can still render on.
    # We cannot reasonably run the full async pipeline here (no project_id,
    # no pool), so we emit a compact one-page HTML referring callers to the
    # new endpoint.
    project_name = p.get("name", "Project")
    capacity_mw = float(p.get("capacity_mw") or 0)
    technology = (p.get("workload") or "solar").lower()

    generated_at = datetime.utcnow().strftime("%d %b %Y %H:%M UTC")

    # Inline minimal HTML — explicitly flag that the full pack is produced by
    # /api/reports/lender-pack (endpoint wired by project_actions.py).
    irr = kpis.get("irr_pct", "—")
    dscr = kpis.get("dscr", "—")
    capex = kpis.get("capex_gbp_m", "—")

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Lender pack (legacy shim) — {project_name}</title>
<style>
  @page {{ size: A4; margin: 18mm 15mm; }}
  body {{ font-family: 'DM Sans', -apple-system, sans-serif; color: #1a1a2e;
         font-size: 11px; line-height: 1.55; margin: 0; }}
  h1 {{ color: #D4A018; font-size: 26px;
       border-bottom: 3px solid #D4A018; padding-bottom: 10px; margin: 0 0 6px; }}
  h2 {{ font-size: 14px; margin: 22px 0 6px;
       border-bottom: 1px solid #E8EAED; padding-bottom: 4px; color: #1a1a2e; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 10.5px; margin-top: 6px; }}
  th, td {{ text-align: left; padding: 5px 7px; border-bottom: 1px solid #E8EAED; }}
  th {{ background: #F7F8FA; font-weight: 700; font-size: 9px;
       letter-spacing: 0.04em; text-transform: uppercase; color: #4B5563; }}
  .note {{ background: #FFF8E6; border-left: 4px solid #D4A018;
          padding: 10px 14px; margin-top: 18px; font-size: 10.5px; }}
</style></head><body>
<h1>{project_name}</h1>
<div>Lender Information Pack — legacy one-page summary — issued by {issuer} to {bank}</div>
<h2>Headline metrics</h2>
<table>
  <tr><th>Capacity</th><td>{capacity_mw:.1f} MW {technology.upper()}</td></tr>
  <tr><th>IRR (P50)</th><td>{irr}%</td></tr>
  <tr><th>DSCR (P50)</th><td>{dscr}x</td></tr>
  <tr><th>CAPEX</th><td>£{capex}m</td></tr>
</table>
<div class="note">
  <b>This is a compact legacy view.</b> The full 15-section institutional
  Lender Information Pack (cover + reliance, transaction summary, sources &
  uses, base / downside / breakeven model pack, LMA covenant package,
  MEL, TDDR, CP / CS, precedent transactions, security, model audit,
  signature block) is generated via POST /api/reports/lender-pack with
  project_id. The full pack includes DCFEvaluator (BOT-A) base / downside /
  breakeven cases, LMA-standard covenant thresholds with cure rights and
  PRA SS31/15 MEL framing.
</div>
<div style="margin-top:28px;padding-top:12px;border-top:1px solid #E8EAED;
            font-size:8.5px;color:#9CA3AF;">
  Prepared by {issuer} · Audience: {bank} · Generated {generated_at} ·
  Cite: LMA IGFA 2024 / PRA SS31/15 / RICS Red Book 2025.
</div>
</body></html>"""
