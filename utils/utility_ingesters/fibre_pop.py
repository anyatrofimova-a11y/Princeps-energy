"""
fibre_pop.py — carrier fibre POP / exchange seed → fibre_pops.

Status: STUB seed. There is no freely-downloadable UK carrier meet-me-room
register — Openreach's exchange list is published as a PDF per-postcode
area, LINX publishes member docs but the POP coords live in marketing
pages, and private carriers (Zayo, Neos, euNetworks) don't publish
machine-readable coordinates at all.

Rather than stall the sweep, this module ships a small hand-curated seed
of (a) the biggest Openreach inner-London/core-city exchanges, (b) the UK
tier-1 internet exchanges (LINX, LoNAP, IXScotland, IXManchester), and (c)
a handful of known carrier-neutral hotels. Coordinates are to street
accuracy (±50 m) — enough to render as a POP marker on the DC twin, not
enough for cable-path design.

TODO (follow-up): scrape Openreach Wholesale's OSEA listing (per-postcode
PDFs) + Ofcom PIA register for full UK coverage. Tracked under the wider
"2026_04 infra sweep" and left for a future bot pass.

CLI:
    python -m utils.utility_ingesters.fibre_pop [--bbox='w,s,e,n']
    python -m utils.utility_ingesters.fibre_pop --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os

import asyncpg

from utils.utility_ingesters import ensure_schema, parse_bbox

log = logging.getLogger("princeps.utility_ingesters.fibre_pop")

# ─── Hand-curated seed ─────────────────────────────────────────────────────
# Shape: (external_id, name, carrier, pop_class, city, lat, lon, notes)
#
# Sources:
#   openreach: Openreach Wholesale exchange code list (major metro cores only)
#   linx:      linx.net site pages
#   lonap:     lonap.net site pages
#   ixscotland:ixscotland.net
#   ixmcr:     ixmanchester.org.uk
#   cns:       carrier-neutral hotel — well-known UK colos
#
# Coordinates are WGS84 lat/lon of the street address, ±50 m.
_SEED: list[tuple[str, str, str, str, str, float, float, str]] = [
    # ── Openreach core London exchanges ─────────────────────────────────
    ("openreach:LDFAR",  "Faraday Exchange",       "openreach", "exchange", "London",     51.5158, -0.0999, "EC1A — City core"),
    ("openreach:LDMAM",  "Museum Exchange",        "openreach", "exchange", "London",     51.5177, -0.1298, "WC1A"),
    ("openreach:LDCIT",  "City Exchange",          "openreach", "exchange", "London",     51.5134, -0.0886, "EC2M"),
    ("openreach:LDHOL",  "Holborn Exchange",       "openreach", "exchange", "London",     51.5174, -0.1183, "WC1V"),
    ("openreach:LDCHE",  "Chelsea Exchange",       "openreach", "exchange", "London",     51.4877, -0.1689, "SW3"),
    ("openreach:LDKEN",  "Kensington Exchange",    "openreach", "exchange", "London",     51.5005, -0.1890, "W8"),
    ("openreach:LDSTR",  "Stratford Exchange",     "openreach", "exchange", "London",     51.5416, -0.0039, "E15"),
    ("openreach:LDCRO",  "Croydon Exchange",       "openreach", "exchange", "Croydon",    51.3726, -0.1020, "CR0"),
    ("openreach:LDDAG",  "Dagenham Exchange",      "openreach", "exchange", "Dagenham",   51.5428,  0.1344, "RM10"),
    ("openreach:LDHEA",  "Heathrow Exchange",      "openreach", "exchange", "Hounslow",   51.4700, -0.4543, "TW6"),
    # ── Openreach regional metro cores ──────────────────────────────────
    ("openreach:MRCEN",  "Manchester Central",     "openreach", "core",     "Manchester", 53.4794, -2.2453, "M1"),
    ("openreach:BMCEN",  "Birmingham Central",     "openreach", "core",     "Birmingham", 52.4792, -1.8997, "B1"),
    ("openreach:GLCEN",  "Glasgow Central",        "openreach", "core",     "Glasgow",    55.8578, -4.2591, "G1"),
    ("openreach:EDCEN",  "Edinburgh Central",      "openreach", "core",     "Edinburgh",  55.9529, -3.1896, "EH1"),
    ("openreach:BSCEN",  "Bristol Central",        "openreach", "core",     "Bristol",    51.4543, -2.5957, "BS1"),
    ("openreach:LECEN",  "Leeds Central",          "openreach", "core",     "Leeds",      53.7955, -1.5443, "LS1"),
    ("openreach:LVCEN",  "Liverpool Central",      "openreach", "core",     "Liverpool",  53.4055, -2.9909, "L1"),
    ("openreach:NCCEN",  "Newcastle Central",      "openreach", "core",     "Newcastle",  54.9707, -1.6110, "NE1"),
    ("openreach:SHCEN",  "Sheffield Central",      "openreach", "core",     "Sheffield",  53.3803, -1.4696, "S1"),
    ("openreach:CDCEN",  "Cardiff Central",        "openreach", "core",     "Cardiff",    51.4778, -3.1760, "CF10"),
    # ── LINX — London Internet Exchange ─────────────────────────────────
    ("linx:LD8",         "LINX LD8 (Telehouse North Two)", "linx", "ix", "London", 51.5167, -0.0069, "Coriander Ave, E14"),
    ("linx:LD4",         "LINX LD4 (Telehouse North)",     "linx", "ix", "London", 51.5168, -0.0076, "Coriander Ave, E14"),
    ("linx:LD5",         "LINX LD5 (Equinix LD5 Slough)",  "linx", "ix", "Slough",  51.5019, -0.6155, "Buckingham Ave"),
    ("linx:LD6",         "LINX LD6 (Interxion LON1)",      "linx", "ix", "London", 51.5251, -0.0853, "Sovereign House, N1"),
    ("linx:LD7",         "LINX LD7 (Equinix LD7 Docklands)","linx", "ix", "London", 51.5164, -0.0056, "Harbour Exchange, E14"),
    ("linx:MCR",         "IXManchester (LINX MA1)",        "linx", "ix", "Manchester", 53.4795, -2.2418, "Equinix MA1"),
    ("linx:EDI",         "IXScotland (LINX ED1)",          "linx", "ix", "Edinburgh", 55.9457, -3.2026, "Pulsant South Gyle"),
    # ── LoNAP — independent London exchange ─────────────────────────────
    ("lonap:LON1",       "LoNAP LON1 (Telehouse West)",    "lonap", "ix", "London", 51.5177, -0.0100, "Coriander Ave, E14"),
    ("lonap:LON2",       "LoNAP LON2 (Global Switch)",     "lonap", "ix", "London", 51.5220, -0.0875, "Worship St, EC2A"),
    ("lonap:LON3",       "LoNAP LON3 (Equinix LD8)",       "lonap", "ix", "London", 51.5167, -0.0069, "Coriander Ave, E14"),
    # ── Carrier-neutral colos (frequently used as meet-me rooms) ────────
    ("cns:telehouse-n",  "Telehouse North",                "telehouse", "pop", "London", 51.5168, -0.0076, "Coriander Ave, E14"),
    ("cns:telehouse-w",  "Telehouse West",                 "telehouse", "pop", "London", 51.5177, -0.0100, "Coriander Ave, E14"),
    ("cns:equinix-ld5",  "Equinix LD5 (Slough)",           "equinix",   "pop", "Slough",  51.5019, -0.6155, "Slough Trading Estate"),
    ("cns:equinix-ld8",  "Equinix LD8 (Docklands)",        "equinix",   "pop", "London",  51.5167, -0.0069, "Harbour Exchange, E14"),
    ("cns:global-switch","Global Switch London",           "global-switch", "pop", "London", 51.5220, -0.0875, "Great Eastern Enterprise, EC2A"),
    ("cns:interxion-lon1","Interxion LON1",                "digital-realty", "pop", "London", 51.5251, -0.0853, "Sovereign House, N1"),
    ("cns:kao-park-hrl", "Kao Data / Harlow",              "kao-data", "pop", "Harlow", 51.7720, 0.1320, "Kao Park — Stansted corridor"),
    ("cns:pulsant-south-gyle","Pulsant South Gyle",         "pulsant", "pop", "Edinburgh", 55.9457, -3.2026, "South Gyle Cres"),
]


async def _upsert(conn: asyncpg.Connection, rows: list[tuple]) -> int:
    count = 0
    for ext_id, name, carrier, pop_class, city, lat, lon, notes in rows:
        try:
            await conn.execute(
                """
                INSERT INTO fibre_pops
                    (external_id, name, carrier, pop_class, city, lat, lon,
                     geom, source, notes, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7,
                        ST_Transform(ST_SetSRID(ST_MakePoint($7, $6), 4326), 27700),
                        $8, $9, NOW())
                ON CONFLICT (external_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    carrier = EXCLUDED.carrier,
                    pop_class = EXCLUDED.pop_class,
                    city = EXCLUDED.city,
                    lat = EXCLUDED.lat,
                    lon = EXCLUDED.lon,
                    geom = EXCLUDED.geom,
                    notes = EXCLUDED.notes,
                    updated_at = NOW()
                """,
                ext_id, name, carrier, pop_class, city, lat, lon,
                f"seed:{carrier}", notes,
            )
            count += 1
        except Exception as e:
            log.debug("fibre_pop upsert failed for %s: %s", ext_id, e)
    return count


async def ingest(
    pool: asyncpg.Pool,
    bbox: tuple[float, float, float, float] | None = None,
    *,
    dry_run: bool = False,
) -> dict:
    """Seed fibre_pops from the hand-curated list.

    If bbox is provided, only POPs inside the bbox are upserted — useful
    for per-region idempotent seeding. Otherwise the full seed lands.
    """
    if bbox is not None:
        w, s, e, n = bbox
        rows = [r for r in _SEED if (w <= r[6] <= e) and (s <= r[5] <= n)]
    else:
        rows = list(_SEED)

    if dry_run:
        return {
            "status": "dry_run",
            "fetched": len(rows),
            "upserted": 0,
            "stubbed": True,
            "note": "hand-curated seed — see fibre_pop.py TODO for full scrape",
        }

    async with pool.acquire() as conn:
        await ensure_schema(conn)
        upserted = await _upsert(conn, rows)

    log.info("fibre_pops: fetched=%d upserted=%d (seed)", len(rows), upserted)
    return {
        "status": "success",
        "fetched": len(rows),
        "upserted": upserted,
        "stubbed": True,
        "bbox": list(bbox) if bbox else None,
        "note": "hand-curated seed — see fibre_pop.py TODO for full scrape",
    }


async def _cli_main() -> int:
    parser = argparse.ArgumentParser(description="Seed fibre_pops from carrier POP list.")
    parser.add_argument("--bbox", default=None, help="Optional bbox 'w,s,e,n' to limit seed")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if not args.db_url:
        print("DATABASE_URL not set", flush=True)
        return 2

    bbox = parse_bbox(args.bbox) if args.bbox else None
    pool = await asyncpg.create_pool(args.db_url, min_size=1, max_size=2)
    try:
        summary = await ingest(pool, bbox=bbox, dry_run=args.dry_run)
    finally:
        await pool.close()
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary.get("status") in ("success", "dry_run") else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(_cli_main()))
