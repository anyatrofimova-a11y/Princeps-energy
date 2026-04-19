/**
 * Demo data fixtures for pitch deck — realistic UK solar site.
 * Site: Greenfield near Bicester, Oxfordshire (51.88N, 1.16W)
 * Capacity: 5 MW ground-mount solar
 */

export const DEMO_PARCEL_ID = "BICESTER-DEMO-5MW";

export const DEMO_LOCATION = { lat: 51.88, lon: -1.16 };

export const DEMO_EXPLAIN = {
  parcel_id: "BICESTER-DEMO-5MW",
  lat: 51.88,
  lon: -1.16,
  location_name: "Greenfield Site, Bicester, Oxfordshire",
  area_ha: 12.4,
  score_total: 98,
  score: { total: 98 },
  explanation: "Strong solar site on Grade 3b agricultural land with excellent grid proximity and no major environmental constraints.",
  context: {
    score_components: {
      resource: 27,
      grid: 24,
      planning: 23,
      environment: 24,
    },
  },
};

export const DEMO_SOLAR_YIELD = {
  annual_energy_kwh: 5475000,       // 5MW * 10.95% CF
  capacity_factor_pct: 10.95,
  monthly_energy_kwh: [
    215000, 285000, 425000, 540000, 610000, 630000,
    625000, 570000, 450000, 325000, 220000, 180000,
  ],
  peak_sun_hours: 3.8,
  inverter_clipping: 0.8,
  system_losses_pct: 14.2,
};

export const DEMO_GRID_CONTEXT = {
  nearest_substation: {
    name: "Bicester 33kV Primary",
    distance_km: 1.8,
    voltage_kv: 33,
    headroom_mw: 12.5,
  },
  demand: {
    daily_avg: 42.6,
    peak_demand: 78.3,
    peak_hour: 18,
    hourly_demand_mw: [
      23, 21, 20, 19, 20, 25, 35, 48, 55, 52,
      50, 49, 48, 47, 48, 52, 60, 72, 78, 68,
      55, 42, 32, 26,
    ],
  },
  solar_generation: {
    hourly: {
      avg_solar_mw: [
        0, 0, 0, 0, 0, 0.2, 0.8, 1.5, 2.5, 3.2,
        3.8, 4.1, 4.3, 4.2, 3.9, 3.2, 2.4, 1.2, 0.3, 0, 0, 0, 0, 0,
      ],
    },
  },
  curtailment: {
    avg_risk: 0.08,
    peak_risk: 0.32,
    peak_risk_hour: 13,
    hourly_risk: [
      0, 0, 0, 0, 0, 0, 0.02, 0.06, 0.12, 0.18,
      0.25, 0.30, 0.32, 0.28, 0.22, 0.15, 0.08, 0.02, 0, 0, 0, 0, 0, 0,
    ],
  },
  weather: { temp_avg: 10.8, cloud_cover: 58, solar_radiation: 1045 },
};

export const DEMO_AGENT_RESULT = {
  verdict: "GO",
  confidence: 0.87,
  intent: "feasibility",
  summary: "Site demonstrates strong feasibility across all 9 assessment domains. Grade 3b agricultural land with 12.5 MW grid headroom at Bicester 33kV, 1.8km distant. No SSSI, SAC or flood zone constraints. Estimated 5,475 MWh/yr at 10.95% capacity factor. Recommend proceeding to detailed grid study and pre-planning assessment.",
  risks: [
    "Cumulative landscape impact — 2 operational solar farms within 5km radius",
    "Agricultural Land Classification at Grade 3b boundary — verify with detailed soil survey",
    "G99 application required for 5MW capacity (>50kW threshold)",
  ],
  opportunities: [
    "12.5 MW headroom available — potential for capacity expansion to 10MW",
    "South-facing aspect with <3 degree slope — optimal panel orientation",
    "No heritage assets or listed buildings within 500m buffer",
    "Local planning authority has 85% solar approval rate (last 5 years)",
  ],
  next_steps: [
    "Commission detailed grid study with SSEN",
    "Submit pre-planning enquiry to Cherwell District Council",
    "Obtain ALC soil survey to confirm Grade 3b classification",
    "Engage ecology consultant for BNG baseline assessment",
  ],
  domains: {
    dno_infrastructure: { score: 85, status: "GO", detail: "33kV connection, 12.5MW headroom, 1.8km cable route" },
    topography: { score: 92, status: "GO", detail: "Mean slope 2.8 deg, south-facing, elevation 85-92m AOD" },
    solar_resource: { score: 78, status: "GO", detail: "1,045 kWh/m2 GHI, 10.95% CF, moderate cloud cover" },
    agricultural_land: { score: 70, status: "CAUTION", detail: "Grade 3b — not BMV, but borderline" },
    administrative: { score: 88, status: "GO", detail: "Cherwell District, SSEN licence area" },
    neighbouring_projects: { score: 65, status: "CAUTION", detail: "2 solar farms within 5km, cumulative impact review needed" },
    flood_zones: { score: 95, status: "GO", detail: "Flood Zone 1, no surface water risk, JRC occurrence <1%" },
    protected_areas: { score: 98, status: "GO", detail: "No SSSI, SAC, SPA, AONB, National Park constraints" },
    vision_ai: { score: 90, status: "GO", detail: "Flat terrain, no significant shading, clear access routes" },
  },
};

export const DEMO_GEEFLOW_DATA = {
  extractions: {
    land_use: {
      class_percentages: {
        grass: 62,
        crops: 18,
        built: 8,
        trees: 7,
        shrub_and_scrub: 3,
        bare: 1,
        water: 0.5,
        flooded_vegetation: 0.3,
        snow_and_ice: 0.2,
      },
      dominant_class: "grass",
      developable_pct: 80,
    },
    terrain: {
      elevation: { mean_m: 88, min_m: 82, max_m: 96 },
      slope: { mean_deg: 2.8, p90_deg: 5.1, max_deg: 8.3 },
      aspect: { south_facing_pct: 72, dominant_direction: "SSW" },
      roughness: { mean: 0.15 },
    },
    solar_resource: {
      annual_ghi_kwh_m2: 1045,
      monthly: [
        { month: 1, ghi_kwh_m2_day: 0.8, temperature_c: 4.2 },
        { month: 2, ghi_kwh_m2_day: 1.4, temperature_c: 4.8 },
        { month: 3, ghi_kwh_m2_day: 2.5, temperature_c: 7.1 },
        { month: 4, ghi_kwh_m2_day: 3.8, temperature_c: 9.5 },
        { month: 5, ghi_kwh_m2_day: 4.6, temperature_c: 12.8 },
        { month: 6, ghi_kwh_m2_day: 5.1, temperature_c: 15.9 },
        { month: 7, ghi_kwh_m2_day: 4.9, temperature_c: 17.8 },
        { month: 8, ghi_kwh_m2_day: 4.2, temperature_c: 17.3 },
        { month: 9, ghi_kwh_m2_day: 3.1, temperature_c: 14.6 },
        { month: 10, ghi_kwh_m2_day: 1.8, temperature_c: 10.9 },
        { month: 11, ghi_kwh_m2_day: 1.0, temperature_c: 7.2 },
        { month: 12, ghi_kwh_m2_day: 0.6, temperature_c: 4.9 },
      ],
    },
    vegetation: {
      green_cover_pct: 69,
      annual_ndvi_mean: 0.58,
    },
    flood_risk: {
      risk_level: "LOW",
      water_occurrence_pct: 0.8,
      seasonality_months_mean: 2,
      environmental_constraint: false,
    },
    sar_backscatter: {
      mean_vv_db: -12.4,
      mean_vh_db: -18.7,
      soil_moisture_indicator: "moderate",
    },
    ndvi_timeseries: {
      trend: "stable",
      seasonal_amplitude: 0.32,
    },
  },
  site_score: {
    total_score: 82,
    max_score: 100,
    recommendation: "GO",
    components: {
      resource: 85, terrain: 92, land_use: 78,
      grid: 80, planning: 75,
    },
    summary: "Excellent suitability — flat grassland with strong solar resource and grid proximity.",
  },
};

export const DEMO_ENERGY_PRICE = {
  export_rate_p: 5.5,
  import_rate_p: 28.6,
  agile_current_p: 12.3,
};

export const DEMO_DEFERRAL = {
  allocations: [
    { asset: "Bicester 33kV Tx", deferral_value_gbp: 450000, years: 3 },
    { asset: "Launton 11kV feeder", deferral_value_gbp: 120000, years: 5 },
  ],
};

export const DEMO_SLOPE_STATS = {
  mean_slope_deg: 2.8,
  max_slope_deg: 8.3,
  p90_slope_deg: 5.1,
  south_facing_pct: 72,
};

export const DEMO_SOLAR_HOURLY = {
  hourly_kw: [0,0,0,0,0,0.5,12,38,72,95,112,118,120,116,108,88,62,28,5,0,0,0,0,0],
  daily_total_kwh: 994,
};

export const DEMO_HEIGHTMAP = {
  min_elevation: 82,
  max_elevation: 96,
  mean_elevation: 88,
};

/**
 * Inject all demo data into SiteContext setters.
 * Call from PitchPage useEffect on mount.
 */
export function injectDemoData(ctx) {
  ctx.setParcelId(DEMO_PARCEL_ID);
  ctx.setPickedLocation(DEMO_LOCATION);
  ctx.setAgentResult(DEMO_AGENT_RESULT);

  // These setters are exposed on the context value object
  if (ctx.setSolarYield) ctx.setSolarYield(DEMO_SOLAR_YIELD);
  if (ctx.setGridContext) ctx.setGridContext(DEMO_GRID_CONTEXT);
  if (ctx.setExplain) ctx.setExplain(DEMO_EXPLAIN);
  if (ctx.setGeeflowData) ctx.setGeeflowData(DEMO_GEEFLOW_DATA);
  if (ctx.setEnergyPrice) ctx.setEnergyPrice(DEMO_ENERGY_PRICE);
  if (ctx.setDeferral) ctx.setDeferral(DEMO_DEFERRAL);
  if (ctx.setSlopeStats) ctx.setSlopeStats(DEMO_SLOPE_STATS);
  if (ctx.setSolarHourly) ctx.setSolarHourly(DEMO_SOLAR_HOURLY);
  if (ctx.setHeightmap) ctx.setHeightmap(DEMO_HEIGHTMAP);
  if (ctx.setWorkflowStage) ctx.setWorkflowStage("study");
  if (ctx.setActiveIntent) ctx.setActiveIntent("feasibility");
  if (ctx.setAnalyticsCollapsed) ctx.setAnalyticsCollapsed(false);
}
