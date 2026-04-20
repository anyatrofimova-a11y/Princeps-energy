"""SIC-keyed typology library — normalised load curves per MW installed.

Each typology provides a 24-hour half-hourly profile (48 points) plus
weekday/weekend modifiers, load factor, weather sensitivity, and long-term
annual growth rates keyed to NESO FES 2024 pathways and DESNZ sub-national
consumption stats.

Sources:
- DESNZ Sub-national electricity consumption statistics (2022/2023)
- NESO Future Energy Scenarios 2024 pathways (annual demand index 2024→2050)
- BEIS Industrial Energy Consumption in the UK
- Uptime Institute PUE survey (data centres)
- Carbon Trust Building Energy Benchmarks (commercial)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import math


@dataclass
class Typology:
    key: str                          # slug
    name: str                         # human label
    sic_codes: list[str]              # 2007 SIC codes covered
    load_factor: float                # annual mean / peak, 0-1
    weekday_weekend_ratio: float      # weekday_peak / weekend_peak
    weather_sensitivity: float        # MW change per degC below 15C (per MW peak)
    hh_profile: list[float]           # 48 half-hour multipliers, normalised so peak = 1.0
    ev_uplift_frac: float = 0.0       # fraction of peak added per full-pen EV adoption
    hp_uplift_frac: float = 0.0       # ditto for heat pumps (winter-weighted)
    base_growth_pa: float = 0.015     # central annual growth
    pathway_growth: dict[str, float] = field(default_factory=dict)  # NESO FES pathways
    description: str = ""

    def profile_for_interval(self, interval_min: int) -> list[float]:
        """Resample HH profile to given interval. interval_min divides 1440."""
        if interval_min == 30:
            return list(self.hh_profile)
        if interval_min == 60:
            # average each pair
            return [(self.hh_profile[i] + self.hh_profile[i + 1]) / 2
                    for i in range(0, 48, 2)]
        if interval_min == 15:
            out: list[float] = []
            for v in self.hh_profile:
                out.extend([v, v])
            return out
        # generic linear interpolation
        steps = 1440 // interval_min
        out = []
        for i in range(steps):
            frac = (i * interval_min / 30.0) % 48
            a = int(frac) % 48
            b = (a + 1) % 48
            w = frac - int(frac)
            out.append(self.hh_profile[a] * (1 - w) + self.hh_profile[b] * w)
        return out


def _bell(peak_hh: float, width: float, amplitude: float, base: float) -> list[float]:
    """Build a bell-shaped 48-point HH curve peaking at peak_hh (0..48)."""
    out = []
    for i in range(48):
        d = min(abs(i - peak_hh), 48 - abs(i - peak_hh))
        v = base + amplitude * math.exp(-(d * d) / (2 * width * width))
        out.append(v)
    m = max(out)
    return [v / m for v in out]


def _flat_with_dip(base: float, dip_hh: float, dip_amount: float) -> list[float]:
    """Flat ~base with a dip (e.g. DC cooling low at night)."""
    out = [base] * 48
    for i in range(48):
        d = min(abs(i - dip_hh), 48 - abs(i - dip_hh))
        if d < 6:
            out[i] = base - dip_amount * math.exp(-(d * d) / 18)
    m = max(out)
    return [v / m for v in out]


def _twin_peak(morning_hh: float, evening_hh: float, amp: float, base: float) -> list[float]:
    """Classic residential twin-peak."""
    out = []
    for i in range(48):
        dm = min(abs(i - morning_hh), 48 - abs(i - morning_hh))
        de = min(abs(i - evening_hh), 48 - abs(i - evening_hh))
        v = base + amp * (math.exp(-(dm * dm) / 10) + 1.3 * math.exp(-(de * de) / 10))
        out.append(v)
    m = max(out)
    return [v / m for v in out]


# ----------------------------------------------------------------------------
# The typology library — ranked by UK energy developer pipeline relevance.
# ----------------------------------------------------------------------------
SIC_TYPOLOGIES: dict[str, Typology] = {
    "data_centre_hyperscale": Typology(
        key="data_centre_hyperscale",
        name="Hyperscale data centre",
        sic_codes=["63110", "63120"],
        load_factor=0.92,
        weekday_weekend_ratio=1.02,
        weather_sensitivity=0.008,  # cooling uplift in summer
        hh_profile=[0.93 + 0.04 * math.sin((i - 14) / 48 * 2 * math.pi) for i in range(48)],
        ev_uplift_frac=0.0,
        hp_uplift_frac=0.0,
        base_growth_pa=0.06,
        pathway_growth={
            "leading_the_way": 0.085,
            "consumer_transformation": 0.07,
            "system_transformation": 0.075,
            "falling_short": 0.035,
            "central": 0.06,
        },
        description="24/7 IT load, flat ~90% LF, PUE 1.2-1.4. Summer cooling uplift.",
    ),
    "data_centre_colo": Typology(
        key="data_centre_colo",
        name="Colocation / enterprise data centre",
        sic_codes=["63110"],
        load_factor=0.78,
        weekday_weekend_ratio=1.05,
        weather_sensitivity=0.012,
        hh_profile=[0.82 + 0.10 * max(0.0, math.sin((i - 10) / 48 * 2 * math.pi)) for i in range(48)],
        base_growth_pa=0.045,
        pathway_growth={
            "leading_the_way": 0.06, "consumer_transformation": 0.05,
            "system_transformation": 0.055, "falling_short": 0.025, "central": 0.045,
        },
        description="Business-hour peak, overnight ~80%, PUE 1.5-1.7.",
    ),
    "heavy_industry_chemicals": Typology(
        key="heavy_industry_chemicals",
        name="Heavy industry — chemicals / petrochem",
        sic_codes=["20110", "20130", "20140", "20150", "20160", "20170"],
        load_factor=0.85,
        weekday_weekend_ratio=1.08,
        weather_sensitivity=0.003,
        hh_profile=_flat_with_dip(0.88, 5, 0.12),  # slight overnight maintenance dip
        base_growth_pa=0.005,
        pathway_growth={
            "leading_the_way": 0.02, "consumer_transformation": 0.01,
            "system_transformation": 0.015, "falling_short": -0.005, "central": 0.005,
        },
        description="Continuous-process plant, minor shift dip, some electrification upside.",
    ),
    "heavy_industry_steel": Typology(
        key="heavy_industry_steel",
        name="Heavy industry — steel / metals (EAF)",
        sic_codes=["24100", "24200", "24400", "24510"],
        load_factor=0.55,
        weekday_weekend_ratio=1.35,
        weather_sensitivity=0.002,
        hh_profile=_bell(peak_hh=22, width=9, amplitude=0.7, base=0.25),
        base_growth_pa=0.04,  # EAF electrification
        pathway_growth={
            "leading_the_way": 0.09, "consumer_transformation": 0.06,
            "system_transformation": 0.07, "falling_short": 0.01, "central": 0.04,
        },
        description="Electric Arc Furnace — peaky, off-peak dispatch, strong decarb-driven growth.",
    ),
    "commercial_office": Typology(
        key="commercial_office",
        name="Commercial office",
        sic_codes=["68100", "68200", "70100", "70220", "69100"],
        load_factor=0.42,
        weekday_weekend_ratio=3.2,
        weather_sensitivity=0.020,
        hh_profile=_bell(peak_hh=26, width=7, amplitude=0.85, base=0.15),
        ev_uplift_frac=0.05,
        hp_uplift_frac=0.08,
        base_growth_pa=0.012,
        pathway_growth={
            "leading_the_way": 0.025, "consumer_transformation": 0.02,
            "system_transformation": 0.02, "falling_short": 0.005, "central": 0.012,
        },
        description="09:00-18:00 peak, strong weekend drop, HVAC weather-sensitive.",
    ),
    "retail_shopping": Typology(
        key="retail_shopping",
        name="Retail / shopping centre",
        sic_codes=["47110", "47190", "47710", "47610"],
        load_factor=0.48,
        weekday_weekend_ratio=0.95,   # weekends as strong as weekdays
        weather_sensitivity=0.018,
        hh_profile=_bell(peak_hh=28, width=9, amplitude=0.75, base=0.22),
        ev_uplift_frac=0.12,
        base_growth_pa=0.010,
        pathway_growth={
            "leading_the_way": 0.02, "consumer_transformation": 0.015,
            "system_transformation": 0.018, "falling_short": 0.004, "central": 0.010,
        },
        description="Trading-hours peak, equal weekends, strong EV-charging uplift potential.",
    ),
    "ev_charging_hub": Typology(
        key="ev_charging_hub",
        name="EV ultra-rapid charging hub",
        sic_codes=["47300", "52210"],
        load_factor=0.28,
        weekday_weekend_ratio=0.85,
        weather_sensitivity=0.005,
        hh_profile=_twin_peak(morning_hh=16, evening_hh=36, amp=0.55, base=0.12),
        ev_uplift_frac=1.0,  # dominated by EV
        base_growth_pa=0.18,
        pathway_growth={
            "leading_the_way": 0.28, "consumer_transformation": 0.22,
            "system_transformation": 0.20, "falling_short": 0.10, "central": 0.18,
        },
        description="Travel-peak demand 8am/6pm, <30% LF. Highest growth typology.",
    ),
    "cold_storage": Typology(
        key="cold_storage",
        name="Cold storage / refrigerated logistics",
        sic_codes=["52101", "10890"],
        load_factor=0.72,
        weekday_weekend_ratio=1.15,
        weather_sensitivity=0.028,   # strongly ambient-driven
        hh_profile=_bell(peak_hh=30, width=14, amplitude=0.35, base=0.60),
        base_growth_pa=0.025,
        pathway_growth={
            "leading_the_way": 0.04, "consumer_transformation": 0.03,
            "system_transformation": 0.035, "falling_short": 0.015, "central": 0.025,
        },
        description="High LF, summer-peaking, flat profile — good grid customer.",
    ),
    "residential_hp_heavy": Typology(
        key="residential_hp_heavy",
        name="Residential — heat-pump heavy",
        sic_codes=["98000"],   # household-activity proxy
        load_factor=0.38,
        weekday_weekend_ratio=0.88,
        weather_sensitivity=0.045,   # HP-dominant
        hh_profile=_twin_peak(morning_hh=14, evening_hh=38, amp=0.55, base=0.22),
        ev_uplift_frac=0.30,
        hp_uplift_frac=0.60,
        base_growth_pa=0.030,
        pathway_growth={
            "leading_the_way": 0.055, "consumer_transformation": 0.050,
            "system_transformation": 0.035, "falling_short": 0.010, "central": 0.030,
        },
        description="Twin-peak, morning+evening, winter HP surge. Largest FES growth band.",
    ),
    "waste_treatment": Typology(
        key="waste_treatment",
        name="Waste & water treatment",
        sic_codes=["37000", "38210", "38320", "36000"],
        load_factor=0.68,
        weekday_weekend_ratio=1.10,
        weather_sensitivity=0.006,
        hh_profile=_flat_with_dip(0.78, 6, 0.18),
        base_growth_pa=0.012,
        pathway_growth={
            "leading_the_way": 0.02, "consumer_transformation": 0.015,
            "system_transformation": 0.018, "falling_short": 0.005, "central": 0.012,
        },
        description="Continuous pumps/aeration, mild daytime uplift.",
    ),
    "manufacturing_general": Typology(
        key="manufacturing_general",
        name="General manufacturing (single-shift)",
        sic_codes=["25000", "28000", "29000", "27000"],
        load_factor=0.50,
        weekday_weekend_ratio=2.8,
        weather_sensitivity=0.008,
        hh_profile=_bell(peak_hh=22, width=7, amplitude=0.80, base=0.15),
        base_growth_pa=0.008,
        pathway_growth={
            "leading_the_way": 0.025, "consumer_transformation": 0.015,
            "system_transformation": 0.02, "falling_short": 0.000, "central": 0.008,
        },
        description="06:00-18:00 shift, weekend drop, moderate electrification.",
    ),
    "food_processing": Typology(
        key="food_processing",
        name="Food & drink processing",
        sic_codes=["10000", "10110", "10200", "10500", "10610", "10710", "11000"],
        load_factor=0.65,
        weekday_weekend_ratio=1.35,
        weather_sensitivity=0.015,
        hh_profile=_bell(peak_hh=24, width=11, amplitude=0.55, base=0.35),
        base_growth_pa=0.012,
        pathway_growth={
            "leading_the_way": 0.025, "consumer_transformation": 0.02,
            "system_transformation": 0.02, "falling_short": 0.005, "central": 0.012,
        },
        description="Extended-shift, refrigeration-heavy. Moderate LF, summer uplift.",
    ),
    "hospital_healthcare": Typology(
        key="hospital_healthcare",
        name="Hospital / large healthcare",
        sic_codes=["86100", "86200", "87100"],
        load_factor=0.74,
        weekday_weekend_ratio=1.05,
        weather_sensitivity=0.015,
        hh_profile=_bell(peak_hh=22, width=11, amplitude=0.30, base=0.70),
        hp_uplift_frac=0.20,
        base_growth_pa=0.014,
        pathway_growth={
            "leading_the_way": 0.03, "consumer_transformation": 0.022,
            "system_transformation": 0.024, "falling_short": 0.006, "central": 0.014,
        },
        description="24/7 near-flat, daytime HVAC uplift, modest weekend dip.",
    ),
    "port_logistics_electrified": Typology(
        key="port_logistics_electrified",
        name="Port / shore-power / electric logistics",
        sic_codes=["52220", "50200", "52240"],
        load_factor=0.45,
        weekday_weekend_ratio=1.25,
        weather_sensitivity=0.004,
        hh_profile=_bell(peak_hh=24, width=10, amplitude=0.60, base=0.30),
        ev_uplift_frac=0.25,
        base_growth_pa=0.055,
        pathway_growth={
            "leading_the_way": 0.11, "consumer_transformation": 0.08,
            "system_transformation": 0.09, "falling_short": 0.025, "central": 0.055,
        },
        description="Shore-power + electric cranes/trucks. Fast-growing decarb pathway.",
    ),
}


DEFAULT_TYPOLOGY_KEY = "commercial_office"


def get_typology(key_or_sic: str) -> Typology:
    """Fetch typology by slug or SIC code. Falls back to commercial_office."""
    if not key_or_sic:
        return SIC_TYPOLOGIES[DEFAULT_TYPOLOGY_KEY]
    k = key_or_sic.strip().lower()
    if k in SIC_TYPOLOGIES:
        return SIC_TYPOLOGIES[k]
    for typ in SIC_TYPOLOGIES.values():
        if k in (c.lower() for c in typ.sic_codes):
            return typ
    # partial match
    for typ in SIC_TYPOLOGIES.values():
        if k in typ.key or k in typ.name.lower():
            return typ
    return SIC_TYPOLOGIES[DEFAULT_TYPOLOGY_KEY]


def list_typologies() -> list[dict[str, Any]]:
    """Serialisable list for the /typologies endpoint."""
    return [
        {
            "key": t.key,
            "name": t.name,
            "sic_codes": t.sic_codes,
            "load_factor": t.load_factor,
            "weekday_weekend_ratio": t.weekday_weekend_ratio,
            "weather_sensitivity_pct_per_degC": round(t.weather_sensitivity * 100, 2),
            "ev_uplift_frac": t.ev_uplift_frac,
            "hp_uplift_frac": t.hp_uplift_frac,
            "base_growth_pa": t.base_growth_pa,
            "pathway_growth": t.pathway_growth,
            "description": t.description,
        }
        for t in SIC_TYPOLOGIES.values()
    ]


def gross_profile(
    typ: Typology,
    peak_mw: float,
    interval_min: int,
    steps: int,
    start_hh_offset: int = 0,
    weekday_factor: float = 1.0,
) -> list[float]:
    """Generate a multi-step gross load curve in MW.

    - typ: typology
    - peak_mw: installed peak demand (MW)
    - interval_min: step size (min)
    - steps: number of timesteps
    - start_hh_offset: HH index (0..47) of first step
    - weekday_factor: 1.0 weekday, <1.0 for weekend scaling
    """
    profile = typ.profile_for_interval(interval_min)
    slots_per_day = len(profile)
    out = []
    for i in range(steps):
        slot = (start_hh_offset + i) % slots_per_day
        mult = profile[slot] * weekday_factor
        out.append(round(peak_mw * mult, 3))
    return out
