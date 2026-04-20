"""Python-side glue for the Princeps paperwork partials.

BOT-R1 cross-cutting scaffolding. These helpers are deliberately isolated from
the main render pipeline so that each pack-rewrite bot can decide how to wire
them in without a shared edit to `utils/report_renderer.py` or similar.

Usage (from a pack bot):

    from jinja2 import Environment
    from templates.report._partials.helpers import register_jinja_helpers

    env = Environment(...)
    register_jinja_helpers(env)

    # Now `{{ regcite("G99_v2") }}` works inside the template.

The `regcite_lookup` function attempts to import
`app.regulatory.versions` (BOT-R2 deliverable). If that module is not
importable at render time, it silently falls back to a hard-coded canonical
table so packs never crash.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical fallback table.
#
# Mirrors the rows in docs/audits/industry_standards_index.md. Only add / edit
# here when that index changes. This table is the fallback when
# app.regulatory.versions is not importable.
# ---------------------------------------------------------------------------

_FALLBACK_REGCITES: Dict[str, Dict[str, str]] = {
    # Grid
    "G99_v2": {
        "title": "ENA Engineering Recommendation G99",
        "version": "Issue 2, 10 March 2025",
        "publisher": "Energy Networks Association",
        "url": "https://dcode.org.uk/assets/250307ena-erec-g99-issue-2-(2025).pdf",
        "note": "Storage-inclusive requirements mandatory from 1 March 2026.",
    },
    "G100_v2": {
        "title": "ENA EREC G100 — Export Limitation Schemes",
        "version": "Issue 2 (2023), Amendment 3",
        "publisher": "Energy Networks Association",
        "url": "https://www.energynetworks.org/industry-hub/resource-library/",
        "note": "",
    },
    "P28": {
        "title": "ENA EREC P28 — Voltage Fluctuations",
        "version": "Issue 2, 2019",
        "publisher": "Energy Networks Association",
        "url": "https://www.energynetworks.org/",
        "note": "",
    },
    "P29": {
        "title": "ENA EREC P29 — Voltage Unbalance Limits",
        "version": "1990",
        "publisher": "Energy Networks Association",
        "url": "https://www.energynetworks.org/",
        "note": "",
    },
    "DCode_v43": {
        "title": "UK Distribution Code",
        "version": "v43, 2024",
        "publisher": "DCode Panel",
        "url": "https://dcode.org.uk/",
        "note": "",
    },
    "GridCode_v6r24": {
        "title": "NESO GB Grid Code",
        "version": "Issue 6 Revision 24 (2025)",
        "publisher": "NESO",
        "url": "https://www.neso.energy/industry-information/codes/grid-code",
        "note": "",
    },
    "ESQCR_2002": {
        "title": "Electricity Safety, Quality and Continuity Regulations 2002",
        "version": "SI 2002/2665, as amended",
        "publisher": "UK Government",
        "url": "https://www.legislation.gov.uk/uksi/2002/2665",
        "note": "",
    },
    "CCCM_v19": {
        "title": "Common Connection Charging Methodology",
        "version": "v19, 2024",
        "publisher": "Energy Networks Association",
        "url": "https://www.energynetworks.org/industry-hub/connections/common-connection-charging-methodology",
        "note": "",
    },
    "TMO4_Gate2": {
        "title": "NESO Connections Reform TMO4+ Gate 2",
        "version": "Ofgem approved 15 Apr 2025; TMO4+ live 10 Jun 2025",
        "publisher": "Ofgem / NESO",
        "url": "https://www.neso.energy/industry-information/connections-reform/connections-reform-timeline",
        "note": (
            "Gate 2 Phase 1 transmission / large-embedded offers issue mid-May → mid-Sep 2026; "
            "distribution offers early Jul → mid-Nov 2026. Queue reduced from ~700 GW to 283 GW."
        ),
    },
    # Planning TCPA
    "NPPF_2024": {
        "title": "National Planning Policy Framework",
        "version": "December 2024 edition (published 12 Dec 2024)",
        "publisher": "MHCLG",
        "url": "https://assets.publishing.service.gov.uk/media/67aafe8f3b41f783cca46251/NPPF_December_2024.pdf",
        "note": "Renewables paras: 162 (climate), 165 (suitable areas), 168 (determination test).",
    },
    "1APP_v6": {
        "title": "Planning Portal 1APP Standard Application Form",
        "version": "v6 (2023)",
        "publisher": "Planning Portal",
        "url": "https://www.planningportal.co.uk/services/help/faq/1app-standard-application-form",
        "note": "",
    },
    "EIA_Regs_2017": {
        "title": "Town & Country Planning (EIA) Regulations 2017",
        "version": "SI 2017/571, amended 2018, 2020",
        "publisher": "UK Government",
        "url": "https://www.legislation.gov.uk/uksi/2017/571",
        "note": "",
    },
    "EN1_2024": {
        "title": "Overarching National Policy Statement for Energy (EN-1)",
        "version": "2025 revision (published 12 Nov 2025)",
        "publisher": "DESNZ",
        "url": "https://www.gov.uk/government/publications/overarching-national-policy-statement-for-energy-en-1-2025",
        "note": (
            "2025 revision supersedes the Nov 2023 refresh (designated 17 Jan 2024) "
            "for DCO applications accepted for examination from the in-force date. "
            "Nov 2023 refresh continues to apply to earlier acceptances — use acceptance-date logic."
        ),
    },
    "EN3_2024": {
        "title": "NPS for Renewable Energy Infrastructure (EN-3)",
        "version": "2025 revision (in force 6 Jan 2026)",
        "publisher": "DESNZ",
        "url": "https://www.gov.uk/government/publications/national-policy-statement-for-renewable-energy-infrastructure-en-3-2025",
        "note": (
            "2025 revision in force 6 January 2026 — applies to DCO applications accepted "
            "for examination on or after that date. Applications accepted before remain "
            "governed by the Nov 2023 refresh (designated 17 Jan 2024). Use acceptance-date logic."
        ),
    },
    "EN5_2024": {
        "title": "NPS for Electricity Networks Infrastructure (EN-5)",
        "version": "2025 revision (published 12 Nov 2025)",
        "publisher": "DESNZ",
        "url": "https://www.gov.uk/government/publications/national-policy-statements-for-energy-infrastructure",
        "note": (
            "2025 revision supersedes the Nov 2023 refresh (designated 17 Jan 2024) "
            "subject to the 21-sitting-day parliamentary period. Applications accepted "
            "before the 2025 in-force date remain governed by the earlier refresh."
        ),
    },
    "TCPA_1990": {
        "title": "Town and Country Planning Act 1990",
        "version": "1990 c.8, as amended",
        "publisher": "UK Government",
        "url": "https://www.legislation.gov.uk/ukpga/1990/8",
        "note": "",
    },
    # NSIP
    "PA_2008": {
        "title": "Planning Act 2008",
        "version": "c.29, as amended by LURA 2023",
        "publisher": "UK Government",
        "url": "https://www.legislation.gov.uk/ukpga/2008/29",
        "note": "",
    },
    "IPA_Regs_2009": {
        "title": "Infrastructure Planning (Applications: Prescribed Forms and Procedure) Regulations 2009",
        "version": "SI 2009/2264, amended through 2024",
        "publisher": "UK Government",
        "url": "https://www.legislation.gov.uk/uksi/2009/2264",
        "note": "",
    },
    # BNG
    "EA_2021": {
        "title": "Environment Act 2021 s.98 + Schedule 14",
        "version": "c.30. BNG mandatory 12 Feb 2024 (major) / 2 Apr 2024 (minor)",
        "publisher": "UK Government",
        "url": "https://www.legislation.gov.uk/ukpga/2021/30",
        "note": "",
    },
    "StatBioMetric_v1": {
        "title": "Statutory Biodiversity Metric",
        "version": "v1.0, 29 November 2023",
        "publisher": "Natural England",
        "url": "https://www.gov.uk/government/publications/statutory-biodiversity-metric-tools-and-guides",
        "note": "Only metric accepted for s.98 mandatory BNG from 12 Feb 2024.",
    },
    "UKHab_v2": {
        "title": "UK Habitat Classification (UKHab)",
        "version": "v2.0, 2023",
        "publisher": "UKHab Partnership",
        "url": "https://www.ukhab.org/",
        "note": "",
    },
    # H&S
    "CDM_2015": {
        "title": "Construction (Design and Management) Regulations 2015",
        "version": "SI 2015/51",
        "publisher": "UK Government",
        "url": "https://www.legislation.gov.uk/uksi/2015/51",
        "note": "",
    },
    "HSE_L153": {
        "title": "HSE L153 — Managing Health and Safety in Construction (ACoP)",
        "version": "2015, reprinted 2019",
        "publisher": "HSE Books",
        "url": "https://www.hse.gov.uk/pubns/books/l153.htm",
        "note": "",
    },
    # Finance / valuation
    "RICS_RedBook_2025": {
        "title": "RICS Valuation — Global Standards (Red Book)",
        "version": "Effective 31 January 2025",
        "publisher": "RICS",
        "url": "https://www.rics.org/profession-standards/rics-standards-and-guidance/sector-standards/valuation-standards/red-book",
        "note": "",
    },
    "RICS_FVA_2021": {
        "title": "RICS Professional Statement — Financial Viability in Planning",
        "version": "2nd edition, 2021 (effective 1 May 2021)",
        "publisher": "RICS",
        "url": "https://www.rics.org/profession-standards/rics-standards-and-guidance/sector-standards/real-estate-standards/financial-viability-in-planning",
        "note": "",
    },
    "PRA_SS3_19": {
        "title": "PRA SS3/19 — Climate Financial Risk",
        "version": "April 2019, refreshed 2023",
        "publisher": "Bank of England / PRA",
        "url": "https://www.bankofengland.co.uk/prudential-regulation/publication/2019/enhancing-banks-and-insurers-approaches-to-managing-the-financial-risks-from-climate-change-ss",
        "note": "",
    },
    # EIA technical
    "IEMA_ES_8": {
        "title": "IEMA Guidelines for Environmental Impact Assessment",
        "version": "8th edition, 2024",
        "publisher": "IEMA",
        "url": "https://www.iema.net/",
        "note": "",
    },
    "GLVIA3": {
        "title": "Guidelines for Landscape and Visual Impact Assessment (GLVIA)",
        "version": "3rd edition, 2013",
        "publisher": "Landscape Institute / IEMA",
        "url": "https://landscapeinstitute.org/",
        "note": "",
    },
    "CAP738": {
        "title": "CAA CAP 738 — Solar Glare Assessment",
        "version": "2019",
        "publisher": "Civil Aviation Authority",
        "url": "https://www.caa.co.uk/publication/download/16600",
        "note": "",
    },
    "BS4142_2019": {
        "title": "BS 4142:2014+A1:2019 — Industrial & Commercial Sound",
        "version": "2019",
        "publisher": "BSI",
        "url": "https://shop.bsigroup.com/",
        "note": "",
    },
    # DC
    "ISO_30134_2": {
        "title": "ISO/IEC 30134-2 — Power Usage Effectiveness (PUE)",
        "version": "2016",
        "publisher": "ISO",
        "url": "https://www.iso.org/standard/63451.html",
        "note": "",
    },
    "ISO_30134_9": {
        "title": "ISO/IEC 30134-9 — Water Usage Effectiveness (WUE)",
        "version": "2022",
        "publisher": "ISO",
        "url": "https://www.iso.org/standard/76708.html",
        "note": "",
    },
    "EU_EED_Art12": {
        "title": "EU Energy Efficiency Directive 2023/1791 Art.12",
        "version": "2023, reporting from May 2024",
        "publisher": "European Union",
        "url": "https://eur-lex.europa.eu/eli/dir/2023/1791/oj",
        "note": "",
    },
}


def regcite_lookup(key: str) -> Dict[str, str]:
    """Resolve a citation key to a formatted dict.

    Tries BOT-R2's `app.regulatory.versions` module first; falls back to the
    hard-coded table above. Unknown keys return a clearly-marked stub so the
    pack renders a visible TODO rather than crashing.
    """
    try:
        from app.regulatory import versions as _versions  # type: ignore

        if hasattr(_versions, "lookup"):
            res = _versions.lookup(key)
            if res:
                return res
        if hasattr(_versions, "CITATIONS") and key in _versions.CITATIONS:
            return _versions.CITATIONS[key]
    except Exception as exc:
        log.debug(
            "regcite_lookup: app.regulatory.versions not available, "
            "using fallback (%s)", exc
        )

    if key in _FALLBACK_REGCITES:
        return _FALLBACK_REGCITES[key]

    return {
        "title": f"[UNRESOLVED CITATION: {key}]",
        "version": "TO POPULATE",
        "publisher": "TO POPULATE",
        "url": "",
        "note": "Citation key not found in app.regulatory.versions or fallback table.",
    }


def format_regcite(key: str) -> str:
    """Format a citation key as a single inline string."""
    c = regcite_lookup(key)
    parts = [c["title"], c["version"]]
    if c.get("publisher"):
        parts.append(c["publisher"])
    return " — ".join(p for p in parts if p)


def format_prov_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a provenance entry so missing fields render as TO POPULATE."""
    retrieved = entry.get("retrieved_utc") or entry.get("retrieved") or ""
    if not retrieved:
        retrieved = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    return {
        "n": entry.get("n", "?"),
        "claim": entry.get("claim") or "TO POPULATE",
        "source": entry.get("source") or "TO POPULATE",
        "url": entry.get("url") or "",
        "retrieved_utc": retrieved,
        "method": entry.get("method") or "unspecified",
    }


def default_revision_code(
    project_code: Optional[str] = None,
    pack_type: Optional[str] = None,
    rev: Optional[str] = None,
) -> str:
    """Build a PROJ-PACK-REV-NN revision reference code."""
    p = project_code or "PROJ"
    pt = pack_type or "PACK"
    r = rev or "P01"
    return f"{p}-{pt}-{r}"


def register_jinja_helpers(env: Any) -> None:
    """Register the partials' helpers on a Jinja `Environment`.

    Pack-rewrite bots call this once after constructing their Jinja env.
    No edit to the shared render pipeline is required.
    """
    env.globals.setdefault("regcite", format_regcite)
    env.globals.setdefault("regcite_dict", regcite_lookup)
    env.globals.setdefault("default_revision_code", default_revision_code)
    env.filters.setdefault("prov_entry", format_prov_entry)
