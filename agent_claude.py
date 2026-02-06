# agent_claude.py
import os
import json
import logging
import requests
from jsonschema import validate, ValidationError

log = logging.getLogger(__name__)

# Expected JSON schema returned by the LLM agent (strict)
AGENT_SCHEMA = {
    "type": "object",
    "required": ["parcel_id", "positioning_score", "summary", "recommendations", "confidence"],
    "properties": {
        "parcel_id": {"type": "string"},
        "positioning_score": {"type": "number", "minimum": 0, "maximum": 100},
        "summary": {"type": "string"},
        "recommendations": {
            "type": "array",
            "items": {"type": "string"}
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}
    },
    "additionalProperties": False
}

def build_claude_prompt(context: dict) -> str:
    """
    Build the Claude prompt text from structured context. This version instructs the model
    to return ONLY JSON, matching AGENT_SCHEMA semantics.
    """
    template = """
You are a renewable energy project feasibility assistant. Given the structured parcel data below,
produce EXACTLY one JSON object matching the schema:

{
  "parcel_id": string,
  "positioning_score": number,      // 0-100 (higher = better)
  "summary": string,                // short analysis
  "recommendations": [string],      // list of recommended next steps
  "confidence": number              // 0.0 - 1.0
}

RULES:
- Output only valid JSON (no explanation text).
- Do NOT include any personal data (PII).
- If data is missing or uncertain, say so in "summary" and lower "confidence".
- Keep "recommendations" short bullet-style strings.

Parcel context:
{context}
"""
    return template.replace("{context}", json.dumps(context, indent=2))

def extract_json_from_text(text: str) -> str:
    """
    If model returns extra text, try to find a JSON object substring and return it.
    """
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model response")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i+1]
                return candidate
    raise ValueError("Could not extract balanced JSON from response")

def call_claude_api(prompt: str, model="claude-2", timeout=30):
    """
    Generic Claude API call. You must set:
      - CLAUDE_API_URL: base endpoint for your Claude instance or proxy
      - CLAUDE_API_KEY: secret (read from env)
    Many Claude deployments use an HTTP POST with JSON { "prompt": "...", "model": ... }
    Update request structure to match your provider.
    """
    url = os.environ.get("CLAUDE_API_URL")  # e.g. "https://api.anthropic.com/v1/complete"
    key = os.environ.get("CLAUDE_API_KEY")
    if not url or not key:
        raise RuntimeError("CLAUDE_API_URL and CLAUDE_API_KEY must be set in environment")

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

    payload = {
        "prompt": prompt,
        "model": model,
        "max_tokens": 800,
        "temperature": 0.0
    }

    log.info("Calling Claude API at %s", url)
    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.text if r.text else r.json()

def get_structured_agent_output(context: dict):
    """Build prompt, call Claude provider, extract & validate JSON, and return dict."""
    prompt = build_claude_prompt(context)
    raw = call_claude_api(prompt)
    if isinstance(raw, dict):
        text = json.dumps(raw)
    else:
        text = str(raw)

    try:
        json_str = extract_json_from_text(text)
        parsed = json.loads(json_str)
    except Exception as e:
        log.exception("Failed to parse JSON from model response: %s", e)
        raise

    try:
        validate(instance=parsed, schema=AGENT_SCHEMA)
    except ValidationError as e:
        log.exception("Agent JSON failed schema validation: %s", e)
        raise

    return parsed
