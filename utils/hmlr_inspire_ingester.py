"""
HMLR INSPIRE Index Polygons ingester.

Source
------
HM Land Registry publishes INSPIRE index polygons (registered land title
extents) as monthly GML inside per-local-authority zipfiles:

    https://use-land-property-data.service.gov.uk/datasets/inspire/download

Access notes
~~~~~~~~~~~~
The public download page is behind a login / click-through and a
rate-limited CDN; direct automated pulls frequently 403. For dev we
therefore expose *two* modes:

1. `--councils "City of London,Camden"`  -- constructs the expected URL
   pattern and attempts to fetch. Gracefully logs and skips on 403.
2. `--zipfile /path/to/export.zip --authority "City of London"` --
   processes a locally-downloaded zipfile. This is the reliable path
   for dev/demos.

Either way, the GML features are parsed, reprojected to SRID 27700
(they already ship in BNG), simplified to a small tolerance, and
upserted into ``hmlr_inspire_parcels``.

CLI
~~~
    python -m utils.hmlr_inspire_ingester --zipfile Land_Registry_Cadastral_Parcels.zip \
        --authority "City of London"
    python -m utils.hmlr_inspire_ingester --councils "City of London,Camden" --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import re
import tempfile
import zipfile
from typing import Any, Iterator
from xml.etree import ElementTree as ET

import asyncpg
import httpx

log = logging.getLogger("princeps.hmlr_inspire_ingester")

BASE_URL = "https://use-land-property-data.service.gov.uk/datasets/inspire/download"
USER_AGENT = "Princeps/1.0 overlay-ingester"
TIMEOUT = 120
RATE_DELAY = 0.5

# GML namespaces used by INSPIRE Index Polygons
GML_NS = {
    "gml": "http://www.opengis.net/gml/3.2",
    "gml_legacy": "http://www.opengis.net/gml",
    # HMLR publishes a small INSPIRE feature schema; we tolerate both root forms.
}


def _db_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://anyatrofimova@localhost:5432/feasibly",
    )


def _slugify_council(name: str) -> str:
    """HMLR zipfile slugs use TitleCase with no spaces: 'City of London' -> 'City_of_London'."""
    return re.sub(r"\s+", "_", name.strip())


def _candidate_urls(council: str) -> list[str]:
    """Best-effort guesses for the monthly download path. HMLR rotates these
    each month; if none resolve we fall back to local-file mode.
    """
    slug = _slugify_council(council)
    return [
        f"{BASE_URL}/{slug}.zip",
        f"https://use-land-property-data.service.gov.uk/datasets/inspire/download/{slug}.zip",
    ]


def fetch_zip_for_council(council: str) -> bytes | None:
    """Attempt to fetch a council's INSPIRE zipfile. Returns None on any
    auth/gating failure (caller should fall through to local-file mode).
    """
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=TIMEOUT, headers=headers, follow_redirects=True) as client:
        for url in _candidate_urls(council):
            try:
                r = client.get(url)
            except httpx.HTTPError as e:
                log.warning("INSPIRE fetch %s errored: %s", url, e)
                continue
            if r.status_code == 200 and r.headers.get("content-type", "").startswith(
                ("application/zip", "application/octet-stream")
            ):
                log.info("Fetched INSPIRE zip for %s (%d bytes)", council, len(r.content))
                return r.content
            log.info("INSPIRE %s -> HTTP %s (%s)", url, r.status_code, r.headers.get("content-type"))
    log.warning("INSPIRE download gated for %s — supply --zipfile instead", council)
    return None


def _iter_gml_features(gml_bytes: bytes) -> Iterator[tuple[str, str]]:
    """Yield (inspire_id, gml_polygon_xml) pairs from an HMLR INSPIRE GML file.

    HMLR uses an ``INSPIRE`` feature with ``INSPIREID`` and a ``geometry`` child
    that holds a MultiSurface / MultiPolygon GML fragment. Different monthly
    releases swap between gml 3.2 and legacy 3.1.1 namespaces; we strip the
    namespace when matching.
    """
    try:
        root = ET.fromstring(gml_bytes)
    except ET.ParseError as e:
        log.error("GML parse failed: %s", e)
        return

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    for member in root.iter():
        if local(member.tag) not in {"featureMember", "member"}:
            continue
        feat = next((c for c in member if local(c.tag) not in {"boundedBy"}), None)
        if feat is None:
            continue
        inspire_id = None
        geom_elem = None
        for child in feat.iter():
            lt = local(child.tag)
            if lt in {"INSPIREID", "inspireid", "fid"} and child.text:
                inspire_id = child.text.strip()
            if lt in {"geometry", "the_geom"} and geom_elem is None:
                geom_elem = child
        if inspire_id and geom_elem is not None:
            # Emit the inner geometry XML (the first element child)
            inner = next(iter(geom_elem), None)
            if inner is not None:
                yield inspire_id, ET.tostring(inner, encoding="unicode")


def _iter_zip_gml(zip_bytes: bytes) -> Iterator[bytes]:
    """Yield raw GML bytes from every ``*.gml`` entry inside a HMLR zipfile."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.filename.lower().endswith(".gml"):
                with zf.open(info) as fh:
                    yield fh.read()


async def upsert_parcels(
    conn: asyncpg.Connection,
    records: list[tuple[str, str]],
    authority_name: str,
    simplify_tolerance_m: float = 0.5,
) -> int:
    """Upsert parcels. ``records`` is ``[(inspire_id, gml_xml), ...]``."""
    sql = """
        INSERT INTO hmlr_inspire_parcels (
            inspire_id, authority_name, area_m2, geom, raw_data, ingested_at
        )
        VALUES (
            $1, $2,
            ST_Area(geom_proj),
            ST_Multi(ST_SimplifyPreserveTopology(geom_proj, $4)),
            $3::jsonb,
            NOW()
        )
        ON CONFLICT (inspire_id) DO UPDATE SET
            authority_name = EXCLUDED.authority_name,
            area_m2        = EXCLUDED.area_m2,
            geom           = EXCLUDED.geom,
            raw_data       = EXCLUDED.raw_data,
            ingested_at    = NOW()
    """
    # We parse GML via ST_GeomFromGML which expects native SRS 27700.
    # Use a CTE wrapper to build geom_proj once.
    wrapped = """
        WITH g AS (
            SELECT ST_SetSRID(ST_GeomFromGML($5), 27700) AS geom_proj
        )
        INSERT INTO hmlr_inspire_parcels (
            inspire_id, authority_name, area_m2, geom, raw_data, ingested_at
        )
        SELECT $1, $2,
               ST_Area(g.geom_proj),
               ST_Multi(ST_SimplifyPreserveTopology(g.geom_proj, $4)),
               $3::jsonb, NOW()
        FROM g
        ON CONFLICT (inspire_id) DO UPDATE SET
            authority_name = EXCLUDED.authority_name,
            area_m2        = EXCLUDED.area_m2,
            geom           = EXCLUDED.geom,
            raw_data       = EXCLUDED.raw_data,
            ingested_at    = NOW()
    """
    n = 0
    for inspire_id, gml_xml in records:
        try:
            await conn.execute(
                wrapped,
                inspire_id,
                authority_name,
                json.dumps({"source": "hmlr_inspire", "authority": authority_name}),
                simplify_tolerance_m,
                gml_xml,
            )
            n += 1
        except Exception as e:
            log.warning("upsert parcel %s failed: %s", inspire_id, e)
    return n


async def ingest(
    councils: list[str] | None,
    zipfile_path: str | None,
    authority: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    summary: dict[str, Any] = {"councils": {}, "total_parcels": 0, "dry_run": dry_run}

    tasks: list[tuple[str, bytes]] = []

    if zipfile_path:
        if not authority:
            raise ValueError("--zipfile requires --authority")
        with open(zipfile_path, "rb") as fh:
            tasks.append((authority, fh.read()))
    elif councils:
        for c in councils:
            data = fetch_zip_for_council(c)
            if data is None:
                summary["councils"][c] = {"status": "gated", "parcels": 0}
                continue
            tasks.append((c, data))
            await asyncio.sleep(RATE_DELAY)
    else:
        raise ValueError("Supply --councils or --zipfile")

    if dry_run:
        for c, blob in tasks:
            count = 0
            for gml in _iter_zip_gml(blob):
                count += sum(1 for _ in _iter_gml_features(gml))
            summary["councils"][c] = {"status": "dry", "parcels": count}
            summary["total_parcels"] += count
        return summary

    conn = await asyncpg.connect(_db_url())
    try:
        for c, blob in tasks:
            records: list[tuple[str, str]] = []
            for gml in _iter_zip_gml(blob):
                records.extend(_iter_gml_features(gml))
            written = await upsert_parcels(conn, records, authority_name=c)
            summary["councils"][c] = {"status": "ok", "parcels": written}
            summary["total_parcels"] += written
    finally:
        await conn.close()

    return summary


def _cli() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest HMLR INSPIRE parcel polygons.",
        epilog=(
            "The public download is often gated. If --councils fails, "
            "download the ZIP manually from use-land-property-data.service.gov.uk "
            "and rerun with --zipfile."
        ),
    )
    ap.add_argument("--councils", type=str,
                    help="Comma-separated local-authority names (e.g. 'City of London,Camden')")
    ap.add_argument("--zipfile", type=str,
                    help="Local HMLR INSPIRE zipfile path (fallback for gated downloads)")
    ap.add_argument("--authority", type=str,
                    help="Authority name to stamp on parcels when using --zipfile")
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and parse but do not write to DB")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    councils = [c.strip() for c in args.councils.split(",")] if args.councils else None
    result = asyncio.run(ingest(
        councils=councils,
        zipfile_path=args.zipfile,
        authority=args.authority,
        dry_run=args.dry_run,
    ))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _cli()
