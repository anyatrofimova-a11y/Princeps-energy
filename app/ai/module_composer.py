"""Workshop module composer — Claude turns a prompt into a manifest dict.

Public API:
    async def compose_manifest(claude, prompt, target_type) -> dict

The manifest shape is enforced by the `Manifest` Pydantic model. We pass the
two DTDL schemas (data_centre + bess_unit) into the system prompt so Claude
binds widgets only to fields that exist. No emojis, no prose, no fences in
output — strict JSON.

Caps: ≤180 lines. No drag-drop. No charting libs.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.helpers import CLAUDE_MODEL

log = logging.getLogger("princeps.ai.module_composer")

# ---------------------------------------------------------------------------
# DTDL load — module-level cache so we don't read disk per request.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DTDL_DIR = _REPO_ROOT / "ontology" / "dtdl"


def _load_dtdl(name: str) -> dict[str, Any]:
    p = _DTDL_DIR / f"{name}.json"
    try:
        return json.loads(p.read_text())
    except Exception as exc:  # pragma: no cover — surfaced to callers below
        log.warning("DTDL %s missing or invalid: %s", name, exc)
        return {}


_DTDL_DC = _load_dtdl("data_centre")
_DTDL_BESS = _load_dtdl("bess_unit")


def _dtdl_field_names(dtdl: dict[str, Any]) -> list[str]:
    """Flat list of property/telemetry/component names — for the prompt."""
    out: list[str] = []
    for c in dtdl.get("contents", []) or []:
        n = c.get("name")
        if n:
            out.append(n)
    return out


# ---------------------------------------------------------------------------
# Manifest schema — strict but minimal.
# ---------------------------------------------------------------------------
ALLOWED_KINDS = {"ObjectCard", "ObjectTable", "Chart", "Map", "Markdown", "ActionButton"}


class Variable(BaseModel):
    name: str
    kind: Literal["object_set", "single_object", "primitive"]
    type: str | None = None


class Widget(BaseModel):
    id: str
    kind: str
    # Composer sometimes 0-indexes; we accept either and clamp at render.
    col: int = Field(ge=0, le=12)
    row: int | None = None
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=1, le=24, default=1)
    props: dict[str, Any] = Field(default_factory=dict)
    bindings: dict[str, Any] = Field(default_factory=dict)


class Layout(BaseModel):
    type: Literal["grid"] = "grid"
    cols: int = 12


class Manifest(BaseModel):
    slug: str
    title: str
    target_type: str | None = None
    layout: Layout = Field(default_factory=Layout)
    variables: list[Variable] = Field(default_factory=list)
    widgets: list[Widget] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Compose — single Claude call, JSON-only output.
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """You are Princeps Workshop Composer. Given a user request and the DTDL schemas below, output a JSON manifest matching this exact shape: {slug, title, target_type, layout: {type:'grid',cols:12}, variables:[{name, kind:'object_set'|'single_object'|'primitive', type?}], widgets:[{id, kind, col, row, w, h, props, bindings}]}. Allowed widget kinds: ObjectCard, ObjectTable, Chart, Map, Markdown, ActionButton. Bindings reference variables via ${variable.field} template syntax. Bind only to fields that exist in the DTDL. Output JSON only — no prose, no code fences."""


def _build_user_prompt(prompt: str, target_type: str | None) -> str:
    parts = [f"User request: {prompt.strip()}"]
    if target_type:
        parts.append(f"Target type: {target_type}")
    parts.append("\n--- DTDL: data_centre ---")
    parts.append(f"Fields: {', '.join(_dtdl_field_names(_DTDL_DC)) or '(none)'}")
    parts.append("\n--- DTDL: bess_unit ---")
    parts.append(f"Fields: {', '.join(_dtdl_field_names(_DTDL_BESS)) or '(none)'}")
    parts.append("\nReturn the manifest JSON only.")
    return "\n".join(parts)


_FENCE_RX = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _FENCE_RX.sub("", text).strip()


async def compose_manifest(
    claude,
    prompt: str,
    target_type: str | None = None,
) -> dict[str, Any]:
    """Single-shot Claude composition. Raises ValueError on invalid output."""
    if not prompt or not prompt.strip():
        raise ValueError("prompt is required")

    model = os.environ.get("WORKSHOP_COMPOSER_MODEL", CLAUDE_MODEL)
    user_msg = _build_user_prompt(prompt, target_type)

    try:
        resp = await claude.messages.create(
            model=model,
            max_tokens=2000,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:
        log.exception("Claude composer call failed")
        raise ValueError(f"composer call failed: {type(exc).__name__}: {exc}") from exc

    text_blocks = [b.text for b in (resp.content or []) if getattr(b, "type", None) == "text"]
    raw = _strip_fences("".join(text_blocks))
    if not raw:
        raise ValueError("composer returned empty content")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("composer non-JSON output: %s", raw[:400])
        raise ValueError(f"composer returned non-JSON: {exc}") from exc

    try:
        manifest = Manifest.model_validate(data)
    except ValidationError as exc:
        log.warning("composer invalid manifest: %s", exc)
        raise ValueError(f"composer manifest failed validation: {exc}") from exc

    bad = [w.kind for w in manifest.widgets if w.kind not in ALLOWED_KINDS]
    if bad:
        raise ValueError(f"unknown widget kinds: {bad}")

    return manifest.model_dump(mode="json")
