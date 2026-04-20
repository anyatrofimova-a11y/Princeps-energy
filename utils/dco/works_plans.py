"""
Works Plans — Reg 5(2)(b).

The Works Plans identify each 'Work No.' described in Schedule 1 of the
draft DCO by reference to its location within the Order limits. Convention
is 1:2500 or 1:5000 at A1 with each work numbered and coloured per the
order of works.

This module is a thin GeoJSON-to-PNG helper. The full submission will
require professionally draughted plans, but the skeleton demonstrates
structural compliance.

Citation: "In fulfilment of Regulation 5(2)(b) of the Infrastructure
Planning (Applications: Prescribed Forms and Procedure) Regulations 2009
(SI 2009/2264)."
"""

from __future__ import annotations

import base64
import io
import logging

log = logging.getLogger("princeps.dco.works_plans")


def build_works_plan(
    project: dict,
    *,
    site_boundary_geojson: dict | None = None,
    works_geojson: dict | None = None,
) -> dict:
    """Return Works Plan document structure with embedded PNG."""
    proj_name = project.get("name") or "[Project]"
    tech = (project.get("workload_type") or project.get("technology") or "solar").lower()

    png = _render_works_png(project, site_boundary_geojson, works_geojson)

    works_schedule = _default_works_schedule(tech, project.get("capacity_mw"))

    return {
        "document_title": "Works Plans",
        "sheet_title": f"Works Plan — {proj_name} — Sheet 1 of 1",
        "regulation_citation": (
            "In fulfilment of Regulation 5(2)(b) of the Infrastructure Planning "
            "(Applications: Prescribed Forms and Procedure) Regulations 2009 "
            "(SI 2009/2264). Scale 1:2500 at A1 (presented here indicatively). "
            "Numbered Work references correspond to Schedule 1 of the draft Order."
        ),
        "works_schedule": works_schedule,
        "legend": [
            {"symbol": "Red line", "meaning": "Order limits (as Land Plan)"},
            {"symbol": "Colour-filled area with Work No.", "meaning": "Discrete work area — cross-reference Schedule 1"},
            {"symbol": "Arrow / linear", "meaning": "Linear works (cable, access track)"},
        ],
        "figure_png_data_uri": png,
        "sheet_notes": [
            "Read in conjunction with the Land Plans and the Book of Reference.",
            "Work No. references correspond to Schedule 1 (Authorised development) of the draft DCO.",
            "Limits of deviation — the horizontal and vertical limits within which each work may be varied — are defined in article [x] of the draft Order.",
            "Crown copyright and database rights [YEAR] Ordnance Survey [LICENCE NUMBER].",
        ],
        "revision_block": {
            "revision": "P01",
            "status": "Application skeleton",
            "drawn_by": "Princeps",
            "checked_by": "[TO POPULATE]",
            "approved_by": "[TO POPULATE]",
        },
    }


def _default_works_schedule(tech: str, cap_mw) -> list[dict]:
    """Produce a default Work No. list matching draft DCO Schedule 1."""
    if tech == "solar":
        return [
            {"work_no": "1", "short_description": f"Solar PV generating station up to {cap_mw or '[CAP]'} MW"},
            {"work_no": "2", "short_description": "Electricity storage facility (BESS)"},
            {"work_no": "3", "short_description": "On-site substation compound"},
            {"work_no": "4", "short_description": "Grid connection cable(s) and associated works"},
            {"work_no": "5", "short_description": "Temporary construction compounds and laydown areas"},
            {"work_no": "6", "short_description": "Landscaping, biodiversity mitigation and drainage"},
        ]
    if tech == "bess":
        return [
            {"work_no": "1", "short_description": f"Battery energy storage system up to {cap_mw or '[CAP]'} MW"},
            {"work_no": "2", "short_description": "On-site substation"},
            {"work_no": "3", "short_description": "Grid connection infrastructure"},
            {"work_no": "4", "short_description": "Ancillary works (fencing, internal roads, landscaping)"},
        ]
    if tech == "dc":
        return [
            {"work_no": "1", "short_description": f"Data centre campus up to {cap_mw or '[CAP]'} MW IT load"},
            {"work_no": "2", "short_description": "On-site primary substation and grid connection"},
            {"work_no": "3", "short_description": "Emergency standby generation and fuel storage"},
            {"work_no": "4", "short_description": "Fibre connection and access roads"},
        ]
    return [{"work_no": "1", "short_description": "[Work No. 1 — TO POPULATE]"}]


def _render_works_png(
    project: dict,
    site_boundary_geojson: dict | None,
    works_geojson: dict | None,
) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle, Polygon as MplPoly
    except Exception as e:
        log.warning("matplotlib unavailable: %s", e)
        return ""

    fig, ax = plt.subplots(figsize=(8, 6), dpi=150)
    ax.set_aspect("equal")
    proj_name = project.get("name") or "[Project]"
    ax.set_title(f"Works Plan — {proj_name}\nReg 5(2)(b) SI 2009/2264", fontsize=9)

    lat = project.get("lat")
    lon = project.get("lon")

    # Draw a schematic "works" layout — colour-numbered boxes inside an outline
    if lat and lon:
        d = 0.005  # ~ 500m
        # outline
        outline = MplPoly([(lon - d, lat - d), (lon + d, lat - d), (lon + d, lat + d), (lon - d, lat + d)],
                          closed=True, edgecolor="red", facecolor="none", linewidth=2.0)
        ax.add_patch(outline)

        # Work 1 (solar array) — NW quadrant
        w1 = Rectangle((lon - d * 0.9, lat + d * 0.1), d * 1.0, d * 0.7,
                       edgecolor="#C9A64B", facecolor="#F5E9C8", linewidth=1.2)
        ax.add_patch(w1)
        ax.text(lon - d * 0.4, lat + d * 0.45, "1\nSolar PV", ha="center", va="center", fontsize=8, color="#7A5C18")

        # Work 2 (BESS) — SW corner
        w2 = Rectangle((lon - d * 0.9, lat - d * 0.8), d * 0.5, d * 0.4,
                       edgecolor="#1B365D", facecolor="#D1DCEA", linewidth=1.2)
        ax.add_patch(w2)
        ax.text(lon - d * 0.65, lat - d * 0.6, "2\nBESS", ha="center", va="center", fontsize=8, color="#1B365D")

        # Work 3 (substation) — SE
        w3 = Rectangle((lon + d * 0.3, lat - d * 0.8), d * 0.4, d * 0.4,
                       edgecolor="#007A8C", facecolor="#B8DCE2", linewidth=1.2)
        ax.add_patch(w3)
        ax.text(lon + d * 0.5, lat - d * 0.6, "3\nSubstn", ha="center", va="center", fontsize=8, color="#007A8C")

        # Work 4 (cable to POC) — arrow leaving SE corner
        ax.annotate("4 — grid cable",
                    xy=(lon + d * 1.5, lat - d * 1.0), xytext=(lon + d * 0.5, lat - d * 0.6),
                    arrowprops=dict(arrowstyle="->", color="#A88732", lw=1.2),
                    fontsize=8, color="#A88732")

        ax.set_xlim(lon - d * 2, lon + d * 2)
        ax.set_ylim(lat - d * 2, lat + d * 2)
        ax.set_xlabel("Longitude (WGS84)")
        ax.set_ylabel("Latitude (WGS84)")
    else:
        ax.text(0.5, 0.5, "TO POPULATE\nWorks layout pending",
                ha="center", va="center", fontsize=12, color="darkred", transform=ax.transAxes)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)

    ax.annotate("N", xy=(0.95, 0.95), xytext=(0.95, 0.88),
                xycoords="axes fraction", ha="center", fontsize=12, fontweight="bold",
                arrowprops=dict(facecolor="black", width=2, headwidth=8))
    ax.grid(True, linestyle=":", linewidth=0.3, alpha=0.5)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
