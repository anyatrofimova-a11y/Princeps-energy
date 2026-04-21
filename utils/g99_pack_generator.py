"""G99 Application Pack Generator — ENA EREC G99 Issue 2 (full Sections A–H).

Produces the full ENA EREC G99 **Issue 2** (June 2024 / 10 March 2025)
application pack as required by a UK DNO assessment engineer (UKPN / SSEN /
NGED / SPEN / NPG / ENWL).

The pack covers:

    Section A — Applicant, Site and Proposed Connection Details
    Section B — Generating Plant / Energy Storage Unit Data
                (incl. fault contribution, LVRT / HVRT, ride-through,
                island detection)
    Section C — Interface Protection
                (full G99 §13 schedule — UV, OV, UF, OF, ROCOF, NVD)
    Section D — Control, Monitoring and SCADA
                (ICCP / DNP3 signal list, ANM, restoration)
    Section E — Single Line Diagram
                (embedded SVG from utils.sld_generator)
    Section F — Harmonic Emission and Flicker Assessment
                (G5/5 Issue 1 + P28 Issue 2)
    Section G — Commissioning Plan and Witness Points
    Section H — Site-Specific Conditions
                (derogations, reactive scheduling, voltage-rise)
    Annex C  — Storage-Specific Declarations
                (live from 2026-03-01 where BESS is part of the scheme)

Values pulled from Princeps assessment are tagged
``[Princeps v{version}]`` adjacent to the value. Unknown fields become
``[TO BE CONFIRMED — Applicant to complete]`` with yellow highlight (CSS
``.field-missing``).

Rendering stack:
    - Jinja2 templates under ``templates/g99_pack/``
    - HTML → PDF via Playwright Chromium (in ``app.routers.reports``)
    - A4 portrait, 12 mm margins

Public API (unchanged for back-compat):
    - generate_g99_pack(data, brief=None)  -> dict[html, filename, form_data]
    - generate_g99_application_from_project(project, grid, site) -> dict
    - generate_g99_application_from_scalars(lat, lon, mw, tech, kv, ...)
    - G99_VERSION: dict, G99_REFERENCE: str

Consumers:
    POST /api/reports/g99-pack
    POST /api/reports/g99-pdf
"""
from __future__ import annotations

import html
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from utils.g99_protection_schedule import (
    G55_FLICKER_LIMITS,
    G55_THDV_LIMIT_EHV_PCT,
    G55_THDV_LIMIT_LV_PCT,
    G55_THDV_LIMIT_MV_PCT,
    G99_FREQUENCY_RESPONSE,
    RIDE_THROUGH_HVRT,
    RIDE_THROUGH_LVRT,
    g99_type as _resolve_g99_type,
    get_protection_schedule,
    harmonic_limits_with_highorder,
)
from utils.g99_table_101 import get_table_101

# ---------------------------------------------------------------------------
# Optional imports — defensive guards
# ---------------------------------------------------------------------------
try:  # pragma: no cover
    from utils.osgb import to_grid_ref as _osgb_to_grid_ref
    _HAS_OSGB = True
except Exception:
    _osgb_to_grid_ref = None  # type: ignore
    _HAS_OSGB = False

try:  # pragma: no cover
    from app.regulatory import versions as _reg_versions  # type: ignore
    _HAS_REG_VERSIONS = True
except Exception:
    _reg_versions = None  # type: ignore
    _HAS_REG_VERSIONS = False

try:  # pragma: no cover
    from utils import g99_brief as _g99_brief_module  # noqa: F401
    _HAS_G99_BRIEF = True
except Exception:
    _g99_brief_module = None
    _HAS_G99_BRIEF = False

# SLD generator — required for Section E. Deferred imports keep test import
# surface minimal but we need the function itself here.
from utils.sld_generator import generate_sld as _generate_sld  # noqa: E402

log = logging.getLogger("princeps.g99_pack_generator")

_PRINCEPS_VERSION = "1.0"
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_MISSING_MARKER = "[TO BE CONFIRMED — Applicant to complete]"

# ---------------------------------------------------------------------------
# Canonical G99 version block
# ---------------------------------------------------------------------------


def _g99_version() -> dict[str, str]:
    """Return the active G99 version metadata (prefers app.regulatory.versions)."""
    if _HAS_REG_VERSIONS:
        try:
            row = _reg_versions.get("g99")  # type: ignore[union-attr]
            return {
                "name": row.get("name", "Engineering Recommendation G99"),
                "version": row.get("version", "Issue 2"),
                "published": row.get("published", "2025-03-10"),
                "effective": row.get("effective", "2025-03-10"),
                "citation": (
                    _reg_versions.cite("g99")  # type: ignore[union-attr]
                    if hasattr(_reg_versions, "cite")
                    else "ENA EREC G99 Issue 2 (10 March 2025)"
                ),
                "annex_c_effective": "2026-03-01",
                "notes": row.get("notes", ""),
                "url": row.get("url", ""),
            }
        except Exception as exc:  # pragma: no cover
            log.debug("app.regulatory.versions lookup failed: %s", exc)
    return {
        "name": "Engineering Recommendation G99",
        "version": "Issue 2",
        "published": "2025-03-10",
        "effective": "2025-03-10",
        "citation": "ENA EREC G99 Issue 2 (10 March 2025)",
        "annex_c_effective": "2026-03-01",
        "notes": (
            "Issue 2 consolidated February 2024 Amendment 1 and was "
            "published 10 March 2025. Storage-specific Annex C provisions "
            "go live 1 March 2026."
        ),
        "url": "https://www.energynetworks.org/publications/engineering-recommendation-g99-issue-2-amendment-1-february-2024",
    }


G99_VERSION = _g99_version()
G99_REFERENCE = G99_VERSION["citation"]


# ---------------------------------------------------------------------------
# Jinja environment
# ---------------------------------------------------------------------------


def _jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml", "svg", "j2"]),
    )
    env.globals["field"] = _render_field
    env.globals["missing_marker"] = _MISSING_MARKER
    env.filters["log10"] = lambda v: math.log10(max(float(v), 1e-9))
    return env


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_g99_pack(data: dict, *, brief: dict | None = None) -> dict:
    """Generate the ENA G99 Issue 2 application pack.

    Args:
        data: Request payload (see G99PackRequest in the reports router).
            Expected keys (all optional):
              site, capacity, grid, technology, agent_result, brief
        brief: Optional pre-built brief dict from utils.g99_brief.

    Returns:
        {'form_data': dict, 'html': str, 'filename': str,
         'document_type': 'g99_application', 'auto_fill_pct': int,
         'provenance': str}
    """
    data = data or {}
    site = data.get("site", {}) or {}
    capacity = data.get("capacity", {}) or {}
    grid = data.get("grid", {}) or {}
    tech = data.get("technology", {}) or {}
    agent = data.get("agent_result", {}) or {}

    if brief is None:
        brief = data.get("brief") or None
    ctx = (brief or {}).get("form_context") if brief else None

    if ctx:
        provenance = "g99_brief_module"
    elif _HAS_G99_BRIEF:
        provenance = "g99_brief_module_available"
    else:
        provenance = "awaiting_g99_brief_module"

    # -------- Resolve primary inputs --------
    lat, lon = _pick_latlon(site, ctx)
    capacity_kw = _pick_capacity_kw(capacity, ctx)
    capacity_mw = capacity_kw / 1000.0
    technology = _pick_technology(tech, ctx)

    application_type = "G100" if capacity_kw <= 50 else "G99"
    ena_category = _ena_category(capacity_kw)

    poc_voltage_kv, recommended_voltage = _resolve_voltage(grid, ctx, capacity_mw)
    dno = _pick(grid, ctx, "dno", site.get("dno", _MISSING_MARKER),
                brief_path=["poc_substation", "dno"])
    poc_name = _pick(grid, ctx, "nearest_substation", _MISSING_MARKER,
                     brief_path=["poc_substation", "name"])
    distance_km = _pick(grid, ctx, "distance_km", None,
                        brief_path=["poc_substation", "distance_km"])
    fault_level_ka = _pick(grid, ctx, "fault_level_ka", None,
                           brief_path=["poc_substation", "fault_level_ka"])

    is_storage = _is_storage_technology(technology)
    g99_type_str = _resolve_g99_type(capacity_mw, recommended_voltage)

    # -------- Protection schedule (G99 Issue 2 §13) --------
    schedule = get_protection_schedule(
        voltage_kv=recommended_voltage, type_category=g99_type_str,
    )
    table_101 = get_table_101(
        voltage_kv=recommended_voltage,
        anti_islanding_scheme="rocof",
        g99_type=g99_type_str,
    )

    # -------- Build section blocks --------
    form: dict[str, Any] = {}
    form["meta"] = _meta_block(
        application_type, ena_category, provenance, is_storage,
        capacity_mw=capacity_mw, g99_type_str=g99_type_str,
        site_name=site.get("name", "site"), agent=agent,
    )
    form["section_a_applicant"] = _section_a(
        site=site, lat=lat, lon=lon, dno=dno, poc_name=poc_name,
        distance_km=distance_km, poc_voltage_kv=poc_voltage_kv,
        recommended_voltage=recommended_voltage, capacity_mw=capacity_mw,
        ena_category=ena_category, g99_type_str=g99_type_str,
    )
    form["section_b_units"] = _section_b_units(
        technology=technology, tech=tech, capacity_mw=capacity_mw,
        poc_voltage_kv=recommended_voltage, is_storage=is_storage,
        g99_type_str=g99_type_str,
    )
    form["section_c_protection"] = _section_c_protection(
        schedule=schedule, table_101=table_101, capacity_mw=capacity_mw,
        recommended_voltage=recommended_voltage,
    )
    form["section_d_scada"] = _section_d_scada(
        capacity_mw=capacity_mw, is_storage=is_storage,
    )
    form["section_e_sld"] = _section_e_sld(
        capacity_kw=capacity_kw, voltage_kv=recommended_voltage,
        technology=technology, is_storage=is_storage,
    )
    form["section_f_harmonics"] = _section_f_harmonics(
        voltage_kv=recommended_voltage,
    )
    form["section_g_commissioning"] = _section_g_commissioning(
        ena_category=ena_category, is_storage=is_storage,
        g99_type_str=g99_type_str,
    )
    form["section_h_site_specific"] = _section_h_site_specific(
        capacity_mw=capacity_mw, recommended_voltage=recommended_voltage,
        is_storage=is_storage,
    )
    form["section_i_signatures"] = _section_i_signatures()
    form["princeps_assessment"] = {
        "verdict": agent.get("verdict", "—"),
        "confidence_pct": round((agent.get("confidence", 0) or 0) * 100),
        "summary": agent.get("summary", ""),
        "risks": agent.get("risks", []),
        "opportunities": agent.get("opportunities", []),
    }

    if is_storage:
        form["annex_c_storage"] = _annex_c_storage(
            capacity_mw=capacity_mw, tech=tech, ena_category=ena_category,
        )

    # -------- Render HTML --------
    html_out = _render_via_jinja(form, capacity_kw=capacity_kw,
                                  voltage_kv=recommended_voltage)

    filename = f"princeps-g99-{_slug(site.get('name', 'site'))}.pdf"
    filled, total = _count_filled(form)
    auto_fill_pct = round(filled / total * 100) if total else 0

    return {
        "form_data": form,
        "html": html_out,
        "filename": filename,
        "document_type": "g99_application",
        "auto_fill_pct": auto_fill_pct,
        "provenance": provenance,
    }


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _meta_block(
    application_type: str,
    ena_category: str,
    provenance: str,
    is_storage: bool,
    *,
    capacity_mw: float,
    g99_type_str: str,
    site_name: str,
    agent: dict,
) -> dict[str, Any]:
    ver = G99_VERSION
    verdict = agent.get("verdict", "—")
    verdict_color = {
        "GO": "#228B22",
        "CAUTION": "#D4A017",
        "NO-GO": "#C0392B",
    }.get(verdict, "#4a4a4a")
    doc_ref = f"PRX-G99-{_slug(site_name).upper()[:8]}-P01"
    return {
        "application_type": application_type,
        "ena_category": ena_category,
        "ena_reference": ver["citation"],
        "g99_version": ver["version"],
        "g99_published": ver["published"],
        "annex_c_effective": ver["annex_c_effective"],
        "annex_c_applies": is_storage,
        "g99_type": g99_type_str,
        "url": ver.get("url", ""),
        "provenance": provenance,
        "princeps_version": _PRINCEPS_VERSION,
        "generated_by": "Princeps",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "doc_ref": doc_ref,
        "verdict_color": verdict_color,
        "disclaimer": (
            "Pre-filled from Princeps assessment. Every field must be verified "
            "by a qualified electrical engineer before submission to the DNO. "
            "Princeps does not constitute engineering advice."
        ),
        "attestation_lines": [
            f"Prepared against ENA {ver['citation']}.",
            f"Generating unit category: {g99_type_str}, ENA category {ena_category}.",
            (
                "Annex C (storage) provisions apply — live 1 March 2026."
                if is_storage
                else "Annex C (storage) not applicable to this scheme."
            ),
            (
                "SCADA availability target ≥99% per Clause 7.5 applies (scheme > 10 MW)."
                if capacity_mw > 10
                else "SCADA availability mandatory target does not bind (scheme ≤ 10 MW)."
            ),
        ],
    }


def _section_a(
    *,
    site: dict,
    lat: float,
    lon: float,
    dno: str,
    poc_name: str,
    distance_km: float | None,
    poc_voltage_kv: float,
    recommended_voltage: float,
    capacity_mw: float,
    ena_category: str,
    g99_type_str: str,
) -> dict[str, Any]:
    ngr = _latlon_to_osgb(lat, lon)
    return {
        "applicant": {
            "company": site.get("applicant_company") or _MISSING_MARKER,
            "address": site.get("applicant_address") or _MISSING_MARKER,
            "company_number": site.get("applicant_company_number") or _MISSING_MARKER,
            "primary_contact": site.get("primary_contact") or _MISSING_MARKER,
            "telephone": site.get("applicant_telephone") or _MISSING_MARKER,
            "email": site.get("applicant_email") or _MISSING_MARKER,
            "signatory": site.get("signatory") or _MISSING_MARKER,
            "signature_date": site.get("signature_date") or _MISSING_MARKER,
        },
        "installer": {
            "company": site.get("installer_company") or _MISSING_MARKER,
            "accreditation_scheme": site.get("installer_scheme") or _MISSING_MARKER,
            "accreditation_number": site.get("installer_number") or _MISSING_MARKER,
            "contact_email": site.get("installer_email") or _MISSING_MARKER,
            "contact_phone": site.get("installer_phone") or _MISSING_MARKER,
        },
        "site": {
            "name": site.get("name", _MISSING_MARKER),
            "address": site.get("address", _MISSING_MARKER),
            "postcode": site.get("postcode", _MISSING_MARKER),
            "lpa": site.get("lpa", _MISSING_MARKER),
            "ward": site.get("ward", _MISSING_MARKER),
            "mpan": site.get("mpan", _MISSING_MARKER),
            "ngr": ngr,
            "wgs84": (
                f"{lat:.6f}, {lon:.6f}" if lat and lon else _MISSING_MARKER
            ),
            "land_area_ha": site.get("area_ha") or _MISSING_MARKER,
        },
        "connection": {
            "dno_licence_area": dno,
            "substation_id": poc_name,
            "proposed_voltage_kv": recommended_voltage,
            "existing_voltage_kv": poc_voltage_kv,
            "type": (
                "New dedicated connection" if capacity_mw > 5
                else "Modification to existing supply"
            ),
            "distance_km": distance_km if distance_km is not None else _MISSING_MARKER,
            "metering_arrangement": (
                "Half-hourly export + import metering (Elexon CT class 0.5S "
                "on revenue, class 5P10 on protection)"
            ),
            "g99_type": g99_type_str,
            "ena_category": ena_category,
        },
    }


def _section_b_units(
    *,
    technology: str,
    tech: dict,
    capacity_mw: float,
    poc_voltage_kv: float,
    is_storage: bool,
    g99_type_str: str,
) -> dict[str, Any]:
    # Unit schedule — aggregate into at most 8 representative unit blocks so
    # the table stays readable; the applicant may split further at
    # commissioning. For BESS use ~1 block per 25 MW container; for solar
    # group by inverter family; for wind each turbine may want its own row
    # (cap at 12).
    if tech.get("num_units"):
        num_units = max(1, int(tech["num_units"]))
    elif is_storage:
        num_units = max(1, min(8, math.ceil(capacity_mw / 12.5)))
    elif technology == "wind":
        num_units = max(1, min(12, math.ceil(capacity_mw / 4.0)))
    else:  # solar / default
        num_units = max(1, min(8, math.ceil(capacity_mw / 10.0)))
    unit_mw = capacity_mw / num_units
    unit_mva = unit_mw / 0.95  # ±0.95 pf, sized to MVA

    interface_type = (
        "Inverter (grid-forming)" if tech.get("grid_forming") else
        "Inverter (grid-following)" if technology in {"solar", "bess", "battery", "storage", "hybrid"} else
        "Full-converter" if technology == "wind" else
        "Synchronous"
    )

    # Sub-transient / fault-level figures (per G99 Issue 2 §12 defaults)
    # Inverter-interfaced units: typical Isc/Irated = 1.1–1.3, X/R low (<2)
    # Synchronous machines: Isc/Irated ≈ 5–8, X/R ≈ 5–10
    if "inverter" in interface_type.lower():
        isc_over_irated = 1.2
        xr_ratio = 1.2
        basis = "Inverter sub-cycle contribution, G99 Issue 2 §12.4."
    elif technology == "wind":
        isc_over_irated = 1.3
        xr_ratio = 1.5
        basis = "Full-converter wind (Type 4) per G99 Issue 2 §12.4."
    else:
        isc_over_irated = 5.5
        xr_ratio = 6.0
        basis = "Synchronous machine, G99 Issue 2 §12.3 defaults; to be replaced with manufacturer data."

    irated_a = (unit_mw * 1e6) / (poc_voltage_kv * 1000.0 * math.sqrt(3)) if poc_voltage_kv else 0
    isc_a = irated_a * isc_over_irated
    fault_mva_poc = unit_mva * isc_over_irated

    units = []
    for i in range(num_units):
        units.append({
            "unit_id": f"U{i + 1:02d}",
            "unit_type": _tech_label(technology, is_storage),
            "make_model": tech.get("manufacturer", _MISSING_MARKER) + " / " + tech.get("model", _MISSING_MARKER),
            "rated_mw_export": round(unit_mw, 3),
            "rated_mw_import": round(unit_mw, 3) if is_storage else "—",
            "mva": round(unit_mva, 3),
            "pf_range": "+0.95 lead to -0.95 lag",
            "type_test_certificate": tech.get("annex_b_cert", _MISSING_MARKER),
            "interface_type": interface_type,
            "isc_sub_transient_a": round(isc_a, 1),
            "isc_over_irated": f"{isc_over_irated:.1f}",
            "xr_ratio": f"{xr_ratio:.1f}",
            "fault_contribution_mva": round(fault_mva_poc, 3),
            "fault_basis": basis,
        })

    # Ride-through envelopes (G99 Issue 2 Annex A)
    freq_modes = G99_FREQUENCY_RESPONSE
    ride_through = {
        "type_category": g99_type_str,
        "freq_continuous": "49.0 Hz — 51.0 Hz (G99 Issue 2 Annex A.4, Table A.1)",
        "freq_extended": (
            "47.0 Hz — 52.0 Hz (limited time per Grid Code operational "
            "notice 1 — 20 s below 47.5 Hz, 90 s above 51.5 Hz)"
        ),
        "lfsm_o": (
            f"Activation {freq_modes['LFSM-O']['threshold_hz']} Hz, "
            f"droop {freq_modes['LFSM-O']['droop_pct']}%"
        ),
        "lfsm_u": (
            f"Activation {freq_modes['LFSM-U']['threshold_hz']} Hz, "
            f"droop {freq_modes['LFSM-U']['droop_pct']}%"
            + ("" if capacity_mw >= 50 else " (not mandatory below 50 MW)")
        ),
        "fsm": (
            f"Deadband ±{freq_modes['FSM']['deadband_hz']} Hz, "
            f"droop {freq_modes['FSM']['droop_pct_range']}"
            + ("" if capacity_mw >= 50 else " (not mandatory below 50 MW)")
        ),
        "rocof_withstand": "≥1 Hz/s sustained for 500 ms (G99 Issue 2 Clause 10.6)",
    }

    anti_islanding = {
        "primary_scheme": "Rate of Change of Frequency (ROCOF)",
        "rocof_hz_per_s": 1.0,
        "rocof_window_ms": 500,
        "rocof_time_delay_s": 0.5,
        "vector_shift": "Disabled per G99 Issue 2 §13.6 (enable only if DNO requires legacy backup)",
        "intentional_islanding": "Not permitted unless formal island agreement with DNO",
    }

    return {
        "totals": {
            "export_mw": round(capacity_mw, 3),
            "import_mw": round(capacity_mw, 3) if is_storage else "—",
            "mva": round(capacity_mw / 0.95, 3),
            "power_factor_range": "+0.95 leading to -0.95 lagging (G99 Issue 2 §4.6)",
            "reactive_capability": (
                f"±{capacity_mw * 0.329:.2f} MVAr at Pmax (4-quadrant inverter)"
                if "inverter" in interface_type.lower()
                else f"±{capacity_mw * 0.33:.2f} MVAr at Pmax"
            ),
            "number_of_units": num_units,
            "frequency_hz": 50,
            "phases": "Three-phase",
        },
        "units": units,
        "ride_through": ride_through,
        "anti_islanding": anti_islanding,
    }


def _section_c_protection(
    *,
    schedule: list[dict[str, Any]],
    table_101: dict,
    capacity_mw: float,
    recommended_voltage: float,
) -> dict[str, Any]:
    # Pick sensible CT / VT ratios for the voltage level
    if recommended_voltage >= 110:
        ct_main = "400/1 A"
        ct_metering = "400/1 A"
        vt_ratio = f"{int(recommended_voltage * 1000 / math.sqrt(3))}:√3 / 110/√3 V"
    elif recommended_voltage >= 33:
        ct_main = "200/1 A"
        ct_metering = "200/1 A"
        vt_ratio = "33kV/√3 : 110/√3 V"
    elif recommended_voltage >= 11:
        ct_main = "100/1 A"
        ct_metering = "100/1 A"
        vt_ratio = "11kV/√3 : 110/√3 V"
    else:
        ct_main = "200/5 A"
        ct_metering = "200/5 A"
        vt_ratio = "— (LV, no VT)"

    return {
        "relay": {
            "manufacturer": _MISSING_MARKER,
            "model": _MISSING_MARKER,
            "firmware_version": _MISSING_MARKER,
            "annex_b_certificate": _MISSING_MARKER,
            "sealed_after_commissioning": True,
        },
        "schedule": schedule,
        "ct_vt": {
            "ct_ratio_main": ct_main,
            "ct_class_protection": "5P20 (IEC 61869-2)",
            "ct_ratio_metering": ct_metering,
            "ct_class_metering": "0.5S (Elexon-approved, IEC 61869-2)",
            "vt_ratio": vt_ratio,
            "vt_class": "3P (protection) / 0.5 (metering)",
        },
        "intertrip": {
            "required": capacity_mw > 5.0,
            "signalling_medium": (
                "Dual-path fibre (primary) + PSTN (backup)"
                if capacity_mw > 5 else _MISSING_MARKER
            ),
            "dependability": "≥99.95% availability, ≤100 ms operate time",
            "security": (
                "Single-point-of-failure immune (two independent paths)"
                if capacity_mw > 5 else _MISSING_MARKER
            ),
            "signals": (
                "Transfer-trip from DNO → generator CB open; Permissive "
                "from generator synchronisation release."
                if capacity_mw > 5
                else "Not applicable (≤ 5 MW scheme)"
            ),
        },
        "table_101_meta": table_101.get("meta", {}),
        "voltage_step_notes": table_101.get("voltage_step_notes", []),
    }


def _section_d_scada(
    *,
    capacity_mw: float,
    is_storage: bool,
) -> dict[str, Any]:
    mandatory = capacity_mw > 10
    signals: list[dict[str, str]] = [
        {"group": "Status", "point": "CB52 open/closed",
         "type": "Binary", "direction": "Site → DNO",
         "note": "Main incomer breaker position."},
        {"group": "Status", "point": "Ground switch position",
         "type": "Binary", "direction": "Site → DNO", "note": ""},
        {"group": "Status", "point": "Interface protection trip",
         "type": "Binary", "direction": "Site → DNO",
         "note": "Composite trip summary for all 27/59/81/81R stages."},
        {"group": "Analog", "point": "Active power (MW)",
         "type": "Float32", "direction": "Site → DNO", "note": "1-s refresh."},
        {"group": "Analog", "point": "Reactive power (MVAr)",
         "type": "Float32", "direction": "Site → DNO", "note": ""},
        {"group": "Analog", "point": "Frequency (Hz)",
         "type": "Float32", "direction": "Site → DNO", "note": ""},
        {"group": "Analog", "point": "Voltage L1/L2/L3",
         "type": "Float32", "direction": "Site → DNO", "note": ""},
        {"group": "Control", "point": "Active power setpoint",
         "type": "Float32", "direction": "DNO → Site",
         "note": "For ANM curtailment."},
        {"group": "Control", "point": "Reactive power setpoint",
         "type": "Float32", "direction": "DNO → Site",
         "note": "For reactive dispatch."},
        {"group": "Control", "point": "Trip command (hardwired)",
         "type": "Binary", "direction": "DNO → Site",
         "note": "Independent of SCADA path."},
    ]
    if is_storage:
        signals.extend([
            {"group": "Analog", "point": "State of charge (%)",
             "type": "Float32", "direction": "Site → DNO",
             "note": "BESS — for Annex C."},
            {"group": "Analog", "point": "Available headroom (MW charge/discharge)",
             "type": "Float32", "direction": "Site → DNO", "note": ""},
        ])

    return {
        "scada": {
            "platform": _MISSING_MARKER,
            "availability_target": "≥99%" if mandatory else "≥97% recommended",
            "availability_mandatory": mandatory,
            "protocol": (
                "IEC 61850-8-1 (GOOSE + MMS) for Type C/D; "
                "DNP3 over TCP/IP for Type B; hardwired for Type A."
            ),
            "transport": (
                "Dual-path fibre + 4G cellular backup"
                if mandatory else _MISSING_MARKER
            ),
            "cyber_standard": "IEC 62443-3-3 SL-2 (minimum) / NCSC CAF",
            "redundancy": (
                "Dual NCC endpoints (primary + DR site)"
                if mandatory else _MISSING_MARKER
            ),
        },
        "iccp_dnp3": signals,
        "anm": {
            "in_anm_zone": _MISSING_MARKER,
            "platform": _MISSING_MARKER,
            "curtailment_path": (
                "ANM master → local ANM cubicle → inverter active-power limit"
                if capacity_mw > 10 else _MISSING_MARKER
            ),
            "response_time_s": 30 if capacity_mw > 10 else _MISSING_MARKER,
            "expected_curtailment_pct": (
                "2–8% (site-dependent)" if capacity_mw > 10 else "<1%"
            ),
        },
        "black_start": {
            "capable": _MISSING_MARKER,
            "restoration_time_minutes": _MISSING_MARKER,
            "grid_forming": _MISSING_MARKER,
            "virtual_inertia": _MISSING_MARKER,
        },
    }


def _section_e_sld(
    *,
    capacity_kw: float,
    voltage_kv: float,
    technology: str,
    is_storage: bool,
) -> dict[str, Any]:
    # Build an assets list suitable for utils.sld_generator.generate_sld
    assets: list[dict[str, Any]] = []
    if is_storage or technology in {"bess", "battery", "storage"}:
        assets.append({
            "type": "bess",
            "name": "BESS",
            "capacity_kw": capacity_kw,
            "capacity_kwh": capacity_kw * 2,
        })
    elif technology == "solar" or technology == "hybrid":
        # Split into 4 arrays for readability
        for i in range(4):
            assets.append({
                "type": "solar",
                "name": f"PV {i + 1}",
                "capacity_kw": capacity_kw / 4,
            })

    sld = _generate_sld(assets, capacity_kw=capacity_kw, voltage_kv=voltage_kv)

    return {
        "svg": sld["svg"],
        "components": sld["components"],
        "cable_schedule": sld["cable_schedule"],
        "incomer_switchgear": f"{voltage_kv} kV SF6 gas-insulated switchgear, "
                              f"630 A continuous, 25 kA/3 s short-time",
        "ct_vt_location": "At PoC incomer, on generator side of isolator",
        "isolator_earth_switch": "Manually-operated, interlocked with CB52",
        "aux_transformer": f"{round(capacity_kw * 0.02)} kVA, {voltage_kv} kV / 400 V",
        "ups": "10 kVA, 30-min autonomy, feeding protection + SCADA + telecoms",
        "metering_ct_class": "Class 0.5S (Elexon-approved)",
    }


def _section_f_harmonics(
    *,
    voltage_kv: float,
) -> dict[str, Any]:
    # Determine voltage band + THDv planning limit
    if voltage_kv <= 1.0:
        band = "LV (≤ 1 kV)"
        thdv_limit = G55_THDV_LIMIT_LV_PCT
        pst_limit = G55_FLICKER_LIMITS["LV"]["Pst"]
        plt_limit = G55_FLICKER_LIMITS["LV"]["Plt"]
    elif voltage_kv <= 35:
        band = "MV (1 kV < Un ≤ 35 kV)"
        thdv_limit = G55_THDV_LIMIT_MV_PCT
        pst_limit = G55_FLICKER_LIMITS["MV"]["Pst"]
        plt_limit = G55_FLICKER_LIMITS["MV"]["Plt"]
    else:
        band = "EHV (35 kV < Un ≤ 230 kV)"
        thdv_limit = G55_THDV_LIMIT_EHV_PCT
        pst_limit = G55_FLICKER_LIMITS["HV"]["Pst"]
        plt_limit = G55_FLICKER_LIMITS["HV"]["Plt"]

    # Build 2–50 harmonic table with missing-marker declared columns
    harmonic_rows = []
    for r in harmonic_limits_with_highorder():
        harmonic_rows.append({
            "h": r["h"],
            "type": r["type"],
            "limit_pct": r["limit_pct"],
            "declared_pct": _MISSING_MARKER,
            "over_limit": False,
        })

    return {
        "basis": {
            "voltage_kv": voltage_kv,
            "voltage_band": band,
            "thdv_limit_pct": thdv_limit,
            "reference": (
                "ENA EREC G5/5 Issue 1 (2020) — Stage 1 limits; "
                "ENA EREC P28 Issue 2 (2019) — flicker."
            ),
        },
        "thdv": {
            "declared_pct": _MISSING_MARKER,
            "headroom_pct": _MISSING_MARKER,
        },
        "harmonics": harmonic_rows,
        "flicker": {
            "pst_limit": pst_limit,
            "plt_limit": plt_limit,
            "pst_worst": _MISSING_MARKER,
            "pst_continuous": _MISSING_MARKER,
            "plt_worst": _MISSING_MARKER,
            "plt_continuous": _MISSING_MARKER,
            "pst_status": "TBD",
            "plt_status": "TBD",
        },
    }


def _section_g_commissioning(
    *,
    ena_category: str,
    is_storage: bool,
    g99_type_str: str,
) -> dict[str, Any]:
    sequence = [
        {"name": "Static tests complete",
         "description": "Insulation resistance, continuity, torque checks signed off.",
         "duration": "1 day", "witness": False},
        {"name": "Energise aux boards",
         "description": "Energise aux transformer + LV aux board; verify UPS autonomy.",
         "duration": "0.5 day", "witness": False},
        {"name": "Dead-bus close test",
         "description": "CB52 operation test, no voltage applied to generator side.",
         "duration": "0.5 day", "witness": True},
        {"name": "Interface protection live test (secondary injection)",
         "description": (
             "Inject secondary currents / voltages to verify UV, OV, UF, OF, "
             "ROCOF trip timings against G99 Issue 2 Table 13.1."
         ),
         "duration": "1 day", "witness": True},
        {"name": "Loss-of-mains verification (ROCOF)",
         "description": (
             "Inject 1 Hz/s ramp over 500 ms window; verify trip within 500 ms. "
             "Then inject 0.95 Hz/s to verify ride-through (no trip)."
         ),
         "duration": "0.5 day", "witness": True},
        {"name": "Vector-shift proving (if enabled)",
         "description": "Inject step phase-jump; verify no spurious trip when disabled.",
         "duration": "0.25 day", "witness": False},
        {"name": "Live synchronisation",
         "description": (
             "First synchronisation across CB52 under DNO witness. Record "
             "voltage step and frequency error within ENA P28 limits."
         ),
         "duration": "0.5 day", "witness": True},
        {"name": "Ramp to rated output + reactive P-Q demo",
         "description": (
             "Ramp to 100% Pmax; demonstrate ±0.95 pf capability across the "
             "P-Q envelope; log inverter setpoint tracking."
         ),
         "duration": "1 day", "witness": True},
        {"name": "SCADA handshake",
         "description": (
             "Verify ICCP / DNP3 point list end-to-end with DNO NCC; confirm "
             "setpoint response time ≤30 s."
         ),
         "duration": "0.5 day", "witness": True},
    ]
    if is_storage:
        sequence.extend([
            {"name": "Annex C — SoC envelope test",
             "description": (
                 "Sustain declared dynamic containment MW at min SoC and max SoC; "
                 "prove no trip on low-cell undervoltage (BMS)."
             ),
             "duration": "0.5 day", "witness": True},
            {"name": "Annex C — BMS trip & reset",
             "description": (
                 "Simulate per-cell overvoltage / overtemperature; verify per-rack "
                 "contactor opening and controlled reset sequence."
             ),
             "duration": "0.5 day", "witness": False},
        ])
    sequence.append({
        "name": "G99 A2 confirmation returned",
        "description": "Completed commissioning statement sent to DNO within 28 days.",
        "duration": "—", "witness": False,
    })

    tests = [
        {"name": "UV1 (U< Stage 1) trip",
         "method": "Secondary injection — step from 100% to 79% Un",
         "pass_criterion": "Trip within 2.5 ± 0.1 s",
         "witness_by_dno": True,
         "clause": "G99 Issue 2 Clause 13.4.2 / Table 13.1"},
        {"name": "UV2 (U< Stage 2) trip",
         "method": "Step from 100% to 49% Un",
         "pass_criterion": "Trip within 0.5 ± 0.05 s",
         "witness_by_dno": True,
         "clause": "G99 Issue 2 Clause 13.4.2 / Table 13.1"},
        {"name": "OV1 (U> Stage 1) trip",
         "method": "Step from 100% to 111% Un",
         "pass_criterion": "Trip within 1.0 ± 0.1 s",
         "witness_by_dno": True,
         "clause": "G99 Issue 2 Clause 13.4.3 / Table 13.1"},
        {"name": "OV3 (U> Stage 3) trip",
         "method": "Step from 100% to 121% Un",
         "pass_criterion": "Trip within 100 ± 20 ms",
         "witness_by_dno": True,
         "clause": "G99 Issue 2 Clause 13.4.3 / Table 13.1"},
        {"name": "UF2 (f<<) trip",
         "method": "Ramp frequency to 46.9 Hz",
         "pass_criterion": "Trip within 0.5 ± 0.05 s",
         "witness_by_dno": True,
         "clause": "G99 Issue 2 Clause 13.5 / Table 13.2"},
        {"name": "OF2 (f>>) trip",
         "method": "Ramp frequency to 52.1 Hz",
         "pass_criterion": "Trip within 0.5 ± 0.05 s",
         "witness_by_dno": True,
         "clause": "G99 Issue 2 Clause 13.5 / Table 13.2"},
        {"name": "ROCOF trip",
         "method": "1.1 Hz/s ramp over 500 ms window",
         "pass_criterion": "Trip within 500 ± 100 ms",
         "witness_by_dno": True,
         "clause": "G99 Issue 2 Clause 13.6"},
        {"name": "ROCOF ride-through (non-trip)",
         "method": "0.95 Hz/s ramp over 500 ms window",
         "pass_criterion": "No trip; continuous operation maintained",
         "witness_by_dno": True,
         "clause": "G99 Issue 2 Clause 10.6"},
        {"name": "LFSM-O response",
         "method": "Step frequency to 50.5 Hz at Pmax",
         "pass_criterion": "Active power reduced per 5% droop within 10 s",
         "witness_by_dno": g99_type_str in {"Type C", "Type D"},
         "clause": "G99 Issue 2 Clause 4.2"},
    ]
    today = datetime.now(timezone.utc).date()
    return {
        "sequence": sequence,
        "tests": tests,
        "schedule": {
            "window": f"{(today + timedelta(days=60)).isoformat()} — "
                       f"{(today + timedelta(days=67)).isoformat()} "
                       f"(7-day commissioning window)",
            "witness_points_count": sum(1 for s in sequence if s.get("witness")),
            "dno_engineer_notified": _MISSING_MARKER,
            "a2_due_date": (today + timedelta(days=90)).isoformat(),
        },
    }


def _section_h_site_specific(
    *,
    capacity_mw: float,
    recommended_voltage: float,
    is_storage: bool,
) -> dict[str, Any]:
    # Voltage rise analysis — rough SCR-based classification
    # (DNO engineer must overwrite with real study)
    return {
        "derogations": [],
        "anti_islanding_special": {
            "additional_passive": _MISSING_MARKER,
            "active_detection": _MISSING_MARKER,
            "island_agreement": "Not requested — default anti-island regime per Clause 13.6",
        },
        "reactive_mode": {
            "selected_mode": "Voltage-control (generator-follows-voltage)"
            if capacity_mw >= 10 else "Power-factor control",
            "voltage_setpoint_pu": 1.00 if capacity_mw >= 10 else _MISSING_MARKER,
            "droop_pct": 4.0 if capacity_mw >= 10 else _MISSING_MARKER,
            "pf_setpoint": _MISSING_MARKER if capacity_mw >= 10 else 1.0,
        },
        "voltage_rise": {
            "scr": _MISSING_MARKER,
            "network_classification": (
                "Weak" if recommended_voltage <= 33 and capacity_mw > 10 else "Moderate"
            ),
            "rise_pct": _MISSING_MARKER,
            "headroom_pct": _MISSING_MARKER,
        },
    }


def _section_i_signatures() -> dict[str, Any]:
    return {
        "applicant": {
            "printed_name": _MISSING_MARKER,
            "signed": False,
            "date": _MISSING_MARKER,
        },
        "installer": {
            "printed_name": _MISSING_MARKER,
            "accreditation_body": _MISSING_MARKER,
            "signed": False,
            "date": _MISSING_MARKER,
        },
        "consulting_engineer": {
            "printed_name": _MISSING_MARKER,
            "institution": _MISSING_MARKER,
            "signed": False,
            "date": _MISSING_MARKER,
        },
        "declaration": (
            "I/We declare that the information provided is, to the best of our "
            "knowledge, accurate and complete, and that the generating plant "
            "will comply with ENA EREC G99 Issue 2. Where Princeps-derived "
            "values have been pre-filled, they have been independently verified "
            "against manufacturer data and site-specific conditions."
        ),
    }


# ---------------------------------------------------------------------------
# Annex C — Storage-specific declarations
# ---------------------------------------------------------------------------


def _annex_c_storage(
    *,
    capacity_mw: float,
    tech: dict,
    ena_category: str,
) -> dict[str, Any]:
    duration_h = float(tech.get("duration_h", 2.0))
    grid_forming = bool(tech.get("grid_forming", False))
    black_start = bool(tech.get("black_start_capable", False))
    return {
        "title": "Annex C — Storage Declarations (G99 Issue 2, effective 1 March 2026)",
        "applicability": (
            "Mandatory for electrical energy storage systems connected under "
            "G99 Issue 2 from 1 March 2026. This project includes BESS and "
            "therefore Annex C applies in full."
        ),
        "nameplate": {
            "rated_charge_mw": tech.get("rated_charge_mw", capacity_mw),
            "rated_discharge_mw": tech.get("rated_discharge_mw", capacity_mw),
            "usable_energy_mwh": tech.get(
                "usable_energy_mwh", round(capacity_mw * duration_h, 2)
            ),
            "duration_h": duration_h,
            "round_trip_efficiency_pct": tech.get("rte_pct", 88),
        },
        "frequency_response_modes": {
            "dynamic_containment": {
                "capability_mw": round(capacity_mw, 2),
                "response_time_ms": 500,
                "declared": False,
            },
            "dynamic_moderation": {
                "capability_mw": round(capacity_mw, 2),
                "response_time_ms": 500,
                "declared": False,
            },
            "dynamic_regulation": {
                "capability_mw": round(capacity_mw * 0.5, 2),
                "response_time_ms": 500,
                "declared": False,
            },
            "firm_frequency_response": {
                "capability_mw": round(capacity_mw * 0.5, 2),
                "response_time_ms": 10000,
                "declared": False,
            },
            "note": (
                "Declare MW capability and sustained duration for each service at "
                "the relevant SoC envelope per NGESO product terms."
            ),
        },
        "state_of_charge_management": {
            "min_soc_pct": 10,
            "max_soc_pct": 90,
            "frequency_service_reserve_pct": 20,
            "auto_recharge_after_event": True,
        },
        "anti_islanding_storage": {
            "primary_scheme": (
                "Grid-forming virtual synchronous machine with ROCOF blocking"
                if grid_forming
                else "Grid-following with ROCOF + passive LoM"
            ),
            "virtual_inertia_mw_s_per_mw": (
                tech.get("virtual_inertia_s", 5.0) if grid_forming else 0.0
            ),
            "black_start_capable": black_start,
        },
        "bess_specific_protection": {
            "dc_side": [
                "DC overcurrent / earth fault",
                "DC arc fault detection",
                "DC insulation monitoring (IMD)",
            ],
            "bms": [
                "Cell overvoltage / undervoltage (BMS)",
                "Cell overtemperature (BMS + external)",
                "String imbalance monitoring",
            ],
            "thermal_runaway": [
                "Per-rack gas detection (H2 + CO)",
                "Per-container deflagration vent",
                "Automatic fire suppression (NFPA 855 compliant)",
            ],
            "ac_side": [
                "Anti-parallel protection matching G99 §13 schedule",
                "Reverse power protection where charging is prohibited",
            ],
        },
        "grid_forming_declaration": {
            "mode": "grid-forming" if grid_forming else "grid-following",
            "synchronous_support": grid_forming,
            "compliance_evidence": _MISSING_MARKER,
        },
        "ena_reference": f"G99 Issue 2 Annex C, effective {G99_VERSION['annex_c_effective']}",
        "category_impact_note": (
            f"Annex C applies to all storage categories. This project is "
            f"Category {ena_category}."
        ),
    }


# ---------------------------------------------------------------------------
# Jinja render
# ---------------------------------------------------------------------------


def _render_via_jinja(form: dict, *, capacity_kw: float, voltage_kv: float) -> str:
    env = _jinja_env()

    # Pre-compute ride-through chart geometry
    lvrt_ctx = _ride_through_chart_context(
        RIDE_THROUGH_LVRT, title="Low Voltage Ride-Through — G99 Issue 2 Annex A",
        prefix="lvrt", upper_bound=True,
    )
    hvrt_ctx = _ride_through_chart_context(
        RIDE_THROUGH_HVRT, title="High Voltage Ride-Through — G99 Issue 2 Annex A",
        prefix="hvrt", upper_bound=False,
    )

    lvrt_svg = env.get_template("g99_pack/_lvrt_curve.svg.j2").render(**lvrt_ctx)
    hvrt_svg = env.get_template("g99_pack/_hvrt_curve.svg.j2").render(**hvrt_ctx)

    sld_svg = form["section_e_sld"]["svg"]

    css = _render_css()

    return env.get_template("g99_pack/main.html.j2").render(
        form=form,
        meta=form["meta"],
        css=css,
        sld_svg=sld_svg,
        lvrt_svg=lvrt_svg,
        hvrt_svg=hvrt_svg,
        section_a=form["section_a_applicant"],
        section_b=form["section_b_units"],
        section_c=form["section_c_protection"],
        section_d=form["section_d_scada"],
        section_f=form["section_f_harmonics"],
        section_g=form["section_g_commissioning"],
    )


def _ride_through_chart_context(
    pts: list[tuple[float, float]],
    *,
    title: str,
    prefix: str,
    upper_bound: bool,
) -> dict[str, Any]:
    """Build SVG-ready chart geometry for the LVRT / HVRT curves."""
    width = 520
    height = 260
    pad_l, pad_r, pad_t, pad_b = 54, 18, 28, 38
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    t_min_log = math.log10(0.1)   # 0.1 ms
    t_max_log = math.log10(12500)  # ~12.5 s

    v_max = 120  # both charts share a 0-120% axis

    def _x(t_ms: float) -> float:
        t = max(t_ms, 0.1)
        logt = math.log10(t)
        return pad_l + ((logt - t_min_log) / (t_max_log - t_min_log)) * plot_w

    def _y(v_pct: float) -> float:
        return (height - pad_b) - (v_pct / v_max) * plot_h

    polyline_pts = []
    for t_ms, v_pu in pts:
        polyline_pts.append(f"{_x(t_ms):.1f},{_y(v_pu * 100):.1f}")
    polyline = " ".join(polyline_pts)

    # Polygon = polyline + closure to fill "safe" region.
    # For LVRT, fill region is ABOVE the line (right-edge-top then left-edge-top).
    # For HVRT, fill region is BELOW the line (right-edge-bottom then left-edge-bottom).
    if upper_bound:
        polygon = f"{polyline} {_x(10000)},{pad_t} {_x(0.1)},{pad_t}"
    else:
        polygon = f"{polyline} {_x(60000)},{height - pad_b} {_x(0.1)},{height - pad_b}"

    y_ticks = [(f"{v}%", _y(v)) for v in (0, 25, 50, 75, 100, 120)]
    x_ticks = []
    for label, t in [("1 ms", 1), ("10 ms", 10), ("100 ms", 100),
                     ("1 s", 1000), ("10 s", 10000)]:
        x_ticks.append((label, _x(t)))

    return {
        f"{prefix}_title": title,
        f"{prefix}_svg_polyline": polyline,
        f"{prefix}_svg_polygon": polygon,
        f"{prefix}_x_ticks": x_ticks,
        f"{prefix}_y_ticks": y_ticks,
        "width": width,
        "height": height,
        "pad_l": pad_l,
        "pad_r": pad_r,
        "pad_t": pad_t,
        "pad_b": pad_b,
    }


def _render_field(v: Any) -> str:
    """Render a form field value.

    - ``[TO BE CONFIRMED — Applicant to complete]`` → yellow-highlighted span.
    - ``None`` / ``''`` → missing marker.
    - Other string "[…]" placeholder → yellow highlight.
    - Everything else → HTML-escaped string.
    """
    if v is None or v == "":
        v = _MISSING_MARKER
    s = str(v)
    if s == _MISSING_MARKER:
        from markupsafe import Markup
        return Markup(
            f'<span class="field-missing">{html.escape(_MISSING_MARKER)}</span>'
        )
    if s.startswith("[") and s.endswith("]"):
        from markupsafe import Markup
        return Markup(f'<span class="field-missing">{html.escape(s)}</span>')
    return html.escape(s)


def _render_css() -> str:
    return """
      :root {
        --gold:#C9A64B; --gold-dark:#A88732; --gold-light:#F5E9C8;
        --ink:#1a1a1a; --ink-muted:#4a4a4a; --rule:#E6D9B8;
        --paper:#ffffff; --soft:#FAF7EE;
      }
      html,body { margin:0; padding:0; background:var(--paper); color:var(--ink); }
      body { font-family:'Inter','Segoe UI',system-ui,sans-serif;
             font-size:10.5px; line-height:1.5; padding:14px 20px; }
      h1 { font-size:24px; letter-spacing:1px; margin:0 0 4px; }
      h1::before { content:"\\25C6"; color:var(--gold); margin-right:10px; }
      h2 { font-size:14px; margin:18px 0 8px; padding:6px 10px;
           background:var(--gold-light); border-left:4px solid var(--gold);
           letter-spacing:.5px; font-weight:700; }
      h3 { font-size:11.5px; margin:12px 0 4px;
           border-bottom:1px dotted var(--rule); padding-bottom:2px;
           font-weight:600; }
      p.section-lead, p.note { color:var(--ink-muted); font-size:9.5px; }
      .note { color:var(--ink-muted); font-size:9px; }
      .prov { color:var(--gold-dark); font-family:'JetBrains Mono',
              'Consolas',monospace; font-size:8.5px; margin-left:4px; }
      .field-missing { background:#FFF5AA; border:1px dashed #C9A64B;
                       padding:1px 5px; border-radius:2px; color:#7a5c00;
                       font-family:'JetBrains Mono','Consolas',monospace;
                       font-size:8.8px; font-weight:600; }
      table.form { width:100%; border-collapse:collapse; margin:4px 0 10px; }
      table.form td { padding:4px 8px; border-bottom:1px solid var(--rule);
                      vertical-align:top; }
      table.form td.lbl { font-weight:600; width:42%; color:var(--ink-muted); }
      table.set { width:100%; border-collapse:collapse; margin:6px 0 10px;
                  font-size:9.2px; }
      table.set th { background:var(--gold); color:#fff; padding:5px 8px;
                     text-align:left; text-transform:uppercase;
                     letter-spacing:.3px; font-size:9px; }
      table.set td { padding:4px 7px; border-bottom:1px solid var(--rule);
                      vertical-align:top; }
      table.set tr:nth-child(even) td { background:var(--soft); }
      table.set tr.over-limit td { background:#FFE6E6; }
      table.protection-schedule td.stage { font-weight:700; color:var(--ink); }
      table.protection-schedule td.clause { font-size:8.5px; color:var(--ink-muted); }
      table.protection-schedule tr.note-row td { background:#FFFBEF;
                     font-size:9px; color:var(--ink-muted);
                     border-bottom:1px solid var(--rule); }
      ol.sequence li { margin:3px 0; }
      .witness-tag { display:inline-block; background:var(--gold);
                     color:#fff; padding:1px 6px; border-radius:3px;
                     font-size:8.5px; margin-left:6px; font-weight:600; }
      .ride-through { display:flex; gap:10px; margin:8px 0; }
      .rt-card { flex:1; border:1px solid var(--rule); border-radius:4px;
                 padding:6px; background:#fff; }
      .rt-card svg { width:100%; height:auto; }
      .sld-frame { border:1px solid var(--rule); border-radius:4px;
                   padding:8px; margin:8px 0; background:#fff; overflow:hidden; }
      .sld-frame svg { width:100%; height:auto; max-height:340px; }
      .cover { padding:20px 0 10px; border-bottom:3px solid var(--gold); }
      .cover-strip { height:4px; background:var(--gold); margin-bottom:14px; }
      .cover-sub { color:var(--ink-muted); font-size:11px; margin:4px 0 12px; }
      table.cover-meta { width:100%; margin:6px 0 10px; border-collapse:collapse; }
      table.cover-meta td { padding:3px 8px; border-bottom:1px solid var(--rule); }
      table.cover-meta td.lbl { font-weight:700; color:var(--ink-muted);
                                width:32%; }
      .attestation { background:#FFF8E1; border-left:3px solid var(--gold);
                     padding:8px 12px; font-size:9.5px; margin:10px 0; }
      .disclaimer { background:var(--gold-light); border-left:3px solid
                    var(--gold-dark); padding:7px 10px; border-radius:3px;
                    font-size:9px; color:var(--gold-dark); margin:6px 0; }
      .verdict { display:inline-block; padding:3px 14px; border-radius:4px;
                 font-weight:800; font-size:14px; color:white; }
      .sig-row { display:flex; gap:10px; margin-top:10px; }
      .sig-cell { flex:1; border:1px dashed var(--rule); border-radius:4px;
                  padding:10px; min-height:88px; background:#fff; }
      .sig-cell .role { font-weight:700; margin-bottom:6px; font-size:10px; }
      .sig-line { border-bottom:1px solid var(--gold); margin:30px 0 6px; }
      .declaration { font-size:9.5px; color:var(--ink-muted);
                     padding:6px 0; border-bottom:1px dotted var(--rule); }
      .doc-footer { margin-top:22px; padding-top:10px;
                    border-top:2px solid var(--gold); font-size:8.5px;
                    color:var(--ink-muted); text-align:center; }
      .page-break { page-break-after:always; break-after:page;
                    height:1px; display:block; }
      section.g99-section { page-break-inside:auto; break-inside:auto; }
      section.g99-section h2 { page-break-after:avoid; break-after:avoid; }
      section.g99-section h3 { page-break-after:avoid; break-after:avoid; }
      table { page-break-inside:auto; }
      table tr { page-break-inside:avoid; break-inside:avoid; }
      .annex-c { background:#FFFBEF; border:1px solid var(--gold);
                 padding:8px 12px; border-radius:4px; }
      @media print { body { padding:6mm 8mm; } h2 { break-before:avoid; }
                     .page-break { page-break-after:always; } }
    """


# ---------------------------------------------------------------------------
# Resolvers / helpers
# ---------------------------------------------------------------------------


def _pick(
    raw: dict, ctx: dict | None, key: str, default: Any,
    *, brief_path: list[str] | None = None,
) -> Any:
    if ctx:
        if brief_path:
            cur: Any = ctx
            for p in brief_path:
                if isinstance(cur, dict) and p in cur and cur[p] is not None:
                    cur = cur[p]
                else:
                    cur = None
                    break
            if cur is not None:
                return cur
        if key in ctx and ctx[key] is not None:
            return ctx[key]
    if key in raw and raw[key] is not None:
        return raw[key]
    return default


def _pick_latlon(site: dict, ctx: dict | None) -> tuple[float, float]:
    if ctx and ctx.get("project"):
        p = ctx["project"]
        lat, lon = p.get("lat"), p.get("lon")
        if lat is not None and lon is not None:
            return float(lat), float(lon)
    return float(site.get("lat") or 0.0), float(site.get("lon") or 0.0)


def _pick_capacity_kw(capacity: dict, ctx: dict | None) -> float:
    if ctx and ctx.get("project"):
        mw = ctx["project"].get("capacity_mw")
        if mw is not None:
            return float(mw) * 1000.0
    kw = capacity.get("capacity_kw")
    if kw is not None:
        return float(kw)
    mw = capacity.get("capacity_mw")
    if mw is not None:
        return float(mw) * 1000.0
    return 5000.0


def _pick_technology(tech: dict, ctx: dict | None) -> str:
    if ctx and ctx.get("project"):
        return (ctx["project"].get("technology") or "solar").lower()
    return (tech.get("type") or "solar").lower()


def _is_storage_technology(technology: str) -> bool:
    t = (technology or "").lower()
    return any(k in t for k in (
        "bess", "battery", "storage", "hybrid", "bss", "pumped_storage",
    ))


def _tech_label(technology: str, is_storage: bool) -> str:
    t = (technology or "").lower()
    if is_storage or t in {"bess", "battery", "storage"}:
        return "Li-ion BESS (inverter-interfaced)"
    if t == "solar":
        return "PV inverter"
    if t == "wind":
        return "Full-converter wind turbine"
    if "synchronous" in t:
        return "Synchronous machine"
    return "Inverter-interfaced"


def _resolve_voltage(
    grid: dict, ctx: dict | None, capacity_mw: float,
) -> tuple[float, float]:
    existing: Any = None
    if ctx and ctx.get("poc_substation"):
        existing = ctx["poc_substation"].get("voltage_kv")
    if existing is None:
        existing = grid.get("voltage_kv")
    if existing is None:
        existing = 33.0
    existing = float(existing)

    if capacity_mw > 50:
        recommended = 132.0
    elif capacity_mw > 5:
        recommended = 33.0
    else:
        recommended = 11.0
    return existing, recommended


def _ena_category(capacity_kw: float) -> str:
    if capacity_kw <= 16:
        return "A1"
    if capacity_kw <= 50:
        return "A2"
    if capacity_kw <= 1000:
        return "B"
    if capacity_kw <= 50_000:
        return "C"
    return "D (NSIP)"


def _latlon_to_osgb(lat: float, lon: float, precision: int = 8) -> str:
    if not lat or not lon:
        return _MISSING_MARKER
    if _HAS_OSGB and _osgb_to_grid_ref is not None:
        try:
            return _osgb_to_grid_ref(lat, lon, precision=precision)
        except Exception as exc:  # pragma: no cover
            log.debug("osgb conversion failed: %s", exc)
    try:
        from pyproj import Transformer  # type: ignore

        tr = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
        easting, northing = tr.transform(lon, lat)
        return f"OSGB36 E {int(easting)}, N {int(northing)} (pyproj fallback)"
    except Exception:
        return _MISSING_MARKER


def _slug(s: str | None) -> str:
    return re.sub(r"[^\w-]", "-", s or "site").strip("-")[:40].lower()


def _count_filled(d: dict) -> tuple[int, int]:
    filled = 0
    total = 0
    placeholders = {"[", "to be confirmed", "to be", "tbd", "tbc", "n/a", "—"}
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


# ---------------------------------------------------------------------------
# Back-compat adapters
# ---------------------------------------------------------------------------


def generate_g99_application_from_project(
    project: dict, grid_context: dict, site_context: dict
) -> dict:
    site = {
        "name": project.get("name") or site_context.get("site_name") or "",
        "address": site_context.get("address", ""),
        "postcode": site_context.get("postcode", ""),
        "lat": project.get("lat"),
        "lon": project.get("lon"),
        "area_ha": site_context.get("land_area_ha") or project.get("land_area_ha"),
        "dno": grid_context.get("dno", ""),
    }
    capacity = {
        "capacity_mw": project.get("capacity_mw"),
        "capacity_kw": (project.get("capacity_mw") or 0) * 1000.0,
    }
    grid = {
        "voltage_kv": grid_context.get("voltage_kv"),
        "nearest_substation": grid_context.get("nearest_substation", ""),
        "distance_km": grid_context.get("nearest_substation_distance_km"),
        "headroom_mw": grid_context.get("headroom_mw"),
        "dno": grid_context.get("dno", ""),
    }
    technology = {"type": (project.get("technology") or "solar").lower()}
    return generate_g99_pack({
        "site": site, "capacity": capacity,
        "grid": grid, "technology": technology,
    })


def generate_g99_application_from_scalars(
    lat: float, lon: float, capacity_mw: float, technology: str,
    voltage_kv: float, dno: str | None = None, phase: str = "three_phase",
    applicant: dict[str, str] | None = None,
) -> dict:
    site = {
        "name": (applicant or {}).get("site_name") or "[Site name]",
        "lat": lat, "lon": lon, "dno": dno or "",
    }
    capacity = {
        "capacity_mw": capacity_mw,
        "capacity_kw": capacity_mw * 1000.0,
    }
    grid = {"voltage_kv": voltage_kv, "dno": dno or ""}
    tech = {"type": (technology or "solar").lower()}
    pack = generate_g99_pack({
        "site": site, "capacity": capacity, "grid": grid, "technology": tech,
    })
    if applicant and isinstance(pack.get("form_data"), dict):
        sec_a = pack["form_data"].get("section_a_applicant", {})
        sec_a.setdefault("applicant", {}).update(applicant)
    return pack


__all__ = [
    "generate_g99_pack",
    "generate_g99_application_from_project",
    "generate_g99_application_from_scalars",
    "G99_VERSION",
    "G99_REFERENCE",
]


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    out = generate_g99_pack({
        "site": {"name": "Uttoxeter BESS", "lat": 52.9, "lon": -1.86,
                 "postcode": "ST14 8BH"},
        "capacity": {"capacity_mw": 100},
        "grid": {"voltage_kv": 33, "nearest_substation": "NGED Uttoxeter",
                 "distance_km": 1.2, "dno": "NGED"},
        "technology": {"type": "bess", "duration_h": 2, "grid_forming": True},
        "agent_result": {"verdict": "GO", "confidence": 0.82,
                          "summary": "Viable 100 MW BESS site."},
    })
    print("filename:", out["filename"])
    print("provenance:", out["provenance"])
    print("auto_fill_pct:", out.get("auto_fill_pct"))
    print("annex_c_present:", "annex_c_storage" in out["form_data"])
    print("html length:", len(out["html"]))
