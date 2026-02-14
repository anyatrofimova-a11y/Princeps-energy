"""
Legacy Asset Planning & Compliance Module.

Provides asset lifecycle management, regulatory compliance checking,
repowering opportunity assessment, and decommissioning planning for
UK energy infrastructure.
"""

from __future__ import annotations

import math
from datetime import datetime, date
from typing import Any

# UK regulatory frameworks and thresholds
UK_ASSET_LIFECYCLES = {
    "solar_farm": {"design_life_years": 25, "warranty_typical": 10, "degradation_pct_yr": 0.5},
    "wind_farm": {"design_life_years": 25, "warranty_typical": 5, "degradation_pct_yr": 1.0},
    "battery_storage": {"design_life_years": 15, "warranty_typical": 10, "degradation_pct_yr": 2.0},
    "substation": {"design_life_years": 40, "warranty_typical": 0, "degradation_pct_yr": 0.3},
    "transformer": {"design_life_years": 35, "warranty_typical": 0, "degradation_pct_yr": 0.4},
    "cable_route": {"design_life_years": 40, "warranty_typical": 0, "degradation_pct_yr": 0.2},
    "inverter": {"design_life_years": 12, "warranty_typical": 5, "degradation_pct_yr": 1.5},
}

UK_COMPLIANCE_FRAMEWORKS = {
    "planning": {
        "nsip_threshold_mw": 50,
        "epc_required": True,
        "eia_threshold_mw": 5,
        "decommissioning_bond_required_mw": 5,
    },
    "environmental": {
        "biodiversity_net_gain_pct": 10,
        "habitat_survey_required": True,
        "eia_screening_threshold_ha": 0.5,
    },
    "grid": {
        "g99_threshold_kw": 50,
        "ecp1_applies": True,
        "protection_review_interval_years": 5,
    },
    "safety": {
        "cdm_applies": True,
        "hse_notification_mw": 1,
        "fire_risk_assessment_required": True,
    },
}

DECOMMISSIONING_COSTS_PER_KW = {
    "solar_farm": 45,      # GBP/kW
    "wind_farm": 120,
    "battery_storage": 80,
    "substation": 200,
}


def assess_asset_lifecycle(
    asset_type: str,
    commissioning_date: str,
    capacity_kw: float,
    current_condition_score: float | None = None,
) -> dict[str, Any]:
    """
    Assess where an asset is in its lifecycle and generate compliance timeline.

    Args:
        asset_type: Type of energy asset (solar_farm, wind_farm, etc.)
        commissioning_date: ISO date string (YYYY-MM-DD)
        capacity_kw: Installed capacity in kW
        current_condition_score: Optional 0-100 GeoAI condition score

    Returns:
        Lifecycle assessment with compliance milestones
    """
    lifecycle = UK_ASSET_LIFECYCLES.get(asset_type, UK_ASSET_LIFECYCLES["solar_farm"])
    try:
        comm_date = date.fromisoformat(commissioning_date)
    except (ValueError, TypeError):
        comm_date = date(2015, 1, 1)

    today = date.today()
    age_years = (today - comm_date).days / 365.25
    design_life = lifecycle["design_life_years"]
    remaining_life = max(0, design_life - age_years)
    degradation = lifecycle["degradation_pct_yr"] * age_years
    current_output_pct = max(0, 100 - degradation)

    # Condition assessment
    if current_condition_score is not None:
        condition = current_condition_score
    else:
        condition = max(0, 100 - (age_years / design_life) * 50 - degradation)

    if condition >= 70:
        status = "OPERATIONAL"
    elif condition >= 40:
        status = "DEGRADED"
    else:
        status = "END_OF_LIFE"

    # Compliance milestones
    milestones = _generate_milestones(asset_type, comm_date, capacity_kw, age_years, lifecycle)

    # Repowering assessment
    repowering = _assess_repowering(asset_type, age_years, capacity_kw, remaining_life, condition)

    # Decommissioning estimate
    decomm = _estimate_decommissioning(asset_type, capacity_kw)

    return {
        "asset_type": asset_type,
        "commissioning_date": commissioning_date,
        "age_years": round(age_years, 1),
        "design_life_years": design_life,
        "remaining_life_years": round(remaining_life, 1),
        "lifecycle_pct": round(min(100, (age_years / design_life) * 100), 1),
        "degradation_pct": round(degradation, 1),
        "current_output_pct": round(current_output_pct, 1),
        "condition_score": round(condition, 1),
        "status": status,
        "capacity_kw": capacity_kw,
        "milestones": milestones,
        "repowering": repowering,
        "decommissioning": decomm,
    }


def _generate_milestones(
    asset_type: str, comm_date: date, capacity_kw: float,
    age_years: float, lifecycle: dict,
) -> list[dict]:
    """Generate compliance milestones and deadlines."""
    milestones = []
    today = date.today()
    capacity_mw = capacity_kw / 1000

    # Warranty expiry
    warranty = lifecycle.get("warranty_typical", 0)
    if warranty > 0:
        warranty_date = date(comm_date.year + warranty, comm_date.month, comm_date.day)
        milestones.append({
            "event": "Warranty Expiry",
            "date": warranty_date.isoformat(),
            "status": "passed" if warranty_date < today else "upcoming",
            "action": "Review extended warranty or maintenance contract options",
        })

    # Protection relay review (every 5 years for grid-connected)
    if capacity_mw > 0.05:
        review_interval = UK_COMPLIANCE_FRAMEWORKS["grid"]["protection_review_interval_years"]
        last_review = comm_date.year + int(age_years // review_interval) * review_interval
        next_review_year = last_review + review_interval
        milestones.append({
            "event": "Grid Protection Review (G99)",
            "date": f"{next_review_year}-01-01",
            "status": "upcoming" if next_review_year > today.year else "overdue",
            "action": "Commission protection relay testing and G99 compliance check",
        })

    # EIA monitoring (if > 5MW)
    if capacity_mw >= UK_COMPLIANCE_FRAMEWORKS["planning"]["eia_threshold_mw"]:
        milestones.append({
            "event": "EIA Monitoring Report Due",
            "date": f"{today.year}-12-31",
            "status": "upcoming",
            "action": "Submit annual environmental monitoring report to LPA",
        })

    # Mid-life refurbishment
    mid_life = lifecycle["design_life_years"] // 2
    mid_date = date(comm_date.year + mid_life, comm_date.month, comm_date.day)
    milestones.append({
        "event": "Mid-Life Refurbishment Window",
        "date": mid_date.isoformat(),
        "status": "passed" if mid_date < today else "upcoming",
        "action": "Major component inspection and replacement planning",
    })

    # End of design life
    eol_date = date(
        comm_date.year + lifecycle["design_life_years"],
        comm_date.month,
        comm_date.day,
    )
    milestones.append({
        "event": "Design Life End",
        "date": eol_date.isoformat(),
        "status": "passed" if eol_date < today else "upcoming",
        "action": "Repower, life extension assessment, or decommissioning",
    })

    # Decommissioning bond review (if > 5MW)
    if capacity_mw >= UK_COMPLIANCE_FRAMEWORKS["planning"]["decommissioning_bond_required_mw"]:
        milestones.append({
            "event": "Decommissioning Bond Review",
            "date": f"{today.year + 1}-04-01",
            "status": "upcoming",
            "action": "Review decommissioning bond adequacy with updated cost estimates",
        })

    # Biodiversity net gain reporting
    milestones.append({
        "event": "BNG Monitoring Report",
        "date": f"{today.year}-09-30",
        "status": "upcoming",
        "action": f"Submit {UK_COMPLIANCE_FRAMEWORKS['environmental']['biodiversity_net_gain_pct']}% BNG progress report",
    })

    milestones.sort(key=lambda m: m["date"])
    return milestones


def _assess_repowering(
    asset_type: str, age_years: float, capacity_kw: float,
    remaining_life: float, condition: float,
) -> dict:
    """Assess repowering opportunity and economics."""
    # Technology improvement factor (annual efficiency gain)
    tech_improvement = {
        "solar_farm": 0.5,   # 0.5% annual cell efficiency improvement
        "wind_farm": 1.0,
        "battery_storage": 3.0,
        "substation": 0.2,
    }
    improvement_pct = tech_improvement.get(asset_type, 0.5) * age_years

    # Repowering capacity gain (modern equipment on same footprint)
    capacity_gain_pct = min(80, improvement_pct * 1.5)
    new_capacity_kw = capacity_kw * (1 + capacity_gain_pct / 100)

    # Cost estimate (GBP/kW for repowering — typically 60-70% of greenfield)
    repower_cost_per_kw = {
        "solar_farm": 450,
        "wind_farm": 900,
        "battery_storage": 350,
        "substation": 150,
    }
    cost = repower_cost_per_kw.get(asset_type, 500) * new_capacity_kw / 1000

    # ROI years based on UK energy prices (~5p/kWh export, ~15p/kWh PPA)
    annual_revenue = new_capacity_kw * 0.11 * 8760 * 0.10 / 1000  # CF ~10%, avg 11p/kWh
    roi_years = round(cost / annual_revenue, 1) if annual_revenue > 0 else None

    recommended = (
        remaining_life < 5
        or condition < 50
        or (age_years > 15 and capacity_gain_pct > 30)
    )

    return {
        "recommended": recommended,
        "urgency": "high" if remaining_life < 3 else ("medium" if remaining_life < 8 else "low"),
        "current_capacity_kw": capacity_kw,
        "new_capacity_kw": round(new_capacity_kw, 1),
        "capacity_gain_pct": round(capacity_gain_pct, 1),
        "technology_improvement_pct": round(improvement_pct, 1),
        "estimated_cost_gbp": round(cost),
        "estimated_roi_years": roi_years,
        "planning_considerations": [
            "Existing planning consent may cover repowering (check conditions)",
            "Permitted development rights may apply for like-for-like replacement",
            "Section 73 variation possible if within original parameters",
            "New EIA screening may be required for increased capacity",
        ],
    }


def _estimate_decommissioning(asset_type: str, capacity_kw: float) -> dict:
    """Estimate decommissioning costs and requirements."""
    cost_per_kw = DECOMMISSIONING_COSTS_PER_KW.get(asset_type, 60)
    total_cost = cost_per_kw * capacity_kw

    return {
        "estimated_cost_gbp": round(total_cost),
        "cost_per_kw_gbp": cost_per_kw,
        "requirements": [
            "Remove all above-ground infrastructure",
            "Remove foundations to 1m depth (agricultural land)",
            "Reinstate land to pre-development condition",
            "Disconnect and make safe all electrical connections",
            "Remove access tracks (unless landowner retention agreed)",
            "Environmental remediation if contamination found",
        ],
        "typical_duration_months": _decomm_duration(asset_type, capacity_kw),
        "waste_categories": {
            "recyclable_metals": "High value — steel, aluminium, copper",
            "panels_modules": "WEEE regulations apply — specialist recycling required",
            "concrete": "Crush and reuse on-site where possible",
            "cable": "Strip and recycle copper/aluminium",
        },
    }


def _decomm_duration(asset_type: str, capacity_kw: float) -> int:
    """Estimate decommissioning duration in months."""
    base = {"solar_farm": 3, "wind_farm": 6, "battery_storage": 2, "substation": 4}
    months = base.get(asset_type, 4)
    # Scale with capacity
    if capacity_kw > 5000:
        months += 3
    if capacity_kw > 50000:
        months += 6
    return months


def compliance_check(
    asset_type: str,
    capacity_kw: float,
    commissioning_date: str,
    overlays: list[str] | None = None,
    has_planning_consent: bool = True,
) -> dict[str, Any]:
    """
    Run a comprehensive compliance check against UK regulatory frameworks.

    Returns pass/fail status for each framework with remediation actions.
    """
    capacity_mw = capacity_kw / 1000
    overlays = overlays or []
    overlay_set = {o.lower() for o in overlays}

    checks = []

    # Planning compliance
    planning_status = "pass"
    planning_issues = []
    if not has_planning_consent:
        planning_status = "fail"
        planning_issues.append("No valid planning consent — enforcement risk")
    if capacity_mw >= 50:
        planning_issues.append("NSIP threshold — DCO required (Planning Act 2008)")
    if capacity_mw >= 5:
        planning_issues.append("EIA development — Environmental Statement required")
    checks.append({
        "framework": "Planning & Consents",
        "status": planning_status,
        "issues": planning_issues,
        "actions": ["Review planning conditions and compliance deadlines"] if planning_issues else [],
    })

    # Environmental compliance
    env_status = "pass"
    env_issues = []
    if any("sssi" in o for o in overlay_set):
        env_status = "warning"
        env_issues.append("Site within/adjacent to SSSI — Natural England consultation required")
    if any("aonb" in o for o in overlay_set):
        env_status = "warning"
        env_issues.append("Site within AONB — landscape impact assessment needed")
    if any("flood" in o for o in overlay_set):
        env_issues.append("Flood zone — sequential/exception test may apply")
    if any("heritage" in o for o in overlay_set):
        env_issues.append("Heritage designation — Historic England consultation may be required")
    checks.append({
        "framework": "Environmental",
        "status": env_status,
        "issues": env_issues,
        "actions": [f"Commission specialist survey for: {', '.join(env_issues)}"] if env_issues else [],
    })

    # Grid compliance
    grid_status = "pass"
    grid_issues = []
    if capacity_kw > UK_COMPLIANCE_FRAMEWORKS["grid"]["g99_threshold_kw"]:
        grid_issues.append("G99 compliance required — protection settings review needed")
    checks.append({
        "framework": "Grid Connection (G99/G100)",
        "status": grid_status,
        "issues": grid_issues,
        "actions": ["Schedule protection relay test"] if grid_issues else [],
    })

    # Health & Safety
    safety_status = "pass"
    safety_issues = []
    if capacity_mw >= 1:
        safety_issues.append("HSE notification required for construction/major works")
    safety_issues.append("CDM Regulations 2015 apply — Principal Designer required for works")
    safety_issues.append("Fire risk assessment required for battery/electrical installations")
    checks.append({
        "framework": "Health & Safety (CDM/HSE)",
        "status": safety_status,
        "issues": safety_issues,
        "actions": ["Review H&S file and ensure CDM compliance for planned works"],
    })

    # Overall verdict
    statuses = [c["status"] for c in checks]
    if "fail" in statuses:
        overall = "NON-COMPLIANT"
    elif "warning" in statuses:
        overall = "REQUIRES_ATTENTION"
    else:
        overall = "COMPLIANT"

    return {
        "overall_status": overall,
        "checks": checks,
        "asset_type": asset_type,
        "capacity_kw": capacity_kw,
        "total_issues": sum(len(c["issues"]) for c in checks),
    }


async def setup_legacy_table(conn) -> None:
    """Create the legacy_assets table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS legacy_assets (
            asset_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            TEXT NOT NULL,
            asset_type      TEXT NOT NULL DEFAULT 'solar_farm',
            capacity_kw     DOUBLE PRECISION DEFAULT 0,
            commissioning   DATE,
            status          TEXT DEFAULT 'operational',
            condition_score DOUBLE PRECISION,
            owner           TEXT,
            notes           TEXT,
            metadata        JSONB DEFAULT '{}',
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            geometry        GEOMETRY(Point, 27700)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_legacy_assets_geom
        ON legacy_assets USING GIST (geometry)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_legacy_assets_type
        ON legacy_assets (asset_type)
    """)


async def seed_sample_legacy_assets(conn) -> None:
    """Seed sample UK legacy energy assets for demo purposes."""
    count = await conn.fetchval("SELECT count(*) FROM legacy_assets")
    if count > 0:
        return

    samples = [
        ("Westmill Solar Park", "solar_farm", 5000, "2011-03-15", 52.2546, -1.6804),
        ("Swindon Solar Farm", "solar_farm", 4800, "2013-06-20", 51.5558, -1.7797),
        ("Shotwick Solar Park", "solar_farm", 72000, "2016-09-01", 53.2240, -3.0320),
        ("Bradenstoke Substation", "substation", 33000, "1998-01-01", 51.5029, -1.9445),
        ("Melksham Grid Battery", "battery_storage", 25000, "2020-11-15", 51.3773, -2.1383),
        ("Goonhilly Wind Farm", "wind_farm", 6000, "2004-07-01", 50.0490, -5.1810),
        ("Pen y Cymoedd Wind Farm", "wind_farm", 228000, "2017-04-01", 51.7439, -3.5642),
        ("Leighton Buzzard BESS", "battery_storage", 6000, "2014-12-01", 51.9167, -0.6597),
    ]

    for name, atype, cap, comm, lat, lon in samples:
        lifecycle = UK_ASSET_LIFECYCLES.get(atype, UK_ASSET_LIFECYCLES["solar_farm"])
        try:
            comm_date = date.fromisoformat(comm)
        except ValueError:
            comm_date = date(2015, 1, 1)
        age = (date.today() - comm_date).days / 365.25
        condition = max(0, 100 - (age / lifecycle["design_life_years"]) * 50
                        - lifecycle["degradation_pct_yr"] * age)
        status = "operational" if condition >= 40 else "degraded"

        await conn.execute("""
            INSERT INTO legacy_assets (name, asset_type, capacity_kw, commissioning, status, condition_score, geometry)
            VALUES ($1, $2, $3, $4, $5, $6,
                    ST_Transform(ST_SetSRID(ST_MakePoint($7, $8), 4326), 27700))
            ON CONFLICT DO NOTHING
        """, name, atype, cap, comm_date, status, round(condition, 1), lon, lat)
