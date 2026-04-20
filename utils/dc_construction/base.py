"""
Base types for data centre construction-layer engineering primitives.

Every concrete asset (shell, cooling, substation, cables, roads, fence,
gensets, UPS) inherits from `ConstructionAsset`. The shape is deliberately
thin — dimensions, area/volume, CapEx/OpEx, and a list of standards
citations — so the composer can stitch assets together into a single
`DcConstructionSpec` that the frontend drawer renders in its Spec / Cost /
Standards tabs.

Naming & units:
    * SI throughout (metres, kg, W, V, A, m³).
    * Currency is Great British Pounds (£) — 2025 delivered tender rates,
      capacity-weighted indices from DBEI construction cost data and
      RICS BCIS. Figures are engineer-scale, not audit-grade.
    * Every "magic number" emitted at the field level carries a
      `StandardCitation` so the drawer can show the provenance tooltip
      the task explicitly requires.

Standards referenced across the package (the central list):
    EN 50600-1, EN 50600-2-1, EN 50600-2-2, EN 50600-2-3,
    EN 50600-2-4, EN 50600-2-5, EN 50600-2-6 — data centre facilities
    and infrastructures (general, building construction, power,
    environmental, telecom cabling, security, DCIM).
    BS 7671:2018+A2:2022 — IET Wiring Regulations, cable sizing.
    BS 9991:2015 — Fire safety in residential and mixed-use,
    referenced for compartmentation of IT halls in mixed occupancy.
    BS 9999:2017 — Fire safety code of practice for the design,
    management and use of buildings, applied to HGV-accessible DC
    access roads and fire appliance turning heads.
    BS EN 1991-1-1 (Eurocode 1) — imposed loads incl. server rack load.
    Approved Document Part B — Fire safety.
    Approved Document Part L (2021) — Conservation of fuel and power
    (thermal envelope, air permeability ≤ 5 m³/(h·m²)).
    ISO 8528-1:2018 — Reciprocating IC engine-driven AC generating sets,
    performance ratings: COP, PRP, LTP, ESP.
    EU Stage V — Non-road mobile machinery emissions (for gensets).
    IEEE C37.119-2016 — Guide for breaker failure protection (the
    numbered-standard the task asks for — 37.119 belongs to the
    C37.x relay protection family).
    Uptime Institute — Tier Standard: Topology (Tier 1..4).
    LPS 1175 — Loss Prevention Standard for perimeter security,
    ratings A1..H20.
    CIBSE Guide F — Energy efficiency in buildings (chiller selection).
    ASHRAE TC 9.9 — Thermal guidelines for data processing environments.
    The Green Grid WUE — Water Usage Effectiveness (m³ / MWh IT).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Citation primitive
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StandardCitation:
    """A citation the frontend can render as a tooltip on any numeric field."""
    standard: str          # e.g. "EN 50600-2-2:2019"
    clause: str            # e.g. "§ 7.3.2 Distribution redundancy"
    note: str = ""         # plain-English paraphrase
    url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"standard": self.standard, "clause": self.clause,
                "note": self.note, "url": self.url}


def cite(standard: str, clause: str = "", note: str = "",
         url: Optional[str] = None) -> StandardCitation:
    return StandardCitation(standard=standard, clause=clause, note=note, url=url)


# ---------------------------------------------------------------------------
# Field wrapper: a number with its citation and unit
# ---------------------------------------------------------------------------


@dataclass
class CitedValue:
    """A value paired with the standard that dictates it."""
    value: Any
    unit: str = ""
    citation: Optional[StandardCitation] = None
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "citation": self.citation.to_dict() if self.citation else None,
            "note": self.note,
        }


def cv(value: Any, unit: str = "",
       citation: Optional[StandardCitation] = None,
       note: str = "") -> CitedValue:
    return CitedValue(value=value, unit=unit, citation=citation, note=note)


# ---------------------------------------------------------------------------
# Base asset
# ---------------------------------------------------------------------------


@dataclass
class ConstructionAsset:
    """Root of the type hierarchy. Every construction-layer object inherits
    this envelope so the composer + router can treat them uniformly."""
    type: str                              # "shell" | "cooling" | …
    label: str                             # human-readable name
    dimensions: Dict[str, float] = field(default_factory=dict)   # m, m, m
    area_m2: float = 0.0
    volume_m3: float = 0.0
    capex_gbp: float = 0.0
    opex_gbp_per_yr: float = 0.0
    standards_citations: List[StandardCitation] = field(default_factory=list)
    provenance: str = ""                   # short free-text: "EN 50600-2-2 + UK rates"
    spec: Dict[str, CitedValue] = field(default_factory=dict)   # engineering fields
    notes: List[str] = field(default_factory=list)

    def add_cite(self, citation: StandardCitation) -> "ConstructionAsset":
        if citation not in self.standards_citations:
            self.standards_citations.append(citation)
        return self

    def set(self, key: str, value: CitedValue) -> "ConstructionAsset":
        self.spec[key] = value
        if value.citation is not None:
            self.add_cite(value.citation)
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "dimensions": self.dimensions,
            "area_m2": round(self.area_m2, 2),
            "volume_m3": round(self.volume_m3, 2),
            "capex_gbp": round(self.capex_gbp, 0),
            "opex_gbp_per_yr": round(self.opex_gbp_per_yr, 0),
            "standards_citations": [c.to_dict() for c in self.standards_citations],
            "provenance": self.provenance,
            "spec": {k: v.to_dict() for k, v in self.spec.items()},
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Full spec envelope
# ---------------------------------------------------------------------------


@dataclass
class DcConstructionSpec:
    project_id: str
    it_load_mw: float
    tier: int                              # Uptime Institute 1..4
    redundancy: str                        # "N" | "N+1" | "2N" | "2N+1"
    cooling_type: str                      # "mechanical" | "hybrid" | …
    assets: Dict[str, ConstructionAsset] = field(default_factory=dict)
    totals: Dict[str, float] = field(default_factory=dict)
    standards_index: List[StandardCitation] = field(default_factory=list)

    def add(self, key: str, asset: ConstructionAsset) -> None:
        self.assets[key] = asset
        for c in asset.standards_citations:
            if c not in self.standards_index:
                self.standards_index.append(c)

    def recompute_totals(self) -> None:
        self.totals = {
            "capex_gbp": round(sum(a.capex_gbp for a in self.assets.values()), 0),
            "opex_gbp_per_yr": round(sum(a.opex_gbp_per_yr for a in self.assets.values()), 0),
            "footprint_m2": round(sum(a.area_m2 for a in self.assets.values()), 1),
            "asset_count": len(self.assets),
        }

    def to_dict(self) -> Dict[str, Any]:
        self.recompute_totals()
        return {
            "project_id": self.project_id,
            "it_load_mw": self.it_load_mw,
            "tier": self.tier,
            "redundancy": self.redundancy,
            "cooling_type": self.cooling_type,
            "assets": {k: a.to_dict() for k, a in self.assets.items()},
            "totals": self.totals,
            "standards_index": [c.to_dict() for c in self.standards_index],
        }
