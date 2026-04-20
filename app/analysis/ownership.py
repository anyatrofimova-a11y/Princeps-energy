"""Ownership analysis — Land Registry adjacency + price-paid cluster signal.

Returns a confidence-weighted ownership clarity score (0-1) and adjacency
signals. If source data is thin, returns reduced confidence with an honest
explanation instead of crashing.
"""

from __future__ import annotations

import logging
from typing import Any

from app.analysis.types import (
    Analysis,
    ProvenanceEntry,
    degraded,
    truncate,
    utcnow,
)

log = logging.getLogger("princeps.analysis.ownership")

ADJACENCY_RADIUS_M = 200.0
CLUSTER_RADIUS_M = 500.0


async def ownership(parcel: Any, *, pool=None) -> Analysis:
    """Ownership-clarity score for a parcel.

    Signal mix:
      - parcel found in HMLR INSPIRE (baseline)
      - adjacent parcels sharing authority (aggregation potential)
      - price-paid clustering nearby (active transaction neighbourhood)
    """

    parcel_id = _extract_id(parcel)
    target_key = f"parcel:{parcel_id}"

    if pool is None:
        return degraded("ownership", target_key, "no db pool", units="score")

    prov: list[ProvenanceEntry] = []
    try:
        async with pool.acquire() as conn:
            parcel_row = await conn.fetchrow(
                """SELECT inspire_id, authority_name,
                          ST_Area(geom) / 10000.0 AS area_ha,
                          ST_Centroid(geom) AS centroid
                   FROM hmlr_inspire_parcels WHERE inspire_id = $1""",
                parcel_id,
            )
            if not parcel_row:
                prov.append(ProvenanceEntry(source="hmlr_inspire_parcels", kind="missing", detail=parcel_id))
                return degraded("ownership", target_key, "parcel not found", units="score", provenance=prov)

            authority = parcel_row["authority_name"]
            area_ha = float(parcel_row["area_ha"] or 0.0)
            prov.append(ProvenanceEntry(
                source="hmlr_inspire_parcels", kind="cached",
                detail=f"authority={authority} area={area_ha:.1f}ha",
            ))

            adj_n, adj_same = await _adjacency(conn, parcel_id, authority, prov)
            pp_n = await _price_paid_cluster(conn, parcel_id, prov)
            ccod_hit = await _ccod_lookup(conn, parcel_id, prov)

            clarity = 0.4  # baseline: parcel exists in HMLR
            signals: list[str] = [f"HMLR: {authority or 'unknown authority'}"]
            if adj_n > 0:
                clarity += 0.15
                signals.append(f"{adj_n} adjacent parcel(s)")
            if adj_same > 0 and adj_n > 0:
                clarity += 0.10 * min(1.0, adj_same / max(adj_n, 1))
                signals.append(f"{adj_same} share authority")
            if pp_n > 0:
                clarity += 0.10
                signals.append(f"{pp_n} price-paid transactions nearby")
            if ccod_hit:
                clarity += 0.20
                signals.append("CCOD corporate owner match")

            clarity = min(1.0, clarity)
            thin = adj_n == 0 and pp_n == 0 and not ccod_hit
            confidence = 0.3 if thin else min(0.9, 0.5 + 0.1 * (adj_n > 0) + 0.15 * (pp_n > 0) + 0.15 * (ccod_hit))

            explanation = truncate(
                f"Parcel {parcel_id} ({area_ha:.1f} ha, {authority or 'no authority'}): "
                f"clarity {clarity:.2f}. Signals: {'; '.join(signals)}. "
                + ("Source data thin; increase confidence once CCOD + price-paid ingests land." if thin else "")
            )

            return Analysis(
                value=clarity,
                p10=max(0.0, clarity - 0.15),
                p50=clarity,
                p90=min(1.0, clarity + 0.10),
                confidence=confidence,
                explanation=explanation,
                provenance=prov,
                computed_utc=utcnow(),
                kind="ownership",
                target_key=target_key,
                units="score",
            )
    except Exception as e:  # noqa: BLE001
        log.exception("ownership failed: %s", e)
        prov.append(ProvenanceEntry(source="ownership", kind="missing", detail=f"{type(e).__name__}: {e}"))
        return degraded("ownership", target_key, f"error {type(e).__name__}", units="score", provenance=prov)


async def analyse_ownership(parcel_id: str, *, pool=None) -> Analysis:
    return await ownership(parcel_id, pool=pool)


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


async def _adjacency(conn, parcel_id: str, authority: str | None, prov: list[ProvenanceEntry]) -> tuple[int, int]:
    try:
        row = await conn.fetchrow(
            """SELECT COUNT(*)::int AS n,
                      COUNT(*) FILTER (WHERE q.authority_name = $2)::int AS same
               FROM hmlr_inspire_parcels p, hmlr_inspire_parcels q
               WHERE p.inspire_id = $1 AND q.inspire_id <> $1
                 AND ST_DWithin(p.geom, q.geom, $3)""",
            parcel_id, authority, ADJACENCY_RADIUS_M,
        )
        n = int(row["n"] or 0) if row else 0
        same = int(row["same"] or 0) if row else 0
        prov.append(ProvenanceEntry(
            source="hmlr_inspire_parcels:adjacency", kind="cached",
            detail=f"within {ADJACENCY_RADIUS_M:.0f}m: n={n} same_authority={same}",
        ))
        return n, same
    except Exception as e:  # noqa: BLE001
        prov.append(ProvenanceEntry(source="hmlr_inspire_parcels:adjacency", kind="missing", detail=str(e)[:80]))
        return 0, 0


async def _price_paid_cluster(conn, parcel_id: str, prov: list[ProvenanceEntry]) -> int:
    try:
        row = await conn.fetchrow(
            """SELECT COUNT(*)::int AS n
               FROM hmlr_price_paid pp, hmlr_inspire_parcels p
               WHERE p.inspire_id = $1
                 AND ST_DWithin(pp.geom, p.geom, $2)""",
            parcel_id, CLUSTER_RADIUS_M,
        )
        n = int(row["n"] or 0) if row else 0
        prov.append(ProvenanceEntry(
            source="hmlr_price_paid", kind="cached",
            detail=f"within {CLUSTER_RADIUS_M:.0f}m: n={n}",
        ))
        return n
    except Exception as e:  # noqa: BLE001
        prov.append(ProvenanceEntry(source="hmlr_price_paid", kind="missing", detail=str(e)[:80]))
        return 0


async def _ccod_lookup(conn, parcel_id: str, prov: list[ProvenanceEntry]) -> bool:
    try:
        row = await conn.fetchrow(
            """SELECT 1 FROM hmlr_ccod c, hmlr_inspire_parcels p
               WHERE p.inspire_id = $1 AND c.title_number = p.title_number LIMIT 1""",
            parcel_id,
        )
        hit = bool(row)
        prov.append(ProvenanceEntry(
            source="hmlr_ccod", kind="cached" if hit else "missing",
            detail="match" if hit else "no match",
        ))
        return hit
    except Exception as e:  # noqa: BLE001
        prov.append(ProvenanceEntry(source="hmlr_ccod", kind="missing", detail=str(e)[:80]))
        return False
