"""
Gemini 3D Asset Modeller — uses Google Gemini to research construction specs
for energy infrastructure assets and generate procedural 3D model parameters.

Supports: data_centre, substation, solar_farm, wind_turbine, bess, hydrogen_electrolyser

Returns structured JSON with dimensions, materials, sub-components,
and construction protocol that the frontend Three.js renderer can build.
"""

import json
import logging
import os
import httpx

log = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Fallback specs when Gemini is unavailable
FALLBACK_SPECS = {
    "data_centre": {
        "name": "Hyperscale Data Centre",
        "footprint_m": [80, 50],
        "height_m": 15,
        "components": [
            {"type": "hall", "dims": [70, 40, 12], "color": "#2a2a3e", "position": [0, 6, 0]},
            {"type": "cooling_yard", "dims": [25, 40, 4], "color": "#3d5a80", "position": [47, 2, 0]},
            {"type": "generator_compound", "dims": [20, 15, 5], "color": "#4a4a4a", "position": [-45, 2.5, 15]},
            {"type": "hv_switchgear", "dims": [8, 4, 6], "color": "#6b4226", "position": [-45, 3, -15]},
            {"type": "security_fence", "dims": [90, 0.1, 60], "color": "#666666", "position": [0, 1.2, 0]},
            {"type": "admin_block", "dims": [15, 8, 12], "color": "#4a5568", "position": [-35, 4, -20]},
            {"type": "roof_unit", "dims": [6, 3, 6], "color": "#5a7d9a", "position": [0, 13.5, 0], "repeat": [4, 1, 3], "spacing": [14, 0, 10]},
        ],
        "power_mw": 30,
        "construction_months": 24,
        "cost_gbp_m": 450,
        "protocol": [
            "Site clearance and earthworks (3 months)",
            "Foundations — reinforced concrete raft, 600mm thick (2 months)",
            "Steel frame erection — 15m clear span (3 months)",
            "Envelope — insulated composite panels, vapour barrier (2 months)",
            "MEP first fix — raised floor, containment, busbar (3 months)",
            "Cooling plant — N+1 chillers, dry coolers, CRAH units (2 months)",
            "HV/LV power — 33/11kV transformers, UPS, generators (3 months)",
            "IT fit-out — racks, PDUs, structured cabling (2 months)",
            "Testing and commissioning — Tier III certification (2 months)",
            "Handover and go-live (2 months)",
        ],
    },
    "substation": {
        "name": "132/33kV Grid Supply Point",
        "footprint_m": [60, 40],
        "height_m": 12,
        "components": [
            {"type": "transformer", "dims": [6, 5, 4], "color": "#5d4e37", "position": [-10, 2.5, 0]},
            {"type": "transformer", "dims": [6, 5, 4], "color": "#5d4e37", "position": [10, 2.5, 0]},
            {"type": "busbar_gantry", "dims": [40, 0.3, 0.3], "color": "#c0c0c0", "position": [0, 10, 0]},
            {"type": "circuit_breaker", "dims": [2, 4, 2], "color": "#4a90d9", "position": [-20, 2, 5]},
            {"type": "circuit_breaker", "dims": [2, 4, 2], "color": "#4a90d9", "position": [0, 2, 5]},
            {"type": "circuit_breaker", "dims": [2, 4, 2], "color": "#4a90d9", "position": [20, 2, 5]},
            {"type": "control_room", "dims": [10, 4, 8], "color": "#4a5568", "position": [20, 2, -15]},
            {"type": "security_fence", "dims": [65, 0.1, 45], "color": "#666666", "position": [0, 1.2, 0]},
            {"type": "insulator_stack", "dims": [0.5, 3, 0.5], "color": "#e8d5b7", "position": [-10, 7, 0], "repeat": [1, 1, 1]},
        ],
        "power_mw": 90,
        "construction_months": 18,
        "cost_gbp_m": 25,
        "protocol": [
            "Ground investigation and environmental assessment (2 months)",
            "Civil works — foundations, cable trenches, access roads (3 months)",
            "Steelwork — gantries, equipment supports (2 months)",
            "Primary plant — transformers, switchgear delivery and installation (4 months)",
            "Secondary systems — protection relays, SCADA, telecomms (2 months)",
            "Cabling — HV/LV power cables, control cables, earthing (2 months)",
            "Testing — primary injection, protection proving (1 month)",
            "Commissioning and energisation (2 months)",
        ],
    },
    "solar_farm": {
        "name": "50MW Ground-Mount Solar Farm",
        "footprint_m": [500, 300],
        "height_m": 4,
        "components": [
            {"type": "panel_row", "dims": [480, 0.05, 2.2], "color": "#1a237e", "position": [0, 2.5, 0], "repeat": [1, 1, 60], "spacing": [0, 0, 4.5]},
            {"type": "inverter_station", "dims": [6, 3, 3], "color": "#37474f", "position": [-200, 1.5, 0], "repeat": [1, 1, 5], "spacing": [0, 0, 50]},
            {"type": "transformer_pad", "dims": [4, 2.5, 3], "color": "#5d4e37", "position": [-210, 1.25, 0], "repeat": [1, 1, 5], "spacing": [0, 0, 50]},
            {"type": "substation", "dims": [15, 5, 10], "color": "#4a5568", "position": [-230, 2.5, 0]},
            {"type": "perimeter_fence", "dims": [510, 0.1, 310], "color": "#666666", "position": [0, 1, 0]},
            {"type": "access_track", "dims": [520, 0.05, 4], "color": "#8d6e63", "position": [0, 0.05, -145]},
        ],
        "power_mw": 50,
        "construction_months": 12,
        "cost_gbp_m": 35,
        "protocol": [
            "Planning consent and grid connection agreement (6-12 months)",
            "Ecological surveys, BNG assessment, EIA (3 months)",
            "Site preparation — access tracks, fencing, drainage (2 months)",
            "Pile driving — steel screw piles for mounting frames (2 months)",
            "Mounting structure — aluminium tracker/fixed-tilt frames (2 months)",
            "Panel installation — bifacial modules, string wiring (3 months)",
            "Electrical — inverters, transformers, MV cabling (2 months)",
            "Grid connection — DNO switchgear, G99 compliance (1 month)",
            "Commissioning and performance testing (1 month)",
        ],
    },
    "bess": {
        "name": "100MW/200MWh Battery Storage Facility",
        "footprint_m": [80, 60],
        "height_m": 4,
        "components": [
            {"type": "battery_container", "dims": [12, 2.9, 2.4], "color": "#263238", "position": [0, 1.45, 0], "repeat": [4, 1, 8], "spacing": [15, 0, 5]},
            {"type": "pcs_inverter", "dims": [3, 2.5, 2], "color": "#37474f", "position": [-35, 1.25, 0], "repeat": [1, 1, 8], "spacing": [0, 0, 5]},
            {"type": "step_up_transformer", "dims": [5, 4, 4], "color": "#5d4e37", "position": [-42, 2, -10]},
            {"type": "step_up_transformer", "dims": [5, 4, 4], "color": "#5d4e37", "position": [-42, 2, 10]},
            {"type": "control_building", "dims": [8, 3.5, 6], "color": "#4a5568", "position": [35, 1.75, -25]},
            {"type": "fire_suppression", "dims": [3, 2, 3], "color": "#b71c1c", "position": [35, 1, 25]},
            {"type": "security_fence", "dims": [90, 0.1, 70], "color": "#666666", "position": [0, 1.2, 0]},
        ],
        "power_mw": 100,
        "construction_months": 14,
        "cost_gbp_m": 80,
        "protocol": [
            "Planning and grid connection offer acceptance (6 months)",
            "Site clearance and earthworks (2 months)",
            "Foundations — concrete pads for containers and equipment (2 months)",
            "Battery container delivery and placement (2 months)",
            "PCS/inverter installation and DC cabling (2 months)",
            "HV transformer and switchgear installation (2 months)",
            "BMS commissioning — cell balancing, thermal management (1 month)",
            "Grid compliance testing — G99, dynamic containment pre-qual (1 month)",
            "Commercial operations date (COD)",
        ],
    },
    "wind_turbine": {
        "name": "5MW Onshore Wind Turbine",
        "footprint_m": [20, 20],
        "height_m": 120,
        "components": [
            {"type": "tower_base", "dims": [6, 2, 6], "color": "#616161", "position": [0, 1, 0]},
            {"type": "tower_section_1", "dims": [4.5, 30, 4.5], "color": "#e0e0e0", "position": [0, 16, 0]},
            {"type": "tower_section_2", "dims": [3.5, 30, 3.5], "color": "#e0e0e0", "position": [0, 46, 0]},
            {"type": "tower_section_3", "dims": [2.8, 25, 2.8], "color": "#e0e0e0", "position": [0, 73.5, 0]},
            {"type": "nacelle", "dims": [8, 4, 4], "color": "#bdbdbd", "position": [0, 88, 0]},
            {"type": "hub", "dims": [2, 2, 2], "color": "#9e9e9e", "position": [5, 88, 0]},
            {"type": "blade", "dims": [0.8, 0.15, 60], "color": "#f5f5f5", "position": [6, 88, 0], "rotation": [0, 0, 0]},
            {"type": "blade", "dims": [0.8, 0.15, 60], "color": "#f5f5f5", "position": [6, 88, 0], "rotation": [120, 0, 0]},
            {"type": "blade", "dims": [0.8, 0.15, 60], "color": "#f5f5f5", "position": [6, 88, 0], "rotation": [240, 0, 0]},
            {"type": "foundation", "dims": [16, 0.5, 16], "color": "#757575", "position": [0, 0.25, 0]},
        ],
        "power_mw": 5,
        "construction_months": 8,
        "cost_gbp_m": 6,
        "protocol": [
            "Environmental impact assessment and aviation consultation (6 months)",
            "Access road construction — crane hardstanding (2 months)",
            "Foundation — reinforced concrete gravity base, 16m diameter (1 month)",
            "Tower erection — 3 sections via 750-tonne crane (3 days)",
            "Nacelle and hub lift (1 day)",
            "Blade installation (1 day)",
            "Electrical — transformer, MV cable to substation (1 month)",
            "Commissioning and grid synchronisation (2 weeks)",
        ],
    },
}


async def generate_asset_spec(asset_type: str, capacity_mw: float = None,
                                custom_prompt: str = None) -> dict:
    """
    Generate 3D asset specification using Gemini AI.

    Falls back to built-in specs if Gemini is unavailable.
    """
    if not GEMINI_API_KEY:
        log.info("No GEMINI_API_KEY — using fallback specs for %s", asset_type)
        spec = FALLBACK_SPECS.get(asset_type)
        if not spec:
            return {"error": f"Unknown asset type: {asset_type}. Available: {list(FALLBACK_SPECS.keys())}"}
        if capacity_mw:
            spec = {**spec, "power_mw": capacity_mw}
        return spec

    # Build Gemini prompt
    prompt = f"""You are an energy infrastructure construction expert. Generate a detailed 3D model specification for a {asset_type.replace('_', ' ')}.

{"Capacity: " + str(capacity_mw) + " MW" if capacity_mw else ""}
{custom_prompt or ""}

Return a JSON object with:
- name: descriptive name
- footprint_m: [width, depth] in meters
- height_m: max height
- components: array of sub-components, each with:
  - type: component name
  - dims: [width, height, depth] in meters
  - color: hex color string
  - position: [x, y, z] relative to centre (y is up)
  - repeat: [nx, ny, nz] optional repeat count
  - spacing: [sx, sy, sz] optional spacing between repeats
  - rotation: [rx, ry, rz] optional rotation in degrees
- power_mw: rated capacity
- construction_months: total build time
- cost_gbp_m: approximate cost in £ millions
- protocol: array of construction phase strings with durations

Use realistic UK construction standards (BS/IEC). Include all major visible components.
Return ONLY valid JSON, no markdown."""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 4096,
                    },
                },
            )
            r.raise_for_status()
            data = r.json()

        text = data["candidates"][0]["content"]["parts"][0]["text"]
        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        spec = json.loads(text)
        return spec

    except Exception as e:
        log.warning("Gemini asset generation failed: %s — using fallback", e)
        spec = FALLBACK_SPECS.get(asset_type)
        if not spec:
            return {"error": f"Gemini failed and no fallback for: {asset_type}"}
        if capacity_mw:
            spec = {**spec, "power_mw": capacity_mw}
        return spec


def list_asset_types() -> list:
    """Return available asset types with descriptions."""
    return [
        {"id": "data_centre", "label": "Hyperscale Data Centre", "icon": "server", "default_mw": 30},
        {"id": "substation", "label": "Grid Substation (132/33kV)", "icon": "zap", "default_mw": 90},
        {"id": "solar_farm", "label": "Ground-Mount Solar Farm", "icon": "sun", "default_mw": 50},
        {"id": "bess", "label": "Battery Storage (BESS)", "icon": "battery", "default_mw": 100},
        {"id": "wind_turbine", "label": "Onshore Wind Turbine", "icon": "wind", "default_mw": 5},
    ]
