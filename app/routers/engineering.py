"""Engineering-primitives HTTP router.

Exposes the UK-standards engineering calculations (BS 7671, IEC 60364/62548,
ENA G99, ISO 9613-2, FAA SGHAT, UK PPG 2014, National Grid GRIP) implemented
in the `utils.electrical_design`, `utils.environmental_modelling` and
`utils.construction_schedule` modules.

All endpoints are POST /api/v1/engineering/*, returning JSON-serialisable
pydantic models that round-trip cleanly.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.electrical_design import (
    size_ac_cable,
    size_dc_string,
    g99_screen,
    reactive_power_requirement,
)
from utils.environmental_modelling import (
    glare_assessment,
    shadow_flicker,
    noise_propagation_iso9613_2,
)
from utils.construction_schedule import build_schedule


router = APIRouter(prefix="/api/v1/engineering", tags=["engineering"])


# ---------------------------------------------------------------------------
# CABLE SIZING
# ---------------------------------------------------------------------------
class CableRequest(BaseModel):
    mw: float = Field(..., gt=0, description="Design power rating (MW)")
    voltage_kv: int = Field(..., description="System voltage: 11, 33 or 132")
    length_km: float = Field(..., ge=0, description="Cable run length (km)")
    ambient_temp_c: float = Field(20.0, description="Ambient ground/air temperature (°C)")
    install_method: Literal["direct_buried", "in_duct", "in_air", "in_trough"] = "direct_buried"
    power_factor: float = Field(0.95, gt=0, le=1)
    max_voltage_drop_pct: float = Field(5.0, gt=0, le=10)


class CableResponse(BaseModel):
    conductor_size_mm2: int
    voltage_kv: int
    length_km: float
    current_a: float
    ampacity_a: float
    voltage_drop_pct: float
    losses_kw: float
    cost_per_km_gbp: float
    total_cost_gbp: float
    install_method: str
    ambient_c: float
    derating_factor: float
    standard: str


@router.post("/cable", response_model=CableResponse)
def size_cable(req: CableRequest) -> CableResponse:
    try:
        spec = size_ac_cable(
            mw=req.mw,
            voltage_kv=req.voltage_kv,
            length_km=req.length_km,
            ambient_temp_c=req.ambient_temp_c,
            install_method=req.install_method,
            power_factor=req.power_factor,
            max_voltage_drop_pct=req.max_voltage_drop_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return CableResponse(**spec.to_dict())


# ---------------------------------------------------------------------------
# DC STRING SIZING
# ---------------------------------------------------------------------------
class DCStringRequest(BaseModel):
    panel_voc: float = Field(..., gt=0)
    panel_isc: float = Field(..., gt=0)
    n_panels_series: int = Field(..., gt=0)
    n_strings: int = Field(..., gt=0)
    ambient_temp_c: float = 20.0
    temp_coeff_voc_pct_per_c: float = -0.28
    cold_cell_temp_c: float = -10.0


class DCStringResponse(BaseModel):
    string_voltage_v: float
    string_current_a: float
    recommended_cable_mm2: int
    combiner_rating_a: float
    string_voc_cold_v: float
    temp_coeff_pct_per_c: float
    standard: str


@router.post("/dc-string", response_model=DCStringResponse)
def size_dc(req: DCStringRequest) -> DCStringResponse:
    try:
        spec = size_dc_string(
            panel_voc=req.panel_voc,
            panel_isc=req.panel_isc,
            n_panels_series=req.n_panels_series,
            n_strings=req.n_strings,
            ambient_temp_c=req.ambient_temp_c,
            temp_coeff_voc_pct_per_c=req.temp_coeff_voc_pct_per_c,
            cold_cell_temp_c=req.cold_cell_temp_c,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return DCStringResponse(**spec.to_dict())


# ---------------------------------------------------------------------------
# G99 SCREENING
# ---------------------------------------------------------------------------
class G99Request(BaseModel):
    mw: float = Field(..., gt=0)
    voltage_kv: int = Field(..., gt=0)
    poc_fault_level_mva: float = Field(500.0, gt=0)


class G99Response(BaseModel):
    fault_contribution_ka: float
    voltage_step_change_pct: float
    application_route: str
    threshold_mw: float
    voltage_kv: int
    poc_fault_level_mva: float
    reactive_power_mvar: float
    flags: list[str]
    standard: str


@router.post("/g99", response_model=G99Response)
def screen_g99(req: G99Request) -> G99Response:
    try:
        result = g99_screen(
            mw=req.mw,
            voltage_kv=req.voltage_kv,
            poc_fault_level_mva=req.poc_fault_level_mva,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return G99Response(**result.to_dict())


# ---------------------------------------------------------------------------
# REACTIVE POWER
# ---------------------------------------------------------------------------
class ReactiveRequest(BaseModel):
    mw: float = Field(..., gt=0)
    pf_target: float = Field(0.95, gt=0, le=1)
    operating_pf: float = Field(1.0, gt=0, le=1)


class ReactiveResponse(BaseModel):
    mvar_required: float
    pf_target: float
    operating_pf: float


@router.post("/reactive", response_model=ReactiveResponse)
def reactive(req: ReactiveRequest) -> ReactiveResponse:
    try:
        q = reactive_power_requirement(req.mw, req.pf_target, req.operating_pf)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ReactiveResponse(
        mvar_required=round(q, 3),
        pf_target=req.pf_target,
        operating_pf=req.operating_pf,
    )


# ---------------------------------------------------------------------------
# GLARE
# ---------------------------------------------------------------------------
class Receptor(BaseModel):
    name: str
    lat: float
    lon: float


class GlareRequest(BaseModel):
    panel_lat: float
    panel_lon: float
    panel_tilt_deg: float = 35.0
    panel_azimuth_deg: float = 180.0
    receptors: list[Receptor]
    year: int
    sample_minutes: int = 15
    module_reflectance: float = 0.02


class GlareEventOut(BaseModel):
    date: str
    time_local: str
    duration_min: float
    intensity: str
    luminance_cd_m2: float
    receptor_name: str
    receptor_bearing_deg: float
    solar_altitude_deg: float


class GlareResponse(BaseModel):
    events: list[GlareEventOut]
    total_events: int
    high_intensity_count: int
    standard: str = "FAA SGHAT AC 150/5300-15B"


@router.post("/glare", response_model=GlareResponse)
def glare(req: GlareRequest) -> GlareResponse:
    receptors = [r.model_dump() for r in req.receptors]
    events = glare_assessment(
        panel_lat=req.panel_lat,
        panel_lon=req.panel_lon,
        panel_tilt_deg=req.panel_tilt_deg,
        panel_azimuth_deg=req.panel_azimuth_deg,
        receptors=receptors,
        year=req.year,
        sample_minutes=req.sample_minutes,
        module_reflectance=req.module_reflectance,
    )
    high = sum(1 for e in events if e.get("intensity") == "high")
    return GlareResponse(
        events=[GlareEventOut(**e) for e in events],
        total_events=len(events),
        high_intensity_count=high,
    )


# ---------------------------------------------------------------------------
# SHADOW FLICKER
# ---------------------------------------------------------------------------
class FlickerRequest(BaseModel):
    turbine_lat: float
    turbine_lon: float
    hub_height_m: float = Field(..., gt=0)
    rotor_diameter_m: float = Field(..., gt=0)
    receptors: list[Receptor]
    year: int
    sample_minutes: int = 15
    turbine_axis_az_deg: Optional[float] = None


class FlickerEventOut(BaseModel):
    receptor: str
    total_hours_per_year: float
    max_day_hours: float
    month_distribution: dict[str, float]
    exceeds_uk_threshold: bool
    standard: str


class FlickerResponse(BaseModel):
    events: list[FlickerEventOut]


@router.post("/flicker", response_model=FlickerResponse)
def flicker(req: FlickerRequest) -> FlickerResponse:
    receptors = [r.model_dump() for r in req.receptors]
    events = shadow_flicker(
        turbine_lat=req.turbine_lat,
        turbine_lon=req.turbine_lon,
        hub_height_m=req.hub_height_m,
        rotor_diameter_m=req.rotor_diameter_m,
        receptors=receptors,
        year=req.year,
        sample_minutes=req.sample_minutes,
        turbine_axis_az_deg=req.turbine_axis_az_deg,
    )
    return FlickerResponse(events=[FlickerEventOut(**e) for e in events])


# ---------------------------------------------------------------------------
# NOISE
# ---------------------------------------------------------------------------
class NoiseRequest(BaseModel):
    source_db: float = Field(..., description="Sound power level at source (dBA)")
    source_lat: float
    source_lon: float
    receptor_lat: float
    receptor_lon: float
    wind_direction_deg: float = 0.0
    ground_type: Literal["soft", "hard", "mixed"] = "soft"
    night_limit_dba: float = 45.0
    day_limit_dba: float = 55.0
    atmospheric_coeff_db_per_m: float = 0.003


class NoiseResponse(BaseModel):
    sound_pressure_dba: float
    distance_m: float
    a_div_db: float
    a_atm_db: float
    a_gr_db: float
    a_met_db: float
    night_limit_dba: float
    day_limit_dba: float
    exceeds_night: bool
    exceeds_day: bool
    ground_type: str
    standard: str


@router.post("/noise", response_model=NoiseResponse)
def noise(req: NoiseRequest) -> NoiseResponse:
    result = noise_propagation_iso9613_2(
        source_db=req.source_db,
        source_lat=req.source_lat,
        source_lon=req.source_lon,
        receptor_lat=req.receptor_lat,
        receptor_lon=req.receptor_lon,
        wind_direction_deg=req.wind_direction_deg,
        ground_type=req.ground_type,
        night_limit_dba=req.night_limit_dba,
        day_limit_dba=req.day_limit_dba,
        atmospheric_coeff_db_per_m=req.atmospheric_coeff_db_per_m,
    )
    return NoiseResponse(**result.to_dict())


# ---------------------------------------------------------------------------
# CONSTRUCTION SCHEDULE
# ---------------------------------------------------------------------------
class ScheduleRequest(BaseModel):
    project_type: Literal["solar", "bess", "dc", "wind_onshore"]
    mw: float = Field(..., gt=0)
    start_date: date
    site_complexity: Literal["low", "med", "high"] = "med"


class TaskOut(BaseModel):
    id: str
    name: str
    stage: int
    start: str
    end: str
    duration_days: int
    predecessors: list[str]
    early_start: int
    early_finish: int
    late_start: int
    late_finish: int
    float_days: int


class ScheduleResponse(BaseModel):
    project_type: str
    mw: float
    site_complexity: str
    start_date: str
    end_date: str
    total_duration_days: int
    critical_path: list[str]
    tasks: list[TaskOut]
    standard: str


@router.post("/schedule", response_model=ScheduleResponse)
def schedule(req: ScheduleRequest) -> ScheduleResponse:
    try:
        sch = build_schedule(
            project_type=req.project_type,
            mw=req.mw,
            start_date=req.start_date,
            site_complexity=req.site_complexity,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    payload = sch.to_dict()
    payload["tasks"] = [TaskOut(**t) for t in payload["tasks"]]
    return ScheduleResponse(**payload)
