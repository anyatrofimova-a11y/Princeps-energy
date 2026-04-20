"""Engineering primitives router — /api/engineering/*.

Thin wrappers over the pure-Python util modules:
  - utils.electrical_design (cable sizing, G99, reactive power, harmonics)
  - utils.bess_thermal
  - utils.dc_heat_rejection
  - utils.noise_propagation (top-level propagate_noise)
  - utils.glint_glare
  - utils.civil_earthworks
  - utils.lcoe

Each endpoint POSTs a pydantic request model, calls the util, returns the
dataclass dict (inputs_echo / outputs / assumptions / provenance / warnings).
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.electrical_design import (
    size_ac_cable,
    g99_screen,
    reactive_power_requirement,
    estimate_harmonic_distortion,
)
from utils.bess_thermal import (
    cell_thermal,
    cycle_life,
    augmentation_plan,
    nfpa_855_safety_zones,
)
from utils.dc_heat_rejection import heat_rejection
from utils.noise_propagation import propagate_noise
from utils.glint_glare import screen_glint_glare
from utils.civil_earthworks import estimate_earthworks, access_road_check
from utils.lcoe import compute_lcoe


router = APIRouter(prefix="/api/engineering", tags=["engineering-primitives"])


# ---------------------------------------------------------------------------
# CABLE SIZING + G99 SCREEN + REACTIVE + HARMONICS
# ---------------------------------------------------------------------------
class CableSizingRequest(BaseModel):
    mw: float = Field(..., gt=0)
    voltage_kv: float = Field(..., description="0.415, 11, 33, or 132")
    length_km: float = Field(..., ge=0)
    ambient_temp_c: float = 20.0
    install_method: Literal["direct_buried", "in_duct", "in_air", "in_trough"] = "direct_buried"
    power_factor: float = Field(0.95, gt=0, le=1)
    max_voltage_drop_pct: float = Field(5.0, gt=0, le=10)
    # G99 screen
    run_g99_screen: bool = True
    poc_fault_level_mva: float = 500.0
    # Harmonics
    run_harmonic_screen: bool = True
    inverter_thd_pct: float = 3.0
    n_inverters: int = 1
    filter_attenuation_pct: float = 0.0


@router.post("/cable-sizing")
def cable_sizing(req: CableSizingRequest):
    try:
        # Convert fractional voltages where the internal table uses float keys
        # (AC_CABLE_TABLE now supports 0.415 directly)
        voltage = req.voltage_kv
        if voltage == int(voltage) and voltage > 1:
            voltage = int(voltage)
        cable = size_ac_cable(
            mw=req.mw, voltage_kv=voltage, length_km=req.length_km,
            ambient_temp_c=req.ambient_temp_c,
            install_method=req.install_method,
            power_factor=req.power_factor,
            max_voltage_drop_pct=req.max_voltage_drop_pct,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    payload = {
        "inputs_echo": req.model_dump(),
        "outputs": {"cable": cable.to_dict()},
        "assumptions": [
            "BS 7671 installation-method + temperature derating",
            "IEC 60287 losses model (AC resistance only, XLPE Cu)",
        ],
        "provenance": "BS 7671:2018+A2:2022 / IEC 60287 / IEC 60364",
        "warnings": [],
    }

    if req.run_g99_screen and voltage in (11, 33, 132):
        try:
            g99 = g99_screen(
                mw=req.mw, voltage_kv=int(voltage),
                poc_fault_level_mva=req.poc_fault_level_mva,
            )
            payload["outputs"]["g99_screen"] = g99.to_dict()
        except ValueError as e:
            payload["warnings"].append(f"g99_screen skipped: {e}")

    if req.run_harmonic_screen:
        try:
            har = estimate_harmonic_distortion(
                mw=req.mw, voltage_kv=voltage,
                inverter_thd_pct=req.inverter_thd_pct,
                n_inverters=req.n_inverters,
                short_circuit_mva=req.poc_fault_level_mva,
                filter_attenuation_pct=req.filter_attenuation_pct,
            )
            payload["outputs"]["harmonics"] = har.to_dict()
            payload["warnings"].extend(har.warnings)
        except ValueError as e:
            payload["warnings"].append(f"harmonics skipped: {e}")

    if req.run_g99_screen and voltage in (11, 33, 132):
        payload["outputs"]["reactive_mvar_at_0p95"] = round(
            reactive_power_requirement(req.mw, pf_target=0.95, operating_pf=1.0), 3
        )

    return payload


# ---------------------------------------------------------------------------
# BESS THERMAL
# ---------------------------------------------------------------------------
class BESSThermalRequest(BaseModel):
    nameplate_mwh: float = Field(..., gt=0)
    chemistry: Literal["LFP", "NMC"] = "LFP"
    ambient_c: float = 15.0
    avg_cell_temp_c: float = 25.0
    c_rate: float = 0.5
    avg_dod_pct: float = 80.0
    cycles_per_day: float = 1.0
    cooling: Literal["passive", "forced_air", "liquid"] = "forced_air"
    hold_years: int = 15
    enclosure_kwh: float = 500.0
    n_enclosures: int = 10
    near_residential: bool = False
    near_ignition_source: bool = False


@router.post("/bess-thermal")
def bess_thermal(req: BESSThermalRequest):
    try:
        thermal = cell_thermal(
            ambient_c=req.ambient_c, c_rate=req.c_rate,
            cycles_per_day=req.cycles_per_day,
            cooling=req.cooling, chemistry=req.chemistry,
        )
        life = cycle_life(
            chemistry=req.chemistry, avg_temp_c=req.avg_cell_temp_c,
            avg_dod_pct=req.avg_dod_pct, cycles_per_day=req.cycles_per_day,
            years=req.hold_years,
        )
        plan = augmentation_plan(
            nameplate_mwh=req.nameplate_mwh, chemistry=req.chemistry,
            avg_temp_c=req.avg_cell_temp_c,
            avg_dod_pct=req.avg_dod_pct,
            cycles_per_day=req.cycles_per_day,
            hold_years=req.hold_years,
        )
        zones = nfpa_855_safety_zones(
            enclosure_kwh=req.enclosure_kwh,
            chemistry=req.chemistry,
            n_enclosures=req.n_enclosures,
            near_residential=req.near_residential,
            near_ignition_source=req.near_ignition_source,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    all_warnings = []
    for r in (thermal, life, plan, zones):
        all_warnings.extend(r.warnings)

    return {
        "inputs_echo": req.model_dump(),
        "outputs": {
            "cell_thermal": thermal.to_dict(),
            "cycle_life": life.to_dict(),
            "augmentation_plan": plan.to_dict(),
            "nfpa_855_zones": zones.to_dict(),
        },
        "assumptions": sorted({a for r in (thermal, life, plan, zones) for a in r.assumptions}),
        "provenance": "NFPA 855:2023; IEC 62933-5-2; Wang 2014; Arrhenius",
        "warnings": all_warnings,
    }


# ---------------------------------------------------------------------------
# DC HEAT REJECTION
# ---------------------------------------------------------------------------
class DCHeatRequest(BaseModel):
    it_load_mw: float = Field(..., gt=0)
    cooling: Literal["air", "water", "adiabatic", "immersion"] = "adiabatic"
    ambient_c: float = 15.0
    location: Literal["UK", "IE", "NL", "other"] = "UK"
    grid_gco2_per_kwh: Optional[float] = None
    hours_per_year: int = 8760


@router.post("/dc-heat-rejection")
def dc_heat_rejection(req: DCHeatRequest):
    try:
        r = heat_rejection(
            it_load_mw=req.it_load_mw, cooling=req.cooling,
            ambient_c=req.ambient_c, location=req.location,
            grid_gco2_per_kwh=req.grid_gco2_per_kwh,
            hours_per_year=req.hours_per_year,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return r.to_dict()


# ---------------------------------------------------------------------------
# NOISE PROPAGATION
# ---------------------------------------------------------------------------
class NoiseRequest(BaseModel):
    source_lwa_dba: float = Field(..., description="Source sound power level dB(A)")
    distance_m: float = Field(..., gt=0)
    source_height_m: float = 2.0
    receiver_height_m: float = 1.5
    ground: Literal["soft", "mixed", "hard"] = "soft"
    barrier_attenuation_db: float = 0.0
    atmospheric_coeff_db_per_km: float = 3.7
    compliance_limit_dba: float = 35.0
    tonal: bool = False


@router.post("/noise")
def noise(req: NoiseRequest):
    try:
        r = propagate_noise(
            source_lwa_dba=req.source_lwa_dba,
            distance_m=req.distance_m,
            source_height_m=req.source_height_m,
            receiver_height_m=req.receiver_height_m,
            ground=req.ground,
            barrier_attenuation_db=req.barrier_attenuation_db,
            atmospheric_coeff_db_per_km=req.atmospheric_coeff_db_per_km,
            compliance_limit_dba=req.compliance_limit_dba,
            tonal=req.tonal,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return r.to_dict()


# ---------------------------------------------------------------------------
# GLINT / GLARE
# ---------------------------------------------------------------------------
class GlareRequest(BaseModel):
    panel_lat: float
    panel_lon: float
    panel_tilt_deg: float = 35.0
    panel_azimuth_deg: float = 180.0
    receptor_lat: float
    receptor_lon: float
    panel_height_m: float = 2.5
    receptor_height_m: float = 1.7
    panel_area_m2: float = 10.0
    module_reflectance: float = 0.02
    sample_days: int = 12
    beam_half_angle_deg: float = 2.5


@router.post("/glint-glare")
def glint_glare(req: GlareRequest):
    try:
        r = screen_glint_glare(
            panel_lat=req.panel_lat, panel_lon=req.panel_lon,
            panel_tilt_deg=req.panel_tilt_deg,
            panel_azimuth_deg=req.panel_azimuth_deg,
            receptor_lat=req.receptor_lat,
            receptor_lon=req.receptor_lon,
            panel_height_m=req.panel_height_m,
            receptor_height_m=req.receptor_height_m,
            panel_area_m2=req.panel_area_m2,
            module_reflectance=req.module_reflectance,
            sample_days=req.sample_days,
            beam_half_angle_deg=req.beam_half_angle_deg,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return r.to_dict()


# ---------------------------------------------------------------------------
# EARTHWORKS
# ---------------------------------------------------------------------------
class EarthworksRequest(BaseModel):
    area_m2: float = Field(..., gt=0)
    mean_slope_pct: float = 3.0
    slope_std_pct: float = 1.5
    platform_target: Literal["level", "graded"] = "level"
    dtm: Optional[list[list[float]]] = None
    target_grade_m: Optional[list[list[float]]] = None
    cell_size_m: float = 5.0
    # Optional access-road check
    run_access_road: bool = False
    access_start_elev_m: float = 0.0
    access_end_elev_m: float = 0.0
    access_length_m: float = 100.0
    vehicle_class: Literal["HGV", "car", "emergency"] = "HGV"


@router.post("/earthworks")
def earthworks(req: EarthworksRequest):
    try:
        r = estimate_earthworks(
            area_m2=req.area_m2,
            mean_slope_pct=req.mean_slope_pct,
            slope_std_pct=req.slope_std_pct,
            platform_target=req.platform_target,
            dtm=req.dtm,
            target_grade_m=req.target_grade_m,
            cell_size_m=req.cell_size_m,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    payload = r.to_dict()
    if req.run_access_road:
        try:
            road = access_road_check(
                start_elev_m=req.access_start_elev_m,
                end_elev_m=req.access_end_elev_m,
                road_length_m=req.access_length_m,
                vehicle_class=req.vehicle_class,
            )
            payload["outputs"]["access_road"] = road.to_dict()
            payload["warnings"].extend(road.warnings)
        except ValueError as e:
            payload["warnings"].append(f"access_road_check skipped: {e}")
    return payload


# ---------------------------------------------------------------------------
# LCOE
# ---------------------------------------------------------------------------
class LCOERequest(BaseModel):
    capex_gbp: float = Field(..., ge=0)
    opex_schedule_gbp: list[float]
    annual_generation_mwh: float = Field(..., gt=0)
    discount_rate: float = Field(0.08, gt=-0.2, lt=1.0)
    lifetime_years: int = Field(..., gt=0)
    capex_schedule_gbp: Optional[list[float]] = None
    degradation_pct_per_yr: float = 0.5
    residual_value_gbp: float = 0.0


@router.post("/lcoe")
def lcoe(req: LCOERequest):
    try:
        r = compute_lcoe(
            capex_gbp=req.capex_gbp,
            opex_schedule_gbp=req.opex_schedule_gbp,
            annual_generation_mwh=req.annual_generation_mwh,
            discount_rate=req.discount_rate,
            lifetime_years=req.lifetime_years,
            capex_schedule_gbp=req.capex_schedule_gbp,
            degradation_pct_per_yr=req.degradation_pct_per_yr,
            residual_value_gbp=req.residual_value_gbp,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return r.to_dict()
