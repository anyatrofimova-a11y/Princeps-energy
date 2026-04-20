"""AI fallback for site enrichment fields.

Used only for fields that a free UK API could not resolve. Typical use case:
postcodes.io is momentarily rate-limited / down, and we want a best-guess LPA
name from what we already have (e.g. a postcode district or a parliamentary
constituency). Do NOT call this for fields an API successfully returned —
deterministic API results are always preferred.

The AI path marks provenance as ``ai_inferred`` with a confidence of 0.6
so the 1APP renderer can flag the field as pending-review.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger("princeps.site_enrichment.ai")

MODEL = os.getenv("PRINCEPS_SITE_ENRICHMENT_MODEL", "claude-3-5-haiku-20241022")


async def _get_anthropic_client():
    """Return an AsyncAnthropic client or None if the SDK / key is missing."""
    try:
        import anthropic
    except ImportError:
        return None
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.AsyncAnthropic(api_key=api_key)


_PROMPT = """You are a UK planning data assistant. Given a WGS84 coordinate and
optional context hints, return best-guess values for the requested fields as a
single JSON object. Use official UK local-government naming (e.g. "City of
Westminster", not "Westminster"). If you are uncertain, return null for that
field.

Coordinate: lat={lat}, lon={lon}
Context hints (may be partial or empty):
{hints}

Required JSON schema:
{{
  "postcode": "<nearest UK postcode, or null>",
  "local_planning_authority": "<LPA name, or null>",
  "parish": "<civil parish, or 'unparished area', or null>",
  "ward": "<electoral ward name, or null>"
}}

Return ONLY the JSON object, no commentary.
"""


async def ai_fill_missing(enrichment, *, pc_hint: Optional[dict[str, Any]] = None) -> None:
    """Fill any ``None`` fields on ``enrichment`` using Claude, marking each
    AI-filled value with provenance ``source="ai_inferred"``.

    Side-effects only; no return value. Silently no-ops if the Anthropic SDK
    or API key is unavailable.
    """
    from utils.site_enrichment import EnrichedField, _provenance

    missing = {
        "postcode": enrichment.postcode.value in (None, ""),
        "local_planning_authority": enrichment.local_planning_authority.value in (None, ""),
        "parish": enrichment.parish.value in (None, ""),
        "ward": enrichment.ward.value in (None, ""),
    }
    if not any(missing.values()):
        return

    client = await _get_anthropic_client()
    if client is None:
        log.info("ai_fill_missing: Anthropic client unavailable (SDK or key missing)")
        return

    hints = {
        "postcode_hint": (pc_hint or {}).get("postcode"),
        "outcode_hint": (pc_hint or {}).get("outcode"),
        "region": (pc_hint or {}).get("region"),
        "admin_district": (pc_hint or {}).get("admin_district"),
        "parliamentary_constituency": (pc_hint or {}).get("parliamentary_constituency"),
    }
    prompt = _PROMPT.format(
        lat=enrichment.lat, lon=enrichment.lon,
        hints=json.dumps(hints, indent=2),
    )

    try:
        resp = await client.messages.create(
            model=MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        log.info("ai_fill_missing: API call failed: %s", e)
        return

    try:
        body = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        # Claude sometimes wraps JSON in ```json fences despite instruction
        body = body.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(body)
    except Exception as e:
        log.info("ai_fill_missing: response parse failed: %s body=%s", e, body[:200] if 'body' in locals() else '<empty>')
        return

    if missing["postcode"] and data.get("postcode"):
        enrichment.postcode = EnrichedField(
            value=data["postcode"],
            provenance=_provenance("ai_inferred", method="ai_fallback", confidence=0.6),
        )
    if missing["local_planning_authority"] and data.get("local_planning_authority"):
        enrichment.local_planning_authority = EnrichedField(
            value=data["local_planning_authority"],
            provenance=_provenance("ai_inferred", method="ai_fallback", confidence=0.6),
        )
    if missing["parish"] and data.get("parish"):
        enrichment.parish = EnrichedField(
            value=data["parish"],
            provenance=_provenance("ai_inferred", method="ai_fallback", confidence=0.55),
        )
    if missing["ward"] and data.get("ward"):
        enrichment.ward = EnrichedField(
            value=data["ward"],
            provenance=_provenance("ai_inferred", method="ai_fallback", confidence=0.55),
        )
