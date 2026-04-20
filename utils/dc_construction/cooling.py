"""
Cooling plant — CRAC, chillers, cooling towers, chilled-water topology, WUE.

Heat-rejection model:
    IT load kW × (PUE_cooling_share) → heat rejected
    PUE_cooling_share is the cooling overhead — hybrid ≈ 0.20, free-cooling ≈ 0.10,
    evaporative ≈ 0.15, mechanical (chilled-water only) ≈ 0.30.

WUE calculation (The Green Grid):
    WUE = (annual site water use in L) / (annual IT energy in kWh)
    Reported as m³ / MWh IT (identical ratio, cleaner unit).

Standards:
    EN 50600-2-3:2019 §§ 5, 6, 7 (environmental conditions; cooling
        system classes A1–A3; spatial separation; maintenance access).
    EN 50600-4-9:2021 (water usage effectiveness — the KPI definition
        the frontend badge shows).
    ASHRAE TC 9.9 (2021) — Thermal Guidelines for Data Processing
        Environments; recommended envelope 18–27 °C @ 60 % RH.
    CIBSE Guide F (2012 + 2021 corrigenda) — chiller selection, free
        cooling hours mapping for UK climate zones.
    BS EN 378-1..4:2016 — refrigerating systems & heat pumps safety.
    Uptime Tier Standard §§ C2, C3 (concurrently-maintainable cooling).
"""

from __future__ import annotations

import math

from .base import ConstructionAsset, cite, cv


# PUE cooling-overhead share per cooling type
_COOLING_PUE_SHARE = {
    "mechanical":     0.30,
    "hybrid":         0.20,
    "free_cooling":   0.10,
    "evaporative":    0.15,
    "immersion":      0.08,
    "liquid":         0.07,
}

# Annual free-cooling hours for UK climate (CIBSE Guide F, central England)
_FREE_COOLING_HOURS_UK = {
    "mechanical":     0,
    "hybrid":         4_200,   # partial free cooling when T_ambient < 16 °C
    "free_cooling":   7_100,
    "evaporative":    6_400,
    "immersion":      8_200,   # year-round if secondary loop ≥ 45 °C
    "liquid":         8_000,
}

# Water consumption factor — L of water per MWh IT energy
# (Green Grid WUE; evaporative ~1.5, hybrid ~0.8, mech closed ~0.05)
_WUE_L_PER_MWH = {
    "mechanical":     50,
    "hybrid":         800,
    "free_cooling":   300,
    "evaporative":    1_500,
    "immersion":      100,
    "liquid":         250,
}


def _redundancy_factor(redundancy: str) -> float:
    return {"N": 1.0, "N+1": 1.15, "2N": 2.0, "2N+1": 2.15}.get(redundancy, 1.15)


def design_cooling(
    it_load_mw: float,
    tier: int = 3,
    redundancy: str = "N+1",
    cooling_type: str = "hybrid",
) -> ConstructionAsset:
    it_load_mw = max(0.5, float(it_load_mw))
    cooling_type = cooling_type if cooling_type in _COOLING_PUE_SHARE else "hybrid"

    # Thermal rejection (kW)
    cooling_overhead_mw = it_load_mw * _COOLING_PUE_SHARE[cooling_type]
    reject_mw = it_load_mw + cooling_overhead_mw * 0.85

    # Chiller sizing — UK pack size 1,500 kW per machine (CIBSE Guide F)
    chiller_unit_kw = 1_500
    rf = _redundancy_factor(redundancy)
    chiller_count_n = max(1, math.ceil(reject_mw * 1000 / chiller_unit_kw))
    chiller_count = math.ceil(chiller_count_n * rf)
    chiller_total_kw = chiller_count * chiller_unit_kw
    chiller_tonnage = chiller_total_kw / 3.517  # 1 ton refrigeration = 3.517 kW

    # CRAC sizing — per IT hall, 100 kW per CRAC (typical perimeter DX/CW unit)
    crac_unit_kw = 100
    crac_count = math.ceil(it_load_mw * 1000 / crac_unit_kw * rf)

    # Cooling towers — 1 tower per 3 MW reject @ hybrid/evaporative
    if cooling_type in ("hybrid", "evaporative", "mechanical"):
        tower_count = math.ceil(reject_mw / 3.0 * rf)
    else:
        tower_count = 0

    # Free-cooling hours and water consumption
    free_cool_h = _FREE_COOLING_HOURS_UK[cooling_type]
    wue_l_per_mwh = _WUE_L_PER_MWH[cooling_type]
    annual_it_mwh = it_load_mw * 8_760 * 0.60    # 60 % utilisation avg
    water_m3_yr = annual_it_mwh * wue_l_per_mwh / 1_000

    # WUE in m³/MWh
    wue_m3_mwh = wue_l_per_mwh / 1_000

    # Physical yard: 35 % of shell footprint (matches geometric model)
    yard_area_m2 = it_load_mw * 600 * 0.35
    yard_height_m = 5.0

    # CapEx — £220k / chiller (1.5 MW air-cooled screw), £30k per CRAC,
    # £60k per cooling tower, plus glycol/primary/secondary piping at
    # £450/kW reject. Based on DBEI construction data + MEP indices.
    capex = (chiller_count * 220_000
             + crac_count * 30_000
             + tower_count * 60_000
             + reject_mw * 1000 * 450)

    # OpEx — chiller service contracts + chemical dosing + water charges
    opex = (chiller_count * 12_000
            + water_m3_yr * 2.10           # UK industrial water tariff ~£2.10/m³
            + tower_count * 6_000)

    c_en_2_3 = cite("EN 50600-2-3:2019", "§§ 5–7 Environmental conditions",
                    "Class A1–A3 thermal envelope, cooling redundancy, maintenance.")
    c_wue = cite("EN 50600-4-9:2021", "WUE KPI definition",
                 "Water Usage Effectiveness — annual L ÷ IT MWh.")
    c_ashrae = cite("ASHRAE TC 9.9 (2021)", "Thermal Guidelines",
                    "Recommended inlet 18–27 °C, 8.0 % dp min / 70 % rh max.")
    c_cibse = cite("CIBSE Guide F (2021)", "Chiller selection & free-cooling hours",
                   "UK free-cooling hour maps used for sizing.")
    c_bs378 = cite("BS EN 378-1..4:2016", "Refrigerating systems safety",
                   "Machinery room ventilation, refrigerant charge limits.")
    c_tier = cite("Uptime Tier Standard: Topology", "§ C2 Cooling path redundancy",
                  "Tier 3: concurrently-maintainable. Tier 4: fault-tolerant.")

    a = ConstructionAsset(
        type="cooling",
        label="Cooling plant",
        dimensions={
            "yard_width_m": round(math.sqrt(yard_area_m2 * 1.4), 1),
            "yard_depth_m": round(math.sqrt(yard_area_m2 / 1.4), 1),
            "height_m": yard_height_m,
        },
        area_m2=round(yard_area_m2, 1),
        volume_m3=round(yard_area_m2 * yard_height_m, 1),
        capex_gbp=round(capex, 0),
        opex_gbp_per_yr=round(opex, 0),
        provenance="EN 50600-2-3 + CIBSE F + The Green Grid WUE",
    )

    a.set("cooling_type", cv(cooling_type, "", c_ashrae,
                             "Topology affects PUE, WUE, free-cooling hours."))
    a.set("chiller_count", cv(chiller_count, "units", c_tier,
                              f"{redundancy}: N={chiller_count_n}, ×{rf} redundancy factor"))
    a.set("chiller_unit_kw", cv(chiller_unit_kw, "kW each", c_cibse,
                                "1.5 MW air-cooled screw chiller — CIBSE Guide F benchmark"))
    a.set("chiller_total_tonnage_tonRef",
          cv(round(chiller_tonnage, 0), "ton refrigeration", c_cibse,
             "1 ton = 3.517 kW"))
    a.set("crac_count", cv(crac_count, "CRAC units", c_en_2_3,
                           "100 kW perimeter CRAC per 100 kW IT"))
    a.set("cooling_tower_count", cv(tower_count, "units", c_cibse,
                                    "1 tower per 3 MW reject (hybrid/evap)"))
    a.set("free_cooling_hours_yr",
          cv(free_cool_h, "h/yr", c_cibse, "UK central-England climate"))
    a.set("water_consumption_m3_yr",
          cv(round(water_m3_yr, 0), "m³/yr", c_wue,
             "WUE × annual IT MWh × 60 % avg utilisation"))
    a.set("wue_m3_per_MWh",
          cv(round(wue_m3_mwh, 3), "m³/MWh", c_wue,
             "Green Grid definition — site water / IT energy"))
    a.set("glycol_loop",
          cv(35 if cooling_type in ("hybrid", "free_cooling", "evaporative") else 0,
             "% ethylene glycol", c_bs378,
             "Low-temperature protection for outdoor coil circuits"))
    a.set("chilled_water_topology",
          cv("Primary/Secondary/Tertiary — CHWS 7 °C / CHWR 14 °C / rack 22 °C",
             "", c_en_2_3, "Tertiary pumps at each hall for temp control"))
    a.set("refrigerant",
          cv("R-1234ze (GWP 7) — HFO low-GWP" if cooling_type != "immersion"
             else "Two-phase dielectric fluid", "",
             c_bs378, "F-gas regulation 2024 phase-down compliant"))

    a.notes.append(
        f"Nominal reject: {reject_mw*1000:.0f} kW. "
        f"Free-cooling hours: {free_cool_h} h/yr. "
        f"Annual water draw: {water_m3_yr:,.0f} m³."
    )
    return a
