"""LTDS Excel workbook parser → canonical SubstationProject list.

Each of the 6 UK DNOs publishes a Long Term Development Statement every
November. The file is an Excel workbook, but the schema drifts between DNOs
(different sheet names, different column orders, different units). We handle
this with a dispatcher: each DNO has a dedicated column-mapping callable that
returns a list of `SubstationProject` instances.

V1 status
---------
* UKPN — **wired end-to-end** (HTTP fetch via OpenDataSoft, parse, return).
  UKPN publishes its LTDS primary/grid substations dataset as CSV/JSON on
  the OpenDataSoft portal (dataset ids `ltds-tab-6-grid-substations-loading`
  and `ltds-tab-2-primary-substations-loading`). This parser handles both
  the downloaded .xlsx form and the ODS JSON form.
* SSEN, SPEN, NGED, NPG, ENWL — **stubbed** with TODO notes describing the
  column-mapping delta that each DNO requires.

Each DNO-specific adapter is registered in DNO_DISPATCHERS; `parse_ltds_workbook`
looks up the right one by the `dno` argument.

TODO after v1
-------------
* Wire NGED to the CIM ingester output (ltds_substations table) — they
  publish CIM RDF/XML instead of Excel. We can pull from Postgres directly
  without re-parsing.
* Wire the remaining 4 DNOs once we have their workbook samples in
  `data/ltds/<dno>/2025/`. Each adapter needs:
    - sheet name(s) for primary / grid / BSP substations
    - header row offset (some DNOs have 2-3 title rows before headers)
    - column name → field mapping
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from .schema import (
    SubstationProject,
    PARENT_COMPANY_BY_DEVELOPER,
    COUNTRY_BY_DEVELOPER,
)

log = logging.getLogger("princeps.substation_tracker.ltds_excel")

# ---------------------------------------------------------------------------
# Dependency guards — openpyxl is a heavy import; we only need it when we
# actually parse a workbook. httpx is pulled in elsewhere in the project so
# it's safe.
# ---------------------------------------------------------------------------
def _load_openpyxl():
    try:
        import openpyxl  # type: ignore
        return openpyxl
    except ImportError as exc:
        raise RuntimeError(
            "openpyxl is required for LTDS Excel parsing — "
            "install with `.venv/bin/pip install openpyxl`"
        ) from exc


# ---------------------------------------------------------------------------
# UKPN — primary exemplar (end-to-end)
# ---------------------------------------------------------------------------
UKPN_ODS_BASE = "https://ukpowernetworks.opendatasoft.com/api/explore/v2.1/catalog/datasets"
UKPN_ODS_PRIMARY_DS = "ukpn-primary-postcode-area"  # primary substation loading info
UKPN_ODS_GRID_DS = "ukpn-grid-and-primary-sites"    # grid+primary sites w/ coords

# UKPN licence area codes → region label.
UKPN_LICENCE_AREAS = {
    "EPN": "Eastern Power Networks",
    "SPN": "South Eastern Power Networks",
    "LPN": "London Power Networks",
}


async def fetch_ukpn_ods_records(dataset_id: str = UKPN_ODS_GRID_DS, limit: int = 100) -> list[dict]:
    """Fetch all UKPN LTDS records via the OpenDataSoft v2.1 catalog API.

    We reuse the project's shared UKPN ODS endpoint. No auth required for
    public datasets, but an `apikey` is honoured if `UKPN_ODS_APIKEY` is set.
    """
    import os
    import httpx

    apikey = os.environ.get("UKPN_ODS_APIKEY", "").strip()
    auth = f"&apikey={apikey}" if apikey else ""
    records: list[dict] = []
    offset = 0
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            url = f"{UKPN_ODS_BASE}/{dataset_id}/records?limit={limit}&offset={offset}{auth}"
            r = await client.get(url)
            if r.status_code != 200:
                log.warning("UKPN ODS %s HTTP %d at offset %d", dataset_id, r.status_code, offset)
                break
            data = r.json()
            batch = data.get("results", [])
            if not batch:
                break
            records.extend(batch)
            total = int(data.get("total_count", 0) or 0)
            offset += limit
            if offset >= total:
                break
    log.info("UKPN ODS %s: fetched %d records", dataset_id, len(records))
    return records


def _ukpn_to_project(rec: dict) -> SubstationProject | None:
    """Map one UKPN ODS record → SubstationProject. Returns None if unusable."""
    name = (rec.get("sitename") or rec.get("sitefunctionallocation") or "").strip()
    if not name:
        return None

    licence_area = (rec.get("licencearea") or "").strip()
    region = UKPN_LICENCE_AREAS.get(licence_area, licence_area or "Unknown")

    # Voltage — UKPN exposes single voltage for the site, so use primary only.
    voltage = _safe_float(rec.get("sitevoltage"))

    # Transformer rating — max of summer/winter as capacity proxy.
    trans_summer = _safe_float(rec.get("transratingsummer"))
    trans_winter = _safe_float(rec.get("transratingwinter"))
    capacity_mva: float | None = None
    if trans_summer or trans_winter:
        capacity_mva = max(x for x in (trans_summer, trans_winter) if x is not None)

    # Coords — prefer spatial_coordinates, fallback to geo_point_2d.
    lat, lon = _extract_latlon(rec)
    wkt = f"POINT({lon} {lat})" if lat and lon else None

    # OSGB is not provided by UKPN ODS — pipeline layer will convert from WGS84.
    project_id = _canonical_id("UKPN", name, None)

    # Site type → station_type + upgrade/new guess.
    site_type = (rec.get("sitetype") or "").lower()
    station_type = "substation"  # UKPN grid/primary are all substations, no switching stations in this dataset.

    return SubstationProject(
        project_id=project_id,
        external_ids={"ltds": rec.get("sitefunctionallocation") or name},
        substation_name=name,
        station_type=station_type,
        parent_project=None,
        project_description=site_type or None,
        upgrade_or_new="unknown",  # LTDS is a snapshot — upgrade classification lives in RIIO CV.
        region=region,
        lpa=None,
        county=rec.get("county"),
        country=COUNTRY_BY_DEVELOPER.get("UKPN", "England"),
        geom_wkt=wkt,
        osgb_easting=None,
        osgb_northing=None,
        parent_company=PARENT_COMPANY_BY_DEVELOPER.get("UKPN"),
        developer="UKPN",
        voltage_kv_primary=voltage,
        voltage_kv_secondary=None,
        voltage_description=None,
        equipment_description=rec.get("sitetype"),
        equipment_capacity_mva=capacity_mva,
        construction_year=None,
        construction_date_detail=None,
        construction_status="complete",  # LTDS only lists operational assets.
        operation_year=None,
        operation_date_detail=None,
        capex_gbp_millions=None,
        capex_description=None,
        capex_price_base_year=None,
        financial_description=None,
        source_type="LTDS",
        source_docket_id=rec.get("sitefunctionallocation"),
        docket_profile_url=f"https://ukpowernetworks.opendatasoft.com/explore/dataset/{UKPN_ODS_GRID_DS}/",
        source_links=[],
        capex_source_link=None,
        last_updated=datetime.utcnow(),
        confidence=0.85,  # UKPN ODS is authoritative for UKPN assets.
        sme_reviewed=False,
    )


def parse_ukpn_workbook(path: Path | None = None, records: Iterable[dict] | None = None) -> list[SubstationProject]:
    """Parse UKPN LTDS into SubstationProject records.

    Accepts either a local xlsx path OR pre-fetched ODS records. When only a
    path is given, we read the workbook directly; when `records` are given
    (from `fetch_ukpn_ods_records`) we skip the workbook.
    """
    if records is not None:
        out = [p for p in (_ukpn_to_project(r) for r in records) if p is not None]
        log.info("UKPN LTDS: produced %d SubstationProject records from %d input", len(out), sum(1 for _ in records))
        return out

    if path is None:
        return []

    openpyxl = _load_openpyxl()
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows: list[SubstationProject] = []
    # Heuristic: iterate all sheets, look for a header row containing
    # 'Site Name' or similar, then read records.
    for sheet in wb.worksheets:
        header_row, headers = _find_header_row(sheet, candidates=("site name", "sitename", "substation"))
        if not headers:
            continue
        for row in sheet.iter_rows(min_row=header_row + 1, values_only=True):
            if not row or all(v is None for v in row):
                continue
            rec = {h: row[i] if i < len(row) else None for i, h in enumerate(headers)}
            # Normalise ODS-style keys so `_ukpn_to_project` can reuse.
            norm = {
                "sitename": rec.get("site name") or rec.get("sitename") or rec.get("substation name"),
                "sitefunctionallocation": rec.get("functional location") or rec.get("site functional location"),
                "licencearea": rec.get("licence area") or rec.get("licence_area"),
                "sitevoltage": rec.get("site voltage (kv)") or rec.get("voltage kv") or rec.get("voltage"),
                "transratingsummer": rec.get("trans rating summer (mva)") or rec.get("summer rating mva"),
                "transratingwinter": rec.get("trans rating winter (mva)") or rec.get("winter rating mva"),
                "sitetype": rec.get("site type") or rec.get("sitetype"),
                "county": rec.get("county"),
            }
            proj = _ukpn_to_project(norm)
            if proj:
                rows.append(proj)
    log.info("UKPN LTDS workbook: produced %d rows from %s", len(rows), path)
    return rows


# ---------------------------------------------------------------------------
# SSEN — stub
# ---------------------------------------------------------------------------
def parse_ssen_workbook(path: Path | None = None, **_: Any) -> list[SubstationProject]:
    """SSEN LTDS parser — STUB.

    TODO — column-mapping delta vs UKPN:
    * SSEN publishes two LTDS files: "SEPD" (Southern) and "SHEPD" (Scottish
      Hydro). Each has multiple sheets:
        - "Primary Substations"  — headers at row 3
        - "Grid Substations"      — headers at row 2
        - "Transformer Data"      — per-transformer capacity breakdown
    * Column names differ from UKPN:
        - 'Site Name'             → substation_name
        - 'Primary / Grid'        → station_type marker
        - 'Nominal Voltage (kV)'  → voltage_kv_primary
        - 'Firm Capacity (MVA)'   → equipment_capacity_mva
        - 'Forecast Winter Peak Demand (MW) 2024/25' ... 2028/29 — used for upgrade prediction
        - 'Region' uses SSEN's internal zone codes (N1..N6, S1..S6)
    * Licence area inferred from filename (SEPD vs SHEPD).
    * Country: SEPD = England, SHEPD = Scotland.

    When wired, call `_load_openpyxl()`, iterate the two substation sheets,
    map columns via a dict literal, and emit SubstationProject records.
    """
    log.warning("SSEN LTDS parser is not yet implemented — returning empty list")
    return []


# ---------------------------------------------------------------------------
# SPEN — stub
# ---------------------------------------------------------------------------
def parse_spen_workbook(path: Path | None = None, **_: Any) -> list[SubstationProject]:
    """SPEN (SP Energy Networks) LTDS parser — STUB.

    TODO — column-mapping delta vs UKPN:
    * SPEN has two licence areas: SPD (SP Distribution, Scotland) and SPM
      (SP Manweb, North Wales + NW England). Single LTDS workbook with a
      licence-area column.
    * Sheets we care about:
        - "Demand Substations"
        - "BSP" (Bulk Supply Points)
        - "Primary"
    * Header offset: row 4 (SPEN uses 3 title rows with logo + version).
    * Column names:
        - 'Name'
        - 'Voltage [kV]'          → voltage_kv_primary
        - 'Transformer MVA'       → equipment_capacity_mva
        - 'Forecast Demand 2028' (MW)  — used for upgrade prediction
        - 'Planned Works'         → upgrade_or_new ("New Build"|"Reinforcement"|"-")
        - 'Commissioning Year'    → operation_year
        - 'Estimated Capex £m'    → capex_gbp_millions (where populated)
    * Country: SPD = Scotland, SPM = Wales (or England for north-western rural).
    """
    log.warning("SPEN LTDS parser is not yet implemented — returning empty list")
    return []


# ---------------------------------------------------------------------------
# NGED — stub (they use CIM XML, not Excel)
# ---------------------------------------------------------------------------
def parse_nged_workbook(path: Path | None = None, **_: Any) -> list[SubstationProject]:
    """NGED (National Grid Electricity Distribution) LTDS parser — STUB.

    NGED actually publishes CIM RDF/XML (IEC 61970 Stage 1.3 EQ profile),
    NOT Excel. The canonical path is to pull the already-ingested data from
    the `ltds_substations` Postgres table (see `utils/ltds_cim_ingester.py`
    — owned by another agent, do not duplicate its logic here).

    When wired this function should:
      1. Take a pool: asyncpg.Pool argument.
      2. `SELECT mrid, name, dno, licence_area, lat, lon, ...
             FROM ltds_substations WHERE dno='NGED'`
      3. Join `ltds_voltage_levels` for voltage_kv_primary.
      4. Join `ltds_power_transformers` + `ltds_transformer_ends` for
         equipment_capacity_mva (sum of ratedS across end 1 per transformer).
      5. Emit SubstationProject records with source_type='LTDS'.

    Column-mapping delta vs UKPN:
    * No Excel workbook — bridge via CIM tables instead.
    * Licence area is one of: 'East Midlands', 'West Midlands',
      'South West', 'South Wales'.
    * Parent company is National Grid plc (same as NGET — they are sibling
      licensees of the same holding, National Grid Group).
    """
    log.warning("NGED LTDS parser is not yet implemented — use CIM pipeline for NGED")
    return []


# ---------------------------------------------------------------------------
# NPG — stub
# ---------------------------------------------------------------------------
def parse_npg_workbook(path: Path | None = None, **_: Any) -> list[SubstationProject]:
    """NPG (Northern Powergrid) LTDS parser — STUB.

    TODO — column-mapping delta vs UKPN:
    * NPG has two licence areas: NPN (Northeast — Northumberland, Tyne
      and Wear, County Durham, Teesside) and NPY (Yorkshire — W, S, N, E,
      Humber).
    * Workbook layout:
        - Tab "LTDS 2024 NPN" and "LTDS 2024 NPY"
        - Headers at row 2
    * Column names (match UKPN closely but some differ):
        - 'Substation Name'
        - 'Voltage (kV)'
        - 'Rating (MVA)' - winter firm only (no summer/winter split)
        - 'Forecast Peak Demand 2028 (MW)'
        - 'Headroom (MVA)'
        - 'Grid Reference' → OSGB easting/northing (pre-computed)
    * Country: England only.
    """
    log.warning("NPG LTDS parser is not yet implemented — returning empty list")
    return []


# ---------------------------------------------------------------------------
# ENWL — stub
# ---------------------------------------------------------------------------
def parse_enwl_workbook(path: Path | None = None, **_: Any) -> list[SubstationProject]:
    """ENWL (Electricity North West) LTDS parser — STUB.

    TODO — column-mapping delta vs UKPN:
    * ENWL has a single licence area (ENWL).
    * Workbook layout:
        - Tab "BSP & Primary Substations"
        - Headers at row 1 (clean)
    * Column names:
        - 'Substation Name'
        - 'Type' ('BSP' | 'Primary' | 'Grid')
        - 'Nominal Voltage (kV)'
        - 'Firm Capacity (MVA)'
        - 'Winter Peak Demand 2024 (MVA)'
        - 'Constraint' — flag for reinforcement candidacy
    * Country: England only.
    """
    log.warning("ENWL LTDS parser is not yet implemented — returning empty list")
    return []


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
DNO_DISPATCHERS: dict[str, Callable[..., list[SubstationProject]]] = {
    "UKPN": parse_ukpn_workbook,
    "SSEN": parse_ssen_workbook,
    "SPEN": parse_spen_workbook,
    "NGED": parse_nged_workbook,
    "NPG":  parse_npg_workbook,
    "ENWL": parse_enwl_workbook,
}


def parse_ltds_workbook(dno: str, path: Path | None = None, **kwargs: Any) -> list[SubstationProject]:
    """Dispatch to the DNO-specific parser.

    Args:
        dno:   One of UKPN, SSEN, SPEN, NGED, NPG, ENWL (case-insensitive).
        path:  Path to the .xlsx workbook (may be None for online-only DNOs).
        **kwargs: Passed through to the dispatcher — e.g. `records=` for UKPN.

    Raises:
        ValueError if `dno` is not a known licensee.
    """
    key = dno.upper().strip()
    if key not in DNO_DISPATCHERS:
        raise ValueError(f"Unknown DNO '{dno}'; expected one of {list(DNO_DISPATCHERS)}")
    return DNO_DISPATCHERS[key](path=path, **kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _extract_latlon(rec: dict) -> tuple[float | None, float | None]:
    """Try the common UKPN ODS coordinate carriers in priority order."""
    geo = rec.get("spatial_coordinates") or rec.get("geo_point_2d")
    if isinstance(geo, dict):
        lat = geo.get("lat")
        lon = geo.get("lon") or geo.get("lng")
        if lat and lon:
            return float(lat), float(lon)
    shape = rec.get("geo_shape")
    if isinstance(shape, dict):
        coords = (shape.get("geometry") or {}).get("coordinates")
        if isinstance(coords, list) and len(coords) >= 2:
            return float(coords[1]), float(coords[0])
    return None, None


def _canonical_id(developer: str, name: str, year: int | None) -> str:
    """Build a stable SUB-<dev>-<slug>-<yr> project id."""
    slug = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")
    slug = slug[:32] if slug else "UNKNOWN"
    yr = str(year) if year else "LIVE"
    return f"SUB-{developer}-{slug}-{yr}"


def _find_header_row(sheet, candidates: tuple[str, ...], max_scan: int = 10) -> tuple[int, list[str]]:
    """Scan the top `max_scan` rows for one that contains any of `candidates`.

    Returns (row_index, normalised_headers_lower). Returns (0, []) if not found.
    """
    for row_idx, row in enumerate(sheet.iter_rows(min_row=1, max_row=max_scan, values_only=True), start=1):
        cells = [str(c).strip().lower() if c is not None else "" for c in row]
        if any(any(cand in c for cand in candidates) for c in cells):
            return row_idx, cells
    return 0, []
