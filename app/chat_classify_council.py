"""Council classifier — does this query need the multi-pod Council surface?

Single entry point: ``needs_council(claude, query)`` returns
``{needs_council: bool, domains: [str], reason: str}``.

Ranking:
  1. Tiny Claude prompt (<100 words) for nuanced domain detection.
  2. Keyword heuristic fallback if Claude raises (network, parse, key).

A 5-minute in-memory cache keyed on the lowercased query keeps repeat
hits cheap (chat rail will reclassify on every send when the user
re-types the same prompt).
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

log = logging.getLogger("princeps.chat.classify_council")

CLAUDE_HAIKU = "claude-haiku-4-5"  # cheap + fast; classifier doesn't need Sonnet

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TTL_SECONDS = 300

_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "grid": ("grid", "headroom", "queue", "tec ", "ecr", "substation", "dno", "neso", "feeder", "11kv", "33kv", "132kv", "400kv"),
    "bess": ("bess", "battery", "storage", "co-located", "colocated", "duration"),
    "dc": ("data centre", "data center", "datacentre", "datacenter", "hyperscaler", "ai compute", "gpu", "colo"),
    "planning": ("planning", "repd", "consent", "lpa", "nsip", "dco", "permitted development"),
    "finance": ("ppa", "irr", "npv", "tariff", "cfd", "revenue stack", "merchant"),
    "land": ("freehold", "leasehold", "option", "land agent", "title", "land registry"),
}

_CLASSIFIER_SYSTEM = (
    "You classify whether a user query needs a multi-domain expert council "
    "(3+ specialists across grid/bess/dc/planning/finance/land) or single-pass "
    "chat. Council = 2+ distinct domains AND a tradeoff/comparison/co-design "
    "question. Output JSON only: "
    '{"needs_council": bool, "domains": [...], "reason": "<=15 words"}. '
    "Domains are 'grid'|'bess'|'dc'|'planning'|'finance'|'land'."
)


def _heuristic(query: str) -> dict[str, Any]:
    q = (query or "").lower()
    domains = [d for d, kws in _DOMAIN_KEYWORDS.items() if any(k in q for k in kws)]
    needs = len(domains) >= 2
    return {
        "needs_council": needs,
        "domains": domains,
        "reason": "heuristic: " + (
            f"{len(domains)} domains matched" if needs else "single domain or none"
        ),
        "source": "heuristic",
    }


def _cache_get(query: str) -> dict[str, Any] | None:
    key = (query or "").strip().lower()
    if not key:
        return None
    hit = _CACHE.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts > _TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return dict(value)


def _cache_put(query: str, value: dict[str, Any]) -> None:
    key = (query or "").strip().lower()
    if not key:
        return
    if len(_CACHE) > 200:
        # cheap LRU-ish trim — drop the 50 oldest
        oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:50]
        for k, _ in oldest:
            _CACHE.pop(k, None)
    _CACHE[key] = (time.time(), dict(value))


_JSON_RE = re.compile(r"\{.*\}", re.S)


def _parse_claude(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    m = _JSON_RE.search(raw)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    needs = bool(obj.get("needs_council"))
    domains = obj.get("domains") or []
    if not isinstance(domains, list):
        domains = []
    domains = [str(d).lower() for d in domains if isinstance(d, (str, int))]
    reason = str(obj.get("reason") or "")[:200]
    return {"needs_council": needs, "domains": domains, "reason": reason}


async def needs_council(claude: Any, query: str) -> dict[str, Any]:
    """Classify whether a user query needs the multi-pod Council surface.

    Returns ``{needs_council: bool, domains: [str], reason: str, source: str}``.
    Never raises — falls back to a keyword heuristic on any error.
    """
    if not query or not query.strip():
        return {"needs_council": False, "domains": [], "reason": "empty", "source": "guard"}

    cached = _cache_get(query)
    if cached:
        cached["source"] = cached.get("source", "cache") + "+cache"
        return cached

    if claude is None:
        out = _heuristic(query)
        _cache_put(query, out)
        return out

    try:
        message = await claude.messages.create(
            model=CLAUDE_HAIKU,
            max_tokens=180,
            temperature=0.0,
            system=_CLASSIFIER_SYSTEM,
            messages=[{"role": "user", "content": query.strip()}],
        )
        raw = message.content[0].text if message.content else ""
        parsed = _parse_claude(raw)
        if parsed is None:
            out = _heuristic(query)
        else:
            parsed["source"] = "claude"
            out = parsed
    except Exception as exc:
        log.warning("classify_council Claude call failed: %s", exc)
        out = _heuristic(query)

    _cache_put(query, out)
    return out
