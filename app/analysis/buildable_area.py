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
