"""
Princeps Usage Tracker — freemium monetisation MVP.

Tracks API usage per user/session and enforces tier quotas.
Storage: ~/.princeps_usage.json (no DB dependency for MVP).

Tiers:
  free         — 5 assessments, 10 map views, 0 PDFs, 0 API calls
  professional — unlimited assessments, unlimited maps, 50 PDFs, 1000 API calls
  enterprise   — unlimited everything
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

USAGE_FILE = Path.home() / ".princeps_usage.json"

# ── Tier definitions ────────────────────────────────────────────────────────

TIER_LIMITS = {
    "free": {
        "assessment":  5,
        "map_view":    10,
        "pdf_export":  0,
        "api_call":    0,
    },
    "professional": {
        "assessment":  -1,   # -1 = unlimited
        "map_view":    -1,
        "pdf_export":  50,
        "api_call":    1000,
    },
    "enterprise": {
        "assessment":  -1,
        "map_view":    -1,
        "pdf_export":  -1,
        "api_call":    -1,
    },
}

TIER_LABELS = {
    "free":         "Free",
    "professional": "Professional",
    "enterprise":   "Enterprise",
}

TIER_PRICES = {
    "free":         0,
    "professional": 500,      # GBP/month
    "enterprise":   5000,     # GBP/month (starting)
}

# ── Endpoint → category mapping ────────────────────────────────────────────

ENDPOINT_CATEGORIES = {
    # Assessments
    "/api/agent/run":           "assessment",
    "/api/agent/feasibility":   "assessment",
    "/api/grid/assess":         "assessment",
    "/api/grid/power-flow":     "assessment",
    "/api/demand/forecast":     "assessment",
    "/api/geeflow/extract":     "assessment",
    "/api/geoai/run":           "assessment",
    # Map views
    "/api/grid/capacity-map":   "map_view",
    "/api/grid/substations":    "map_view",
    "/api/grid/lines":          "map_view",
    "/api/layers":              "map_view",
    "/api/sites":               "map_view",
    # PDF exports
    "/api/export/pdf":          "pdf_export",
    "/api/report/generate":     "pdf_export",
    # General API
    "/api/chat":                "api_call",
    "/api/demand/scenarios":    "api_call",
    "/api/demand/historical":   "api_call",
    "/api/demand/gsps":         "api_call",
    "/api/demand/summary":      "api_call",
    "/api/grid/live-status":    "api_call",
}


def _categorise_endpoint(endpoint: str) -> str:
    """Map an endpoint path to a usage category."""
    # Exact match first
    if endpoint in ENDPOINT_CATEGORIES:
        return ENDPOINT_CATEGORIES[endpoint]
    # Prefix match
    for prefix, cat in ENDPOINT_CATEGORIES.items():
        if endpoint.startswith(prefix):
            return cat
    # Default: count as api_call
    return "api_call"


# ── Storage helpers ─────────────────────────────────────────────────────────

def _current_month_key() -> str:
    """Return 'YYYY-MM' for the current UTC month."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _load_usage() -> dict:
    """Load usage data from JSON file."""
    if not USAGE_FILE.exists():
        return {}
    try:
        with open(USAGE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_usage(data: dict) -> None:
    """Persist usage data to JSON file."""
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _ensure_user(data: dict, user_id: str, month: str) -> dict:
    """Ensure the user/month structure exists."""
    if user_id not in data:
        data[user_id] = {"tier": "free", "months": {}}
    if month not in data[user_id]["months"]:
        data[user_id]["months"][month] = {
            "assessment":  0,
            "map_view":    0,
            "pdf_export":  0,
            "api_call":    0,
            "events":      [],
        }
    return data


# ── Public API ──────────────────────────────────────────────────────────────

def record_usage(
    user_id: str,
    endpoint: str,
    tier: Optional[str] = None,
) -> dict:
    """
    Log an API call for a user.

    Returns:
        dict with keys: recorded (bool), category, used, limit, tier
    """
    data = _load_usage()
    month = _current_month_key()
    data = _ensure_user(data, user_id, month)

    # Update tier if provided
    if tier and tier in TIER_LIMITS:
        data[user_id]["tier"] = tier

    effective_tier = data[user_id]["tier"]
    category = _categorise_endpoint(endpoint)
    limits = TIER_LIMITS.get(effective_tier, TIER_LIMITS["free"])
    limit = limits.get(category, 0)
    current = data[user_id]["months"][month].get(category, 0)

    # Check if over quota (unlimited = -1)
    if limit != -1 and current >= limit:
        return {
            "recorded": False,
            "category": category,
            "used": current,
            "limit": limit if limit != -1 else "unlimited",
            "tier": effective_tier,
            "message": f"Quota exceeded: {current}/{limit} {category} this month",
        }

    # Record the usage
    data[user_id]["months"][month][category] = current + 1
    data[user_id]["months"][month]["events"].append({
        "endpoint": endpoint,
        "category": category,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Keep events list manageable (last 500)
    if len(data[user_id]["months"][month]["events"]) > 500:
        data[user_id]["months"][month]["events"] = \
            data[user_id]["months"][month]["events"][-500:]

    _save_usage(data)

    return {
        "recorded": True,
        "category": category,
        "used": current + 1,
        "limit": limit if limit != -1 else "unlimited",
        "tier": effective_tier,
    }


def check_quota(user_id: str, tier: Optional[str] = None) -> dict:
    """
    Check remaining quota for a user.

    Returns:
        dict per category: { allowed, used, limit, tier, categories: {...} }
    """
    data = _load_usage()
    month = _current_month_key()
    data = _ensure_user(data, user_id, month)

    effective_tier = tier or data[user_id].get("tier", "free")
    if tier and tier in TIER_LIMITS:
        data[user_id]["tier"] = tier
        _save_usage(data)

    limits = TIER_LIMITS.get(effective_tier, TIER_LIMITS["free"])
    month_data = data[user_id]["months"][month]

    categories = {}
    all_allowed = True

    for cat, limit in limits.items():
        used = month_data.get(cat, 0)
        unlimited = limit == -1
        allowed = unlimited or used < limit
        if not allowed:
            all_allowed = False
        categories[cat] = {
            "used": used,
            "limit": "unlimited" if unlimited else limit,
            "allowed": allowed,
            "remaining": "unlimited" if unlimited else max(0, limit - used),
        }

    return {
        "allowed": all_allowed,
        "tier": effective_tier,
        "tier_label": TIER_LABELS.get(effective_tier, effective_tier),
        "price_gbp": TIER_PRICES.get(effective_tier, 0),
        "month": month,
        "categories": categories,
    }


def get_usage_summary(user_id: str) -> dict:
    """
    Monthly usage breakdown for a user.

    Returns:
        dict with current month stats, tier info, and recent history.
    """
    data = _load_usage()
    month = _current_month_key()
    data = _ensure_user(data, user_id, month)

    effective_tier = data[user_id].get("tier", "free")
    limits = TIER_LIMITS.get(effective_tier, TIER_LIMITS["free"])
    month_data = data[user_id]["months"][month]

    # Current month breakdown
    current = {}
    for cat, limit in limits.items():
        used = month_data.get(cat, 0)
        unlimited = limit == -1
        current[cat] = {
            "used": used,
            "limit": "unlimited" if unlimited else limit,
            "pct": 0 if unlimited else (
                round(100 * used / limit) if limit > 0 else 100 if used > 0 else 0
            ),
        }

    # Historical months (last 6)
    history = {}
    all_months = sorted(data[user_id].get("months", {}).keys(), reverse=True)
    for m in all_months[:6]:
        mdata = data[user_id]["months"][m]
        history[m] = {
            cat: mdata.get(cat, 0)
            for cat in ["assessment", "map_view", "pdf_export", "api_call"]
        }

    # Total event count this month
    event_count = len(month_data.get("events", []))

    return {
        "user_id": user_id,
        "tier": effective_tier,
        "tier_label": TIER_LABELS.get(effective_tier, effective_tier),
        "price_gbp": TIER_PRICES.get(effective_tier, 0),
        "month": month,
        "current": current,
        "history": history,
        "total_events_this_month": event_count,
    }


def set_tier(user_id: str, tier: str) -> dict:
    """
    Upgrade/downgrade a user's tier.

    Returns:
        dict with new tier info and updated quotas.
    """
    if tier not in TIER_LIMITS:
        return {"error": f"Unknown tier: {tier}. Valid: {list(TIER_LIMITS.keys())}"}

    data = _load_usage()
    month = _current_month_key()
    data = _ensure_user(data, user_id, month)
    data[user_id]["tier"] = tier
    _save_usage(data)

    return {
        "user_id": user_id,
        "tier": tier,
        "tier_label": TIER_LABELS[tier],
        "price_gbp": TIER_PRICES[tier],
        "quotas": check_quota(user_id)["categories"],
    }


def reset_usage(user_id: str) -> dict:
    """Reset current month usage for a user (admin/testing)."""
    data = _load_usage()
    month = _current_month_key()
    data = _ensure_user(data, user_id, month)
    data[user_id]["months"][month] = {
        "assessment": 0,
        "map_view": 0,
        "pdf_export": 0,
        "api_call": 0,
        "events": [],
    }
    _save_usage(data)
    return {"reset": True, "user_id": user_id, "month": month}
