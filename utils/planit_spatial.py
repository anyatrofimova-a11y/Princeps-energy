"""
utils/planit_spatial.py — Radius-query against the PlanIt API for any UK
planning application within Xkm of a lat/lon, no keyword filter.

The Princeps Intelligence stack already has `app/ingestion/planit_lpa.py`
which scrapes PlanIt with energy-keywords ("solar farm", "battery storage",
"data centre", …). That is the right tool for *building a regulatory feed*.
This module solves a different problem:

    "For asset X at (lat, lon), give me every planning decision in the
     surrounding Xkm — agricultural barns, telecom masts, housing, road
     widening, schools — so I can characterise the local planning context
     before I commit to an option."

PlanIt's spatial endpoint is undocumented but stable (used by their own
map). Schema discovered by inspection of /api/applics/json:

    GET https://www.planit.org.uk/api/applics/json
        ?lat={lat}&lng={lng}&krad={km}    spatial filter
        &start_date=YYYY-MM-DD             ISO date floor on app date
        &compress=on                       newest-first paging
        &pg_sz={N}                         page size (default 100, max 250)
        &page={p}                          1-based pagination

Response (JSON):
    {
      "total": <int>, "page_size": <int>,
      "records": [
        {
          "uid": "23/00012/FUL",
          "name": "Construction of dwelling at ...",
          "url": "https://www.planit.org.uk/planapplic/...",
          "associated_url": "<council portal deep-link>",
          "lat": <float>, "lng": <float>,
          "altlab": "Status: Decided",
          "start_date": "2023-04-01", "decided_date": "2023-09-12",
          "consulted_date": "...",
          "app_size": "Other", "app_type": "Full",
          "app_state": "Decided", "decision": "Approved",
          "area_name": "South Gloucestershire",
          "authority_name": "South Gloucestershire Council",
          "authority_id": "SouthGloucestershire",
          ...
        },
        ...
      ]
    }

We surface:
    fetch_nearby(lat, lon, radius_km, since_days) -> list[NearbyApplication]

with a SQLite-style asyncpg cache table `planit_nearby_cache` keyed by
(lat, lon, radius_km, since_days) so the asset popup never blocks on a slow
PlanIt request twice.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

log = logging.getLogger("princeps.planit_spatial")

_PLANIT_BASE = "https://www.planit.org.uk/api/applics/json"
_USER_AGENT = "Princeps/1.0 (+https://princeps.energy) planit-spatial"
_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
_MAX_PAGES = 8       # safety cap: 8 × 250 = 2000 apps per call
_PAGE_SIZE = 250


@dataclass(frozen=True)
class NearbyApplication:
    """One planning application from PlanIt's spatial index."""
    uid: str
    name: str
    description: str | None
    lat: float | None
    lng: float | None
    distance_km: float | None
    authority_name: str | None
    authority_id: str | None
    area_name: str | None
    app_type: str | None
    app_state: str | None
    decision: str | None
    start_date: str | None        # ISO YYYY-MM-DD
    decided_date: str | None
    consulted_date: str | None
    associated_url: str | None    # deep-link to council portal
    planit_url: str | None        # PlanIt aggregator page
    raw: dict | None = None       # passthrough for the renderer


def _haversine_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    from math import radians, sin, cos, asin, sqrt
    R = 6371.0
    lat1, lat2 = radians(a_lat), radians(b_lat)
    dlat = radians(b_lat - a_lat)
    dlng = radians(b_lng - a_lng)
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * R * asin(min(1.0, sqrt(h)))


def _parse_record(rec: dict, query_lat: float, query_lng: float) -> NearbyApplication | None:
    uid = (rec.get("uid") or rec.get("reference") or "").strip()
    if not uid:
        return None
    rec_lat = rec.get("lat")
    rec_lng = rec.get("lng") or rec.get("lon")
    distance = None
    try:
        if rec_lat is not None and rec_lng is not None:
            distance = round(_haversine_km(
                float(query_lat), float(query_lng),
                float(rec_lat), float(rec_lng),
            ), 3)
    except Exception:
        distance = None
    return NearbyApplication(
        uid=uid,
        name=str(rec.get("name") or rec.get("title") or "")[:300],
        description=(rec.get("description") or rec.get("summary") or None),
        lat=float(rec_lat) if rec_lat is not None else None,
        lng=float(rec_lng) if rec_lng is not None else None,
        distance_km=distance,
        authority_name=rec.get("authority_name") or rec.get("area_name"),
        authority_id=rec.get("authority_id") or rec.get("authority"),
        area_name=rec.get("area_name"),
        app_type=rec.get("app_type") or rec.get("app_size"),
        app_state=rec.get("app_state") or rec.get("altlab"),
        decision=rec.get("decision"),
        start_date=rec.get("start_date") or rec.get("date_received"),
        decided_date=rec.get("decided_date") or rec.get("date_decided"),
        consulted_date=rec.get("consulted_date") or rec.get("date_consulted"),
        associated_url=rec.get("associated_url") or rec.get("url_council"),
        planit_url=rec.get("url"),
        raw=None,
    )


async def fetch_nearby(
    lat: float,
    lng: float,
    radius_km: float = 5.0,
    since_days: int = 365 * 5,
    *,
    keyword: str | None = None,
    max_records: int = 1000,
    client: httpx.AsyncClient | None = None,
) -> list[NearbyApplication]:
    """Return planning applications within radius_km of (lat, lng).

    Parameters
    ----------
    lat, lng        WGS84 decimal degrees.
    radius_km       Search radius (km) — PlanIt's `krad`.
    since_days      Backstop ISO date floor; default 5 years of history.
    keyword         Optional free-text filter routed through PlanIt's `search`.
                    Leave None for the full neutral sweep that the user asked
                    for ("any application near here, not just renewables").
    max_records     Hard cap to protect the asset popup.
    """
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError(f"lat/lng out of range: ({lat}, {lng})")
    if radius_km <= 0:
        return []
    radius_km = min(radius_km, 30.0)        # PlanIt errors above ~30 km
    since = (date.today() - timedelta(days=since_days)).isoformat()

    params_base: dict[str, Any] = {
        "lat": f"{lat:.6f}",
        "lng": f"{lng:.6f}",
        "krad": f"{radius_km:.2f}",
        "compress": "on",
        "start_date": since,
        "pg_sz": _PAGE_SIZE,
        "sort": "-start_date",
    }
    if keyword:
        params_base["search"] = keyword

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT})

    out: list[NearbyApplication] = []
    try:
        for pg in range(1, _MAX_PAGES + 1):
            params = dict(params_base, page=pg)
            try:
                r = await client.get(_PLANIT_BASE, params=params)
                r.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("planit page %d failed (%s) — stopping pagination", pg, exc)
                break
            data = r.json()
            recs = data.get("records") or data.get("data") or []
            if not recs:
                break
            for rec in recs:
                nb = _parse_record(rec, lat, lng)
                if nb is not None:
                    out.append(nb)
                if len(out) >= max_records:
                    break
            if len(out) >= max_records or len(recs) < _PAGE_SIZE:
                break
    finally:
        if own_client:
            await client.aclose()

    out.sort(key=lambda a: (a.distance_km if a.distance_km is not None else 9e9))
    return out


# ---------------------------------------------------------------------------
# Caching layer (asyncpg)
# ---------------------------------------------------------------------------
_DDL = """
CREATE TABLE IF NOT EXISTS planit_nearby_cache (
    cache_key       TEXT PRIMARY KEY,
    lat             DOUBLE PRECISION NOT NULL,
    lng             DOUBLE PRECISION NOT NULL,
    radius_km       DOUBLE PRECISION NOT NULL,
    since_days      INTEGER NOT NULL,
    keyword         TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload         JSONB NOT NULL,
    record_count    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS planit_nearby_cache_geo_idx
    ON planit_nearby_cache (lat, lng);
"""


async def ensure_schema(pool) -> None:
    async with pool.acquire() as c:
        await c.execute(_DDL)


def _cache_key(lat: float, lng: float, radius_km: float, since_days: int, kw: str | None) -> str:
    return f"{lat:.5f}:{lng:.5f}:{radius_km:.2f}:{since_days}:{kw or '-'}"


async def fetch_nearby_cached(
    pool,
    lat: float,
    lng: float,
    radius_km: float = 5.0,
    since_days: int = 365 * 5,
    *,
    keyword: str | None = None,
    ttl_minutes: int = 60 * 12,
    max_records: int = 1000,
) -> list[NearbyApplication]:
    """Cache-aware variant — returns DB-cached records if fresh enough."""
    await ensure_schema(pool)
    key = _cache_key(lat, lng, radius_km, since_days, keyword)
    async with pool.acquire() as c:
        row = await c.fetchrow(
            "SELECT payload, fetched_at FROM planit_nearby_cache WHERE cache_key = $1",
            key,
        )
    if row is not None:
        age = (datetime.now(timezone.utc) - row["fetched_at"]).total_seconds() / 60.0
        if age < ttl_minutes:
            payload = row["payload"]
            if isinstance(payload, str):
                import json
                payload = json.loads(payload)
            return [NearbyApplication(**rec) for rec in payload]

    fresh = await fetch_nearby(
        lat, lng, radius_km, since_days,
        keyword=keyword, max_records=max_records,
    )
    payload = [asdict(a) for a in fresh]
    async with pool.acquire() as c:
        import json
        await c.execute(
            """
            INSERT INTO planit_nearby_cache
                (cache_key, lat, lng, radius_km, since_days, keyword, payload, record_count)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
            ON CONFLICT (cache_key) DO UPDATE
            SET payload = EXCLUDED.payload,
                fetched_at = now(),
                record_count = EXCLUDED.record_count
            """,
            key, lat, lng, radius_km, since_days, keyword,
            json.dumps(payload), len(fresh),
        )
    return fresh


# ---------------------------------------------------------------------------
# Convenience: classify nearby apps for the asset-intel popup
# ---------------------------------------------------------------------------
def classify(apps: list[NearbyApplication]) -> dict:
    """Bucket the apps by status / type / decision so the UI can show counts."""
    by_state: dict[str, int] = {}
    by_decision: dict[str, int] = {}
    by_authority: dict[str, int] = {}
    energy_keywords = ("solar", "battery", "storage", "wind", "data centre",
                       "datacentre", "data-centre", "hydrogen", "grid",
                       "substation", "ev charging", "biomass", "energy")
    energy_apps = []
    for a in apps:
        st = (a.app_state or "Unknown").strip()
        by_state[st] = by_state.get(st, 0) + 1
        d = (a.decision or "Pending").strip()
        by_decision[d] = by_decision.get(d, 0) + 1
        au = (a.authority_name or "Unknown").strip()
        by_authority[au] = by_authority.get(au, 0) + 1
        if any(kw in (a.name or "").lower() or kw in (a.description or "").lower()
               for kw in energy_keywords):
            energy_apps.append(a.uid)
    return {
        "total": len(apps),
        "by_state": dict(sorted(by_state.items(), key=lambda kv: -kv[1])),
        "by_decision": dict(sorted(by_decision.items(), key=lambda kv: -kv[1])),
        "by_authority": dict(sorted(by_authority.items(), key=lambda kv: -kv[1])[:8]),
        "energy_related_uids": energy_apps[:50],
        "earliest_start": min(
            (a.start_date for a in apps if a.start_date), default=None,
        ),
        "latest_decision": max(
            (a.decided_date for a in apps if a.decided_date), default=None,
        ),
    }
