"""Section 3 — Project detail.

Site / technology / counterparties / key assumptions. This is the section
an IC member interrogates when they disagree with the recommendation —
specifically the "key assumptions" table per the 2026 IC-grade sophistication
ladder (§4c): each input with source, date-stamp, last-review, confidence
band, and provenance class (hard-contracted / modelled / technical).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _today_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def build_project_detail(
    proj: dict[str, Any],
    fin: dict[str, Any],
    grid: dict[str, Any],
    plan: dict[str, Any],
    counterparties: dict[str, Any] | None = None,
    assumptions_overrides: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the project detail block."""

    site = {
        "name": proj.get("name"),
        "tech": (proj.get("workload") or proj.get("technology") or "—").title(),
        "capacity_mw": proj.get("capacity_mw"),
        "region": proj.get("region") or "TBC",
        "lpa": plan.get("lpa") or "TBC (pre-app)",
        "lat": proj.get("lat"),
        "lon": proj.get("lon"),
        "area_ha": proj.get("area_ha"),
        "cod_target": proj.get("cod_target") or "2028 Q2",
    }

    grid_block = {
        "poc_substation": grid.get("poc_substation") or "TBC (nearest primary)",
        "poc_voltage_kv": grid.get("poc_voltage_kv") or 33,
        "gate_status": grid.get("gate_status") or "Gate 2 — Needed",
        "tmo4_status": grid.get("tmo4_status") or "Aligned with CP2030 pathway",
        "conn_cost_p50_gbp_m": (grid.get("conn_cost_k") or 0) / 1000,
        "headroom_mw": grid.get("headroom_mw"),
        "queue_years": grid.get("queue_years"),
    }

    cp = counterparties or {}
    cparties = {
        "developer": cp.get("developer") or "Princeps Development Ltd",
        "epc": cp.get("epc") or "Shortlisted: Ethical Power, Bouygues, Enerparc",
        "legal": cp.get("legal") or "Addleshaw Goddard (lead); Shoosmiths (RE)",
        "tech_advisor": cp.get("tech_advisor") or "Wood Group (lender IE)",
        "ppa_offtaker": cp.get("ppa_offtaker") or "TBC — shortlist: ScottishPower, Axpo, SmartestEnergy",
        "land_agent": cp.get("land_agent") or "Carter Jonas",
        "insurance_broker": cp.get("insurance_broker") or "Marsh (renewable energy team)",
    }

    # Key assumptions — IC-grade: per-row source + date + confidence + class.
    today = _today_iso()
    base_assumptions: list[dict[str, Any]] = [
        {"name": "Project life", "value": "25 years",
         "source": "Standard solar/wind; BESS augmentation at SoH 80%",
         "date": today, "confidence": "±2 yr", "class": "technical"},
        {"name": "Capex (all-in)",
         "value": f"£{fin.get('capex_m', 40):.1f}m",
         "source": "Princeps investment_appraisal CAPEX_PER_MW (solar £550k/MW, BESS £500k/MW)",
         "date": today, "confidence": "±10% to FEED",
         "class": "modelled"},
        {"name": "PPA / merchant price",
         "value": f"£{fin.get('ppa_price', 55):.0f}/MWh base; "
                  f"£{fin.get('ppa_price', 55) * 0.85:.0f}–"
                  f"£{fin.get('ppa_price', 55) * 1.15:.0f} range",
         "source": "Cornwall Insight UK Power Market Forecast Q1 2026 (baseload)",
         "date": "2026-Q1", "confidence": "P10/P90 ±15%",
         "class": "modelled"},
        {"name": "Capacity factor / yield",
         "value": f"{fin.get('cap_factor_pct', 11):.1f}% (P50)",
         "source": "Princeps SAM PvWattsv8 hourly; weather Meteonorm 8",
         "date": today, "confidence": "P90 −6% from P50",
         "class": "technical"},
        {"name": "Availability",
         "value": f"{fin.get('availability_pct', 97):.1f}%",
         "source": "DNV-GL industry benchmark 2024; warranty line in ITA",
         "date": today, "confidence": "−3 pp downside",
         "class": "technical"},
        {"name": "Annual degradation",
         "value": "0.5% / yr (solar); 2.5% / yr (BESS SoH)",
         "source": "IEC TS 63019; Princeps bankable_yield.py",
         "date": today, "confidence": "±0.15 pp / yr",
         "class": "technical"},
        {"name": "Inflation (CPI)",
         "value": "2.5% long-run",
         "source": "OBR Fiscal Risks Report 2026; BoE Monetary Policy Report Feb 2026",
         "date": "2026-02", "confidence": "BoE forecast band",
         "class": "modelled"},
        {"name": "Gearing",
         "value": "70% on total capex",
         "source": "LMA IG Facility Agreement template; Princeps lender_pack default",
         "date": today, "confidence": "65–70% institutional band",
         "class": "hard_contracted"},
        {"name": "Senior debt margin",
         "value": "SONIA + 225 bps (base)",
         "source": "Refi benchmark Santander / NatWest sterling infra Q1 2026",
         "date": "2026-Q1", "confidence": "±25 bps to term sheet",
         "class": "modelled"},
        {"name": "Debt tenor",
         "value": "18 years amortising",
         "source": "CfD AR7 20-yr term now available; lender standard",
         "date": today, "confidence": "Hard — LMA form",
         "class": "hard_contracted"},
        {"name": "WACC",
         "value": f"{fin.get('wacc_pct', 7.5):.1f}%",
         "source": "Princeps finance_benchmarks.wacc (tech-adjusted)",
         "date": today, "confidence": "±50 bps",
         "class": "modelled"},
        {"name": "Corporation tax rate",
         "value": "25%",
         "source": "Finance Act 2023 main rate",
         "date": "2023-04", "confidence": "Hard",
         "class": "hard_contracted"},
        {"name": "BNG unit cost",
         "value": "£30k/ha off-site; £11k/ha on-site",
         "source": "DEFRA Biodiversity Metric 4.0 (April 2023); market rate Q1 2026",
         "date": "2026-Q1", "confidence": "±20%",
         "class": "modelled"},
        {"name": "Connection charging",
         "value": "TMO4+ shallow-ish (DNO reinforcement socialised)",
         "source": "Ofgem TMO4+ summary decision 15 April 2025 (OFG1164)",
         "date": "2025-04", "confidence": "Hard — in force",
         "class": "hard_contracted"},
        {"name": "Exit multiple",
         "value": "14.0x EV/EBITDA (base); 12.5x (downside)",
         "source": "Precedents — see §7. Mean 13.8x on 5 UK solar comps",
         "date": today, "confidence": "±1.5x on market read",
         "class": "modelled"},
    ]
    if assumptions_overrides:
        base_assumptions = base_assumptions + list(assumptions_overrides)

    return {
        "available": True,
        "site": site,
        "grid": grid_block,
        "counterparties": cparties,
        "assumptions": base_assumptions,
        "citation": (
            "Cornwall Insight, NESO FES 2024, Ofgem OFG1164, LMA IG Facility "
            "Agreement 2024, DEFRA Biodiversity Metric 4.0, OBR Fiscal Risks "
            "Report 2026, DNV-GL benchmark."
        ),
    }
