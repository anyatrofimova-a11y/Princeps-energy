"""Entity resolution across LTDS / NOA / CSNP / NSIP / LPA / S37 / RIIO sources.

Problem: the same physical substation is referred to by different names in
different sources. Examples:

    LTDS:  "Bramley 400kV"
    NOA:   "Bramley Substation Reinforcement — 400kV 3rd SGT"
    NSIP:  "Bramley North Substation Extension"
    LPA:   "Extension to existing Bramley 400kV substation"

We need one canonical project id per physical site.

Strategy
--------
1. Normalise the site name: strip voltage suffixes, SGT counts, "substation",
   "extension", punctuation, case.
2. rapidfuzz token_set_ratio + partial_ratio on normalised name — threshold
   0.85 by default.
3. Geo-proximity as a tiebreaker + a boost — if two candidates are within
   500 m of each other (via `grid_substations` coordinates joined by name
   match) we consider them the same site with high confidence.
4. Confidence score combines the name similarity + geo proximity + source
   overlap strength.

The resolver can operate in two modes:
* **pure-name** — no DB access, just fuzzy match across a list of
  SubstationProject instances. Fastest path; good enough when LTDS provides
  authoritative name.
* **with-db**   — an asyncpg pool is supplied and we query `grid_substations`
  to enrich with known OSGB coordinates, boosting confidence.
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .schema import SubstationProject

log = logging.getLogger("princeps.substation_tracker.resolver")


# ---------------------------------------------------------------------------
# Dependency guard — rapidfuzz is optional; we degrade to python's difflib
# when it is unavailable (test env on minimal Python 3.14 venv).
# ---------------------------------------------------------------------------
try:
    from rapidfuzz.fuzz import token_set_ratio, partial_ratio  # type: ignore
    _HAS_RAPIDFUZZ = True
except ImportError:  # pragma: no cover
    from difflib import SequenceMatcher

    def token_set_ratio(a: str, b: str) -> float:
        return 100 * SequenceMatcher(None, a, b).ratio()

    def partial_ratio(a: str, b: str) -> float:
        return 100 * SequenceMatcher(None, a, b).ratio()

    _HAS_RAPIDFUZZ = False


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------
_TRAIL_STRIP = (
    "substation", "sub station", "switching station", "switching",
    "extension", "reinforcement", "replacement", "new build", "new",
    "upgrade", "uprate", "works", "project", "scheme",
    "400kv", "275kv", "132kv", "66kv", "33kv", "11kv",
    "400/132", "275/132", "132/33", "400 kv", "275 kv", "132 kv",
    "sgt", "grid supply point", "gsp", "bsp", "primary", "bulk supply point",
)
_PUNCT_RE = re.compile(r"[\-_/,.&()]+")
_WS_RE = re.compile(r"\s+")


def normalise_name(raw: str) -> str:
    """Aggressive normalisation — lowercase, drop qualifiers, collapse whitespace."""
    if not raw:
        return ""
    s = raw.lower()
    s = _PUNCT_RE.sub(" ", s)
    # Order matters — drop the longest qualifier first.
    for token in sorted(_TRAIL_STRIP, key=len, reverse=True):
        s = s.replace(token, " ")
    s = re.sub(r"\b\d{1,3}\s*kv\b", " ", s)
    s = re.sub(r"\b\d+\s*(mva|mw)\b", " ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


# ---------------------------------------------------------------------------
# Geo helper
# ---------------------------------------------------------------------------
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _coords_from_wkt(wkt: str | None) -> tuple[float, float] | None:
    if not wkt:
        return None
    m = re.match(r"POINT\s*\(\s*([-0-9.]+)\s+([-0-9.]+)\s*\)", wkt, re.I)
    if not m:
        return None
    return float(m.group(2)), float(m.group(1))  # (lat, lon)


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------
@dataclass
class ResolvedMatch:
    """One deduplicated substation — cluster of source records."""

    project_id: str
    canonical: SubstationProject   # the chosen canonical record
    members: list[SubstationProject] = field(default_factory=list)
    confidence: float = 0.0
    match_reasons: list[str] = field(default_factory=list)


class EntityResolver:
    """Fuzzy-matches SubstationProject records across sources.

    Usage:

        resolver = EntityResolver(name_threshold=85, geo_threshold_m=500)
        # Optional: hydrate DB coords for a set of names
        await resolver.hydrate_from_pool(pool, [r.substation_name for r in records])
        matches = resolver.resolve(records)

    The resolver is safe to re-use across batches.
    """

    def __init__(
        self,
        name_threshold: float = 85.0,
        geo_threshold_m: float = 500.0,
    ) -> None:
        self.name_threshold = name_threshold
        self.geo_threshold_m = geo_threshold_m
        # name → (lat, lon) map from grid_substations
        self._known_coords: dict[str, tuple[float, float]] = {}

    # ------------------------------------------------------------------
    async def hydrate_from_pool(self, pool, names: Iterable[str]) -> int:
        """Enrich known-name → coords lookup from PostGIS `grid_substations`.

        This lets the geo tiebreaker fire for rows that carry no coords of
        their own (most LTDS + NOA records).
        """
        uniq_names = {n for n in names if n}
        if not uniq_names:
            return 0
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT name,
                           ST_X(ST_Transform(geom, 4326)) AS lon,
                           ST_Y(ST_Transform(geom, 4326)) AS lat
                    FROM grid_substations
                    WHERE geom IS NOT NULL
                      AND name = ANY($1::text[])
                    """,
                    list(uniq_names),
                )
        except Exception as exc:
            log.warning("hydrate_from_pool failed (DB may not have grid_substations): %s", exc)
            return 0

        for r in rows:
            name = r["name"]
            if r["lat"] is not None and r["lon"] is not None:
                self._known_coords[normalise_name(name)] = (float(r["lat"]), float(r["lon"]))
        log.info("EntityResolver hydrated %d known coords", len(self._known_coords))
        return len(self._known_coords)

    # ------------------------------------------------------------------
    def resolve(self, records: Sequence[SubstationProject]) -> list[ResolvedMatch]:
        """Cluster a list of SubstationProject records by canonical site.

        Complexity: O(N*K) where K is avg cluster count — fine for the
        600-900 UK substation scale.
        """
        clusters: list[ResolvedMatch] = []

        for rec in records:
            placed = False
            rec_norm = normalise_name(rec.substation_name)
            rec_coord = self._coord_for(rec, rec_norm)
            for cluster in clusters:
                if self._same_entity(rec, rec_norm, rec_coord, cluster):
                    cluster.members.append(rec)
                    # Rescore confidence on growth.
                    cluster.confidence = max(cluster.confidence, rec.confidence)
                    placed = True
                    break
            if not placed:
                # Start a new cluster with this record as canonical.
                clusters.append(ResolvedMatch(
                    project_id=rec.project_id,
                    canonical=rec,
                    members=[rec],
                    confidence=rec.confidence,
                    match_reasons=["new_cluster"],
                ))

        # Second pass — pick the best canonical per cluster (prefer LTDS > RIIO > NOA > CSNP > NSIP > LPA > S37 > OFTO).
        for cluster in clusters:
            cluster.canonical = _pick_canonical(cluster.members)
            cluster.project_id = cluster.canonical.project_id
            cluster.confidence = _score_cluster(cluster.members)

        log.info("EntityResolver: %d input records → %d canonical clusters", len(records), len(clusters))
        return clusters

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _coord_for(self, rec: SubstationProject, rec_norm: str) -> tuple[float, float] | None:
        """Best available (lat, lon) for this record."""
        if rec.geom_wkt:
            c = _coords_from_wkt(rec.geom_wkt)
            if c:
                return c
        # Fall back to the hydrated DB map.
        return self._known_coords.get(rec_norm)

    def _same_entity(
        self,
        rec: SubstationProject,
        rec_norm: str,
        rec_coord: tuple[float, float] | None,
        cluster: ResolvedMatch,
    ) -> bool:
        """Decide whether `rec` belongs in `cluster`."""
        # 1. Same developer is not required — TOs sometimes appear in DNO
        #    LTDS as supply points. But if two records from different
        #    developers match by name, require geo proximity.
        any_member_matches = False
        for member in cluster.members:
            mnorm = normalise_name(member.substation_name)
            tsr = token_set_ratio(rec_norm, mnorm)
            pr = partial_ratio(rec_norm, mnorm)
            if tsr >= self.name_threshold or pr >= self.name_threshold + 5:
                any_member_matches = True
                if rec.developer == member.developer:
                    cluster.match_reasons.append(f"name:{tsr:.0f}/developer:{rec.developer}")
                    return True
                # Cross-developer — require geo proximity.
                m_coord = self._coord_for(member, mnorm)
                if rec_coord and m_coord:
                    d = haversine_m(rec_coord[0], rec_coord[1], m_coord[0], m_coord[1])
                    if d <= self.geo_threshold_m:
                        cluster.match_reasons.append(f"name:{tsr:.0f}/geo:{d:.0f}m")
                        return True
        # 2. Strong geo-only match (names differ significantly but coords co-locate)
        if rec_coord and any_member_matches is False:
            for member in cluster.members:
                mnorm = normalise_name(member.substation_name)
                m_coord = self._coord_for(member, mnorm)
                if m_coord:
                    d = haversine_m(rec_coord[0], rec_coord[1], m_coord[0], m_coord[1])
                    if d <= self.geo_threshold_m / 4:  # tight threshold for pure geo
                        cluster.match_reasons.append(f"geo-tight:{d:.0f}m")
                        return True
        return False


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------
_SOURCE_PREF_ORDER = ("LTDS", "RIIO_ED", "RIIO_ET", "NOA", "CSNP", "NSIP_DCO", "LPA", "S37", "OFTO", "RFP")


def _pick_canonical(members: Sequence[SubstationProject]) -> SubstationProject:
    """Pick the best source record to be canonical for a cluster."""
    if not members:
        raise ValueError("_pick_canonical called with empty members")
    def rank(m: SubstationProject) -> tuple[int, float]:
        try:
            pref = _SOURCE_PREF_ORDER.index(m.source_type)
        except ValueError:
            pref = len(_SOURCE_PREF_ORDER)
        return (pref, -m.confidence)
    return sorted(members, key=rank)[0]


def _score_cluster(members: Sequence[SubstationProject]) -> float:
    """Confidence 0-1 of the cluster.

    Heuristic: base = max member confidence. Bonus +0.1 per additional source
    type (multi-source triangulation). Capped at 1.0.
    """
    if not members:
        return 0.0
    base = max(m.confidence for m in members)
    source_count = len({m.source_type for m in members})
    bonus = 0.1 * max(0, source_count - 1)
    return min(1.0, base + bonus)
