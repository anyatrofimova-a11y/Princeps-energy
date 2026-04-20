"""Buildable-area analysis.

Clips a parcel polygon against exclusion overlays (AONB, SSSI, flood zones, ALC
grades 1-2, slope, etc.) via PostGIS ST_Difference and returns the net buildable
hectares with a confidence band.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.analysis import Analysis, _utcnow, _truncate

log = logging.getLogger("princeps.analysis.buildable")

DEFAULT_BAND_PCT = 0.10


@dataclass
class BuildableFilters:
    """Which exclusion overlays to subtract."""

    exclude_aonb: bool = True
    exclude_sssi: bool = True
    exclude_flood_zone_3: bool = True
    exclude_alc_grade_1_2: bool = True
    slope_max_deg: float = 10.0
    max_distance_to_substation_km: float | None = None
    custom: list[str] = field(default_factory=list)

    def layer_names(self) -> list[str]:
        names: list[str] = list(self.custom)
        if self.exclude_aonb: names.append("aonb")
        if self.exclude_sssi: names.append("sssi")
        if self.exclude_flood_zone_3: names.append("flood3")
        if self.exclude_alc_grade_1_2: names.append("alc_1_2")
        return names


async def analyse_buildable(
    parcel_id: str,
    filters: BuildableFilters | None = None,
    *,
    pool=None,
) -> Analysis:
    """Net buildable hectares for a parcel after applying filters."""

    filters = filters or BuildableFilters()
    if pool is None:
        return _degraded(parcel_id, "no db pool")

    try:
        async with pool.acquire() as conn:
            parcel = await conn.fetchrow(
                """SELECT inspire_id, authority_name,
                          ST_Area(geom) / 10000.0 AS area_ha,
                          ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geom_geojson
                   FROM hmlr_inspire_parcels WHERE inspire_id = $1""",
                parcel_id,
            )
            if not parcel:
                return _degraded(parcel_id, "parcel not found")

            area_ha = float(parcel["area_ha"] or 0)
            if area_ha == 0:
                return _degraded(parcel_id, "parcel has zero area")

            exclusion_layers = filters.layer_names()
            excluded_ha = 0.0
            applied: list[dict] = []
            for layer in exclusion_layers:
                layer_area = await _overlap_ha(conn, parcel_id, layer)
                excluded_ha += layer_area
                applied.append({"layer": layer, "overlap_ha": layer_area})

            buildable_ha = max(0.0, area_ha - excluded_ha)
            band = buildable_ha * DEFAULT_BAND_PCT
            p10 = max(0.0, buildable_ha - band)
            p90 = buildable_ha + band

            explanation = _truncate(
                f"Parcel {parcel_id} ({area_ha:.1f} ha): subtracted {excluded_ha:.1f} ha "
                f"across {len(exclusion_layers)} exclusion layers "
                f"({', '.join(exclusion_layers) or 'none'}). "
                f"Net buildable {buildable_ha:.1f} ha."
            )
            confidence = 0.8 if applied else 0.5

            return Analysis(
                kind="buildable",
                target_key=f"parcel:{parcel_id}",
                value=buildable_ha,
                p10=p10,
                p50=buildable_ha,
                p90=p90,
                confidence=confidence,
                units="ha",
                explanation=explanation,
                provenance={
                    "tables": ["hmlr_inspire_parcels", "magic_constraints", "alc_grades"],
                    "parcel_id": parcel_id,
                    "area_ha": area_ha,
                    "exclusions_applied": applied,
                    "geometry": parcel["geom_geojson"],
                },
                computed_at=_utcnow(),
            )
    except Exception as e:  # noqa: BLE001
        log.exception("buildable analysis failed: %s", e)
        return _degraded(parcel_id, f"error: {type(e).__name__}")


async def _overlap_ha(conn, parcel_id: str, layer: str) -> float:
    """Return hectares of overlap between the parcel and a named MAGIC layer."""
    if layer in ("alc_1_2",):
        q = """
            SELECT COALESCE(SUM(ST_Area(ST_Intersection(p.geom, a.geom))) / 10000.0, 0)::float AS ha
            FROM hmlr_inspire_parcels p, alc_grades a
            WHERE p.inspire_id = $1 AND a.alc_grade IN ('1','2')
              AND ST_Intersects(p.geom, a.geom)
        """
    else:
        q = """
            SELECT COALESCE(SUM(ST_Area(ST_Intersection(p.geom, ST_Transform(m.geom::geometry, 27700))))
                   / 10000.0, 0)::float AS ha
            FROM hmlr_inspire_parcels p, magic_constraints m
            WHERE p.inspire_id = $1 AND m.source_layer = $2
              AND ST_Intersects(p.geom, ST_Transform(m.geom::geometry, 27700))
        """
    try:
        row = await conn.fetchrow(q, parcel_id, layer) if layer not in ("alc_1_2",) \
            else await conn.fetchrow(q, parcel_id)
        return float(row["ha"] or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def _degraded(parcel_id: str, reason: str) -> Analysis:
    return Analysis(
        kind="buildable",
        target_key=f"parcel:{parcel_id}",
        value=None,
        p10=None, p50=None, p90=None,
        confidence=0.0,
        units="ha",
        explanation=_truncate(f"buildable analysis unavailable: {reason}"),
        provenance={"error": reason},
        computed_at=_utcnow(),
    )
