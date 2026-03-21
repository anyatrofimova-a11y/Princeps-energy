"""
G99 Application Pack Generator — pre-fills G99/G100 form data
and generates a PDF application pack with site map and key parameters.

ENA Engineering Recommendation G99 Issue 2 (March 2025):
  - Applies to all generating plant >16A per phase (or >3.68kW single-phase)
  - G99 for bespoke connection assessment (non-type-tested)
  - G100 for type-tested inverter systems

This generator pre-fills the application data fields from Princeps assessment
results, saving developers ~2 days of manual form filling per site.
"""
import io
import json
import math
from datetime import datetime


def generate_g99_pack(data: dict) -> dict:
    """
    Generate G99 application pack data from site assessment.

    Args:
        data: dict with keys: site, capacity, grid, technology, agent_result

    Returns:
        dict with all G99 form fields pre-filled + PDF-ready HTML
    """
    site = data.get("site", {})
    capacity = data.get("capacity", {})
    grid = data.get("grid", {})
    tech = data.get("technology", {})
    agent = data.get("agent_result", {})

    lat = site.get("lat", 0)
    lon = site.get("lon", 0)
    capacity_kw = capacity.get("capacity_kw", 5000)
    capacity_mw = capacity_kw / 1000

    # Determine G99 vs G100 route
    application_type = "G100" if capacity_kw <= 50 else "G99"
    # Determine ENA category
    if capacity_kw <= 16:
        ena_category = "A1"
    elif capacity_kw <= 50:
        ena_category = "A2"
    elif capacity_kw <= 1000:
        ena_category = "B"
    elif capacity_kw <= 50000:
        ena_category = "C"
    else:
        ena_category = "D (NSIP)"

    # Connection voltage logic
    voltage_kv = grid.get("voltage_kv", 33)
    if capacity_mw > 50:
        recommended_voltage = 132
    elif capacity_mw > 5:
        recommended_voltage = 33
    else:
        recommended_voltage = 11

    # Fault level estimate (simplified)
    fault_level_mva = voltage_kv * voltage_kv / 10  # rough Z-based estimate

    # Build form fields
    form = {
        "meta": {
            "application_type": application_type,
            "ena_category": ena_category,
            "ena_reference": "EREC G99 Issue 2 (March 2025)",
            "generated_by": "Princeps AI Platform",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "disclaimer": "Pre-filled from AI assessment. All fields must be verified by a qualified engineer before submission to the DNO.",
        },

        "section_1_applicant": {
            "applicant_name": "[Developer Name]",
            "company": "[Company Name]",
            "address": "[Registered Address]",
            "contact_email": "[email]",
            "contact_phone": "[phone]",
            "mpan": "[to be assigned]",
        },

        "section_2_site": {
            "site_name": site.get("name", ""),
            "site_address": site.get("address", site.get("name", "")),
            "postcode": site.get("postcode", ""),
            "grid_reference": _latlon_to_osgb(lat, lon),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "land_area_ha": site.get("area_ha"),
            "land_ownership": "[Freehold / Leasehold / Option]",
        },

        "section_3_generation": {
            "technology": tech.get("type", "Solar Photovoltaic"),
            "total_capacity_kw": capacity_kw,
            "total_capacity_mw": round(capacity_mw, 2),
            "number_of_units": tech.get("num_units", math.ceil(capacity_kw / 500)),
            "unit_capacity_kw": tech.get("unit_kw", min(500, capacity_kw)),
            "inverter_type": tech.get("inverter", "Grid-following"),
            "inverter_manufacturer": tech.get("inverter_make", "[To be specified]"),
            "phases": 3,
            "power_factor_range": "0.95 leading to 0.95 lagging",
            "reactive_power_capability": "Yes — 4-quadrant inverter",
            "fault_ride_through": "Compliant with EREC G99 Annex 1",
            "anti_islanding": "Rate of Change of Frequency (RoCoF) + Vector Shift",
            "estimated_annual_output_mwh": round(capacity_mw * 8760 * 0.11, 0),  # ~11% CF UK solar
            "commissioning_date": "[Target date]",
        },

        "section_4_connection": {
            "proposed_voltage_kv": recommended_voltage,
            "nearest_substation": grid.get("nearest_substation", ""),
            "distance_to_poc_km": grid.get("distance_km"),
            "grid_headroom_mw": grid.get("headroom_mw"),
            "estimated_fault_level_mva": round(fault_level_mva, 1),
            "connection_type": "New dedicated connection" if capacity_mw > 5 else "Existing supply modification",
            "metering": "Half-hourly export metering (HH CT/VT)",
            "protection_scheme": f"G99 compliant — over/under voltage, over/under frequency, RoCoF, neutral voltage displacement" if voltage_kv >= 33 else "G99 Stage 1 — loss of mains + O/U V/F",
            "earthing": "Solid earthing via dedicated earth electrode",
            "dno": grid.get("dno", site.get("dno", "[DNO licence area]")),
            "dno_ref": "[To be assigned by DNO]",
        },

        "section_5_costs": {
            "estimated_connection_cost_p10": grid.get("connection_cost", {}).get("p10_gbp"),
            "estimated_connection_cost_p50": grid.get("connection_cost", {}).get("p50_gbp"),
            "estimated_connection_cost_p90": grid.get("connection_cost", {}).get("p90_gbp"),
            "cost_basis": f"Princeps estimate: {grid.get('distance_km', 0):.1f}km at {recommended_voltage}kV",
            "uk_rates_per_km": {
                "11kV": "£80,000/km",
                "33kV": "£150,000/km",
                "132kV": "£500,000/km",
            },
        },

        "section_6_compliance": {
            "g99_threshold": "Yes" if capacity_kw > 50 else "No (G100 route)",
            "cdm_2015": "Principal Designer to be appointed",
            "bng_10pct": "Biodiversity Net Gain assessment required" if capacity_mw > 0.5 else "Below threshold",
            "eia_screening": "Required" if capacity_mw > 5 else "Below threshold",
            "nsip": "Yes — DCO route via Planning Inspectorate" if capacity_mw > 50 else "No — Local planning authority",
            "flood_zone": agent.get("domains", {}).get("flood_zones", {}).get("detail", "Check required"),
            "protected_areas": agent.get("domains", {}).get("protected_areas", {}).get("detail", "Check required"),
        },

        "section_7_verdict": {
            "princeps_verdict": agent.get("verdict", "—"),
            "confidence": f"{round((agent.get('confidence', 0)) * 100)}%",
            "summary": agent.get("summary", ""),
            "key_risks": agent.get("risks", []),
            "key_opportunities": agent.get("opportunities", []),
        },
    }

    # Generate HTML for PDF rendering
    html = _render_g99_html(form)

    return {
        "form_data": form,
        "html": html,
        "filename": f"princeps-g99-{_slug(site.get('name', 'site'))}.pdf",
    }


def _latlon_to_osgb(lat, lon):
    """Approximate WGS84 to OS Grid Reference (6-figure)."""
    # Simplified — real conversion uses Helmert transformation
    if not (49 < lat < 61 and -8 < lon < 2):
        return f"{lat:.4f}N, {abs(lon):.4f}{'W' if lon < 0 else 'E'}"
    # Very rough approximation for demo
    e = int((lon + 2) * 100000 + 400000)
    n = int((lat - 49) * 110000 + 100000)
    return f"TL {e % 100000:05d} {n % 100000:05d}"


def _slug(s):
    import re
    return re.sub(r"[^\w-]", "-", s or "site").strip("-")[:40]


def _render_g99_html(form):
    """Render G99 application pack as printable HTML."""
    meta = form["meta"]
    s1 = form["section_1_applicant"]
    s2 = form["section_2_site"]
    s3 = form["section_3_generation"]
    s4 = form["section_4_connection"]
    s5 = form["section_5_costs"]
    s6 = form["section_6_compliance"]
    s7 = form["section_7_verdict"]

    verdict_color = "#16a34a" if s7["princeps_verdict"] == "GO" else "#f59e0b" if s7["princeps_verdict"] == "CAUTION" else "#dc2626"

    rows = lambda d: "".join(f'<tr><td class="lbl">{k.replace("_", " ").title()}</td><td>{v if v is not None else "—"}</td></tr>' for k, v in d.items() if not isinstance(v, (dict, list)))

    risks_html = "".join(f'<li class="risk">{r}</li>' for r in s7.get("key_risks", []))
    opps_html = "".join(f'<li class="opp">{o}</li>' for o in s7.get("key_opportunities", []))

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; margin: 0; padding: 24px; color: #1f2937; font-size: 11px; }}
  h1 {{ color: #7c5cfc; font-size: 22px; margin: 0 0 4px; }}
  h2 {{ color: #374151; font-size: 14px; margin: 24px 0 8px; padding: 6px 10px; background: #f3f0ff; border-left: 3px solid #7c5cfc; }}
  .subtitle {{ color: #6b7280; font-size: 10px; }}
  .disclaimer {{ background: #fef3c7; padding: 8px 12px; border-radius: 6px; font-size: 9px; color: #92400e; margin: 12px 0; }}
  table {{ width: 100%; border-collapse: collapse; margin: 4px 0 12px; }}
  td {{ padding: 4px 8px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }}
  .lbl {{ font-weight: 600; width: 40%; color: #374151; }}
  .verdict {{ display: inline-block; padding: 4px 16px; border-radius: 4px; font-weight: 800; font-size: 18px; color: white; background: {verdict_color}; }}
  .risk {{ color: #dc2626; }}
  .opp {{ color: #16a34a; }}
  ul {{ padding-left: 16px; }}
  li {{ margin: 3px 0; }}
  .footer {{ margin-top: 24px; padding-top: 12px; border-top: 1px solid #e5e7eb; font-size: 9px; color: #9ca3af; }}
</style></head><body>
<h1>G99 Application Pack</h1>
<div class="subtitle">{meta['ena_reference']} &mdash; {meta['application_type']} Route (Category {meta['ena_category']})</div>
<div class="subtitle">Generated by {meta['generated_by']} on {meta['generated_at'][:10]}</div>
<div class="disclaimer">{meta['disclaimer']}</div>

<h2>1. Applicant Details</h2>
<table>{rows(s1)}</table>

<h2>2. Site Details</h2>
<table>{rows(s2)}</table>

<h2>3. Generating Plant</h2>
<table>{rows(s3)}</table>

<h2>4. Proposed Connection</h2>
<table>{rows(s4)}</table>

<h2>5. Connection Cost Estimate</h2>
<table>{rows(s5)}</table>

<h2>6. Regulatory Compliance</h2>
<table>{rows(s6)}</table>

<h2>7. AI Feasibility Verdict</h2>
<div style="margin: 8px 0;"><span class="verdict">{s7['princeps_verdict']}</span> <span style="margin-left:8px; color:#6b7280;">Confidence: {s7['confidence']}</span></div>
<p>{s7['summary']}</p>
{f'<h3 style="color:#dc2626;font-size:11px;">Key Risks</h3><ul>{risks_html}</ul>' if risks_html else ''}
{f'<h3 style="color:#16a34a;font-size:11px;">Key Opportunities</h3><ul>{opps_html}</ul>' if opps_html else ''}

<div class="footer">
  This document was auto-generated by Princeps and contains pre-filled G99 application data based on AI assessment.
  All values must be verified by a qualified electrical engineer before submission to the Distribution Network Operator.
  Princeps is not a substitute for professional engineering advice.
</div>
</body></html>"""
