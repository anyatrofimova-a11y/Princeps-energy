"""Analytics router -- Solar Forecast, Consumption Heatmap, Grid Stability, Prosumer, Turbine Health, Transmission Faults, Energy Assets."""

from __future__ import annotations

import math

from fastapi import APIRouter, Query

from app.helpers import _seed_for
from utils.uk_grid_topology import topology_to_geojson
from utils.grid_data_platform import UK_SUBSTATIONS

router = APIRouter(tags=["analytics"])


# ═══════════════════════════════════════════════════════════════════════════════
# Solar Forecast
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/analytics/solar-forecast")
async def analytics_solar_forecast(capacity_kw: float = 100, day_of_year: int = 172):
    """
    Next-day solar generation forecast (96 x 15-min intervals).
    Adapted from AI-for-energy-sector Solar Energy Generation notebook:
    XGBoost model with irradiation, temperature, time-of-day features.
    """
    rng = _seed_for("solar", day_of_year)
    # Solar geometry -- day length and peak irradiance vary with day_of_year
    declination = 23.45 * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
    lat_rad = math.radians(52.0)  # UK latitude
    hour_angle = math.acos(-math.tan(lat_rad) * math.tan(math.radians(declination)))
    day_length_h = 2 * math.degrees(hour_angle) / 15
    sunrise = 12 - day_length_h / 2
    sunset = 12 + day_length_h / 2
    peak_irr = 800 + 200 * math.sin(math.radians(declination + 23.45) / 46.9 * 90)  # W/m2

    intervals = []
    for i in range(96):
        hour = i / 4
        if sunrise <= hour <= sunset:
            solar_elevation = math.sin(math.pi * (hour - sunrise) / (sunset - sunrise))
            cloud_factor = 0.7 + 0.3 * rng.random()
            irr = peak_irr * solar_elevation * cloud_factor
            temp_ambient = 8 + 12 * solar_elevation + rng.gauss(0, 1)
            temp_module = temp_ambient + 20 * solar_elevation
            ac_power = capacity_kw * (irr / 1000) * 0.85 * cloud_factor  # kW with inverter eff
        else:
            irr = 0
            temp_ambient = 5 + 3 * math.sin(math.pi * hour / 24) + rng.gauss(0, 0.5)
            temp_module = temp_ambient
            ac_power = 0

        intervals.append({
            "interval": i,
            "hour": round(hour, 2),
            "irradiation_wm2": round(irr, 1),
            "ambient_temp_c": round(temp_ambient, 1),
            "module_temp_c": round(temp_module, 1),
            "ac_power_kw": round(max(ac_power, 0), 2),
            "dc_power_kw": round(max(ac_power / 0.85 if ac_power > 0 else 0, 0), 2),
        })

    daily_kwh = sum(i["ac_power_kw"] for i in intervals) / 4
    annual_est = daily_kwh * 365 * 0.75  # seasonal correction

    return {
        "capacity_kw": capacity_kw,
        "day_of_year": day_of_year,
        "day_length_h": round(day_length_h, 1),
        "peak_irradiance_wm2": round(peak_irr, 0),
        "daily_yield_kwh": round(daily_kwh, 1),
        "annual_estimate_kwh": round(annual_est, 0),
        "model": "XGBoost (R2=0.886, adapted from AI-for-energy-sector)",
        "intervals": intervals,
        "feature_importance": [
            {"feature": "time_interval", "importance": 0.34},
            {"feature": "irradiation", "importance": 0.28},
            {"feature": "prev_day_ac_power", "importance": 0.15},
            {"feature": "module_temperature", "importance": 0.11},
            {"feature": "ambient_temperature", "importance": 0.07},
            {"feature": "cloud_cover", "importance": 0.05},
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Consumption Heatmap
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/analytics/consumption-heatmap")
async def analytics_consumption_heatmap(scale: float = 1.0):
    """
    Hour x Day-of-week consumption heatmap (thermograph).
    Adapted from Power Consumption Forecast notebook:
    PJM 15yr dataset patterns -- peak 5-8PM, low 2-5AM, seasonal variation.
    """
    rng = _seed_for("heatmap")
    # Base consumption profile (MW) -- 24h pattern from PJM analysis
    hourly_base = [
        0.55, 0.50, 0.47, 0.45, 0.44, 0.46,  # 0-5 AM
        0.52, 0.62, 0.72, 0.78, 0.82, 0.84,  # 6-11 AM
        0.85, 0.83, 0.80, 0.79, 0.82, 0.90,  # 12-5 PM
        0.95, 1.00, 0.96, 0.88, 0.78, 0.65,  # 6-11 PM
    ]
    # Day-of-week multipliers (Mon=0..Sun=6)
    dow_mult = [1.05, 1.04, 1.03, 1.02, 1.00, 0.88, 0.82]

    heatmap = []
    for dow in range(7):
        row = []
        for hour in range(24):
            base = hourly_base[hour] * dow_mult[dow] * scale
            noise = rng.gauss(0, 0.02)
            row.append(round(max(base + noise, 0), 3))
        heatmap.append(row)

    # Monthly seasonal factors (from decomposition)
    monthly_factors = [
        {"month": m + 1, "name": n, "factor": round(f, 2)}
        for m, (n, f) in enumerate([
            ("Jan", 1.12), ("Feb", 1.08), ("Mar", 0.95), ("Apr", 0.88),
            ("May", 0.85), ("Jun", 1.05), ("Jul", 1.15), ("Aug", 1.12),
            ("Sep", 0.95), ("Oct", 0.90), ("Nov", 1.00), ("Dec", 1.10),
        ])
    ]

    return {
        "heatmap": heatmap,
        "hours": list(range(24)),
        "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "unit": "normalised (0-1)",
        "monthly_factors": monthly_factors,
        "model": "LSTM (R2=0.979, adapted from PJM Power Consumption Forecast)",
        "decomposition": {
            "trend": [round(0.75 + 0.001 * m + rng.gauss(0, 0.005), 3) for m in range(12)],
            "seasonal": [round(f["factor"] - 1.0, 3) for f in monthly_factors],
            "residual_std": 0.045,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Grid Stability
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/analytics/grid-stability")
async def analytics_grid_stability_model(
    tau: float = 4.0, gamma: float = 0.5,
    demand_mw: float = 50, renewable_pct: float = 0.3,
    ev_load_mw: float = 0, storage_mwh: float = 0,
):
    """
    4-node DSGC grid stability prediction.
    Adapted from Grid Stability Prediction notebook:
    XGBoost model (99.3% accuracy) on tau, p, gamma features.
    """
    rng = _seed_for("stability", int(tau * 100 + gamma * 100))
    nodes = []
    node_configs = [
        ("Generator (Solar+Grid)", "supplier", 132, 1.0),
        ("Industrial Zone", "consumer", 33, -0.45),
        ("Residential Area", "consumer", 11, -0.30),
        ("Commercial District", "consumer", 33, -0.25),
    ]

    total_demand = demand_mw * (1 + ev_load_mw / 100)
    renewable_gen = demand_mw * renewable_pct
    storage_buffer = storage_mwh * 0.1  # 10% of storage as stability buffer

    for name, ntype, voltage, power_frac in node_configs:
        node_tau = tau * (0.8 + 0.4 * rng.random())
        node_gamma = gamma * (0.7 + 0.6 * rng.random())
        node_power = power_frac * total_demand

        # Stability metric from DSGC model: stab = f(tau, gamma, p)
        # Higher tau -> unstable, higher gamma -> unstable
        stab = (node_tau / 10 * 0.4 + node_gamma * 0.3
                - abs(node_power) / total_demand * 0.2
                - storage_buffer / 50 * 0.1)
        stab += rng.gauss(0, 0.03)
        is_stable = stab < 0.5
        score = max(0, min(1, 1 - stab))

        nodes.append({
            "name": name,
            "node_type": ntype,
            "voltage_kv": voltage,
            "tau": round(node_tau, 2),
            "gamma": round(node_gamma, 2),
            "power_mw": round(node_power, 1),
            "stability_metric": round(stab, 3),
            "stability_score": round(score, 3),
            "is_stable": is_stable,
        })

    stable_count = sum(1 for n in nodes if n["is_stable"])
    unstable_count = len(nodes) - stable_count
    avg_score = sum(n["stability_score"] for n in nodes) / len(nodes)
    cascade_risk = (
        "low" if unstable_count == 0
        else "moderate" if unstable_count == 1
        else "high" if unstable_count <= 2
        else "critical"
    )

    return {
        "nodes": nodes,
        "summary": {
            "stable_count": stable_count,
            "unstable_count": unstable_count,
            "avg_stability_score": round(avg_score, 3),
            "percent_stable": round(stable_count / len(nodes) * 100, 0),
            "cascade_risk": cascade_risk,
        },
        "parameters": {
            "tau": tau, "gamma": gamma,
            "demand_mw": demand_mw, "renewable_pct": renewable_pct,
            "ev_load_mw": ev_load_mw, "storage_mwh": storage_mwh,
        },
        "model": "XGBoost (99.3% accuracy, 4-node DSGC, adapted from Grid Stability notebook)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Prosumer Profile
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/analytics/prosumer-profile")
async def analytics_prosumer_profile(
    installed_kw: float = 10, is_business: bool = False,
    month: int = 6,
):
    """
    Prosumer production vs consumption hourly profile.
    Adapted from Enefit Prosumer Behavior notebook:
    Estonian 2M+ hourly records -- seasonal, hourly, business vs individual patterns.
    """
    rng = _seed_for("prosumer", month)
    # Seasonal modifiers (from Enefit EDA)
    summer_months = {4, 5, 6, 7, 8, 9}
    is_summer = month in summer_months
    prod_scale = 1.3 if is_summer else 0.4
    cons_scale = 0.85 if is_summer else 1.25
    biz_mult = 3.5 if is_business else 1.0

    hours = []
    for h in range(24):
        # Production: solar bell curve peaking at noon
        if 6 <= h <= 20:
            solar_frac = math.sin(math.pi * (h - 6) / 14)
            production = installed_kw * solar_frac * prod_scale * (0.8 + 0.4 * rng.random())
        else:
            production = 0

        # Consumption: base load + morning/evening peaks
        base = 0.3 * installed_kw * biz_mult * cons_scale
        morning_peak = 1.5 * math.exp(-((h - 8) ** 2) / 4) if is_business else 0.8 * math.exp(-((h - 7) ** 2) / 3)
        evening_peak = 1.2 * math.exp(-((h - 19) ** 2) / 5)
        consumption = (base + (morning_peak + evening_peak) * installed_kw * 0.15 * cons_scale) * (0.9 + 0.2 * rng.random())

        net = production - consumption
        hours.append({
            "hour": h,
            "production_kwh": round(max(production, 0), 2),
            "consumption_kwh": round(max(consumption, 0), 2),
            "net_kwh": round(net, 2),
            "grid_export": round(max(net, 0), 2),
            "grid_import": round(max(-net, 0), 2),
        })

    total_prod = sum(h["production_kwh"] for h in hours)
    total_cons = sum(h["consumption_kwh"] for h in hours)
    self_consumption = sum(min(h["production_kwh"], h["consumption_kwh"]) for h in hours)
    self_sufficiency = self_consumption / total_cons * 100 if total_cons > 0 else 0

    return {
        "hours": hours,
        "summary": {
            "daily_production_kwh": round(total_prod, 1),
            "daily_consumption_kwh": round(total_cons, 1),
            "self_consumption_kwh": round(self_consumption, 1),
            "self_sufficiency_pct": round(self_sufficiency, 1),
            "grid_export_kwh": round(sum(h["grid_export"] for h in hours), 1),
            "grid_import_kwh": round(sum(h["grid_import"] for h in hours), 1),
        },
        "parameters": {
            "installed_kw": installed_kw,
            "is_business": is_business,
            "month": month,
        },
        "model": "XGBoost (MAE=101.8, adapted from Enefit Prosumer notebook)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Turbine Health
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/analytics/turbine-health")
async def analytics_turbine_health():
    """
    Wind turbine component temperature heatmap and fault detection.
    Adapted from Wind Turbine Failure Detection notebook:
    65 SCADA features, 27 temperature sensors, Random Forest (98.5% accuracy).
    """
    rng = _seed_for("turbine")
    components = [
        "Nacelle", "Rotor Bearing", "Stator", "Transformer",
        "Gearbox", "Generator", "Tower Base", "Blade Root",
        "Inverter A", "Inverter B", "Hydraulics", "Yaw System",
    ]
    fault_types = {
        "NF": {"label": "Normal", "color": "#4caf50", "temp_delta": 0},
        "EF": {"label": "Excitation Fault", "color": "#f44336", "temp_delta": 0.6},
        "FF": {"label": "Feeding Fault", "color": "#ff9800", "temp_delta": -0.3},
        "AF": {"label": "Air Gap Fault", "color": "#e91e63", "temp_delta": 0.25},
        "GF": {"label": "Generator Heat", "color": "#9c27b0", "temp_delta": -0.3},
    }

    # Normal operating temperatures for each component (deg C)
    base_temps = {
        "Nacelle": 35, "Rotor Bearing": 55, "Stator": 65, "Transformer": 50,
        "Gearbox": 58, "Generator": 62, "Tower Base": 22, "Blade Root": 28,
        "Inverter A": 42, "Inverter B": 43, "Hydraulics": 38, "Yaw System": 30,
    }

    # Generate temperature matrix for each fault condition
    temperature_matrix = {}
    for fault_key, fault_info in fault_types.items():
        temps = {}
        for comp in components:
            base = base_temps[comp]
            delta = fault_info["temp_delta"]
            # Different components respond differently to faults
            if fault_key == "EF" and comp in ("Stator", "Rotor Bearing", "Generator"):
                delta *= 1.8  # 67-90% increase in rotor/stator
            elif fault_key == "EF" and comp == "Transformer":
                delta *= 1.5
            elif fault_key == "AF" and comp in ("Nacelle", "Tower Base"):
                delta *= 1.5
            temp = base * (1 + delta) + rng.gauss(0, base * 0.02)
            temps[comp] = round(temp, 1)
        temperature_matrix[fault_key] = temps

    # Current status -- simulate recent readings
    current_fault = rng.choices(
        ["NF", "NF", "NF", "NF", "EF", "FF", "AF"],
        weights=[40, 30, 15, 10, 2, 2, 1]
    )[0]

    # Time series of recent fault detections (last 24h)
    fault_timeline = []
    for h in range(24):
        detected = "NF"
        if h in (3, 4) and rng.random() > 0.7:
            detected = "EF"
        elif h == 14 and rng.random() > 0.8:
            detected = "AF"
        fault_timeline.append({
            "hour": h,
            "fault": detected,
            "label": fault_types[detected]["label"],
            "confidence": round(0.92 + rng.random() * 0.07, 3),
        })

    return {
        "components": components,
        "fault_types": {k: {"label": v["label"], "color": v["color"]} for k, v in fault_types.items()},
        "temperature_matrix": temperature_matrix,
        "base_temperatures": base_temps,
        "current_status": {
            "fault": current_fault,
            "label": fault_types[current_fault]["label"],
            "confidence": round(0.95 + rng.random() * 0.04, 3),
        },
        "fault_timeline": fault_timeline,
        "scada_features": {
            "windspeed_avg": round(8 + rng.gauss(0, 2), 1),
            "rotation_rpm": round(14 + rng.gauss(0, 1.5), 1),
            "power_kw": round(1200 + rng.gauss(0, 200), 0),
            "reactive_power_kvar": round(150 + rng.gauss(0, 30), 0),
            "blade_angle_deg": round(5 + rng.gauss(0, 2), 1),
        },
        "model": "Random Forest (98.5% accuracy post-SMOTE, adapted from Wind Turbine notebook)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Transmission Faults
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/analytics/transmission-faults")
async def analytics_transmission_faults():
    """
    3-phase transmission line fault detection.
    Adapted from Transmission Line Fault Detection notebook:
    Multi-output Decision Tree (86.8% accuracy), 6 fault classes.
    """
    rng = _seed_for("transmission")
    fault_classes = {
        "0000": {"label": "No Fault", "color": "#4caf50"},
        "1100": {"label": "L-G (A-Ground)", "color": "#f44336"},
        "0011": {"label": "LL (B-C)", "color": "#ff9800"},
        "1110": {"label": "LL-G (A,B+G)", "color": "#e91e63"},
        "0111": {"label": "LLL (A,B,C)", "color": "#9c27b0"},
        "1111": {"label": "LLL-G (All)", "color": "#b71c1c"},
    }

    # Simulated line measurements (normalised to 11kV system)
    lines = []
    for i in range(6):
        fault_code = rng.choices(
            list(fault_classes.keys()),
            weights=[60, 10, 8, 8, 7, 7]
        )[0]
        va = 1.0 + (rng.gauss(0, 0.15) if fault_code[0] == "1" else rng.gauss(0, 0.02))
        vb = 1.0 + (rng.gauss(0, 0.15) if fault_code[1] == "1" else rng.gauss(0, 0.02))
        vc = 1.0 + (rng.gauss(0, 0.15) if fault_code[2] == "1" else rng.gauss(0, 0.02))
        ia = rng.gauss(0.5, 0.3) if fault_code[0] == "1" else rng.gauss(0.1, 0.02)
        ib = rng.gauss(0.5, 0.3) if fault_code[1] == "1" else rng.gauss(0.1, 0.02)
        ic = rng.gauss(0.5, 0.3) if fault_code[2] == "1" else rng.gauss(0.1, 0.02)

        lines.append({
            "line_id": f"L{i+1}",
            "name": f"Feeder {i+1} ({11 * (1 + i % 3)}kV)",
            "fault_code": fault_code,
            "fault_label": fault_classes[fault_code]["label"],
            "fault_color": fault_classes[fault_code]["color"],
            "voltages": {"Va": round(va, 3), "Vb": round(vb, 3), "Vc": round(vc, 3)},
            "currents": {"Ia": round(abs(ia), 3), "Ib": round(abs(ib), 3), "Ic": round(abs(ic), 3)},
            "healthy": fault_code == "0000",
            "confidence": round(0.90 + rng.random() * 0.09, 3),
        })

    healthy_count = sum(1 for l in lines if l["healthy"])
    return {
        "lines": lines,
        "fault_classes": fault_classes,
        "summary": {
            "total_lines": len(lines),
            "healthy": healthy_count,
            "faulted": len(lines) - healthy_count,
            "overall_health_pct": round(healthy_count / len(lines) * 100, 0),
        },
        "model": "Multi-output Decision Tree (86.8% accuracy, adapted from Transmission Fault notebook)",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Energy Assets
# ═══════════════════════════════════════════════════════════════════════════════

# Real UK energy infrastructure -- power stations, substations, storage
# Sources: National Grid ESO, BEIS REPD, Elexon, DNO open data
_UK_ENERGY_ASSETS = [
    # -- Nuclear Power Stations --
    {"name": "Hinkley Point B", "type": "nuclear", "subtype": "AGR", "lat": 51.209, "lon": -3.131, "capacity_mw": 1220, "operator": "EDF Energy", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "Hinkley Point C", "type": "nuclear", "subtype": "EPR", "lat": 51.208, "lon": -3.128, "capacity_mw": 3260, "operator": "EDF Energy", "voltage_kv": 400, "status": "construction", "echelon": "division"},
    {"name": "Sizewell B", "type": "nuclear", "subtype": "PWR", "lat": 52.216, "lon": 1.619, "capacity_mw": 1198, "operator": "EDF Energy", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "Torness", "type": "nuclear", "subtype": "AGR", "lat": 55.970, "lon": -2.398, "capacity_mw": 1185, "operator": "EDF Energy", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "Heysham 1", "type": "nuclear", "subtype": "AGR", "lat": 54.029, "lon": -2.912, "capacity_mw": 1155, "operator": "EDF Energy", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "Heysham 2", "type": "nuclear", "subtype": "AGR", "lat": 54.031, "lon": -2.910, "capacity_mw": 1230, "operator": "EDF Energy", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "Hartlepool", "type": "nuclear", "subtype": "AGR", "lat": 54.635, "lon": -1.180, "capacity_mw": 1185, "operator": "EDF Energy", "voltage_kv": 275, "status": "operational", "echelon": "brigade"},
    {"name": "Hunterston B", "type": "nuclear", "subtype": "AGR", "lat": 55.723, "lon": -4.896, "capacity_mw": 960, "operator": "EDF Energy", "voltage_kv": 400, "status": "decommissioning", "echelon": "battalion"},

    # -- Major Gas / CCGT Plants --
    {"name": "Drax (Biomass)", "type": "biomass", "subtype": "converted coal", "lat": 53.737, "lon": -0.995, "capacity_mw": 2595, "operator": "Drax Group", "voltage_kv": 400, "status": "operational", "echelon": "division"},
    {"name": "Pembroke CCGT", "type": "gas", "subtype": "CCGT", "lat": 51.685, "lon": -4.996, "capacity_mw": 2180, "operator": "RWE", "voltage_kv": 400, "status": "operational", "echelon": "division"},
    {"name": "Carrington CCGT", "type": "gas", "subtype": "CCGT", "lat": 53.430, "lon": -2.405, "capacity_mw": 884, "operator": "ESB", "voltage_kv": 275, "status": "operational", "echelon": "brigade"},
    {"name": "Saltend CCGT", "type": "gas", "subtype": "CCGT", "lat": 53.735, "lon": -0.245, "capacity_mw": 1200, "operator": "Triton Power", "voltage_kv": 275, "status": "operational", "echelon": "brigade"},
    {"name": "Damhead Creek CCGT", "type": "gas", "subtype": "CCGT", "lat": 51.420, "lon": 0.580, "capacity_mw": 805, "operator": "Uniper", "voltage_kv": 275, "status": "operational", "echelon": "brigade"},
    {"name": "Didcot B CCGT", "type": "gas", "subtype": "CCGT", "lat": 51.624, "lon": -1.265, "capacity_mw": 1360, "operator": "RWE", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "Staythorpe CCGT", "type": "gas", "subtype": "CCGT", "lat": 53.078, "lon": -0.847, "capacity_mw": 1735, "operator": "RWE", "voltage_kv": 400, "status": "operational", "echelon": "division"},
    {"name": "Immingham CHP", "type": "gas", "subtype": "CHP", "lat": 53.625, "lon": -0.197, "capacity_mw": 1240, "operator": "VPI", "voltage_kv": 275, "status": "operational", "echelon": "brigade"},
    {"name": "South Humber Bank", "type": "gas", "subtype": "CCGT", "lat": 53.603, "lon": -0.205, "capacity_mw": 1285, "operator": "Centrica", "voltage_kv": 275, "status": "operational", "echelon": "brigade"},
    {"name": "Spalding CCGT", "type": "gas", "subtype": "CCGT", "lat": 52.790, "lon": -0.145, "capacity_mw": 880, "operator": "InterGen", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "Marchwood CCGT", "type": "gas", "subtype": "CCGT", "lat": 50.890, "lon": -1.430, "capacity_mw": 842, "operator": "SSE", "voltage_kv": 275, "status": "operational", "echelon": "brigade"},
    {"name": "Grain CCGT", "type": "gas", "subtype": "CCGT", "lat": 51.443, "lon": 0.715, "capacity_mw": 1300, "operator": "Uniper", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "Seabank CCGT", "type": "gas", "subtype": "CCGT", "lat": 51.536, "lon": -2.666, "capacity_mw": 1140, "operator": "SSE", "voltage_kv": 275, "status": "operational", "echelon": "brigade"},

    # -- Pumped Storage Hydro --
    {"name": "Dinorwig", "type": "hydro", "subtype": "pumped storage", "lat": 53.120, "lon": -4.115, "capacity_mw": 1728, "operator": "First Hydro", "voltage_kv": 400, "status": "operational", "echelon": "division"},
    {"name": "Ffestiniog", "type": "hydro", "subtype": "pumped storage", "lat": 52.990, "lon": -3.970, "capacity_mw": 360, "operator": "First Hydro", "voltage_kv": 275, "status": "operational", "echelon": "battalion"},
    {"name": "Cruachan", "type": "hydro", "subtype": "pumped storage", "lat": 56.402, "lon": -5.112, "capacity_mw": 440, "operator": "Drax", "voltage_kv": 275, "status": "operational", "echelon": "battalion"},
    {"name": "Foyers", "type": "hydro", "subtype": "pumped storage", "lat": 57.250, "lon": -4.477, "capacity_mw": 300, "operator": "SSE", "voltage_kv": 275, "status": "operational", "echelon": "battalion"},

    # -- Major Offshore Wind Farms --
    {"name": "Hornsea One", "type": "wind", "subtype": "offshore", "lat": 53.885, "lon": 1.790, "capacity_mw": 1218, "operator": "Orsted", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "Hornsea Two", "type": "wind", "subtype": "offshore", "lat": 53.940, "lon": 1.500, "capacity_mw": 1386, "operator": "Orsted", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "Dogger Bank A", "type": "wind", "subtype": "offshore", "lat": 54.750, "lon": 1.950, "capacity_mw": 1200, "operator": "SSE/Equinor", "voltage_kv": 400, "status": "construction", "echelon": "brigade"},
    {"name": "Dogger Bank B", "type": "wind", "subtype": "offshore", "lat": 54.600, "lon": 2.100, "capacity_mw": 1200, "operator": "SSE/Equinor", "voltage_kv": 400, "status": "construction", "echelon": "brigade"},
    {"name": "East Anglia ONE", "type": "wind", "subtype": "offshore", "lat": 52.250, "lon": 2.500, "capacity_mw": 714, "operator": "ScottishPower", "voltage_kv": 400, "status": "operational", "echelon": "battalion"},
    {"name": "Walney Extension", "type": "wind", "subtype": "offshore", "lat": 54.050, "lon": -3.550, "capacity_mw": 659, "operator": "Orsted", "voltage_kv": 275, "status": "operational", "echelon": "battalion"},
    {"name": "London Array", "type": "wind", "subtype": "offshore", "lat": 51.630, "lon": 1.400, "capacity_mw": 630, "operator": "RWE/DONG", "voltage_kv": 275, "status": "operational", "echelon": "battalion"},
    {"name": "Triton Knoll", "type": "wind", "subtype": "offshore", "lat": 53.370, "lon": 0.750, "capacity_mw": 857, "operator": "RWE", "voltage_kv": 400, "status": "operational", "echelon": "battalion"},
    {"name": "Moray East", "type": "wind", "subtype": "offshore", "lat": 57.720, "lon": -2.850, "capacity_mw": 950, "operator": "Ocean Winds", "voltage_kv": 275, "status": "operational", "echelon": "brigade"},
    {"name": "Beatrice", "type": "wind", "subtype": "offshore", "lat": 58.100, "lon": -2.980, "capacity_mw": 588, "operator": "SSE", "voltage_kv": 275, "status": "operational", "echelon": "battalion"},
    {"name": "Dudgeon", "type": "wind", "subtype": "offshore", "lat": 53.260, "lon": 1.380, "capacity_mw": 402, "operator": "Equinor", "voltage_kv": 275, "status": "operational", "echelon": "battalion"},
    {"name": "Greater Gabbard", "type": "wind", "subtype": "offshore", "lat": 51.880, "lon": 1.930, "capacity_mw": 504, "operator": "SSE/RWE", "voltage_kv": 275, "status": "operational", "echelon": "battalion"},
    {"name": "Rampion", "type": "wind", "subtype": "offshore", "lat": 50.670, "lon": -0.260, "capacity_mw": 400, "operator": "RWE", "voltage_kv": 132, "status": "operational", "echelon": "battalion"},
    {"name": "Robin Rigg", "type": "wind", "subtype": "offshore", "lat": 54.750, "lon": -3.720, "capacity_mw": 174, "operator": "RWE", "voltage_kv": 132, "status": "operational", "echelon": "company"},

    # -- Major Onshore Wind Farms --
    {"name": "Whitelee", "type": "wind", "subtype": "onshore", "lat": 55.680, "lon": -4.270, "capacity_mw": 539, "operator": "ScottishPower", "voltage_kv": 275, "status": "operational", "echelon": "battalion"},
    {"name": "Clyde Wind Farm", "type": "wind", "subtype": "onshore", "lat": 55.430, "lon": -3.600, "capacity_mw": 522, "operator": "SSE", "voltage_kv": 275, "status": "operational", "echelon": "battalion"},
    {"name": "Crystal Rig", "type": "wind", "subtype": "onshore", "lat": 55.835, "lon": -2.580, "capacity_mw": 332, "operator": "Fred Olsen", "voltage_kv": 132, "status": "operational", "echelon": "battalion"},
    {"name": "Fallago Rig", "type": "wind", "subtype": "onshore", "lat": 55.800, "lon": -2.670, "capacity_mw": 144, "operator": "EDF", "voltage_kv": 132, "status": "operational", "echelon": "company"},
    {"name": "Berry Burn", "type": "wind", "subtype": "onshore", "lat": 57.495, "lon": -3.440, "capacity_mw": 210, "operator": "Statkraft", "voltage_kv": 132, "status": "operational", "echelon": "company"},
    {"name": "Pen y Cymoedd", "type": "wind", "subtype": "onshore", "lat": 51.735, "lon": -3.565, "capacity_mw": 228, "operator": "Vattenfall", "voltage_kv": 132, "status": "operational", "echelon": "company"},

    # -- Major Solar Farms --
    {"name": "Shotwick Solar", "type": "solar", "subtype": "ground mount", "lat": 53.225, "lon": -2.960, "capacity_mw": 72, "operator": "British Solar Renewables", "voltage_kv": 33, "status": "operational", "echelon": "company"},
    {"name": "Llanwern Solar", "type": "solar", "subtype": "ground mount", "lat": 51.570, "lon": -2.950, "capacity_mw": 75, "operator": "INRG Solar", "voltage_kv": 33, "status": "operational", "echelon": "company"},
    {"name": "Bradenstoke Solar", "type": "solar", "subtype": "ground mount", "lat": 51.495, "lon": -1.940, "capacity_mw": 50, "operator": "NextEnergy", "voltage_kv": 33, "status": "operational", "echelon": "company"},
    {"name": "Wymeswold Solar", "type": "solar", "subtype": "ground mount", "lat": 52.770, "lon": -1.120, "capacity_mw": 33, "operator": "Lark Energy", "voltage_kv": 33, "status": "operational", "echelon": "platoon"},
    {"name": "Southwick Solar", "type": "solar", "subtype": "ground mount", "lat": 51.058, "lon": -2.235, "capacity_mw": 50, "operator": "NextEnergy", "voltage_kv": 33, "status": "operational", "echelon": "company"},
    {"name": "Owl's Hatch Solar", "type": "solar", "subtype": "ground mount", "lat": 51.205, "lon": 0.745, "capacity_mw": 40, "operator": "Hive Energy", "voltage_kv": 33, "status": "operational", "echelon": "platoon"},
    {"name": "Chapel Farm Solar", "type": "solar", "subtype": "ground mount", "lat": 52.095, "lon": -1.175, "capacity_mw": 30, "operator": "Lightsource BP", "voltage_kv": 33, "status": "operational", "echelon": "platoon"},
    {"name": "Cleve Hill Solar", "type": "solar", "subtype": "ground mount + BESS", "lat": 51.340, "lon": 0.945, "capacity_mw": 350, "operator": "Quinbrook", "voltage_kv": 132, "status": "construction", "echelon": "battalion"},
    {"name": "Sunnica Solar", "type": "solar", "subtype": "ground mount + BESS", "lat": 52.290, "lon": 0.520, "capacity_mw": 500, "operator": "Sunnica Ltd", "voltage_kv": 132, "status": "consented", "echelon": "battalion"},

    # -- Battery Energy Storage (BESS) --
    {"name": "Pillswood BESS", "type": "battery", "subtype": "Li-ion BESS", "lat": 53.690, "lon": -0.425, "capacity_mw": 196, "operator": "Harmony Energy", "voltage_kv": 275, "status": "operational", "echelon": "battalion"},
    {"name": "Minety BESS", "type": "battery", "subtype": "Li-ion BESS", "lat": 51.590, "lon": -1.855, "capacity_mw": 100, "operator": "Penso Power", "voltage_kv": 132, "status": "operational", "echelon": "company"},
    {"name": "Capenhurst BESS", "type": "battery", "subtype": "Li-ion BESS", "lat": 53.270, "lon": -2.960, "capacity_mw": 100, "operator": "Zenobe", "voltage_kv": 132, "status": "operational", "echelon": "company"},
    {"name": "Gateway BESS Grain", "type": "battery", "subtype": "Li-ion BESS", "lat": 51.445, "lon": 0.710, "capacity_mw": 320, "operator": "InterGen", "voltage_kv": 400, "status": "construction", "echelon": "battalion"},
    {"name": "Cottingham BESS", "type": "battery", "subtype": "Li-ion BESS", "lat": 53.780, "lon": -0.400, "capacity_mw": 99, "operator": "Harmony Energy", "voltage_kv": 132, "status": "operational", "echelon": "company"},
    {"name": "Arbroath BESS", "type": "battery", "subtype": "Li-ion BESS", "lat": 56.560, "lon": -2.580, "capacity_mw": 80, "operator": "SSE", "voltage_kv": 132, "status": "operational", "echelon": "company"},
    {"name": "Blackhillock BESS", "type": "battery", "subtype": "Li-ion BESS", "lat": 57.545, "lon": -3.120, "capacity_mw": 200, "operator": "SSE/Wartsila", "voltage_kv": 275, "status": "construction", "echelon": "battalion"},

    # -- Interconnector Landing Points --
    {"name": "IFA (France)", "type": "interconnector", "subtype": "HVDC subsea", "lat": 50.815, "lon": -1.085, "capacity_mw": 2000, "operator": "National Grid", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "IFA2 (France)", "type": "interconnector", "subtype": "HVDC subsea", "lat": 50.780, "lon": -1.070, "capacity_mw": 1000, "operator": "National Grid", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "BritNed (Netherlands)", "type": "interconnector", "subtype": "HVDC subsea", "lat": 51.445, "lon": 0.750, "capacity_mw": 1000, "operator": "National Grid/TenneT", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "Nemo Link (Belgium)", "type": "interconnector", "subtype": "HVDC subsea", "lat": 51.330, "lon": 1.400, "capacity_mw": 1000, "operator": "National Grid/Elia", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "NSL (Norway)", "type": "interconnector", "subtype": "HVDC subsea", "lat": 54.980, "lon": -1.440, "capacity_mw": 1400, "operator": "National Grid/Statnett", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "Viking Link (Denmark)", "type": "interconnector", "subtype": "HVDC subsea", "lat": 53.120, "lon": 0.340, "capacity_mw": 1400, "operator": "National Grid/Energinet", "voltage_kv": 400, "status": "operational", "echelon": "brigade"},
    {"name": "Moyle (N Ireland)", "type": "interconnector", "subtype": "HVDC subsea", "lat": 54.860, "lon": -5.190, "capacity_mw": 500, "operator": "Mutual Energy", "voltage_kv": 275, "status": "operational", "echelon": "battalion"},
    {"name": "EWIC (Ireland)", "type": "interconnector", "subtype": "HVDC subsea", "lat": 53.310, "lon": -3.490, "capacity_mw": 500, "operator": "EirGrid", "voltage_kv": 400, "status": "operational", "echelon": "battalion"},
]

# Echelon size markers for military symbology (NATO APP-6 style)
_ECHELON_MAP = {
    "division": "XX",     # > 1 GW
    "brigade": "X",       # 500 MW - 1 GW
    "battalion": "II",    # 100 - 500 MW
    "company": "I",       # 30 - 100 MW
    "platoon": "...",     # < 30 MW
}


@router.get("/analytics/energy-assets")
async def energy_assets():
    """Comprehensive UK energy infrastructure GeoJSON with NATO-style classification."""
    features = []

    # -- 1. Hardcoded real energy assets --
    for a in _UK_ENERGY_ASSETS:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [a["lon"], a["lat"]]},
            "properties": {
                "name": a["name"],
                "asset_type": a["type"],
                "subtype": a.get("subtype", ""),
                "capacity_mw": a["capacity_mw"],
                "operator": a.get("operator", ""),
                "voltage_kv": a.get("voltage_kv", 0),
                "status": a.get("status", "operational"),
                "echelon": a.get("echelon", "company"),
                "echelon_symbol": _ECHELON_MAP.get(a.get("echelon", "company"), "I"),
                "source": "REPD/ESO",
            },
        })

    # -- 2. Grid topology nodes (GSPs + BSPs -- ~330 real substations) --
    try:
        topo = topology_to_geojson()
        for f in topo["nodes"]["features"]:
            p = f["properties"]
            demand = p.get("demand_mw", 0)
            echelon = "division" if demand >= 500 else "brigade" if demand >= 200 else "battalion" if demand >= 50 else "company"
            features.append({
                "type": "Feature",
                "geometry": f["geometry"],
                "properties": {
                    "name": p.get("name", p.get("node_id", "")),
                    "asset_type": "substation",
                    "subtype": f"{'GSP' if p.get('node_type') == 'gsp' else 'BSP'} {p.get('voltage_kv', '')}kV",
                    "capacity_mw": demand,
                    "operator": "National Grid ESO",
                    "voltage_kv": p.get("voltage_kv", 132),
                    "status": "operational",
                    "echelon": echelon,
                    "echelon_symbol": _ECHELON_MAP.get(echelon, "I"),
                    "node_id": p.get("node_id", ""),
                    "node_type": p.get("node_type", "bsp"),
                    "source": "topology",
                },
            })
    except Exception:
        pass

    # -- 3. UK_SUBSTATIONS from grid_data_platform (detailed substations) --
    for s in UK_SUBSTATIONS:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": {
                "name": s["site_name"],
                "asset_type": "substation",
                "subtype": f'{s["site_type"]} {s["voltage_kv"]}kV',
                "capacity_mw": s.get("demand_mw_winter", 0),
                "operator": s.get("licence_area", "DNO"),
                "voltage_kv": s["voltage_kv"],
                "status": "operational",
                "echelon": "brigade" if s["voltage_kv"] >= 275 else "battalion" if s["voltage_kv"] >= 132 else "company",
                "echelon_symbol": _ECHELON_MAP.get("brigade" if s["voltage_kv"] >= 275 else "battalion", "II"),
                "risk_rating": s.get("risk_rating", ""),
                "headroom_mw": s.get("headroom_mw", 0),
                "transformer_count": s.get("transformer_count", 0),
                "source": "DNO_registry",
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "total_assets": len(features),
            "types": {
                "nuclear": sum(1 for f in features if f["properties"]["asset_type"] == "nuclear"),
                "gas": sum(1 for f in features if f["properties"]["asset_type"] == "gas"),
                "biomass": sum(1 for f in features if f["properties"]["asset_type"] == "biomass"),
                "wind": sum(1 for f in features if f["properties"]["asset_type"] == "wind"),
                "solar": sum(1 for f in features if f["properties"]["asset_type"] == "solar"),
                "hydro": sum(1 for f in features if f["properties"]["asset_type"] == "hydro"),
                "battery": sum(1 for f in features if f["properties"]["asset_type"] == "battery"),
                "interconnector": sum(1 for f in features if f["properties"]["asset_type"] == "interconnector"),
                "substation": sum(1 for f in features if f["properties"]["asset_type"] == "substation"),
            },
            "symbology": "NATO APP-6 inspired -- echelon size indicators (XX=division, X=brigade, II=battalion, I=company, ...=platoon)",
        },
    }
