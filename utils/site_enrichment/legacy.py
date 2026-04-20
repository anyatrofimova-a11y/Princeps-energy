"""Deterministic site enrichment — postcode / LPA / parish / ward / UPRN / title.

Replaces the `[Postcode required]` / `[Local Planning Authority — confirm from
LPA boundary service]` placeholder strings in the 1APP summary, DCO application
form, and Book of Reference with real values derived from free UK APIs.

Lookup sources (free, no API key)
---------------------------------
* **postcodes.io** — reverse geocode lat/lon → nearest postcode, returns
  admin_district, admin_ward, parish, parliamentary_constituency, OSGB
  eastings/northings, LSOA/MSOA codes. Single JSON endpoint, unauthenticated,
  maintainer requests polite throttling (< 10 req/s).

* **planning.data.gov.uk** — MHCLG unified planning data API. Used for:
    - ``dataset=local-planning-authority`` point-in-polygon → LPA name + code
    - ``dataset=parish`` point-in-polygon → civil parish (where one exists)
    - ``dataset=title-boundary`` point-in-polygon → HMLR INSPIRE parcel match
  Reuses the async paginator pattern from
  ``app/connectors/designations/_common.py`` (same service family).

* **HMLR INSPIRE polygons in Postgres** (``hmlr_inspire_parcels`` table) —
  when the DB has ingested the open INSPIRE dataset, a lat/lon point lookup
  is free and fast. Returns ``inspire_id`` (treated as parcel identifier,
  NOT the HMLR Title Number — a true Title Number requires a paid HMLR
  Official Copy search).

Fields that are not directly derivable
--------------------------------------
* **UPRN** — Ordnance Survey AddressBase is a licensed product. OS Open UPRN
  is a 40M-row CSV dump (too heavy to ingest here). postcodes.io does not
  expose UPRN. Planning.data.gov.uk does not publish a UPRN lookup at point
  granularity. We therefore return ``None`` with provenance
  ``lookup_method="deferred_to_addressbase_purchase"`` and attach a
  structured TODO so the downstream 1APP renderer flags the field as
  "pending — order UPRN via AddressBase Plus" rather than a bare
  placeholder.

* **Land Registry Title Number** — The Title Number itself is only available
  via an Official Copy search (£3 per title). We can derive the INSPIRE
  polygon ID (which uniquely identifies the registered parcel), but we
  cannot surface the Title Number text without a paid lookup. Same TODO
  pattern: ``lookup_method="hmlr_official_search_required"`` plus the
  INSPIRE ID when available.

Provenance
----------
Every enriched field carries its own small dict:
    {"source": "postcodes.io" | "planning.data.gov.uk" | "hmlr_inspire_parcels"
             | "ai_inferred" | "deferred_to_addressbase_purchase" | "hmlr_official_search_required",
     "method": "reverse_geocode" | "point_in_polygon" | "postgres_spatial"
             | "downstream_order_required" | "ai_fallback",
     "confidence": float in [0,1] (1.0 for deterministic API hit, 0.6 for AI),
     "retrieved_utc": "2026-04-19T..."}

Caching
-------
Callers cache the full ``SiteEnrichment`` dict on ``projects.metadata
["site_enrichment"]`` keyed by ``(lat, lon, rev_date)`` so repeated planning
bundle generations are O(1) DB reads. See ``POST /api/sites/{project_id}
/enrich`` in ``app/routers/project_actions.py`` for the cache writer.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

log = logging.getLogger("princeps.site_enrichment")

USER_AGENT = "Princeps/1.0 site-enrichment"
HTTP_TIMEOUT = 20.0

POSTCODES_IO_BASE = "https://api.postcodes.io"
PLANNING_DATA_BASE = "https://www.planning.data.gov.uk/entity.json"

# Polite throttle — postcodes.io maintainers ask for < 10 req/s; we keep plenty of headroom.
_RATE_LIMIT_S = 0.15


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _provenance(
    source: str,
    *,
    method: str,
    confidence: float,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "source": source,
        "method": method,
        "confidence": round(float(confidence), 3),
        "retrieved_utc": _now_iso(),
    }
    if extra:
        out.update(extra)
    return out


def _point_wkt(lat: float, lon: float) -> str:
    """WGS84 POINT WKT for planning.data.gov.uk geometry filter (lon first)."""
    return f"POINT({lon} {lat})"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class EnrichedField:
    value: Any = None
    provenance: dict[str, Any] = field(default_factory=dict)
    todo: Optional[str] = None  # filled when value is None but recoverable by human action

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"value": self.value, "provenance": self.provenance}
        if self.todo:
            d["todo"] = self.todo
        return d


@dataclass
class SiteEnrichment:
    lat: float
    lon: float
    postcode: EnrichedField = field(default_factory=EnrichedField)
    osgb_grid_ref: EnrichedField = field(default_factory=EnrichedField)
    local_planning_authority: EnrichedField = field(default_factory=EnrichedField)
    parish: EnrichedField = field(default_factory=EnrichedField)
    ward: EnrichedField = field(default_factory=EnrichedField)
    parliamentary_constituency: EnrichedField = field(default_factory=EnrichedField)
    uprn: EnrichedField = field(default_factory=EnrichedField)
    land_registry_title: EnrichedField = field(default_factory=EnrichedField)
    rev_date: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "rev_date": self.rev_date,
            "postcode": self.postcode.to_dict(),
            "osgb_grid_ref": self.osgb_grid_ref.to_dict(),
            "local_planning_authority": self.local_planning_authority.to_dict(),
            "parish": self.parish.to_dict(),
            "ward": self.ward.to_dict(),
            "parliamentary_constituency": self.parliamentary_constituency.to_dict(),
            "uprn": self.uprn.to_dict(),
            "land_registry_title": self.land_registry_title.to_dict(),
        }

    def fill_summary(self) -> dict[str, int]:
        """Return {filled, deferred, missing} counts."""
        filled = deferred = missing = 0
        for f in (
            self.postcode, self.osgb_grid_ref, self.local_planning_authority,
            self.parish, self.ward, self.parliamentary_constituency,
            self.uprn, self.land_registry_title,
        ):
            if f.value not in (None, "", []):
                filled += 1
            elif f.todo:
                deferred += 1
            else:
                missing += 1
        return {"filled": filled, "deferred": deferred, "missing": missing}


# ---------------------------------------------------------------------------
# Individual lookups
# ---------------------------------------------------------------------------

async def lookup_postcode(
    lat: float,
    lon: float,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Reverse-geocode via postcodes.io.

    Returns a flat dict with the nearest postcode plus admin attributes, or
    ``{}`` if the call fails / no UK postcode within range.
    """
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    try:
        # postcodes endpoint returns the nearest postcodes ordered by distance
        url = f"{POSTCODES_IO_BASE}/postcodes"
        try:
            r = await client.get(url, params={"lon": lon, "lat": lat, "limit": 1})
        except httpx.HTTPError as e:
            log.warning("postcodes.io lat=%s lon=%s network error: %s", lat, lon, e)
            return {}
        if r.status_code != 200:
            log.info("postcodes.io lat=%s lon=%s status=%d", lat, lon, r.status_code)
            return {}
        try:
            data = r.json()
        except Exception as e:
            log.warning("postcodes.io JSON decode error: %s", e)
            return {}
        results = (data or {}).get("result") or []
        if not results:
            return {}
        rec = results[0]
        codes = rec.get("codes") or {}
        return {
            "postcode": rec.get("postcode"),
            "outcode": rec.get("outcode"),
            "incode": rec.get("incode"),
            "eastings": rec.get("eastings"),
            "northings": rec.get("northings"),
            "admin_district": rec.get("admin_district"),
            "admin_district_code": codes.get("admin_district"),
            "admin_ward": rec.get("admin_ward"),
            "admin_ward_code": codes.get("admin_ward"),
            "parish": rec.get("parish"),
            "parish_code": codes.get("parish"),
            "parliamentary_constituency": rec.get("parliamentary_constituency_2024")
                or rec.get("parliamentary_constituency"),
            "parliamentary_constituency_code": codes.get("parliamentary_constituency_2024")
                or codes.get("parliamentary_constituency"),
            "country": rec.get("country"),
            "region": rec.get("region"),
            "lsoa": rec.get("lsoa"),
            "msoa": rec.get("msoa"),
            "distance_m": rec.get("distance"),
        }
    finally:
        if owns_client and client is not None:
            await client.aclose()


def _osgb_ref_from_eastings_northings(e: int | float, n: int | float, precision: int = 6) -> str:
    """Convert OSGB36 eastings/northings (metres, EPSG:27700) to an all-numeric
    British National Grid reference at the requested digit precision (default
    6 = 100 m grid, e.g. "TQ 300 803").

    The OS grid is a lettered 5x5 block scheme. The 500 km tiles covering
    Great Britain are (bottom-left origin at SV):

        H J     (rows 2-2 in the 500km grid, i.e. n100k // 5 == 2)
        N O
        S T     (e100k // 5 == 0 -> S/N/H, == 1 -> T/O/J)

    Inside each 500 km tile the 100 km sub-tiles follow the standard
    "A..Z skipping I" layout, bottom-row A-E through top-row V-Z, but indexed
    from the top of the block downwards when addressed by ``n100k % 5``.
    """
    try:
        e = int(round(float(e)))
        n = int(round(float(n)))
    except Exception:
        return ""
    if e < 0 or n < 0 or e >= 700_000 or n >= 1_300_000:
        return ""  # outside the British National Grid extent

    e100k = e // 100_000
    n100k = n // 100_000

    # 500 km tile letter (Great Britain subset of the global OS grid)
    _500km = [["S", "T"],
              ["N", "O"],
              ["H", "J"]]
    col_500 = e100k // 5
    row_500 = n100k // 5
    if not (0 <= col_500 < 2 and 0 <= row_500 < 3):
        return ""
    first = _500km[row_500][col_500]

    # 100 km sub-tile letter. Rows indexed top-down: ``n100k % 5 == 4`` is
    # the bottom row (A-E); ``== 0`` is the top row (V-Z). Counter-intuitive
    # but required to make the grid read like a map.
    _rows_top_to_bottom = ["VWXYZ", "QRSTU", "LMNOP", "FGHJK", "ABCDE"]
    col_100 = e100k % 5
    row_100 = n100k % 5
    second = _rows_top_to_bottom[row_100][col_100]

    digit_len = max(1, precision // 2)
    e_frac = (e % 100_000) // (10 ** (5 - digit_len))
    n_frac = (n % 100_000) // (10 ** (5 - digit_len))
    return f"{first}{second} {e_frac:0{digit_len}d} {n_frac:0{digit_len}d}"


async def _planning_point_lookup(
    dataset: str,
    lat: float,
    lon: float,
    *,
    client: Optional[httpx.AsyncClient] = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Point-in-polygon lookup against planning.data.gov.uk."""
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    try:
        try:
            r = await client.get(
                PLANNING_DATA_BASE,
                params={
                    "dataset": dataset,
                    "geometry": _point_wkt(lat, lon),
                    "geometry_relation": "intersects",
                    "limit": limit,
                },
            )
        except httpx.HTTPError as e:
            log.warning("planning.data.gov.uk %s network error: %s", dataset, e)
            return []
        if r.status_code != 200:
            log.info("planning.data.gov.uk %s status=%d", dataset, r.status_code)
            return []
        try:
            data = r.json()
        except Exception:
            return []
        return (data or {}).get("entities") or []
    finally:
        if owns_client and client is not None:
            await client.aclose()


async def lookup_lpa(
    lat: float,
    lon: float,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Point-in-polygon LPA lookup via planning.data.gov.uk."""
    entities = await _planning_point_lookup("local-planning-authority", lat, lon, client=client)
    if not entities:
        return {}
    ent = entities[0]
    return {
        "name": _clean_lpa_name(ent.get("name")),
        "code": ent.get("reference"),
        "entity_id": ent.get("entity"),
        "organisation_id": ent.get("organisation"),
        "url": f"https://www.planning.data.gov.uk/entity/{ent.get('entity')}" if ent.get("entity") else None,
    }


def _clean_lpa_name(raw: Optional[str]) -> Optional[str]:
    """Strip the trailing " LPA" planning.data.gov.uk tacks on to LPA names."""
    if not raw:
        return raw
    s = raw.strip()
    if s.endswith(" LPA"):
        s = s[:-4].strip()
    return s


async def lookup_parish(
    lat: float,
    lon: float,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Civil parish lookup. Central London / City of Westminster is an
    unparished area and will return ``{}`` — callers should fall back to the
    postcodes.io ``parish`` field which includes the "unparished area" flag.
    """
    entities = await _planning_point_lookup("parish", lat, lon, client=client)
    if not entities:
        return {}
    ent = entities[0]
    return {
        "name": ent.get("name"),
        "code": ent.get("reference"),
        "entity_id": ent.get("entity"),
    }


async def lookup_ward(
    lat: float,
    lon: float,
    *,
    postcode_data: Optional[dict[str, Any]] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Prefer the admin_ward returned by postcodes.io — it is ONS-coded and
    generally authoritative. planning.data.gov.uk does not publish a
    dedicated ``ward`` dataset point lookup, so if the postcode call gave us
    nothing we return ``{}`` and let the orchestrator fall back.
    """
    if postcode_data and postcode_data.get("admin_ward"):
        return {
            "name": postcode_data["admin_ward"],
            "code": postcode_data.get("admin_ward_code"),
            "nearest_postcode": postcode_data.get("postcode"),
        }
    # Re-query postcodes.io if we weren't passed the data
    pc = await lookup_postcode(lat, lon, client=client)
    if pc.get("admin_ward"):
        return {
            "name": pc["admin_ward"],
            "code": pc.get("admin_ward_code"),
            "nearest_postcode": pc.get("postcode"),
        }
    return {}


async def lookup_uprn(
    lat: float,
    lon: float,
    *,
    address_hint: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """UPRN lookup.

    OS Open UPRN is a 40M-row downloadable CSV; postcodes.io does not expose
    UPRN; planning.data.gov.uk has no public point->UPRN endpoint. Until the
    Princeps data platform ingests OS Open UPRN (or takes an AddressBase Plus
    licence), this returns a structured TODO so the planning pack flags the
    field honestly instead of shipping a placeholder string.
    """
    return {
        "value": None,
        "todo": (
            "UPRN not available via free point-lookup APIs. Order OS Open UPRN "
            "(free download, ~2 GB CSV) or AddressBase Plus (licensed, ~£4k/yr) "
            "and re-run enrichment. Until then leave blank or enter on-site."
        ),
        "lookup_method": "deferred_to_addressbase_purchase",
    }


async def lookup_land_registry_title(
    lat: float,
    lon: float,
    *,
    polygon_wkt: Optional[str] = None,
    pool=None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Land Registry title-number lookup.

    Strategy:
      1. If an asyncpg ``pool`` is provided and ``hmlr_inspire_parcels`` has
         rows at this point, return the INSPIRE polygon ID (this is NOT the
         HMLR Title Number — but it is the canonical parcel identifier used
         by HMLR for registered land) and flag that an Official Copy search
         is still required for the actual Title Number + tenure + proprietor.
      2. Otherwise, try planning.data.gov.uk ``title-boundary`` point lookup
         (may return INSPIRE polygon metadata for registered freehold land).
      3. If nothing hits, return a structured TODO with the HMLR Official
         Copy order URL (£3 per title, ``land-registry.data.gov.uk``).
    """
    # 1) Postgres INSPIRE lookup
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT inspire_id, authority_name, authority_code, area_m2
                       FROM hmlr_inspire_parcels
                       WHERE ST_Intersects(
                           geom,
                           ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                       )
                       ORDER BY area_m2 ASC NULLS LAST
                       LIMIT 1""",
                    lon, lat,
                )
            if row:
                return {
                    "inspire_id": row["inspire_id"],
                    "authority_name": row["authority_name"],
                    "authority_code": row["authority_code"],
                    "area_m2": float(row["area_m2"]) if row["area_m2"] is not None else None,
                    "title_number": None,  # Title Number itself is paywalled
                    "tenure": None,
                    "ownership_type": None,
                    "lookup_method": "postgres_spatial",
                    "note": (
                        "INSPIRE polygon identified. The HMLR Title Number, tenure, "
                        "and registered proprietor require an Official Copy (Register "
                        "Extract) search at land-registry.data.gov.uk (£3 per title)."
                    ),
                }
        except Exception as e:
            log.info("hmlr_inspire_parcels DB lookup skipped: %s", e)

    # 2) planning.data.gov.uk title-boundary point lookup
    try:
        entities = await _planning_point_lookup("title-boundary", lat, lon, client=client, limit=1)
    except Exception:
        entities = []
    if entities:
        ent = entities[0]
        return {
            "inspire_id": ent.get("reference"),
            "entity_id": ent.get("entity"),
            "title_number": None,
            "tenure": None,
            "ownership_type": None,
            "lookup_method": "planning_data_gov_uk_title_boundary",
            "note": (
                "INSPIRE polygon returned by planning.data.gov.uk. Title Number "
                "and proprietor require an HMLR Official Copy search."
            ),
        }

    # 3) Nothing matched — structured TODO
    return {
        "inspire_id": None,
        "title_number": None,
        "tenure": None,
        "ownership_type": None,
        "lookup_method": "hmlr_official_search_required",
        "todo": (
            "No INSPIRE polygon found at this point in the Princeps DB or "
            "planning.data.gov.uk. Site may be unregistered land, Crown land, "
            "or outside current INSPIRE coverage. Order an HMLR Official Copy "
            "(Register Extract) or Index Map Search at "
            "https://www.gov.uk/search-property-information-land-registry "
            "(£3 per title search, £4 per index map search)."
        ),
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def enrich_site(
    lat: float,
    lon: float,
    *,
    polygon_wkt: Optional[str] = None,
    address_hint: Optional[str] = None,
    pool=None,
    client: Optional[httpx.AsyncClient] = None,
    rate_limit_s: float = _RATE_LIMIT_S,
    use_ai_fallback: bool = False,
) -> SiteEnrichment:
    """Run every lookup, building a :class:`SiteEnrichment`.

    Each lookup runs independently — a failure in one field does not cascade.
    Results are populated with per-field provenance so the downstream pack
    renderer can render "filled" vs "pending" honestly.
    """
    out = SiteEnrichment(lat=lat, lon=lon)

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    try:
        # 1) postcodes.io — single call covers postcode, OSGB e/n, LPA hint,
        # ward, parish, parliamentary constituency.
        pc = await lookup_postcode(lat, lon, client=client)
        await asyncio.sleep(rate_limit_s)

        if pc.get("postcode"):
            out.postcode = EnrichedField(
                value=pc["postcode"],
                provenance=_provenance(
                    "postcodes.io", method="reverse_geocode", confidence=0.98,
                    extra={"distance_m": pc.get("distance_m")},
                ),
            )
        if pc.get("eastings") is not None and pc.get("northings") is not None:
            out.osgb_grid_ref = EnrichedField(
                value=_osgb_ref_from_eastings_northings(pc["eastings"], pc["northings"]),
                provenance=_provenance(
                    "postcodes.io", method="ons_easting_northing_derivation",
                    confidence=0.98,
                    extra={"eastings": pc["eastings"], "northings": pc["northings"]},
                ),
            )
        if pc.get("parliamentary_constituency"):
            out.parliamentary_constituency = EnrichedField(
                value=pc["parliamentary_constituency"],
                provenance=_provenance(
                    "postcodes.io", method="reverse_geocode", confidence=0.95,
                    extra={"code": pc.get("parliamentary_constituency_code")},
                ),
            )

        # 2) LPA — planning.data.gov.uk (authoritative), fall back to
        # postcodes.io admin_district if planning.data is down.
        lpa = await lookup_lpa(lat, lon, client=client)
        await asyncio.sleep(rate_limit_s)
        if lpa.get("name"):
            out.local_planning_authority = EnrichedField(
                value=lpa["name"],
                provenance=_provenance(
                    "planning.data.gov.uk", method="point_in_polygon", confidence=0.98,
                    extra={"code": lpa.get("code"), "url": lpa.get("url")},
                ),
            )
        elif pc.get("admin_district"):
            out.local_planning_authority = EnrichedField(
                value=pc["admin_district"],
                provenance=_provenance(
                    "postcodes.io", method="admin_district_from_postcode",
                    confidence=0.85,
                    extra={"code": pc.get("admin_district_code"),
                           "note": "Admin district = LPA in unitary/London borough areas; verify for two-tier (district vs county)."},
                ),
            )

        # 3) Parish — planning.data.gov.uk first, fall back to postcodes.io
        # which includes "unparished area" labels for inner-city sites.
        parish = await lookup_parish(lat, lon, client=client)
        await asyncio.sleep(rate_limit_s)
        if parish.get("name"):
            out.parish = EnrichedField(
                value=parish["name"],
                provenance=_provenance(
                    "planning.data.gov.uk", method="point_in_polygon", confidence=0.97,
                    extra={"code": parish.get("code")},
                ),
            )
        elif pc.get("parish"):
            out.parish = EnrichedField(
                value=pc["parish"],
                provenance=_provenance(
                    "postcodes.io", method="reverse_geocode", confidence=0.90,
                    extra={"code": pc.get("parish_code")},
                ),
            )

        # 4) Ward
        ward = await lookup_ward(lat, lon, postcode_data=pc, client=client)
        if ward.get("name"):
            out.ward = EnrichedField(
                value=ward["name"],
                provenance=_provenance(
                    "postcodes.io", method="reverse_geocode", confidence=0.95,
                    extra={"code": ward.get("code"),
                           "nearest_postcode": ward.get("nearest_postcode")},
                ),
            )

        # 5) UPRN — deterministic "deferred" marker.
        uprn = await lookup_uprn(lat, lon, address_hint=address_hint, client=client)
        out.uprn = EnrichedField(
            value=uprn.get("value"),
            provenance=_provenance(
                "deferred_to_addressbase_purchase",
                method="downstream_order_required",
                confidence=0.0,
            ),
            todo=uprn.get("todo"),
        )

        # 6) Land Registry title
        lr = await lookup_land_registry_title(
            lat, lon, polygon_wkt=polygon_wkt, pool=pool, client=client,
        )
        await asyncio.sleep(rate_limit_s)
        if lr.get("title_number"):
            out.land_registry_title = EnrichedField(
                value={"title_number": lr["title_number"],
                       "tenure": lr.get("tenure"),
                       "ownership_type": lr.get("ownership_type")},
                provenance=_provenance(
                    "hmlr_inspire_parcels", method=lr.get("lookup_method") or "postgres_spatial",
                    confidence=0.9,
                    extra={"inspire_id": lr.get("inspire_id")},
                ),
            )
        elif lr.get("inspire_id"):
            # INSPIRE polygon only — Title Number still paywalled.
            out.land_registry_title = EnrichedField(
                value={
                    "title_number": None,
                    "inspire_id": lr["inspire_id"],
                    "tenure": None,
                    "ownership_type": None,
                },
                provenance=_provenance(
                    "hmlr_inspire_parcels" if lr.get("lookup_method") == "postgres_spatial" else "planning.data.gov.uk",
                    method=lr.get("lookup_method") or "point_in_polygon",
                    confidence=0.5,
                    extra={"note": lr.get("note")},
                ),
                todo=lr.get("note"),
            )
        else:
            out.land_registry_title = EnrichedField(
                value=None,
                provenance=_provenance(
                    "hmlr_official_search_required",
                    method="downstream_order_required",
                    confidence=0.0,
                ),
                todo=lr.get("todo"),
            )

    finally:
        if owns_client and client is not None:
            await client.aclose()

    # 7) AI fallback for fields that came back empty.
    if use_ai_fallback:
        try:
            from utils.site_enrichment_ai import ai_fill_missing
            await ai_fill_missing(out, pc_hint=pc)
        except Exception as e:
            log.info("site_enrichment AI fallback skipped: %s", e)

    return out


# ---------------------------------------------------------------------------
# Convenience — project dict integration
# ---------------------------------------------------------------------------

def apply_enrichment_to_site_dict(
    site: dict[str, Any],
    enrichment: SiteEnrichment,
) -> dict[str, Any]:
    """Mutate ``site`` (used by document_automation.generate_planning_summary)
    with values from ``enrichment``, without overwriting caller-supplied
    values. Returns ``site`` for chaining.
    """
    def _set(key: str, val: Any) -> None:
        if val in (None, "", []):
            return
        if site.get(key) in (None, "", "[Postcode required]",
                             "[Parish — confirm from LPA boundary data]",
                             "[Ward — confirm from LPA boundary data]",
                             "[UPRN — look up at Ordnance Survey AddressBase]",
                             "[Title number — HMLR official search required]",
                             "[Local Planning Authority — confirm from LPA boundary service]"):
            site[key] = val

    _set("postcode", enrichment.postcode.value)
    _set("local_authority", enrichment.local_planning_authority.value)
    _set("lpa", enrichment.local_planning_authority.value)
    _set("parish", enrichment.parish.value)
    _set("ward", enrichment.ward.value)
    _set("uprn", enrichment.uprn.value)
    if enrichment.land_registry_title.value:
        val = enrichment.land_registry_title.value
        if isinstance(val, dict):
            _set("title_number", val.get("title_number") or val.get("inspire_id"))
        else:
            _set("title_number", val)
    if enrichment.osgb_grid_ref.value:
        _set("osgb_reference", enrichment.osgb_grid_ref.value)
        _set("osgb_grid_ref", enrichment.osgb_grid_ref.value)
    return site


def apply_enrichment_to_project_dict(
    project: dict[str, Any],
    enrichment: SiteEnrichment,
) -> dict[str, Any]:
    """Mutate ``project`` (used by one_app_filler.fill_1app / dco application
    form) with values from ``enrichment``. Writes into both top-level keys
    and ``project['metadata']`` so every downstream consumer picks them up.
    """
    md = project.setdefault("metadata", {}) if isinstance(project.get("metadata"), dict) else {}
    project["metadata"] = md

    def _proj_set(key: str, val: Any) -> None:
        if val in (None, "", []):
            return
        if not project.get(key):
            project[key] = val
        if not md.get(key):
            md[key] = val

    _proj_set("postcode", enrichment.postcode.value)
    _proj_set("lpa", enrichment.local_planning_authority.value)
    _proj_set("local_authority", enrichment.local_planning_authority.value)
    _proj_set("county", enrichment.local_planning_authority.value)  # best proxy
    _proj_set("osgb_reference", enrichment.osgb_grid_ref.value)
    _proj_set("osgb_grid_ref", enrichment.osgb_grid_ref.value)
    _proj_set("parish", enrichment.parish.value)
    _proj_set("ward", enrichment.ward.value)
    _proj_set("uprn", enrichment.uprn.value)
    md.setdefault("parish_ward", None)
    if enrichment.parish.value and enrichment.ward.value:
        md["parish_ward"] = f"{enrichment.parish.value} / {enrichment.ward.value}"
    elif enrichment.ward.value:
        md["parish_ward"] = enrichment.ward.value

    if enrichment.land_registry_title.value:
        val = enrichment.land_registry_title.value
        if isinstance(val, dict):
            _proj_set("title_number", val.get("title_number") or val.get("inspire_id"))
        else:
            _proj_set("title_number", val)

    md["site_enrichment"] = enrichment.to_dict()
    return project


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    async def _main() -> None:
        # Thames BESS Phase 1 coordinate
        e = await enrich_site(lat=51.5074, lon=-0.1278)
        print(json.dumps(e.to_dict(), indent=2))
        print("fill_summary:", e.fill_summary())

    asyncio.run(_main())
