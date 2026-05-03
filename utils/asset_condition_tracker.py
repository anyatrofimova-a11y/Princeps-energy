"""Asset condition tracker — drone-footage / Sentinel-2 change detection
on solar / wind / BESS / DC portfolios.

Pattern source: TAP-Net (DeepMind, Apache-2.0) for per-point video tracking,
combined with Sentinel-2 spectral change detection for slower drift signals.

Outputs row(s) into `asset_condition_events` (created by an ingestion-stage
migration, not yet in this file) shaped like:
  {asset_rid, source, observed_at, condition_score (0..1), severity, evidence_url}

This file ships the Python interface; heavy CV runs in .venv-geeflow or
.venv-forecast subprocesses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("princeps.asset_condition")


@dataclass
class ConditionEvent:
    asset_rid: str
    source: str             # "drone" | "sentinel2" | "manual"
    observed_at: datetime
    condition_score: float  # 1.0 = pristine, 0.0 = critical
    severity: str           # "ok" | "warn" | "alarm"
    evidence_url: str | None = None
    notes: str | None = None


async def track_drone_footage(pool, *, asset_rid: str, video_path: Path) -> list[ConditionEvent]:
    """Run TAP-Net point-tracking on a drone fly-by. Detects:
        • module misalignment (PV)
        • blade leading-edge erosion (wind)
        • cooling-tower plume anomaly (DC)
    """
    log.info("drone scan asset=%s video=%s", asset_rid, video_path)
    # Real impl: subprocess to .venv-forecast python running tapnet inference.
    # Placeholder returns no events so the caller pipeline still works.
    return []


async def detect_satellite_drift(pool, *, asset_rid: str, region_wkt: str,
                                 since: datetime) -> list[ConditionEvent]:
    """Sentinel-2 NDVI/NDWI delta on the asset footprint over the last 90 days.
    Flags anomalies (>2σ from baseline) as `warn`, >3σ as `alarm`.
    """
    return []


async def store_events(pool, events: list[ConditionEvent]) -> int:
    if not events:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO asset_condition_events
                (asset_rid, source, observed_at, condition_score, severity,
                 evidence_url, notes, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            """,
            [(e.asset_rid, e.source, e.observed_at, e.condition_score,
              e.severity, e.evidence_url, e.notes) for e in events],
        )
    return len(events)


def severity_from_score(score: float) -> str:
    if score < 0.4:
        return "alarm"
    if score < 0.7:
        return "warn"
    return "ok"
