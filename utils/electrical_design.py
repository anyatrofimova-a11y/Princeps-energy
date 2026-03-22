"""Solar farm electrical design — auto-string, inverter placement, cable routing, SLD."""

import math
import json

# Standard equipment specs
INVERTERS = {
    "huawei_sun2000_215": {"name": "Huawei SUN2000-215KTL", "kva": 215, "max_strings": 12, "mppt_count": 6, "dc_voltage_range": "600-1500V", "cost_gbp": 8500},
    "sungrow_sg250hx": {"name": "Sungrow SG250HX", "kva": 250, "max_strings": 12, "mppt_count": 12, "dc_voltage_range": "500-1500V", "cost_gbp": 9200},
    "sma_sunny_central": {"name": "SMA Sunny Central UP", "kva": 4600, "max_strings": 48, "mppt_count": 1, "dc_voltage_range": "850-1500V", "cost_gbp": 85000, "type": "central"},
}

TRANSFORMERS = {
    "33kv_5mva": {"name": "33/0.69kV 5MVA", "mva": 5, "primary_kv": 33, "secondary_kv": 0.69, "cost_gbp": 120000},
    "33kv_10mva": {"name": "33/0.69kV 10MVA", "mva": 10, "primary_kv": 33, "secondary_kv": 0.69, "cost_gbp": 180000},
    "11kv_2mva": {"name": "11/0.4kV 2MVA", "mva": 2, "primary_kv": 11, "secondary_kv": 0.4, "cost_gbp": 45000},
}

CABLE_SPECS = {
    "dc_string": {"type": "DC", "voltage": "1500V", "cross_section_mm2": 6, "cost_per_m_gbp": 3.50, "max_current_a": 40},
    "dc_main": {"type": "DC", "voltage": "1500V", "cross_section_mm2": 16, "cost_per_m_gbp": 8.00, "max_current_a": 80},
    "ac_lv": {"type": "AC LV", "voltage": "690V", "cross_section_mm2": 240, "cost_per_m_gbp": 35.00, "max_current_a": 400},
    "ac_mv_33kv": {"type": "AC MV", "voltage": "33kV", "cross_section_mm2": 185, "cost_per_m_gbp": 85.00, "max_current_a": 350},
    "ac_mv_11kv": {"type": "AC MV", "voltage": "11kV", "cross_section_mm2": 95, "cost_per_m_gbp": 45.00, "max_current_a": 250},
}

def design_electrical(
    layout_summary: dict,  # from solar_layout_engine
    panel_watts: int = 600,
    panel_voc: float = 51.8,  # open circuit voltage
    panel_isc: float = 14.5,  # short circuit current
    modules_per_string: int = 24,
    inverter_type: str = "huawei_sun2000_215",
    transformer_voltage_kv: int = 33,
    poc_lat: float = None,  # point of connection
    poc_lon: float = None,
) -> dict:
    """Auto-generate electrical design from solar layout."""

    total_panels = layout_summary.get("total_panels", 10000)
    total_mwp = layout_summary.get("total_mwp", total_panels * panel_watts / 1e6)
    total_strings = math.ceil(total_panels / modules_per_string)

    inv = INVERTERS.get(inverter_type, INVERTERS["huawei_sun2000_215"])

    # String voltage check
    string_voc = modules_per_string * panel_voc
    if string_voc > 1500:
        modules_per_string = int(1500 / panel_voc)
        total_strings = math.ceil(total_panels / modules_per_string)
        string_voc = modules_per_string * panel_voc

    # Number of inverters
    strings_per_inverter = inv["max_strings"]
    n_inverters = math.ceil(total_strings / strings_per_inverter)

    # Number of transformers
    if transformer_voltage_kv == 33:
        tx = TRANSFORMERS["33kv_5mva"] if total_mwp < 15 else TRANSFORMERS["33kv_10mva"]
    else:
        tx = TRANSFORMERS["11kv_2mva"]
    n_transformers = math.ceil(total_mwp / tx["mva"])

    # Inverter groups (inverters per transformer)
    inverters_per_tx = math.ceil(n_inverters / n_transformers)

    # Cable length estimates
    avg_string_length_m = 30  # average DC string cable run
    avg_dc_main_m = 50  # DC main from combiner to inverter
    avg_ac_lv_m = 20  # inverter to transformer (LV side)
    avg_ac_mv_m = 200 * n_transformers  # transformer to POC (MV cable)

    dc_string_total_m = total_strings * avg_string_length_m
    dc_main_total_m = n_inverters * avg_dc_main_m
    ac_lv_total_m = n_inverters * avg_ac_lv_m
    ac_mv_total_m = avg_ac_mv_m

    # Costs
    dc_cable_cost = dc_string_total_m * CABLE_SPECS["dc_string"]["cost_per_m_gbp"] + dc_main_total_m * CABLE_SPECS["dc_main"]["cost_per_m_gbp"]
    ac_cable_cost = ac_lv_total_m * CABLE_SPECS["ac_lv"]["cost_per_m_gbp"] + ac_mv_total_m * CABLE_SPECS[f"ac_mv_{transformer_voltage_kv}kv"]["cost_per_m_gbp"]
    inverter_cost = n_inverters * inv["cost_gbp"]
    transformer_cost = n_transformers * tx["cost_gbp"]

    # Losses
    dc_losses_pct = 1.5  # DC cable losses
    ac_losses_pct = 1.0  # AC cable losses
    transformer_losses_pct = 1.0
    inverter_losses_pct = 2.0
    total_electrical_losses_pct = dc_losses_pct + ac_losses_pct + transformer_losses_pct + inverter_losses_pct

    # Single Line Diagram data
    sld = {
        "levels": [
            {"level": "DC String", "voltage": f"{string_voc:.0f}V DC", "count": total_strings, "equipment": f"{modules_per_string} panels/string"},
            {"level": "Inverter", "voltage": f"{inv['kva']}kVA", "count": n_inverters, "equipment": inv["name"]},
            {"level": "Transformer", "voltage": f"{tx['primary_kv']}/{tx['secondary_kv']}kV", "count": n_transformers, "equipment": tx["name"]},
            {"level": "MV Collection", "voltage": f"{transformer_voltage_kv}kV", "count": 1, "equipment": f"{transformer_voltage_kv}kV switchgear"},
            {"level": "Point of Connection", "voltage": f"{transformer_voltage_kv}kV", "count": 1, "equipment": "DNO metering + protection"},
        ],
        "connections": [
            {"from": "DC String", "to": "Inverter", "cable": "DC 1500V 6mm²", "count": total_strings},
            {"from": "Inverter", "to": "Transformer", "cable": f"AC {tx['secondary_kv']}kV 240mm²", "count": n_inverters},
            {"from": "Transformer", "to": "MV Collection", "cable": f"AC {transformer_voltage_kv}kV 185mm²", "count": n_transformers},
            {"from": "MV Collection", "to": "Point of Connection", "cable": f"AC {transformer_voltage_kv}kV 185mm²", "count": 1},
        ],
    }

    return {
        "design": {
            "total_panels": total_panels,
            "total_mwp": round(total_mwp, 2),
            "modules_per_string": modules_per_string,
            "total_strings": total_strings,
            "string_voc": round(string_voc, 1),
            "string_isc": panel_isc,
            "inverter": inv["name"],
            "inverter_count": n_inverters,
            "strings_per_inverter": strings_per_inverter,
            "transformer": tx["name"],
            "transformer_count": n_transformers,
            "inverters_per_transformer": inverters_per_tx,
            "collection_voltage_kv": transformer_voltage_kv,
        },
        "cables": {
            "dc_string": {"length_m": dc_string_total_m, "spec": "1500V DC 6mm²", "cost_gbp": round(dc_string_total_m * 3.5)},
            "dc_main": {"length_m": dc_main_total_m, "spec": "1500V DC 16mm²", "cost_gbp": round(dc_main_total_m * 8)},
            "ac_lv": {"length_m": ac_lv_total_m, "spec": f"{tx['secondary_kv']}kV 240mm²", "cost_gbp": round(ac_lv_total_m * 35)},
            "ac_mv": {"length_m": ac_mv_total_m, "spec": f"{transformer_voltage_kv}kV 185mm²", "cost_gbp": round(ac_mv_total_m * 85)},
            "total_cable_m": dc_string_total_m + dc_main_total_m + ac_lv_total_m + ac_mv_total_m,
            "total_cable_cost_gbp": round(dc_cable_cost + ac_cable_cost),
        },
        "costs": {
            "inverters_gbp": round(inverter_cost),
            "transformers_gbp": round(transformer_cost),
            "dc_cables_gbp": round(dc_cable_cost),
            "ac_cables_gbp": round(ac_cable_cost),
            "switchgear_gbp": round(n_transformers * 35000),
            "protection_gbp": round(25000 + n_transformers * 15000),
            "earthing_gbp": round(total_mwp * 5000),
            "total_ebos_gbp": round(inverter_cost + transformer_cost + dc_cable_cost + ac_cable_cost + n_transformers * 50000 + total_mwp * 5000),
            "ebos_per_mwp_gbp": round((inverter_cost + transformer_cost + dc_cable_cost + ac_cable_cost + n_transformers * 50000) / total_mwp),
        },
        "losses": {
            "dc_cable_pct": dc_losses_pct,
            "inverter_pct": inverter_losses_pct,
            "transformer_pct": transformer_losses_pct,
            "ac_cable_pct": ac_losses_pct,
            "total_electrical_pct": total_electrical_losses_pct,
        },
        "sld": sld,
        "equipment_list": [
            {"item": inv["name"], "qty": n_inverters, "unit_cost": inv["cost_gbp"], "total": round(inverter_cost)},
            {"item": tx["name"], "qty": n_transformers, "unit_cost": tx["cost_gbp"], "total": round(transformer_cost)},
            {"item": f"{transformer_voltage_kv}kV RMU", "qty": n_transformers, "unit_cost": 35000, "total": round(n_transformers * 35000)},
            {"item": f"DC Cable 6mm² ({dc_string_total_m}m)", "qty": 1, "unit_cost": round(dc_string_total_m * 3.5), "total": round(dc_string_total_m * 3.5)},
            {"item": f"MV Cable {transformer_voltage_kv}kV ({ac_mv_total_m}m)", "qty": 1, "unit_cost": round(ac_mv_total_m * 85), "total": round(ac_mv_total_m * 85)},
        ],
    }
