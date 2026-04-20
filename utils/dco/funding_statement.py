"""
Funding Statement — Reg 5(2)(f).

Required by Reg 5(2)(f) and paragraph 17 of DCLG Guidance "Planning Act
2008: Procedures for the compulsory acquisition of land" (Sept 2013 rev.
2023). The Funding Statement must set out:
  - How the undertaker will fund the scheme (including construction and
    operation);
  - Where compulsory acquisition is sought, that the undertaker has
    resources available to meet the compensation liability arising from
    any acquisition of interests in land and any claims under the Land
    Compensation Act 1973;
  - The timescale within which resources are expected to be available.

Citation: "In fulfilment of Regulation 5(2)(f) of the Infrastructure
Planning (Applications: Prescribed Forms and Procedure) Regulations 2009
(SI 2009/2264)."
"""

from __future__ import annotations

from datetime import datetime


def build_funding_statement(project: dict, *, cpo_sought: bool = False) -> dict:
    proj_name = project.get("name") or "[Project]"
    cap = project.get("capacity_mw")
    cap_mw = cap if isinstance(cap, (int, float)) else 0

    # Indicative capex — Princeps standard rates; full FS would reference a real model
    capex_m = _indicative_capex(project.get("workload_type") or project.get("technology") or "solar", cap_mw)
    opex_m_per_yr = round(capex_m * 0.025, 1)  # ~2.5% opex
    ca_compensation_reserve_m = round(capex_m * 0.03, 1) if cpo_sought else 0

    return {
        "document_title": "Funding Statement",
        "regulation_citation": (
            "In fulfilment of Regulation 5(2)(f) of the Infrastructure Planning "
            "(Applications: Prescribed Forms and Procedure) Regulations 2009 "
            "(SI 2009/2264) and paragraph 17 of DCLG Guidance: Planning Act "
            "2008 — Procedures for the compulsory acquisition of land "
            "(September 2013, rev. 2023)."
        ),
        "sections": [
            {
                "n": "1",
                "heading": "Introduction",
                "body": (
                    f"This Funding Statement accompanies the application by the undertaker for "
                    f"the {proj_name} Development Consent Order 20xx. It confirms the "
                    f"undertaker's financial ability to fund: (a) the design, construction "
                    f"and commissioning of the authorised development; (b) its operation and "
                    f"maintenance; (c) where applicable, the compensation liability arising "
                    f"from compulsory acquisition; and (d) decommissioning at the end of the "
                    f"consented period."
                ),
            },
            {
                "n": "2",
                "heading": "The undertaker and its corporate structure",
                "body": (
                    "The undertaker is [Applicant SPV], a special purpose vehicle wholly "
                    "owned by [Parent Sponsor]. The SPV is capitalised by equity subscription "
                    "from the parent and is planned to reach financial close under a senior "
                    "debt facility with a syndicate of commercial banks. [TO POPULATE — "
                    "corporate structure diagram, ultimate beneficial ownership, sponsor "
                    "track record.]"
                ),
            },
            {
                "n": "3",
                "heading": "Estimated costs",
                "body": (
                    f"The indicative capital cost of the scheme is £{capex_m:,.0f}M, with "
                    f"indicative annual operating costs of £{opex_m_per_yr:,.1f}M. These "
                    f"figures are derived from comparable schemes and Princeps' internal "
                    f"cost model; a full bankable CAPEX estimate will be provided at "
                    f"financial close."
                ),
                "tables": [
                    {
                        "title": "Table 3.1 — Indicative cost envelope",
                        "columns": ["Cost item", "£M", "Source"],
                        "rows": [
                            ["Design and development", f"{capex_m * 0.05:,.1f}", "Princeps benchmark"],
                            ["Module / plant supply", f"{capex_m * 0.55:,.1f}", "Manufacturer EPC"],
                            ["Balance of plant / civils", f"{capex_m * 0.20:,.1f}", "EPC contractor"],
                            ["Grid connection and substation", f"{capex_m * 0.10:,.1f}", "DNO CCCM v19"],
                            ["Contingency", f"{capex_m * 0.08:,.1f}", "Lender-grade 8%"],
                            ["Land acquisition (freely negotiated)", f"{capex_m * 0.02:,.1f}", "Option agreements"],
                            [
                                "Compulsory acquisition compensation reserve",
                                f"{ca_compensation_reserve_m:,.1f}" if cpo_sought else "N/A",
                                "DCLG Guidance para 17" if cpo_sought else "No CPO sought",
                            ],
                            ["TOTAL indicative CAPEX", f"{capex_m + ca_compensation_reserve_m:,.1f}", ""],
                        ],
                    },
                ],
            },
            {
                "n": "4",
                "heading": "Sources of funding",
                "body": (
                    "The undertaker proposes to fund the scheme through a combination of: "
                    "(a) equity from [Parent Sponsor] and (potentially) institutional "
                    "co-investors; and (b) senior debt under a project finance facility "
                    "structured to the Loan Market Association Investment Grade Facility "
                    "Agreement precedent. A target gearing ratio of 60–70% debt / 30–40% "
                    "equity is assumed. [TO POPULATE — lead arrangers, term sheet status, "
                    "equity commitment letters.]"
                ),
            },
            {
                "n": "5",
                "heading": "Compulsory acquisition compensation" if cpo_sought else "Land acquisition (no CA sought)",
                "body": (
                    f"A compensation reserve of £{ca_compensation_reserve_m:,.1f}M has been "
                    f"set aside to meet the potential liability arising from the compulsory "
                    f"acquisition of interests in land within the Order limits, any claims "
                    f"under Part 1 of the Land Compensation Act 1973, and statutory interest. "
                    f"The reserve is based on independent valuation advice from [Red Book "
                    f"valuer] (see Appendix A). The undertaker confirms that the reserve is "
                    f"available for the full 5-year validity window of the CA powers per "
                    f"article 23 of the draft Order. "
                    if cpo_sought else
                    "No powers of compulsory acquisition are sought. All land within the "
                    "Order limits is subject to either freehold ownership by the undertaker "
                    "or option agreements / leases on commercial terms with the relevant "
                    "landowners. [TO POPULATE — schedule of option agreements.]"
                ),
            },
            {
                "n": "6",
                "heading": "Timescale of funding availability",
                "body": (
                    "Equity is available from the date of the Order being made. Senior debt "
                    "drawdown is expected to coincide with commencement of construction, "
                    "subject to conditions precedent typical of project finance facilities "
                    "(planning permission / DCO, grid connection agreement executed, EPC "
                    "contract executed, O&M contract executed, insurance in place). The "
                    "compulsory acquisition compensation reserve (where applicable) is held "
                    "on a ring-fenced basis and is available from the date of the Order "
                    "being made until expiry of the CA time-limit under article 23."
                ),
            },
            {
                "n": "7",
                "heading": "Decommissioning security",
                "body": (
                    "A decommissioning bond or equivalent security will be provided at the "
                    "end of the operational life of the scheme to secure the undertaker's "
                    "obligations under requirement R11 of the draft Order. The form and "
                    "quantum of that security will be agreed with the relevant local "
                    "authority prior to commencement of operation."
                ),
            },
            {
                "n": "8",
                "heading": "Supporting documents",
                "body": (
                    "[TO POPULATE — letter of comfort from sponsor, term sheet from lead "
                    "arranger, Red Book valuation of land interests, Companies House filings, "
                    "latest audited accounts of parent, evidence of committed equity.]"
                ),
            },
        ],
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _indicative_capex(tech: str, cap_mw: float) -> float:
    """Princeps indicative £/MW benchmarks — for skeleton only."""
    if cap_mw <= 0:
        return 0.0
    if tech == "solar":
        return round(cap_mw * 0.85, 1)  # £0.85M / MW (2025 UK solar)
    if tech == "bess":
        return round(cap_mw * 0.60, 1)  # £0.60M / MW (1h duration)
    if tech == "dc":
        return round(cap_mw * 8.0, 1)  # £8M / MW IT load
    if tech in ("onshore_wind", "wind"):
        return round(cap_mw * 1.3, 1)
    if tech == "offshore_wind":
        return round(cap_mw * 2.5, 1)
    return round(cap_mw * 1.0, 1)
