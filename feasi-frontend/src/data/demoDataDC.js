/**
 * Demo data fixtures for Google DC pitch — Waltham Cross, Hertfordshire.
 * Site: Near Google's existing UK DC infrastructure
 * Capacity: 100 MW data centre with co-located solar + BESS
 * Grid: 132kV connection via Brimsdown substation
 */

export const DEMO_DC_PARCEL_ID = "WALTHAM-CROSS-DC-100MW";

export const DEMO_DC_LOCATION = { lat: 51.685, lon: -0.035 };

export const DEMO_DC_EXPLAIN = {
  parcel_id: "WALTHAM-CROSS-DC-100MW",
  lat: 51.685,
  lon: -0.035,
  location_name: "Waltham Cross, Hertfordshire",
  area_ha: 8.5,
  score_total: 78,
  score: { total: 78 },
  explanation: "Strong data centre site with 132kV grid proximity, existing DC cluster, and excellent fibre connectivity. Behind-the-meter solar+BESS co-location viable.",
  dno: "UKPN",
};

export const DEMO_DC_SOLAR_YIELD = {
  annual_energy_kwh: 52000000,    // 50MW co-located solar
  capacity_factor_pct: 11.8,
  monthly_energy_kwh: [
    2100000, 2800000, 4200000, 5400000, 6100000, 6300000,
    6200000, 5600000, 4400000, 3200000, 2200000, 1800000,
  ],
  peak_sun_hours: 3.6,
  system_losses_pct: 14.8,
};

export const DEMO_DC_GRID_CONTEXT = {
  nearest_substation: {
    name: "Brimsdown 132kV Grid",
    distance_km: 2.1,
    voltage_kv: 132,
    headroom_mw: 87,
  },
  demand: {
    daily_avg: 320,
    peak_demand: 485,
    peak_hour: 14,
    hourly_demand_mw: [
      280, 265, 258, 255, 260, 275, 310, 360, 400, 430,
      455, 470, 480, 485, 475, 460, 440, 420, 390, 360,
      340, 320, 300, 290,
    ],
  },
  connection_cost: {
    p10_gbp: 850000,
    p50_gbp: 1300000,
    p90_gbp: 2100000,
  },
};

export const DEMO_DC_AGENT_RESULT = {
  verdict: "GO",
  confidence: 0.82,
  intent: "dc_colocation",
  summary: "Site demonstrates strong suitability for 100MW hyperscale data centre. 87MW grid headroom at Brimsdown 132kV (2.1km), established DC cluster with Google precedent. 52% achievable CFE with co-located 50MW solar + 200MWh BESS. Water stress is moderate — hybrid cooling recommended. Planning pathway clear via NSIP route (>50MW).",
  risks: [
    "Green Belt proximity — requires Very Special Circumstances justification under NPPF",
    "Water stress in Lee Valley catchment — evaporative cooling may face EA objections",
    "Grid queue depth at Brimsdown — 8 applications ahead, estimated 18-month wait for connection offer",
    "Embodied carbon of GPU servers drives 97% of lifecycle CO₂ — requires robust offset strategy",
  ],
  opportunities: [
    "87MW grid headroom at 132kV — sufficient for full 100MW load with 50MW behind-the-meter solar offset",
    "Existing DC cluster (Google, Equinix, Kao Data) provides planning precedent and shared infrastructure",
    "Behind-the-meter BESS shifts demand to low-carbon periods — 15-25% carbon reduction achievable",
    "Enterprise Zone designation under consideration — potential 5-year business rates relief",
    "Dual-feed 132kV supply available via Waltham Cross + Enfield substations — N-1 resilient",
  ],
  next_steps: [
    "Submit NSIP pre-application to Planning Inspectorate (>50MW threshold)",
    "Engage UKPN for formal 132kV connection application via G99 route",
    "Commission water stress assessment with Environment Agency consultation",
    "Secure land option — 8.5ha required for DC hall + solar array + BESS compound",
  ],
  domains: {
    power_capacity: { score: 88, status: "GO", detail: "132kV dual-feed available, Brimsdown + Enfield" },
    grid_headroom: { score: 82, status: "GO", detail: "87MW headroom, 8 queue applications, ~18mo wait" },
    fibre_proximity: { score: 95, status: "GO", detail: "Dark fibre to Docklands IX, 0.8ms latency" },
    ixp_proximity: { score: 90, status: "GO", detail: "LINX at Harbour Exchange 25km, Equinix LD4 30km" },
    water_cooling: { score: 55, status: "CAUTION", detail: "Lee Navigation 1.2km, moderate stress catchment" },
    land_planning: { score: 65, status: "CAUTION", detail: "Green Belt edge, NSIP route, DC precedent exists" },
    resilience: { score: 85, status: "GO", detail: "Dual-feed 132kV, independent grid supply points" },
    cfe_potential: { score: 52, status: "CAUTION", detail: "52% achievable CFE with 50MW solar + 200MWh BESS" },
    cooling_climate: { score: 78, status: "GO", detail: "PUE 1.18 target, 3200 free cooling hours/yr" },
    constraint_clearance: { score: 88, status: "GO", detail: "No SSSI, SAC, SPA; Flood Zone 1" },
    water_stress: { score: 55, status: "CAUTION", detail: "Lee Valley serious water stress — hybrid cooling" },
    incentives: { score: 40, status: "CAUTION", detail: "No current Enterprise Zone; AI Growth Zone pending" },
    regulatory: { score: 75, status: "GO", detail: "NSIP eligible, 3 DC precedents in 5km radius" },
    connectivity: { score: 92, status: "GO", detail: "8 fibre providers, 3 dark fibre routes" },
    financial_tco: { score: 68, status: "CAUTION", detail: "£18M 10yr TCO, £1.3M grid connection P50" },
  },
};

export const DEMO_DC_GEEFLOW_DATA = {
  extractions: {
    land_use: {
      class_percentages: {
        built: 35,
        grass: 28,
        crops: 15,
        trees: 12,
        water: 5,
        bare: 3,
        shrub_and_scrub: 2,
      },
      dominant_class: "built",
      developable_pct: 70,
    },
    terrain: {
      elevation: { mean_m: 24, min_m: 18, max_m: 32 },
      slope: { mean_deg: 1.2, p90_deg: 2.8, max_deg: 4.5 },
      aspect: { south_facing_pct: 45, dominant_direction: "SE" },
      roughness: { mean: 0.25 },
    },
    solar_resource: {
      annual_ghi_kwh_m2: 1020,
      monthly: [
        { month: 1, ghi_kwh_m2_day: 0.7, temperature_c: 5.1 },
        { month: 2, ghi_kwh_m2_day: 1.3, temperature_c: 5.5 },
        { month: 3, ghi_kwh_m2_day: 2.4, temperature_c: 7.8 },
        { month: 4, ghi_kwh_m2_day: 3.7, temperature_c: 10.2 },
        { month: 5, ghi_kwh_m2_day: 4.5, temperature_c: 13.5 },
        { month: 6, ghi_kwh_m2_day: 5.0, temperature_c: 16.4 },
        { month: 7, ghi_kwh_m2_day: 4.8, temperature_c: 18.5 },
        { month: 8, ghi_kwh_m2_day: 4.1, temperature_c: 18.0 },
        { month: 9, ghi_kwh_m2_day: 3.0, temperature_c: 15.2 },
        { month: 10, ghi_kwh_m2_day: 1.7, temperature_c: 11.5 },
        { month: 11, ghi_kwh_m2_day: 0.9, temperature_c: 7.8 },
        { month: 12, ghi_kwh_m2_day: 0.6, temperature_c: 5.6 },
      ],
    },
    flood_risk: {
      risk_level: "LOW",
      water_occurrence_pct: 1.2,
      environmental_constraint: false,
    },
  },
  site_score: {
    total_score: 78,
    max_score: 100,
    recommendation: "GO",
    components: {
      resource: 72, terrain: 90, land_use: 70,
      grid: 85, planning: 65,
    },
    summary: "Strong DC suitability — flat terrain, 132kV proximity, established DC cluster.",
  },
};

export const DEMO_DC_ENERGY_PRICE = {
  export_rate_p: 5.5,
  import_rate_p: 28.6,
  agile_current_p: 14.8,
};

export const DEMO_DC_PLACED_ASSETS = [
  { id: "dc-1", assetType: "data_centre", label: "DC Hall A (100MW)", mw: 100, lat: 51.685, lon: -0.035, color: "#9333ea" },
  { id: "solar-1", assetType: "solar_array", label: "Solar Array (50MW)", mw: 50, lat: 51.6835, lon: -0.032, color: "#D4A018" },
  { id: "bess-1", assetType: "bess", label: "BESS (200MWh)", mw: 50, lat: 51.6865, lon: -0.032, color: "#16a34a" },
  { id: "sub-1", assetType: "substation", label: "132kV Substation", mw: 0, lat: 51.6855, lon: -0.038, color: "#78909c" },
  { id: "tx-1", assetType: "transformer", label: "Step-down TX", mw: 0, lat: 51.6845, lon: -0.036, color: "#0891b2" },
];

export const DEMO_DC_SIM_24H = {
  summary: {
    total_energy_mwh: 2190,
    total_carbon_tonnes: 394.2,
    total_water_m3: 850,
    avg_pue: 1.21,
    wue_l_per_kwh: 0.39,
    peak_power_kw: 121000,
    min_pue: 1.15,
    max_pue: 1.32,
    battery_final_soc_pct: 55,
    capacity_mw: 100,
  },
};

/**
 * Inject DC demo data into SiteContext for Google pitch.
 * Call from PitchPage when entering DC demo slides.
 */
export function injectDemoDCData(ctx) {
  ctx.setParcelId(DEMO_DC_PARCEL_ID);
  ctx.setPickedLocation(DEMO_DC_LOCATION);
  ctx.setAgentResult(DEMO_DC_AGENT_RESULT);

  if (ctx.setSolarYield) ctx.setSolarYield(DEMO_DC_SOLAR_YIELD);
  if (ctx.setGridContext) ctx.setGridContext(DEMO_DC_GRID_CONTEXT);
  if (ctx.setExplain) ctx.setExplain(DEMO_DC_EXPLAIN);
  if (ctx.setGeeflowData) ctx.setGeeflowData(DEMO_DC_GEEFLOW_DATA);
  if (ctx.setEnergyPrice) ctx.setEnergyPrice(DEMO_DC_ENERGY_PRICE);
  if (ctx.setWorkflowStage) ctx.setWorkflowStage("study");
  if (ctx.setActiveIntent) ctx.setActiveIntent("dc_colocation");
  if (ctx.setAnalyticsCollapsed) ctx.setAnalyticsCollapsed(false);

  // Place demo assets on map
  if (ctx.setPlacedAssets) ctx.setPlacedAssets(DEMO_DC_PLACED_ASSETS);
}
