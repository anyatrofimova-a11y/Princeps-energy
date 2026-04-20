"""
DCO Application Form — Reg 5(2)(a) & Regulation 6 content.

The Infrastructure Planning (Applications: Prescribed Forms and Procedure)
Regulations 2009 (SI 2009/2264), as amended, prescribe the application form
under Reg 5(2)(a) read with Reg 6 / Schedule 2 ("Form 1"). The form must
include the applicant name, site description, a description of the
development, the s.35 direction reference (if opted-in), the draft order
title, and a list of accompanying documents.

This module produces a structured dict rendered by templates/report/dco_pack.html.
Every section lives under a numbered Form 1 heading so a PINS reviewer can
tick the checklist.

Citation: "In fulfilment of Reg 5(2)(a) read with Reg 6 and Schedule 2 of the
Infrastructure Planning (Applications: Prescribed Forms and Procedure)
Regulations 2009 (SI 2009/2264, as amended)."
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def build_application_form(
    project: dict,
    *,
    applicant: dict | None = None,
    agent: dict | None = None,
    s35_direction: dict | None = None,
    draft_order_title: str | None = None,
    enrichment: dict | None = None,
) -> dict:
    """Return a Form 1 dict per SI 2009/2264 Schedule 2.

    Parameters
    ----------
    project: dict
        ``_load_project_summary`` shape (name, lat, lon, capacity_mw, workload_type, area_m2).
    applicant: dict | None
        Optional {name, company_number, registered_office, contact, email, phone}.
    agent: dict | None
        Optional {name, firm, address, email, phone, planning_portal_agent_id}.
    s35_direction: dict | None
        Optional {reference, decision_date, direction_text} for DCs opting-in under s.35 PA 2008.
    draft_order_title: str | None
        The title of the draft order as it appears on the order itself.
    enrichment: dict | None
        Optional :func:`utils.site_enrichment.enrich_site` output. When set,
        its values populate section 4 (Site Location) so the Form 1 does not
        ship with ``[LPA — TO POPULATE]`` / ``[Postcode — TO POPULATE]``
        placeholder strings.
    """
    if enrichment:
        _merge_enrichment_into_project(project, enrichment)

    proj_name = project.get("name") or "[Project name — TO POPULATE]"
    cap = project.get("capacity_mw")
    tech = (project.get("workload_type") or project.get("technology") or "solar").lower()
    lat = project.get("lat")
    lon = project.get("lon")
    area_m2 = project.get("area_m2")
    area_ha = round(area_m2 / 10_000, 2) if area_m2 else None

    # NSIP threshold evaluation (PA 2008 s.14-s.16, s.30-s.35)
    threshold_test = _evaluate_nsip_threshold(tech, cap)

    applicant = applicant or {}
    agent = agent or {}

    form = {
        "form_title": "Form 1 — Application for an Order granting Development Consent",
        "regulation_citation": (
            "In fulfilment of Regulation 5(2)(a) read with Regulation 6 and "
            "Schedule 2 of the Infrastructure Planning (Applications: "
            "Prescribed Forms and Procedure) Regulations 2009 (SI 2009/2264, "
            "as amended by SI 2012/635, SI 2018/378, SI 2024/276)."
        ),
        "primary_act": "Planning Act 2008 c.29 (as amended by the Localism Act 2011 and Levelling-up and Regeneration Act 2023)",
        "sections": [
            {
                "n": "1",
                "heading": "Applicant details",
                "fields": [
                    _field("Applicant name", applicant.get("name")),
                    _field("Company number (Companies House)", applicant.get("company_number")),
                    _field("Registered office", applicant.get("registered_office")),
                    _field("Principal contact", applicant.get("contact")),
                    _field("Email", applicant.get("email")),
                    _field("Telephone", applicant.get("phone")),
                ],
            },
            {
                "n": "2",
                "heading": "Agent details (if appointed)",
                "fields": [
                    _field("Agent name", agent.get("name")),
                    _field("Firm", agent.get("firm")),
                    _field("Address", agent.get("address")),
                    _field("Email", agent.get("email")),
                    _field("Telephone", agent.get("phone")),
                    _field("Planning Portal agent ID", agent.get("planning_portal_agent_id")),
                ],
            },
            {
                "n": "3",
                "heading": "The proposed development",
                "fields": [
                    _field("Proposed development name", proj_name),
                    _field("Proposed nameplate capacity (MW)", cap),
                    _field("Primary technology", tech),
                    _field("Site area (ha)", area_ha),
                    _field(
                        "Short description",
                        _short_description(proj_name, tech, cap, area_ha),
                    ),
                ],
            },
            {
                "n": "4",
                "heading": "Site location",
                "fields": [
                    _field("Centroid latitude (WGS84)", lat),
                    _field("Centroid longitude (WGS84)", lon),
                    _field("Local Planning Authority area", project.get("lpa") or "[LPA — TO POPULATE]"),
                    _field("County / Unitary authority", project.get("county") or "[County — TO POPULATE]"),
                    _field("Grid reference (OSGB36)", project.get("osgb_reference") or "[OSGB36 — TO POPULATE via pyproj]"),
                    _field("Postcode", project.get("postcode") or "[Postcode — TO POPULATE]"),
                    _field("Parish", project.get("parish") or "[Parish — TO POPULATE]"),
                    _field("Ward", project.get("ward") or "[Ward — TO POPULATE]"),
                ],
            },
            {
                "n": "5",
                "heading": "Nationally Significant Infrastructure Project status",
                "fields": [
                    _field("NSIP threshold route", threshold_test["route"]),
                    _field("Statutory threshold test", threshold_test["test"]),
                    _field("NSIP type (PA 2008 s.14)", threshold_test["s14_type"]),
                    _field(
                        "S.35 direction (Business or Commercial Projects)",
                        (s35_direction or {}).get("reference")
                        or ("N/A — meets statutory threshold" if threshold_test["meets_threshold"] else "[s.35 direction — TO POPULATE]"),
                    ),
                    _field("S.35 decision date", (s35_direction or {}).get("decision_date")),
                ],
            },
            {
                "n": "6",
                "heading": "Order sought",
                "fields": [
                    _field(
                        "Draft order title",
                        draft_order_title or f"The {proj_name} Development Consent Order 20xx",
                    ),
                    _field(
                        "Order type",
                        "Development Consent Order under s.114 Planning Act 2008",
                    ),
                    _field(
                        "Compulsory acquisition sought",
                        "[Yes / No — TO POPULATE. If Yes, see Book of Reference and Statement of Reasons for CA.]",
                    ),
                    _field(
                        "Deemed Marine Licence sought",
                        "[Yes / No — TO POPULATE (required only for works below MHWS)]",
                    ),
                ],
            },
            {
                "n": "7",
                "heading": "Environmental Impact Assessment",
                "fields": [
                    _field(
                        "EIA status (per Infrastructure Planning (EIA) Regulations 2017 SI 2017/572)",
                        "EIA development — Environmental Statement submitted per Reg 5(2)(g)",
                    ),
                    _field("Scoping Opinion request date", "[TO POPULATE]"),
                    _field("Scoping Opinion receipt date", "[TO POPULATE]"),
                    _field("PEIR publication date", "[TO POPULATE]"),
                ],
            },
            {
                "n": "8",
                "heading": "Pre-application consultation",
                "fields": [
                    _field("s.42 consultees notified", "[TO POPULATE — see Consultation Report]"),
                    _field("s.47 SoCC (Statement of Community Consultation) publication date", "[TO POPULATE]"),
                    _field("s.47 SoCC consultation period", "[TO POPULATE, minimum 28 days]"),
                    _field("s.48 publicity publication", "[TO POPULATE — 2 local papers + London Gazette]"),
                ],
            },
            {
                "n": "9",
                "heading": "Accompanying documents (Reg 5(2))",
                "fields": [],
                "document_index": _reg5_document_index(),
            },
            {
                "n": "10",
                "heading": "Application fee",
                "fields": [
                    _field(
                        "Acceptance fee (Infrastructure Planning (Fees) Regulations 2010 SI 2010/106)",
                        "£9,344 (2024-25 banded, generation >1 GW £44,444) — [confirm band]",
                    ),
                    _field("Payment reference", "[TO POPULATE]"),
                ],
            },
            {
                "n": "11",
                "heading": "Declaration",
                "fields": [
                    _field("Signed (authorised signatory)", "[Signature block — TO POPULATE at submission]"),
                    _field("Name", "[TO POPULATE]"),
                    _field("Position", "[Director / Company Secretary — TO POPULATE]"),
                    _field("Date", "[TO POPULATE]"),
                ],
            },
        ],
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return form


def _field(label: str, value: Any) -> dict:
    """Wrap a field value; mark empty as TO-POPULATE for the HTML renderer."""
    if value is None or value == "" or (isinstance(value, str) and value.startswith("[")):
        return {"label": label, "value": value or "[TO POPULATE]", "status": "pending"}
    return {"label": label, "value": value, "status": "filled"}


def _short_description(name: str, tech: str, cap_mw: float | None, area_ha: float | None) -> str:
    cap_txt = f"{cap_mw:.0f} MW" if isinstance(cap_mw, (int, float)) else "[capacity — TO POPULATE]"
    area_txt = f" on {area_ha:.1f} ha" if area_ha else ""
    if tech == "solar":
        return (
            f"Construction and operation of a {cap_txt} solar photovoltaic generating "
            f"station{area_txt}, with associated battery energy storage system, "
            f"connection infrastructure, inverter/transformer stations, internal "
            f"access tracks, landscaping, and ecological enhancement works. "
            f"({name})"
        )
    if tech == "bess":
        return (
            f"Construction and operation of a {cap_txt} battery energy storage "
            f"system{area_txt} including containerised lithium-ion battery units, "
            f"power conversion system, transformer and substation compound, and "
            f"connection infrastructure. ({name})"
        )
    if tech == "dc":
        return (
            f"Construction and operation of a {cap_txt} data centre campus{area_txt} "
            f"including data halls, cooling plant, emergency generators, fuel storage, "
            f"on-site substation, fibre connection and associated works. ({name})"
        )
    return (
        f"Construction and operation of a {cap_txt} {tech} development{area_txt}. ({name})"
    )


def _evaluate_nsip_threshold(tech: str, cap_mw: float | None) -> dict:
    """PA 2008 s.14-s.16, s.30-s.35 thresholds."""
    cap = cap_mw or 0
    if tech == "solar":
        meets = cap >= 50
        return {
            "route": "DCO (NSIP)" if meets else "DCO via s.35 opt-in (Business or Commercial Projects)",
            "test": f"Installed generating capacity {cap:.0f} MW vs 50 MW threshold (onshore, PA 2008 s.15(2))",
            "meets_threshold": meets,
            "s14_type": "s.14(1)(a) — Construction of a generating station (onshore)",
        }
    if tech == "onshore_wind":
        meets = cap >= 100  # threshold post-LURA 2023 uplift (expected)
        return {
            "route": "DCO" if meets else "TCPA 1990 (not NSIP)",
            "test": f"Installed generating capacity {cap:.0f} MW vs post-LURA 2023 uplift threshold",
            "meets_threshold": meets,
            "s14_type": "s.14(1)(a) — Construction of a generating station (onshore)",
        }
    if tech == "offshore_wind":
        meets = cap >= 100
        return {
            "route": "DCO" if meets else "Marine Licence only",
            "test": f"Installed generating capacity {cap:.0f} MW vs 100 MW threshold (PA 2008 s.15(3))",
            "meets_threshold": meets,
            "s14_type": "s.14(1)(a) — Construction of a generating station (offshore)",
        }
    if tech == "bess":
        # BESS not a generating station per ss.15; DCO only via s.35
        return {
            "route": "DCO via s.35 opt-in (Business or Commercial Projects)",
            "test": "BESS is not a 'generating station' under PA 2008 s.15 — DCO consent only if Secretary of State issues a direction under s.35.",
            "meets_threshold": False,
            "s14_type": "N/A — not a PA 2008 s.14 NSIP type",
        }
    if tech == "dc":
        return {
            "route": "DCO via s.35 opt-in (Business or Commercial Projects)",
            "test": (
                "Data centres are not listed in PA 2008 s.14. Opt-in to DCO "
                "available under s.35 where SoS directs that a project is of "
                "national significance, per the Infrastructure Planning "
                "(Business or Commercial Projects) (Amendment) Regulations 2026."
            ),
            "meets_threshold": False,
            "s14_type": "s.35A — Business or Commercial Projects opt-in",
        }
    return {
        "route": "[Route — TO POPULATE]",
        "test": "[Threshold test — TO POPULATE]",
        "meets_threshold": False,
        "s14_type": "[PA 2008 s.14 type — TO POPULATE]",
    }


def _merge_enrichment_into_project(project: dict, enrichment: dict) -> None:
    """Populate ``project`` with values from
    :func:`utils.site_enrichment.enrich_site` output, skipping existing
    non-empty values.
    """
    def _pick(field: str) -> Any:
        rec = enrichment.get(field)
        if isinstance(rec, dict):
            return rec.get("value")
        return rec

    def _set(key: str, value: Any) -> None:
        if value in (None, "", []):
            return
        if not project.get(key):
            project[key] = value

    _set("postcode", _pick("postcode"))
    _set("lpa", _pick("local_planning_authority"))
    # For DCO Form 1 the "County / Unitary authority" row often echoes the
    # LPA for unitary / London borough areas. Use as a best-effort fallback
    # so the pack doesn't render "[County — TO POPULATE]" unnecessarily.
    _set("county", _pick("local_planning_authority"))
    _set("osgb_reference", _pick("osgb_grid_ref"))
    _set("parish", _pick("parish"))
    _set("ward", _pick("ward"))
    title_val = _pick("land_registry_title")
    if isinstance(title_val, dict):
        tn = title_val.get("title_number") or title_val.get("inspire_id")
        if tn:
            _set("title_number", tn)


def _reg5_document_index() -> list[dict]:
    """The prescribed Reg 5(2) document set — appears in s.9 of Form 1."""
    return [
        {"ref": "Reg 5(2)(a)", "doc": "Application form (this document)", "required": True},
        {"ref": "Reg 5(2)(b)", "doc": "Plans (Land / Works / Access & ROW / General Arrangement)", "required": True},
        {"ref": "Reg 5(2)(c)", "doc": "Copy of draft Development Consent Order", "required": True},
        {"ref": "Reg 5(2)(d)", "doc": "Explanatory Memorandum (explaining each article of the draft DCO)", "required": True},
        {"ref": "Reg 5(2)(e)", "doc": "Statement of Reasons", "required": True},
        {"ref": "Reg 5(2)(f)", "doc": "Funding Statement", "required": True},
        {"ref": "Reg 5(2)(g)", "doc": "Environmental Statement (EIA development)", "required": True},
        {"ref": "Reg 5(2)(h)", "doc": "Consultation Report (s.42 / s.47 / s.48)", "required": True},
        {"ref": "Reg 5(2)(i)", "doc": "Book of Reference (Categories 1, 2, 3)", "required": True},
        {"ref": "Reg 5(2)(j)", "doc": "Habitats Regulations Assessment (where HRA triggered)", "required": False},
        {"ref": "Reg 5(2)(k)", "doc": "Flood Risk Assessment (EA standing advice)", "required": False},
        {"ref": "Reg 5(2)(l)", "doc": "Design and Access Statement", "required": False},
        {"ref": "Reg 5(2)(m)", "doc": "Any Statement of Fact relating to use of land (s.59 PA 2008)", "required": False},
    ]
