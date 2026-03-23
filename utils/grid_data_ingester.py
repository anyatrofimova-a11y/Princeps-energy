"""
Grid Data Ingester — unified adapters for UK DNO capacity data.

Adapters:
  - OpenDataSoftAdapter: UKPN, NPG, SPEN, ENWL (4 DNOs — UKPN/SPEN/ENWL need API keys)
  - CKANAdapter: NESO Data Portal (api.neso.energy), NGED, SSEN (data-api.ssen.co.uk)
  - OverpassAdapter: OpenStreetMap power infrastructure

All adapters write to the grid_* PostGIS tables (SRID 27700).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("princeps.grid_data_ingester")

_TIMEOUT = 60
_USER_AGENT = "Princeps/1.0 grid-ingester"

# ─── DNO Configuration ────────────────────────────────────────────────────

DNO_CONFIGS = {
    "ukpn": {
        "name": "UK Power Networks",
        "platform": "opendatasoft",
        "base_url": "https://ukpowernetworks.opendatasoft.com",
        # NOTE: UKPN now requires an API key for record access (data_visible=false).
        # Set env var UKPN_ODS_APIKEY to enable. Without it, requests return 403.
        "datasets": {
            "substations": "ukpn-grid-supply-points-overview",
            "headroom": "dfes-network-headroom-report",
            "ecr": "ukpn-embedded-capacity-register",
        },
        "api_key_env": "UKPN_ODS_APIKEY",
        "regions": ["Eastern (EPN)", "London (LPN)", "South East (SPN)"],
    },
    "npg": {
        "name": "Northern Powergrid",
        "platform": "opendatasoft",
        "base_url": "https://northernpowergrid.opendatasoft.com",
        "datasets": {
            "substations": "heatmapdatatable",
            "demand_headroom": "npg_ndp_demand_headroom",
            "gen_headroom": "npg_ndp_generation_headroom",
            "ecr": "embedded-capacity-register",
        },
        "regions": ["North East England", "Yorkshire"],
    },
    "spen": {
        "name": "SP Energy Networks",
        "platform": "opendatasoft",
        "base_url": "https://spenergynetworks.opendatasoft.com",
        # NOTE: SPEN now requires an API key for record access (data_visible=false).
        # Set env var SPEN_ODS_APIKEY to enable. Without it, requests return 403.
        "datasets": {
            "substations": "gsp-overview",
            "capacity": "capacity-management-system",
            "ecr": "embedded-capacity-register",
        },
        "api_key_env": "SPEN_ODS_APIKEY",
        "regions": ["South Scotland", "Merseyside & North Wales"],
    },
    "enwl": {
        "name": "Electricity North West",
        "platform": "opendatasoft",
        "base_url": "https://electricitynorthwest.opendatasoft.com",
        # NOTE: ENWL now requires an API key for record access (data_visible=false).
        # Set env var ENWL_ODS_APIKEY to enable. Without it, requests return 403.
        "datasets": {
            "substations": "enwl-gsp-heatmap",
            "capacity": "enwl-pry-heatmap",
            "ecr": "enwl-embedded-capacity-register-2-1mw-and-above",
        },
        "api_key_env": "ENWL_ODS_APIKEY",
        "regions": ["North West England"],
    },
    "ssen": {
        "name": "SSEN Distribution",
        "platform": "ckan",
        # SSEN moved from OpenDataSoft to Datopian/CKAN portal in 2025
        "base_url": "https://data-api.ssen.co.uk",
        "datasets": {
            "capacity": "52e9a305-ad90-4c81-9175-20a40ef57894",  # Headroom Dashboard Data (March 2026)
            "ecr": "bbae6797-364a-4b2d-a01a-8395e21bee76",       # ECR Part 1 - 1MW (March 2026)
        },
        "regions": ["Southern Scotland", "North of Scotland", "Southern England"],
    },
    "nged": {
        "name": "National Grid Electricity Distribution",
        "platform": "ckan",
        "base_url": "https://connecteddata.nationalgrid.co.uk",
        # NOTE: Network capacity resource requires auth. Set NGED_CKAN_APIKEY env var.
        # ECR is publicly accessible.
        "datasets": {
            "capacity": "d1895bd3-d9d2-4886-a0a3-b7eadd9ab6c2",  # Network Capacity Map CSV
            "headroom": "d1963858-d451-4794-a6bf-123fad0f0b3a",   # Network Opportunity Map Headroom
            "ecr": "82a4ae83-77a3-4e7b-9060-8072ed96de9d",        # ECR JAN 2026 CSV
        },
        "api_key_env": "NGED_CKAN_APIKEY",
        "regions": ["West Midlands", "East Midlands", "South West", "South Wales"],
    },
}

NESO_CONFIG = {
    # data.nationalgrideso.com is defunct — migrated to api.neso.energy (NESO rebrand)
    "base_url": "https://api.neso.energy",
    "api_path": "/api/3/action/datastore_search",
    "datasets": {
        "demand_data": "177f6fa4-ae49-4182-81ea-0c6b35f26ca6",    # Daily Demand Update
        "gen_mix": "f93d1835-75bc-43e5-84ad-12472b180a98",         # Generation Mix (unchanged)
        "tec_register": "17becbab-e3e8-473f-b303-3806f43a6a10",   # TEC Register
    },
}


# ─── Base Adapter ──────────────────────────────────────────────────────────

class DataAdapter:
    """Base class for grid data adapters."""

    def __init__(self, dno_code: str, config: dict):
        self.dno_code = dno_code
        self.config = config
        self.name = config["name"]

    async def fetch_substations(self) -> list[dict]:
        raise NotImplementedError

    async def fetch_ecr(self) -> list[dict]:
        raise NotImplementedError

    async def fetch_headroom(self) -> list[dict]:
        raise NotImplementedError


# ─── OpenDataSoft Adapter ──────────────────────────────────────────────────

class OpenDataSoftAdapter(DataAdapter):
    """
    Adapter for DNOs using OpenDataSoft platform.
    API: /api/explore/v2.1/catalog/datasets/{dataset_id}/records
    """

    def __init__(self, dno_code: str, config: dict):
        super().__init__(dno_code, config)
        self.base_url = config["base_url"]
        # Support API key auth — many DNO portals now require it
        api_key_env = config.get("api_key_env")
        self.api_key = os.environ.get(api_key_env, "") if api_key_env else ""

    async def _fetch_records(
        self, dataset_id: str, limit: int = 100, offset: int = 0,
        where: str | None = None,
    ) -> list[dict]:
        """Fetch records from an ODS dataset with pagination."""
        url = f"{self.base_url}/api/explore/v2.1/catalog/datasets/{dataset_id}/records"
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if where:
            params["where"] = where

        headers: dict[str, str] = {"User-Agent": _USER_AGENT}
        if self.api_key:
            headers["Authorization"] = f"Apikey {self.api_key}"

        all_records: list[dict] = []
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers=headers,
            follow_redirects=True,
        ) as client:
            while True:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
                results = data.get("results", [])
                if not results:
                    break
                all_records.extend(results)
                total = data.get("total_count", 0)
                if len(all_records) >= total:
                    break
                params["offset"] = len(all_records)

        return all_records

    async def fetch_substations(self) -> list[dict]:
        """Fetch substation data — maps to grid_substations table."""
        dataset_key = None
        for key in ("substations", "demand_headroom", "capacity"):
            if key in self.config["datasets"]:
                dataset_key = key
                break
        if not dataset_key:
            return []

        dataset_id = self.config["datasets"][dataset_key]
        records = await self._fetch_records(dataset_id, limit=100)

        substations = []
        for rec in records:
            fields = rec.get("fields", rec)
            geo = rec.get("geo_point_2d") or fields.get("geo_point_2d") or {}

            lat = geo.get("lat") or fields.get("latitude") or fields.get("lat")
            lon = geo.get("lon") or fields.get("longitude") or fields.get("lon")

            name = (
                fields.get("substation_name")
                or fields.get("name")
                or fields.get("site_name")
                or fields.get("gsp_name")
                or "Unknown"
            )

            substations.append({
                "external_id": fields.get("id") or fields.get("substation_id") or name,
                "name": name,
                "dno": self.dno_code,
                "region": fields.get("licence_area") or fields.get("region"),
                "voltage_kv": _parse_num(fields.get("voltage_kv") or fields.get("voltage")),
                "site_type": fields.get("site_type") or fields.get("type"),
                "demand_mw": _parse_num(fields.get("demand_mw") or fields.get("max_demand_mw")),
                "generation_mw": _parse_num(fields.get("generation_mw") or fields.get("connected_gen_mw")),
                "demand_headroom_mw": _parse_num(
                    fields.get("demand_headroom_mw")
                    or fields.get("thermal_demand_headroom_mw")
                    or fields.get("spare_capacity_mw")
                ),
                "gen_headroom_mw": _parse_num(
                    fields.get("gen_headroom_mw")
                    or fields.get("thermal_generation_headroom_mw")
                    or fields.get("generation_headroom_mw")
                ),
                "fault_level_ka": _parse_num(fields.get("fault_level_ka")),
                "transformer_rating_mva": _parse_num(
                    fields.get("transformer_rating_mva") or fields.get("rated_mva")
                ),
                "rag_demand": fields.get("rag_demand") or fields.get("demand_rag"),
                "rag_generation": fields.get("rag_generation") or fields.get("generation_rag"),
                "lat": _parse_num(lat),
                "lon": _parse_num(lon),
                "raw_data": fields,
            })

        log.info("[%s] Fetched %d substations from %s", self.dno_code, len(substations), dataset_id)
        return substations

    async def fetch_ecr(self) -> list[dict]:
        """Fetch Embedded Capacity Register entries."""
        if "ecr" not in self.config["datasets"]:
            return []

        dataset_id = self.config["datasets"]["ecr"]
        records = await self._fetch_records(dataset_id, limit=100)

        entries = []
        for rec in records:
            fields = rec.get("fields", rec)
            geo = rec.get("geo_point_2d") or fields.get("geo_point_2d") or {}

            entries.append({
                "external_id": fields.get("id") or fields.get("ref"),
                "site_name": fields.get("site_name") or fields.get("name"),
                "dno": self.dno_code,
                "technology": _classify_tech(fields.get("technology") or fields.get("fuel_type")),
                "capacity_mw": _parse_num(fields.get("capacity_mw") or fields.get("installed_capacity_mw")),
                "voltage_kv": _parse_num(fields.get("voltage_kv") or fields.get("connection_voltage")),
                "substation_name": fields.get("substation_name") or fields.get("connection_point"),
                "status": fields.get("status") or fields.get("connection_status"),
                "lat": _parse_num(geo.get("lat") or fields.get("latitude")),
                "lon": _parse_num(geo.get("lon") or fields.get("longitude")),
                "raw_data": fields,
            })

        log.info("[%s] Fetched %d ECR entries from %s", self.dno_code, len(entries), dataset_id)
        return entries


# ─── CKAN Adapter ──────────────────────────────────────────────────────────

class CKANAdapter(DataAdapter):
    """Adapter for NESO Data Portal and NGED Connected Data Portal (CKAN v3)."""

    def __init__(self, dno_code: str, config: dict):
        super().__init__(dno_code, config)
        self.base_url = config["base_url"]
        self.api_path = "/api/3/action/datastore_search"
        # Support API key auth for CKAN portals that require it
        api_key_env = config.get("api_key_env")
        self.api_key = os.environ.get(api_key_env, "") if api_key_env else ""

    async def _fetch_records(
        self, resource_id: str, page_size: int = 1000,
    ) -> list[dict]:
        """Fetch all records from a CKAN datastore resource."""
        url = f"{self.base_url}{self.api_path}"
        all_records: list[dict] = []
        offset = 0

        headers: dict[str, str] = {"User-Agent": _USER_AGENT}
        if self.api_key:
            headers["Authorization"] = self.api_key

        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers=headers,
            follow_redirects=True,
        ) as client:
            while True:
                r = await client.get(url, params={
                    "resource_id": resource_id,
                    "limit": page_size,
                    "offset": offset,
                })
                r.raise_for_status()
                data = r.json()
                records = data.get("result", {}).get("records", [])
                if not records:
                    break
                all_records.extend(records)
                offset += len(records)
                if len(records) < page_size:
                    break

        return all_records

    async def fetch_substations(self) -> list[dict]:
        """NGED substations from CKAN."""
        dataset_key = next(
            (k for k in ("capacity", "substations") if k in self.config["datasets"]),
            None,
        )
        if not dataset_key:
            return []

        resource_id = self.config["datasets"][dataset_key]
        records = await self._fetch_records(resource_id)

        substations = []
        for row in records:
            name = (
                str(row.get("Substation Name", row.get("Name", ""))).strip()
                or "Unknown"
            )
            substations.append({
                "external_id": str(row.get("_id", name)),
                "name": name,
                "dno": self.dno_code,
                "region": row.get("Region") or row.get("Licence Area"),
                "voltage_kv": _parse_num(row.get("Voltage (kV)") or row.get("Voltage")),
                "site_type": row.get("Type") or row.get("Site Type"),
                "demand_mw": _parse_num(row.get("Demand (MW)") or row.get("Peak Demand")),
                "generation_mw": _parse_num(row.get("Generation (MW)")),
                "demand_headroom_mw": _parse_num(
                    row.get("Demand Headroom (MW)") or row.get("Spare Capacity (MW)")
                ),
                "gen_headroom_mw": _parse_num(
                    row.get("Generation Headroom (MW)") or row.get("Gen Headroom (MW)")
                ),
                "fault_level_ka": _parse_num(row.get("Fault Level (kA)")),
                "transformer_rating_mva": _parse_num(row.get("Rating (MVA)")),
                "rag_demand": row.get("Demand RAG"),
                "rag_generation": row.get("Generation RAG"),
                "lat": _parse_num(row.get("Latitude") or row.get("lat")),
                "lon": _parse_num(row.get("Longitude") or row.get("lon")),
                "raw_data": row,
            })

        log.info("[%s] Fetched %d substations via CKAN", self.dno_code, len(substations))
        return substations

    async def fetch_ecr(self) -> list[dict]:
        if "ecr" not in self.config["datasets"]:
            return []
        resource_id = self.config["datasets"]["ecr"]
        records = await self._fetch_records(resource_id)

        entries = []
        for row in records:
            entries.append({
                "external_id": str(row.get("_id", "")),
                "site_name": row.get("Site Name") or row.get("Name"),
                "dno": self.dno_code,
                "technology": _classify_tech(row.get("Technology") or row.get("Fuel Type")),
                "capacity_mw": _parse_num(row.get("Capacity (MW)") or row.get("Installed Capacity")),
                "voltage_kv": _parse_num(row.get("Voltage (kV)")),
                "substation_name": row.get("Connection Point") or row.get("Substation"),
                "status": row.get("Status") or row.get("Connection Status"),
                "lat": _parse_num(row.get("Latitude")),
                "lon": _parse_num(row.get("Longitude")),
                "raw_data": row,
            })

        log.info("[%s] Fetched %d ECR entries via CKAN", self.dno_code, len(entries))
        return entries


# ─── Overpass Adapter (OSM Power Infrastructure) ──────────────────────────

class OverpassAdapter:
    """Extract UK power grid topology from OpenStreetMap via Overpass API."""

    OVERPASS_URL = "https://overpass-api.de/api/interpreter"

    async def fetch_substations(
        self, min_voltage_kv: int = 33,
    ) -> list[dict]:
        """Fetch UK substations from OSM at or above a voltage threshold."""
        voltage_v = min_voltage_kv * 1000
        query = f"""
        [out:json][timeout:120];
        area["ISO3166-1"="GB"]->.gb;
        (
          node["power"="substation"]["voltage"~"{voltage_v}"](area.gb);
          way["power"="substation"]["voltage"~"{voltage_v}"](area.gb);
        );
        out center tags;
        """
        data = await self._run_query(query)
        substations = []
        for el in data.get("elements", []):
            tags = el.get("tags", {})
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")
            if not lat or not lon:
                continue

            voltage_str = tags.get("voltage", "")
            voltage_kv = _parse_voltage_kv(voltage_str)

            substations.append({
                "osm_id": el.get("id"),
                "name": tags.get("name", f"OSM-{el.get('id')}"),
                "voltage_kv": voltage_kv,
                "operator": tags.get("operator"),
                "lat": lat,
                "lon": lon,
                "raw_data": tags,
            })

        log.info("OSM: Fetched %d substations (>=%d kV)", len(substations), min_voltage_kv)
        return substations

    async def fetch_power_lines(
        self, min_voltage_kv: int = 132,
    ) -> list[dict]:
        """Fetch UK transmission/distribution lines from OSM."""
        voltage_v = min_voltage_kv * 1000
        query = f"""
        [out:json][timeout:120];
        area["ISO3166-1"="GB"]->.gb;
        way["power"="line"](if:number(t["voltage"])>={voltage_v})(area.gb);
        out geom tags;
        """
        data = await self._run_query(query)
        lines = []
        for el in data.get("elements", []):
            tags = el.get("tags", {})
            geometry = el.get("geometry", [])
            if len(geometry) < 2:
                continue

            coords = [(pt["lon"], pt["lat"]) for pt in geometry]
            voltage_kv = _parse_voltage_kv(tags.get("voltage", ""))
            circuits = _parse_int(tags.get("circuits", "1"))

            lines.append({
                "osm_id": el.get("id"),
                "voltage_kv": voltage_kv,
                "circuits": circuits or 1,
                "operator": tags.get("operator"),
                "coords": coords,  # list of (lon, lat) tuples
                "raw_data": tags,
            })

        log.info("OSM: Fetched %d power lines (>=%d kV)", len(lines), min_voltage_kv)
        return lines

    async def _run_query(self, query: str) -> dict:
        async with httpx.AsyncClient(
            timeout=180,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            r = await client.post(self.OVERPASS_URL, data={"data": query})
            r.raise_for_status()
            return r.json()


# ─── DNO Boundary Loader ─────────────────────────────────────────────────

async def fetch_dno_boundaries() -> list[dict]:
    """
    Fetch DNO licence area boundaries from NESO Data Portal.
    Returns GeoJSON features for each licence area.
    """
    url = "https://api.neso.energy/api/3/action/package_show"
    params = {"id": "gis-boundaries-for-gb-dno-license-areas"}

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
    ) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        pkg = r.json().get("result", {})

        # Find the GeoJSON resource
        geojson_url = None
        for resource in pkg.get("resources", []):
            fmt = (resource.get("format") or "").lower()
            name = (resource.get("name") or "").lower()
            if "geojson" in fmt or "geojson" in name:
                geojson_url = resource["url"]
                break

        if not geojson_url:
            log.warning("No GeoJSON resource found in NESO DNO boundaries dataset")
            return []

        r2 = await client.get(geojson_url)
        r2.raise_for_status()
        geojson = r2.json()

    features = geojson.get("features", [])
    boundaries = []
    for feat in features:
        props = feat.get("properties", {})
        boundaries.append({
            "dno_code": props.get("DNO_Code") or props.get("LicenseAreaCode") or props.get("Name", ""),
            "dno_name": props.get("Name") or props.get("DNO_Name", ""),
            "long_name": props.get("LongName") or props.get("Full_Name"),
            "geojson": feat.get("geometry"),
        })

    log.info("Fetched %d DNO boundary polygons", len(boundaries))
    return boundaries


# ─── Database Upsert Functions ────────────────────────────────────────────

async def upsert_substations(conn, substations: list[dict]) -> int:
    """Insert/update substations into grid_substations table."""
    count = 0
    for sub in substations:
        lat, lon = sub.get("lat"), sub.get("lon")
        if lat is None or lon is None:
            continue

        await conn.execute("""
            INSERT INTO grid_substations (
                external_id, name, dno, region, voltage_kv, site_type,
                demand_mw, generation_mw, demand_headroom_mw, gen_headroom_mw,
                fault_level_ka, transformer_rating_mva,
                rag_demand, rag_generation, geom, raw_data, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10,
                $11, $12,
                $13, $14,
                ST_Transform(ST_SetSRID(ST_MakePoint($15, $16), 4326), 27700),
                $17, NOW()
            )
            ON CONFLICT (external_id, dno) DO UPDATE SET
                name = EXCLUDED.name,
                demand_mw = COALESCE(EXCLUDED.demand_mw, grid_substations.demand_mw),
                generation_mw = COALESCE(EXCLUDED.generation_mw, grid_substations.generation_mw),
                demand_headroom_mw = COALESCE(EXCLUDED.demand_headroom_mw, grid_substations.demand_headroom_mw),
                gen_headroom_mw = COALESCE(EXCLUDED.gen_headroom_mw, grid_substations.gen_headroom_mw),
                rag_demand = COALESCE(EXCLUDED.rag_demand, grid_substations.rag_demand),
                rag_generation = COALESCE(EXCLUDED.rag_generation, grid_substations.rag_generation),
                raw_data = EXCLUDED.raw_data,
                updated_at = NOW()
        """,
            sub.get("external_id"), sub["name"], sub["dno"], sub.get("region"),
            sub.get("voltage_kv"), sub.get("site_type"),
            sub.get("demand_mw"), sub.get("generation_mw"),
            sub.get("demand_headroom_mw"), sub.get("gen_headroom_mw"),
            sub.get("fault_level_ka"), sub.get("transformer_rating_mva"),
            sub.get("rag_demand"), sub.get("rag_generation"),
            lon, lat,
            json.dumps(sub.get("raw_data", {}), default=str),
        )
        count += 1

    return count


async def upsert_ecr(conn, entries: list[dict]) -> int:
    """Insert ECR entries into grid_ecr table."""
    count = 0
    for entry in entries:
        lat, lon = entry.get("lat"), entry.get("lon")
        geom_expr = (
            "ST_Transform(ST_SetSRID(ST_MakePoint($11, $12), 4326), 27700)"
            if lat and lon else "NULL"
        )

        # Link to substation if possible
        sub_link = None
        if entry.get("substation_name"):
            sub_link = await conn.fetchval(
                "SELECT id FROM grid_substations WHERE name ILIKE $1 AND dno = $2 LIMIT 1",
                f"%{entry['substation_name']}%", entry["dno"],
            )

        await conn.execute(f"""
            INSERT INTO grid_ecr (
                external_id, site_name, dno, technology, capacity_mw,
                voltage_kv, substation_name, substation_id, status,
                geom, raw_data, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9,
                {geom_expr}, $13, NOW()
            )
            ON CONFLICT DO NOTHING
        """,
            entry.get("external_id"), entry.get("site_name"), entry["dno"],
            entry.get("technology"), entry.get("capacity_mw"),
            entry.get("voltage_kv"), entry.get("substation_name"), sub_link,
            entry.get("status"),
            *([lon, lat] if lat and lon else []),
            json.dumps(entry.get("raw_data", {}), default=str),
        )
        count += 1

    return count


async def upsert_grid_lines(conn, lines: list[dict]) -> int:
    """Insert grid lines from OSM into grid_lines table."""
    count = 0
    for line in lines:
        coords = line.get("coords", [])
        if len(coords) < 2:
            continue

        # Build WKT LineString
        coord_str = ", ".join(f"{lon} {lat}" for lon, lat in coords)
        wkt = f"LINESTRING({coord_str})"

        # Calculate approximate length
        from math import radians, sin, cos, atan2, sqrt
        total_km = 0.0
        for i in range(len(coords) - 1):
            lon1, lat1 = coords[i]
            lon2, lat2 = coords[i + 1]
            dlat = radians(lat2 - lat1)
            dlon = radians(lon2 - lon1)
            a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
            total_km += 6371 * 2 * atan2(sqrt(a), sqrt(1 - a))

        await conn.execute("""
            INSERT INTO grid_lines (osm_id, voltage_kv, circuits, operator, length_km, geom, raw_data)
            VALUES ($1, $2, $3, $4, $5,
                    ST_Transform(ST_GeomFromText($6, 4326), 27700), $7)
            ON CONFLICT DO NOTHING
        """,
            line.get("osm_id"), line.get("voltage_kv"), line.get("circuits"),
            line.get("operator"), round(total_km, 2), wkt,
            json.dumps(line.get("raw_data", {}), default=str),
        )
        count += 1

    return count


async def upsert_dno_boundaries(conn, boundaries: list[dict]) -> int:
    """Insert DNO licence boundaries into grid_dno_boundaries."""
    count = 0
    for b in boundaries:
        geojson = b.get("geojson")
        if not geojson:
            continue

        await conn.execute("""
            INSERT INTO grid_dno_boundaries (dno_code, dno_name, long_name, geom)
            VALUES ($1, $2, $3,
                    ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($4), 4326), 27700))
            ON CONFLICT (dno_code) DO UPDATE SET
                dno_name = EXCLUDED.dno_name,
                geom = EXCLUDED.geom
        """,
            b["dno_code"], b["dno_name"], b.get("long_name"),
            json.dumps(geojson),
        )
        count += 1

    return count


# ─── Log Helpers ──────────────────────────────────────────────────────────

async def log_ingestion(conn, source: str, dataset: str, status: str,
                         fetched: int = 0, upserted: int = 0, error: str | None = None):
    """Record an ingestion run in grid_ingestion_log."""
    await conn.execute("""
        INSERT INTO grid_ingestion_log (source, dataset, status, records_fetched, records_upserted, error, finished_at)
        VALUES ($1, $2, $3, $4, $5, $6, CASE WHEN $3 != 'running' THEN NOW() END)
    """, source, dataset, status, fetched, upserted, error)


# ─── Orchestrator ─────────────────────────────────────────────────────────

def get_adapter(dno_code: str) -> DataAdapter:
    """Create the appropriate adapter for a DNO."""
    config = DNO_CONFIGS.get(dno_code)
    if not config:
        raise ValueError(f"Unknown DNO: {dno_code}")

    if config["platform"] == "opendatasoft":
        return OpenDataSoftAdapter(dno_code, config)
    elif config["platform"] == "ckan":
        return CKANAdapter(dno_code, config)
    else:
        raise ValueError(f"Unknown platform: {config['platform']}")


async def ingest_all_dnos(pool) -> dict:
    """
    Run ingestion for all DNOs. Called from FastAPI lifespan or background task.

    Returns summary dict with counts per DNO.
    """
    t0 = time.time()
    summary: dict[str, Any] = {}

    async with pool.acquire() as conn:
        # Ensure tables exist
        migration = open(
            str(__import__("pathlib").Path(__file__).parent.parent / "sql" / "migrate_grid_connection.sql")
        ).read()
        for stmt in migration.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("--"):
                try:
                    await conn.execute(stmt)
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        log.warning("Migration statement failed: %s", e)

        # Ingest each DNO
        for dno_code in DNO_CONFIGS:
            try:
                adapter = get_adapter(dno_code)

                subs = await adapter.fetch_substations()
                sub_count = await upsert_substations(conn, subs) if subs else 0

                ecr = await adapter.fetch_ecr()
                ecr_count = await upsert_ecr(conn, ecr) if ecr else 0

                await log_ingestion(conn, dno_code, "substations", "done", len(subs), sub_count)
                if ecr:
                    await log_ingestion(conn, dno_code, "ecr", "done", len(ecr), ecr_count)

                summary[dno_code] = {
                    "substations": sub_count,
                    "ecr": ecr_count,
                    "status": "done",
                }
                log.info("[%s] Ingested %d substations, %d ECR", dno_code, sub_count, ecr_count)

            except Exception as e:
                log.error("[%s] Ingestion failed: %s", dno_code, e)
                await log_ingestion(conn, dno_code, "all", "failed", error=str(e))
                summary[dno_code] = {"status": "failed", "error": str(e)}

        # DNO boundaries
        try:
            boundaries = await fetch_dno_boundaries()
            b_count = await upsert_dno_boundaries(conn, boundaries)
            summary["dno_boundaries"] = b_count
            log.info("Ingested %d DNO boundaries", b_count)
        except Exception as e:
            log.warning("DNO boundaries ingestion failed: %s", e)
            summary["dno_boundaries"] = {"error": str(e)}

        # OSM power infrastructure
        try:
            osm = OverpassAdapter()
            osm_lines = await osm.fetch_power_lines(min_voltage_kv=132)
            line_count = await upsert_grid_lines(conn, osm_lines)
            summary["osm_lines"] = line_count
            log.info("Ingested %d OSM power lines", line_count)
        except Exception as e:
            log.warning("OSM ingestion failed: %s", e)
            summary["osm_lines"] = {"error": str(e)}

    elapsed = round(time.time() - t0, 1)
    summary["elapsed_s"] = elapsed
    log.info("Grid data ingestion complete in %.1fs", elapsed)
    return summary


# ─── Helpers ──────────────────────────────────────────────────────────────

TECH_MAP = {
    "solar": "solar", "photovoltaic": "solar", "pv": "solar",
    "wind": "wind", "onshore": "wind", "offshore": "wind",
    "battery": "bess", "storage": "bess", "bess": "bess",
    "gas": "gas", "ccgt": "gas", "ocgt": "gas",
    "biomass": "biomass", "hydro": "hydro", "nuclear": "nuclear",
    "chp": "chp", "diesel": "diesel",
}


def _classify_tech(raw: str | None) -> str:
    if not raw:
        return "other"
    lower = raw.strip().lower()
    for key, cat in TECH_MAP.items():
        if key in lower:
            return cat
    return "other"


def _parse_num(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


def _parse_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(float(str(val).strip().replace(",", "")))
    except (ValueError, TypeError):
        return None


def _parse_voltage_kv(voltage_str: str) -> float | None:
    """Parse OSM voltage string (e.g. '400000', '132000;33000') to kV."""
    if not voltage_str:
        return None
    # Take the highest voltage if multiple
    parts = voltage_str.replace(";", ",").split(",")
    voltages = []
    for p in parts:
        v = _parse_num(p)
        if v and v > 100:  # Likely in volts
            voltages.append(v / 1000)
        elif v:
            voltages.append(v)
    return max(voltages) if voltages else None
