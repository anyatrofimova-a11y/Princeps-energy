"""
app.reports.report_dno_engagement — DNO Engagement Pack PDF generator.

Pipeline:
    compose_dno_pack(project_id) ─► DnoPackPayload
                                  ├─► render_dno_engagement_html(payload)
                                  └─► html_to_pdf(html) ─► PDF bytes

Reuses the Playwright + A4 pattern from
:mod:`utils.report_grid_connection` — we don't rewrite the PDF pipeline,
we just plug a new template into it.

Jinja environment roots at ``templates/dno_engagement/``. Main template
is ``main.html.j2``.

Cited (entire pack): ENA EREC G99 Issue 2, CCCM v19, ENA EREC P28 / P29,
ENA EREC P2 Issue 7, ENA EREC G5 Issue 5, BS EN ISO 8528-1, NESO SOF.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from utils.dno_engagement import compose_dno_pack, DnoPackPayload

log = logging.getLogger("princeps.reports.dno_engagement")

_TEMPLATES_DIR = (
    Path(__file__).resolve().parent.parent.parent / "templates" / "dno_engagement"
)

# Brand palette — match the rest of the Princeps report suite.
BRAND = {
    "gold": "#D4A018",
    "gold_light": "#E8C54A",
    "gold_dark": "#B88B0E",
    "navy": "#1B365D",
    "teal": "#007A8C",
    "dark": "#1a1a2e",
    "green": "#24a148",
    "amber": "#f1c21b",
    "red": "#da1e28",
    "grey": "#697077",
    "grey_light": "#a8a8a8",
    "light": "#f4f4f4",
    "white": "#ffffff",
}

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml", "j2", "html.j2"]),
)


def _fmt_gbp(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"\u00a3{float(value):,.0f}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_gbp_k(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"\u00a3{float(value) / 1000.0:,.0f}k"
    except (TypeError, ValueError):
        return "N/A"


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def render_dno_engagement_html(payload: DnoPackPayload | dict) -> str:
    """Render the full 16-section HTML."""
    if isinstance(payload, DnoPackPayload):
        p_dict = payload.to_dict()
    else:
        p_dict = dict(payload)

    ctx = {
        "p": p_dict,
        "brand": BRAND,
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "fmt_gbp": _fmt_gbp,
        "fmt_gbp_k": _fmt_gbp_k,
    }
    try:
        template = _jinja_env.get_template("main.html.j2")
        return template.render(**ctx)
    except Exception:
        log.exception("DNO engagement template render failed")
        raise


# ---------------------------------------------------------------------------
# HTML → PDF
# ---------------------------------------------------------------------------
async def html_to_pdf(html_string: str) -> bytes:
    """A4-portrait PDF via Playwright Chromium."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "playwright not installed. Run: pip install playwright && "
            "playwright install chromium"
        )

    tmp = tempfile.NamedTemporaryFile(
        suffix=".html", delete=False, mode="w", encoding="utf-8",
    )
    try:
        tmp.write(html_string)
        tmp.close()
        file_url = f"file://{tmp.name}"
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch()
            except Exception:
                raise RuntimeError(
                    "Chromium not installed. Run: playwright install chromium"
                )
            page = await browser.new_page()
            await page.goto(file_url, wait_until="networkidle", timeout=60000)
            pdf_bytes = await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "0.5in", "bottom": "0.6in",
                        "left": "0.4in", "right": "0.4in"},
            )
            await browser.close()
            return pdf_bytes
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------
async def generate_dno_engagement_pack(
    project_id: str,
    target_dno: str | None = None,
    *,
    conn=None,
    pool=None,
    run_power_flow: bool = True,
) -> tuple[DnoPackPayload, bytes]:
    """
    Full DNO engagement pack — returns (payload, pdf_bytes).

    The payload can be streamed as JSON via ``/preview`` and the PDF via
    ``/pdf``; both endpoints live in :mod:`app.routers.dno_engagement`.
    """
    log.info(
        "Generating DNO engagement pack: project=%s target_dno=%s",
        project_id, target_dno or "auto",
    )
    payload = await compose_dno_pack(
        project_id=project_id,
        target_dno=target_dno,
        conn=conn,
        pool=pool,
        run_power_flow=run_power_flow,
    )
    log.info(
        "Pack composed: verdict=%s, asks=%d, sub_errors=%s",
        payload.executive_verdict,
        len(payload.asks),
        list((payload.sub_module_errors or {}).keys()),
    )

    html = render_dno_engagement_html(payload)
    pdf_bytes = await html_to_pdf(html)
    log.info("DNO engagement pack PDF generated: %d bytes", len(pdf_bytes))
    return payload, pdf_bytes
