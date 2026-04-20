"""
Conditions Precedent (CP) / Conditions Subsequent (CS) schedule
generator for UK project-finance energy deals.

DD packs targeting lender debt close, equity close, or Notice to Proceed
(NTP) are expected to present a formal CP schedule: each item captured as
{item, responsible party, target date, status, evidence pointer}. The
generator also produces a CS schedule for items that must be satisfied
post-close (O&M signed, spares agreement, security perfection confirmed,
etc.).

Taxonomy tracks the LMA / LSTA precedent-finance facility agreement
structure (see LMA Leveraged Facility Agreement and LMA Real Estate
Finance templates). We distinguish:

    CP category         Meaning
    ----------------------------------------------------------
    constitutional      Borrower / project company incorporation docs
    authorisation       Board / shareholder resolutions, consents
    legal_opinion       English + local counsel legal opinions
    real_estate         Land rights, leases, easements perfected
    consent             Planning consent, environmental permits
    grid                Grid connection offer accepted, interface agreements
    construction        EPC contract executed, NTP issued
    revenue             PPA / offtake contracts executed
    insurance           Insurance bound, broker letter
    financial           Equity funded, hedging in place, accounts opened
    security            Security documents signed (perfection may be CS)
    transactional       CP certificate, utilisation request, drawdown evidence

    CS category         Meaning
    ----------------------------------------------------------
    post_close_docs     O&M, LTSA, asset-management agreements
    perfection          Registered security — Companies House, Land Registry
    reserve_accounts    DSR / MSR funding
    reporting           First periodic lender report, compliance certificates
    performance         Performance security / bank guarantees in place
    operational         First synchronisation, provisional take-over

Each item: {id, category, item, responsible, target_date, status,
evidence, lma_ref}. Status is one of: pending | in_progress | met |
waived | not_applicable.

Project-specific overrides merge in from `projects.metadata` JSONB (see
backend schema: projects.metadata -> 'cp_cs_overrides'). Override shape:

    {
      "cp_overrides": [{"id": "cp_14_grid_offer", "status": "met",
                        "evidence": "NGED offer ref 123/25"}],
      "cs_overrides": [{"id": "cs_04_perfection", "target_date": "2026-06-30"}],
      "additional_cp": [{"id": "cp_local_01", "category": "consent",
                         "item": "Scottish CAR licence", ...}],
      "additional_cs": [...]
    }
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from typing import Any


_VALID_STATUS = {"pending", "in_progress", "met", "waived", "not_applicable"}


# ---------------------------------------------------------------------------
# Default CP schedule (UK project-finance energy deal)
# ---------------------------------------------------------------------------

_DEFAULT_CPS: list[dict[str, Any]] = [
    # Constitutional
    {
        "id": "cp_01_constitutional",
        "category": "constitutional",
        "item": "Certified copies of borrower and obligor constitutional documents",
        "responsible": "Sponsor / Borrower counsel",
        "offset_days": -30,
        "lma_ref": "LMA CP Sch 2 §1 (Original Obligors)",
    },
    {
        "id": "cp_02_authorisation",
        "category": "authorisation",
        "item": "Board resolutions and shareholder resolutions authorising the transaction",
        "responsible": "Sponsor",
        "offset_days": -14,
        "lma_ref": "LMA CP Sch 2 §1 (Authorisations)",
    },
    {
        "id": "cp_03_directors_cert",
        "category": "authorisation",
        "item": "Directors' certificate confirming no default, resolutions, constitutional docs unchanged",
        "responsible": "Borrower directors",
        "offset_days": -3,
        "lma_ref": "LMA CP Sch 2 §1 (Certificates)",
    },

    # Legal opinions
    {
        "id": "cp_04_legal_opinion_borrower",
        "category": "legal_opinion",
        "item": "Borrower's counsel legal opinion (capacity, enforceability)",
        "responsible": "Borrower counsel",
        "offset_days": -3,
        "lma_ref": "LMA CP Sch 2 §2 (Legal Opinions)",
    },
    {
        "id": "cp_05_legal_opinion_lender",
        "category": "legal_opinion",
        "item": "Lender's counsel legal opinion on finance + security documents",
        "responsible": "Lender counsel",
        "offset_days": -3,
        "lma_ref": "LMA CP Sch 2 §2 (Legal Opinions)",
    },

    # Real estate / land rights
    {
        "id": "cp_06_land_rights",
        "category": "real_estate",
        "item": "Land rights perfected — freehold / option / lease with sufficient term (min 25 yrs + extension)",
        "responsible": "Land agent / Borrower",
        "offset_days": -45,
        "lma_ref": "LMA REF CP §3 (Real Estate)",
    },
    {
        "id": "cp_07_title_report",
        "category": "real_estate",
        "item": "Certificate of title / replies to real estate due diligence satisfactory to Agent",
        "responsible": "Real estate counsel",
        "offset_days": -14,
        "lma_ref": "LMA REF CP §3",
    },
    {
        "id": "cp_08_easements",
        "category": "real_estate",
        "item": "Grid / cable / access easements signed and registered or undertaking from seller's solicitor",
        "responsible": "Land agent",
        "offset_days": -21,
        "lma_ref": "LMA REF CP §3",
    },

    # Consents
    {
        "id": "cp_09_planning_consent_final",
        "category": "consent",
        "item": "Planning consent granted, judicial review period expired or satisfactorily discharged",
        "responsible": "Planning consultant",
        "offset_days": -60,
        "lma_ref": "LMA CP Sch 2 §3 (Consents) — bespoke energy add-on",
    },
    {
        "id": "cp_10_conditions_discharged",
        "category": "consent",
        "item": "All pre-commencement planning conditions discharged by LPA",
        "responsible": "Planning consultant",
        "offset_days": -30,
        "lma_ref": "LMA CP Sch 2 §3",
    },
    {
        "id": "cp_11_environmental_permits",
        "category": "consent",
        "item": "Environmental permits issued (EA / SEPA / NRW where applicable)",
        "responsible": "Environmental consultant",
        "offset_days": -30,
        "lma_ref": "LMA CP Sch 2 §3",
    },
    {
        "id": "cp_12_s106_discharged",
        "category": "consent",
        "item": "S.106 / UU obligations (community benefit, highways) signed and discharged",
        "responsible": "Planning counsel",
        "offset_days": -30,
        "lma_ref": "LMA CP Sch 2 §3",
    },

    # Grid
    {
        "id": "cp_13_grid_offer_accepted",
        "category": "grid",
        "item": "DNO / TNO grid connection offer accepted; acceptance fee paid",
        "responsible": "Borrower / grid consultant",
        "offset_days": -90,
        "lma_ref": "Bespoke energy CP (grid interface)",
    },
    {
        "id": "cp_14_connection_agreement",
        "category": "grid",
        "item": "Bilateral connection agreement and modification application signed (where applicable)",
        "responsible": "Borrower",
        "offset_days": -45,
        "lma_ref": "Bespoke energy CP",
    },
    {
        "id": "cp_15_g99_g100_progress",
        "category": "grid",
        "item": "G99 / G100 / EREC S application submitted and accepted by DNO",
        "responsible": "Electrical design lead",
        "offset_days": -30,
        "lma_ref": "Bespoke energy CP",
    },

    # Construction
    {
        "id": "cp_16_epc_wrap_executed",
        "category": "construction",
        "item": "EPC wrap contract (or multi-contracting set) executed; performance bonds posted",
        "responsible": "EPC counterparty + Borrower",
        "offset_days": -30,
        "lma_ref": "LMA CP Sch 2 §4 (Project Documents)",
    },
    {
        "id": "cp_17_om_contract_agreed",
        "category": "construction",
        "item": "Form of long-term O&M / LTSA agreed in final form (execution may be CS)",
        "responsible": "Borrower",
        "offset_days": -14,
        "lma_ref": "LMA CP Sch 2 §4",
    },
    {
        "id": "cp_18_construction_budget",
        "category": "construction",
        "item": "Construction budget, drawdown schedule and base case model agreed",
        "responsible": "Borrower + model auditor",
        "offset_days": -14,
        "lma_ref": "LMA CP Sch 2 §5 (Financial)",
    },

    # Revenue
    {
        "id": "cp_19_ppa_executed",
        "category": "revenue",
        "item": "PPA / route-to-market offtake contract executed with approved counterparty",
        "responsible": "Borrower",
        "offset_days": -30,
        "lma_ref": "LMA CP Sch 2 §4 (Project Documents)",
    },
    {
        "id": "cp_20_cfd_award",
        "category": "revenue",
        "item": "AR / CfD Allocation Round award (if applicable) confirmed and contract signed",
        "responsible": "Borrower",
        "offset_days": -60,
        "lma_ref": "Bespoke energy CP",
    },

    # Insurance
    {
        "id": "cp_21_insurance_bound",
        "category": "insurance",
        "item": "Construction All Risks, Delay in Start-Up, third-party liability bound; broker letter of undertaking",
        "responsible": "Insurance broker",
        "offset_days": -14,
        "lma_ref": "LMA CP Sch 2 §6 (Insurance)",
    },

    # Financial / accounts
    {
        "id": "cp_22_equity_funding",
        "category": "financial",
        "item": "Base-case equity contribution funded or equity commitment letter in agreed form",
        "responsible": "Sponsor",
        "offset_days": -3,
        "lma_ref": "LMA CP Sch 2 §5",
    },
    {
        "id": "cp_23_hedging",
        "category": "financial",
        "item": "Interest-rate hedging strategy documented; ISDA executed (if day-one hedging required)",
        "responsible": "Borrower treasury",
        "offset_days": -7,
        "lma_ref": "LMA CP Sch 2 §7 (Hedging)",
    },
    {
        "id": "cp_24_accounts_opened",
        "category": "financial",
        "item": "Project account bank letter; accounts opened (Proceeds, DSRA, MRA, Distribution)",
        "responsible": "Borrower treasury",
        "offset_days": -7,
        "lma_ref": "LMA CP Sch 2 §5",
    },

    # Security
    {
        "id": "cp_25_security_signed",
        "category": "security",
        "item": "Security documents (debenture, share charges, real-estate security, subordination) signed",
        "responsible": "Borrower + security agent",
        "offset_days": -1,
        "lma_ref": "LMA CP Sch 2 §8 (Security)",
    },

    # Transactional
    {
        "id": "cp_26_cp_certificate",
        "category": "transactional",
        "item": "CP satisfaction certificate from Agent confirming all CPs met",
        "responsible": "Facility Agent",
        "offset_days": 0,
        "lma_ref": "LMA CP Sch 2 §9 (Certificate)",
    },
    {
        "id": "cp_27_utilisation_request",
        "category": "transactional",
        "item": "Utilisation / drawdown request delivered with funds flow statement",
        "responsible": "Borrower",
        "offset_days": 0,
        "lma_ref": "LMA Utilisation",
    },
]


# ---------------------------------------------------------------------------
# Default CS schedule
# ---------------------------------------------------------------------------

_DEFAULT_CSS: list[dict[str, Any]] = [
    {
        "id": "cs_01_om_execution",
        "category": "post_close_docs",
        "item": "Long-term O&M / LTSA agreement signed and delivered to Agent",
        "responsible": "Borrower",
        "offset_days": 60,
        "lma_ref": "LMA Information Undertakings",
    },
    {
        "id": "cs_02_spares_agreement",
        "category": "post_close_docs",
        "item": "Strategic spares agreement or spares inventory letter",
        "responsible": "Borrower / EPC",
        "offset_days": 90,
        "lma_ref": "Bespoke energy CS",
    },
    {
        "id": "cs_03_companies_house",
        "category": "perfection",
        "item": "Security registered at Companies House within statutory 21 days (MR01)",
        "responsible": "Security agent counsel",
        "offset_days": 21,
        "lma_ref": "CA 2006 s.859A — LMA security agent undertaking",
    },
    {
        "id": "cs_04_land_registry",
        "category": "perfection",
        "item": "Legal mortgage and restriction registered at HM Land Registry; title updated",
        "responsible": "Real estate counsel",
        "offset_days": 60,
        "lma_ref": "LRA 2002 s.27 — LMA REF template",
    },
    {
        "id": "cs_05_dsra_funding",
        "category": "reserve_accounts",
        "item": "Debt Service Reserve Account funded to 6 months' service (or LC equivalent)",
        "responsible": "Borrower treasury",
        "offset_days": 30,
        "lma_ref": "LMA Financial Covenants",
    },
    {
        "id": "cs_06_performance_security",
        "category": "performance",
        "item": "EPC performance bond and parent company guarantee delivered and acceptable to Agent",
        "responsible": "EPC counterparty",
        "offset_days": 14,
        "lma_ref": "Bespoke energy CS",
    },
    {
        "id": "cs_07_first_compliance_cert",
        "category": "reporting",
        "item": "First compliance certificate delivered per Information Undertakings",
        "responsible": "Borrower",
        "offset_days": 90,
        "lma_ref": "LMA Information Undertakings",
    },
    {
        "id": "cs_08_drawdown_reports",
        "category": "reporting",
        "item": "Construction drawdown reports signed by Lenders' Technical Adviser each milestone",
        "responsible": "Lenders' Technical Adviser",
        "offset_days": 30,
        "lma_ref": "LMA Information Undertakings",
    },
    {
        "id": "cs_09_first_sync",
        "category": "operational",
        "item": "First synchronisation / energisation confirmed by DNO",
        "responsible": "Commissioning engineer + DNO",
        "offset_days": 270,
        "lma_ref": "Bespoke energy CS",
    },
    {
        "id": "cs_10_takeover",
        "category": "operational",
        "item": "Provisional take-over certificate under EPC; O&M period commences",
        "responsible": "Owner's engineer",
        "offset_days": 365,
        "lma_ref": "Bespoke energy CS",
    },
    {
        "id": "cs_11_model_audit",
        "category": "reporting",
        "item": "Operating base-case model re-audit post-COD and delivered to Agent",
        "responsible": "Model auditor",
        "offset_days": 395,
        "lma_ref": "LMA Financial Covenants",
    },
]


# ---------------------------------------------------------------------------
# Target-date handling
# ---------------------------------------------------------------------------

def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


def _offset(anchor: date | None, days: int) -> str:
    if anchor is None:
        sign = "-" if days < 0 else "+"
        return f"T{sign}{abs(days)}d (anchor TBC)"
    return (anchor + timedelta(days=days)).isoformat()


def _merge_overrides(
    base: list[dict[str, Any]],
    overrides: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Apply {id: ..., <fields>} overrides onto the base list by id."""
    if not overrides:
        return base
    by_id = {item["id"]: item for item in base}
    for ov in overrides:
        oid = ov.get("id")
        if not oid or oid not in by_id:
            continue
        by_id[oid].update({k: v for k, v in ov.items() if k != "id"})
    return list(by_id.values())


def _normalise_status(status: Any) -> str:
    if not status:
        return "pending"
    s = str(status).lower().strip()
    if s in _VALID_STATUS:
        return s
    return "pending"


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def generate_cp_cs_schedule(
    project_name: str = "Project",
    target_close_date: Any = None,
    cod_date: Any = None,
    project_metadata: dict | None = None,
    capacity_mw: float | None = None,
    tech_type: str | None = None,
    region: str | None = None,
) -> dict:
    """Generate CP + CS schedule for a UK project-finance energy deal.

    Args:
        project_name: human-friendly name used in the header.
        target_close_date: anchor for CP dates (debt close / NTP). Date,
                           datetime, or ISO string accepted.
        cod_date: anchor for CS dates (Commercial Operation Date). Defaults
                  to 14 months after close if not supplied.
        project_metadata: value of `projects.metadata` JSONB. Overrides are
                          read from:
              metadata["cp_cs_overrides"] = {"cp_overrides": [...],
                                             "cs_overrides": [...],
                                             "additional_cp": [...],
                                             "additional_cs": [...]}
        capacity_mw: used for flagging (e.g. CfD CP if > some threshold).
        tech_type: solar | bess | wind | dc — drops inapplicable CPs.
        region: UK region — Scotland pulls in CAR permit line, etc.

    Returns:
        {cp_schedule, cs_schedule, summary, html, markdown, document_type}
    """
    close = _to_date(target_close_date)
    cod = _to_date(cod_date)
    if cod is None and close is not None:
        cod = close + timedelta(days=420)  # ~14 months default build

    overrides = {}
    if project_metadata and isinstance(project_metadata, dict):
        overrides = project_metadata.get("cp_cs_overrides") or {}

    cps = [dict(x) for x in _DEFAULT_CPS]
    css = [dict(x) for x in _DEFAULT_CSS]

    # Drop CfD line if not applicable
    t = (tech_type or "").lower()
    if t in ("bess", "dc"):
        cps = [c for c in cps if c["id"] != "cp_20_cfd_award"]

    # Scotland-specific add
    if (region or "").strip().lower() in ("scotland", "scot", "sco"):
        cps.append({
            "id": "cp_scot_01_car_licence",
            "category": "consent",
            "item": "SEPA CAR licence issued (water environment) — Scotland only",
            "responsible": "Environmental consultant",
            "offset_days": -30,
            "lma_ref": "Bespoke Scotland CP",
        })

    cps = _merge_overrides(cps, overrides.get("cp_overrides"))
    css = _merge_overrides(css, overrides.get("cs_overrides"))
    for extra in overrides.get("additional_cp", []) or []:
        if extra.get("id"):
            cps.append(extra)
    for extra in overrides.get("additional_cs", []) or []:
        if extra.get("id"):
            css.append(extra)

    # Resolve dates + statuses
    def _finalise(items: list[dict], anchor: date | None) -> list[dict]:
        out = []
        for it in items:
            target = it.get("target_date") or _offset(anchor, int(it.get("offset_days") or 0))
            out.append({
                "id": it["id"],
                "category": it.get("category", "other"),
                "item": it["item"],
                "responsible": it.get("responsible", "[Responsible party]"),
                "target_date": target,
                "status": _normalise_status(it.get("status")),
                "evidence": it.get("evidence", "[Evidence pending]"),
                "lma_ref": it.get("lma_ref", ""),
            })
        return out

    cp_rows = _finalise(cps, close)
    cs_rows = _finalise(css, cod)

    # Counts by status
    def _counts(rows):
        c = {s: 0 for s in _VALID_STATUS}
        for r in rows:
            c[r["status"]] += 1
        return c

    cp_counts = _counts(cp_rows)
    cs_counts = _counts(cs_rows)

    summary = {
        "project_name": project_name,
        "target_close_date": close.isoformat() if close else None,
        "cod_date": cod.isoformat() if cod else None,
        "capacity_mw": capacity_mw,
        "tech_type": tech_type,
        "region": region,
        "cp_total": len(cp_rows),
        "cs_total": len(cs_rows),
        "cp_status_counts": cp_counts,
        "cs_status_counts": cs_counts,
        "cp_ready_pct": round(
            100 * (cp_counts["met"] + cp_counts["waived"] + cp_counts["not_applicable"])
            / max(1, len(cp_rows))
        ),
        "cs_ready_pct": round(
            100 * (cs_counts["met"] + cs_counts["waived"] + cs_counts["not_applicable"])
            / max(1, len(cs_rows))
        ),
    }

    return {
        "document_type": "cp_cs_schedule",
        "cp_schedule": cp_rows,
        "cs_schedule": cs_rows,
        "summary": summary,
        "html": render_cp_cs_html(project_name, cp_rows, cs_rows, summary),
        "markdown": render_cp_cs_markdown(project_name, cp_rows, cs_rows, summary),
        "citation": {
            "precedent": "LMA Leveraged Facility Agreement + LMA Real Estate Finance template "
                         "(Loan Market Association); LSTA investment-grade precedent (cross-check).",
            "note": "Energy-specific CPs (grid offer, PPA, planning discharge, G99/G100) are bespoke to UK energy project finance.",
        },
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

_STATUS_BADGE = {
    "met": ("#166534", "#f0fdf4"),
    "waived": ("#1e40af", "#eff6ff"),
    "not_applicable": ("#6b7280", "#f3f4f6"),
    "in_progress": ("#92400e", "#fef3c7"),
    "pending": ("#b91c1c", "#fee2e2"),
}


def _badge(status: str) -> str:
    fg, bg = _STATUS_BADGE.get(status, ("#6b7280", "#f3f4f6"))
    return (
        f'<span style="background:{bg};color:{fg};padding:1px 6px;'
        f'border-radius:3px;font-size:9px;font-weight:600;text-transform:uppercase;">'
        f'{status.replace("_", " ")}</span>'
    )


def render_cp_cs_html(project_name: str, cps: list[dict], css: list[dict], summary: dict) -> str:
    def _rows(items):
        return "".join(
            f"<tr><td>{it['id']}</td><td>{it['category']}</td><td>{it['item']}</td>"
            f"<td>{it['responsible']}</td><td>{it['target_date']}</td>"
            f"<td>{_badge(it['status'])}</td><td>{it['evidence']}</td>"
            f"<td style='font-size:8px;color:#6b7280;'>{it['lma_ref']}</td></tr>"
            for it in items
        )

    cp_table = _rows(cps)
    cs_table = _rows(css)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>CP/CS Schedule — {project_name}</title>
<style>
body {{ font-family: 'DM Sans', system-ui, sans-serif; margin: 0; padding: 28px;
       color: #0F1318; font-size: 11px; line-height: 1.5; }}
h1 {{ color: #F5B731; font-size: 22px; margin: 0 0 4px; }}
h2 {{ color: #374151; font-size: 14px; margin: 22px 0 6px;
     padding: 6px 10px; background: #FFF8E6; border-left: 3px solid #F5B731; }}
.subtitle {{ color: #6b7280; font-size: 10px; }}
.summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;
          margin: 12px 0 20px; }}
.s-card {{ padding: 10px; background: #F7F8FA; border-radius: 6px; }}
.s-lbl {{ font-size: 8px; color: #6B7280; letter-spacing: 0.06em;
        text-transform: uppercase; font-weight: 700; }}
.s-val {{ font-family: 'JetBrains Mono', monospace; font-size: 18px;
        font-weight: 700; color: #0F1318; margin-top: 3px; }}
table {{ width: 100%; border-collapse: collapse; margin: 4px 0 10px;
       font-size: 10px; }}
th, td {{ padding: 4px 6px; border-bottom: 1px solid #e5e7eb;
       vertical-align: top; text-align: left; }}
th {{ background: #f9fafb; font-weight: 600; color: #374151;
    font-size: 9px; text-transform: uppercase; letter-spacing: 0.04em; }}
.footer {{ margin-top: 24px; padding-top: 10px;
         border-top: 1px solid #e5e7eb; font-size: 9px; color: #9ca3af; }}
</style></head><body>

<h1>Conditions Precedent / Subsequent Schedule</h1>
<div class="subtitle">{project_name} · Generated {datetime.utcnow().strftime('%d %b %Y')}</div>

<div class="summary">
  <div class="s-card"><div class="s-lbl">CP total</div>
    <div class="s-val">{summary['cp_total']}</div></div>
  <div class="s-card"><div class="s-lbl">CP ready</div>
    <div class="s-val">{summary['cp_ready_pct']}%</div></div>
  <div class="s-card"><div class="s-lbl">CS total</div>
    <div class="s-val">{summary['cs_total']}</div></div>
  <div class="s-card"><div class="s-lbl">CS ready</div>
    <div class="s-val">{summary['cs_ready_pct']}%</div></div>
</div>

<h2>Conditions Precedent</h2>
<table>
<tr><th>ID</th><th>Category</th><th>Item</th><th>Responsible</th>
    <th>Target</th><th>Status</th><th>Evidence</th><th>LMA ref</th></tr>
{cp_table}
</table>

<h2>Conditions Subsequent</h2>
<table>
<tr><th>ID</th><th>Category</th><th>Item</th><th>Responsible</th>
    <th>Target</th><th>Status</th><th>Evidence</th><th>LMA ref</th></tr>
{cs_table}
</table>

<div class="footer">
  Structure tracks LMA Leveraged Facility Agreement + LMA Real Estate Finance precedent,
  cross-checked against LSTA investment-grade templates. Energy-specific CPs (grid
  offer, PPA / CfD, planning discharge, G99/G100) are bespoke additions. All target
  dates are indicative relative to close; replace with executed schedule before
  distribution to the facility agent.
</div>

</body></html>"""


def render_cp_cs_markdown(project_name: str, cps: list[dict], css: list[dict], summary: dict) -> str:
    lines: list[str] = []
    lines.append(f"# CP/CS Schedule — {project_name}")
    lines.append("")
    lines.append(f"Generated {datetime.utcnow().strftime('%Y-%m-%d')}.")
    lines.append("")
    lines.append(
        f"**CP total**: {summary['cp_total']} · "
        f"**CP ready**: {summary['cp_ready_pct']}% · "
        f"**CS total**: {summary['cs_total']} · "
        f"**CS ready**: {summary['cs_ready_pct']}%"
    )
    lines.append("")

    def _section(title: str, rows: list[dict]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| ID | Category | Item | Responsible | Target | Status | Evidence | LMA ref |")
        lines.append("|----|----------|------|-------------|--------|--------|----------|---------|")
        for r in rows:
            lines.append(
                f"| {r['id']} | {r['category']} | {r['item']} | {r['responsible']} | "
                f"{r['target_date']} | {r['status']} | {r['evidence']} | {r['lma_ref']} |"
            )
        lines.append("")

    _section("Conditions Precedent", cps)
    _section("Conditions Subsequent", css)

    lines.append(
        "_Structure tracks LMA Leveraged Facility Agreement + LMA Real Estate Finance "
        "precedent, cross-checked against LSTA investment-grade templates. Energy-specific "
        "CPs (grid offer, PPA / CfD, planning discharge, G99/G100) are bespoke additions._"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Subprocess bridge
# ---------------------------------------------------------------------------

def main() -> None:
    raw = sys.stdin.read()
    try:
        req = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    try:
        result = generate_cp_cs_schedule(
            project_name=req.get("project_name", "Project"),
            target_close_date=req.get("target_close_date"),
            cod_date=req.get("cod_date"),
            project_metadata=req.get("project_metadata"),
            capacity_mw=req.get("capacity_mw"),
            tech_type=req.get("tech_type") or req.get("technology"),
            region=req.get("region"),
        )
        json.dump(result, sys.stdout, default=str)
    except Exception as e:  # pragma: no cover
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
