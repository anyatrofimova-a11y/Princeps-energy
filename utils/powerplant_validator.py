"""powerplantmatching cross-validation for REPD.

Goal: fetch the international powerplantmatching dataset, filter to UK,
fuzzy-match against ``repd_projects`` to flag rows where REPD reports a
different capacity than the consensus of GEM/JRC/OPSD.

Public surface:
  ``fetch_uk_powerplants(refresh=False) -> pd.DataFrame``
  ``cross_validate_repd(pool, fuzz_threshold=85) -> dict``
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import asyncpg

log = logging.getLogger(__name__)

_CACHE_PATH = "/app/cache/pm_uk_powerplants.parquet"


def fetch_uk_powerplants(refresh: bool = False):
    """Return the UK-filtered powerplantmatching matched dataset."""
    import pandas as pd
    if not refresh and os.path.exists(_CACHE_PATH):
        return pd.read_parquet(_CACHE_PATH)
    import powerplantmatching as pm
    df = pm.powerplants(update=refresh)
    uk = df[df["Country"] == "United Kingdom"].copy()
    os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
    uk.to_parquet(_CACHE_PATH)
    return uk


async def cross_validate_repd(
    pool: asyncpg.Pool,
    fuzz_threshold: int = 85,
) -> dict[str, Any]:
    """For each UK powerplant in PM, find the nearest REPD project by name
    and report capacity divergence.
    """
    from rapidfuzz import fuzz, process
    uk = await asyncio.to_thread(fetch_uk_powerplants)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT repd_id, site_name, capacity_mw, tech_category "
            "FROM repd_projects WHERE site_name IS NOT NULL AND capacity_mw > 0"
        )
    repd_names = [r["site_name"] for r in rows]
    repd_lookup = {r["site_name"]: r for r in rows}

    matches = []
    divergent = []
    unmatched = 0
    for _, p in uk.iterrows():
        pm_name = str(p.get("Name", "")).strip()
        pm_cap = float(p.get("Capacity", 0) or 0)
        if not pm_name or pm_cap <= 0:
            continue
        best = process.extractOne(pm_name, repd_names, scorer=fuzz.WRatio)
        if not best or best[1] < fuzz_threshold:
            unmatched += 1
            continue
        repd_row = repd_lookup[best[0]]
        repd_cap = float(repd_row["capacity_mw"] or 0)
        delta_pct = (
            round(100 * abs(pm_cap - repd_cap) / max(repd_cap, 1), 1)
            if repd_cap else None
        )
        rec = {
            "repd_id": repd_row["repd_id"],
            "repd_name": best[0],
            "repd_capacity_mw": repd_cap,
            "pm_name": pm_name,
            "pm_capacity_mw": round(pm_cap, 1),
            "fuzz_score": best[1],
            "delta_pct": delta_pct,
        }
        matches.append(rec)
        if delta_pct is not None and delta_pct > 20:
            divergent.append(rec)

    return {
        "uk_plants_in_pm": int(len(uk)),
        "matched": len(matches),
        "unmatched": unmatched,
        "divergent_over_20pct": len(divergent),
        "divergent_samples": divergent[:10],
    }


if __name__ == "__main__":
    async def _main():
        pool = await asyncpg.create_pool(
            os.environ["DATABASE_URL"],
            min_size=1, max_size=3, statement_cache_size=0,
        )
        r = await cross_validate_repd(pool)
        print(json.dumps(r, default=str)[:2000])
        await pool.close()
    asyncio.run(_main())
