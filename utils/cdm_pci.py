"""
CDM Pre-Construction Information (PCI) skeleton generator.

Under the Construction (Design and Management) Regulations 2015
(SI 2015/51), Regulation 4 requires the client to provide Pre-Construction
Information (PCI) to every designer and contractor as soon as is
practicable before appointment. The content is prescribed by Schedule 2
and expanded in HSE L153 (ACoP) — "Managing health and safety in
construction".

This module produces a structured PCI skeleton in the Schedule 2 order:

  Section 1  Project information
  Section 2  Client considerations and management requirements
  Section 3  Environment and existing site hazards
              (survey summaries — pulled from Princeps data if available)
  Section 4  Existing structures / services and demolition hazards
  Section 5  Significant design and construction hazards
  Section 6  Health and safety file — coordination and arrangements
  Section 7  Planning timeline (milestones + PD/PC appointment windows)

The CDM F10 Notification (HSE form at hse.gov.uk/forms/notification/f10.htm)
is NOT the PCI — F10 is the notification under Regulation 6. The two
documents live side-by-side in the construction/DD pack.

Return shape matches the rest of utils/document_automation.py generators:
    {form_data: dict, html: str, document_type: str, auto_fill_pct: int}

Usage (module):
    from utils.cdm_pci import generate_pci
    pack = generate_pci(site={...}, capacity_mw=50, technology="solar",
                        environmental={...}, timeline={...})
    html_string = pack["html"]

Usage (subprocess / stdio):
    echo '{"site":{"name":"Demo"},"capacity_mw":50}' |
        python utils/cdm_pci.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PLACEHOLDER_MARKERS = ("[", "tbc", "tbd", "to be", "—", "n/a")


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _count_filled(d: Any) -> tuple[int, int]:
    """Count (filled, total) leaf fields, treating [placeholder] strings as unfilled."""
    filled = 0
    total = 0
    if isinstance(d, dict):
        for v in d.values():
            f, t = _count_filled(v)
            filled += f
            total += t
    elif isinstance(d, list):
        total += 1
        if d:
            filled += 1
    else:
        total += 1
        s = str(d).strip().lower() if d is not None else ""
        if s and not any(m in s for m in _PLACEHOLDER_MARKERS):
            filled += 1
    return filled, total


def _pct(filled: int, total: int) -> int:
    return round(filled / total * 100) if total > 0 else 0


# ---------------------------------------------------------------------------
# Hazard + risk libraries (ground-truth defaults; overridden by inputs)
# ---------------------------------------------------------------------------

_TECH_DESIGN_HAZARDS: dict[str, list[dict[str, str]]] = {
    "solar": [
        {
            "hazard": "Working at height (panel mounting, tracker install)",
            "control": "MEWP or fixed scaffold; FASET-trained crew; edge protection on any elevated platform",
            "reg_ref": "WAH Regs 2005 Reg 6; HSE GS6",
        },
        {
            "hazard": "DC arc flash on energised strings",
            "control": "Lock-out/tag-out before work; only qualified persons; PV isolators rated per BS EN 62446",
            "reg_ref": "Electricity at Work Regs 1989 Reg 14",
        },
        {
            "hazard": "Manual handling of 25-30 kg modules",
            "control": "Two-person lift; vacuum lifters on large-format modules; rotate crew",
            "reg_ref": "Manual Handling Ops Regs 1992",
        },
        {
            "hazard": "HV commissioning at inverter / substation transformer",
            "control": "SAP/SCP appointed; permit-to-work; arc-rated PPE; dead-testing before live work",
            "reg_ref": "EAWR 1989 Reg 4; HSE HSR25",
        },
    ],
    "bess": [
        {
            "hazard": "Thermal runaway / cell fire in battery container",
            "control": "NFCC fire strategy; 6 m separation between containers; gas venting design; sprinkler per FM Global",
            "reg_ref": "Regulatory Reform (Fire Safety) Order 2005; NFCC guidance 2023",
        },
        {
            "hazard": "HV arc flash at PCS and 33 kV transformer",
            "control": "Arc-rated PPE (ATPV 40 cal/cm² minimum); safe approach distances per ENA TS 41-24",
            "reg_ref": "EAWR 1989 Reg 14; ENA TS 41-24",
        },
        {
            "hazard": "Toxic gas release during battery failure (HF, CO)",
            "control": "H2/CO/HF detection with SCADA interlock; SCBA for entry post-event",
            "reg_ref": "COSHH 2002; DSEAR 2002",
        },
        {
            "hazard": "Heavy lift (container placement, transformer drop)",
            "control": "Appointed Person lift plan; CPA Red Book; 360° exclusion zone",
            "reg_ref": "LOLER 1998; BS 7121",
        },
    ],
    "wind": [
        {
            "hazard": "Work at height on turbine nacelle / tower",
            "control": "Fall-arrest system; rope rescue team on site; RUK WindSafe competence",
            "reg_ref": "WAH Regs 2005; RenewableUK WindSafe",
        },
        {
            "hazard": "Blade / nacelle tandem lift",
            "control": "Appointed Person; CPA Red Book; wind-speed stop criteria",
            "reg_ref": "LOLER 1998 Reg 8",
        },
    ],
    "dc": [
        {
            "hazard": "Live HV switchgear commissioning (11 kV / 33 kV)",
            "control": "SAP/SCP with documented authorisations; two-person rule; LOTO",
            "reg_ref": "EAWR 1989 Reg 14",
        },
        {
            "hazard": "Refrigerant gas handling (chillers, CDUs)",
            "control": "F-Gas Regulated engineer; leak detection; evacuation plan",
            "reg_ref": "F-Gas Regs (EU) 517/2014 as retained",
        },
        {
            "hazard": "Confined space in plenum / cable pits",
            "control": "Permit-to-work; gas test; top-man standby; rescue plan",
            "reg_ref": "Confined Spaces Regs 1997",
        },
    ],
}


_COMMON_EXISTING_HAZARDS: list[dict[str, str]] = [
    {
        "hazard": "Ground contamination (legacy agrochemical / fuel)",
        "action": "Phase 1 desk study — extend to Phase 2 intrusive if trigger concentrations breach LQM/CIEH S4UL",
        "evidence_ref": "[Phase 1 contamination report]",
    },
    {
        "hazard": "Buried services (HV cable, gas, water, telecoms)",
        "action": "LSBUD enquiry; CAT & genny survey before any excavation; HSG47 compliance",
        "evidence_ref": "[LSBUD enquiry reference]",
    },
    {
        "hazard": "Overhead lines crossing or adjacent",
        "action": "HSE GS6 exclusion zones; goalpost system for vehicle crossing; DNO liaison",
        "evidence_ref": "[OHL survey / DNO letter]",
    },
    {
        "hazard": "Ecology — protected species (badger, bat, nesting birds)",
        "action": "Ecologist walk-over; species-specific survey in-season; EPS mitigation licence if needed",
        "evidence_ref": "[Preliminary Ecological Appraisal]",
    },
    {
        "hazard": "Unexploded ordnance (UXO) risk",
        "action": "Desk-based UXO risk assessment; intrusive UXO survey if site is in elevated-risk area",
        "evidence_ref": "[UXO desk study]",
    },
    {
        "hazard": "Public access / footpaths / bridleways",
        "action": "Diversion order under Highways Act s.119; Heras fencing; signage; traffic management plan",
        "evidence_ref": "[Public Rights of Way plan]",
    },
]


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_pci(
    site: dict | None = None,
    capacity_mw: float = 0.0,
    technology: str = "solar",
    environmental: dict | None = None,
    timeline: dict | None = None,
    client: dict | None = None,
) -> dict:
    """Generate a Pre-Construction Information (PCI) skeleton.

    Args:
        site: {name, address, postcode, lat, lon, area_ha, local_authority}
        capacity_mw: installed capacity (used to scale workforce / coordination).
        technology: solar | bess | wind | dc (drives design-hazard library).
        environmental: {phase1_contamination, ecology, flood_zone, ground_conditions}
                       — free-form dict; individual keys mapped into Section 3.
        timeline: {start_date, end_date, duration_months, max_workers,
                   pd_appointment_date, pc_appointment_date}
        client: {name, address, contact, phone, email}

    Returns:
        {form_data, html, document_type, auto_fill_pct}
    """
    site = site or {}
    environmental = environmental or {}
    timeline = timeline or {}
    client = client or {}
    tech_key = technology.lower() if technology else "solar"

    # Build Section 3 — environment & existing hazards. Merge in anything
    # Princeps already knows from environmental scans / surveys.
    existing_hazards: list[dict[str, str]] = []
    for h in _COMMON_EXISTING_HAZARDS:
        h = dict(h)  # shallow copy so we don't mutate the module-level list
        key_map = {
            "Ground contamination": "phase1_contamination",
            "Buried services": "buried_services",
            "Overhead lines": "overhead_lines",
            "Ecology": "ecology",
            "Unexploded ordnance": "uxo",
            "Public access": "public_rights_of_way",
        }
        for label, env_key in key_map.items():
            if h["hazard"].startswith(label) and env_key in environmental:
                h["evidence_ref"] = str(environmental[env_key])
        existing_hazards.append(h)

    # Gap list — transparently flag which surveys are still missing.
    survey_gaps = [
        key for key, label in [
            ("phase1_contamination", "Phase 1 contamination desk study"),
            ("ecology", "Preliminary ecological appraisal"),
            ("flood_zone", "Flood Risk Assessment"),
            ("ground_conditions", "Ground investigation / GI report"),
        ]
        if key not in environmental
    ]

    design_hazards = _TECH_DESIGN_HAZARDS.get(tech_key, _TECH_DESIGN_HAZARDS["solar"])

    # Significant-risk register — top hazards requiring designer/contractor
    # attention (CDM Reg 9(3), Reg 11 coordination).
    significant_risks = [
        {
            "risk": "Electrical safety during commissioning",
            "severity": "High",
            "likelihood": "Medium",
            "residual": "Medium",
            "owner": "Principal Contractor + SAP",
        },
        {
            "risk": "Working at height",
            "severity": "High",
            "likelihood": "Medium" if tech_key == "solar" else "Low",
            "residual": "Low",
            "owner": "Principal Contractor",
        },
        {
            "risk": "Heavy lifts (transformer, container, nacelle)",
            "severity": "High",
            "likelihood": "Low",
            "residual": "Low",
            "owner": "Appointed Person (LOLER)",
        },
        {
            "risk": "Site traffic — plant/pedestrian interface",
            "severity": "Medium",
            "likelihood": "Medium",
            "residual": "Low",
            "owner": "Principal Contractor + Traffic Marshal",
        },
    ]
    if tech_key == "bess":
        significant_risks.insert(0, {
            "risk": "Lithium-ion thermal runaway / fire",
            "severity": "High",
            "likelihood": "Low",
            "residual": "Medium",
            "owner": "Principal Designer + NFCC liaison",
        })

    # Planning timeline — working backwards from construction start
    start_date = timeline.get("start_date") or "[Start date]"
    end_date = timeline.get("end_date") or "[End date]"
    duration_months = timeline.get("duration_months")
    if duration_months is None:
        # Scale with capacity — solar baseline, 3 months + 0.12 mo/MW, capped
        duration_months = round(3 + 0.12 * max(1.0, capacity_mw))
        duration_months = min(max(duration_months, 3), 36)

    planning_timeline = [
        {"milestone": "PCI issued to PD + all designers", "target": "T-16 weeks", "responsible": "Client"},
        {"milestone": "Principal Designer appointed (Reg 5)", "target": timeline.get("pd_appointment_date", "T-14 weeks"), "responsible": "Client"},
        {"milestone": "Principal Contractor appointed (Reg 5)", "target": timeline.get("pc_appointment_date", "T-10 weeks"), "responsible": "Client"},
        {"milestone": "Construction Phase Plan drafted (Reg 12)", "target": "T-6 weeks", "responsible": "Principal Contractor"},
        {"milestone": "F10 notification submitted to HSE (Reg 6)", "target": "T-4 weeks", "responsible": "Client / PD"},
        {"milestone": "Construction start (mobilisation)", "target": start_date, "responsible": "Principal Contractor"},
        {"milestone": "Practical completion + H&S file handover (Reg 12(8))", "target": end_date, "responsible": "Principal Designer"},
    ]

    form = {
        "meta": {
            "document_type": "CDM Pre-Construction Information (PCI)",
            "legislation": "Construction (Design and Management) Regulations 2015 (SI 2015/51)",
            "regulation": "Regulation 4 (client duties) and Schedule 2 (PCI content)",
            "acop_reference": "HSE L153 — Managing health and safety in construction",
            "generated_by": "Princeps AI Platform",
            "generated_at": _now_iso(),
            "disclaimer": (
                "Skeleton PCI auto-populated from Princeps project data. Must be "
                "reviewed and completed by the Client (or the Principal Designer "
                "on the Client's behalf) before appointment of designers and "
                "contractors. Cite F10 notification separately under Reg 6."
            ),
        },

        # Section 1 — Project information (Schedule 2 (1))
        "section_1_project": {
            "project_title": f"{site.get('name', 'Site')} — {capacity_mw:.1f} MW {tech_key.upper()}",
            "site_address": site.get("address") or site.get("name") or "[Site address]",
            "postcode": site.get("postcode", "[Postcode]"),
            "local_authority": site.get("local_authority", "[Local Planning Authority]"),
            "latitude": site.get("lat", "[Lat]"),
            "longitude": site.get("lon", "[Lon]"),
            "area_ha": site.get("area_ha", "[Site area ha]"),
            "client_name": client.get("name", "[Client Name]"),
            "client_address": client.get("address", "[Client Address]"),
            "client_contact": client.get("contact", "[Client contact]"),
            "client_phone": client.get("phone", "[Phone]"),
            "client_email": client.get("email", "[Email]"),
            "construction_start": start_date,
            "construction_end": end_date,
            "duration_months": duration_months,
        },

        # Section 2 — Client considerations & management requirements (Sch 2 (2))
        "section_2_management": {
            "h_and_s_goals": "Zero RIDDOR events; AFR < 1.0 per 100k hours worked.",
            "site_rules_summary": "Induction mandatory; PPE to site standard; permits-to-work for hot/HV/confined space.",
            "welfare_arrangements": "Compliant with Sch 2 of CDM 2015 — WC, washing, drying, rest, drinking water, changing facilities before workers arrive on site.",
            "site_access_strategy": "Single controlled entry with signing-in; separate plant / pedestrian routes; speed limit 10 mph within compound.",
            "emergency_procedures": "Muster point to be identified; emergency contacts posted in compound; NHS-qualified first aider on site each shift.",
            "information_exchange": "Weekly PD/PC coordination; monthly client progress; BIM-lite document exchange via project portal.",
        },

        # Section 3 — Environment & existing site hazards (Sch 2 (3)(a))
        "section_3_existing_hazards": {
            "hazards": existing_hazards,
            "survey_gaps_identified": survey_gaps,
            "note": (
                "Evidence references marked in square brackets are gaps — the Client "
                "must commission these surveys before the PD/PC can rely on the PCI."
            ) if survey_gaps else "All listed surveys available in project data room.",
        },

        # Section 4 — Existing structures / demolition hazards (Sch 2 (3)(b))
        "section_4_existing_structures": {
            "demolition_required": environmental.get("demolition_required", "None — greenfield or brownfield with no structures"),
            "asbestos_survey": environmental.get("asbestos_survey", "Pre-demolition R&D survey required if any existing structure to be removed (Reg 5, Control of Asbestos Regs 2012)"),
            "structural_survey": environmental.get("structural_survey", "[Structural survey report reference]"),
            "temporary_works": "Propping / sheet piling for any deep excavation >1.2 m (BS 5975 TWC).",
        },

        # Section 5 — Significant design & construction hazards (Sch 2 (3)(c))
        "section_5_significant_risks": {
            "design_hazards": design_hazards,
            "significant_risk_register": significant_risks,
            "design_principle": "Apply General Principles of Prevention (CDM 2015 Sch 1) — avoid, evaluate, combat at source, adapt to worker, substitute, collective over individual.",
        },

        # Section 6 — Health and safety file & coordination (Sch 2 (4))
        "section_6_coordination": {
            "h_and_s_file_location": "Held by PD during design; handed to Client at practical completion (Reg 12(8)).",
            "coordination_meetings": "Weekly PD/PC coordination; fortnightly designer risk reviews during design stage.",
            "designer_interfaces": "Civil / electrical / grid-connection designers coordinated via PD; shared design risk register.",
            "subcontractor_management": "PC to pre-qualify all subcontractors (SSIP equivalent); competence evidence filed.",
            "handover_deliverables": "As-built drawings, O&M manuals, residual risk register, PAT / commissioning certificates, structural certificates.",
        },

        # Section 7 — Planning timeline
        "section_7_planning_timeline": {
            "milestones": planning_timeline,
            "notes": "T = construction start. All lead times indicative; flex for DNO energisation date.",
        },
    }

    filled, total = _count_filled(form)
    pct = _pct(filled, total)

    return {
        "form_data": form,
        "html": render_pci_html(form),
        "markdown": render_pci_markdown(form),
        "document_type": "cdm_pci",
        "auto_fill_pct": pct,
    }


# ---------------------------------------------------------------------------
# HTML render — reuses the Princeps document chrome style
# ---------------------------------------------------------------------------

_STYLE = """
body { font-family: 'DM Sans', 'Segoe UI', system-ui, sans-serif; margin: 0;
       padding: 28px; color: #1f2937; font-size: 11px; line-height: 1.5; }
h1 { color: #F5B731; font-size: 22px; margin: 0 0 4px; }
h2 { color: #374151; font-size: 14px; margin: 22px 0 6px;
     padding: 6px 10px; background: #FFF8E6; border-left: 3px solid #F5B731; }
h3 { font-size: 12px; color: #4b5563; margin: 12px 0 4px; }
.subtitle { color: #6b7280; font-size: 10px; }
.disclaimer { background: #fef3c7; padding: 8px 12px; border-radius: 6px;
              font-size: 9px; color: #92400e; margin: 10px 0; }
table { width: 100%; border-collapse: collapse; margin: 4px 0 10px;
        font-size: 10px; }
th, td { padding: 4px 8px; border-bottom: 1px solid #e5e7eb;
         vertical-align: top; text-align: left; }
th { background: #f9fafb; font-weight: 600; color: #374151; }
.lbl { font-weight: 600; width: 38%; color: #374151; }
.gap { color: #b45309; background: #fef3c7; padding: 1px 6px;
       border-radius: 3px; font-size: 9px; font-weight: 600; }
.footer { margin-top: 24px; padding-top: 10px;
          border-top: 1px solid #e5e7eb; font-size: 9px; color: #9ca3af; }
"""


def _kv_table(d: dict) -> str:
    rows = []
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            continue
        rows.append(
            f'<tr><td class="lbl">{k.replace("_", " ").title()}</td><td>{v}</td></tr>'
        )
    return "<table>" + "".join(rows) + "</table>"


def _hazard_table(hazards: list[dict]) -> str:
    if not hazards:
        return "<p><em>None identified.</em></p>"
    header = "<tr>" + "".join(f"<th>{k.replace('_',' ').title()}</th>"
                              for k in hazards[0].keys()) + "</tr>"
    body = "".join(
        "<tr>" + "".join(f"<td>{v}</td>" for v in h.values()) + "</tr>"
        for h in hazards
    )
    return f"<table>{header}{body}</table>"


def _timeline_table(items: list[dict]) -> str:
    if not items:
        return "<p><em>Timeline pending.</em></p>"
    rows = "".join(
        f"<tr><td>{i['milestone']}</td><td>{i['target']}</td><td>{i['responsible']}</td></tr>"
        for i in items
    )
    return (
        "<table><tr><th>Milestone</th><th>Target</th><th>Responsible</th></tr>"
        + rows + "</table>"
    )


def render_pci_html(form: dict) -> str:
    meta = form["meta"]
    s3 = form["section_3_existing_hazards"]
    s5 = form["section_5_significant_risks"]
    s7 = form["section_7_planning_timeline"]

    gap_html = ""
    if s3.get("survey_gaps_identified"):
        gaps = ", ".join(s3["survey_gaps_identified"])
        gap_html = (
            f'<p><span class="gap">GAPS</span> '
            f'Outstanding surveys: {gaps}.</p>'
        )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>CDM PCI — {form['section_1_project'].get('project_title', 'Project')}</title>
<style>{_STYLE}</style></head><body>

<h1>CDM Pre-Construction Information</h1>
<div class="subtitle">{meta['legislation']}</div>
<div class="subtitle">{meta['regulation']}</div>
<div class="subtitle">{meta['acop_reference']}</div>
<div class="subtitle">Generated by {meta['generated_by']} on {meta['generated_at'][:10]}</div>
<div class="disclaimer">{meta['disclaimer']}</div>

<h2>1. Project information</h2>
{_kv_table(form['section_1_project'])}

<h2>2. Client considerations &amp; management requirements</h2>
{_kv_table(form['section_2_management'])}

<h2>3. Environment &amp; existing site hazards</h2>
{_hazard_table(s3['hazards'])}
{gap_html}

<h2>4. Existing structures &amp; demolition hazards</h2>
{_kv_table(form['section_4_existing_structures'])}

<h2>5. Significant design &amp; construction hazards</h2>
<h3>Design hazards</h3>
{_hazard_table(s5['design_hazards'])}
<h3>Significant risk register</h3>
{_hazard_table(s5['significant_risk_register'])}
<p><em>{s5['design_principle']}</em></p>

<h2>6. Health &amp; safety file and coordination arrangements</h2>
{_kv_table(form['section_6_coordination'])}

<h2>7. Planning timeline</h2>
{_timeline_table(s7['milestones'])}
<p class="subtitle">{s7['notes']}</p>

<div class="footer">
  Generated by Princeps · {meta['generated_at'][:10]} ·
  References: CDM Regulations 2015 (SI 2015/51) · HSE L153 ACoP ·
  F10 notification (separate): <a href="https://www.hse.gov.uk/forms/notification/f10.htm">hse.gov.uk/forms/notification/f10.htm</a>
</div>

</body></html>"""


# ---------------------------------------------------------------------------
# Markdown render — for cases where the frontend just wants text
# ---------------------------------------------------------------------------

def render_pci_markdown(form: dict) -> str:
    meta = form["meta"]
    p = form["section_1_project"]

    lines: list[str] = []
    lines.append(f"# CDM Pre-Construction Information — {p.get('project_title', 'Project')}")
    lines.append("")
    lines.append(f"*{meta['legislation']}*")
    lines.append(f"*{meta['regulation']}*")
    lines.append(f"*{meta['acop_reference']}*")
    lines.append("")
    lines.append(f"Generated by {meta['generated_by']} on {meta['generated_at'][:10]}.")
    lines.append("")

    lines.append("## 1. Project information")
    for k, v in p.items():
        lines.append(f"- **{k.replace('_', ' ').title()}**: {v}")
    lines.append("")

    lines.append("## 2. Client considerations and management requirements")
    for k, v in form["section_2_management"].items():
        lines.append(f"- **{k.replace('_', ' ').title()}**: {v}")
    lines.append("")

    lines.append("## 3. Environment and existing site hazards")
    for h in form["section_3_existing_hazards"]["hazards"]:
        lines.append(f"- **{h['hazard']}** — {h['action']} (evidence: {h['evidence_ref']})")
    if form["section_3_existing_hazards"].get("survey_gaps_identified"):
        gaps = ", ".join(form["section_3_existing_hazards"]["survey_gaps_identified"])
        lines.append(f"")
        lines.append(f"**Outstanding survey gaps:** {gaps}")
    lines.append("")

    lines.append("## 4. Existing structures and demolition hazards")
    for k, v in form["section_4_existing_structures"].items():
        lines.append(f"- **{k.replace('_', ' ').title()}**: {v}")
    lines.append("")

    lines.append("## 5. Significant design and construction hazards")
    lines.append("### Design hazards")
    for h in form["section_5_significant_risks"]["design_hazards"]:
        lines.append(f"- **{h['hazard']}** — {h['control']} ({h['reg_ref']})")
    lines.append("")
    lines.append("### Significant risk register")
    for r in form["section_5_significant_risks"]["significant_risk_register"]:
        lines.append(
            f"- **{r['risk']}** — severity {r['severity']}, "
            f"likelihood {r['likelihood']}, residual {r['residual']} "
            f"(owner: {r['owner']})"
        )
    lines.append("")

    lines.append("## 6. Health and safety file and coordination")
    for k, v in form["section_6_coordination"].items():
        lines.append(f"- **{k.replace('_', ' ').title()}**: {v}")
    lines.append("")

    lines.append("## 7. Planning timeline")
    for m in form["section_7_planning_timeline"]["milestones"]:
        lines.append(f"- **{m['milestone']}** — target {m['target']} (owner: {m['responsible']})")
    lines.append("")
    lines.append(f"*{form['section_7_planning_timeline']['notes']}*")
    lines.append("")
    lines.append("---")
    lines.append(
        "Cite: CDM Regulations 2015 (SI 2015/51) · HSE L153 ACoP · "
        "F10 notification: https://www.hse.gov.uk/forms/notification/f10.htm"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Subprocess bridge — consistent with utils/due_diligence.py pattern
# ---------------------------------------------------------------------------

def main() -> None:
    raw = sys.stdin.read()
    try:
        req = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    try:
        result = generate_pci(
            site=req.get("site") or {},
            capacity_mw=float(req.get("capacity_mw", 0) or 0),
            technology=req.get("technology", "solar"),
            environmental=req.get("environmental") or {},
            timeline=req.get("timeline") or {},
            client=req.get("client") or {},
        )
        json.dump(result, sys.stdout)
    except Exception as e:  # pragma: no cover
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
