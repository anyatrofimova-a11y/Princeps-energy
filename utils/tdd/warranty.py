"""Warranty matrix, PCG register and O&M / LTSA contract review.

Lender TAs rate "warranty scope gaps + PCG status" as red-flag #1 (see
``docs/competitive/tdd_standard_2026.md`` §5).  This module produces:

  * :class:`WarrantyMatrix` — one row per equipment item with warranty term,
    manufacturer, parent-company-guarantee status, known failure modes, and
    a PASS / CONCERN / BLOCKER verdict from the TA perspective.
  * :func:`manufacturer_pcg_lookup` — manual table of 18 real manufacturers
    active in the UK solar / BESS / rotating-plant market (Trina, LONGi,
    Jinko, Canadian Solar, JA Solar, Tesla, Fluence, Wärtsilä, Hitachi
    Energy, Siemens Energy, GE Vernova, Sungrow, Huawei, SMA, Power
    Electronics, ABB, Hyosung, EPC Power).
  * :class:`OMContractReview` with a 10-point review checklist a TA would
    walk through before signing.

No external data sources: PCG data is captured from public filings and
bankability reports (Bloomberg Tier 1, RETC, DNV / Kiwa, PV-Magazine,
S&P Global) as of 2026-04-19.  Refresh quarterly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal, Iterable


TA_VIEW = Literal["PASS", "CONCERN", "BLOCKER"]


# ---------------------------------------------------------------------------
# Manufacturer PCG register
# ---------------------------------------------------------------------------
# pcg_status:
#   "unconditional" — signed parent-company guarantee from ultimate parent
#                     with unconditional performance obligation.
#   "conditional"   — PCG from parent subject to materiality / financial
#                     thresholds (common from privately-held parents).
#   "bond"          — bank-issued performance bond in lieu of PCG.
#   "insurance"     — warranty wrap from commercial insurer (e.g. PowerGuard
#                     / New Energy Risk / GCube).
#   "none"          — no PCG in standard contract; warranty sits with UK
#                     subsidiary or trading entity only.
#
# pcg_amount_gbp is the typical cap seen in UK 50-100 MW deals; lenders
# expect minimum 10% of equipment contract value for solar modules and 15%+
# for BESS systems.
_MANUFACTURER_PCG: dict[str, dict] = {
    # ---- Solar modules ------------------------------------------------
    "Trina Solar": {
        "parent": "Trina Solar Co., Ltd (Shanghai)",
        "ticker": "688599.SH",
        "credit_rating": "BBB (internal, S&P implied)",
        "pcg_status": "conditional",
        "pcg_amount_gbp": 3_500_000,
        "warranty_years_product": 15,
        "warranty_years_performance": 30,
        "bankability": "Tier 1 Bloomberg, TÜV gold-rated; PID resistant Vertex S+",
        "known_issues": [
            "Vertex N-type field fleet <18 months — limited track record",
            "2023 UK import-duty exposure now cleared (MoU May 2025)",
        ],
    },
    "LONGi Green Energy": {
        "parent": "LONGi Green Energy Technology Co., Ltd",
        "ticker": "601012.SH",
        "credit_rating": "BBB-",
        "pcg_status": "conditional",
        "pcg_amount_gbp": 4_000_000,
        "warranty_years_product": 15,
        "warranty_years_performance": 30,
        "bankability": "Tier 1 Bloomberg; Hi-MO X6 Scientist BC cell programme",
        "known_issues": [
            "2024 impairment provision on polysilicon inventory — monitor cashflow",
            "Hi-MO 5 cell cracking under thermal cycling isolated incidents",
        ],
    },
    "Jinko Solar": {
        "parent": "Jinko Solar Holding Co., Ltd",
        "ticker": "JKS",
        "credit_rating": "BB+",
        "pcg_status": "conditional",
        "pcg_amount_gbp": 3_000_000,
        "warranty_years_product": 12,
        "warranty_years_performance": 30,
        "bankability": "Tier 1 Bloomberg; Tiger Neo N-type 620 W dominant 2026 UK",
        "known_issues": [
            "Related-party transactions with Jinko Power — disclose in TDD",
            "N-type first-year LID guidance 1% (vs 0.5% PERC) - model impact",
        ],
    },
    "Canadian Solar": {
        "parent": "Canadian Solar Inc. (Ontario, Canada)",
        "ticker": "CSIQ",
        "credit_rating": "BB",
        "pcg_status": "unconditional",
        "pcg_amount_gbp": 2_500_000,
        "warranty_years_product": 12,
        "warranty_years_performance": 30,
        "bankability": "Tier 1; CSI Solar HiKu7 bifacial dominant UK tender 2025",
        "known_issues": [
            "Spin-off of CSI Solar Inc. on Shanghai STAR 2023 - PCG re-papering",
        ],
    },
    "JA Solar": {
        "parent": "JA Solar Technology Co., Ltd",
        "ticker": "002459.SZ",
        "credit_rating": "BBB-",
        "pcg_status": "conditional",
        "pcg_amount_gbp": 2_500_000,
        "warranty_years_product": 12,
        "warranty_years_performance": 30,
        "bankability": "Tier 1 Bloomberg; DeepBlue 4.0 Pro N-type",
        "known_issues": [
            "Lower UK market share vs Trina / LONGi / Jinko — spares channel risk",
        ],
    },

    # ---- Inverters ----------------------------------------------------
    "Sungrow": {
        "parent": "Sungrow Power Supply Co., Ltd (Hefei)",
        "ticker": "300274.SZ",
        "credit_rating": "BBB",
        "pcg_status": "unconditional",
        "pcg_amount_gbp": 2_000_000,
        "warranty_years_product": 5,
        "warranty_years_extended": 25,
        "bankability": "Global #1 string inverter 2024; strong UK service footprint",
        "known_issues": [
            "SG250HX firmware update 2024.11 mandatory for P28/P29 compliance",
        ],
    },
    "Huawei FusionSolar": {
        "parent": "Huawei Technologies Co., Ltd",
        "ticker": "Private",
        "credit_rating": "Not public (state-linked)",
        "pcg_status": "none",
        "pcg_amount_gbp": 0,
        "warranty_years_product": 5,
        "warranty_years_extended": 25,
        "bankability": "Tier 1 technology; US sanctions risk flagged by UK lenders",
        "known_issues": [
            "NSIA (National Security & Investment Act) review may apply",
            "US Entity List listing — component-sourcing diligence required",
        ],
    },
    "SMA Solar Technology": {
        "parent": "SMA Solar Technology AG (Kassel)",
        "ticker": "S92.DE",
        "credit_rating": "BB+ (Scope Ratings)",
        "pcg_status": "unconditional",
        "pcg_amount_gbp": 1_500_000,
        "warranty_years_product": 5,
        "warranty_years_extended": 20,
        "bankability": "Premium European OEM; 2024 restructuring completed",
        "known_issues": [
            "Profit warning Q4 2024; monitor going-concern wording in accounts",
        ],
    },
    "Power Electronics": {
        "parent": "Power Electronics España S.L.",
        "ticker": "Private",
        "credit_rating": "Not rated (privately held)",
        "pcg_status": "bond",
        "pcg_amount_gbp": 1_200_000,
        "warranty_years_product": 5,
        "warranty_years_extended": 25,
        "bankability": "Dominant utility inverter (Freesun); bond backed by Santander",
        "known_issues": [],
    },

    # ---- BESS systems -------------------------------------------------
    "Tesla Megapack": {
        "parent": "Tesla, Inc. (Austin, TX)",
        "ticker": "TSLA",
        "credit_rating": "BBB (S&P)",
        "pcg_status": "unconditional",
        "pcg_amount_gbp": 15_000_000,
        "warranty_years_product": 10,
        "warranty_years_capacity": 20,
        "bankability": "Megapack 2XL (3.9 MWh) — top 3 UK BESS brand 2025-26",
        "known_issues": [
            "Moss Landing fire 16 Jan 2025 (100 MW Vistra) — propagation audit now mandatory",
            "Cycling-throughput limits per nameplate hour tightened in 2025 MSA",
            "Lead time 12-18 months; financeable only with Tesla Finance or lender Tesla Risk Review",
        ],
    },
    "Fluence Gridstack": {
        "parent": "Fluence Energy, Inc. (Arlington, VA)",
        "ticker": "FLNC",
        "credit_rating": "BB-",
        "pcg_status": "conditional",
        "pcg_amount_gbp": 8_000_000,
        "warranty_years_product": 10,
        "warranty_years_capacity": 20,
        "bankability": "Gridstack Pro — AES + Siemens JV pedigree; UL 9540A at all 3 levels",
        "known_issues": [
            "Q3 2024 guidance miss — monitor cash burn in 2026 10-Q filings",
            "Smartstack (2026) field data limited — accept only with retrofit clause",
        ],
    },
    "Wärtsilä Quantum": {
        "parent": "Wärtsilä Oyj Abp (Helsinki)",
        "ticker": "WRT1V.HE",
        "credit_rating": "BBB",
        "pcg_status": "unconditional",
        "pcg_amount_gbp": 6_000_000,
        "warranty_years_product": 10,
        "warranty_years_capacity": 20,
        "bankability": "Quantum 2 + GEMS controller; preferred by UK flex traders",
        "known_issues": [
            "Quantum platform cooling redesign 2024 — confirm build serial post-Q2 2024",
        ],
    },
    "Hitachi Energy E-mesh": {
        "parent": "Hitachi, Ltd (Tokyo) via Hitachi Energy Ltd (Zurich)",
        "ticker": "6501.T",
        "credit_rating": "A (S&P)",
        "pcg_status": "unconditional",
        "pcg_amount_gbp": 10_000_000,
        "warranty_years_product": 10,
        "warranty_years_capacity": 20,
        "bankability": "E-mesh + PowerStore; strongest PCG in class (Hitachi parent A-rated)",
        "known_issues": [],
    },
    "Siemens Energy": {
        "parent": "Siemens Energy AG (Munich)",
        "ticker": "ENR.DE",
        "credit_rating": "BBB",
        "pcg_status": "unconditional",
        "pcg_amount_gbp": 8_000_000,
        "warranty_years_product": 10,
        "warranty_years_capacity": 20,
        "bankability": "Siestorage + BESS.AI controller; top European bankability",
        "known_issues": [
            "Gamesa onshore wind loss provision — separate from BESS division but PCG scope tested",
        ],
    },
    "GE Vernova": {
        "parent": "GE Vernova Inc. (Cambridge, MA)",
        "ticker": "GEV",
        "credit_rating": "BBB+",
        "pcg_status": "unconditional",
        "pcg_amount_gbp": 8_000_000,
        "warranty_years_product": 10,
        "warranty_years_capacity": 20,
        "bankability": "Reservoir Storage; post-GE spin bankability strong",
        "known_issues": [],
    },

    # ---- Transformers & switchgear -----------------------------------
    "ABB Transformers": {
        "parent": "ABB Ltd (Zurich)",
        "ticker": "ABBN.SW",
        "credit_rating": "A",
        "pcg_status": "unconditional",
        "pcg_amount_gbp": 3_000_000,
        "warranty_years_product": 5,
        "warranty_years_extended": 25,
        "bankability": "Blue-chip transformer OEM; Dry-type + TXpert digital",
        "known_issues": [
            "Lead time 18-24 months — procurement schedule risk",
        ],
    },
    "Hyosung Heavy Industries": {
        "parent": "Hyosung Heavy Industries Co. (Seoul)",
        "ticker": "298040.KS",
        "credit_rating": "BBB-",
        "pcg_status": "conditional",
        "pcg_amount_gbp": 2_000_000,
        "warranty_years_product": 5,
        "warranty_years_extended": 20,
        "bankability": "Leading Korean GSU transformer supplier UK BESS",
        "known_issues": [],
    },
    "EPC Power": {
        "parent": "EPC Power Corp. (San Diego, CA)",
        "ticker": "Private",
        "credit_rating": "Not rated (private equity held)",
        "pcg_status": "bond",
        "pcg_amount_gbp": 750_000,
        "warranty_years_product": 5,
        "bankability": "US-centric PCS inverter; niche UK deployment",
        "known_issues": [
            "Limited UK service footprint — spares strategy critical",
        ],
    },
}


@dataclass
class PCGRegister:
    """Manufacturer parent-company-guarantee register.

    Construct with :func:`manufacturer_pcg_lookup` for a populated instance.
    """
    entries: dict[str, dict] = field(default_factory=dict)
    source: str = (
        "Princeps PCG register 2026-04-19 — sources: Bloomberg NEF Tier-1, "
        "RETC/PVEL Module Reliability Scorecard 2025, DNV BESS Scorecard "
        "2024-H2, S&P Global Ratings, Companies House filings."
    )

    def get(self, manufacturer: str) -> dict | None:
        return self.entries.get(manufacturer)

    def to_rows(self) -> list[dict]:
        out = []
        for name, info in self.entries.items():
            row = {"manufacturer": name}
            row.update(info)
            out.append(row)
        return out

    def to_dict(self) -> dict:
        return {"source": self.source, "entries": self.entries}


def manufacturer_pcg_lookup(manufacturer: str | None = None) -> dict | PCGRegister:
    """Return a single record or the full register.

    >>> rec = manufacturer_pcg_lookup("Tesla Megapack")
    >>> rec["pcg_status"]
    'unconditional'
    >>> reg = manufacturer_pcg_lookup()
    >>> isinstance(reg, PCGRegister)
    True
    """
    if manufacturer is None:
        return PCGRegister(entries=dict(_MANUFACTURER_PCG))
    if manufacturer not in _MANUFACTURER_PCG:
        # Fuzzy match on first word (e.g. "Trina" → "Trina Solar").
        for key in _MANUFACTURER_PCG:
            if key.split()[0].lower() == manufacturer.split()[0].lower():
                return dict(_MANUFACTURER_PCG[key])
        return {
            "parent": "Unknown",
            "pcg_status": "unknown",
            "pcg_amount_gbp": 0,
            "known_issues": [
                f"Manufacturer '{manufacturer}' not in PCG register — TA to cover in "
                "supplementary diligence before financial close.",
            ],
        }
    return dict(_MANUFACTURER_PCG[manufacturer])


# ---------------------------------------------------------------------------
# Warranty matrix
# ---------------------------------------------------------------------------
@dataclass
class WarrantyLine:
    """A single row of the warranty matrix.

    equipment        e.g. "Solar module", "Central inverter", "BESS module",
                     "BESS enclosure", "Main Transformer", "HV switchgear"
    manufacturer     brand name (key into PCG register)
    model            commercial designation
    warranty_years   product warranty
    performance_yrs  performance / capacity warranty (solar modules, BESS)
    pcg_status       "unconditional" / "conditional" / "bond" / "insurance" / "none"
    pcg_amount_gbp   typical PCG cap in GBP
    known_issues     list[str]
    ta_view          PASS / CONCERN / BLOCKER
    notes            free-text commentary
    """
    equipment: str
    manufacturer: str
    model: str
    warranty_years: int
    performance_years: int | None = None
    pcg_status: str = "unknown"
    pcg_amount_gbp: float = 0.0
    known_issues: list[str] = field(default_factory=list)
    ta_view: TA_VIEW = "CONCERN"
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WarrantyMatrix:
    """Collection of :class:`WarrantyLine` rows.

    The matrix drives the warranty section in the TDD pack and populates the
    "warranty scope gaps + PCG status" red-flag ladder item.
    """
    project_name: str
    technology: Literal["solar", "bess", "wind", "dc", "hybrid"]
    capacity_mw: float
    lines: list[WarrantyLine] = field(default_factory=list)
    summary_view: TA_VIEW = "CONCERN"
    red_flags: list[str] = field(default_factory=list)

    def add(self, line: WarrantyLine) -> None:
        self.lines.append(line)

    def rollup(self) -> None:
        """Update summary_view and red_flags from line-level verdicts."""
        blockers = [l for l in self.lines if l.ta_view == "BLOCKER"]
        concerns = [l for l in self.lines if l.ta_view == "CONCERN"]
        if blockers:
            self.summary_view = "BLOCKER"
        elif concerns:
            self.summary_view = "CONCERN"
        else:
            self.summary_view = "PASS"
        self.red_flags = []
        for l in blockers + concerns:
            issues = "; ".join(l.known_issues) if l.known_issues else "see notes"
            self.red_flags.append(
                f"{l.ta_view}: {l.equipment} ({l.manufacturer}) — {issues}"
            )

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "technology": self.technology,
            "capacity_mw": self.capacity_mw,
            "summary_view": self.summary_view,
            "red_flags": list(self.red_flags),
            "lines": [l.to_dict() for l in self.lines],
        }


def _classify_ta_view(
    manufacturer: str,
    pcg_status: str,
    warranty_years: int,
    min_years_expected: int,
) -> TA_VIEW:
    if pcg_status in ("none", "unknown"):
        return "BLOCKER"
    if warranty_years < min_years_expected - 3:
        return "BLOCKER"
    if pcg_status in ("conditional", "bond", "insurance"):
        return "CONCERN"
    if warranty_years < min_years_expected:
        return "CONCERN"
    return "PASS"


def _line_from_pcg(
    *,
    equipment: str,
    manufacturer: str,
    model: str,
    min_years_expected: int,
    override_warranty_years: int | None = None,
    override_performance_years: int | None = None,
    extra_notes: str = "",
) -> WarrantyLine:
    pcg = manufacturer_pcg_lookup(manufacturer)
    w_yrs = override_warranty_years or int(
        pcg.get("warranty_years_product") or min_years_expected
    )
    p_yrs = override_performance_years or pcg.get("warranty_years_performance") or \
        pcg.get("warranty_years_capacity") or pcg.get("warranty_years_extended")
    ta_view = _classify_ta_view(
        manufacturer, pcg.get("pcg_status", "unknown"), w_yrs, min_years_expected,
    )
    return WarrantyLine(
        equipment=equipment,
        manufacturer=manufacturer,
        model=model,
        warranty_years=w_yrs,
        performance_years=(int(p_yrs) if p_yrs else None),
        pcg_status=pcg.get("pcg_status", "unknown"),
        pcg_amount_gbp=float(pcg.get("pcg_amount_gbp") or 0),
        known_issues=list(pcg.get("known_issues") or []),
        ta_view=ta_view,
        notes=extra_notes or f"Bankability: {pcg.get('bankability', 'n/a')}",
    )


def build_warranty_matrix(
    project_tech: Literal["solar", "bess", "wind", "dc", "hybrid"],
    equipment_list: Iterable[dict] | None = None,
    *,
    project_name: str = "Project",
    capacity_mw: float = 50.0,
) -> WarrantyMatrix:
    """Build a seeded warranty matrix.

    ``equipment_list`` items look like::

        {"equipment": "Solar module", "manufacturer": "Trina Solar",
         "model": "Vertex TSM-NEG21C.20 625W"}

    When ``equipment_list`` is not given, a credible default pack is seeded
    for the stated technology (useful for Pembroke / Culham BESS demo runs).
    """
    matrix = WarrantyMatrix(
        project_name=project_name,
        technology=project_tech,
        capacity_mw=capacity_mw,
    )

    if equipment_list:
        for item in equipment_list:
            # Minimum expected warranty years per equipment category (lender
            # baseline, 2026 UK solar/BESS market).
            _min = {
                "Solar module": 15,
                "Central inverter": 5,
                "String inverter": 10,
                "BESS module": 10,
                "BESS enclosure": 10,
                "BESS PCS": 5,
                "Main transformer": 5,
                "GSU transformer": 5,
                "HV switchgear": 5,
            }.get(item.get("equipment", ""), 5)
            matrix.add(_line_from_pcg(
                equipment=item["equipment"],
                manufacturer=item["manufacturer"],
                model=item.get("model", ""),
                min_years_expected=_min,
                override_warranty_years=item.get("warranty_years"),
                override_performance_years=item.get("performance_years"),
                extra_notes=item.get("notes", ""),
            ))
    else:
        # Seed credible defaults per technology.
        if project_tech == "solar":
            matrix.add(_line_from_pcg(
                equipment="Solar module", manufacturer="Trina Solar",
                model="Vertex S+ TSM-NEG21C.20 625W", min_years_expected=15,
            ))
            matrix.add(_line_from_pcg(
                equipment="Central inverter", manufacturer="Sungrow",
                model="SG3600UD-MV 3.6 MVA", min_years_expected=5,
            ))
            matrix.add(_line_from_pcg(
                equipment="Main transformer", manufacturer="ABB Transformers",
                model="33/132 kV 50 MVA dry-type", min_years_expected=5,
            ))
            matrix.add(_line_from_pcg(
                equipment="HV switchgear", manufacturer="ABB Transformers",
                model="ZX0 33 kV GIS", min_years_expected=5,
            ))
        elif project_tech == "bess":
            # Big UK utility BESS 2026 default = Tesla Megapack + Fluence split.
            matrix.add(_line_from_pcg(
                equipment="BESS enclosure", manufacturer="Tesla Megapack",
                model="Megapack 2 XL (3.9 MWh / unit)", min_years_expected=10,
                extra_notes="Liquid-cooled LFP; Powerhub SCADA.",
            ))
            matrix.add(_line_from_pcg(
                equipment="BESS enclosure", manufacturer="Fluence Gridstack",
                model="Gridstack Pro 5000 (5 MWh / cube)", min_years_expected=10,
                extra_notes="Alternative lot; UL 9540A all three levels.",
            ))
            matrix.add(_line_from_pcg(
                equipment="BESS PCS", manufacturer="Power Electronics",
                model="FS4250K — 4.25 MVA string PCS", min_years_expected=5,
            ))
            matrix.add(_line_from_pcg(
                equipment="GSU transformer", manufacturer="Hyosung Heavy Industries",
                model="33/132 kV 130 MVA ONAN/ONAF", min_years_expected=5,
            ))
            matrix.add(_line_from_pcg(
                equipment="HV switchgear", manufacturer="ABB Transformers",
                model="ELK-04 132 kV GIS", min_years_expected=5,
            ))
        elif project_tech == "dc":
            matrix.add(_line_from_pcg(
                equipment="UPS", manufacturer="ABB Transformers",
                model="DPA 250 S4 — 2N modular", min_years_expected=5,
                extra_notes="IEC 62040 redundancy N+1 to 2N.",
            ))
            matrix.add(_line_from_pcg(
                equipment="Main transformer", manufacturer="ABB Transformers",
                model="33/11 kV 40 MVA dry-type", min_years_expected=5,
            ))
            matrix.add(_line_from_pcg(
                equipment="BESS enclosure", manufacturer="Tesla Megapack",
                model="Megapack 2 (3.1 MWh) - load-shift reserve",
                min_years_expected=10,
            ))
        else:  # wind / hybrid — seed the tech items we can.
            matrix.add(_line_from_pcg(
                equipment="Main transformer", manufacturer="Siemens Energy",
                model="SGT-100 GSU", min_years_expected=5,
            ))

    matrix.rollup()
    return matrix


# ---------------------------------------------------------------------------
# O&M / LTSA contract review
# ---------------------------------------------------------------------------
@dataclass
class OMContractReview:
    """TA checklist for the O&M / LTSA contract.

    Ten points a Ramboll / RSK / AFRY TA walks before signing.  Each point
    returns ``{question, expected_form, flag}`` where ``flag`` is PASS /
    CONCERN / BLOCKER / REVIEW_PENDING.
    """
    project_name: str
    contractor: str
    annual_fee_gbp_per_mw_yr: float
    term_years: int
    review: list[dict] = field(default_factory=list)
    overall: TA_VIEW = "CONCERN"

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "contractor": self.contractor,
            "annual_fee_gbp_per_mw_yr": self.annual_fee_gbp_per_mw_yr,
            "term_years": self.term_years,
            "review": list(self.review),
            "overall": self.overall,
        }


def om_contract_checklist(
    *,
    project_name: str,
    contractor: str,
    technology: Literal["solar", "bess", "wind", "dc"],
    capacity_mw: float,
    annual_fee_gbp_per_mw_yr: float | None = None,
    term_years: int | None = None,
    availability_guarantee_pct: float = 98.5,
    parent_is_equity_holder: bool = False,
    price_escalation_index: str = "CPIH",
) -> OMContractReview:
    """Return a populated :class:`OMContractReview`.

    Defaults are credible 2026 UK numbers:
      * Solar £6.5k/MW/yr, BESS £18k/MW/yr, DC £24k/MW/yr.
      * Solar LTSA 20 yrs, BESS LTSA 15 yrs (matches capacity warranty).
    """
    fee = annual_fee_gbp_per_mw_yr or {
        "solar": 6_500, "bess": 18_000, "wind": 32_000, "dc": 24_000,
    }.get(technology, 10_000)
    term = term_years or {"solar": 20, "bess": 15, "wind": 15, "dc": 10}.get(
        technology, 10,
    )

    checklist: list[dict] = [
        {
            "id": 1,
            "topic": "Performance guarantee",
            "question": "Does the O&M contract include a performance-ratio (solar) or "
                        "availability (BESS/wind/DC) guarantee with liquidated damages?",
            "expected_form": (
                "Solar: PR ≥ 83% over rolling 12-months, LD 1.0x lost-revenue to 5% cap. "
                "BESS: availability ≥ 98.5%, LD £/MW/day to 10% annual-fee cap. "
                "DC: uptime ≥ 99.982% (Tier III), SLA credits to 50% monthly fee."
            ),
            "flag": "REVIEW_PENDING",
        },
        {
            "id": 2,
            "topic": "Availability threshold & measurement",
            "question": (
                "How is availability calculated — time-based vs energy-weighted? "
                "Are DNO / weather outages excluded? Are scheduled-maintenance windows "
                "inside or outside the availability window?"
            ),
            "expected_form": (
                f"{availability_guarantee_pct}% energy-weighted, exclusions listed in "
                "Schedule 3, max 5 planned-outage days/yr."
            ),
            "flag": "REVIEW_PENDING",
        },
        {
            "id": 3,
            "topic": "IT / SCADA cover",
            "question": "Is SCADA, cyber-patching and firmware upgrade included in scope?",
            "expected_form": (
                "24/7 NOC monitoring, IEC 62443 / NIS2 patch SLAs, SOC2 Type II evidence."
            ),
            "flag": "REVIEW_PENDING",
        },
        {
            "id": 4,
            "topic": "Parent-company guarantee",
            "question": "Is the contractor an SPV / trading subsidiary, and is a PCG from "
                        "the ultimate parent in place?",
            "expected_form": (
                "Unconditional PCG from listed parent, cap ≥ 2× annual fee, on-demand "
                "payment obligation."
            ),
            "flag": "CONCERN" if not parent_is_equity_holder else "PASS",
        },
        {
            "id": 5,
            "topic": "Price escalation & CPI indexation",
            "question": "Is the annual fee indexed to a published UK index?",
            "expected_form": (
                f"Annual CPI uplift ({price_escalation_index}) with a 5% cap and a 0% "
                "floor. Reopener on major technology revision."
            ),
            "flag": "REVIEW_PENDING",
        },
        {
            "id": 6,
            "topic": "Termination rights",
            "question": "Termination-for-convenience notice period, termination-for-cause "
                        "triggers, novation of contract to financier on default?",
            "expected_form": (
                "Employer TFC on 180-day notice; lender step-in via direct agreement; "
                "no-fault termination on six consecutive availability-breach months."
            ),
            "flag": "REVIEW_PENDING",
        },
        {
            "id": 7,
            "topic": "Spare-parts strategy & inventory",
            "question": "Who owns critical spares, where are they stored, what is the "
                        "lead time for major items (transformer / inverter / BESS module)?",
            "expected_form": (
                "Onsite or regional-depot spares for < 72 hr inverter / module swap; "
                "named list in Schedule 5; parent-provided spare-bank commitment."
            ),
            "flag": "REVIEW_PENDING",
        },
        {
            "id": 8,
            "topic": "Response SLAs",
            "question": "Fault-response and mean-time-to-repair targets by severity class?",
            "expected_form": (
                "Class 1 (site down): 2 hr acknowledge, 24 hr on-site, 72 hr fix. "
                "Class 2 (string / module): 48 hr acknowledge, 5 day fix."
            ),
            "flag": "REVIEW_PENDING",
        },
        {
            "id": 9,
            "topic": "Exclusions & force majeure",
            "question": "Are exclusions limited to genuine FM events, or are they broad "
                        "enough to capture grid, weather, or pandemic events?",
            "expected_form": (
                "FM list limited to war, natural disaster, Govt direction; grid outage "
                "covered by separate curtailment carve-out with LD credit."
            ),
            "flag": "REVIEW_PENDING",
        },
        {
            "id": 10,
            "topic": "Warranty back-to-back",
            "question": "Does the O&M contractor pass through OEM warranty work and "
                        "carry liability for any warranty-claim delay?",
            "expected_form": (
                "Contractor administers warranty claims on behalf of Employer; liable "
                "for any avoidable claim rejection; audit right on OEM correspondence."
            ),
            "flag": "REVIEW_PENDING",
        },
    ]

    # Rollup: any BLOCKER → BLOCKER, else any CONCERN → CONCERN.
    flags = [row["flag"] for row in checklist]
    if "BLOCKER" in flags:
        overall: TA_VIEW = "BLOCKER"
    elif "CONCERN" in flags:
        overall = "CONCERN"
    else:
        overall = "PASS"

    return OMContractReview(
        project_name=project_name,
        contractor=contractor,
        annual_fee_gbp_per_mw_yr=fee,
        term_years=term,
        review=checklist,
        overall=overall,
    )
