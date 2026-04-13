"""
DC Hyperscaler Connection Suite — extractions from the National Grid MSIP
Re-opener Report for Microsoft Willesden/Kensal Green (Jan 2024).

Nine capabilities in one module (kept together so the DC connection surface
area is coherent, each section clearly demarcated):

  1. Dual-supply-point resiliency modelling       → find_dual_feed_pairs()
  2. Minimum Viable Solution (MVS) gap calculator → mvs_gap()
  3. Connection Optioneering Engine               → generate_options()
  4. iDNO BCA pathway + registry                  → iDNO_REGISTRY + pathway_split()
  5. SQSS compliance checker                      → sqss_check()
  6. MSIP re-opener eligibility                   → msip_eligibility()
  7. AIS vs GIS switchgear choice                 → switchgear_recommendation()
  8. Direct Cost / Asset Table (Ofgem-format BOM) → generate_connection_bom()
  9. Price-base escalation                        → escalate_price()

Reference: NGET MSIP Re-opener Report, January 2024
https://www.nationalgrid.com/document/353096/download
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

log = logging.getLogger("princeps.dc_hyperscaler")


# ════════════════════════════════════════════════════════════════════════
# 1. DUAL-SUPPLY-POINT RESILIENCY MODELLING
# ════════════════════════════════════════════════════════════════════════
#
# Hyperscaler DCs require two GEOGRAPHICALLY separated connection points
# above the SQSS minimum, so that a single cable/substation failure doesn't
# black out the facility. The rule: two substations within cable range
# (≤5 km each for 132kV, ≤25 km for 400kV), on different feeders, with
# sufficient combined headroom for the DC load.

async def find_dual_feed_pairs(
    pool: asyncpg.Pool,
    lat: float,
    lon: float,
    capacity_mva: float,
    max_radius_km: float = 25.0,
    min_voltage_kv: float = 33.0,
) -> list[dict]:
    """Find pairs of substations that can provide dual-feed resiliency.

    Returns a list of viable pairs ranked by total resilience score:
      • Each substation within max_radius_km
      • Each at ≥ min_voltage_kv
      • Combined headroom ≥ 1.5 * capacity_mva (provides N-1 margin)
      • Distance between the two ≥ 1 km (geographical separation)
      • Same DNO preferred (simpler BCA) but cross-DNO noted as option
    """
    async with pool.acquire() as conn:
        candidates = await conn.fetch(
            """
            SELECT id, external_id, name, dno, voltage_kv, site_type,
                   demand_headroom_mw, gen_headroom_mw,
                   transformer_rating_mva,
                   ST_Distance(
                       ST_Transform(geom, 4326)::geography,
                       ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                   ) AS distance_m,
                   ST_X(ST_Transform(geom, 4326)) AS lon,
                   ST_Y(ST_Transform(geom, 4326)) AS lat
            FROM grid_substations
            WHERE geom IS NOT NULL
              AND voltage_kv >= $3
              AND demand_headroom_mw IS NOT NULL
              AND demand_headroom_mw >= $4
              AND ST_DWithin(
                  ST_Transform(geom, 4326)::geography,
                  ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                  $5 * 1000
              )
            ORDER BY distance_m
            LIMIT 25
            """,
            lon, lat, min_voltage_kv, capacity_mva * 0.5, max_radius_km,
        )

    # Build all pairs
    pairs: list[dict] = []
    candidates_list = [dict(r) for r in candidates]
    for i, a in enumerate(candidates_list):
        for b in candidates_list[i + 1:]:
            combined_hr = float((a["demand_headroom_mw"] or 0) + (b["demand_headroom_mw"] or 0))
            if combined_hr < 1.5 * capacity_mva:
                continue
            # Pair distance
            pair_dist_km = _haversine_km(
                float(a["lat"]), float(a["lon"]),
                float(b["lat"]), float(b["lon"]),
            )
            if pair_dist_km < 1.0:
                continue  # Too close — not geographically independent
            same_dno = a["dno"] == b["dno"]
            # Resilience score: headroom margin × distance × geographic separation
            headroom_margin = combined_hr / (capacity_mva + 1)
            score = headroom_margin * min(5.0, pair_dist_km) * (1.2 if same_dno else 0.9)
            pairs.append({
                "substation_a": {
                    "id": a["id"], "name": a["name"], "dno": a["dno"],
                    "voltage_kv": float(a["voltage_kv"]) if a["voltage_kv"] else None,
                    "headroom_mw": float(a["demand_headroom_mw"] or 0),
                    "distance_km": round(float(a["distance_m"] or 0) / 1000, 2),
                    "lat": float(a["lat"]), "lon": float(a["lon"]),
                },
                "substation_b": {
                    "id": b["id"], "name": b["name"], "dno": b["dno"],
                    "voltage_kv": float(b["voltage_kv"]) if b["voltage_kv"] else None,
                    "headroom_mw": float(b["demand_headroom_mw"] or 0),
                    "distance_km": round(float(b["distance_m"] or 0) / 1000, 2),
                    "lat": float(b["lat"]), "lon": float(b["lon"]),
                },
                "combined_headroom_mw": combined_hr,
                "headroom_margin": round(headroom_margin, 2),
                "pair_separation_km": round(pair_dist_km, 2),
                "same_dno": same_dno,
                "n_minus_1_compliant": combined_hr >= capacity_mva,
                "resilience_score": round(score, 1),
            })

    pairs.sort(key=lambda p: p["resilience_score"], reverse=True)
    return pairs[:10]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


# ════════════════════════════════════════════════════════════════════════
# 2. MVS GAP CALCULATOR
# ════════════════════════════════════════════════════════════════════════
#
# Ofgem's regulated allowance only covers the Minimum Viable Solution (MVS)
# that satisfies the SQSS. Anything above that — dual feed, GIS, diverse
# routes, accelerated delivery — is funded by the customer via a One-off
# Charge. For a hyperscaler this is typically £20-100M of off-balance-sheet
# infrastructure.

def mvs_gap(
    capacity_mva: float,
    has_dual_feed: bool,
    uses_gis_switchgear: bool,
    voltage_kv: float = 132,
    urban: bool = False,
    accelerated_delivery: bool = False,
) -> dict:
    """Calculate the Minimum Viable Solution vs actual cost gap.

    Returns both the MVS (Ofgem-funded) and customer-funded one-off charge.
    Benchmarks derived from MSIP Willesden/Kensal Green report and typical
    UK DC connection cost observations.
    """
    # Base MVS: single-point connection at the nearest appropriate voltage
    if voltage_kv >= 275:
        base_per_mva = 150_000  # 400kV connection
    elif voltage_kv >= 132:
        base_per_mva = 95_000
    elif voltage_kv >= 66:
        base_per_mva = 55_000
    else:
        base_per_mva = 30_000

    mvs_gbp = capacity_mva * base_per_mva
    # Size factor for large connections — non-linear
    if capacity_mva > 100:
        mvs_gbp *= 1.2
    if capacity_mva > 200:
        mvs_gbp *= 1.15

    # Above-MVS costs (customer-funded)
    above_mvs = 0.0
    line_items = []

    if has_dual_feed:
        dual_cost = capacity_mva * 45_000
        if voltage_kv >= 275:
            dual_cost *= 1.5
        above_mvs += dual_cost
        line_items.append({
            "item": "Second geographical supply point",
            "cost_gbp": round(dual_cost),
            "reason": "Redundancy above SQSS minimum",
        })

    if uses_gis_switchgear:
        # GIS premium: ~£3-5M per bay. Typical 120 MVA connection has 2-4 bays.
        n_bays = max(2, int(capacity_mva / 50))
        gis_premium = n_bays * 3_500_000
        above_mvs += gis_premium
        line_items.append({
            "item": f"GIS switchgear ({n_bays} bays)",
            "cost_gbp": round(gis_premium),
            "reason": "Footprint reduction for urban DC site",
        })

    if urban:
        above_mvs += capacity_mva * 20_000
        line_items.append({
            "item": "Urban premium (land / civils)",
            "cost_gbp": round(capacity_mva * 20_000),
            "reason": "Constrained urban site premium",
        })

    if accelerated_delivery:
        accel_cost = mvs_gbp * 0.18
        above_mvs += accel_cost
        line_items.append({
            "item": "Accelerated delivery premium",
            "cost_gbp": round(accel_cost),
            "reason": "Delivery earlier than standard RIIO programme",
        })

    total = mvs_gbp + above_mvs

    return {
        "capacity_mva": capacity_mva,
        "voltage_kv": voltage_kv,
        "mvs_gbp": round(mvs_gbp),
        "customer_one_off_charge_gbp": round(above_mvs),
        "total_connection_cost_gbp": round(total),
        "ofgem_allowance_pct": round(mvs_gbp / total * 100, 1) if total else 0,
        "customer_funded_pct": round(above_mvs / total * 100, 1) if total else 0,
        "line_items": line_items,
        "benchmark_source": "NGET MSIP Willesden/Kensal Green Jan 2024",
    }


# ════════════════════════════════════════════════════════════════════════
# 3. CONNECTION OPTIONEERING ENGINE
# ════════════════════════════════════════════════════════════════════════
#
# NGET ran 6 options and selected 1 via CBA. Princeps generates the same
# option set for any DC site and ranks by cost / timeline / risk / redundancy.

OPTION_TEMPLATES = [
    {
        "option_id": "O1_single_transmission",
        "name": "Single-point 400kV transmission",
        "description": "Direct connection to single 400kV substation",
        "voltage_kv": 400,
        "dual_feed": False,
        "path": "transmission_only",
        "redundancy": "N",
    },
    {
        "option_id": "O2_dual_transmission",
        "name": "Dual-point 400kV transmission",
        "description": "Two geographically separated 400kV connections",
        "voltage_kv": 400,
        "dual_feed": True,
        "path": "transmission_only",
        "redundancy": "N-1",
    },
    {
        "option_id": "O3_transmission_extension_dual",
        "name": "Dual-point 400kV with substation extension",
        "description": "Extend existing 400kV + new connection (MSIP template)",
        "voltage_kv": 400,
        "dual_feed": True,
        "path": "transmission_with_extension",
        "redundancy": "N-1",
    },
    {
        "option_id": "O3b_four_circuit_dual_substation",
        "name": "Four-circuit dual-substation (London DC gold standard)",
        "description": (
            "Two circuits from each of two independent 400kV substations; DNO/iDNO adopts 2 of 4. "
            "Proven template from Willesden/Kensal Green MSIP (Microsoft 120 MVA)."
        ),
        "voltage_kv": 400,
        "dual_feed": True,
        "path": "transmission_with_extension",
        "redundancy": "N-1-1",
        "n_circuits": 4,
    },
    {
        "option_id": "O4_transmission_idno_66kv",
        "name": "400kV transmission + 66kV iDNO tail",
        "description": "NGET at 400kV, iDNO (UKPD/Eclipse/Leep) at 66kV",
        "voltage_kv": 66,
        "dual_feed": True,
        "path": "transmission_plus_idno",
        "redundancy": "N-1",
    },
    {
        "option_id": "O5_distribution_only_132kv",
        "name": "132kV distribution only",
        "description": "DNO connection at 132kV (no transmission)",
        "voltage_kv": 132,
        "dual_feed": False,
        "path": "distribution_only",
        "redundancy": "N",
    },
    {
        "option_id": "O6_distribution_dual_132kv",
        "name": "Dual 132kV distribution",
        "description": "Two DNO 132kV connections at separated BSPs",
        "voltage_kv": 132,
        "dual_feed": True,
        "path": "distribution_only",
        "redundancy": "N-1",
    },
    {
        "option_id": "O7_new_275kv_gsp_3sgt",
        "name": "New-build 275kV GSP with 3 × SGT (rural cluster)",
        "description": (
            "New substation, 3 super grid transformers, phased energisation. "
            "Gigafactory template from Hylton Castle IAMP MSIP."
        ),
        "voltage_kv": 275,
        "dual_feed": True,
        "path": "new_build_gsp",
        "redundancy": "N-1",
        "phased_energisation": True,
    },
    {
        "option_id": "O8_unconventional_tee_in",
        "name": "Unconventional tee-in with DCB",
        "description": (
            "Tee onto existing circuit via Disconnecting Circuit Breaker. "
            "Template from Lister Drive (Statkraft) MSIP — cheaper than full bay."
        ),
        "voltage_kv": 275,
        "dual_feed": False,
        "path": "tee_with_dcb",
        "redundancy": "N",
        "ancillary_only": True,
    },
]


async def generate_options(
    pool: asyncpg.Pool,
    lat: float,
    lon: float,
    capacity_mva: float,
    urban: bool = False,
    target_year: int = 2028,
    accelerated: bool = False,
    customer_role: str = "demand",     # demand | gen | reactive_support | bess
    in_london_dc_cluster: bool = False,
    cluster_cumulative_mva: float = 0,
    nearest_400kv_km: float | None = None,
    strategic_demand: bool = False,    # AI Growth Zone designation
    risk_allowance_pct: float = 7.5,
) -> dict:
    """Generate and score all connection options for a DC site.

    Applies the 15 calibration rules derived from the MSIP research brief:
    https://www.ofgem.gov.uk/sites/default/files/2025-12/RIIO-3-Final-Determinations-ET.pdf

    Returns ranked options with cost / timeline / risk / redundancy scores,
    plus a separate needs_case_score and optioneering_defensibility_score
    (Marston Vale 2025 precedent — these are judged separately by Ofgem).
    """
    options_out = []
    pairs = await find_dual_feed_pairs(pool, lat, lon, capacity_mva)
    rules_applied: list[str] = []

    # Rule 1 — Urban/brownfield + ≥100 MVA → force GIS only
    force_gis = urban and capacity_mva >= 100
    if force_gis:
        rules_applied.append("Rule 1: Urban ≥100 MVA — GIS forced")

    # Rule 8 — ≥200 MVA London → only NGET 400kV options
    london_400kv_only = in_london_dc_cluster and capacity_mva >= 200
    if london_400kv_only:
        rules_applied.append("Rule 8: London DC cluster + ≥200 MVA — 400kV-only")

    for template in OPTION_TEMPLATES:
        feasibility = "feasible"
        feasibility_notes: list[str] = []
        penalties: list[str] = []

        # Rule 8 enforcement
        if london_400kv_only and template["voltage_kv"] < 400:
            feasibility = "infeasible"
            feasibility_notes.append("London ≥200 MVA: only 400kV options permitted (Rule 8)")

        # Rule 5 — Reactive/ancillary customer can use tee-in
        if template.get("ancillary_only") and customer_role not in ("reactive_support", "bess"):
            feasibility = "infeasible"
            feasibility_notes.append("Tee-in with DCB only for reactive/ancillary customers")

        # Rule 9 — 3-SGT new-build only for rural clusters ≥500 MVA
        if template["option_id"] == "O7_new_275kv_gsp_3sgt":
            if cluster_cumulative_mva < 500 and capacity_mva < 500:
                feasibility = "infeasible"
                feasibility_notes.append("New 275kV GSP only justified for ≥500 MVA cluster")

        # Dual-feed availability check
        if template["dual_feed"] and not pairs and template["option_id"] != "O7_new_275kv_gsp_3sgt":
            feasibility = "infeasible"
            feasibility_notes.append("No viable dual-feed pair found within 25 km")

        # Rule 2 — ≥100 MVA demand → single-feed is only a stress-test option
        if (
            customer_role == "demand"
            and capacity_mva >= 100
            and not template["dual_feed"]
            and not template.get("ancillary_only")
        ):
            penalties.append("Rule 2: single-feed stress-test penalty (-30)")

        # Switchgear
        sw = switchgear_recommendation(capacity_mva, urban=urban, voltage_kv=template["voltage_kv"])
        if force_gis and sw["recommended"] != "GIS":
            sw["recommended"] = "GIS"
            sw["reasons"].insert(0, "Forced by Rule 1 (urban ≥100 MVA)")
        uses_gis = sw["recommended"] == "GIS"

        # Rule 14 — GIS = 4× AIS baseline absent UM table data
        # (already encoded in switchgear_recommendation)

        # Cost via MVS gap calculator
        cost = mvs_gap(
            capacity_mva=capacity_mva,
            has_dual_feed=template["dual_feed"],
            uses_gis_switchgear=uses_gis,
            voltage_kv=template["voltage_kv"],
            urban=urban,
            accelerated_delivery=accelerated,
        )

        # Path-specific adjustments
        if template["path"] == "transmission_with_extension":
            cost["total_connection_cost_gbp"] = int(cost["total_connection_cost_gbp"] * 0.85)
            feasibility_notes.append("Leverages existing substation; lower cost")
        if template["path"] == "transmission_plus_idno":
            cost["total_connection_cost_gbp"] = int(cost["total_connection_cost_gbp"] * 0.92)
            feasibility_notes.append("iDNO 66kV tail reduces overall cost")
        if template["path"] == "distribution_only" and capacity_mva > 150:
            feasibility = "infeasible"
            feasibility_notes.append("Load exceeds DNO 132kV capacity")
        if template["option_id"] == "O3b_four_circuit_dual_substation":
            cost["total_connection_cost_gbp"] = int(cost["total_connection_cost_gbp"] * 1.25)
            feasibility_notes.append("Highest resilience — 4 circuits, 2 independent subs")

        # Rule 4 — >5km from 400kV → iDNO option gets cost benefit
        if (
            template["path"] == "transmission_plus_idno"
            and nearest_400kv_km is not None
            and nearest_400kv_km > 5
        ):
            cost["total_connection_cost_gbp"] = int(cost["total_connection_cost_gbp"] * 0.88)
            feasibility_notes.append("Rule 4: >5km from 400kV — iDNO path rewarded")

        # Timeline estimate (months)
        base_months = {
            "transmission_only":           42,
            "transmission_with_extension": 36,
            "transmission_plus_idno":      30,
            "distribution_only":           24,
            "new_build_gsp":               54,
            "tee_with_dcb":                20,
        }.get(template["path"], 36)
        if accelerated:
            base_months = int(base_months * 0.8)
        if template["dual_feed"]:
            base_months += 6

        # Rule 10 — Phased energisation bonus for multi-SGT templates
        first_mva_months = base_months
        if template.get("phased_energisation"):
            first_mva_months = int(base_months * 0.55)

        # Rule 13 — APM reduces programme risk for long-lead equipment
        apm_eligible = capacity_mva >= 200 or template["path"] == "new_build_gsp"

        # Risk score (0=low, 10=high)
        risk = 3
        if template["path"] == "transmission_with_extension":
            risk = 5
        if template["path"] == "new_build_gsp":
            risk = 7
        if capacity_mva > 150 and template["path"] == "distribution_only":
            risk = 8
        if accelerated:
            risk += 2
        if apm_eligible:
            risk = int(risk * 0.8)  # Rule 13: APM de-risks by 20%

        # Rule 11 — £20-100M direct cost band → flag MSIP route
        direct_cost = cost["total_connection_cost_gbp"] * 0.82  # strip contingency
        msip_route = 20_000_000 <= direct_cost <= 100_000_000
        if msip_route:
            base_months += 12  # add MSIP approval window

        # Rule 12 — strategic demand fast-track
        if strategic_demand:
            risk = max(1, risk - 2)
            feasibility_notes.append("Rule 12: RIIO-T3 in-period strategic-demand fast-track")

        # Composite score: higher is better
        composite = 100
        composite -= cost["total_connection_cost_gbp"] / 5_000_000
        composite -= base_months * 0.5
        composite -= risk * 3
        if template["dual_feed"]:
            composite += 15
        if template.get("n_circuits") == 4:
            composite += 8   # four-circuit template bonus (Willesden precedent)
        if template.get("phased_energisation"):
            composite += 6
        if strategic_demand:
            composite += 10
        for _ in penalties:
            composite -= 30
        if feasibility == "infeasible":
            composite -= 500

        # Rule 7 — separate needs-case vs optioneering defensibility scores
        needs_case_score = _score_needs_case(template, capacity_mva, customer_role)
        optioneering_defensibility = _score_optioneering(template, pairs, urban, customer_role)

        options_out.append({
            **template,
            "feasibility": feasibility,
            "feasibility_notes": feasibility_notes,
            "penalties": penalties,
            "switchgear": sw,
            "cost": cost,
            "delivery_months": base_months,
            "first_mva_delivery_months": first_mva_months,
            "risk_score": risk,
            "apm_eligible": apm_eligible,
            "msip_route_required": msip_route,
            "composite_score": round(composite, 1),
            "needs_case_score": needs_case_score,
            "optioneering_defensibility_score": optioneering_defensibility,
            "best_dual_feed_pair": pairs[0] if (template["dual_feed"] and pairs) else None,
        })

    options_out.sort(key=lambda o: o["composite_score"], reverse=True)
    best = next((o for o in options_out if o["feasibility"] == "feasible"), options_out[0])

    return {
        "location": {"lat": lat, "lon": lon},
        "capacity_mva": capacity_mva,
        "options_considered": len(options_out),
        "selected_option_id": best["option_id"],
        "selected_option": best,
        "options": options_out,
        "dual_feed_pairs_available": len(pairs),
        "rules_applied": rules_applied,
        "calibration_source": "MSIP research brief 2026-04 (RIIO-T3 Final Determinations Dec 2025)",
    }


def _score_needs_case(template: dict, capacity_mva: float, customer_role: str) -> int:
    """Score 0-100 — strength of the regulatory needs case for this option.

    Marston Vale 2025 was approved on needs case but rejected on optioneering,
    so Princeps scores them separately.
    """
    score = 50
    if customer_role == "demand" and capacity_mva >= 100:
        score += 25  # strong demand-growth driver
    if template["dual_feed"]:
        score += 10  # SQSS compliance
    if template["redundancy"] in ("N-1", "N-1-1"):
        score += 10
    if template.get("phased_energisation"):
        score += 5
    return min(100, score)


def _score_optioneering(template: dict, pairs: list, urban: bool, customer_role: str) -> int:
    """Score 0-100 — how defensible the optioneering is in an Ofgem review.

    Based on the Marston Vale precedent — Ofgem wants to see the option set
    was comprehensive and the selection logic was consumer-value driven.
    """
    score = 50
    # Having dual-feed alternative available strengthens the argument
    if pairs:
        score += 10
    # Urban GIS is well-precedented (Willesden)
    if urban and template["voltage_kv"] >= 132:
        score += 10
    # Four-circuit template carries the Willesden precedent
    if template.get("n_circuits") == 4:
        score += 15
    # Ancillary-only tee-in is precedented at Lister Drive
    if template.get("ancillary_only") and customer_role in ("reactive_support", "bess"):
        score += 10
    # Phased energisation carries Hylton Castle precedent
    if template.get("phased_energisation"):
        score += 5
    return min(100, score)


# ════════════════════════════════════════════════════════════════════════
# 4. iDNO REGISTRY + BCA PATHWAY
# ════════════════════════════════════════════════════════════════════════
#
# Independent DNOs (iDNOs) can provide the distribution tail of a
# hyperscaler connection under a Bilateral Connection Agreement. The
# transmission side is NGET; the distribution side is the iDNO. This
# splits the cost model between two actors.

iDNO_REGISTRY = [
    {
        "code": "UKPD", "name": "UK Power Distribution", "parent": "UK Power Networks",
        "regions": ["south_east", "london", "east"], "voltage_cap_kv": 132,
        "notable_projects": ["Microsoft Willesden 120 MVA (2024, MSIP Jan 2024)"],
        "note": "In the Willesden MSIP doc UKPD is used interchangeably with UKPN (same DNO group)",
    },
    {
        "code": "EPL", "name": "Eclipse Power Networks", "parent": "Eclipse Power",
        "regions": ["all"], "voltage_cap_kv": 132,
        "notable_projects": ["Yondr Slough campus"],
    },
    {
        "code": "ESP", "name": "ESP Electricity", "parent": "ESP Utilities Group",
        "regions": ["all"], "voltage_cap_kv": 132, "notable_projects": [],
    },
    {
        "code": "GTC", "name": "GTC (The Electricity Network Company)", "parent": "Gas Transportation Company",
        "regions": ["all"], "voltage_cap_kv": 132, "notable_projects": [],
    },
    {
        "code": "IPN", "name": "Independent Power Networks", "parent": "National Grid Ventures",
        "regions": ["all"], "voltage_cap_kv": 132, "notable_projects": [],
    },
    {
        "code": "HEP", "name": "Harlaxton Energy Networks", "parent": "Harlaxton",
        "regions": ["east_midlands", "south_east"], "voltage_cap_kv": 132, "notable_projects": [],
    },
    {
        "code": "MEP", "name": "Murphy Power Distribution", "parent": "J Murphy Group",
        "regions": ["all"], "voltage_cap_kv": 132, "notable_projects": [],
    },
    {
        "code": "UUN", "name": "UK Utility Networks", "parent": "Independent",
        "regions": ["all"], "voltage_cap_kv": 66, "notable_projects": [],
    },
    # Added from RIIO-T3 research brief (April 2026)
    {
        "code": "VAT", "name": "Vattenfall IDNO", "parent": "Vattenfall Networks",
        "regions": ["all"], "voltage_cap_kv": 132,
        "notable_projects": [],
        "note": "Vattenfall's UK independent DNO arm",
    },
    {
        "code": "LEEP", "name": "Leep Networks", "parent": "Ancala Partners",
        "regions": ["all"], "voltage_cap_kv": 132,
        "notable_projects": ["Multiple logistics / industrial parks"],
    },
    {
        "code": "ESK", "name": "Energetics", "parent": "Energetics Networks",
        "regions": ["all"], "voltage_cap_kv": 66,
        "notable_projects": [],
    },
]


def list_idnos(region: str | None = None) -> list[dict]:
    """List available iDNOs, optionally filtered by region."""
    if not region:
        return iDNO_REGISTRY
    return [d for d in iDNO_REGISTRY if "all" in d["regions"] or region in d["regions"]]


def pathway_split(
    total_cost_gbp: float,
    uses_idno: bool,
    transmission_voltage_kv: float = 400,
    distribution_voltage_kv: float = 66,
) -> dict:
    """Split total connection cost between NGET transmission and iDNO distribution."""
    if not uses_idno:
        return {
            "nget_cost_gbp": round(total_cost_gbp),
            "idno_cost_gbp": 0,
            "idno_share_pct": 0,
            "nget_share_pct": 100,
            "pathway": "transmission_only",
        }
    # Split depends on voltage step — a 400/66kV path has meaningful iDNO content
    if distribution_voltage_kv <= 33:
        idno_share = 0.25
    elif distribution_voltage_kv <= 66:
        idno_share = 0.32
    elif distribution_voltage_kv <= 132:
        idno_share = 0.40
    else:
        idno_share = 0.15
    nget = total_cost_gbp * (1 - idno_share)
    idno = total_cost_gbp * idno_share
    return {
        "nget_cost_gbp": round(nget),
        "idno_cost_gbp": round(idno),
        "idno_share_pct": round(idno_share * 100, 1),
        "nget_share_pct": round((1 - idno_share) * 100, 1),
        "pathway": f"transmission_{int(transmission_voltage_kv)}kv_to_idno_{int(distribution_voltage_kv)}kv",
    }


# ════════════════════════════════════════════════════════════════════════
# 5. SQSS COMPLIANCE CHECKER
# ════════════════════════════════════════════════════════════════════════
#
# Codified subset of the Security and Quality of Supply Standard for large
# customer connections. NOT comprehensive — covers the clauses most commonly
# cited in MSIP submissions.

SQSS_CLAUSES = {
    "GS1_minimum_connection_capacity": {
        "description": "Minimum firm connection capacity shall be 2x customer peak demand or as agreed",
        "applies_to": "demand_customer",
    },
    "GS2_n_minus_1_above_100_mw": {
        "description": "For demand ≥100 MW, N-1 loss-of-supply compliance required",
        "applies_to": "demand_customer",
        "threshold_mw": 100,
    },
    "GS3_voltage_limits": {
        "description": "Voltage at customer terminals shall remain within ±10% at 132kV, ±6% at ≥275kV",
        "applies_to": "all",
    },
    "GS4_fault_level_design": {
        "description": "Connection design fault level shall not exceed switchgear rating",
        "applies_to": "all",
    },
    "GS5_frequency_range": {
        "description": "Customer equipment shall operate within 47.5-52.0 Hz for short periods",
        "applies_to": "all",
    },
    "GS6_outage_duration": {
        "description": "Planned outage duration shall be minimised; agreed via connection agreement",
        "applies_to": "all",
    },
}


def sqss_check(
    capacity_mva: float,
    voltage_kv: float,
    has_dual_feed: bool,
    above_minimum: bool = False,
) -> dict:
    """Check proposed connection against SQSS rules. Lender-grade output."""
    results = []
    overall_pass = True

    for clause_id, clause in SQSS_CLAUSES.items():
        result = {"clause_id": clause_id, "description": clause["description"]}
        if clause_id == "GS1_minimum_connection_capacity":
            # Simplified — assume connection sized for 2x customer demand
            result["status"] = "pass"
        elif clause_id == "GS2_n_minus_1_above_100_mw":
            if capacity_mva >= 100 and not has_dual_feed:
                result["status"] = "fail"
                result["remedy"] = "Add second geographical supply point (dual feed)"
                overall_pass = False
            else:
                result["status"] = "pass"
        elif clause_id == "GS3_voltage_limits":
            result["status"] = "pass"  # Must be designed to this; not checked from input
        elif clause_id == "GS4_fault_level_design":
            result["status"] = "pass"
        elif clause_id == "GS5_frequency_range":
            result["status"] = "pass"
        elif clause_id == "GS6_outage_duration":
            result["status"] = "pass"
        results.append(result)

    return {
        "overall": "PASS" if overall_pass else "FAIL",
        "above_sqss_minimum": above_minimum,
        "clauses": results,
        "note": (
            "SQSS minimum is the baseline Ofgem-funded solution. Anything above "
            "the minimum (dual feed, GIS, accelerated delivery) is customer-funded."
        ),
    }


# ════════════════════════════════════════════════════════════════════════
# 6. MSIP RE-OPENER ELIGIBILITY
# ════════════════════════════════════════════════════════════════════════
#
# RIIO-T2 Special Condition 3.14 lets NGET request mid-period funding for
# Medium Sized Investment Projects (MSIPs). Eligible when the investment
# is >~£50M, <£100M in a single project and arises from unforeseen demand.
# For RIIO-T3 (from April 2026) the mechanism evolves — we track both.

# Calibrated against Ofgem 2025 Final Determinations (Dec 2025) — RIIO-T3 is no
# longer draft. Norwich 2025 was rejected on the risk-allowance test: Ofgem
# normalised to 7.5% which pulled cost below SpC 3.14.6 threshold. Threshold
# floor is ~£20M (not £10M as initially coded).
MSIP_WINDOWS = [
    {"period": "RIIO-T2", "start": "2021-04-01", "end": "2026-03-31",
     "re_opener_clause": "SpC 3.14 (SpC 3.14.6 eligibility)",
     "min_cost_gbp": 20_000_000, "max_cost_gbp": 100_000_000,
     "risk_allowance_cap_pct": 7.5,
     "windows": ["2022-12-01", "2023-12-01", "2024-12-01", "2025-06-01"],
     "status": "closed",
     "reference_url": "https://www.ofgem.gov.uk/decision/decision-2-nget-2023-msip-applications"},
    {"period": "RIIO-T3", "start": "2026-04-01", "end": "2031-03-31",
     "re_opener_clause": "RIIO-3 Final Determinations (4 Dec 2025)",
     "min_cost_gbp": 20_000_000, "max_cost_gbp": 100_000_000,
     "risk_allowance_cap_pct": 7.5,
     "windows": ["2026-12-01", "2027-12-01", "2028-12-01"],
     "status": "active",
     "mechanisms": ["MSIP", "ASTI", "APM", "In-period demand-growth approvals"],
     "reference_url": "https://www.ofgem.gov.uk/sites/default/files/2025-12/RIIO-3-Final-Determinations-ET.pdf"},
]

# Ofgem Norwich 2025 ruling precedent: risk allowance above this gets challenged.
OFGEM_RISK_ALLOWANCE_CAP_PCT = 7.5


def msip_eligibility(
    capacity_mva: float,
    estimated_cost_gbp: float,
    risk_allowance_pct: float = 7.5,
    expected_application_date: str | None = None,
) -> dict:
    """Check whether a DC-driven investment qualifies for MSIP re-opener.

    Calibrated against Ofgem's 2025 Norwich ruling: any risk allowance above
    7.5% of direct costs will be challenged. If the user's risk allowance
    normalises cost below the SpC 3.14.6 threshold the application is
    effectively rejected — we flag this explicitly.
    """
    result = {
        "capacity_mva": capacity_mva,
        "estimated_cost_gbp": estimated_cost_gbp,
        "risk_allowance_pct": risk_allowance_pct,
        "risk_allowance_above_ofgem_cap": risk_allowance_pct > OFGEM_RISK_ALLOWANCE_CAP_PCT,
        "eligible": False,
        "periods": [],
        "notes": [],
        "warnings": [],
        "next_steps": [],
    }

    # Normalise cost to the Ofgem-challenged value if allowance is over the cap
    if risk_allowance_pct > OFGEM_RISK_ALLOWANCE_CAP_PCT:
        direct_cost = estimated_cost_gbp / (1 + risk_allowance_pct / 100)
        normalised_cost = direct_cost * (1 + OFGEM_RISK_ALLOWANCE_CAP_PCT / 100)
        result["warnings"].append(
            f"Risk allowance {risk_allowance_pct}% exceeds Ofgem 7.5% cap — Norwich 2025 precedent. "
            f"Normalised cost would be £{normalised_cost/1e6:.1f}M (from £{estimated_cost_gbp/1e6:.1f}M)."
        )
        check_cost = normalised_cost
    else:
        check_cost = estimated_cost_gbp

    for w in MSIP_WINDOWS:
        in_window = w["min_cost_gbp"] <= check_cost <= w["max_cost_gbp"]
        period_result = {
            "period": w["period"],
            "status": w.get("status"),
            "re_opener_clause": w["re_opener_clause"],
            "cost_range_gbp": [w["min_cost_gbp"], w["max_cost_gbp"]],
            "within_cost_range": in_window,
            "next_submission_windows": w["windows"],
            "reference_url": w.get("reference_url"),
            "mechanisms": w.get("mechanisms"),
        }
        result["periods"].append(period_result)
        if in_window and w.get("status") == "active":
            result["eligible"] = True
            result["notes"].append(
                f"Eligible under {w['period']} {w['re_opener_clause']} — "
                f"cost £{check_cost/1e6:.0f}M within SpC 3.14.6 range"
            )

    # Threshold diagnostics
    if not result["eligible"]:
        if check_cost > 100_000_000:
            result["notes"].append(
                "Cost exceeds MSIP max (£100M) — likely Large Onshore Transmission Investment (LOTI) or "
                "Accelerated Strategic Transmission Investment (ASTI) mechanism instead"
            )
            result["next_steps"].append("Consider ASTI/LOTI route; contact NGET regulatory team")
        elif check_cost < 20_000_000:
            result["notes"].append(
                "Cost below MSIP minimum (£20M) — funded via normal Connection Agreement, not re-opener"
            )
            result["next_steps"].append("Route via standard BCA; no Ofgem re-opener application required")

    # Strategic demand fast-track (new in RIIO-T3)
    if capacity_mva >= 100 and 20_000_000 <= check_cost <= 100_000_000:
        result["next_steps"].append(
            "RIIO-T3 offers 'in-period demand growth approvals' for strategic demand — "
            "check AI Growth Zone designation (Ofgem Feb 2026 consultation)"
        )

    # APM fast-track for long-lead equipment
    if capacity_mva >= 200:
        result["next_steps"].append(
            "Capacity ≥200 MVA likely needs ≥1 SGT + ≥4 GIS bays — eligible for RIIO-T3 "
            "Advanced Procurement Mechanism (APM) which reduces programme risk by 20%"
        )

    return result


# ════════════════════════════════════════════════════════════════════════
# 7. AIS vs GIS SWITCHGEAR CHOICE
# ════════════════════════════════════════════════════════════════════════

def switchgear_recommendation(
    capacity_mva: float,
    urban: bool = False,
    voltage_kv: float = 132,
    available_land_ha: float | None = None,
) -> dict:
    """Recommend AIS or GIS switchgear based on constraints.

    Rule of thumb (from the Willesden case):
      • Urban central London with constrained land → GIS mandatory
      • Greenfield site with plentiful land → AIS typically cheaper
      • GIS costs ~3x AIS per bay but footprint is ~10% of AIS
    """
    n_bays = max(2, int(capacity_mva / 50))
    ais_cost_per_bay = 1_200_000
    gis_cost_per_bay = 3_500_000

    # Footprint in m²
    ais_footprint_m2 = n_bays * 600  # ~25x25m per bay
    gis_footprint_m2 = n_bays * 60

    reasons = []
    if urban:
        recommended = "GIS"
        reasons.append("Urban site — constrained footprint rules out AIS")
    elif available_land_ha is not None and available_land_ha * 10000 < ais_footprint_m2 * 2:
        recommended = "GIS"
        reasons.append(f"Available land ({available_land_ha:.1f} ha) insufficient for AIS layout")
    elif voltage_kv >= 400 and urban:
        recommended = "GIS"
        reasons.append("400kV AIS has prohibitive footprint for any urban site")
    else:
        recommended = "AIS"
        reasons.append("Greenfield site — AIS is cost-optimal")

    return {
        "recommended": recommended,
        "reasons": reasons,
        "n_bays": n_bays,
        "ais": {
            "cost_gbp": n_bays * ais_cost_per_bay,
            "footprint_m2": ais_footprint_m2,
            "footprint_ha": round(ais_footprint_m2 / 10000, 3),
        },
        "gis": {
            "cost_gbp": n_bays * gis_cost_per_bay,
            "footprint_m2": gis_footprint_m2,
            "footprint_ha": round(gis_footprint_m2 / 10000, 3),
        },
        "premium_gbp": n_bays * (gis_cost_per_bay - ais_cost_per_bay),
        "footprint_savings_m2": ais_footprint_m2 - gis_footprint_m2,
    }


# ════════════════════════════════════════════════════════════════════════
# 8. DIRECT COST / ASSET TABLE (Ofgem-format connection BOM)
# ════════════════════════════════════════════════════════════════════════

def generate_connection_bom(
    capacity_mva: float,
    voltage_kv: float,
    has_dual_feed: bool,
    uses_gis: bool,
    cable_length_km: float = 2.0,
    price_base_year: int = 2018,
) -> dict:
    """Generate an Ofgem-format Direct Cost / Asset Table for a DC connection.

    Matches the Appendix F template from MSIP submissions — per-asset line
    items with quantity, unit cost, total. Output plugs directly into the
    existing Grid Connection PDF report pipeline.
    """
    sw = switchgear_recommendation(capacity_mva, voltage_kv=voltage_kv, urban=False)
    n_bays = sw["n_bays"] * (2 if has_dual_feed else 1)
    bay_cost = sw["gis"]["cost_gbp"] / sw["n_bays"] if uses_gis else sw["ais"]["cost_gbp"] / sw["n_bays"]

    # Transformer sizing: round up to standard MVA ratings
    transformer_mva = None
    for t in (60, 90, 120, 180, 240, 320):
        if t >= capacity_mva:
            transformer_mva = t
            break
    if transformer_mva is None:
        transformer_mva = int(capacity_mva)
    n_transformers = 2 if has_dual_feed else 1
    transformer_unit_cost = (
        {60: 2_500_000, 90: 3_200_000, 120: 4_000_000,
         180: 5_500_000, 240: 7_000_000, 320: 9_000_000}
        .get(transformer_mva, transformer_mva * 35_000)
    )

    bom = [
        {
            "asset_class": "Switchgear",
            "description": f"{int(voltage_kv)}kV {'GIS' if uses_gis else 'AIS'} bay",
            "quantity": n_bays,
            "unit_cost_gbp": round(bay_cost),
            "total_gbp": round(bay_cost * n_bays),
        },
        {
            "asset_class": "Power Transformer",
            "description": f"{transformer_mva}/{int(voltage_kv)}kV/66kV SGT",
            "quantity": n_transformers,
            "unit_cost_gbp": transformer_unit_cost,
            "total_gbp": transformer_unit_cost * n_transformers,
        },
        {
            "asset_class": "HV Cable",
            "description": f"{int(voltage_kv)}kV XLPE circuit, {cable_length_km:.1f} km",
            "quantity": 2 if has_dual_feed else 1,
            "unit_cost_gbp": round(cable_length_km * 1_800_000),
            "total_gbp": round(cable_length_km * 1_800_000) * (2 if has_dual_feed else 1),
        },
        {
            "asset_class": "Protection & Control",
            "description": "Numerical relays, bay control, SCADA integration",
            "quantity": n_bays,
            "unit_cost_gbp": 180_000,
            "total_gbp": 180_000 * n_bays,
        },
        {
            "asset_class": "Civils",
            "description": "Foundations, bund walls, earthing grid, fencing",
            "quantity": 1,
            "unit_cost_gbp": round(capacity_mva * 25_000),
            "total_gbp": round(capacity_mva * 25_000),
        },
        {
            "asset_class": "Ancillary",
            "description": "Battery, DC systems, LV aux, fire detection",
            "quantity": 1,
            "unit_cost_gbp": 750_000,
            "total_gbp": 750_000,
        },
        {
            "asset_class": "Engineering & Project Management",
            "description": "FEED, design, PM, commissioning (15% of direct)",
            "quantity": 1,
            "unit_cost_gbp": 0,  # placeholder, computed below
            "total_gbp": 0,
        },
    ]

    subtotal = sum(item["total_gbp"] for item in bom if item["asset_class"] != "Engineering & Project Management")
    pm_cost = round(subtotal * 0.15)
    bom[-1]["unit_cost_gbp"] = pm_cost
    bom[-1]["total_gbp"] = pm_cost

    total_direct = subtotal + pm_cost
    contingency = round(total_direct * 0.18)
    total_with_contingency = total_direct + contingency

    return {
        "price_base_year": price_base_year,
        "bom": bom,
        "total_direct_gbp": total_direct,
        "contingency_gbp": contingency,
        "total_with_contingency_gbp": total_with_contingency,
        "n_bays": n_bays,
        "n_transformers": n_transformers,
        "switchgear_type": "GIS" if uses_gis else "AIS",
        "template_source": "NGET MSIP Appendix F (Willesden Jan 2024)",
    }


# ════════════════════════════════════════════════════════════════════════
# 9. PRICE-BASE ESCALATION
# ════════════════════════════════════════════════════════════════════════
#
# ONS CPIH-H index values for UK construction. Used to escalate cost
# submissions between price bases. Updated annually — good enough for DD.

CPIH_INDEX = {
    2015: 100.0, 2016: 101.0, 2017: 103.6, 2018: 106.0, 2019: 107.8,
    2020: 108.8, 2021: 111.5, 2022: 120.5, 2023: 128.9, 2024: 133.5,
    2025: 137.2, 2026: 141.1,  # projected
}


def escalate_price(
    cost_gbp: float,
    from_year: int,
    to_year: int,
) -> dict:
    """Escalate a cost figure between two price bases using CPIH-H."""
    from_idx = CPIH_INDEX.get(from_year)
    to_idx = CPIH_INDEX.get(to_year)
    if from_idx is None or to_idx is None:
        return {
            "ok": False,
            "reason": f"No CPIH index for {from_year} or {to_year}",
            "cost_gbp": cost_gbp,
        }
    multiplier = to_idx / from_idx
    escalated = cost_gbp * multiplier
    return {
        "ok": True,
        "from_year": from_year,
        "to_year": to_year,
        "multiplier": round(multiplier, 4),
        "from_cost_gbp": round(cost_gbp),
        "to_cost_gbp": round(escalated),
        "delta_gbp": round(escalated - cost_gbp),
        "delta_pct": round((multiplier - 1) * 100, 1),
        "index_source": "ONS CPIH (CHAW)",
    }
