"""
Building shell — structural envelope, IT hall compartmentation, Part L envelope.

Sizing heuristic (DIRECTIONALLY CORRECT, not survey-grade):
    footprint ≈ 600 m² per MW IT load (2-storey hyperscale hall layout)
    height    = min(24 m, 12 m base + 0.4 m per MW)
    GFA       = footprint × storey_count

Standards anchored:
    EN 50600-2-1:2021 §§ 4,5,6 (building construction — robustness,
        fire, telecommunications space, safety).
    BS 9991:2015 §§ 3.4–3.7 (compartmentation — IT halls treated as
        high fire-load occupancy; 2,000 m² compartment ceiling is the
        working limit absent sprinklers + smoke control).
    Approved Document Part B Vol 2, Table B1 (maximum compartment
        size for industrial buildings).
    Approved Document Part L 2021 §§ 5.10–5.14 (air permeability
        ≤ 5 m³/(h·m²) @ 50 Pa; U-values: roof 0.18, wall 0.26,
        floor 0.18 W/m²K).
    BS EN 1991-1-1:2002 §§ 6.3 + UK NA Table NA.3 (imposed floor
        loads — server-rack halls typically designed 12–15 kN/m²).
    Uptime Institute Tier Standard: Topology (2022), Tier 3 requires
        concurrently-maintainable path — drives double-skin plenum.
"""

from __future__ import annotations

import math

from .base import ConstructionAsset, cite, cv


def design_shell(
    it_load_mw: float,
    tier: int = 3,
    ceiling_height_m: float = 6.0,
    it_hall_max_area_m2: float = 2_000.0,   # BS 9991 / ADB compartment ceiling
    slab_loading_kn_m2: float = 15.0,       # BS EN 1991-1-1, server halls
) -> ConstructionAsset:

    it_load_mw = max(0.5, float(it_load_mw))
    footprint = it_load_mw * 600.0                          # m² @ 600 m²/MW
    height_m = min(24.0, 12.0 + 0.4 * it_load_mw)
    storey_count = 2 if it_load_mw <= 250 else 1            # hyperscale halls tend single-storey over 250 MW
    gfa = footprint * storey_count
    volume = gfa * ceiling_height_m

    # IT hall count — compartmented at 2,000 m² per BS 9991 / ADB
    usable_ratio = 0.62                                     # 62% of GFA is IT whitespace
    whitespace = gfa * usable_ratio
    hall_count = max(1, math.ceil(whitespace / it_hall_max_area_m2))
    hall_area = round(whitespace / hall_count, 1)

    # CapEx — RICS BCIS 2025 mean rate for industrial sheds + DC premium.
    # £2,400/m² GFA for a Tier 3 hall; +£300/m² for Tier 4; -£200 for Tier 2.
    tier_premium = {1: -300, 2: -200, 3: 0, 4: 300}.get(tier, 0)
    capex_rate = 2_400 + tier_premium
    capex = gfa * capex_rate

    # OpEx — building-fabric-only: insurance, fabric maintenance,
    # periodic re-coating of cladding. ~£12/m² GFA/yr.
    opex = gfa * 12.0

    cite_en_2_1 = cite("EN 50600-2-1:2021",
                       "§§ 4-6 Building construction",
                       "Robustness, fire-protection, telecom space, safety.")
    cite_bs_9991 = cite("BS 9991:2015",
                        "§§ 3.4–3.7 Compartmentation",
                        "IT hall ≤ 2,000 m² compartment (high fire-load).")
    cite_adb = cite("Approved Document B Vol 2",
                    "Table B1 maximum compartment size",
                    "Industrial: 2,000 m² unsprinklered, higher with AFSS.")
    cite_partl = cite("Approved Document L (2021)",
                      "§§ 5.10-5.14 Air permeability & U-values",
                      "AP ≤ 5 m³/(h·m²)@50Pa; wall U ≤ 0.26 W/m²K; roof ≤ 0.18.")
    cite_ec1 = cite("BS EN 1991-1-1:2002",
                    "Table NA.3 UK NA",
                    "Server-hall imposed load 12–15 kN/m² typical.")
    cite_tier = cite("Uptime Tier Standard: Topology (2022)",
                     "Tier 3 requires concurrently-maintainable path",
                     "Drives double-skin plenum & 2N path separation in shell.")

    a = ConstructionAsset(
        type="shell",
        label="Building shell",
        dimensions={
            "width_m": round(math.sqrt(footprint), 1),
            "depth_m": round(math.sqrt(footprint), 1),
            "height_m": round(height_m, 1),
            "storey_count": storey_count,
        },
        area_m2=round(footprint, 1),
        volume_m3=round(volume, 1),
        capex_gbp=round(capex, 0),
        opex_gbp_per_yr=round(opex, 0),
        provenance="EN 50600-2-1 + BS 9991 + Part L + RICS BCIS 2025",
    )

    a.set("footprint_m2", cv(round(footprint, 1), "m²",
                             cite_en_2_1, "600 m²/MW hyperscale rule of thumb"))
    a.set("gfa_m2", cv(round(gfa, 1), "m²", cite_en_2_1,
                       f"2-storey: footprint × {storey_count}"))
    a.set("height_m", cv(round(height_m, 1), "m", cite_en_2_1,
                         "12 m base + 0.4 m/MW, capped at 24 m"))
    a.set("structural_system",
          cv("Steel portal frame + reinforced concrete slab on piles", "",
             cite_ec1, "Pile type chosen by ground investigation (Phase 2)"))
    a.set("floor_loading_kN_m2",
          cv(slab_loading_kn_m2, "kN/m²", cite_ec1,
             "Server-rack load incl. 45U cabinets at max fill."))
    a.set("roof_spec",
          cv("Composite insulated panel, PIR 150 mm, U = 0.18 W/m²K", "",
             cite_partl, "Part L 2021 notional roof U-value"))
    a.set("wall_spec",
          cv("Composite insulated panel, PIR 120 mm, U = 0.26 W/m²K", "",
             cite_partl, "Part L 2021 notional wall U-value"))
    a.set("air_permeability",
          cv(5.0, "m³/(h·m²)@50 Pa", cite_partl,
             "Part L 2021 § 5.13 limit"))
    a.set("it_hall_count", cv(hall_count, "halls", cite_bs_9991,
                              "Each ≤ 2,000 m² compartment floor area"))
    a.set("it_hall_area_each_m2",
          cv(hall_area, "m²", cite_bs_9991,
             "62% usable ratio × GFA / hall count"))
    a.set("floor_construction",
          cv("Slab-on-grade with 800 mm raised access floor in IT halls", "",
             cite_ec1, "Underfloor air + cable distribution plenum"))
    a.set("fire_compartment_wall_rating",
          cv(120, "minutes", cite_adb,
             "2 hr fire-resisting walls between IT compartments"))
    a.set("tier_path_separation",
          cv("2N electrical risers in separate 2 hr fire cells" if tier >= 3
             else "Single riser",
             "", cite_tier, "Tier 3 concurrent maintainability"))

    a.notes.append(
        f"Hall layout: {hall_count} × {hall_area:.0f} m² IT compartments. "
        f"Walk-through aisles + non-IT support space account for remaining 38 % of GFA."
    )
    return a
