#!/usr/bin/env python3
"""
Balancing Mechanism modeller — Princeps Phase 9
Models UK BM participation: BOA (Bid-Offer Acceptance) volumes,
constraint payments, system buy/sell prices, BM unit revenue.

Based on NESO settlement data patterns.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "bm_revenue", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland"}
  {"command": "boa_profile", "capacity_mw": 50, "region": "Scotland",
   "hours_ahead": 24}
  {"command": "system_prices", "date": "2025-01-15"}
"""

import json
import math
import random
import sys

# ── UK BM market parameters ───────────────────────────────────────────────

# System Buy Price (SBP) and System Sell Price (SSP) patterns
# Based on typical UK settlement data
SBP_BASE = {  # £/MWh by hour — SBP typically higher
    "winter": [52, 45, 38, 35, 33, 38, 58, 82, 95, 85, 72, 62,
               55, 52, 58, 72, 98, 125, 140, 105, 78, 62, 55, 48],
    "summer": [35, 28, 22, 18, 16, 22, 42, 62, 72, 65, 55, 48,
               42, 38, 42, 55, 72, 92, 105, 82, 62, 48, 40, 35],
}

SSP_BASE = {  # Typically lower than SBP (system short → high SBP)
    "winter": [32, 28, 22, 18, 16, 20, 35, 52, 62, 55, 48, 42,
               38, 35, 38, 48, 65, 82, 92, 72, 55, 42, 35, 32],
    "summer": [22, 18, 12, 8, 5, 12, 28, 42, 52, 48, 38, 32,
               28, 25, 28, 38, 52, 68, 78, 58, 42, 32, 28, 22],
}

# BOA acceptance probability by region and technology
BOA_PROFILES = {
    "Scotland": {
        "wind": {"bid_prob": 0.35, "offer_prob": 0.08, "avg_volume_pct": 0.45},
        "solar": {"bid_prob": 0.15, "offer_prob": 0.05, "avg_volume_pct": 0.30},
        "bess": {"bid_prob": 0.20, "offer_prob": 0.25, "avg_volume_pct": 0.60},
    },
    "North": {
        "wind": {"bid_prob": 0.22, "offer_prob": 0.10, "avg_volume_pct": 0.35},
        "solar": {"bid_prob": 0.10, "offer_prob": 0.06, "avg_volume_pct": 0.25},
        "bess": {"bid_prob": 0.18, "offer_prob": 0.22, "avg_volume_pct": 0.55},
    },
    "Midlands": {
        "wind": {"bid_prob": 0.12, "offer_prob": 0.12, "avg_volume_pct": 0.25},
        "solar": {"bid_prob": 0.08, "offer_prob": 0.08, "avg_volume_pct": 0.20},
        "bess": {"bid_prob": 0.15, "offer_prob": 0.20, "avg_volume_pct": 0.50},
    },
    "South": {
        "wind": {"bid_prob": 0.08, "offer_prob": 0.15, "avg_volume_pct": 0.20},
        "solar": {"bid_prob": 0.06, "offer_prob": 0.10, "avg_volume_pct": 0.18},
        "bess": {"bid_prob": 0.12, "offer_prob": 0.22, "avg_volume_pct": 0.50},
    },
}

# Constraint payment benchmarks (£/MWh — based on NESO outturn)
CONSTRAINT_PAYMENT_RATES = {
    "Scotland": {"mean": 68, "std": 25, "max": 180},
    "North": {"mean": 52, "std": 18, "max": 120},
    "Wales": {"mean": 48, "std": 15, "max": 110},
    "Midlands": {"mean": 40, "std": 12, "max": 85},
    "East": {"mean": 42, "std": 14, "max": 95},
    "South": {"mean": 38, "std": 10, "max": 75},
    "London": {"mean": 35, "std": 8, "max": 65},
}


def bm_revenue_estimate(capacity_mw: float = 50, technology: str = "wind",
                          region: str = "Scotland") -> dict:
    """
    Estimate annual BM revenue potential for a generation unit.
    """
    profile = BOA_PROFILES.get(region, BOA_PROFILES["Midlands"])
    tech_profile = profile.get(technology, profile.get("solar"))
    constraint_rates = CONSTRAINT_PAYMENT_RATES.get(region, CONSTRAINT_PAYMENT_RATES["Midlands"])

    bid_prob = tech_profile["bid_prob"]
    offer_prob = tech_profile["offer_prob"]
    avg_vol_pct = tech_profile["avg_volume_pct"]

    # Annual BOA volume estimation
    hours_year = 8760
    bid_hours = hours_year * bid_prob
    offer_hours = hours_year * offer_prob
    avg_vol_mw = capacity_mw * avg_vol_pct

    # Bid revenue (turn-down payments — paid TO generator)
    constraint_price = constraint_rates["mean"]
    bid_revenue = bid_hours * avg_vol_mw * constraint_price

    # Offer revenue (turn-up payments — paid TO generator for increasing output)
    offer_price = 45  # Typical offer acceptance price £/MWh
    offer_revenue = offer_hours * avg_vol_mw * offer_price

    # Total BM revenue
    total_bm = bid_revenue + offer_revenue

    # System price spread revenue (for BESS arbitrage in BM)
    if technology == "bess":
        spread_hours = hours_year * 0.3  # 30% of hours have meaningful spread
        avg_spread = 25  # £/MWh typical SBP-SSP spread
        spread_revenue = spread_hours * avg_vol_mw * avg_spread * 0.5
        total_bm += spread_revenue
    else:
        spread_revenue = 0

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
        },
        "annual_estimates": {
            "bid_acceptance_hours": round(bid_hours),
            "offer_acceptance_hours": round(offer_hours),
            "avg_accepted_volume_mw": round(avg_vol_mw, 1),
            "bid_revenue_gbp": round(bid_revenue),
            "offer_revenue_gbp": round(offer_revenue),
            "spread_revenue_gbp": round(spread_revenue),
            "total_bm_revenue_gbp": round(total_bm),
            "revenue_per_mw_gbp": round(total_bm / max(capacity_mw, 1)),
        },
        "constraint_prices": {
            "mean_gbp_mwh": constraint_rates["mean"],
            "std_gbp_mwh": constraint_rates["std"],
            "max_gbp_mwh": constraint_rates["max"],
        },
        "market_context": {
            "bid_probability": bid_prob,
            "offer_probability": offer_prob,
            "region_constraint_intensity": "HIGH" if bid_prob > 0.25 else "MEDIUM" if bid_prob > 0.12 else "LOW",
        },
    }


def boa_profile(capacity_mw: float = 50, region: str = "Scotland",
                technology: str = "wind", hours_ahead: int = 24,
                month: int = 1) -> dict:
    """
    Generate hourly BOA acceptance profile.
    """
    profile = BOA_PROFILES.get(region, BOA_PROFILES["Midlands"])
    tech_profile = profile.get(technology, profile.get("solar"))
    is_winter = month in (11, 12, 1, 2, 3)
    sbp = SBP_BASE["winter" if is_winter else "summer"]
    ssp = SSP_BASE["winter" if is_winter else "summer"]

    random.seed(42 + month)
    hourly = []
    total_bid_vol = 0
    total_offer_vol = 0
    total_bid_rev = 0
    total_offer_rev = 0

    for h in range(min(hours_ahead, 24)):
        hour = h % 24

        # Bid probability varies by hour (peaks at demand peaks)
        hour_factor = 0.7 + 0.3 * max(
            math.exp(-0.5 * ((hour - 8) / 2.5) ** 2),
            math.exp(-0.5 * ((hour - 17) / 3) ** 2),
        )
        bid_prob = min(0.95, tech_profile["bid_prob"] * hour_factor * (1.3 if is_winter else 0.8))
        offer_prob = min(0.95, tech_profile["offer_prob"] * (0.8 + 0.2 * (1 - hour_factor)))

        bid_accepted = random.random() < bid_prob
        offer_accepted = random.random() < offer_prob and not bid_accepted

        bid_vol = capacity_mw * tech_profile["avg_volume_pct"] * random.uniform(0.3, 1.0) if bid_accepted else 0
        offer_vol = capacity_mw * tech_profile["avg_volume_pct"] * random.uniform(0.2, 0.8) if offer_accepted else 0

        # Prices with volatility
        bid_price = sbp[hour] + random.gauss(0, 10)
        offer_price = ssp[hour] + random.gauss(5, 8)

        bid_rev = bid_vol * max(0, bid_price)
        offer_rev = offer_vol * max(0, offer_price)

        total_bid_vol += bid_vol
        total_offer_vol += offer_vol
        total_bid_rev += bid_rev
        total_offer_rev += offer_rev

        hourly.append({
            "hour": hour,
            "sbp_gbp_mwh": round(sbp[hour] + random.gauss(0, 5), 1),
            "ssp_gbp_mwh": round(ssp[hour] + random.gauss(0, 3), 1),
            "bid_accepted": bid_accepted,
            "offer_accepted": offer_accepted,
            "bid_volume_mw": round(bid_vol, 1),
            "offer_volume_mw": round(offer_vol, 1),
            "bid_revenue_gbp": round(bid_rev),
            "offer_revenue_gbp": round(offer_rev),
            "action": "BID" if bid_accepted else ("OFFER" if offer_accepted else "NONE"),
        })

    return {
        "parameters": {"capacity_mw": capacity_mw, "region": region, "technology": technology},
        "hourly": hourly[:hours_ahead],
        "summary": {
            "total_bid_volume_mwh": round(total_bid_vol, 1),
            "total_offer_volume_mwh": round(total_offer_vol, 1),
            "total_bid_revenue_gbp": round(total_bid_rev),
            "total_offer_revenue_gbp": round(total_offer_rev),
            "total_bm_revenue_gbp": round(total_bid_rev + total_offer_rev),
            "bid_acceptances": sum(1 for h in hourly if h["bid_accepted"]),
            "offer_acceptances": sum(1 for h in hourly if h["offer_accepted"]),
        },
    }


def system_prices(date: str = "2025-01-15") -> dict:
    """Generate system price forecast (SBP/SSP) for a day."""
    dt = None
    try:
        dt = __import__("datetime").datetime.fromisoformat(date)
    except Exception:
        dt = __import__("datetime").datetime(2025, 1, 15)

    month = dt.month
    is_winter = month in (11, 12, 1, 2, 3)
    sbp = SBP_BASE["winter" if is_winter else "summer"]
    ssp = SSP_BASE["winter" if is_winter else "summer"]

    random.seed(int(dt.timestamp()) % 10000)
    hourly = []
    for h in range(24):
        s_buy = sbp[h] + random.gauss(0, 8)
        s_sell = ssp[h] + random.gauss(0, 5)
        hourly.append({
            "hour": h,
            "sbp_gbp_mwh": round(max(0, s_buy), 1),
            "ssp_gbp_mwh": round(max(0, s_sell), 1),
            "spread_gbp_mwh": round(max(0, s_buy - s_sell), 1),
            "system_long": s_sell > s_buy,
        })

    return {
        "date": date,
        "season": "winter" if is_winter else "summer",
        "hourly": hourly,
        "summary": {
            "avg_sbp": round(sum(h["sbp_gbp_mwh"] for h in hourly) / 24, 1),
            "avg_ssp": round(sum(h["ssp_gbp_mwh"] for h in hourly) / 24, 1),
            "max_sbp": round(max(h["sbp_gbp_mwh"] for h in hourly), 1),
            "avg_spread": round(sum(h["spread_gbp_mwh"] for h in hourly) / 24, 1),
            "system_long_hours": sum(1 for h in hourly if h["system_long"]),
        },
    }


# ── Subprocess bridge ──────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    cmd = req.get("command", "")
    try:
        if cmd == "bm_revenue":
            result = bm_revenue_estimate(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
            )
            json.dump(result, sys.stdout)
        elif cmd == "boa_profile":
            result = boa_profile(
                capacity_mw=req.get("capacity_mw", 50),
                region=req.get("region", "Scotland"),
                technology=req.get("technology", "wind"),
                hours_ahead=req.get("hours_ahead", 24),
                month=req.get("month", 1),
            )
            json.dump(result, sys.stdout)
        elif cmd == "system_prices":
            result = system_prices(req.get("date", "2025-01-15"))
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
