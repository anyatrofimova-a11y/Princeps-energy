"""G99 Application Pack Generator — canonical Princeps entry point.

Produces a pre-filled ENA Engineering Recommendation G99 **Issue 2** (published
10 March 2025) application pack. Storage-inclusive requirements (Annex C) are
mandatory from 1 March 2026; this module populates Annex C whenever a BESS or
hybrid project is detected, flagging fields the developer must confirm before
submission.

Sections follow the ENA form order:

    (A) Applicant / installer details
    (B) Installation site
    (C) Connection arrangement and Point of Connection
    (D) Generator / storage specifications and anti-islanding
    (E) Export limits and DNO interface settings
    (F) Protection settings (cross-ref G99 Issue 2 Table 10.1)
    (G) Fault-level contribution
    (H) Commissioning checklist
    (I) Signatures
    (Annex C) Storage-specific declarations — go-live 1 March 2026

This is the single canonical generator. The two previous duplicates
(``utils.market_intelligence.generate_g99_application`` and
``utils.g99_compliance.generate_g99_application``) now delegate here via thin
passthroughs that adapt their legacy input shapes; callers in
``app/routers/planning_ml.py`` and ``app/routers/grid.py`` continue to work
without change.

Inputs come from ``utils.g99_brief.build_g99_brief`` where available (the
``brief`` kwarg or ``data["brief"]``) and fall back to the raw request payload.
Protection settings are pulled from ``utils.g99_table_101`` (BOT-N). The OSGB
grid reference is produced by ``utils.osgb.to_grid_ref`` (BOT-R2) — no more
linear approximations.

Consumers:
  - POST /api/reports/g99-pack (JSON)
  - POST /api/reports/g99-pdf  (Playwright-rendered PDF)
"""
from __future__ import annotations

import html
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any

from utils.g99_table_101 import get_table_101

# ---------------------------------------------------------------------------
# OSGB conversion — BOT-R2's canonical helper. We keep a defensive fallback
# so the pack still renders (with a visible TODO) if the module is missing.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - import guard
    from utils.osgb import to_grid_ref as _osgb_to_grid_ref

    _HAS_OSGB = True
except Exception:  # pragma: no cover - defensive
    _osgb_to_grid_ref = None  # type: ignore[assignment]
    _HAS_OSGB = False

# ---------------------------------------------------------------------------
# Regulatory version strings — prefer BOT-R2's app.regulatory.versions if
# present (single source of truth), otherwise fall back to the G99 Issue 2
# strings attested in the COUNCIL-1 paperwork rewrite spec.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - import guard
    from app.regulatory import versions as _reg_versions  # type: ignore

    _HAS_REG_VERSIONS = True
except Exception:  # pragma: no cover - defensive
    _reg_versions = None  # type: ignore[assignment]
    _HAS_REG_VERSIONS = False


# ---------------------------------------------------------------------------
# BOT-B's g99_brief module is optional — if it's on disk we record the fact
# in the provenance tag, otherwise we continue with what the caller passed.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - import guard
    from utils import g99_brief as _g99_brief_module  # type: ignore  # noqa: F401

    _HAS_G99_BRIEF = True
except Exception:  # pragma: no cover - defensive
    _g99_brief_module = None
    _HAS_G99_BRIEF = False


log = logging.getLogger("princeps.g99_pack_generator")


# Canonical G99 Issue 2 strings (used in cover, header, footer, meta).
def _g99_version() -> dict[str, str]:
    """Return the active G99 version block. Prefers app.regulatory.versions."""
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
        except Exception as exc:
            log.debug("app.regulatory.versions lookup failed: %s", exc)
    # Fallback — hard-coded canonical Issue 2 strings.
    return {
        "name": "Engineering Recommendation G99",
        "version": "Issue 2",
        "published": "2025-03-10",
        "effective": "2025-03-10",
        "citation": "ENA EREC G99 Issue 2 (10 March 2025)",
        "annex_c_effective": "2026-03-01",
        "notes": (
            "Issue 2 published 10 March 2025. Storage-specific Annex C "
            "provisions mandatory from 1 March 2026."
        ),
        "url": "https://www.energynetworks.org/industry-hub/resource-library/?search=G99",
    }


G99_VERSION = _g99_version()
G99_REFERENCE = G99_VERSION["citation"]  # back-compat export used by tests


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_g99_pack(data: dict, *, brief: dict | None = None) -> dict:
    """Generate the G99 application pack payload.

    Args:
        data: Request payload shaped as
            ``{"site":..., "capacity":..., "grid":..., "technology":...,
              "agent_result":..., "brief":...}``. All keys optional.
        brief: Optional pre-built brief dict from
            ``utils.g99_brief.build_g99_brief``. If omitted, ``data["brief"]``
            is consulted. ``brief["form_context"]`` is preferred over raw
            payload fields where present.

    Returns:
        ``{"form_data": dict, "html": str, "filename": str,
           "document_type": "g99_application",
           "auto_fill_pct": int,
           "provenance": str}``.
    """
    data = data or {}
    site = data.get("site", {}) or {}
    capacity = data.get("capacity", {}) or {}
    grid = data.get("grid", {}) or {}
    tech = data.get("technology", {}) or {}
    agent = data.get("agent_result", {}) or {}

    if brief is None:
        brief = data.get("brief") or None
    form_context = (brief or {}).get("form_context") if brief else None

    if form_context:
        provenance = "g99_brief_module"
    elif _HAS_G99_BRIEF:
        provenance = "g99_brief_module_available"
    else:
        provenance = "awaiting_g99_brief_module"

    # ---------------- Resolve inputs -----------------
    lat, lon = _pick_latlon(site, form_context)
    capacity_kw = _pick_capacity_kw(capacity, form_context)
    capacity_mw = capacity_kw / 1000.0
    technology = _pick_technology(tech, form_context)

    application_type = "G100" if capacity_kw <= 50 else "G99"
    ena_category = _ena_category(capacity_kw)

    poc_voltage_kv, recommended_voltage = _resolve_voltage(
        grid, form_context, capacity_mw
    )
    dno = _pick(
        grid, form_context, "dno",
        site.get("dno", "[DNO licence area]"),
        brief_path=["poc_substation", "dno"],
    )
    poc_name = _pick(
        grid, form_context, "nearest_substation", "[DNO primary]",
        brief_path=["poc_substation", "name"],
    )
    distance_km = _pick(
        grid, form_context, "distance_km", None,
        brief_path=["poc_substation", "distance_km"],
    )
    fault_level_ka = _pick(
        grid, form_context, "fault_level_ka", None,
        brief_path=["poc_substation", "fault_level_ka"],
    )

    is_storage = _is_storage_technology(technology)

    # Protection settings — G99 Issue 2 Table 10.1 (single source of truth).
    table_101 = get_table_101(
        voltage_kv=poc_voltage_kv,
        anti_islanding_scheme="rocof",
        g99_type=_g99_type_tag(capacity_kw, capacity_mw),
    )

    fault_contribution = _fault_contribution(
        capacity_mw, technology, poc_voltage_kv
    )

    # ---------------- Build form -----------------
    form = {
        "meta": _meta_block(
            application_type, ena_category, provenance, is_storage
        ),
        "section_a_applicant": _section_a(),
        "section_b_site": _section_b(site, lat, lon, dno),
        "section_c_connection": _section_c(
            capacity_mw, poc_voltage_kv, recommended_voltage,
            poc_name, distance_km, ena_category,
        ),
        "section_d_generator": _section_d(
            technology, tech, capacity_kw, capacity_mw, is_storage,
        ),
        "section_e_export_limits": _section_e(capacity_mw),
        "section_f_protection": _section_f(table_101),
        "section_g_fault_level": _section_g(fault_contribution, fault_level_ka),
        "section_h_commissioning": _section_h(ena_category, is_storage),
        "section_i_signatures": _section_i(),
        "princeps_assessment": {
            "verdict": agent.get("verdict", "—"),
            "confidence_pct": round((agent.get("confidence", 0) or 0) * 100),
            "summary": agent.get("summary", ""),
            "risks": agent.get("risks", []),
            "opportunities": agent.get("opportunities", []),
        },
    }

    if is_storage:
        form["annex_c_storage"] = _annex_c_storage(
            capacity_mw, tech, ena_category
        )

    html_out = _render_g99_html(form)
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
# Meta / section builders
# ---------------------------------------------------------------------------

def _meta_block(
    application_type: str,
    ena_category: str,
    provenance: str,
    is_storage: bool,
) -> dict[str, Any]:
    ver = G99_VERSION
    return {
        "application_type": application_type,
        "ena_category": ena_category,
        "ena_reference": ver["citation"],
        "g99_version": ver["version"],
        "g99_published": ver["published"],
        "annex_c_effective": ver["annex_c_effective"],
        "annex_c_applies": is_storage,
        "url": ver.get("url", ""),
        "provenance": provenance,
        "generated_by": "Princeps",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": (
            "Pre-filled from Princeps assessment. Every field must be verified "
            "by a qualified electrical engineer before submission to the DNO. "
            "Princeps does not constitute engineering advice."
        ),
        "attestation_lines": [
            f"Prepared to ENA EREC G99 Issue 2, published {ver['published']}.",
            (
                "Annex C (storage) requirements go live 1 March 2026; "
                "applicable to this project." if is_storage else
                "Annex C (storage) requirements go live 1 March 2026; "
                "not applicable — no storage declared."
            ),
        ],
    }


def _section_a() -> dict[str, Any]:
    return {
        "title": "Section A — Applicant and Installer Details",
        "applicant": {
            "name": "[Developer / Site Owner Name]",
            "company": "[Applicant Company]",
            "company_number": "[Companies House number]",
            "address": "[Registered address]",
            "postcode": "[Postcode]",
            "telephone": "[Telephone]",
            "email": "[Email]",
            "role": "Generator owner / developer",
        },
        "installer": {
            "name": "[Installer name]",
            "company": "[Installer company]",
            "accreditation_scheme": "[MCS / RECC / NICEIC / NAPIT]",
            "accreditation_number": "[Accreditation number]",
            "contact_email": "[Installer email]",
            "contact_phone": "[Installer telephone]",
        },
        "consultant_engineer": {
            "name": "[Consulting electrical engineer]",
            "institution_membership": "[IET / IEEE / EngTech]",
            "signed_off": False,
        },
    }


def _section_b(
    site: dict,
    lat: float,
    lon: float,
    dno: str,
) -> dict[str, Any]:
    return {
        "title": "Section B — Installation Site",
        "site_name": site.get("name", "[Site name]"),
        "site_address": site.get("address", site.get("name", "[Site address]")),
        "postcode": site.get("postcode", "[Postcode]"),
        "grid_reference_os": _latlon_to_osgb(lat, lon, precision=8),
        "latitude": round(lat, 6) if lat is not None else None,
        "longitude": round(lon, 6) if lon is not None else None,
        "land_area_ha": site.get("area_ha"),
        "land_ownership": "[Freehold / Leasehold / Option]",
        "planning_reference": "[Local planning authority reference]",
        "access_arrangements": "[Site access details]",
        "dno_licence_area": dno,
    }


def _section_c(
    capacity_mw: float,
    poc_voltage_kv: float,
    recommended_voltage: float,
    poc_name: str,
    distance_km: float | None,
    ena_category: str,
) -> dict[str, Any]:
    return {
        "title": "Section C — Connection Arrangement and Point of Connection",
        "connection_type": (
            "New dedicated connection" if capacity_mw > 5
            else "Modification to existing supply"
        ),
        "proposed_voltage_kv": recommended_voltage,
        "existing_voltage_kv": poc_voltage_kv,
        "point_of_connection_substation": poc_name,
        "point_of_connection_distance_km": distance_km,
        "earthing_arrangement": (
            "Solid earthing via dedicated earth electrode"
            if poc_voltage_kv >= 11
            else "TN-C-S via DNO service cable"
        ),
        "metering_arrangement": (
            "Half-hourly export + import metering (HH CT/VT)"
        ),
        "mpan_core": "[MPAN — to be confirmed]",
        "dno_reference": "[To be assigned by DNO]",
        "intertrip_required": ena_category in ("C", "D (NSIP)"),
    }


def _section_d(
    technology: str,
    tech: dict,
    capacity_kw: float,
    capacity_mw: float,
    is_storage: bool,
) -> dict[str, Any]:
    cf = 0.11 if technology == "solar" else 0.25 if technology == "wind" else 0.6
    return {
        "title": "Section D — Generating Plant / Storage Specifications",
        "technology": technology,
        "total_capacity_kw": capacity_kw,
        "total_capacity_mw": round(capacity_mw, 3),
        "number_of_units": tech.get("num_units", math.ceil(capacity_kw / 500)),
        "unit_capacity_kw": tech.get("unit_kw", min(500, capacity_kw)),
        "manufacturer": tech.get("manufacturer", "[Manufacturer]"),
        "model": tech.get("model", "[Model]"),
        "phase_configuration": "Three-phase",
        "rated_frequency_hz": 50,
        "rated_power_factor": 0.95,
        "power_factor_range": "0.95 leading to 0.95 lagging",
        "reactive_power_capability": "4-quadrant inverter \u00b1 0.329 \u00d7 Pmax",
        "inverter": {
            "type": tech.get(
                "inverter",
                "Grid-forming battery PCS" if is_storage
                else "Grid-following string inverter",
            ),
            "topology": tech.get(
                "inverter_topology",
                "Containerised PCS" if is_storage else "Central",
            ),
            "manufacturer": tech.get("inverter_make", "[To be specified]"),
            "g99_type_test_certificate": (
                "[Reference to G99 Issue 2 Annex B certificate]"
            ),
        },
        "anti_islanding": {
            "primary_scheme": "Rate of Change of Frequency (RoCoF)",
            "rocof_setting_hz_per_s": 1.0,
            "rocof_window_ms": 500,
            "rocof_time_delay_s": 0.5,
            "vector_shift_enabled": False,
            "vector_shift_note": (
                "Vector-shift is disabled by default under G99 Issue 2; "
                "enable only if the DNO explicitly requests as legacy backup."
            ),
            "intentional_islanding": False,
            "loss_of_mains_ride_through": (
                "\u22651 Hz/s for 500 ms per G99 Issue 2 \u00a710.6"
            ),
        },
        "fault_ride_through": {
            "required": capacity_mw >= 1.0,
            "profile": (
                "G99 Issue 2 Annex A.7 envelope (zero voltage 140 ms, "
                "recovery to 85% by 1500 ms)"
            ),
        },
        "estimated_annual_output_mwh": round(capacity_mw * 8760 * cf, 0),
    }


def _section_e(capacity_mw: float) -> dict[str, Any]:
    return {
        "title": "Section E — Export Limits and DNO Interface Settings",
        "requested_export_mw": capacity_mw,
        "export_limit_scheme": (
            "Active Network Management (ANM)" if capacity_mw > 10
            else "Hard-wired export limit relay"
        ),
        "reverse_power_protection": capacity_mw < 1.0,
        "anm_signal_type": (
            "Fibre / 4G to DNO NMS" if capacity_mw > 10 else "N/A"
        ),
        "curtailment_expected_pct": (
            "2-8%" if capacity_mw > 10 else "< 1%"
        ),
        "dno_interface_signals": [
            "Trip command (hardwired)",
            "Setpoint (MW/MVAr) via DNP3 or IEC 61850 for Type C/D",
            "Permissive signal — required before synchronisation",
        ],
        "dno_scada_interface": (
            "IEC 61850 (Type C/D) / DNP3 (Type B) / hardwired (Type A)"
        ),
    }


def _section_f(table_101: dict) -> dict[str, Any]:
    return {
        "title": (
            "Section F — Protection Settings "
            "(cross-reference G99 Issue 2 Table 10.1)"
        ),
        "reference_table": table_101["meta"]["reference"],
        "voltage_band": table_101["meta"]["voltage_band"],
        "anti_islanding_scheme": table_101["meta"]["anti_islanding_scheme"],
        "voltage_protection": table_101["voltage_protection"],
        "frequency_protection": table_101["frequency_protection"],
        "loss_of_mains": table_101["loss_of_mains"],
        "neutral_voltage_displacement": table_101["nvd"],
        "settings_sealed_after_commissioning": True,
        "relay_manufacturer": "[Relay manufacturer]",
        "relay_model": "[G99 Issue 2 type-tested relay model]",
        "voltage_step_notes": table_101["voltage_step_notes"],
        "table_101_rows": table_101["rows"],
    }


def _section_g(
    fault_contribution: dict[str, Any],
    fault_level_ka: Any,
) -> dict[str, Any]:
    return {
        "title": "Section G — Fault-Level Contribution",
        **fault_contribution,
        "network_fault_level_at_poc_mva": "[To be provided by DNO]",
        "switchgear_rating_ka": fault_level_ka,
        "contribution_note": (
            "Generator fault contribution must not cause total network fault "
            "level to exceed switchgear ratings at the point of connection. "
            "DNO will assess per G99 Issue 2 \u00a712."
        ),
    }


def _section_h(
    ena_category: str,
    is_storage: bool,
) -> dict[str, Any]:
    return {
        "title": "Section H — Commissioning Checklist",
        "items": _commissioning_checklist(ena_category, is_storage),
        "witness_by_dno": ena_category in ("B", "C", "D (NSIP)"),
        "expected_commissioning_date": "[Target date]",
    }


def _section_i() -> dict[str, Any]:
    return {
        "title": "Section I — Signatures",
        "applicant": {
            "printed_name": "[Applicant full name]",
            "signed": False,
            "date": "[YYYY-MM-DD]",
        },
        "installer": {
            "printed_name": "[Installer full name]",
            "accreditation_body": "[Scheme]",
            "signed": False,
            "date": "[YYYY-MM-DD]",
        },
        "consulting_engineer": {
            "printed_name": "[Chartered Engineer name]",
            "institution": "[IET / IEEE / EngTech]",
            "signed": False,
            "date": "[YYYY-MM-DD]",
        },
        "declaration": (
            "I/We declare that the information provided is, to the best of "
            "our knowledge, accurate and complete, and that the generating "
            "plant will comply with ENA EREC G99 Issue 2 (10 March 2025)."
        ),
    }


# ---------------------------------------------------------------------------
# Annex C — storage-specific block (mandatory from 1 March 2026)
# ---------------------------------------------------------------------------

def _annex_c_storage(
    capacity_mw: float,
    tech: dict,
    ena_category: str,
) -> dict[str, Any]:
    """Populate Annex C storage declarations per G99 Issue 2.

    Annex C requires BESS applicants to declare:
      - discharge capability in frequency response modes (FFR / DC / DR / DM)
      - state-of-charge management and minimum SoC for frequency services
      - anti-islanding behaviour specific to grid-forming / grid-following
      - BESS-specific protection (DC-side, battery management, thermal runaway)
      - grid-forming vs grid-following declaration
      - black start capability declaration (where applicable)
    """
    duration_h = float(tech.get("duration_h", 2.0))
    grid_forming = bool(tech.get("grid_forming", False))
    black_start = bool(tech.get("black_start_capable", False))
    return {
        "title": (
            "Annex C — Storage Declarations (G99 Issue 2, effective "
            "1 March 2026)"
        ),
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
                "declared": False,
            },
            "dynamic_regulation": {
                "capability_mw": round(capacity_mw * 0.5, 2),
                "declared": False,
            },
            "firm_frequency_response": {
                "capability_mw": round(capacity_mw * 0.5, 2),
                "declared": False,
            },
            "note": (
                "Declare the MW capability and sustained duration for each "
                "service at the relevant SoC envelope per NGESO product terms."
            ),
        },
        "state_of_charge_management": {
            "min_soc_pct": 10,
            "max_soc_pct": 90,
            "frequency_service_reserve_pct": 20,
            "auto_recharge_after_event": True,
            "note": (
                "SoC envelope must allow sustained response for the declared "
                "frequency service window without excursions below the minimum "
                "operating SoC of the cell manufacturer."
            ),
        },
        "anti_islanding_storage": {
            "primary_scheme": (
                "Grid-forming virtual synchronous machine with RoCoF blocking"
                if grid_forming else
                "Grid-following with RoCoF + passive LoM"
            ),
            "virtual_inertia_mw_s_per_mw": (
                tech.get("virtual_inertia_s", 5.0) if grid_forming else 0.0
            ),
            "black_start_capable": black_start,
            "note": (
                "Grid-forming converters operating without a reference must "
                "satisfy the G99 Issue 2 Annex C \u00a7C.4 intentional-island "
                "prohibition unless a formal island agreement with the DNO "
                "is in place."
            ),
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
                "Anti-parallel protection matching G99 Table 10.1",
                "Reverse power protection where charging is prohibited",
            ],
        },
        "grid_forming_declaration": {
            "mode": "grid-forming" if grid_forming else "grid-following",
            "synchronous_support": grid_forming,
            "compliance_evidence": (
                "[Type test certificate and hardware-in-the-loop study reference]"
            ),
        },
        "commercial_services": [
            f"Dynamic Containment: {'declared' if capacity_mw >= 1 else 'n/a'}",
            f"Balancing Mechanism: {'available' if capacity_mw >= 1 else 'n/a'}",
            (
                "Black start: declared"
                if black_start else
                "Black start: not declared"
            ),
        ],
        "commissioning_additions": [
            "Annex C commissioning: SoC excursion test under declared response",
            "Annex C commissioning: dynamic response step test (FFR envelope)",
            "Annex C commissioning: BMS trip and reset verification",
        ],
        "ena_reference": (
            f"G99 Issue 2 Annex C, effective "
            f"{G99_VERSION['annex_c_effective']}"
        ),
        "category_impact_note": (
            "Annex C applies to all storage categories. The Type-specific "
            "Sections D, E, F and H must be read in conjunction with this Annex. "
            f"This project is Category {ena_category}."
        ),
    }


# ---------------------------------------------------------------------------
# Resolvers / helpers
# ---------------------------------------------------------------------------

def _pick(
    raw: dict,
    ctx: dict | None,
    key: str,
    default: Any,
    *,
    brief_path: list[str] | None = None,
) -> Any:
    """Prefer value from brief context, then raw payload, then default."""
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
        lat = p.get("lat")
        lon = p.get("lon")
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
    return any(
        k in t for k in (
            "bess", "battery", "storage", "hybrid", "bss", "pumped_storage"
        )
    )


def _g99_type_tag(capacity_kw: float, capacity_mw: float) -> str:
    if capacity_kw <= 50:
        return "Type A"
    if capacity_mw <= 10:
        return "Type B"
    if capacity_mw <= 50:
        return "Type C"
    return "Type D"


def _resolve_voltage(
    grid: dict,
    ctx: dict | None,
    capacity_mw: float,
) -> tuple[float, float]:
    """Return ``(existing_poc_voltage_kv, recommended_voltage_kv)``."""
    existing = None
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


def _fault_contribution(
    capacity_mw: float,
    technology: str,
    voltage_kv: float,
) -> dict[str, Any]:
    """Approximate inverter fault-level contribution per G99 Issue 2 \u00a712."""
    t = (technology or "").lower()
    if t in ("solar", "bess", "battery", "storage", "hybrid"):
        multiplier = 1.2
        description = (
            "Inverter-interfaced (solar / BESS) — sub-cycle, "
            "G99 Issue 2 Type B/C guidance."
        )
    elif t == "wind":
        multiplier = 1.3
        description = "Full-converter wind turbine (Type 4)."
    else:
        multiplier = 1.5
        description = "Conservative default — verify with manufacturer."
    rated_current_a = (
        capacity_mw * 1_000_000 / (voltage_kv * 1000.0 * math.sqrt(3))
        if voltage_kv > 0 else 0
    )
    peak_ka = rated_current_a * multiplier / 1000.0
    return {
        "multiplier_of_rated": multiplier,
        "rated_current_a": round(rated_current_a, 1),
        "estimated_peak_ka": round(peak_ka, 3),
        "description": description,
        "basis": "inverter-interfaced, sub-cycle, G99 Issue 2 \u00a712",
    }


def _commissioning_checklist(
    category: str,
    is_storage: bool,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        {"step": "G99 Issue 2 A1 application form submitted", "required": True, "done": False},
        {"step": "Installer-declared SLD reviewed by DNO", "required": True, "done": False},
        {"step": "Protection relay settings (Table 10.1) verified + sealed",
         "required": True, "done": False},
        {"step": "Loss-of-mains test (RoCoF injection)", "required": True, "done": False},
        {"step": "Over/under voltage trip test — all stages", "required": True, "done": False},
        {"step": "Over/under frequency trip test — all stages", "required": True, "done": False},
        {"step": "Anti-islanding timer verified (\u2264 2 s)", "required": True, "done": False},
        {"step": "Earth continuity + fault loop impedance measured",
         "required": True, "done": False},
    ]
    if category in ("B", "C", "D (NSIP)"):
        items.extend([
            {"step": "Interface protection witness test (DNO present)",
             "required": True, "done": False},
            {"step": "Fault-level calculation + switchgear adequacy",
             "required": True, "done": False},
            {"step": "Reactive power P-Q chart demonstrated",
             "required": True, "done": False},
        ])
    if category in ("C", "D (NSIP)"):
        items.extend([
            {"step": "Dynamic stability study submitted", "required": True, "done": False},
            {"step": "Fault ride-through demonstrated on type-test or at site",
             "required": True, "done": False},
            {"step": "Intertrip / teleprotection test", "required": True, "done": False},
        ])
    if category == "D (NSIP)":
        items.append(
            {"step": "NGESO Grid Code compliance statement",
             "required": True, "done": False}
        )
    if is_storage:
        items.extend([
            {"step": "Annex C — SoC envelope verified for declared frequency response",
             "required": True, "done": False},
            {"step": "Annex C — BMS trip and reset verification",
             "required": True, "done": False},
            {"step": "Annex C — grid-forming / grid-following declaration logged",
             "required": True, "done": False},
        ])
    items.append(
        {"step": "G99 A2 commissioning confirmation returned to DNO",
         "required": True, "done": False}
    )
    return items


def _latlon_to_osgb(
    lat: float,
    lon: float,
    precision: int = 8,
) -> str:
    """Return a true OSGB36 National Grid reference via ``utils.osgb``.

    COUNCIL-1 flagged the previous linear approximation (was at line 169 in
    the old generator) as a fabrication. This now delegates to BOT-R2's
    pyproj-backed helper. If the helper is missing we raise a visible TODO
    rather than silently returning a bogus prefix.
    """
    if _HAS_OSGB and _osgb_to_grid_ref is not None:
        return _osgb_to_grid_ref(lat, lon, precision=precision)
    # TODO: remove this branch once utils.osgb is guaranteed present. Inline
    # pyproj path kept so the generator never crashes a pack render.
    try:
        from pyproj import Transformer  # type: ignore

        transformer = Transformer.from_crs(
            "EPSG:4326", "EPSG:27700", always_xy=True
        )
        easting, northing = transformer.transform(lon, lat)
        return (
            f"[OSGB36 pyproj fallback — "
            f"E {int(easting)}, N {int(northing)}]"
        )
    except Exception:
        return f"[OSGB TODO — WGS84 {lat:.5f}, {lon:.5f}]"


def _slug(s: str | None) -> str:
    return re.sub(r"[^\w-]", "-", s or "site").strip("-")[:40]


def _count_filled(d: dict) -> tuple[int, int]:
    filled = 0
    total = 0
    placeholders = {"[", "to be", "tbd", "tbc", "n/a", "—"}
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
# HTML rendering — matches the ENA form layout. Gold Princeps palette.
# ---------------------------------------------------------------------------

def _render_g99_html(form: dict) -> str:
    meta = form["meta"]
    sections_html = [
        _render_section_a(form["section_a_applicant"]),
        _render_section_b(form["section_b_site"]),
        _render_section_c(form["section_c_connection"]),
        _render_section_d(form["section_d_generator"]),
        _render_section_e(form["section_e_export_limits"]),
        _render_section_f(form["section_f_protection"]),
        _render_section_g(form["section_g_fault_level"]),
        _render_section_h(form["section_h_commissioning"]),
        _render_section_i(form["section_i_signatures"]),
    ]

    if form.get("annex_c_storage"):
        sections_html.append(_render_annex_c(form["annex_c_storage"]))

    assessment = form.get("princeps_assessment", {})
    verdict = assessment.get("verdict", "—")
    verdict_color = {
        "GO": "#228B22",
        "CAUTION": "#D4A017",
        "NO-GO": "#C0392B",
    }.get(verdict, "#4a4a4a")

    css = _render_css()
    header = _render_header(meta, assessment, verdict, verdict_color)
    footer = _render_footer(meta)

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>G99 Application Pack — "
        f"{html.escape(form['section_b_site'].get('site_name','Site'))}</title>"
        f"<style>{css}</style></head><body>"
        f"{header}"
        f"{''.join(sections_html)}"
        f"{footer}"
        "</body></html>"
    )


def _render_css() -> str:
    return """
      :root {
        --gold: #C9A64B; --gold-dark: #A88732; --gold-light: #F5E9C8;
        --ink: #1a1a1a; --ink-muted: #4a4a4a; --rule: #E6D9B8;
      }
      body { font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
             margin: 0; padding: 22px; color: var(--ink);
             font-size: 10.5px; line-height: 1.5; }
      h1 { color: var(--ink); font-size: 22px; margin: 0 0 2px;
           letter-spacing: 1px; }
      h1::before { content: "\\25C6"; color: var(--gold); margin-right: 8px; }
      h2 { color: var(--ink); font-size: 13.5px; margin: 18px 0 6px;
           padding: 5px 10px; background: var(--gold-light);
           border-left: 4px solid var(--gold); letter-spacing: .5px;
           font-weight: 700; }
      h3 { color: var(--ink); font-size: 11px; margin: 10px 0 4px;
           border-bottom: 1px dotted var(--rule); font-weight: 600; }
      .subtitle { color: var(--ink-muted); font-size: 9.5px; }
      .disclaimer { background: var(--gold-light); padding: 7px 10px;
                    border-radius: 4px; font-size: 9px;
                    color: var(--gold-dark); margin: 10px 0;
                    border-left: 3px solid var(--gold-dark); }
      .attestation { background: #fff8e1; padding: 6px 10px; border-radius: 4px;
                     font-size: 9px; color: var(--ink); margin: 6px 0;
                     border-left: 3px solid var(--gold); }
      .annex-c { background: #fffbea; padding: 8px 10px;
                 border: 1px solid var(--gold); border-radius: 4px;
                 margin: 10px 0; }
      .annex-c h2 { background: var(--gold); color: #fff;
                    border-left: 4px solid var(--gold-dark); }
      .meta-strip { display: flex; gap: 14px; font-size: 9px;
                    color: var(--ink-muted); margin: 2px 0 10px;
                    flex-wrap: wrap; }
      .meta-strip span.chip { background: var(--gold-light);
                              color: var(--gold-dark); padding: 2px 8px;
                              border-radius: 8px; font-weight: 600; }
      table.form { width: 100%; border-collapse: collapse;
                   margin: 3px 0 10px; }
      table.form td { padding: 3px 8px; border-bottom: 1px solid var(--rule);
                      vertical-align: top; }
      table.form td.lbl { font-weight: 600; width: 42%;
                          color: var(--ink-muted); }
      table.set { width: 100%; border-collapse: collapse; margin: 6px 0 10px;
                  font-size: 9.5px; }
      table.set th { background: var(--gold); color: #fff; padding: 5px 8px;
                     font-weight: 600; text-align: left; letter-spacing: .3px;
                     font-size: 9px; text-transform: uppercase; }
      table.set td { padding: 4px 8px; border-bottom: 1px solid var(--rule); }
      table.set tr:nth-child(even) td { background: #FAF7EE; }
      ul.check { padding-left: 18px; margin: 4px 0; }
      ul.check li { margin: 2px 0; list-style: square; }
      .verdict { display: inline-block; padding: 3px 14px; border-radius: 4px;
                 font-weight: 800; font-size: 14px; color: white; }
      .note { color: var(--ink-muted); font-size: 9px; }
      .sig-box { display: flex; gap: 12px; margin-top: 8px; }
      .sig-box .sig { flex: 1; border: 1px dashed var(--rule);
                      border-radius: 4px; padding: 8px; min-height: 64px; }
      .sig-box .sig .role { font-weight: 700; font-size: 10px;
                             color: var(--ink); }
      .sig-box .sig .line { border-bottom: 1px solid var(--gold);
                             margin: 18px 0 4px; }
      .footer { margin-top: 24px; padding-top: 10px;
                border-top: 2px solid var(--gold); font-size: 8.5px;
                color: var(--ink-muted); text-align: center; }
      .placeholder { color: var(--gold-dark); background: var(--gold-light);
                     padding: 1px 4px; border: 1px dashed var(--gold-dark);
                     border-radius: 2px; font-family: 'JetBrains Mono',
                     'Consolas', monospace; font-size: 9px; }
    """


def _render_header(
    meta: dict,
    assessment: dict,
    verdict: str,
    verdict_color: str,
) -> str:
    provenance_line = (
        f"Data provenance: <strong>{html.escape(meta['provenance'])}</strong>"
    )
    if meta["provenance"] == "awaiting_g99_brief_module":
        provenance_line += (
            " — upstream brief module not detected; "
            "fields pre-filled from raw project context."
        )
    attestation_html = "<br>".join(
        f"\u2022 {html.escape(line)}" for line in meta.get("attestation_lines", [])
    )
    return (
        f"<h1>G99 APPLICATION PACK</h1>"
        f"<div class='subtitle'>{html.escape(meta['ena_reference'])} "
        f"&mdash; {html.escape(meta['application_type'])} Route "
        f"(Category {html.escape(meta['ena_category'])})</div>"
        f"<div class='meta-strip'>"
        f"<span class='chip'>{html.escape(meta['application_type'])}</span>"
        f"<span class='chip'>Category {html.escape(meta['ena_category'])}</span>"
        f"<span class='chip'>G99 {html.escape(meta['g99_version'])}</span>"
        f"<span class='chip'>Published {html.escape(meta['g99_published'])}</span>"
        + (
            f"<span class='chip'>Annex C live "
            f"{html.escape(meta['annex_c_effective'])}</span>"
            if meta.get("annex_c_applies") else
            f"<span class='chip'>Annex C storage: N/A</span>"
        )
        + f"<span>Generated {meta['generated_at'][:10]} by "
          f"{html.escape(meta['generated_by'])}</span>"
          f"</div>"
          f"<div class='attestation'><strong>Attestation</strong><br>"
          f"{attestation_html}</div>"
          f"<div class='disclaimer'>{html.escape(meta['disclaimer'])}"
          f"<br><span class='note'>{provenance_line}</span></div>"
          f"<div style='margin: 6px 0 4px;'>"
          f"<span class='verdict' style='background:{verdict_color};'>"
          f"{html.escape(verdict)}</span>"
          f" <span class='note' style='margin-left:8px;'>Princeps confidence: "
          f"{assessment.get('confidence_pct','—')}%</span></div>"
          f"<p class='note'>{html.escape(assessment.get('summary',''))}</p>"
    )


def _render_footer(meta: dict) -> str:
    return (
        f"<div class='footer'>"
        f"Prepared by Princeps against {html.escape(meta['ena_reference'])}. "
        f"G99 Issue 2 published {html.escape(meta['g99_published'])}; "
        f"Annex C (storage) effective {html.escape(meta['annex_c_effective'])}. "
        f"All values must be verified by a qualified electrical engineer "
        f"before submission to the Distribution Network Operator. "
        f"Princeps is not a substitute for professional engineering advice."
        f"</div>"
    )


def _render_kv_table(d: dict[str, Any]) -> str:
    rows = []
    for k, v in d.items():
        if isinstance(v, (dict, list)) or k == "title":
            continue
        rows.append(
            f"<tr><td class='lbl'>{_humanise(k)}</td>"
            f"<td>{_fmt(v)}</td></tr>"
        )
    return f"<table class='form'>{''.join(rows)}</table>" if rows else ""


def _render_subsection(title: str, d: dict[str, Any]) -> str:
    return f"<h3>{html.escape(title)}</h3>{_render_kv_table(d)}"


def _render_section_a(s: dict) -> str:
    return (
        f"<h2>{html.escape(s['title'])}</h2>" +
        _render_subsection("Applicant", s.get("applicant", {})) +
        _render_subsection("Installer", s.get("installer", {})) +
        _render_subsection("Consulting engineer",
                           s.get("consultant_engineer", {}))
    )


def _render_section_b(s: dict) -> str:
    return f"<h2>{html.escape(s['title'])}</h2>{_render_kv_table(s)}"


def _render_section_c(s: dict) -> str:
    return f"<h2>{html.escape(s['title'])}</h2>{_render_kv_table(s)}"


def _render_section_d(s: dict) -> str:
    return (
        f"<h2>{html.escape(s['title'])}</h2>" +
        _render_kv_table(s) +
        _render_subsection("Inverter", s.get("inverter", {})) +
        _render_subsection("Anti-islanding", s.get("anti_islanding", {})) +
        _render_subsection("Fault ride-through", s.get("fault_ride_through", {}))
    )


def _render_section_e(s: dict) -> str:
    signals = s.get("dno_interface_signals", []) or []
    signals_html = (
        "<ul class='check'>" +
        "".join(f"<li>{html.escape(str(sig))}</li>" for sig in signals) +
        "</ul>"
        if signals else ""
    )
    return (
        f"<h2>{html.escape(s['title'])}</h2>" +
        _render_kv_table(s) +
        (
            f"<h3>DNO interface signals</h3>{signals_html}"
            if signals_html else ""
        )
    )


def _render_section_f(s: dict) -> str:
    rows = s.get("table_101_rows", []) or []
    rows_html = "".join(
        f"<tr><td>{html.escape(str(r.get('category','')))}</td>"
        f"<td><strong>{html.escape(str(r.get('function','')))}</strong></td>"
        f"<td>{html.escape(str(r.get('threshold','')))}</td>"
        f"<td>{html.escape(str(r.get('time_s','')))}</td>"
        f"<td>{html.escape(str(r.get('action','')))}</td></tr>"
        for r in rows
    )
    tbl = (
        "<table class='set'><tr><th>Category</th><th>Function</th>"
        "<th>Setting</th><th>Time (s)</th><th>Action</th></tr>"
        f"{rows_html}</table>"
    )
    step_notes = s.get("voltage_step_notes", []) or []
    notes_html = (
        "<ul class='check'>" +
        "".join(f"<li>{html.escape(str(n))}</li>" for n in step_notes) +
        "</ul>"
        if step_notes else ""
    )
    return (
        f"<h2>{html.escape(s['title'])}</h2>"
        f"<div class='note'>Cross-reference: "
        f"{html.escape(str(s.get('reference_table','G99 Issue 2 Table 10.1')))} "
        f"&middot; voltage band "
        f"{html.escape(str(s.get('voltage_band','—')))} "
        f"&middot; anti-islanding: <strong>"
        f"{html.escape(str(s.get('anti_islanding_scheme','rocof')))}</strong>"
        f"</div>"
        f"{tbl}"
        f"<h3>ENA P28/P29 voltage-step compliance (\u00b13% normal)</h3>"
        f"{notes_html}"
    )


def _render_section_g(s: dict) -> str:
    return f"<h2>{html.escape(s['title'])}</h2>{_render_kv_table(s)}"


def _render_section_h(s: dict) -> str:
    items = s.get("items", []) or []
    items_html = "".join(
        f"<tr><td>{'\u2611' if it.get('done') else '\u2610'}</td>"
        f"<td>{html.escape(str(it.get('step','')))}</td>"
        f"<td>{'Required' if it.get('required') else 'Optional'}</td></tr>"
        for it in items
    )
    tbl = (
        "<table class='set'><tr><th></th><th>Commissioning step</th>"
        "<th>Status</th></tr>"
        f"{items_html}</table>"
    )
    meta = {
        "witness_by_dno": s.get("witness_by_dno"),
        "expected_commissioning_date": s.get("expected_commissioning_date"),
    }
    return (
        f"<h2>{html.escape(s['title'])}</h2>"
        f"{_render_kv_table(meta)}{tbl}"
    )


def _render_section_i(s: dict) -> str:
    sigs = []
    for role in ("applicant", "installer", "consulting_engineer"):
        b = s.get(role, {})
        sigs.append(
            f"<div class='sig'>"
            f"<div class='role'>"
            f"{html.escape(role.replace('_',' ').title())}</div>"
            f"<div class='line'></div>"
            f"<div class='note'>Name: "
            f"{html.escape(str(b.get('printed_name','[Name]')))}</div>"
            f"<div class='note'>Date: "
            f"{html.escape(str(b.get('date','[YYYY-MM-DD]')))}</div>"
            f"</div>"
        )
    return (
        f"<h2>{html.escape(s['title'])}</h2>"
        f"<div class='note'>{html.escape(str(s.get('declaration','')))}</div>"
        f"<div class='sig-box'>{''.join(sigs)}</div>"
    )


def _render_annex_c(s: dict) -> str:
    nameplate = s.get("nameplate", {}) or {}
    fr = s.get("frequency_response_modes", {}) or {}
    soc = s.get("state_of_charge_management", {}) or {}
    ai = s.get("anti_islanding_storage", {}) or {}
    bess = s.get("bess_specific_protection", {}) or {}
    gfm = s.get("grid_forming_declaration", {}) or {}
    comm = s.get("commercial_services", []) or []
    commissioning = s.get("commissioning_additions", []) or []

    fr_rows = []
    for mode_key, mode_val in fr.items():
        if mode_key == "note" or not isinstance(mode_val, dict):
            continue
        fr_rows.append(
            f"<tr><td><strong>{_humanise(mode_key)}</strong></td>"
            f"<td>{_fmt(mode_val.get('capability_mw'))} MW</td>"
            f"<td>{_fmt(mode_val.get('response_time_ms','—'))} ms</td>"
            f"<td>{'Declared' if mode_val.get('declared') else 'Not declared'}"
            f"</td></tr>"
        )
    fr_tbl = (
        "<table class='set'><tr><th>Mode</th><th>Capability</th>"
        "<th>Response</th><th>Status</th></tr>"
        f"{''.join(fr_rows)}</table>"
    )

    bess_rows = []
    for k, v in bess.items():
        if isinstance(v, list):
            bess_rows.append(
                f"<tr><td class='lbl'>{_humanise(k)}</td>"
                f"<td>{html.escape(', '.join(str(x) for x in v))}</td></tr>"
            )
    bess_tbl = f"<table class='form'>{''.join(bess_rows)}</table>"

    comm_html = (
        "<ul class='check'>" +
        "".join(f"<li>{html.escape(str(c))}</li>" for c in comm) +
        "</ul>"
    )
    commissioning_html = (
        "<ul class='check'>" +
        "".join(
            f"<li>{html.escape(str(x))}</li>" for x in commissioning
        ) +
        "</ul>"
    )

    return (
        f"<div class='annex-c'>"
        f"<h2>{html.escape(s['title'])}</h2>"
        f"<div class='note'>{html.escape(str(s.get('applicability','')))}</div>"
        f"<h3>Nameplate</h3>{_render_kv_table(nameplate)}"
        f"<h3>Frequency response modes</h3>{fr_tbl}"
        f"<div class='note'>{html.escape(str(fr.get('note','')))}</div>"
        f"<h3>State of charge management</h3>{_render_kv_table(soc)}"
        f"<h3>Anti-islanding (storage-specific)</h3>{_render_kv_table(ai)}"
        f"<h3>BESS-specific protection</h3>{bess_tbl}"
        f"<h3>Grid-forming declaration</h3>{_render_kv_table(gfm)}"
        f"<h3>Commercial services</h3>{comm_html}"
        f"<h3>Additional commissioning tests</h3>{commissioning_html}"
        f"<div class='note'>"
        f"Reference: {html.escape(str(s.get('ena_reference','')))}. "
        f"{html.escape(str(s.get('category_impact_note','')))}"
        f"</div>"
        f"</div>"
    )


def _humanise(key: str) -> str:
    return key.replace("_", " ").replace("-", " ").title()


def _fmt(v: Any) -> str:
    if v is None or v == "":
        return "<span class='note'>—</span>"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        return f"{v:,.3f}".rstrip("0").rstrip(".")
    s = str(v)
    if s.startswith("["):
        return f"<span class='placeholder'>{html.escape(s)}</span>"
    return html.escape(s)


# ---------------------------------------------------------------------------
# Back-compat passthrough adapters for legacy duplicate callsites
# (utils.market_intelligence.generate_g99_application and
#  utils.g99_compliance.generate_g99_application). These stay in the dedicated
# modules as thin wrappers — they call into this canonical generator.
# ---------------------------------------------------------------------------


def generate_g99_application_from_project(
    project: dict, grid_context: dict, site_context: dict
) -> dict:
    """Canonical adapter for the ``market_intelligence`` input shape.

    The legacy ``utils.market_intelligence.generate_g99_application`` accepted
    ``(project, grid_context, site_context)``. This adapter re-packs that
    triple into the canonical payload and returns the full pack (form_data +
    html + filename + ...).
    """
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
    technology = {
        "type": (project.get("technology") or "solar").lower(),
    }
    return generate_g99_pack({
        "site": site,
        "capacity": capacity,
        "grid": grid,
        "technology": technology,
    })


def generate_g99_application_from_scalars(
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str,
    voltage_kv: float,
    dno: str | None = None,
    phase: str = "three_phase",
    applicant: dict[str, str] | None = None,
) -> dict:
    """Canonical adapter for the ``g99_compliance`` input shape.

    ``utils.g99_compliance.generate_g99_application`` historically took
    positional scalars. This adapter assembles them into the canonical
    payload and returns the full pack.
    """
    site = {
        "name": (applicant or {}).get("site_name") or "[Site name]",
        "lat": lat,
        "lon": lon,
        "dno": dno or "",
    }
    capacity = {
        "capacity_mw": capacity_mw,
        "capacity_kw": capacity_mw * 1000.0,
    }
    grid = {
        "voltage_kv": voltage_kv,
        "dno": dno or "",
    }
    tech = {"type": (technology or "solar").lower()}
    pack = generate_g99_pack({
        "site": site,
        "capacity": capacity,
        "grid": grid,
        "technology": tech,
    })
    # Preserve the ``g99_compliance`` contract: merge the applicant sub-dict
    # into Section A if supplied.
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
# CLI / import smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover - manual smoke test
    out = generate_g99_pack({
        "site": {"name": "Uttoxeter BESS", "lat": 52.9, "lon": -1.86,
                  "postcode": "ST14 8BH"},
        "capacity": {"capacity_mw": 100},
        "grid": {"voltage_kv": 33, "nearest_substation": "NGED Uttoxeter",
                  "distance_km": 1.2, "dno": "NGED"},
        "technology": {"type": "bess", "duration_h": 2,
                        "grid_forming": True},
        "agent_result": {"verdict": "GO", "confidence": 0.82,
                          "summary": "Viable 100 MW BESS site."},
    })
    print("filename:", out["filename"])
    print("provenance:", out["provenance"])
    print("auto_fill_pct:", out.get("auto_fill_pct"))
    print("annex_c_present:", "annex_c_storage" in out["form_data"])
    print("html length:", len(out["html"]))
