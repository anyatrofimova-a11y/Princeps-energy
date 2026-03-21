"""Construction Monitoring — satellite-based construction activity detection.

Uses GeeFlow NDVI timeseries from geeflow_extractions to detect earthworks,
panel/turbine installation, and energisation at pipeline project sites.

For sites without GEE access, falls back to an analytical model based on
REPD status changes and typical construction timelines.

Detection approach:
  1. Query geeflow_extractions for NDVI extractions near the site
  2. If NDVI drops >0.2 over 6 months -> earthworks / site clearance
  3. If NDVI stays low + built-area increases -> installation in progress
  4. If built-area stabilises -> commissioning / energised
  5. No significant change -> no_change
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, date, timedelta
from typing import Any
from uuid import UUID

log = logging.getLogger("princeps.construction_monitor")


# ---------------------------------------------------------------------------
# Construction milestone templates
# ---------------------------------------------------------------------------

SOLAR_MILESTONES: list[dict[str, Any]] = [
    {"phase": "Mobilisation", "weeks": 2, "description": "Site setup, temporary access, welfare"},
    {"phase": "Civils & Earthworks", "weeks": 4, "description": "Access roads, cable trenching, foundations"},
    {"phase": "Mounting Structure", "weeks": 6, "description": "Pile driving, tracker/fixed mount installation"},
    {"phase": "Module Installation", "weeks": 8, "description": "Panel mounting, string wiring"},
    {"phase": "Electrical BOS", "weeks": 4, "description": "Inverters, transformers, switchgear, cabling"},
    {"phase": "Grid Connection", "weeks": 2, "description": "DNO witnessing, commissioning, G99 tests"},
    {"phase": "Snagging & Handover", "weeks": 2, "description": "Defect rectification, O&M handover, PAC"},
]

WIND_MILESTONES: list[dict[str, Any]] = [
    {"phase": "Mobilisation", "weeks": 3, "description": "Site setup, crane pads, temporary roads"},
    {"phase": "Civils & Earthworks", "weeks": 8, "description": "Access tracks, foundations, crane hardstandings"},
    {"phase": "Foundation Curing", "weeks": 4, "description": "Gravity base / piled foundation cure period"},
    {"phase": "Turbine Delivery", "weeks": 4, "description": "Component delivery, laydown area staging"},
    {"phase": "Turbine Erection", "weeks": 12, "description": "Tower, nacelle, rotor assembly and lift"},
    {"phase": "Electrical BOS", "weeks": 6, "description": "Array cabling, substation, control building"},
    {"phase": "Grid Connection", "weeks": 4, "description": "DNO/TO witnessing, G99 compliance, commissioning"},
    {"phase": "Snagging & Handover", "weeks": 3, "description": "Defect rectification, SCADA tuning, PAC"},
]

BESS_MILESTONES: list[dict[str, Any]] = [
    {"phase": "Mobilisation", "weeks": 2, "description": "Site setup, security fencing, welfare"},
    {"phase": "Civils & Earthworks", "weeks": 3, "description": "Foundations, cable trenching, drainage"},
    {"phase": "Container Delivery", "weeks": 2, "description": "Battery container placement, HVAC hookup"},
    {"phase": "Electrical Installation", "weeks": 4, "description": "PCS, transformers, switchgear, cabling"},
    {"phase": "Controls & SCADA", "weeks": 2, "description": "EMS, BMS, SCADA integration and testing"},
    {"phase": "Grid Connection", "weeks": 2, "description": "DNO witnessing, protection relay testing, G99"},
    {"phase": "Snagging & Handover", "weeks": 2, "description": "Defect rectification, performance testing, PAC"},
]

MILESTONE_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "solar": SOLAR_MILESTONES,
    "wind": WIND_MILESTONES,
    "bess": BESS_MILESTONES,
}

# Total expected construction durations (weeks) by technology + capacity
_DURATION_MAP = {
    "solar_small":  28,   # <50MW: ~7 months
    "solar_large":  44,   # >=50MW: ~11 months
    "wind":         52,   # ~12-14 months
    "bess":         17,   # ~4 months
}

# Phase detection thresholds
_NDVI_DROP_THRESHOLD = 0.2       # NDVI decrease indicating earthworks
_NDVI_LOW_THRESHOLD = 0.15       # NDVI level indicating bare/built ground
_BUILT_INCREASE_THRESHOLD = 5.0  # percentage points increase in built class


# ---------------------------------------------------------------------------
# Core: detect_construction_activity
# ---------------------------------------------------------------------------

async def detect_construction_activity(
    lat: float,
    lon: float,
    radius_m: float = 500,
    pool=None,
) -> dict[str, Any]:
    """Detect construction activity at a location using NDVI change analysis.

    Queries geeflow_extractions for vegetation (NDVI) and change_detection
    data near the coordinates. Compares recent vs baseline NDVI to infer
    construction phase.

    Returns:
        activity_detected (bool), confidence (0-1),
        phase (earthworks/foundations/installation/energised/no_change),
        ndvi_change, date_range
    """
    radius_km = radius_m / 1000.0

    # Default result for when no DB data is available
    result = {
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
        "activity_detected": False,
        "confidence": 0.0,
        "phase": "no_change",
        "ndvi_change": 0.0,
        "built_change_pct": 0.0,
        "date_range": None,
        "data_source": "none",
        "details": {},
    }

    if pool is None:
        result["data_source"] = "analytical_fallback"
        result["details"]["note"] = "No database pool — analytical fallback only"
        return result

    async with pool.acquire() as conn:
        # ----- Fetch NDVI timeseries from geeflow_extractions -----
        ndvi_rows = await conn.fetch(
            """
            SELECT result_data, created_at
            FROM geeflow_extractions
            WHERE mode IN ('vegetation', 'ndvi_timeseries')
              AND abs(lat - $1) < 0.01 AND abs(lon - $2) < 0.01
              AND radius_km <= $3 * 2
            ORDER BY created_at ASC
            """,
            lat, lon, radius_km,
        )

        # ----- Fetch change detection data -----
        change_rows = await conn.fetch(
            """
            SELECT result_data, created_at
            FROM geeflow_extractions
            WHERE mode = 'change_detection'
              AND abs(lat - $1) < 0.01 AND abs(lon - $2) < 0.01
              AND radius_km <= $3 * 2
            ORDER BY created_at DESC LIMIT 1
            """,
            lat, lon, radius_km,
        )

    if not ndvi_rows and not change_rows:
        result["data_source"] = "no_satellite_data"
        result["details"]["note"] = (
            "No GeeFlow extractions found for this location. "
            "Run /geeflow/extract/vegetation or /geeflow/extract/ndvi_timeseries first."
        )
        return result

    # ----- Analyse NDVI changes -----
    ndvi_values: list[dict] = []
    for row in ndvi_rows:
        data = row["result_data"]
        if isinstance(data, str):
            data = json.loads(data)

        created = row["created_at"]

        # Handle ndvi_timeseries mode (multi-year)
        if data.get("mode") == "ndvi_timeseries":
            for annual in data.get("annual_data", []):
                ndvi_values.append({
                    "year": annual.get("year"),
                    "ndvi_mean": annual.get("ndvi_mean", 0),
                    "ndvi_std": annual.get("ndvi_std", 0),
                    "date": created,
                })
        # Handle vegetation mode (single year monthly)
        elif data.get("mode") == "vegetation":
            annual_ndvi = data.get("annual_ndvi_mean", 0)
            year = data.get("year", created.year if created else None)
            ndvi_values.append({
                "year": year,
                "ndvi_mean": annual_ndvi,
                "ndvi_std": data.get("annual_ndvi_std", 0),
                "date": created,
            })

    # ----- Analyse change detection -----
    built_change = 0.0
    if change_rows:
        cd_data = change_rows[0]["result_data"]
        if isinstance(cd_data, str):
            cd_data = json.loads(cd_data)
        changes_pct = cd_data.get("changes_pct", {})
        built_change = changes_pct.get("built", 0.0)

    # ----- Determine construction phase -----
    if len(ndvi_values) >= 2:
        # Sort by year
        ndvi_values.sort(key=lambda x: x.get("year", 0))
        baseline = ndvi_values[0]
        latest = ndvi_values[-1]
        ndvi_change = latest["ndvi_mean"] - baseline["ndvi_mean"]

        result["ndvi_change"] = round(ndvi_change, 4)
        result["built_change_pct"] = round(built_change, 1)
        result["data_source"] = "geeflow_satellite"
        result["date_range"] = {
            "baseline_year": baseline.get("year"),
            "latest_year": latest.get("year"),
        }
        result["details"] = {
            "baseline_ndvi": round(baseline["ndvi_mean"], 4),
            "latest_ndvi": round(latest["ndvi_mean"], 4),
            "ndvi_trend": "declining" if ndvi_change < -0.05 else "stable" if abs(ndvi_change) < 0.05 else "increasing",
            "built_area_change_pct": round(built_change, 1),
            "extractions_analysed": len(ndvi_values),
        }

        # Phase classification logic
        if ndvi_change < -_NDVI_DROP_THRESHOLD:
            # Significant NDVI drop — earthworks or construction
            result["activity_detected"] = True
            if built_change > _BUILT_INCREASE_THRESHOLD:
                # Built area increased significantly — installation phase
                result["phase"] = "installation"
                result["confidence"] = min(0.9, 0.5 + abs(ndvi_change) + built_change / 20)
            elif latest["ndvi_mean"] < _NDVI_LOW_THRESHOLD:
                # Very low NDVI — foundations / early construction
                result["phase"] = "foundations"
                result["confidence"] = min(0.85, 0.4 + abs(ndvi_change))
            else:
                # Moderate NDVI drop — earthworks in progress
                result["phase"] = "earthworks"
                result["confidence"] = min(0.8, 0.3 + abs(ndvi_change))

        elif latest["ndvi_mean"] < _NDVI_LOW_THRESHOLD and built_change > _BUILT_INCREASE_THRESHOLD * 2:
            # Low NDVI + large built increase — project likely energised / complete
            result["activity_detected"] = True
            result["phase"] = "energised"
            result["confidence"] = min(0.85, 0.5 + built_change / 30)

        elif built_change > _BUILT_INCREASE_THRESHOLD:
            # Moderate built increase without big NDVI drop — possible installation
            result["activity_detected"] = True
            result["phase"] = "installation"
            result["confidence"] = min(0.7, 0.3 + built_change / 20)

        else:
            # No significant change
            result["activity_detected"] = False
            result["phase"] = "no_change"
            result["confidence"] = 0.7  # high confidence of no change

    elif len(ndvi_values) == 1:
        # Only one data point — limited analysis
        single = ndvi_values[0]
        result["data_source"] = "geeflow_satellite"
        result["details"] = {
            "note": "Single extraction — cannot determine temporal change",
            "ndvi_mean": round(single["ndvi_mean"], 4),
            "year": single.get("year"),
        }
        if single["ndvi_mean"] < _NDVI_LOW_THRESHOLD and built_change > _BUILT_INCREASE_THRESHOLD:
            result["activity_detected"] = True
            result["phase"] = "installation"
            result["confidence"] = 0.4
        elif single["ndvi_mean"] < _NDVI_LOW_THRESHOLD:
            result["activity_detected"] = True
            result["phase"] = "earthworks"
            result["confidence"] = 0.3

    # Clamp confidence
    result["confidence"] = round(min(1.0, max(0.0, result["confidence"])), 2)

    return result


# ---------------------------------------------------------------------------
# Core: monitor_pipeline_sites
# ---------------------------------------------------------------------------

async def monitor_pipeline_sites(pool) -> list[dict[str, Any]]:
    """Scan all construction/energised-stage projects for construction activity.

    Queries the projects table for sites in 'construction' or 'energised' stage,
    then checks each for satellite-detected construction activity.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT project_id, name, technology, capacity_mw, lat, lon, stage,
                   stage_entered_at, created_at
            FROM projects
            WHERE stage IN ('construction', 'energised')
              AND lat IS NOT NULL AND lon IS NOT NULL
            ORDER BY stage_entered_at DESC NULLS LAST
            LIMIT 200
            """
        )

    if not rows:
        return []

    results = []
    for row in rows:
        try:
            activity = await detect_construction_activity(
                lat=row["lat"],
                lon=row["lon"],
                radius_m=500,
                pool=pool,
            )

            # Determine if satellite data conflicts with recorded stage
            stage = row["stage"]
            satellite_phase = activity.get("phase", "no_change")
            stage_mismatch = False

            if stage == "construction" and satellite_phase == "no_change" and activity["confidence"] > 0.5:
                stage_mismatch = True
            elif stage == "energised" and satellite_phase in ("earthworks", "foundations"):
                stage_mismatch = True

            results.append({
                "project_id": str(row["project_id"]),
                "name": row["name"],
                "technology": row["technology"],
                "capacity_mw": float(row["capacity_mw"]) if row["capacity_mw"] else None,
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "recorded_stage": stage,
                "stage_entered_at": row["stage_entered_at"].isoformat() if row["stage_entered_at"] else None,
                "satellite_detection": activity,
                "stage_mismatch": stage_mismatch,
            })
        except Exception as exc:
            log.warning("Failed to monitor project %s: %s", row["project_id"], exc)
            results.append({
                "project_id": str(row["project_id"]),
                "name": row["name"],
                "error": str(exc)[:200],
            })

    return results


# ---------------------------------------------------------------------------
# Core: estimate_completion
# ---------------------------------------------------------------------------

async def estimate_completion(
    project_id: str,
    pool,
) -> dict[str, Any]:
    """Estimate construction completion for a project.

    Uses technology and capacity to calculate expected duration,
    then compares construction start date to now.
    """
    pid = UUID(project_id)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT project_id, name, technology, capacity_mw, lat, lon,
                   stage, stage_entered_at, created_at, metadata
            FROM projects
            WHERE project_id = $1
            """,
            pid,
        )

    if not row:
        return {"error": "Project not found", "project_id": project_id}

    technology = (row["technology"] or "solar").lower()
    capacity_mw = float(row["capacity_mw"]) if row["capacity_mw"] else 50.0
    stage = row["stage"]
    stage_entered = row["stage_entered_at"]

    # Determine construction start date
    if stage in ("construction", "energised") and stage_entered:
        construction_start = stage_entered.date() if hasattr(stage_entered, 'date') else stage_entered
    else:
        # Project not yet in construction — estimate from now
        construction_start = date.today()

    # Calculate expected duration
    timeline = construction_timeline(technology, capacity_mw)
    total_weeks = timeline["total_weeks"]
    expected_duration = timedelta(weeks=total_weeks)
    estimated_completion = construction_start + expected_duration

    # Calculate progress
    today = date.today()
    elapsed = (today - construction_start).days
    total_days = expected_duration.days
    pct_complete = min(100.0, max(0.0, (elapsed / total_days * 100) if total_days > 0 else 0))

    # On-track assessment
    days_ahead_behind = (estimated_completion - today).days
    if stage == "energised":
        on_track = True
        pct_complete = 100.0
    elif days_ahead_behind >= 0:
        on_track = True
    else:
        on_track = False

    # Current milestone estimate
    current_milestone = _estimate_current_milestone(technology, pct_complete)

    return {
        "project_id": project_id,
        "name": row["name"],
        "technology": technology,
        "capacity_mw": capacity_mw,
        "stage": stage,
        "construction_start": construction_start.isoformat(),
        "estimated_completion": estimated_completion.isoformat(),
        "total_weeks": total_weeks,
        "pct_complete": round(pct_complete, 1),
        "on_track": on_track,
        "days_ahead_behind": days_ahead_behind,
        "current_milestone": current_milestone,
        "milestones": timeline["milestones"],
    }


def _estimate_current_milestone(technology: str, pct_complete: float) -> dict[str, Any]:
    """Given completion %, estimate which milestone the project is in."""
    tech_key = technology.lower().replace("battery", "bess")
    milestones = MILESTONE_TEMPLATES.get(tech_key, SOLAR_MILESTONES)
    total_weeks = sum(m["weeks"] for m in milestones)
    cumulative = 0.0

    for ms in milestones:
        ms_pct_start = (cumulative / total_weeks) * 100
        cumulative += ms["weeks"]
        ms_pct_end = (cumulative / total_weeks) * 100
        if pct_complete <= ms_pct_end:
            return {
                "phase": ms["phase"],
                "description": ms["description"],
                "pct_through_phase": round(
                    (pct_complete - ms_pct_start) / (ms_pct_end - ms_pct_start) * 100
                    if ms_pct_end > ms_pct_start else 0, 1
                ),
            }

    # Past 100%
    return {
        "phase": milestones[-1]["phase"],
        "description": milestones[-1]["description"],
        "pct_through_phase": 100.0,
    }


# ---------------------------------------------------------------------------
# Core: construction_timeline
# ---------------------------------------------------------------------------

def construction_timeline(
    technology: str,
    capacity_mw: float,
) -> dict[str, Any]:
    """Return a detailed milestone timeline with typical durations.

    Scales durations based on capacity and technology. Solar scales linearly
    for large projects; wind scales by turbine count; BESS is relatively fixed.
    """
    tech_key = technology.lower().replace("battery", "bess")
    milestones_template = MILESTONE_TEMPLATES.get(tech_key, SOLAR_MILESTONES)

    # Capacity scale factor
    if tech_key == "solar":
        if capacity_mw < 10:
            scale = 0.7
        elif capacity_mw < 50:
            scale = 1.0
        else:
            scale = 1.0 + (capacity_mw - 50) / 200  # gradual increase
    elif tech_key == "wind":
        turbines = max(1, int(capacity_mw / 4))  # ~4MW per turbine
        if turbines <= 5:
            scale = 0.8
        elif turbines <= 20:
            scale = 1.0
        else:
            scale = 1.0 + (turbines - 20) / 40
    else:  # bess
        if capacity_mw < 20:
            scale = 0.8
        elif capacity_mw < 100:
            scale = 1.0
        else:
            scale = 1.1

    scale = min(scale, 2.0)  # cap at 2x

    milestones = []
    cumulative_weeks = 0
    for ms in milestones_template:
        scaled_weeks = max(1, round(ms["weeks"] * scale))
        milestones.append({
            "phase": ms["phase"],
            "description": ms["description"],
            "duration_weeks": scaled_weeks,
            "start_week": cumulative_weeks,
            "end_week": cumulative_weeks + scaled_weeks,
        })
        cumulative_weeks += scaled_weeks

    total_weeks = cumulative_weeks

    # Expected duration ranges
    if tech_key == "solar":
        if capacity_mw < 50:
            range_weeks = (12, 28)
        else:
            range_weeks = (28, 52)
    elif tech_key == "wind":
        range_weeks = (48, 78)
    else:
        range_weeks = (12, 24)

    return {
        "technology": tech_key,
        "capacity_mw": capacity_mw,
        "total_weeks": total_weeks,
        "total_months": round(total_weeks / 4.33, 1),
        "milestones": milestones,
        "typical_range_weeks": {"min": range_weeks[0], "max": range_weeks[1]},
        "scale_factor": round(scale, 2),
        "notes": _technology_notes(tech_key, capacity_mw),
    }


def _technology_notes(technology: str, capacity_mw: float) -> list[str]:
    """Generate technology-specific construction notes."""
    notes = []
    if technology == "solar":
        notes.append(f"Solar {capacity_mw}MW — {'NSIP/DCO route' if capacity_mw >= 50 else 'TCPA route'}")
        if capacity_mw >= 50:
            notes.append("DCO projects typically add 12-18 months pre-construction for examination")
        notes.append("UK peak construction season: March-October (daylight hours, ground conditions)")
        notes.append("Module supply lead time: 8-16 weeks from order depending on manufacturer")
    elif technology == "wind":
        turbines = max(1, int(capacity_mw / 4))
        notes.append(f"Wind {capacity_mw}MW (~{turbines} turbines at 4MW)")
        notes.append("Turbine delivery requires AIL (Abnormal Indivisible Load) route survey")
        notes.append("Crane availability is a critical path item — book 6+ months ahead")
        notes.append("Foundation curing requires 28-day minimum before tower erection")
    else:
        notes.append(f"BESS {capacity_mw}MW — containerised battery energy storage")
        notes.append("Battery container lead time: 12-20 weeks from manufacturer")
        notes.append("Fire suppression system must be commissioned before energisation")
        notes.append("BESS planning typically simpler than generation — shorter overall programme")
    return notes
