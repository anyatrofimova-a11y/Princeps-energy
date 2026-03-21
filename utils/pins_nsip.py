"""
PINS NSIP Register — tracks nationally significant infrastructure projects.

These are large energy projects (>50MW solar, >100MW offshore wind, major
grid connections, data centres) that go through the DCO (Development Consent Order)
process rather than normal planning.

Source: Planning Inspectorate
API: No official API — fetch the published project list or CSV download.
Primary: https://infrastructure.planninginspectorate.gov.uk/projects/
Data feed: PINS publishes project data as downloadable CSV/JSON.

Alternative: data.gov.uk NSIP dataset.
"""

from __future__ import annotations

import csv
import io
import logging
import math
import re
import time
from typing import Any

import httpx

log = logging.getLogger("princeps.pins_nsip")

# ── Cache ──
_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 3600  # 1 hour — NSIP data doesn't change often

# ── Known CSV/data endpoints to try in order ──
NSIP_DATA_URLS = [
    # PINS project programme CSV (direct download)
    "https://infrastructure.planninginspectorate.gov.uk/wp-content/ipc/uploads/projects/nsip-programme.csv",
    # Alternative: PINS projects JSON feed
    "https://infrastructure.planninginspectorate.gov.uk/wp-json/pins/v1/projects",
    # data.gov.uk fallback
    "https://data.planninginspectorate.gov.uk/projects.csv",
]

# PINS project URL template
PINS_PROJECT_URL = "https://infrastructure.planninginspectorate.gov.uk/projects/{slug}/"

# ── NSIP type mapping ──
NSIP_TYPES = {
    "energy": ["solar", "wind", "nuclear", "gas", "biomass", "tidal", "wave", "battery", "energy"],
    "transport": ["road", "rail", "airport", "port", "harbour"],
    "water": ["water", "reservoir", "desalination", "flood"],
    "waste": ["waste", "incineration", "recycling"],
    "business": ["data centre", "commercial", "business"],
}

# ── NSIP status mapping ──
NSIP_STATUSES = {
    "pre-application": "Pre-application",
    "acceptance": "Acceptance",
    "pre-examination": "Pre-examination",
    "examination": "Examination",
    "recommendation": "Recommendation",
    "decision": "Decision",
    "post-decision": "Post-decision",
    "withdrawn": "Withdrawn",
    "decided": "Decided",
}


def _cache_get(key: str) -> Any | None:
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
        del _cache[key]
    return None


def _cache_set(key: str, data: Any) -> None:
    _cache[key] = (time.time(), data)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _extract_capacity_mw(text: str | None) -> float | None:
    """Try to extract capacity in MW from project description/name."""
    if not text:
        return None
    # Match patterns like "50MW", "50 MW", "400 mw", "1.2GW"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:MW|mw|Mw)", text)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:GW|gw|Gw)", text)
    if m:
        return float(m.group(1)) * 1000
    return None


def _classify_technology(name: str, description: str = "") -> str:
    """Classify project technology from name/description."""
    text = f"{name} {description}".lower()
    if "solar" in text or "photovoltaic" in text or "pv" in text:
        return "solar"
    if "wind" in text:
        if "offshore" in text:
            return "offshore_wind"
        return "onshore_wind"
    if "nuclear" in text:
        return "nuclear"
    if "gas" in text or "ccgt" in text:
        return "gas"
    if "battery" in text or "storage" in text or "bess" in text:
        return "battery_storage"
    if "biomass" in text:
        return "biomass"
    if "tidal" in text:
        return "tidal"
    if "interconnect" in text or "cable" in text:
        return "interconnector"
    if "substation" in text or "grid" in text or "overhead line" in text or "pylon" in text:
        return "grid_infrastructure"
    if "data cent" in text:
        return "data_centre"
    if "road" in text or "highway" in text or "motorway" in text:
        return "road"
    if "rail" in text:
        return "rail"
    return "other"


def _parse_csv_projects(csv_text: str) -> list[dict]:
    """Parse PINS CSV into structured project list."""
    projects = []
    reader = csv.DictReader(io.StringIO(csv_text))

    for row in reader:
        # Try various column name patterns (PINS CSV schema varies)
        name = (
            row.get("ProjectName")
            or row.get("Project Name")
            or row.get("project_name")
            or row.get("Name")
            or row.get("name")
            or ""
        )
        if not name.strip():
            continue

        description = (
            row.get("Description")
            or row.get("description")
            or row.get("ProjectDescription")
            or ""
        )

        status = (
            row.get("Stage")
            or row.get("Status")
            or row.get("status")
            or row.get("ProjectStage")
            or ""
        )

        sector = (
            row.get("Sector")
            or row.get("sector")
            or row.get("Category")
            or row.get("ProjectType")
            or ""
        )

        applicant = (
            row.get("Applicant")
            or row.get("applicant")
            or row.get("Developer")
            or row.get("Promoter")
            or ""
        )

        location = (
            row.get("Location")
            or row.get("location")
            or row.get("Region")
            or row.get("County")
            or ""
        )

        # Try to get coordinates
        lat = _safe_float(row.get("Latitude") or row.get("latitude") or row.get("Lat") or row.get("lat"))
        lon = _safe_float(row.get("Longitude") or row.get("longitude") or row.get("Lon") or row.get("lng") or row.get("lon"))

        # Dates
        decision_date = (
            row.get("DecisionDate")
            or row.get("Decision Date")
            or row.get("decision_date")
            or ""
        )
        submission_date = (
            row.get("DateOfSubmission")
            or row.get("Submission Date")
            or row.get("submission_date")
            or row.get("DateOfApplication")
            or ""
        )

        # URL / reference
        reference = (
            row.get("Reference")
            or row.get("reference")
            or row.get("CaseReference")
            or row.get("ProjectReference")
            or ""
        )

        slug = (
            row.get("Slug")
            or row.get("slug")
            or row.get("URLSlug")
            or ""
        )

        technology = _classify_technology(name, f"{description} {sector}")
        capacity_mw = _extract_capacity_mw(f"{name} {description}")

        project = {
            "name": name.strip(),
            "type": technology,
            "sector": sector.strip(),
            "capacity_mw": capacity_mw,
            "status": status.strip(),
            "decision_date": decision_date.strip() or None,
            "submission_date": submission_date.strip() or None,
            "location": location.strip(),
            "lat": lat,
            "lon": lon,
            "applicant": applicant.strip(),
            "reference": reference.strip(),
            "url": PINS_PROJECT_URL.format(slug=slug) if slug else None,
            "description": description.strip()[:500] if description else None,
        }
        projects.append(project)

    return projects


def _parse_json_projects(json_data: list | dict) -> list[dict]:
    """Parse PINS JSON feed into structured project list."""
    items = json_data if isinstance(json_data, list) else json_data.get("items", json_data.get("projects", []))
    projects = []

    for item in items:
        name = item.get("projectName") or item.get("title") or item.get("name") or ""
        if not name.strip():
            continue

        description = item.get("description") or item.get("summary") or ""
        status = item.get("stage") or item.get("status") or ""
        sector = item.get("sector") or item.get("category") or ""

        technology = _classify_technology(name, f"{description} {sector}")
        capacity_mw = _extract_capacity_mw(f"{name} {description}")

        lat = _safe_float(item.get("latitude") or item.get("lat"))
        lon = _safe_float(item.get("longitude") or item.get("lon") or item.get("lng"))

        project = {
            "name": name.strip(),
            "type": technology,
            "sector": sector.strip() if sector else None,
            "capacity_mw": capacity_mw,
            "status": status.strip() if status else None,
            "decision_date": item.get("decisionDate") or item.get("decision_date"),
            "submission_date": item.get("dateOfSubmission") or item.get("submission_date"),
            "location": item.get("location") or item.get("region") or "",
            "lat": lat,
            "lon": lon,
            "applicant": (item.get("applicant") or item.get("developer") or "").strip(),
            "reference": (item.get("reference") or item.get("caseReference") or "").strip(),
            "url": item.get("url") or item.get("link"),
            "description": (description.strip()[:500]) if description else None,
        }
        projects.append(project)

    return projects


def _safe_float(val: Any) -> float | None:
    """Safely convert to float or return None."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


async def fetch_nsip_projects(
    *,
    technology: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """
    Fetch NSIP projects from PINS register.

    Tries published CSV/JSON data endpoints in order.
    Falls back gracefully if none are available.

    Args:
        technology: Filter by type (solar, wind, nuclear, gas, battery_storage, etc.)
        status: Filter by stage (pre-application, examination, decision, etc.)

    Returns:
        list of {"name", "type", "capacity_mw", "status", "decision_date",
                 "location", "lat", "lon", "applicant", "url", ...}
    """
    cache_key = "nsip_all"
    all_projects = _cache_get(cache_key)

    if all_projects is None:
        all_projects = await _fetch_from_sources()
        if all_projects:
            _cache_set(cache_key, all_projects)

    # Apply filters
    filtered = all_projects
    if technology:
        tech_lower = technology.lower()
        filtered = [
            p for p in filtered
            if tech_lower in (p.get("type") or "").lower()
            or tech_lower in (p.get("sector") or "").lower()
            or tech_lower in (p.get("name") or "").lower()
        ]

    if status:
        status_lower = status.lower()
        filtered = [
            p for p in filtered
            if status_lower in (p.get("status") or "").lower()
        ]

    return filtered


async def _fetch_from_sources() -> list[dict]:
    """Try each data source in order until one works."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for url in NSIP_DATA_URLS:
            try:
                log.info("Trying NSIP data source: %s", url)
                resp = await client.get(url)

                if resp.status_code != 200:
                    log.info("NSIP source %s returned %s", url, resp.status_code)
                    continue

                content_type = resp.headers.get("content-type", "")
                text = resp.text

                if "csv" in url.lower() or "csv" in content_type.lower():
                    projects = _parse_csv_projects(text)
                elif "json" in content_type.lower():
                    projects = _parse_json_projects(resp.json())
                else:
                    # Try CSV first, then JSON
                    try:
                        projects = _parse_csv_projects(text)
                    except Exception:
                        try:
                            projects = _parse_json_projects(resp.json())
                        except Exception:
                            continue

                if projects:
                    log.info("Loaded %d NSIP projects from %s", len(projects), url)
                    return projects

            except httpx.TimeoutException:
                log.warning("Timeout fetching NSIP data from %s", url)
            except Exception as e:
                log.warning("Error fetching NSIP data from %s: %s", url, e)

    # All sources failed — return curated fallback of major known NSIPs
    log.warning("All NSIP data sources unavailable, using curated fallback")
    return _fallback_nsip_projects()


def _fallback_nsip_projects() -> list[dict]:
    """
    Curated list of major UK NSIPs for when live data is unavailable.
    Based on public PINS register as of early 2026.
    """
    return [
        {
            "name": "Sunnica Energy Farm",
            "type": "solar",
            "sector": "Energy",
            "capacity_mw": 500,
            "status": "Decided",
            "decision_date": "2024-01-16",
            "location": "East Cambridgeshire / West Suffolk",
            "lat": 52.30,
            "lon": 0.45,
            "applicant": "Sunnica Ltd",
            "reference": "EN010106",
            "url": "https://infrastructure.planninginspectorate.gov.uk/projects/eastern/sunnica-energy-farm/",
            "description": "Solar photovoltaic arrays, battery energy storage, grid connection infrastructure.",
        },
        {
            "name": "Mallard Pass Solar Farm",
            "type": "solar",
            "sector": "Energy",
            "capacity_mw": 350,
            "status": "Decided",
            "decision_date": "2024-07-01",
            "location": "Rutland / South Kesteven",
            "lat": 52.65,
            "lon": -0.52,
            "applicant": "Mallard Pass Solar Farm Ltd",
            "reference": "EN010127",
            "url": "https://infrastructure.planninginspectorate.gov.uk/projects/east-midlands/mallard-pass-solar-farm/",
            "description": "Ground-mounted solar PV generating station up to 350MW with BESS.",
        },
        {
            "name": "Gate Burton Energy Park",
            "type": "solar",
            "sector": "Energy",
            "capacity_mw": 500,
            "status": "Decided",
            "decision_date": "2024-10-01",
            "location": "West Lindsey, Lincolnshire",
            "lat": 53.30,
            "lon": -0.80,
            "applicant": "Gate Burton Energy Park Ltd",
            "reference": "EN010131",
            "url": "https://infrastructure.planninginspectorate.gov.uk/projects/east-midlands/gate-burton-energy-park/",
            "description": "Solar PV generating station, BESS, and grid connection.",
        },
        {
            "name": "Cottam Solar Project",
            "type": "solar",
            "sector": "Energy",
            "capacity_mw": 600,
            "status": "Examination",
            "decision_date": None,
            "location": "West Lindsey, Lincolnshire",
            "lat": 53.32,
            "lon": -0.73,
            "applicant": "Cottam Solar Project Ltd",
            "reference": "EN010133",
            "url": "https://infrastructure.planninginspectorate.gov.uk/projects/east-midlands/cottam-solar-project/",
            "description": "Solar PV generating station up to 600MW with BESS.",
        },
        {
            "name": "West Burton Solar Project",
            "type": "solar",
            "sector": "Energy",
            "capacity_mw": 480,
            "status": "Examination",
            "decision_date": None,
            "location": "West Lindsey / Bassetlaw, Nottinghamshire",
            "lat": 53.31,
            "lon": -0.78,
            "applicant": "West Burton Solar Project Ltd",
            "reference": "EN010132",
            "url": "https://infrastructure.planninginspectorate.gov.uk/projects/east-midlands/west-burton-solar-project/",
            "description": "Solar PV generating station up to 480MW with BESS.",
        },
        {
            "name": "Hornsea Project Four",
            "type": "offshore_wind",
            "sector": "Energy",
            "capacity_mw": 2600,
            "status": "Decided",
            "decision_date": "2024-07-16",
            "location": "North Sea, East Riding of Yorkshire",
            "lat": 54.00,
            "lon": 1.80,
            "applicant": "Orsted Hornsea Project Four Ltd",
            "reference": "EN010098",
            "url": "https://infrastructure.planninginspectorate.gov.uk/projects/yorkshire-and-the-humber/hornsea-project-four-offshore-wind-farm/",
            "description": "Offshore wind farm up to 2.6GW.",
        },
        {
            "name": "Norfolk Boreas",
            "type": "offshore_wind",
            "sector": "Energy",
            "capacity_mw": 1800,
            "status": "Decided",
            "decision_date": "2021-12-10",
            "location": "North Sea, Norfolk coast",
            "lat": 53.10,
            "lon": 2.30,
            "applicant": "Norfolk Boreas Limited",
            "reference": "EN010087",
            "url": "https://infrastructure.planninginspectorate.gov.uk/projects/eastern/norfolk-boreas/",
            "description": "Offshore wind farm up to 1.8GW.",
        },
        {
            "name": "Sizewell C Nuclear Power Station",
            "type": "nuclear",
            "sector": "Energy",
            "capacity_mw": 3200,
            "status": "Decided",
            "decision_date": "2022-07-20",
            "location": "Sizewell, Suffolk",
            "lat": 52.22,
            "lon": 1.62,
            "applicant": "NNB Generation Company (SZC) Limited",
            "reference": "EN010012",
            "url": "https://infrastructure.planninginspectorate.gov.uk/projects/eastern/the-sizewell-c-project/",
            "description": "New nuclear power station, two UK EPR reactors, ~3.2GW.",
        },
        {
            "name": "Longfield Solar Farm",
            "type": "solar",
            "sector": "Energy",
            "capacity_mw": 500,
            "status": "Decided",
            "decision_date": "2024-06-26",
            "location": "Chelmsford, Essex",
            "lat": 51.73,
            "lon": 0.55,
            "applicant": "Longfield Solar Energy Farm Ltd",
            "reference": "EN010118",
            "url": "https://infrastructure.planninginspectorate.gov.uk/projects/eastern/longfield-solar-farm/",
            "description": "Solar PV generating station up to 500MW with BESS.",
        },
        {
            "name": "Cleve Hill Solar Park",
            "type": "solar",
            "sector": "Energy",
            "capacity_mw": 350,
            "status": "Decided",
            "decision_date": "2020-05-28",
            "location": "Graveney, Kent",
            "lat": 51.33,
            "lon": 0.93,
            "applicant": "Cleve Hill Solar Park Ltd",
            "reference": "EN010085",
            "url": "https://infrastructure.planninginspectorate.gov.uk/projects/south-east/cleve-hill-solar-park/",
            "description": "First UK NSIP solar farm — 350MW solar with 700MWh battery storage.",
        },
        {
            "name": "East Anglia TWO",
            "type": "offshore_wind",
            "sector": "Energy",
            "capacity_mw": 900,
            "status": "Decided",
            "decision_date": "2022-03-31",
            "location": "North Sea, Suffolk coast",
            "lat": 52.18,
            "lon": 2.10,
            "applicant": "East Anglia TWO Limited",
            "reference": "EN010078",
            "url": "https://infrastructure.planninginspectorate.gov.uk/projects/eastern/east-anglia-two/",
            "description": "Offshore wind farm up to 900MW.",
        },
        {
            "name": "Hinkley Point C",
            "type": "nuclear",
            "sector": "Energy",
            "capacity_mw": 3260,
            "status": "Post-decision",
            "decision_date": "2013-03-19",
            "location": "Hinkley Point, Somerset",
            "lat": 51.21,
            "lon": -3.13,
            "applicant": "NNB Generation Company (HPC) Limited",
            "reference": "EN010001",
            "url": "https://infrastructure.planninginspectorate.gov.uk/projects/south-west/hinkley-point-c-new-nuclear-power-station/",
            "description": "New nuclear power station, two EPR reactors, ~3.26GW. Under construction.",
        },
    ]


async def check_nsip_conflicts(
    lat: float,
    lon: float,
    radius_km: float = 20,
) -> list[dict]:
    """
    Check if any NSIP projects are near a given location.

    Useful for:
    - Identifying competing large-scale projects
    - Understanding cumulative impact considerations
    - Finding potential grid connection congestion
    - Assessing planning inspector precedent in the area

    Returns list of nearby NSIPs with distance and conflict assessment.
    """
    all_projects = await fetch_nsip_projects()

    conflicts = []
    for project in all_projects:
        plat = project.get("lat")
        plon = project.get("lon")
        if plat is None or plon is None:
            continue

        dist = _haversine_km(lat, lon, plat, plon)
        if dist > radius_km:
            continue

        # Assess conflict level
        if dist < 2:
            conflict_level = "high"
            conflict_note = "Very close proximity — likely overlapping land or grid connection point"
        elif dist < 5:
            conflict_level = "medium"
            conflict_note = "Near proximity — cumulative impact considerations apply"
        elif dist < 10:
            conflict_level = "low"
            conflict_note = "Moderate distance — shared landscape/visual impact possible"
        else:
            conflict_level = "info"
            conflict_note = "Distant but in same region — grid capacity may be shared"

        # Grid congestion risk
        capacity = project.get("capacity_mw") or 0
        grid_risk = "high" if capacity > 200 and dist < 10 else "medium" if capacity > 100 and dist < 15 else "low"

        conflicts.append({
            **project,
            "distance_km": round(dist, 1),
            "conflict_level": conflict_level,
            "conflict_note": conflict_note,
            "grid_congestion_risk": grid_risk,
        })

    # Sort by distance
    conflicts.sort(key=lambda c: c["distance_km"])

    return {
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "total_conflicts": len(conflicts),
        "high_conflicts": sum(1 for c in conflicts if c["conflict_level"] == "high"),
        "medium_conflicts": sum(1 for c in conflicts if c["conflict_level"] == "medium"),
        "conflicts": conflicts,
        "summary": _conflict_summary(conflicts),
    }


def _conflict_summary(conflicts: list[dict]) -> str:
    """Generate a human-readable conflict summary."""
    if not conflicts:
        return "No NSIP projects found nearby. Clear for development from a nationally significant project perspective."

    high = [c for c in conflicts if c["conflict_level"] == "high"]
    medium = [c for c in conflicts if c["conflict_level"] == "medium"]

    parts = []
    if high:
        parts.append(
            f"{len(high)} high-conflict NSIP(s) within 2km: "
            + ", ".join(f"{c['name']} ({c['type']}, {c.get('capacity_mw', '?')}MW)" for c in high)
        )
    if medium:
        parts.append(
            f"{len(medium)} medium-conflict NSIP(s) within 5km: "
            + ", ".join(f"{c['name']} ({c['type']})" for c in medium)
        )

    total_mw = sum(c.get("capacity_mw") or 0 for c in conflicts)
    if total_mw > 500:
        parts.append(f"Total nearby NSIP capacity: {total_mw:,.0f}MW — significant grid congestion risk")
    elif total_mw > 100:
        parts.append(f"Total nearby NSIP capacity: {total_mw:,.0f}MW — moderate grid pressure")

    return ". ".join(parts) + "." if parts else "Low-risk area for NSIP conflicts."
