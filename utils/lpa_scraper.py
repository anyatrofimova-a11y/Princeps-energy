"""
lpa_scraper — Real LPA Pulse data from UK council planning portals.

Subprocess-style script.  Reads a JSON payload from stdin, writes a JSON
result to stdout.  Designed to be invoked by the FastAPI router via
`_run_generic_subprocess(LPA_SCRIPT, payload, timeout=15)`.

Input shape:
    {"lpa_name": "South Cambridgeshire", "workload_type": "solar"}

Output shape (success):
    {
        "lpa_name": "...",
        "score": 73,
        "score_label": "Receptive",
        "tier": "good",
        "breakdown": {
            "approval_rate_pct": 78,
            "median_decision_days": 92,
            "recent_decisions_12mo": 14,
            "political_stance": "supportive|neutral|hostile",
            "precedent_strength": "strong|moderate|weak"
        },
        "narrative": "...",
        "evidence_count": 14,
        "evidence_urls": [...],
        "fetched_at": "ISO timestamp",
        "source": "firecrawl-lean live scrape" | "direct httpx fallback"
    }

Output shape (failure):
    {"error": "<reason>", "fallback_to_synthetic": true}

Strategy:
1. Look up LPA → planning portal URL in LPA_REGISTRY (10 LPAs hard-coded).
2. Prefer the `firecrawl` CLI (firecrawl-lean / firecrawl-cli) if available
   and authenticated — produces the highest-quality structured output.
3. Fall back to direct `httpx` + `BeautifulSoup` scrape — always works for
   server-rendered portals (most UK councils still are).
4. Conservative concurrency: one LPA at a time, 2-second delay between
   page fetches, single-shot for the recent-decisions index page.
5. Honour robots.txt where present (best-effort; many councils omit it).
6. In-memory TTL cache (1 hour) so repeated calls for the same LPA do
   not re-hit the council site.

This file is intentionally subprocess-safe (no FastAPI / DB imports);
it can be imported in-process too — see `scrape_lpa_sync` below.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

# ── Lookup table of supported LPAs ─────────────────────────────────────────
#
# Key = lower-case canonical name (matched fuzzily on input).
# `portal` = recent-decisions / committee page that actually lists items.
# `kind` = portal software family (Idox / Northgate / Civica / generic).
#
# These were the most common UK council planning systems as of 2026-04.
# Adding new LPAs is purely additive.

LPA_REGISTRY: dict[str, dict[str, str]] = {
    "south cambridgeshire": {
        "portal": "https://applications.greatercambridgeplanning.org/online-applications/search.do?action=weeklyList",
        "decisions": "https://applications.greatercambridgeplanning.org/online-applications/search.do?action=monthlyList",
        "kind": "idox",
    },
    "north yorkshire": {
        "portal": "https://onlineplanningregister.northyorks.gov.uk/online-applications/search.do?action=weeklyList",
        "decisions": "https://onlineplanningregister.northyorks.gov.uk/online-applications/search.do?action=monthlyList",
        "kind": "idox",
    },
    "west berkshire": {
        "portal": "https://publicaccess.westberks.gov.uk/online-applications/search.do?action=weeklyList",
        "decisions": "https://publicaccess.westberks.gov.uk/online-applications/search.do?action=monthlyList",
        "kind": "idox",
    },
    "mid suffolk": {
        "portal": "https://planning.baberghmidsuffolk.gov.uk/online-applications/search.do?action=weeklyList",
        "decisions": "https://planning.baberghmidsuffolk.gov.uk/online-applications/search.do?action=monthlyList",
        "kind": "idox",
    },
    "east riding": {
        "portal": "https://newplanningaccess.eastriding.gov.uk/newplanningaccess/search.do?action=weeklyList",
        "decisions": "https://newplanningaccess.eastriding.gov.uk/newplanningaccess/search.do?action=monthlyList",
        "kind": "idox",
    },
    "cornwall": {
        "portal": "https://planning.cornwall.gov.uk/online-applications/search.do?action=weeklyList",
        "decisions": "https://planning.cornwall.gov.uk/online-applications/search.do?action=monthlyList",
        "kind": "idox",
    },
    "highland": {
        "portal": "https://wam.highland.gov.uk/wam/search.do?action=weeklyList",
        "decisions": "https://wam.highland.gov.uk/wam/search.do?action=monthlyList",
        "kind": "idox",
    },
    "lothian": {
        # Mid/East/West Lothian + Edinburgh share common pattern; default to City of Edinburgh.
        "portal": "https://citydev-portal.edinburgh.gov.uk/idoxpa-web/search.do?action=weeklyList",
        "decisions": "https://citydev-portal.edinburgh.gov.uk/idoxpa-web/search.do?action=monthlyList",
        "kind": "idox",
    },
    "pembrokeshire": {
        "portal": "https://planning.pembrokeshire.gov.uk/online-applications/search.do?action=weeklyList",
        "decisions": "https://planning.pembrokeshire.gov.uk/online-applications/search.do?action=monthlyList",
        "kind": "idox",
    },
    "wrexham": {
        "portal": "https://planning.wrexham.gov.uk/planning/search.do?action=weeklyList",
        "decisions": "https://planning.wrexham.gov.uk/planning/search.do?action=monthlyList",
        "kind": "idox",
    },
}

USER_AGENT = (
    "Mozilla/5.0 (compatible; PrincepsLPABot/1.0; +https://princeps.energy/bot)"
)
HTTP_TIMEOUT = 12.0  # per-request seconds
PAGE_DELAY = 2.0     # seconds between consecutive page fetches
MAX_DECISIONS = 20   # cap rows extracted

# ── Tiny in-process TTL cache ──────────────────────────────────────────────
# Keyed by lpa_name (lower-case) + workload_type. 1-hour TTL.
_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
CACHE_TTL_S = 3600


# ── Workload classifier (very simple keyword regex) ────────────────────────

WORKLOAD_PATTERNS = {
    "solar": re.compile(r"\b(solar|photovoltaic|pv\b|solar farm|solar park)\b", re.I),
    "bess":  re.compile(r"\b(bess|battery|energy storage|bsf)\b", re.I),
    "wind":  re.compile(r"\b(wind turbine|wind farm|onshore wind)\b", re.I),
    "dc":    re.compile(r"\b(data centre|data center|datacentre|hyperscale)\b", re.I),
}

DECISION_APPROVED = re.compile(
    r"\b(approved|granted|permitted|permission granted|approval|grant)\b", re.I
)
DECISION_REFUSED = re.compile(r"\b(refused|rejected|withdrawn)\b", re.I)


# ── LPA name normalisation / lookup ────────────────────────────────────────

def _normalise_lpa_name(name: str) -> str:
    s = (name or "").lower().strip()
    # Strip common suffixes for fuzzy matching
    for suffix in (
        " district council", " county council", " borough council",
        " city council", " council", " combined authority",
    ):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s.strip()


def _lookup_lpa(name: str) -> dict[str, str] | None:
    norm = _normalise_lpa_name(name)
    if norm in LPA_REGISTRY:
        return LPA_REGISTRY[norm]
    # Best-effort partial: find any registry key contained in the normalised input
    for key, cfg in LPA_REGISTRY.items():
        if key in norm or norm in key:
            return cfg
    return None


# ── robots.txt check (best-effort, non-blocking on failure) ────────────────

def _robots_allows(url: str) -> bool:
    try:
        parsed = urlparse(url)
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
        rp.read()
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True  # Silently allow when robots.txt is missing/broken.


# ── firecrawl CLI path (lean install via npm) ──────────────────────────────

def _firecrawl_available() -> bool:
    """True iff the firecrawl CLI is installed AND authenticated."""
    if shutil.which("firecrawl") is None:
        return False
    try:
        r = subprocess.run(
            ["firecrawl", "--status"], capture_output=True, text=True, timeout=4
        )
        # CLI prints something like 'Authenticated: yes' on success.
        return r.returncode == 0 and "auth" in (r.stdout + r.stderr).lower()
    except Exception:
        return False


def _firecrawl_scrape(url: str) -> str | None:
    """Scrape a URL via the firecrawl CLI; returns markdown or None."""
    try:
        r = subprocess.run(
            ["firecrawl", "scrape", url, "--only-main-content", "--format", "markdown"],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    except Exception:
        pass
    return None


# ── Direct httpx fallback ──────────────────────────────────────────────────

def _httpx_get(url: str) -> str | None:
    try:
        import httpx  # imported lazily so script works even if not installed
    except ImportError:
        return None
    try:
        with httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"},
            follow_redirects=True,
        ) as client:
            r = client.get(url)
            if r.status_code == 200 and r.text:
                return r.text
    except Exception:
        return None
    return None


# ── Extract decisions table (Idox-flavoured HTML) ──────────────────────────

DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})[/\-\s]([A-Za-z]{3,9})[/\-\s](\d{4})\b"),  # 12 Jan 2026
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),                     # 12/01/2026
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),                         # 2026-01-12
]


def _parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    for pat in DATE_PATTERNS:
        m = pat.search(raw)
        if not m:
            continue
        try:
            if pat is DATE_PATTERNS[0]:
                day, mon, year = m.groups()
                return datetime.strptime(f"{day} {mon[:3]} {year}", "%d %b %Y")
            if pat is DATE_PATTERNS[1]:
                day, mon, year = m.groups()
                return datetime(int(year), int(mon), int(day))
            year, mon, day = m.groups()
            return datetime(int(year), int(mon), int(day))
        except (ValueError, TypeError):
            continue
    return None


def _extract_decisions(html_or_md: str, base_url: str, *, limit: int = MAX_DECISIONS) -> list[dict[str, Any]]:
    """Best-effort decision extraction. Works on Idox HTML and firecrawl MD."""
    out: list[dict[str, Any]] = []

    # First pass — proper HTML parse if BeautifulSoup is available.
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        BeautifulSoup = None  # type: ignore

    if BeautifulSoup is not None and "<html" in html_or_md.lower():
        soup = BeautifulSoup(html_or_md, "html.parser")
        # Idox lists results in <li class="searchresult"> with a <p> per field.
        items = soup.select("li.searchresult, li.result, div.searchresult")
        for it in items[:limit]:
            text = it.get_text(" ", strip=True)
            if not text:
                continue
            link_el = it.find("a", href=True)
            href = urljoin(base_url, link_el["href"]) if link_el else None
            received = None
            decision = None
            decided = None
            for p in it.find_all(["p", "div"]):
                t = p.get_text(" ", strip=True)
                low = t.lower()
                if "registered" in low or "received" in low:
                    received = _parse_date(t)
                if "decision" in low and "date" in low:
                    decided = _parse_date(t)
                if "decision" in low and "status" in low:
                    decision = t.split(":", 1)[-1].strip()
                if not decision:
                    if DECISION_APPROVED.search(t):
                        decision = "approved"
                    elif DECISION_REFUSED.search(t):
                        decision = "refused"
            out.append({
                "title": text[:200],
                "url": href,
                "received_at": received.isoformat() if received else None,
                "decided_at": decided.isoformat() if decided else None,
                "decision": (decision or "unknown").lower(),
                "workload": _classify_workload(text),
            })

    # Markdown / fallback — line-by-line heuristic.
    if not out:
        for line in html_or_md.splitlines():
            line = line.strip()
            if not line or len(line) < 10:
                continue
            if not (DECISION_APPROVED.search(line) or DECISION_REFUSED.search(line)
                    or "application" in line.lower()):
                continue
            url_m = re.search(r"https?://\S+", line)
            received = _parse_date(line)
            decision = "approved" if DECISION_APPROVED.search(line) else (
                "refused" if DECISION_REFUSED.search(line) else "unknown"
            )
            out.append({
                "title": line[:200],
                "url": url_m.group(0) if url_m else None,
                "received_at": received.isoformat() if received else None,
                "decided_at": received.isoformat() if received else None,
                "decision": decision,
                "workload": _classify_workload(line),
            })
            if len(out) >= limit:
                break

    return out


def _classify_workload(text: str) -> str:
    for label, pat in WORKLOAD_PATTERNS.items():
        if pat.search(text):
            return label
    return "general"


# ── Aggregate decisions → score + breakdown ────────────────────────────────

def _aggregate(decisions: list[dict[str, Any]], lpa_name: str, workload_type: str) -> dict[str, Any]:
    relevant = decisions
    workload_scoped = [d for d in decisions if d.get("workload") == workload_type]

    if workload_scoped:
        relevant = workload_scoped

    decided = [d for d in relevant if d.get("decision") in ("approved", "refused")]
    n_decided = len(decided)
    n_approved = sum(1 for d in decided if d["decision"] == "approved")

    approval_rate = round(100 * n_approved / n_decided) if n_decided else None

    # Median decision time (received → decided) in days
    spans: list[int] = []
    for d in decided:
        try:
            r = datetime.fromisoformat(d["received_at"]) if d.get("received_at") else None
            x = datetime.fromisoformat(d["decided_at"]) if d.get("decided_at") else None
            if r and x and x >= r:
                spans.append((x - r).days)
        except Exception:
            pass
    spans.sort()
    median_days = spans[len(spans) // 2] if spans else None

    # Recent 12mo
    cutoff = datetime.now(tz=timezone.utc).replace(tzinfo=None) - timedelta(days=365)
    recent = [d for d in relevant if d.get("received_at") and
              _safe_isodt(d["received_at"]) and _safe_isodt(d["received_at"]) >= cutoff]
    recent_count = len(recent) if recent else len(relevant[:12])

    # Score: weighted blend of approval rate, decision speed, evidence depth.
    score = _compute_score(approval_rate, median_days, recent_count)

    if score >= 70:
        label, tier = "Receptive", "good"
    elif score >= 50:
        label, tier = "Mixed", "ok"
    else:
        label, tier = "Hostile", "bad"

    political_stance = (
        "supportive" if (approval_rate or 0) >= 70 else
        "neutral"   if (approval_rate or 0) >= 45 else
        "resistant"
    )
    precedent_strength = (
        "strong"   if recent_count >= 12 and (approval_rate or 0) >= 65 else
        "moderate" if recent_count >= 6 else
        "weak"
    )

    workload_label = {
        "solar": "utility-scale solar",
        "bess": "battery storage",
        "dc": "data centre",
        "wind": "onshore wind",
    }.get(workload_type, workload_type)

    if approval_rate is not None and median_days is not None:
        narrative = (
            f"{lpa_name} approved {approval_rate}% of {n_decided} {workload_label} "
            f"and adjacent applications observed in committee minutes, with a "
            f"median end-to-end decision time of {median_days} days. Recent 12-month "
            f"throughput stands at {recent_count} comparable items."
        )
    else:
        narrative = (
            f"{lpa_name} planning portal returned {len(relevant)} items but the "
            f"index page lacked structured decision dates; recommend manual review "
            f"of committee minutes for {workload_label}."
        )

    evidence_urls = [d["url"] for d in relevant[:MAX_DECISIONS] if d.get("url")]

    return {
        "lpa_name": lpa_name,
        "score": score,
        "score_label": label,
        "tier": tier,
        "breakdown": {
            "approval_rate_pct": approval_rate if approval_rate is not None else 0,
            "median_decision_days": median_days if median_days is not None else 0,
            "recent_decisions_12mo": recent_count,
            "political_stance": political_stance,
            "precedent_strength": precedent_strength,
        },
        "narrative": narrative,
        "evidence_count": len(relevant),
        "evidence_urls": evidence_urls[:10],
    }


def _safe_isodt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _compute_score(approval: int | None, median_days: int | None, recent: int) -> int:
    # Anchor: 50.  +/- depending on signals.
    s = 50
    if approval is not None:
        s += int((approval - 50) * 0.6)            # ±30 for 0%/100%
    if median_days is not None:
        if median_days < 60:
            s += 10
        elif median_days < 100:
            s += 4
        elif median_days > 180:
            s -= 8
    if recent >= 15:
        s += 8
    elif recent >= 8:
        s += 3
    elif recent <= 2:
        s -= 6
    return max(5, min(95, s))


# ── Top-level orchestration ────────────────────────────────────────────────

def scrape_lpa_sync(lpa_name: str, workload_type: str = "solar") -> dict[str, Any]:
    """Synchronous entry-point. Returns success or error dict."""
    cache_key = (_normalise_lpa_name(lpa_name), workload_type.lower())
    now = time.time()
    if cache_key in _CACHE:
        ts, payload = _CACHE[cache_key]
        if now - ts < CACHE_TTL_S:
            payload = dict(payload)
            payload["cache"] = "hit"
            return payload

    cfg = _lookup_lpa(lpa_name)
    if cfg is None:
        return {"error": f"LPA '{lpa_name}' not in supported registry "
                         f"({len(LPA_REGISTRY)} councils)",
                "fallback_to_synthetic": True}

    portal_url = cfg["decisions"]
    if not _robots_allows(portal_url):
        return {"error": "robots.txt disallows crawling this portal",
                "fallback_to_synthetic": True}

    source: str
    body: str | None = None

    if _firecrawl_available():
        body = _firecrawl_scrape(portal_url)
        if body:
            source = "firecrawl-lean live scrape"
        else:
            source = "firecrawl unavailable, used httpx fallback"
            time.sleep(PAGE_DELAY)
            body = _httpx_get(portal_url)
    else:
        source = "direct httpx fallback (firecrawl CLI not installed)"
        body = _httpx_get(portal_url)

    if not body:
        return {"error": "all scrape attempts failed (network or block)",
                "fallback_to_synthetic": True}

    decisions = _extract_decisions(body, portal_url, limit=MAX_DECISIONS)
    if not decisions:
        return {"error": "scrape succeeded but no decisions extracted",
                "fallback_to_synthetic": True,
                "source": source}

    out = _aggregate(decisions, lpa_name=lpa_name, workload_type=workload_type.lower())
    out["fetched_at"] = datetime.now(tz=timezone.utc).isoformat()
    out["source"] = source
    out["cache"] = "miss"

    _CACHE[cache_key] = (now, out)
    return out


# ── Subprocess entry-point (stdin/stdout JSON) ────────────────────────────

def _main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw or "{}")
    except Exception as exc:
        sys.stdout.write(json.dumps(
            {"error": f"bad input: {exc}", "fallback_to_synthetic": True}
        ))
        return

    lpa_name = (payload.get("lpa_name") or "").strip()
    workload_type = (payload.get("workload_type") or "solar").strip().lower()
    if not lpa_name:
        sys.stdout.write(json.dumps(
            {"error": "lpa_name required", "fallback_to_synthetic": True}
        ))
        return

    try:
        result = scrape_lpa_sync(lpa_name, workload_type)
    except Exception as exc:  # last-resort safety net
        result = {"error": f"unhandled: {exc.__class__.__name__}: {exc}",
                  "fallback_to_synthetic": True}
    sys.stdout.write(json.dumps(result, default=str))


if __name__ == "__main__":
    _main()
