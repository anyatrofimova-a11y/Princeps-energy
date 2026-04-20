"""
Land Plans — Reg 5(2)(b) and Reg 7.

The Land Plans identify the extent of the Order land (the land to which the
application relates), the limits of deviation, and each plot numbered to
correspond to the Book of Reference. By convention the Land Plans are
presented at 1:2500 or 1:5000 Ordnance Survey scale with a red line
boundary indicating the Order limits, plot numbering, and a key.

This skeleton uses matplotlib to render a GeoJSON site boundary (and each
parcel polygon) to PNG. The PNG is embedded by the master template via a
data: URI. A full submission would use QGIS or Mapbox Static API to render
an OS 1:2500 basemap under the red line — that upgrade is tracked as a
Phase 7 task.

Citation: "In fulfilment of Regulation 5(2)(b) and Regulation 7 of the
Infrastructure Planning (Applications: Prescribed Forms and Procedure)
Regulations 2009 (SI 2009/2264)."
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

log = logging.getLogger("princeps.dco.land_plans")


def build_land_plan(
    project: dict,
    *,
    site_boundary_geojson: dict | None = None,
    parcels_geojson: dict | None = None,
) -> dict:
    """Return a Land Plan document structure with embedded PNG(s)."""
    proj_name = project.get("name") or "[Project]"

    png_data_uri = _render_land_plan_png(
        project,
        site_boundary_geojson=site_boundary_geojson,
        parcels_geojson=parcels_geojson,
    )

    return {
        "document_title": "Land Plans",
        "sheet_title": f"Land Plan — {proj_name} — Sheet 1 of 1",
        "regulation_citation": (
            "In fulfilment of Regulation 5(2)(b) and Regulation 7 of the "
            "Infrastructure Planning (Applications: Prescribed Forms and "
            "Procedure) Regulations 2009 (SI 2009/2264). Scale 1:2500 at A1 "
            "(presented here at A4 indicative). North up. OS coordinates EPSG:27700."
        ),
        "legend": [
            {"symbol": "Red line, solid", "meaning": "Order limits"},
            {"symbol": "Red hatching", "meaning": "Land to be acquired compulsorily (Category 1 Book of Reference)"},
            {"symbol": "Blue hatching", "meaning": "Land in which rights only are sought (Category 2)"},
            {"symbol": "Green hatching", "meaning": "Land subject to temporary possession (Category 3)"},
            {"symbol": "Numbered plots", "meaning": "Plot numbers cross-referenced to the Book of Reference"},
        ],
        "figure_png_data_uri": png_data_uri,
        "sheet_notes": [
            "This plan shall be read in conjunction with the Book of Reference and the Works Plans.",
            "All measurements in metres. All co-ordinates OSGB36 / British National Grid (EPSG:27700).",
            "Crown copyright and database rights [YEAR] Ordnance Survey [LICENCE NUMBER].",
            "Do not scale from this drawing for construction purposes.",
        ],
        "revision_block": {
            "revision": "P01",
            "status": "Application skeleton — full plans at submission",
            "drawn_by": "Princeps",
            "checked_by": "[TO POPULATE]",
            "approved_by": "[TO POPULATE]",
        },
    }


def _render_land_plan_png(
    project: dict,
    *,
    site_boundary_geojson: dict | None,
    parcels_geojson: dict | None,
) -> str:
    """Render a small PNG Land Plan and return as data: URI."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon as MplPoly
    except Exception as e:
        log.warning("matplotlib unavailable: %s", e)
        return ""

    fig, ax = plt.subplots(figsize=(8, 6), dpi=150)
    ax.set_aspect("equal")

    # Title / frame
    proj_name = project.get("name") or "[Project]"
    ax.set_title(f"Land Plan — {proj_name}\nReg 5(2)(b) Infrastructure Planning (Applications: Prescribed Forms and Procedure) Regulations 2009", fontsize=9)

    drew_anything = False

    # Draw site boundary (red)
    if site_boundary_geojson:
        try:
            _draw_geojson(ax, site_boundary_geojson, edgecolor="red", linewidth=2.0, fill=False, label="Order limits")
            drew_anything = True
        except Exception as e:
            log.warning("Failed to draw site boundary: %s", e)

    # Draw parcels (hatched, numbered)
    if parcels_geojson:
        try:
            _draw_geojson(ax, parcels_geojson, edgecolor="darkred", linewidth=0.7, fill=True, alpha=0.2, label="Plots")
            drew_anything = True
        except Exception as e:
            log.warning("Failed to draw parcels: %s", e)

    if not drew_anything:
        # Draw a stylised placeholder so the pack doesn't have a blank page
        lat = project.get("lat")
        lon = project.get("lon")
        if lat and lon:
            # A crude 500m square around centroid in WGS84
            d = 0.005
            poly = [(lon - d, lat - d), (lon + d, lat - d), (lon + d, lat + d), (lon - d, lat + d)]
            p = MplPoly(poly, closed=True, edgecolor="red", facecolor="none", linewidth=2.0, linestyle="--")
            ax.add_patch(p)
            ax.text(lon, lat, "Order limits\n(indicative)", ha="center", va="center", fontsize=8, color="red")
            ax.set_xlim(lon - d * 2, lon + d * 2)
            ax.set_ylim(lat - d * 2, lat + d * 2)
            ax.set_xlabel("Longitude (WGS84)")
            ax.set_ylabel("Latitude (WGS84)")
        else:
            ax.text(0.5, 0.5, "TO POPULATE\nSite boundary not yet ingested",
                    ha="center", va="center", fontsize=12, color="darkred", transform=ax.transAxes)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)

    # North arrow (simple)
    ax.annotate("N", xy=(0.95, 0.95), xytext=(0.95, 0.88),
                xycoords="axes fraction", ha="center", fontsize=12, fontweight="bold",
                arrowprops=dict(facecolor="black", width=2, headwidth=8))

    ax.grid(True, linestyle=":", linewidth=0.3, alpha=0.5)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _draw_geojson(ax, geojson: dict, *, edgecolor="red", facecolor="none",
                  linewidth=1.5, fill=False, alpha=0.3, label=None):
    """Draw polygons from a GeoJSON FeatureCollection / Feature / Geometry."""
    from matplotlib.patches import Polygon as MplPoly

    features = []
    if geojson.get("type") == "FeatureCollection":
        features = geojson.get("features") or []
    elif geojson.get("type") == "Feature":
        features = [geojson]
    else:
        # raw geometry
        features = [{"type": "Feature", "geometry": geojson, "properties": {}}]

    drew = False
    for feat in features:
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if gtype == "Polygon":
            for ring in coords:
                if ring and len(ring) >= 3:
                    poly = MplPoly(
                        [(x, y) for x, y in ring],
                        closed=True,
                        edgecolor=edgecolor,
                        facecolor=facecolor if fill else "none",
                        linewidth=linewidth,
                        alpha=alpha if fill else 1.0,
                        hatch="///" if fill else None,
                    )
                    ax.add_patch(poly)
                    drew = True
        elif gtype == "MultiPolygon":
            for polygon in coords:
                for ring in polygon:
                    if ring and len(ring) >= 3:
                        poly = MplPoly(
                            [(x, y) for x, y in ring],
                            closed=True,
                            edgecolor=edgecolor,
                            facecolor=facecolor if fill else "none",
                            linewidth=linewidth,
                            alpha=alpha if fill else 1.0,
                            hatch="///" if fill else None,
                        )
                        ax.add_patch(poly)
                        drew = True

    if drew:
        ax.relim()
        ax.autoscale_view()
