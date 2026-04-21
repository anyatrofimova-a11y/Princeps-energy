"""Pipeline: assemble → render → Playwright PDF for the IC memo pack."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

# Reuse the grid-connection Playwright bridge.
from utils.report_grid_connection import html_to_pdf

from .sections import (
    build_recommendation_box,
    build_exec_summary,
    build_project_detail,
    build_financial_case,
    build_risk_matrix,
    build_ask_vote,
    build_precedents_section,
)

log = logging.getLogger("princeps.ic_memo_pack")

_TEMPLATES_ROOT = Path(__file__).resolve().parent.parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_ROOT)),
    autoescape=True,
)

MODEL_VERSION = "ICMemoPack v1.0 (2026-04-19)"


def _doc_hash(proj: dict) -> str:
    key = f"{proj.get('project_id','')}{proj.get('name','')}{datetime.utcnow().isoformat()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10].upper()


def _default_verdict(fin: dict, grid: dict, plan: dict) -> str:
    """Derive a verdict from the headline metrics if caller doesn't pass one."""
    irr = fin.get("p50_irr") or fin.get("equity_irr_pct") or 0
    planning_p = plan.get("planning_p") or plan.get("probability_approved_pct") or 0
    headroom = grid.get("headroom_mw") or 0
    if irr >= 12 and planning_p >= 70 and headroom > 0:
        return "GO"
    if irr <= 8 or planning_p < 40:
        return "NO-GO"
    return "CAUTION"


def _references() -> list[dict[str, Any]]:
    return [
        {"n": 1, "title": "IC memo standard 2026 (Princeps internal spec)",
         "publisher": "Princeps / Research-2", "year": 2026, "url": None},
        {"n": 2, "title": "Ofgem TMO4+ decision (15 April 2025, OFG1164)",
         "publisher": "Ofgem", "year": 2025,
         "url": "https://www.ofgem.gov.uk/sites/default/files/2025-04/Summary-Decision-Document-TMO4-package.pdf"},
        {"n": 3, "title": "Ofgem Gate 2 Criteria Methodology Final Decision",
         "publisher": "Ofgem", "year": 2025,
         "url": "https://www.ofgem.gov.uk/sites/default/files/2025-04/Gate-2-Criteria-Methodology-Final-Decision.pdf"},
        {"n": 4, "title": "PRA SS31/15 Internal ratings based approaches",
         "publisher": "PRA / Bank of England", "year": 2020, "url": None},
        {"n": 5, "title": "LMA Investment Grade Facility Agreement (2024 update)",
         "publisher": "Loan Market Association", "year": 2024, "url": None},
        {"n": 6, "title": "Cornwall Insight UK Power Market Forecast Q1 2026",
         "publisher": "Cornwall Insight", "year": 2026,
         "url": "https://www.cornwall-insight.com/"},
        {"n": 7, "title": "NESO Future Energy Scenarios 2024",
         "publisher": "National Energy System Operator", "year": 2024,
         "url": "https://www.neso.energy/future-energy/future-energy-scenarios"},
        {"n": 8, "title": "National Policy Statements EN-1 / EN-3 (2025)",
         "publisher": "UK Government", "year": 2026,
         "url": "https://www.gov.uk/government/publications/national-policy-statement-for-renewable-energy-infrastructure-en-3-2025"},
        {"n": 9, "title": "Planning & Infrastructure Act 2025",
         "publisher": "UK Parliament", "year": 2025,
         "url": "https://bills.parliament.uk/bills/3946"},
        {"n": 10, "title": "Environment Act 2021 (BNG 10% net gain)",
         "publisher": "UK Government", "year": 2021, "url": None},
        {"n": 11, "title": "DEFRA Biodiversity Metric 4.0",
         "publisher": "DEFRA / Natural England", "year": 2023, "url": None},
        {"n": 12, "title": "RICS Red Book Global Standards 2025",
         "publisher": "RICS", "year": 2025,
         "url": "https://www.rics.org/content/dam/ricsglobal/documents/standards/Red-Book-Global-Standards-incorporating-IVS.pdf"},
    ]


def assemble_ic_memo_context(
    *,
    proj: dict[str, Any],
    fin: dict[str, Any],
    grid: dict[str, Any],
    plan: dict[str, Any],
    counterparties: dict[str, Any] | None = None,
    risks: list[dict[str, Any]] | None = None,
    ticket_gbp_m: float = 12.0,
    hold_years: int = 7,
    verdict: str | None = None,
    market_context: dict[str, Any] | None = None,
    # Engine inputs (optional — triggers combined-downside engine)
    base_capex: float | None = None,
    base_revenue: list[float] | None = None,
    base_opex: list[float] | None = None,
    wacc: float | None = None,
    gearing_pct: float = 0.70,
    interest_rate: float = 0.06,
    debt_term_years: int = 18,
    live_precedents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the full Jinja context dict."""
    verdict = verdict or _default_verdict(fin, grid, plan)

    risk_section = build_risk_matrix(risks=risks)
    recommendation = build_recommendation_box(
        proj=proj,
        fin=fin,
        verdict=verdict,
        ticket_gbp_m=ticket_gbp_m,
        hold_years=hold_years,
        risks=risk_section["rows"],
    )
    exec_summary = build_exec_summary(
        proj=proj,
        fin=fin,
        grid=grid,
        plan=plan,
        market_context=market_context,
        ticket_gbp_m=ticket_gbp_m,
        hold_years=hold_years,
    )
    project_detail = build_project_detail(
        proj=proj,
        fin=fin,
        grid=grid,
        plan=plan,
        counterparties=counterparties,
    )
    financial_case = build_financial_case(
        fin=fin,
        base_capex=base_capex,
        base_revenue=base_revenue,
        base_opex=base_opex,
        wacc=wacc,
        gearing_pct=gearing_pct,
        interest_rate=interest_rate,
        debt_term_years=debt_term_years,
    )
    ask_vote = build_ask_vote(
        ticket_gbp_m=ticket_gbp_m,
        hold_years=hold_years,
        target_irr_pct=(fin.get("p50_irr") or 11.0),
        target_moic=(fin.get("moic") or fin.get("equity_multiple") or 1.80),
    )
    # Tech mapping: DC benchmarks against solar + BESS co-located comps
    _raw_tech = (proj.get("workload") or proj.get("technology") or "solar").lower()
    _comp_tech = {"dc": "solar", "datacentre": "solar", "data_centre": "solar"}.get(_raw_tech, _raw_tech)
    precedents = build_precedents_section(
        tech=_comp_tech,
        capacity_mw=proj.get("capacity_mw"),
        live_rows=live_precedents,
    )

    return {
        # Shared-base contract (templates/_shared/_base.html.j2)
        "report_type": "Investment Committee Memorandum (Pack)",
        "project_title": proj.get("name", "Untitled Project"),
        "tagline": "Equity IC decision pack — 6-section standard",
        "revision": "P01",
        "revision_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "recipient": proj.get("addressee")
                     or "Investment Committee, Princeps Infrastructure Fund I",
        "reliance_type": "investor",
        "client_ref": proj.get("client_ref"),
        "doc_ref": (proj.get("project_id") or "PPS") + "-ICP",
        "project_ref": proj.get("project_id"),
        "doc_hash": _doc_hash(proj),
        "references": _references(),
        "model_version": MODEL_VERSION,

        # Raw context for introspection
        "proj": proj,
        "fin": fin,
        "grid_ctx": grid,
        "plan_ctx": plan,

        # Six sections + precedents
        "sections": {
            "s01_recommendation": recommendation,
            "s02_exec_summary": exec_summary,
            "s03_project_detail": project_detail,
            "s04_financial_case": financial_case,
            "s05_risk_matrix": risk_section,
            "s06_ask_vote": ask_vote,
            "s_precedents": precedents,
        },
        "verdict_variant": recommendation["verdict_variant"],
    }


async def generate_ic_memo_pack_pdf(
    *,
    proj: dict[str, Any],
    fin: dict[str, Any],
    grid: dict[str, Any],
    plan: dict[str, Any],
    counterparties: dict[str, Any] | None = None,
    risks: list[dict[str, Any]] | None = None,
    ticket_gbp_m: float = 12.0,
    hold_years: int = 7,
    verdict: str | None = None,
    market_context: dict[str, Any] | None = None,
    base_capex: float | None = None,
    base_revenue: list[float] | None = None,
    base_opex: list[float] | None = None,
    wacc: float | None = None,
    gearing_pct: float = 0.70,
    interest_rate: float = 0.06,
    debt_term_years: int = 18,
    live_precedents: list[dict[str, Any]] | None = None,
) -> bytes:
    """Assemble → render → PDF."""
    ctx = assemble_ic_memo_context(
        proj=proj, fin=fin, grid=grid, plan=plan,
        counterparties=counterparties, risks=risks,
        ticket_gbp_m=ticket_gbp_m, hold_years=hold_years,
        verdict=verdict, market_context=market_context,
        base_capex=base_capex, base_revenue=base_revenue, base_opex=base_opex,
        wacc=wacc, gearing_pct=gearing_pct, interest_rate=interest_rate,
        debt_term_years=debt_term_years,
        live_precedents=live_precedents,
    )
    template = _env.get_template("ic_memo/pack.html.j2")
    html = template.render(**ctx)
    log.info("ic_memo_pack: rendered HTML (%d chars) for %s",
             len(html), proj.get("name"))
    return await html_to_pdf(html)
