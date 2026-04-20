"""
app/alerts — Princeps Alerts runtime (Task #6).

Contains:
  - ``seed.py`` — 84 UK alert SKUs seeded on startup (idempotent).
  - ``starter_packs.py`` — 5 ICP-tagged bundles (solar_dev, bess_dev, dc_dev,
    grid_consultant, land_agent) subscribed via one POST.
  - ``delivery.py`` — email / in-app / Slack webhook dispatch.
  - ``digest_worker.py`` — cadence-driven digest runner that selects new
    documents since last_run, calls Claude Haiku with the alert's llm_prompt,
    stores a digest row and triggers delivery.
  - ``user_tiers.py`` — ``get_user_tier()`` helper + default ``free`` seed.

The router layer lives in ``app/routers/alerts.py``.
"""

from app.alerts.seed import seed_alert_definitions  # re-export for startup
from app.alerts.user_tiers import (
    get_user_tier,
    seed_user_tier_defaults,
)

__all__ = [
    "seed_alert_definitions",
    "seed_user_tier_defaults",
    "get_user_tier",
]
