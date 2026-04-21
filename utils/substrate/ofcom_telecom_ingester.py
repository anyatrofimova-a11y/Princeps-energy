"""
Ofcom fixed telecom links ingester.

Ofcom publishes the Wireless Telegraphy Register (WTR) — every licensed
fixed link above 1 GHz with transmit / receive station coordinates,
frequency, bandwidth, licensee. Public under OGL v3 from
``https://www.ofcom.org.uk/spectrum/information/spectrum-information-system``
and ``https://api.ofcom.org.uk/`` (register access requires a free
developer key).

Each WTR record has **two** stations (A and B). We construct a LineString
between them so the consultee resolver can test line-of-sight
interference buffers with ``ST_DWithin(link_geom, site, 1000)``.

Live API details vary — the WTR is available as a bulk CSV download
and as a paginated JSON API. This ingester prefers the bulk CSV
(configurable via ``OFCOM_WTR_CSV_URL``) and falls back to a no-op if
the source is unreachable, so the consultee engine doesn't hard-fail.

Usage::

    python -m utils.substrate.ofcom_telecom_ingester            # full refresh
    python -m utils.substrate.ofcom_telecom_ingester -0.5,51,0.5,52

Library::

    from utils.substrate.ofcom_telecom_ingester import ingest_ofcom_links
    await ingest_ofcom_links(pool, bbox=None)
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import sys
from typing import Any

import httpx

log = logging.getLogger("princeps.substrate.ofcom_telecom")

SOURCE = "ofcom_telecom_links"

# Default URL is a placeholder — Ofcom distributes the WTR under changing
# dataset IDs. Operators should set OFCOM_WTR_CSV_URL to the current one.
_CSV_URL = os.environ.get(
    "OFCOM_WTR_CSV_URL",
    "https://api.ofcom.org.uk/spectrum/v1/wtr-fixed-links.csv",
)

_CSV_COLUMNS = {
    "licence_no":      ("Licence Number", "LicenceNumber", "licence_no"),
    "operator":        ("Licensee", "Operator", "LicenseeName", "licensee"),
    "freq_mhz_tx":     ("Frequency (MHz)", "TxFrequency", "freq_tx_mhz"),
    "freq_mhz_rx":     ("Rx Frequency (MHz)", "RxFrequency", "freq_rx_mhz"),
    "bandwidth_mhz":   ("Bandwidth (MHz)", "Bandwidth", "bandwidth_mhz"),
    "station_a_lat":   ("Station A Lat", "StationALat", "a_lat"),
    "station_a_lon":   ("Station A Lon", "StationALon", "a_lon"),
    "station_b_lat":   ("Station B Lat", "StationBLat", "b_lat"),
    "station_b_lon":   ("Station B Lon", "StationBLon", "b_lon"),
    "licence_expiry":  ("Licence Expiry Date", "ExpiryDate", "licence_expiry"),
}


def _pick(row: dict[str, Any], candidates: tuple[str, ...]) -> Any:
    for k in candidates:
        if k in row and row[k] not in ("", None):
            return row[k]
    # Case-insensitive fallback.
    low = {k.lower(): v for k, v in row.items()}
    for k in candidates:
        v = low.get(k.lower())
        if v not in ("", None):
            return v
    return None


def _float_or_none(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float] | None) -> bool:
    if bbox is None:
        return True
    min_lon, min_lat, max_lon, max_lat = bbox
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


# ───────────────────────── CSV fetcher ─────────────────────────────────

async def fetch_wtr_csv(
    *, client: httpx.AsyncClient | None = None, timeout_s: float = 90.0,
) -> list[dict[str, Any]]:
    """Download the WTR CSV and return parsed rows. Returns [] on failure
    (caller decides whether to fail-open or log)."""
    owns = client is None
    if owns:
        client = httpx.AsyncClient(timeout=timeout_s, headers={
            "User-Agent": "Princeps Ofcom telecom ingester (contact@princeps.energy)",
            "Accept": "text/csv, application/json",
        })
    try:
        resp = await client.get(_CSV_URL)
        resp.raise_for_status()
        text = resp.text
    except httpx.HTTPError as e:
        log.warning("Ofcom WTR fetch failed — ingester will skip live data: %s", e)
        return []
    finally:
        if owns:
            await client.aclose()

    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as e:
        log.warning("Ofcom WTR CSV parse failed: %s", e)
        return []
    log.info("Ofcom WTR: %d raw rows fetched", len(rows))
    return rows


# ───────────────────────── Upsert ──────────────────────────────────────

_UPSERT_SQL = """
    INSERT INTO ofcom_telecom_links
        (feature_id, operator, service_class,
         frequency_mhz_tx, frequency_mhz_rx, bandwidth_mhz,
         licence_expiry, source_updated_at, geom, raw)
    VALUES ($1, $2, $3, $4, $5, $6, $7::date, now(),
            ST_MakeLine(
                ST_SetSRID(ST_MakePoint($8, $9), 4326),
                ST_SetSRID(ST_MakePoint($10, $11), 4326)
            )::geography,
            $12::jsonb)
    ON CONFLICT (feature_id) DO UPDATE SET
        operator         = EXCLUDED.operator,
        service_class    = EXCLUDED.service_class,
        frequency_mhz_tx = EXCLUDED.frequency_mhz_tx,
        frequency_mhz_rx = EXCLUDED.frequency_mhz_rx,
        bandwidth_mhz    = EXCLUDED.bandwidth_mhz,
        licence_expiry   = EXCLUDED.licence_expiry,
        source_updated_at = EXCLUDED.source_updated_at,
        geom = EXCLUDED.geom,
        raw  = EXCLUDED.raw
    RETURNING (xmax = 0) AS inserted
"""


async def upsert_wtr_rows(
    pool,
    rows: list[dict[str, Any]],
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, int]:
    if not rows:
        return {"inserted": 0, "updated": 0, "skipped": 0}
    inserted = updated = skipped = 0
    async with pool.acquire() as conn:
        for row in rows:
            licence_no = _pick(row, _CSV_COLUMNS["licence_no"])
            a_lat = _float_or_none(_pick(row, _CSV_COLUMNS["station_a_lat"]))
            a_lon = _float_or_none(_pick(row, _CSV_COLUMNS["station_a_lon"]))
            b_lat = _float_or_none(_pick(row, _CSV_COLUMNS["station_b_lat"]))
            b_lon = _float_or_none(_pick(row, _CSV_COLUMNS["station_b_lon"]))
            if not licence_no or None in (a_lat, a_lon, b_lat, b_lon):
                skipped += 1
                continue
            if not (_in_bbox(a_lat, a_lon, bbox) or _in_bbox(b_lat, b_lon, bbox)):
                skipped += 1
                continue
            try:
                r = await conn.fetchrow(
                    _UPSERT_SQL,
                    f"ofcom:{licence_no}",
                    _pick(row, _CSV_COLUMNS["operator"]),
                    "fixed_link",
                    _float_or_none(_pick(row, _CSV_COLUMNS["freq_mhz_tx"])),
                    _float_or_none(_pick(row, _CSV_COLUMNS["freq_mhz_rx"])),
                    _float_or_none(_pick(row, _CSV_COLUMNS["bandwidth_mhz"])),
                    _pick(row, _CSV_COLUMNS["licence_expiry"]),
                    a_lon, a_lat, b_lon, b_lat,
                    json.dumps(row),
                )
                if r and r["inserted"]:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                log.debug("Ofcom upsert %s failed: %s", licence_no, e)
                skipped += 1
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


# ───────────────────────── Entry point ─────────────────────────────────

async def ingest_ofcom_links(
    pool,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    """Fetch Ofcom WTR fixed links and upsert to ``ofcom_telecom_links``.

    If the WTR endpoint is unreachable we log a warning and return a
    zero-row result. The table is still populated (possibly with no new
    rows), so the consultee resolver's predicate test will just return
    false and the rule will fail open as before — but without the noisy
    "table missing" warning.
    """
    run_id = None
    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            "INSERT INTO constraint_layers_ingest_log (layer, bbox, started_at) "
            "VALUES ($1, $2::jsonb, now()) RETURNING id",
            "ofcom_telecom_links", json.dumps(list(bbox)) if bbox else None,
        )

    try:
        rows = await fetch_wtr_csv()
        counts = await upsert_wtr_rows(pool, rows, bbox=bbox)
    except Exception as e:
        log.exception("Ofcom WTR ingest failed")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE constraint_layers_ingest_log "
                "SET finished_at=now(), status='failed', error_message=$1 WHERE id=$2",
                str(e), run_id,
            )
        return {"layer": "ofcom_telecom_links", "error": str(e)}

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE constraint_layers_ingest_log "
            "SET finished_at=now(), status='ok', rows_inserted=$1, rows_updated=$2 "
            "WHERE id=$3",
            counts["inserted"], counts["updated"], run_id,
        )
    log.info("Ofcom WTR ingest: inserted=%d updated=%d skipped=%d",
             counts["inserted"], counts["updated"], counts.get("skipped", 0))
    return {"layer": "ofcom_telecom_links", "bbox": bbox, **counts}


# ───────────────────────── CLI ─────────────────────────────────────────

def _parse_bbox(s: str) -> tuple[float, float, float, float]:
    parts = [float(p) for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError(f"bbox must be minLon,minLat,maxLon,maxLat — got {s!r}")
    return tuple(parts)  # type: ignore[return-value]


async def _cli():
    bbox = _parse_bbox(sys.argv[1]) if len(sys.argv) > 1 else None
    from app.deps import get_pool
    pool = await get_pool()
    try:
        result = await ingest_ofcom_links(pool, bbox)
        print(json.dumps(result, indent=2, default=str))
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_cli())
