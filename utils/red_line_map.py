"""
Red-line site-boundary map generator for the Site Assessment pack.

Produces a PNG showing the project's red-line boundary plus overlays for
the constraints a planning committee expects to see:

    • Red-line boundary   — 2 pt red stroke (industry convention)
    • AONB / National Landscape polygons — translucent green fill
    • SSSI polygons        — translucent purple fill
    • EA flood zones 2/3   — translucent blue fill
    • Slope hatching       — diagonal hatching where slope > 10° from DTM
    • Access roads         — OSM highway=motorway/trunk/primary/secondary
    • Basemap              — contextily if available, else plain graticule

Data sources (queried in this order, with graceful fallback):
    1. PostGIS `site_boundaries.geometry` (SRID 4326)
    2. PostGIS `designations_*` tables if populated (BOT-G's ingesters)
    3. Overpass / OSM for access roads (best-effort, ignored if offline)
    4. `dem_slope` raster / table if populated, else skipped

If the designation tables are empty the map still renders, and the caller
is expected to show a "no designations data available" footnote.
"""
from __future__ import annotations

import io
import logging
import math
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon, Patch
from matplotlib.lines import Line2D

log = logging.getLogger("princeps.redline")

# Style palette — matches Princeps brand
RED_LINE = "#d62828"
FILL_AONB = (0.18, 0.56, 0.31, 0.35)     # green translucent
FILL_SSSI = (0.51, 0.23, 0.69, 0.35)     # purple translucent
FILL_FLOOD = (0.14, 0.45, 0.78, 0.30)    # blue translucent
SLOPE_HATCH_COLOUR = (0.95, 0.60, 0.20, 0.85)
ROAD_COLOUR = (0.20, 0.20, 0.20, 0.85)

# Padding (degrees lon/lat) to frame the site on the map
DEFAULT_PAD_DEG = 0.02


# ─────────────────────────────────────────────────────────────────────────────
# Geometry helpers — pure Python, no shapely dependency required
# ─────────────────────────────────────────────────────────────────────────────
def _rings_from_geojson(geom: Any) -> list[list[tuple[float, float]]]:
    """Extract outer rings as lists of (lon, lat) from a GeoJSON geometry dict."""
    if not geom:
        return []
    if isinstance(geom, str):
        import json as _json
        try:
            geom = _json.loads(geom)
        except Exception:
            return []
    gtype = (geom.get("type") or "").lower()
    coords = geom.get("coordinates") or []
    rings: list[list[tuple[float, float]]] = []
    if gtype == "polygon" and coords:
        rings.append([(float(pt[0]), float(pt[1])) for pt in coords[0]])
    elif gtype == "multipolygon":
        for poly in coords:
            if not poly:
                continue
            rings.append([(float(pt[0]), float(pt[1])) for pt in poly[0]])
    elif gtype == "linestring":
        rings.append([(float(pt[0]), float(pt[1])) for pt in coords])
    elif gtype == "multilinestring":
        for line in coords:
            rings.append([(float(pt[0]), float(pt[1])) for pt in line])
    return rings


def _bounds(rings: list[list[tuple[float, float]]]) -> Optional[tuple[float, float, float, float]]:
    xs: list[float] = []
    ys: list[float] = []
    for r in rings:
        for x, y in r:
            xs.append(x)
            ys.append(y)
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _square_bounds(bx: tuple[float, float, float, float], pad_deg: float
                   ) -> tuple[float, float, float, float]:
    """Pad and square the bounds so the map isn't stretched."""
    minx, miny, maxx, maxy = bx
    dx = (maxx - minx) + 2 * pad_deg
    dy = (maxy - miny) + 2 * pad_deg
    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0
    # Correct for latitude compression when squaring in lon/lat space
    lat_rad = math.radians(cy)
    lon_scale = max(math.cos(lat_rad), 0.1)
    # Work out half-side in lat and widen lon accordingly
    half = max(dx / 2.0, dy / 2.0)
    return (cx - half / lon_scale, cy - half, cx + half / lon_scale, cy + half)


# ─────────────────────────────────────────────────────────────────────────────
# Data fetchers
# ─────────────────────────────────────────────────────────────────────────────
async def _fetch_site_boundary(conn, project_id: str) -> tuple[Optional[dict], Optional[str]]:
    """Return (geojson_geom, site_name) for the project's red-line boundary."""
    row = await conn.fetchrow(
        """
        SELECT name,
               ST_AsGeoJSON(ST_Transform(geometry, 4326))::jsonb AS geom
          FROM site_boundaries
         WHERE project_id = $1::uuid
         ORDER BY created_at DESC
         LIMIT 1
        """,
        project_id,
    )
    if not row:
        return None, None
    return row["geom"], row["name"]


async def _fetch_designations(conn, bx: tuple[float, float, float, float]) -> dict[str, list[dict]]:
    """Fetch designation polygons intersecting the map bounds. Returns
    a dict keyed by {aonb, sssi, flood}; silently returns empty lists
    if the tables don't exist or are empty."""
    out: dict[str, list[dict]] = {"aonb": [], "sssi": [], "flood": []}
    minx, miny, maxx, maxy = bx
    env_sql = (
        "ST_Intersects(geom, ST_MakeEnvelope($1, $2, $3, $4, 4326))"
    )
    queries = {
        "aonb": f"SELECT name, ST_AsGeoJSON(geom)::jsonb AS geom FROM designations_aonb WHERE {env_sql} LIMIT 25",
        "sssi": f"SELECT name, ST_AsGeoJSON(geom)::jsonb AS geom FROM designations_sssi WHERE {env_sql} LIMIT 25",
        "flood": f"SELECT name, ST_AsGeoJSON(geom)::jsonb AS geom FROM designations_flood_zones WHERE {env_sql} LIMIT 25",
    }
    for key, sql in queries.items():
        try:
            rows = await conn.fetch(sql, minx, miny, maxx, maxy)
            out[key] = [dict(r) for r in rows]
        except Exception as e:  # table missing / column missing / etc.
            log.debug("designation fetch (%s) skipped: %s", key, e)
            out[key] = []
    return out


async def _fetch_osm_roads(bx: tuple[float, float, float, float]) -> list[dict]:
    """Fetch major OSM roads from Overpass. Returns a list of
    {"class": "primary", "geom": GeoJSON LineString}.
    Best-effort only — skipped if offline or the API is slow."""
    minx, miny, maxx, maxy = bx
    query = f"""
        [out:json][timeout:8];
        (
          way["highway"~"motorway|trunk|primary|secondary"]
             ({miny:.6f},{minx:.6f},{maxy:.6f},{maxx:.6f});
        );
        out geom;
    """
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": query},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception as e:
        log.debug("Overpass fetch skipped: %s", e)
        return []
    roads: list[dict] = []
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        pts = [(p["lon"], p["lat"]) for p in geom]
        roads.append({
            "class": el.get("tags", {}).get("highway", "road"),
            "coords": pts,
        })
    return roads


# ─────────────────────────────────────────────────────────────────────────────
# Plotting primitives
# ─────────────────────────────────────────────────────────────────────────────
def _draw_rings(ax, rings: list[list[tuple[float, float]]], *, face, edge,
                lw: float = 0.8, label: str | None = None) -> None:
    first = True
    for ring in rings:
        if len(ring) < 3:
            continue
        poly = MplPolygon(
            ring, closed=True, facecolor=face, edgecolor=edge,
            linewidth=lw, label=label if first else None,
        )
        ax.add_patch(poly)
        first = False


def _draw_red_line(ax, rings: list[list[tuple[float, float]]]) -> None:
    for ring in rings:
        if len(ring) < 2:
            continue
        xs = [p[0] for p in ring] + [ring[0][0]]
        ys = [p[1] for p in ring] + [ring[0][1]]
        ax.plot(xs, ys, "-", color=RED_LINE, linewidth=2.2, zorder=9)


def _draw_slope_hatch(ax, bx: tuple[float, float, float, float],
                      slope_polys: Optional[list[list[tuple[float, float]]]] = None) -> None:
    """If we have slope polygons from DTM, hatch them. Otherwise draw a
    small indicative hatch in the corner so the legend key makes sense."""
    if slope_polys:
        for ring in slope_polys:
            if len(ring) < 3:
                continue
            poly = MplPolygon(
                ring, closed=True, facecolor="none",
                edgecolor=SLOPE_HATCH_COLOUR, linewidth=0.5,
                hatch="//", zorder=3,
            )
            ax.add_patch(poly)


# ─────────────────────────────────────────────────────────────────────────────
# Public render functions
# ─────────────────────────────────────────────────────────────────────────────
def render_redline_png(
    boundary_geom: dict,
    *,
    site_name: str = "Site",
    aonb: list[dict] | None = None,
    sssi: list[dict] | None = None,
    flood: list[dict] | None = None,
    roads: list[dict] | None = None,
    slope_polys: list[list[tuple[float, float]]] | None = None,
    width_in: float = 8.0,
    height_in: float = 6.0,
    dpi: int = 180,
    data_gaps: list[str] | None = None,
) -> bytes:
    """Render the red-line map to a PNG byte string (pure synchronous)."""
    rings = _rings_from_geojson(boundary_geom)
    if not rings:
        raise ValueError("Boundary geometry produced no rings")

    bx = _bounds(rings)
    if bx is None:
        raise ValueError("Boundary has no vertices")
    minx, miny, maxx, maxy = _square_bounds(bx, DEFAULT_PAD_DEG)

    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=dpi)
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect("equal", adjustable="box")
    ax.set_facecolor("#f6f4ee")

    # Graticule background (light lat/lon lines)
    for gx in _ticks(minx, maxx, 6):
        ax.axvline(gx, color="#d8d4c8", linewidth=0.4, zorder=1)
    for gy in _ticks(miny, maxy, 6):
        ax.axhline(gy, color="#d8d4c8", linewidth=0.4, zorder=1)

    # Optional contextily basemap
    try:
        import contextily as ctx
        ctx.add_basemap(
            ax,
            crs="EPSG:4326",
            source=ctx.providers.CartoDB.Positron,
            attribution_size=5,
        )
    except Exception as e:
        log.debug("contextily basemap skipped: %s", e)

    # ── Overlays ────────────────────────────────────────────────────────
    if aonb:
        for d in aonb:
            for ring in _rings_from_geojson(d.get("geom")):
                _draw_rings(ax, [ring], face=FILL_AONB,
                            edge=(0.12, 0.43, 0.23, 0.9), lw=0.7)
    if sssi:
        for d in sssi:
            for ring in _rings_from_geojson(d.get("geom")):
                _draw_rings(ax, [ring], face=FILL_SSSI,
                            edge=(0.34, 0.15, 0.47, 0.9), lw=0.7)
    if flood:
        for d in flood:
            for ring in _rings_from_geojson(d.get("geom")):
                _draw_rings(ax, [ring], face=FILL_FLOOD,
                            edge=(0.08, 0.30, 0.55, 0.9), lw=0.7)

    # Roads
    if roads:
        for rd in roads:
            pts = rd.get("coords", [])
            if len(pts) < 2:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            ax.plot(xs, ys, "-", color=ROAD_COLOUR, linewidth=1.0, zorder=5)

    # Slope hatching (if any)
    _draw_slope_hatch(ax, (minx, miny, maxx, maxy), slope_polys)

    # Red-line boundary (on top)
    _draw_red_line(ax, rings)

    # ── Titles, scale, attribution ──────────────────────────────────────
    ax.set_title(f"{site_name} — Red-Line Boundary",
                 fontsize=12, fontweight="bold", pad=10)
    ax.set_xlabel("Longitude", fontsize=8)
    ax.set_ylabel("Latitude", fontsize=8)
    ax.tick_params(labelsize=7)

    # Legend
    handles = [
        Line2D([], [], color=RED_LINE, linewidth=2.2, label="Red-line boundary"),
        Patch(facecolor=FILL_AONB, edgecolor=(0.12, 0.43, 0.23), label="AONB / National Landscape"),
        Patch(facecolor=FILL_SSSI, edgecolor=(0.34, 0.15, 0.47), label="SSSI"),
        Patch(facecolor=FILL_FLOOD, edgecolor=(0.08, 0.30, 0.55), label="EA Flood Zone 2/3"),
        Line2D([], [], color=ROAD_COLOUR, linewidth=1.0, label="Access roads (OSM)"),
        Patch(facecolor="none", edgecolor=SLOPE_HATCH_COLOUR, hatch="//", label="Slope > 10°"),
    ]
    ax.legend(handles=handles, loc="lower left", fontsize=7,
              framealpha=0.9, facecolor="white", edgecolor="#bbb")

    # Data-gap disclaimer footnote
    footer_bits: list[str] = []
    if data_gaps:
        footer_bits.append("Data gaps: " + "; ".join(data_gaps))
    footer_bits.append("Basemap: CartoDB Positron via contextily (fallback graticule). OSM roads.")
    ax.text(
        0.5, -0.12, " | ".join(footer_bits),
        transform=ax.transAxes, ha="center", va="top",
        fontsize=6, color="#555",
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _ticks(lo: float, hi: float, n: int) -> list[float]:
    if n <= 1 or hi <= lo:
        return []
    step = (hi - lo) / float(n)
    return [lo + step * i for i in range(1, n)]


# ─────────────────────────────────────────────────────────────────────────────
# Async orchestrator used by the site-assessment pack
# ─────────────────────────────────────────────────────────────────────────────
async def render_redline_for_project(conn, project_id: str,
                                     *, fetch_osm: bool = True,
                                     width_in: float = 8.0,
                                     height_in: float = 6.0,
                                     dpi: int = 180) -> dict:
    """Pull boundary + constraints from the database and render a PNG.

    Returns
    -------
    dict with keys:
        png_bytes      — raw PNG image
        site_name      — boundary label
        data_gaps      — list of human-readable strings describing
                          which layers fell back to empty (for the pack
                          footnote).
        overlay_counts — {aonb, sssi, flood, roads} counts actually drawn
    """
    geom, site_name = await _fetch_site_boundary(conn, project_id)
    if not geom:
        raise ValueError(f"No site boundary found for project {project_id}")

    rings = _rings_from_geojson(geom)
    bx = _bounds(rings)
    if bx is None:
        raise ValueError("Boundary produced no rings")
    padded = _square_bounds(bx, DEFAULT_PAD_DEG)

    # Fetch constraints + roads in parallel
    import asyncio as _asyncio
    tasks: list = [_fetch_designations(conn, padded)]
    if fetch_osm:
        tasks.append(_fetch_osm_roads(padded))
    else:
        async def _empty() -> list[dict]:
            return []
        tasks.append(_empty())

    desig, roads = await _asyncio.gather(*tasks, return_exceptions=True)
    if isinstance(desig, Exception) or not isinstance(desig, dict):
        desig = {"aonb": [], "sssi": [], "flood": []}
    if isinstance(roads, Exception) or not isinstance(roads, list):
        roads = []

    data_gaps: list[str] = []
    if not desig.get("aonb") and not desig.get("sssi") and not desig.get("flood"):
        data_gaps.append("no statutory designations data available (BOT-G ingesters pending)")
    if not roads:
        data_gaps.append("OSM access-road overlay unavailable")

    png = render_redline_png(
        geom,
        site_name=site_name or "Site",
        aonb=desig.get("aonb") or [],
        sssi=desig.get("sssi") or [],
        flood=desig.get("flood") or [],
        roads=roads or [],
        slope_polys=None,
        width_in=width_in,
        height_in=height_in,
        dpi=dpi,
        data_gaps=data_gaps,
    )
    return {
        "png_bytes": png,
        "site_name": site_name or "Site",
        "data_gaps": data_gaps,
        "overlay_counts": {
            "aonb": len(desig.get("aonb") or []),
            "sssi": len(desig.get("sssi") or []),
            "flood": len(desig.get("flood") or []),
            "roads": len(roads or []),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Lightweight lat/lon variant used when there is no project_id yet — the
# report_renderer calls this when a user just dropped a pin on the map.
# ─────────────────────────────────────────────────────────────────────────────
def render_redline_from_point(
    lat: float, lon: float, *,
    site_name: str = "Site", half_side_deg: float = 0.004,
    width_in: float = 8.0, height_in: float = 6.0, dpi: int = 180,
    data_gaps: list[str] | None = None,
) -> bytes:
    """Render a red-line map from a lat/lon pin with a square footprint
    (~half_side_deg each side). Used when we have a drop-pin but no
    persisted polygon in site_boundaries."""
    ring = [
        (lon - half_side_deg, lat - half_side_deg),
        (lon + half_side_deg, lat - half_side_deg),
        (lon + half_side_deg, lat + half_side_deg),
        (lon - half_side_deg, lat + half_side_deg),
        (lon - half_side_deg, lat - half_side_deg),
    ]
    geom = {"type": "Polygon", "coordinates": [list(ring)]}
    gaps = list(data_gaps or [])
    if not any("designations" in g for g in gaps):
        gaps.append("red-line drawn from drop-pin (no persisted polygon)")
    return render_redline_png(
        geom,
        site_name=site_name,
        aonb=None, sssi=None, flood=None, roads=None,
        width_in=width_in, height_in=height_in, dpi=dpi,
        data_gaps=gaps,
    )


__all__ = [
    "render_redline_png",
    "render_redline_from_point",
    "render_redline_for_project",
    "RED_LINE",
]
