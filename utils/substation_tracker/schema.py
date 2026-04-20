"""30-field canonical SubstationProject schema — the UK reference schema for
a substation project record, with UK-specific field conventions (OSGB 27700
coordinates, GBP, RIIO price base years, DNO/TO licensee terminology).

Scope: 600–900 substation projects across the 3 transmission owners
(NGET, SPT, SHE-T) and 6 DNO licensees (UKPN, SSEN, SPEN, NGED, NPG, ENWL),
sourced from LTDS / RIIO BPs / NESO NOA+CSNP / PINS NSIP / DESNZ S37 / OFTO
tender packs / LPA (via PlanIt).

Note on UK vs US column deltas
------------------------------
* US "utility" → UK "developer" (licensee brand, e.g. "UKPN", "SPT")
* US "state" → UK "country" (England/Wales/Scotland/NI)
* Lat/lng → OSGB easting/northing + WGS84 WKT (both carried for round-trip)
* Capex is GBP millions, tagged with RIIO price base year (usually 18/19)
* "Docket" concept → UK equivalents: RIIO CV cost ID, NOA project code, NSIP
  PINS reference, S37 DESNZ ref, LPA planning application number.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Literal enums (kept as Literal types for Pydantic + easy JSON round-trip)
# ---------------------------------------------------------------------------
StationType = Literal["substation", "switching_station"]

UpgradeType = Literal["new", "upgrade", "replacement", "unknown"]

Country = Literal["England", "Wales", "Scotland", "Northern Ireland"]

ConstructionStatus = Literal[
    "planned",
    "under_construction",
    "complete",
    "cancelled",
    "deferred",
    "unknown",
]

SourceType = Literal[
    "LTDS",        # DNO Long Term Development Statement (annual, Nov)
    "NOA",         # NESO Network Options Assessment
    "CSNP",        # NESO Centralised Strategic Network Plan
    "RIIO_ET",     # Ofgem RIIO-ET2/T3 business plan + CV cost matrix
    "RIIO_ED",     # Ofgem RIIO-ED2 DNO business plan + CV cost matrix
    "NSIP_DCO",    # PINS National Infrastructure Planning register
    "LPA",         # Local Planning Authority (PlanIt / Council portals)
    "S37",         # DESNZ S37 Electricity Act overhead-line + substation consents
    "OFTO",        # Offshore Transmission Owner tender packs (Ofgem)
    "RFP",         # Ad hoc tender / RFP package
]


# ---------------------------------------------------------------------------
# Canonical 30-field record
# ---------------------------------------------------------------------------
class SubstationProject(BaseModel):
    """The 30 fields of canonical parity + UK specifics.

    Every parser produces instances of this type. The entity resolver consumes
    a list of these and emits one deduplicated row per canonical `project_id`.
    """

    # ── Identity (3 fields) ────────────────────────────────────────────────
    project_id: str = Field(
        ...,
        description=("Canonical Princeps ID. "
                     "Scheme: SUB-<dno_or_to>-<slug>-<yr> "
                     "e.g. SUB-UKPN-BRAMLEY-2028"),
    )
    external_ids: dict[str, str] = Field(
        default_factory=dict,
        description=("Map of source_type → source-internal id. "
                     "Keys: ltds, noa, csnp, nsip, lpa, s37, riio_cv, ofto."),
    )
    substation_name: str

    # ── Project context (3 fields) ─────────────────────────────────────────
    station_type: StationType = "substation"
    parent_project: str | None = Field(
        None, description='E.g. "Energy Gateway", "EGL1", "Beauly-Denny".',
    )
    project_description: str | None = None

    upgrade_or_new: UpgradeType = "unknown"

    # ── Location (7 fields) ────────────────────────────────────────────────
    region: str = Field(
        ..., description=("TO zone (e.g. 'NGET-South') or DNO licence area "
                          "(e.g. 'EPN', 'SPN', 'LPN' for UKPN)."),
    )
    lpa: str | None = Field(
        None, description="Local Planning Authority name if known.",
    )
    county: str | None = None
    country: Country = "England"
    geom_wkt: str | None = Field(
        None,
        description=("POINT WKT — always WGS84 (EPSG:4326). "
                     "OSGB is held separately in osgb_easting/northing."),
    )
    osgb_easting: float | None = None
    osgb_northing: float | None = None

    # ── Developer (2 fields) ───────────────────────────────────────────────
    parent_company: str | None = Field(
        None,
        description=("Parent corporate group, e.g. 'National Grid plc' "
                     "(owns NGET), 'Iberdrola' (owns SPT, SPEN)."),
    )
    developer: str = Field(
        ...,
        description=("Licensee code: 'NGET', 'SPT', 'SHE-T', 'UKPN', "
                     "'SSEN', 'SPEN', 'NGED', 'NPG', 'ENWL'."),
    )

    # ── Electrical (5 fields) ──────────────────────────────────────────────
    voltage_kv_primary: float | None = None
    voltage_kv_secondary: float | None = None
    voltage_description: str | None = Field(
        None, description='Human text — e.g. "400/132 kV, 2 × 240 MVA SGT".',
    )
    equipment_description: str | None = None
    equipment_capacity_mva: float | None = None

    # ── Timeline (5 fields) ────────────────────────────────────────────────
    construction_year: int | None = None
    construction_date_detail: str | None = Field(
        None, description='E.g. "Q2 2028", "Sep 2029".',
    )
    construction_status: ConstructionStatus = "unknown"
    operation_year: int | None = None
    operation_date_detail: str | None = None

    # ── Finance (4 fields) ─────────────────────────────────────────────────
    capex_gbp_millions: float | None = None
    capex_description: str | None = None
    capex_price_base_year: int | None = Field(
        None,
        description=("Price base year for capex in 2-digit form, e.g. 18 "
                     "(2018/19 — RIIO-ET2 base) or 23 (2023/24 — RIIO-ED2)."),
    )
    financial_description: str | None = None

    # ── Provenance (5 fields) ──────────────────────────────────────────────
    source_type: SourceType
    source_docket_id: str | None = Field(
        None, description='Primary source reference (e.g. NOA project code, NSIP PINS ref, RIIO CV ID).',
    )
    docket_profile_url: str | None = None
    source_links: list[str] = Field(
        default_factory=list,
        description="Up to 6 links — doc PDFs, portal URLs, CV references.",
    )
    capex_source_link: str | None = None

    # ── Housekeeping (3 fields) ────────────────────────────────────────────
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="0–1 composite confidence. Drives SME review queue priority.",
    )
    sme_reviewed: bool = False

    # ----- validators -----------------------------------------------------

    @field_validator("source_links")
    @classmethod
    def _cap_source_links(cls, v: list[str]) -> list[str]:
        if len(v) > 6:
            return v[:6]
        return v

    @field_validator("capex_price_base_year")
    @classmethod
    def _coerce_price_base(cls, v: int | None) -> int | None:
        if v is None:
            return v
        # Accept 2018 → 18, 2023 → 23 — always store 2-digit form.
        if v >= 100:
            return v % 100
        return v

    # ----- convenience ----------------------------------------------------

    def primary_link(self) -> str | None:
        """First non-empty provenance URL — useful for UI."""
        return self.docket_profile_url or (self.source_links[0] if self.source_links else None) or self.capex_source_link

    def to_row(self) -> dict:
        """Flat dict suitable for data_subscription_rows upsert."""
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Constants used by parsers/resolvers
# ---------------------------------------------------------------------------
# Licensee → parent company (used by parsers that only know the licensee).
PARENT_COMPANY_BY_DEVELOPER: dict[str, str] = {
    "NGET":   "National Grid plc",
    "SPT":    "Iberdrola",
    "SHE-T":  "SSE plc",
    "UKPN":   "UK Power Networks Holdings Ltd",
    "SSEN":   "SSE plc",
    "SPEN":   "Iberdrola",
    "NGED":   "National Grid plc",
    "NPG":    "Northern Powergrid Holdings (Berkshire Hathaway)",
    "ENWL":   "Electricity North West Ltd (CKI / Iberdrola JV)",
}

# Licensee → primary country coverage (some cross borders — England default).
COUNTRY_BY_DEVELOPER: dict[str, Country] = {
    "NGET":  "England",
    "SPT":   "Scotland",
    "SHE-T": "Scotland",
    "UKPN":  "England",
    "SSEN":  "Scotland",
    "SPEN":  "Scotland",
    "NGED":  "England",
    "NPG":   "England",
    "ENWL":  "England",
}

# RIIO price base year for each licensee's most recent business plan.
RIIO_PRICE_BASE_BY_DEVELOPER: dict[str, int] = {
    # RIIO-ET2 (April 2021–March 2026) 18/19 prices
    "NGET":  18,
    "SPT":   18,
    "SHE-T": 18,
    # RIIO-ED2 (April 2023–March 2028) 20/21 prices
    "UKPN":  20,
    "SSEN":  20,
    "SPEN":  20,
    "NGED":  20,
    "NPG":   20,
    "ENWL":  20,
}
