"""
app/alerts/starter_packs.py — 5 ICP-aligned alert bundles.

Each pack subscribes a user to a curated set of alert slugs in one request.
The 5-alert soft cap on the free tier still applies; if the pack exceeds the
cap, the router returns a partial-success response with the remaining slugs
in ``pack_remaining`` so the UI can prompt for an upgrade.

Public router: ``POST /api/alerts/starter-pack/{slug}/subscribe``.
"""

from __future__ import annotations

from typing import Any

from app.alerts.seed import catalogue_slugs


# Ordered deliberately: the first N slugs in each pack are the ones that
# fit inside the 5-alert free cap when a pack is auto-subscribed.
STARTER_PACKS: dict[str, dict[str, Any]] = {
    "solar_dev": {
        "title": "UK solar developer",
        "description": "AR7, REPD, DNO ECR, TEC register, Gate 2, planning appeals, curtailment, corporate PPAs.",
        "alerts": [
            "ar7-cfd-notices",
            "repd-new-entries",
            "dno-ecr-weekly",
            "tec-register-deltas",
            "lpa-major-energy-10mw",
            "gate2-offer-decisions",
            "offer-withdrawals",
            "planning-appeals",
            "bng-nsip-filings",
            "curtailment-volumes",
            "corporate-ppa-announcements",
            "ar6-delivery-milestones",
        ],
    },
    "bess_dev": {
        "title": "BESS developer",
        "description": "Capacity Market, LDES cap-and-floor, AR7 storage, co-location, BMRS imbalance, DFS tenders.",
        "alerts": [
            "capacity-market-auctions",
            "bess-planning-filings",
            "ldes-cap-and-floor",
            "battery-fire-comah",
            "ar7-storage-eligible",
            "colocation-filings",
            "bmrs-imbalance-daily",
            "negative-pricing-events",
            "dfs-tenders",
            "dno-ecr-weekly",
        ],
    },
    "dc_dev": {
        "title": "Data-centre developer",
        "description": "Hyperscaler siting, large-load offers, DC planning >20MW, BTM, DSR, liquid-cooling permits, Sovereign AI.",
        "alerts": [
            "hyperscaler-siting",
            "large-load-connection-offers",
            "dc-planning-20mw",
            "btm-generation",
            "dsr-flex-agreements",
            "liquid-cooling-permits",
            "uk-sovereign-ai-compute",
            "west-london-power-ceiling",
            "scottish-dc-corridor",
            "water-stress-dc-permits",
            "tec-register-deltas",
            "gate2-offer-decisions",
            "nsip-dco-applications",
            "bs9991-grenfell-flowdown",
        ],
    },
    "grid_consultant": {
        "title": "Grid consultant",
        "description": "RIIO-ED3, REMA, BSC/DCUSA/CUSC/GC mod tracker, LTDS, LTDS, DNO business plans, SIF/NIA.",
        "alerts": [
            "riio-ed3-consultation",
            "rema-implementation",
            "bsc-mod-decisions",
            "dcusa-change-proposals",
            "stc-sqss-changes",
            "ofgem-open-letters",
            "ltds-publication-diff",
            "transmission-works-tracker",
            "firm-nonfirm-split-shifts",
            "cmp-gc-mod-tracker",
            "balancing-services-monthly",
            "curtailment-volumes",
            "riio-ed2-ed3-capex-allowances",
            "dno-business-plan-updates",
            "utility-credit-rating",
            "sif-awards",
            "nia-annual-reports",
            "dlr-advanced-conductor-pilots",
        ],
    },
    "land_agent": {
        "title": "Land agent",
        "description": "LPA majors, REPD, NSIPs, BNG, ROC end-of-life, new SPVs, director watchlist, dissolutions.",
        "alerts": [
            "lpa-major-energy-10mw",
            "repd-new-entries",
            "nsip-dco-applications",
            "bng-nsip-filings",
            "roc-lifetime-end",
            "new-spv-incorporations",
            "director-watchlist",
            "dissolutions-project-spvs",
        ],
    },
}


def get_pack(slug: str) -> dict[str, Any] | None:
    """Return the pack dict for *slug* or ``None`` if it doesn't exist."""
    return STARTER_PACKS.get(slug)


def list_packs() -> list[dict[str, Any]]:
    """Serialise all packs as a list (for GET endpoints / UI)."""
    return [{"slug": k, **v} for k, v in STARTER_PACKS.items()]


def validate_packs_against_catalogue() -> list[str]:
    """Return any pack slugs that reference alerts missing from the catalogue.

    Used by tests to guard against catalogue drift.
    """
    available = catalogue_slugs()
    missing: list[str] = []
    for pack_slug, pack in STARTER_PACKS.items():
        for alert_slug in pack["alerts"]:
            if alert_slug not in available:
                missing.append(f"{pack_slug}:{alert_slug}")
    return missing


__all__ = [
    "STARTER_PACKS",
    "get_pack",
    "list_packs",
    "validate_packs_against_catalogue",
]
