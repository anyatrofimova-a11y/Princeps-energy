"""Buildable-area analysis — parcel minus protected designations.

If designation tables (AONB/SSSI/flood/ALC/etc) are empty or missing, returns a
low-confidence Analysis naming the upstream sources so BOT-G's ingest can be
tracked. Does not raise on missing data.
"""

from __future__ import annotations

import logging
from typing import Any

from app.analysis.types import (
    Analysis,
    ProvenanceEntry,
    Scenario,
    coerce_scenario,
    degraded,
    truncate,
    utcnow,
)

log = logging.getLogger("princeps.analysis.buildable_area")

DESIGNATION_LAYERS = [
    ("magic_constraints", "aonb", "AONB"),
    ("magic_constraints", "sssi", "SSSI"),
    ("magic_constraints", "nnr", "NNR"),
    ("magic_constraints", "sac", "SAC"),
    ("magic_constraints", "spa", "SPA"),
    ("magic_constraints", "ramsar", "Ramsar"),
    ("magic_constraints", "flood_zone_3", "Flood Zone 3"),
    ("magic_constraints", "flood_zone_2", "Flood Zone 2"),
    ("alc_grades", "1_2", "ALC grades 1 & 2"),
]


async def buildable_area(
    parcel: Any,
    scenario: str | Scenario = Scenario.CENTRAL,
    *,
    pool=None,
) -> Analysis:
    """Net buildable hectares for a parcel after subtracting protected designations."""

    parcel_id = _extract_id(parcel)
    scenario_e = coerce_scenario(scenario)
    target_key = f"parcel:{parcel_id}"

    if pool is None:
        return degraded("buildable_area", target_key, "no db pool", units="ha")

    prov: list[ProvenanceEntry] = []
    try:
        async with pool.acquire() as conn:
            parcel_row = await conn.fetchrow(
                """SELECT inspire_id, authority_name,
                          ST_Area(geom) / 10000.0 AS area_ha
                   FROM hmlr_inspire_parcels WHERE inspire_id = $1""",
                parcel_id,
            )
            if not parcel_row:
                prov.append(ProvenanceEntry(source="hmlr_inspire_parcels", kind="missing", detail=parcel_id))
                return degraded("buildable_area", target_key, "parcel not found", units="ha", provenance=prov)

            area_ha = float(parcel_row["area_ha"] or 0.0)
            prov.append(ProvenanceEntry(source="hmlr_inspire_parcels", kind="cached", detail=f"area={area_ha:.2f}ha"))
            if area_ha <= 0:
                return degraded("buildable_area", target_key, "zero-area parcel", units="ha", provenance=prov)

            layer_counts = await _count_designation_rows(conn, prov)
            any_designations = any(v > 0 for v in layer_counts.values())

            if not any_designations:
                missing = [name for _, _, name in DESIGNATION_LAYERS]
                explanation = truncate(
                    f"Parcel {parcel_id} area {area_ha:.1f} ha. "
                    f"Designation tables empty: {', '.join(missing)}. "
                    f"Returning parcel area with reduced confidence until BOT-G populates sources."
                )
                return Analysis(
                    value=area_ha,
                    p10=area_ha * 0.5,
                    p50=area_ha,
                    p90=area_ha,
                    confidence=0.2,
                    explanation=explanation,
                    provenance=prov + [ProvenanceEntry(
                        source="awaiting_designations", kind="missing",
                        detail="AONB, SSSI, flood zones, ALC 1-2 tables not populated",
                    )],
                    computed_utc=utcnow(),
                    kind="buildable_area",
                    target_key=target_key,
                    units="ha",
                )

            excluded_ha = 0.0
            applied: list[dict] = []
            for table, code, label in DESIGNATION_LAYERS:
                if layer_counts.get((table, code), 0) == 0:
                    continue
                ha = await _overlap_ha(conn, parcel_id, table, code)
                excluded_ha += ha
                applied.append({"layer": label, "overlap_ha": round(ha, 3)})
                prov.append(ProvenanceEntry(
                    source=f"{table}:{code}", kind="cached", detail=f"overlap={ha:.2f}ha",
                ))

            buildable_ha = max(0.0, area_ha - excluded_ha)
            band = max(buildable_ha * 0.10, 0.1)
            p10 = max(0.0, buildable_ha - band)
            p90 = buildable_ha + band
            confidence = 0.8 if applied else 0.5

            explanation = truncate(
                f"Parcel {parcel_id} ({area_ha:.1f} ha): subtracted {excluded_ha:.1f} ha across "
                f"{len(applied)} designation layers. Net buildable {buildable_ha:.1f} ha "
                f"(scenario={scenario_e.value})."
            )

            return Analysis(
                value=buildable_ha,
                p10=p10,
                p50=buildable_ha,
                p90=p90,
                confidence=confidence,
                explanation=explanation,
                provenance=prov,
                computed_utc=utcnow(),
                kind="buildable_area",
                target_key=target_key,
                units="ha",
            )
    except Exception as e:  # noqa: BLE001
        log.exception("buildable_area failed: %s", e)
        prov.append(ProvenanceEntry(source="buildable_area", kind="missing", detail=f"{type(e).__name__}: {e}"))
        return degraded("buildable_area", target_key, f"error {type(e).__name__}", units="ha", provenance=prov)


async def analyse_buildable_area(parcel_id: str, scenario: str = "central", *, pool=None) -> Analysis:
    return await buildable_area(parcel_id, scenario, pool=pool)


# ── Positive-buildable polygon ─────────────────────────────────────────────
#
# The legacy ``/api/design/buildable-mask`` endpoint returns a list of
# *restricted* polygons the frontend must subtract from a circular buffer.
# That was a workaround; the frontend shouldn't have to do geometry ops just
# to know where it can build. This companion function returns the BUILDABLE
# polygon directly (buffer minus each restriction) with honest provenance so
# callers can render it as a single fill layer.


async def positive_buildable_polygon(
    lat: float,
    lon: float,
    radius_m: float,
    *,
    pool=None,
    mask_payload: dict | None = None,
) -> dict:
    """Return the BUILDABLE polygon around (lat, lon) as a GeoJSON Feature.

    Starts from a circular buffer of ``radius_m`` metres and subtracts every
    restriction polygon in ``mask_payload['features']`` (classes starting with
    ``restricted_``). When shapely is available we do a real polygon
    difference; otherwise we fall back to a Polygon with inner rings (i.e.
    holes), which is what the frontend hook already understands.

    ``mask_payload`` can be supplied by the caller (when they've just fetched
    the mask) to avoid re-running the expensive GeeFlow composite.
    """
    from datetime import datetime as _dt
    import math as _m

    try:
        from shapely.geometry import Polygon as _Poly, mapping as _mapping, shape as _shape
        from shapely.ops import unary_union as _union
        _has_shapely = True
    except Exception:
        _has_shapely = False

    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * _m.cos(_m.radians(lat))
    segments = 64
    outer_ring: list[list[float]] = []
    for i in range(segments + 1):
        t = 2 * _m.pi * i / segments
        dlat = (radius_m * _m.sin(t)) / m_per_deg_lat
        dlon = (radius_m * _m.cos(t)) / m_per_deg_lon
        outer_ring.append([lon + dlon, lat + dlat])

    features = []
    warning = None
    if mask_payload and isinstance(mask_payload, dict):
        features = mask_payload.get("features") or []
        warning = mask_payload.get("warning")

    restricted_polys: list[list[list[float]]] = []
    for f in features:
        props = (f or {}).get("properties") or {}
        cls = str(props.get("class") or "")
        if not cls.startswith("restricted"):
            continue
        geom = (f or {}).get("geometry") or {}
        gtype = geom.get("type")
        if gtype == "Polygon":
            coords = geom.get("coordinates") or []
            if coords and coords[0] and len(coords[0]) >= 4:
                restricted_polys.append(coords[0])
        elif gtype == "MultiPolygon":
            for poly in geom.get("coordinates") or []:
                if poly and poly[0] and len(poly[0]) >= 4:
                    restricted_polys.append(poly[0])

    buildable_geom: dict
    buildable_area_ha: float
    if _has_shapely and restricted_polys:
        try:
            site = _Poly(outer_ring)
            restricted = _union([_Poly(r) for r in restricted_polys if len(r) >= 4])
            diff = site.difference(restricted)
            if diff.is_empty:
                buildable_geom = {"type": "Polygon", "coordinates": []}
                buildable_area_ha = 0.0
            else:
                buildable_geom = _mapping(diff)
                # approximate area in ha using equal-earth-ish projection
                buildable_area_ha = _approx_area_ha(buildable_geom, lat)
        except Exception as exc:
            warning = (warning or "") + f" shapely diff failed: {type(exc).__name__}"
            buildable_geom = {
                "type": "Polygon",
                "coordinates": [outer_ring, *restricted_polys],
            }
            buildable_area_ha = _approx_area_ha(buildable_geom, lat)
    else:
        # No shapely OR no restrictions — return polygon with holes (matches
        # the existing frontend fallback behaviour).
        rings = [outer_ring] + restricted_polys
        buildable_geom = {"type": "Polygon", "coordinates": rings}
        buildable_area_ha = _approx_area_ha(buildable_geom, lat)

    site_area_ha = _m.pi * (radius_m ** 2) / 10_000.0
    excluded_ha = max(0.0, site_area_ha - buildable_area_ha)

    reasons = []
    for f in features:
        props = (f or {}).get("properties") or {}
        if str(props.get("class") or "").startswith("restricted"):
            reasons.append({
                "class": props.get("class"),
                "reason": props.get("reason") or props.get("name") or "",
                "source": props.get("source") or "mask",
            })

    explanation = (
        f"Site buffer {site_area_ha:.1f} ha; subtracted {excluded_ha:.1f} ha across "
        f"{len(restricted_polys)} restricted polygon(s). "
        f"Net buildable {buildable_area_ha:.1f} ha."
    )
    if warning:
        explanation += f" Warning: {warning}."
    if not restricted_polys:
        explanation += (
            " No restrictions in mask — either area is genuinely clear or "
            "upstream constraint tables (MAGIC, EA flood, ALC, ancient woodland) "
            "have not yet been ingested for this area."
        )

    provenance = {
        "data_provenance": "mixed" if restricted_polys else (
            "synthetic_fallback" if warning else "osm"
        ),
        "last_refreshed_utc": _dt.utcnow().isoformat(timespec="seconds") + "Z",
        "reason": (
            "Built from /api/design/buildable-mask (GeeFlow composite + PostGIS "
            "constraint tables). Restriction geometry quality depends on which "
            "tables BOT-G has ingested."
        ),
    }
    if warning:
        provenance["warning"] = warning

    feature = {
        "type": "Feature",
        "geometry": buildable_geom,
        "properties": {
            "class": "buildable",
            "area_ha": round(buildable_area_ha, 3),
            "site_area_ha": round(site_area_ha, 3),
            "excluded_ha": round(excluded_ha, 3),
            "restriction_count": len(restricted_polys),
            "reasons": reasons,
        },
    }
    return {
        "type": "FeatureCollection",
        "features": [feature],
        "buildable_area_ha": round(buildable_area_ha, 3),
        "site_area_ha": round(site_area_ha, 3),
        "excluded_ha": round(excluded_ha, 3),
        "provenance": provenance,
        "explanation": explanation,
        "warning": warning,
    }


def _approx_area_ha(geom: dict, ref_lat: float) -> float:
    """Quick ha area using local equirectangular projection. Good to ~1% at UK
    latitudes for the scales we care about (< 5 km radius)."""
    import math as _m
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * _m.cos(_m.radians(ref_lat))

    def _ring_area_m2(ring: list[list[float]]) -> float:
        if len(ring) < 4:
            return 0.0
        a = 0.0
        for i in range(len(ring) - 1):
            x1 = ring[i][0] * m_per_deg_lon
            y1 = ring[i][1] * m_per_deg_lat
            x2 = ring[i + 1][0] * m_per_deg_lon
            y2 = ring[i + 1][1] * m_per_deg_lat
            a += x1 * y2 - x2 * y1
        return abs(a) / 2.0

    total = 0.0
    gtype = geom.get("type")
    if gtype == "Polygon":
        rings = geom.get("coordinates") or []
        if rings:
            total = _ring_area_m2(rings[0])
            for hole in rings[1:]:
                total -= _ring_area_m2(hole)
    elif gtype == "MultiPolygon":
        for poly in geom.get("coordinates") or []:
            if not poly:
                continue
            outer = _ring_area_m2(poly[0])
            holes = sum(_ring_area_m2(h) for h in poly[1:])
            total += max(0.0, outer - holes)
    return max(0.0, total) / 10_000.0


# ── internals ────────────────────────────────────────────────────────────

def _extract_id(parcel: Any) -> str:
    if isinstance(parcel, str):
        return parcel
    for attr in ("inspire_id", "id"):
        v = getattr(parcel, attr, None)
        if v:
            return str(v)
    data = getattr(parcel, "data", None)
    if isinstance(data, dict):
        for k in ("inspire_id", "parcel_id", "id"):
            if data.get(k):
                return str(data[k])
    raise ValueError("cannot extract parcel id")


async def _count_designation_rows(conn, prov: list[ProvenanceEntry]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    try:
        mc = await conn.fetch(
            "SELECT source_layer, COUNT(*)::int AS n FROM magic_constraints GROUP BY source_layer"
        )
        layers = {r["source_layer"]: r["n"] for r in mc}
        for table, code, _label in DESIGNATION_LAYERS:
            if table == "magic_constraints":
                counts[(table, code)] = int(layers.get(code, 0))
    except Exception as e:  # noqa: BLE001
        prov.append(ProvenanceEntry(source="magic_constraints", kind="missing", detail=str(e)[:80]))
    try:
        row = await conn.fetchrow(
            "SELECT COUNT(*)::int AS n FROM alc_grades WHERE alc_grade IN ('1','2')"
        )
        counts[("alc_grades", "1_2")] = int(row["n"] or 0) if row else 0
    except Exception as e:  # noqa: BLE001
        prov.append(ProvenanceEntry(source="alc_grades", kind="missing", detail=str(e)[:80]))
    return counts


async def _overlap_ha(conn, parcel_id: str, table: str, code: str) -> float:
    try:
        if table == "alc_grades":
            q = """
                SELECT COALESCE(SUM(ST_Area(ST_Intersection(p.geom, a.geom))) / 10000.0, 0)::float AS ha
                FROM hmlr_inspire_parcels p, alc_grades a
                WHERE p.inspire_id = $1 AND a.alc_grade IN ('1','2')
                  AND ST_Intersects(p.geom, a.geom)
            """
            row = await conn.fetchrow(q, parcel_id)
        else:
            q = """
                SELECT COALESCE(SUM(ST_Area(ST_Intersection(p.geom,
                       ST_Transform(m.geom::geometry, 27700)))) / 10000.0, 0)::float AS ha
                FROM hmlr_inspire_parcels p, magic_constraints m
                WHERE p.inspire_id = $1 AND m.source_layer = $2
                  AND ST_Intersects(p.geom, ST_Transform(m.geom::geometry, 27700))
            """
            row = await conn.fetchrow(q, parcel_id, code)
        return float(row["ha"] or 0.0) if row else 0.0
    except Exception:  # noqa: BLE001
        return 0.0
