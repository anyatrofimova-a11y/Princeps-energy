"""
utils/bmrs_bmu.py — Per-BMU dispatch + registry against the Elexon Insights
Solution.

Elexon BMRS publishes per-BMU (Balancing Mechanism Unit) physical levels at
30-min granularity. As of the 2024 BMRS migration:

    /datasets/PN/stream     Physical Notifications (notified MW per period)
    /datasets/MELS/stream   Maximum Export Levels (rated capability)
    /datasets/BOALF/stream  Bid-Offer Acceptance Levels (NESO instructions)
    /reference/bmunits/all  Full BMU registry (party + fuel)

The legacy ``B1610`` dataset has been retired; we use **PN** as the
per-period dispatch signal (notified rather than metered, but published in
near real-time and accurate to within fractions of a MW for almost all
units). Fields per record::

    {settlementDate, settlementPeriod, timeFrom, timeTo,
     levelFrom, levelTo, bmUnit, nationalGridBmUnit, ...}

We compute period mean = (levelFrom + levelTo) / 2 and total MWh =
sum(period_mean) * 0.5.

Public surface:
    bmu_registry()                  — full BMU↔lead-party registry, cached
    match_bmus_by_name(query)       — registry has no geometry, so we match
                                      by lead-party / BMU id substring
    dispatch_window(bmu, days=14)   — PN-summarised curve for one BMU
    rated_capability(bmu)           — MELS-derived rated MW
    asset_dispatch_summary(...)     — one-shot helper for the popup
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from functools import lru_cache

import httpx

log = logging.getLogger("princeps.bmrs_bmu")

_BMRS_BASE = "https://data.elexon.co.uk/bmrs/api/v1"
_USER_AGENT = "Princeps/1.0 (+https://princeps.energy) bmrs-bmu"
_TIMEOUT = httpx.Timeout(20.0, connect=8.0)


@dataclass(frozen=True)
class BmuRecord:
    bmu_id: str
    lead_party: str | None
    lead_party_id: str | None
    fuel_type: str | None
    bmu_type: str | None
    ngc_bmu_id: str | None
    elexon_bmu_id: str | None
    ic_lead_party: str | None
    asset_id: str | None


@dataclass(frozen=True)
class DispatchWindow:
    bmu_id: str
    settlement_from: str
    settlement_to: str
    n_periods: int
    min_mw: float | None
    max_mw: float | None
    mean_mw: float | None
    median_mw: float | None
    total_mwh: float | None
    capacity_factor: float | None
    last_period: str | None
    last_mw: float | None


# ---------------------------------------------------------------------------
# BMU registry
# ---------------------------------------------------------------------------
_REGISTRY_TTL_S = 60 * 60 * 24    # daily refresh
_registry_cache: dict[str, Any] = {"records": None, "fetched": None}


async def bmu_registry(*, client: httpx.AsyncClient | None = None,
                       force: bool = False) -> list[BmuRecord]:
    """Return the complete BMU↔party↔fuel registry. Cached for 24 h."""
    now = datetime.now(timezone.utc)
    if (
        not force
        and _registry_cache["records"] is not None
        and _registry_cache["fetched"]
        and (now - _registry_cache["fetched"]).total_seconds() < _REGISTRY_TTL_S
    ):
        return _registry_cache["records"]

    own = client is None
    if own:
        client = httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT},
        )
    try:
        r = await client.get(f"{_BMRS_BASE}/reference/bmunits/all")
        r.raise_for_status()
        body = r.json()
        rows = body if isinstance(body, list) else body.get("data") or []
        out: list[BmuRecord] = []
        for it in rows:
            out.append(BmuRecord(
                bmu_id=str(it.get("elexonBmUnit") or it.get("bmUnit") or it.get("ngcBmUnit") or ""),
                lead_party=it.get("leadPartyName"),
                lead_party_id=it.get("leadPartyId"),
                fuel_type=it.get("fuelType"),
                bmu_type=it.get("bmUnitType"),
                ngc_bmu_id=it.get("ngcBmUnit"),
                elexon_bmu_id=it.get("elexonBmUnit"),
                ic_lead_party=it.get("interconnectorLeadPartyName"),
                asset_id=it.get("assetId"),
            ))
        out = [r for r in out if r.bmu_id]
        _registry_cache["records"] = out
        _registry_cache["fetched"] = now
        return out
    except httpx.HTTPError as exc:
        log.warning("bmu_registry fetch failed: %s", exc)
        return _registry_cache["records"] or []
    finally:
        if own:
            await client.aclose()


# ---------------------------------------------------------------------------
# Match helpers — registry has no geometry, so we match by lead-party name
# ---------------------------------------------------------------------------
def _norm(s: str | None) -> str:
    if not s:
        return ""
    return "".join(ch.lower() for ch in s if ch.isalnum())


async def match_bmus_by_name(query: str, *, client: httpx.AsyncClient | None = None,
                             max_n: int = 6) -> list[BmuRecord]:
    """Return BMUs whose lead-party or BMU id contains tokens of ``query``.

    Designed to be called with an asset/site name + nearest plant operator
    discovered from Wikidata. Falls back to substring matching.
    """
    reg = await bmu_registry(client=client)
    if not query or not reg:
        return []
    q = _norm(query)
    if len(q) < 3:
        return []
    out = []
    for rec in reg:
        score = 0
        for f in (rec.lead_party, rec.bmu_id, rec.ngc_bmu_id, rec.elexon_bmu_id, rec.asset_id):
            f_norm = _norm(f)
            if not f_norm:
                continue
            if q in f_norm or f_norm in q:
                score += 1
        if score:
            out.append((score, rec))
    out.sort(key=lambda x: -x[0])
    return [r for _, r in out[:max_n]]


# ---------------------------------------------------------------------------
# Dispatch window
# ---------------------------------------------------------------------------
async def _stream_dataset(
    dataset: str,
    *,
    bmu_id: str,
    since: str,
    until: str,
    client: httpx.AsyncClient,
) -> list[dict]:
    r = await client.get(
        f"{_BMRS_BASE}/datasets/{dataset}/stream",
        params={"from": since, "to": until, "bmUnit": bmu_id, "format": "json"},
    )
    if r.status_code != 200:
        log.info("%s %s status=%s", dataset, bmu_id, r.status_code)
        return []
    body = r.json()
    return body if isinstance(body, list) else (body.get("data") or [])


async def dispatch_window(
    bmu_id: str,
    *,
    days: int = 14,
    client: httpx.AsyncClient | None = None,
) -> DispatchWindow | None:
    """Pull PN dispatch for ``bmu_id`` over the last N days and summarise.

    Each PN record gives the notified MW level at the start (`levelFrom`)
    and end (`levelTo`) of a settlement period; we average to a per-period
    mean MW and reduce to min / max / mean / median / total MWh / capacity
    factor.
    """
    if not bmu_id:
        return None
    since = (date.today() - timedelta(days=days)).isoformat() + "T00:00Z"
    until = (date.today() + timedelta(days=1)).isoformat() + "T00:00Z"

    own = client is None
    if own:
        client = httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT},
        )
    try:
        rows = await _stream_dataset("PN", bmu_id=bmu_id, since=since, until=until, client=client)
        if not rows:
            return None
        mw_values: list[float] = []
        last_period_label: str | None = None
        last_mw: float | None = None
        last_time: str | None = None
        for it in rows:
            lf = it.get("levelFrom")
            lt = it.get("levelTo")
            if lf is None and lt is None:
                continue
            try:
                if lf is not None and lt is not None:
                    avg = (float(lf) + float(lt)) / 2.0
                else:
                    avg = float(lf if lf is not None else lt)
            except (TypeError, ValueError):
                continue
            mw_values.append(avg)
            tt = it.get("timeTo") or ""
            if tt > (last_time or ""):
                last_time = tt
                last_period_label = (
                    f"{it.get('settlementDate')} SP{it.get('settlementPeriod')}"
                )
                last_mw = avg
        if not mw_values:
            return None
        mw_sorted = sorted(mw_values)
        n = len(mw_sorted)
        median = mw_sorted[n // 2] if n % 2 else (mw_sorted[n // 2 - 1] + mw_sorted[n // 2]) / 2
        total_mwh = sum(mw_values) * 0.5     # 30-min periods
        max_mw = max(mw_values)
        cap_factor = (sum(mw_values) / (max_mw * n)) if max_mw and n else None
        return DispatchWindow(
            bmu_id=bmu_id,
            settlement_from=since[:10],
            settlement_to=until[:10],
            n_periods=n,
            min_mw=round(min(mw_values), 2),
            max_mw=round(max_mw, 2),
            mean_mw=round(sum(mw_values) / n, 2),
            median_mw=round(median, 2),
            total_mwh=round(total_mwh, 1),
            capacity_factor=round(cap_factor, 4) if cap_factor is not None else None,
            last_period=last_period_label,
            last_mw=round(last_mw, 2) if last_mw is not None else None,
        )
    except httpx.HTTPError as exc:
        log.warning("dispatch_window fetch failed (%s): %s", bmu_id, exc)
        return None
    finally:
        if own:
            await client.aclose()


async def rated_capability(
    bmu_id: str,
    *,
    days: int = 14,
    client: httpx.AsyncClient | None = None,
) -> dict | None:
    """Pull MELS to derive the rated maximum export level."""
    if not bmu_id:
        return None
    since = (date.today() - timedelta(days=days)).isoformat() + "T00:00Z"
    until = (date.today() + timedelta(days=1)).isoformat() + "T00:00Z"
    own = client is None
    if own:
        client = httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT},
        )
    try:
        rows = await _stream_dataset("MELS", bmu_id=bmu_id, since=since, until=until, client=client)
        if not rows:
            return None
        levels = []
        for it in rows:
            lf = it.get("levelFrom"); lt = it.get("levelTo")
            for v in (lf, lt):
                try:
                    if v is not None:
                        levels.append(float(v))
                except (TypeError, ValueError):
                    pass
        if not levels:
            return None
        return {
            "bmu_id": bmu_id,
            "rated_export_max_mw": round(max(levels), 2),
            "rated_export_typical_mw": round(sorted(levels)[len(levels) // 2], 2),
            "n_observations": len(levels),
        }
    except httpx.HTTPError as exc:
        log.warning("rated_capability fetch failed (%s): %s", bmu_id, exc)
        return None
    finally:
        if own:
            await client.aclose()


# ---------------------------------------------------------------------------
# Convenience: resolve + summarise for asset-intel popup
# ---------------------------------------------------------------------------
async def asset_dispatch_summary(
    *,
    asset_name: str | None,
    operator: str | None,
    days: int = 14,
    client: httpx.AsyncClient | None = None,
) -> dict | None:
    """One-shot: try to resolve probable BMUs from name/operator, then pull
    a 14-day dispatch summary for the top candidate."""
    queries = [q for q in (asset_name, operator) if q]
    if not queries:
        return None
    tried: set[str] = set()
    candidates: list[BmuRecord] = []
    for q in queries:
        for c in await match_bmus_by_name(q, client=client, max_n=6):
            if c.bmu_id in tried:
                continue
            tried.add(c.bmu_id)
            candidates.append(c)
        if candidates:
            break
    if not candidates:
        return None
    summaries = []
    for c in candidates[:3]:    # cap to top-3 to keep the popup snappy
        d = await dispatch_window(c.bmu_id, days=days, client=client)
        cap = await rated_capability(c.bmu_id, days=days, client=client)
        summaries.append({
            "bmu": asdict(c),
            "dispatch": asdict(d) if d else None,
            "rated": cap,
        })
    return {
        "queries": queries,
        "n_candidates": len(candidates),
        "summaries": summaries,
    }
