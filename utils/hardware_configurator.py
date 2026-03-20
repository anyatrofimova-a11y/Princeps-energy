"""
Hardware Configurator — Modular IoT Monitoring Kit Builder

Atech-inspired snap-together sensor module system for energy infrastructure.
Recommends and configures monitoring kits based on site type, capacity, and
monitoring requirements. Modules connect via standard interfaces (I2C, MQTT,
Modbus, analog) and auto-register with Princeps telemetry.

Each module has real specs, UK pricing (ex-VAT), power requirements, and
communication protocol. Kits are auto-sized based on site parameters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any

# ============================================================================
# Module Catalogue — real products, UK pricing 2025-26
# ============================================================================

SENSOR_CATALOGUE = [
    # ── Irradiance & Solar Resource ──
    {"id": "IRR-PYRANO-01", "name": "Hukseflux SR30 Pyranometer",
     "category": "irradiance", "type": "sensor",
     "unit_cost_gbp": 1850, "power_w": 0.1, "weight_kg": 0.9,
     "interface": "analog_4-20mA", "accuracy": "±1.2%",
     "measurement": "GHI (W/m²)", "range": "0-2000 W/m²",
     "ip_rating": "IP67", "operating_temp": "-40 to +80°C",
     "description": "Secondary standard pyranometer for bankable irradiance data"},

    {"id": "IRR-REFCELL-01", "name": "Ingenieurbüro Mencke Si Reference Cell",
     "category": "irradiance", "type": "sensor",
     "unit_cost_gbp": 420, "power_w": 0.05, "weight_kg": 0.3,
     "interface": "analog_4-20mA", "accuracy": "±2.5%",
     "measurement": "POA irradiance (W/m²)", "range": "0-1500 W/m²",
     "ip_rating": "IP67", "operating_temp": "-40 to +85°C",
     "description": "Plane-of-array reference cell, fast response for inverter tracking"},

    # ── Weather Station ──
    {"id": "WX-STATION-01", "name": "Davis Vantage Pro2 Plus",
     "category": "weather", "type": "sensor",
     "unit_cost_gbp": 895, "power_w": 0.5, "weight_kg": 3.2,
     "interface": "serial_RS232", "accuracy": "±0.5°C temp, ±3% RH",
     "measurement": "temp, humidity, pressure, wind speed/dir, rain",
     "ip_rating": "IP44", "operating_temp": "-40 to +65°C",
     "description": "Professional weather station with solar-powered wireless ISS"},

    {"id": "WX-ANEMOMETER-01", "name": "NRG #40C Anemometer",
     "category": "weather", "type": "sensor",
     "unit_cost_gbp": 340, "power_w": 0.02, "weight_kg": 0.2,
     "interface": "pulse_output", "accuracy": "±0.1 m/s",
     "measurement": "wind speed (m/s)", "range": "1-96 m/s",
     "ip_rating": "IP65", "operating_temp": "-55 to +60°C",
     "description": "IEC 61400-12 compliant cup anemometer for wind resource"},

    {"id": "WX-TEMP-AMB-01", "name": "Campbell Scientific CS215 T/RH Probe",
     "category": "weather", "type": "sensor",
     "unit_cost_gbp": 285, "power_w": 0.04, "weight_kg": 0.15,
     "interface": "SDI-12", "accuracy": "±0.3°C, ±2% RH",
     "measurement": "ambient temperature (°C), relative humidity (%)",
     "ip_rating": "IP65", "operating_temp": "-40 to +70°C",
     "description": "Precision ambient temp/humidity for module temperature modelling"},

    # ── Power Metering ──
    {"id": "PWR-METER-01", "name": "Schneider PM5350 Power Meter",
     "category": "power_meter", "type": "sensor",
     "unit_cost_gbp": 1450, "power_w": 8, "weight_kg": 0.5,
     "interface": "modbus_TCP", "accuracy": "±0.5% (Class 0.5S)",
     "measurement": "V, I, P, Q, S, PF, THD, energy (kWh)",
     "ip_rating": "IP52", "operating_temp": "-25 to +70°C",
     "description": "Revenue-grade 3-phase power analyser with Modbus TCP/IP"},

    {"id": "PWR-CT-01", "name": "Magnelab SCT-0750-100 CT Clamp",
     "category": "power_meter", "type": "sensor",
     "unit_cost_gbp": 65, "power_w": 0, "weight_kg": 0.3,
     "interface": "analog_0-0.333V", "accuracy": "±1%",
     "measurement": "AC current (A)", "range": "0-100A",
     "ip_rating": "IP20", "operating_temp": "-30 to +70°C",
     "description": "Split-core CT for non-invasive current measurement"},

    {"id": "PWR-EXPORT-01", "name": "Eastron SDM630-Modbus V2",
     "category": "power_meter", "type": "sensor",
     "unit_cost_gbp": 95, "power_w": 2, "weight_kg": 0.25,
     "interface": "modbus_RTU", "accuracy": "±0.5%",
     "measurement": "3-phase kWh, kVArh, V, I, PF, demand",
     "ip_rating": "IP51", "operating_temp": "-25 to +55°C",
     "description": "DIN-rail export/import meter with MID certification"},

    # ── Module/String Monitoring ──
    {"id": "STR-MON-01", "name": "Tigo TS4-A-O String Optimiser",
     "category": "string_monitor", "type": "sensor",
     "unit_cost_gbp": 28, "power_w": 0.5, "weight_kg": 0.22,
     "interface": "wireless_PLC", "accuracy": "±2%",
     "measurement": "module V, I, P, temperature",
     "ip_rating": "IP68", "operating_temp": "-40 to +85°C",
     "description": "Per-module monitoring + rapid shutdown, PLC comms to gateway"},

    {"id": "STR-MON-02", "name": "SolarEdge S440 Power Optimiser",
     "category": "string_monitor", "type": "sensor",
     "unit_cost_gbp": 35, "power_w": 0.5, "weight_kg": 0.36,
     "interface": "wireless_PLC", "accuracy": "±1%",
     "measurement": "module V, I, P, energy",
     "ip_rating": "IP68", "operating_temp": "-40 to +85°C",
     "description": "Per-module MPPT + monitoring with SolarEdge ecosystem"},

    # ── Environmental / Soil ──
    {"id": "ENV-FLOOD-01", "name": "Senix ToughSonic CHEM 10 Ultrasonic Level",
     "category": "environmental", "type": "sensor",
     "unit_cost_gbp": 520, "power_w": 1.5, "weight_kg": 0.6,
     "interface": "analog_4-20mA", "accuracy": "±0.2%",
     "measurement": "water level (mm)", "range": "0-3000mm",
     "ip_rating": "IP68", "operating_temp": "-40 to +70°C",
     "description": "Flood/water level sensor for low-lying site monitoring"},

    {"id": "ENV-SOIL-01", "name": "Meter TEROS 12 Soil Sensor",
     "category": "environmental", "type": "sensor",
     "unit_cost_gbp": 195, "power_w": 0.012, "weight_kg": 0.14,
     "interface": "SDI-12", "accuracy": "±0.03 m³/m³ VWC",
     "measurement": "soil moisture (VWC), temperature, EC",
     "ip_rating": "IP68", "operating_temp": "-40 to +60°C",
     "description": "Soil moisture for ground-mount stability and BNG monitoring"},

    {"id": "ENV-TILT-01", "name": "Murata SCA100T Inclinometer",
     "category": "environmental", "type": "sensor",
     "unit_cost_gbp": 180, "power_w": 0.09, "weight_kg": 0.05,
     "interface": "analog_0-5V", "accuracy": "±0.05°",
     "measurement": "tilt angle (°)", "range": "±30°",
     "ip_rating": "IP67", "operating_temp": "-40 to +125°C",
     "description": "Pole/structure tilt monitoring for asset condition assessment"},

    # ── Thermal Imaging ──
    {"id": "THERM-CAM-01", "name": "FLIR A50 Thermal Camera",
     "category": "thermal", "type": "sensor",
     "unit_cost_gbp": 3200, "power_w": 12, "weight_kg": 0.88,
     "interface": "ethernet_GigE", "accuracy": "±2°C",
     "measurement": "thermal image 464×348, -20 to 550°C",
     "ip_rating": "IP66", "operating_temp": "-20 to +50°C",
     "description": "Fixed thermal camera for hot-spot detection on transformers/panels"},

    {"id": "THERM-SPOT-01", "name": "Optris CS LT IR Sensor",
     "category": "thermal", "type": "sensor",
     "unit_cost_gbp": 280, "power_w": 1, "weight_kg": 0.05,
     "interface": "analog_4-20mA", "accuracy": "±1°C",
     "measurement": "surface temperature (°C)", "range": "-40 to +1030°C",
     "ip_rating": "IP65", "operating_temp": "-20 to +85°C",
     "description": "Spot IR sensor for transformer/cable joint hot-spot monitoring"},

    # ── Gateways & Controllers ──
    {"id": "GW-EDGE-01", "name": "Advantech UNO-2271G Edge Gateway",
     "category": "gateway", "type": "controller",
     "unit_cost_gbp": 680, "power_w": 15, "weight_kg": 1.1,
     "interface": "ethernet,wifi,4G,modbus,mqtt", "ports": "2xLAN,4xUSB,2xCOM,8xDIO",
     "ip_rating": "IP40", "operating_temp": "-20 to +60°C",
     "description": "Industrial edge gateway — aggregates sensors, runs MQTT broker, pushes to Princeps"},

    {"id": "GW-LORA-01", "name": "Kerlink Wirnet iStation LoRaWAN Gateway",
     "category": "gateway", "type": "controller",
     "unit_cost_gbp": 950, "power_w": 8, "weight_kg": 2.5,
     "interface": "LoRaWAN,ethernet,4G", "range_km": 15,
     "ip_rating": "IP67", "operating_temp": "-40 to +55°C",
     "description": "Outdoor LoRaWAN gateway for wide-area sensor networks (large solar farms)"},

    {"id": "GW-DATALOGGER-01", "name": "Campbell Scientific CR1000X Datalogger",
     "category": "gateway", "type": "controller",
     "unit_cost_gbp": 1650, "power_w": 0.7, "weight_kg": 0.86,
     "interface": "SDI-12,analog,modbus,ethernet",
     "channels": "16 analog, 4 pulse, 8 digital",
     "ip_rating": "IP30", "operating_temp": "-55 to +70°C",
     "description": "Research-grade datalogger for bankable met station data (IEC 61724)"},

    # ── Connectivity ──
    {"id": "CONN-4G-01", "name": "Teltonika RUT955 Industrial 4G Router",
     "category": "connectivity", "type": "controller",
     "unit_cost_gbp": 310, "power_w": 7, "weight_kg": 0.36,
     "interface": "4G_LTE,ethernet,wifi,RS232,RS485",
     "ip_rating": "IP30", "operating_temp": "-40 to +75°C",
     "description": "Industrial 4G router with dual SIM failover for remote sites"},

    {"id": "CONN-SOLAR-PSU-01", "name": "Victron SmartSolar 100/20 + 50Ah LFP Kit",
     "category": "power_supply", "type": "controller",
     "unit_cost_gbp": 420, "power_w": 0, "weight_kg": 8.5,
     "interface": "12V_DC", "capacity_wh": 640,
     "description": "Off-grid power supply for remote sensor stations — 50W panel + 50Ah LFP + MPPT"},
]

# Build lookup by ID
_CATALOGUE_BY_ID = {m["id"]: m for m in SENSOR_CATALOGUE}


# ============================================================================
# Kit Templates — pre-configured monitoring packages by site type
# ============================================================================

KIT_TEMPLATES = {
    "solar_farm": {
        "name": "Solar Farm Monitoring Kit",
        "description": "IEC 61724-compliant monitoring for utility-scale solar PV",
        "modules": [
            {"module_id": "IRR-PYRANO-01", "qty_per_mw": 1, "min_qty": 1, "role": "GHI measurement (bankable)"},
            {"module_id": "IRR-REFCELL-01", "qty_per_mw": 2, "min_qty": 2, "role": "POA irradiance per array orientation"},
            {"module_id": "WX-STATION-01", "qty_per_mw": 0, "min_qty": 1, "role": "Site weather station"},
            {"module_id": "WX-TEMP-AMB-01", "qty_per_mw": 0.5, "min_qty": 1, "role": "Ambient temp for module temp model"},
            {"module_id": "PWR-METER-01", "qty_per_mw": 1, "min_qty": 1, "role": "Revenue meter at POC"},
            {"module_id": "PWR-EXPORT-01", "qty_per_mw": 0, "min_qty": 1, "role": "Grid export/import meter"},
            {"module_id": "STR-MON-01", "qty_per_mw": 0, "min_qty": 0, "role": "Per-module monitoring (optional)",
             "optional": True, "qty_per_panel": 1},
            {"module_id": "THERM-CAM-01", "qty_per_mw": 0, "min_qty": 0, "role": "Transformer thermal monitoring",
             "optional": True, "qty_fixed": 1},
            {"module_id": "GW-EDGE-01", "qty_per_mw": 0, "min_qty": 1, "role": "Edge gateway — MQTT to Princeps"},
            {"module_id": "CONN-4G-01", "qty_per_mw": 0, "min_qty": 1, "role": "4G backhaul"},
        ],
    },
    "bess": {
        "name": "BESS Facility Monitoring Kit",
        "description": "Battery energy storage system monitoring and safety",
        "modules": [
            {"module_id": "PWR-METER-01", "qty_per_mw": 1, "min_qty": 2, "role": "AC-side power metering"},
            {"module_id": "PWR-CT-01", "qty_per_mw": 3, "min_qty": 6, "role": "Per-string DC current measurement"},
            {"module_id": "WX-TEMP-AMB-01", "qty_per_mw": 0, "min_qty": 2, "role": "Container ambient + outdoor temp"},
            {"module_id": "THERM-SPOT-01", "qty_per_mw": 2, "min_qty": 4, "role": "Busbar/cable joint hot-spot"},
            {"module_id": "THERM-CAM-01", "qty_per_mw": 0, "min_qty": 1, "role": "Transformer/switchgear thermal"},
            {"module_id": "ENV-FLOOD-01", "qty_per_mw": 0, "min_qty": 1, "role": "Flood level at site perimeter"},
            {"module_id": "GW-EDGE-01", "qty_per_mw": 0, "min_qty": 1, "role": "Edge gateway — MQTT to Princeps"},
            {"module_id": "CONN-4G-01", "qty_per_mw": 0, "min_qty": 1, "role": "4G backhaul with failover"},
        ],
    },
    "wind_farm": {
        "name": "Wind Farm Monitoring Kit",
        "description": "Met mast and turbine condition monitoring",
        "modules": [
            {"module_id": "WX-ANEMOMETER-01", "qty_per_mw": 0, "min_qty": 3, "role": "Hub-height wind measurement (3 heights)"},
            {"module_id": "WX-STATION-01", "qty_per_mw": 0, "min_qty": 1, "role": "Ground-level weather station"},
            {"module_id": "WX-TEMP-AMB-01", "qty_per_mw": 0, "min_qty": 2, "role": "Temperature at nacelle + ground"},
            {"module_id": "PWR-METER-01", "qty_per_mw": 1, "min_qty": 1, "role": "Turbine output metering"},
            {"module_id": "PWR-EXPORT-01", "qty_per_mw": 0, "min_qty": 1, "role": "Grid export meter"},
            {"module_id": "ENV-TILT-01", "qty_per_mw": 2, "min_qty": 2, "role": "Tower foundation tilt monitoring"},
            {"module_id": "GW-DATALOGGER-01", "qty_per_mw": 0, "min_qty": 1, "role": "IEC 61400-12 compliant datalogger"},
            {"module_id": "GW-LORA-01", "qty_per_mw": 0, "min_qty": 1, "role": "LoRaWAN for distributed sensor coverage"},
            {"module_id": "CONN-4G-01", "qty_per_mw": 0, "min_qty": 1, "role": "4G backhaul"},
        ],
    },
    "substation": {
        "name": "Substation Monitoring Kit",
        "description": "Distribution substation condition & load monitoring",
        "modules": [
            {"module_id": "PWR-METER-01", "qty_per_mw": 0, "min_qty": 2, "role": "HV and LV side power metering"},
            {"module_id": "PWR-CT-01", "qty_per_mw": 0, "min_qty": 6, "role": "Per-feeder current monitoring"},
            {"module_id": "THERM-CAM-01", "qty_per_mw": 0, "min_qty": 1, "role": "Transformer thermal imaging"},
            {"module_id": "THERM-SPOT-01", "qty_per_mw": 0, "min_qty": 4, "role": "Bushing/cable box hot-spots"},
            {"module_id": "WX-TEMP-AMB-01", "qty_per_mw": 0, "min_qty": 1, "role": "Ambient temp for DLR calculation"},
            {"module_id": "ENV-FLOOD-01", "qty_per_mw": 0, "min_qty": 1, "role": "Flood risk monitoring"},
            {"module_id": "GW-EDGE-01", "qty_per_mw": 0, "min_qty": 1, "role": "Edge gateway — Modbus + MQTT"},
            {"module_id": "CONN-4G-01", "qty_per_mw": 0, "min_qty": 1, "role": "4G backhaul"},
        ],
    },
    "met_mast": {
        "name": "Pre-Construction Met Station",
        "description": "12-month bankable resource assessment station",
        "modules": [
            {"module_id": "IRR-PYRANO-01", "qty_per_mw": 0, "min_qty": 2, "role": "GHI + diffuse (with shading ring)"},
            {"module_id": "IRR-REFCELL-01", "qty_per_mw": 0, "min_qty": 1, "role": "POA reference cell"},
            {"module_id": "WX-STATION-01", "qty_per_mw": 0, "min_qty": 1, "role": "Full weather station"},
            {"module_id": "WX-ANEMOMETER-01", "qty_per_mw": 0, "min_qty": 2, "role": "Wind at 2 heights"},
            {"module_id": "WX-TEMP-AMB-01", "qty_per_mw": 0, "min_qty": 1, "role": "Ambient temperature"},
            {"module_id": "ENV-SOIL-01", "qty_per_mw": 0, "min_qty": 1, "role": "Soil moisture for foundation design"},
            {"module_id": "GW-DATALOGGER-01", "qty_per_mw": 0, "min_qty": 1, "role": "IEC 61724 compliant datalogger"},
            {"module_id": "CONN-SOLAR-PSU-01", "qty_per_mw": 0, "min_qty": 1, "role": "Off-grid solar power supply"},
            {"module_id": "CONN-4G-01", "qty_per_mw": 0, "min_qty": 1, "role": "4G telemetry uplink"},
        ],
    },
}


# ============================================================================
# Kit Builder
# ============================================================================

def recommend_kit(
    site_type: str = "solar_farm",
    capacity_mw: float = 5.0,
    include_optional: bool = False,
    extra_modules: list[str] | None = None,
) -> dict[str, Any]:
    """
    Recommend a monitoring kit for a given site type and capacity.

    Returns a complete kit specification with modules, quantities,
    total cost, wiring diagram hints, and MQTT topic structure.
    """
    template = KIT_TEMPLATES.get(site_type)
    if not template:
        return {"error": f"Unknown site type: {site_type}. Available: {list(KIT_TEMPLATES.keys())}"}

    modules = []
    total_cost = 0
    total_power_w = 0
    total_weight_kg = 0

    for entry in template["modules"]:
        mod = _CATALOGUE_BY_ID.get(entry["module_id"])
        if not mod:
            continue

        is_optional = entry.get("optional", False)
        if is_optional and not include_optional:
            continue

        # Calculate quantity
        qty_from_capacity = math.ceil(entry.get("qty_per_mw", 0) * capacity_mw)
        qty = max(entry.get("min_qty", 1), qty_from_capacity)
        if entry.get("qty_fixed"):
            qty = entry["qty_fixed"]

        line_cost = qty * mod["unit_cost_gbp"]
        total_cost += line_cost
        total_power_w += qty * mod["power_w"]
        total_weight_kg += qty * mod["weight_kg"]

        modules.append({
            "module_id": mod["id"],
            "name": mod["name"],
            "category": mod["category"],
            "qty": qty,
            "unit_cost_gbp": mod["unit_cost_gbp"],
            "line_cost_gbp": line_cost,
            "interface": mod["interface"],
            "role": entry["role"],
            "optional": is_optional,
            "measurement": mod.get("measurement", ""),
            "accuracy": mod.get("accuracy", ""),
            "ip_rating": mod.get("ip_rating", ""),
        })

    # Add any extra modules requested
    if extra_modules:
        for mod_id in extra_modules:
            mod = _CATALOGUE_BY_ID.get(mod_id)
            if mod and not any(m["module_id"] == mod_id for m in modules):
                line_cost = mod["unit_cost_gbp"]
                total_cost += line_cost
                total_power_w += mod["power_w"]
                total_weight_kg += mod["weight_kg"]
                modules.append({
                    "module_id": mod["id"],
                    "name": mod["name"],
                    "category": mod["category"],
                    "qty": 1,
                    "unit_cost_gbp": mod["unit_cost_gbp"],
                    "line_cost_gbp": line_cost,
                    "interface": mod["interface"],
                    "role": "User-added module",
                    "optional": False,
                    "measurement": mod.get("measurement", ""),
                    "accuracy": mod.get("accuracy", ""),
                    "ip_rating": mod.get("ip_rating", ""),
                })

    # Generate MQTT topic structure
    mqtt_topics = _generate_mqtt_topics(site_type, modules)

    # Generate wiring summary
    wiring = _generate_wiring_summary(modules)

    return {
        "kit_name": template["name"],
        "site_type": site_type,
        "capacity_mw": capacity_mw,
        "description": template["description"],
        "modules": modules,
        "module_count": sum(m["qty"] for m in modules),
        "total_cost_gbp": total_cost,
        "total_power_w": round(total_power_w, 1),
        "total_weight_kg": round(total_weight_kg, 1),
        "mqtt_topics": mqtt_topics,
        "wiring": wiring,
        "compliance": _compliance_notes(site_type),
    }


def get_catalogue(category: str | None = None) -> list[dict]:
    """Return the full sensor catalogue, optionally filtered by category."""
    if category:
        return [m for m in SENSOR_CATALOGUE if m["category"] == category]
    return SENSOR_CATALOGUE


def get_module(module_id: str) -> dict | None:
    """Get a single module by ID."""
    return _CATALOGUE_BY_ID.get(module_id)


def list_kit_templates() -> dict[str, dict]:
    """Return available kit templates with summary info."""
    return {
        k: {"name": v["name"], "description": v["description"], "module_count": len(v["modules"])}
        for k, v in KIT_TEMPLATES.items()
    }


def custom_kit(module_ids: list[dict]) -> dict[str, Any]:
    """
    Build a custom kit from a list of {module_id, qty} dicts.
    """
    modules = []
    total_cost = 0
    total_power_w = 0
    total_weight_kg = 0

    for entry in module_ids:
        mod = _CATALOGUE_BY_ID.get(entry.get("module_id", ""))
        if not mod:
            continue
        qty = entry.get("qty", 1)
        line_cost = qty * mod["unit_cost_gbp"]
        total_cost += line_cost
        total_power_w += qty * mod["power_w"]
        total_weight_kg += qty * mod["weight_kg"]
        modules.append({
            "module_id": mod["id"],
            "name": mod["name"],
            "category": mod["category"],
            "qty": qty,
            "unit_cost_gbp": mod["unit_cost_gbp"],
            "line_cost_gbp": line_cost,
            "interface": mod["interface"],
            "role": entry.get("role", "Custom"),
            "optional": False,
            "measurement": mod.get("measurement", ""),
            "accuracy": mod.get("accuracy", ""),
            "ip_rating": mod.get("ip_rating", ""),
        })

    return {
        "kit_name": "Custom Monitoring Kit",
        "site_type": "custom",
        "description": "User-configured monitoring kit",
        "modules": modules,
        "module_count": sum(m["qty"] for m in modules),
        "total_cost_gbp": total_cost,
        "total_power_w": round(total_power_w, 1),
        "total_weight_kg": round(total_weight_kg, 1),
        "mqtt_topics": _generate_mqtt_topics("custom", modules),
        "wiring": _generate_wiring_summary(modules),
    }


# ============================================================================
# Internal helpers
# ============================================================================

def _generate_mqtt_topics(site_type: str, modules: list[dict]) -> list[dict]:
    """Generate MQTT topic structure for the kit."""
    topics = [
        {"topic": f"princeps/{site_type}/+/status", "purpose": "Device heartbeat & online status", "qos": 1},
        {"topic": f"princeps/{site_type}/+/telemetry", "purpose": "Sensor readings (JSON payload)", "qos": 0},
        {"topic": f"princeps/{site_type}/+/alarm", "purpose": "Threshold breach alerts", "qos": 2},
        {"topic": f"princeps/{site_type}/+/config", "purpose": "Remote configuration updates", "qos": 1},
    ]

    # Add category-specific topics
    categories = set(m["category"] for m in modules)
    if "irradiance" in categories:
        topics.append({"topic": f"princeps/{site_type}/+/irradiance", "purpose": "GHI/POA readings (W/m²)", "qos": 0})
    if "power_meter" in categories:
        topics.append({"topic": f"princeps/{site_type}/+/power", "purpose": "Power/energy readings", "qos": 0})
    if "weather" in categories:
        topics.append({"topic": f"princeps/{site_type}/+/weather", "purpose": "Weather station data", "qos": 0})
    if "thermal" in categories:
        topics.append({"topic": f"princeps/{site_type}/+/thermal", "purpose": "Thermal alerts & images", "qos": 1})

    return topics


def _generate_wiring_summary(modules: list[dict]) -> dict:
    """Summarise wiring/connectivity requirements."""
    interfaces = {}
    for m in modules:
        iface = m["interface"]
        for proto in iface.split(","):
            proto = proto.strip()
            interfaces[proto] = interfaces.get(proto, 0) + m["qty"]

    return {
        "interfaces": interfaces,
        "requires_gateway": any(m["category"] == "gateway" for m in modules),
        "requires_4g": any(m["category"] == "connectivity" for m in modules),
        "requires_power_supply": any(m["category"] == "power_supply" for m in modules),
        "total_analog_channels": sum(
            m["qty"] for m in modules if "analog" in m["interface"]
        ),
        "total_modbus_devices": sum(
            m["qty"] for m in modules if "modbus" in m["interface"]
        ),
        "total_sdi12_devices": sum(
            m["qty"] for m in modules if "SDI-12" in m["interface"]
        ),
    }


def _compliance_notes(site_type: str) -> list[str]:
    """Return compliance/standards notes for the kit type."""
    notes = [
        "All sensors should be calibrated annually to maintain data quality",
        "Data logger must record at ≤1-minute intervals for IEC 61724 compliance",
    ]
    if site_type == "solar_farm":
        notes.extend([
            "IEC 61724-1:2021 — Photovoltaic system performance monitoring",
            "Pyranometer must be ISO 9060:2018 Class A or B for bankable data",
            "Module temperature measurement via back-of-module thermocouple (PT1000)",
        ])
    elif site_type == "bess":
        notes.extend([
            "BESS fire detection per NFPA 855 and BS EN 62485-2",
            "Gas detection (H₂, CO, VOC) recommended for Li-ion enclosures",
            "HVAC monitoring mandatory per manufacturer warranty terms",
        ])
    elif site_type == "wind_farm":
        notes.extend([
            "IEC 61400-12-1:2022 — Wind turbine power performance testing",
            "Anemometer calibration per MEASNET procedures",
            "Minimum 12-month measurement campaign for bankable wind data",
        ])
    elif site_type == "substation":
        notes.extend([
            "IEC 61850 for substation automation interoperability",
            "DNO metering code of practice compliance",
            "Transformer DGA (dissolved gas analysis) recommended for >5MVA units",
        ])
    return notes
