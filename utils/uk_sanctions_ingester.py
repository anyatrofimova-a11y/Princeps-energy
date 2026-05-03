"""UK sanctions ingester — downloads the Office of Financial Sanctions
Implementation (OFSI) consolidated list from gov.uk and loads it into
`uk_sanctions_list`.

Licence: OGL-3.0 (commercial-safe). Registered in app/license_guard/licenses.yaml
as 'uk_sanctions_consolidated'.

Source: https://www.gov.uk/government/publications/the-uk-sanctions-list
The consolidated list is published as ODS / CSV / XML. We use the CSV
export for parsing simplicity.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from datetime import datetime
from typing import Iterable

import httpx

log = logging.getLogger("princeps.uk_sanctions")

OFSI_CONSOLIDATED_CSV = (
    "https://ofsistorage.blob.core.windows.net/publishlive/2022format/"
    "ConList.csv"
)
DEFAULT_TIMEOUT = 60.0


async def fetch_consolidated_csv(url: str = OFSI_CONSOLIDATED_CSV) -> str:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        # OFSI ships the CSV in CP1252 / ISO-8859-1 quite often.
        return r.content.decode("cp1252", errors="replace")


def parse_consolidated_csv(csv_text: str) -> list[dict]:
    """Parse the OFSI consolidated list. Returns one dict per individual /
    entity / vessel / aircraft entry.
    """
    rows = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for raw in reader:
        full_name = _join_names(raw)
        if not full_name:
            continue
        rows.append({
            "entry_id": _stable_entry_id(raw),
            "full_name": full_name,
            "aliases": _split_aliases(raw.get("Alias Type", ""), raw.get("Aliases")),
            "dob": _parse_date(raw.get("DOB")),
            "nationality": raw.get("Nationality"),
            "regime": raw.get("Regime"),
            "listing_date": _parse_date(raw.get("Listed On")),
            "sanctions_type": raw.get("Sanctions Type") or raw.get("Type of sanction"),
            "raw": raw,
        })
    return rows


def _join_names(row: dict) -> str:
    parts = [row.get("Name 6") or row.get("Surname"), row.get("Name 1") or row.get("FirstName"),
             row.get("Name 2"), row.get("Name 3"), row.get("Name 4"), row.get("Name 5")]
    return " ".join(p for p in parts if p).strip() or (row.get("Entity Name") or "").strip()


def _split_aliases(_type: str, val: str | None) -> list[str]:
    if not val:
        return []
    # OFSI separates aliases with semicolons or pipes inconsistently.
    return [a.strip() for a in val.replace("|", ";").split(";") if a.strip()]


def _parse_date(s: str | None):
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _stable_entry_id(row: dict) -> str:
    """OFSI's "Group ID" is the canonical id but isn't always present in the
    CSV export. Hash a stable subset as fallback.
    """
    gid = (row.get("Group ID") or row.get("GroupId") or "").strip()
    if gid:
        return f"OFSI:{gid}"
    seed = "|".join((
        (row.get("Regime") or ""),
        (row.get("Listed On") or ""),
        _join_names(row),
        (row.get("DOB") or ""),
    ))
    return "OFSI:hash-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


async def upsert_all(pool, entries: Iterable[dict]) -> int:
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO uk_sanctions_list (entry_id, full_name, aliases, dob,
                nationality, regime, listing_date, sanctions_type, raw, fetched_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9, NOW())
            ON CONFLICT (entry_id) DO UPDATE SET
                full_name=EXCLUDED.full_name,
                aliases=EXCLUDED.aliases,
                dob=EXCLUDED.dob,
                nationality=EXCLUDED.nationality,
                regime=EXCLUDED.regime,
                listing_date=EXCLUDED.listing_date,
                sanctions_type=EXCLUDED.sanctions_type,
                raw=EXCLUDED.raw,
                fetched_at=NOW()
            """,
            [
                (
                    e["entry_id"], e["full_name"], e["aliases"], e["dob"],
                    e.get("nationality"), e.get("regime"), e.get("listing_date"),
                    e.get("sanctions_type"), json.dumps(e.get("raw") or {}),
                )
                for e in entries
            ],
        )
    return sum(1 for _ in entries)


async def screen_name(pool, name: str, *, threshold: float = 0.6, limit: int = 10) -> list[dict]:
    """Fuzzy-match a single name against the loaded sanctions list using
    pg_trgm similarity. Returns matches above `threshold` ordered by score.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT entry_id, full_name, regime, sanctions_type, listing_date,
                   similarity(full_name, $1) AS score
            FROM uk_sanctions_list
            WHERE full_name % $1
              AND similarity(full_name, $1) >= $2
            ORDER BY score DESC
            LIMIT $3
            """,
            name, threshold, limit,
        )
    return [dict(r) for r in rows]


async def refresh(pool) -> dict:
    """One-shot refresh: download CSV → parse → upsert. Returns counts."""
    csv_text = await fetch_consolidated_csv()
    rows = parse_consolidated_csv(csv_text)
    n = await upsert_all(pool, rows)
    log.info("uk sanctions refresh: %d rows upserted", n)
    return {"rows_upserted": n, "fetched_at": datetime.utcnow().isoformat()}
