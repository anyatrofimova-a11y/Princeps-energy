"""
Grid data provenance helpers.

Every grid analysis result must carry an honest provenance block so the
frontend can tell users whether the numbers came from a live NESO/DNO feed,
a cached DB snapshot, OSM, or a synthetic fallback.

No silent substitutions: if the NESO call fails we still return a 200 result
but with provenance="synthetic_fallback" and a human-readable reason.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Source identifiers used across the grid modules.
SRC_NESO_LIVE = "neso_live"
SRC_DNO_ODS = "dno_opendatasoft"
SRC_DNO_CKAN = "dno_ckan"
SRC_DB_SNAPSHOT = "db_snapshot"
SRC_OSM = "osm"
SRC_SYNTHETIC = "synthetic_fallback"
SRC_MIXED = "mixed"

VALID_SOURCES = {
    SRC_NESO_LIVE, SRC_DNO_ODS, SRC_DNO_CKAN, SRC_DB_SNAPSHOT,
    SRC_OSM, SRC_SYNTHETIC, SRC_MIXED,
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_provenance(
    source: str,
    last_refreshed_utc: datetime | None = None,
    reason: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build a provenance block.

    source             — one of VALID_SOURCES.
    last_refreshed_utc — when the underlying data was last refreshed.
                         Falls back to now() if unknown; stale_days is then 0.
    reason             — mandatory if source == synthetic_fallback; explains
                         why the live feed could not be used.
    extra              — extra audit fields (dno, dataset, etc.) merged in.
    """
    if source not in VALID_SOURCES:
        source = SRC_SYNTHETIC
        reason = (reason or "") + f" (unknown source coerced to synthetic_fallback)"

    refreshed = last_refreshed_utc or _now_utc()
    if refreshed.tzinfo is None:
        refreshed = refreshed.replace(tzinfo=timezone.utc)
    stale_days = max(0, (_now_utc() - refreshed).days)

    block: dict[str, Any] = {
        "data_provenance": source,
        "last_refreshed_utc": _iso(refreshed),
        "stale_days": stale_days,
    }
    if reason:
        block["reason"] = reason
    if source == SRC_SYNTHETIC and "reason" not in block:
        block["reason"] = "live feed unavailable; falling back to synthetic defaults"
    if extra:
        block["audit"] = extra
    return block


def combine_provenance(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Combine several provenance blocks into a single summary.

    If any input is synthetic the combined source is synthetic_fallback
    (caller decides whether that is acceptable). Otherwise returns the
    oldest last_refreshed_utc and the shared source, or 'mixed'.
    """
    if not blocks:
        return make_provenance(SRC_SYNTHETIC, reason="no upstream provenance supplied")

    sources = {b.get("data_provenance") for b in blocks}
    reasons = [b.get("reason") for b in blocks if b.get("reason")]

    if SRC_SYNTHETIC in sources:
        combined = SRC_SYNTHETIC
    elif len(sources) == 1:
        combined = next(iter(sources))
    else:
        combined = SRC_MIXED

    # Oldest refresh dominates staleness.
    refreshes: list[datetime] = []
    for b in blocks:
        iso = b.get("last_refreshed_utc")
        if not iso:
            continue
        try:
            refreshes.append(datetime.fromisoformat(iso.replace("Z", "+00:00")))
        except Exception:
            continue
    oldest = min(refreshes) if refreshes else None

    reason = "; ".join(r for r in reasons if r) or None
    return make_provenance(combined, oldest, reason=reason)
