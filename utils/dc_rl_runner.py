#!/usr/bin/env python3
"""
dc-rl Physics Runner — subprocess bridge to HPE SustainDC thermal model.

Provides physics-based data centre simulation:
  - DC thermal model: IT power, HVAC cooling, rack temperatures, PUE
  - Battery model: charge/discharge with efficiency curves, SoC tracking
  - Carbon-aware scheduling: workload shifting to minimise carbon footprint
  - 24h simulation: hourly physics with weather + carbon intensity inputs

Usage (subprocess, same pattern as sam_runner.py / grid_power_flow.py):
    python dc_rl_runner.py simulate '{"it_load_pct": 60, "ambient_temp_c": 18, ...}'
    python dc_rl_runner.py simulate_24h '{"it_load_mw": 50, "hourly_ambient_c": [...], ...}'
    python dc_rl_runner.py battery '{"capacity_mwh": 100, "soc_pct": 50, ...}'
    python dc_rl_runner.py optimise '{"it_load_mw": 50, "hourly_ambient_c": [...], ...}'

Requires: numpy (available in .venv-grid/)

Power models ported from OpenDC (AtLarge Research, TU Delft, MIT license):
  - 8 CPU power models: constant, linear, square, cubic, sqrt, MSE, asymptotic, interpolation
  - Embodied carbon tracking (manufacturing CO2 per host)
"""
import json
import sys
import os
import math

import numpy as np


# ═══════════════════════════════════════════════════════════════════
#  OPENDC POWER MODELS (ported from Java → Python)
#  Source: vendor/opendc/opendc-simulator/.../PowerModels.java
#  License: MIT (AtLarge Research, TU Delft)
# ═══════════════════════════════════════════════════════════════════

def power_constant(util: float, power: float = 500.0, **_) -> float:
    """Fixed power regardless of utilisation."""
    return power

def power_linear(util: float, max_power: float = 500.0, idle_power: float = 200.0, **_) -> float:
    """P = idle + (max - idle) * utilisation."""
    u = max(0.0, min(1.0, util))
    return idle_power + (max_power - idle_power) * u

def power_square(util: float, max_power: float = 500.0, idle_power: float = 200.0, **_) -> float:
    """P = idle + (max - idle) * utilisation^2."""
    u = max(0.0, min(1.0, util))
    return idle_power + (max_power - idle_power) * u ** 2

def power_cubic(util: float, max_power: float = 500.0, idle_power: float = 200.0, **_) -> float:
    """P = idle + (max - idle) * utilisation^3."""
    u = max(0.0, min(1.0, util))
    return idle_power + (max_power - idle_power) * u ** 3

def power_sqrt(util: float, max_power: float = 500.0, idle_power: float = 200.0, **_) -> float:
    """P = idle + (max - idle) * sqrt(utilisation). CloudSim model."""
    u = max(0.0, min(1.0, util))
    return idle_power + (max_power - idle_power) * math.sqrt(u)

def power_mse(util: float, max_power: float = 500.0, idle_power: float = 200.0,
              calibration: float = 1.4, **_) -> float:
    """MSE-minimised model (Fan et al., ACM SIGARCH'07)."""
    factor = (max_power - idle_power) / 100
    return idle_power + factor * (2 * util - util ** calibration) * 100

def power_asymptotic(util: float, max_power: float = 500.0, idle_power: float = 200.0,
                     asym_util: float = 0.3, dvfs: bool = False, **_) -> float:
    """Asymptotic model from GreenCloud. asym_util in [0.2, 0.5]."""
    factor = (max_power - idle_power) / 2
    u = max(0.0, min(1.0, util))
    if dvfs:
        return idle_power + factor * (1 + u ** 3 - math.exp(-(u ** 3) / asym_util))
    return idle_power + factor * (1 + u - math.exp(-u / asym_util))

def power_interpolate(util: float, power_levels: list = None, **_) -> float:
    """Linear interpolation over measured power levels (SPEC benchmark style).
    power_levels: list of 11 values [P@0%, P@10%, ..., P@100%]."""
    if not power_levels:
        power_levels = [200, 230, 260, 295, 330, 365, 400, 430, 460, 485, 500]
    u = max(0.0, min(1.0, util))
    idx = u * 10
    floor_idx = int(math.floor(idx))
    ceil_idx = min(int(math.ceil(idx)), len(power_levels) - 1)
    if floor_idx == ceil_idx:
        return power_levels[floor_idx]
    frac = idx - floor_idx
    return power_levels[floor_idx] + (power_levels[ceil_idx] - power_levels[floor_idx]) * frac

POWER_MODELS = {
    "constant": power_constant,
    "linear": power_linear,
    "square": power_square,
    "cubic": power_cubic,
    "sqrt": power_sqrt,
    "mse": power_mse,
    "asymptotic": power_asymptotic,
    "interpolate": power_interpolate,
}

# Embodied carbon data (kgCO2e per server, typical values from OpenDC research)
EMBODIED_CARBON = {
    "standard_1u": {"kgco2e": 320, "lifetime_years": 5},
    "gpu_server": {"kgco2e": 1200, "lifetime_years": 4},
    "storage_server": {"kgco2e": 450, "lifetime_years": 6},
    "networking": {"kgco2e": 150, "lifetime_years": 7},
    "rack_infrastructure": {"kgco2e": 80, "lifetime_years": 15},
}

# ── Add dc-rl to path ──────────────────────────────────────────────
DC_RL_ROOT = os.path.join(os.path.dirname(__file__), "..", "vendor", "dc-rl")
sys.path.insert(0, DC_RL_ROOT)

from utils.dc_config_reader import DC_Config
from envs.datacenter import DataCenter_ITModel, calculate_chiller_power


# ═══════════════════════════════════════════════════════════════════
#  DC CONFIG — scalable to any capacity
# ═══════════════════════════════════════════════════════════════════

def _build_dc_model(capacity_mw: float = 1.0, num_rows: int = 4, racks_per_row: int = 5):
    """Build a DataCenter_ITModel scaled to the given capacity."""
    dc_config = DC_Config("dc_config.json", datacenter_capacity_mw=capacity_mw)

    num_racks = num_rows * racks_per_row
    # Scale total power to match requested capacity
    total_kw = capacity_mw * 1000
    max_w_per_rack = int(total_kw * 1000 / num_racks)  # watts per rack

    # Build CPU configs for each rack
    rack_cpu_config = []
    cpus_per_rack = min(dc_config.CPUS_PER_RACK, 200)
    for _ in range(num_racks):
        rack_cpu_config.append([
            {"full_load_pwr": 170, "idle_pwr": 110}
            for _ in range(cpus_per_rack)
        ])

    # Supply/return approach temps (from dc_config defaults, extended to num_racks)
    base_supply = [5.3, 5.0, 5.0, 5.3]
    supply_temps = []
    for i in range(num_racks):
        row_idx = i // racks_per_row
        supply_temps.append(base_supply[row_idx % len(base_supply)])

    dc_model = DataCenter_ITModel(
        num_racks=num_racks,
        rack_supply_approach_temp_list=supply_temps,
        rack_CPU_config=rack_cpu_config,
        max_W_per_rack=max_w_per_rack,
        DC_ITModel_config=dc_config,
    )
    return dc_model, dc_config


# ═══════════════════════════════════════════════════════════════════
#  HVAC PHYSICS — CRAC + chiller + cooling tower
# ═══════════════════════════════════════════════════════════════════

def _compute_hvac(dc_model, dc_config, rackwise_cpu_pwr, rackwise_itfan_pwr,
                  rackwise_outlet_temp, crac_setpoint, ambient_temp_c):
    """Compute HVAC power breakdown from dc-rl physics model."""
    total_it_pwr_w = sum(rackwise_cpu_pwr) + sum(rackwise_itfan_pwr)
    avg_outlet_temp = float(np.mean(rackwise_outlet_temp))

    # CRAC fan power (proportional to airflow^3)
    num_racks = len(dc_model.racks_list)
    total_rack_fan_v = sum(r.get_total_rack_fan_v() for r in dc_model.racks_list)
    crac_supply_flow = dc_config.CRAC_SUPPLY_AIR_FLOW_RATE_pu * total_it_pwr_w
    crac_ref_flow = dc_config.CRAC_REFRENCE_AIR_FLOW_RATE_pu * total_it_pwr_w
    crac_fan_pwr = dc_config.CRAC_FAN_REF_P * num_racks * (crac_supply_flow / max(crac_ref_flow, 1e-6)) ** 3

    # Chiller — EnergyPlus-derived model from dc-rl
    heat_load = total_it_pwr_w  # all IT heat must be removed
    max_cooling_cap = total_it_pwr_w * 1.3  # 30% headroom
    chiller_pwr = calculate_chiller_power(max_cooling_cap, heat_load, ambient_temp_c)

    # Cooling tower fan + pumps
    ct_fan_pwr = dc_config.CT_FAN_REF_P * (crac_supply_flow / max(crac_ref_flow, 1e-6))
    cw_pump_pwr = (dc_config.CW_PRESSURE_DROP * dc_config.CW_WATER_FLOW_RATE) / dc_config.CW_PUMP_EFFICIENCY
    ct_pump_pwr = (dc_config.CT_PRESSURE_DROP * dc_config.CT_WATER_FLOW_RATE) / dc_config.CT_PUMP_EFFICIENCY

    total_hvac_pwr = crac_fan_pwr + chiller_pwr + ct_fan_pwr + cw_pump_pwr + ct_pump_pwr

    # Water usage estimation
    dc_model.hot_water_temp = avg_outlet_temp
    dc_model.cold_water_temp = crac_setpoint
    dc_model.wet_bulb_temp = ambient_temp_c - 3  # rough approximation
    try:
        water_usage_l_15min = dc_model.calculate_cooling_tower_water_usage()
    except Exception:
        water_usage_l_15min = 0.0

    return {
        "crac_fan_kw": round(crac_fan_pwr / 1000, 2),
        "chiller_kw": round(chiller_pwr / 1000, 2),
        "ct_fan_kw": round(ct_fan_pwr / 1000, 2),
        "pumps_kw": round((cw_pump_pwr + ct_pump_pwr) / 1000, 2),
        "total_hvac_kw": round(total_hvac_pwr / 1000, 2),
        "water_usage_l_per_15min": round(float(water_usage_l_15min), 2),
    }


# ═══════════════════════════════════════════════════════════════════
#  BATTERY MODEL — from dc-rl Battery2 class
# ═══════════════════════════════════════════════════════════════════

class BatteryModel:
    """Simplified battery model from dc-rl's Battery2 class."""

    def __init__(self, capacity_mwh, soc_pct=50.0, eff_charge=0.95,
                 eff_discharge=0.95, max_c_rate=0.5, max_d_rate=1.0):
        self.capacity_mwh = capacity_mwh
        self.soc_mwh = capacity_mwh * soc_pct / 100
        self.eff_c = eff_charge
        self.eff_d = eff_discharge
        self.max_charge_mw = capacity_mwh * max_c_rate
        self.max_discharge_mw = capacity_mwh * max_d_rate

    @property
    def soc_pct(self):
        return (self.soc_mwh / self.capacity_mwh) * 100 if self.capacity_mwh > 0 else 0

    def step(self, action_mw, dt_hours=1.0):
        """
        action_mw > 0 = charge, < 0 = discharge.
        Returns actual power exchanged (MW) and new SoC.
        """
        if action_mw > 0:  # charge
            capped = min(action_mw, self.max_charge_mw)
            energy_in = capped * dt_hours * self.eff_c
            headroom = self.capacity_mwh - self.soc_mwh
            energy_stored = min(energy_in, headroom)
            self.soc_mwh += energy_stored
            actual_mw = energy_stored / (dt_hours * self.eff_c) if dt_hours > 0 else 0
        else:  # discharge
            capped = max(action_mw, -self.max_discharge_mw)
            energy_out = abs(capped) * dt_hours
            available = self.soc_mwh * self.eff_d
            energy_delivered = min(energy_out, available)
            self.soc_mwh -= energy_delivered / self.eff_d
            actual_mw = -energy_delivered / dt_hours if dt_hours > 0 else 0

        return round(actual_mw, 4), round(self.soc_pct, 2)


# ═══════════════════════════════════════════════════════════════════
#  COMMANDS
# ═══════════════════════════════════════════════════════════════════

def cmd_simulate(params: dict) -> dict:
    """
    Single-timestep DC thermal simulation.

    Input:
        it_load_pct (float): IT utilisation 0-100
        ambient_temp_c (float): outside air temperature
        crac_setpoint_c (float): CRAC supply setpoint (default 18)
        capacity_mw (float): DC IT capacity in MW (default 1)
    Output:
        it_power_kw, hvac breakdown, PUE, rack temperatures, water usage
    """
    it_load_pct = params.get("it_load_pct", 50)
    ambient_temp_c = params.get("ambient_temp_c", 20)
    crac_setpoint = params.get("crac_setpoint_c", 18)
    capacity_mw = params.get("capacity_mw", 1.0)

    dc_model, dc_config = _build_dc_model(capacity_mw)
    num_racks = len(dc_model.racks_list)
    ite_load_list = [it_load_pct] * num_racks

    rackwise_cpu, rackwise_fan, rackwise_outlet = \
        dc_model.compute_datacenter_IT_load_outlet_temp(ite_load_list, crac_setpoint)

    total_it_kw = (sum(rackwise_cpu) + sum(rackwise_fan)) / 1000
    hvac = _compute_hvac(dc_model, dc_config, rackwise_cpu, rackwise_fan,
                         rackwise_outlet, crac_setpoint, ambient_temp_c)

    total_power_kw = total_it_kw + hvac["total_hvac_kw"]
    pue = total_power_kw / max(total_it_kw, 0.001)

    return {
        "it_load_pct": it_load_pct,
        "capacity_mw": capacity_mw,
        "it_power_kw": round(total_it_kw, 2),
        "hvac": hvac,
        "total_power_kw": round(total_power_kw, 2),
        "pue": round(pue, 3),
        "avg_inlet_temp_c": round(float(np.mean(dc_model.rackwise_inlet_temp)), 1),
        "avg_outlet_temp_c": round(float(np.mean(rackwise_outlet)), 1),
        "max_outlet_temp_c": round(float(np.max(rackwise_outlet)), 1),
        "ambient_temp_c": ambient_temp_c,
        "crac_setpoint_c": crac_setpoint,
        "water_usage_l_per_15min": hvac["water_usage_l_per_15min"],
        "num_racks": num_racks,
        "model": "sustaindc_v1",
    }


def cmd_simulate_24h(params: dict) -> dict:
    """
    24-hour hourly DC simulation with weather and carbon intensity.

    Input:
        it_load_mw (float): average IT load in MW
        hourly_ambient_c (list[24]): ambient temp per hour
        hourly_it_load_pct (list[24], optional): IT util per hour (default flat)
        hourly_carbon_gco2_kwh (list[24], optional): carbon intensity per hour
        crac_setpoint_c (float): CRAC setpoint (default 18)
        battery_mwh (float, optional): battery capacity (0 = none)
        battery_soc_pct (float, optional): initial SoC (default 50)
    Output:
        hourly results + daily summary (energy, carbon, PUE, water, battery)
    """
    it_load_mw = params.get("it_load_mw", 50)
    hourly_ambient = params.get("hourly_ambient_c", [15] * 24)
    hourly_it_pct = params.get("hourly_it_load_pct", [60] * 24)
    hourly_ci = params.get("hourly_carbon_gco2_kwh", [200] * 24)
    crac_setpoint = params.get("crac_setpoint_c", 18)
    batt_mwh = params.get("battery_mwh", 0)
    batt_soc = params.get("battery_soc_pct", 50)

    # Pad to 24 hours
    hourly_ambient = (hourly_ambient + [15] * 24)[:24]
    hourly_it_pct = (hourly_it_pct + [60] * 24)[:24]
    hourly_ci = (hourly_ci + [200] * 24)[:24]

    dc_model, dc_config = _build_dc_model(it_load_mw)
    num_racks = len(dc_model.racks_list)

    battery = BatteryModel(batt_mwh, batt_soc) if batt_mwh > 0 else None

    hourly_results = []
    total_energy_kwh = 0
    total_carbon_gco2 = 0
    total_water_l = 0

    for h in range(24):
        amb = hourly_ambient[h]
        it_pct = hourly_it_pct[h]
        ci = hourly_ci[h]

        ite_load_list = [it_pct] * num_racks
        rackwise_cpu, rackwise_fan, rackwise_outlet = \
            dc_model.compute_datacenter_IT_load_outlet_temp(ite_load_list, crac_setpoint)

        total_it_kw = (sum(rackwise_cpu) + sum(rackwise_fan)) / 1000
        hvac = _compute_hvac(dc_model, dc_config, rackwise_cpu, rackwise_fan,
                             rackwise_outlet, crac_setpoint, amb)
        total_kw = total_it_kw + hvac["total_hvac_kw"]
        pue = total_kw / max(total_it_kw, 0.001)

        # Battery: charge when CI low, discharge when CI high
        batt_action_mw = 0
        batt_soc_pct = 0
        if battery:
            median_ci = float(np.median(hourly_ci))
            if ci < median_ci * 0.8:
                # Low carbon — charge
                batt_action_mw = battery.max_charge_mw * 0.8
            elif ci > median_ci * 1.2:
                # High carbon — discharge to offset grid
                batt_action_mw = -battery.max_discharge_mw * 0.6
            actual_mw, batt_soc_pct = battery.step(batt_action_mw)
            batt_action_mw = actual_mw

        # Grid draw = total DC power - battery discharge (if discharging)
        grid_draw_kw = total_kw - max(-batt_action_mw * 1000, 0) + max(batt_action_mw * 1000, 0)
        grid_draw_kw = max(grid_draw_kw, 0)

        energy_kwh = grid_draw_kw  # 1 hour step
        carbon_gco2 = energy_kwh * ci
        water_l = hvac["water_usage_l_per_15min"] * 4  # 4 x 15min = 1 hour

        total_energy_kwh += energy_kwh
        total_carbon_gco2 += carbon_gco2
        total_water_l += water_l

        hourly_results.append({
            "hour": h,
            "ambient_temp_c": amb,
            "it_load_pct": it_pct,
            "it_power_kw": round(total_it_kw, 1),
            "hvac_kw": round(hvac["total_hvac_kw"], 1),
            "total_kw": round(total_kw, 1),
            "grid_draw_kw": round(grid_draw_kw, 1),
            "pue": round(pue, 3),
            "carbon_intensity": ci,
            "carbon_kg": round(carbon_gco2 / 1000, 2),
            "water_l": round(water_l, 1),
            "battery_soc_pct": round(batt_soc_pct, 1) if battery else None,
            "battery_mw": round(batt_action_mw, 2) if battery else None,
            "avg_inlet_c": round(float(np.mean(dc_model.rackwise_inlet_temp)), 1),
            "avg_outlet_c": round(float(np.mean(rackwise_outlet)), 1),
        })

    avg_pue = np.mean([r["pue"] for r in hourly_results])
    wue = total_water_l / max(total_energy_kwh, 1)  # L/kWh

    return {
        "hourly": hourly_results,
        "summary": {
            "total_energy_mwh": round(total_energy_kwh / 1000, 2),
            "total_carbon_tonnes": round(total_carbon_gco2 / 1e6, 3),
            "total_water_m3": round(total_water_l / 1000, 2),
            "avg_pue": round(float(avg_pue), 3),
            "wue_l_per_kwh": round(float(wue), 4),
            "peak_power_kw": round(max(r["total_kw"] for r in hourly_results), 1),
            "min_pue": round(min(r["pue"] for r in hourly_results), 3),
            "max_pue": round(max(r["pue"] for r in hourly_results), 3),
            "battery_final_soc_pct": round(battery.soc_pct, 1) if battery else None,
            "capacity_mw": it_load_mw,
        },
        "model": "sustaindc_v1",
    }


def cmd_battery(params: dict) -> dict:
    """
    Standalone battery simulation step.

    Input:
        capacity_mwh, soc_pct, action_mw (+charge/-discharge), dt_hours
    Output:
        actual_mw, new_soc_pct, energy_mwh
    """
    batt = BatteryModel(
        capacity_mwh=params.get("capacity_mwh", 100),
        soc_pct=params.get("soc_pct", 50),
        eff_charge=params.get("eff_charge", 0.95),
        eff_discharge=params.get("eff_discharge", 0.95),
        max_c_rate=params.get("max_c_rate", 0.5),
        max_d_rate=params.get("max_d_rate", 1.0),
    )
    dt = params.get("dt_hours", 1.0)
    action_mw = params.get("action_mw", 0)

    actual_mw, new_soc = batt.step(action_mw, dt)

    return {
        "actual_mw": actual_mw,
        "new_soc_pct": new_soc,
        "energy_mwh": round(abs(actual_mw) * dt, 4),
        "capacity_mwh": batt.capacity_mwh,
    }


def cmd_optimise(params: dict) -> dict:
    """
    Carbon-optimised 24h simulation — shifts battery charge/discharge
    to minimise total carbon footprint.

    Same inputs as simulate_24h, but returns both baseline and optimised results.
    """
    # Baseline (no battery optimisation)
    baseline_params = {**params, "battery_mwh": 0}
    baseline = cmd_simulate_24h(baseline_params)

    # Optimised (with battery)
    optimised = cmd_simulate_24h(params)

    carbon_saved_tonnes = (
        baseline["summary"]["total_carbon_tonnes"] -
        optimised["summary"]["total_carbon_tonnes"]
    )
    carbon_reduction_pct = (
        carbon_saved_tonnes / max(baseline["summary"]["total_carbon_tonnes"], 0.001)
    ) * 100

    return {
        "baseline": baseline["summary"],
        "optimised": optimised["summary"],
        "hourly": optimised["hourly"],
        "savings": {
            "carbon_saved_tonnes": round(carbon_saved_tonnes, 3),
            "carbon_reduction_pct": round(carbon_reduction_pct, 1),
            "energy_saved_mwh": round(
                baseline["summary"]["total_energy_mwh"] -
                optimised["summary"]["total_energy_mwh"], 2
            ),
            "water_saved_m3": round(
                baseline["summary"]["total_water_m3"] -
                optimised["summary"]["total_water_m3"], 2
            ),
        },
        "model": "sustaindc_v1",
    }


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

def cmd_power_curve(params: dict) -> dict:
    """
    Generate a power consumption curve for a given model.

    Input:
        model (str): Power model name (linear, square, cubic, sqrt, mse, asymptotic, interpolate)
        max_power_w (float): Max server power (W)
        idle_power_w (float): Idle server power (W)
        num_servers (int): Number of servers
    Output:
        Curve with power at each 5% utilisation step, plus model metadata
    """
    model_name = params.get("model", "linear")
    max_power = params.get("max_power_w", 500)
    idle_power = params.get("idle_power_w", 200)
    num_servers = params.get("num_servers", 1000)
    model_params = {
        "max_power": max_power, "idle_power": idle_power,
        "calibration": params.get("calibration", 1.4),
        "asym_util": params.get("asym_util", 0.3),
        "dvfs": params.get("dvfs", False),
        "power_levels": params.get("power_levels"),
    }

    fn = POWER_MODELS.get(model_name, power_linear)
    curve = []
    for pct in range(0, 105, 5):
        util = pct / 100
        power_per_server = fn(util, **model_params)
        curve.append({
            "utilisation_pct": pct,
            "power_per_server_w": round(power_per_server, 1),
            "total_power_kw": round(power_per_server * num_servers / 1000, 1),
        })

    return {
        "model": model_name,
        "num_servers": num_servers,
        "max_power_w": max_power,
        "idle_power_w": idle_power,
        "curve": curve,
        "available_models": list(POWER_MODELS.keys()),
    }


def cmd_lifecycle_carbon(params: dict) -> dict:
    """
    Calculate lifecycle carbon footprint (operational + embodied).

    Input:
        annual_energy_mwh (float): Annual energy consumption
        grid_carbon_gco2_kwh (float): Average grid carbon intensity
        num_servers (int): Number of servers
        server_type (str): standard_1u, gpu_server, storage_server
        facility_lifetime_years (int): DC operational lifetime
    Output:
        Operational, embodied, and total lifecycle carbon
    """
    annual_mwh = params.get("annual_energy_mwh", 50000)
    ci = params.get("grid_carbon_gco2_kwh", 200)
    num_servers = params.get("num_servers", 1000)
    server_type = params.get("server_type", "standard_1u")
    lifetime = params.get("facility_lifetime_years", 25)

    # Operational carbon
    annual_operational_tco2 = annual_mwh * ci / 1e6  # tonnes CO2
    lifetime_operational_tco2 = annual_operational_tco2 * lifetime

    # Embodied carbon (OpenDC data)
    server_spec = EMBODIED_CARBON.get(server_type, EMBODIED_CARBON["standard_1u"])
    server_replacements = math.ceil(lifetime / server_spec["lifetime_years"])
    total_server_embodied_tco2 = (
        num_servers * server_spec["kgco2e"] * server_replacements / 1000
    )

    # Rack + networking infrastructure
    num_racks = math.ceil(num_servers / 42)  # 42U racks
    rack_spec = EMBODIED_CARBON["rack_infrastructure"]
    rack_replacements = math.ceil(lifetime / rack_spec["lifetime_years"])
    rack_embodied_tco2 = num_racks * rack_spec["kgco2e"] * rack_replacements / 1000

    networking_embodied_tco2 = (
        num_racks * 2 * EMBODIED_CARBON["networking"]["kgco2e"]  # 2 switches per rack
        * math.ceil(lifetime / EMBODIED_CARBON["networking"]["lifetime_years"]) / 1000
    )

    total_embodied_tco2 = total_server_embodied_tco2 + rack_embodied_tco2 + networking_embodied_tco2
    total_lifecycle_tco2 = lifetime_operational_tco2 + total_embodied_tco2
    embodied_pct = (total_embodied_tco2 / max(total_lifecycle_tco2, 0.001)) * 100

    return {
        "operational": {
            "annual_tco2": round(annual_operational_tco2, 1),
            "lifetime_tco2": round(lifetime_operational_tco2, 1),
        },
        "embodied": {
            "servers_tco2": round(total_server_embodied_tco2, 1),
            "racks_tco2": round(rack_embodied_tco2, 1),
            "networking_tco2": round(networking_embodied_tco2, 1),
            "total_tco2": round(total_embodied_tco2, 1),
            "server_replacements": server_replacements,
        },
        "lifecycle": {
            "total_tco2": round(total_lifecycle_tco2, 1),
            "embodied_pct": round(embodied_pct, 1),
            "operational_pct": round(100 - embodied_pct, 1),
        },
        "inputs": {
            "num_servers": num_servers,
            "server_type": server_type,
            "facility_lifetime_years": lifetime,
            "annual_energy_mwh": annual_mwh,
            "grid_carbon_gco2_kwh": ci,
        },
    }


COMMANDS = {
    "simulate": cmd_simulate,
    "simulate_24h": cmd_simulate_24h,
    "battery": cmd_battery,
    "optimise": cmd_optimise,
    "power_curve": cmd_power_curve,
    "lifecycle_carbon": cmd_lifecycle_carbon,
}

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({"error": f"Usage: {sys.argv[0]} <command> '<json_params>'",
                          "commands": list(COMMANDS.keys())}))
        sys.exit(1)

    command = sys.argv[1]
    try:
        params = json.loads(sys.argv[2])
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}))
        sys.exit(1)

    if command not in COMMANDS:
        print(json.dumps({"error": f"Unknown command: {command}",
                          "commands": list(COMMANDS.keys())}))
        sys.exit(1)

    try:
        result = COMMANDS[command](params)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e), "command": command}))
        sys.exit(1)
