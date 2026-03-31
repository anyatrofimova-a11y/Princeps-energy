"""
Council meeting transcript search for UK energy planning intelligence.

Wraps the CouncilSearcher (bellingcat) provider logic to fetch, index, and
search UK council meeting transcripts for energy-related discussions.

Uses a separate SQLite database with FTS5 for full-text search.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = PROJECT_ROOT / "vendor" / "council-searcher"
DB_DIR = PROJECT_ROOT / "data"
DB_PATH = DB_DIR / "council_meetings.db"

# Ensure vendor code is importable
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

# ── Default energy search terms ────────────────────────────────────────────────
ENERGY_TERMS = [
    "solar farm",
    "wind farm",
    "battery storage",
    "substation",
    "planning application",
    "renewable energy",
    "grid connection",
    "environmental impact",
    "solar panels",
    "wind turbine",
    "energy storage",
    "power station",
    "national grid",
    "electricity generation",
    "net zero",
    "carbon neutral",
    "EV charging",
    "heat pump",
    "green energy",
    "photovoltaic",
]

# ── Well-known UK authorities on public-i ──────────────────────────────────────
# Subset of authorities known to use the public-i platform for webcasting.
# Users can add more via refresh_index(authorities=[...]).
DEFAULT_AUTHORITIES = [
    "norfolk",
    "suffolk",
    "cambridgeshire",
    "lincolnshire",
    "essex",
    "hertfordshire",
    "kent",
    "surrey",
    "hampshire",
    "devon",
    "somerset",
    "dorset",
    "wiltshire",
    "oxfordshire",
    "warwickshire",
    "northamptonshire",
    "nottinghamshire",
    "derbyshire",
    "staffordshire",
    "cornwall",
]


# ── Database setup ─────────────────────────────────────────────────────────────

def _ensure_db() -> sqlite3.Connection:
    """Create database and tables if they don't exist. Return connection."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS providers (
            id TEXT PRIMARY KEY,
            config TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS authorities (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT 'publici',
            nice_name TEXT,
            meeting_count INTEGER DEFAULT 0,
            transcript_count INTEGER DEFAULT 0,
            last_refreshed TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meetings (
            uid TEXT PRIMARY KEY,
            authority TEXT,
            title TEXT,
            description TEXT,
            datetime TEXT,
            unixtime INTEGER,
            link TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transcripts (
            uid TEXT,
            transcript TEXT,
            title TEXT,
            description TEXT,
            start_time TEXT,
            end_time TEXT,
            PRIMARY KEY (uid, start_time, end_time)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agenda (
            uid TEXT,
            agenda_id TEXT,
            agenda_text TEXT,
            agenda_time TEXT,
            PRIMARY KEY (uid, agenda_id)
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
            uid,
            transcript,
            tokenize='porter'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS offsets (
            uid TEXT,
            offset INTEGER,
            start_time TEXT,
            start_time_seconds INTEGER,
            PRIMARY KEY (uid, offset)
        )
    """)
    conn.commit()
    return conn


# ── Query sanitisation (from CouncilSearcher) ──────────────────────────────────

_clean_query = re.compile(r'[^a-zA-Z0-9"]')

def _sanitize_query(query: str) -> str:
    text = _clean_query.sub(" ", query)
    if text.count('"') % 2 == 1:
        text = text.replace('"', "")
    return text.strip()


# ── Search ─────────────────────────────────────────────────────────────────────

def search_planning_mentions(
    query: str,
    authorities: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Search council meeting transcripts for energy/planning mentions.

    Args:
        query: FTS5 search query (e.g. "solar farm")
        authorities: optional list of authority IDs to filter
        date_from: ISO date string (YYYY-MM-DD) lower bound
        date_to: ISO date string (YYYY-MM-DD) upper bound
        limit: max results to return
        offset: pagination offset

    Returns:
        dict with 'results' list and 'total' count, each result containing:
        - uid, title, authority, datetime, snippet, start_time, link, rank
    """
    conn = _ensure_db()
    try:
        sanitized = _sanitize_query(query)
        if not sanitized:
            return {"results": [], "total": 0, "query": query}

        params: list = [sanitized]

        count_sql = """
            SELECT COUNT(*)
            FROM transcripts_fts
            WHERE transcript MATCH ?
        """
        query_sql = """
            SELECT uid, snippet(transcripts_fts, 1, '<mark>', '</mark>', '', 70) AS snippet,
                   rank, transcript
            FROM transcripts_fts
            WHERE transcript MATCH ?
        """

        # Authority filter
        if authorities:
            placeholders = ",".join("?" for _ in authorities)
            auth_filter = f"""
                AND uid IN (
                    SELECT uid FROM meetings WHERE authority IN ({placeholders})
                )
            """
            query_sql += auth_filter
            count_sql += auth_filter
            params.extend(authorities)

        # Date filters
        if date_from:
            date_filter = """
                AND uid IN (
                    SELECT uid FROM meetings WHERE datetime >= ?
                )
            """
            query_sql += date_filter
            count_sql += date_filter
            params.append(date_from)

        if date_to:
            date_filter = """
                AND uid IN (
                    SELECT uid FROM meetings WHERE datetime <= ?
                )
            """
            query_sql += date_filter
            count_sql += date_filter
            params.append(date_to)

        # Ordering and pagination
        query_sql += " ORDER BY bm25(transcripts_fts)"
        query_sql += " LIMIT ? OFFSET ?"
        query_params = params + [limit, offset]

        total = conn.execute(count_sql, params).fetchone()[0]
        results = conn.execute(query_sql, query_params).fetchall()

        # Resolve timestamps for video links
        formatted = []
        for uid, snippet, rank, transcript in results:
            snippet_cleaned = snippet.replace("<mark>", "").replace("</mark>", "")
            offset_val = transcript.find(snippet_cleaned)

            row = conn.execute("""
                SELECT o.start_time, o.start_time_seconds,
                       m.title, m.datetime, m.unixtime, m.link, m.authority
                FROM offsets o
                JOIN meetings m ON o.uid = m.uid
                WHERE o.uid = ? AND o.offset <= ?
                ORDER BY o.offset DESC
                LIMIT 1
            """, (uid, offset_val)).fetchone()

            if row:
                start_time, start_secs, title, dt, unixtime, link, authority = row
                meeting_link = f"{link}/start_time/{int(1000 * start_secs)}" if link and start_secs else link
                formatted.append({
                    "uid": uid,
                    "title": title,
                    "authority": authority,
                    "datetime": dt,
                    "unixtime": unixtime,
                    "snippet": snippet,
                    "start_time": start_time,
                    "rank": rank,
                    "link": meeting_link,
                })

        return {"results": formatted, "total": total, "query": query}
    finally:
        conn.close()


def get_authorities() -> list[dict[str, Any]]:
    """List all indexed authorities with meeting/transcript counts."""
    conn = _ensure_db()
    try:
        rows = conn.execute("""
            SELECT id, nice_name, meeting_count, transcript_count, last_refreshed
            FROM authorities
            ORDER BY id ASC
        """).fetchall()
        return [
            {
                "id": r[0],
                "name": r[1] or r[0].replace("_", " ").title(),
                "meeting_count": r[2] or 0,
                "transcript_count": r[3] or 0,
                "last_refreshed": r[4],
            }
            for r in rows
        ]
    finally:
        conn.close()


def refresh_index(authorities: list[str] | None = None) -> dict[str, Any]:
    """
    Refresh the council meeting index for specified authorities.

    Fetches meeting data from public-i platform, downloads transcripts,
    and indexes them in the local SQLite FTS5 database.

    Args:
        authorities: list of authority IDs (e.g. ["norfolk", "suffolk"]).
                     Defaults to DEFAULT_AUTHORITIES if None.

    Returns:
        Summary dict with counts of meetings and transcripts indexed.
    """
    target_authorities = authorities or DEFAULT_AUTHORITIES[:5]  # Start with top 5 to avoid overload

    conn = _ensure_db()
    summary = {"authorities_processed": 0, "meetings_indexed": 0, "transcripts_indexed": 0, "errors": []}

    try:
        from api.providers.publici import PublicI
        from api.db.meetings import add_meetings_to_db as _upstream_add
    except ImportError as e:
        log.warning("CouncilSearcher vendor code not available: %s", e)
        summary["errors"].append(f"Import error: {e}")
        return summary

    for auth_id in target_authorities:
        try:
            log.info("Refreshing council index for: %s", auth_id)

            # Ensure authority record exists
            conn.execute(
                "INSERT OR IGNORE INTO authorities (id, provider) VALUES (?, 'publici')",
                (auth_id,),
            )
            conn.commit()

            # Build index via PublicI provider
            provider = PublicI(authority=auth_id)
            index = provider.build_index()
            if not index:
                log.info("No meetings found for %s", auth_id)
                continue

            # Fetch transcripts
            meetings = provider.get_meetings(index)

            # Store in our local DB
            _store_meetings(conn, auth_id, meetings)

            meeting_count = len(meetings)
            transcript_count = sum(1 for m in meetings if m.get("parsed_transcript"))

            # Update authority stats
            conn.execute("""
                UPDATE authorities
                SET meeting_count = ?,
                    transcript_count = ?,
                    last_refreshed = ?
                WHERE id = ?
            """, (meeting_count, transcript_count, datetime.utcnow().isoformat(), auth_id))
            conn.commit()

            summary["authorities_processed"] += 1
            summary["meetings_indexed"] += meeting_count
            summary["transcripts_indexed"] += transcript_count
            log.info("Indexed %d meetings (%d with transcripts) for %s",
                     meeting_count, transcript_count, auth_id)

        except Exception as e:
            log.warning("Failed to refresh %s: %s", auth_id, e)
            summary["errors"].append(f"{auth_id}: {e}")

    conn.close()
    return summary


def _store_meetings(conn: sqlite3.Connection, authority: str, meetings: list[dict]) -> None:
    """Store meetings and transcripts in the local SQLite DB."""
    for item in meetings:
        uid = item.get("uid", "")
        if not uid:
            continue

        conn.execute("""
            INSERT OR IGNORE INTO meetings (uid, authority, title, description, datetime, unixtime, link)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            uid, authority, item.get("title"), item.get("description"),
            item.get("datetime"), item.get("unixtime"), item.get("link"),
        ))

        parsed = item.get("parsed_transcript")
        if parsed:
            for start_time, end_time, text in parsed:
                conn.execute("""
                    INSERT OR IGNORE INTO transcripts (uid, transcript, title, description, start_time, end_time)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (uid, text, item.get("title"), item.get("description"), start_time, end_time))

            # FTS index — full concatenated transcript
            full_transcript = " ".join(text for _, _, text in parsed)
            existing = conn.execute(
                "SELECT 1 FROM transcripts_fts WHERE uid = ?", (uid,)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO transcripts_fts (uid, transcript) VALUES (?, ?)",
                    (uid, full_transcript),
                )

            # Offset table for timestamp lookups
            offset = 0
            for start_time, end_time, text in parsed:
                start_secs = sum(
                    float(x) * 60 ** i
                    for i, x in enumerate(reversed(start_time.split(":")))
                ) // 1
                conn.execute("""
                    INSERT OR IGNORE INTO offsets (uid, offset, start_time, start_time_seconds)
                    VALUES (?, ?, ?, ?)
                """, (uid, offset, start_time, int(start_secs)))
                offset += len(text) + 1

        if item.get("agenda"):
            for agenda_item in item["agenda"]:
                conn.execute("""
                    INSERT OR IGNORE INTO agenda (uid, agenda_id, agenda_text, agenda_time)
                    VALUES (?, ?, ?, ?)
                """, (
                    uid,
                    agenda_item.get("id"),
                    agenda_item.get("text"),
                    agenda_item.get("time"),
                ))

    conn.commit()


def energy_summary(limit_per_term: int = 5) -> dict[str, Any]:
    """
    Pre-built summary of recent energy-related council discussions.

    Searches across all default energy terms and aggregates results
    into a summary with term-level breakdown.
    """
    conn = _ensure_db()
    try:
        summary_terms = []
        total_mentions = 0
        all_results = []
        seen_uids = set()

        for term in ENERGY_TERMS[:12]:  # Top 12 terms to keep response reasonable
            sanitized = _sanitize_query(term)
            if not sanitized:
                continue

            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM transcripts_fts WHERE transcript MATCH ?",
                    (sanitized,),
                ).fetchone()[0]
            except sqlite3.OperationalError:
                count = 0

            if count > 0:
                summary_terms.append({"term": term, "count": count})
                total_mentions += count

                # Get top results for this term
                try:
                    rows = conn.execute("""
                        SELECT tf.uid,
                               snippet(transcripts_fts, 1, '<mark>', '</mark>', '', 50) AS snippet,
                               m.title, m.datetime, m.authority
                        FROM transcripts_fts tf
                        JOIN meetings m ON tf.uid = m.uid
                        WHERE tf.transcript MATCH ?
                        ORDER BY m.unixtime DESC
                        LIMIT ?
                    """, (sanitized, limit_per_term)).fetchall()
                except sqlite3.OperationalError:
                    rows = []

                for uid, snippet, title, dt, authority in rows:
                    if uid not in seen_uids:
                        seen_uids.add(uid)
                        all_results.append({
                            "uid": uid,
                            "title": title,
                            "authority": authority,
                            "datetime": dt,
                            "snippet": snippet,
                            "matched_term": term,
                        })

        # Sort all results by datetime descending
        all_results.sort(key=lambda r: r.get("datetime") or "", reverse=True)

        authorities = get_authorities()
        return {
            "total_energy_mentions": total_mentions,
            "terms": sorted(summary_terms, key=lambda t: t["count"], reverse=True),
            "recent_discussions": all_results[:30],
            "authorities_indexed": len(authorities),
            "authorities": authorities,
        }
    finally:
        conn.close()


def search_for_agent(query: str, authorities: list[str] | None = None) -> str:
    """
    Convenience function for the agent system. Returns a compact text summary
    of search results suitable for injection into Claude context.
    """
    result = search_planning_mentions(query, authorities=authorities, limit=10)
    if not result["results"]:
        return f"No council meeting mentions found for '{query}'."

    lines = [f"Found {result['total']} council meeting mentions for '{query}':"]
    for r in result["results"]:
        auth = (r.get("authority") or "unknown").replace("_", " ").title()
        dt = r.get("datetime", "")[:10]
        snippet = r.get("snippet", "").replace("<mark>", "**").replace("</mark>", "**")
        lines.append(f"  - [{auth}] {r.get('title', 'Untitled')} ({dt}): {snippet}")
    return "\n".join(lines)
