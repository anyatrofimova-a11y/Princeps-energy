"""
Chained agent workflows — run multiple intents sequentially as a single SSE stream.

Each step reuses `run_structured_agent()` unchanged; results from prior steps
are compacted and injected as `prior_analyses` context for downstream steps.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator

from agent import run_structured_agent, _default_actions

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Workflow presets
# ---------------------------------------------------------------------------

WORKFLOW_PRESETS: dict[str, dict[str, Any]] = {
    "full_feasibility": {
        "label": "Full Feasibility",
        "description": "Comprehensive site assessment across all domains",
        "steps": [
            "feasibility",
            "grid_study",
            "environmental",
            "financial",
            "planning",
            "satellite_analysis",
            "bess_optimisation",
        ],
    },
    "grid_deep_dive": {
        "label": "Grid Deep Dive",
        "description": "Grid-constrained site analysis with BESS optimisation",
        "steps": [
            "grid_study",
            "grid_efficiency",
            "bess_optimisation",
            "financial",
        ],
    },
    "investment_ready": {
        "label": "Investment Ready",
        "description": "Investor due-diligence package",
        "steps": [
            "feasibility",
            "grid_study",
            "financial",
            "planning",
            "environmental",
            "legacy_compliance",
            "procurement",
        ],
    },
}


def _compact_step_result(result: dict) -> dict:
    """Shrink an agent result for injection into downstream context."""
    return {
        "intent": result.get("intent"),
        "verdict": result.get("verdict"),
        "confidence": result.get("confidence"),
        "summary": result.get("summary", "")[:300],
        "risks": result.get("risks", [])[:5],
        "opportunities": result.get("opportunities", [])[:5],
        "recommended_capacity_kw": result.get("recommended_capacity_kw"),
        "estimated_roi_years": result.get("estimated_roi_years"),
    }


def _build_workflow_summary(results: dict[str, dict]) -> dict:
    """Aggregate verdicts, confidence, risks, opportunities across all steps."""
    verdicts = {}
    all_risks = []
    all_opportunities = []
    confidences = []

    for intent, result in results.items():
        v = result.get("verdict", "CAUTION")
        verdicts[intent] = v
        confidences.append(result.get("confidence", 0.5))
        all_risks.extend(result.get("risks", [])[:3])
        all_opportunities.extend(result.get("opportunities", [])[:3])

    # Overall verdict: NO-GO if any NO-GO, CAUTION if any CAUTION, else GO
    if "NO-GO" in verdicts.values():
        overall = "NO-GO"
    elif "CAUTION" in verdicts.values():
        overall = "CAUTION"
    else:
        overall = "GO"

    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

    return {
        "overall_verdict": overall,
        "average_confidence": round(avg_confidence, 2),
        "step_verdicts": verdicts,
        "top_risks": list(dict.fromkeys(all_risks))[:8],
        "top_opportunities": list(dict.fromkeys(all_opportunities))[:8],
        "steps_completed": len(results),
    }


async def stream_workflow(
    client,
    model: str,
    base_context: dict[str, Any],
    preset_key: str,
) -> AsyncIterator[str]:
    """
    Async generator that yields SSE events for a chained workflow.

    Events:
      workflow_start  — { preset, steps, total }
      step_start      — { step, index, total, intent }
      step_complete   — { step, index, total, intent, result }
      step_error      — { step, index, total, intent, error }
      workflow_summary — { summary }
      workflow_done    — {}
    """
    preset = WORKFLOW_PRESETS.get(preset_key)
    if not preset:
        yield f"event: error\ndata: {json.dumps({'error': f'Unknown preset: {preset_key}'})}\n\n"
        return

    steps = preset["steps"]
    total = len(steps)
    results: dict[str, dict] = {}
    prior_analyses: list[dict] = []

    yield f"event: workflow_start\ndata: {json.dumps({'preset': preset_key, 'label': preset['label'], 'steps': steps, 'total': total})}\n\n"

    for idx, intent in enumerate(steps):
        step_num = idx + 1
        yield f"event: step_start\ndata: {json.dumps({'step': step_num, 'index': idx, 'total': total, 'intent': intent})}\n\n"

        # Build enriched context with prior analyses
        step_context = {**base_context, "intent": intent}
        if prior_analyses:
            step_context["prior_analyses"] = prior_analyses

        t0 = time.time()
        try:
            result = await run_structured_agent(
                client=client,
                model=model,
                context=step_context,
                intent=intent,
            )
            elapsed = round(time.time() - t0, 2)
            result["elapsed_s"] = elapsed

            # Override actions with server-side defaults
            result["actions"] = _default_actions(intent, base_context)

            results[intent] = result
            prior_analyses.append(_compact_step_result(result))

            yield f"event: step_complete\ndata: {json.dumps({'step': step_num, 'index': idx, 'total': total, 'intent': intent, 'result': result})}\n\n"

        except Exception as exc:
            elapsed = round(time.time() - t0, 2)
            log.warning("Workflow step %s (%s) failed: %s", step_num, intent, exc)
            error_info = {
                "step": step_num,
                "index": idx,
                "total": total,
                "intent": intent,
                "error": str(exc),
                "elapsed_s": elapsed,
            }
            yield f"event: step_error\ndata: {json.dumps(error_info)}\n\n"
            # Continue to next step — don't abort the whole workflow

    # Build and emit summary
    if results:
        summary = _build_workflow_summary(results)
        yield f"event: workflow_summary\ndata: {json.dumps({'summary': summary})}\n\n"

    yield f"event: workflow_done\ndata: {json.dumps({'steps_completed': len(results), 'steps_failed': total - len(results)})}\n\n"
