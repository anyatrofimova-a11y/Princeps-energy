"""
Document Automation Engine — auto-generates UK energy development application forms
from Princeps assessment data.

Priority 1 document types:
  1. G99 Grid Connection Application (Parts 1-4b)
  2. Planning Application Summary (1APP pre-fill)
  3. EIA Screening Request (Schedule 2 criteria)
  4. CDM F10 Notification (HSE pre-fill)
  5. BNG Baseline Assessment (simplified biodiversity metric)
  6. Licence Exemption Memo

Each generator returns:
  {"form_data": dict, "html": str, "document_type": str, "auto_fill_pct": int}
"""

from __future__ import annotations

import math
import re
from datetime import datetime, date
from typing import Any

from app.regulatory.versions import (
    cite as _cite_reg,
    cite_nps as _cite_nps,
    nppf_para as _nppf_para,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _latlon_to_osgb(lat: float, lon: float) -> str:
    """WGS84 (decimal degrees) to a real 6-figure OS Grid Reference.

    Delegates to :func:`utils.osgb.to_grid_ref`, which uses pyproj
    (EPSG:4326 -> EPSG:27700) or a pure-Python Airy-1830 fallback.
    Fixed 2026-04-19 to replace a fabricated approximation that produced
    invalid grid references on generated packs (COUNCIL-1 audit).
    """
    from utils.osgb import to_grid_ref

    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return "—"
    if not (math.isfinite(lat_f) and math.isfinite(lon_f)):
        return "—"
    return to_grid_ref(lat_f, lon_f, precision=6)


def _slug(s: str) -> str:
    return re.sub(r"[^\w-]", "-", s or "site").strip("-")[:40]


# Placeholder strings we consider "empty" and overwritable from enrichment.
_PLACEHOLDER_VALUES = frozenset({
    "[Postcode required]",
    "[Parish — confirm from LPA boundary data]",
    "[Ward — confirm from LPA boundary data]",
    "[UPRN — look up at Ordnance Survey AddressBase]",
    "[Title number — HMLR official search required]",
    "[Local Planning Authority — confirm from LPA boundary service]",
    "[Local Planning Authority]",
    "[Postcode]",
})


def _merge_enrichment_into_site(site: dict, enrichment: dict) -> None:
    """Populate ``site`` with enrichment values (from
    :func:`utils.site_enrichment.enrich_site`), skipping any caller-supplied
    value that is non-placeholder.
    """
    def _pick(field: str) -> Any:
        rec = enrichment.get(field)
        if isinstance(rec, dict):
            return rec.get("value")
        return rec

    def _set_if_empty(key: str, value: Any) -> None:
        if value in (None, "", []):
            return
        existing = site.get(key)
        if existing in (None, "", *_PLACEHOLDER_VALUES):
            site[key] = value

    _set_if_empty("postcode", _pick("postcode"))
    _set_if_empty("local_authority", _pick("local_planning_authority"))
    _set_if_empty("lpa", _pick("local_planning_authority"))
    _set_if_empty("parish", _pick("parish"))
    _set_if_empty("ward", _pick("ward"))
    _set_if_empty("parliamentary_constituency", _pick("parliamentary_constituency"))
    uprn_val = _pick("uprn")
    if uprn_val:
        _set_if_empty("uprn", uprn_val)
    title_val = _pick("land_registry_title")
    if isinstance(title_val, dict):
        tn = title_val.get("title_number") or title_val.get("inspire_id")
        if tn:
            _set_if_empty("title_number", tn)
    elif title_val:
        _set_if_empty("title_number", title_val)
    osgb = _pick("osgb_grid_ref")
    if osgb:
        _set_if_empty("osgb_reference", osgb)
        _set_if_empty("osgb_grid_ref", osgb)


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _pct(filled: int, total: int) -> int:
    return round(filled / total * 100) if total > 0 else 0


def _count_filled(d: dict) -> tuple[int, int]:
    """Count (filled, total) fields in a nested dict, ignoring placeholder values."""
    filled = 0
    total = 0
    placeholders = {"[", "to be", "—", "n/a", "check required", "tbc", "tbd"}
    for v in d.values():
        if isinstance(v, dict):
            f, t = _count_filled(v)
            filled += f
            total += t
        elif isinstance(v, list):
            total += 1
            if v:
                filled += 1
        else:
            total += 1
            sv = str(v).strip().lower() if v is not None else ""
            if sv and not any(p in sv for p in placeholders):
                filled += 1
    return filled, total


def _princeps_style() -> str:
    """Shared CSS for all generated documents."""
    return """
    body { font-family: 'Segoe UI', system-ui, sans-serif; margin: 0; padding: 28px; color: #1f2937; font-size: 11px; line-height: 1.5; }
    h1 { color: #7c5cfc; font-size: 22px; margin: 0 0 4px; }
    h2 { color: #374151; font-size: 14px; margin: 24px 0 8px; padding: 6px 10px; background: #f3f0ff; border-left: 3px solid #7c5cfc; }
    h3 { font-size: 12px; color: #4b5563; margin: 16px 0 6px; }
    .subtitle { color: #6b7280; font-size: 10px; }
    .disclaimer { background: #fef3c7; padding: 8px 12px; border-radius: 6px; font-size: 9px; color: #92400e; margin: 12px 0; }
    .info-box { background: #eff6ff; padding: 8px 12px; border-radius: 6px; font-size: 10px; color: #1e40af; margin: 8px 0; border-left: 3px solid #3b82f6; }
    .warn-box { background: #fef3c7; padding: 8px 12px; border-radius: 6px; font-size: 10px; color: #92400e; margin: 8px 0; border-left: 3px solid #f59e0b; }
    .ok-box { background: #f0fdf4; padding: 8px 12px; border-radius: 6px; font-size: 10px; color: #166534; margin: 8px 0; border-left: 3px solid #22c55e; }
    table { width: 100%; border-collapse: collapse; margin: 4px 0 12px; }
    td, th { padding: 4px 8px; border-bottom: 1px solid #e5e7eb; vertical-align: top; text-align: left; }
    th { background: #f9fafb; font-weight: 600; color: #374151; }
    .lbl { font-weight: 600; width: 40%; color: #374151; }
    .placeholder { color: #9ca3af; font-style: italic; }
    .check { color: #16a34a; font-weight: 600; }
    .cross { color: #dc2626; font-weight: 600; }
    .neutral { color: #6b7280; }
    ul { padding-left: 16px; }
    li { margin: 3px 0; }
    .footer { margin-top: 24px; padding-top: 12px; border-top: 1px solid #e5e7eb; font-size: 9px; color: #9ca3af; }
    .badge { display: inline-block; padding: 2px 10px; border-radius: 4px; font-weight: 700; font-size: 10px; color: white; }
    .badge-go { background: #16a34a; }
    .badge-caution { background: #f59e0b; }
    .badge-nogo { background: #dc2626; }
    .badge-info { background: #3b82f6; }
    @media print { body { padding: 12px; } }
    """


def _table_rows(d: dict, skip_complex: bool = True) -> str:
    """Render dict as HTML table rows."""
    rows = []
    for k, v in d.items():
        if skip_complex and isinstance(v, (dict, list)):
            continue
        label = k.replace("_", " ").title()
        val = v if v is not None else "—"
        cls = ' class="placeholder"' if isinstance(v, str) and v.startswith("[") else ""
        rows.append(f'<tr><td class="lbl">{label}</td><td{cls}>{val}</td></tr>')
    return "".join(rows)


def _footer(doc_type: str) -> str:
    return f"""<div class="footer">
    This {doc_type} was auto-generated by Princeps AI Platform on {datetime.utcnow().strftime('%d %B %Y')}.
    All values must be verified by qualified professionals before submission.
    Princeps is not a substitute for professional engineering, legal, or planning advice.
    </div>"""


# ===========================================================================
# 1. G99 Grid Connection Application (Parts 1-4b)
# ===========================================================================

def generate_g99_application(
    site: dict,
    capacity: dict,
    grid: dict,
    technology: dict,
) -> dict:
    """Generate a G99/G100 grid connection application with Parts 1-4b.

    Args:
        site: {name, address, postcode, lat, lon, area_ha, dno}
        capacity: {capacity_kw, capacity_mw}
        grid: {voltage_kv, nearest_substation, distance_km, headroom_mw,
               connection_cost: {p10_gbp, p50_gbp, p90_gbp}, dno}
        technology: {type, inverter, inverter_make, num_units, unit_kw,
                     dc_ac_ratio, module_type, module_wp}

    Returns:
        {form_data, html, document_type, auto_fill_pct}
    """
    lat = site.get("lat", 0)
    lon = site.get("lon", 0)
    capacity_kw = capacity.get("capacity_kw", 5000)
    capacity_mw = capacity.get("capacity_mw", capacity_kw / 1000)

    # Determine application route
    app_type = "G100" if capacity_kw <= 50 else "G99"
    if capacity_kw <= 16:
        ena_cat = "A1"
    elif capacity_kw <= 50:
        ena_cat = "A2"
    elif capacity_kw <= 1000:
        ena_cat = "B"
    elif capacity_kw <= 50000:
        ena_cat = "C"
    else:
        ena_cat = "D (NSIP)"

    # Connection voltage
    if capacity_mw > 50:
        rec_voltage = 132
    elif capacity_mw > 5:
        rec_voltage = 33
    else:
        rec_voltage = 11

    voltage_kv = grid.get("voltage_kv", rec_voltage)
    fault_level_mva = round(voltage_kv * voltage_kv / 10, 1)

    # DC/AC ratio and inverter sizing
    dc_ac = technology.get("dc_ac_ratio", 1.20)
    num_inverters = technology.get("num_units", math.ceil(capacity_kw / 500))
    inverter_kw = technology.get("unit_kw", min(500, capacity_kw))

    form = {
        "meta": {
            "document_type": "G99 Grid Connection Application",
            "application_route": app_type,
            "ena_category": ena_cat,
            "ena_reference": "EREC G99 Issue 2 (March 2025)",
            "generated_by": "Princeps AI Platform",
            "generated_at": _now_iso(),
            "disclaimer": (
                "Pre-filled from AI assessment. All fields must be verified "
                "by a qualified engineer before submission to the DNO."
            ),
        },

        # Part 1: Applicant details
        "part_1_applicant": {
            "applicant_name": "[Developer Name]",
            "company_name": "[Company Name]",
            "registered_address": "[Registered Address]",
            "contact_email": "[email]",
            "contact_phone": "[phone]",
            "company_reg_number": "[Company number]",
            "mpan_top_line": "[to be assigned by DNO]",
            "existing_connection_agreement": "No",
            "authorised_signatory": "[Name and position]",
        },

        # Part 2: Site details
        "part_2_site": {
            "site_name": site.get("name", ""),
            "site_address": site.get("address", site.get("name", "")),
            "postcode": site.get("postcode", ""),
            "os_grid_reference": _latlon_to_osgb(lat, lon),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "land_area_ha": site.get("area_ha"),
            "land_ownership": "[Freehold / Leasehold / Option]",
            "existing_supply_capacity_kva": site.get("existing_supply_kva", "None"),
            "existing_metering": site.get("existing_metering", "None"),
            "dno_licence_area": grid.get("dno", site.get("dno", "[DNO licence area]")),
        },

        # Part 3: Import / export requirements
        "part_3_import_export": {
            "max_export_capacity_kw": capacity_kw,
            "max_export_capacity_mw": round(capacity_mw, 2),
            "proposed_connection_voltage_kv": rec_voltage,
            "max_import_capacity_kw": round(capacity_kw * 0.05, 1),  # ~5% of export for aux
            "import_required": "Yes — auxiliary supply for monitoring, SCADA, security",
            "connection_type": (
                "New dedicated connection"
                if capacity_mw > 5
                else "Modification to existing supply"
            ),
            "phases": 3,
            "power_factor_export": "0.95 lagging to 0.95 leading (adjustable)",
            "power_factor_import": "Unity",
            "metering_arrangement": "Half-hourly export metering (HH CT/VT)",
            "settlement_type": "HH via BSC",
            "commissioning_target": "[Target date]",
        },

        # Part 4b: Power park module data
        "part_4b_power_park": {
            "technology_type": technology.get("type", "Solar Photovoltaic"),
            "module_type": technology.get("module_type", "Monocrystalline PERC"),
            "module_rating_wp": technology.get("module_wp", 580),
            "total_dc_capacity_kwp": round(capacity_kw * dc_ac, 1),
            "dc_ac_ratio": dc_ac,
            "number_of_inverters": num_inverters,
            "inverter_rated_kw": inverter_kw,
            "inverter_type": technology.get("inverter", "Grid-following"),
            "inverter_manufacturer": technology.get("inverter_make", "[To be specified]"),
            "reactive_power_capability_kvar": round(capacity_kw * 0.33, 1),
            "reactive_power_mode": "4-quadrant (Q+/Q-/P+/P-)",
            "frequency_response": "Compliant — synthetic inertia capable",
            "fault_ride_through": "Compliant with EREC G99 Annex 1",
            "anti_islanding_method": "RoCoF + Vector Shift",
            "rocof_setting_hz_s": 1.0,
            "loss_of_mains_type": "G99 Stage 1",
            "over_voltage_stage_1_pct": 110,
            "under_voltage_stage_1_pct": 87,
            "over_frequency_stage_1_hz": 50.4,
            "under_frequency_stage_1_hz": 47.5,
            "estimated_annual_yield_mwh": round(capacity_mw * 8760 * 0.11),
        },

        # Additional connection info
        "connection_details": {
            "nearest_substation": grid.get("nearest_substation", ""),
            "distance_to_poc_km": grid.get("distance_km"),
            "available_headroom_mw": grid.get("headroom_mw"),
            "estimated_fault_level_mva": fault_level_mva,
            "protection_scheme": (
                "G99 compliant — O/U voltage, O/U frequency, RoCoF, "
                "neutral voltage displacement, reverse power"
                if voltage_kv >= 33
                else "G99 Stage 1 — loss of mains + O/U V/F"
            ),
            "earthing_arrangement": "Solid earthing via dedicated earth electrode",
            "estimated_connection_cost_p50_gbp": (
                grid.get("connection_cost", {}).get("p50_gbp")
            ),
        },
    }

    filled, total = _count_filled(form)
    auto_fill_pct = _pct(filled, total)

    html = _render_g99_html(form)

    return {
        "form_data": form,
        "html": html,
        "document_type": "g99_application",
        "auto_fill_pct": auto_fill_pct,
    }


def _render_g99_html(form: dict) -> str:
    meta = form["meta"]
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>G99 Application — {form['part_2_site'].get('site_name', 'Site')}</title>
<style>{_princeps_style()}</style></head><body>
<h1>G99 Grid Connection Application</h1>
<div class="subtitle">{meta['ena_reference']} — {meta['application_route']} Route (Category {meta['ena_category']})</div>
<div class="subtitle">Generated by {meta['generated_by']} on {meta['generated_at'][:10]}</div>
<div class="disclaimer">{meta['disclaimer']}</div>

<h2>Part 1 — Applicant Details</h2>
<table>{_table_rows(form['part_1_applicant'])}</table>

<h2>Part 2 — Site Details</h2>
<table>{_table_rows(form['part_2_site'])}</table>

<h2>Part 3 — Import / Export Requirements</h2>
<table>{_table_rows(form['part_3_import_export'])}</table>

<h2>Part 4b — Power Park Module Data</h2>
<table>{_table_rows(form['part_4b_power_park'])}</table>

<h2>Connection Details</h2>
<table>{_table_rows(form['connection_details'])}</table>

{_footer('G99 Grid Connection Application')}
</body></html>"""


# ===========================================================================
# 2. Planning Application Summary (1APP pre-fill)
# ===========================================================================

def generate_planning_summary(
    site: dict,
    assessment: dict,
    constraints: dict,
    enrichment: dict | None = None,
) -> dict:
    """Generate a UK 2026 industry-standard planning application summary.

    Parameters
    ----------
    enrichment : dict | None
        Optional output of ``utils.site_enrichment.enrich_site(...).to_dict()``.
        When provided, its values (postcode, LPA, parish, ward, OSGB grid ref,
        UPRN, title number) are used to overwrite any ``site`` fields that are
        empty or still carry the ``[X required]`` / ``[X — confirm...]``
        placeholder strings. Fields that enrichment could not resolve remain
        as structured TODO markers rather than bare placeholders.

    Aligned with: NPPF Dec 2024 (paras 86(c)/87/161/173), NPS EN-1 (2025),
    Town & Country Planning (EIA) Regs 2017, Environment Act 2021 (mandatory
    BNG from 12 Feb 2024 TCPA, NSIPs from May 2026), Planning & Infrastructure
    Act 2025, Infrastructure Planning (Business or Commercial Projects)
    (Amendment) Regs 2026 (DC NSIP opt-in via s.35 Planning Act 2008).

    Args:
        site: {name, address, postcode, lat, lon, area_ha, land_use,
               local_authority, ward, parish, last_known_use, existing_buildings}
        assessment: {capacity_mw, technology ("solar"|"wind"|"bess"|"dc"|"hybrid"),
                     it_load_mw, panel_count, access_road, construction_months,
                     description, pue_target, wue_target_l_per_kwh,
                     annual_water_m3, backup_genset_count, backup_genset_mva,
                     heat_reuse_mwth, heat_reuse_partner, dc_floorspace_sqm,
                     gross_external_area_sqm, building_height_m, use_class,
                     employees_ops, construction_peak_hgv_per_day}
        constraints: {flood_zone, agricultural_grade, green_belt, aonb,
                      conservation_area, listed_buildings, sssi, sac, spa,
                      ramsar, tpo, public_rights_of_way, watercourse, archaeology,
                      proximity_residential_m, heat_network_zone}

    Returns:
        {form_data, html, document_type, auto_fill_pct}
    """
    # Merge enrichment into ``site`` so downstream placeholder fallbacks
    # (e.g. ``site.get("postcode", "[Postcode required]")``) pick up real
    # values. Never overwrites a caller-supplied non-placeholder value.
    if enrichment:
        _merge_enrichment_into_site(site, enrichment)

    lat = site.get("lat", 0)
    lon = site.get("lon", 0)
    tech = (assessment.get("technology") or "solar").lower()
    is_dc = tech in ("dc", "data_centre", "datacentre", "hyperscale")
    capacity_mw = float(assessment.get("capacity_mw") or assessment.get("it_load_mw") or 5.0)
    area_ha = float(site.get("area_ha") or (capacity_mw * 2 if not is_dc else max(5.0, capacity_mw / 20)))

    # Planning route (2026 reality)
    planning_route = _determine_planning_route(tech, capacity_mw, site)
    authority = planning_route["determining_authority"]

    # EIA screening — Schedule 1 / Schedule 2 Regulations 2017
    eia = _screen_eia(tech, capacity_mw, area_ha, constraints)

    # Use class (2025 case-law: B8 for DC)
    use_class = assessment.get("use_class") or _default_use_class(tech)

    land_use = site.get("land_use", {})
    existing_use_desc = _describe_land_use(land_use)

    fz = constraints.get("flood_zone", 1)
    flood_declaration = {
        1: "Zone 1 — low probability of flooding (<1 in 1000 annual). Sequential / Exception Tests not required; FRA still needed for sites ≥1 ha (NPPF para 173).",
        2: "Zone 2 — medium probability of flooding (1 in 100–1000). Sequential Test required; FRA mandatory.",
        3: "Zone 3 — high probability of flooding (>1 in 100). Sequential AND Exception Tests required; FRA mandatory; development highly constrained.",
    }.get(fz, f"Flood Zone {fz} — verify against Environment Agency flood map for planning.")

    ag_grade = constraints.get("agricultural_grade", 3)
    is_bmv = ag_grade <= 2
    ag_declaration = (
        f"Grade {ag_grade} — Best and Most Versatile (BMV) agricultural land. Material consideration under {_nppf_para('BMV')}. Requires justification and, where possible, use of lower-grade land."
        if is_bmv else f"Grade {ag_grade} — not BMV. Agricultural Land Classification survey recommended at pre-app."
    )

    form: dict[str, Any] = {
        "meta": {
            "document_type": "Planning Application Summary — UK Industry Standard (1APP + NPPF 2024)",
            "planning_route": planning_route["route"],
            "determining_authority": authority,
            "route_legal_basis": planning_route["legal_basis"],
            "nsip_opt_in_available": planning_route["nsip_opt_in"],
            "cni_designation": planning_route["cni"],
            "use_class_order_1987_as_amended": use_class,
            "generated_by": "Princeps AI Platform",
            "generated_at": _now_iso(),
            "disclaimer": (
                "AUTO-GENERATED — NOT A SUBMISSION. This summary assists pre-application "
                "preparation. Every figure must be verified by the applicant's planning, "
                "legal, engineering and environmental consultants before any formal "
                "submission. Reliance on this document does not transfer liability to "
                "Princeps or its operators."
            ),
        },

        "section_1_site_details": {
            "site_address": site.get("address", site.get("name", "")),
            "postcode": site.get("postcode") or "[Postcode required]",
            "os_grid_reference": site.get("osgb_reference") or _latlon_to_osgb(lat, lon),
            "latitude_wgs84": round(lat, 6),
            "longitude_wgs84": round(lon, 6),
            "site_area_ha": round(area_ha, 2),
            "local_planning_authority": authority,
            "parish": site.get("parish") or "[Parish — confirm from LPA boundary data]",
            "ward": site.get("ward") or "[Ward — confirm from LPA boundary data]",
            "site_identifier_uprn": site.get("uprn") or "[UPRN — order OS Open UPRN / AddressBase Plus]",
            "land_registry_title": site.get("title_number") or "[Title number — HMLR Official Copy (£3) required]",
        },

        "section_2_proposed_development": {
            "proposal_description": (
                assessment.get("description")
                or _default_proposal_description(tech, capacity_mw, area_ha, assessment)
            ),
            "technology_type": "Data Centre (Hyperscale)" if is_dc else tech.title(),
            "use_class_order_1987": use_class,
            "gross_external_area_sqm": assessment.get("gross_external_area_sqm") or assessment.get("dc_floorspace_sqm") or ("[GEA — architect to confirm]" if is_dc else None),
            "installed_capacity_mw": round(capacity_mw, 2),
            "it_load_mw": assessment.get("it_load_mw") if is_dc else None,
            "number_of_panels": (
                assessment.get("panel_count")
                or (math.ceil(capacity_mw * 1000 / 0.58) if tech == "solar" else None)
            ),
            "number_of_turbines": assessment.get("turbine_count") if tech == "wind" else None,
            "max_building_height_m_aod": assessment.get("building_height_m") or _tech_max_height(tech),
            "construction_period_months": assessment.get("construction_months", _est_construction(capacity_mw, is_dc)),
            "operational_life_years": 25 if is_dc else (40 if tech == "solar" else 25),
            "decommissioning_plan": (
                "Decommissioning & Site Restoration Plan to be secured by planning condition; "
                "bond or equivalent financial instrument recommended where operational life is defined."
            ),
        },

        "section_3_existing_use": {
            "existing_primary_land_use": existing_use_desc,
            "is_land_vacant": "No" if land_use else "[Verify on site visit and aerial photography]",
            "last_known_use": site.get("last_known_use", existing_use_desc),
            "existing_buildings_on_site": site.get("existing_buildings", "[Survey required]"),
            "previously_developed_land_pdl": "Yes" if (land_use.get("built") or 0) > 0.5 else "No (greenfield / agricultural)",
            "contamination_risk": site.get("contamination_risk", "[Preliminary Risk Assessment (Phase 1 desk study) required]"),
        },

        "section_4_access_and_transport": {
            "existing_access": assessment.get("access_road", "[To be confirmed on site plan]"),
            "new_access_required": "[Transport Assessment needed if >5,000 sqm B8 — DfT Guidance on Transport Assessment]" if is_dc else "[Confirm against LPA thresholds]",
            "public_highway_frontage": "[Confirm from OS MasterMap highway layer]",
            "visibility_splay_adequate": "[Visibility splays to be demonstrated per Manual for Streets / DMRB CD 123]",
            "construction_traffic_route": (
                "Construction Traffic Management Plan (CTMP) to be submitted — route to avoid residential areas, "
                "agreed with Highways Authority. Peak HGV movement: "
                f"{assessment.get('construction_peak_hgv_per_day') or (120 if is_dc else 40)} per day."
            ),
            "travel_plan_required": "Yes — operational travel plan mandatory for DC >1,000 sqm" if is_dc else ("Yes" if capacity_mw > 20 else "Not normally required"),
            "abnormal_loads_required": "Yes — transformer deliveries + pre-cast concrete" if (capacity_mw > 10 or is_dc) else "Unlikely",
            "cycle_parking_ev_charging": (
                "Cycle parking and EV charging to Part S / Local Plan standards; minimum 20% EV-ready provision for staff parking."
                if is_dc else "As per Local Plan parking standards."
            ),
        },

        "section_5_flood_risk_and_drainage": {
            "flood_zone_ea": fz,
            "flood_zone_declaration": flood_declaration,
            "flood_risk_assessment_required": "Yes" if (fz >= 2 or area_ha >= 1) else "No",
            "sequential_test_required": "Yes" if fz >= 2 else "No",
            "exception_test_required": "Yes" if fz >= 3 else "No",
            "suds_strategy": (
                "SuDS Management Train (source / site / regional controls) required. "
                "Greenfield runoff rates (Qbar) to be achieved. Hierarchy per PPG Flood Risk ID 7."
            ),
            "watercourse_within_site": constraints.get("watercourse", "[Check Environment Agency Main Rivers / OS watercourse layers]"),
            "surface_water_sewer_capacity": "[Thames Water / local wastewater undertaker capacity check required]",
            "pollution_prevention": "Construction phase: oil interceptors, silt fences, refuelling bunds. Operational: none normally needed (no fuel storage beyond genset day tanks).",
        },

        "section_6_agricultural_land": {
            "agricultural_land_classification_grade": ag_grade,
            "alc_declaration": ag_declaration,
            "bmv_land_affected_ha": round(area_ha, 2) if is_bmv else 0,
            "alc_post_1988_survey_required": "Yes — provisional 1:250,000 maps are insufficient for determination" if is_bmv else "Recommended",
            "soil_management_plan": "Soil Management Plan (Defra Code of Practice 2009) required — pre-commencement condition.",
            "reversibility_statement": (
                "Full reversibility within 12 months of decommissioning; shallow pile foundations; topsoil stripping limited to access tracks and substation platforms."
                if tech == "solar"
                else ("Not reversible — permanent buildings and deep foundations." if is_dc else "Partial reversibility — containers on pad foundations.")
            ),
        },

        "section_7_designations_and_constraints": {
            "green_belt": f"Yes — Very Special Circumstances required ({_nppf_para('GREEN_BELT_VSC')} / {_nppf_para('GREEN_BELT_SECTION')})" if constraints.get("green_belt") else "No",
            "aonb_national_landscape": "Yes — great weight given to landscape conservation (NPPF para 189)" if constraints.get("aonb") else "No",
            "conservation_area": "Yes — s.72 Planning (LBCA) Act 1990 applies" if constraints.get("conservation_area") else "No",
            "listed_buildings_within_500m": "Yes — Heritage Impact Assessment required (s.66 P(LBCA)A 1990)" if constraints.get("listed_buildings") else "No",
            "scheduled_ancient_monument": constraints.get("sam", "No / [Check Historic England National Heritage List]"),
            "sssi": "Yes — Natural England notification required under Wildlife & Countryside Act 1981" if constraints.get("sssi") else "No",
            "sac_spa_ramsar_natura_2000": "Yes — Habitats Regulations Assessment (HRA) required" if (constraints.get("sac") or constraints.get("spa") or constraints.get("ramsar")) else "No",
            "ancient_woodland": constraints.get("ancient_woodland", "[Check Natural England Ancient Woodland Inventory]"),
            "tree_preservation_orders": "Yes — TPO consent required for works to protected trees" if constraints.get("tpo") else "No",
            "public_rights_of_way": "Yes — PROW diversion / temporary closure may be needed" if constraints.get("public_rights_of_way") else "No",
            "archaeological_interest": constraints.get("archaeology", "Desk-Based Assessment required; evaluation trenching if DBA identifies potential."),
        },

        "section_8_eia_screening": {
            "eia_regulations": "Town and Country Planning (Environmental Impact Assessment) Regulations 2017 (as amended)",
            "schedule_1_trigger": eia["schedule_1"],
            "schedule_2_trigger": eia["schedule_2"],
            "eia_opinion_required": eia["opinion"],
            "likely_outcome": eia["likely_outcome"],
            "sensitivity_factors": eia["sensitivity_factors"],
            "recommended_scope": eia["recommended_scope"],
        },

        "section_9_biodiversity_net_gain": {
            "regime": "Environment Act 2021 — mandatory BNG for TCPA applications from 12 Feb 2024 (major), 2 Apr 2024 (minor); NSIPs from May 2026.",
            "minimum_gain_pct": "10% (statutory minimum — LPAs may set higher in Local Plan)",
            "management_period_years": 30,
            "delivery_hierarchy": "1) on-site; 2) off-site with legal agreement (S106 / conservation covenant); 3) statutory biodiversity credits (last resort).",
            "baseline_metric": f"{_cite_reg('statutory_biodiversity_metric')} — baseline habitat condition survey required by competent ecologist (CIEEM).",
            "habitat_management_and_monitoring_plan": "HMMP required — to be secured by S106 or conservation covenant; 30-year monitoring reports to LPA / responsible body.",
            "biodiversity_gain_plan_stage": "To be submitted post-permission, pre-commencement.",
        },

        "section_10_climate_and_sustainability": {
            "nppf_climate_paragraphs": "NPPF 2024 paras 161 (climate), 164–166 (renewable energy), 86(c)/87 (data centre needs).",
            "energy_sustainability_statement": "Required — demonstrate efficiency hierarchy: Be Lean → Be Clean → Be Green → Be Seen.",
            "embodied_carbon_assessment": "RICS Whole Life Carbon Assessment 2nd Ed. (2023) — recommended; required in London Plan / Welsh PPW / increasingly in county Local Plans.",
            "heat_network_zoning": constraints.get("heat_network_zone", "[Check emerging Heat Network Zone designation under Energy Act 2023]"),
            "heat_reuse_feasibility": (
                f"Assessment required (NPPF para 161). Available heat offtake: {assessment.get('heat_reuse_mwth', 'TBD')} MW thermal. "
                f"Partner: {assessment.get('heat_reuse_partner', '[Engagement with local heat network operator required — e.g., Thames Valley Energy]')}."
                if is_dc else "N/A"
            ),
            "circular_economy_statement": "Required — demolition / construction / operational waste hierarchy.",
        },

        "section_11_dc_technical_schedule": _dc_technical_schedule(is_dc, capacity_mw, assessment) if is_dc else None,

        "section_12_noise_air_lighting": {
            "noise_assessment_standard": "BS 4142:2014+A1:2019 (industrial / commercial noise); BS 8233:2014 (internal receptors).",
            "expected_noise_sources": (
                "Dry coolers, chillers, CRAH fans, backup generator testing (≤50 hr/yr), transformer hum."
                if is_dc else (
                    "Panel tracker motors (minor), inverter cooling fans, HV transformer hum." if tech == "solar"
                    else "Turbine blade aerodynamic + mechanical noise, gearbox." if tech == "wind"
                    else "Inverter fans, HVAC; higher during C-rate charging."
                )
            ),
            "air_quality_assessment": (
                "Required — standby diesel generators (Stage V / HVO). Dispersion modelling to EA BAT for emergency backup diesel engines (50 hr/yr test cap, vertical uncapped stack)."
                if is_dc else "Screening assessment — construction dust mitigation (IAQM 2014)."
            ),
            "lighting_assessment": "Institution of Lighting Professionals GN01:21 — obtrusive light; environmental zone determined by LPA (E1 dark / E2 rural / E3 suburban / E4 urban).",
            "electromagnetic_compatibility": (
                "BS EN 55011 Class A (industrial) / Class B (residential proximity). Set-back from sensitive receptors demonstrated."
                if is_dc else "BS EN 50470 for DNO metering; general EMC compliance via CE/UKCA marking."
            ),
        },

        "section_13_supporting_documents": _build_validation_checklist(
            tech, capacity_mw, area_ha, is_dc, fz, constraints, assessment
        ),

        "section_14_consultation_and_obligations": {
            "pre_application_engagement": (
                "LPA pre-app service — strongly recommended; written opinion requested. "
                "Statutory consultees: Environment Agency, Natural England, Historic England, Highways, DNO, Thames Water (or local wastewater)."
            ),
            "statement_of_community_involvement": "Required — proportionate to scale; reference LPA adopted SCI.",
            "planning_and_infrastructure_act_2025_changes": (
                "Statutory s.42/s.47/s.48 pre-app consultation duty for NSIPs REPEALED (P&I Act 2025, in force from 2026 commencement). "
                "Replaced with SoS guidance-led early engagement — still expect multi-round public exhibitions and s.56 notification in practice."
            ),
            "s106_heads_of_terms": _s106_heads_of_terms(tech, capacity_mw, is_dc, area_ha, authority),
            "cil_liability": _cil_note(authority, is_dc, area_ha),
            "community_benefit": (
                "Community Benefit Fund (onshoreWIND / largeSOLAR): ~£5k/MW/yr industry benchmark. "
                "Heat offtake, fibre drops, STEM outreach, local employment clauses negotiated via S106."
            ),
        },

        "section_15_policy_references": _policy_references(tech, capacity_mw, is_dc, authority),
    }

    # Remove any None sections for cleanliness
    form = {k: v for k, v in form.items() if v is not None}

    filled, total = _count_filled(form)
    auto_fill_pct = _pct(filled, total)

    html = _render_planning_html(form)

    return {
        "form_data": form,
        "html": html,
        "document_type": "planning_summary",
        "auto_fill_pct": auto_fill_pct,
    }


# ---------------------------------------------------------------------------
# Planning-route determination (2026 reality)
# ---------------------------------------------------------------------------

def _determine_planning_route(tech: str, capacity_mw: float, site: dict) -> dict:
    """Route applicable as of April 2026.

    Key 2026 refs:
    - Planning Act 2008 s.14 thresholds
    - Infrastructure Planning (Business or Commercial Projects) (Amendment)
      Regs 2026 (made 8 Jan 2026) — brings DCs into NSIP via s.35 opt-in
    - DSIT CNI designation for DCs (12 Sep 2024) — security/resilience only,
      does not itself change planning route.
    - Planning & Infrastructure Act 2025 (Royal Assent 18 Dec 2025) — repeals
      s.42/s.47/s.48 statutory pre-app duty.
    """
    is_dc = tech in ("dc", "data_centre", "datacentre", "hyperscale")
    authority = site.get("local_authority", "[Local Planning Authority — confirm from LPA boundary service]")

    if is_dc:
        # DC NSIP route is OPT-IN via s.35 direction — not automatic at any threshold.
        # De facto: hyperscale schemes in 2026 are still mostly TCPA 1990 Full.
        return {
            "route": ("TCPA 1990 s.70 — Full Application (most likely) OR NSIP via s.35 Planning Act 2008 direction (opt-in, Jan 2026 regs)."),
            "determining_authority": authority,
            "legal_basis": "Town and Country Planning Act 1990 s.70 / Infrastructure Planning (Business or Commercial Projects) (Amendment) Regs 2026.",
            "nsip_opt_in": "Available — applicant may request s.35 Secretary of State direction if nationally significant.",
            "cni": "Data Centre sector designated CNI by DSIT on 12 Sep 2024 (HCWS89). Security / resilience designation only — does not alter planning route.",
        }
    if tech == "solar" and capacity_mw > 100:
        return {
            "route": "NSIP — Development Consent Order (Planning Act 2008 s.15, as amended 2025).",
            "determining_authority": "Planning Inspectorate (PINS) — Secretary of State (DESNZ) decides.",
            "legal_basis": "Planning Act 2008. NPS EN-1 (revised 2025) + EN-3 apply.",
            "nsip_opt_in": "N/A — mandatory route above 100 MW threshold (post-Apr 2024 reform).",
            "cni": "N/A",
        }
    if tech == "wind" and capacity_mw > 100:  # Onshore wind NSIP threshold reset post-2024
        return {
            "route": "NSIP — Development Consent Order (Planning Act 2008 s.15).",
            "determining_authority": "Planning Inspectorate (PINS) — Secretary of State (DESNZ) decides.",
            "legal_basis": "Planning Act 2008. NPS EN-1 + EN-3 apply (2025 revision; EN-3 in force 6 Jan 2026).",
            "nsip_opt_in": "N/A — mandatory.",
            "cni": "N/A",
        }
    return {
        "route": "Town and Country Planning Act 1990 s.70 — Full Application.",
        "determining_authority": authority,
        "legal_basis": "Town and Country Planning Act 1990; Town and Country Planning (Development Management Procedure) (England) Order 2015.",
        "nsip_opt_in": "Not available at this scale.",
        "cni": "N/A",
    }


def _default_use_class(tech: str) -> str:
    """Use Class Order 1987 (as amended).

    For DC: B8 (storage & distribution) — confirmed by 2025 appeal decisions
    APP/P1940/W/24/3346061 (Abbotts Langley, 12 May 2025) and
    APP/N0410/W/24/3347353 (Bucks, 9 Jul 2025). Some LPAs still prefer sui
    generis — decide case-by-case and reflect in condition.
    """
    if tech in ("dc", "data_centre", "datacentre", "hyperscale"):
        return "B8 (storage and distribution) — per 2025 appeal decisions; alternatively sui generis subject to LPA view."
    if tech in ("solar", "wind", "bess"):
        return "Sui generis (renewable electricity generating station) — GPDO Part 14 PD rights where applicable."
    return "To be confirmed — no established class for this development type."


def _screen_eia(tech: str, capacity_mw: float, area_ha: float, constraints: dict) -> dict:
    """EIA screening under T&CP (EIA) Regs 2017, Schedules 1 and 2.

    Schedule 1 triggers MANDATORY EIA:
      - Para 21: thermal power stations ≥300 MW (rarely a DC unless CHP).
      - Para 3(a): nuclear; 9(a): major roads — not relevant here.

    Schedule 2 triggers SCREENING (EIA required if significant effects):
      - Para 3(a): industrial installations for carrying electricity — all
        overground lines >15 km (solar/wind typically trigger).
      - Para 3(i): wind farms — all screening (previously >0.5 ha / >5 turbines).
      - Para 10(a): Industrial estate development — THRESHOLD 5 ha
        (post-2015 threshold; DC sites ≥5 ha typically trigger).
      - Para 10(b): Urban development projects — non-dwelling >1 ha or area
        >150 dwellings. DC on greenfield >1 ha triggers screening.
    """
    is_dc = tech in ("dc", "data_centre", "datacentre", "hyperscale")
    sensitivity = []
    if constraints.get("aonb"): sensitivity.append("AONB / National Landscape")
    if constraints.get("sssi"): sensitivity.append("SSSI")
    if constraints.get("sac") or constraints.get("spa") or constraints.get("ramsar"):
        sensitivity.append("Natura 2000 / Ramsar site")
    if constraints.get("conservation_area"): sensitivity.append("Conservation Area")
    if constraints.get("flood_zone", 1) >= 2: sensitivity.append(f"Flood Zone {constraints.get('flood_zone')}")
    if (constraints.get("agricultural_grade") or 3) <= 2: sensitivity.append("BMV agricultural land")
    if (constraints.get("proximity_residential_m") or 9999) < 500:
        sensitivity.append(f"Residential receptors within {constraints.get('proximity_residential_m')} m")

    # Schedule 1
    schedule_1 = "Not triggered"
    if tech == "thermal" and capacity_mw >= 300:
        schedule_1 = "Para 21 — thermal power station ≥300 MW. MANDATORY EIA."

    # Schedule 2
    schedule_2_triggers = []
    if is_dc and area_ha >= 5:
        schedule_2_triggers.append("Para 10(a) industrial estate — site area ≥5 ha.")
    if is_dc and area_ha > 1:
        schedule_2_triggers.append("Para 10(b) urban development — non-dwelling development >1 ha on non-previously-developed land.")
    if tech == "solar" and area_ha > 0.5:
        schedule_2_triggers.append("Para 3(a) industrial installation for electricity production.")
    if tech == "wind":
        schedule_2_triggers.append("Para 3(i) wind farm — all installations screen-in under 2017 Regs.")
    if tech == "bess" and capacity_mw > 50:
        schedule_2_triggers.append("Para 3(a) industrial installation — large BESS typically screens-in.")

    schedule_2 = "; ".join(schedule_2_triggers) if schedule_2_triggers else "Not triggered"

    # Opinion & outcome
    if schedule_1 != "Not triggered":
        opinion = "Mandatory EIA. Scoping Opinion should be requested before ES preparation."
        outcome = "EIA Development — full Environmental Statement required."
    elif schedule_2 != "Not triggered":
        opinion = "Screening Opinion must be requested from LPA / PINS before application, per Reg. 6."
        if sensitivity or (is_dc and area_ha >= 10):
            outcome = "Likely EIA Development — sensitivity factors present. Proceed to Scoping."
        else:
            outcome = "May be screened out (negative screening) subject to LPA view on significance."
    else:
        opinion = "No screening opinion strictly required, but recommended as a safeguard."
        outcome = "Likely not EIA Development."

    # Recommended scope (headline chapters)
    scope = [
        "Landscape & Visual Impact (GLVIA3, photomontages, ZTV)",
        "Ecology (BNG baseline, protected species, HRA if Natura 2000 near)",
        "Heritage & Archaeology (DBA, setting assessment)",
        "Traffic & Transport (construction + operational)",
        "Noise & Vibration (BS 4142 / BS 8233)",
        "Air Quality (IAQM / EA BAT for gensets)",
        "Hydrology & Flood Risk (FRA + SuDS)",
        "Ground Conditions & Contamination (Phase 1 + Phase 2 if needed)",
        "Climate Change (IEMA Assessing Greenhouse Gas Emissions, 2022)",
        "Cumulative Effects Assessment",
    ]
    if is_dc:
        scope.extend([
            "Water Resources (demand, wastewater, thermal discharge)",
            "Socio-economic (employment, skills, business rates)",
            "Electromagnetic Fields (BS EN 55011)",
        ])

    return {
        "schedule_1": schedule_1,
        "schedule_2": schedule_2,
        "opinion": opinion,
        "likely_outcome": outcome,
        "sensitivity_factors": sensitivity or ["None identified from current constraints data."],
        "recommended_scope": scope,
    }


def _dc_technical_schedule(is_dc: bool, capacity_mw: float, a: dict) -> dict | None:
    if not is_dc:
        return None
    it_load = float(a.get("it_load_mw") or capacity_mw)
    pue = a.get("pue_target") or 1.25
    wue = a.get("wue_target_l_per_kwh") or 0.3
    gensets_n = a.get("backup_genset_count") or max(4, math.ceil(it_load / 3.0))
    genset_mva = a.get("backup_genset_mva") or 3.0
    annual_mwh = it_load * pue * 8760
    annual_m3 = a.get("annual_water_m3") or round(annual_mwh * wue / 1000)
    return {
        "ict_load_mw": round(it_load, 2),
        "total_facility_load_mw": round(it_load * pue, 2),
        "power_usage_effectiveness_target": f"PUE ≤ {pue:.2f} (EU EED target 1.2 new-build / 1.3 retrofit by 2027)",
        "cooling_architecture": a.get("cooling", "[Air / evaporative / adiabatic / liquid — architect to confirm]"),
        "water_usage_effectiveness_target": f"WUE ≤ {wue:.2f} L/kWh (techUK 2025 baseline ≤ 0.4 L/kWh for dry/adiabatic)",
        "annual_water_consumption_m3": annual_m3,
        "thames_water_pre_app": "Mandatory engagement — bulk water offer + wastewater discharge consent.",
        "grid_connection_capacity_mw": round(it_load * pue * 1.1, 2),
        "grid_connection_route": "G99 Relevant Embedded Large Power Station (if ≤50 MW import at HV DNO) / direct transmission connection via NESO (if ≥100 MW) — confirm offer ref + energisation date.",
        "standby_generators": f"{gensets_n} × {genset_mva:.1f} MVA standby diesel generators (Stage V / Tier 4 Final; HVO-compatible). Vertical uncapped stacks; 50 hr/yr test cap per EA BAT.",
        "emission_standard": "Stage V compliant; NOx / PM / CO dispersion modelled to IAQM + Defra AQTAG06.",
        "fuel_storage": "Day tanks + bulk storage per BS 5410 / CIRIA C736 (pollution prevention).",
        "heat_reuse_mwth": a.get("heat_reuse_mwth", "[Feasibility assessment required per NPPF 2024 para 161]"),
        "heat_reuse_partner": a.get("heat_reuse_partner", "[LPA / heat network operator engagement required]"),
        "security_bs5357_ls_iso27001": "Physical security to BS 5979 / CPNI guidance; OT security to IEC 62443; ISMS to ISO 27001.",
        "fire_safety": "NFCC BESS guidance (if on-site BESS); BS 9999 for occupied areas; gaseous suppression in data halls (NOVEC / FM200 / Inergen).",
    }


def _build_validation_checklist(
    tech: str, capacity_mw: float, area_ha: float, is_dc: bool,
    fz: int, constraints: dict, a: dict,
) -> dict:
    """LPA validation checklist — national 1APP + typical LPA local list.

    Basis: Town and Country Planning (DMPO) (England) Order 2015; typical
    Slough / Thames Valley local validation list; NPPF 2024; mandatory BNG.
    """
    is_major = area_ha >= 1 or capacity_mw >= 5 or is_dc
    has_heritage = constraints.get("listed_buildings") or constraints.get("conservation_area") or constraints.get("sam")
    has_ecology_risk = constraints.get("sssi") or constraints.get("sac") or constraints.get("spa") or constraints.get("ramsar")

    checklist = {
        "1_1app_application_forms": "Required — signed; correct fee tier; ownership certificate (A/B/C/D); agricultural holdings certificate.",
        "2_location_plan": "Required — 1:1250 or 1:2500; red line; north arrow; scale bar.",
        "3_site_block_plan": "Required — 1:200 or 1:500; existing + proposed; access, parking, landscape, levels.",
        "4_elevations_and_floor_plans": "Required — 1:100; all new and altered elevations and floors.",
        "5_design_and_access_statement": "Required — Article 9 DMPO 2015.",
        "6_planning_statement": "Required — cite NPPF 2024 paras 86(c), 87; Local Plan compliance matrix.",
        "7_energy_and_sustainability_statement": "Required — Be Lean / Be Clean / Be Green / Be Seen hierarchy; whole-life carbon (RICS WLCA 2nd Ed).",
        "8_transport_assessment": (
            "Required — DfT Guidance on Transport Assessment triggers at >5,000 sqm B8." if is_dc
            else ("Required — operational + construction phases." if capacity_mw > 10 else "Transport Statement sufficient.")
        ),
        "9_travel_plan": "Required for major; link to LPA monitoring sum.",
        "10_flood_risk_assessment": (
            "Required — EA FRA Standing Advice + PPG Flood Risk ID 7."
            if (fz >= 2 or area_ha >= 1) else "Not required (Zone 1 < 1 ha)."
        ),
        "11_drainage_strategy_suds": "Required — hierarchy: infiltration → watercourse → surface water sewer → foul (last resort); Qbar greenfield target.",
        "12_water_consumption_statement": "Required — cooling architecture, annual m³, Thames Water / local undertaker engagement letter." if is_dc else "Not normally required.",
        "13_noise_impact_assessment": (
            "Required — BS 4142:2014+A1:2019 for plant; BS 8233 for internal receptors; MID for BS 4142 (gov.uk)."
            if is_dc or tech == "wind" else "Screening sufficient for solar / BESS subject to LPA view."
        ),
        "14_air_quality_assessment": (
            "Required — standby diesel genset stack dispersion modelling; EA BAT for emergency backup diesel engines."
            if is_dc else "Construction dust assessment (IAQM 2014)."
        ),
        "15_biodiversity_net_gain_plan": (
            f"MANDATORY (Environment Act 2021) — 10% statutory minimum, 30-year management. {_cite_reg('statutory_biodiversity_metric')} baseline + gain plan."
        ),
        "16_preliminary_ecological_appraisal": "Required — PEA + species surveys as indicated; CIEEM competent ecologist.",
        "17_habitats_regulations_assessment": "Required — competent authority screening under Conservation of Habitats and Species Regs 2017." if has_ecology_risk else "Not required.",
        "18_landscape_and_visual_impact_assessment": (
            "Required — Guidelines for Landscape & Visual Impact Assessment 3rd Ed. (GLVIA3); photomontages from agreed viewpoints."
            if (is_major or constraints.get("aonb")) else "Recommended."
        ),
        "19_heritage_impact_assessment": "Required — Historic England GPA 3; setting assessment." if has_heritage else "Screening only.",
        "20_archaeological_desk_based_assessment": "Required — CIfA Standard and Guidance for Historic Environment DBA; evaluation trenching if DBA identifies potential.",
        "21_arboricultural_survey": "Required — BS 5837:2012; tree constraints plan; AIA/AMS for works within RPAs.",
        "22_glint_and_glare_study": "Required — FAA SGHAT / Pager Power methodology; receptors include residential, highway, rail, aviation." if tech == "solar" else "Not applicable.",
        "23_agricultural_land_classification": "Required — post-1988 ALC survey if 1:250k maps suggest BMV (Grade 1–3a).",
        "24_external_lighting_assessment": "Required — Institution of Lighting Professionals GN01:21; environmental zone classification.",
        "25_waste_and_circular_economy_statement": "Required — demolition / construction / operational waste hierarchy; reuse + recycling targets.",
        "26_cemp_outline": "Outline CEMP with application; full CEMP secured by pre-commencement condition.",
        "27_ctmp": "Construction Traffic Management Plan — pre-commencement condition.",
        "28_lighting_at_construction": "Task lighting only; curfew if adjacent to residential.",
        "29_fire_safety_strategy": (
            "Required — NFCC BESS guidance v3 (if BESS); BS 9999; gaseous suppression design for data halls."
            if is_dc or tech == "bess" else "Building Regs Part B sufficient for ancillary buildings."
        ),
        "30_utilities_statement": "Required — confirm grid connection offer (G99/G100 or NESO), water, wastewater, telecoms, gas (if applicable).",
        "31_heat_reuse_feasibility": "Required — NPPF 2024 para 161; check Heat Network Zoning under Energy Act 2023." if is_dc else "Not applicable.",
        "32_statement_of_community_involvement": "Required — reference LPA adopted SCI; record pre-app exhibitions, consultation responses.",
        "33_cil_additional_info_form": "Required where LPA has adopted CIL (check LPA charging schedule — Slough has not adopted CIL as of 2024).",
        "34_section_106_draft_heads_of_terms": "Strongly recommended at submission to speed determination.",
        "35_bng_statement_of_intent": "Required at submission; full Biodiversity Gain Plan post-permission, pre-commencement.",
    }
    return checklist


def _s106_heads_of_terms(tech: str, capacity_mw: float, is_dc: bool, area_ha: float, authority: str) -> list[str]:
    heads = [
        "Biodiversity Net Gain — 10% minimum, 30-year HMMP, financial contribution for monitoring / default.",
        "Highways works — junction improvements, bond for repair of construction damage.",
        "Travel Plan monitoring contribution (typically £5k–£15k).",
    ]
    if is_dc:
        heads.extend([
            "Employment & Skills Plan — construction phase apprenticeship targets (typically 1 per £3–5m of build cost); local labour clause; annual KPI reporting.",
            "Heat offtake safeguard — pipework to site boundary by defined operational trigger; first right of refusal for local heat network operator.",
            "Fibre / digital connectivity contribution — leverage DC fibre routing for community benefit.",
            "STEM outreach — school partnerships, work experience, curriculum support.",
        ])
    if tech in ("solar", "wind", "bess"):
        heads.extend([
            "Community Benefit Fund — ~£5k/MW/yr industry benchmark (indicative; not a tax on planning).",
            "Decommissioning bond or equivalent financial instrument — full site restoration.",
            "Landscape & ecology management — long-term stewardship.",
        ])
    if area_ha > 5:
        heads.append("Public access / Public Rights of Way improvements — permissive paths, interpretation boards.")
    return heads


def _cil_note(authority: str, is_dc: bool, area_ha: float) -> str:
    # Slough does not have an adopted CIL charging schedule (as of Jan 2024);
    # many Thames Valley authorities do. Generic note below.
    if "slough" in (authority or "").lower():
        return (
            "Slough Borough Council has not adopted a CIL Charging Schedule (Jan 2024 position). "
            "Contributions via S106 only. Confirm current status at submission."
        )
    return (
        "Check LPA CIL Charging Schedule. CIL is a non-negotiable per-m² tariff; Regulation 123 list of infrastructure replaced by Infrastructure Funding Statements (IFS) since 2019. "
        "CIL additional information form accompanies application."
    )


def _policy_references(tech: str, capacity_mw: float, is_dc: bool, authority: str) -> dict:
    nppf = [
        "NPPF Dec 2024 — para 11 (presumption in favour of sustainable development).",
        "NPPF Dec 2024 — paras 86(c), 87 (data centre needs, clustering, grid proximity).",
        "NPPF Dec 2024 — paras 161, 164–166 (climate change, renewables, low-carbon tech).",
        "NPPF Dec 2024 — para 173 (flood risk sequential / exception).",
        f"{_nppf_para('BMV')} (Best and Most Versatile agricultural land).",
        "NPPF Dec 2024 — paras 189–193 (heritage assets; great weight).",
    ]
    ppg = [
        "PPG Flood Risk and Coastal Change",
        "PPG Noise",
        "PPG Air Quality",
        "PPG Climate Change",
        "PPG Biodiversity Net Gain",
        "PPG Use of Planning Conditions",
    ]
    nps = []
    if tech == "solar" and capacity_mw > 100:
        nps.extend([
            "NPS EN-1 (revised 2025) — overarching energy.",
            "NPS EN-3 (revised 2025) — renewables (solar).",
            "NPS EN-5 — electricity networks.",
        ])
    if tech == "wind" and capacity_mw > 100:
        nps.extend([
            "NPS EN-1 (revised 2025) — overarching energy.",
            "NPS EN-3 (revised 2025) — renewables (wind).",
            "NPS EN-5 — electricity networks.",
        ])
    if is_dc:
        nps.append("No designated NPS for data centres as of Apr 2026 (DSIT consultation opened Feb 2026). NPS EN-1 relevant where NSIP route via s.35 taken.")

    local = ["[Adopted Local Plan — confirm for LPA, include site allocation policies]"]
    if "slough" in (authority or "").lower():
        local = [
            "Slough Local Plan Core Strategy (adopted 2008) — CP1 (spatial strategy), CP4 (Slough Trading Estate), CP8 (sustainability), CP9 (natural + built environment).",
            "Slough Emerging Local Plan — Reg 19 consultation late 2025; SSA2 Slough Trading Estate lists data centres as permitted use.",
            "Slough Site Allocations DPD — relevant allocations.",
            "Slough Local Validation List — https://www.slough.gov.uk/planning-application-validation-requirements",
        ]

    case_law = []
    if is_dc:
        case_law = [
            "Appeal APP/P1940/W/24/3346061 (Abbotts Langley, 12 May 2025) — confirmed B8 use class for 84,000 sqm DC.",
            "Appeal APP/N0410/W/24/3347353 (Bucks, 9 Jul 2025) — confirmed B8 use class for 72,000 sqm DC.",
        ]

    return {
        "nppf_paragraphs": nppf,
        "planning_practice_guidance": ppg,
        "national_policy_statements": nps or ["Not applicable (TCPA route)."],
        "local_plan_policies": local,
        "use_class_case_law": case_law or ["N/A"],
        "statutes": [
            "Town and Country Planning Act 1990 s.70 (TCPA route).",
            "Planning Act 2008 s.14/s.15/s.35 (NSIP route).",
            "Planning and Infrastructure Act 2025 (Royal Assent 18 Dec 2025).",
            "Environment Act 2021 (mandatory BNG).",
            "Conservation of Habitats and Species Regulations 2017 (HRA).",
            "Town and Country Planning (Environmental Impact Assessment) Regulations 2017.",
            "Infrastructure Planning (Business or Commercial Projects) (Amendment) Regulations 2026 (DC NSIP opt-in).",
        ],
    }


def _describe_land_use(land_use: dict) -> str:
    """Describe existing land use from GeeFlow DynamicWorld classes."""
    if not land_use:
        return "[Existing land use to be confirmed]"
    # Map DynamicWorld to readable descriptions
    dw_map = {
        "crops": "Agricultural arable land",
        "grass": "Pastoral grassland",
        "shrub_and_scrub": "Scrubland / marginal land",
        "trees": "Woodland",
        "built": "Previously developed (brownfield)",
        "bare": "Bare ground",
        "water": "Waterbody",
        "flooded_vegetation": "Wetland / marshy ground",
        "snow_and_ice": "Undeveloped land",
    }
    dominant = max(land_use, key=land_use.get) if land_use else None
    if dominant:
        return dw_map.get(dominant, dominant.replace("_", " ").title())
    return "[Existing land use to be confirmed]"


def _default_proposal_description(tech: str, cap_mw: float, area_ha: float, assessment: dict | None = None) -> str:
    a = assessment or {}
    tech = (tech or "solar").lower()
    if tech in ("dc", "data_centre", "datacentre", "hyperscale"):
        gea = a.get("gross_external_area_sqm") or a.get("dc_floorspace_sqm") or int(area_ha * 5500)
        it_load = a.get("it_load_mw") or cap_mw
        pue = a.get("pue_target") or 1.25
        total_mw = it_load * pue
        gensets = a.get("backup_genset_count") or max(4, math.ceil(it_load / 3.0))
        genset_mva = a.get("backup_genset_mva") or 3.0
        return (
            f"Construction and operation of a hyperscale data centre campus comprising data hall buildings with a "
            f"total gross external area (GEA) of approximately {gea:,} sqm on a site of {area_ha:.1f} hectares, with "
            f"a design IT load of {it_load:.1f} MW (total facility load approximately {total_mw:.1f} MW at PUE "
            f"{pue:.2f}). The proposal includes electrical infrastructure (primary substation, transformers, switchgear, "
            f"HV/LV distribution), mechanical cooling plant (chillers, dry/adiabatic coolers, CRAH units), "
            f"{gensets} no. {genset_mva:.1f} MVA standby diesel (HVO-compatible, Stage V) generators with associated "
            f"fuel storage, water treatment plant, security and fire-safety systems, perimeter fencing with CCTV, "
            f"access roads, car and cycle parking (Part S compliant), lorry bays, landscape and biodiversity "
            f"enhancements delivering a minimum 10% Biodiversity Net Gain, and all associated engineering and "
            f"ancillary operations. The development is proposed under Use Class B8 (storage and distribution)."
        )
    tech_desc = {
        "solar": (
            f"Installation of a ground-mounted solar photovoltaic generating station with an installed capacity of "
            f"{cap_mw:.1f} MW on approximately {area_ha:.1f} hectares of land, together with associated infrastructure "
            f"including inverters, transformers, on-site substation, co-located battery energy storage (where applicable), "
            f"security fencing (deer-type, 2.0 m), CCTV, unsurfaced access tracks, landscape and biodiversity "
            f"enhancements delivering a minimum 10% Biodiversity Net Gain, and sheep-grazing management for the "
            f"operational life of the scheme."
        ),
        "wind": (
            f"Erection of wind turbine generators with a combined installed capacity of {cap_mw:.1f} MW, together with "
            f"associated infrastructure including permanent access tracks, crane hardstandings, on-site substation and "
            f"control building, underground cabling, anemometry mast, temporary construction compound and site office, "
            f"and landscape / biodiversity enhancements delivering a minimum 10% Biodiversity Net Gain."
        ),
        "bess": (
            f"Installation of a battery energy storage system (BESS) with a power rating of {cap_mw:.1f} MW and storage "
            f"capacity of approximately {cap_mw * 2:.1f} MWh, together with associated infrastructure including "
            f"inverters, transformers, on-site substation, fire-safety systems (NFCC BESS guidance v3 compliant), "
            f"security fencing, CCTV, access tracks, and landscape / biodiversity enhancements delivering a minimum "
            f"10% Biodiversity Net Gain."
        ),
    }
    return tech_desc.get(tech, f"Installation of a {tech} energy development of {cap_mw:.1f} MW capacity.")


def _tech_max_height(tech: str) -> str:
    return {"solar": "3.0m (panel top)", "wind": "[Hub height + blade length]", "bess": "3.5m (container height)"}.get(tech, "[To be confirmed]")


def _est_construction(cap_mw: float, is_dc: bool = False) -> int:
    if is_dc:
        # Hyperscale DC shells typically 18-30 months per phase; large campuses phased.
        if cap_mw <= 25:
            return 18
        if cap_mw <= 100:
            return 30
        return 42
    if cap_mw <= 5:
        return 4
    elif cap_mw <= 20:
        return 8
    elif cap_mw <= 50:
        return 12
    return 18


def _render_planning_html(form: dict) -> str:
    meta = form["meta"]
    site = form["section_1_site_details"]

    def _section(num: int, title: str, key: str, intro: str | None = None) -> str:
        data = form.get(key)
        if data is None:
            return ""
        body = _render_value(data)
        intro_html = f'<div class="info-box">{intro}</div>' if intro else ""
        return f'<h2>{num}. {title}</h2>{intro_html}{body}'

    sections = []
    sections.append(_section(1, "Site Details", "section_1_site_details"))
    sections.append(_section(2, "Proposed Development", "section_2_proposed_development"))
    sections.append(_section(3, "Existing Use", "section_3_existing_use"))
    sections.append(_section(4, "Access & Transport", "section_4_access_and_transport"))
    sections.append(_section(5, "Flood Risk & Drainage", "section_5_flood_risk_and_drainage",
        "Flood risk under NPPF 2024 para 173 + PPG Flood Risk ID 7. FRA mandatory for sites ≥1 ha or in Flood Zones 2/3."))
    sections.append(_section(6, "Agricultural Land", "section_6_agricultural_land",
        f"Best and Most Versatile (BMV) land = Grades 1, 2, 3a. Material consideration under {_nppf_para('BMV')}."))
    sections.append(_section(7, "Designations & Constraints", "section_7_designations_and_constraints"))
    sections.append(_section(8, "EIA Screening", "section_8_eia_screening",
        "Screening under Town and Country Planning (Environmental Impact Assessment) Regulations 2017. Screening Opinion must be requested from LPA / PINS per Reg. 6 before application."))
    sections.append(_section(9, "Biodiversity Net Gain", "section_9_biodiversity_net_gain",
        f"BNG is MANDATORY under the Environment Act 2021. Minimum 10% net gain, secured for 30 years via S106 or Conservation Covenant. {_cite_reg('statutory_biodiversity_metric')} baseline."))
    sections.append(_section(10, "Climate & Sustainability", "section_10_climate_and_sustainability"))
    if form.get("section_11_dc_technical_schedule"):
        sections.append(_section(11, "Data Centre Technical Schedule", "section_11_dc_technical_schedule",
            "DC-specific technical schedule — power, cooling, water, heat reuse, standby generation, security. Required to demonstrate NPPF 2024 paras 86(c), 87, 161."))
    sections.append(_section(12, "Noise, Air Quality & Lighting", "section_12_noise_air_lighting"))
    sections.append(_section(13, "Supporting Documents — Validation Checklist", "section_13_supporting_documents",
        "National 1APP + typical LPA local validation list. Items marked 'Required' are mandatory for the application to be validated; 'Recommended' items are typically requested by the LPA and speed determination."))
    sections.append(_section(14, "Consultation & Planning Obligations (S106/CIL)", "section_14_consultation_and_obligations"))
    sections.append(_section(15, "Policy References", "section_15_policy_references",
        "Cite these in the Planning Statement. Local Plan policies are LPA-specific — populate from adopted Local Plan."))

    body_html = "\n\n".join(s for s in sections if s)

    banner = ""
    if meta.get("cni_designation") and meta["cni_designation"] != "N/A":
        banner += f'<div class="info-box"><strong>CNI status:</strong> {meta["cni_designation"]}</div>'
    if meta.get("nsip_opt_in_available") and "available" in str(meta["nsip_opt_in_available"]).lower():
        banner += f'<div class="info-box"><strong>NSIP route:</strong> {meta["nsip_opt_in_available"]}</div>'

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Planning Summary — {site.get('site_address', 'Site')}</title>
<style>{_princeps_style()}</style></head><body>
<h1>Planning Application Summary</h1>
<div class="subtitle"><strong>Route:</strong> {meta['planning_route']}</div>
<div class="subtitle"><strong>Determining Authority:</strong> {meta['determining_authority']}</div>
<div class="subtitle"><strong>Legal basis:</strong> {meta.get('route_legal_basis', '')}</div>
<div class="subtitle"><strong>Use Class Order 1987:</strong> {meta.get('use_class_order_1987_as_amended', '')}</div>
<div class="subtitle">Generated by {meta['generated_by']} on {meta['generated_at'][:10]}</div>
{banner}
<div class="disclaimer">{meta['disclaimer']}</div>

{body_html}

{_footer('Planning Application Summary — UK Industry Standard (NPPF 2024 / EIA Regs 2017 / Environment Act 2021 / P&I Act 2025)')}
</body></html>"""


def _render_value(val: Any, depth: int = 0) -> str:
    """Recursively render form values into HTML.

    dict → two-column table (label | value)
    list → bullet list
    scalar → text (with placeholder class if it starts with '[')
    """
    if isinstance(val, dict):
        rows = []
        for k, v in val.items():
            label = k.replace("_", " ").title()
            rendered = _render_value(v, depth + 1)
            rows.append(f'<tr><td class="lbl">{label}</td><td>{rendered}</td></tr>')
        return f"<table>{''.join(rows)}</table>"
    if isinstance(val, list):
        if not val:
            return '<span class="neutral">(none)</span>'
        items = "".join(f"<li>{_render_value(x, depth + 1)}</li>" for x in val)
        return f"<ul>{items}</ul>"
    if val is None:
        return '<span class="neutral">—</span>'
    text = str(val)
    if text.startswith("["):
        return f'<span class="placeholder">{text}</span>'
    if text.lower() in ("required", "mandatory"):
        return f'<span class="cross" style="color:#b45309">{text}</span>'
    if text.lower() in ("yes", "not required", "n/a"):
        return f'<span class="neutral">{text}</span>'
    return text


# ===========================================================================
# 3. EIA Screening Request
# ===========================================================================

def generate_eia_screening(
    site: dict,
    capacity_mw: float,
    constraints: dict,
) -> dict:
    """Generate an EIA screening request under the Town and Country Planning
    (Environmental Impact Assessment) Regulations 2017.

    Args:
        site: {name, address, lat, lon, area_ha, land_use, local_authority}
        capacity_mw: proposed installed capacity in MW
        constraints: {flood_zone, aonb, sssi, sac, spa, ramsar,
                      conservation_area, green_belt, agricultural_grade,
                      proximity_residential_m, proximity_watercourse_m}

    Returns:
        {form_data, html, document_type, auto_fill_pct}
    """
    area_ha = site.get("area_ha", capacity_mw * 2)
    lat = site.get("lat", 0)
    lon = site.get("lon", 0)

    # Schedule 2 threshold checks
    # Solar/wind: >0.5 ha site area OR >5 MW capacity triggers screening
    schedule_2_triggered = capacity_mw > 5 or area_ha > 0.5
    mandatory_eia = capacity_mw > 50  # NSIP route = EIA mandatory (Sched. 1 >50MW)

    # Site sensitivity scoring
    sensitivity_factors = []
    sensitivity_score = 0

    if constraints.get("aonb"):
        sensitivity_factors.append(("AONB / National Landscape", "HIGH", "Designated landscape — strong policy protection"))
        sensitivity_score += 3
    if constraints.get("sssi"):
        sensitivity_factors.append(("SSSI", "HIGH", "Statutory nature conservation site"))
        sensitivity_score += 3
    if constraints.get("sac") or constraints.get("spa") or constraints.get("ramsar"):
        sensitivity_factors.append(("Natura 2000 / Ramsar", "VERY HIGH", "European/international nature conservation"))
        sensitivity_score += 4
    if constraints.get("conservation_area"):
        sensitivity_factors.append(("Conservation Area", "MEDIUM", "Designated heritage asset"))
        sensitivity_score += 2
    if constraints.get("green_belt"):
        sensitivity_factors.append(("Green Belt", "MEDIUM", "Very special circumstances required"))
        sensitivity_score += 2
    fz = constraints.get("flood_zone", 1)
    if fz >= 3:
        sensitivity_factors.append(("Flood Zone 3", "HIGH", "High probability of flooding"))
        sensitivity_score += 3
    elif fz == 2:
        sensitivity_factors.append(("Flood Zone 2", "MEDIUM", "Medium probability of flooding"))
        sensitivity_score += 1
    ag = constraints.get("agricultural_grade", 3)
    if ag <= 2:
        sensitivity_factors.append(("BMV Agricultural Land", "MEDIUM", f"Grade {ag} — best and most versatile"))
        sensitivity_score += 2
    prox_res = constraints.get("proximity_residential_m")
    if prox_res and prox_res < 500:
        sensitivity_factors.append(("Proximity to Receptors", "MEDIUM", f"{prox_res}m to nearest residential"))
        sensitivity_score += 2

    if not sensitivity_factors:
        sensitivity_factors.append(("No sensitive designations identified", "LOW", "Standard site"))

    # Likely significant effects checklist
    effects = {
        "landscape_visual": {
            "likely": capacity_mw > 5 or constraints.get("aonb", False),
            "detail": f"{'Large scale' if capacity_mw > 20 else 'Medium scale'} installation — LVIA {'required' if capacity_mw > 5 else 'recommended'}",
        },
        "ecology_biodiversity": {
            "likely": True,
            "detail": "Habitat disturbance during construction; operational effects on ground-nesting birds. Ecological survey required.",
        },
        "cultural_heritage": {
            "likely": bool(constraints.get("conservation_area") or constraints.get("listed_buildings")),
            "detail": "Potential setting impact on heritage assets" if constraints.get("conservation_area") else "No heritage constraints identified",
        },
        "hydrology_flood_risk": {
            "likely": fz >= 2,
            "detail": f"Flood Zone {fz} — {'FRA required' if fz >= 2 else 'low risk'}",
        },
        "ground_conditions": {
            "likely": capacity_mw > 20,
            "detail": "Ground investigation may be needed for foundation design",
        },
        "traffic_transport": {
            "likely": capacity_mw > 10,
            "detail": f"Construction traffic: est. {int(capacity_mw * 30)} HGV movements over {_est_construction(capacity_mw)} months",
        },
        "noise_vibration": {
            "likely": capacity_mw > 20 or site.get("technology") == "wind",
            "detail": "Inverter/transformer hum; construction noise. Assessment recommended.",
        },
        "glint_glare": {
            "likely": site.get("technology", "solar") == "solar",
            "detail": "Solar panel reflections — glint and glare study required for aviation and residential receptors",
        },
        "cumulative_effects": {
            "likely": capacity_mw > 10,
            "detail": "Assessment of cumulative impact with nearby consented/operational renewable schemes",
        },
        "agricultural_land_loss": {
            "likely": ag <= 3 and capacity_mw > 5,
            "detail": f"Grade {ag} — {'BMV loss is material consideration' if ag <= 2 else 'not BMV but reversible'}",
        },
    }

    # Screening opinion
    if mandatory_eia:
        screening_opinion = "EIA MANDATORY — Schedule 1 development (>50MW generating station)"
        opinion_class = "cross"
    elif sensitivity_score >= 6:
        screening_opinion = "EIA LIKELY REQUIRED — significant environmental sensitivities identified"
        opinion_class = "cross"
    elif schedule_2_triggered and sensitivity_score >= 3:
        screening_opinion = "EIA SCREENING RECOMMENDED — Schedule 2 thresholds exceeded with moderate sensitivity"
        opinion_class = "neutral"
    elif schedule_2_triggered:
        screening_opinion = "EIA SCREENING ADVISABLE — Schedule 2 thresholds exceeded but low sensitivity"
        opinion_class = "neutral"
    else:
        screening_opinion = "EIA UNLIKELY TO BE REQUIRED — below Schedule 2 thresholds"
        opinion_class = "check"

    form = {
        "meta": {
            "document_type": "EIA Screening Request",
            "legislation": "Town and Country Planning (EIA) Regulations 2017",
            "schedule": "Schedule 1" if mandatory_eia else "Schedule 2 (10(a) — industrial installations for production of electricity)",
            "generated_by": "Princeps AI Platform",
            "generated_at": _now_iso(),
            "disclaimer": (
                "Indicative screening assessment only. Formal screening opinion "
                "must be requested from the Local Planning Authority under Reg. 6."
            ),
        },

        "project_details": {
            "site_name": site.get("name", ""),
            "site_address": site.get("address", ""),
            "os_grid_reference": _latlon_to_osgb(lat, lon),
            "local_authority": site.get("local_authority", "[LPA]"),
            "proposal": _default_proposal_description(
                site.get("technology", "solar"), capacity_mw, area_ha
            ),
            "capacity_mw": round(capacity_mw, 2),
            "site_area_ha": round(area_ha, 2),
            "technology": site.get("technology", "solar").title(),
        },

        "schedule_2_assessment": {
            "schedule_2_category": "10(a) — Industrial installations for the production of electricity, steam and hot water",
            "column_1_description": "Energy industry installations",
            "column_2_threshold": ">0.5 hectare or >5 MW",
            "site_exceeds_area_threshold": "Yes" if area_ha > 0.5 else "No",
            "site_exceeds_capacity_threshold": "Yes" if capacity_mw > 5 else "No",
            "screening_required": "Yes" if schedule_2_triggered else "No",
        },

        "sensitivity_analysis": {
            "overall_sensitivity_score": sensitivity_score,
            "sensitivity_rating": (
                "Very High" if sensitivity_score >= 8 else
                "High" if sensitivity_score >= 6 else
                "Medium" if sensitivity_score >= 3 else "Low"
            ),
            "factors": sensitivity_factors,
        },

        "likely_significant_effects": effects,

        "screening_conclusion": {
            "opinion": screening_opinion,
            "mandatory_eia": mandatory_eia,
            "schedule_2_triggered": schedule_2_triggered,
            "sensitivity_score": sensitivity_score,
            "significant_effects_count": sum(1 for e in effects.values() if e["likely"]),
            "recommendation": (
                "Submit EIA with Environmental Statement"
                if mandatory_eia or sensitivity_score >= 6
                else "Request formal Screening Opinion from LPA under Reg. 6"
                if schedule_2_triggered
                else "EIA not expected to be required — proceed with standard application"
            ),
        },
    }

    filled, total = _count_filled(form)
    auto_fill_pct = _pct(filled, total)

    html = _render_eia_html(form, opinion_class)

    return {
        "form_data": form,
        "html": html,
        "document_type": "eia_screening",
        "auto_fill_pct": auto_fill_pct,
    }


def _render_eia_html(form: dict, opinion_class: str) -> str:
    meta = form["meta"]
    sens = form["sensitivity_analysis"]
    effects = form["likely_significant_effects"]
    conclusion = form["screening_conclusion"]

    # Sensitivity factors table
    sens_rows = ""
    for name, level, detail in sens["factors"]:
        color = {"VERY HIGH": "#dc2626", "HIGH": "#ea580c", "MEDIUM": "#d97706", "LOW": "#16a34a"}.get(level, "#6b7280")
        sens_rows += f'<tr><td>{name}</td><td style="color:{color};font-weight:600;">{level}</td><td>{detail}</td></tr>'

    # Effects checklist
    effects_rows = ""
    for effect_name, e in effects.items():
        icon = '<span class="check">Likely</span>' if e["likely"] else '<span class="neutral">Unlikely</span>'
        effects_rows += f'<tr><td>{effect_name.replace("_", " ").title()}</td><td>{icon}</td><td>{e["detail"]}</td></tr>'

    badge_cls = {"check": "badge-go", "cross": "badge-nogo"}.get(opinion_class, "badge-caution")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>EIA Screening — {form['project_details'].get('site_name', 'Site')}</title>
<style>{_princeps_style()}</style></head><body>
<h1>EIA Screening Request</h1>
<div class="subtitle">{meta['legislation']}</div>
<div class="subtitle">{meta['schedule']}</div>
<div class="subtitle">Generated by {meta['generated_by']} on {meta['generated_at'][:10]}</div>
<div class="disclaimer">{meta['disclaimer']}</div>

<h2>1. Project Details</h2>
<table>{_table_rows(form['project_details'])}</table>

<h2>2. Schedule 2 Criteria Assessment</h2>
<table>{_table_rows(form['schedule_2_assessment'])}</table>

<h2>3. Site Sensitivity Analysis</h2>
<div class="{'warn-box' if sens['overall_sensitivity_score'] >= 3 else 'ok-box'}">
  Overall Sensitivity: <strong>{sens['sensitivity_rating']}</strong> (score: {sens['overall_sensitivity_score']}/20)
</div>
<table><tr><th>Factor</th><th>Sensitivity</th><th>Detail</th></tr>{sens_rows}</table>

<h2>4. Likely Significant Effects Checklist</h2>
<table><tr><th>Environmental Topic</th><th>Likely?</th><th>Detail</th></tr>{effects_rows}</table>

<h2>5. Screening Conclusion</h2>
<div style="margin:8px 0;"><span class="badge {badge_cls}">{conclusion['opinion']}</span></div>
<table>
  <tr><td class="lbl">Significant Effects Identified</td><td>{conclusion['significant_effects_count']} of {len(effects)}</td></tr>
  <tr><td class="lbl">Recommendation</td><td><strong>{conclusion['recommendation']}</strong></td></tr>
</table>

{_footer('EIA Screening Assessment')}
</body></html>"""


# ===========================================================================
# 4. CDM F10 Notification
# ===========================================================================

def generate_f10_notification(
    site: dict,
    capacity_mw: float,
    timeline: dict,
) -> dict:
    """Generate a pre-filled CDM 2015 F10 Notification for HSE.

    The Construction (Design and Management) Regulations 2015 require an F10
    to be sent to HSE before construction begins if the project involves
    >30 working days with >20 workers simultaneously, OR >500 person-days.

    Args:
        site: {name, address, postcode, lat, lon}
        capacity_mw: installed capacity in MW
        timeline: {start_date, end_date, duration_months, max_workers,
                   client_name, client_address, pd_name, pd_company,
                   pc_name, pc_company}

    Returns:
        {form_data, html, document_type, auto_fill_pct}
    """
    duration_months = timeline.get("duration_months", _est_construction(capacity_mw))
    duration_days = duration_months * 22  # working days
    max_workers = timeline.get("max_workers", _est_max_workers(capacity_mw))
    person_days = int(duration_days * max_workers * 0.7)  # average occupancy ~70%

    # F10 trigger check
    trigger_30day_20worker = duration_days > 30 and max_workers > 20
    trigger_500pd = person_days > 500
    f10_required = trigger_30day_20worker or trigger_500pd

    form = {
        "meta": {
            "document_type": "CDM F10 Notification to HSE",
            "legislation": "Construction (Design and Management) Regulations 2015",
            "regulation": "Regulation 6 — Notification",
            "hse_submission": "Online at https://www.hse.gov.uk/forms/notification/f10.htm",
            "generated_by": "Princeps AI Platform",
            "generated_at": _now_iso(),
            "disclaimer": (
                "Pre-filled F10 notification data. Must be submitted by the Client "
                "or on their behalf before the construction phase begins."
            ),
        },

        "notification_trigger": {
            "f10_required": "Yes" if f10_required else "No",
            "trigger_reason": (
                "Project exceeds 30 working days AND 20+ simultaneous workers"
                if trigger_30day_20worker
                else "Project exceeds 500 person-days"
                if trigger_500pd
                else "Below notification thresholds (submit voluntarily if desired)"
            ),
            "estimated_working_days": duration_days,
            "estimated_max_workers": max_workers,
            "estimated_person_days": person_days,
        },

        "section_1_project": {
            "project_title": f"{site.get('name', 'Solar Farm')} — {capacity_mw:.1f} MW {'Solar Farm' if capacity_mw > 0 else 'Energy Project'}",
            "project_description": (
                f"Construction of a {capacity_mw:.1f} MW ground-mounted solar "
                f"photovoltaic generating station including civil works, "
                f"electrical installation, grid connection, and commissioning."
            ),
            "site_address": site.get("address", site.get("name", "")),
            "postcode": site.get("postcode", ""),
            "local_authority": site.get("local_authority", "[LPA]"),
        },

        "section_2_client": {
            "client_name": timeline.get("client_name", "[Client Name]"),
            "client_address": timeline.get("client_address", "[Client Address]"),
            "client_contact": "[Contact name]",
            "client_phone": "[Phone]",
            "client_email": "[Email]",
        },

        "section_3_principal_designer": {
            "pd_name": timeline.get("pd_name", "[Principal Designer Name]"),
            "pd_company": timeline.get("pd_company", "[PD Company]"),
            "pd_address": "[PD Address]",
            "pd_phone": "[Phone]",
            "pd_email": "[Email]",
            "pd_appointment_date": "[Date of appointment]",
        },

        "section_4_principal_contractor": {
            "pc_name": timeline.get("pc_name", "[Principal Contractor Name]"),
            "pc_company": timeline.get("pc_company", "[PC Company]"),
            "pc_address": "[PC Address]",
            "pc_phone": "[Phone]",
            "pc_email": "[Email]",
            "pc_appointment_date": "[Date of appointment]",
        },

        "section_5_dates": {
            "planned_start_date": timeline.get("start_date", "[Start date]"),
            "planned_end_date": timeline.get("end_date", "[End date]"),
            "estimated_duration_weeks": round(duration_months * 4.3),
            "estimated_duration_months": duration_months,
            "max_workers_at_any_time": max_workers,
            "planned_number_of_contractors": _est_contractors(capacity_mw),
        },

        "section_6_existing_risks": {
            "asbestos_survey_required": "Pre-demolition survey if existing buildings",
            "ground_contamination": "[Phase 1 desk study to be undertaken]",
            "overhead_power_lines": "[Check — exclusion zones per GS6/HSE]",
            "underground_services": "[CAT/Genny survey before excavation]",
            "public_access_to_site": "[Secure site boundary with Heras fencing]",
            "working_at_height": "Panel mounting — scaffolding/MEWP for substations",
            "lifting_operations": "Transformer delivery — appointed person, lift plan",
            "electrical_hazards": "HV commissioning — SAP/SCP, permits to work",
        },
    }

    filled, total = _count_filled(form)
    auto_fill_pct = _pct(filled, total)

    html = _render_f10_html(form, f10_required)

    return {
        "form_data": form,
        "html": html,
        "document_type": "cdm_f10",
        "auto_fill_pct": auto_fill_pct,
    }


def _est_max_workers(cap_mw: float) -> int:
    if cap_mw <= 5:
        return 15
    elif cap_mw <= 20:
        return 40
    elif cap_mw <= 50:
        return 80
    return 150


def _est_contractors(cap_mw: float) -> int:
    if cap_mw <= 5:
        return 3
    elif cap_mw <= 20:
        return 5
    elif cap_mw <= 50:
        return 8
    return 12


def _render_f10_html(form: dict, f10_required: bool) -> str:
    meta = form["meta"]
    trigger = form["notification_trigger"]
    box_cls = "warn-box" if f10_required else "ok-box"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>CDM F10 — {form['section_1_project'].get('project_title', 'Project')}</title>
<style>{_princeps_style()}</style></head><body>
<h1>CDM F10 Notification</h1>
<div class="subtitle">{meta['legislation']}</div>
<div class="subtitle">{meta['regulation']}</div>
<div class="subtitle">Generated by {meta['generated_by']} on {meta['generated_at'][:10]}</div>
<div class="disclaimer">{meta['disclaimer']}</div>

<div class="{box_cls}">
  <strong>F10 Notification {'REQUIRED' if f10_required else 'Not Required'}</strong><br>
  {trigger['trigger_reason']}
</div>

<h2>1. Project Details</h2>
<table>{_table_rows(form['section_1_project'])}</table>

<h2>2. Client Details</h2>
<table>{_table_rows(form['section_2_client'])}</table>

<h2>3. Principal Designer</h2>
<table>{_table_rows(form['section_3_principal_designer'])}</table>

<h2>4. Principal Contractor</h2>
<table>{_table_rows(form['section_4_principal_contractor'])}</table>

<h2>5. Dates and Workforce</h2>
<table>{_table_rows(form['section_5_dates'])}</table>

<h2>6. Existing Risks and Hazards</h2>
<table>{_table_rows(form['section_6_existing_risks'])}</table>

<div class="info-box">
  Submit online: <strong>{meta['hse_submission']}</strong><br>
  The F10 must be submitted by the Client (or on their behalf) before the construction phase begins.
</div>

{_footer('CDM F10 Notification')}
</body></html>"""


# ===========================================================================
# 5. BNG Baseline Assessment
# ===========================================================================

# DynamicWorld class -> UKHab broad habitat mapping
DYNAMICWORLD_TO_UKHAB = {
    "crops": {
        "ukhab": "c1 — Arable and horticulture",
        "distinctiveness": "Low",
        "distinctiveness_score": 2,
        "default_condition": "Poor",
        "condition_score": 1,
    },
    "grass": {
        "ukhab": "g3 — Modified grassland",
        "distinctiveness": "Low",
        "distinctiveness_score": 2,
        "default_condition": "Moderate",
        "condition_score": 2,
    },
    "shrub_and_scrub": {
        "ukhab": "h3 — Mixed scrub",
        "distinctiveness": "Medium",
        "distinctiveness_score": 4,
        "default_condition": "Moderate",
        "condition_score": 2,
    },
    "trees": {
        "ukhab": "w1 — Broadleaved woodland",
        "distinctiveness": "High",
        "distinctiveness_score": 6,
        "default_condition": "Moderate",
        "condition_score": 2,
    },
    "built": {
        "ukhab": "u1 — Developed land; sealed surface",
        "distinctiveness": "V.Low",
        "distinctiveness_score": 0,
        "default_condition": "N/A — Other",
        "condition_score": 0,
    },
    "bare": {
        "ukhab": "u1 — Artificial unvegetated",
        "distinctiveness": "V.Low",
        "distinctiveness_score": 0,
        "default_condition": "N/A — Other",
        "condition_score": 0,
    },
    "water": {
        "ukhab": "r1 — Standing open water",
        "distinctiveness": "Medium",
        "distinctiveness_score": 4,
        "default_condition": "Moderate",
        "condition_score": 2,
    },
    "flooded_vegetation": {
        "ukhab": "f2 — Reedbeds",
        "distinctiveness": "High",
        "distinctiveness_score": 6,
        "default_condition": "Moderate",
        "condition_score": 2,
    },
    "snow_and_ice": {
        "ukhab": "u1 — Other",
        "distinctiveness": "V.Low",
        "distinctiveness_score": 0,
        "default_condition": "N/A",
        "condition_score": 0,
    },
}

# Solar farm habitat creation strategies (for 10% net gain)
SOLAR_HABITAT_STRATEGIES = [
    {
        "habitat": "Wildflower meadow (g3a — Other neutral grassland)",
        "distinctiveness": "Medium (4)",
        "bu_per_ha": 8.0,
        "notes": "Seed under/between panels. High compatibility with solar operations.",
        "time_to_target_years": 5,
    },
    {
        "habitat": "Species-rich hedgerow planting",
        "distinctiveness": "Medium (4)",
        "bu_per_ha": 6.0,  # per 100m of hedgerow
        "notes": "Site boundary screening + biodiversity. Double-count for landscape and BNG.",
        "time_to_target_years": 10,
    },
    {
        "habitat": "Native woodland copse",
        "distinctiveness": "High (6)",
        "bu_per_ha": 12.0,
        "notes": "Corners and edges of site. Avoid shading panels. 30-year management plan.",
        "time_to_target_years": 15,
    },
    {
        "habitat": "Pond / wetland creation",
        "distinctiveness": "High (6)",
        "bu_per_ha": 12.0,
        "notes": "SuDS attenuation integrated with BNG. Great Crested Newt potential.",
        "time_to_target_years": 5,
    },
    {
        "habitat": "Tussocky grassland margins",
        "distinctiveness": "Low (2)",
        "bu_per_ha": 4.0,
        "notes": "Easy win around fence lines. Benefits small mammals and reptiles.",
        "time_to_target_years": 3,
    },
]


def generate_bng_baseline(
    site: dict,
    geeflow_data: dict,
) -> dict:
    """Generate a simplified BNG baseline assessment using DynamicWorld land cover.

    Uses the Defra Biodiversity Metric 4.0 simplified methodology:
    Biodiversity Units = Area (ha) x Distinctiveness x Condition x Strategic Significance

    Args:
        site: {name, lat, lon, area_ha}
        geeflow_data: {land_use: {class: pct, ...}, ndvi_mean, ndvi_trend}

    Returns:
        {form_data, html, document_type, auto_fill_pct}
    """
    area_ha = site.get("area_ha", 10.0)
    land_use = geeflow_data.get("land_use", {})

    # Calculate baseline biodiversity units per habitat
    habitat_baseline = []
    total_baseline_bu = 0

    for dw_class, pct in land_use.items():
        if pct <= 0:
            continue
        mapping = DYNAMICWORLD_TO_UKHAB.get(dw_class)
        if not mapping:
            continue
        habitat_area = area_ha * pct / 100
        # BU = area x distinctiveness x condition x strategic (1.0 default)
        bu = habitat_area * mapping["distinctiveness_score"] * mapping["condition_score"] * 1.0
        total_baseline_bu += bu
        habitat_baseline.append({
            "dynamicworld_class": dw_class,
            "ukhab_habitat": mapping["ukhab"],
            "area_ha": round(habitat_area, 2),
            "area_pct": round(pct, 1),
            "distinctiveness": mapping["distinctiveness"],
            "distinctiveness_score": mapping["distinctiveness_score"],
            "condition": mapping["default_condition"],
            "condition_score": mapping["condition_score"],
            "strategic_significance": 1.0,
            "biodiversity_units": round(bu, 2),
        })

    # If no land use data provided, estimate from area
    if not habitat_baseline:
        # Assume modified grassland as default
        bu = area_ha * 2 * 2 * 1.0
        total_baseline_bu = bu
        habitat_baseline.append({
            "dynamicworld_class": "grass (assumed)",
            "ukhab_habitat": "g3 — Modified grassland",
            "area_ha": round(area_ha, 2),
            "area_pct": 100,
            "distinctiveness": "Low",
            "distinctiveness_score": 2,
            "condition": "Moderate",
            "condition_score": 2,
            "strategic_significance": 1.0,
            "biodiversity_units": round(bu, 2),
        })

    total_baseline_bu = round(total_baseline_bu, 2)

    # 10% net gain target
    net_gain_target_bu = round(total_baseline_bu * 0.10, 2)
    # Total post-development BU needed
    post_dev_target = round(total_baseline_bu + net_gain_target_bu, 2)

    # Estimate habitat creation needed (using wildflower meadow as primary strategy)
    primary_strategy = SOLAR_HABITAT_STRATEGIES[0]
    creation_area_ha = round(net_gain_target_bu / primary_strategy["bu_per_ha"], 2) if primary_strategy["bu_per_ha"] > 0 else 0

    # NDVI condition adjustment
    ndvi = geeflow_data.get("ndvi_mean")
    ndvi_note = ""
    if ndvi is not None:
        if ndvi > 0.6:
            ndvi_note = f"NDVI {ndvi:.2f} — good vegetation condition, baseline may be higher"
        elif ndvi < 0.3:
            ndvi_note = f"NDVI {ndvi:.2f} — poor vegetation, baseline may be lower"
        else:
            ndvi_note = f"NDVI {ndvi:.2f} — moderate vegetation condition"

    form = {
        "meta": {
            "document_type": "BNG Baseline Assessment (Simplified)",
            "legislation": "Environment Act 2021 — Biodiversity Net Gain",
            "metric": "Defra Biodiversity Metric 4.0 (simplified)",
            "net_gain_requirement": "Minimum 10% measurable biodiversity net gain",
            "generated_by": "Princeps AI Platform",
            "generated_at": _now_iso(),
            "disclaimer": (
                "Simplified BNG baseline from satellite land cover classification. "
                "A full Biodiversity Metric 4.0 assessment by a qualified ecologist "
                "is required for planning submission."
            ),
        },

        "site_summary": {
            "site_name": site.get("name", ""),
            "total_area_ha": round(area_ha, 2),
            "os_grid_reference": _latlon_to_osgb(site.get("lat", 0), site.get("lon", 0)),
            "data_source": "Google DynamicWorld V1 satellite classification",
            "ndvi_condition": ndvi_note or "No NDVI data available",
        },

        "habitat_baseline": habitat_baseline,

        "baseline_summary": {
            "total_baseline_biodiversity_units": total_baseline_bu,
            "number_of_habitat_types": len(habitat_baseline),
            "dominant_habitat": (
                max(habitat_baseline, key=lambda h: h["area_ha"])["ukhab_habitat"]
                if habitat_baseline else "Unknown"
            ),
        },

        "net_gain_target": {
            "baseline_bu": total_baseline_bu,
            "required_gain_pct": 10,
            "required_gain_bu": net_gain_target_bu,
            "post_development_target_bu": post_dev_target,
        },

        "habitat_creation_strategies": SOLAR_HABITAT_STRATEGIES,

        "recommended_approach": {
            "primary_strategy": primary_strategy["habitat"],
            "estimated_creation_area_ha": creation_area_ha,
            "pct_of_site_area": round(creation_area_ha / area_ha * 100, 1) if area_ha > 0 else 0,
            "time_to_target_condition_years": primary_strategy["time_to_target_years"],
            "management_plan_duration_years": 30,
            "note": (
                "Solar farms are well-suited to BNG delivery: panels provide "
                "shade/shelter for grassland, and site boundaries accommodate "
                "hedgerow and woodland planting."
            ),
        },
    }

    filled, total = _count_filled(form)
    auto_fill_pct = _pct(filled, total)

    html = _render_bng_html(form)

    return {
        "form_data": form,
        "html": html,
        "document_type": "bng_baseline",
        "auto_fill_pct": auto_fill_pct,
    }


def _render_bng_html(form: dict) -> str:
    meta = form["meta"]
    baseline = form["habitat_baseline"]
    summary = form["baseline_summary"]
    target = form["net_gain_target"]
    strategies = form["habitat_creation_strategies"]
    approach = form["recommended_approach"]

    # Habitat baseline table
    hab_rows = ""
    for h in baseline:
        hab_rows += (
            f'<tr><td>{h["ukhab_habitat"]}</td><td>{h["area_ha"]}</td>'
            f'<td>{h["distinctiveness"]}</td><td>{h["condition"]}</td>'
            f'<td><strong>{h["biodiversity_units"]}</strong></td></tr>'
        )

    # Strategy table
    strat_rows = ""
    for s in strategies:
        strat_rows += (
            f'<tr><td>{s["habitat"]}</td><td>{s["distinctiveness"]}</td>'
            f'<td>{s["bu_per_ha"]}</td><td>{s["time_to_target_years"]} yrs</td>'
            f'<td>{s["notes"]}</td></tr>'
        )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>BNG Baseline — {form['site_summary'].get('site_name', 'Site')}</title>
<style>{_princeps_style()}</style></head><body>
<h1>Biodiversity Net Gain Baseline Assessment</h1>
<div class="subtitle">{meta['legislation']}</div>
<div class="subtitle">{meta['metric']}</div>
<div class="subtitle">Generated by {meta['generated_by']} on {meta['generated_at'][:10]}</div>
<div class="disclaimer">{meta['disclaimer']}</div>

<h2>Site Summary</h2>
<table>{_table_rows(form['site_summary'])}</table>

<h2>Habitat Baseline</h2>
<table>
  <tr><th>UKHab Habitat</th><th>Area (ha)</th><th>Distinctiveness</th><th>Condition</th><th>BU</th></tr>
  {hab_rows}
</table>

<div class="info-box">
  <strong>Baseline Total: {summary['total_baseline_biodiversity_units']} Biodiversity Units</strong>
  across {summary['number_of_habitat_types']} habitat type(s).
  Dominant habitat: {summary['dominant_habitat']}
</div>

<h2>10% Net Gain Target</h2>
<table>
  <tr><td class="lbl">Baseline BU</td><td>{target['baseline_bu']}</td></tr>
  <tr><td class="lbl">Required Gain (10%)</td><td><strong>+{target['required_gain_bu']} BU</strong></td></tr>
  <tr><td class="lbl">Post-Development Target</td><td><strong>{target['post_development_target_bu']} BU</strong></td></tr>
</table>

<h2>Habitat Creation Strategies for Solar Farms</h2>
<table>
  <tr><th>Habitat</th><th>Distinctiveness</th><th>BU/ha</th><th>Time to Target</th><th>Notes</th></tr>
  {strat_rows}
</table>

<h2>Recommended Approach</h2>
<div class="ok-box">
  <strong>{approach['primary_strategy']}</strong><br>
  Create approximately <strong>{approach['estimated_creation_area_ha']} ha</strong>
  ({approach['pct_of_site_area']}% of site area) to achieve 10% net gain.<br>
  {approach['note']}
</div>
<table>{_table_rows(approach)}</table>

{_footer('BNG Baseline Assessment')}
</body></html>"""


# ===========================================================================
# 6. Licence Exemption Memo
# ===========================================================================

def generate_licence_memo(capacity_kw: float) -> dict:
    """Generate a memo confirming electricity generation licence exemption status.

    Under the Electricity (Class Exemptions from the Requirement for a Licence)
    Order 2001, generators below 50 MW are exempt from holding a generation licence.

    Args:
        capacity_kw: proposed installed capacity in kW

    Returns:
        {form_data, html, document_type, auto_fill_pct}
    """
    capacity_mw = capacity_kw / 1000
    is_exempt = capacity_mw < 50

    # Relevant exemption classes
    if capacity_mw < 10:
        exemption_class = "Class A — Small generators (declared net capacity <10 MW)"
        class_detail = (
            "The station has a declared net capacity of less than 10 MW and "
            "qualifies for Class A exemption under Schedule 2 of the Order."
        )
    elif capacity_mw < 50:
        exemption_class = "Class B — Medium generators (declared net capacity <50 MW)"
        class_detail = (
            "The station has a declared net capacity of less than 50 MW and "
            "qualifies for Class B exemption under Schedule 2 of the Order, "
            "provided it is not a large power station as defined in the Electricity Act 1989."
        )
    else:
        exemption_class = "NO EXEMPTION — Generation licence required from Ofgem"
        class_detail = (
            "The station has a declared net capacity of 50 MW or more and "
            "requires a generation licence from the Gas and Electricity Markets Authority (Ofgem) "
            "under Section 6 of the Electricity Act 1989."
        )

    # Supply licence check
    supply_exempt = capacity_mw < 5
    supply_note = (
        "Exempt from supply licence requirement (DNC <5 MW)"
        if supply_exempt
        else "May require supply licence if supplying third parties directly (DNC >= 5 MW)"
    )

    form = {
        "meta": {
            "document_type": "Licence Exemption Memo",
            "legislation": "Electricity Act 1989, Section 4",
            "order": "Electricity (Class Exemptions from the Requirement for a Licence) Order 2001 (SI 2001/3270)",
            "amended_by": "Electricity (Class Exemptions from the Requirement for a Licence) (Amendment) Order 2007",
            "generated_by": "Princeps AI Platform",
            "generated_at": _now_iso(),
            "disclaimer": (
                "This memo is for information only and does not constitute legal advice. "
                "Consult a qualified energy lawyer to confirm exemption status."
            ),
        },

        "capacity_assessment": {
            "declared_net_capacity_kw": round(capacity_kw, 1),
            "declared_net_capacity_mw": round(capacity_mw, 2),
            "exemption_threshold_mw": 50,
            "is_exempt": is_exempt,
        },

        "exemption_determination": {
            "status": "EXEMPT" if is_exempt else "LICENCE REQUIRED",
            "exemption_class": exemption_class,
            "class_detail": class_detail,
            "supply_licence_status": supply_note,
        },

        "legal_references": {
            "electricity_act_1989_s4": (
                "Section 4(1): It shall be unlawful for a person to generate electricity "
                "for the purpose of giving a supply to any premises or enabling a supply "
                "to be so given unless he is authorised to do so by a licence or is exempted."
            ),
            "class_exemptions_order_2001": (
                "SI 2001/3270: Provides class exemptions for small and medium generators "
                "from the requirement to hold a generation licence."
            ),
            "ofgem_guidance": (
                "Ofgem Decision Letter: Generators with DNC <50 MW are exempt from "
                "the requirement for a generation licence, subject to conditions in the Order."
            ),
        },

        "conditions_and_obligations": {
            "roc_eligibility": "Yes — exempt generators may receive ROCs/CFDs" if is_exempt else "N/A",
            "bsc_participation": (
                "Optional — may register as a BSC Party for settlement purposes"
                if is_exempt else "Required"
            ),
            "grid_code_compliance": (
                "Required if DNC >1 MW and connected at 132 kV or above"
                if capacity_mw > 1 else "Not required"
            ),
            "distribution_code_compliance": "Required for all connections to DNO network",
            "data_registration": (
                "Register with Elexon as an Exempt Export BMU if >100 kW"
                if capacity_kw > 100 else "No registration required"
            ),
        },
    }

    filled, total = _count_filled(form)
    auto_fill_pct = _pct(filled, total)

    html = _render_licence_html(form, is_exempt)

    return {
        "form_data": form,
        "html": html,
        "document_type": "licence_memo",
        "auto_fill_pct": auto_fill_pct,
    }


def _render_licence_html(form: dict, is_exempt: bool) -> str:
    meta = form["meta"]
    det = form["exemption_determination"]
    cap = form["capacity_assessment"]

    status_cls = "ok-box" if is_exempt else "warn-box"
    badge_cls = "badge-go" if is_exempt else "badge-nogo"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Licence Exemption Memo</title>
<style>{_princeps_style()}</style></head><body>
<h1>Electricity Generation Licence — Exemption Memo</h1>
<div class="subtitle">{meta['legislation']}</div>
<div class="subtitle">{meta['order']}</div>
<div class="subtitle">Generated by {meta['generated_by']} on {meta['generated_at'][:10]}</div>
<div class="disclaimer">{meta['disclaimer']}</div>

<div class="{status_cls}">
  <span class="badge {badge_cls}">{det['status']}</span>
  <div style="margin-top:6px;"><strong>{det['exemption_class']}</strong></div>
  <div>{det['class_detail']}</div>
</div>

<h2>Capacity Assessment</h2>
<table>{_table_rows(cap)}</table>

<h2>Exemption Determination</h2>
<table>{_table_rows(det)}</table>

<h2>Legal References</h2>
<table>{_table_rows(form['legal_references'])}</table>

<h2>Conditions and Obligations</h2>
<table>{_table_rows(form['conditions_and_obligations'])}</table>

{_footer('Licence Exemption Memo')}
</body></html>"""


# ===========================================================================
# Document Checklist
# ===========================================================================

# Full document requirements matrix
DOCUMENT_REQUIREMENTS = [
    {
        "id": "g99_application",
        "name": "G99 Grid Connection Application",
        "category": "Grid Connection",
        "required_if": lambda cap_kw, tech, constraints: cap_kw > 50,
        "description": "ENA EREC G99 application to DNO for bespoke connection assessment",
        "typical_lead_time_weeks": 12,
    },
    {
        "id": "g100_application",
        "name": "G100 Type-Tested Application",
        "category": "Grid Connection",
        "required_if": lambda cap_kw, tech, constraints: 16 < cap_kw <= 50,
        "description": "Simplified application for type-tested inverter systems 16A-50kW",
        "typical_lead_time_weeks": 6,
    },
    {
        "id": "planning_application",
        "name": "Full Planning Application (1APP)",
        "category": "Planning",
        "required_if": lambda cap_kw, tech, constraints: cap_kw > 50 and cap_kw / 1000 <= 50,
        "description": "Town and Country Planning Act 1990 — full application to LPA",
        "typical_lead_time_weeks": 16,
    },
    {
        "id": "dco_application",
        "name": "Development Consent Order",
        "category": "Planning",
        "required_if": lambda cap_kw, tech, constraints: cap_kw / 1000 > 50,
        "description": "NSIP application to Planning Inspectorate under Planning Act 2008",
        "typical_lead_time_weeks": 78,
    },
    {
        "id": "eia_screening",
        "name": "EIA Screening Request",
        "category": "Environmental",
        "required_if": lambda cap_kw, tech, constraints: cap_kw / 1000 > 5 or constraints.get("area_ha", 0) > 0.5,
        "description": "Reg. 6 screening opinion request under EIA Regulations 2017",
        "typical_lead_time_weeks": 3,
    },
    {
        "id": "eia_scoping",
        "name": "EIA Scoping Report",
        "category": "Environmental",
        "required_if": lambda cap_kw, tech, constraints: cap_kw / 1000 > 50 or constraints.get("sensitivity_score", 0) >= 6,
        "description": "Reg. 15 scoping opinion for Environmental Statement content",
        "typical_lead_time_weeks": 5,
    },
    {
        "id": "environmental_statement",
        "name": "Environmental Statement",
        "category": "Environmental",
        "required_if": lambda cap_kw, tech, constraints: cap_kw / 1000 > 50,
        "description": "Full ES for EIA development — submitted with planning/DCO application",
        "typical_lead_time_weeks": 26,
    },
    {
        "id": "ecological_survey",
        "name": "Preliminary Ecological Appraisal",
        "category": "Environmental",
        "required_if": lambda cap_kw, tech, constraints: True,
        "description": "Phase 1 habitat survey and protected species assessment",
        "typical_lead_time_weeks": 4,
    },
    {
        "id": "bng_assessment",
        "name": "BNG Baseline Assessment",
        "category": "Environmental",
        "required_if": lambda cap_kw, tech, constraints: True,
        "description": "Biodiversity Metric 4.0 — baseline + gain plan for 10% net gain",
        "typical_lead_time_weeks": 4,
    },
    {
        "id": "flood_risk_assessment",
        "name": "Flood Risk Assessment",
        "category": "Environmental",
        "required_if": lambda cap_kw, tech, constraints: constraints.get("flood_zone", 1) >= 2 or constraints.get("area_ha", 0) > 1,
        "description": "Site-specific FRA for Environment Agency and LPA",
        "typical_lead_time_weeks": 4,
    },
    {
        "id": "cdm_f10",
        "name": "CDM F10 Notification",
        "category": "Health & Safety",
        "required_if": lambda cap_kw, tech, constraints: cap_kw / 1000 > 1,
        "description": "CDM 2015 Reg. 6 notification to HSE before construction",
        "typical_lead_time_weeks": 1,
    },
    {
        "id": "construction_phase_plan",
        "name": "Construction Phase Plan",
        "category": "Health & Safety",
        "required_if": lambda cap_kw, tech, constraints: True,
        "description": "CDM 2015 — health and safety arrangements for construction",
        "typical_lead_time_weeks": 4,
    },
    {
        "id": "licence_memo",
        "name": "Generation Licence Exemption Memo",
        "category": "Licensing",
        "required_if": lambda cap_kw, tech, constraints: cap_kw / 1000 < 50,
        "description": "Confirmation of exemption under Class Exemptions Order 2001",
        "typical_lead_time_weeks": 1,
    },
    {
        "id": "generation_licence",
        "name": "Ofgem Generation Licence",
        "category": "Licensing",
        "required_if": lambda cap_kw, tech, constraints: cap_kw / 1000 >= 50,
        "description": "Application to Ofgem for electricity generation licence",
        "typical_lead_time_weeks": 12,
    },
    {
        "id": "lvia",
        "name": "Landscape and Visual Impact Assessment",
        "category": "Planning",
        "required_if": lambda cap_kw, tech, constraints: cap_kw / 1000 > 5 or constraints.get("aonb"),
        "description": "Professional LVIA with viewpoint photography and photomontages",
        "typical_lead_time_weeks": 8,
    },
    {
        "id": "transport_statement",
        "name": "Transport Statement / Assessment",
        "category": "Planning",
        "required_if": lambda cap_kw, tech, constraints: cap_kw / 1000 > 10,
        "description": "Construction traffic impact assessment and management plan",
        "typical_lead_time_weeks": 4,
    },
    {
        "id": "noise_assessment",
        "name": "Noise Impact Assessment",
        "category": "Planning",
        "required_if": lambda cap_kw, tech, constraints: tech == "wind" or (tech == "bess" and cap_kw / 1000 > 10),
        "description": "BS 4142 assessment for operational noise impact on receptors",
        "typical_lead_time_weeks": 4,
    },
    {
        "id": "glint_glare",
        "name": "Glint and Glare Assessment",
        "category": "Planning",
        "required_if": lambda cap_kw, tech, constraints: tech == "solar",
        "description": "Solar reflection analysis for residential and aviation receptors",
        "typical_lead_time_weeks": 3,
    },
    {
        "id": "heritage_assessment",
        "name": "Heritage Impact Assessment",
        "category": "Planning",
        "required_if": lambda cap_kw, tech, constraints: constraints.get("listed_buildings") or constraints.get("conservation_area"),
        "description": "Assessment of impact on designated and non-designated heritage assets",
        "typical_lead_time_weeks": 6,
    },
    {
        "id": "agricultural_land_classification",
        "name": "Agricultural Land Classification Survey",
        "category": "Planning",
        "required_if": lambda cap_kw, tech, constraints: constraints.get("agricultural_grade", 4) <= 3 and tech == "solar",
        "description": "Soil survey to confirm ALC grade and BMV status",
        "typical_lead_time_weeks": 4,
    },
    {
        "id": "grid_power_flow_study",
        "name": "Grid Power Flow Study",
        "category": "Grid Connection",
        "required_if": lambda cap_kw, tech, constraints: cap_kw / 1000 > 5,
        "description": "Load flow and fault level analysis for connection assessment",
        "typical_lead_time_weeks": 4,
    },
    {
        "id": "bess_fire_safety",
        "name": "BESS Fire Safety Assessment",
        "category": "Health & Safety",
        "required_if": lambda cap_kw, tech, constraints: tech == "bess" or constraints.get("includes_bess"),
        "description": "NFCC guidance compliance — fire risk assessment for battery storage",
        "typical_lead_time_weeks": 4,
    },
    {
        "id": "decommissioning_plan",
        "name": "Decommissioning Plan",
        "category": "Planning",
        "required_if": lambda cap_kw, tech, constraints: cap_kw / 1000 > 5,
        "description": "Site restoration plan and financial security (planning condition)",
        "typical_lead_time_weeks": 2,
    },
    {
        "id": "community_benefit_scheme",
        "name": "Community Benefit Scheme",
        "category": "Planning",
        "required_if": lambda cap_kw, tech, constraints: cap_kw / 1000 > 5,
        "description": "Community fund / shared ownership proposal",
        "typical_lead_time_weeks": 2,
    },
]


def get_document_checklist(
    capacity_kw: float,
    technology: str = "solar",
    constraints: dict | None = None,
) -> dict:
    """Return a checklist of all required documents for a given project.

    Args:
        capacity_kw: proposed installed capacity in kW
        technology: "solar", "wind", "bess"
        constraints: site constraints dict

    Returns:
        {checklist, summary, total_lead_time_weeks}
    """
    constraints = constraints or {}
    checklist = []
    total_weeks = 0
    categories: dict[str, list] = {}

    for doc in DOCUMENT_REQUIREMENTS:
        try:
            required = doc["required_if"](capacity_kw, technology, constraints)
        except Exception:
            required = False

        item = {
            "id": doc["id"],
            "name": doc["name"],
            "category": doc["category"],
            "required": required,
            "description": doc["description"],
            "lead_time_weeks": doc["typical_lead_time_weeks"],
            "auto_generatable": doc["id"] in {
                "g99_application", "planning_summary", "eia_screening",
                "cdm_f10", "bng_assessment", "licence_memo",
            },
        }
        checklist.append(item)

        if required:
            total_weeks = max(total_weeks, doc["typical_lead_time_weeks"])
            cat = doc["category"]
            categories.setdefault(cat, [])
            categories[cat].append(doc["name"])

    required_count = sum(1 for c in checklist if c["required"])
    auto_count = sum(1 for c in checklist if c["required"] and c["auto_generatable"])

    return {
        "checklist": checklist,
        "summary": {
            "total_documents": len(checklist),
            "required_documents": required_count,
            "auto_generatable": auto_count,
            "manual_required": required_count - auto_count,
            "critical_path_weeks": total_weeks,
            "capacity_kw": capacity_kw,
            "capacity_mw": round(capacity_kw / 1000, 2),
            "technology": technology,
        },
        "by_category": categories,
    }


# ===========================================================================
# Dispatch — unified entry point
# ===========================================================================

GENERATORS = {
    "g99_application": generate_g99_application,
    "planning_summary": generate_planning_summary,
    "eia_screening": generate_eia_screening,
    "cdm_f10": generate_f10_notification,
    "bng_baseline": generate_bng_baseline,
    "licence_memo": generate_licence_memo,
}


def generate_document(document_type: str, data: dict) -> dict:
    """Dispatch to the appropriate document generator.

    Args:
        document_type: one of g99_application, planning_summary, eia_screening,
                       cdm_f10, bng_baseline, licence_memo
        data: document-specific payload (varies by type)

    Returns:
        {form_data, html, document_type, auto_fill_pct}

    Raises:
        ValueError: unknown document_type
    """
    gen = GENERATORS.get(document_type)
    if not gen:
        raise ValueError(
            f"Unknown document_type '{document_type}'. "
            f"Valid types: {', '.join(sorted(GENERATORS.keys()))}"
        )

    # Route arguments based on document type
    if document_type == "g99_application":
        return gen(
            site=data.get("site", {}),
            capacity=data.get("capacity", {}),
            grid=data.get("grid", {}),
            technology=data.get("technology", {}),
        )
    elif document_type == "planning_summary":
        return gen(
            site=data.get("site", {}),
            assessment=data.get("assessment", {}),
            constraints=data.get("constraints", {}),
        )
    elif document_type == "eia_screening":
        return gen(
            site=data.get("site", {}),
            capacity_mw=data.get("capacity_mw", data.get("capacity", {}).get("capacity_mw", 5.0)),
            constraints=data.get("constraints", {}),
        )
    elif document_type == "cdm_f10":
        return gen(
            site=data.get("site", {}),
            capacity_mw=data.get("capacity_mw", data.get("capacity", {}).get("capacity_mw", 5.0)),
            timeline=data.get("timeline", {}),
        )
    elif document_type == "bng_baseline":
        return gen(
            site=data.get("site", {}),
            geeflow_data=data.get("geeflow_data", data.get("geeflow", {})),
        )
    elif document_type == "licence_memo":
        return gen(
            capacity_kw=data.get("capacity_kw", data.get("capacity", {}).get("capacity_kw", 5000)),
        )
    else:
        raise ValueError(f"No dispatch handler for '{document_type}'")
