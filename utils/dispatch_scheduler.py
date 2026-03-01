#!/usr/bin/env python3
"""
Dispatch scheduler — Princeps Phase 9
Optimal export/import schedule for a generation or BESS site.
Considers grid constraints, wholesale prices, curtailment windows,
and battery state-of-charge to maximize revenue.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "schedule", "capacity_mw": 50, "technology": "solar",
   "region": "Midlands", "connection_type": "anm", "headroom_mw": 30,
   "hours_ahead": 24}
  {"command": "bess_schedule", "power_mw": 25, "energy_mwh": 50,
   "soc_pct": 50, "region": "Midlands", "hours_ahead": 24}
  {"command": "revenue_comparison", "capacity_mw": 50, "technology": "solar",
   "region": "Midlands"}
"""

import json
import math
import random
import sys

# ── UK wholesale price profile (£/MWh) — typical winter/summer ──────────
PRICE_PROFILES = {
    "winter": [38, 32, 28, 25, 24, 28, 45, 62, 72, 65, 58, 52,
               48, 45, 48, 58, 75, 95, 105, 85, 65, 52, 45, 40],
    "summer": [28, 22, 18, 15, 14, 18, 32, 48, 55, 50, 42, 38,
               35, 32, 35, 42, 55, 72, 78, 62, 48, 38, 32, 30],
}

# Frequency response rates (£/MW/hr)
FFR_RATE = 12  # Firm Frequency Response
DC_RATE = 17   # Dynamic Containment
DM_RATE = 8    # Dynamic Moderation

# Generation profiles (normalised)
SOLAR_PROFILE = [0, 0, 0, 0, 0.02, 0.08, 0.20, 0.40, 0.60, 0.78, 0.90, 0.96,
                 1.00, 0.98, 0.92, 0.80, 0.62, 0.40, 0.18, 0.05, 0, 0, 0, 0]
WIND_PROFILE = [0.72, 0.75, 0.78, 0.80, 0.82, 0.78, 0.70, 0.62,
                0.55, 0.50, 0.48, 0.45, 0.42, 0.45, 0.50, 0.55,
                0.60, 0.65, 0.68, 0.70, 0.72, 0.74, 0.73, 0.72]

# Constraint probability by hour (simplified — winter Scottish boundary)
CONSTRAINT_PROFILE = {
    "Scotland": [0.65, 0.60, 0.55, 0.50, 0.48, 0.52, 0.58, 0.55,
                 0.45, 0.38, 0.32, 0.28, 0.25, 0.28, 0.35, 0.45,
                 0.55, 0.68, 0.75, 0.65, 0.55, 0.48, 0.58, 0.62],
    "Midlands": [0.18, 0.15, 0.12, 0.10, 0.10, 0.12, 0.22, 0.30,
                 0.35, 0.28, 0.22, 0.18, 0.15, 0.15, 0.20, 0.28,
                 0.38, 0.45, 0.48, 0.38, 0.28, 0.22, 0.20, 0.18],
}


def _get_gen_profile(technology: str) -> list:
    return SOLAR_PROFILE if technology == "solar" else WIND_PROFILE


def _get_price_profile(month: int) -> list:
    if month in (11, 12, 1, 2, 3):
        return PRICE_PROFILES["winter"]
    return PRICE_PROFILES["summer"]


def _get_constraint_profile(region: str) -> list:
    return CONSTRAINT_PROFILE.get(region, CONSTRAINT_PROFILE["Midlands"])


def schedule_generation(capacity_mw: float = 50, technology: str = "solar",
                         region: str = "Midlands",
                         connection_type: str = "anm",
                         headroom_mw: float = 30,
                         hours_ahead: int = 24,
                         month: int = 1) -> dict:
    """
    Generate optimal dispatch schedule for a generation site.
    """
    gen_profile = _get_gen_profile(technology)
    price_profile = _get_price_profile(month)
    constraint_profile = _get_constraint_profile(region)

    # Connection type affects export limit
    export_limit = headroom_mw if connection_type in ("anm", "non_firm", "timed") else capacity_mw
    curtailment_factor = {"firm": 0.02, "anm": 0.55, "non_firm": 1.0, "timed": 0.4}.get(connection_type, 0.5)

    hourly = []
    total_generated = 0
    total_exported = 0
    total_curtailed = 0
    total_revenue = 0
    total_constraint_revenue = 0

    for h in range(min(hours_ahead, 24)):
        hour = h % 24
        # Generation
        generated_mw = capacity_mw * gen_profile[hour] * (0.85 + random.gauss(0, 0.08))
        generated_mw = max(0, generated_mw)

        # Constraint check
        constraint_prob = constraint_profile[hour]
        is_constrained = random.random() < constraint_prob * curtailment_factor

        # Export calculation
        if is_constrained and connection_type != "firm":
            effective_export = min(generated_mw, export_limit * 0.3)  # Severely reduced
            constraint_payment = (generated_mw - effective_export) * price_profile[hour] * 0.8
        else:
            effective_export = min(generated_mw, export_limit)
            constraint_payment = 0

        curtailed_mw = max(0, generated_mw - effective_export)
        price = price_profile[hour]
        revenue = effective_export * price

        total_generated += generated_mw
        total_exported += effective_export
        total_curtailed += curtailed_mw
        total_revenue += revenue
        total_constraint_revenue += constraint_payment

        hourly.append({
            "hour": hour,
            "generated_mw": round(generated_mw, 2),
            "exported_mw": round(effective_export, 2),
            "curtailed_mw": round(curtailed_mw, 2),
            "export_limit_mw": round(export_limit, 1),
            "price_gbp_mwh": price,
            "revenue_gbp": round(revenue, 2),
            "constraint_payment_gbp": round(constraint_payment, 2),
            "is_constrained": is_constrained,
            "constraint_probability": round(constraint_prob, 3),
            "action": "CURTAILED" if curtailed_mw > 0.5 else "EXPORT",
        })

    # Repeat for remaining hours if needed
    for h in range(24, hours_ahead):
        hourly.append(hourly[h % 24].copy())
        hourly[-1]["hour"] = h

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "connection_type": connection_type,
            "headroom_mw": headroom_mw,
            "export_limit_mw": export_limit,
        },
        "schedule": hourly[:hours_ahead],
        "summary": {
            "total_generated_mwh": round(total_generated, 1),
            "total_exported_mwh": round(total_exported, 1),
            "total_curtailed_mwh": round(total_curtailed, 1),
            "curtailment_pct": round(total_curtailed / max(total_generated, 0.01) * 100, 1),
            "total_revenue_gbp": round(total_revenue),
            "constraint_payments_gbp": round(total_constraint_revenue),
            "effective_price_gbp_mwh": round(total_revenue / max(total_exported, 0.01), 2),
            "constrained_hours": sum(1 for h in hourly[:hours_ahead] if h["is_constrained"]),
        },
    }


def schedule_bess(power_mw: float = 25, energy_mwh: float = 50,
                   soc_pct: float = 50, region: str = "Midlands",
                   hours_ahead: int = 24, month: int = 1) -> dict:
    """
    Generate optimal BESS dispatch schedule — arbitrage + frequency response.
    """
    price_profile = _get_price_profile(month)
    constraint_profile = _get_constraint_profile(region)

    # Sort hours by price to determine charge/discharge strategy
    price_ranked = sorted(range(24), key=lambda h: price_profile[h])
    charge_hours = set(price_ranked[:8])     # Cheapest 8 hours → charge
    discharge_hours = set(price_ranked[-8:])  # Most expensive 8 hours → discharge
    ffr_hours = set(price_ranked[8:16])       # Middle hours → frequency response

    soc_mwh = energy_mwh * soc_pct / 100
    efficiency = 0.88  # Round-trip efficiency

    hourly = []
    total_revenue = 0
    total_charged = 0
    total_discharged = 0
    total_ffr_revenue = 0

    for h in range(min(hours_ahead, 24)):
        hour = h % 24
        price = price_profile[hour]
        constraint_prob = constraint_profile[hour]

        action = "IDLE"
        power = 0
        revenue = 0
        ffr_revenue = 0

        if hour in charge_hours and soc_mwh < energy_mwh * 0.95:
            # Charge
            charge_mw = min(power_mw, (energy_mwh - soc_mwh) / 1)
            soc_mwh += charge_mw * efficiency
            power = -charge_mw
            revenue = -charge_mw * price  # Cost of charging
            total_charged += charge_mw
            action = "CHARGE"

        elif hour in discharge_hours and soc_mwh > energy_mwh * 0.1:
            # Discharge — but check for constraint-enhanced pricing
            discharge_mw = min(power_mw, soc_mwh / 1)
            soc_mwh -= discharge_mw
            power = discharge_mw
            # Constraint uplift on price
            if constraint_prob > 0.5:
                effective_price = price * (1 + constraint_prob * 0.5)
            else:
                effective_price = price
            revenue = discharge_mw * effective_price
            total_discharged += discharge_mw
            action = "DISCHARGE"

        elif hour in ffr_hours:
            # Frequency response — hold capacity available
            available_mw = min(power_mw, soc_mwh / 2)
            ffr_revenue = available_mw * DC_RATE
            total_ffr_revenue += ffr_revenue
            action = "FFR"

        total_revenue += revenue + ffr_revenue

        hourly.append({
            "hour": hour,
            "action": action,
            "power_mw": round(power, 2),
            "soc_mwh": round(soc_mwh, 1),
            "soc_pct": round(soc_mwh / energy_mwh * 100, 1),
            "price_gbp_mwh": price,
            "revenue_gbp": round(revenue, 2),
            "ffr_revenue_gbp": round(ffr_revenue, 2),
            "constraint_probability": round(constraint_prob, 3),
        })

    # Annualise
    daily_revenue = total_revenue
    annual_revenue = daily_revenue * 365
    cycles_per_day = total_discharged / max(energy_mwh, 1)

    return {
        "parameters": {
            "power_mw": power_mw,
            "energy_mwh": energy_mwh,
            "initial_soc_pct": soc_pct,
            "region": region,
        },
        "schedule": hourly[:hours_ahead],
        "summary": {
            "total_charged_mwh": round(total_charged, 1),
            "total_discharged_mwh": round(total_discharged, 1),
            "arbitrage_revenue_gbp": round(total_revenue - total_ffr_revenue),
            "ffr_revenue_gbp": round(total_ffr_revenue),
            "total_daily_revenue_gbp": round(daily_revenue),
            "estimated_annual_revenue_gbp": round(annual_revenue),
            "cycles_per_day": round(cycles_per_day, 2),
            "final_soc_pct": round(soc_mwh / energy_mwh * 100, 1),
        },
    }


def revenue_comparison(capacity_mw: float = 50, technology: str = "solar",
                        region: str = "Midlands") -> dict:
    """Compare revenue across connection types and seasons."""
    results = []
    for conn in ["firm", "anm", "non_firm", "timed"]:
        winter = schedule_generation(capacity_mw, technology, region, conn, capacity_mw * 0.6, 24, month=1)
        summer = schedule_generation(capacity_mw, technology, region, conn, capacity_mw * 0.6, 24, month=7)
        annual_est = (winter["summary"]["total_revenue_gbp"] * 182 +
                      summer["summary"]["total_revenue_gbp"] * 183)
        results.append({
            "connection_type": conn,
            "winter_daily_gbp": winter["summary"]["total_revenue_gbp"],
            "summer_daily_gbp": summer["summary"]["total_revenue_gbp"],
            "estimated_annual_gbp": round(annual_est),
            "winter_curtailment_pct": winter["summary"]["curtailment_pct"],
            "summer_curtailment_pct": summer["summary"]["curtailment_pct"],
        })
    results.sort(key=lambda r: -r["estimated_annual_gbp"])
    return {"capacity_mw": capacity_mw, "technology": technology, "region": region, "comparison": results}


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
        if cmd == "schedule":
            result = schedule_generation(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "solar"),
                region=req.get("region", "Midlands"),
                connection_type=req.get("connection_type", "anm"),
                headroom_mw=req.get("headroom_mw", 30),
                hours_ahead=req.get("hours_ahead", 24),
                month=req.get("month", 1),
            )
            json.dump(result, sys.stdout)
        elif cmd == "bess_schedule":
            result = schedule_bess(
                power_mw=req.get("power_mw", 25),
                energy_mwh=req.get("energy_mwh", 50),
                soc_pct=req.get("soc_pct", 50),
                region=req.get("region", "Midlands"),
                hours_ahead=req.get("hours_ahead", 24),
                month=req.get("month", 1),
            )
            json.dump(result, sys.stdout)
        elif cmd == "revenue_comparison":
            result = revenue_comparison(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "solar"),
                region=req.get("region", "Midlands"),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()
