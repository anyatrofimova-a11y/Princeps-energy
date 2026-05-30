"""planning.data.gov.uk — unified ingester + spatial helpers (Task #17).

Collapses the Top-21 OGL v3.0 datasets at https://www.planning.data.gov.uk
into one async API: fetch_designations / overlap_check / nearest_within.
Live HTTP via the Entity API; geometries reprojected on the wire
(EPSG:4326 -> 27700). 24h in-memory cache keyed by (slug, bbox, day).
Polite rate-limiting (<5 concurrent, 100ms jitter, exp backoff on 429/5xx).
flood-risk-zone is API-filter only — never bulk-loaded (2.58 GB).
"""

from __future__ import annotations

import asyncio, hashlib, json, logging, random, time
from datetime import date, datetime, timezone


def _to_date(v: Any) -> date | None:
    """Coerce a date-like value to ``datetime.date`` (asyncpg requires it for ::date params)."""
    if v is None or v == "":
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None
from typing import Any, Iterable

import httpx
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform as shp_transform
from shapely.geometry.base import BaseGeometry

log = logging.getLogger("princeps.planning_data_uk")

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

BASE = "https://www.planning.data.gov.uk"
BULK = "https://files.planning.data.gov.uk/dataset"

# Top-21 OGL v3.0 datasets (slugs).
TOP21: list[str] = [
    "site-of-special-scientific-interest",
    "ancient-woodland",
    "flood-risk-zone",
    "green-belt",
    "agricultural-land-classification",
    "special-area-of-conservation",
    "special-protection-area",
    "ramsar",
    "listed-building",
    "listed-building-outline",
    "conservation-area",
    "scheduled-monument",
    "national-park",
    "area-of-outstanding-natural-beauty",
    "local-nature-reserve",
    "national-nature-reserve",
    "nutrient-neutrality-catchment",
    "tree-preservation-zone",
    "article-4-direction-area",
    "brownfield-land",
    "local-planning-authority",
]

# Severity tiering: CRITICAL = NO-GO unless special justification;
# HIGH = NPPF balance / mitigation; MEDIUM = informational.
SEVERITY: dict[str, str] = {
    "site-of-special-scientific-interest": "CRITICAL",
    "special-area-of-conservation": "CRITICAL",
    "special-protection-area": "CRITICAL",
    "ramsar": "CRITICAL", "ancient-woodland": "CRITICAL",
    "scheduled-monument": "CRITICAL", "national-park": "CRITICAL",
    "national-nature-reserve": "CRITICAL",
    "flood-risk-zone": "HIGH", "green-belt": "HIGH",
    "area-of-outstanding-natural-beauty": "HIGH",
    "agricultural-land-classification": "HIGH",
    "listed-building": "HIGH", "listed-building-outline": "HIGH",
    "conservation-area": "HIGH",
    "nutrient-neutrality-catchment": "HIGH",
    "tree-preservation-zone": "HIGH",
    "article-4-direction-area": "HIGH",
    "local-nature-reserve": "MEDIUM", "brownfield-land": "MEDIUM",
    "local-planning-authority": "MEDIUM",
}

# Bulk-API blocklist — these are too large to ever bulk-download.
BULK_BLOCKLIST = {"flood-risk-zone"}

USER_AGENT = "Princeps/1.0 planning.data.gov.uk ingester (anya.trofimova@yahoo.com)"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_CONCURRENCY = 5
CACHE_TTL_SECONDS = 24 * 3600  # 24 h

# ---------------------------------------------------------------------------
# Reprojection helpers (cached singletons)
# ---------------------------------------------------------------------------

_TX_4326_TO_27700 = Transformer.from_crs(4326, 27700, always_xy=True)
_TX_27700_TO_4326 = Transformer.from_crs(27700, 4326, always_xy=True)


def reproject_4326_to_27700(geom: BaseGeometry) -> BaseGeometry:
    return shp_transform(lambda x, y, z=None: _TX_4326_TO_27700.transform(x, y), geom)


def reproject_27700_to_4326(geom: BaseGeometry) -> BaseGeometry:
    return shp_transform(lambda x, y, z=None: _TX_27700_TO_4326.transform(x, y), geom)


def bbox_27700_to_4326(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Reproject a (minx, miny, maxx, maxy) bbox 27700 -> 4326 via 4 corners."""
    minx, miny, maxx, maxy = bbox
    pts = [_TX_27700_TO_4326.transform(x, y) for x, y in
           ((minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy))]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# In-memory cache (slug, bbox_hash, day-bucket) -> features
# ---------------------------------------------------------------------------

_CACHE: dict[tuple[str, str, str], tuple[float, list[dict]]] = {}
_CACHE_LOCK = asyncio.Lock()


def _day_bucket() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _bbox_hash(bbox: tuple[float, float, float, float]) -> str:
    return hashlib.md5(json.dumps(list(bbox)).encode()).hexdigest()[:12]


async def _cache_get(key: tuple[str, str, str]) -> list[dict] | None:
    async with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        ts, payload = entry
        if time.time() - ts > CACHE_TTL_SECONDS:
            _CACHE.pop(key, None)
            return None
        return payload


async def _cache_put(key: tuple[str, str, str], payload: list[dict]) -> None:
    async with _CACHE_LOCK:
        if len(_CACHE) > 512:  # soft cap — evict oldest 128
            for k, _ in sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:128]:
                _CACHE.pop(k, None)
        _CACHE[key] = (time.time(), payload)


# ---------------------------------------------------------------------------
# HTTP — polite shared session + retry
# ---------------------------------------------------------------------------

_SESSION_SEMAPHORE = asyncio.Semaphore(DEFAULT_MAX_CONCURRENCY)


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any] | None = None,
    *,
    max_retries: int = 5,
) -> dict[str, Any]:
    """GET with concurrency cap, jitter, and exponential backoff."""
    last_exc: Exception | None = None
    async with _SESSION_SEMAPHORE:
        for attempt in range(max_retries):
            await asyncio.sleep(random.uniform(0, 0.1))  # jitter
            try:
                r = await client.get(url, params=params)
                if r.status_code in (429, 500, 502, 503, 504):
                    wait = min(60.0, 2.0 ** attempt + random.random())
                    log.warning("planning.data.gov.uk HTTP %s — retry in %.1fs", r.status_code, wait)
                    await asyncio.sleep(wait)
                    continue
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last_exc = exc
                wait = min(30.0, 2.0 ** attempt + random.random())
                log.warning("planning.data.gov.uk request failed (%s) — retry in %.1fs", exc, wait)
                await asyncio.sleep(wait)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("planning.data.gov.uk request exhausted retries with no error captured")


# ---------------------------------------------------------------------------
# Core: fetch_designations
# ---------------------------------------------------------------------------

async def fetch_designations(
    bbox_27700: tuple[float, float, float, float],
    datasets: Iterable[str] = TOP21,
    *,
    limit_per_dataset: int = 500,
    client: httpx.AsyncClient | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch live designations for a bbox (EPSG:27700) across `datasets`.

    Returns a dict keyed by slug with a list of GeoJSON features whose
    geometries have been reprojected to EPSG:27700. Each feature carries
    the original ``properties`` plus ``severity``, ``entity_id`` and a
    ``source_url`` for click-through.
    """
    bbox_4326 = bbox_27700_to_4326(bbox_27700)
    out: dict[str, list[dict[str, Any]]] = {}

    close_when_done = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    try:
        async def _one(slug: str) -> tuple[str, list[dict]]:
            key = (slug, _bbox_hash(bbox_4326), _day_bucket())
            cached = await _cache_get(key)
            if cached is not None:
                return slug, cached
            url = f"{BASE}/entity.geojson"
            params = {
                "dataset": slug,
                "geometry_relation": "intersects",
                "geometry": (
                    f"POLYGON(({bbox_4326[0]} {bbox_4326[1]}, "
                    f"{bbox_4326[2]} {bbox_4326[1]}, "
                    f"{bbox_4326[2]} {bbox_4326[3]}, "
                    f"{bbox_4326[0]} {bbox_4326[3]}, "
                    f"{bbox_4326[0]} {bbox_4326[1]}))"
                ),
                "limit": min(500, limit_per_dataset),
            }
            try:
                data = await _get_json(client, url, params=params)
            except Exception as exc:
                log.warning("fetch_designations %s failed: %s", slug, exc)
                await _cache_put(key, [])
                return slug, []

            features = data.get("features", []) or []
            cleaned: list[dict] = []
            for feat in features:
                try:
                    geom_geojson = feat.get("geometry")
                    if not geom_geojson:
                        continue
                    geom_4326 = shape(geom_geojson)
                    geom_27700 = reproject_4326_to_27700(geom_4326)
                    props = feat.get("properties") or {}
                    entity_id = props.get("entity") or props.get("entity_id")
                    cleaned.append({
                        "type": "Feature",
                        "entity_id": entity_id,
                        "dataset": slug,
                        "severity": SEVERITY.get(slug, "MEDIUM"),
                        "source_url": (
                            f"{BASE}/entity/{entity_id}" if entity_id else None
                        ),
                        "properties": props,
                        "geometry_4326": geom_geojson,
                        "geometry_27700": mapping(geom_27700),
                    })
                except Exception as exc:
                    log.debug("feat skip in %s: %s", slug, exc)
            await _cache_put(key, cleaned)
            return slug, cleaned

        results = await asyncio.gather(
            *[_one(slug) for slug in datasets], return_exceptions=False
        )
        for slug, feats in results:
            out[slug] = feats
    finally:
        if close_when_done:
            await client.aclose()
    return out


# ---------------------------------------------------------------------------
# Core: overlap_check
# ---------------------------------------------------------------------------

async def overlap_check(
    site_polygon_27700: BaseGeometry,
    datasets: Iterable[str] = TOP21,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return designations that overlap a site polygon (EPSG:27700).

    Each hit carries ``overlap_m2`` and ``overlap_pct`` for auditable
    citations in the agent verdict.
    """
    bbox = tuple(site_polygon_27700.bounds)  # (minx, miny, maxx, maxy)
    feats_by_slug = await fetch_designations(bbox, datasets=datasets, client=client)
    site_area = max(1e-6, site_polygon_27700.area)
    out: dict[str, list[dict]] = {}
    for slug, feats in feats_by_slug.items():
        hits: list[dict] = []
        for feat in feats:
            try:
                geom = shape(feat["geometry_27700"])
                if not geom.intersects(site_polygon_27700):
                    continue
                inter = geom.intersection(site_polygon_27700)
                if inter.is_empty:
                    continue
                area_m2 = float(inter.area)
                hits.append({
                    "entity_id": feat.get("entity_id"),
                    "dataset": slug,
                    "severity": feat.get("severity"),
                    "name": (feat.get("properties") or {}).get("name"),
                    "reference": (feat.get("properties") or {}).get("reference"),
                    "source_url": feat.get("source_url"),
                    "overlap_m2": round(area_m2, 1),
                    "overlap_pct": round(100.0 * area_m2 / site_area, 2),
                })
            except Exception as exc:
                log.debug("overlap calc skip in %s: %s", slug, exc)
        if hits:
            out[slug] = sorted(hits, key=lambda h: -h["overlap_m2"])
    return out


# ---------------------------------------------------------------------------
# Core: nearest_within
# ---------------------------------------------------------------------------

async def nearest_within(
    point_27700: tuple[float, float],
    distance_m: float,
    datasets: Iterable[str] = TOP21,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return designations within `distance_m` of a point (EPSG:27700)."""
    from shapely.geometry import Point

    pt = Point(point_27700)
    # Build a search bbox from a buffered envelope.
    pad = max(distance_m, 100.0)
    bbox = (pt.x - pad, pt.y - pad, pt.x + pad, pt.y + pad)
    feats_by_slug = await fetch_designations(bbox, datasets=datasets, client=client)
    out: dict[str, list[dict]] = {}
    for slug, feats in feats_by_slug.items():
        hits: list[dict] = []
        for feat in feats:
            try:
                geom = shape(feat["geometry_27700"])
                d = float(geom.distance(pt))
                if d <= distance_m:
                    hits.append({
                        "entity_id": feat.get("entity_id"),
                        "dataset": slug,
                        "severity": feat.get("severity"),
                        "name": (feat.get("properties") or {}).get("name"),
                        "reference": (feat.get("properties") or {}).get("reference"),
                        "source_url": feat.get("source_url"),
                        "distance_m": round(d, 1),
                    })
            except Exception as exc:
                log.debug("nearest calc skip in %s: %s", slug, exc)
        if hits:
            out[slug] = sorted(hits, key=lambda h: h["distance_m"])
    return out


# ---------------------------------------------------------------------------
# Schema bootstrap (idempotent, called from db_setup / startup)
# ---------------------------------------------------------------------------

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS planning_designations (
    entity_id BIGINT PRIMARY KEY,
    dataset TEXT NOT NULL,
    reference TEXT,
    name TEXT,
    organisation_entity TEXT,
    quality TEXT,
    entry_date DATE,
    start_date DATE,
    end_date DATE,
    attrs JSONB,
    geom GEOMETRY(MultiPolygon, 27700) NOT NULL,
    source_url TEXT,
    last_updated TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS planning_designations_gix ON planning_designations USING GIST(geom);
CREATE INDEX IF NOT EXISTS planning_designations_ds ON planning_designations(dataset);

CREATE TABLE IF NOT EXISTS planning_designations_etag (
    dataset TEXT PRIMARY KEY,
    etag TEXT,
    last_modified TEXT,
    last_refresh TIMESTAMPTZ,
    rows_loaded INT,
    status TEXT
);
"""


async def ensure_schema(pool) -> None:
    """Create the planning_designations table + ETag tracker."""
    async with pool.acquire() as conn:
        await conn.execute(CREATE_SQL)
    log.info("planning_designations schema ensured")


# ---------------------------------------------------------------------------
# Bulk upsert helper (used by scripts/refresh_planning_data_uk.py)
# ---------------------------------------------------------------------------

async def upsert_designation_rows(
    conn,
    rows: list[dict[str, Any]],
) -> int:
    """Bulk UPSERT planning_designations rows. Returns count written.

    Each row dict must contain: ``entity_id`` (int), ``dataset`` (str),
    ``geom_geojson`` (dict in EPSG:4326), and optional metadata fields.
    """
    sql = """
    INSERT INTO planning_designations
      (entity_id, dataset, reference, name, organisation_entity, quality,
       entry_date, start_date, end_date, attrs, geom, source_url, last_updated)
    VALUES (
      $1, $2, $3, $4, $5, $6,
      $7::date, $8::date, $9::date, $10::jsonb,
      ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($11), 4326), 27700)),
      $12, NOW()
    )
    ON CONFLICT (entity_id) DO UPDATE SET
       dataset = EXCLUDED.dataset,
       reference = EXCLUDED.reference,
       name = EXCLUDED.name,
       organisation_entity = EXCLUDED.organisation_entity,
       quality = EXCLUDED.quality,
       entry_date = EXCLUDED.entry_date,
       start_date = EXCLUDED.start_date,
       end_date = EXCLUDED.end_date,
       attrs = EXCLUDED.attrs,
       geom = EXCLUDED.geom,
       source_url = EXCLUDED.source_url,
       last_updated = NOW()
    """
    n = 0
    skipped: dict[str, int] = {}
    first_error: str | None = None
    for r in rows:
        eid, slug, geom = r.get("entity_id"), r.get("dataset"), r.get("geom_geojson")
        if not eid or not slug or not geom:
            skipped["missing_required"] = skipped.get("missing_required", 0) + 1
            continue
        try:
            await conn.execute(
                sql, int(eid), slug, r.get("reference"), r.get("name"),
                r.get("organisation_entity"), r.get("quality"),
                _to_date(r.get("entry_date")), _to_date(r.get("start_date")),
                _to_date(r.get("end_date")),
                json.dumps(r.get("attrs") or {}), json.dumps(geom),
                r.get("source_url"),
            )
            n += 1
        except Exception as exc:
            key = type(exc).__name__
            skipped[key] = skipped.get(key, 0) + 1
            if first_error is None:
                first_error = f"{key}: {exc}"[:300]
    if skipped:
        log.warning("upsert dropped rows for %s: written=%d skipped=%s first_error=%s",
                     rows[0].get("dataset") if rows else "?", n, skipped, first_error)
    return n


async def record_etag(conn, dataset: str, *, etag: str | None,
                      last_modified: str | None, rows_loaded: int, status: str) -> None:
    await conn.execute(
        "INSERT INTO planning_designations_etag "
        "(dataset, etag, last_modified, last_refresh, rows_loaded, status) "
        "VALUES ($1, $2, $3, NOW(), $4, $5) "
        "ON CONFLICT (dataset) DO UPDATE SET etag=EXCLUDED.etag, "
        "last_modified=EXCLUDED.last_modified, last_refresh=EXCLUDED.last_refresh, "
        "rows_loaded=EXCLUDED.rows_loaded, status=EXCLUDED.status",
        dataset, etag, last_modified, rows_loaded, status,
    )


async def stored_etag(conn, dataset: str) -> tuple[str | None, str | None]:
    row = await conn.fetchrow(
        "SELECT etag, last_modified FROM planning_designations_etag WHERE dataset = $1",
        dataset,
    )
    return (row["etag"], row["last_modified"]) if row else (None, None)
