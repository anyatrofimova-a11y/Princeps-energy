"""
app/ingestion/classifier.py — topic-tagging for ingested documents.

Two-stage:

  1. **Rule-based trigger regex** — cheap, covers the common UK-energy tags
     (NSIP, NPPF, G99, CMP, CfD, TEC, AR7, EN-1/3/5, etc.). If any regex
     matches, those tags are returned without touching the LLM.

  2. **LLM fallback** (Claude Haiku) — only invoked when the rule set
     produces zero tags. Returns a small, controlled vocabulary of tags.

Topic tags live in ``documents.topic_tags`` (jsonb). Downstream routers
query them via a GIN index.

Budget guardrail: Haiku is ~$4/M output tokens — classify() uses
max_tokens=120 and ~400 input tokens, so ~$0.002/doc worst case.
Workers pre-check ``self.llm_enabled`` to skip the LLM entirely on dry runs.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.ingestion.claude import HAIKU_MODEL

log = logging.getLogger("princeps.ingestion.classifier")


# ── Rule-based triggers ─────────────────────────────────────────────────────
# Each entry: (tag, compiled regex). Regexes are intentionally broad;
# precision is sacrificed for recall because the LLM can refine later.

_RULES: list[tuple[str, re.Pattern]] = [
    # Planning / consenting
    ("nsip",      re.compile(r"\bN\s*S\s*I\s*P\b|nationally[-\s]significant", re.I)),
    ("dco",       re.compile(r"\b(?:DCO|development consent order)\b", re.I)),
    ("nppf",      re.compile(r"\bNPPF\b|national planning policy framework", re.I)),
    ("en-1",      re.compile(r"\bEN[-\s]?1\b|overarching energy npss?", re.I)),
    ("en-3",      re.compile(r"\bEN[-\s]?3\b|renewable energy.+nps", re.I)),
    ("en-5",      re.compile(r"\bEN[-\s]?5\b|electricity networks.+nps", re.I)),
    ("section36", re.compile(r"section\s*36|\bs\.?\s*36\b", re.I)),
    ("s37",       re.compile(r"section\s*37|\bs\.?\s*37\b", re.I)),
    ("appeal",    re.compile(r"\bappeal(?:ed)?\b|planning inspectorate appeal", re.I)),
    ("call_in",   re.compile(r"call[-\s]in(?:ned)?|secretary of state call[-\s]in", re.I)),

    # Grid / connection codes
    ("g99",       re.compile(r"\bG\s*99\b|engineering recommendation 99", re.I)),
    ("g98",       re.compile(r"\bG\s*98\b", re.I)),
    ("tec",       re.compile(r"\bT\s*E\s*C\b|transmission entry capacity", re.I)),
    ("cmp",       re.compile(r"\bCMP\s*\d+|connection and use of system", re.I)),
    ("cusc",      re.compile(r"\bCUSC\b", re.I)),
    ("grid_code", re.compile(r"\bGC\s*\d+|grid code (?:modification|amendment)", re.I)),
    ("stc",       re.compile(r"\bSTC\b|system operator.+transmission owner", re.I)),
    ("bsc",       re.compile(r"\bBSC\s*P\d+|balancing and settlement code", re.I)),
    ("dcusa",     re.compile(r"\bDCUSA\b|distribution connection.+use of system", re.I)),
    ("tmo4plus",  re.compile(r"TMO4\+?|target model option 4", re.I)),
    ("gate2",     re.compile(r"\bGate\s*2\b", re.I)),

    # Market mechanisms
    ("cfd",       re.compile(r"\bCfD\b|contracts? for difference|AR[\s-]?\d", re.I)),
    ("ar7",       re.compile(r"\bAR\s*7\b|allocation round 7", re.I)),
    ("ar6",       re.compile(r"\bAR\s*6\b|allocation round 6", re.I)),
    ("cm",        re.compile(r"\bcapacity market\b", re.I)),
    ("rema",      re.compile(r"\bREMA\b|review of electricity market arrangements", re.I)),
    ("ppa",       re.compile(r"\bPPA\b|power purchase agreement", re.I)),

    # Regulatory / industry
    ("riio",      re.compile(r"\bRIIO[-\s]?(?:T|ED|GD)?\d?\b", re.I)),
    ("ofgem",     re.compile(r"\bOfgem\b", re.I)),
    ("desnz",     re.compile(r"\bDESNZ\b|department for energy security", re.I)),
    ("neso",      re.compile(r"\bNESO\b|national energy system operator", re.I)),
    ("nged",      re.compile(r"\bNGED\b|national grid electricity distribution", re.I)),

    # Tech / assets
    ("solar",     re.compile(r"\bsolar\b|photovoltaic|PV[\s-]?(?:plant|farm)", re.I)),
    ("bess",      re.compile(r"\bBESS\b|battery (?:energy )?storage|grid-scale battery", re.I)),
    ("wind",      re.compile(r"\bwind (?:farm|turbine|park)\b", re.I)),
    ("offshore",  re.compile(r"\boffshore\b", re.I)),
    ("onshore",   re.compile(r"\bonshore\b", re.I)),
    ("hydrogen",  re.compile(r"\bhydrogen\b|H2 (?:production|electrolyser)", re.I)),
    ("data_centre", re.compile(r"data[-\s]?centre|data[-\s]?center|\bDC\b(?!\s*\d)", re.I)),
    ("interconnector", re.compile(r"interconnector\b", re.I)),
    ("nuclear",   re.compile(r"\bnuclear\b|SMR\b", re.I)),

    # Environmental
    ("bng",       re.compile(r"\bBNG\b|biodiversity net gain", re.I)),
    ("eia",       re.compile(r"\bEIA\b|environmental impact assessment|scoping opinion", re.I)),
    ("habitats",  re.compile(r"habitats regulations assessment|HRA\b", re.I)),

    # Incidents / safety
    ("comah",     re.compile(r"\bCOMAH\b|control of major accident hazards", re.I)),
    ("battery_fire", re.compile(r"battery fire|thermal runaway|BESS (?:fire|incident)", re.I)),
]


# Tags that the LLM may return as fallback. Kept small so the model
# doesn't invent tags that never hit the GIN index.
_LLM_VOCAB = [
    "planning", "consenting", "grid_connection", "code_modification",
    "cfd_round", "capacity_market", "riio", "rema", "tariffs", "standards",
    "incident", "procurement", "market_intel", "policy", "misc",
]


async def classify_document(
    text: str,
    *,
    claude=None,
    source: str = "",
) -> list[str]:
    """
    Return a list of topic tags for the given text.

    Args:
        text: title + body_text concatenation (truncated upstream)
        claude: optional AsyncAnthropic client; when ``None`` the function
                stays rule-based only.
        source: ingestion source slug (ofgem / pins_nsip / ...), included
                in the LLM prompt as a hint.
    """
    if not text:
        return []

    tags: set[str] = set()
    lower_snippet = text[:16_000]
    for tag, pattern in _RULES:
        if pattern.search(lower_snippet):
            tags.add(tag)

    if tags or claude is None:
        return sorted(tags)

    # ── LLM fallback (Haiku) ─────────────────────────────────────────────
    try:
        prompt = _llm_prompt(text, source)
        resp = await claude.messages.create(
            model=HAIKU_MODEL,
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = ""
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                raw = block.text
                break
        tags = _parse_llm_tags(raw)
    except Exception as e:
        log.warning("classifier LLM fallback failed: %s", e)
        return []

    return sorted(tags)


async def classify_batch(
    texts: list[str],
    *,
    claude=None,
    source: str = "",
    batch_size: int = 20,
) -> list[list[str]]:
    """
    Batched classifier — one LLM call per ``batch_size`` docs to minimise cost.

    Currently delegates to :func:`classify_document` per-item because the
    rule stage is already batch-trivial. Reserved shape for a future
    multi-doc prompt (single LLM call, parsed JSON list).
    """
    out: list[list[str]] = []
    for t in texts:
        out.append(await classify_document(t, claude=claude, source=source))
    return out


# ── Internals ────────────────────────────────────────────────────────────────

def _llm_prompt(text: str, source: str) -> str:
    vocab = ", ".join(_LLM_VOCAB)
    snippet = text[:4000]
    return (
        "You are classifying a UK energy-sector document. Return a JSON "
        "array of 1-3 tags drawn ONLY from this vocabulary: "
        f"[{vocab}].\n\n"
        f"Source: {source or 'unknown'}\n\n"
        f"Document:\n{snippet}\n\n"
        "Respond with ONLY the JSON array."
    )


def _parse_llm_tags(raw: str) -> set[str]:
    raw = (raw or "").strip()
    # Strip common code-fence decorations
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw).rstrip("`").strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return {str(t).strip().lower() for t in parsed if t and isinstance(t, str)}
    except Exception:
        pass
    # Very defensive fallback: split on commas
    return {t.strip().lower() for t in raw.split(",") if t.strip()}
