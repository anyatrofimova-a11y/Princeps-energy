"""Render a validated site-memo JSON into a 1-page A4 PDF via Jinja2 + Playwright.

Reuses the ``html_to_pdf`` utility from ``utils.report_renderer`` so we share
the same Chromium launch path used by the long-form reports.
"""

from __future__ import annotations

import logging
import os
import pathlib
from datetime import datetime
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger("princeps.site_memo.renderer")

_TEMPLATES_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "templates"
    / "site_memo"
)
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)

# Output dir — also mounted as static in app/main.py if desired.
MEMO_OUTPUT_DIR = pathlib.Path(
    os.environ.get(
        "SITE_MEMO_OUTPUT_DIR",
        str(pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "site_memos"),
    )
)
MEMO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Number formatting helpers — JetBrains Mono + UK thousand separators
# ---------------------------------------------------------------------------
def _fmt_num(v: Any, digits: int = 1, unit: str = "") -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    s = f"{f:,.{digits}f}"
    return f"{s}{unit}" if unit else s


def _fmt_int(v: Any, unit: str = "") -> str:
    try:
        i = int(round(float(v)))
    except (TypeError, ValueError):
        return "—"
    return f"{i:,}{unit}" if unit else f"{i:,}"


def _fmt_date(v: Any) -> str:
    if not v:
        return "—"
    s = str(v)
    # Trim ISO datetime to date portion.
    return s[:10]


_jinja_env.filters["fnum"] = _fmt_num
_jinja_env.filters["fint"] = _fmt_int
_jinja_env.filters["fdate"] = _fmt_date


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def render_memo_html(memo_json: dict, project: dict | None = None) -> str:
    """Pure string render — used by tests and by the PDF path."""
    project = project or memo_json.get("_project") or {}
    tmpl = _jinja_env.get_template("memo.html.j2")
    return tmpl.render(
        memo=memo_json,
        project=project,
        generated_at=memo_json.get("_generated_at") or datetime.utcnow().isoformat(),
    )


async def render_memo_pdf(
    memo_json: dict,
    project: dict | None = None,
    *,
    filename_hint: str | None = None,
) -> tuple[bytes, pathlib.Path]:
    """Render the memo to A4 portrait PDF. Returns ``(pdf_bytes, saved_path)``."""
    html = render_memo_html(memo_json, project=project)

    # Reuse the existing Chromium path.
    from utils.report_renderer import html_to_pdf

    pdf_bytes = await html_to_pdf(html)

    slug = (filename_hint or memo_json.get("title") or "memo").strip().replace(" ", "_")
    slug = "".join(c for c in slug if c.isalnum() or c in ("_", "-"))[:80] or "memo"
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = MEMO_OUTPUT_DIR / f"{slug}_{ts}.pdf"
    path.write_bytes(pdf_bytes)
    return pdf_bytes, path
