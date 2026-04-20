"""One-page AI Site Memo generator.

Two-stage pipeline:
  1. ``memo_composer.compose_memo(...)`` -> structured JSON (Claude Sonnet 4.6).
  2. ``memo_renderer.render_memo_pdf(memo_json)`` -> A4 portrait PDF bytes.

Both stages are kept independent so the JSON can be cached and re-rendered
without re-incurring the LLM cost.
"""

from .memo_composer import compose_memo, MEMO_SCHEMA
from .memo_renderer import render_memo_pdf, render_memo_html

__all__ = ["compose_memo", "render_memo_pdf", "render_memo_html", "MEMO_SCHEMA"]
