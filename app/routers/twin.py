"""
app/routers/twin.py — FastAPI router for the Princeps 3D twin
authoritative backend.

Endpoints
---------
    GET  /api/twin/asset-catalogue
        Return the canonical ``app/data/asset_catalogue.json`` so the
        frontend renderer never diverges from the server-side layout
        engine.

    POST /api/twin/layout
        Body: ``{workload, params, site_polygon_wkt}``
        Returns: ``LayoutResponse`` — a list of ``PlacedAsset`` records with
        metric-offset xyz + rotation + scale.

    POST /api/twin/snapshot/{project_id}
        Body: ``{viewport, mode, layers}``
        Returns: server-rendered PNG of the twin (via Playwright headless
        Chromium pointed at the local frontend). Falls back to a diagnostic
        SVG if Playwright is unavailable.

    POST /api/twin/ga-drawing/{project_id}
        Body: ``{scale: 2000, paper_size: 'A1'}``
        Returns: A1 landscape PDF GA drawing via Jinja2 + Playwright.

    POST /api/twin/ifc-export/{project_id}
        Returns: IFC file via ``ifcopenshell`` if installed; otherwise falls
        back to DXF via ``ezdxf``; else returns a 501 with install guidance.

Register in ``app/main.py`` by adding ``"twin"`` to ``_ROUTER_MODULES``.
"""

from __future__ import annotations

import io
import json
import logging
import os
import tempfile
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import asyncpg
from fastapi import APIRouter, Body, Depends, HTTPException, Path as PathParam
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from jinja2 import Environment, FileSystemLoader

from app.deps import get_pool
from app.models.asset_primitive import (
    LayoutRequest,
    LayoutResponse,
    PlacedAsset,
)
from utils.asset_layout_engine import (
    _load_catalogue,
    catalogue_raw,
    layout_site_full,
)

log = logging.getLogger("princeps.twin")
router = APIRouter(tags=["twin"], prefix="")

# ---------------------------------------------------------------------------
# Paths + jinja env
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[2]
_CATALOGUE_PATH = _ROOT / "app" / "data" / "asset_catalogue.json"
_GA_TEMPLATES_DIR = _ROOT / "templates" / "ga_drawing"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_GA_TEMPLATES_DIR)),
    autoescape=True,
)


# ---------------------------------------------------------------------------
# Pydantic bodies
# ---------------------------------------------------------------------------
class SnapshotRequest(BaseModel):
    viewport: dict = Field(
        default_factory=dict,
        description="{center:[lon,lat], zoom, pitch, bearing, width_px, height_px}",
    )
    mode: Literal["3d", "2d", "plan"] = "3d"
    layers: list[str] = Field(
        default_factory=lambda: ["site", "assets", "grid"],
        description="Layer ids to render",
    )
    front_url: str | None = Field(
        None,
        description="Override of the frontend URL (default http://localhost:3000)",
    )


class GADrawingRequest(BaseModel):
    scale: int = Field(2000, ge=100, le=10000, description="Drawing scale 1:N")
    paper_size: Literal["A0", "A1", "A2", "A3"] = "A1"
    revision: str = "P1"
    project_name: str | None = None


class IFCExportRequest(BaseModel):
    include_grid: bool = False
    include_terrain: bool = False


# ---------------------------------------------------------------------------
# GET /api/twin/asset-catalogue
# ---------------------------------------------------------------------------
@router.get("/api/twin/asset-catalogue")
async def get_asset_catalogue():
    """Canonical catalogue consumed by BOTH frontend + backend layout engine."""
    try:
        # Warm the cache + validate on every call (cheap — cached by lru_cache).
        _ = _load_catalogue()
    except Exception as exc:
        log.exception("catalogue load failed")
        raise HTTPException(500, f"catalogue load failed: {exc}")
    return JSONResponse(catalogue_raw())


# ---------------------------------------------------------------------------
# POST /api/twin/layout
# ---------------------------------------------------------------------------
@router.post("/api/twin/layout", response_model=LayoutResponse)
async def post_layout(req: LayoutRequest = Body(...)):
    """Parametric site layout — authoritative server-side engine.

    Example body::

        {
          "workload": "bess",
          "params": {"mw_ac": 50, "mwh": 100, "duration_h": 2},
          "site_polygon_wkt": "POLYGON((-1.2 52.5, -1.196 52.5, -1.196 52.503, -1.2 52.503, -1.2 52.5))"
        }
    """
    try:
        resp = layout_site_full(req.workload, req.params, req.site_polygon_wkt)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        log.exception("layout_site failed")
        raise HTTPException(500, f"layout engine failed: {exc}")
    return resp


# ---------------------------------------------------------------------------
# POST /api/twin/snapshot/{project_id}
# ---------------------------------------------------------------------------
@router.post("/api/twin/snapshot/{project_id}")
async def post_snapshot(
    project_id: str = PathParam(..., description="Project UUID"),
    req: SnapshotRequest = Body(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Render the twin to a PNG via Playwright headless Chromium.

    The frontend must be running (default http://localhost:3000) and expose
    a ``/twin/{project_id}/snapshot`` route that accepts the viewport +
    mode + layers as querystring. If Playwright is unavailable the endpoint
    returns a diagnostic SVG so callers never 500.
    """
    try:
        _ = _uuid.UUID(project_id)
    except Exception:
        raise HTTPException(400, f"project_id is not a valid UUID: {project_id!r}")

    front = (req.front_url or os.environ.get("PRINCEPS_FRONTEND_URL")
             or "http://localhost:3000").rstrip("/")

    # Build the querystring for the frontend snapshot route.
    vp = req.viewport or {}
    qs_parts = [f"mode={req.mode}"]
    if req.layers:
        qs_parts.append("layers=" + ",".join(req.layers))
    for k, v in vp.items():
        qs_parts.append(f"{k}={json.dumps(v) if isinstance(v, (list, dict)) else v}")
    url = f"{front}/twin/{project_id}/snapshot?{'&'.join(qs_parts)}"
    width = int(vp.get("width_px") or 1920)
    height = int(vp.get("height_px") or 1080)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return _fallback_snapshot_svg(project_id, url, reason="playwright not installed")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={"width": width, "height": height})
            await page.goto(url, wait_until="networkidle", timeout=60000)
            png_bytes = await page.screenshot(type="png", full_page=False)
            await browser.close()
    except Exception as exc:
        log.warning("playwright snapshot failed: %s", exc)
        return _fallback_snapshot_svg(project_id, url, reason=str(exc))

    fname = f"twin-snapshot-{project_id[:8]}.png"
    return StreamingResponse(
        io.BytesIO(png_bytes),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


def _fallback_snapshot_svg(project_id: str, url: str, reason: str) -> Response:
    """Return a trivially valid SVG placeholder when headless render is down."""
    safe_url = url.replace("<", "&lt;").replace(">", "&gt;")
    safe_reason = reason.replace("<", "&lt;").replace(">", "&gt;")[:160]
    svg = (
        '<?xml version="1.0"?>'
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">'
        '<rect width="960" height="540" fill="#111827"/>'
        '<text x="480" y="240" fill="#d4a018" text-anchor="middle" '
        'font-family="sans-serif" font-size="28" font-weight="700">'
        'Princeps Twin Snapshot Unavailable</text>'
        f'<text x="480" y="285" fill="#e5e7eb" text-anchor="middle" '
        f'font-family="monospace" font-size="14">project: {project_id}</text>'
        f'<text x="480" y="315" fill="#9ca3af" text-anchor="middle" '
        f'font-family="monospace" font-size="12">{safe_url}</text>'
        f'<text x="480" y="365" fill="#f59e0b" text-anchor="middle" '
        f'font-family="sans-serif" font-size="13">{safe_reason}</text>'
        '</svg>'
    )
    return Response(content=svg, media_type="image/svg+xml")


# ---------------------------------------------------------------------------
# POST /api/twin/ga-drawing/{project_id}
# ---------------------------------------------------------------------------
@router.post("/api/twin/ga-drawing/{project_id}")
async def post_ga_drawing(
    project_id: str = PathParam(..., description="Project UUID"),
    req: GADrawingRequest = Body(default_factory=GADrawingRequest),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """A1 landscape PDF GA drawing via Jinja2 + Playwright."""
    try:
        pid = _uuid.UUID(project_id)
    except Exception:
        raise HTTPException(400, f"project_id is not a valid UUID: {project_id!r}")

    # Load project metadata (workload, params, site polygon if stored).
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT project_id, name, technology, capacity_mw, lat, lon,
                      metadata, stage, verdict
                 FROM projects WHERE project_id = $1""", pid,
        )
    if not row:
        raise HTTPException(404, f"project {project_id} not found")

    meta = _coerce_meta(row["metadata"])
    workload = (meta.get("workload") or row["technology"] or "solar").lower()
    # Normalise to engine dispatch keys.
    if workload in ("datacentre", "data_centre", "data centre"):
        workload = "dc"
    if workload in ("battery", "storage"):
        workload = "bess"
    if workload in ("hydrogen",):
        workload = "h2"

    wkt = meta.get("site_polygon_wkt") or meta.get("polygon_wkt")
    if not wkt and row["lat"] is not None and row["lon"] is not None:
        # Build a fallback 300 × 300 m box centred on the project lat/lon.
        import math as _m
        lat0 = float(row["lat"])
        lon0 = float(row["lon"])
        d = 0.0018  # ~200 m
        dlon = d / max(1e-6, _m.cos(_m.radians(lat0)))
        wkt = (f"POLYGON(({lon0-dlon} {lat0-d}, {lon0+dlon} {lat0-d}, "
               f"{lon0+dlon} {lat0+d}, {lon0-dlon} {lat0+d}, {lon0-dlon} {lat0-d}))")
    if not wkt:
        raise HTTPException(400, "project has no site polygon and no lat/lon — cannot render GA")

    # Build engine params from project metadata.
    cap_mw = float(row["capacity_mw"] or meta.get("capacity_mw") or 50.0)
    params = _params_for_workload(workload, cap_mw, meta)
    try:
        layout = layout_site_full(workload, params, wkt)
    except Exception as exc:
        log.exception("layout failed for project %s", project_id)
        raise HTTPException(500, f"layout failed: {exc}")

    catalogue = _load_catalogue()

    # Render template → HTML → PDF.
    try:
        template = _jinja_env.get_template("a1_landscape.html.j2")
    except Exception:
        raise HTTPException(500, "GA template templates/ga_drawing/a1_landscape.html.j2 missing")

    # Build placed-asset view-model with dims pulled from catalogue.
    view_assets: list[dict] = []
    for pa in layout.placed_assets:
        prim = catalogue.get(pa.primitive_id)
        if not prim:
            continue
        view_assets.append({
            "id": pa.primitive_id,
            "label": prim.label,
            "x": pa.xyz[0], "y": pa.xyz[1], "z": pa.xyz[2],
            "rot": pa.rotation_deg,
            "length": prim.dimensions_m.length_m,
            "width": prim.dimensions_m.width_m,
            "height": prim.dimensions_m.height_m,
            "colour": prim.colour_hex,
            "type": prim.type,
            "material": prim.material,
            "role": (pa.metadata or {}).get("role"),
        })

    # Collect unique primitives used for the legend.
    unique_primitives = {}
    for pa in layout.placed_assets:
        if pa.primitive_id not in unique_primitives:
            prim = catalogue.get(pa.primitive_id)
            if prim:
                unique_primitives[pa.primitive_id] = prim
    legend = [
        {
            "id": pid, "label": p.label, "colour": p.colour_hex,
            "count": sum(1 for a in layout.placed_assets if a.primitive_id == pid),
            "standards": ", ".join(p.standards_cited),
        }
        for pid, p in unique_primitives.items()
    ]

    # Standards digest.
    all_standards = sorted({
        s for p in unique_primitives.values() for s in p.standards_cited
    })

    ctx = {
        "project": {
            "id": str(row["project_id"]),
            "name": req.project_name or row["name"] or "Project",
            "technology": row["technology"],
            "capacity_mw": float(row["capacity_mw"]) if row["capacity_mw"] is not None else None,
            "stage": row["stage"],
            "verdict": row["verdict"],
            "lat": float(row["lat"]) if row["lat"] is not None else None,
            "lon": float(row["lon"]) if row["lon"] is not None else None,
        },
        "workload": workload,
        "params": params,
        "layout": {
            "bbox_m": layout.bbox_m,
            "centroid_lonlat": layout.centroid_lonlat,
            "centroid_osgb": layout.centroid_osgb,
            "counts": layout.counts,
            "notes": layout.notes,
            "placed_assets": view_assets,
        },
        "legend": legend,
        "standards": all_standards,
        "scale": req.scale,
        "paper_size": req.paper_size,
        "revision": req.revision,
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "grid_ref": _format_grid_ref(layout.centroid_osgb),
    }

    html_str = template.render(**ctx)

    pdf_bytes = await _html_to_pdf(html_str, paper_size=req.paper_size)
    fname = f"princeps-GA-{project_id[:8]}-{req.revision}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _format_grid_ref(osgb: tuple[float, float] | None) -> str | None:
    if not osgb:
        return None
    try:
        from utils.osgb import to_grid_ref
        # osgb is (easting, northing) but to_grid_ref expects (lat, lon); so
        # do a small round-trip via pyproj.
        from pyproj import Transformer
        to_4326 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
        lon, lat = to_4326.transform(osgb[0], osgb[1])
        return to_grid_ref(lat, lon, precision=8)
    except Exception:
        return f"E {int(osgb[0])} N {int(osgb[1])}"


def _coerce_meta(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, str)):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _params_for_workload(workload: str, cap_mw: float, meta: dict) -> dict:
    """Derive engine params from project row + metadata."""
    p = dict(meta.get("layout_params") or {})
    if workload == "bess":
        p.setdefault("mw_ac", cap_mw)
        p.setdefault("duration_h", meta.get("duration_h") or 2.0)
        p.setdefault("mwh", p.get("mw_ac") * p.get("duration_h"))
    elif workload == "solar":
        p.setdefault("mw_ac", cap_mw)
        p.setdefault("mwp", cap_mw * (meta.get("dc_ac_ratio") or 1.25))
    elif workload == "wind":
        p.setdefault("turbines", int(meta.get("turbines") or max(1, cap_mw // 4.5)))
    elif workload == "dc":
        p.setdefault("mw_it", meta.get("mw_it") or cap_mw)
        p.setdefault("tier", meta.get("tier") or "tier3")
        p.setdefault("redundancy_n_plus", int(meta.get("redundancy_n_plus") or 1))
    elif workload == "ev":
        p.setdefault("vehicles", int(meta.get("vehicles") or 20))
    elif workload == "h2":
        p.setdefault("kg_day", float(meta.get("kg_day") or 1000.0))
    return p


async def _html_to_pdf(html: str, paper_size: str = "A1") -> bytes:
    """Render HTML to PDF via headless Chromium. Reuses the Grid Connection
    PDF pattern."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise HTTPException(
            501,
            "playwright not installed — run: pip install playwright && "
            "playwright install chromium",
        )
    # A1 landscape = 841 × 594 mm.
    page_fmts = {
        "A0": {"width": "1189mm", "height": "841mm"},
        "A1": {"width": "841mm", "height": "594mm"},
        "A2": {"width": "594mm", "height": "420mm"},
        "A3": {"width": "420mm", "height": "297mm"},
    }
    dims = page_fmts.get(paper_size, page_fmts["A1"])

    with tempfile.NamedTemporaryFile(suffix=".html", mode="w",
                                     delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    try:
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch()
            except Exception:
                raise HTTPException(
                    501,
                    "Chromium not installed — run: playwright install chromium",
                )
            page = await browser.new_page()
            await page.goto(f"file://{tmp}", wait_until="networkidle", timeout=60000)
            pdf = await page.pdf(
                width=dims["width"],
                height=dims["height"],
                landscape=True,
                print_background=True,
                margin={"top": "10mm", "bottom": "10mm",
                        "left": "10mm", "right": "10mm"},
            )
            await browser.close()
            return pdf
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# POST /api/twin/ifc-export/{project_id}
# ---------------------------------------------------------------------------
@router.post("/api/twin/ifc-export/{project_id}")
async def post_ifc_export(
    project_id: str = PathParam(..., description="Project UUID"),
    req: IFCExportRequest = Body(default_factory=IFCExportRequest),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Export the authoritative layout to IFC (via ifcopenshell) or DXF
    (via ezdxf) as a fallback. Returns the file bytes; file extension
    communicates the format."""
    try:
        pid = _uuid.UUID(project_id)
    except Exception:
        raise HTTPException(400, f"project_id is not a valid UUID: {project_id!r}")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT project_id, name, technology, capacity_mw, lat, lon, metadata
                 FROM projects WHERE project_id = $1""", pid,
        )
    if not row:
        raise HTTPException(404, f"project {project_id} not found")

    meta = _coerce_meta(row["metadata"])
    workload = (meta.get("workload") or row["technology"] or "solar").lower()
    if workload in ("datacentre", "data_centre"):
        workload = "dc"
    if workload in ("battery", "storage"):
        workload = "bess"
    wkt = meta.get("site_polygon_wkt") or meta.get("polygon_wkt")
    if not wkt:
        raise HTTPException(400, "project has no site polygon — cannot export IFC")

    cap_mw = float(row["capacity_mw"] or 50.0)
    params = _params_for_workload(workload, cap_mw, meta)
    layout = layout_site_full(workload, params, wkt)
    catalogue = _load_catalogue()

    # Prefer ifcopenshell — write an IFC4 RC1 SPF file with one
    # IfcBuildingElementProxy per placed asset.
    try:
        import ifcopenshell
        import ifcopenshell.api
        data = _write_ifc(row, layout, catalogue, ifcopenshell, include_terrain=req.include_terrain)
        fname = f"princeps-twin-{project_id[:8]}.ifc"
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    except ImportError:
        log.info("ifcopenshell not installed — falling back to DXF")
    except Exception as exc:
        log.warning("IFC export failed, falling back to DXF: %s", exc)

    # DXF fallback.
    try:
        import ezdxf
    except ImportError:
        raise HTTPException(
            501,
            "Neither ifcopenshell nor ezdxf installed. Install one: "
            "pip install ifcopenshell OR pip install ezdxf",
        )
    data = _write_dxf(row, layout, catalogue, ezdxf)
    fname = f"princeps-twin-{project_id[:8]}.dxf"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/dxf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _write_ifc(project_row, layout, catalogue, ifcopenshell, include_terrain=False) -> bytes:
    """Build a minimal IFC4 file with each placed asset as IfcBuildingElementProxy.

    Full BIM semantic mapping (IfcSlab, IfcBuildingStorey, IfcFoundation)
    is a v2 exercise; v1 ships a proxy-per-asset footprint that is
    dimensionally and spatially correct and thereby opens cleanly in
    Revit / Navisworks / Solibri.
    """
    import ifcopenshell.api as api
    import ifcopenshell.guid as guid

    f = ifcopenshell.file(schema="IFC4")

    # Create project/site/building hierarchy via the api helper.
    proj = api.run("root.create_entity", f, ifc_class="IfcProject",
                   name=project_row["name"] or "Princeps Project")
    api.run("unit.assign_unit", f, length={"is_metric": True, "raw": "METERS"})
    ctx = api.run("context.add_context", f, context_type="Model")
    body = api.run("context.add_context", f,
                   context_type="Model", context_identifier="Body",
                   target_view="MODEL_VIEW", parent=ctx)

    site = api.run("root.create_entity", f, ifc_class="IfcSite",
                   name="Site")
    api.run("aggregate.assign_object", f, relating_object=proj, product=site)

    bldg = api.run("root.create_entity", f, ifc_class="IfcBuilding",
                   name="Twin")
    api.run("aggregate.assign_object", f, relating_object=site, product=bldg)

    # One proxy per placed asset.
    for pa in layout.placed_assets:
        prim = catalogue.get(pa.primitive_id)
        if not prim:
            continue
        proxy = api.run("root.create_entity", f,
                        ifc_class="IfcBuildingElementProxy",
                        name=prim.label)
        matrix = _ifc_placement_matrix(pa.xyz, pa.rotation_deg)
        api.run("geometry.edit_object_placement", f, product=proxy, matrix=matrix)
        rep = api.run(
            "geometry.add_representation", f,
            context=body, blender_object=None,
            geometry=None,
            # Use a simple swept-solid box representation:
            should_generate_uvs=False,
        ) if False else None
        # Fallback — write a simple extruded rectangle via raw API.
        _attach_box_representation(
            f, proxy, body,
            length=prim.dimensions_m.length_m,
            width=prim.dimensions_m.width_m,
            height=prim.dimensions_m.height_m,
        )
        api.run("spatial.assign_container", f,
                products=[proxy], relating_structure=bldg)

    return f.to_string().encode("utf-8")


def _ifc_placement_matrix(xyz: tuple[float, float, float], rot_deg: float):
    """Build a 4×4 transformation matrix for IFC placement."""
    import math as _m
    c = _m.cos(_m.radians(rot_deg))
    s = _m.sin(_m.radians(rot_deg))
    return [
        [c, -s, 0.0, xyz[0]],
        [s,  c, 0.0, xyz[1]],
        [0.0, 0.0, 1.0, xyz[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _attach_box_representation(f, proxy, body_ctx, length, width, height):
    """Attach an IfcShapeRepresentation with a single IfcExtrudedAreaSolid box."""
    # Centred rectangle profile.
    profile = f.create_entity(
        "IfcRectangleProfileDef",
        ProfileType="AREA",
        XDim=length,
        YDim=width,
    )
    # Axis placement at origin.
    axis = f.create_entity(
        "IfcAxis2Placement3D",
        Location=f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0)),
    )
    solid = f.create_entity(
        "IfcExtrudedAreaSolid",
        SweptArea=profile,
        Position=axis,
        ExtrudedDirection=f.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)),
        Depth=height,
    )
    shape = f.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=body_ctx,
        RepresentationIdentifier="Body",
        RepresentationType="SweptSolid",
        Items=[solid],
    )
    prod_def = f.create_entity(
        "IfcProductDefinitionShape",
        Representations=[shape],
    )
    proxy.Representation = prod_def


def _write_dxf(project_row, layout, catalogue, ezdxf) -> bytes:
    """DXF fallback — each asset as a LWPOLYLINE rectangle on a layer named
    after the primitive id. Unit = metres (ezdxf default model-space)."""
    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()
    for pa in layout.placed_assets:
        prim = catalogue.get(pa.primitive_id)
        if not prim:
            continue
        layer_name = prim.id.replace(".", "_")
        if layer_name not in doc.layers:
            doc.layers.add(name=layer_name)
        hl = prim.dimensions_m.length_m / 2.0
        hw = prim.dimensions_m.width_m / 2.0
        cx, cy = pa.xyz[0], pa.xyz[1]
        pts = [
            (cx - hl, cy - hw),
            (cx + hl, cy - hw),
            (cx + hl, cy + hw),
            (cx - hl, cy + hw),
            (cx - hl, cy - hw),
        ]
        msp.add_lwpolyline(pts, dxfattribs={"layer": layer_name})
        msp.add_text(prim.label, dxfattribs={"layer": layer_name, "height": 1.0}).set_placement(
            (cx, cy + hw + 1.0)
        )
    import io as _io
    buf = _io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")
