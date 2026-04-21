"""
app.routers.dno_engagement — DNO Engagement Pack HTTP endpoints (Task #18).

Endpoints
---------
POST /api/reports/dno-engagement-pack/{project_id}
    Orchestrates the full pack — returns preview_json + pack_version
    (body: optional {"target_dno": "SSEN"}).

GET  /api/reports/dno-engagement-pack/{project_id}/preview
    Lightweight JSON preview (no PDF generation).

POST /api/reports/dno-engagement-pack/{project_id}/pdf
    Full PDF stream (A4 portrait).

POST /api/reports/dno-engagement-pack/{project_id}/send
    Email the generated pack to an addressee with a covering letter.
    Body: {recipient_email, covering_letter}.

The workflow DB schema (``project_dno_engagements``) is owned by a
sibling agent (Task #20); this router does NOT read or write to it.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field

from app.deps import get_pool
from utils.dno_engagement import compose_dno_pack
from app.reports.report_dno_engagement import (
    generate_dno_engagement_pack,
    render_dno_engagement_html,
    html_to_pdf,
)

log = logging.getLogger("princeps.dno_engagement_router")
router = APIRouter(tags=["dno_engagement"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class PackRequest(BaseModel):
    target_dno: str | None = Field(
        default=None,
        description="Canonical DNO code (SSEN/UKPN/NGED/SPEN/NPG/ENWL/NIE). "
                    "If None, auto-resolves from project location.",
    )
    run_power_flow: bool = Field(
        default=True,
        description="Run Tier 2 pandapower N/N-1 (set False for preview speed).",
    )


class PackResponse(BaseModel):
    project_id: str
    pack_version: str
    preview_json: dict[str, Any]


class SendRequest(BaseModel):
    recipient_email: EmailStr
    covering_letter: str = Field(
        default="",
        description="Free-text covering note prepended to the pack email body.",
    )
    target_dno: str | None = None


def _safe_filename(name: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "-")
    return clean[:60] or "dno-pack"


# ---------------------------------------------------------------------------
# POST /api/reports/dno-engagement-pack/{project_id}
# ---------------------------------------------------------------------------
@router.post(
    "/api/reports/dno-engagement-pack/{project_id}",
    response_model=PackResponse,
)
async def api_generate_pack(
    project_id: str,
    body: PackRequest | None = None,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Compose the full pack and return preview JSON + version."""
    body = body or PackRequest()
    try:
        async with pool.acquire() as conn:
            payload = await compose_dno_pack(
                project_id=project_id,
                target_dno=body.target_dno,
                conn=conn,
                pool=pool,
                run_power_flow=body.run_power_flow,
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.exception("DNO engagement pack compose failed")
        raise HTTPException(
            status_code=500,
            detail=f"DNO engagement pack compose failed: {e}",
        )

    return PackResponse(
        project_id=project_id,
        pack_version=payload.pack_version,
        preview_json=payload.to_dict(),
    )


# ---------------------------------------------------------------------------
# GET /api/reports/dno-engagement-pack/{project_id}/preview
# ---------------------------------------------------------------------------
@router.get("/api/reports/dno-engagement-pack/{project_id}/preview")
async def api_preview_pack(
    project_id: str,
    target_dno: str | None = None,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Fast JSON preview — skips the Tier 2 subprocess so the constraint
    envelope degrades gracefully to a ``success=False`` stub. Useful
    for front-end rendering while the full pack is being assembled.
    """
    try:
        async with pool.acquire() as conn:
            payload = await compose_dno_pack(
                project_id=project_id,
                target_dno=target_dno,
                conn=conn,
                pool=pool,
                run_power_flow=False,
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.exception("DNO engagement pack preview failed")
        raise HTTPException(
            status_code=500,
            detail=f"DNO engagement pack preview failed: {e}",
        )

    return JSONResponse(payload.to_dict())


# ---------------------------------------------------------------------------
# POST /api/reports/dno-engagement-pack/{project_id}/pdf
# ---------------------------------------------------------------------------
@router.post("/api/reports/dno-engagement-pack/{project_id}/pdf")
async def api_pack_pdf(
    project_id: str,
    body: PackRequest | None = None,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate and stream the A4 PDF."""
    body = body or PackRequest()
    try:
        async with pool.acquire() as conn:
            payload, pdf_bytes = await generate_dno_engagement_pack(
                project_id=project_id,
                target_dno=body.target_dno,
                conn=conn,
                pool=pool,
                run_power_flow=body.run_power_flow,
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        log.exception("DNO engagement pack PDF generation failed")
        raise HTTPException(
            status_code=500,
            detail=f"DNO engagement pack PDF generation failed: {e}",
        )

    filename = (
        f"princeps-dno-pack-"
        f"{_safe_filename(payload.project_name or project_id)}.pdf"
    )
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Pack-Version": payload.pack_version,
        },
    )


# ---------------------------------------------------------------------------
# POST /api/reports/dno-engagement-pack/{project_id}/send
# ---------------------------------------------------------------------------
@router.post("/api/reports/dno-engagement-pack/{project_id}/send")
async def api_pack_send(
    project_id: str,
    body: SendRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Generate the pack and dispatch it to ``recipient_email`` with the
    supplied covering letter. Uses the repo's existing email helper if
    available; otherwise returns a 501 with a clear error so the caller
    can fall back to manual attach.
    """
    try:
        async with pool.acquire() as conn:
            payload, pdf_bytes = await generate_dno_engagement_pack(
                project_id=project_id,
                target_dno=body.target_dno,
                conn=conn,
                pool=pool,
                run_power_flow=True,
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.exception("DNO engagement pack PDF generation failed (send path)")
        raise HTTPException(
            status_code=500,
            detail=f"DNO engagement pack PDF generation failed: {e}",
        )

    # Attempt to send via the existing outbound email helper. Fall back to
    # a structured 501 if no SMTP is configured — the caller then knows to
    # download + attach manually.
    try:
        from utils.email_dispatcher import send_email_with_attachment  # type: ignore
        await send_email_with_attachment(
            to=body.recipient_email,
            subject=(
                f"Princeps DNO Engagement Pack — {payload.project_name} "
                f"(v{payload.pack_version})"
            ),
            body=(
                (body.covering_letter or "").strip()
                + "\n\n---\nAttached: DNO Engagement Pack\n"
                  f"Generated: {payload.generated_at}\n"
                  f"Target DNO: {payload.target_dno or 'auto-resolved'}\n"
                  f"Verdict: {payload.executive_verdict}\n"
            ),
            attachment_name=(
                f"princeps-dno-pack-"
                f"{_safe_filename(payload.project_name or project_id)}.pdf"
            ),
            attachment_bytes=pdf_bytes,
            attachment_mime="application/pdf",
        )
        dispatched = True
        detail = "sent"
    except ImportError:
        dispatched = False
        detail = (
            "No outbound email helper configured — pack generated but not "
            "dispatched. Download via /pdf and attach manually."
        )
    except Exception as e:  # noqa: BLE001
        dispatched = False
        detail = f"Email dispatch failed: {e}"
        log.exception("DNO engagement pack email dispatch failed")

    return JSONResponse(
        {
            "project_id": project_id,
            "recipient_email": body.recipient_email,
            "dispatched": dispatched,
            "pack_version": payload.pack_version,
            "pdf_bytes": len(pdf_bytes),
            "detail": detail,
        },
        status_code=200 if dispatched else 202,
    )
