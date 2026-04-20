"""Event-driven dirty-tracking for forecast recomputation.

When new ECR rows land (or other upstream changes), mark affected sites dirty
so an external scheduler can re-run their forecast. Pure in-memory; the
scheduler itself lives elsewhere.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Iterable


_LOCK = threading.Lock()
_DIRTY: dict[str, dict] = {}   # site_id → {reason, ts_utc, source}


def mark_dirty(site_id: str, reason: str = "upstream_update",
               source: str = "unknown") -> None:
    if not site_id:
        return
    with _LOCK:
        _DIRTY[site_id] = {
            "reason": reason,
            "source": source,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
        }


def note_ecr_change(gsp_ids: Iterable[str],
                    substation_ids: Iterable[str] | None = None) -> int:
    """Mark every affected GSP / substation dirty. Returns count."""
    n = 0
    for gid in gsp_ids or []:
        mark_dirty(f"gsp:{gid}", reason="ecr_change", source="grid_ingester")
        n += 1
    for sid in substation_ids or []:
        mark_dirty(f"sub:{sid}", reason="ecr_change", source="grid_ingester")
        n += 1
    return n


def dirty_sites() -> list[dict]:
    """Snapshot of currently-dirty sites."""
    with _LOCK:
        return [
            {"site_id": sid, **meta}
            for sid, meta in _DIRTY.items()
        ]


def clear_dirty(site_ids: Iterable[str] | None = None) -> int:
    """Clear dirty flags. No argument → clear all."""
    with _LOCK:
        if site_ids is None:
            n = len(_DIRTY)
            _DIRTY.clear()
            return n
        n = 0
        for sid in site_ids:
            if sid in _DIRTY:
                del _DIRTY[sid]
                n += 1
        return n
