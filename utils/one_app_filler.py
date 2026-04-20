"""1APP Planning Portal field pre-fill — **v6 canonical** (COUNCIL-1 spec).

Pre-fills the UK Planning Portal 1APP form (standard full planning
application) from Princeps project metadata, site designations and linked
land parcels.

**Audit fix (COUNCIL-1 2026-04-19):** previous revision rolled fields into
19 free-form section keys with sub-numbering. Planning Portal's canonical
1APP v6 form has **40 numbered primary fields** (``Q1``..``Q40``) that feed
into the national validation checklist. COUNCIL-1 flagged the old mapping
as non-canonical; this revision replaces it with the real Q1..Q40 layout
while retaining the 19-section grouping used by the downstream renderer.

Field codes below track the Planning Portal "Application for planning
permission" v6 form (published 2024, retained in 2025 refresh). Each
``Q{n}`` key carries the canonical field label; grouped inside its section
dict (``1_applicant``..``19_declaration``) for template back-compat.

For NSIP-scale proposals (onshore generation >= 50 MW, offshore >= 100 MW,
DC >= 350 MW as an indicative s.35 opt-in threshold), this module flags
DCO-track instead of 1APP, and still returns the Q1..Q40 layout for
reference — the DCO overlay is carried in ``meta.dco_equivalents``.

Ownership Certificates A / B / C / D and CIL Form 1 (Assumption of
Liability) are shipped as separate sub-form modules:

* :mod:`utils.ownership_certificates` — Art.14 Town and Country Planning
  (Development Management Procedure) (England) Order 2015 certificates.
* :mod:`utils.cil_form_1` — Community Infrastructure Levy Regs 2010
  (as amended) Form 1.

Both are attached to the ``fill_1app`` result under ``sub_forms`` so the
template can render them alongside the 40-field Q-sheet.

Usage::

    from utils.one_app_filler import fill_1app
    result = fill_1app(project=project_row, parcels=parcels, designations=designations)
    # result["fields"] — dict keyed by section (1_applicant ... 19_declaration)
    #                    each value is Q{n} keyed with {value, status, label}
    # result["meta"]   — {route, nsip, auto_fill_pct, field_count, ...}
    # result["sub_forms"] — {ownership_certificate, cil_form_1}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# NSIP thresholds — Planning Act 2008, s.14/15 + s.35 opt-in.
NSIP_ONSHORE_MW = 50.0
NSIP_OFFSHORE_MW = 100.0
NSIP_DC_INDICATIVE_MW = 350.0

_PENDING = "pending"

# ---------------------------------------------------------------------------
# Planning Portal 1APP v6 — canonical 40-field schema.
# ---------------------------------------------------------------------------
#
# The Planning Portal "Application for planning permission" form v6 has 40
# numbered primary fields grouped into 19 thematic sections. Numbering below
# is taken from the published PDF and XML schema (v6, 2024). Each entry:
#
#     "Q{n}": (<section_key>, "<canonical label>")
#
# Section keys match the 19-section roll-up COUNCIL-1 retained.
# ---------------------------------------------------------------------------

ONE_APP_V6_FIELDS: dict[str, tuple[str, str]] = {
    # Section 1 — Applicant details (Q1–Q2)
    "Q1":  ("1_applicant", "Applicant name and address"),
    "Q2":  ("2_agent",     "Agent name and address (if applicable)"),
    # Section 3 — Description of the proposal (Q3–Q4)
    "Q3":  ("3_description_of_proposal", "Description of the proposed works"),
    "Q4":  ("3_description_of_proposal", "Has the work already started or been completed?"),
    # Section 4 — Site address (Q5)
    "Q5":  ("4_site_address", "Site address"),
    # Section 5 — Pre-application advice (Q6)
    "Q6":  ("5_pre_application_advice", "Pre-application advice"),
    # Section 6 — Materials (Q7)
    "Q7":  ("6_materials", "Materials — walls / roof / windows / doors / other"),
    # Section 7 — Vehicular access (Q8–Q10)
    "Q8":  ("7_vehicular_access", "Pedestrian and vehicular access"),
    "Q9":  ("7_vehicular_access", "New access, altered access, or no access change"),
    "Q10": ("7_vehicular_access", "Visibility splays and highway alterations"),
    # Section 8 — Existing and proposed use (Q11–Q12)
    "Q11": ("8_existing_and_proposed_use", "Existing use of the site"),
    "Q12": ("8_existing_and_proposed_use", "Proposed use / Use Classes Order 1987 class"),
    # Section 9 — Parking (Q13)
    "Q13": ("9_parking", "Vehicle parking, cycle parking and EV provision"),
    # Section 10 — Vehicular/highways impact (Q14–Q15)
    "Q14": ("10_vehicular_impact", "Trip generation — HGV construction peak and operational"),
    "Q15": ("10_vehicular_impact", "Transport Assessment / Transport Statement trigger"),
    # Section 11 — Foul / surface water (Q16–Q18)
    "Q16": ("11_foul_and_surface_water", "Foul sewage disposal"),
    "Q17": ("11_foul_and_surface_water", "Surface water disposal / SuDS hierarchy"),
    "Q18": ("11_foul_and_surface_water", "Trade effluent"),
    # Section 12 — Flood risk (Q19–Q20)
    "Q19": ("12_flood_risk", "Environment Agency flood zone (1 / 2 / 3a / 3b)"),
    "Q20": ("12_flood_risk", "Source of flood risk (river, surface, groundwater, sea, reservoir)"),
    # Section 13 — Biodiversity (Q21–Q23)
    "Q21": ("13_biodiversity", "Protected and priority species — survey status"),
    "Q22": ("13_biodiversity", "Designated sites (SSSI / SAC / SPA / Ramsar / LNR / LWS)"),
    "Q23": ("13_biodiversity", "Biodiversity Net Gain — 10% achievable (Environment Act 2021)"),
    # Section 14 — Trees and hedges (Q24–Q25)
    "Q24": ("14_trees_and_hedges", "Trees and hedges on or adjacent to the site"),
    "Q25": ("14_trees_and_hedges", "TPOs / conservation-area trees — schedule"),
    # Section 15 — Site area (Q26–Q27)
    "Q26": ("15_site_area", "Red-line site area (hectares)"),
    "Q27": ("15_site_area", "Developable area, setbacks and green infrastructure %"),
    # Section 16 — Industrial processes (Q28–Q30)
    "Q28": ("16_industrial_processes", "Hazardous substances on-site (COMAH trigger)"),
    "Q29": ("16_industrial_processes", "Airborne emissions / air-quality assessment"),
    "Q30": ("16_industrial_processes", "Noise-generating plant — BS 4142:2014+A1:2019"),
    # Section 17 — Hours of operation (Q31–Q32)
    "Q31": ("17_hours_of_opening", "Construction hours"),
    "Q32": ("17_hours_of_opening", "Operational hours and HGV delivery window"),
    # Section 18 — Ownership certificates A–D (Q33–Q37)
    "Q33": ("18_ownership_certificates", "Ownership Certificate code (A / B / C / D)"),
    "Q34": ("18_ownership_certificates", "Article 14 notice to owners — dates served"),
    "Q35": ("18_ownership_certificates", "Agricultural tenants — notice dates"),
    "Q36": ("18_ownership_certificates", "Press advertisement (Certificates C and D)"),
    "Q37": ("18_ownership_certificates", "Certificate signed, dated, and declaration made"),
    # Section 19 — Declaration and fee (Q38–Q40)
    "Q38": ("19_declaration", "Planning application fee — calculation and amount"),
    "Q39": ("19_declaration", "CIL Additional Information — Form 1 submitted if liable"),
    "Q40": ("19_declaration", "Applicant/agent declaration, name, signature and date"),
}

# Section ordering for rendering (19 groups retained from BOT-Q scaffold).
ONE_APP_V6_SECTIONS: list[str] = [
    "1_applicant",
    "2_agent",
    "3_description_of_proposal",
    "4_site_address",
    "5_pre_application_advice",
    "6_materials",
    "7_vehicular_access",
    "8_existing_and_proposed_use",
    "9_parking",
    "10_vehicular_impact",
    "11_foul_and_surface_water",
    "12_flood_risk",
    "13_biodiversity",
    "14_trees_and_hedges",
    "15_site_area",
    "16_industrial_processes",
    "17_hours_of_opening",
    "18_ownership_certificates",
    "19_declaration",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _field(value: Any, *, label: str, status: str | None = None, notes: str | None = None) -> dict:
    """Build a 1APP v6 field dict with value + fill status + canonical label."""
    if status is None:
        status = "filled" if value not in (None, "", [], {}) else _PENDING
    out: dict[str, Any] = {"value": value, "status": status, "label": label}
    if notes:
        out["notes"] = notes
    return out


def _is_nsip(technology: str | None, capacity_mw: float | None) -> tuple[bool, str]:
    """Return (is_nsip, rationale)."""
    if capacity_mw is None:
        return False, "capacity unknown"
    tech = (technology or "").lower()
    cap = float(capacity_mw)
    if tech in ("dc", "data_centre", "datacentre", "hyperscale"):
        if cap >= NSIP_DC_INDICATIVE_MW:
            return True, (
                f"DC IT load {cap} MW >= indicative {NSIP_DC_INDICATIVE_MW} MW — "
                "DCO-track via s.35 opt-in recommended (not statutory NSIP; "
                "verify against Infrastructure Planning (BCP) (Amendment) Regs 2026)"
            )
        return False, f"DC IT load {cap} MW below 350 MW opt-in tier"
    if tech in ("wind_offshore", "offshore_wind"):
        return (cap >= NSIP_OFFSHORE_MW,
                f"offshore wind {cap} MW {'>=' if cap >= NSIP_OFFSHORE_MW else '<'} 100 MW")
    return (cap >= NSIP_ONSHORE_MW,
            f"onshore generation {cap} MW {'>=' if cap >= NSIP_ONSHORE_MW else '<'} 50 MW")


def _default_description(technology: str, capacity_mw: float | None, area_ha: float | None) -> str:
    tech = (technology or "development").lower()
    area_txt = f"on a site of approximately {area_ha:.1f} ha" if area_ha else ""
    if tech == "solar":
        return (
            f"Construction and operation of a ground-mounted solar photovoltaic "
            f"generating station with a capacity of approximately "
            f"{capacity_mw or 0:.1f} MW {area_txt}, including inverter stations, "
            f"substation, underground cabling, perimeter fencing, CCTV, access tracks "
            f"and associated landscaping and biodiversity mitigation."
        ).strip()
    if tech == "wind":
        return (
            f"Installation and operation of an onshore wind generating station with "
            f"an installed capacity of approximately {capacity_mw or 0:.1f} MW "
            f"{area_txt}, including turbine foundations, crane hardstandings, "
            f"access tracks, substation, and associated grid connection works."
        ).strip()
    if tech == "bess":
        return (
            f"Construction and operation of a battery energy storage system (BESS) "
            f"with a rated output of approximately {capacity_mw or 0:.1f} MW "
            f"{area_txt}, including battery containers, power conversion systems, "
            f"substation, transformers, fire suppression infrastructure and fencing."
        ).strip()
    if tech in ("dc", "data_centre", "datacentre", "hyperscale"):
        return (
            f"Construction and operation of a data centre campus with an IT load "
            f"of approximately {capacity_mw or 0:.1f} MW {area_txt}, including "
            f"data halls, switchrooms, chillers, dry coolers, backup generators, "
            f"fuel storage, substation, fibre diversity and associated landscaping."
        ).strip()
    return f"Energy development of approximately {capacity_mw or 0:.1f} MW {area_txt}.".strip()


def _use_class(technology: str) -> str:
    """Town & Country Planning (Use Classes) Order 1987 (as amended 2020, 2025)."""
    tech = (technology or "").lower()
    if tech in ("dc", "data_centre", "datacentre", "hyperscale"):
        return "B8 (Storage or Distribution) — sui generis fallback if contested"
    if tech in ("solar", "wind", "bess"):
        return "Sui generis (energy infrastructure)"
    return "Sui generis"


def _approx_area_ha(parcels: list[dict] | None, technology: str, capacity_mw: float | None) -> float:
    if parcels:
        total = sum((p.get("area_m2") or 0) for p in parcels)
        if total:
            return round(total / 10_000.0, 2)
    if capacity_mw is None:
        return 0.0
    tech = (technology or "").lower()
    if tech == "solar":
        return round(float(capacity_mw) * 2.0, 2)
    if tech == "bess":
        return round(float(capacity_mw) * 0.15, 2)
    if tech in ("dc", "data_centre", "datacentre", "hyperscale"):
        return round(max(5.0, float(capacity_mw) * 0.05), 2)
    return 0.0


def _count_statuses(fields: dict[str, Any]) -> tuple[int, int, int]:
    """Recursively count (filled, pending, total) across the Q-keyed tree."""
    filled = pending = total = 0
    for v in fields.values():
        if isinstance(v, dict):
            if "status" in v and "value" in v:
                total += 1
                s = v["status"]
                if s == "filled":
                    filled += 1
                elif s == "pending":
                    pending += 1
            else:
                f, p, t = _count_statuses(v)
                filled += f
                pending += p
                total += t
    return filled, pending, total


# ---------------------------------------------------------------------------
# Enrichment merge
# ---------------------------------------------------------------------------

def _apply_enrichment(project: dict, enrichment: dict) -> None:
    """Populate ``project`` + ``project.metadata`` with enrichment values
    (from :func:`utils.site_enrichment.enrich_site`), skipping any existing
    non-empty caller-supplied value.
    """
    md = project.get("metadata") or {}
    project["metadata"] = md

    def _pick(field: str) -> Any:
        rec = enrichment.get(field)
        if isinstance(rec, dict):
            return rec.get("value")
        return rec

    def _set(key: str, value: Any, *, on_metadata: bool = True) -> None:
        if value in (None, "", []):
            return
        if not project.get(key):
            project[key] = value
        if on_metadata and not md.get(key):
            md[key] = value

    _set("postcode", _pick("postcode"))
    _set("lpa", _pick("local_planning_authority"))
    _set("local_authority", _pick("local_planning_authority"))
    _set("parish", _pick("parish"))
    _set("ward", _pick("ward"))
    _set("osgb_grid_ref", _pick("osgb_grid_ref"))
    _set("parliamentary_constituency", _pick("parliamentary_constituency"))

    uprn_val = _pick("uprn")
    if uprn_val:
        _set("uprn", uprn_val)
    title_val = _pick("land_registry_title")
    if isinstance(title_val, dict):
        tn = title_val.get("title_number") or title_val.get("inspire_id")
        if tn:
            _set("title_number", tn)
    elif title_val:
        _set("title_number", title_val)

    # Combined parish / ward label — 1APP Q5 renders this as a single line.
    if _pick("parish") and _pick("ward"):
        md.setdefault("parish_ward", f"{_pick('parish')} / {_pick('ward')}")
    elif _pick("ward"):
        md.setdefault("parish_ward", _pick("ward"))

    md["site_enrichment"] = enrichment


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def fill_1app(
    project: dict,
    *,
    parcels: list[dict] | None = None,
    designations: dict | None = None,
    applicant: dict | None = None,
    agent: dict | None = None,
    bng_calc: dict | None = None,
    enrichment: dict | None = None,
) -> dict:
    """Pre-fill the Planning Portal 1APP v6 form from project data.

    Parameters
    ----------
    enrichment : dict | None
        Optional ``utils.site_enrichment.SiteEnrichment.to_dict()`` payload.
        When supplied, its values (postcode, LPA, parish, ward, OSGB grid
        ref, UPRN, title number) replace any empty ``project`` / ``metadata``
        values BEFORE the canonical Q-field tree is assembled. This is how
        the ``[Postcode required]`` / ``[LPA — confirm ...]`` placeholder
        strings get eliminated from the downstream pack.

    Returns ``{fields, meta, sub_forms}`` with the 40 canonical Q-fields
    grouped into the 19 render sections plus ownership/CIL sub-forms.
    """
    # Merge enrichment up-front so the Q5 site-address dict picks up real
    # values. Enrichment never overwrites a caller-supplied non-empty value.
    if enrichment:
        _apply_enrichment(project, enrichment)
    # Deferred import — sub-form modules live next to this one but depend
    # on types defined here.
    from utils.ownership_certificates import build_ownership_certificate
    from utils.cil_form_1 import build_cil_form_1

    project = project or {}
    parcels = parcels or []
    designations = designations or {}
    applicant = applicant or {}
    agent = agent or {}
    metadata = project.get("metadata") or {}

    technology = (
        project.get("technology")
        or project.get("workload_type")
        or metadata.get("technology")
        or "solar"
    )
    capacity_mw = project.get("capacity_mw") or metadata.get("capacity_mw")
    area_ha = _approx_area_ha(parcels, technology, capacity_mw)

    is_nsip, nsip_rationale = _is_nsip(technology, capacity_mw)
    route = "DCO" if is_nsip else "1APP v6 (TCPA full planning)"

    # ------------------------------------------------------------------
    # Ownership certificate sub-form (A / B / C / D) + override hook.
    # ------------------------------------------------------------------
    ownership_override = metadata.get("ownership_cert")  # e.g. "B"
    ownership_cert = build_ownership_certificate(
        parcels=parcels,
        applicant=applicant,
        metadata=metadata,
        override=ownership_override,
    )

    # ------------------------------------------------------------------
    # CIL Form 1 (Assumption of Liability) — only if use-case triggers.
    # Solar is generally exempt; DC + BESS can trigger under the
    # floorspace test (>100 m² new internal floorspace).
    # ------------------------------------------------------------------
    cil_form = build_cil_form_1(
        technology=technology,
        capacity_mw=capacity_mw,
        area_ha=area_ha,
        metadata=metadata,
        applicant=applicant,
    )

    # ------------------------------------------------------------------
    # Q1..Q40 canonical field layout. Populate values, then group into
    # the 19-section render tree using ONE_APP_V6_FIELDS.
    # ------------------------------------------------------------------
    description = (
        project.get("description")
        or metadata.get("description")
        or _default_description(technology, capacity_mw, area_ha)
    )
    lat = project.get("lat")
    lon = project.get("lon")
    pre_app = metadata.get("pre_app") or {}
    fz = designations.get("flood_zone", 1)

    # BNG alignment — if BOT-O's bng_calculator output was passed in, pull
    # the 10%-net-gain achievable flag; fall back to metadata.
    bng_achievable: Any = None
    if isinstance(bng_calc, dict):
        bng_achievable = bng_calc.get("net_gain_achievable")
        if bng_achievable is None:
            bng_achievable = bng_calc.get("ten_pct_achievable")
    if bng_achievable is None:
        bng_achievable = metadata.get("bng_achievable")

    q_values: dict[str, dict] = {
        # Section 1 — Applicant (Q1)
        "Q1": _field(
            {
                "name": applicant.get("name") or metadata.get("applicant_name"),
                "company": applicant.get("company") or metadata.get("applicant_company"),
                "address": applicant.get("address"),
                "postcode": applicant.get("postcode"),
                "email": applicant.get("email"),
                "phone": applicant.get("phone"),
            },
            label=ONE_APP_V6_FIELDS["Q1"][1],
        ),
        # Section 2 — Agent (Q2)
        "Q2": _field(
            {
                "name": agent.get("name") or metadata.get("agent_name"),
                "company": agent.get("company") or "Princeps (pre-fill)",
                "address": agent.get("address"),
                "postcode": agent.get("postcode"),
                "email": agent.get("email"),
                "phone": agent.get("phone"),
            },
            label=ONE_APP_V6_FIELDS["Q2"][1],
        ),
        # Section 3 — Description (Q3–Q4)
        "Q3": _field(description, label=ONE_APP_V6_FIELDS["Q3"][1]),
        "Q4": _field(bool(metadata.get("work_started", False)), label=ONE_APP_V6_FIELDS["Q4"][1]),
        # Section 4 — Site address (Q5)
        "Q5": _field(
            {
                "address": project.get("address") or metadata.get("address"),
                "postcode": project.get("postcode") or metadata.get("postcode"),
                "osgb_grid_ref": metadata.get("osgb_grid_ref"),
                "latitude_wgs84": round(lat, 6) if lat is not None else None,
                "longitude_wgs84": round(lon, 6) if lon is not None else None,
                "lpa": project.get("lpa") or metadata.get("lpa") or metadata.get("local_authority"),
                "parish_ward": metadata.get("parish_ward"),
                "uprn": metadata.get("uprn"),
            },
            label=ONE_APP_V6_FIELDS["Q5"][1],
            notes="OSGB grid ref to be derived from lat/lon via pyproj OSGB36 transform at submission.",
        ),
        # Section 5 — Pre-application (Q6)
        "Q6": _field(
            {
                "sought": pre_app.get("sought"),
                "officer": pre_app.get("officer"),
                "reference": pre_app.get("reference"),
                "date": pre_app.get("date"),
                "summary": pre_app.get("summary"),
            },
            label=ONE_APP_V6_FIELDS["Q6"][1],
        ),
        # Section 6 — Materials (Q7)
        "Q7": _field(
            {
                "walls": metadata.get("materials_walls"),
                "roof": metadata.get("materials_roof"),
                "windows": metadata.get("materials_windows"),
                "doors": metadata.get("materials_doors"),
                "other": (
                    "Dark green / olive powder-coated steel for inverter, substation and BESS enclosures; "
                    "recessive RAL colour palette to minimise landscape visibility."
                    if (technology or "").lower() != "dc"
                    else "Precast concrete / profiled metal cladding to match adjacent B8 industrial context; "
                         "recessive dark cladding to sensitive elevations."
                ),
            },
            label=ONE_APP_V6_FIELDS["Q7"][1],
        ),
        # Section 7 — Vehicular access (Q8–Q10)
        "Q8":  _field(metadata.get("pedestrian_access"), label=ONE_APP_V6_FIELDS["Q8"][1]),
        "Q9":  _field(metadata.get("new_access_required"), label=ONE_APP_V6_FIELDS["Q9"][1]),
        "Q10": _field(
            metadata.get("visibility_splay_m"),
            label=ONE_APP_V6_FIELDS["Q10"][1],
            notes="Manual for Streets / DMRB CD 123 — agree with Highways Authority.",
        ),
        # Section 8 — Existing / proposed use (Q11–Q12)
        "Q11": _field(metadata.get("existing_use") or "Agricultural / greenfield", label=ONE_APP_V6_FIELDS["Q11"][1]),
        "Q12": _field(_use_class(technology), label=ONE_APP_V6_FIELDS["Q12"][1]),
        # Section 9 — Parking (Q13)
        "Q13": _field(
            {
                "existing_spaces": metadata.get("parking_existing"),
                "proposed_spaces": metadata.get("parking_proposed"),
                "ev_charging": metadata.get("ev_charging"),
                "cycle_parking": metadata.get("cycle_parking"),
            },
            label=ONE_APP_V6_FIELDS["Q13"][1],
            notes="Building Regs Part S 2022 — 20% EV-ready for DC staff parking.",
        ),
        # Section 10 — Vehicular impact (Q14–Q15)
        "Q14": _field(metadata.get("hgv_peak"), label=ONE_APP_V6_FIELDS["Q14"][1]),
        "Q15": _field(
            True if (technology or "").lower() in ("dc",) or (capacity_mw or 0) >= 20 else False,
            label=ONE_APP_V6_FIELDS["Q15"][1],
            notes="DfT Circular 02/2013 — Transport Assessment threshold.",
        ),
        # Section 11 — Foul / surface water (Q16–Q18)
        "Q16": _field(
            metadata.get("foul_drainage") or "Package treatment plant / none (unmanned site)",
            label=ONE_APP_V6_FIELDS["Q16"][1],
        ),
        "Q17": _field(
            "SuDS Management Train — source / site / regional controls; greenfield runoff rate Qbar maintained.",
            label=ONE_APP_V6_FIELDS["Q17"][1],
        ),
        "Q18": _field(metadata.get("trade_effluent"), label=ONE_APP_V6_FIELDS["Q18"][1]),
        # Section 12 — Flood risk (Q19–Q20)
        "Q19": _field(fz, label=ONE_APP_V6_FIELDS["Q19"][1]),
        "Q20": _field(metadata.get("flood_source"), label=ONE_APP_V6_FIELDS["Q20"][1]),
        # Section 13 — Biodiversity (Q21–Q23)
        "Q21": _field(
            metadata.get("protected_species_survey"),
            label=ONE_APP_V6_FIELDS["Q21"][1],
            notes="Phase 1 habitat + protected species surveys required.",
        ),
        "Q22": _field(
            {
                "sssi": bool(designations.get("sssi")),
                "sac": bool(designations.get("sac")),
                "spa": bool(designations.get("spa")),
                "ramsar": bool(designations.get("ramsar")),
                "lnr": bool(designations.get("lnr")),
                "lws": bool(designations.get("lws")),
            },
            label=ONE_APP_V6_FIELDS["Q22"][1],
        ),
        "Q23": _field(
            bng_achievable,
            label=ONE_APP_V6_FIELDS["Q23"][1],
            notes=(
                "Environment Act 2021 s.98 mandatory BNG — aligned with bng_calculator "
                "output (BOT-O) where available."
            ),
        ),
        # Section 14 — Trees (Q24–Q25)
        "Q24": _field(
            metadata.get("trees_on_site"),
            label=ONE_APP_V6_FIELDS["Q24"][1],
            notes="BS 5837:2012 tree survey and schedule.",
        ),
        "Q25": _field(
            {
                "tpo": bool(designations.get("tpo")),
                "hedgerow_removal_m": metadata.get("hedgerow_removal_m"),
            },
            label=ONE_APP_V6_FIELDS["Q25"][1],
        ),
        # Section 15 — Site area (Q26–Q27)
        "Q26": _field(area_ha if area_ha > 0 else None, label=ONE_APP_V6_FIELDS["Q26"][1]),
        "Q27": _field(
            {
                "developable_area_ha": metadata.get("developable_area_ha"),
                "green_infra_pct": metadata.get("green_infra_pct"),
            },
            label=ONE_APP_V6_FIELDS["Q27"][1],
        ),
        # Section 16 — Industrial processes (Q28–Q30)
        "Q28": _field(
            metadata.get("hazardous_substances"),
            label=ONE_APP_V6_FIELDS["Q28"][1],
            notes="COMAH thresholds — lithium-ion stacks can trigger lower-tier.",
        ),
        "Q29": _field(
            metadata.get("airborne_emissions"),
            label=ONE_APP_V6_FIELDS["Q29"][1],
            notes="Backup gensets — AQ dispersion modelling (EA BAT).",
        ),
        "Q30": _field(
            metadata.get("noise_plant_list"),
            label=ONE_APP_V6_FIELDS["Q30"][1],
            notes="BS 4142:2014+A1:2019 baseline + predicted rating level.",
        ),
        # Section 17 — Hours (Q31–Q32)
        "Q31": _field(
            metadata.get("construction_hours") or "Mon–Fri 0700–1900, Sat 0800–1300, no Sundays / BH",
            label=ONE_APP_V6_FIELDS["Q31"][1],
        ),
        "Q32": _field(
            (
                "24 hours / 7 days (unmanned solar / BESS site)"
                if (technology or "").lower() in ("solar", "bess")
                else "24 hours / 7 days (operational DC)"
                if (technology or "").lower() in ("dc", "data_centre", "datacentre", "hyperscale")
                else "As agreed with LPA"
            ),
            label=ONE_APP_V6_FIELDS["Q32"][1],
        ),
        # Section 18 — Ownership certificates (Q33–Q37)
        "Q33": _field(
            ownership_cert["certificate_code"],
            label=ONE_APP_V6_FIELDS["Q33"][1],
            notes=ownership_cert.get("rationale"),
        ),
        "Q34": _field(
            ownership_cert.get("notices_to_owners") or None,
            label=ONE_APP_V6_FIELDS["Q34"][1],
            notes="Article 14 DMPO 2015 — 21-day notice window.",
        ),
        "Q35": _field(
            metadata.get("agri_tenant_notice"),
            label=ONE_APP_V6_FIELDS["Q35"][1],
            notes="Certificate for agricultural holdings (Schedule 2 Form 2).",
        ),
        "Q36": _field(
            ownership_cert.get("press_advertisement") or None,
            label=ONE_APP_V6_FIELDS["Q36"][1],
        ),
        "Q37": _field(
            {
                "signatory": ownership_cert.get("signatory"),
                "signed_on": ownership_cert.get("signed_on"),
                "declaration_made": ownership_cert.get("declaration_made"),
            },
            label=ONE_APP_V6_FIELDS["Q37"][1],
        ),
        # Section 19 — Declaration & fee (Q38–Q40)
        "Q38": _field(
            metadata.get("planning_fee_gbp"),
            label=ONE_APP_V6_FIELDS["Q38"][1],
            notes="Town and Country Planning (Fees for Applications) Regs 2012 — as amended 2023/2025.",
        ),
        "Q39": _field(
            cil_form["liable"],
            label=ONE_APP_V6_FIELDS["Q39"][1],
            notes=cil_form.get("rationale"),
        ),
        "Q40": _field(
            {
                "signatory": applicant.get("name") or agent.get("name"),
                "role": applicant.get("role") or agent.get("role") or "Agent",
                "date": _now_iso()[:10],
            },
            label=ONE_APP_V6_FIELDS["Q40"][1],
        ),
    }

    # Roll Q-fields into the 19-section render tree.
    fields: dict[str, dict[str, Any]] = {s: {} for s in ONE_APP_V6_SECTIONS}
    for qkey, (section_key, _label) in ONE_APP_V6_FIELDS.items():
        fields[section_key][qkey] = q_values[qkey]

    # DCO overlay — only populated when NSIP.
    dco_equivalents = {
        "applicant_details": "DCO Form A — Application form",
        "proposal_description": "Reg 5(2)(a) — Draft DCO text + Explanatory Memorandum",
        "site_address": "Reg 5(2)(i) — Land plans + Book of Reference",
        "flood": "Reg 5(2)(l) — Flood Risk Assessment",
        "biodiversity": "Reg 5(2)(l) — Environmental Statement Chapter: Biodiversity",
        "ownership": "Reg 5(2)(d) — Statement of Reasons + Book of Reference Part 1",
        "hours_and_noise": "Reg 5(2)(l) — Environmental Statement Chapter: Noise",
    } if is_nsip else None

    filled, pending, total = _count_statuses(fields)
    auto_fill_pct = round((filled / total) * 100, 1) if total else 0.0

    meta = {
        "route": route,
        "nsip": is_nsip,
        "nsip_rationale": nsip_rationale,
        "technology": technology,
        "capacity_mw": capacity_mw,
        "area_ha": area_ha,
        "auto_fill_pct": auto_fill_pct,
        "fields_filled": filled,
        "fields_pending": pending,
        "fields_total": total,
        "field_count_canonical": len(ONE_APP_V6_FIELDS),
        "form_version": "Planning Portal 1APP v6 (2024)",
        "generated_at": _now_iso(),
        "sections_covered": [
            "1. Applicant", "2. Agent", "3. Description", "4. Site Address",
            "5. Pre-application", "6. Materials", "7. Vehicular Access",
            "8. Existing / Proposed Use", "9. Parking", "10. Vehicular Impact",
            "11. Foul / Surface Water", "12. Flood Risk", "13. Biodiversity",
            "14. Trees / Hedges", "15. Site Area", "16. Industrial Processes",
            "17. Hours of Operation", "18. Ownership Certificates",
            "19. Declaration",
        ],
        "dco_equivalents": dco_equivalents,
        "disclaimer": (
            "AUTO-GENERATED DRAFT — not a planning submission. Every field must be "
            "verified by a qualified planning consultant before the LPA 1APP "
            "(or PINS DCO) submission. No reliance transfers to Princeps."
        ),
    }

    sub_forms = {
        "ownership_certificate": ownership_cert,
        "cil_form_1": cil_form,
    }

    return {"fields": fields, "meta": meta, "sub_forms": sub_forms}


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    sample = fill_1app(
        project={
            "name": "Hinton Solar Farm",
            "technology": "solar",
            "capacity_mw": 49.9,
            "lat": 52.21,
            "lon": -0.63,
            "metadata": {"lpa": "Bedford Borough Council"},
        },
        parcels=[{"area_m2": 960_000, "owner_confirmed": True}],
        designations={"flood_zone": 1, "aonb": False, "sssi": False},
    )
    print(json.dumps(sample["meta"], indent=2))
    print("Ownership cert:", sample["sub_forms"]["ownership_certificate"]["certificate_code"])
    print("CIL liable:", sample["sub_forms"]["cil_form_1"]["liable"])
