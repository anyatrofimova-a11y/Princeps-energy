"""
dc_regulatory_intel.py — NSIP/TM04+ regulatory intelligence for DC site selection.

Assesses the regulatory pathway for large-scale data-centre developments,
including NSIP opt-in eligibility (Planning & Infrastructure Act 2025),
TM04+ grid connection gate stages, and local planning authority track record.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import asyncpg

log = logging.getLogger("princeps.dc_regulatory")

# ---------------------------------------------------------------------------
# NSIP thresholds (Planning & Infrastructure Act 2025)
# ---------------------------------------------------------------------------
NSIP_THRESHOLD_MW = 50   # DCs can opt-in to NSIP pathway above this
NSIP_RECOMMENDED_MW = 100  # Strongly recommended for speed above this

# ---------------------------------------------------------------------------
# TM04+ gate stages
# ---------------------------------------------------------------------------
TM04_GATES: dict[str, dict[str, Any]] = {
    "gate_1": {
        "label": "Gate 1 — Indicative Offer",
        "timeline_months": 6,
        "certainty": "low",
    },
    "gate_2": {
        "label": "Gate 2 — Firm Offer",
        "timeline_months": 18,
        "certainty": "high",
    },
    "gate_3": {
        "label": "Gate 3 — Connection Agreement",
        "timeline_months": 24,
        "certainty": "committed",
    },
}

# ---------------------------------------------------------------------------
# UK planning authority approval rates for industrial/DC schemes
# ---------------------------------------------------------------------------
PLANNING_AUTHORITIES: dict[str, dict[str, Any]] = {
    "Broxbourne": {
        "approval_rate": 0.85, "avg_months": 12, "dc_precedent": True,
        "lat": 51.747, "lon": -0.020,
        "notes": "Google Waltham Cross approved",
    },
    "Epping Forest": {
        "approval_rate": 0.70, "avg_months": 18, "dc_precedent": True,
        "lat": 51.710, "lon": 0.050,
        "notes": "Google North Weald approved",
    },
    "Thurrock": {
        "approval_rate": 0.80, "avg_months": 14, "dc_precedent": False,
        "lat": 51.493, "lon": 0.313,
        "notes": "Purfleet area",
    },
    "Redcar & Cleveland": {
        "approval_rate": 0.90, "avg_months": 10, "dc_precedent": False,
        "lat": 54.597, "lon": -1.078,
        "notes": "Teesside — freeport",
    },
    "Slough": {
        "approval_rate": 0.75, "avg_months": 16, "dc_precedent": True,
        "lat": 51.511, "lon": -0.595,
        "notes": "Equinix LD cluster",
    },
    "Sunderland": {
        "approval_rate": 0.82, "avg_months": 12, "dc_precedent": False,
        "lat": 54.906, "lon": -1.381,
        "notes": "IAMP industrial area",
    },
    "Havering": {
        "approval_rate": 0.72, "avg_months": 16, "dc_precedent": True,
        "lat": 51.577, "lon": 0.212,
        "notes": "Beam Reach — DC cluster",
    },
    "Crawley": {
        "approval_rate": 0.78, "avg_months": 14, "dc_precedent": True,
        "lat": 51.109, "lon": -0.187,
        "notes": "Gatwick corridor — Vantage, Virtus",
    },
    "Trafford": {
        "approval_rate": 0.80, "avg_months": 14, "dc_precedent": True,
        "lat": 53.422, "lon": -2.347,
        "notes": "Trafford Park — Equinix MA cluster",
    },
    "Newport": {
        "approval_rate": 0.83, "avg_months": 11, "dc_precedent": False,
        "lat": 51.588, "lon": -2.998,
        "notes": "South Wales — semiconductor + DC interest",
    },
}

# Fallback for unknown authorities
DEFAULT_AUTHORITY: dict[str, Any] = {
    "approval_rate": 0.65, "avg_months": 18, "dc_precedent": False,
    "lat": 52.5, "lon": -1.5,
    "notes": "UK average",
}


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


# ---------------------------------------------------------------------------
# Authority matching
# ---------------------------------------------------------------------------

def _find_nearest_authority(
    lat: float,
    lon: float,
) -> tuple[str, dict[str, Any]]:
    """Match a site to the nearest known planning authority using haversine."""
    best_name = "default"
    best_data = DEFAULT_AUTHORITY
    best_dist = float("inf")

    for name, data in PLANNING_AUTHORITIES.items():
        d = _haversine(lat, lon, data["lat"], data["lon"])
        if d < best_dist:
            best_dist = d
            best_name = name
            best_data = data

    # Only use matched authority if reasonably close (<30 km)
    if best_dist > 30:
        log.debug("No authority within 30 km of (%.4f, %.4f); using UK default",
                  lat, lon)
        return "Unknown (UK default)", DEFAULT_AUTHORITY

    log.debug("Nearest authority to (%.4f, %.4f): %s (%.1f km)",
              lat, lon, best_name, best_dist)
    return best_name, best_data


# ---------------------------------------------------------------------------
# NSIP pathway
# ---------------------------------------------------------------------------

def _nsip_pathway(capacity_mw: float) -> str:
    """Determine planning pathway based on capacity."""
    if capacity_mw >= NSIP_THRESHOLD_MW:
        if capacity_mw >= NSIP_RECOMMENDED_MW:
            return "opt_in_nsip"
        return "opt_in_nsip"
    if capacity_mw < 1:
        return "permitted_development"
    return "standard_planning"


# ---------------------------------------------------------------------------
# Grid connection queue (TM04+)
# ---------------------------------------------------------------------------

async def _check_tm04_queue(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    search_radius_km: float = 25.0,
) -> dict[str, Any]:
    """
    Query grid_ecr for connection offers near the site.

    Determines TM04+ gate stage based on existing queue entries and their
    status.  Returns gate assignment, queue position estimate, and timeline.
    """
    # Convert search radius to metres for PostGIS ST_DWithin (SRID 27700)
    search_radius_m = search_radius_km * 1000

    try:
        row = await conn.fetchrow("""
            SELECT
                COUNT(*) AS total_entries,
                COUNT(*) FILTER (
                    WHERE status ILIKE '%%queue%%'
                       OR status ILIKE '%%accepted%%'
                       OR status ILIKE '%%offer%%'
                ) AS active_entries,
                COALESCE(SUM(capacity_mw) FILTER (
                    WHERE status ILIKE '%%queue%%'
                       OR status ILIKE '%%accepted%%'
                ), 0) AS queued_mw,
                COUNT(*) FILTER (
                    WHERE status ILIKE '%%connected%%'
                       OR status ILIKE '%%energised%%'
                ) AS connected_entries
            FROM grid_ecr
            WHERE geom IS NOT NULL
              AND ST_DWithin(
                    geom,
                    ST_Transform(
                        ST_SetSRID(ST_MakePoint($1, $2), 4326),
                        27700
                    ),
                    $3
                  )
        """, lon, lat, search_radius_m)
    except Exception as exc:
        log.warning("grid_ecr query failed: %s", exc)
        return {
            "gate": None,
            "gate_label": None,
            "timeline_months": None,
            "queue_position": None,
            "queued_mw": 0,
            "error": str(exc),
        }

    if row is None or row["total_entries"] == 0:
        # No ECR data nearby — assume Gate 1 starting position
        return {
            "gate": "gate_1",
            "gate_label": TM04_GATES["gate_1"]["label"],
            "timeline_months": TM04_GATES["gate_1"]["timeline_months"],
            "queue_position": 1,
            "queued_mw": 0,
        }

    active = int(row["active_entries"])
    queued_mw = float(row["queued_mw"])
    connected = int(row["connected_entries"])

    # Heuristic gate assignment:
    # - Large queue (>500 MW active) → Gate 1 likely (long wait)
    # - Moderate queue (100-500 MW) → Gate 2 achievable
    # - Low queue (<100 MW) → Gate 3 feasible
    if queued_mw > 500:
        gate = "gate_1"
        position = active + 1
    elif queued_mw > 100:
        gate = "gate_2"
        position = max(1, active - connected + 1)
    else:
        gate = "gate_3" if connected > 0 else "gate_2"
        position = max(1, active - connected + 1)

    return {
        "gate": gate,
        "gate_label": TM04_GATES[gate]["label"],
        "timeline_months": TM04_GATES[gate]["timeline_months"],
        "queue_position": position,
        "queued_mw": round(queued_mw, 1),
    }


# ---------------------------------------------------------------------------
# Risk & opportunity analysis
# ---------------------------------------------------------------------------

def _assess_risks(
    capacity_mw: float,
    pathway: str,
    authority_data: dict[str, Any],
    tm04: dict[str, Any],
) -> list[str]:
    """Identify regulatory risks for the proposed development."""
    risks: list[str] = []

    # Planning risks
    if authority_data["approval_rate"] < 0.70:
        risks.append("Low planning approval rate (<70%) in this authority")
    if authority_data["avg_months"] > 16:
        risks.append(f"Slow determination ({authority_data['avg_months']} months average)")
    if not authority_data["dc_precedent"]:
        risks.append("No data-centre precedent in this planning authority")

    # NSIP risks
    if pathway == "opt_in_nsip" and capacity_mw < NSIP_RECOMMENDED_MW:
        risks.append("NSIP opt-in below 100 MW — may not justify DCO cost and complexity")

    # Grid connection risks
    if tm04.get("queued_mw", 0) > 300:
        risks.append(f"High grid connection queue ({tm04['queued_mw']} MW queued nearby)")
    if tm04.get("gate") == "gate_1":
        risks.append("Only at TM04+ Gate 1 — indicative offer, low certainty")
    if tm04.get("timeline_months") and tm04["timeline_months"] > 18:
        risks.append(f"Grid connection timeline >{tm04['timeline_months']} months")

    # Environmental / community
    if capacity_mw > 200:
        risks.append("Very large DC (>200 MW) — likely to trigger Environmental Impact Assessment")

    return risks


def _assess_opportunities(
    capacity_mw: float,
    pathway: str,
    authority_data: dict[str, Any],
    tm04: dict[str, Any],
) -> list[str]:
    """Identify regulatory opportunities for the proposed development."""
    opps: list[str] = []

    if authority_data["dc_precedent"]:
        opps.append("Planning authority has approved DCs before — positive precedent")
    if authority_data["approval_rate"] >= 0.85:
        opps.append(f"High approval rate ({authority_data['approval_rate']:.0%}) in this authority")

    if pathway == "opt_in_nsip":
        opps.append("NSIP pathway available — single DCO replaces multiple consents")
        if capacity_mw >= NSIP_RECOMMENDED_MW:
            opps.append("Large scale justifies NSIP — typically faster than local planning for >100 MW")

    if tm04.get("gate") in ("gate_2", "gate_3"):
        opps.append(f"Grid connection at {tm04.get('gate_label', 'advanced gate')} — higher certainty")
    if tm04.get("queued_mw", 0) < 50:
        opps.append("Low grid queue (<50 MW) — faster connection likely")

    if pathway == "permitted_development":
        opps.append("Small scale qualifies for permitted development — no planning application needed")

    return opps


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

def _compute_regulatory_score(
    pathway: str,
    authority_data: dict[str, Any],
    tm04: dict[str, Any],
) -> int:
    """
    Compute 0-100 regulatory score.

    Factors:
    - NSIP eligibility + gate stage + DC precedent + approval rate
    """
    score = 40  # baseline

    # NSIP bonus
    if pathway == "opt_in_nsip":
        score += 15

    # TM04+ gate bonus
    gate = tm04.get("gate")
    if gate == "gate_3":
        score += 20
    elif gate == "gate_2":
        score += 12
    elif gate == "gate_1":
        score += 5

    # Planning authority quality
    rate = authority_data["approval_rate"]
    if rate >= 0.85:
        score += 15
    elif rate >= 0.75:
        score += 10
    elif rate >= 0.65:
        score += 5

    # DC precedent
    if authority_data["dc_precedent"]:
        score += 10

    # Fast determination
    if authority_data["avg_months"] <= 12:
        score += 5

    # Queue penalty
    queued = tm04.get("queued_mw", 0)
    if queued > 500:
        score -= 15
    elif queued > 200:
        score -= 8

    return max(0, min(100, score))


# ---------------------------------------------------------------------------
# Main assessment
# ---------------------------------------------------------------------------

async def assess_regulatory(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    capacity_mw: float = 100,
) -> dict[str, Any]:
    """
    Assess regulatory pathway and risk for a data-centre site.

    Parameters
    ----------
    conn : asyncpg.Connection
        Database connection (queries grid_ecr for TM04+ queue data).
    lat, lon : float
        Site coordinates in WGS84.
    capacity_mw : float
        Proposed IT load in MW.

    Returns
    -------
    dict with keys:
        regulatory_score           : int    (0-100)
        nsip_eligible              : bool
        nsip_recommended           : bool
        nsip_pathway               : str    (opt_in_nsip | standard_planning | permitted_development)
        tm04_gate                  : str | None
        tm04_timeline_months       : int | None
        connection_queue_position  : int | None
        planning_authority         : str
        approval_rate              : float
        avg_determination_months   : int
        dc_precedent               : bool
        risks                      : list[str]
        opportunities              : list[str]
    """
    log.info("Assessing regulatory pathway at (%.4f, %.4f) for %s MW DC",
             lat, lon, capacity_mw)

    # NSIP pathway
    pathway = _nsip_pathway(capacity_mw)
    nsip_eligible = capacity_mw >= NSIP_THRESHOLD_MW
    nsip_recommended = capacity_mw >= NSIP_RECOMMENDED_MW

    # Planning authority
    authority_name, authority_data = _find_nearest_authority(lat, lon)

    # TM04+ grid connection queue
    tm04 = await _check_tm04_queue(conn, lat, lon)

    # Risks and opportunities
    risks = _assess_risks(capacity_mw, pathway, authority_data, tm04)
    opportunities = _assess_opportunities(capacity_mw, pathway, authority_data, tm04)

    # Score
    score = _compute_regulatory_score(pathway, authority_data, tm04)

    result: dict[str, Any] = {
        "regulatory_score": score,
        "nsip_eligible": nsip_eligible,
        "nsip_recommended": nsip_recommended,
        "nsip_pathway": pathway,
        "tm04_gate": tm04.get("gate"),
        "tm04_gate_label": tm04.get("gate_label"),
        "tm04_timeline_months": tm04.get("timeline_months"),
        "connection_queue_position": tm04.get("queue_position"),
        "connection_queued_mw": tm04.get("queued_mw", 0),
        "planning_authority": authority_name,
        "approval_rate": authority_data["approval_rate"],
        "avg_determination_months": authority_data["avg_months"],
        "dc_precedent": authority_data["dc_precedent"],
        "risks": risks,
        "opportunities": opportunities,
    }

    # Flat docket list sourced from the live regulatory registry (added
    # 2026-04-19 BOT-Y sweep). The DCHyperscaler docket strip renders this
    # under the "Regulatory · live dockets" card. Each entry is
    # {title, status, state, date, source, docket}.
    try:
        from app.regulatory.versions import get as _reg_get
    except Exception:
        _reg_get = None

    items: list[dict[str, Any]] = []
    if _reg_get is not None:
        def _item(key: str, state: str) -> dict[str, Any]:
            try:
                spec = _reg_get(key)
                return {
                    "title": f"{spec['name']} — {spec['version']}",
                    "source": spec["name"],
                    "status": state,
                    "state": state,
                    "date": spec.get("effective") or spec.get("published"),
                    "url": spec.get("url"),
                    "docket": key,
                }
            except Exception:
                return {"title": key, "status": state, "state": state}

        # Ofgem RIIO-T3 Final Determinations Dec 2025 — cost allowance frame
        # that MSIP/MVS numbers hang off. Not a standard in the registry
        # yet so build inline.
        items.append({
            "title": "Ofgem RIIO-T3 Final Determinations — Dec 2025",
            "source": "Ofgem",
            "status": "in_force",
            "state": "in_force",
            "date": "2025-12-18",
            "url": "https://www.ofgem.gov.uk/publications/riio-t3-final-determinations",
            "docket": "riio_t3",
        })
        # NESO TMO4+ / Gate 2 — status depends on site's current gate
        tmo4_state = "in_force" if tm04.get("gate") else "applies"
        items.append(_item("tmo4_gate2", tmo4_state))
        # EU EED Art.12 — applies to DCs >=100 kW IT load (reporting since
        # 15 Sep 2024). Post-Brexit DE-scoped for GB but still cited by
        # multinational operators that report group-wide.
        items.append({
            "title": "EU Energy Efficiency Directive Art. 12 — DC reporting",
            "source": "EU EED (Directive 2023/1791)",
            "status": "applies_non_uk" if capacity_mw >= 0.1 else "n/a",
            "state": "applies_non_uk",
            "date": "2024-09-15",
            "url": "https://energy.ec.europa.eu/topics/energy-efficiency/energy-efficiency-targets-directive-and-rules/energy-efficiency-directive_en",
            "docket": "eu_eed_art12",
        })
        # DEFRA BNG — 10% biodiversity net gain mandatory for NSIPs from
        # May 2026 (statutory commencement), Town & Country Planning since
        # 12 Feb 2024.
        bng_state = "required" if pathway != "permitted_development" else "exempt"
        items.append({
            "title": "DEFRA Biodiversity Net Gain — 10% mandatory",
            "source": "DEFRA / Environment Act 2021",
            "status": bng_state,
            "state": bng_state,
            "date": "2024-02-12",
            "url": "https://www.gov.uk/guidance/understanding-biodiversity-net-gain",
            "docket": "bng_10pct",
        })
        # BNG for NSIPs — May 2026 commencement
        if pathway == "opt_in_nsip":
            items.append({
                "title": "BNG for NSIPs — mandatory from May 2026",
                "source": "Environment Act 2021 (sch. 15 para 2, NSIPs)",
                "status": "commences_may_2026",
                "state": "pending",
                "date": "2026-05-01",
                "url": "https://www.gov.uk/guidance/statutory-biodiversity-net-gain",
                "docket": "bng_nsip",
            })
        # Town & Country Planning (EIA) Regulations 2017 — EIA threshold
        # for DCs is >0.5 ha typically schedule 2; >200 MW typically
        # triggers schedule 1 mandatory EIA.
        if capacity_mw > 200:
            eia_state = "mandatory"
        elif capacity_mw >= NSIP_THRESHOLD_MW:
            eia_state = "likely_required"
        else:
            eia_state = "screening"
        items.append({
            "title": "Town & Country Planning (EIA) Regulations 2017",
            "source": "DLUHC / Ministry of Housing",
            "status": eia_state,
            "state": eia_state,
            "date": "2017-05-16",
            "url": "https://www.legislation.gov.uk/uksi/2017/571/contents",
            "docket": "tcp_eia_2017",
        })
        # NPPF Dec 2024 — current edition. Frontend shows this as info.
        items.append(_item("nppf", "in_force"))
        # Planning & Infrastructure Act 2025 — phased commencement context.
        items.append(_item("pinfra_act_2025", "phased_commencement"))
        # EN-3 (energy NPS) — most current revision Jan 2026
        items.append(_item("en3", "in_force"))

    result["items"] = items
    # Convenience scalars the legacy frontend fallback synth path uses.
    result["eu_eed_compliant"] = None   # unknown without operator data
    result["bng_required"] = bng_state in ("required", "mandatory") if items else None

    log.info("Regulatory result: score=%d pathway=%s authority=%s gate=%s dockets=%d",
             score, pathway, authority_name, tm04.get("gate"), len(items))
    return result
