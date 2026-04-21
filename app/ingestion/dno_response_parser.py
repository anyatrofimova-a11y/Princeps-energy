"""
app/ingestion/dno_response_parser.py — Claude-driven structured extraction
from an uploaded DNO response (email body or PDF).

Input: either the raw email body (as text) or a path to a PDF that has
already been downloaded to local disk. PDF text extraction uses pypdf if
available — otherwise the route degrades to "raw text unavailable" and
the parser works from whatever metadata it has.

Output: a compact dict that slots directly into the `structured_extract`
jsonb column on ``dno_engagement_responses``. The schema is consumed by
the ``get_dno_engagement_status`` agent tool (``app/dockets/dno_engagement_tool.py``)
and must stay stable — version it via an ``_schema_version`` field if
a breaking change is ever required.

Output shape:

    {
      "_schema_version": 1,
      "sentiment": "positive" | "conditional" | "negative"
                  | "holding" | "silent" | "unknown",
      "requested_info": [str],           # items the DNO has asked for
      "proposed_poc": {                   # optional — their counter-POC
          "sub_id":     str | null,
          "name":       str | null,
          "voltage_kv": int | null
      } | null,
      "firm_split_delta": number | null,  # MW moved firm → non-firm
      "timeline_revision": {              # optional — new date vs original
          "new_energisation_date": str | null,  # ISO
          "days_delta":            int | null,   # +ve = later
          "rationale":             str | null
      } | null,
      "deadlines": [                      # items WE have to do by a date
          {"label": str, "due_at": str}   # ISO or natural text
      ],
      "sentiment_reason": str,            # ≤160 chars
      "raw_excerpt": str                  # ≤400 chars verbatim snippet
    }

The parser is explicitly defensive: the DNO may reply with anything from
a one-line "acknowledged — 90 days to respond" through to a 40-page
connection offer. We don't retry, we don't re-read PDFs on failure, we
just return whatever came back even if partial.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger("princeps.ingestion.dno_response_parser")


# Keep on Haiku — responses are short, the extraction is structured,
# and cost per call matters at scale. If we see the sibling engine
# start producing multi-thousand-word responses we can upgrade to
# Sonnet, but not today.
_HAIKU_MODEL = os.getenv("DNO_PARSER_MODEL", "claude-haiku-4-5")

_MAX_INPUT_CHARS = 40_000  # ~10k tokens — hard cap on combined text


# ---------------------------------------------------------------------------
# Extraction prompt — kept terse because Haiku follows "please extract"
# instructions well and doesn't need chain-of-thought scaffolding.
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You extract structured data from UK DNO connection-offer responses. "
    "Input is plain text (email body or PDF text). Output STRICTLY a single "
    "valid JSON object with the schema described in the user message. "
    "Never include commentary, markdown fences, or trailing text. If a "
    "field can't be determined from the source, use null (object/number "
    "fields) or [] (array fields). Do not invent values. Be concise."
)


_SCHEMA_EXAMPLE = {
    "_schema_version": 1,
    "sentiment": "conditional",
    "sentiment_reason": "Accepts in principle but moves 8 MW to non-firm",
    "requested_info": [
        "Updated load profile including diurnal shape",
        "Confirmation of LFM contribution",
    ],
    "proposed_poc": {
        "sub_id": None,
        "name": "Bishop's Stortford 33kV",
        "voltage_kv": 33,
    },
    "firm_split_delta": -8.0,
    "timeline_revision": {
        "new_energisation_date": "2028-09-01",
        "days_delta": 180,
        "rationale": "Requires BSP transformer uplift",
    },
    "deadlines": [
        {"label": "Supply updated load profile", "due_at": "2026-05-15"},
    ],
    "raw_excerpt": "...we can offer firm 22 MW and non-firm 8 MW...",
}


def _user_prompt(source_text: str) -> str:
    schema_json = json.dumps(_SCHEMA_EXAMPLE, indent=2)
    return (
        "Extract structured data from this UK DNO response. Output MUST match "
        "this exact JSON shape (example shown, values will differ):\n\n"
        f"```json\n{schema_json}\n```\n\n"
        "Rules:\n"
        "- `sentiment` is one of: positive, conditional, negative, holding, silent, unknown. "
        "Use 'holding' for pure acknowledgements (e.g. '90-day response window confirmed'). "
        "Use 'silent' only if there's no substantive content.\n"
        "- `firm_split_delta` is in MW: negative = moved firm → non-firm, positive = moved "
        "non-firm → firm. Null if the response doesn't discuss firm vs non-firm.\n"
        "- `timeline_revision.days_delta` is days relative to the most recent prior energisation "
        "date we asked for. Positive = the DNO is proposing a later date. Null if unchanged.\n"
        "- `raw_excerpt` must be a verbatim snippet ≤400 chars — no paraphrasing.\n"
        "- Output ONLY the JSON object, nothing else.\n\n"
        "Source text:\n"
        "--- BEGIN ---\n"
        f"{source_text}\n"
        "--- END ---"
    )


# ---------------------------------------------------------------------------
# PDF text extraction — best-effort, degrades gracefully.
# ---------------------------------------------------------------------------

def _extract_pdf_text(path: str) -> str:
    """Return concatenated text from a PDF, or an empty string on any failure."""
    try:
        import pypdf  # type: ignore
    except Exception:
        log.debug("pypdf not installed — PDF text extraction unavailable")
        return ""
    try:
        reader = pypdf.PdfReader(path)
        chunks: list[str] = []
        for page in reader.pages:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(chunks).strip()
    except Exception as e:
        log.warning("PDF text extraction failed for %s: %s", path, e)
        return ""


# ---------------------------------------------------------------------------
# JSON extraction from Claude output
# ---------------------------------------------------------------------------

def _parse_first_json_object(text: str) -> dict[str, Any]:
    """Extract the first balanced JSON object. Tolerates fences + prose."""
    if not text:
        raise ValueError("empty response from Claude")
    # Strip common fenced-code wrappers
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.lstrip()
            if part.startswith("json"):
                part = part[4:]
            if part.strip().startswith("{"):
                text = part
                break
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("no JSON object found in Claude response")
    return json.loads(text[start:end])


def _coerce_schema(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise Claude's output against the expected schema. Missing fields
    get safe defaults. Extra fields are dropped (forward-compat left to the
    consumer)."""
    out: dict[str, Any] = {
        "_schema_version": 1,
        "sentiment": (raw.get("sentiment") or "unknown"),
        "sentiment_reason": (raw.get("sentiment_reason") or "")[:160],
        "requested_info": [],
        "proposed_poc": None,
        "firm_split_delta": None,
        "timeline_revision": None,
        "deadlines": [],
        "raw_excerpt": (raw.get("raw_excerpt") or "")[:400],
    }
    allowed_sentiments = {"positive", "conditional", "negative",
                          "holding", "silent", "unknown"}
    if out["sentiment"] not in allowed_sentiments:
        out["sentiment"] = "unknown"

    req = raw.get("requested_info")
    if isinstance(req, list):
        out["requested_info"] = [str(x) for x in req if x]

    poc = raw.get("proposed_poc")
    if isinstance(poc, dict):
        try:
            v_kv = poc.get("voltage_kv")
            v_kv = int(v_kv) if v_kv is not None else None
        except (TypeError, ValueError):
            v_kv = None
        out["proposed_poc"] = {
            "sub_id": poc.get("sub_id"),
            "name":   poc.get("name"),
            "voltage_kv": v_kv,
        }

    fsd = raw.get("firm_split_delta")
    if isinstance(fsd, (int, float)):
        out["firm_split_delta"] = float(fsd)

    tr = raw.get("timeline_revision")
    if isinstance(tr, dict):
        try:
            dd = tr.get("days_delta")
            dd = int(dd) if dd is not None else None
        except (TypeError, ValueError):
            dd = None
        out["timeline_revision"] = {
            "new_energisation_date": tr.get("new_energisation_date"),
            "days_delta": dd,
            "rationale":  tr.get("rationale"),
        }

    deadlines = raw.get("deadlines")
    if isinstance(deadlines, list):
        out["deadlines"] = [
            {
                "label":  str(d.get("label", "")),
                "due_at": d.get("due_at"),
            }
            for d in deadlines
            if isinstance(d, dict) and d.get("label")
        ]

    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def parse_dno_response(
    *,
    claude: Any,
    raw_body: str | None = None,
    raw_pdf_path: str | None = None,
    model: str = _HAIKU_MODEL,
) -> dict[str, Any]:
    """Parse a DNO response into the Princeps structured-extract schema.

    Args:
        claude: AsyncAnthropic client (``app.state.claude``). Pass None if
            you want to force the fallback path.
        raw_body: Email body text or already-extracted PDF text.
        raw_pdf_path: Path to the PDF — only read if ``raw_body`` is empty
            AND pypdf is installed.
        model: Claude model; defaults to Haiku for cost.

    Returns:
        A dict conforming to the schema documented at module level.

    Raises:
        ValueError: if neither raw_body nor raw_pdf_path is supplied.
    """
    source_text = raw_body or ""
    if not source_text and raw_pdf_path:
        source_text = _extract_pdf_text(raw_pdf_path)
    if not source_text:
        raise ValueError("no source text — raw_body and raw_pdf_path both empty/unreadable")

    # Clip hard — Claude sees a trimmed tail marker so it knows we truncated.
    if len(source_text) > _MAX_INPUT_CHARS:
        source_text = source_text[:_MAX_INPUT_CHARS] + "\n[…truncated…]"

    # Graceful fallback when Claude isn't wired (CI / tests / rotated key).
    if claude is None:
        log.warning("parse_dno_response: no Claude client — returning minimal stub")
        return _coerce_schema({
            "sentiment": "unknown",
            "sentiment_reason": "llm_unavailable",
            "raw_excerpt": source_text[:400],
        })

    try:
        message = await claude.messages.create(
            model=model,
            max_tokens=1500,
            temperature=0.0,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _user_prompt(source_text)}],
        )
        text = message.content[0].text if message.content else ""
        raw = _parse_first_json_object(text)
        return _coerce_schema(raw)
    except Exception as e:
        log.warning("Claude parse failed: %s — falling back to stub", e)
        return _coerce_schema({
            "sentiment": "unknown",
            "sentiment_reason": f"parse_failed: {str(e)[:80]}",
            "raw_excerpt": source_text[:400],
        })


__all__ = ["parse_dno_response"]
