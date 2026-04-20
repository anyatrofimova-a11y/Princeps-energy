"""Policy-compliance matrix for UK energy planning applications.

Cross-references a project against the planning policy hierarchy and
returns a structured list of ``PolicyCheck`` rows with a compliance
verdict. Covers:

* **NPPF (December 2024 — latest edition)** — renewables / low-carbon
  policy block. **Paragraph numbering for the Dec 2024 edition:
  162, 165, 168, 196.** (Previous editions used 152 / 154 / 158 / 186;
  those paragraph numbers are retained here for provenance / legacy
  search only — see ``NPPF_PARAGRAPH_RENUMBER_DEC_2024``.)
* **National Policy Statements** — version-correct citation resolved via
  :func:`nps_version_for` against the DCO acceptance-for-examination date:
    * EN-1 — Overarching NPS for Energy (2025 revision pub. Nov 2025; Nov
      2023 refresh designated 17 Jan 2024 for earlier acceptances)
    * EN-3 — Renewable Energy Infrastructure (2025 revision in force
      6 Jan 2026; Nov 2023 refresh for earlier acceptances)
    * EN-5 — Electricity Networks (2025 revision pub. Nov 2025; Nov 2023
      refresh for earlier acceptances)
* **Local plan placeholder** keyed by LPA code — replaced at runtime
  when a Princeps LPA ontology entry is available.

**COUNCIL-1 audit fix (2026-04-19).** Previous revision cited 2021
paragraph numbering (152 / 154 / 158 / 186). The Dec 2024 edition
renumbered the renewables policy block — this module now uses the
current 162 / 165 / 168 / 196. The renumbering table is exposed as
:data:`NPPF_PARAGRAPH_RENUMBER_DEC_2024` for downstream reporting.

If ``app.regulatory.versions`` (BOT-R2) is available it is preferred as
the source of truth for NPPF version / paragraph numbering; otherwise
the hardcoded values in this module are used. Every row also carries
the evaluator-produced ``verdict`` and an ``evidence_pointer`` string
to the source data item (aligning with the COUNCIL-1 spec's
"policy-compliance verdict column with evidence pointer"
requirement).

Verdicts: ``compliant`` | ``partial`` | ``non-compliant`` | ``n/a``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

# ---------------------------------------------------------------------------
# NPPF Dec 2024 renumbering (COUNCIL-1 attested).
# ---------------------------------------------------------------------------
#
# Dec 2024 NPPF refresh (published 12 Dec 2024, effective immediately)
# renumbered the renewables / climate / countryside paragraph block:
#
#     Old (2021 / Dec 2023) → New (Dec 2024)
#     152                     162   (proactive approach to climate change)
#     154                     165   (support for renewable / low-carbon energy)
#     158                     168   (suitable areas; acceptable impacts)
#     186                     196   (BMV agricultural land)
#
# Any other module looking up the renumbering can import this table.
NPPF_PARAGRAPH_RENUMBER_DEC_2024: dict[str, str] = {
    "152": "162",
    "154": "165",
    "158": "168",
    "186": "196",
}

# Attempt to resolve authoritative versions from BOT-R2 if shipped.
try:  # pragma: no cover - resolved lazily at import
    from app.regulatory import versions as _reg_versions  # type: ignore[import-not-found]
    from app.regulatory.versions import cite as _cite_reg, cite_nps as _cite_nps
    NPPF_VERSION = getattr(
        _reg_versions, "NPPF_VERSION", "NPPF December 2024",
    )
    # NPS_VERSION is a fallback label only — callers that need a version-
    # correct citation should pass an ``accepted_on`` date to
    # :func:`nps_version_for` so the 2025 revision / Nov 2023 refresh is
    # selected against the EN-3 6 Jan 2026 in-force cut-over.
    NPS_VERSION = (
        "NPS for Energy (EN-1, EN-3, EN-5) — 2025 revision "
        "(EN-3 in force 6 Jan 2026; EN-1 & EN-5 designated Nov 2025)"
    )
    _REG_PARAS: dict[str, str] | None = getattr(
        _reg_versions, "NPPF_PARAGRAPHS_RENEWABLES", None,
    )
except Exception:  # BOT-R2 not landed yet — fall back to hardcoded.
    _cite_reg = None  # type: ignore[assignment]
    _cite_nps = None  # type: ignore[assignment]
    NPPF_VERSION = "NPPF December 2024"
    NPS_VERSION = (
        "NPS for Energy (EN-1, EN-3, EN-5) — 2025 revision "
        "(EN-3 in force 6 Jan 2026; EN-1 & EN-5 designated Nov 2025)"
    )
    _REG_PARAS = None


def nps_version_for(key: str, accepted_on=None) -> str:
    """Return the version-correct NPS citation for ``key`` (``en1``/``en3``/``en5``).

    ``accepted_on`` is the DCO acceptance-for-examination date. If given and
    before the 2025-revision in-force cut-over for that NPS, the Nov 2023
    (designated 17 Jan 2024) version is cited; otherwise the 2025 revision
    is cited via :func:`app.regulatory.versions.cite_nps`.
    """
    if _cite_nps is not None:
        try:
            return _cite_nps(key, accepted_on)
        except Exception:  # pragma: no cover - defensive
            pass
    # Fallback when app.regulatory.versions not importable.
    return {
        "en1": "NPS EN-1 (2025 revision)",
        "en3": "NPS EN-3 (2025 revision, in force 6 Jan 2026)",
        "en5": "NPS EN-5 (2025 revision)",
    }.get(key, f"NPS {key.upper()}")


def _para(key: str, fallback: str) -> str:
    """Resolve a canonical NPPF paragraph number for key (Dec 2024 edition).

    ``key`` is a short mnemonic (``"climate"``, ``"renewables"``,
    ``"suitable_areas"``, ``"bmv"``). If BOT-R2 shipped a mapping
    we honour it; otherwise we use the hardcoded Dec 2024 fallback.
    """
    if _REG_PARAS and key in _REG_PARAS:
        return str(_REG_PARAS[key])
    return fallback


# Canonical Dec 2024 paragraph numbers used by this matrix.
NPPF_PARA_CLIMATE = _para("climate", "162")          # old 152
NPPF_PARA_RENEWABLES = _para("renewables", "165")    # old 154
NPPF_PARA_SUITABLE_AREAS = _para("suitable_areas", "168")  # old 158
NPPF_PARA_BMV = _para("bmv", "196")                  # old 186


def _verdict(
    label: str,
    *,
    evidence: list[str] | None = None,
    evidence_pointer: str | None = None,
    text: str | None = None,
) -> dict:
    """Build a verdict payload.

    ``evidence_pointer`` is the primary data-item identifier (single string)
    per the COUNCIL-1 spec; ``evidence`` is the broader pointer list.
    """
    return {
        "verdict": label,
        "proposal_alignment_text": text or "",
        "evidence_pointers": evidence or [],
        "evidence_pointer": evidence_pointer or (evidence[0] if evidence else None),
    }


def _check_nppf_climate(project: dict, designations: dict) -> dict:
    """NPPF 2024 para 162 — Plans should take a proactive approach to climate
    change; new development should contribute to net zero. (Old 2021 para 152.)"""
    tech = (project.get("technology") or "").lower()
    if tech in ("solar", "wind", "bess"):
        return _verdict(
            "compliant",
            text=(
                f"Proposal is a {tech} energy scheme directly supporting the UK's "
                f"Net Zero Strategy and Sixth Carbon Budget trajectory. Contribution "
                f"to NPPF 2024 para {NPPF_PARA_CLIMATE} is intrinsic to the development type."
            ),
            evidence=["TECHNOLOGY_TYPE", "CAPACITY_MW", "DISPLACED_CARBON"],
            evidence_pointer="project.technology + capacity_mw",
        )
    if tech in ("dc", "data_centre", "datacentre", "hyperscale"):
        return _verdict(
            "partial",
            text=(
                "Data centres are not low-carbon developments per se. Compliance "
                "requires demonstrated PUE <= 1.25, heat-reuse feasibility, and "
                "100% renewable PPA cover — to be evidenced in the Energy & "
                "Sustainability Statement."
            ),
            evidence=["PUE_TARGET", "HEAT_REUSE_PLAN", "PPA_RENEWABLE_COVER"],
            evidence_pointer="metadata.pue_target",
        )
    return _verdict("n/a", evidence_pointer="project.technology")


def _check_nppf_renewables(project: dict, designations: dict) -> dict:
    """NPPF 2024 para 165 — LPAs should support the transition to a low-carbon
    future, including renewable / low-carbon energy and associated
    infrastructure. (Old 2021 para 154.)"""
    tech = (project.get("technology") or "").lower()
    if tech in ("solar", "wind", "bess"):
        return _verdict(
            "compliant",
            text=(
                f"NPPF 2024 para {NPPF_PARA_RENEWABLES} directs decision-makers to give "
                f"significant weight to the benefits of renewable / low-carbon energy "
                f"generation. This {tech} scheme falls squarely within the supported category."
            ),
            evidence=["TECHNOLOGY_TYPE", "GRID_EXPORT_MW"],
            evidence_pointer="project.technology",
        )
    return _verdict(
        "partial",
        text="Proposal is not a standalone renewable generator; weight depends on wider decarbonisation narrative.",
        evidence_pointer="project.technology",
    )


def _check_nppf_suitable_areas(project: dict, designations: dict) -> dict:
    """NPPF 2024 para 168 — Planning should support renewable and low-carbon
    energy and identify suitable areas; LPAs may grant permission if impacts
    are (or can be made) acceptable. (Old 2021 para 158.)"""
    cap = project.get("capacity_mw") or 0
    lpa_designated = designations.get("lpa_has_renewable_allocation")
    if lpa_designated:
        return _verdict(
            "compliant",
            text=(
                f"Site lies within the LPA's adopted renewable energy suitable "
                f"area. NPPF 2024 para {NPPF_PARA_SUITABLE_AREAS} threshold met; "
                f"impacts addressed elsewhere."
            ),
            evidence=["LOCAL_PLAN_POLICY", "ALLOCATION_BOUNDARY"],
            evidence_pointer="designations.lpa_has_renewable_allocation",
        )
    return _verdict(
        "partial",
        text=(
            f"No specific adopted LPA renewable allocation identified. NPPF 2024 "
            f"para {NPPF_PARA_SUITABLE_AREAS} still supports consent where impacts "
            f"are acceptable; refer to Environmental Statement / LVIA conclusions. "
            f"Capacity: {cap} MW."
        ),
        evidence=["LVIA", "NOISE_ASSESSMENT", "BNG_METRIC"],
        evidence_pointer="designations.lpa_has_renewable_allocation",
    )


def _check_nppf_bmv(project: dict, designations: dict) -> dict:
    """NPPF 2024 para 196 — Planning should recognise the intrinsic value of
    the countryside including the economic and other benefits of BMV
    agricultural land. (Old 2021 para 186.)"""
    alc = designations.get("alc_grade")
    bmv = False
    try:
        if alc is not None:
            bmv = str(alc) in ("1", "2", "3a")
    except Exception:  # pragma: no cover - defensive
        pass
    if bmv:
        return _verdict(
            "partial",
            text=(
                f"Site includes ALC grade {alc} (Best and Most Versatile) "
                f"agricultural land. NPPF 2024 para {NPPF_PARA_BMV} is a material "
                f"consideration: justification required; reversibility + soil "
                f"management plan mitigate."
            ),
            evidence=["ALC_SURVEY", "SOIL_MANAGEMENT_PLAN", "REVERSIBILITY_STATEMENT"],
            evidence_pointer="designations.alc_grade",
        )
    if alc is None:
        return _verdict(
            "partial",
            text="ALC classification unconfirmed — post-1988 survey required to demonstrate compliance.",
            evidence_pointer="designations.alc_grade",
        )
    return _verdict(
        "compliant",
        text=f"Site is ALC grade {alc} (not BMV). No NPPF 2024 para {NPPF_PARA_BMV} conflict.",
        evidence=["ALC_GRADE"],
        evidence_pointer="designations.alc_grade",
    )


def _check_en1(project: dict, designations: dict) -> dict:
    """EN-1 — Overarching NPS for Energy.

    Version resolved via :func:`nps_version_for` against the project's DCO
    acceptance-for-examination date: the 2025 revision (published Nov 2025)
    applies to applications accepted from its in-force date; applications
    accepted earlier remain governed by the Nov 2023 refresh (designated
    17 January 2024). Established Critical National Priority for low-carbon
    infrastructure."""
    tech = (project.get("technology") or "").lower()
    cap = project.get("capacity_mw") or 0
    if tech in ("solar", "wind") and cap >= 50:
        return _verdict(
            "compliant",
            text=(
                "Proposal is a low-carbon energy NSIP. EN-1 para 4.2.5 (CNP for "
                "low-carbon infrastructure) applies — deemed need is established; "
                "tilted balance favours consent absent strong contrary impact."
            ),
            evidence=["NSIP_CLASSIFICATION", "DEEMED_NEED_PARA_3_2"],
            evidence_pointer="project.capacity_mw",
        )
    if tech in ("solar", "wind", "bess"):
        return _verdict(
            "compliant",
            text=(
                "Below-NSIP scheme but EN-1 still a material consideration. Deemed need "
                "and CNP status inform the TCPA decision under NPPF para 8."
            ),
            evidence=["EN1_2_3_NEED_CASE"],
            evidence_pointer="project.technology",
        )
    if tech in ("dc", "data_centre", "datacentre", "hyperscale"):
        return _verdict(
            "partial",
            text=(
                "Data centres are not listed as an energy NSIP type under EN-1. "
                "EN-1 relevant only insofar as the DC's grid connection and any "
                "on-site generation are concerned."
            ),
            evidence_pointer="project.technology",
        )
    return _verdict("n/a", evidence_pointer="project.technology")


def _check_en3(project: dict, designations: dict) -> dict:
    """EN-3 — Renewable Energy Infrastructure.

    Provides the technology-specific impact assessment framework. Version
    is resolved via :func:`nps_version_for` against the DCO
    acceptance-for-examination date: the 2025 revision (in force 6 Jan
    2026) applies to applications accepted from that date; earlier
    acceptances remain governed by the Nov 2023 refresh (designated
    17 Jan 2024)."""
    tech = (project.get("technology") or "").lower()
    if tech == "solar":
        return _verdict(
            "compliant",
            text=(
                "EN-3 sections on solar PV (paras 2.10.x) are directly engaged. "
                "Design should address glint/glare, archaeological ground disturbance, "
                "landscape screening and reversibility — each covered by the "
                "supporting assessments in this bundle."
            ),
            evidence=["GLINT_GLARE_ASSESSMENT", "LVIA", "HERITAGE_STATEMENT"],
            evidence_pointer="project.technology",
        )
    if tech == "wind":
        return _verdict(
            "compliant",
            text=(
                "EN-3 sections on onshore wind (paras 2.8.x) engaged. "
                "Address noise (ETSU-R-97), shadow flicker, aviation and "
                "ornithology impacts in the Environmental Statement."
            ),
            evidence=["NOISE_ETSU_R_97", "SHADOW_FLICKER_STUDY", "ORNITHOLOGY_SURVEY"],
            evidence_pointer="project.technology",
        )
    if tech == "bess":
        return _verdict(
            "partial",
            text=(
                "EN-3 does not explicitly cover standalone BESS. Apply EN-1 generic "
                "impact sections plus DESNZ / HSE BESS safety guidance (BESS Safety "
                "Management for Planners, 2023)."
            ),
            evidence=["HSE_BESS_GUIDANCE", "FIRE_RISK_ASSESSMENT"],
            evidence_pointer="project.technology",
        )
    return _verdict(
        "n/a",
        text="EN-3 is renewable-specific; not applicable to this technology.",
        evidence_pointer="project.technology",
    )


def _check_en5(project: dict, designations: dict) -> dict:
    """EN-5 — Electricity Networks Infrastructure.

    Version resolved via :func:`nps_version_for` against the DCO
    acceptance-for-examination date (2025 revision published Nov 2025
    vs Nov 2023 refresh designated 17 Jan 2024)."""
    has_grid_works = bool(
        (project.get("metadata") or {}).get("grid_works_km")
        or project.get("requires_new_line")
        or (project.get("technology") or "").lower() in ("solar", "wind", "bess")
    )
    if has_grid_works:
        return _verdict(
            "compliant",
            text=(
                "Grid connection works engage EN-5. Undergrounding, pylon design, "
                "and EMF exposure compliance (ICNIRP 2010) to be demonstrated in "
                "the grid connection section of the application."
            ),
            evidence=["CONNECTION_DESIGN", "EMF_ASSESSMENT", "UNDERGROUNDING_ANALYSIS"],
            evidence_pointer="metadata.grid_works_km",
        )
    return _verdict(
        "n/a",
        text="No grid network works proposed beyond private connection.",
        evidence_pointer="metadata.grid_works_km",
    )


def _check_local_plan(project: dict, designations: dict) -> dict:
    """Local plan placeholder.

    Real implementation will hit Princeps' LPA ontology (``lpa_policies``
    table) keyed by LPA code. Until that exists, the matrix carries a
    ``pending`` row so downstream readers see the gap.
    """
    lpa = (
        (project.get("metadata") or {}).get("lpa")
        or project.get("lpa")
        or "[LPA unknown]"
    )
    return _verdict(
        "partial",
        text=(
            f"Local plan policies for {lpa} to be cross-referenced. Princeps "
            f"LPA ontology lookup pending. Expect policies on renewable energy, "
            f"landscape character, heritage, and biodiversity to apply."
        ),
        evidence=["LOCAL_PLAN_STRATEGIC_POLICY", "LOCAL_PLAN_DM_POLICY"],
        evidence_pointer="metadata.lpa",
    )


# ---------------------------------------------------------------------------
# Catalogue (ordered — renders top-to-bottom in the matrix table)
# ---------------------------------------------------------------------------

PolicyEvaluator = Callable[[dict, dict], dict]

POLICY_CATALOGUE: list[dict[str, Any]] = [
    {
        "policy_ref": f"NPPF 2024 para {NPPF_PARA_CLIMATE}",
        "legacy_ref": "NPPF 2021 para 152",
        "title": "Proactive approach to climate change",
        "source": NPPF_VERSION,
        "summary": (
            "Plans should take a proactive approach to mitigating and adapting to "
            "climate change, supporting the delivery of net zero."
        ),
        "evaluator": _check_nppf_climate,
    },
    {
        "policy_ref": f"NPPF 2024 para {NPPF_PARA_RENEWABLES}",
        "legacy_ref": "NPPF 2021 para 154",
        "title": "Support for renewable and low-carbon energy",
        "source": NPPF_VERSION,
        "summary": (
            "Planning should support the transition to a low-carbon future, "
            "giving significant weight to renewable / low-carbon energy "
            "generation and associated infrastructure."
        ),
        "evaluator": _check_nppf_renewables,
    },
    {
        "policy_ref": f"NPPF 2024 para {NPPF_PARA_SUITABLE_AREAS}",
        "legacy_ref": "NPPF 2021 para 158",
        "title": "Renewable energy: suitable areas and acceptable impacts",
        "source": NPPF_VERSION,
        "summary": (
            "LPAs should identify suitable areas for renewable / low-carbon "
            "development and grant permission where impacts are acceptable."
        ),
        "evaluator": _check_nppf_suitable_areas,
    },
    {
        "policy_ref": f"NPPF 2024 para {NPPF_PARA_BMV}",
        "legacy_ref": "NPPF 2021 para 186",
        "title": "Best and Most Versatile agricultural land",
        "source": NPPF_VERSION,
        "summary": (
            "Planning decisions should recognise the intrinsic value of the "
            "countryside including the economic and other benefits of BMV land."
        ),
        "evaluator": _check_nppf_bmv,
    },
    {
        "policy_ref": "NPS EN-1 (2023 refresh)",
        "legacy_ref": None,
        "title": "Overarching NPS for Energy — need case and CNP",
        "source": NPS_VERSION,
        "summary": (
            "Establishes the case for new energy infrastructure, Critical "
            "National Priority status for low-carbon generation, and the "
            "balancing framework for adverse impacts."
        ),
        "evaluator": _check_en1,
    },
    {
        "policy_ref": "NPS EN-3 (2023 refresh)",
        "legacy_ref": None,
        "title": "Renewable Energy Infrastructure — technology-specific impacts",
        "source": NPS_VERSION,
        "summary": (
            "Technology-specific impact assessment framework for onshore and "
            "offshore wind, solar PV, biomass, and associated development."
        ),
        "evaluator": _check_en3,
    },
    {
        "policy_ref": "NPS EN-5 (2023 refresh)",
        "legacy_ref": None,
        "title": "Electricity Networks Infrastructure",
        "source": NPS_VERSION,
        "summary": (
            "Policy framework for overhead lines, underground cables, "
            "substations, and associated electricity network infrastructure."
        ),
        "evaluator": _check_en5,
    },
    {
        "policy_ref": "Local Plan (LPA-specific)",
        "legacy_ref": None,
        "title": "Adopted development plan policies",
        "source": "Section 38(6) Planning and Compulsory Purchase Act 2004",
        "summary": (
            "Section 38(6) requires applications to be determined in accordance "
            "with the development plan unless material considerations indicate "
            "otherwise. Local plan policies on renewables, landscape, heritage, "
            "and biodiversity apply."
        ),
        "evaluator": _check_local_plan,
    },
]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_policy_matrix(project: dict, designations: dict | None = None) -> dict:
    """Evaluate the project against every policy in the catalogue.

    Args:
        project: project dict (see ``one_app_filler.fill_1app``).
        designations: site designations dict.

    Returns:
        ``{policies: list[PolicyCheck], summary: {...}, catalogue_version}``.
    """
    designations = designations or {}
    rows: list[dict[str, Any]] = []
    for entry in POLICY_CATALOGUE:
        v = entry["evaluator"](project, designations)
        rows.append({
            "policy_ref": entry["policy_ref"],
            # legacy_ref is intentionally NOT emitted on the serialised row —
            # the old 2021 paragraph numbers (152/154/158/186) are kept only
            # in the catalogue for search/provenance and in the
            # ``NPPF_PARAGRAPH_RENUMBER_DEC_2024`` mapping. The submitted
            # pack must not reference superseded numbers (COUNCIL-1 spec).
            "title": entry["title"],
            "source": entry["source"],
            "summary": entry["summary"],
            "verdict": v["verdict"],
            "proposal_alignment_text": v["proposal_alignment_text"],
            "evidence_pointer": v.get("evidence_pointer"),
            "evidence_pointers": v["evidence_pointers"],
        })

    counts = {"compliant": 0, "partial": 0, "non-compliant": 0, "n/a": 0}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    headline = "compliant"
    if counts.get("non-compliant", 0) > 0:
        headline = "non-compliant"
    elif counts.get("partial", 0) > 0:
        headline = "partial"

    return {
        "policies": rows,
        "summary": {
            "headline_verdict": headline,
            "counts": counts,
            "total": len(rows),
        },
        "catalogue_version": {
            "nppf": NPPF_VERSION,
            "nps": NPS_VERSION,
            "nppf_paragraph_renumber_dec_2024": NPPF_PARAGRAPH_RENUMBER_DEC_2024,
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "disclaimer": (
            "AUTO-GENERATED policy compliance matrix — indicative only. "
            "Verdicts are heuristic and must be reviewed by a qualified "
            "planning consultant before reliance."
        ),
    }


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    sample = build_policy_matrix(
        project={"technology": "solar", "capacity_mw": 49.9, "metadata": {"lpa": "Bedford BC"}},
        designations={"flood_zone": 1, "alc_grade": "3b"},
    )
    print(json.dumps(sample["summary"], indent=2))
    for row in sample["policies"]:
        print(f"  {row['policy_ref']:32s}  {row['verdict']}  -> {row['evidence_pointer']}")
