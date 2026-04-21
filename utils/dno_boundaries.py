"""
utils.dno_boundaries — DNO / IDNO / TO licence-area helpers.

Backs the map-filter overlay system (Task #19) and gives the rest of Princeps
a single place to answer:

    * which DNO is this point in?
    * which IDNOs sit inside licence-area X?
    * which DNOs does this line / cable route cross?

Data source is the PostGIS table ``dno_licence_areas`` seeded from
``app/fixtures/dno_licence_areas.geojson`` (see migration 0016).

All geometry is stored in EPSG:27700 (OSGB36 / British National Grid). These
helpers accept WGS84 inputs and transform at query time via ST_Transform, so
callers never have to reproject.

Async-only — every public function takes the asyncpg Pool that sits on
``app.state.pool`` and uses ``pool.acquire()``.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

log = logging.getLogger("princeps.dno_boundaries")

# Fixture lives next to the migration that creates the table.
_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "app" / "fixtures" / "dno_licence_areas.geojson"
)


# ─── Fixture loader (no DB — used at startup + by tests) ────────────────────

def load_geojson(as_of: date | str | None = None) -> dict[str, Any]:
    """
    Load the seed GeoJSON FeatureCollection, optionally filtering to features
    that were in force on ``as_of``.

    Parameters
    ----------
    as_of
        Optional ISO date string or datetime.date. When provided, features
        whose ``effective_from > as_of`` or ``effective_to <= as_of`` are
        dropped.

    Returns
    -------
    A dict in GeoJSON FeatureCollection shape. Raises FileNotFoundError if
    the fixture file is missing.
    """
    if not _FIXTURE_PATH.exists():
        raise FileNotFoundError(f"DNO licence-area fixture not found: {_FIXTURE_PATH}")

    with _FIXTURE_PATH.open("r", encoding="utf-8") as f:
        fc = json.load(f)

    if as_of is None:
        return fc

    # Normalise as_of → ISO string for lexical comparison (ISO dates sort).
    if isinstance(as_of, date):
        as_of_iso = as_of.isoformat()
    else:
        as_of_iso = str(as_of)

    kept: list[dict[str, Any]] = []
    for feat in fc.get("features", []):
        props = feat.get("properties", {}) or {}
        eff_from = props.get("effective_from") or "0001-01-01"
        eff_to   = props.get("effective_to")   # may be None = still in force
        if eff_from > as_of_iso:
            continue
        if eff_to and eff_to <= as_of_iso:
            continue
        kept.append(feat)

    return {
        "type": "FeatureCollection",
        "name": fc.get("name", "dno_licence_areas"),
        "crs":  fc.get("crs"),
        "meta": fc.get("meta"),
        "features": kept,
    }


# ─── DB helpers ─────────────────────────────────────────────────────────────

async def dno_for_point(pool, lng: float, lat: float) -> str | None:
    """
    Return the DNO slug whose licence area contains the WGS84 point
    (``lng``, ``lat``). Only rows with ``operator_class='DNO'`` are considered
    so that Transmission Owner overlays don't shadow the answer. Returns the
    most-specific (smallest) matching polygon so e.g. ``ukpn-lpn`` beats the
    parent ``ukpn`` if both happen to be seeded.

    Returns None when no licence area contains the point (offshore, outside
    GB & NI, or table unpopulated).
    """
    sql = """
        SELECT dno_slug
        FROM dno_licence_areas
        WHERE operator_class = 'DNO'
          AND (effective_to IS NULL OR effective_to > now()::date)
          AND ST_Contains(
                geom,
                ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
              )
        ORDER BY ST_Area(geom) ASC
        LIMIT 1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, lng, lat)
    return row["dno_slug"] if row else None


async def idnos_within(pool, dno_slug: str) -> list[dict[str, Any]]:
    """
    Return IDNO licence-area rows whose geometry is fully contained within the
    DNO (or DNO sub-region) identified by ``dno_slug``.

    Uses ST_Covers on the parent geometry — IDNO polygons that merely overlap
    the DNO (crossing a boundary) are excluded. Most UK IDNOs are embedded in
    a single host DNO so this is almost always safe.
    """
    sql = """
        WITH parent AS (
            SELECT geom
            FROM dno_licence_areas
            WHERE dno_slug = $1
              AND operator_class = 'DNO'
            LIMIT 1
        )
        SELECT
            i.dno_slug,
            i.display_name,
            i.licence_region,
            i.parent_slug,
            i.source,
            i.source_url,
            i.effective_from::text  AS effective_from,
            i.effective_to::text    AS effective_to
        FROM dno_licence_areas i, parent p
        WHERE i.operator_class = 'IDNO'
          AND ST_Covers(p.geom, i.geom)
        ORDER BY i.display_name
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, dno_slug)
    return [dict(r) for r in rows]


async def dno_crosses(pool, line_geom: str | dict) -> list[str]:
    """
    Given a line geometry (GeoJSON LineString dict OR WKT string, assumed
    WGS84 unless it already embeds an SRID), return the list of DNO slugs
    whose licence areas the line intersects.

    Useful for flagging grid-connection routes that cross DNO boundaries (a
    common Gate-2 headache).

    Parameters
    ----------
    line_geom
        * dict  — GeoJSON geometry (LineString / MultiLineString) in EPSG:4326.
        * str   — WKT or EWKT.

    Returns slugs in no particular order, deduplicated.
    """
    # Build a geometry expression that resolves in SQL.
    if isinstance(line_geom, dict):
        wkt_or_geojson = json.dumps(line_geom)
        geom_expr = "ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($1), 4326), 27700)"
    else:
        geom_expr = "ST_Transform(ST_GeomFromEWKT($1), 27700)"

    sql = f"""
        SELECT DISTINCT dno_slug
        FROM dno_licence_areas
        WHERE operator_class = 'DNO'
          AND ST_Intersects(geom, {geom_expr})
        ORDER BY dno_slug
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, wkt_or_geojson if isinstance(line_geom, dict) else line_geom)
    return [r["dno_slug"] for r in rows]


# ─── GeoJSON pull for map overlay endpoint ──────────────────────────────────

async def licence_areas_geojson(
    pool,
    as_of: date | str | None = None,
    simplify: float | None = 0.0005,
    operator_class: str | None = None,
) -> dict[str, Any]:
    """
    Pull licence-area polygons from PostGIS as a WGS84 GeoJSON
    FeatureCollection, ready to ship to the frontend.

    Parameters
    ----------
    as_of
        Optional ISO date / date — filter to rows in force on that date.
    simplify
        Optional ST_SimplifyPreserveTopology tolerance in degrees (WGS84).
        ``None`` disables simplification. Default 0.0005 ≈ 55 m, plenty for
        a GB-scale overlay.
    operator_class
        Optional filter: 'DNO' | 'IDNO' | 'TO'. None → all.
    """
    if as_of is None:
        as_of_sql = "now()::date"
        params: list[Any] = []
        param_idx = 1
    elif isinstance(as_of, date):
        as_of_sql = f"${1}::date"
        params = [as_of.isoformat()]
        param_idx = 2
    else:
        as_of_sql = f"${1}::date"
        params = [str(as_of)]
        param_idx = 2

    class_sql = ""
    if operator_class:
        class_sql = f" AND operator_class = ${param_idx}::operator_class "
        params.append(operator_class)
        param_idx += 1

    simplify_expr = "geom" if not simplify else f"ST_SimplifyPreserveTopology(geom, {float(simplify)})"
    # Transform to WGS84 for the browser.
    geom_wgs = f"ST_Transform({simplify_expr}, 4326)"

    sql = f"""
        SELECT
            dno_slug,
            operator_class::text                     AS operator_class,
            display_name,
            licence_region,
            parent_slug,
            effective_from::text                     AS effective_from,
            effective_to::text                       AS effective_to,
            source,
            source_url,
            note,
            ST_AsGeoJSON({geom_wgs})::json           AS geometry
        FROM dno_licence_areas
        WHERE (effective_from <= {as_of_sql})
          AND (effective_to IS NULL OR effective_to > {as_of_sql})
          {class_sql}
        ORDER BY operator_class, dno_slug
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": r["geometry"],
            "properties": {
                "dno_slug":       r["dno_slug"],
                "operator_class": r["operator_class"],
                "display_name":   r["display_name"],
                "licence_region": r["licence_region"],
                "parent_slug":    r["parent_slug"],
                "effective_from": r["effective_from"],
                "effective_to":   r["effective_to"],
                "source":         r["source"],
                "source_url":     r["source_url"],
                "note":           r["note"],
            },
        })

    return {
        "type": "FeatureCollection",
        "name": "dno_licence_areas",
        "features": features,
    }


async def dno_metadata(pool, slug: str) -> dict[str, Any] | None:
    """
    Return a dict with one DNO's metadata + its sub-regions (rows whose
    ``parent_slug = slug``). Returns None when the slug is unknown.
    """
    async with pool.acquire() as conn:
        head = await conn.fetchrow(
            """
            SELECT
                dno_slug,
                operator_class::text                     AS operator_class,
                display_name,
                licence_region,
                parent_slug,
                effective_from::text                     AS effective_from,
                effective_to::text                       AS effective_to,
                source,
                source_url,
                note
            FROM dno_licence_areas
            WHERE dno_slug = $1
            LIMIT 1
            """,
            slug,
        )
        if head is None:
            return None

        subs = await conn.fetch(
            """
            SELECT
                dno_slug,
                operator_class::text  AS operator_class,
                display_name,
                licence_region,
                effective_from::text  AS effective_from,
                effective_to::text    AS effective_to
            FROM dno_licence_areas
            WHERE parent_slug = $1
            ORDER BY display_name
            """,
            slug,
        )

    return {
        **dict(head),
        "sub_regions": [dict(s) for s in subs],
    }
