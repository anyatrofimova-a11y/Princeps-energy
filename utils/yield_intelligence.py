"""Solar yield intelligence — row shading, layout comparison, hourly profiles."""

import math
from datetime import datetime


def calculate_shade_factor(
    row_pitch_m: float,
    panel_height_m: float,
    tilt_deg: float,
    latitude: float,
    month: int = 12,  # worst case = December
    hour: float = 9.0,  # morning shade
) -> float:
    """Calculate inter-row shade factor (0=fully shaded, 1=no shade)."""
    # Solar position
    day_of_year = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349][month - 1]
    declination = 23.45 * math.sin(math.radians(360/365 * (day_of_year - 81)))
    hour_angle = (hour - 12) * 15  # degrees

    lat_rad = math.radians(latitude)
    dec_rad = math.radians(declination)
    ha_rad = math.radians(hour_angle)

    # Solar altitude
    sin_alt = (math.sin(lat_rad) * math.sin(dec_rad) +
               math.cos(lat_rad) * math.cos(dec_rad) * math.cos(ha_rad))
    solar_altitude = math.degrees(math.asin(max(-1, min(1, sin_alt))))

    if solar_altitude <= 0:
        return 0  # Sun below horizon

    # Shadow length from panel top edge
    panel_top_height = panel_height_m * math.sin(math.radians(tilt_deg))
    shadow_length = panel_top_height / math.tan(math.radians(solar_altitude))

    # Shade factor = fraction of next row that is unshaded
    if shadow_length <= 0:
        return 1.0

    shaded_fraction = min(1.0, shadow_length / row_pitch_m)
    return max(0, 1.0 - shaded_fraction)


def annual_shade_loss(
    row_pitch_m: float,
    panel_height_m: float,
    tilt_deg: float,
    latitude: float,
) -> dict:
    """Calculate annual shade loss percentage and monthly breakdown."""
    monthly_losses = []
    # GHI-weighted hours per month (UK-typical solar hours)
    ghi_weights = [0.3, 0.45, 0.75, 1.1, 1.35, 1.4, 1.3, 1.15, 0.85, 0.55, 0.35, 0.25]

    total_weighted_loss = 0
    total_weight = 0

    for month in range(1, 13):
        month_loss = 0
        hours_checked = 0
        # Check hours 7-17 (main generation hours)
        for hour_10 in range(70, 171, 5):  # 7.0 to 17.0 in 0.5 steps
            hour = hour_10 / 10
            sf = calculate_shade_factor(row_pitch_m, panel_height_m, tilt_deg, latitude, month, hour)
            shade_loss = 1 - sf
            month_loss += shade_loss
            hours_checked += 1

        avg_month_loss = month_loss / hours_checked if hours_checked > 0 else 0
        monthly_losses.append({
            "month": month,
            "shade_loss_pct": round(avg_month_loss * 100, 2),
            "shade_factor": round(1 - avg_month_loss, 3),
        })

        total_weighted_loss += avg_month_loss * ghi_weights[month - 1]
        total_weight += ghi_weights[month - 1]

    annual_loss = total_weighted_loss / total_weight if total_weight > 0 else 0

    return {
        "annual_shade_loss_pct": round(annual_loss * 100, 2),
        "monthly": monthly_losses,
        "worst_month": max(monthly_losses, key=lambda m: m["shade_loss_pct"]),
        "best_month": min(monthly_losses, key=lambda m: m["shade_loss_pct"]),
    }


def compare_layouts(
    latitude: float,
    site_area_ha: float,
    capacity_mwp: float = None,
    panel_watts: int = 600,
    panel_width_m: float = 2.278,
    panel_height_m: float = 1.134,
) -> dict:
    """Compare layout variants — fixed vs tracker, portrait vs landscape, different GCR."""

    variants = []

    configs = [
        {"name": "Fixed 25\u00b0 Landscape GCR 35%", "tilt": 25, "tracking": "fixed", "gcr": 0.35, "orientation": "landscape"},
        {"name": "Fixed 25\u00b0 Landscape GCR 40%", "tilt": 25, "tracking": "fixed", "gcr": 0.40, "orientation": "landscape"},
        {"name": "Fixed 25\u00b0 Landscape GCR 50%", "tilt": 25, "tracking": "fixed", "gcr": 0.50, "orientation": "landscape"},
        {"name": "Fixed 15\u00b0 Landscape GCR 50%", "tilt": 15, "tracking": "fixed", "gcr": 0.50, "orientation": "landscape"},
        {"name": "Fixed 25\u00b0 Portrait GCR 40%", "tilt": 25, "tracking": "fixed", "gcr": 0.40, "orientation": "portrait"},
        {"name": "Single-Axis Tracker GCR 30%", "tilt": 0, "tracking": "single_axis", "gcr": 0.30, "orientation": "landscape"},
        {"name": "Single-Axis Tracker GCR 35%", "tilt": 0, "tracking": "single_axis", "gcr": 0.35, "orientation": "landscape"},
    ]

    site_area_m2 = site_area_ha * 10000

    for cfg in configs:
        # Panel dimensions based on orientation
        if cfg["orientation"] == "portrait":
            pw, ph = panel_height_m, panel_width_m  # swap
        else:
            pw, ph = panel_width_m, panel_height_m

        # Ground coverage
        panel_ground_width = ph * math.cos(math.radians(cfg["tilt"])) if cfg["tracking"] == "fixed" else ph
        row_pitch = panel_ground_width / cfg["gcr"]

        # Panels that fit
        usable_area = site_area_m2 * 0.70  # 70% usable after setbacks, access
        panel_area = pw * ph
        panels_by_area = int(usable_area * cfg["gcr"] / panel_area)
        total_mwp = panels_by_area * panel_watts / 1e6

        # Shade analysis
        shade = annual_shade_loss(row_pitch, ph, cfg["tilt"], latitude)

        # Yield calculation
        # UK base specific yield by latitude
        base_yield = 1100 if latitude < 52 else 1000 if latitude < 54 else 900
        tracker_gain = 1.175 if cfg["tracking"] == "single_axis" else 1.0
        tilt_factor = 1.0 + 0.003 * (cfg["tilt"] - 20) if 10 <= cfg["tilt"] <= 35 else 0.97  # optimal ~25 UK
        shade_factor = 1 - shade["annual_shade_loss_pct"] / 100

        specific_yield = base_yield * tracker_gain * tilt_factor * shade_factor * 0.82  # PR=0.82
        annual_mwh = total_mwp * specific_yield / 1000 * 1000  # MWp * kWh/kWp
        cf = annual_mwh / (total_mwp * 8760) * 100 if total_mwp > 0 else 0

        # LCOE estimate
        capex_per_mwp = 550000 if cfg["tracking"] == "fixed" else 650000
        total_capex = total_mwp * capex_per_mwp
        annual_opex = total_mwp * 10000
        lcoe = (total_capex * 0.08 + annual_opex) / annual_mwh if annual_mwh > 0 else 999  # 8% WACC

        # Revenue
        ppa_price = 50  # GBP/MWh
        annual_revenue = annual_mwh * ppa_price

        variants.append({
            "name": cfg["name"],
            "tracking": cfg["tracking"],
            "tilt_deg": cfg["tilt"],
            "gcr": cfg["gcr"],
            "orientation": cfg["orientation"],
            "row_pitch_m": round(row_pitch, 2),
            "total_panels": panels_by_area,
            "total_mwp": round(total_mwp, 2),
            "shade_loss_pct": shade["annual_shade_loss_pct"],
            "specific_yield_kwh_kwp": round(specific_yield),
            "annual_mwh": round(annual_mwh),
            "capacity_factor_pct": round(cf, 1),
            "lcoe_gbp_mwh": round(lcoe, 1),
            "annual_revenue_gbp": round(annual_revenue),
            "total_capex_gbp": round(total_capex),
            "irr_estimate_pct": round((annual_revenue - annual_opex) / total_capex * 100, 1) if total_capex > 0 else 0,
        })

    # Sort by annual revenue descending
    variants.sort(key=lambda v: v["annual_revenue_gbp"], reverse=True)

    return {
        "latitude": latitude,
        "site_area_ha": site_area_ha,
        "panel_watts": panel_watts,
        "variants": variants,
        "recommended": variants[0]["name"],
        "recommendation_reason": f"Highest annual revenue (\u00a3{variants[0]['annual_revenue_gbp']:,})",
    }


def hourly_generation_profile(
    capacity_mwp: float,
    latitude: float,
    tilt_deg: float = 25,
    tracking: str = "fixed",
    month: int = 6,  # June default
) -> dict:
    """Generate hourly power output profile for a given month."""
    hours = []
    for h in range(24):
        hour = h + 0.5  # mid-hour
        day_of_year = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349][month - 1]
        declination = 23.45 * math.sin(math.radians(360/365 * (day_of_year - 81)))
        hour_angle = (hour - 12) * 15

        lat_rad = math.radians(latitude)
        dec_rad = math.radians(declination)
        ha_rad = math.radians(hour_angle)

        sin_alt = (math.sin(lat_rad) * math.sin(dec_rad) +
                   math.cos(lat_rad) * math.cos(dec_rad) * math.cos(ha_rad))
        solar_altitude = math.degrees(math.asin(max(-1, min(1, sin_alt))))

        if solar_altitude <= 0:
            power_mw = 0
        else:
            # Simplified irradiance model
            clear_sky_ghi = 1000 * math.sin(math.radians(solar_altitude))  # W/m2
            # UK cloud factor
            cloud_factors = [0.25, 0.30, 0.40, 0.50, 0.55, 0.58, 0.55, 0.50, 0.45, 0.35, 0.28, 0.22]
            cloud = cloud_factors[month - 1]
            ghi = clear_sky_ghi * cloud

            # Tracker gain
            tracker_factor = 1.175 if tracking == "single_axis" else 1.0

            power_mw = capacity_mwp * (ghi / 1000) * 0.82 * tracker_factor  # PR = 0.82

        hours.append({"hour": h, "power_mw": round(max(0, power_mw), 3)})

    daily_mwh = sum(h["power_mw"] for h in hours)
    peak_mw = max(h["power_mw"] for h in hours)

    return {
        "month": month,
        "capacity_mwp": capacity_mwp,
        "tilt_deg": tilt_deg,
        "tracking": tracking,
        "daily_mwh": round(daily_mwh, 1),
        "peak_mw": round(peak_mw, 2),
        "capacity_factor_pct": round(daily_mwh / (capacity_mwp * 24) * 100, 1),
        "hours": hours,
    }
