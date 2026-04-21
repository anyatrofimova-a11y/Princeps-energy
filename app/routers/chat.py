"""Chat router — conversational AI panel with SSE streaming."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import asyncpg

import chat as chat_module
from app.deps import get_pool, get_claude
from app.helpers import (
    CLAUDE_MODEL,
    run_sam_subprocess, run_geeflow_subprocess, run_geoai_subprocess,
    fetch_parcel_context,
)

router = APIRouter(tags=["chat"])


class ChatSessionRequest(BaseModel):
    parcel_id: str | None = None
    # BOT-CHC 2026-04-19 — frontend was silently dropping project_id because
    # the model omitted it; session then had no idea which project it was
    # born under. Now persisted on ChatSession.project_id for every turn.
    project_id: str | None = None


class ChatMessageRequest(BaseModel):
    message: str
    # Legacy flat UI context (workspace/view/pathname/focus + free-form keys).
    # BOT-CHC 2026-04-19: the new nested `page_context` block lives inside
    # `context.page_context` — see lib/pageContext.js for the wire shape.
    context: dict | None = None


@router.post("/chat/session")
async def create_chat_session(
    body: ChatSessionRequest = ChatSessionRequest(),
    pool = Depends(get_pool),
):
    """Create a new chat session, optionally linked to a parcel + project."""
    session = chat_module.create_session(
        parcel_id=body.parcel_id,
        project_id=body.project_id,
    )
    # Pre-fetch a project summary so even turn-1 system prompt knows name,
    # technology, capacity, stage, DNO, TEC — before any page_context lands.
    if body.project_id:
        try:
            await chat_module.hydrate_project_summary(session, body.project_id, pool)
        except Exception:
            # Summary is a nice-to-have; never block session creation.
            pass
    return {
        "session_id": session.id,
        "parcel_id": session.parcel_id,
        "project_id": session.project_id,
    }


@router.post("/chat/{session_id}/message")
async def chat_message(
    session_id: str,
    body: ChatMessageRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    claude=Depends(get_claude),
):
    """Stream a chat response as SSE events (text deltas, tool calls, map layers)."""
    session = chat_module.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    return StreamingResponse(
        chat_module.stream_chat_response(
            session,
            body.message,
            client=claude,
            model=CLAUDE_MODEL,
            pool=pool,
            run_sam_subprocess=run_sam_subprocess,
            fetch_parcel_context=fetch_parcel_context,
            run_geeflow_subprocess=run_geeflow_subprocess,
            run_geoai_subprocess=run_geoai_subprocess,
            ui_context=body.context,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/{session_id}/upload")
async def chat_upload(session_id: str, file: UploadFile):
    """Upload a file (CSV, Excel, PDF) to a chat session for analysis."""
    session = chat_module.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:  # 20 MB limit
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")

    filename = file.filename or "upload"
    summary = chat_module.parse_uploaded_file(filename, content)
    session.uploaded_files.append({
        "filename": filename,
        "content_bytes": content,
        "summary": summary,
        "type": summary.get("type", "unknown"),
        "size_bytes": len(content),
    })

    return {
        "filename": filename,
        "size": len(content),
        "type": summary.get("type", "unknown"),
        "summary": summary,
    }
