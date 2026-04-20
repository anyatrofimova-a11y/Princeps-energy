"""
Statement of Reasons — Reg 5(2)(e).

The Statement of Reasons sets out:
  - why the project is needed;
  - the policy and legal basis for the consent sought;
  - alternatives considered and why rejected;
  - where compulsory acquisition is sought, why CA is necessary and
    proportionate (Human Rights Act 1998 Article 1 of the First Protocol,
    Article 8) and why land cannot be acquired by agreement.

DCLG Guidance "Planning Act 2008: Guidance related to procedures for the
compulsory acquisition of land" (September 2013 rev. 2023) is the
authoritative reference for the CA dimension.

Citation: "In fulfilment of Reg 5(2)(e) of the Infrastructure Planning
(Applications: Prescribed Forms and Procedure) Regulations 2009
(SI 2009/2264)."
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

try:  # pragma: no cover — resolved lazily at import
    from app.regulatory.versions import cite_nps as _cite_nps
except Exception:  # pragma: no cover
    _cite_nps = None  # type: ignore[assignment]


def _parse_accepted_on(project: dict) -> Optional[date]:
    """Best-effort parse of the DCO acceptance-for-examination date.

    Accepts ISO-8601 strings, ``datetime``/``date`` objects, or None. Returns
    None if unparseable — callers then default to the current NPS revision.
    """
    val = project.get("dco_accepted_on") or project.get("accepted_on") or project.get("acceptance_date")
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
        except Exception:
            return None
    return None


def _nps_cite(key: str, accepted_on: Optional[date]) -> str:
    """Version-correct NPS citation for EN-1 / EN-3 / EN-5."""
    if _cite_nps is not None:
        try:
            return _cite_nps(key, accepted_on)
        except Exception:  # pragma: no cover - defensive
            pass
    return {
        "en1": "NPS EN-1 (2025 revision)",
        "en3": "NPS EN-3 (2025 revision, in force 6 Jan 2026)",
        "en5": "NPS EN-5 (2025 revision)",
    }.get(key, f"NPS {key.upper()}")


def build_statement_of_reasons(project: dict, *, cpo_sought: bool = False) -> dict:
    """Return a SoR document structure."""
    proj_name = project.get("name") or "[Project]"
    tech = (project.get("workload_type") or project.get("technology") or "solar").lower()
    cap = project.get("capacity_mw") or "[CAP]"
    accepted_on = _parse_accepted_on(project)
    en1_cite = _nps_cite("en1", accepted_on)
    en3_cite = _nps_cite("en3", accepted_on)
    en5_cite = _nps_cite("en5", accepted_on)

    return {
        "document_title": "Statement of Reasons",
        "regulation_citation": (
            "In fulfilment of Regulation 5(2)(e) of the Infrastructure Planning "
            "(Applications: Prescribed Forms and Procedure) Regulations 2009 "
            "(SI 2009/2264, as amended), and (where compulsory acquisition is "
            "sought) section 123 of the Planning Act 2008 and the DCLG Guidance "
            "Planning Act 2008: Procedures for the compulsory acquisition of "
            "land (Sept 2013, rev. 2023)."
        ),
        "primary_legislation": [
            "Planning Act 2008 c.29",
            "Localism Act 2011 c.20",
            "Levelling-up and Regeneration Act 2023 c.55",
            "Human Rights Act 1998 (Articles 6, 8, A1P1)",
            "Equality Act 2010 s.149",
            "Compulsory Purchase Act 1965 (as applied by PA 2008 s.125)",
        ],
        "policy_basis": _policy_basis(tech),
        "sections": [
            {
                "n": "1",
                "heading": "Introduction and purpose",
                "body": (
                    f"This Statement of Reasons is submitted by the undertaker in support of "
                    f"its application for the {proj_name} Development Consent Order 20xx. "
                    f"It explains the need for the scheme, the legal and policy basis on "
                    f"which development consent is sought, the alternatives considered and "
                    f"rejected, and (where applicable) the justification for the powers of "
                    f"compulsory acquisition contained in the draft Order."
                ),
            },
            {
                "n": "2",
                "heading": "The undertaker",
                "body": (
                    "The undertaker is [Applicant Name], a company incorporated in England "
                    "and Wales with company number [COMPANY NUMBER]. The undertaker is a "
                    "special purpose vehicle wholly owned by [Parent / Sponsor] and has "
                    "been established for the purpose of developing, owning and operating "
                    f"the {proj_name}. [TO POPULATE — ultimate beneficial ownership and "
                    "corporate structure diagram.]"
                ),
            },
            {
                "n": "3",
                "heading": "Description of the scheme",
                "body": _scheme_description(tech, cap, proj_name),
            },
            {
                "n": "4",
                "heading": "Need for the scheme",
                "body": _need_case(tech, accepted_on),
            },
            {
                "n": "5",
                "heading": "Policy support",
                "body": (
                    f"Development consent for the scheme is supported by the National Policy "
                    f"Statements designated under section 5 of the Planning Act 2008. The "
                    f"relevant NPS are {en1_cite}; {en3_cite}; and {en5_cite}. Under section "
                    f"104 of the 2008 Act, the Secretary of State must decide an application "
                    f"in accordance with the relevant NPS except to the extent that one of "
                    f"the exceptions in section 104(4) to (8) applies. Section 6 of this "
                    f"Statement addresses policy compliance paragraph-by-paragraph. "
                    f"[TO POPULATE — NPS compliance matrix.]"
                ),
            },
            {
                "n": "6",
                "heading": "Alternatives considered",
                "body": _alternatives_discussion(tech),
            },
            {
                "n": "7",
                "heading": "Environmental effects and mitigation",
                "body": (
                    "The environmental effects of the scheme, the mitigation proposed and "
                    "the residual effects are reported in full in the Environmental "
                    "Statement (ES) submitted under Reg 5(2)(g). The ES is EIA development "
                    "under the Infrastructure Planning (Environmental Impact Assessment) "
                    "Regulations 2017 (SI 2017/572). Where significant effects remain, the "
                    "undertaker considers that the benefits of the scheme outweigh those "
                    "residual effects, having regard to paragraph [x] of NPS EN-1."
                ),
            },
            {
                "n": "8",
                "heading": "The case for compulsory acquisition"
                           if cpo_sought
                           else "Land ownership and rights (no compulsory acquisition sought)",
                "body": _ca_case(cpo_sought, proj_name),
            },
            {
                "n": "9",
                "heading": "Human Rights and Equalities",
                "body": _human_rights_section(cpo_sought),
            },
            {
                "n": "10",
                "heading": "Funding and deliverability",
                "body": (
                    "A Funding Statement is provided separately under Reg 5(2)(f) setting "
                    "out the resources available to implement the scheme (including any "
                    "compulsory acquisition compensation liabilities) and the timescale over "
                    "which they are expected to be available — per DCLG Guidance paragraph 17."
                ),
            },
            {
                "n": "11",
                "heading": "Conclusion",
                "body": (
                    "The undertaker respectfully requests that the Secretary of State grants "
                    "development consent for the scheme in the terms of the draft Order "
                    f"(with such modifications as may be agreed). The {proj_name} is needed, "
                    "is supported by the relevant National Policy Statements, and (where "
                    "compulsory acquisition is sought) satisfies the tests in section 122 "
                    "of the 2008 Act, the DCLG Guidance and the Human Rights Act 1998."
                ),
            },
        ],
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _policy_basis(tech: str) -> list[str]:
    base = [
        "NPS EN-1: Overarching National Policy Statement for Energy (January 2024)",
        "NPS EN-5: Electricity Networks Infrastructure (January 2024)",
        "NPPF (December 2024) — material consideration, paragraphs 162, 165, 168",
    ]
    if tech == "solar":
        base.insert(1, "NPS EN-3: Renewable Energy Infrastructure (January 2024), Part 2 — Solar Photovoltaic")
    elif tech in ("onshore_wind", "offshore_wind"):
        base.insert(1, "NPS EN-3: Renewable Energy Infrastructure (January 2024), Part 3 — Onshore/Offshore Wind")
    elif tech == "bess":
        base.insert(1, "NPS EN-1 (January 2024) paragraphs on electricity storage; Smart Systems and Flexibility Plan 2021")
    elif tech == "dc":
        base.insert(1, "Secretary of State direction under s.35 PA 2008 (Business or Commercial Projects); National Data Infrastructure Strategy 2025")
    return base


def _scheme_description(tech: str, cap, proj_name: str) -> str:
    cap_txt = f"up to {cap:.0f} MW" if isinstance(cap, (int, float)) else f"up to {cap} MW"
    if tech == "solar":
        return (
            f"The scheme comprises the construction and operation of the {proj_name}, a solar "
            f"photovoltaic generating station with nameplate capacity {cap_txt}, together with "
            f"an associated electricity storage facility, on-site substation, underground and "
            f"overhead grid connection infrastructure, internal access tracks, temporary "
            f"construction compounds, landscape and biodiversity mitigation, and ancillary "
            f"works. The scheme is described in full in Schedule 1 to the draft Order, shown "
            f"on the Works Plans, and is the subject of the Environmental Statement."
        )
    if tech == "bess":
        return (
            f"The scheme comprises the construction and operation of the {proj_name}, a "
            f"{cap_txt} battery energy storage system (BESS), with associated on-site "
            f"substation, grid connection infrastructure, fire suppression, thermal "
            f"management and ancillary works."
        )
    if tech == "dc":
        return (
            f"The scheme comprises the construction and operation of the {proj_name}, a data "
            f"centre campus with up to {cap_txt} of IT load, including data halls, mechanical "
            f"and electrical plant, standby generators and fuel storage, an on-site substation, "
            f"grid connection and fibre infrastructure, and ancillary works."
        )
    return f"[TO POPULATE — scheme description for {tech}, {cap_txt}.]"


def _need_case(tech: str, accepted_on: Optional[date] = None) -> str:
    en1_cite = _nps_cite("en1", accepted_on)
    en3_cite = _nps_cite("en3", accepted_on)
    common = (
        "The United Kingdom is committed to a legally-binding target of net zero greenhouse "
        "gas emissions by 2050 under section 1 of the Climate Change Act 2008 (as amended by "
        "the 2019 Order). The Sixth Carbon Budget (2033-37) and the Clean Power 2030 Action "
        "Plan (DESNZ, December 2024) set out the Government's plan to decarbonise the "
        f"electricity system by 2030. {en1_cite} confirms 'urgent' and 'critical' need for "
        "new low-carbon electricity infrastructure (EN-1 Part 3 — need for new energy NPS "
        "infrastructure). "
    )
    if tech == "solar":
        return (
            common
            + f"{en3_cite} Part 2 confirms that large-scale solar PV is required to "
            "meet the Government's ambition of 70 GW of solar PV capacity by 2035. The scheme "
            "contributes directly to this need. [TO POPULATE — site-specific MWh per annum, "
            "CO2 displacement at grid carbon intensity, homes equivalent.]"
        )
    if tech == "bess":
        return (
            common
            + "Large-scale electricity storage is required to balance the increasing proportion "
            "of variable renewables on the system. The British Energy Security Strategy (April "
            "2022) and the NESO Future Energy Scenarios (2024) both identify a step change in "
            "battery storage capacity as a pre-condition for Clean Power 2030."
        )
    if tech == "dc":
        return (
            common
            + "The UK's digital infrastructure is critical national infrastructure (designated "
            "September 2024). Data centre capacity is needed to support AI, cloud computing and "
            "public services, as set out in the National Data Infrastructure Strategy (2025) "
            "and the AI Opportunities Action Plan (January 2025). The scheme will provide "
            "[TO POPULATE — IT load MW, jobs, economic contribution]."
        )
    return common + "[TO POPULATE — technology-specific need case.]"


def _alternatives_discussion(tech: str) -> str:
    return (
        "Under paragraph 4.4 of NPS EN-1 and Regulation 14 of the Infrastructure Planning "
        "(EIA) Regulations 2017, the undertaker has considered reasonable alternatives. The "
        "alternatives considered are: (a) the 'do nothing' alternative; (b) alternative "
        "sites; (c) alternative layouts and technologies; (d) alternative grid connection "
        "routes. Each is reported in Chapter 3 of the Environmental Statement. The preferred "
        "scheme is selected on the basis of deliverability, environmental impact, policy "
        "support and economic efficiency. [TO POPULATE — site selection and optioneering "
        "narrative, cross-referenced to ES Chapter 3.]"
    )


def _ca_case(cpo_sought: bool, proj_name: str) -> str:
    if not cpo_sought:
        return (
            "The undertaker has secured (or is in advanced negotiations to secure) all land "
            "interests required for the scheme through freely-negotiated option agreements "
            "and leases with the relevant landowners. Accordingly, no powers of compulsory "
            "acquisition are sought in the draft Order. The Book of Reference is nonetheless "
            "provided under Reg 5(2)(i) to identify Category 1 interests, Category 2 rights, "
            "and Category 3 holders who may be entitled to notice."
        )
    return (
        f"Powers of compulsory acquisition are sought in Part 5 of the draft Order. The "
        f"undertaker confirms that, for each plot of land subject to compulsory acquisition "
        f"as identified in the Book of Reference: "
        f"(a) there is a 'compelling case in the public interest' per section 122 of the "
        f"Planning Act 2008 and paragraph 13 of the DCLG Guidance; "
        f"(b) the land is required for the authorised development, or to facilitate it, or "
        f"is incidental to it (s.122(2)); "
        f"(c) the statutory purposes for which the land may be acquired engage s.122(3) and "
        f"are set out article-by-article in the Explanatory Memorandum; "
        f"(d) reasonable alternatives to compulsory acquisition have been considered and "
        f"rejected — the undertaker has actively sought to acquire the required interests "
        f"by private treaty (see Compulsory Acquisition negotiation log at Appendix [ref]); "
        f"(e) the Human Rights Act 1998 proportionality test is satisfied (see Section 9); "
        f"(f) the undertaker has sufficient resources to meet the compensation liability "
        f"arising from the proposed acquisition (see Funding Statement). "
        f"The {proj_name} cannot proceed without the compulsory acquisition powers sought "
        f"because [TO POPULATE — site-specific justification for each plot]."
    )


def _human_rights_section(cpo_sought: bool) -> str:
    if not cpo_sought:
        return (
            "The undertaker has considered the provisions of the European Convention on "
            "Human Rights as given effect by the Human Rights Act 1998 and the public sector "
            "equality duty under section 149 of the Equality Act 2010. No compulsory "
            "acquisition powers are sought and the only engagement of Article 8 and A1P1 "
            "arises from such temporary construction-phase impacts as are identified in the "
            "Environmental Statement. Those impacts are mitigated per the Outline CEMP."
        )
    return (
        "The undertaker has carefully considered the interference with the rights of the "
        "owners and occupiers of the Order land under Article 8 (respect for private and "
        "family life, home and correspondence), Article 1 of the First Protocol (protection "
        "of property) and Article 6 (right to a fair hearing). The undertaker considers "
        "that: (a) the interference is lawful, being authorised by the Order (once made) "
        "in accordance with the 2008 Act; (b) it pursues the legitimate public interest of "
        "delivering nationally significant infrastructure aligned to the UK's net-zero and "
        "energy security policies; and (c) it is proportionate, being no more extensive "
        "than is necessary. Compensation is payable in accordance with the Compulsory "
        "Purchase Act 1965 and the Land Compensation Act 1973. An Equality Impact "
        "Assessment has been prepared and is provided as an appendix to the Environmental "
        "Statement."
    )
