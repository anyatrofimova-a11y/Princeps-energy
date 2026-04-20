"""
app/ingestion/base.py — shared base class for Intelligence ingestion workers.

Lifecycle for every worker::

    fetch()   →   parse()   →   classify()   →   extract()
                                                   ↓
                               geocode()   →   embed()   →   dedupe()
                                                                ↓
                                                            write()

Subclasses override :meth:`fetch` and :meth:`parse`; everything downstream
has a sensible default. Each worker also writes one row per run to
``intelligence_ingestion_log``.

The DB shape is ``documents`` (and optionally ``dockets``) from
``app/migrations/0001_intelligence_schema.sql``. Upserts always key on
``documents.source_url`` which has a UNIQUE constraint.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx

from app.ingestion.classifier import classify_document
from app.ingestion.dedupe import minhash_signature, is_near_duplicate
from app.ingestion.embeddings import embed_text
from app.ingestion.ner import extract_fields
from app.ingestion.claude import get_claude_client

log = logging.getLogger("princeps.ingestion.base")


# ── Rate-limit defaults (can be overridden per worker) ───────────────────────
_DEFAULT_REQ_PER_SEC = 1.0
_DEFAULT_HTTP_TIMEOUT_S = 60


# ── Result / context ─────────────────────────────────────────────────────────

@dataclass
class IngestionResult:
    """Summary of a single ingestion run — persisted to intelligence_ingestion_log."""

    source: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str = "running"   # running | ok | partial | failed
    rows_fetched: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_failed: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_gbp: float = 0.0
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawItem:
    """
    Item returned by :meth:`IngestionWorker.parse` — the minimum shape the
    downstream stages understand. Workers are free to pass extra keys via
    ``raw``; they end up in ``documents.extracted_fields``.
    """

    source_url: str
    title: str
    body_text: str | None = None
    published_at: datetime | None = None
    filing_type: str | None = None
    procedural_stage: str | None = None
    commission_authority: str | None = None
    pages: int | None = None
    body_pdf_path: str | None = None
    postcode: str | None = None          # if present, geocode() will set geometry
    lat: float | None = None             # explicit lat/lon override postcode
    lon: float | None = None
    docket_id: str | None = None         # uuid string; link to existing docket if known
    raw: dict[str, Any] = field(default_factory=dict)


# ── Postcode geocoder (postcodes.io) ─────────────────────────────────────────

_POSTCODES_IO = "https://api.postcodes.io/postcodes"


async def geocode_postcode(
    client: httpx.AsyncClient, postcode: str
) -> tuple[float, float] | None:
    """Return (lat, lon) via postcodes.io or ``None`` on failure."""
    pc = postcode.strip().replace(" ", "").upper()
    if not pc:
        return None
    try:
        r = await client.get(f"{_POSTCODES_IO}/{pc}", timeout=10)
        if r.status_code != 200:
            return None
        data = r.json().get("result") or {}
        lat, lon = data.get("latitude"), data.get("longitude")
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)
    except Exception:
        return None


# ── Shared worker ────────────────────────────────────────────────────────────

class IngestionWorker:
    """
    Base class for all Princeps Intelligence workers.

    Subclasses must set ``SOURCE`` (slug, used in ``documents.source``) and
    implement :meth:`fetch` and :meth:`parse`. The remaining stages are
    override points — ``classify``, ``extract``, ``geocode``, ``embed``,
    ``dedupe``, ``write`` — with defaults that handle the common case.

    Example::

        class OfgemWorker(IngestionWorker):
            SOURCE = "ofgem"
            async def fetch(self): ...
            async def parse(self, fetched): ...
    """

    SOURCE: str = "base"

    # Rate limits (can be overridden per-source)
    req_per_sec: float = _DEFAULT_REQ_PER_SEC
    http_timeout_s: int = _DEFAULT_HTTP_TIMEOUT_S

    # If True, worker calls the embedder inline. Set False for large batch
    # jobs where the nightly embed pass is preferred.
    embed_inline: bool = False

    # Whether to call the classifier/extractor inline. Cheap Haiku classifier
    # is safe inline; disable only if a nightly re-classify job is wired up.
    classify_inline: bool = True
    extract_inline: bool = True

    # Allow a daily-budget style override to short-circuit expensive LLM
    # stages if you want to dry-run a worker.
    llm_enabled: bool = True

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self._last_req_at = 0.0
        self._claude = None   # lazy

    # ── Rate-limit helper used by subclasses ─────────────────────────────────

    async def _throttle(self) -> None:
        """Enforce ``self.req_per_sec`` between successive outbound requests."""
        if self.req_per_sec <= 0:
            return
        min_gap = 1.0 / self.req_per_sec
        now = time.time()
        elapsed = now - self._last_req_at
        if elapsed < min_gap:
            await asyncio.sleep(min_gap - elapsed)
        self._last_req_at = time.time()

    # ── Lifecycle stages ─────────────────────────────────────────────────────

    async def fetch(self, client: httpx.AsyncClient) -> Any:
        """Fetch raw upstream payload(s). Returns whatever parse() expects."""
        raise NotImplementedError

    async def parse(self, fetched: Any) -> list[RawItem]:
        """Convert fetched payload(s) into a list of :class:`RawItem`."""
        raise NotImplementedError

    async def classify(self, item: RawItem) -> list[str]:
        """Return topic tags — regex-first with LLM fallback."""
        if not self.classify_inline:
            return []
        text = f"{item.title}\n\n{item.body_text or ''}"
        return await classify_document(
            text=text,
            claude=self._get_claude() if self.llm_enabled else None,
            source=self.SOURCE,
        )

    async def extract(self, item: RawItem) -> dict[str, Any]:
        """
        NER: counterparty, capacity_mw, poc_substation, capex_gbp, commissioning_date.
        Regex-first with LLM fallback for messy text.
        """
        if not self.extract_inline:
            return {}
        text = f"{item.title}\n\n{item.body_text or ''}"
        return await extract_fields(
            text=text,
            claude=self._get_claude() if self.llm_enabled else None,
        )

    async def geocode(
        self, item: RawItem, client: httpx.AsyncClient
    ) -> tuple[float, float] | None:
        """Resolve item → (lat, lon). Uses explicit lat/lon first, then postcode."""
        if item.lat is not None and item.lon is not None:
            return float(item.lat), float(item.lon)
        if item.postcode:
            return await geocode_postcode(client, item.postcode)
        return None

    async def embed(self, item: RawItem) -> list[float] | None:
        """Compute a 1536-dim embedding. Inline if ``embed_inline`` else None."""
        if not self.embed_inline or not self.llm_enabled:
            return None
        text = (item.title or "") + "\n\n" + (item.body_text or "")
        if not text.strip():
            return None
        return await embed_text(text[:8000])

    async def dedupe(
        self, item: RawItem, conn: asyncpg.Connection
    ) -> bool:
        """
        Return True if this item appears to be a duplicate of an earlier
        document already in the DB. Uses MinHash on title + body_text prefix.
        """
        text = (item.title or "") + " " + (item.body_text or "")[:4000]
        if not text.strip():
            return False
        sig = minhash_signature(text)
        # Coarse prefilter by source + published_at window
        rows = await conn.fetch(
            """
            SELECT doc_id, title, coalesce(body_text,'') AS body_text
              FROM documents
             WHERE source = $1
               AND ($2::timestamptz IS NULL OR
                    published_at BETWEEN $2::timestamptz - INTERVAL '7 days'
                                     AND $2::timestamptz + INTERVAL '7 days')
             LIMIT 200
            """,
            self.SOURCE,
            item.published_at,
        )
        for r in rows:
            other = (r["title"] or "") + " " + (r["body_text"] or "")[:4000]
            if is_near_duplicate(sig, minhash_signature(other)):
                return True
        return False

    async def write(
        self,
        item: RawItem,
        topic_tags: list[str],
        extracted: dict[str, Any],
        geom_lat_lon: tuple[float, float] | None,
        embedding: list[float] | None,
        conn: asyncpg.Connection,
    ) -> tuple[bool, bool]:
        """
        Upsert the item into ``documents``.

        Returns ``(inserted, updated)`` — exactly one is True on success.
        Uses ON CONFLICT (source_url) DO UPDATE so re-ingestion is safe.
        """
        extracted_fields = {**(item.raw or {}), **(extracted or {})}

        lat, lon = (None, None)
        if geom_lat_lon:
            lat, lon = geom_lat_lon

        row = await conn.fetchrow(
            """
            INSERT INTO documents (
                source, source_url, docket_id, commission_authority,
                filing_type, procedural_stage, title, body_text,
                body_pdf_path, pages, published_at,
                topic_tags, extracted_fields, embedding,
                geometry
            )
            VALUES (
                $1, $2, $3, $4,
                $5, $6, $7, $8,
                $9, $10, $11,
                $12::jsonb, $13::jsonb, $14,
                CASE
                  WHEN $15::double precision IS NOT NULL
                   AND $16::double precision IS NOT NULL
                  THEN ST_SetSRID(ST_MakePoint($16, $15), 4326)::geography
                  ELSE NULL
                END
            )
            ON CONFLICT (source_url) DO UPDATE SET
                docket_id            = COALESCE(EXCLUDED.docket_id, documents.docket_id),
                commission_authority = COALESCE(EXCLUDED.commission_authority, documents.commission_authority),
                filing_type          = COALESCE(EXCLUDED.filing_type, documents.filing_type),
                procedural_stage     = COALESCE(EXCLUDED.procedural_stage, documents.procedural_stage),
                title                = EXCLUDED.title,
                body_text            = COALESCE(EXCLUDED.body_text, documents.body_text),
                body_pdf_path        = COALESCE(EXCLUDED.body_pdf_path, documents.body_pdf_path),
                pages                = COALESCE(EXCLUDED.pages, documents.pages),
                published_at         = COALESCE(EXCLUDED.published_at, documents.published_at),
                topic_tags           = EXCLUDED.topic_tags,
                extracted_fields     = EXCLUDED.extracted_fields,
                embedding            = COALESCE(EXCLUDED.embedding, documents.embedding),
                geometry             = COALESCE(EXCLUDED.geometry, documents.geometry)
            RETURNING (xmax = 0) AS inserted
            """,
            self.SOURCE,
            item.source_url,
            _uuid_or_none(item.docket_id),
            item.commission_authority,
            item.filing_type,
            item.procedural_stage,
            item.title,
            item.body_text,
            item.body_pdf_path,
            item.pages,
            item.published_at,
            json.dumps(topic_tags or []),
            json.dumps(extracted_fields or {}, default=str),
            embedding,
            lat,
            lon,
        )
        inserted = bool(row and row["inserted"])
        return (inserted, not inserted)

    # ── Orchestration ────────────────────────────────────────────────────────

    async def run(self, run_id: str | None = None) -> IngestionResult:
        """
        Full end-to-end pipeline. Safe to call directly or from the
        APScheduler-triggered cron job in :mod:`app.ingestion.scheduler`.
        """
        started = datetime.now(timezone.utc)
        result = IngestionResult(source=self.SOURCE, started_at=started)

        # Open a run row up front so monitoring can see "running" state.
        log_id = await self._log_start(run_id=run_id, started=started)

        try:
            async with httpx.AsyncClient(
                timeout=self.http_timeout_s,
                follow_redirects=True,
                headers={"User-Agent": "Princeps-Intelligence/1.0 (contact: ops@princeps.energy)"},
            ) as client:
                fetched = await self.fetch(client)
                items = await self.parse(fetched)
                result.rows_fetched = len(items)

                async with self.pool.acquire() as conn:
                    for item in items:
                        try:
                            if await self.dedupe(item, conn):
                                log.info("%s: skipped near-duplicate %s",
                                         self.SOURCE, item.source_url)
                                continue
                            tags = await self.classify(item)
                            extracted = await self.extract(item)
                            loc = await self.geocode(item, client)
                            embedding = await self.embed(item)
                            inserted, updated = await self.write(
                                item, tags, extracted, loc, embedding, conn
                            )
                            if inserted:
                                result.rows_inserted += 1
                            elif updated:
                                result.rows_updated += 1
                        except Exception as e:
                            log.exception(
                                "%s: write failed for %s: %s",
                                self.SOURCE, item.source_url, e,
                            )
                            result.rows_failed += 1

            result.status = "ok" if result.rows_failed == 0 else "partial"

        except Exception as e:
            log.exception("%s: worker failed: %s", self.SOURCE, e)
            result.status = "failed"
            result.error_message = str(e)[:2000]

        result.finished_at = datetime.now(timezone.utc)
        await self._log_finish(log_id, result)
        self._log_cost(result)
        return result

    # ── Internal helpers ────────────────────────────────────────────────────

    def _get_claude(self):
        if self._claude is None:
            self._claude = get_claude_client()
        return self._claude

    async def _log_start(self, *, run_id: str | None, started: datetime) -> int:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO intelligence_ingestion_log
                        (source, run_id, started_at, status)
                    VALUES ($1, $2, $3, 'running')
                    RETURNING id
                    """,
                    self.SOURCE, run_id, started,
                )
            return int(row["id"]) if row else 0
        except Exception as e:
            log.warning("ingestion_log insert failed for %s: %s", self.SOURCE, e)
            return 0

    async def _log_finish(self, log_id: int, result: IngestionResult) -> None:
        if not log_id:
            return
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE intelligence_ingestion_log
                       SET finished_at   = $2,
                           status        = $3,
                           rows_fetched  = $4,
                           rows_inserted = $5,
                           rows_updated  = $6,
                           rows_failed   = $7,
                           tokens_in     = $8,
                           tokens_out    = $9,
                           cost_gbp      = $10,
                           error_message = $11,
                           metadata      = $12::jsonb
                     WHERE id = $1
                    """,
                    log_id,
                    result.finished_at,
                    result.status,
                    result.rows_fetched,
                    result.rows_inserted,
                    result.rows_updated,
                    result.rows_failed,
                    result.tokens_in,
                    result.tokens_out,
                    result.cost_gbp,
                    result.error_message,
                    json.dumps(result.metadata or {}, default=str),
                )
        except Exception as e:
            log.warning("ingestion_log update failed for %s: %s", self.SOURCE, e)

    def _log_cost(self, result: IngestionResult) -> None:
        log.info(
            "ingestion %s: status=%s fetched=%d inserted=%d updated=%d failed=%d "
            "tokens_in=%d tokens_out=%d cost_gbp=%.4f",
            self.SOURCE, result.status, result.rows_fetched,
            result.rows_inserted, result.rows_updated, result.rows_failed,
            result.tokens_in, result.tokens_out, result.cost_gbp,
        )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _uuid_or_none(val: str | None):
    if not val:
        return None
    try:
        from uuid import UUID
        return UUID(val)
    except Exception:
        return None


def stable_source_url(source: str, key: str) -> str:
    """
    For sources that don't publish a stable URL per item, derive a
    deterministic synthetic one. Keeps the UNIQUE(source_url) constraint
    honest while still allowing ON CONFLICT re-runs.
    """
    h = hashlib.sha1(f"{source}:{key}".encode()).hexdigest()[:16]
    return f"princeps://{source}/{h}"
