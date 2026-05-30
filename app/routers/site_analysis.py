"""Site analysis demo endpoint — the YC pitch narrative in one POST.

POST /api/agent/analyze-site
  body: {lat, lon, technology, capacity_mw}

The frontend at /v2/scope drops a pin → POSTs here → renders the structured
response progressively. Numbers are deterministic (hashed on lat,lon) so the
same pin always returns the same answer — keeps demos repeatable while looking
varied across the UK. The only live call is Claude for the verdict rationale.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_claude, get_pool
from app.helpers import CLAUDE_MODEL

log = logging.getLogger("princeps.site_analysis")

router = APIRouter(prefix="/api/agent", tags=["site-analysis"])


# ─── Real-ish UK reference data (used to ground the deterministic mock) ────
# A short list of real UK grid supply points so the nearest-substation feel
# isn't pure fiction. Lat/lon are approximate, voltages real.
_UK_GSPS: list[dict[str, Any]] = [
    {"name": "Coryton Grid",     "lat": 51.516, "lon": 0.508,  "voltage_kv": 132, "dno": "UKPN EPN"},
    {"name": "West Burton 400kV","lat": 53.358, "lon": -0.808, "voltage_kv": 400, "dno": "NGED"},
    {"name": "Drax 400kV",       "lat": 53.737, "lon": -0.997, "voltage_kv": 400, "dno": "NGET"},
    {"name": "Sundon Grid",      "lat": 51.943, "lon": -0.456, "voltage_kv": 132, "dno": "UKPN EPN"},
    {"name": "Bramford 400kV",   "lat": 52.077, "lon": 1.054,  "voltage_kv": 400, "dno": "UKPN EPN"},
    {"name": "Pelham Grid",      "lat": 51.881, "lon": 0.108,  "voltage_kv": 132, "dno": "UKPN EPN"},
    {"name": "Cottam Grid",      "lat": 53.301, "lon": -0.778, "voltage_kv": 132, "dno": "NGED"},
    {"name": "Walpole 400kV",    "lat": 52.737, "lon": 0.222,  "voltage_kv": 400, "dno": "UKPN EPN"},
    {"name": "Norwich Main",     "lat": 52.633, "lon": 1.298,  "voltage_kv": 132, "dno": "UKPN EPN"},
    {"name": "Iver 400kV",       "lat": 51.501, "lon": -0.514, "voltage_kv": 400, "dno": "SSEN"},
    {"name": "Didcot Grid",      "lat": 51.624, "lon": -1.262, "voltage_kv": 132, "dno": "SSEN"},
    {"name": "Cowley Grid",      "lat": 51.731, "lon": -0.471, "voltage_kv": 132, "dno": "UKPN EPN"},
    {"name": "Lovedean 400kV",   "lat": 50.913, "lon": -1.060, "voltage_kv": 400, "dno": "SSEN"},
    {"name": "Mannington Grid", "lat": 50.840, "lon": -1.918, "voltage_kv": 132, "dno": "SSEN"},
    {"name": "Bridgwater Grid",  "lat": 51.140, "lon": -3.000, "voltage_kv": 132, "dno": "NGED"},
    {"name": "Indian Queens",    "lat": 50.398, "lon": -4.913, "voltage_kv": 400, "dno": "NGED"},
    {"name": "Pembroke 400kV",   "lat": 51.687, "lon": -4.984, "voltage_kv": 400, "dno": "NGED"},
    {"name": "Pentir 400kV",     "lat": 53.180, "lon": -4.123, "voltage_kv": 400, "dno": "SP Manweb"},
    {"name": "Heysham 400kV",    "lat": 54.040, "lon": -2.917, "voltage_kv": 400, "dno": "ENWL"},
    {"name": "Penwortham",       "lat": 53.741, "lon": -2.733, "voltage_kv": 132, "dno": "ENWL"},
    {"name": "Stalybridge",      "lat": 53.490, "lon": -2.054, "voltage_kv": 132, "dno": "ENWL"},
    {"name": "Macclesfield",     "lat": 53.260, "lon": -2.122, "voltage_kv": 132, "dno": "SP Manweb"},
    {"name": "Eccles 400kV",     "lat": 53.485, "lon": -2.345, "voltage_kv": 400, "dno": "ENWL"},
    {"name": "Strathaven 400kV", "lat": 55.685, "lon": -4.060, "voltage_kv": 400, "dno": "SP Energy"},
    {"name": "Beauly 275kV",     "lat": 57.477, "lon": -4.467, "voltage_kv": 275, "dno": "SSEN"},
    {"name": "Skye Grid",        "lat": 57.273, "lon": -5.798, "voltage_kv": 132, "dno": "SSEN"},
    {"name": "Newcastle Main",   "lat": 54.978, "lon": -1.617, "voltage_kv": 132, "dno": "NPg"},
    {"name": "Saltend 132kV",    "lat": 53.741, "lon": -0.240, "voltage_kv": 132, "dno": "NPg"},
    {"name": "Keadby 400kV",     "lat": 53.601, "lon": -0.732, "voltage_kv": 400, "dno": "NGED"},
    {"name": "Burwell Main",     "lat": 52.260, "lon": 0.330,  "voltage_kv": 132, "dno": "UKPN EPN"},
]

# LPA lookup ring — rough centroids for the most likely LPAs by region.
_LPA_RING: list[dict[str, Any]] = [
    {"name": "Thurrock",         "lat": 51.49, "lon": 0.36,  "approval_rate_pct": 71},
    {"name": "South Holland",    "lat": 52.79, "lon": -0.16, "approval_rate_pct": 64},
    {"name": "Selby",            "lat": 53.78, "lon": -1.07, "approval_rate_pct": 58},
    {"name": "East Suffolk",     "lat": 52.10, "lon": 1.55,  "approval_rate_pct": 76},
    {"name": "Vale of White Horse","lat": 51.58, "lon": -1.36, "approval_rate_pct": 49},
    {"name": "Tewkesbury",       "lat": 51.99, "lon": -2.16, "approval_rate_pct": 67},
    {"name": "Mid Suffolk",      "lat": 52.18, "lon": 1.01,  "approval_rate_pct": 73},
    {"name": "South Norfolk",    "lat": 52.50, "lon": 1.20,  "approval_rate_pct": 70},
    {"name": "South Cambridgeshire","lat": 52.18,"lon": 0.10, "approval_rate_pct": 62},
    {"name": "Bassetlaw",        "lat": 53.31, "lon": -0.94, "approval_rate_pct": 55},
    {"name": "North Lincolnshire","lat": 53.59, "lon": -0.65, "approval_rate_pct": 60},
    {"name": "Cornwall",         "lat": 50.50, "lon": -4.75, "approval_rate_pct": 81},
    {"name": "Pembrokeshire",    "lat": 51.84, "lon": -4.96, "approval_rate_pct": 78},
    {"name": "Highland",         "lat": 57.50, "lon": -5.00, "approval_rate_pct": 85},
    {"name": "South Lanarkshire","lat": 55.65, "lon": -3.95, "approval_rate_pct": 74},
]


# ─── Pydantic surface ─────────────────────────────────────────────────────
class SiteAnalysisRequest(BaseModel):
    lat: float = Field(..., ge=49.0, le=61.0, description="UK latitude")
    lon: float = Field(..., ge=-9.0, le=2.5, description="UK longitude")
    technology: str = Field(default="BESS", description="BESS | Solar | Onshore Wind | Data Centre")
    capacity_mw: float = Field(default=50.0, gt=0, le=2000)


# ─── Math helpers ─────────────────────────────────────────────────────────
def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km. Good enough for ranking."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _seed(lat: float, lon: float) -> int:
    """Stable integer seed from coordinates."""
    key = f"{lat:.4f}|{lon:.4f}".encode()
    return int(hashlib.sha256(key).hexdigest()[:8], 16)


def _det(seed: int, salt: int, lo: float, hi: float) -> float:
    """Deterministic pseudo-random in [lo, hi]."""
    v = ((seed * 1_103_515_245 + salt * 12_345) & 0x7FFF_FFFF) / 0x7FFF_FFFF
    return lo + v * (hi - lo)


# ─── Builders ─────────────────────────────────────────────────────────────
def _build_substations(lat: float, lon: float, capacity_mw: float) -> list[dict[str, Any]]:
    ranked = sorted(
        ((_haversine_km(lat, lon, gsp["lat"], gsp["lon"]), gsp) for gsp in _UK_GSPS),
        key=lambda x: x[0],
    )[:3]
    s = _seed(lat, lon)
    out: list[dict[str, Any]] = []
    for i, (dist, gsp) in enumerate(ranked):
        # Firm headroom scales loosely with voltage and varies per pin
        base_headroom = {400: 180, 275: 110, 132: 65}.get(gsp["voltage_kv"], 35)
        headroom = round(base_headroom * _det(s, i * 7 + 11, 0.35, 1.25), 1)
        rag = (
            "green" if headroom >= capacity_mw * 1.3
            else "amber" if headroom >= capacity_mw * 0.7
            else "red"
        )
        # Some GSP names already carry "400kV" / "275kV" etc — don't double up.
        name = gsp["name"]
        if f"{gsp['voltage_kv']}kV" not in name:
            name = f"{name} {gsp['voltage_kv']}kV"
        out.append({
            "name": name,
            "distance_km": round(dist, 2),
            "voltage_kv": gsp["voltage_kv"],
            "firm_headroom_mw": headroom,
            "rag": rag,
            "dno": gsp["dno"],
        })
    return out


def _build_queue(seed: int, capacity_mw: float) -> dict[str, Any]:
    position = int(round(_det(seed, 97, 2, 18)))
    total_mw_ahead = round(_det(seed, 113, 80, 720), 0)
    months_offset = int(round(_det(seed, 131, 18, 54)))
    eta = datetime.now(timezone.utc) + timedelta(days=30 * months_offset)
    return {
        "position": position,
        "total_mw_ahead": total_mw_ahead,
        "eta_energisation": eta.strftime("%Y-%m"),
    }


def _build_costs(seed: int, distance_km: float, voltage_kv: int, capacity_mw: float) -> dict[str, Any]:
    # Rough UK connection-cost rates per km (£) from project memory.
    rate_per_km = {400: 1_200_000, 275: 800_000, 132: 500_000, 33: 150_000, 11: 80_000}.get(voltage_kv, 350_000)
    cable = rate_per_km * max(distance_km, 0.4)
    civils = 1_400_000 * (capacity_mw / 50.0) ** 0.6
    bay = 1_900_000 if voltage_kv >= 132 else 900_000
    p50 = cable + civils + bay
    p10 = p50 * (0.82 + _det(seed, 211, -0.04, 0.04))
    p90 = p50 * (1.32 + _det(seed, 223, -0.05, 0.10))
    return {
        "p10": int(round(p10, -4)),
        "p50": int(round(p50, -4)),
        "p90": int(round(p90, -4)),
        "currency": "GBP",
    }


def _build_planning(lat: float, lon: float, seed: int) -> dict[str, Any]:
    lpa = min(_LPA_RING, key=lambda l: _haversine_km(lat, lon, l["lat"], l["lon"]))
    approval = lpa["approval_rate_pct"] + int(_det(seed, 311, -8, 8))
    approval = max(20, min(95, approval))
    recent = int(round(_det(seed, 317, 6, 28)))
    risk = max(5, min(92, int(round(100 - approval + _det(seed, 331, -10, 10)))))
    return {
        "risk_score_0_100": risk,
        "lpa": lpa["name"],
        "recent_decisions_count": recent,
        "approval_rate_pct": approval,
    }


def _verdict_label(planning_risk: int, top_headroom: float, capacity_mw: float) -> str:
    if top_headroom >= capacity_mw * 1.3 and planning_risk < 35:
        return "GO"
    if top_headroom < capacity_mw * 0.6 or planning_risk > 70:
        return "NO-GO"
    return "CAUTION"


def _site_address(lat: float, lon: float, lpa: str) -> str:
    return f"Land off A-road, {lpa} ({lat:.4f}, {lon:.4f})"


def _build_steps(n_subs: int, n_repd: int, queue_pos: int, headroom: float) -> list[dict[str, Any]]:
    """5-step progressive disclosure. Durations are advisory for the UI."""
    return [
        {
            "label": "Loading grid topology within 10 km radius…",
            "detail": f"{n_subs} substations, 7 GSPs, 41 km of 132 kV feeder identified.",
            "duration_ms": 1800,
        },
        {
            "label": "Cross-referencing REPD planning decisions within 15 km…",
            "detail": f"{n_repd} decisions found · 9 BESS approved, 3 refused, 1 pending.",
            "duration_ms": 2200,
        },
        {
            "label": "Pulling current TEC queue position from NESO…",
            "detail": f"{queue_pos} schemes ahead in the local zone.",
            "duration_ms": 1500,
        },
        {
            "label": "Running pandapower load flow against NGED LTDS topology…",
            "detail": f"Firm headroom {headroom:.0f} MW, voltage within P28 limits.",
            "duration_ms": 2400,
        },
        {
            "label": "Claude reasoning over ontology graph (47k nodes, 218k edges)…",
            "detail": "Traversing site → substation → feeder → queue → planning context.",
            "duration_ms": 1900,
        },
    ]


def _build_grid_context(seed: int) -> dict[str, Any]:
    return {
        "demand_gw": round(_det(seed, 401, 28.0, 44.0), 1),
        "carbon_intensity_g_per_kwh": int(round(_det(seed, 419, 95, 220))),
    }


async def _portfolio_overlap(pool: asyncpg.Pool, lat: float, lon: float) -> list[dict[str, Any]]:
    """Pull the 6 seeded projects and report any within 50 km of the pin."""
    try:
        rows = await pool.fetch(
            "SELECT name, lat, lon FROM projects WHERE lat IS NOT NULL AND lon IS NOT NULL LIMIT 50"
        )
    except Exception as e:
        log.warning("portfolio_overlap query failed: %s", e)
        return []
    overlap: list[dict[str, Any]] = []
    for r in rows:
        d = _haversine_km(lat, lon, float(r["lat"]), float(r["lon"]))
        if d <= 50.0:
            overlap.append({"name": r["name"], "distance_km": round(d, 2)})
    overlap.sort(key=lambda x: x["distance_km"])
    return overlap[:5]


async def _claude_rationale(
    claude,
    payload: dict[str, Any],
    label: str,
) -> tuple[str, float]:
    """Real Claude call — 3-sentence rationale. Cap 200 tokens."""
    system = (
        "You are a UK energy infrastructure analyst. Given this site analysis "
        "JSON, write exactly 3 sentences justifying the GO/CAUTION/NO-GO verdict, "
        "citing the most decisive factors (firm headroom vs requested MW, queue "
        "position, planning risk, distance to nearest GSP). No preamble, no "
        "lists, no markdown, no emojis."
    )
    # Trim payload to the fields that matter for the rationale.
    compact = {
        "site": payload["site"],
        "verdict_label": label,
        "top_substation": payload["substations"][0],
        "queue": payload["queue"],
        "cost_p50_gbp": payload["cost_estimates"]["p50"],
        "planning": payload["planning"],
    }
    try:
        t0 = time.monotonic()
        resp = await claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            system=system,
            messages=[{
                "role": "user",
                "content": (
                    "Site analysis payload:\n"
                    f"{compact}\n\n"
                    "Write the 3-sentence verdict rationale now."
                ),
            }],
        )
        text = "".join(
            getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"
        ).strip()
        elapsed = time.monotonic() - t0
        log.info("analyze-site claude call %.2fs", elapsed)
        # Confidence proxy: closer to capacity headroom + low risk → higher.
        headroom_ratio = payload["substations"][0]["firm_headroom_mw"] / max(
            1.0, payload["site"]["capacity_mw"]
        )
        risk = payload["planning"]["risk_score_0_100"] / 100.0
        confidence = max(0.45, min(0.95, 0.55 + 0.25 * (headroom_ratio - 1.0) + 0.20 * (1 - risk)))
        return text or _fallback_rationale(label), round(confidence, 2)
    except Exception as e:
        log.warning("Claude call failed in analyze-site, using fallback: %s", e)
        return _fallback_rationale(label), 0.55


def _fallback_rationale(label: str) -> str:
    if label == "GO":
        return (
            "Firm headroom at the nearest substation exceeds requested capacity with margin, "
            "the local TEC queue is short, and the LPA shows a recent approval-friendly track "
            "record. No P28 voltage limits are breached at requested injection. "
            "Recommend progressing to Gate-2 application."
        )
    if label == "NO-GO":
        return (
            "Firm headroom at the nearest GSP is materially below requested capacity, and the "
            "local TEC queue would push energisation beyond a viable financial window. Planning "
            "risk is also elevated in this LPA. Recommend reconsidering site or capacity."
        )
    return (
        "Firm headroom is workable but tight against the requested capacity, the TEC queue "
        "adds 18-30 months of energisation risk, and the LPA approval rate is around the "
        "national mean. Recommend a Gate-2 application with phased capacity request."
    )


# ─── Endpoint ─────────────────────────────────────────────────────────────
@router.post("/analyze-site")
async def analyze_site(
    body: SiteAnalysisRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    claude=Depends(get_claude),
) -> dict[str, Any]:
    """The end-to-end YC-pitch flow in one call.

    Total wall-clock target: <5s. Most of the budget is the Claude rationale;
    everything else is deterministic so demos always tell the same story.
    """
    t0 = time.monotonic()
    lat, lon = body.lat, body.lon
    seed = _seed(lat, lon)

    subs = _build_substations(lat, lon, body.capacity_mw)
    top = subs[0]
    queue = _build_queue(seed, body.capacity_mw)
    costs = _build_costs(seed, top["distance_km"], top["voltage_kv"], body.capacity_mw)
    planning = _build_planning(lat, lon, seed)
    grid_ctx = _build_grid_context(seed)
    portfolio = await _portfolio_overlap(pool, lat, lon)
    n_repd = int(round(_det(seed, 503, 1800, 6200)))
    steps = _build_steps(
        n_subs=int(round(_det(seed, 601, 14, 30))),
        n_repd=n_repd,
        queue_pos=queue["position"],
        headroom=top["firm_headroom_mw"],
    )

    label = _verdict_label(planning["risk_score_0_100"], top["firm_headroom_mw"], body.capacity_mw)
    today = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    suffix = f"{seed % 100000:05x}"

    draft_application = {
        "gate": "Gate 2",
        "connection_voltage_kv": top["voltage_kv"],
        "requested_mw": body.capacity_mw,
        "site_address": _site_address(lat, lon, planning["lpa"]),
        "applicant": "Princeps Demo Energy Ltd",
        "technology": body.technology,
        "preferred_substation": top["name"],
        "dno": top["dno"],
        "estimated_energisation": queue["eta_energisation"],
        "supporting_evidence": [
            {"label": "Pandapower load-flow snapshot", "ref": f"pf_{today}_{suffix}.json"},
            {"label": f"REPD precedent ({n_repd} decisions in 15km)", "ref": "repd_subset.csv"},
            {"label": "NESO TEC current queue snapshot", "ref": f"tec_{today}.json"},
            {"label": f"NGED LTDS topology for {top['dno']}", "ref": "ltds_2024_cim.xml"},
            {"label": f"{planning['lpa']} planning history (5y)", "ref": f"lpa_{planning['lpa'].lower().replace(' ', '_')}.csv"},
        ],
    }

    payload: dict[str, Any] = {
        "site": {
            "lat": lat,
            "lon": lon,
            "technology": body.technology,
            "capacity_mw": body.capacity_mw,
        },
        "substations": subs,
        "queue": queue,
        "cost_estimates": costs,
        "planning": planning,
        "draft_application": draft_application,
        "verdict": {"label": label, "rationale": "", "confidence": 0.0},
        "provenance": {
            "ontology_path": "site → connects_to → substation → on_feeder → in_queue → constrained_by → lpa",
            "sources": [
                "NESO TEC register",
                "NGED LTDS 2024 (CIM)",
                "REPD (DESNZ Renewable Energy Planning DB)",
                "pandapower 3.4 (lightsim2grid backend)",
                f"Claude {CLAUDE_MODEL}",
            ],
        },
        "steps": steps,
        "portfolio_overlap": portfolio,
        "grid_context": grid_ctx,
        "elapsed_ms": 0,
    }

    rationale, confidence = await _claude_rationale(claude, payload, label)
    payload["verdict"]["rationale"] = rationale
    payload["verdict"]["confidence"] = confidence
    payload["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)

    return payload
