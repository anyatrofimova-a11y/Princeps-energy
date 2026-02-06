"""
Energy-Relevant Planning Applications
Extracted from buildwithtract/planning-applications scraper schema.

Filters UK planning applications for energy infrastructure:
solar, wind, battery storage, substations, grid connections,
EV charging, heat pumps, biomass, and hydroelectric.

Provides database setup, sample seeding, and query functions.
"""

import re
from datetime import date, datetime, timedelta
from uuid import UUID

import asyncpg
import numpy as np

# ---------------------------------------------------------------------------
# Energy keyword categories
# ---------------------------------------------------------------------------

ENERGY_CATEGORIES = {
    "solar": [
        "solar", "photovoltaic", "pv array", "pv panel", "pv installation",
        "solar farm", "solar park", "solar garden", "solar energy",
        "ground mounted solar", "roof mounted solar", "solar generation",
    ],
    "wind": [
        "wind turbine", "wind farm", "wind energy", "wind power",
        "onshore wind", "offshore wind", "wind generation",
    ],
    "battery_storage": [
        "battery", "energy storage", "bess", "battery energy storage",
        "grid scale storage", "storage facility", "lithium ion",
    ],
    "substation": [
        "substation", "electrical substation", "switching station",
        "transformer", "grid supply point",
    ],
    "grid": [
        "grid connection", "grid infrastructure", "power line",
        "overhead line", "underground cable", "cable route",
        "transmission line", "distribution network",
    ],
    "ev_charging": [
        "ev charging", "electric vehicle charging", "charging point",
        "charge point", "rapid charger", "ev infrastructure",
    ],
    "heat_pump": [
        "heat pump", "ground source heat", "air source heat",
        "district heating", "heat network", "geothermal",
    ],
    "biomass": [
        "biomass", "biogas", "anaerobic digestion", "wood pellet",
        "energy from waste", "waste to energy",
    ],
    "hydro": [
        "hydroelectric", "hydro power", "hydro scheme",
        "run of river", "micro hydro",
    ],
}

# Compiled regex for fast matching
_ENERGY_PATTERNS = {
    cat: re.compile("|".join(re.escape(kw) for kw in keywords), re.IGNORECASE)
    for cat, keywords in ENERGY_CATEGORIES.items()
}


def classify_energy(description: str | None) -> list[str]:
    """Return list of energy categories matching the description text."""
    if not description:
        return []
    return [cat for cat, pat in _ENERGY_PATTERNS.items() if pat.search(description)]


def is_energy_relevant(description: str | None) -> bool:
    """Check if a planning application description is energy-related."""
    return len(classify_energy(description)) > 0


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS planning_applications (
    uuid uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    lpa VARCHAR(255) NOT NULL,
    reference VARCHAR(255) NOT NULL,
    url TEXT NOT NULL,
    submitted_date DATE NOT NULL,
    validated_date DATE,
    address TEXT NOT NULL,
    description TEXT,
    application_status VARCHAR(255) NOT NULL DEFAULT 'Submitted',
    application_decision VARCHAR(255),
    application_decision_date DATE,
    application_type VARCHAR(255) NOT NULL DEFAULT 'Full Planning',
    energy_categories TEXT[],
    capacity_mw REAL,
    parish VARCHAR(255),
    ward VARCHAR(255),
    applicant_name VARCHAR(255),
    agent_name TEXT,
    environmental_assessment_requested BOOLEAN,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    centroid GEOMETRY(Point, 4326),
    first_imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT planning_apps_lpa_ref_key UNIQUE (lpa, reference)
);

CREATE INDEX IF NOT EXISTS idx_planning_apps_energy
    ON planning_applications USING GIN (energy_categories);
CREATE INDEX IF NOT EXISTS idx_planning_apps_status
    ON planning_applications (application_status);
CREATE INDEX IF NOT EXISTS idx_planning_apps_centroid
    ON planning_applications USING GIST (centroid);
"""


async def setup_table(conn: asyncpg.Connection):
    """Create the planning_applications table if not exists."""
    await conn.execute(CREATE_TABLE_SQL)


# ---------------------------------------------------------------------------
# Sample energy applications for demo
# ---------------------------------------------------------------------------

_SAMPLE_APPS = [
    {
        "lpa": "south_cambridgeshire",
        "reference": "S/2024/0312/FL",
        "url": "https://applications.greatercambridgeplanning.org/online-applications/S/2024/0312/FL",
        "submitted_date": date(2024, 3, 15),
        "address": "Land north of A505, Melbourn, SG8 6EX",
        "description": "Installation of ground mounted solar farm (49.9MW) with battery energy storage system (BESS), substation, inverters, security fencing and CCTV, landscaping and biodiversity enhancements",
        "application_status": "Under Review",
        "application_type": "Full Planning",
        "capacity_mw": 49.9,
        "lat": 52.074, "lon": 0.013,
        "applicant_name": "Lightsource bp",
    },
    {
        "lpa": "east_suffolk",
        "reference": "DC/24/1897/FUL",
        "url": "https://publicaccess.eastsuffolk.gov.uk/online-applications/DC/24/1897/FUL",
        "submitted_date": date(2024, 5, 22),
        "address": "Land at Grove Farm, Framlingham, IP13 9QH",
        "description": "Erection of 3 no. wind turbines (tip height 125m) and associated infrastructure including access tracks, crane hardstandings, substation compound and underground cabling",
        "application_status": "Decided",
        "application_decision": "Refused",
        "application_decision_date": date(2024, 11, 8),
        "application_type": "Full Planning",
        "capacity_mw": 10.5,
        "lat": 52.222, "lon": 1.344,
        "applicant_name": "RES Group",
    },
    {
        "lpa": "wiltshire",
        "reference": "PL/2024/04281",
        "url": "https://development.wiltshire.gov.uk/pr/s/planning-application/PL/2024/04281",
        "submitted_date": date(2024, 6, 10),
        "address": "Land adjacent to Melksham substation, Bowerhill, SN12 6QX",
        "description": "Construction of battery energy storage system (BESS) with capacity of 100MW/200MWh, including battery containers, power conversion units, grid connection infrastructure and landscaping",
        "application_status": "Decided",
        "application_decision": "Granted",
        "application_decision_date": date(2024, 12, 3),
        "application_type": "Full Planning",
        "capacity_mw": 100.0,
        "lat": 51.362, "lon": -2.125,
        "applicant_name": "Harmony Energy",
    },
    {
        "lpa": "north_yorkshire",
        "reference": "NY/2024/0087/FUL",
        "url": "https://publicaccess.northyorks.gov.uk/online-applications/NY/2024/0087/FUL",
        "submitted_date": date(2024, 2, 5),
        "address": "Land west of Drax Power Station, Selby, YO8 8PJ",
        "description": "Installation of 150MW solar photovoltaic array with associated inverters, transformers, DNO substation, customer substation, battery storage facility, access tracks, fencing and landscaping",
        "application_status": "Under Review",
        "application_type": "Full Planning",
        "capacity_mw": 150.0,
        "lat": 53.735, "lon": -0.997,
        "applicant_name": "Low Carbon",
        "environmental_assessment_requested": True,
    },
    {
        "lpa": "cornwall",
        "reference": "PA24/03891",
        "url": "https://planning.cornwall.gov.uk/online-applications/PA24/03891",
        "submitted_date": date(2024, 4, 18),
        "address": "Trevissome Park, Truro, TR4 8UN",
        "description": "Installation of 48 EV charging points including 12 rapid chargers (150kW) and associated electrical infrastructure, canopy structures with roof mounted solar PV panels",
        "application_status": "Decided",
        "application_decision": "Granted",
        "application_decision_date": date(2024, 7, 25),
        "application_type": "Full Planning",
        "capacity_mw": 0.2,
        "lat": 50.275, "lon": -5.064,
        "applicant_name": "Gridserve",
    },
    {
        "lpa": "highland",
        "reference": "24/01234/FUL",
        "url": "https://wam.highland.gov.uk/wam/applicationDetails.do?reference=24/01234/FUL",
        "submitted_date": date(2024, 3, 28),
        "address": "Land at Dalchork, Lairg, IV27 4DN",
        "description": "Erection of single wind turbine (tip height 77m, hub height 50m, rotor diameter 54m) with capacity of 900kW for community benefit, associated access track and grid connection",
        "application_status": "Decided",
        "application_decision": "Granted",
        "application_decision_date": date(2024, 9, 12),
        "application_type": "Full Planning",
        "capacity_mw": 0.9,
        "lat": 58.026, "lon": -4.585,
        "applicant_name": "Lairg Community Energy",
    },
    {
        "lpa": "somerset",
        "reference": "SCC/3948/2024",
        "url": "https://planning.somerset.gov.uk/online-applications/SCC/3948/2024",
        "submitted_date": date(2024, 7, 2),
        "address": "Former Bridgwater Coal Yard, The Drove, TA6 4BJ",
        "description": "Construction of district heating network with ground source heat pump system (2MW thermal capacity), distribution pipework to serve 450 dwellings, energy centre building",
        "application_status": "Submitted",
        "application_type": "Full Planning",
        "capacity_mw": 2.0,
        "lat": 51.128, "lon": -2.993,
        "applicant_name": "Somerset Council",
    },
    {
        "lpa": "devon",
        "reference": "DCC/4312/2024",
        "url": "https://planning.devon.gov.uk/online-applications/DCC/4312/2024",
        "submitted_date": date(2024, 8, 15),
        "address": "Land at Marsh Barton, Exeter, EX2 8QJ",
        "description": "Anaerobic digestion facility for processing food waste (50,000 tonnes per annum) with biogas upgrading plant, gas-to-grid connection and digestate storage tanks",
        "application_status": "Under Review",
        "application_type": "Full Planning",
        "capacity_mw": 3.5,
        "lat": 50.706, "lon": -3.523,
        "applicant_name": "Biogen Ltd",
    },
    {
        "lpa": "powys",
        "reference": "P/2024/0567",
        "url": "https://planning.powys.gov.uk/online-applications/P/2024/0567",
        "submitted_date": date(2024, 5, 30),
        "address": "Clywedog Reservoir, Llanidloes, SY18 6QF",
        "description": "Installation of micro hydroelectric scheme (250kW) utilising existing dam infrastructure, including intake structure, penstock, turbine house and grid connection via underground cable",
        "application_status": "Decided",
        "application_decision": "Granted",
        "application_decision_date": date(2024, 10, 18),
        "application_type": "Full Planning",
        "capacity_mw": 0.25,
        "lat": 52.441, "lon": -3.625,
        "applicant_name": "Severn Wye Energy Agency",
    },
    {
        "lpa": "oxfordshire",
        "reference": "R3/0198/24",
        "url": "https://myeplanning.oxfordshire.gov.uk/online-applications/R3/0198/24",
        "submitted_date": date(2024, 9, 5),
        "address": "Land at Botley Road, Oxford, OX2 0HA",
        "description": "Construction of 33kV/11kV primary substation and associated switchgear compound, cable routes and landscaping to support new residential development electrical demand",
        "application_status": "Under Review",
        "application_type": "Full Planning",
        "capacity_mw": 0.0,
        "lat": 51.752, "lon": -1.278,
        "applicant_name": "SSEN Distribution",
    },
    {
        "lpa": "lincolnshire",
        "reference": "PL/0098/24",
        "url": "https://planning.lincolnshire.gov.uk/online-applications/PL/0098/24",
        "submitted_date": date(2024, 1, 20),
        "address": "Land east of Heckington, Sleaford, NG34 9RQ",
        "description": "Installation of solar farm (250MW) with co-located battery energy storage system (80MW/160MWh), new 132kV substation, internal access tracks, deer fencing, CCTV and ecological mitigation areas",
        "application_status": "Under Review",
        "application_type": "Full Planning",
        "environmental_assessment_requested": True,
        "capacity_mw": 250.0,
        "lat": 52.958, "lon": -0.285,
        "applicant_name": "Ecotricity",
    },
    {
        "lpa": "kent",
        "reference": "KCC/2024/1234",
        "url": "https://planning.kent.gov.uk/online-applications/KCC/2024/1234",
        "submitted_date": date(2024, 4, 2),
        "address": "Cleve Hill, Graveney, Faversham, ME13 9DX",
        "description": "Ground mounted solar photovoltaic generating station (350MW) with energy storage facility, grid connection to Canterbury North 400kV substation via underground cable route",
        "application_status": "Decided",
        "application_decision": "Granted",
        "application_decision_date": date(2024, 8, 15),
        "application_type": "Full Planning",
        "environmental_assessment_requested": True,
        "capacity_mw": 350.0,
        "lat": 51.341, "lon": 0.916,
        "applicant_name": "Cleve Hill Solar Park Ltd",
    },
]


async def seed_sample_data(conn: asyncpg.Connection):
    """Insert sample energy planning applications if table is empty."""
    count = await conn.fetchval("SELECT COUNT(*) FROM planning_applications")
    if count > 0:
        return count

    for app in _SAMPLE_APPS:
        categories = classify_energy(app["description"])
        lat = app.pop("lat", None)
        lon = app.pop("lon", None)
        centroid_sql = f"ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)" if lat and lon else "NULL"

        await conn.execute(
            f"""
            INSERT INTO planning_applications
                (lpa, reference, url, submitted_date, address, description,
                 application_status, application_decision, application_decision_date,
                 application_type, capacity_mw, energy_categories, applicant_name,
                 environmental_assessment_requested, centroid)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                    {centroid_sql})
            ON CONFLICT (lpa, reference) DO NOTHING
            """,
            app.get("lpa"),
            app.get("reference"),
            app.get("url"),
            app.get("submitted_date"),
            app.get("address"),
            app.get("description"),
            app.get("application_status", "Submitted"),
            app.get("application_decision"),
            app.get("application_decision_date"),
            app.get("application_type", "Full Planning"),
            app.get("capacity_mw"),
            categories,
            app.get("applicant_name"),
            app.get("environmental_assessment_requested"),
        )

    return len(_SAMPLE_APPS)


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

async def query_energy_applications(
    conn: asyncpg.Connection,
    category: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    bbox: tuple[float, float, float, float] | None = None,
) -> list[dict]:
    """
    Query energy-relevant planning applications.

    category: filter by energy category (solar, wind, battery_storage, etc.)
    status:   filter by application status
    bbox:     (min_lon, min_lat, max_lon, max_lat) geographic filter
    """
    conditions = ["energy_categories IS NOT NULL", "array_length(energy_categories, 1) > 0"]
    params: list = []
    idx = 1

    if category:
        conditions.append(f"$${idx}$$ = ANY(energy_categories)")
        # Use parameterised query
        conditions[-1] = f"${idx} = ANY(energy_categories)"
        params.append(category)
        idx += 1

    if status:
        conditions.append(f"application_status = ${idx}")
        params.append(status)
        idx += 1

    if bbox:
        min_lon, min_lat, max_lon, max_lat = bbox
        conditions.append(
            f"centroid IS NOT NULL AND ST_Within(centroid, ST_MakeEnvelope(${idx}, ${idx+1}, ${idx+2}, ${idx+3}, 4326))"
        )
        params.extend([min_lon, min_lat, max_lon, max_lat])
        idx += 4

    where = " AND ".join(conditions)
    params.extend([limit, offset])

    rows = await conn.fetch(
        f"""
        SELECT uuid::text, lpa, reference, url, submitted_date, address,
               description, application_status, application_decision,
               application_decision_date, application_type, energy_categories,
               capacity_mw, applicant_name, environmental_assessment_requested,
               ST_Y(centroid) AS lat, ST_X(centroid) AS lon
        FROM planning_applications
        WHERE {where}
        ORDER BY submitted_date DESC
        LIMIT ${idx} OFFSET ${idx+1}
        """,
        *params,
    )

    return [dict(r) for r in rows]


async def energy_summary(conn: asyncpg.Connection) -> dict:
    """Summary statistics for energy planning applications."""
    total = await conn.fetchval(
        "SELECT COUNT(*) FROM planning_applications WHERE energy_categories IS NOT NULL AND array_length(energy_categories, 1) > 0"
    )

    by_category = await conn.fetch(
        """
        SELECT unnest(energy_categories) AS category, COUNT(*) AS count
        FROM planning_applications
        WHERE energy_categories IS NOT NULL
        GROUP BY category ORDER BY count DESC
        """
    )

    by_status = await conn.fetch(
        """
        SELECT application_status, COUNT(*) AS count
        FROM planning_applications
        WHERE energy_categories IS NOT NULL AND array_length(energy_categories, 1) > 0
        GROUP BY application_status ORDER BY count DESC
        """
    )

    by_decision = await conn.fetch(
        """
        SELECT COALESCE(application_decision, 'Pending') AS decision, COUNT(*) AS count
        FROM planning_applications
        WHERE energy_categories IS NOT NULL AND array_length(energy_categories, 1) > 0
        GROUP BY decision ORDER BY count DESC
        """
    )

    total_capacity = await conn.fetchval(
        "SELECT COALESCE(SUM(capacity_mw), 0) FROM planning_applications WHERE energy_categories IS NOT NULL AND array_length(energy_categories, 1) > 0"
    )

    return {
        "total_applications": total,
        "total_capacity_mw": round(float(total_capacity), 1),
        "by_category": {r["category"]: r["count"] for r in by_category},
        "by_status": {r["application_status"]: r["count"] for r in by_status},
        "by_decision": {r["decision"]: r["count"] for r in by_decision},
        "categories_available": list(ENERGY_CATEGORIES.keys()),
    }


async def applications_geojson(
    conn: asyncpg.Connection,
    category: str | None = None,
) -> dict:
    """Return energy applications as GeoJSON FeatureCollection for map display."""
    apps = await query_energy_applications(conn, category=category, limit=500)

    features = []
    for app in apps:
        if app.get("lat") is None or app.get("lon") is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(app["lon"]), float(app["lat"])],
            },
            "properties": {
                "uuid": app["uuid"],
                "reference": app["reference"],
                "lpa": app["lpa"],
                "address": app["address"],
                "description": app["description"],
                "status": app["application_status"],
                "decision": app.get("application_decision"),
                "categories": app["energy_categories"],
                "capacity_mw": app.get("capacity_mw"),
                "applicant": app.get("applicant_name"),
                "submitted": str(app["submitted_date"]) if app.get("submitted_date") else None,
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
    }
