"""Multi-Country Expansion Framework — country-specific adapters."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CountryAdapter:
    """Base adapter for country-specific data and parameters."""
    code: str
    name: str
    srid: int
    currency: str
    currency_symbol: str
    voltage_levels: list[float] = field(default_factory=list)
    statutory_voltage_limits: dict = field(default_factory=dict)
    electricity_price_avg: float = 80  # per MWh
    discount_rate: float = 0.08
    tax_rate: float = 0.25
    grid_connection_costs: dict = field(default_factory=dict)
    grid_data_sources: list[dict] = field(default_factory=list)
    planning_constraints: list[str] = field(default_factory=list)

    def get_cost_assumptions(self) -> dict:
        return {
            "solar_per_mw": 500_000, "wind_per_mw": 1_200_000,
            "bess_per_mwh": 250_000, "gas_per_mw": 400_000,
            "currency": self.currency,
        }

    def get_climate_zone(self, lat: float, lon: float) -> str:
        return "4A"  # Default marine


class UKAdapter(CountryAdapter):
    def __init__(self):
        super().__init__(
            code="GB", name="United Kingdom", srid=27700,
            currency="GBP", currency_symbol="£",
            voltage_levels=[11, 33, 66, 132, 275, 400],
            statutory_voltage_limits={
                11: (0.94, 1.06), 33: (0.94, 1.06), 66: (0.95, 1.05),
                132: (0.95, 1.05), 275: (0.95, 1.05), 400: (0.95, 1.05),
            },
            electricity_price_avg=85, discount_rate=0.08, tax_rate=0.25,
            grid_connection_costs={"11kv_per_km": 80_000, "33kv_per_km": 150_000, "132kv_per_km": 500_000},
            grid_data_sources=[
                {"dno": "UKPN", "type": "ods", "region": "South East"},
                {"dno": "SSEN", "type": "ckan", "region": "Southern / North Scotland"},
                {"dno": "NGED", "type": "ckan", "region": "South West / Midlands"},
                {"dno": "SPEN", "type": "ods", "region": "Central / South Scotland"},
                {"dno": "NPG", "type": "ods", "region": "North East / Yorkshire"},
                {"dno": "ENWL", "type": "ods", "region": "North West"},
            ],
            planning_constraints=["flood_zone", "sssi", "sac", "spa", "ramsar", "listed_building",
                                  "scheduled_monument", "aonb", "green_belt", "alc_grade", "ancient_woodland"],
        )

    def get_climate_zone(self, lat, lon):
        return "4A"  # Marine (most of UK)


class IrelandAdapter(CountryAdapter):
    def __init__(self):
        super().__init__(
            code="IE", name="Ireland", srid=2157,  # ITM
            currency="EUR", currency_symbol="€",
            voltage_levels=[10, 20, 38, 110, 220, 400],
            statutory_voltage_limits={
                10: (0.94, 1.06), 20: (0.94, 1.06), 38: (0.95, 1.05),
                110: (0.95, 1.05), 220: (0.95, 1.05), 400: (0.95, 1.05),
            },
            electricity_price_avg=95, discount_rate=0.07, tax_rate=0.125,
            grid_connection_costs={"20kv_per_km": 90_000, "38kv_per_km": 170_000, "110kv_per_km": 550_000},
            grid_data_sources=[{"operator": "ESB Networks", "type": "esb"}, {"operator": "EirGrid", "type": "eirgrid"}],
            planning_constraints=["flood_zone", "nha", "sac", "spa", "pnha", "architectural_conservation"],
        )

    def get_cost_assumptions(self):
        base = super().get_cost_assumptions()
        base.update({"solar_per_mw": 550_000, "wind_per_mw": 1_100_000})
        return base


class NetherlandsAdapter(CountryAdapter):
    def __init__(self):
        super().__init__(
            code="NL", name="Netherlands", srid=28992,  # RD New
            currency="EUR", currency_symbol="€",
            voltage_levels=[10, 20, 50, 110, 150, 380],
            statutory_voltage_limits={
                10: (0.94, 1.06), 20: (0.94, 1.06), 50: (0.95, 1.05),
                110: (0.95, 1.05), 150: (0.95, 1.05), 380: (0.95, 1.05),
            },
            electricity_price_avg=80, discount_rate=0.06, tax_rate=0.258,
            grid_connection_costs={"20kv_per_km": 100_000, "50kv_per_km": 200_000, "150kv_per_km": 600_000},
            grid_data_sources=[{"operator": "TenneT", "type": "tennet"}, {"operator": "Stedin", "type": "dso"}, {"operator": "Liander", "type": "dso"}],
            planning_constraints=["flood_zone", "natura2000", "noise_contour", "landscape_protection"],
        )


class GermanyAdapter(CountryAdapter):
    def __init__(self):
        super().__init__(
            code="DE", name="Germany", srid=25832,  # ETRS89 UTM 32N
            currency="EUR", currency_symbol="€",
            voltage_levels=[10, 20, 110, 220, 380],
            statutory_voltage_limits={
                10: (0.94, 1.06), 20: (0.94, 1.06),
                110: (0.95, 1.05), 220: (0.95, 1.05), 380: (0.95, 1.05),
            },
            electricity_price_avg=75, discount_rate=0.06, tax_rate=0.30,
            grid_connection_costs={"20kv_per_km": 95_000, "110kv_per_km": 400_000, "380kv_per_km": 1_200_000},
            grid_data_sources=[
                {"operator": "50Hertz", "type": "tso"}, {"operator": "Amprion", "type": "tso"},
                {"operator": "TenneT DE", "type": "tso"}, {"operator": "TransnetBW", "type": "tso"},
            ],
            planning_constraints=["flood_zone", "natura2000", "landscape_protection", "noise_immission", "bimschg"],
        )


# ── Registry ──────────────────────────────────────────────────────────────

ADAPTERS: dict[str, CountryAdapter] = {
    "GB": UKAdapter(),
    "IE": IrelandAdapter(),
    "NL": NetherlandsAdapter(),
    "DE": GermanyAdapter(),
}


def get_adapter(country_code: str) -> CountryAdapter:
    """Get adapter by ISO country code."""
    return ADAPTERS.get(country_code.upper(), ADAPTERS["GB"])


def detect_country(lat: float, lon: float) -> str:
    """Detect country from coordinates (simple bounding box)."""
    if 49.5 < lat < 61.0 and -8.5 < lon < 2.0:
        if lat > 54.5 and lon < -5.5: return "IE"
        if lat < 53.5 and lon < -6.0: return "IE"
        return "GB"
    if 50.5 < lat < 54.0 and 3.0 < lon < 7.5: return "NL"
    if 47.0 < lat < 55.5 and 5.5 < lon < 15.5: return "DE"
    return "GB"  # Default


def list_countries() -> list[dict]:
    """List all supported countries."""
    return [
        {"code": a.code, "name": a.name, "currency": a.currency, "srid": a.srid,
         "voltage_levels": a.voltage_levels, "electricity_price_avg": a.electricity_price_avg}
        for a in ADAPTERS.values()
    ]
