"""
Market Intelligence Engine — generational capabilities.

Five capabilities no competitor can replicate:

1. Alert system (email/webhook for high-priority opportunities)
2. Auto-generate G99 grid connection applications
3. Land ownership lookup via Companies House API
4. Competitive heat map (where developers are concentrating)
5. Market timing engine (when to submit based on CfD/PPA cycles)

All functions designed to integrate with the Autonomous Prospector
and the Princeps financial modelling stack.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

log = logging.getLogger("princeps.market_intel")

COMPANIES_HOUSE_API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY", "")
COMPANIES_HOUSE_BASE = "https://api.company-information.service.gov.uk"
POSTCODES_IO_BASE = "https://api.postcodes.io"
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")

_HTTP_TIMEOUT = 15.0


# ═══════════════════════════════════════════════════════════════
#  1. ALERT SYSTEM — opportunity notifications
# ═══════════════════════════════════════════════════════════════

_ALERT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS alert_subscriptions (
    id              SERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    technology      TEXT DEFAULT 'any',
    min_mw          REAL DEFAULT 5,
    max_mw          REAL DEFAULT 500,
    regions         JSONB DEFAULT '[]'::jsonb,
    irr_hurdle      REAL DEFAULT 8.0,
    email           TEXT,
    webhook_url     TEXT,
    frequency       TEXT DEFAULT 'daily' CHECK (frequency IN ('daily', 'instant')),
    active          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_sent_at    TIMESTAMPTZ
);
"""


async def _ensure_alert_table(pool) -> None:
    """Create alert_subscriptions table if it doesn't exist."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(_ALERT_TABLE_SQL)
    except Exception as e:
        log.warning("Could not ensure alert table: %s", e)


async def create_alert_subscription(pool, user_id: str, config: dict) -> dict:
    """Subscribe to opportunity alerts.

    config: {
        technology, min_mw, max_mw, regions: [], irr_hurdle,
        email, webhook_url, frequency: "daily"|"instant"
    }
    """
    await _ensure_alert_table(pool)

    technology = config.get("technology", "any")
    min_mw = config.get("min_mw", 5)
    max_mw = config.get("max_mw", 500)
    regions = json.dumps(config.get("regions", []))
    irr_hurdle = config.get("irr_hurdle", 8.0)
    email = config.get("email")
    webhook_url = config.get("webhook_url")
    frequency = config.get("frequency", "daily")

    if not email and not webhook_url:
        return {"error": "At least one of email or webhook_url is required"}

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO alert_subscriptions
                (user_id, technology, min_mw, max_mw, regions,
                 irr_hurdle, email, webhook_url, frequency)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9)
            RETURNING id, created_at
        """, user_id, technology, min_mw, max_mw, regions,
            irr_hurdle, email, webhook_url, frequency)

    return {
        "subscription_id": row["id"],
        "created_at": row["created_at"].isoformat(),
        "status": "active",
        "frequency": frequency,
        "delivery": "email" if email else "webhook",
    }


async def check_and_send_alerts(pool) -> dict:
    """Run opportunity scan for each active subscriber and dispatch alerts.

    Called by the nightly refresh job or triggered manually.
    Returns {sent, skipped, errors}.
    """
    await _ensure_alert_table(pool)

    from utils.autonomous_prospector import run_full_scan

    sent = 0
    skipped = 0
    errors = 0

    async with pool.acquire() as conn:
        subs = await conn.fetch("""
            SELECT * FROM alert_subscriptions WHERE active = TRUE
        """)

    for sub in subs:
        try:
            prefs = {
                "technology": sub["technology"],
                "min_mw": sub["min_mw"],
                "max_mw": sub["max_mw"],
                "regions": json.loads(sub["regions"]) if isinstance(sub["regions"], str) else (sub["regions"] or []),
            }

            result = await run_full_scan(pool, prefs)
            high_priority = [
                o for o in result.get("opportunities", [])
                if o.get("priority") == "HIGH"
            ]

            if not high_priority:
                skipped += 1
                continue

            # Format and send
            html_body = await format_alert_email(high_priority[:5], dict(sub))

            if sub["email"]:
                ok = await _send_email_alert(sub["email"], html_body, len(high_priority))
                if ok:
                    sent += 1
                else:
                    errors += 1

            if sub["webhook_url"]:
                ok = await _send_webhook_alert(sub["webhook_url"], high_priority[:10])
                if ok:
                    sent += 1
                else:
                    errors += 1

            # Update last_sent_at
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE alert_subscriptions SET last_sent_at = now() WHERE id = $1",
                    sub["id"],
                )

        except Exception as e:
            log.warning("Alert dispatch failed for subscription %s: %s", sub["id"], e)
            errors += 1

    return {"sent": sent, "skipped": skipped, "errors": errors}


async def format_alert_email(opportunities: list[dict], subscriber: dict) -> str:
    """Generate HTML email body for opportunity alerts.

    Clean, professional, gold-accented branding.
    """
    rows_html = ""
    for i, opp in enumerate(opportunities[:5], 1):
        urgency_color = "#d4a017" if opp.get("priority") == "HIGH" else "#666"
        rows_html += f"""
        <tr style="border-bottom:1px solid #eee;">
            <td style="padding:12px 8px;font-weight:600;color:#1a1a1a;">{i}.</td>
            <td style="padding:12px 8px;">
                <strong style="color:#1a1a1a;">{opp.get('headline', 'Opportunity')}</strong><br/>
                <span style="color:#666;font-size:13px;">{opp.get('detail', '')[:120]}</span>
            </td>
            <td style="padding:12px 8px;text-align:center;">
                <span style="background:{urgency_color};color:#fff;padding:3px 10px;border-radius:12px;font-size:12px;">
                    {opp.get('priority', 'MEDIUM')}
                </span>
            </td>
            <td style="padding:12px 8px;text-align:right;font-weight:600;">
                {opp.get('capacity_mw') or opp.get('headroom_mw') or opp.get('released_mw', '—')} MW
            </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"/></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f5f0;">
<div style="max-width:600px;margin:0 auto;padding:20px;">
    <div style="background:#1a1a1a;padding:24px 32px;border-radius:8px 8px 0 0;">
        <h1 style="color:#d4a017;margin:0;font-size:22px;letter-spacing:1px;">PRINCEPS</h1>
        <p style="color:#999;margin:4px 0 0;font-size:13px;">Market Intelligence Alert</p>
    </div>
    <div style="background:#fff;padding:24px 32px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0;border-top:none;">
        <p style="color:#333;font-size:15px;line-height:1.6;">
            We've identified <strong>{len(opportunities)}</strong> high-priority
            {subscriber.get('technology', 'energy')} opportunities matching your criteria.
        </p>
        <table style="width:100%;border-collapse:collapse;margin:16px 0;">
            <thead>
                <tr style="border-bottom:2px solid #d4a017;">
                    <th style="padding:8px;text-align:left;color:#999;font-size:12px;width:30px;">#</th>
                    <th style="padding:8px;text-align:left;color:#999;font-size:12px;">OPPORTUNITY</th>
                    <th style="padding:8px;text-align:center;color:#999;font-size:12px;">PRIORITY</th>
                    <th style="padding:8px;text-align:right;color:#999;font-size:12px;">CAPACITY</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div style="text-align:center;margin:24px 0 8px;">
            <a href="https://app.princeps.energy/opportunities"
               style="background:#d4a017;color:#fff;padding:12px 32px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px;">
                View All in Princeps
            </a>
        </div>
        <p style="color:#999;font-size:12px;margin-top:24px;text-align:center;">
            You're receiving this because you subscribed to {subscriber.get('frequency', 'daily')} alerts.
            <a href="https://app.princeps.energy/settings/alerts" style="color:#d4a017;">Manage preferences</a>
        </p>
    </div>
</div>
</body></html>"""


async def _send_email_alert(email: str, html_body: str, count: int) -> bool:
    """Send alert email via SendGrid or Resend API."""
    subject = f"Princeps: {count} high-priority opportunities detected"

    # Try Resend first (simpler API)
    if RESEND_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                    json={
                        "from": "Princeps Alerts <alerts@princeps.energy>",
                        "to": [email],
                        "subject": subject,
                        "html": html_body,
                    },
                )
                return resp.status_code in (200, 201)
        except Exception as e:
            log.warning("Resend email failed: %s", e)

    # Fallback to SendGrid
    if SENDGRID_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={"Authorization": f"Bearer {SENDGRID_API_KEY}"},
                    json={
                        "personalizations": [{"to": [{"email": email}]}],
                        "from": {"email": "alerts@princeps.energy", "name": "Princeps Alerts"},
                        "subject": subject,
                        "content": [{"type": "text/html", "value": html_body}],
                    },
                )
                return resp.status_code in (200, 201, 202)
        except Exception as e:
            log.warning("SendGrid email failed: %s", e)

    log.warning("No email provider configured (set RESEND_API_KEY or SENDGRID_API_KEY)")
    return False


async def _send_webhook_alert(url: str, opportunities: list[dict]) -> bool:
    """POST opportunity data to a subscriber's webhook URL."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                url,
                json={
                    "source": "princeps",
                    "event": "opportunity_alert",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "opportunities": opportunities,
                    "count": len(opportunities),
                },
                headers={"Content-Type": "application/json", "User-Agent": "Princeps/1.0"},
            )
            return 200 <= resp.status_code < 300
    except Exception as e:
        log.warning("Webhook delivery failed to %s: %s", url, e)
        return False


# ═══════════════════════════════════════════════════════════════
#  2. AUTO-GENERATE G99 APPLICATION
# ═══════════════════════════════════════════════════════════════

def generate_g99_application(project: dict, grid_context: dict, site_context: dict) -> dict:
    """Pre-fill a G99/G100 grid connection application form.

    ENA Engineering Recommendation G99 (Issue 2, 2023) applies to all
    generating plant connecting to distribution networks. G100 applies
    to type-tested small-scale (<16A/phase) embedded generators.

    Thresholds:
      - <=3.68kW single-phase or <=11.04kW three-phase: G98 (notification only)
      - >3.68kW (1ph) / >11.04kW (3ph) up to 50kW: G99 Stage 1
      - >50kW: G99 full engineering study (Stage 2)

    Returns a dict with all ENA G99 form fields pre-filled from Princeps data.
    """
    capacity_kw = project.get("capacity_mw", 50) * 1000
    technology = project.get("technology", "solar").lower()
    lat = project.get("lat", 0)
    lon = project.get("lon", 0)

    # Determine connection voltage
    if capacity_kw <= 1000:
        voltage = "LV (400V)"
        phases = "Three Phase"
    elif capacity_kw <= 5000:
        voltage = "11kV"
        phases = "Three Phase"
    elif capacity_kw <= 50000:
        voltage = "33kV"
        phases = "Three Phase"
    else:
        voltage = grid_context.get("recommended_voltage", "132kV")
        phases = "Three Phase"

    # Estimate annual generation
    from utils.uk_energy_assumptions import capacity_factor as get_cf
    cf = get_cf(technology if technology != "bess" else "solar")
    annual_mwh = project.get("capacity_mw", 50) * cf * 8760

    # Determine form type
    if capacity_kw <= 50:
        form_type = "G99 Stage 1 — Simplified Application"
        ena_ref = "ENA EREC G99 Issue 2 2023, Annex A2.1"
    else:
        form_type = "G99 Stage 2 — Full Application"
        ena_ref = "ENA EREC G99 Issue 2 2023, Annex A2.2"

    # Build commissioning estimate (12-24 months from now depending on capacity)
    months_ahead = 12 if capacity_kw < 10000 else 18 if capacity_kw < 50000 else 24
    commissioning = (datetime.now(timezone.utc) + timedelta(days=months_ahead * 30)).strftime("%B %Y")

    # Connection cost estimate
    from utils.uk_energy_assumptions import GRID_CONNECTION_COSTS_GBP_KM
    distance_km = grid_context.get("nearest_substation_distance_km", 3.0)
    voltage_key = voltage.lower().replace(" ", "").replace("(400v)", "11kv").replace("kv", "kv")
    if voltage_key not in GRID_CONNECTION_COSTS_GBP_KM:
        voltage_key = "33kv"
    estimated_cost = distance_km * GRID_CONNECTION_COSTS_GBP_KM.get(voltage_key, 150_000)

    application = {
        "form_type": form_type,
        "ena_reference": ena_ref,

        # Section 1 — Applicant
        "applicant": {
            "company_name": project.get("developer", project.get("company_name", "")),
            "contact_name": project.get("contact_name", ""),
            "address": project.get("company_address", ""),
            "phone": project.get("phone", ""),
            "email": project.get("email", ""),
            "company_registration": project.get("company_number", ""),
        },

        # Section 2 — Site Details
        "site": {
            "name": project.get("name", site_context.get("site_name", "")),
            "address": site_context.get("address", ""),
            "postcode": site_context.get("postcode", ""),
            "grid_reference": _lat_lon_to_grid_ref(lat, lon),
            "lat": lat,
            "lon": lon,
            "mpan": project.get("mpan", "To be confirmed"),
            "land_area_ha": site_context.get("land_area_ha", project.get("land_area_ha")),
        },

        # Section 3 — Proposed Generation
        "generation": {
            "technology": _technology_label(technology),
            "capacity_kw": capacity_kw,
            "number_of_units": _estimate_units(technology, capacity_kw),
            "unit_rating_kw": round(capacity_kw / max(1, _estimate_units(technology, capacity_kw)), 1),
            "phases": phases,
            "power_factor": 0.95 if technology in ("solar", "bess") else 0.98,
            "inverter_type": "Four-quadrant" if technology in ("solar", "bess") else "N/A",
            "export_limiting_proposed": capacity_kw > 50000,
            "export_limit_kw": min(capacity_kw, grid_context.get("headroom_mw", 999) * 1000) if capacity_kw > 50000 else None,
            "expected_annual_generation_mwh": round(annual_mwh, 1),
            "expected_capacity_factor_pct": round(cf * 100, 1),
        },

        # Section 4 — Connection
        "connection": {
            "requested_voltage": voltage,
            "connection_type": "New" if not project.get("mpan") else "Existing — modification",
            "nearest_substation": grid_context.get("nearest_substation", ""),
            "estimated_distance_km": round(distance_km, 1),
            "estimated_connection_cost_gbp": round(estimated_cost),
            "metering_arrangement": "Half-hourly export metering",
        },

        # Section 5 — Commissioning
        "commissioning": {
            "estimated_date": commissioning,
            "construction_duration_months": months_ahead,
            "phased_connection": capacity_kw > 100000,
            "phases_description": f"Single phase — full {capacity_kw/1000:.0f} MW" if capacity_kw <= 100000 else f"Phased: {capacity_kw/2000:.0f} MW Phase 1, {capacity_kw/2000:.0f} MW Phase 2",
        },

        # Section 6 — Emergency Contact
        "emergency_contact": {
            "name": project.get("emergency_contact", project.get("contact_name", "")),
            "phone": project.get("emergency_phone", project.get("phone", "")),
            "available_24h": True,
        },

        # Section 7 — Additional Information
        "additional_information": _generate_additional_info(
            project, grid_context, site_context, technology, capacity_kw, annual_mwh,
        ),

        # Section 8 — Single-Line Diagram Description
        "single_line_diagram": _generate_sld_description(technology, capacity_kw, voltage),

        # Princeps metadata
        "_princeps": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "auto_filled": True,
            "data_sources": ["princeps_grid_assessment", "princeps_site_analysis", "uk_energy_assumptions"],
            "review_required": True,
            "note": "This application has been pre-filled by Princeps. All fields should be reviewed by a qualified engineer before submission to the DNO.",
        },
    }

    return application


def _technology_label(tech: str) -> str:
    labels = {
        "solar": "Photovoltaic (PV) — ground-mounted",
        "onshore_wind": "Wind turbine — onshore",
        "offshore_wind": "Wind turbine — offshore",
        "bess": "Battery Energy Storage System (BESS)",
        "wind": "Wind turbine — onshore",
        "hybrid": "Hybrid (Solar PV + BESS)",
    }
    return labels.get(tech, tech.title())


def _estimate_units(tech: str, capacity_kw: float) -> int:
    if tech == "solar":
        # ~600W panels, but G99 cares about inverter count
        # Typical string inverter: 100-250kW; central inverter: 1-4MW
        if capacity_kw <= 5000:
            return max(1, int(capacity_kw / 100))
        return max(1, int(capacity_kw / 3000))  # central inverters
    if tech in ("wind", "onshore_wind"):
        return max(1, int(capacity_kw / 4500))  # ~4.5MW turbines
    if tech == "bess":
        return max(1, int(capacity_kw / 2500))  # ~2.5MW containers
    return max(1, int(capacity_kw / 1000))


def _lat_lon_to_grid_ref(lat: float, lon: float) -> str:
    """Approximate OS grid reference from WGS84 (for form purposes only)."""
    # Rough conversion — not survey-grade, just for application pre-fill
    if not lat or not lon:
        return "To be confirmed"
    # Very simplified: real conversion needs full Helmert transformation
    return f"{lat:.5f}N, {abs(lon):.5f}{'W' if lon < 0 else 'E'} (OS grid ref to be confirmed)"


def _generate_additional_info(project, grid_ctx, site_ctx, tech, cap_kw, annual_mwh) -> str:
    """Generate the 'additional information' text for the G99 form."""
    cap_mw = cap_kw / 1000
    lines = [
        f"This application is for a {cap_mw:.1f} MW {_technology_label(tech).lower()} project.",
        f"Expected annual generation: {annual_mwh:,.0f} MWh ({annual_mwh/8760/cap_mw*100:.1f}% capacity factor).",
    ]
    if grid_ctx.get("headroom_mw"):
        lines.append(
            f"The nearest substation ({grid_ctx.get('nearest_substation', 'N/A')}) "
            f"has {grid_ctx['headroom_mw']:.0f} MW of available generation headroom."
        )
    if site_ctx.get("land_use"):
        lines.append(f"The site is classified as {site_ctx['land_use']} land.")
    if cap_kw > 50000:
        lines.append(
            "Export limiting may be proposed to match available network capacity. "
            "The applicant is willing to discuss flexible connection arrangements."
        )
    lines.append(
        "Full technical specifications, protection settings, and commissioning "
        "programme will be provided upon request. This application has been prepared "
        "using Princeps site assessment data."
    )
    return " ".join(lines)


def _generate_sld_description(tech: str, cap_kw: float, voltage: str) -> str:
    """Generate a textual single-line diagram description."""
    if tech == "solar":
        if cap_kw <= 5000:
            return (
                f"PV array -> String inverters -> LV switchboard -> "
                f"LV/LV isolation transformer -> DNO point of connection ({voltage}). "
                f"G99 compliant protection relay at point of connection."
            )
        return (
            f"PV array strings -> Central inverter stations -> "
            f"LV/MV step-up transformers (0.4/{voltage.replace('kV','').strip()}kV) -> "
            f"MV ring main unit -> DNO point of connection ({voltage}). "
            f"G99 compliant protection relay with loss-of-mains (RoCoF), "
            f"over/under voltage, over/under frequency."
        )
    if tech in ("wind", "onshore_wind"):
        return (
            f"Wind turbine generator -> Turbine transformer -> "
            f"MV collection network -> Substation transformer -> "
            f"DNO point of connection ({voltage}). "
            f"G99 protection: RoCoF, vector shift, V/F protection."
        )
    if tech == "bess":
        return (
            f"Battery modules -> Battery Management System -> "
            f"Four-quadrant inverter -> LV/MV transformer -> "
            f"DNO point of connection ({voltage}). "
            f"G99 protection with reverse power, RoCoF, V/F limits."
        )
    return f"Generation plant -> Transformer -> DNO point of connection ({voltage})."


def g99_to_pdf_html(application: dict) -> str:
    """Render the G99 application as HTML suitable for wkhtmltopdf or weasyprint.

    Formatted to match the official ENA G99 application form layout.
    """
    app = application.get("applicant", {})
    site = application.get("site", {})
    gen = application.get("generation", {})
    conn = application.get("connection", {})
    comm = application.get("commissioning", {})
    emrg = application.get("emergency_contact", {})

    def _row(label, value):
        v = value if value else "—"
        return f'<tr><td style="padding:6px 12px;font-weight:600;color:#555;width:40%;border:1px solid #ddd;">{label}</td><td style="padding:6px 12px;border:1px solid #ddd;">{v}</td></tr>'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 11pt; color: #333; margin: 40px; }}
  h1 {{ color: #1a1a1a; font-size: 18pt; border-bottom: 3px solid #d4a017; padding-bottom: 8px; }}
  h2 {{ color: #d4a017; font-size: 13pt; margin-top: 24px; border-bottom: 1px solid #eee; padding-bottom: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 8px 0 16px; }}
  .header {{ text-align: center; margin-bottom: 24px; }}
  .ref {{ color: #999; font-size: 9pt; }}
  .note {{ background: #fdf6e3; padding: 12px; border-left: 4px solid #d4a017; margin: 16px 0; font-size: 10pt; }}
</style>
</head>
<body>
<div class="header">
    <h1>Application for Connection of Generation — {application.get('form_type', 'G99')}</h1>
    <p class="ref">{application.get('ena_reference', '')}</p>
</div>

<h2>1. Applicant Details</h2>
<table>
    {_row("Company Name", app.get("company_name"))}
    {_row("Contact Name", app.get("contact_name"))}
    {_row("Address", app.get("address"))}
    {_row("Phone", app.get("phone"))}
    {_row("Email", app.get("email"))}
    {_row("Company Registration", app.get("company_registration"))}
</table>

<h2>2. Site Details</h2>
<table>
    {_row("Site Name", site.get("name"))}
    {_row("Address", site.get("address"))}
    {_row("Postcode", site.get("postcode"))}
    {_row("Grid Reference", site.get("grid_reference"))}
    {_row("MPAN", site.get("mpan"))}
    {_row("Site Area (ha)", site.get("land_area_ha"))}
</table>

<h2>3. Proposed Generation</h2>
<table>
    {_row("Technology", gen.get("technology"))}
    {_row("Total Capacity (kW)", f'{gen.get("capacity_kw", 0):,.0f}')}
    {_row("Number of Units", gen.get("number_of_units"))}
    {_row("Unit Rating (kW)", gen.get("unit_rating_kw"))}
    {_row("Phases", gen.get("phases"))}
    {_row("Power Factor", gen.get("power_factor"))}
    {_row("Inverter Type", gen.get("inverter_type"))}
    {_row("Export Limiting", "Yes" if gen.get("export_limiting_proposed") else "No")}
    {_row("Export Limit (kW)", f'{gen.get("export_limit_kw"):,.0f}' if gen.get("export_limit_kw") else "N/A")}
    {_row("Annual Generation (MWh)", f'{gen.get("expected_annual_generation_mwh", 0):,.0f}')}
    {_row("Capacity Factor", f'{gen.get("expected_capacity_factor_pct", 0):.1f}%')}
</table>

<h2>4. Connection Details</h2>
<table>
    {_row("Requested Voltage", conn.get("requested_voltage"))}
    {_row("Connection Type", conn.get("connection_type"))}
    {_row("Nearest Substation", conn.get("nearest_substation"))}
    {_row("Estimated Distance (km)", conn.get("estimated_distance_km"))}
    {_row("Metering", conn.get("metering_arrangement"))}
</table>

<h2>5. Commissioning</h2>
<table>
    {_row("Estimated Commissioning", comm.get("estimated_date"))}
    {_row("Construction Duration", f'{comm.get("construction_duration_months")} months')}
    {_row("Phased Connection", comm.get("phases_description"))}
</table>

<h2>6. Emergency Contact</h2>
<table>
    {_row("Name", emrg.get("name"))}
    {_row("Phone", emrg.get("phone"))}
    {_row("24h Availability", "Yes" if emrg.get("available_24h") else "No")}
</table>

<h2>7. Single-Line Diagram Description</h2>
<p>{application.get("single_line_diagram", "")}</p>

<h2>8. Additional Information</h2>
<p>{application.get("additional_information", "")}</p>

<div class="note">
    <strong>Note:</strong> This application was pre-filled by Princeps Market Intelligence.
    All fields should be reviewed by a qualified engineer before submission to the DNO.
    Generated: {application.get("_princeps", {}).get("generated_at", "")}
</div>
</body></html>"""


# ═══════════════════════════════════════════════════════════════
#  3. LAND OWNERSHIP LOOKUP
# ═══════════════════════════════════════════════════════════════

async def reverse_geocode(lat: float, lon: float) -> dict:
    """Reverse geocode coordinates to get postcode and address.

    Uses postcodes.io (free, no auth required).
    """
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{POSTCODES_IO_BASE}/postcodes",
                params={"lon": lon, "lat": lat},
            )
            if resp.status_code != 200:
                return {"postcode": None, "error": f"postcodes.io returned {resp.status_code}"}

            data = resp.json()
            if data.get("status") != 200 or not data.get("result"):
                return {"postcode": None, "error": "No postcode found for coordinates"}

            nearest = data["result"][0]
            return {
                "postcode": nearest.get("postcode"),
                "admin_district": nearest.get("admin_district"),
                "parish": nearest.get("parish"),
                "region": nearest.get("region"),
                "country": nearest.get("country"),
                "outcode": nearest.get("outcode"),
                "distance_m": nearest.get("distance"),
            }
    except Exception as e:
        log.warning("Reverse geocode failed: %s", e)
        return {"postcode": None, "error": str(e)}


# SIC codes relevant to land ownership and energy
_RELEVANT_SIC_CODES = {
    "agriculture": ["01"],       # Crop and animal production
    "forestry": ["02"],          # Forestry and logging
    "real_estate": ["68"],       # Real estate activities
    "energy": ["35"],            # Electricity, gas, steam
    "mining": ["06", "08", "09"],  # Extraction
    "land_management": ["81"],   # Services to buildings and landscape
}

_LANDOWNER_SIC_PREFIXES = ("01", "02", "68", "81")
_ENERGY_SIC_PREFIXES = ("35",)


async def lookup_land_ownership(lat: float, lon: float, radius_m: int = 500) -> dict:
    """Look up land ownership using Companies House API and reverse geocoding.

    Companies House API requires an API key via HTTP Basic Auth.
    If COMPANIES_HOUSE_API_KEY is not set, returns mock/indicative data.

    Strategy:
      1. Reverse geocode to get postcode
      2. Search Companies House for companies registered at that postcode
      3. Filter by relevant SIC codes (agriculture, real estate, energy)
    """
    geo = await reverse_geocode(lat, lon)
    postcode = geo.get("postcode")

    if not postcode:
        return {
            "nearby_companies": [],
            "probable_landowners": [],
            "energy_companies": [],
            "postcode": None,
            "geocode": geo,
            "data_source": "postcodes.io",
            "note": "Could not determine postcode for coordinates",
        }

    if not COMPANIES_HOUSE_API_KEY:
        return _mock_land_ownership(postcode, geo)

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            # Search by postcode (Companies House searches registered address text)
            resp = await client.get(
                f"{COMPANIES_HOUSE_BASE}/search/companies",
                params={"q": postcode, "items_per_page": 50},
                auth=(COMPANIES_HOUSE_API_KEY, ""),
            )

            if resp.status_code != 200:
                log.warning("Companies House API returned %s", resp.status_code)
                return _mock_land_ownership(postcode, geo)

            data = resp.json()
            items = data.get("items", [])

            nearby = []
            landowners = []
            energy_cos = []

            for item in items:
                company = {
                    "name": item.get("title", ""),
                    "number": item.get("company_number", ""),
                    "status": item.get("company_status", ""),
                    "address": item.get("address_snippet", ""),
                    "date_of_creation": item.get("date_of_creation"),
                    "sic_codes": item.get("sic_codes") or [],
                    "company_type": item.get("company_type", ""),
                }

                # Only include active companies
                if company["status"] not in ("active", "Active"):
                    continue

                nearby.append(company)

                # Check SIC codes for landowner relevance
                sics = company["sic_codes"]
                if any(
                    any(sic.startswith(prefix) for prefix in _LANDOWNER_SIC_PREFIXES)
                    for sic in sics
                ):
                    landowners.append(company)

                if any(
                    any(sic.startswith(prefix) for prefix in _ENERGY_SIC_PREFIXES)
                    for sic in sics
                ):
                    energy_cos.append(company)

            # If postcode search didn't yield much, also try the outcode
            if len(nearby) < 5 and geo.get("outcode"):
                resp2 = await client.get(
                    f"{COMPANIES_HOUSE_BASE}/search/companies",
                    params={"q": f"{geo['outcode']} farm", "items_per_page": 20},
                    auth=(COMPANIES_HOUSE_API_KEY, ""),
                )
                if resp2.status_code == 200:
                    for item in resp2.json().get("items", []):
                        if item.get("company_status") in ("active", "Active"):
                            co = {
                                "name": item.get("title", ""),
                                "number": item.get("company_number", ""),
                                "status": item.get("company_status", ""),
                                "address": item.get("address_snippet", ""),
                                "sic_codes": item.get("sic_codes") or [],
                            }
                            if co not in nearby:
                                nearby.append(co)
                                sics = co["sic_codes"]
                                if any(any(s.startswith(p) for p in _LANDOWNER_SIC_PREFIXES) for s in sics):
                                    landowners.append(co)

            return {
                "nearby_companies": nearby[:30],
                "probable_landowners": landowners[:15],
                "energy_companies": energy_cos[:10],
                "postcode": postcode,
                "geocode": geo,
                "total_results": data.get("total_results", len(nearby)),
                "data_source": "Companies House API",
            }

    except Exception as e:
        log.warning("Companies House lookup failed: %s", e)
        return _mock_land_ownership(postcode, geo)


def _mock_land_ownership(postcode: str, geo: dict) -> dict:
    """Return indicative data when Companies House API key is not configured."""
    return {
        "nearby_companies": [],
        "probable_landowners": [],
        "energy_companies": [],
        "postcode": postcode,
        "geocode": geo,
        "data_source": "mock (set COMPANIES_HOUSE_API_KEY for live data)",
        "note": (
            "Companies House API key not configured. In production, this "
            "would return companies registered near the site postcode, "
            "filtered by agricultural/real-estate SIC codes to identify "
            "probable landowners."
        ),
        "sic_code_reference": _RELEVANT_SIC_CODES,
    }


# ═══════════════════════════════════════════════════════════════
#  4. COMPETITIVE HEAT MAP
# ═══════════════════════════════════════════════════════════════

# UK bounding box for 10km grid (OSGB approximation in WGS84)
_UK_BBOX = {"min_lat": 49.9, "max_lat": 58.7, "min_lon": -6.5, "max_lon": 1.8}
_GRID_SIZE_DEG = 0.09  # ~10km at UK latitudes


async def competitive_heat_map(
    pool, technology: str = None, bbox: list = None,
) -> dict:
    """Generate a competitive density heat map from REPD data.

    For each ~10km grid cell, counts active projects and sums MW
    in pipeline to produce a competitive pressure score.

    Returns GeoJSON FeatureCollection.
    """
    if bbox and len(bbox) == 4:
        min_lon, min_lat, max_lon, max_lat = bbox
    else:
        min_lat = _UK_BBOX["min_lat"]
        max_lat = _UK_BBOX["max_lat"]
        min_lon = _UK_BBOX["min_lon"]
        max_lon = _UK_BBOX["max_lon"]

    tech_filter = ""
    params: list = [min_lat, max_lat, min_lon, max_lon]
    if technology:
        tech_filter = "AND LOWER(technology) LIKE $5"
        params.append(f"%{technology.lower()}%")

    try:
        async with pool.acquire() as conn:
            # Check if repd_projects table exists
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'repd_projects')"
            )
            if not exists:
                return _empty_heatmap("repd_projects table not found")

            query = f"""
                SELECT
                    FLOOR(lat / {_GRID_SIZE_DEG}) * {_GRID_SIZE_DEG} AS cell_lat,
                    FLOOR(lon / {_GRID_SIZE_DEG}) * {_GRID_SIZE_DEG} AS cell_lon,
                    COUNT(*) AS project_count,
                    COALESCE(SUM(capacity_mw), 0) AS total_mw,
                    COALESCE(AVG(capacity_mw), 0) AS avg_mw,
                    COUNT(DISTINCT COALESCE(developer, 'Unknown')) AS developer_count,
                    MODE() WITHIN GROUP (ORDER BY technology) AS dominant_tech
                FROM repd_projects
                WHERE lat BETWEEN $1 AND $2
                  AND lon BETWEEN $3 AND $4
                  AND status IN (
                      'Submitted', 'Awaiting Construction', 'Under Construction',
                      'Application Submitted', 'Appeal Lodged', 'Approved'
                  )
                  {tech_filter}
                GROUP BY cell_lat, cell_lon
                HAVING COUNT(*) >= 1
                ORDER BY project_count DESC
            """
            rows = await conn.fetch(query, *params)

            if not rows:
                return _empty_heatmap("No active projects in area")

            # Calculate pressure thresholds from distribution
            counts = [r["project_count"] for r in rows]
            p75 = sorted(counts)[int(len(counts) * 0.75)] if counts else 5
            p90 = sorted(counts)[int(len(counts) * 0.90)] if counts else 10

            features = []
            for r in rows:
                pc = r["project_count"]
                if pc >= p90:
                    pressure = "VERY_HIGH"
                elif pc >= p75:
                    pressure = "HIGH"
                elif pc >= max(2, p75 // 2):
                    pressure = "MEDIUM"
                else:
                    pressure = "LOW"

                cell_lat = float(r["cell_lat"])
                cell_lon = float(r["cell_lon"])

                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [cell_lon, cell_lat],
                            [cell_lon + _GRID_SIZE_DEG, cell_lat],
                            [cell_lon + _GRID_SIZE_DEG, cell_lat + _GRID_SIZE_DEG],
                            [cell_lon, cell_lat + _GRID_SIZE_DEG],
                            [cell_lon, cell_lat],
                        ]],
                    },
                    "properties": {
                        "project_count": pc,
                        "total_mw": round(float(r["total_mw"]), 1),
                        "avg_capacity_mw": round(float(r["avg_mw"]), 1),
                        "developer_count": r["developer_count"],
                        "dominant_technology": r["dominant_tech"],
                        "competitive_pressure": pressure,
                    },
                })

            total_projects = sum(r["project_count"] for r in rows)
            total_mw = sum(float(r["total_mw"]) for r in rows)

            return {
                "type": "FeatureCollection",
                "features": features,
                "summary": {
                    "cells": len(features),
                    "total_projects": total_projects,
                    "total_mw": round(total_mw, 1),
                    "very_high_cells": sum(1 for f in features if f["properties"]["competitive_pressure"] == "VERY_HIGH"),
                    "low_cells": sum(1 for f in features if f["properties"]["competitive_pressure"] == "LOW"),
                    "technology_filter": technology,
                },
            }

    except Exception as e:
        log.warning("Competitive heat map failed: %s", e)
        return _empty_heatmap(str(e))


def _empty_heatmap(reason: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [],
        "summary": {"cells": 0, "total_projects": 0, "total_mw": 0, "note": reason},
    }


# ═══════════════════════════════════════════════════════════════
#  5. MARKET TIMING ENGINE
# ═══════════════════════════════════════════════════════════════

# CfD Allocation Round schedule (known + projected)
_CFD_ROUNDS = {
    "AR6": {"window_open": "2024-03", "window_close": "2024-06", "results": "2024-09", "solar_strike_gbp_mwh": 47},
    "AR7": {"window_open": "2026-06", "window_close": "2026-09", "results": "2027-03", "solar_strike_gbp_mwh": 44},
    "AR8": {"window_open": "2027-06", "window_close": "2027-09", "results": "2028-03", "solar_strike_gbp_mwh": 42},
    "AR9": {"window_open": "2028-06", "window_close": "2028-09", "results": "2029-03", "solar_strike_gbp_mwh": 40},
}

# PPA forward curve seasonality (multiplier vs annual average)
_PPA_SEASONAL = {
    "Q1": 1.10,  # Winter — higher demand
    "Q2": 0.92,  # Spring — lower
    "Q3": 0.88,  # Summer — lowest (solar cannibalisation)
    "Q4": 1.12,  # Autumn/winter — highest
}

# PV module price index trend (relative to 2024 baseline)
_MODULE_PRICE_INDEX = {
    2024: 1.00,
    2025: 0.93,
    2026: 0.87,
    2027: 0.82,
    2028: 0.78,
    2029: 0.75,
    2030: 0.73,
}


def market_timing_analysis(
    capacity_mw: float, technology: str, region: str = "England",
) -> dict:
    """Advise on optimal timing for grid application, planning submission,
    PPA execution, and CfD bid based on UK market cycles.

    Factors: CfD rounds, PPA forward curve, grid queue reform (merit-based
    since 2024), planning seasonality, construction material trends.
    """
    now = datetime.now(timezone.utc)
    current_year = now.year
    current_quarter = f"Q{(now.month - 1) // 3 + 1}"

    # Determine next actionable CfD round
    next_cfd = None
    next_cfd_key = None
    for key, rd in _CFD_ROUNDS.items():
        open_date = datetime.strptime(rd["window_open"], "%Y-%m")
        if open_date > now.replace(tzinfo=None):
            next_cfd = rd
            next_cfd_key = key
            break

    # PPA pricing — find optimal quarter for execution
    from utils.uk_energy_assumptions import FINANCIAL_DEFAULTS
    base_ppa = FINANCIAL_DEFAULTS["ppa_price_gbp_mwh"]

    ppa_by_quarter = {}
    for q, mult in _PPA_SEASONAL.items():
        ppa_by_quarter[q] = round(base_ppa * mult, 1)
    best_ppa_quarter = max(ppa_by_quarter, key=ppa_by_quarter.get)

    # Module/CAPEX pricing trend
    module_factor_now = _MODULE_PRICE_INDEX.get(current_year, 1.0)
    module_factor_next = _MODULE_PRICE_INDEX.get(current_year + 1, module_factor_now * 0.95)
    capex_saving_pct = round((1 - module_factor_next / module_factor_now) * 100, 1)

    # Build recommended timeline
    # Logic: land -> grid app -> planning -> PPA -> CfD -> construction
    land_q = _next_quarter(now, 1)
    grid_q = _next_quarter(now, 2)
    # Planning: aim for Q1 or Q2 (LPAs faster, fewer holidays)
    planning_q = _next_q1_or_q2(now, after_months=4)
    # PPA: aim for Q4 (highest forward prices)
    ppa_q = _next_target_quarter(now, "Q4", after_months=12)
    # CfD: next available round
    cfd_q = f"{next_cfd_key} ({next_cfd['window_open']})" if next_cfd else "No round scheduled"
    # Construction: summer after securing revenue
    construction_q = _next_target_quarter(now, "Q2", after_months=18)
    # Energisation: 6-12 months after construction start
    energisation_months = 6 if capacity_mw < 50 else 12 if capacity_mw < 200 else 18
    energisation_q = _next_quarter(now, 24 + energisation_months // 3)

    # IRR sensitivity to timing
    from utils.uk_energy_assumptions import project_npv
    irr_now = project_npv(capacity_mw, technology, ppa_price=base_ppa)
    irr_6m = project_npv(
        capacity_mw, technology,
        ppa_price=base_ppa * _PPA_SEASONAL.get(best_ppa_quarter, 1.0),
    )
    # 12 months: lower CAPEX but PPA may normalise
    irr_12m = project_npv(capacity_mw, technology, ppa_price=base_ppa * 1.02)

    # Market signals
    signals = []
    if _PPA_SEASONAL.get(current_quarter, 1.0) >= 1.05:
        signals.append({
            "signal": "PPA forward prices elevated",
            "impact": "positive",
            "detail": f"Current quarter ({current_quarter}) has historically {int((_PPA_SEASONAL[current_quarter]-1)*100)}% higher baseload prices. Consider locking in PPA now.",
        })
    elif _PPA_SEASONAL.get(current_quarter, 1.0) < 0.95:
        signals.append({
            "signal": "PPA forward prices depressed",
            "impact": "negative",
            "detail": f"Current quarter ({current_quarter}) has historically lower prices. Wait for {best_ppa_quarter} to execute PPA ({ppa_by_quarter[best_ppa_quarter]} vs {ppa_by_quarter[current_quarter]} GBP/MWh).",
        })

    if next_cfd:
        strike = next_cfd.get("solar_strike_gbp_mwh", 45)
        signals.append({
            "signal": f"CfD {next_cfd_key} strike price forecast",
            "impact": "negative" if strike < base_ppa else "positive",
            "detail": f"Expected {technology} strike price {strike} GBP/MWh in {next_cfd_key}. {'Below current PPA rates — PPA may be preferable.' if strike < base_ppa else 'Competitive with PPA — CfD worth pursuing.'}",
        })

    if capex_saving_pct > 3:
        signals.append({
            "signal": "CAPEX costs declining",
            "impact": "positive",
            "detail": f"PV module prices expected to fall ~{capex_saving_pct}% by {current_year + 1}. Delaying construction 12 months saves ~{round(capacity_mw * 1000 * 450 * capex_saving_pct / 100 / 1e6, 1)}M GBP on a {capacity_mw} MW project.",
        })

    signals.append({
        "signal": "Grid queue merit-based reform",
        "impact": "positive" if capacity_mw > 20 else "neutral",
        "detail": "Since 2024, grid queue is merit-based. Projects with planning consent + secured land score higher. Submit grid application AFTER securing land option.",
    })

    if region in ("Scotland", "North England"):
        signals.append({
            "signal": f"Transmission constraints in {region}",
            "impact": "negative",
            "detail": f"Significant curtailment risk in {region} (~5-15% for wind, ~2-5% for solar). Factor curtailment into revenue model. Consider BESS co-location.",
        })

    return {
        "recommended_timeline": {
            "land_option": {
                "when": land_q,
                "reason": "Before grid application — strengthens queue position under merit-based system",
            },
            "grid_application": {
                "when": grid_q,
                "reason": "After land secured, before planning submission to demonstrate commitment to DNO",
            },
            "planning_submission": {
                "when": planning_q,
                "reason": "Q1/Q2 determination is historically 15-20% faster than Q3/Q4 (fewer LPA holidays)",
            },
            "ppa_execution": {
                "when": ppa_q,
                "reason": f"{best_ppa_quarter} forward prices historically {int((_PPA_SEASONAL[best_ppa_quarter]-1)*100)}% above annual average",
            },
            "cfd_bid": {
                "when": cfd_q,
                "reason": f"Project should have planning consent by then. Strike price forecast: {next_cfd.get('solar_strike_gbp_mwh', 'TBC')} GBP/MWh" if next_cfd else "No CfD round currently scheduled in window",
            },
            "construction_start": {
                "when": construction_q,
                "reason": "Post-revenue-certainty (CfD/PPA), summer construction season for optimal progress",
            },
            "energisation": {
                "when": energisation_q,
                "reason": f"~{energisation_months} months construction for {capacity_mw} MW {technology}",
            },
        },
        "irr_sensitivity": {
            "submit_now": {
                "irr_pct": irr_now["irr_pct"],
                "ppa_price_gbp_mwh": base_ppa,
            },
            "wait_6_months": {
                "irr_pct": irr_6m["irr_pct"],
                "ppa_price_gbp_mwh": round(base_ppa * _PPA_SEASONAL.get(best_ppa_quarter, 1.0), 1),
            },
            "wait_12_months": {
                "irr_pct": irr_12m["irr_pct"],
                "ppa_price_gbp_mwh": round(base_ppa * 1.02, 1),
            },
        },
        "market_signals": signals,
        "ppa_seasonal_prices": ppa_by_quarter,
        "module_price_trend": {str(y): round(v, 3) for y, v in _MODULE_PRICE_INDEX.items()},
        "cfd_rounds": {k: v for k, v in _CFD_ROUNDS.items()},
        "analysis_date": now.isoformat(),
        "capacity_mw": capacity_mw,
        "technology": technology,
        "region": region,
    }


def _next_quarter(dt: datetime, months_ahead: int) -> str:
    """Return 'QN YYYY' that is approximately months_ahead from dt."""
    future = dt + timedelta(days=months_ahead * 30)
    q = (future.month - 1) // 3 + 1
    return f"Q{q} {future.year}"


def _next_q1_or_q2(dt: datetime, after_months: int = 3) -> str:
    """Return the next Q1 or Q2 that is at least after_months away."""
    future = dt + timedelta(days=after_months * 30)
    year = future.year
    month = future.month
    if month <= 6:
        # Already in Q1 or Q2
        q = 1 if month <= 3 else 2
        return f"Q{q} {year}"
    # Next year Q1
    return f"Q1 {year + 1}"


def _next_target_quarter(dt: datetime, target_q: str, after_months: int = 6) -> str:
    """Return the next occurrence of target_q (e.g. 'Q4') at least after_months away."""
    future = dt + timedelta(days=after_months * 30)
    q_num = int(target_q[1])
    target_month = (q_num - 1) * 3 + 1
    year = future.year
    if future.month > target_month:
        year += 1
    return f"{target_q} {year}"
