"""
RIIO-ED2 Price Control Tracker — DNO business plans, connection charging, network investment.

Tracks the 2023-2028 RIIO-ED2 price control for all 6 UK DNOs.
Provides developer-relevant analysis of how price control outcomes
affect connection costs, capacity, and timelines.
"""
from __future__ import annotations
import logging
from typing import Any

log = logging.getLogger("princeps.riio_tracker")

# ═══════════════════════════════════════════════════════════════
#  RIIO-ED2 DATA (Ofgem Final Determinations, Nov 2022)
# ═══════════════════════════════════════════════════════════════

RIIO_ED2 = {
    "UKPN": {
        "full_name": "UK Power Networks",
        "licence_areas": ["EPN (East)", "LPN (London)", "SPN (South East)"],
        "region": "South East England & London",
        "totex_allowance_bn": 6.2,
        "base_revenue_bn_yr": 1.24,
        "connection_volumes": {
            "solar_gw": 5.5, "bess_gw": 3.2, "wind_gw": 0.3,
            "ev_charge_points": 500000, "heat_pumps": 400000,
        },
        "load_growth_pct_yr": 1.8,
        "dso_maturity": "Advanced",
        "flexibility_spend_m": 120,
        "strategic_investment_m": 450,
        "innovation_m": 38,
        "connection_charging": {
            "application_fee_gbp": {"demand_lv": 350, "generation_lv": 350, "hv": 1500, "ehv": 2500},
            "cost_per_km_11kv": 80000,
            "cost_per_km_33kv": 150000,
            "cost_per_km_132kv": 500000,
            "reinforcement_policy": "Shallow + partial reinforcement charges",
            "queue_management": "Milestone-based with 12-month planning consent requirement",
        },
        "key_investments": [
            "London Power Tunnels Phase 2 (£1.1bn)",
            "EV network readiness (£320m)",
            "132kV network reinforcement (£180m)",
        ],
    },
    "SSEN": {
        "full_name": "Scottish and Southern Electricity Networks",
        "licence_areas": ["SSEH (North Scotland)", "SSES (Central Southern)"],
        "region": "North Scotland & Central Southern England",
        "totex_allowance_bn": 3.8,
        "base_revenue_bn_yr": 0.76,
        "connection_volumes": {
            "solar_gw": 2.8, "bess_gw": 1.5, "wind_gw": 3.2,
            "ev_charge_points": 180000, "heat_pumps": 220000,
        },
        "load_growth_pct_yr": 2.1,
        "dso_maturity": "Developing",
        "flexibility_spend_m": 65,
        "strategic_investment_m": 280,
        "innovation_m": 22,
        "connection_charging": {
            "application_fee_gbp": {"demand_lv": 300, "generation_lv": 300, "hv": 1200, "ehv": 2000},
            "cost_per_km_11kv": 85000,
            "cost_per_km_33kv": 160000,
            "cost_per_km_132kv": 520000,
            "reinforcement_policy": "Shallow charging + ANM flexible connections",
            "queue_management": "Capacity-based allocation with use-it-or-lose-it",
        },
        "key_investments": [
            "Subsea cable replacements (Scottish islands)",
            "Net Zero Fund (£200m)",
            "33kV automation programme",
        ],
    },
    "NPg": {
        "full_name": "Northern Powergrid",
        "licence_areas": ["NPgN (North East)", "NPgY (Yorkshire)"],
        "region": "North East England & Yorkshire",
        "totex_allowance_bn": 2.6,
        "base_revenue_bn_yr": 0.52,
        "connection_volumes": {
            "solar_gw": 1.2, "bess_gw": 0.8, "wind_gw": 1.5,
            "ev_charge_points": 120000, "heat_pumps": 150000,
        },
        "load_growth_pct_yr": 1.5,
        "dso_maturity": "Developing",
        "flexibility_spend_m": 45,
        "strategic_investment_m": 180,
        "innovation_m": 18,
        "connection_charging": {
            "application_fee_gbp": {"demand_lv": 280, "generation_lv": 280, "hv": 1100, "ehv": 1800},
            "cost_per_km_11kv": 75000,
            "cost_per_km_33kv": 140000,
            "cost_per_km_132kv": 480000,
            "reinforcement_policy": "Shallow charging",
            "queue_management": "Standard queue with annual review",
        },
        "key_investments": [
            "Smart grid automation (£120m)",
            "Flexibility procurement via Piclo Flex",
            "Teesside industrial decarbonisation support",
        ],
    },
    "NGED": {
        "full_name": "National Grid Electricity Distribution",
        "licence_areas": ["WMID (West Midlands)", "EMID (East Midlands)", "SWALES (South Wales)", "SWEST (South West)"],
        "region": "Midlands, South Wales & South West",
        "totex_allowance_bn": 5.4,
        "base_revenue_bn_yr": 1.08,
        "connection_volumes": {
            "solar_gw": 4.2, "bess_gw": 2.5, "wind_gw": 1.8,
            "ev_charge_points": 350000, "heat_pumps": 300000,
        },
        "load_growth_pct_yr": 1.9,
        "dso_maturity": "Advanced",
        "flexibility_spend_m": 95,
        "strategic_investment_m": 380,
        "innovation_m": 30,
        "connection_charging": {
            "application_fee_gbp": {"demand_lv": 320, "generation_lv": 320, "hv": 1300, "ehv": 2200},
            "cost_per_km_11kv": 78000,
            "cost_per_km_33kv": 148000,
            "cost_per_km_132kv": 490000,
            "reinforcement_policy": "Shallow + strategic investment for net zero zones",
            "queue_management": "Queue reform with gate closure process",
        },
        "key_investments": [
            "132kV capacity uplift programme (£280m)",
            "South Wales industrial decarbonisation",
            "Smart meter data platform",
        ],
    },
    "SPEN": {
        "full_name": "SP Energy Networks",
        "licence_areas": ["SPD (South Scotland)", "SPM (Merseyside & North Wales)"],
        "region": "South Scotland, Merseyside & North Wales",
        "totex_allowance_bn": 3.1,
        "base_revenue_bn_yr": 0.62,
        "connection_volumes": {
            "solar_gw": 1.0, "bess_gw": 0.6, "wind_gw": 2.5,
            "ev_charge_points": 100000, "heat_pumps": 130000,
        },
        "load_growth_pct_yr": 1.6,
        "dso_maturity": "Developing",
        "flexibility_spend_m": 40,
        "strategic_investment_m": 200,
        "innovation_m": 15,
        "connection_charging": {
            "application_fee_gbp": {"demand_lv": 300, "generation_lv": 300, "hv": 1200, "ehv": 2000},
            "cost_per_km_11kv": 82000,
            "cost_per_km_33kv": 155000,
            "cost_per_km_132kv": 510000,
            "reinforcement_policy": "Shallow charging",
            "queue_management": "Standard queue management",
        },
        "key_investments": [
            "Renewables integration (Scottish wind corridor)",
            "EV ready network programme",
            "Cross-border interconnection upgrades",
        ],
    },
    "ENWL": {
        "full_name": "Electricity North West",
        "licence_areas": ["ENWL (North West England)"],
        "region": "North West England (Greater Manchester, Lancashire, Cumbria)",
        "totex_allowance_bn": 1.8,
        "base_revenue_bn_yr": 0.36,
        "connection_volumes": {
            "solar_gw": 0.6, "bess_gw": 0.4, "wind_gw": 0.8,
            "ev_charge_points": 80000, "heat_pumps": 100000,
        },
        "load_growth_pct_yr": 1.4,
        "dso_maturity": "Early",
        "flexibility_spend_m": 25,
        "strategic_investment_m": 120,
        "innovation_m": 12,
        "connection_charging": {
            "application_fee_gbp": {"demand_lv": 260, "generation_lv": 260, "hv": 1000, "ehv": 1600},
            "cost_per_km_11kv": 72000,
            "cost_per_km_33kv": 135000,
            "cost_per_km_132kv": 460000,
            "reinforcement_policy": "Shallow charging, competitive in pricing",
            "queue_management": "Standard queue",
        },
        "key_investments": [
            "Manchester industrial decarbonisation hub",
            "Smart street programme",
            "Network resilience (flood protection)",
        ],
    },
}


def get_riio_overview() -> dict:
    """RIIO-ED2 overview across all 6 DNOs."""
    overview = []
    for dno_code, data in RIIO_ED2.items():
        overview.append({
            "dno": dno_code,
            "full_name": data["full_name"],
            "region": data["region"],
            "totex_bn": data["totex_allowance_bn"],
            "load_growth_pct_yr": data["load_growth_pct_yr"],
            "dso_maturity": data["dso_maturity"],
            "solar_pipeline_gw": data["connection_volumes"]["solar_gw"],
            "bess_pipeline_gw": data["connection_volumes"]["bess_gw"],
            "flexibility_spend_m": data["flexibility_spend_m"],
        })

    total_totex = sum(d["totex_allowance_bn"] for d in RIIO_ED2.values())
    total_solar = sum(d["connection_volumes"]["solar_gw"] for d in RIIO_ED2.values())
    total_bess = sum(d["connection_volumes"]["bess_gw"] for d in RIIO_ED2.values())

    return {
        "period": "2023-2028",
        "dnos": overview,
        "totals": {
            "total_totex_bn": round(total_totex, 1),
            "total_solar_pipeline_gw": round(total_solar, 1),
            "total_bess_pipeline_gw": round(total_bess, 1),
            "total_flexibility_spend_m": sum(d["flexibility_spend_m"] for d in RIIO_ED2.values()),
        },
    }


def get_dno_detail(dno: str) -> dict:
    """Detailed RIIO-ED2 metrics for a specific DNO."""
    dno_upper = dno.upper()
    if dno_upper not in RIIO_ED2:
        return {"error": f"Unknown DNO: {dno}. Valid: {', '.join(RIIO_ED2.keys())}"}
    return {"dno": dno_upper, **RIIO_ED2[dno_upper]}


def get_connection_charging(dno: str = None) -> dict:
    """Current connection charging rates by DNO."""
    if dno:
        dno_upper = dno.upper()
        if dno_upper in RIIO_ED2:
            return {"dno": dno_upper, **RIIO_ED2[dno_upper]["connection_charging"]}
        return {"error": f"Unknown DNO: {dno}"}

    # All DNOs comparison
    comparison = []
    for code, data in RIIO_ED2.items():
        cc = data["connection_charging"]
        comparison.append({
            "dno": code,
            "name": data["full_name"],
            "11kv_per_km": cc["cost_per_km_11kv"],
            "33kv_per_km": cc["cost_per_km_33kv"],
            "132kv_per_km": cc["cost_per_km_132kv"],
            "reinforcement_policy": cc["reinforcement_policy"],
            "queue_management": cc["queue_management"],
        })

    # Find cheapest/most expensive
    cheapest_33 = min(comparison, key=lambda c: c["33kv_per_km"])
    most_expensive_33 = max(comparison, key=lambda c: c["33kv_per_km"])

    return {
        "comparison": comparison,
        "cheapest_33kv": {"dno": cheapest_33["dno"], "cost": cheapest_33["33kv_per_km"]},
        "most_expensive_33kv": {"dno": most_expensive_33["dno"], "cost": most_expensive_33["33kv_per_km"]},
        "note": "Rates are indicative — actual charges depend on specific connection works required",
    }


def get_developer_impact(lat: float, lon: float) -> dict:
    """What RIIO-ED2 means for a specific site location."""
    # Determine DNO from approximate geographic mapping
    dno_code = _lat_lon_to_dno(lat, lon)
    dno_data = RIIO_ED2.get(dno_code, RIIO_ED2["UKPN"])

    cc = dno_data["connection_charging"]
    cv = dno_data["connection_volumes"]

    impact = {
        "site": {"lat": lat, "lon": lon},
        "dno": dno_code,
        "dno_name": dno_data["full_name"],
        "region": dno_data["region"],
        "connection_costs": {
            "11kv_per_km": cc["cost_per_km_11kv"],
            "33kv_per_km": cc["cost_per_km_33kv"],
            "132kv_per_km": cc["cost_per_km_132kv"],
            "reinforcement_policy": cc["reinforcement_policy"],
            "queue_policy": cc["queue_management"],
        },
        "capacity_context": {
            "solar_pipeline_gw": cv["solar_gw"],
            "bess_pipeline_gw": cv["bess_gw"],
            "load_growth_pct_yr": dno_data["load_growth_pct_yr"],
            "note": f"{dno_data['full_name']} forecasts {cv['solar_gw']}GW solar and {cv['bess_gw']}GW BESS connections in RIIO-ED2",
        },
        "dso_services": {
            "maturity": dno_data["dso_maturity"],
            "flexibility_spend_m": dno_data["flexibility_spend_m"],
            "note": f"DSO maturity: {dno_data['dso_maturity']}. Flexibility services budget: £{dno_data['flexibility_spend_m']}m",
        },
        "investment_context": {
            "totex_allowance_bn": dno_data["totex_allowance_bn"],
            "strategic_investment_m": dno_data["strategic_investment_m"],
            "key_investments": dno_data["key_investments"],
        },
        "developer_recommendations": _developer_recommendations(dno_code, dno_data),
    }

    return impact


def _developer_recommendations(dno_code: str, data: dict) -> list[str]:
    """Generate actionable recommendations based on RIIO-ED2 outcomes."""
    recs = []
    cc = data["connection_charging"]

    if data["dso_maturity"] == "Advanced":
        recs.append(f"{data['full_name']} has advanced DSO capabilities — explore flexibility services revenue (£{data['flexibility_spend_m']}m budget)")
    if data["load_growth_pct_yr"] > 1.7:
        recs.append(f"High load growth ({data['load_growth_pct_yr']}%/yr) — reinforcement likely, consider timing of connection application")
    if "ANM" in cc.get("reinforcement_policy", ""):
        recs.append("ANM flexible connections available — consider flexible export to avoid reinforcement costs")
    if "milestone" in cc.get("queue_management", "").lower():
        recs.append("Milestone-based queue management — ensure planning consent within required timeline to retain queue position")
    if data["connection_volumes"]["bess_gw"] > 2:
        recs.append(f"Large BESS pipeline ({data['connection_volumes']['bess_gw']}GW) — consider co-location with solar for shared connection")

    return recs


def _lat_lon_to_dno(lat: float, lon: float) -> str:
    """Approximate lat/lon to DNO licence area."""
    if lat > 56:
        return "SSEN"
    if lat > 55 and lon < -3:
        return "SPEN"
    if lat > 54.5:
        return "NPg"
    if lat > 53.5 and lon < -1.5:
        return "ENWL"
    if lat > 53.5:
        return "NPg"
    if lat > 52 and lon < -2.5:
        return "NGED"
    if lat > 51.5 and lon < -1:
        return "NGED"
    if lat > 51 and lon > 0.5:
        return "UKPN"
    if lat > 51:
        return "UKPN"
    if lon < -3:
        return "NGED"
    return "SSEN" if lon < -1 else "UKPN"
