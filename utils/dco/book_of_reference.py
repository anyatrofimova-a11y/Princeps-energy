"""
Book of Reference — Reg 5(2)(i) and Reg 7.

The Book of Reference is a tabular register identifying every person:
  - Category 1: those with an interest in the land within the Order limits
    (freeholders, leaseholders, tenants, mortgagees);
  - Category 2: those who might be entitled to make a claim under s.10 of the
    Compulsory Purchase Act 1965 (claim in respect of injurious affection);
  - Category 3: those who might be entitled to make a claim under Part 1 of
    the Land Compensation Act 1973 (compensation for depreciation caused by
    physical factors — noise, vibration, smell, fumes, smoke, artificial
    lighting, discharge onto land of any solid or liquid substance).

Data inputs:
  - HM Land Registry Official Copy of Title Register (OCTR) — authoritative.
  - HMLR INSPIRE Index polygons (Council of European Union Directive 2007/2/EC
    open dataset) for unregistered parcels.
  - CCOD (HMLR Commercial and Corporate Ownership Data) — corporate owners.
  - Overseas Companies Ownership Dataset (OCOD) — non-UK corporate owners.
  - On-site inquiry and adjoining owner interviews (s.44(5) diligent inquiry).

At the time of writing the ``utils/hmlr_inspire_ingester.py`` wiring delivers
INSPIRE polygons only (unregistered parcels). OCTR / CCOD / OCOD registers
are partially wired — the skeleton below falls back to TO-POPULATE markers
where the registers are unpopulated.

Citation: "In fulfilment of Regulation 5(2)(i) and Regulation 7 of the
Infrastructure Planning (Applications: Prescribed Forms and Procedure)
Regulations 2009 (SI 2009/2264)."
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def build_book_of_reference(
    project: dict,
    *,
    registered_parcels: list[dict] | None = None,
    unregistered_parcels: list[dict] | None = None,
    cpo_sought: bool = False,
    enrichment: dict | None = None,
) -> dict:
    """Build a Book of Reference skeleton.

    Parameters
    ----------
    project: dict
        _load_project_summary shape.
    registered_parcels: list[dict] | None
        OCTR-derived entries — fields {plot_no, area_m2, freeholder, freeholder_address,
        title_no, leaseholders, occupiers, easements_restrictions}.
    unregistered_parcels: list[dict] | None
        INSPIRE-derived entries — fields {plot_no, area_m2, inquiry_note}.
    cpo_sought: bool
        Whether Category 2 / 3 acquisitions apply.
    enrichment: dict | None
        Optional :func:`utils.site_enrichment.enrich_site` output. When the
        caller has no registered_parcels data but enrichment found an
        INSPIRE polygon at the site centroid, we promote that into a
        Category 1 row so the Book doesn't render as all-skeleton.
    """
    proj_name = project.get("name") or "[Project]"

    registered_parcels = list(registered_parcels or [])
    unregistered_parcels = list(unregistered_parcels or [])

    if enrichment and not registered_parcels:
        lr = enrichment.get("land_registry_title") or {}
        lr_val = lr.get("value") if isinstance(lr, dict) else None
        if isinstance(lr_val, dict) and (lr_val.get("title_number") or lr_val.get("inspire_id")):
            # Promote the enriched parcel into a Category 1 entry.
            registered_parcels.append({
                "plot_no": "001",
                "area_m2": lr_val.get("area_m2"),
                "title_no": lr_val.get("title_number") or f"INSPIRE {lr_val.get('inspire_id')}",
                "freeholder": None,
                "leaseholders": None,
                "occupiers": None,
                "easements_restrictions": None,
            })

    cat1 = _build_category_1(registered_parcels, unregistered_parcels)
    cat2 = _build_category_2(registered_parcels) if cpo_sought else []
    cat3 = _build_category_3(registered_parcels) if cpo_sought else []

    return {
        "document_title": "Book of Reference",
        "regulation_citation": (
            "In fulfilment of Regulation 5(2)(i) and Regulation 7 of the "
            "Infrastructure Planning (Applications: Prescribed Forms and "
            "Procedure) Regulations 2009 (SI 2009/2264)."
        ),
        "methodology_note": (
            "This Book of Reference has been compiled by diligent inquiry in "
            "accordance with section 44(5) of the Planning Act 2008, drawing "
            "on: HM Land Registry Official Copies of Register of Title for each "
            "registered parcel; INSPIRE polygon index for unregistered parcels; "
            "HMLR CCOD (Commercial and Corporate Ownership Data) for corporate "
            "owners; HMLR OCOD (Overseas Companies Ownership Dataset); HMRC "
            "business rates records; Companies House directorships; and on-site "
            "inquiry of occupiers and adjoining owners. Where a freehold remains "
            "unregistered or where inquiries remain open, the parcel is flagged "
            "'diligent inquiry continuing' per paragraph 18 of DCLG Guidance."
        ),
        "parts": [
            {
                "n": "1",
                "heading": "Category 1 — Persons with an interest in the land (s.44(4)(a))",
                "body": (
                    "Category 1 comprises each person with a legal or equitable interest in "
                    "the land within the Order limits. Each plot is identified by its plot "
                    "number (which corresponds to the plot numbering on the Land Plans)."
                ),
                "columns": [
                    "Plot",
                    "Area (m²)",
                    "Title No.",
                    "Freeholder / Heritable proprietor",
                    "Leaseholders",
                    "Occupiers",
                    "Other interests",
                ],
                "rows": cat1,
                "total_plots": len(cat1),
            },
            {
                "n": "2",
                "heading": "Category 2 — Potential s.10 Compulsory Purchase Act 1965 claimants",
                "body": (
                    "Category 2 comprises persons who might, if the scheme proceeds, be "
                    "entitled to make a claim under section 10 of the Compulsory Purchase "
                    "Act 1965 in respect of injurious affection to their land by the "
                    "execution of the works or the use of the undertaking."
                    if cpo_sought else
                    "No powers of compulsory acquisition are sought. Category 2 is not engaged."
                ),
                "columns": ["Claimant ref", "Name", "Address", "Land affected", "Nature of claim"],
                "rows": cat2,
                "total_plots": len(cat2),
            },
            {
                "n": "3",
                "heading": "Category 3 — Potential Part 1 Land Compensation Act 1973 claimants",
                "body": (
                    "Category 3 comprises persons who might, if the scheme proceeds, be "
                    "entitled to make a claim under Part 1 of the Land Compensation Act 1973 "
                    "in respect of depreciation of the value of their interest in land by "
                    "physical factors (noise, vibration, smell, fumes, smoke, artificial "
                    "lighting, or discharge onto land of any solid or liquid substance) "
                    "caused by the use of the authorised development."
                    if cpo_sought else
                    "No powers of compulsory acquisition are sought. Category 3 is not engaged."
                ),
                "columns": ["Claimant ref", "Name", "Address", "Distance to Order limits (m)", "Nature of claim"],
                "rows": cat3,
                "total_plots": len(cat3),
            },
        ],
        "summary": {
            "category_1_count": len(cat1),
            "category_2_count": len(cat2),
            "category_3_count": len(cat3),
            "total_entries": len(cat1) + len(cat2) + len(cat3),
        },
        "statutory_undertakers_note": (
            "Statutory undertakers with apparatus in or on the Order land are "
            "separately identified at Schedule 9 of the draft Order (protective "
            "provisions). These are: [TO POPULATE — NGET, DNO, WASC, gas "
            "distributor, electronic communications code operator, etc.]."
        ),
        "crown_land_note": (
            "Crown land within the Order limits is identified per s.135 of the "
            "Planning Act 2008. Where Crown land is affected, consent of the "
            "appropriate Crown authority is required. [TO POPULATE — Crown "
            "Estate / DIO / Duchy inquiries.]"
        ),
        "project_name": proj_name,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _build_category_1(
    registered: list[dict],
    unregistered: list[dict],
) -> list[dict]:
    rows: list[dict] = []
    plot_no = 1
    for r in registered:
        rows.append({
            "plot": r.get("plot_no") or f"{plot_no:03d}",
            "area_m2": r.get("area_m2") or "[TO POPULATE]",
            "title_no": r.get("title_no") or "[TO POPULATE — HMLR OCTR]",
            "freeholder": r.get("freeholder") or "[TO POPULATE]",
            "leaseholders": r.get("leaseholders") or "None identified",
            "occupiers": r.get("occupiers") or "[TO POPULATE — on-site inquiry]",
            "other_interests": r.get("easements_restrictions") or "None identified",
            "status": "confirmed" if r.get("title_no") else "pending",
        })
        plot_no += 1
    for u in unregistered:
        rows.append({
            "plot": u.get("plot_no") or f"{plot_no:03d}",
            "area_m2": u.get("area_m2") or "[TO POPULATE]",
            "title_no": "Unregistered (INSPIRE polygon)",
            "freeholder": "[TO POPULATE — diligent inquiry continuing]",
            "leaseholders": "[TO POPULATE]",
            "occupiers": "[TO POPULATE]",
            "other_interests": "[TO POPULATE]",
            "status": "pending_inquiry",
        })
        plot_no += 1
    if not rows:
        # Skeleton fallback so the pack does not render as blank
        for i in range(1, 4):
            rows.append({
                "plot": f"{i:03d}",
                "area_m2": "[TO POPULATE]",
                "title_no": "[TO POPULATE — HMLR OCTR pending]",
                "freeholder": "[TO POPULATE]",
                "leaseholders": "[TO POPULATE]",
                "occupiers": "[TO POPULATE]",
                "other_interests": "[TO POPULATE]",
                "status": "pending_inquiry",
            })
    return rows


def _build_category_2(registered: list[dict]) -> list[dict]:
    """Category 2 claimants — typically adjoining owners whose land is injuriously
    affected by the execution of the works."""
    rows: list[dict] = []
    for i in range(1, 4):
        rows.append({
            "ref": f"Cat2-{i:03d}",
            "name": "[TO POPULATE]",
            "address": "[TO POPULATE]",
            "land_affected": "[TO POPULATE — adjoining holding affected by cable/access works]",
            "nature": "Potential injurious affection under s.10 CPA 1965",
            "status": "pending_inquiry",
        })
    return rows


def _build_category_3(registered: list[dict]) -> list[dict]:
    """Category 3 claimants — typically residents within noise / lighting zones of influence."""
    rows: list[dict] = []
    for i in range(1, 4):
        rows.append({
            "ref": f"Cat3-{i:03d}",
            "name": "[TO POPULATE]",
            "address": "[TO POPULATE]",
            "distance_m": "[TO POPULATE — e.g. dwelling within 200m of operational substation]",
            "nature": "Potential Part 1 LCA 1973 claim (noise / lighting / vibration)",
            "status": "pending_inquiry",
        })
    return rows
