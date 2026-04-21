"""
app/models/asset_primitive.py — Pydantic models for the Princeps 3D-twin
asset catalogue.

Every physical primitive that can appear on the twin (BESS Megapack, Sungrow
1500 V inverter, Tesla V4 Supercharger, 1 MW hydrogen electrolyser, etc.) is
described by a single ``AssetPrimitive`` record. Records live in
``app/data/asset_catalogue.json`` and are consumed in two places:

    * Frontend — ``GET /api/twin/asset-catalogue`` seeds the client-side
      renderer so each primitive has authoritative dimensions, colour, GLB
      path and vendor metadata.
    * Backend — ``utils.asset_layout_engine.layout_site`` looks up primitives
      by ``id`` and places them on a site polygon following the parametric
      rules attached to the record (count driven by MW / MWh / MWp etc.).

Why a shared model?
    Client-side speed (instant redraw on MW slider move) + server-side
    authority (construction-grade PDF GA drawings and IFC / DXF exports)
    require that the two sides never disagree on what a "Megapack 2XL" is.
    Shipping the catalogue as JSON served from the API — and validated by
    Pydantic on load — guarantees a single source of truth.

Standards cited per primitive should reference the governing UK document:
BS 8629 (BESS safety zones), BS 7698-12 (genset siting), BS EN 61439
(switchgear), ENA EREC G99 Issue 2 (grid code), BS EN IEC 63056 (lithium
battery installations), etc.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------
class Dimensions(BaseModel):
    """Physical bounding box of an asset primitive (metres).

    ``length_m`` is the long axis, ``width_m`` the short axis, ``height_m``
    the vertical extent. ``diameter_m`` is used in place of length/width for
    cylindrical assets (gas vessels, TX radiators, wind-turbine rotor). All
    values are metres. ``clearance_m`` is the minimum external keep-out zone
    required around the asset — used by the layout engine when packing
    rows / yards / exclusion zones.
    """
    model_config = ConfigDict(extra="forbid")

    length_m: float = Field(..., gt=0.0, description="Long axis length (m)")
    width_m: float = Field(..., gt=0.0, description="Short axis width (m)")
    height_m: float = Field(..., gt=0.0, description="Vertical height (m)")
    diameter_m: float | None = Field(
        None, gt=0.0,
        description="For cylindrical primitives — overrides length/width",
    )
    clearance_m: float = Field(
        1.0, ge=0.0,
        description="Minimum external keep-out zone (m) — used by layout engine",
    )


# ---------------------------------------------------------------------------
# Parametric rule
# ---------------------------------------------------------------------------
class ParametricRule(BaseModel):
    """How many instances of this primitive a site needs, expressed as a
    formula driven by the upstream capacity variable.

    Drivers
    -------
        mw_ac     — AC export power (BESS PCS, solar inverter station)
        mwh       — stored energy (BESS container)
        mw_it     — data-centre IT load (halls, coolers, gensets)
        mwp       — solar DC peak (tables)
        vehicles  — EV forecourt (charger count)
        kg_day    — hydrogen output (electrolyser sizing)
        turbines  — explicit turbine count (wind farm)

    Formula
    -------
        Python expression evaluated against the driver. The driver name is
        bound as the variable; e.g. ``ceil(mwh / 3.9)`` for Megapack 2XL,
        ``ceil(mw_ac / 2.0)`` for a 2 MVA PCS skid. The layout engine
        imports ``math`` into the eval namespace so ``ceil``, ``floor``,
        ``max``, ``min`` are all available.

    Constraints
    -----------
        ``count_min`` / ``count_max`` cap the formula result.
        ``spacing_m`` is the intra-row pitch (centre-to-centre).
        ``row_length_max`` caps the number of units per row (e.g. BS 8629
        limits a BESS row to eight 20 ft containers for firefighter access).
    """
    model_config = ConfigDict(extra="forbid")

    driver: Literal[
        "mw_ac", "mwh", "mw_it", "mwp", "vehicles", "kg_day", "turbines",
    ] = Field(..., description="Upstream capacity variable driving the count")
    formula: str = Field(..., description="Python expression bound against driver")
    count_min: int = Field(1, ge=0, description="Minimum units regardless of formula")
    count_max: int = Field(10000, ge=1, description="Upper cap on the formula result")
    spacing_m: float | None = Field(
        None, ge=0.0,
        description="Intra-row pitch (m) — centre-to-centre of adjacent units",
    )
    row_length_max: int | None = Field(
        None, ge=1,
        description="Maximum units per row (e.g. BS 8629 = 8 for BESS)",
    )


# ---------------------------------------------------------------------------
# Asset primitive
# ---------------------------------------------------------------------------
class AssetPrimitive(BaseModel):
    """Canonical description of a single physical asset type.

    Used by the 3D twin renderer, the layout engine, the GA drawing template
    and the IFC / DXF exporters. The catalogue is static JSON — no per-project
    overrides live here; project-specific layouts live in ``placed_assets``.
    """
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ..., min_length=1, max_length=64,
        description="Stable primitive id — e.g. 'bess.megapack_2xl'",
    )
    workload: Literal[
        "bess", "solar", "wind", "data_centre", "ev", "hydrogen", "common",
    ] = Field(..., description="Primary workload family")
    type: str = Field(
        ..., min_length=1,
        description="Sub-category — container, inverter, transformer, hall, "
                    "cooler, genset, electrolyser, turbine, charger, etc.",
    )
    label: str = Field(
        ..., min_length=1,
        description="Human-readable display label (shown in UI / GA legend)",
    )
    vendor: str | None = Field(
        None, description="Manufacturer name (Tesla, Sungrow, Hitachi, etc.)",
    )
    dimensions_m: Dimensions = Field(..., description="Physical bounding box")
    glb_path: str | None = Field(
        None,
        description="Relative path to GLTF mesh served by frontend — e.g. "
                    "'/models/assets/megapack_2xl.glb'",
    )
    fallback_geometry: Literal["box", "cylinder", "truss", "custom"] = Field(
        "box",
        description="Primitive geometry when no GLB is available",
    )
    parametric_rules: list[ParametricRule] = Field(
        default_factory=list,
        description="How many units per unit of driver capacity",
    )
    standards_cited: list[str] = Field(
        default_factory=list,
        description="BS / IEC / IEEE / ENA citations governing the asset",
    )
    material: str = Field(
        "steel",
        description="Dominant material (steel / concrete / GRP / aluminium)",
    )
    colour_hex: str = Field(
        "#808080",
        pattern=r"^#[0-9A-Fa-f]{6}$",
        description="Hex colour for twin rendering and GA legend",
    )
    fire_zone: bool = Field(
        False,
        description="If true, layout engine applies firebreak keep-out",
    )
    cni_grade: Literal["none", "B3", "C5", "SR1"] = Field(
        "none",
        description="Critical National Infrastructure security grade — "
                    "B3 / C5 = CPNI blast standards, SR1 = LPS 1175",
    )
    capacity_rating: dict | None = Field(
        None,
        description="Free-form rating — e.g. {'mw_ac': 2.0, 'mva': 2.5, "
                    "'kv_primary': 33, 'kv_secondary': 0.69}",
    )


# ---------------------------------------------------------------------------
# Convenience types used by the layout engine + twin router
# ---------------------------------------------------------------------------
class PlacedAsset(BaseModel):
    """An instance of a primitive placed on a site.

    Coordinates are metres relative to the site polygon centroid (i.e. the
    centroid sits at (0, 0, 0) in the local ENU frame). Rotation is in
    degrees counter-clockwise looking down the +Z axis. ``scale`` lets the
    renderer stretch a primitive where the catalogue dims can't express a
    continuous variant (data-centre hall length scales with MW_IT).
    """
    model_config = ConfigDict(extra="forbid")

    primitive_id: str = Field(..., description="References AssetPrimitive.id")
    xyz: tuple[float, float, float] = Field(
        ..., description="(east_m, north_m, up_m) from polygon centroid",
    )
    rotation_deg: float = Field(
        0.0,
        description="Counter-clockwise rotation about +Z (degrees)",
    )
    scale: tuple[float, float, float] = Field(
        (1.0, 1.0, 1.0),
        description="Non-uniform scale factor (x, y, z)",
    )
    metadata: dict | None = Field(
        None,
        description="Free-form per-instance metadata — e.g. {'row_index': 2, "
                    "'unit_index': 5, 'role': 'POC'}",
    )


class LayoutRequest(BaseModel):
    """Inbound body for ``POST /api/twin/layout``."""
    model_config = ConfigDict(extra="forbid")

    workload: Literal["bess", "solar", "wind", "dc", "ev", "h2"]
    params: dict = Field(
        default_factory=dict,
        description="Capacity driver dict — {mw_ac, mwh, duration_h, mw_it, "
                    "mwp, turbines, kg_day}. Engine reads the subset needed.",
    )
    site_polygon_wkt: str = Field(
        ...,
        description="Site boundary as WKT (either WGS84 or OSGB36 EPSG:27700). "
                    "The engine computes a centroid and lays out in metres.",
    )


class LayoutResponse(BaseModel):
    """Outbound body for ``POST /api/twin/layout``."""
    model_config = ConfigDict(extra="forbid")

    workload: str
    placed_assets: list[PlacedAsset]
    centroid_lonlat: tuple[float, float] | None = None
    centroid_osgb: tuple[float, float] | None = None
    bbox_m: tuple[float, float, float, float] | None = Field(
        None, description="(min_e, min_n, max_e, max_n) in metres from centroid",
    )
    counts: dict = Field(
        default_factory=dict, description="Primitive id -> count summary",
    )
    notes: list[str] = Field(default_factory=list)
