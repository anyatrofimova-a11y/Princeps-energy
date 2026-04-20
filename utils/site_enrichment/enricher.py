"""Top-level site enrichment orchestrator.

Runs all 8 sub-enrichers in parallel via ``asyncio.gather``.  Each call is
wrapped with an 800 ms timeout; any sub-enricher that times out, errors, or
returns empty has its slot set to ``None`` and its failure string appended to
``errors[]``.  The orchestrator itself never raises.

Results cached for 24 h at key ``enrich:<round5(lat)>,<round5(lon)>`` when
``REDIS_URL`` is set — otherwise cache is a no-op and every call hits the
backends.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import asyncpg

from . import constraints as _constraints
from . import dno as _dno
from . import epc as _epc
from . import hmlr as _hmlr
from . import landuse as _landuse
from . import lpa as _lpa
from . import postcode as _postcode
from . import uprn as _uprn

log = logging.getLogger("princeps.site_enrichment.enricher")


_PER_CALL_TIMEOUT_S = 0.8
_CACHE_TTL_S = 24 * 3600
_KEY_PRECISION = 5


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EnrichmentResult:
    lat: float
    lon: float
    postcode: Optional[dict[str, Any]] = None
    lpa: Optional[dict[str, Any]] = None
    dno: Optional[dict[str, Any]] = None
    uprn: Optional[dict[str, Any]] = None
    hmlr: Optional[dict[str, Any]] = None
    constraints: Optional[dict[str, Any]] = None
    epc: Optional[dict[str, Any]] = None
    landuse: Optional[dict[str, Any]] = None
    errors: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Redis cache shim — optional
# ---------------------------------------------------------------------------

_redis_client = None
_redis_probed = False


async def _get_redis():
    global _redis_client, _redis_probed
    if _redis_probed:
        return _redis_client
    _redis_probed = True
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    try:
        import redis.asyncio as redis  # noqa: WPS433
        _redis_client = redis.from_url(url, decode_responses=True, socket_timeout=0.2)
        await _redis_client.ping()
    except Exception as exc:
        log.info("redis cache disabled: %s", exc)
        _redis_client = None
    return _redis_client


def _cache_key(lat: float, lon: float) -> str:
    return f"enrich:{round(lat, _KEY_PRECISION)},{round(lon, _KEY_PRECISION)}"


async def _cache_get(lat: float, lon: float) -> Optional[dict[str, Any]]:
    r = await _get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(_cache_key(lat, lon))
        return json.loads(raw) if raw else None
    except Exception as exc:
        log.debug("cache get failed: %s", exc)
        return None


async def _cache_set(lat: float, lon: float, payload: dict[str, Any]) -> None:
    r = await _get_redis()
    if r is None:
        return
    try:
        await r.setex(_cache_key(lat, lon), _CACHE_TTL_S, json.dumps(payload, default=str))
    except Exception as exc:
        log.debug("cache set failed: %s", exc)


# ---------------------------------------------------------------------------
# Per-call harness
# ---------------------------------------------------------------------------

async def _guarded(name: str, coro, errors: list[str]) -> Optional[Any]:
    """Run ``coro`` with a per-call timeout; on any failure append to ``errors``."""
    try:
        return await asyncio.wait_for(coro, timeout=_PER_CALL_TIMEOUT_S)
    except asyncio.TimeoutError:
        errors.append(f"{name}: timeout > {_PER_CALL_TIMEOUT_S*1000:.0f} ms")
        return None
    except Exception as exc:  # noqa: BLE001 — we want total catch
        errors.append(f"{name}: {type(exc).__name__}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def enrich(
    lat: float,
    lon: float,
    *,
    pool: Optional[asyncpg.Pool] = None,
    use_cache: bool = True,
) -> EnrichmentResult:
    """Return a fully-populated ``EnrichmentResult``.

    Failure modes are represented on the result (``result.errors``); this
    function is total — it will never raise for an input point, even when
    every backend is missing.
    """
    t0 = time.monotonic()

    if use_cache:
        cached = await _cache_get(lat, lon)
        if cached is not None:
            cached["cache_hit"] = True
            # Backfill schema fields any caller may expect (if older cache shape)
            for k in ("errors",):
                cached.setdefault(k, [])
            return EnrichmentResult(**{
                k: v for k, v in cached.items()
                if k in EnrichmentResult.__dataclass_fields__
            })

    errors: list[str] = []

    # Step 1 — postcode first (its result feeds DNO + EPC).
    postcode_payload = await _guarded("postcode", _postcode.lookup(lat, lon), errors)
    postcode_str = (postcode_payload or {}).get("postcode") if isinstance(postcode_payload, dict) else None

    # Step 2 — parallel gather of the remaining seven.
    lpa_task         = _guarded("lpa",         _lpa.lookup(lat, lon, pool=pool), errors)
    dno_task         = _guarded("dno",         _dno.lookup(lat, lon, pool=pool, postcode=postcode_str), errors)
    uprn_task        = _guarded("uprn",        _uprn.lookup(lat, lon), errors)
    hmlr_task        = _guarded("hmlr",        _hmlr.lookup(lat, lon, pool=pool), errors)
    constraints_task = _guarded("constraints", _constraints.lookup(lat, lon, pool=pool), errors)
    epc_task         = _guarded("epc",         _epc.lookup(lat, lon, postcode=postcode_str), errors)
    landuse_task     = _guarded("landuse",     _landuse.lookup(lat, lon), errors)

    lpa_p, dno_p, uprn_p, hmlr_p, cons_p, epc_p, lu_p = await asyncio.gather(
        lpa_task, dno_task, uprn_task, hmlr_task, constraints_task, epc_task, landuse_task,
    )

    result = EnrichmentResult(
        lat=lat,
        lon=lon,
        postcode=postcode_payload if isinstance(postcode_payload, dict) and postcode_payload else None,
        lpa=lpa_p if isinstance(lpa_p, dict) and lpa_p else None,
        dno=dno_p if isinstance(dno_p, dict) and dno_p else None,
        uprn=uprn_p if isinstance(uprn_p, dict) and uprn_p else None,
        hmlr=hmlr_p if isinstance(hmlr_p, dict) and hmlr_p else None,
        constraints=cons_p if isinstance(cons_p, dict) and cons_p else None,
        epc=epc_p if isinstance(epc_p, dict) and epc_p else None,
        landuse=lu_p if isinstance(lu_p, dict) and lu_p else None,
        errors=errors,
        elapsed_ms=round((time.monotonic() - t0) * 1000.0, 1),
        cache_hit=False,
    )

    if use_cache:
        await _cache_set(lat, lon, result.to_dict())

    return result
