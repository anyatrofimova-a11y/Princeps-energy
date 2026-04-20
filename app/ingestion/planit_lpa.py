"""
app/ingestion/planit_lpa.py — PlanIt API polling for LPA planning apps.

PlanIt (https://www.planit.org.uk/api) aggregates every UK LPA's
planning-application feed. We filter for renewables / BESS / data centre
keywords and upsert one docket per application.

Schedule: every 4h.

Notes:
  * PlanIt returns JSON with a ``records`` array. ``keywords`` is a
    server-side full-text filter.
  * Each record is its own docket (case_type='lpa_planning'), no
    multi-filing fan-out because PlanIt aggregates LPAs that publish very
    differently.
  * Geocoding: PlanIt provides ``latlong`` inline on ~70% of rows; when
    it doesn't, we fall back to ``postcode`` via postcodes.io.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.ingestion.base import IngestionWorker, RawItem

log = logging.getLogger("princeps.ingestion.planit_lpa")

_PLANIT_BASE = "https://www.planit.org.uk/api/applics/json"

# Comma-separated PlanIt `search` keyword sets. Each one is one query;
# dedupe is handled downstream by documents.source_url UNIQUE.
_KEYWORD_SETS = [
    "solar farm",
    "battery storage",
    "grid scale battery",
    "BESS",
    "data centre",
    "data center",
    "hyperscale",
    "grid connection",
    "substation",
    "wind farm",
    "hydrogen electrolyser",
]

# Per call — PlanIt caps at ~500. Keep it modest to stay polite.
_MAX_PER_QUERY = 200


class PlanitLpaWorker(IngestionWorker):
    """Poll PlanIt API → dockets(case_type='lpa_planning') + documents."""

    SOURCE = "planit_lpa"
    req_per_sec = 1.0

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """One search-query call per keyword set; flatten records."""
        out: list[dict[str, Any]] = []
        for kw in _KEYWORD_SETS:
            await self._throttle()
            try:
                r = await client.get(
                    _PLANIT_BASE,
                    params={
                        "search": kw,
                        "pg_sz": _MAX_PER_QUERY,
                        # PlanIt uses `auth_type=F` for full records
                        "auth_type": "F",
                        "sort": "-start_date",
                    },
                    timeout=self.http_timeout_s,
                )
                if r.status_code != 200:
                    log.info("planit: keyword %s returned %s", kw, r.status_code)
                    continue
                payload = r.json() or {}
                records = payload.get("records") or []
                for rec in records:
                    rec["_matched_keyword"] = kw
                out.extend(records)
            except Exception as e:
                log.warning("planit: fetch failed for %s: %s", kw, e)
        log.info("planit: fetched %d records across %d keyword sets",
                 len(out), len(_KEYWORD_SETS))
        return out

    async def parse(self, fetched: list[dict[str, Any]]) -> list[RawItem]:
        if not fetched:
            return []

        async with self.pool.acquire() as conn:
            out: list[RawItem] = []
            seen_urls: set[str] = set()
            for rec in fetched:
                try:
                    item = await self._to_raw_item(conn, rec)
                except Exception as e:
                    log.debug("planit: record parse failed: %s", e)
                    continue
                if item is None or item.source_url in seen_urls:
                    continue
                seen_urls.add(item.source_url)
                out.append(item)
            return out

    async def _to_raw_item(self, conn, rec: dict[str, Any]) -> RawItem | None:
        url = rec.get("url") or rec.get("link") or rec.get("ref_url")
        if not url:
            return None
        ref = rec.get("reference") or rec.get("uid") or rec.get("altid") or ""
        lpa = rec.get("authority_name") or rec.get("authority") or rec.get("area_name") or "LPA"
        desc = rec.get("description") or rec.get("proposal") or ""
        name = rec.get("name") or rec.get("title") or desc[:120] or ref or "Planning application"

        status = rec.get("app_state") or rec.get("status") or rec.get("type") or ""
        start_date = rec.get("start_date") or rec.get("received") or rec.get("date_received")
        decision_date = rec.get("decided_date") or rec.get("decision_date")

        # Geocoding — prefer PlanIt's latlong, then postcode via parent base class
        lat, lon = _split_latlong(rec.get("latlong") or rec.get("location"))
        postcode = rec.get("postcode") or _extract_postcode(rec.get("address", ""))

        # Upsert docket for this planning application
        docket_id = await self._upsert_docket(
            conn,
            ref=ref, name=name, description=desc,
            applicant=rec.get("applicant") or "",
            lpa=lpa, status=status,
            start_date=start_date, decision_date=decision_date,
            lat=lat, lon=lon,
        )

        published = _parse_date(decision_date) or _parse_date(start_date) or datetime.now(timezone.utc)

        return RawItem(
            source_url=url,
            title=f"{lpa}: {name}"[:500],
            body_text=desc or None,
            published_at=published,
            filing_type=_classify_filing_type(rec),
            procedural_stage=_classify_stage(status),
            commission_authority=_norm_lpa(lpa),
            pages=None,
            body_pdf_path=rec.get("docs_url"),
            postcode=postcode,
            lat=lat, lon=lon,
            docket_id=str(docket_id),
            raw={
                "reference": ref,
                "lpa": lpa,
                "status": status,
                "start_date": start_date,
                "decision_date": decision_date,
                "matched_keyword": rec.get("_matched_keyword"),
                "app_size": rec.get("app_size"),
                "app_type": rec.get("app_type"),
            },
        )

    async def _upsert_docket(
        self, conn, *, ref: str, name: str, description: str,
        applicant: str, lpa: str, status: str,
        start_date: Any, decision_date: Any,
        lat: float | None, lon: float | None,
    ) -> Any:
        docket_ref = f"{_norm_lpa(lpa)}/{ref}".strip("/") or name[:80]
        row = await conn.fetchrow(
            """INSERT INTO dockets
                   (source, source_docket_id, title, description, case_type,
                    industry, status, stage, applicant_name, account_name,
                    opened_at, closed_at,
                    geometry)
               VALUES ($1, $2, $3, $4, 'lpa_planning', 'electricity',
                       $5, $6, $7, $8, $9, $10,
                       CASE WHEN $11::double precision IS NOT NULL
                             AND $12::double precision IS NOT NULL
                            THEN ST_SetSRID(ST_MakePoint($12, $11), 4326)::geography
                            ELSE NULL END)
               ON CONFLICT (source, source_docket_id) DO UPDATE
                 SET title = EXCLUDED.title,
                     description = COALESCE(EXCLUDED.description, dockets.description),
                     status = COALESCE(EXCLUDED.status, dockets.status),
                     stage  = COALESCE(EXCLUDED.stage, dockets.stage),
                     closed_at = COALESCE(EXCLUDED.closed_at, dockets.closed_at),
                     geometry = COALESCE(EXCLUDED.geometry, dockets.geometry),
                     updated_at = now()
               RETURNING docket_id""",
            self.SOURCE, docket_ref,
            name[:500], description or None,
            status or None, _classify_stage(status),
            applicant or None, lpa or None,
            _parse_date(start_date) or datetime.now(timezone.utc),
            _parse_date(decision_date),
            lat, lon,
        )
        return row["docket_id"]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _split_latlong(val: Any) -> tuple[float | None, float | None]:
    """PlanIt `latlong` is ``"lat,lon"``; a few LPAs invert the order."""
    if not val:
        return None, None
    try:
        parts = [p.strip() for p in str(val).split(",")]
        if len(parts) != 2:
            return None, None
        a, b = float(parts[0]), float(parts[1])
        # UK lat ~50-60, lon ~-8-2 — detect swapped order
        if abs(a) > 90 and abs(b) <= 90:
            a, b = b, a
        return a, b
    except (ValueError, TypeError):
        return None, None


def _extract_postcode(addr: str) -> str | None:
    import re
    if not addr:
        return None
    m = re.search(
        r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b",
        addr.upper(),
    )
    return m.group(1) if m else None


def _classify_stage(status: str) -> str | None:
    s = (status or "").lower()
    if not s:
        return None
    if "pending" in s or "under consideration" in s or "registered" in s:
        return "pre_app"
    if "granted" in s or "approved" in s or "permitted" in s:
        return "decision"
    if "refused" in s or "rejected" in s:
        return "decision"
    if "withdrawn" in s:
        return "withdrawn"
    if "appeal" in s:
        return "challenge"
    return None


def _classify_filing_type(rec: dict[str, Any]) -> str:
    t = (rec.get("app_type") or "").lower()
    if "full" in t:
        return "full_application"
    if "outline" in t:
        return "outline_application"
    if "reserved" in t:
        return "reserved_matters"
    if "discharge" in t:
        return "discharge_of_conditions"
    if "appeal" in t:
        return "appeal"
    return "planning_application"


def _norm_lpa(lpa: str | None) -> str:
    if not lpa:
        return "lpa"
    import re
    return re.sub(r"[^a-z0-9]+", "-", lpa.strip().lower()).strip("-")[:40]


def _parse_date(val: Any) -> datetime | None:
    if not val:
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                "%d/%m/%Y", "%d %B %Y", "%d %b %Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def run_once(pool):
    """Convenience entry point for APScheduler + manual CLI invocation."""
    worker = PlanitLpaWorker(pool)
    return await worker.run()
