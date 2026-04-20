"""
app/ingestion/ner.py — structured-field extraction for ingested documents.

Extracts (where present):
  - ``counterparty``       — applicant / developer name
  - ``capacity_mw``        — project capacity in MW (GW → MW coerced)
  - ``poc_substation``     — point-of-connection substation name
  - ``capex_gbp``          — capital expenditure in GBP
  - ``commissioning_date`` — ISO date (YYYY-MM-DD)

Regex-first. The LLM fallback (Haiku) is only invoked for messy free-text
fields where the regex didn't find a capacity. Extracted fields are
written to ``documents.extracted_fields`` (jsonb) and surfaced via the
dockets / document detail endpoints.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any

from app.ingestion.claude import HAIKU_MODEL

log = logging.getLogger("princeps.ingestion.ner")


# ── Regexes ──────────────────────────────────────────────────────────────────

_CAPACITY_MW_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:MW|mw|Mw)\b")
_CAPACITY_GW_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:GW|gw|Gw)\b")
_CAPACITY_MWH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:MWh|mwh|MWH|Mwh)\b")

_CAPEX_GBP_RE = re.compile(
    r"£\s*(\d+(?:\.\d+)?)\s*(m|mn|million|bn|billion|b)?\b",
    re.I,
)

# Typical UK POC substation mentions
_POC_RE = re.compile(
    r"(?:point[-\s]of[-\s]connection|POC|connecting (?:to|at)|connection (?:to|at)|grid connection (?:to|at))\s+([A-Z][A-Za-z0-9\'\-\s]{2,50}?)(?:\s+(?:substation|grid|33\s*k[vV]|132\s*k[vV]|400\s*k[vV]|275\s*k[vV]))",
    re.I,
)
_SUBSTATION_RE = re.compile(
    r"\b([A-Z][A-Za-z\'\-\s]{2,30})\s+(?:substation|grid)\b"
)

_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_UK_DATE_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{4})\b",
    re.I,
)

_COMMISSIONING_HINT_RE = re.compile(
    r"(?:commissioning|energisation|energised|operational|COD|commercial operations)\s*(?:date|target|by)?\s*[:\-]?\s*",
    re.I,
)


# ── Public API ───────────────────────────────────────────────────────────────

async def extract_fields(
    text: str,
    *,
    claude=None,
) -> dict[str, Any]:
    """Return a dict of extracted fields for a given blob of text."""
    if not text:
        return {}

    out: dict[str, Any] = {}
    snippet = text[:16_000]

    # Capacity
    cap = _find_capacity_mw(snippet)
    if cap is not None:
        out["capacity_mw"] = cap
    mwh = _CAPACITY_MWH_RE.search(snippet)
    if mwh:
        try:
            out["capacity_mwh"] = float(mwh.group(1))
        except ValueError:
            pass

    # Capex
    capex = _find_capex_gbp(snippet)
    if capex is not None:
        out["capex_gbp"] = capex

    # POC substation
    poc = _find_poc_substation(snippet)
    if poc:
        out["poc_substation"] = poc

    # Commissioning date
    cdate = _find_commissioning_date(snippet)
    if cdate:
        out["commissioning_date"] = cdate.isoformat()

    # Counterparty
    cp = _find_counterparty(snippet)
    if cp:
        out["counterparty"] = cp

    # LLM fallback: only invoke when the regex produced no capacity signal
    # and we have a Claude client. Keeps per-doc cost under ~$0.002.
    needs_llm = claude is not None and "capacity_mw" not in out and len(snippet) > 400
    if needs_llm:
        try:
            llm_out = await _llm_extract(snippet, claude)
            for k, v in llm_out.items():
                out.setdefault(k, v)
        except Exception as e:
            log.debug("NER LLM fallback failed: %s", e)

    return out


# ── Regex helpers ────────────────────────────────────────────────────────────

def _find_capacity_mw(text: str) -> float | None:
    m_mw = _CAPACITY_MW_RE.search(text)
    if m_mw:
        try:
            return float(m_mw.group(1))
        except ValueError:
            pass
    m_gw = _CAPACITY_GW_RE.search(text)
    if m_gw:
        try:
            return float(m_gw.group(1)) * 1000.0
        except ValueError:
            pass
    return None


def _find_capex_gbp(text: str) -> float | None:
    m = _CAPEX_GBP_RE.search(text)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    suffix = (m.group(2) or "").lower()
    if suffix in ("m", "mn", "million"):
        return val * 1_000_000
    if suffix in ("bn", "billion", "b"):
        return val * 1_000_000_000
    # Bare "£123" — treat as pounds; too ambiguous to guess millions
    return val


def _find_poc_substation(text: str) -> str | None:
    m = _POC_RE.search(text)
    if m:
        return _clean_name(m.group(1))
    m = _SUBSTATION_RE.search(text)
    if m:
        return _clean_name(m.group(1))
    return None


def _find_commissioning_date(text: str) -> date | None:
    # Look for a commissioning hint, then grab the closest date within 80 chars.
    for hit in _COMMISSIONING_HINT_RE.finditer(text):
        window = text[hit.end(): hit.end() + 80]
        iso = _ISO_DATE_RE.search(window)
        if iso:
            try:
                return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            except ValueError:
                pass
        uk = _UK_DATE_RE.search(window)
        if uk:
            return _parse_uk_date(uk)
    return None


def _parse_uk_date(m: re.Match) -> date | None:
    try:
        day = int(m.group(1))
        month = _MONTHS.get(m.group(2).lower())
        year = int(m.group(3))
        if not month:
            return None
        return date(year, month, day)
    except ValueError:
        return None


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _find_counterparty(text: str) -> str | None:
    # Weak signal — look for "Applicant: <name>" / "Developer: <name>".
    m = re.search(
        r"(?:applicant|developer|promoter)\s*[:\-]\s*([A-Z][A-Za-z0-9&,\.\s\-]{3,80}?)(?:[\.\n]|$)",
        text,
    )
    if m:
        return _clean_name(m.group(1))
    return None


def _clean_name(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" ,.-'")


# ── LLM fallback ────────────────────────────────────────────────────────────

async def _llm_extract(text: str, claude) -> dict[str, Any]:
    """Tiny Haiku call — only invoked when regex missed a capacity."""
    prompt = (
        "Extract structured fields from the following UK energy document. "
        "Return a JSON object with any of these keys that are explicitly present: "
        "counterparty (str), capacity_mw (number), poc_substation (str), "
        "capex_gbp (number), commissioning_date (ISO YYYY-MM-DD). "
        "Omit any key that is uncertain. Respond with ONLY the JSON object.\n\n"
        f"Document:\n{text[:4000]}"
    )
    resp = await claude.messages.create(
        model=HAIKU_MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = ""
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            raw = block.text
            break
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw).rstrip("`").strip()
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    # Coerce types where sensible
    out: dict[str, Any] = {}
    for k in ("counterparty", "poc_substation"):
        if parsed.get(k):
            out[k] = str(parsed[k]).strip()
    for k in ("capacity_mw", "capex_gbp"):
        try:
            if parsed.get(k) is not None:
                out[k] = float(parsed[k])
        except (ValueError, TypeError):
            pass
    if parsed.get("commissioning_date"):
        try:
            datetime.fromisoformat(str(parsed["commissioning_date"]))
            out["commissioning_date"] = parsed["commissioning_date"]
        except Exception:
            pass
    return out
