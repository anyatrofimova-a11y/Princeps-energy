"""Community Infrastructure Levy — Form 1 (Assumption of Liability).

**Regulatory basis.** Community Infrastructure Levy Regulations 2010
(SI 2010/948) as amended (principally SI 2011/987, SI 2013/982,
SI 2014/385, SI 2019/1103, SI 2020/1070). Form 1 is the statutory
"Assumption of Liability" notice required under regulation 31, and
must accompany any planning application for a CIL-liable development.

**Liability trigger.** Under CIL Regs 2010 reg 6, CIL is chargeable on
development that:

1. comprises the **creation of 100 m² or more of new gross internal
   floorspace** (reg 6(1)(c)); **or**
2. involves the **creation of one or more new dwellings** regardless of
   floorspace (reg 6(1)(a)); **or**
3. involves a change of use to a dwelling (reg 6(1)(b)).

Most open-field renewables (solar, wind, standalone BESS) do **not**
create 100 m² of internal floorspace — transformers and inverter kiosks
are typically treated as plant structures, not buildings with internal
floorspace (see PAS guidance 2022 and the Council of Mortgage Lenders
CIL note 2016). They are therefore generally CIL-exempt.

Data centres, by contrast, are buildings with significant internal
floorspace (data halls, switchrooms, office, corridors) and routinely
exceed the 100 m² threshold. Large BESS compounds with internal access
walkways and control rooms can also trigger. This module runs the test
and returns a structured Form 1 skeleton where liable, or an
explicit-not-liable record where not.

**Important.** Even where not CIL-liable, the LPA Community
Infrastructure Levy (Additional Information) form is still required so
the Council can confirm the exemption. This module returns
``liable=False`` with ``reason`` plus the CIL exemption declaration
wording when the floorspace test is negative.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Statutory floorspace trigger (CIL Regs 2010 reg 6(1)(c)).
CIL_FLOORSPACE_THRESHOLD_M2: float = 100.0

# Indicative internal floorspace per MW — used to test the trigger when
# the project hasn't been through DesignCanvas and a BOM isn't available.
# These are order-of-magnitude planning heuristics, not design figures.
_FLOORSPACE_M2_PER_MW: dict[str, float] = {
    # Solar inverter kiosks + substation control buildings are normally
    # treated as plant (PAS 2022 / CIL Regs reg 40). The *per-MW* figure
    # here is conservative — a 50 MW solar farm typically has <200 m² of
    # buildings with internal floorspace (a single DNO substation control
    # building). Use the explicit metadata.new_floorspace_m2 for accuracy.
    "solar": 1.5,
    # Onshore wind has a somewhat larger O&M building + substation.
    "wind": 8.0,
    # BESS — varies enormously. 35 m²/MW is an upper-bound heuristic; a
    # 50 MW BESS with a single control room / switchgear building is
    # commonly ~200 m² total (i.e. 4 m²/MW). Use metadata override where
    # available.
    "bess": 4.0,
    # DC — data halls + plant + offices. ~900 m²/MW IT (Uptime Institute
    # benchmarking).
    "dc": 900.0,
    "data_centre": 900.0,
    "datacentre": 900.0,
    "hyperscale": 900.0,
}

# Use-case classes that never trigger the floorspace test for standalone
# cases — kept explicit so the reasoning in the document is auditable.
_LOW_FLOORSPACE_TECHS = {"solar", "wind"}

# Use-case classes that the spec calls out as triggering candidates.
_TRIGGER_CANDIDATES = {"dc", "data_centre", "datacentre", "hyperscale", "bess"}

_LIABLE_DECLARATION = (
    "I/we assume liability to pay the Community Infrastructure Levy in "
    "respect of the chargeable development described above and confirm "
    "that I/we have read and understood the notes on assumption of "
    "liability. The assumption of liability takes effect when this "
    "form is received by the collecting authority, under regulation 31 "
    "of the CIL Regulations 2010 (as amended)."
)

_NOT_LIABLE_DECLARATION = (
    "I/we declare that the development the subject of this application "
    "creates less than 100 m² of new gross internal floorspace and does "
    "not create a new dwelling. The development is therefore not liable "
    "to CIL under regulation 6 of the Community Infrastructure Levy "
    "Regulations 2010 (as amended). A CIL Additional Information form "
    "accompanies this application to evidence the exemption."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _estimate_new_floorspace_m2(
    technology: str,
    capacity_mw: float | None,
    metadata: dict,
) -> tuple[float, str]:
    """Return ``(gross_internal_area_m2, source)``.

    Source is ``"metadata"`` when the project already records GIA,
    else ``"heuristic"`` if derived from capacity × _FLOORSPACE_M2_PER_MW.
    """
    explicit = metadata.get("new_floorspace_m2") or metadata.get("gia_m2")
    if explicit is not None:
        try:
            return float(explicit), "metadata.new_floorspace_m2"
        except (TypeError, ValueError):
            pass
    tech = (technology or "").lower()
    coeff = _FLOORSPACE_M2_PER_MW.get(tech, 0.0)
    cap = float(capacity_mw or 0.0)
    return round(coeff * cap, 1), "heuristic (m2/MW table)"


def _triggers_cil(
    technology: str,
    capacity_mw: float | None,
    metadata: dict,
    floorspace_m2: float,
) -> tuple[bool, str]:
    """Apply the regulation 6 floorspace / dwelling trigger test.

    Returns ``(liable, rationale)``.
    """
    # Dwelling / change-of-use-to-dwelling short-circuits.
    if metadata.get("new_dwellings_count"):
        n = metadata["new_dwellings_count"]
        return True, f"CIL Regs 2010 reg 6(1)(a) — {n} new dwelling(s) created."
    if metadata.get("change_of_use_to_dwelling"):
        return True, "CIL Regs 2010 reg 6(1)(b) — change of use to a dwelling."

    tech = (technology or "").lower()

    # Standalone solar / wind: almost always below threshold; call out the
    # exemption explicitly so the reasoning is auditable.
    if tech in _LOW_FLOORSPACE_TECHS:
        if floorspace_m2 >= CIL_FLOORSPACE_THRESHOLD_M2:
            return True, (
                f"{tech} scheme creates {floorspace_m2:.0f} m² new floorspace — "
                f"exceeds {CIL_FLOORSPACE_THRESHOLD_M2:.0f} m² trigger under CIL Regs 2010 reg 6(1)(c); "
                "treat as CIL-liable pending LPA exemption confirmation."
            )
        return False, (
            f"Open-field {tech} generation — estimated {floorspace_m2:.0f} m² "
            f"gross internal floorspace (< {CIL_FLOORSPACE_THRESHOLD_M2:.0f} m² reg 6(1)(c) trigger). "
            "Inverter/substation enclosures treated as plant (PAS 2022)."
        )

    # DC / BESS / other: run the floorspace test.
    if tech in _TRIGGER_CANDIDATES:
        if floorspace_m2 >= CIL_FLOORSPACE_THRESHOLD_M2:
            return True, (
                f"{tech} scheme creates approximately {floorspace_m2:.0f} m² "
                f"of new gross internal floorspace — exceeds "
                f"{CIL_FLOORSPACE_THRESHOLD_M2:.0f} m² trigger under CIL Regs 2010 reg 6(1)(c). "
                "Form 1 Assumption of Liability required."
            )
        return False, (
            f"{tech} scheme estimated {floorspace_m2:.0f} m² new floorspace — "
            f"below {CIL_FLOORSPACE_THRESHOLD_M2:.0f} m² trigger."
        )

    # Unknown tech — default not liable but flag for review.
    if floorspace_m2 >= CIL_FLOORSPACE_THRESHOLD_M2:
        return True, (
            f"Estimated {floorspace_m2:.0f} m² new floorspace — above threshold; "
            "Form 1 rendered pending solicitor confirmation."
        )
    return False, (
        f"Technology '{tech or 'unknown'}' — estimated {floorspace_m2:.0f} m² "
        f"new floorspace; below {CIL_FLOORSPACE_THRESHOLD_M2:.0f} m² trigger."
    )


def build_cil_form_1(
    *,
    technology: str,
    capacity_mw: float | None,
    area_ha: float | None = None,
    metadata: dict | None = None,
    applicant: dict | None = None,
) -> dict[str, Any]:
    """Build the CIL Form 1 (Assumption of Liability) sub-form.

    Args:
        technology: project technology (solar / wind / bess / dc / ...).
        capacity_mw: export / IT-load capacity, used to estimate GIA.
        area_ha: site area (hectares) — carried into the form.
        metadata: project metadata; may include ``new_floorspace_m2``,
            ``gia_m2``, ``new_dwellings_count``,
            ``change_of_use_to_dwelling``, applicant address fields,
            ``cil_collecting_authority``, ``chargeable_use_description``.
        applicant: applicant dict.

    Returns:
        Dict with:
            * ``liable`` — bool
            * ``rationale`` — text explanation of the trigger test
            * ``floorspace_m2`` — estimated GIA
            * ``floorspace_source`` — where the GIA came from
            * ``form_rendered`` — True if Form 1 fields should be shown
            * ``fields`` — dict of Form 1 fields (Parts A–D)
            * ``declaration`` — wording the signatory attests
            * ``signatory``, ``date_signed``
    """
    metadata = metadata or {}
    applicant = applicant or {}

    floorspace_m2, floorspace_source = _estimate_new_floorspace_m2(
        technology, capacity_mw, metadata,
    )
    liable, rationale = _triggers_cil(technology, capacity_mw, metadata, floorspace_m2)

    chargeable_use = (
        metadata.get("chargeable_use_description")
        or f"{(technology or 'energy').title()} — {capacity_mw or 0:.1f} MW"
    )

    # Form 1 fields — mirrors the CIL Form 1 PDF structure (Parts A–D).
    fields: dict[str, Any] = {
        "part_a_about_the_application": {
            "A1_application_reference": metadata.get("application_reference") or "[to be allocated by LPA]",
            "A2_site_address": metadata.get("address") or metadata.get("site_address") or "[site address]",
            "A3_site_area_ha": area_ha,
            "A4_description_of_development": chargeable_use,
            "A5_new_floorspace_m2": floorspace_m2,
            "A5_floorspace_source": floorspace_source,
            "A6_new_dwellings_count": metadata.get("new_dwellings_count") or 0,
        },
        "part_b_person_assuming_liability": {
            "B1_name": applicant.get("name") or metadata.get("applicant_name") or "[applicant name]",
            "B2_company": applicant.get("company") or metadata.get("applicant_company"),
            "B3_address": applicant.get("address") or metadata.get("applicant_address"),
            "B4_postcode": applicant.get("postcode") or metadata.get("applicant_postcode"),
            "B5_email": applicant.get("email"),
            "B6_telephone": applicant.get("phone"),
            "B7_capacity_in_which_assuming": applicant.get("role") or "Owner / Developer",
        },
        "part_c_apportionment": {
            "C1_single_owner_development": bool(metadata.get("single_owner_development", True)),
            "C2_apportionment_schedule": metadata.get("cil_apportionment_schedule"),
        },
        "part_d_declaration": {
            "D1_declaration_text": (
                _LIABLE_DECLARATION if liable else _NOT_LIABLE_DECLARATION
            ),
            "D2_signatory": applicant.get("name") or "[signatory]",
            "D3_role": applicant.get("role") or "Applicant",
            "D4_date": _today_iso(),
        },
    }

    return {
        "liable": liable,
        "rationale": rationale,
        "floorspace_m2": floorspace_m2,
        "floorspace_source": floorspace_source,
        "floorspace_threshold_m2": CIL_FLOORSPACE_THRESHOLD_M2,
        "form_rendered": True,  # Even non-liable cases render a declaration.
        "fields": fields,
        "declaration": _LIABLE_DECLARATION if liable else _NOT_LIABLE_DECLARATION,
        "chargeable_use_description": chargeable_use,
        "signatory": applicant.get("name") or "[signatory]",
        "date_signed": _today_iso(),
        "collecting_authority": metadata.get("cil_collecting_authority") or metadata.get("lpa"),
        "regulation_ref": "Community Infrastructure Levy Regulations 2010 (SI 2010/948), reg 31",
        "trigger_ref": "CIL Regs 2010 reg 6(1) — 100 m² floorspace / new dwelling test",
        "generated_at": _now_iso(),
        "disclaimer": (
            "Auto-generated CIL Form 1 skeleton — CIL liability is ultimately "
            "determined by the Collecting Authority. A qualified planning "
            "consultant / solicitor must verify GIA figures, any "
            "charitable / self-build / social-housing reliefs, and the "
            "apportionment schedule before submission."
        ),
    }


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    for tech, cap in [("solar", 49.9), ("bess", 50), ("dc", 100), ("wind", 20)]:
        out = build_cil_form_1(
            technology=tech, capacity_mw=cap, area_ha=10,
            applicant={"name": "Test Ltd"},
        )
        print(f"{tech} {cap} MW → liable={out['liable']} — {out['rationale'][:80]}")
    print(json.dumps(
        build_cil_form_1(
            technology="dc", capacity_mw=100, area_ha=10,
            metadata={"new_floorspace_m2": 90_000, "lpa": "Slough BC"},
            applicant={"name": "Megawatt DC Ltd", "role": "Developer"},
        )["fields"],
        indent=2,
        default=str,
    ))
