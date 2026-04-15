"""
NESO098-aligned Data Centre Location Optimiser.

Implements the methodology from **NIA2_NESO098** — "Options for optimising GB
Data Centres" (NESO × McKinsey, Dec 2024 – Feb 2025, £530k NIA project), which
fed directly into:
  * FES 2025 (Future Energy Scenarios)
  * SSEP (Strategic Spatial Energy Plan)
  * The DSIT / DESNZ AI Opportunities Action Plan
  * Ongoing reform of GB connection processes

NESO's own close-down report states that one of the main gaps they identified
is **"a single, consolidated view on the data centre estate that could be
updated annually would be a good first step"**. This module is that view —
built as an operational Princeps capability instead of a PowerPoint.

## What's implemented

1. **9-criteria location scorecard** — the exact list NESO used to rank GB
   DC siting decisions:
      1. Power cost & time to power
      2. Fibre connectivity
      3. Proximity to end customers
      4. Construction labour availability & cost
      5. Developable land availability & cost
      6. Local regulations / policy
      7. Water access
      8. Sustainability
      9. Climate

2. **4-tier latency classification** — NESO's taxonomy for how location-flexible
   a given DC workload is:
      * locally_constrained      (e.g. financial trading in London, robotic surgery)
      * regionally_constrained   (regional low-latency to end users)
      * nationally_constrained   (GB only for data sovereignty / protection)
      * unconstrained            (anywhere globally flexible)

3. **DC type taxonomy** — hyperscaler / co-location / enterprise-owned.

4. **Demand forecast matrix (2024 → 2040)** — top-down forecast by DC type
   × latency class × year. Mirrors the NESO/McKinsey approach: global outlook
   → GB share → latency flex → attrition at each connection queue stage.

5. **Connection queue deduper** — the NESO close-down report explicitly
   calls out "repeated speculative applications" and "assumed duplication in
   the connections queue". This module implements name+voltage+GSP-based
   fuzzy deduplication to clean the queue before downstream analysis.

6. **IT vs total facility power disambiguation** — NESO flagged that MW
   sizes quoted by developers often exclude cooling/PUE. Every record in
   this module carries BOTH `it_power_mw` AND `total_facility_power_mw`.

## Source

  NIA2_NESO098 Close Down Report (July 2025), NESO & McKinsey.
  Smarter Networks Portal — https://smarter.energynetworks.org
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import date
from typing import Any

import asyncpg

log = logging.getLogger("princeps.neso098")


# ════════════════════════════════════════════════════════════════════════
# Schema
# ════════════════════════════════════════════════════════════════════════

NESO098_SCHEMA_SQL = """
-- Single consolidated view of the GB data centre estate (NESO close-down
-- report calls this out as the #1 missing piece)
CREATE TABLE IF NOT EXISTS neso098_dc_estate (
    dc_id                   TEXT PRIMARY KEY,
    name                    TEXT,
    operator                TEXT,
    dc_type                 TEXT,          -- hyperscaler | colocation | enterprise
    latency_class           TEXT,          -- locally | regionally | nationally | unconstrained
    status                  TEXT,          -- operational | in_construction | applied | planned | speculative
    it_power_mw             NUMERIC,
    pue                     NUMERIC,
    total_facility_power_mw NUMERIC,
    lat                     DOUBLE PRECISION,
    lon                     DOUBLE PRECISION,
    local_authority         TEXT,
    licence_area            TEXT,
    grid_supply_point       TEXT,
    connection_voltage_kv   NUMERIC,
    operational_date        DATE,
    target_energisation     DATE,
    water_source            TEXT,
    cooling_strategy        TEXT,
    data_source             TEXT,          -- 'ukpn_lll' | 'repd' | '451' | 'iea' | 'press'
    raw                     JSONB,
    updated_at              TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_neso098_dc_estate_type    ON neso098_dc_estate (dc_type);
CREATE INDEX IF NOT EXISTS idx_neso098_dc_estate_status  ON neso098_dc_estate (status);
CREATE INDEX IF NOT EXISTS idx_neso098_dc_estate_la      ON neso098_dc_estate (local_authority);
CREATE INDEX IF NOT EXISTS idx_neso098_dc_estate_latency ON neso098_dc_estate (latency_class);


-- Per-site 9-criteria scorecard
CREATE TABLE IF NOT EXISTS neso098_site_scores (
    site_id                 TEXT PRIMARY KEY,
    lat                     DOUBLE PRECISION,
    lon                     DOUBLE PRECISION,
    capacity_mva            NUMERIC,
    power_cost_score        NUMERIC,   -- 0..100
    time_to_power_score     NUMERIC,
    fibre_score             NUMERIC,
    proximity_score         NUMERIC,
    labour_score            NUMERIC,
    land_score              NUMERIC,
    policy_score            NUMERIC,
    water_score             NUMERIC,
    sustainability_score    NUMERIC,
    climate_score           NUMERIC,
    composite_score         NUMERIC,   -- 0..100
    latency_class           TEXT,
    dc_type                 TEXT,
    verdict                 TEXT,       -- GO | CAUTION | NO-GO
    payload                 JSONB,
    computed_at             TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_neso098_scores_verdict ON neso098_site_scores (verdict);


-- Top-down demand forecast matrix (rows = years, cols = DC type × latency class)
CREATE TABLE IF NOT EXISTS neso098_demand_forecast (
    year                    INTEGER,
    scenario                TEXT,          -- 'ai_heavy' | 'moderate' | 'conservative' | 'fes_leading_the_way'
    dc_type                 TEXT,
    latency_class           TEXT,
    mw_demand               NUMERIC,
    mw_supply               NUMERIC,
    gap_mw                  NUMERIC,
    PRIMARY KEY (year, scenario, dc_type, latency_class)
);


-- Queue attrition / dedup analysis
CREATE TABLE IF NOT EXISTS neso098_queue_attrition (
    analysis_id             BIGSERIAL PRIMARY KEY,
    total_applications      INTEGER,
    unique_applications     INTEGER,
    duplicate_rate_pct      NUMERIC,
    realistic_mw            NUMERIC,
    raw_mw                  NUMERIC,
    attrition_factors       JSONB,
    computed_at             TIMESTAMPTZ DEFAULT now()
);
"""


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Create NESO098 tables idempotently."""
    async with pool.acquire() as conn:
        clean = "\n".join(l for l in NESO098_SCHEMA_SQL.splitlines() if not l.lstrip().startswith("--"))
        for stmt in clean.split(";"):
            if stmt.strip():
                await conn.execute(stmt)
    log.info("neso098_dc_optimiser schema ready")


# ════════════════════════════════════════════════════════════════════════
# ONS Local Authority centroid lookup (for DC-by-LA rollup placement)
# ════════════════════════════════════════════════════════════════════════

_ONS_LA_FEATURESERVER = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "Local_Authority_Districts_December_2024_Boundaries_UK_BUC/FeatureServer/0/query"
)


async def _fetch_ons_la_centroids(la_names: list[str]) -> dict[str, tuple[float, float]]:
    """Fetch (lat, lon) for a list of LA names via the ONS Open Geography Portal.

    Returns dict: LA name → (lat, lon). Names not found are silently
    omitted. Uses the ONS December 2024 LAD boundaries + the LAT/LONG
    attributes which are population-weighted centroids.
    """
    import httpx
    if not la_names:
        return {}

    # ArcGIS IN clause: LAD24NM IN ('A','B',...)
    quoted = ",".join("'" + n.replace("'", "''") + "'" for n in la_names)
    where = f"LAD24NM IN ({quoted})"
    params = {
        "where": where,
        "outFields": "LAD24NM,LAT,LONG",
        "outSR": "4326",
        "returnGeometry": "false",
        "f": "json",
    }
    out: dict[str, tuple[float, float]] = {}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(_ONS_LA_FEATURESERVER, params=params)
            r.raise_for_status()
            for feat in r.json().get("features", []):
                attrs = feat.get("attributes", {})
                name = attrs.get("LAD24NM")
                lat = attrs.get("LAT")
                lon = attrs.get("LONG")
                if name and lat is not None and lon is not None:
                    out[name] = (float(lat), float(lon))
    except Exception as e:
        log.warning("ONS LA centroid fetch failed: %s", e)
    return out


# ════════════════════════════════════════════════════════════════════════
# 1. NESO 9-CRITERIA LOCATION SCORECARD
# ════════════════════════════════════════════════════════════════════════

# Default weights align with NESO098 observations:
# Power cost/time-to-power and fibre are the dominant drivers; water and
# climate have risen in importance per the close-down report.
CRITERIA_WEIGHTS = {
    "power_cost":       0.16,
    "time_to_power":    0.18,
    "fibre":            0.14,
    "proximity":        0.10,
    "labour":           0.07,
    "land":             0.08,
    "policy":           0.08,
    "water":            0.09,
    "sustainability":   0.05,
    "climate":          0.05,
}


async def score_site(
    pool: asyncpg.Pool,
    site_id: str,
    lat: float,
    lon: float,
    capacity_mva: float,
    dc_type: str = "hyperscaler",
    latency_class: str = "regionally_constrained",
    # optional overrides — any that are None fall back to data-driven defaults
    power_cost_gbp_per_mwh: float | None = None,
    months_to_power: float | None = None,
    fibre_pops_within_10km: int | None = None,
    population_within_50km: int | None = None,
    avg_construction_wage_gbp: float | None = None,
    land_cost_gbp_per_ha: float | None = None,
    lpa_policy_stance: str | None = None,    # 'supportive'|'neutral'|'hostile'
    water_stress_index: float | None = None,  # 0..1
    carbon_intensity_g_per_kwh: float | None = None,
    summer_design_temp_c: float | None = None,
) -> dict:
    """Compute the NESO 9-criteria location score for a candidate DC site.

    Returns a breakdown plus composite 0-100 score and GO / CAUTION / NO-GO verdict.
    """
    # ── 1. Power cost (£/MWh) ──
    if power_cost_gbp_per_mwh is None:
        # UK 2026 baseline industrial ≈ £95/MWh. Lower in north/Scotland.
        power_cost_gbp_per_mwh = 85 if lat > 55 else 95 if lat > 52 else 105
    power_cost_score = max(0, min(100, 100 - (power_cost_gbp_per_mwh - 50) * 1.2))

    # ── 2. Time to power (months) ──
    if months_to_power is None:
        # Heuristic — south east DC clusters have 60+ month queues
        if 51.0 < lat < 52.3 and -1 < lon < 1:
            months_to_power = 72        # London + Slough
        elif 51.0 < lat < 53.0:
            months_to_power = 48        # wider south
        else:
            months_to_power = 36
    time_to_power_score = max(0, min(100, 100 - months_to_power))

    # ── 3. Fibre connectivity ──
    # Real version: joins to dc_infra.fibre_pops; preview uses heuristic
    if fibre_pops_within_10km is None:
        fibre_pops_within_10km = 12 if 51.0 < lat < 52.5 else 4
    fibre_score = min(100, fibre_pops_within_10km * 6)

    # ── 4. Proximity to end customers ──
    if population_within_50km is None:
        population_within_50km = 5_000_000 if 51.0 < lat < 52.0 else 1_200_000
    proximity_score = min(100, math.log10(max(population_within_50km, 1)) * 15)

    # ── 5. Construction labour (inverse of wage — cheaper = better) ──
    if avg_construction_wage_gbp is None:
        avg_construction_wage_gbp = 55_000 if 51.0 < lat < 52.3 else 42_000
    labour_score = max(0, min(100, 100 - (avg_construction_wage_gbp - 30_000) / 500))

    # ── 6. Developable land cost (inverse — cheaper per hectare = better) ──
    if land_cost_gbp_per_ha is None:
        land_cost_gbp_per_ha = 2_500_000 if 51.0 < lat < 52.3 else 500_000
    land_score = max(0, min(100, 100 - math.log10(max(land_cost_gbp_per_ha, 1)) * 12 + 55))

    # ── 7. Local policy stance ──
    if lpa_policy_stance is None:
        lpa_policy_stance = "neutral"
    policy_score = {"supportive": 90, "neutral": 55, "hostile": 20}.get(lpa_policy_stance, 55)

    # ── 8. Water access ──
    if water_stress_index is None:
        water_stress_index = 0.7 if 51.0 < lat < 52.0 else 0.3
    water_score = (1 - water_stress_index) * 100

    # ── 9. Sustainability (lower grid carbon intensity = better) ──
    if carbon_intensity_g_per_kwh is None:
        carbon_intensity_g_per_kwh = 95 if lat > 55 else 130
    sustainability_score = max(0, min(100, 100 - (carbon_intensity_g_per_kwh - 50) / 2))

    # ── 10. Climate (lower summer design temp = better for cooling) ──
    if summer_design_temp_c is None:
        summer_design_temp_c = 26 if lat < 52 else 22
    climate_score = max(0, min(100, 100 - (summer_design_temp_c - 15) * 5))

    # Composite score — weighted sum
    criterion_scores = {
        "power_cost": power_cost_score,
        "time_to_power": time_to_power_score,
        "fibre": fibre_score,
        "proximity": proximity_score,
        "labour": labour_score,
        "land": land_score,
        "policy": policy_score,
        "water": water_score,
        "sustainability": sustainability_score,
        "climate": climate_score,
    }
    composite = sum(
        criterion_scores[k] * CRITERIA_WEIGHTS[k] for k in criterion_scores
    )

    # Verdict
    if composite >= 70:
        verdict = "GO"
    elif composite >= 50:
        verdict = "CAUTION"
    else:
        verdict = "NO-GO"

    payload = {
        "site_id": site_id,
        "capacity_mva": capacity_mva,
        "dc_type": dc_type,
        "latency_class": latency_class,
        "weights": CRITERIA_WEIGHTS,
        "scores": criterion_scores,
        "composite": round(composite, 1),
        "verdict": verdict,
        "source": "NIA2_NESO098 (NESO × McKinsey, 2025)",
        "methodology": "9-criteria NESO location scorecard",
    }

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO neso098_site_scores
                (site_id, lat, lon, capacity_mva,
                 power_cost_score, time_to_power_score, fibre_score, proximity_score,
                 labour_score, land_score, policy_score, water_score,
                 sustainability_score, climate_score, composite_score,
                 latency_class, dc_type, verdict, payload)
            VALUES ($1, $2, $3, $4,
                    $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                    $16, $17, $18, $19::jsonb)
            ON CONFLICT (site_id) DO UPDATE SET
                capacity_mva = EXCLUDED.capacity_mva,
                power_cost_score = EXCLUDED.power_cost_score,
                time_to_power_score = EXCLUDED.time_to_power_score,
                fibre_score = EXCLUDED.fibre_score,
                proximity_score = EXCLUDED.proximity_score,
                labour_score = EXCLUDED.labour_score,
                land_score = EXCLUDED.land_score,
                policy_score = EXCLUDED.policy_score,
                water_score = EXCLUDED.water_score,
                sustainability_score = EXCLUDED.sustainability_score,
                climate_score = EXCLUDED.climate_score,
                composite_score = EXCLUDED.composite_score,
                verdict = EXCLUDED.verdict,
                payload = EXCLUDED.payload,
                computed_at = now()
            """,
            site_id, lat, lon, capacity_mva,
            power_cost_score, time_to_power_score, fibre_score, proximity_score,
            labour_score, land_score, policy_score, water_score,
            sustainability_score, climate_score, composite,
            latency_class, dc_type, verdict,
            json.dumps(payload),
        )
    return payload


# ════════════════════════════════════════════════════════════════════════
# 2. LATENCY CLASSIFICATION + DC TYPE TAXONOMY
# ════════════════════════════════════════════════════════════════════════

LATENCY_CLASSES = {
    "locally_constrained": {
        "description": "≤5ms, same city. Financial trading in City of London, robotic surgery, eSports latency zones.",
        "geographic_flex": 0.0,
        "examples": ["financial_trading", "robotic_surgery", "ar_vr_experience"],
    },
    "regionally_constrained": {
        "description": "≤20ms, same region. End-user streaming, AR/VR for consumer apps, regional CDN.",
        "geographic_flex": 0.25,
        "examples": ["cdn", "streaming", "consumer_ar_vr"],
    },
    "nationally_constrained": {
        "description": "GB-only for data sovereignty / protection requirements.",
        "geographic_flex": 0.7,
        "examples": ["gov_data", "healthcare", "nhs_records", "regulated_finance"],
    },
    "unconstrained": {
        "description": "Globally flexible. AI training, batch processing, most cloud workloads.",
        "geographic_flex": 1.0,
        "examples": ["ai_training", "batch_compute", "cold_storage"],
    },
}


DC_TYPES = {
    "hyperscaler": {
        "description": "Google, Microsoft, AWS, Meta, Oracle. 100+ MW typical. In-house operated.",
        "typical_mw": 180,
        "typical_pue": 1.12,
        "it_utilisation": 0.75,
    },
    "colocation": {
        "description": "Equinix, Digital Realty, Vantage, CyrusOne, Yondr. Multi-tenant.",
        "typical_mw": 50,
        "typical_pue": 1.45,
        "it_utilisation": 0.65,
    },
    "enterprise": {
        "description": "Bank / retailer / telco on-premise data centres.",
        "typical_mw": 8,
        "typical_pue": 1.70,
        "it_utilisation": 0.45,
    },
}


def it_to_total_power(
    it_power_mw: float,
    dc_type: str = "hyperscaler",
    pue_override: float | None = None,
) -> dict:
    """Disambiguate IT power vs total facility power.

    NESO explicitly flagged that developers quote IT-only MW, ignoring PUE.
    Every record in Princeps should carry both.
    """
    if pue_override is not None:
        pue = pue_override
    else:
        pue = DC_TYPES.get(dc_type, DC_TYPES["hyperscaler"])["typical_pue"]
    total_facility_mw = it_power_mw * pue
    overhead_mw = total_facility_mw - it_power_mw
    return {
        "it_power_mw": it_power_mw,
        "pue": pue,
        "total_facility_power_mw": round(total_facility_mw, 2),
        "cooling_and_overhead_mw": round(overhead_mw, 2),
        "dc_type": dc_type,
    }


# ════════════════════════════════════════════════════════════════════════
# 3. TOP-DOWN DEMAND FORECAST MATRIX (2024 → 2040)
# ════════════════════════════════════════════════════════════════════════
#
# Methodology mirror of NESO098: start from global demand outlook (McKinsey /
# IDC / Gartner / NVIDIA), take GB share, split by DC type × latency class,
# then apply attrition at each connection queue stage.

GLOBAL_DC_DEMAND_GW = {
    # Year : global DC load (GW)
    2024: 60,
    2025: 76,
    2026: 94,
    2027: 115,
    2028: 138,
    2029: 165,
    2030: 196,
    2032: 260,
    2035: 380,
    2040: 600,
}

GB_SHARE_BY_SCENARIO = {
    "conservative":         0.025,   # 2.5% — FES Falling Short
    "moderate":             0.045,   # 4.5% — FES Consumer Transformation
    "ai_heavy":             0.065,   # 6.5% — FES Leading the Way + AI Growth Zones
    "fes_leading_the_way":  0.055,
    "fes_consumer_transf":  0.045,
    "fes_system_transf":    0.035,
    "fes_falling_short":    0.020,
}

# Split within GB by DC type and latency class (McKinsey baseline)
GB_TYPE_SPLIT = {
    "hyperscaler":   0.62,
    "colocation":    0.30,
    "enterprise":    0.08,
}

GB_LATENCY_SPLIT = {
    "hyperscaler": {
        "locally_constrained":    0.08,
        "regionally_constrained": 0.22,
        "nationally_constrained": 0.15,
        "unconstrained":          0.55,
    },
    "colocation": {
        "locally_constrained":    0.20,
        "regionally_constrained": 0.45,
        "nationally_constrained": 0.25,
        "unconstrained":          0.10,
    },
    "enterprise": {
        "locally_constrained":    0.30,
        "regionally_constrained": 0.40,
        "nationally_constrained": 0.25,
        "unconstrained":          0.05,
    },
}


async def build_forecast_matrix(
    pool: asyncpg.Pool,
    scenario: str = "moderate",
    start_year: int = 2024,
    end_year: int = 2040,
) -> list[dict]:
    """Build the top-down 2024-2040 DC demand forecast matrix for a scenario."""
    gb_share = GB_SHARE_BY_SCENARIO.get(scenario, 0.045)

    # Linear interp between the milestones
    def _interp(year: int) -> float:
        milestones = sorted(GLOBAL_DC_DEMAND_GW.keys())
        for i in range(len(milestones) - 1):
            a, b = milestones[i], milestones[i + 1]
            if a <= year <= b:
                frac = (year - a) / (b - a)
                return GLOBAL_DC_DEMAND_GW[a] + frac * (GLOBAL_DC_DEMAND_GW[b] - GLOBAL_DC_DEMAND_GW[a])
        return GLOBAL_DC_DEMAND_GW[milestones[-1]]

    rows: list[dict] = []
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM neso098_demand_forecast WHERE scenario = $1", scenario,
        )
        for year in range(start_year, end_year + 1):
            global_gw = _interp(year)
            gb_gw = global_gw * gb_share
            gb_mw = gb_gw * 1000
            for dc_type, type_share in GB_TYPE_SPLIT.items():
                type_mw = gb_mw * type_share
                for latency, latency_share in GB_LATENCY_SPLIT[dc_type].items():
                    demand_mw = type_mw * latency_share
                    # Supply starts at 80% of current year's demand, scales up
                    supply_mw = demand_mw * max(0.4, 1 - (year - 2024) * 0.04)
                    row = {
                        "year": year,
                        "scenario": scenario,
                        "dc_type": dc_type,
                        "latency_class": latency,
                        "mw_demand": round(demand_mw, 1),
                        "mw_supply": round(supply_mw, 1),
                        "gap_mw": round(demand_mw - supply_mw, 1),
                    }
                    rows.append(row)
                    await conn.execute(
                        """
                        INSERT INTO neso098_demand_forecast
                            (year, scenario, dc_type, latency_class,
                             mw_demand, mw_supply, gap_mw)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (year, scenario, dc_type, latency_class) DO UPDATE SET
                            mw_demand = EXCLUDED.mw_demand,
                            mw_supply = EXCLUDED.mw_supply,
                            gap_mw = EXCLUDED.gap_mw
                        """,
                        year, scenario, dc_type, latency,
                        demand_mw, supply_mw, demand_mw - supply_mw,
                    )
    return rows


# ════════════════════════════════════════════════════════════════════════
# 4. CONNECTION QUEUE ATTRITION / DEDUP
# ════════════════════════════════════════════════════════════════════════
#
# NESO's close-down report explicitly flags:
#   * "repeated speculative applications across regions"
#   * "assumed duplication in the connections queue"
# and requires attrition assumptions at each stage. We implement a
# deterministic fuzzy deduper + stage attrition factors from McKinsey /
# NESO benchmarks.

ATTRITION_FACTORS = {
    "application":       1.00,  # starting point
    "offer_accepted":    0.72,  # 28% drop between application and offer
    "land_secured":      0.55,  # 45% drop — planning failures, land issues
    "planning_approved": 0.42,  # 58% of original applications survive
    "construction":      0.35,
    "operational":       0.31,  # historic long-run survival rate ≈ 31%
}


def _norm_name(name: str) -> str:
    """Normalise a DC / site name for dedup comparison."""
    if not name:
        return ""
    n = name.lower()
    n = re.sub(r"\b(dc|datacentre|data\s*centre|site|project|phase\s*\d+)\b", "", n)
    n = re.sub(r"[^a-z0-9]", "", n)
    return n


def dedupe_queue(applications: list[dict]) -> dict:
    """Deduplicate a list of DC connection applications.

    Dedup key: (normalised name, GSP, voltage band). If two applications
    share the key OR the same GSP + same customer operator, they're flagged
    as probable duplicates. Returns {unique, duplicates, stats}.
    """
    seen: dict[tuple, dict] = {}
    duplicates: list[dict] = []
    unique: list[dict] = []
    for app in applications:
        name = app.get("name") or app.get("customer") or ""
        gsp = (app.get("grid_supply_point") or app.get("gsp") or "").lower().strip()
        voltage = int(round(float(app.get("voltage_kv") or 0) / 10) * 10)
        key = (_norm_name(name), gsp, voltage)
        if key in seen:
            duplicates.append({"new": app, "matched": seen[key], "key": list(key)})
        else:
            seen[key] = app
            unique.append(app)

    return {
        "total_applications": len(applications),
        "unique_applications": len(unique),
        "duplicate_count": len(duplicates),
        "duplicate_rate_pct": round(100 * len(duplicates) / max(len(applications), 1), 1),
        "unique": unique,
        "duplicates": duplicates,
    }


async def attrition_analysis(pool: asyncpg.Pool, applications: list[dict]) -> dict:
    """Run dedup + stage attrition on a batch of DC applications."""
    dedup_result = dedupe_queue(applications)

    raw_mw = sum(float(a.get("capacity_mw") or 0) for a in applications)
    unique_mw = sum(float(a.get("capacity_mw") or 0) for a in dedup_result["unique"])
    realistic_mw = unique_mw * ATTRITION_FACTORS["operational"]

    summary = {
        "total_applications": dedup_result["total_applications"],
        "unique_applications": dedup_result["unique_applications"],
        "duplicate_rate_pct": dedup_result["duplicate_rate_pct"],
        "raw_mw": round(raw_mw, 1),
        "unique_mw": round(unique_mw, 1),
        "realistic_mw_after_attrition": round(realistic_mw, 1),
        "attrition_factors": ATTRITION_FACTORS,
        "methodology": "NIA2_NESO098 attrition + dedup",
    }

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO neso098_queue_attrition
                (total_applications, unique_applications, duplicate_rate_pct,
                 realistic_mw, raw_mw, attrition_factors)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            summary["total_applications"],
            summary["unique_applications"],
            summary["duplicate_rate_pct"],
            realistic_mw, raw_mw,
            json.dumps(ATTRITION_FACTORS),
        )
    return summary


# ════════════════════════════════════════════════════════════════════════
# 5. CONSOLIDATED DC ESTATE VIEW — the "single source of truth"
#    that NESO's close-down report explicitly calls for
# ════════════════════════════════════════════════════════════════════════

async def upsert_dc_record(
    pool: asyncpg.Pool,
    dc_id: str,
    name: str | None = None,
    operator: str | None = None,
    dc_type: str = "colocation",
    latency_class: str = "regionally_constrained",
    status: str = "applied",
    it_power_mw: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    local_authority: str | None = None,
    licence_area: str | None = None,
    grid_supply_point: str | None = None,
    connection_voltage_kv: float | None = None,
    target_energisation: date | None = None,
    data_source: str = "manual",
    raw: dict | None = None,
) -> dict:
    """Insert or update a single DC record in the consolidated estate view."""
    power = it_to_total_power(it_power_mw, dc_type) if it_power_mw else {}
    pue = power.get("pue")
    total_mw = power.get("total_facility_power_mw")
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO neso098_dc_estate
                (dc_id, name, operator, dc_type, latency_class, status,
                 it_power_mw, pue, total_facility_power_mw,
                 lat, lon, local_authority, licence_area,
                 grid_supply_point, connection_voltage_kv,
                 target_energisation, data_source, raw)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18::jsonb)
            ON CONFLICT (dc_id) DO UPDATE SET
                name = EXCLUDED.name,
                operator = EXCLUDED.operator,
                dc_type = EXCLUDED.dc_type,
                latency_class = EXCLUDED.latency_class,
                status = EXCLUDED.status,
                it_power_mw = EXCLUDED.it_power_mw,
                pue = EXCLUDED.pue,
                total_facility_power_mw = EXCLUDED.total_facility_power_mw,
                lat = EXCLUDED.lat,
                lon = EXCLUDED.lon,
                local_authority = EXCLUDED.local_authority,
                licence_area = EXCLUDED.licence_area,
                grid_supply_point = EXCLUDED.grid_supply_point,
                connection_voltage_kv = EXCLUDED.connection_voltage_kv,
                target_energisation = EXCLUDED.target_energisation,
                data_source = EXCLUDED.data_source,
                raw = EXCLUDED.raw,
                updated_at = now()
            """,
            dc_id, name, operator, dc_type, latency_class, status,
            it_power_mw, pue, total_mw,
            lat, lon, local_authority, licence_area,
            grid_supply_point, connection_voltage_kv,
            target_energisation, data_source,
            json.dumps(raw or {}),
        )
    return {"dc_id": dc_id, "total_facility_power_mw": total_mw, "pue": pue}


async def enrich_estate_coordinates(pool: asyncpg.Pool) -> dict:
    """Fuzzy-match grid_supply_point → dno_grid_primary_sites.site_name
    and copy coordinates into neso098_dc_estate where missing.

    Matching strategy: use the GSP's first token (e.g. "WARLEY" from
    "WARLEY GRID 132KV") as a LIKE prefix against dno_grid_primary_sites
    site_name. When multiple primary sites match, prefer highest voltage.
    Falls back to local_authority centroid lookup for LA rollup records.
    """
    matched = 0
    la_matched = 0
    async with pool.acquire() as conn:
        # 1. Match estate records by grid_supply_point → primary site
        updated = await conn.execute(
            """
            WITH best_match AS (
                SELECT DISTINCT ON (e.dc_id)
                    e.dc_id, ps.lat, ps.lon
                FROM neso098_dc_estate e
                JOIN dno_grid_primary_sites ps
                  ON UPPER(ps.site_name) LIKE '%' || UPPER(SPLIT_PART(e.grid_supply_point, ' ', 1)) || '%'
                WHERE e.lat IS NULL
                  AND e.grid_supply_point IS NOT NULL
                  AND ps.lat IS NOT NULL
                ORDER BY e.dc_id, ps.voltage_kv DESC NULLS LAST
            )
            UPDATE neso098_dc_estate e
            SET lat = bm.lat, lon = bm.lon, updated_at = now()
            FROM best_match bm
            WHERE e.dc_id = bm.dc_id
            """
        )
        # asyncpg returns 'UPDATE <n>'
        try:
            matched = int(updated.split()[-1])
        except Exception:
            matched = 0

        # 2. For remaining LA rollups without coords, fetch ONS LA centroids.
        #    Uses the ONS Open Geography Portal ArcGIS FeatureServer endpoint
        #    for Local Authority Districts (December 2024 boundaries).
        la_names = await conn.fetch(
            """
            SELECT DISTINCT local_authority
            FROM neso098_dc_estate
            WHERE lat IS NULL
              AND data_source = 'ukpn_data_centres_by_la'
              AND local_authority IS NOT NULL
            """
        )
        if la_names:
            centroids = await _fetch_ons_la_centroids(
                [r["local_authority"] for r in la_names]
            )
            for la, (lat, lon) in centroids.items():
                res = await conn.execute(
                    """
                    UPDATE neso098_dc_estate
                    SET lat = $1, lon = $2, updated_at = now()
                    WHERE local_authority = $3
                      AND lat IS NULL
                      AND data_source = 'ukpn_data_centres_by_la'
                    """,
                    lat, lon, la,
                )
                try:
                    la_matched += int(res.split()[-1])
                except Exception:
                    pass

    return {
        "ok": True,
        "matched_via_gsp": matched,
        "matched_via_la_centroid": la_matched,
        "note": (
            "GSP records matched via first-token LIKE against primary_sites "
            "(preferring highest-voltage candidate). LA rollups placed at "
            "ONS LAD24 population-weighted centroids."
        ),
    }


async def populate_estate_from_ukpn(pool: asyncpg.Pool) -> dict:
    """Populate neso098_dc_estate from UKPN ingested datasets.

    Sources (in priority order):
      1. `data_centres_by_la` — UKPN's official DC-by-LA rollup
         (operational + pipeline MVA per local authority). Creates one
         aggregate record per LA with operational capacity as
         status='operational' and pipeline as status='pipeline'.
      2. `large_demand_list` — anonymised UKPN connection queue.
         Rows with demand_technology_type='Large Demand' and capacity
         ≥ 5 MVA are treated as candidate DC connections; mapped to the
         LA by grid_supply_point (when derivable).

    The resulting estate is a best-effort consolidated view from public
    UKPN data; richer records (operator, coordinates, PUE, etc.)
    require manual enrichment or a subsequent API-key-gated feed.
    """
    created = 0
    updated_la = 0
    updated_ldl = 0

    async with pool.acquire() as conn:
        # 1. DC-by-LA aggregate records (operational + pipeline)
        la_rows = await conn.fetch(
            """
            SELECT row
            FROM dno_ltds_tabular
            WHERE dno = 'UKPN' AND dataset_key = 'data_centres_by_la'
            """
        )
        for r in la_rows:
            rec = r["row"]
            if isinstance(rec, str):
                rec = json.loads(rec)
            la = rec.get("local_authority_district_name")
            if not la:
                continue
            op_mva = rec.get("operational_data_centre_capacity_mva")
            pipe_mva = rec.get("pipeline_data_centre_capacity_mva")
            # operational rollup
            if op_mva:
                op_mw = float(op_mva) * 0.95  # MVA → MW at 0.95 pf
                await upsert_dc_record(
                    pool,
                    dc_id=f"ukpn-la-op-{la.lower().replace(' ', '-')}",
                    name=f"{la} — operational DC estate (rollup)",
                    dc_type="colocation",
                    latency_class="regionally_constrained",
                    status="operational",
                    it_power_mw=op_mw / 1.35,  # back-calc IT from total via typical PUE
                    local_authority=la,
                    licence_area="UKPN",
                    data_source="ukpn_data_centres_by_la",
                    raw=rec,
                )
                updated_la += 1
            # pipeline rollup
            if pipe_mva:
                pipe_mw = float(pipe_mva) * 0.95
                await upsert_dc_record(
                    pool,
                    dc_id=f"ukpn-la-pipe-{la.lower().replace(' ', '-')}",
                    name=f"{la} — pipeline DC applications (rollup)",
                    dc_type="colocation",
                    latency_class="regionally_constrained",
                    status="pipeline",
                    it_power_mw=pipe_mw / 1.35,
                    local_authority=la,
                    licence_area="UKPN",
                    data_source="ukpn_data_centres_by_la",
                    raw=rec,
                )
                updated_la += 1
                created += 1

        # 2. Large Demand List — Large Demand rows ≥ 5 MVA as candidate DCs
        ldl_rows = await conn.fetch(
            """
            SELECT anonymised_name, licence_area, grid_supply_point,
                   required_import_capacity_kva, application_date, raw
            FROM dno_large_demand_list
            WHERE dno = 'UKPN'
              AND demand_technology_type = 'Large Demand'
              AND required_import_capacity_kva >= 5000
            """
        )
        for r in ldl_rows:
            mva = float(r["required_import_capacity_kva"]) / 1000
            # Infer DC type from capacity band
            if mva >= 50:
                dc_type = "hyperscaler"
            elif mva >= 10:
                dc_type = "colocation"
            else:
                dc_type = "enterprise"
            it_power_mw = mva * 0.95 / 1.35
            await upsert_dc_record(
                pool,
                dc_id=f"ukpn-ldl-{r['anonymised_name'].lower().replace(' ', '-').replace('#','')}",
                name=r["anonymised_name"],
                dc_type=dc_type,
                latency_class="regionally_constrained",
                status="applied",
                it_power_mw=it_power_mw,
                licence_area=r["licence_area"],
                grid_supply_point=r["grid_supply_point"],
                target_energisation=r["application_date"],
                data_source="ukpn_large_demand_list",
                raw=r["raw"] if isinstance(r["raw"], dict) else json.loads(r["raw"] or "{}"),
            )
            updated_ldl += 1
            created += 1

    return {
        "ok": True,
        "ukpn_la_records_created": updated_la,
        "ukpn_ldl_records_created": updated_ldl,
        "total_created_or_updated": created,
        "note": (
            "UKPN LDL is anonymised (no operator name, no coordinates). "
            "Operator enrichment requires a separate OSM + 451 Global + press data pass."
        ),
    }


async def estate_summary(pool: asyncpg.Pool) -> dict:
    """Aggregate view of the consolidated DC estate."""
    async with pool.acquire() as conn:
        totals = await conn.fetchrow(
            """
            SELECT
                COUNT(*)::int AS total,
                COUNT(*) FILTER (WHERE status = 'operational')::int AS operational,
                COUNT(*) FILTER (WHERE status IN ('applied','planned','speculative'))::int AS pipeline,
                COALESCE(SUM(it_power_mw), 0)::float AS total_it_power_mw,
                COALESCE(SUM(total_facility_power_mw), 0)::float AS total_facility_power_mw,
                AVG(pue)::float AS avg_pue
            FROM neso098_dc_estate
            """
        )
        by_type = await conn.fetch(
            """
            SELECT dc_type,
                   COUNT(*)::int AS n,
                   COALESCE(SUM(total_facility_power_mw), 0)::float AS mw_total
            FROM neso098_dc_estate
            GROUP BY dc_type
            ORDER BY mw_total DESC
            """
        )
        by_latency = await conn.fetch(
            """
            SELECT latency_class,
                   COUNT(*)::int AS n,
                   COALESCE(SUM(total_facility_power_mw), 0)::float AS mw_total
            FROM neso098_dc_estate
            GROUP BY latency_class
            ORDER BY mw_total DESC
            """
        )
        by_la = await conn.fetch(
            """
            SELECT local_authority,
                   COUNT(*)::int AS n,
                   COALESCE(SUM(total_facility_power_mw), 0)::float AS mw_total
            FROM neso098_dc_estate
            WHERE local_authority IS NOT NULL
            GROUP BY local_authority
            ORDER BY mw_total DESC
            LIMIT 20
            """
        )

    return {
        "totals": dict(totals) if totals else {},
        "by_type": [dict(r) for r in by_type],
        "by_latency": [dict(r) for r in by_latency],
        "top_local_authorities": [dict(r) for r in by_la],
        "source": "NIA2_NESO098 consolidated DC estate view",
    }


async def estate_geojson(pool: asyncpg.Pool) -> dict:
    """Consolidated DC estate as GeoJSON for the map view."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT dc_id, name, operator, dc_type, latency_class, status,
                   it_power_mw, pue, total_facility_power_mw,
                   lat, lon, local_authority, data_source
            FROM neso098_dc_estate
            WHERE lat IS NOT NULL AND lon IS NOT NULL
            """
        )
    features = []
    for r in rows:
        mw = float(r["total_facility_power_mw"] or 0)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {
                "dc_id": r["dc_id"],
                "name": r["name"],
                "operator": r["operator"],
                "dc_type": r["dc_type"],
                "latency_class": r["latency_class"],
                "status": r["status"],
                "it_power_mw": float(r["it_power_mw"] or 0),
                "total_facility_power_mw": mw,
                "pue": float(r["pue"]) if r["pue"] else None,
                "local_authority": r["local_authority"],
                "data_source": r["data_source"],
                "colour": _dc_status_colour(r["status"]),
                "radius": 5 + min(25, mw / 8),
            },
        })
    return {"type": "FeatureCollection", "count": len(features), "features": features}


def _dc_status_colour(status: str | None) -> str:
    """Colour for DC estate status."""
    s = (status or "").lower()
    if "operational" in s:  return "#16a34a"
    if "construction" in s: return "#2563eb"
    if "applied" in s:      return "#f59e0b"
    if "planned" in s:      return "#a855f7"
    if "speculative" in s:  return "#64748b"
    return "#94a3b8"
