"""Insurance programme, CEng sign-off block and reliance package.

Implements the Tier-1 lender TDD sections 12 ("Insurance programme") + 15
("Reliance + sign-off") from :file:`docs/competitive/tdd_standard_2026.md`.

No external brokers are hit — figures are deterministic estimates driven by
project CAPEX / revenue exposure, then returned in a shape the Jinja TDD
template can consume directly.

Benchmarks (UK 2026 market, AON / Marsh / WTW private placement ranges):
  * CAR sum-insured ≈ 100% of total EPC + mobilisation.
  * CAR rate ≈ 0.22-0.45% of sum insured per annum (BESS carries the
    higher end; solar < 0.25%).
  * DSU (Delay Start-Up) ≈ 9-15 months gross revenue, sublimit typically
    50-75% of operating-year revenue.
  * Operational property damage ≈ replacement value, typical deductible
    £250k for solar, £500k for BESS.
  * Business interruption ≈ 12 months gross margin.
  * Third-party liability: £10m primary + £20m excess (£30m tower) for
    solar / BESS; £50m + for DC interconnect exposure.
  * Cyber: £5m-£10m first-party + system-failure trigger.
  * Directors' & officers': £5m.

Chartered-engineer sign-off and reliance addressee templates follow the
standard UK lender-TDD convention: a named CEng MICE / MIET engineer, an
Institution of Civil / Electrical Engineers (ICE / IET) membership number
slot, and a single reliance letter with fee × 3 liability cap.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from typing import Literal


# ---------------------------------------------------------------------------
# Insurance programme
# ---------------------------------------------------------------------------
@dataclass
class CoverLine:
    """One line in the insurance programme.

    cover         e.g. "Construction All Risks", "Delay Start-Up",
                  "Operational Property Damage", "Business Interruption",
                  "Third-Party Liability (primary)".
    sum_insured_gbp  in pounds sterling; interpretation depends on cover:
                     CAR → contract value; DSU → gross profit for cover
                     period; BI → gross margin; liability → per-occurrence
                     limit.
    premium_gbp   annual gross premium (indicative).
    deductible_gbp deductible per claim.
    notes         carrier / AON-style layering comment, terrorism add-on
                  references, etc.
    """
    cover: str
    sum_insured_gbp: float
    premium_gbp: float
    deductible_gbp: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class InsuranceProgramme:
    """Full insurance programme for a single project.

    ``adequacy`` is a three-way verdict from the TA perspective:
    PASS (matches or exceeds lender minima), CONCERN (fits but on the low
    side of market practice), BLOCKER (below lender minimum — must be
    topped up before close).
    """
    project_name: str
    technology: Literal["solar", "bess", "wind", "dc", "hybrid"]
    capacity_mw: float
    construction_capex_gbp: float
    annual_revenue_gbp: float
    cover_lines: list[CoverLine] = field(default_factory=list)
    terrorism_add_on: bool = True
    advance_loss_of_profits_months: int = 12
    lender_minimum_met: bool = True
    adequacy: Literal["PASS", "CONCERN", "BLOCKER"] = "PASS"
    notes: list[str] = field(default_factory=list)

    @property
    def total_premium_gbp(self) -> float:
        return sum(c.premium_gbp for c in self.cover_lines)

    def to_dict(self) -> dict:
        base = asdict(self)
        base["total_premium_gbp"] = round(self.total_premium_gbp, 0)
        return base


def _car_premium(construction_capex_gbp: float, technology: str) -> float:
    """Return a representative CAR premium (% of sum-insured)."""
    rate = {
        "solar": 0.0022, "wind": 0.0032,
        "bess": 0.0045, "dc": 0.0028, "hybrid": 0.0035,
    }.get(technology, 0.003)
    return round(construction_capex_gbp * rate, 0)


def _dsu_premium(annual_revenue_gbp: float, months: int, technology: str) -> float:
    """DSU premium — driven by revenue-at-risk × exposure period."""
    period_revenue = annual_revenue_gbp * months / 12.0
    rate = {
        "solar": 0.004, "wind": 0.006, "bess": 0.008,
        "dc": 0.005, "hybrid": 0.006,
    }.get(technology, 0.005)
    return round(period_revenue * rate, 0)


def _implied_annual_revenue(capacity_mw: float, technology: str) -> float:
    """Back-of-envelope annual revenue in £ for cover sizing."""
    if technology == "solar":
        # ~10.5% capacity factor × 8760 h × capacity × £65/MWh blended
        return capacity_mw * 8760 * 0.105 * 65.0
    if technology == "bess":
        # Duration assumption: 2-hr system, ~340 cycles/yr, £85/MWh net margin
        return capacity_mw * 2.0 * 340 * 85.0
    if technology == "wind":
        return capacity_mw * 8760 * 0.34 * 70.0
    if technology == "dc":
        # Colocation gross revenue: £180/kW/month × capacity
        return capacity_mw * 1000 * 180 * 12
    return capacity_mw * 8760 * 0.20 * 70.0


def _default_capex(capacity_mw: float, technology: str) -> float:
    # UK 2026 typical EPC costs (£/MW, turnkey incl. BoP).
    rate = {
        "solar": 560_000, "bess": 450_000,  # £/MWh for BESS treated similarly
        "wind": 1_600_000, "dc": 8_000_000, "hybrid": 900_000,
    }.get(technology, 700_000)
    return capacity_mw * rate


def build_insurance_programme(
    *,
    project_name: str,
    technology: Literal["solar", "bess", "wind", "dc", "hybrid"],
    capacity_mw: float,
    construction_capex_gbp: float | None = None,
    annual_revenue_gbp: float | None = None,
    dsu_months: int = 12,
    terrorism_add_on: bool = True,
    third_party_liability_tower_gbp: float | None = None,
) -> InsuranceProgramme:
    """Produce a credible insurance programme for the given project.

    Good default for a 350 MW / 700 MWh BESS at Pembroke:
      * CAR sum insured ≈ £315m with 0.45% rate ⇒ £1.4m premium.
      * DSU 12 months ≈ £49m revenue, 0.8% rate ⇒ £395k premium.
      * Operational PD ≈ £315m with £500k deductible.
      * BI 12 months ≈ £40m gross margin.
      * Liability £30m tower.
      * Cyber £10m.
    """
    capex = construction_capex_gbp or _default_capex(capacity_mw, technology)
    revenue = annual_revenue_gbp or _implied_annual_revenue(
        capacity_mw, technology,
    )

    car_sum = round(capex, 0)
    car_prem = _car_premium(car_sum, technology)
    car_notes = (
        "Contractors All Risks per JCT MW 2016; cover = EPC + BoP + "
        "mobilisation + materials-in-transit. Replacement-value basis."
    )
    if terrorism_add_on:
        car_notes += " Terrorism extension via Pool Re (£10m sub-limit)."

    dsu_sum = round(revenue * dsu_months / 12.0, 0)
    dsu_prem = _dsu_premium(revenue, dsu_months, technology)
    dsu_notes = (
        f"Delay Start-Up (Advance Loss of Profit). Cover period {dsu_months} "
        "months; indemnity period triggered by physical-damage indemnifiable "
        "under CAR. Deductible 45 days."
    )

    op_sum = round(capex * 0.95, 0)
    op_prem = round(op_sum * (
        0.0014 if technology == "bess" else 0.0009
    ), 0)
    op_deductible = 500_000 if technology == "bess" else 250_000
    op_notes = (
        "Operational Property Damage on replacement-value basis. Fire, "
        "explosion, natural-perils, impact; standard UK energy wording."
    )

    bi_sum = round(revenue * 0.75, 0)
    bi_prem = round(bi_sum * 0.006, 0)
    bi_notes = (
        "Business Interruption — gross margin for 12-month indemnity period; "
        "aggregated with DSU at single-occurrence limit."
    )

    tpl_tower = third_party_liability_tower_gbp or (
        50_000_000 if technology == "dc" else 30_000_000
    )
    tpl_prem = round(tpl_tower * 0.0008, 0)
    tpl_notes = (
        f"Third-Party Liability tower £{tpl_tower/1e6:.0f}m. "
        "Primary £10m + excess layers placed through London market. "
        "Follow-form legal liability, sudden-and-accidental pollution."
    )

    cyber_sum = 5_000_000 if technology != "dc" else 10_000_000
    cyber_prem = round(cyber_sum * 0.014, 0)
    cyber_notes = (
        "First-party + third-party cyber to £{:.0f}m. System-failure trigger "
        "extends to SCADA / BMS / PLC outages causing physical damage; "
        "aligned with NIS2 / CAF and lender cyber-risk schedule."
    ).format(cyber_sum / 1e6)

    do_sum = 5_000_000
    do_prem = round(do_sum * 0.011, 0)
    do_notes = (
        "Directors & Officers tower £5m Side A/B/C. Covers HSE, Companies "
        "Act breaches, environmental prosecutions (Environment Act 2021)."
    )

    programme = InsuranceProgramme(
        project_name=project_name,
        technology=technology,
        capacity_mw=capacity_mw,
        construction_capex_gbp=capex,
        annual_revenue_gbp=round(revenue, 0),
        terrorism_add_on=terrorism_add_on,
        advance_loss_of_profits_months=dsu_months,
        cover_lines=[
            CoverLine("Construction All Risks", car_sum, car_prem, 500_000, car_notes),
            CoverLine("Delay Start-Up (ALoP)", dsu_sum, dsu_prem, 0.0, dsu_notes),
            CoverLine("Operational Property Damage", op_sum, op_prem, op_deductible, op_notes),
            CoverLine("Business Interruption", bi_sum, bi_prem, 0.0, bi_notes),
            CoverLine(f"Third-Party Liability (£{tpl_tower/1e6:.0f}m tower)",
                      tpl_tower, tpl_prem, 25_000, tpl_notes),
            CoverLine("Cyber + System Failure", cyber_sum, cyber_prem, 100_000, cyber_notes),
            CoverLine("Directors & Officers", do_sum, do_prem, 50_000, do_notes),
        ],
    )

    # Adequacy check vs UK lender minima (conservative).
    warnings: list[str] = []
    adequacy: Literal["PASS", "CONCERN", "BLOCKER"] = "PASS"
    if dsu_months < 9:
        adequacy = "CONCERN"
        warnings.append(
            f"DSU period {dsu_months} months is below 9-month lender minimum."
        )
    if car_sum < capex * 0.9:
        adequacy = "BLOCKER"
        warnings.append(
            "CAR sum insured is below 90% of construction CAPEX — material shortfall."
        )
    if tpl_tower < 20_000_000:
        adequacy = "CONCERN"
        warnings.append(
            "Third-party liability below £20m tower — lender benchmark is £20-30m."
        )
    if not terrorism_add_on:
        warnings.append(
            "Terrorism extension not elected — consider Pool Re sub-limit for UK assets."
        )

    programme.adequacy = adequacy
    programme.lender_minimum_met = (adequacy != "BLOCKER")
    programme.notes = warnings or [
        "Programme meets lender minima across all heads of cover.",
        "Re-test at each renewal; DSU can roll to Operational BI at energisation.",
    ]
    return programme


# ---------------------------------------------------------------------------
# Chartered-engineer sign-off block
# ---------------------------------------------------------------------------
@dataclass
class CEngSignOffBlock:
    """Template for the CEng sign-off page of the TDD.

    Contains the scope statement, reliance-cap wording, named engineer(s),
    CEng / institution membership numbers, and the signing date.  The
    template is filled in by the chartered engineer before issue; the
    Princeps-generated version returns an ``is_draft = True`` block with
    ``TO COMPLETE`` markers where required.
    """
    engineer_name: str = "TO COMPLETE — Chartered Engineer"
    engineer_title: str = "Director, Princeps Energy"
    ceng_number: str = "TO COMPLETE — CEng registration number"
    institution: str = "IET / ICE / IMechE"
    institution_number: str = "TO COMPLETE — Institution membership number"
    signing_date: str = ""
    scope_statement: str = (
        "I have reviewed the technical analysis, data sources and model "
        "assumptions set out in this Technical Due Diligence report. To the "
        "best of my professional judgement, and subject to the reliance "
        "cap and exclusions stated in the Reliance Statement, the report "
        "fairly represents the technical position of the Project as of "
        "the revision date."
    )
    reliance_cap_statement: str = (
        "Our aggregate liability in respect of this report is capped at "
        "three (3) times the fees paid to Princeps Energy under the "
        "engagement letter dated TO COMPLETE. No duty of care is owed to "
        "any party other than the addressees listed in the Reliance "
        "Statement."
    )
    is_draft: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def default_ceng_sign_off(
    *,
    engineer_name: str | None = None,
    engineer_title: str | None = None,
    ceng_number: str | None = None,
    institution: str = "IET",
    institution_number: str | None = None,
    signing_date: str | None = None,
) -> CEngSignOffBlock:
    """Return a draft CEng sign-off block.

    Any argument left as ``None`` is kept as the ``TO COMPLETE`` placeholder;
    the chartered engineer fills the block manually before issue (the
    ``is_draft = True`` flag warns the lender-side reader).
    """
    today = signing_date or date.today().strftime("%Y-%m-%d")
    block = CEngSignOffBlock(signing_date=today)
    if engineer_name:
        block.engineer_name = engineer_name
    if engineer_title:
        block.engineer_title = engineer_title
    if ceng_number:
        block.ceng_number = ceng_number
        block.is_draft = False
    block.institution = institution
    if institution_number:
        block.institution_number = institution_number
    if block.engineer_name.startswith("TO COMPLETE") or block.ceng_number.startswith("TO COMPLETE"):
        block.is_draft = True
        block.notes.append(
            "Draft only — a named Chartered Engineer must review, sign and "
            "date this block before the report is issued for reliance."
        )
    return block


# ---------------------------------------------------------------------------
# Reliance package
# ---------------------------------------------------------------------------
@dataclass
class Addressee:
    name: str
    role: str
    basis: str = "Named addressee"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReliancePackage:
    """Who can rely, on what basis, with what cap and expiry.

    The resulting package is consumed by both the existing
    ``templates/report/_partials/_reliance.html`` macro and the new
    ``templates/report/tdd_pack.html`` template.
    """
    client: str
    project_name: str
    purpose: str = "lender technical due diligence"
    reliance_type: Literal["lender", "investor", "planning", "dno", "client"] = "lender"
    addressees: list[Addressee] = field(default_factory=list)
    liability_cap_gbp: float | None = None
    liability_cap_multiplier: float = 3.0
    report_issue_date: str = ""
    reliance_letter_required: bool = True
    third_party_assignable: bool = True
    governing_law: str = "English law, courts of England and Wales"

    def add_addressee(self, name: str, role: str, basis: str | None = None) -> None:
        self.addressees.append(
            Addressee(name=name, role=role, basis=basis or "Named addressee"),
        )

    def to_dict(self) -> dict:
        return {
            "client": self.client,
            "project_name": self.project_name,
            "purpose": self.purpose,
            "reliance_type": self.reliance_type,
            "addressees": [a.to_dict() for a in self.addressees],
            "liability_cap_gbp": self.liability_cap_gbp,
            "liability_cap_multiplier": self.liability_cap_multiplier,
            "report_issue_date": self.report_issue_date,
            "reliance_letter_required": self.reliance_letter_required,
            "third_party_assignable": self.third_party_assignable,
            "governing_law": self.governing_law,
        }


def default_reliance_package(
    *,
    client: str,
    project_name: str,
    lender_name: str = "Syndicate lead bank (TO COMPLETE)",
    sponsor_name: str | None = None,
    insurer_name: str | None = None,
    agency_name: str | None = None,
    liability_cap_gbp: float | None = None,
) -> ReliancePackage:
    """Return a populated reliance package (lender variant by default).

    ``addressees`` is a sensible four-party list (lender, sponsor, insurer,
    UK-Gov agency) — any ``None`` argument drops that row.
    """
    pack = ReliancePackage(
        client=client,
        project_name=project_name,
        report_issue_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    pack.add_addressee(
        name=lender_name, role="Facility Agent / Lender",
        basis="Lender reliance letter (LMA form) — on signature",
    )
    if sponsor_name:
        pack.add_addressee(
            name=sponsor_name, role="Sponsor / Equity holder",
            basis="Client of record; unrestricted reliance",
        )
    if insurer_name:
        pack.add_addressee(
            name=insurer_name, role="Lead insurer / broker",
            basis="Extended reliance for insurance placement",
        )
    if agency_name:
        pack.add_addressee(
            name=agency_name, role="Government agency",
            basis="Read-only reliance, no contractual liability",
        )
    pack.liability_cap_gbp = liability_cap_gbp
    return pack
