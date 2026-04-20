"""
DCO (Development Consent Order) Pack Orchestrator.

Assembles the Reg 5 document set into a single HTML document and renders
to PDF via Playwright. One entry point per Reg 5 document, plus a master
``build_dco_pack`` that stitches them together behind the master template
at ``templates/report/dco_pack.html``.

The pack is generated whenever:
  - project.capacity_mw ≥ 50 MW (onshore generation NSIP, PA 2008 s.15(2));
  - project.capacity_mw ≥ 100 MW (offshore generation NSIP, s.15(3));
  - project.metadata.dco_tracker = true (s.35 opt-in override);
  - project.metadata.nsip_override = true (caller-asserted NSIP).

Reference:
  - Planning Act 2008 c.29.
  - Infrastructure Planning (Applications: Prescribed Forms and Procedure)
    Regulations 2009 (SI 2009/2264, as amended).
  - Infrastructure Planning (Environmental Impact Assessment) Regulations
    2017 (SI 2017/572).
  - PINS Advice Notes 1-18 (various).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.dco.application_form import build_application_form
from utils.dco.book_of_reference import build_book_of_reference
from utils.dco.consultation_report import build_consultation_report
from utils.dco.draft_order import build_draft_order
from utils.dco.environmental_statement_skeleton import (
    build_environmental_statement_skeleton,
)
from utils.dco.explanatory_memorandum import build_explanatory_memorandum
from utils.dco.funding_statement import build_funding_statement
from utils.dco.land_plans import build_land_plan
from utils.dco.statement_of_reasons import build_statement_of_reasons
from utils.dco.works_plans import build_works_plan

log = logging.getLogger("princeps.dco_pack")

# ─── Optional regulatory registry import (BOT-R2 owned — may not exist yet)
try:
    from app.regulatory import cite as _reg_cite  # type: ignore

    def _regcite(key: str, fallback: str) -> str:
        try:
            return _reg_cite(key) or fallback
        except Exception:
            return fallback
except Exception:  # registry not yet landed
    def _regcite(key: str, fallback: str) -> str:
        return fallback


# ─── NSIP qualification ───────────────────────────────────────────────────

def qualifies_for_dco(project: dict) -> dict:
    """Return a verdict dict indicating whether the project is an NSIP / DCO target."""
    tech = (project.get("workload_type") or project.get("technology") or "").lower()
    cap = project.get("capacity_mw") or 0
    meta = project.get("metadata") or {}

    if meta.get("dco_tracker") or meta.get("nsip_override"):
        return {
            "qualifies": True,
            "route": "DCO (caller override)",
            "reason": "metadata.dco_tracker or metadata.nsip_override flag set on project",
            "capacity_mw": cap,
            "technology": tech,
        }

    if tech in ("solar",) and cap >= 50:
        return {"qualifies": True, "route": "DCO (statutory NSIP)",
                "reason": f"Onshore solar {cap} MW >= 50 MW threshold (PA 2008 s.15(2))",
                "capacity_mw": cap, "technology": tech}
    if tech in ("offshore_wind",) and cap >= 100:
        return {"qualifies": True, "route": "DCO (statutory NSIP)",
                "reason": f"Offshore wind {cap} MW >= 100 MW threshold (PA 2008 s.15(3))",
                "capacity_mw": cap, "technology": tech}
    if tech in ("onshore_wind",) and cap >= 100:
        return {"qualifies": True, "route": "DCO (post-LURA 2023 uplift)",
                "reason": f"Onshore wind {cap} MW >= post-LURA 100 MW threshold",
                "capacity_mw": cap, "technology": tech}
    if tech == "dc":
        return {"qualifies": True, "route": "DCO via s.35 opt-in",
                "reason": "Data centres do not meet a PA 2008 s.14 statutory threshold; DCO available by direction of the Secretary of State under s.35",
                "capacity_mw": cap, "technology": tech}

    return {
        "qualifies": False,
        "route": "TCPA 1990 (Town & Country Planning)",
        "reason": f"{tech or 'unknown'} {cap} MW below NSIP threshold and no s.35 opt-in",
        "capacity_mw": cap,
        "technology": tech,
    }


# ─── Orchestrator ─────────────────────────────────────────────────────────

def build_dco_pack(
    project: dict,
    *,
    applicant: dict | None = None,
    agent: dict | None = None,
    s35_direction: dict | None = None,
    cpo_sought: bool = False,
    deemed_marine_licence: bool = False,
    site_boundary_geojson: dict | None = None,
    parcels_geojson: dict | None = None,
    registered_parcels: list[dict] | None = None,
    unregistered_parcels: list[dict] | None = None,
    revision: str = "P01",
    client: str | None = None,
    enrichment: dict | None = None,
) -> dict:
    """Stitch the Reg 5 document set into a pack bundle (structured dict).

    Each key maps to a prescribed document under Reg 5. The master template
    iterates these keys and renders each section.
    """
    verdict = qualifies_for_dco(project)
    if not verdict["qualifies"]:
        log.warning("build_dco_pack called on non-NSIP project: %s", verdict)

    pack = {
        "pack_title": f"{project.get('name','[Project]')} — DCO Application Pack",
        "pack_subtitle": "Reg 5 document set — Infrastructure Planning (Applications: Prescribed Forms and Procedure) Regulations 2009",
        "pack_reference": f"PRINCEPS-DCO-{(project.get('name') or 'PROJ')[:20].replace(' ','_')}-{revision}",
        "revision": revision,
        "client": client or project.get("name"),
        "prepared_by": "Princeps",
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "verdict": verdict,
        "nsip_threshold_citation": _regcite(
            "pa2008_s15",
            "Planning Act 2008 s.14-s.16 (NSIP types), s.15(2) (onshore gen >=50 MW), s.15(3) (offshore >=100 MW), s.35 (SoS direction, Business or Commercial Projects).",
        ),
        "application_regulations_citation": _regcite(
            "si_2009_2264",
            "Infrastructure Planning (Applications: Prescribed Forms and Procedure) Regulations 2009 (SI 2009/2264), as amended.",
        ),
        "eia_regulations_citation": _regcite(
            "si_2017_572",
            "Infrastructure Planning (Environmental Impact Assessment) Regulations 2017 (SI 2017/572).",
        ),
    }

    # Reg 5 documents — each key corresponds to an SI 2009/2264 reg 5(2) sub-paragraph
    pack["reg5_documents"] = {
        "a_application_form": build_application_form(
            project,
            applicant=applicant,
            agent=agent,
            s35_direction=s35_direction,
            enrichment=enrichment,
        ),
        "b_land_plans": build_land_plan(
            project,
            site_boundary_geojson=site_boundary_geojson,
            parcels_geojson=parcels_geojson,
        ),
        "b_works_plans": build_works_plan(
            project,
            site_boundary_geojson=site_boundary_geojson,
        ),
        "c_draft_order": build_draft_order(
            project,
            cpo_sought=cpo_sought,
            deemed_marine_licence=deemed_marine_licence,
        ),
        "d_explanatory_memorandum": None,  # populated after c_draft_order below
        "e_statement_of_reasons": build_statement_of_reasons(project, cpo_sought=cpo_sought),
        "f_funding_statement": build_funding_statement(project, cpo_sought=cpo_sought),
        "g_environmental_statement_skeleton": build_environmental_statement_skeleton(project),
        "h_consultation_report": build_consultation_report(project),
        "i_book_of_reference": build_book_of_reference(
            project,
            registered_parcels=registered_parcels,
            unregistered_parcels=unregistered_parcels,
            cpo_sought=cpo_sought,
            enrichment=enrichment,
        ),
    }
    # EM depends on draft order structure
    pack["reg5_documents"]["d_explanatory_memorandum"] = build_explanatory_memorandum(
        project, pack["reg5_documents"]["c_draft_order"],
    )

    # Document index for Form 1 / pack contents
    pack["document_index"] = _document_index(pack)

    return pack


def _document_index(pack: dict) -> list[dict]:
    """Render the master contents / Reg 5 document index as a table."""
    docs = pack["reg5_documents"]
    return [
        {"n": 1, "reg": "Reg 5(2)(a)", "doc": "Application Form (Form 1)", "status": _status(docs.get("a_application_form"))},
        {"n": 2, "reg": "Reg 5(2)(b)", "doc": "Land Plans", "status": _status(docs.get("b_land_plans"))},
        {"n": 3, "reg": "Reg 5(2)(b)", "doc": "Works Plans", "status": _status(docs.get("b_works_plans"))},
        {"n": 4, "reg": "Reg 5(2)(c)", "doc": "Draft Development Consent Order", "status": _status(docs.get("c_draft_order"))},
        {"n": 5, "reg": "Reg 5(2)(d)", "doc": "Explanatory Memorandum", "status": _status(docs.get("d_explanatory_memorandum"))},
        {"n": 6, "reg": "Reg 5(2)(e)", "doc": "Statement of Reasons", "status": _status(docs.get("e_statement_of_reasons"))},
        {"n": 7, "reg": "Reg 5(2)(f)", "doc": "Funding Statement", "status": _status(docs.get("f_funding_statement"))},
        {"n": 8, "reg": "Reg 5(2)(g)", "doc": "Environmental Statement (skeleton)", "status": "SKELETON"},
        {"n": 9, "reg": "Reg 5(2)(h)", "doc": "Consultation Report", "status": _status(docs.get("h_consultation_report"))},
        {"n": 10, "reg": "Reg 5(2)(i)", "doc": "Book of Reference", "status": _status(docs.get("i_book_of_reference"))},
    ]


def _status(doc: dict | None) -> str:
    if not doc:
        return "MISSING"
    return "PRESENT"


# ─── Rendering ────────────────────────────────────────────────────────────

def render_dco_pack_html(pack: dict) -> str:
    """Render the pack bundle to HTML via the master Jinja2 template."""
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except Exception:
        raise RuntimeError("Jinja2 not installed — cannot render DCO pack HTML")

    # Use the project `templates/` root so `{% include "report/_partials/..." %}` resolves.
    templates_dir = Path(__file__).resolve().parent.parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    # Custom filter — renders newlines as <br>
    env.filters["nl2br"] = lambda s: (s or "").replace("\n", "<br>")
    template = env.get_template("report/dco_pack.html")
    return template.render(pack=pack)


async def render_dco_pack_pdf(pack: dict) -> bytes:
    """Render the pack bundle to PDF via Playwright."""
    html = render_dco_pack_html(pack)
    from utils.report_grid_connection import html_to_pdf  # reuse existing helper
    return await html_to_pdf(html)
