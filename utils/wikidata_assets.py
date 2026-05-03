"""
utils/wikidata_assets.py — SPARQL queries for UK energy-asset biographies.

Wikidata (https://query.wikidata.org/sparql) holds rich profiles for almost
every UK power station, wind farm, solar farm, BESS site of any prominence:
commission year, operator, owner, OEM, gross capacity, fuel, primary fuel,
photo, English Wikipedia URL. Free, no auth, ~5 req/s rate limit.

Two entry points:

    nearest_asset(lat, lon, radius_km)
        Spatial search: which power-station entity sits closest to (lat,lon)
        within `radius_km`? Used when the asset clicked on the map didn't
        have a Wikidata QID attached.

    biography(qid_or_name)
        Look up by Wikidata QID *or* English label. Returns AssetBiography
        with everything Wikidata knows.

The functions are async + use httpx so they slot into the existing fanout
pattern in ``asset_intel_aggregator``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger("princeps.wikidata_assets")

_WD_ENDPOINT = "https://query.wikidata.org/sparql"
_USER_AGENT = "Princeps/1.0 (+https://princeps.energy) wikidata-assets"
_TIMEOUT = httpx.Timeout(20.0, connect=8.0)


@dataclass(frozen=True)
class AssetBiography:
    qid: str | None
    label: str | None
    description: str | None
    fuel: str | None
    primary_fuel_qid: str | None
    capacity_mw: float | None
    operator: str | None
    owner: str | None
    oem: str | None
    commission_year: int | None
    decommission_year: int | None
    coordinates_latlng: tuple[float, float] | None
    en_wikipedia_url: str | None
    image_url: str | None
    instance_of: list[str] | None     # e.g. ["thermal power station","CCGT"]


# ---------------------------------------------------------------------------
# SPARQL helpers
# ---------------------------------------------------------------------------
async def _sparql(query: str, *, client: httpx.AsyncClient | None = None) -> dict | None:
    own = client is None
    if own:
        client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/sparql-results+json"},
        )
    try:
        r = await client.get(_WD_ENDPOINT, params={"query": query, "format": "json"})
        if r.status_code != 200:
            log.warning("wikidata sparql %s: %s", r.status_code, r.text[:160])
            return None
        return r.json()
    except httpx.HTTPError as exc:
        log.warning("wikidata sparql failed: %s", exc)
        return None
    finally:
        if own:
            await client.aclose()


def _val(b: dict, k: str) -> str | None:
    v = b.get(k, {})
    return v.get("value") if isinstance(v, dict) else None


def _to_qid(uri: str | None) -> str | None:
    if not uri:
        return None
    return uri.rsplit("/", 1)[-1] if uri.startswith("http") else uri


# ---------------------------------------------------------------------------
# Nearest power-station search
# ---------------------------------------------------------------------------
async def nearest_asset(
    lat: float,
    lon: float,
    radius_km: float = 2.0,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict | None:
    """Return {qid, label, distance_km} for the nearest power-station entity.

    Scope: Wikidata items that are instances of (or subclasses of) Q159719
    "power station" — covers thermal, nuclear, hydro, wind farm, solar farm.
    """
    q = f"""
    SELECT ?item ?itemLabel ?coord WHERE {{
      SERVICE wikibase:around {{
        ?item wdt:P625 ?coord.
        bd:serviceParam wikibase:center "Point({lon} {lat})"^^geo:wktLiteral.
        bd:serviceParam wikibase:radius "{radius_km}".
      }}
      ?item wdt:P31/wdt:P279* wd:Q159719.
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    LIMIT 5
    """
    res = await _sparql(q, client=client)
    if not res or not res.get("results", {}).get("bindings"):
        return None
    rows = res["results"]["bindings"]
    # parse "Point(lon lat)" coord and pick closest
    from math import radians, sin, cos, asin, sqrt
    def dist(rlat, rlon):
        R = 6371.0
        a = sin(radians(rlat - lat) / 2) ** 2 + \
            cos(radians(lat)) * cos(radians(rlat)) * sin(radians(rlon - lon) / 2) ** 2
        return 2 * R * asin(min(1.0, sqrt(a)))
    closest = None
    for b in rows:
        coord = _val(b, "coord")
        if not coord or not coord.startswith("Point("):
            continue
        try:
            inside = coord[6:-1]
            rlon, rlat = (float(x) for x in inside.split())
        except Exception:
            continue
        d = round(dist(rlat, rlon), 3)
        item = _val(b, "item")
        label = _val(b, "itemLabel") or "—"
        if closest is None or d < closest["distance_km"]:
            closest = {"qid": _to_qid(item), "label": label, "distance_km": d,
                       "lat": rlat, "lon": rlon}
    return closest


# ---------------------------------------------------------------------------
# Full biography by QID
# ---------------------------------------------------------------------------
async def biography(
    qid_or_label: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> AssetBiography | None:
    """Fetch all interesting Wikidata properties for a power-station entity.

    Accepts either a QID (e.g. "Q3138396") or an English label
    ("Seabank Power Station") — labels are resolved via the search API.
    """
    qid = qid_or_label.strip()
    own = client is None
    if own:
        client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/sparql-results+json"},
        )
    try:
        if not qid.startswith("Q") or not qid[1:].isdigit():
            qid = await _resolve_label(qid, client=client)
            if qid is None:
                return None

        q = f"""
        SELECT
          ?label ?description
          (GROUP_CONCAT(DISTINCT ?fuelLabel; separator="|") AS ?fuels)
          (SAMPLE(?primaryFuel) AS ?primaryFuel)
          (SAMPLE(?capacity) AS ?capacity)
          (GROUP_CONCAT(DISTINCT ?operatorLabel; separator="|") AS ?operators)
          (GROUP_CONCAT(DISTINCT ?ownerLabel; separator="|") AS ?owners)
          (GROUP_CONCAT(DISTINCT ?oemLabel; separator="|") AS ?oems)
          (SAMPLE(?inception) AS ?inception)
          (SAMPLE(?diss) AS ?diss)
          (SAMPLE(?coord) AS ?coord)
          (SAMPLE(?image) AS ?image)
          (GROUP_CONCAT(DISTINCT ?instanceLabel; separator="|") AS ?instances)
          (SAMPLE(?enwiki) AS ?enwiki)
        WHERE {{
          BIND(wd:{qid} AS ?item)
          ?item rdfs:label ?label . FILTER(LANG(?label)="en")
          OPTIONAL {{ ?item schema:description ?description . FILTER(LANG(?description)="en") }}
          OPTIONAL {{ ?item wdt:P625 ?coord }}
          OPTIONAL {{ ?item wdt:P571 ?inception }}
          OPTIONAL {{ ?item wdt:P576 ?diss }}
          OPTIONAL {{ ?item wdt:P2109 ?capacity }}
          OPTIONAL {{ ?item wdt:P18 ?image }}
          OPTIONAL {{
            ?item wdt:P31 ?inst .
            ?inst rdfs:label ?instanceLabel . FILTER(LANG(?instanceLabel)="en")
          }}
          OPTIONAL {{
            ?item wdt:P527 ?fuelEntity .
            ?fuelEntity rdfs:label ?fuelLabel . FILTER(LANG(?fuelLabel)="en")
          }}
          OPTIONAL {{ ?item wdt:P1672 ?primaryFuel }}
          OPTIONAL {{
            ?item wdt:P137 ?op .
            ?op rdfs:label ?operatorLabel . FILTER(LANG(?operatorLabel)="en")
          }}
          OPTIONAL {{
            ?item wdt:P127 ?own .
            ?own rdfs:label ?ownerLabel . FILTER(LANG(?ownerLabel)="en")
          }}
          OPTIONAL {{
            ?item wdt:P176 ?oem .
            ?oem rdfs:label ?oemLabel . FILTER(LANG(?oemLabel)="en")
          }}
          OPTIONAL {{
            ?enwiki schema:about ?item ;
                    schema:inLanguage "en" ;
                    schema:isPartOf <https://en.wikipedia.org/> .
          }}
        }}
        GROUP BY ?label ?description
        """
        res = await _sparql(q, client=client)
        if not res:
            return None
        bindings = res.get("results", {}).get("bindings", [])
        if not bindings:
            return None
        b = bindings[0]

        coord = _val(b, "coord")
        latlng: tuple[float, float] | None = None
        if coord and coord.startswith("Point("):
            try:
                inside = coord[6:-1]
                lon_s, lat_s = inside.split()
                latlng = (float(lat_s), float(lon_s))
            except Exception:
                latlng = None

        inception = _val(b, "inception")
        diss = _val(b, "diss")
        try:
            year_in = int(inception[:4]) if inception else None
        except Exception:
            year_in = None
        try:
            year_out = int(diss[:4]) if diss else None
        except Exception:
            year_out = None

        cap = _val(b, "capacity")
        try:
            cap_mw = float(cap) if cap else None
        except Exception:
            cap_mw = None

        return AssetBiography(
            qid=qid,
            label=_val(b, "label"),
            description=_val(b, "description"),
            fuel=_first(_val(b, "fuels")),
            primary_fuel_qid=_to_qid(_val(b, "primaryFuel")),
            capacity_mw=cap_mw,
            operator=_first(_val(b, "operators")),
            owner=_first(_val(b, "owners")),
            oem=_first(_val(b, "oems")),
            commission_year=year_in,
            decommission_year=year_out,
            coordinates_latlng=latlng,
            en_wikipedia_url=_val(b, "enwiki"),
            image_url=_val(b, "image"),
            instance_of=_split(_val(b, "instances")),
        )
    finally:
        if own:
            await client.aclose()


def _split(s: str | None) -> list[str] | None:
    if not s:
        return None
    return [x for x in s.split("|") if x][:5]


def _first(s: str | None) -> str | None:
    if not s:
        return None
    return s.split("|", 1)[0] or None


async def _resolve_label(label: str, *, client: httpx.AsyncClient) -> str | None:
    """Map an English label to a QID via wbsearchentities."""
    r = await client.get(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbsearchentities",
            "search": label,
            "language": "en",
            "format": "json",
            "limit": 5,
            "type": "item",
        },
    )
    if r.status_code != 200:
        return None
    js = r.json()
    for cand in js.get("search", []):
        # Prefer matches whose description hints at energy infrastructure
        desc = (cand.get("description") or "").lower()
        if any(k in desc for k in ("power station", "wind farm", "solar farm",
                                   "battery storage", "data centre",
                                   "nuclear power", "hydroelectric")):
            return cand.get("id")
    if js.get("search"):
        return js["search"][0].get("id")
    return None


def biography_to_dict(b: AssetBiography | None) -> dict | None:
    return asdict(b) if b else None
