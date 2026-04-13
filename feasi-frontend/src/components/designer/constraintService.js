/**
 * Constraint Layer Service
 * UK environmental/planning constraint configs, noise modelling, cost estimators.
 */

export const CONSTRAINT_LAYERS = {
  flood_zone_3: {
    id: "flood_zone_3",
    label: "Flood Zone 3",
    description: "EA high probability flood zone (>1% annual chance)",
    wmsUrl: "https://environment.data.gov.uk/spatialdata/flood-map-for-planning-rivers-and-sea-flood-zone-3/wms",
    wmsLayers: "Flood_Map_for_Planning__Rivers_and_Sea__Flood_Zone_3",
    color: "#3b82f6",
    opacity: 0.3,
    type: "wms",
    severity: "high",
  },
  flood_zone_2: {
    id: "flood_zone_2",
    label: "Flood Zone 2",
    description: "EA medium probability flood zone (0.1-1% annual chance)",
    wmsUrl: "https://environment.data.gov.uk/spatialdata/flood-map-for-planning-rivers-and-sea-flood-zone-2/wms",
    wmsLayers: "Flood_Map_for_Planning__Rivers_and_Sea__Flood_Zone_2",
    color: "#60a5fa",
    opacity: 0.2,
    type: "wms",
    severity: "medium",
  },
  fire_setback: {
    id: "fire_setback",
    label: "NFCC Fire Setbacks",
    description: "30m to buildings, 25m to boundary, 6m inter-container",
    type: "computed",
    severity: "high",
    rules: {
      building_setback_m: 30,
      boundary_setback_m: 25,
      inter_container_m: 6,
      transformer_setback_m: 5,
      access_width_m: 3.7,
      water_supply_litres: 228000,
      water_flow_lpm: 1900,
      water_duration_min: 120,
    },
  },
  noise: {
    id: "noise",
    label: "Noise Contours (BS 4142)",
    description: "Modelled noise propagation to nearest sensitive receptor",
    type: "computed",
    severity: "medium",
    rules: {
      bess_hvac_source_db: 65,
      dc_cooling_source_db: 85,
      dc_generator_source_db: 100,
      residential_limit_day_db: 40,
      residential_limit_night_db: 35,
      background_rating_diff_db: 5,
    },
  },
  ecology_sssi: {
    id: "ecology_sssi",
    label: "SSSI",
    description: "Sites of Special Scientific Interest",
    type: "wms",
    wmsUrl: "https://environment.data.gov.uk/spatialdata/sites-of-special-scientific-interest-england/wms",
    wmsLayers: "Sites_of_Special_Scientific_Interest__England_",
    color: "#16a34a",
    opacity: 0.25,
    severity: "high",
  },
  ecology_ancient_woodland: {
    id: "ecology_ancient_woodland",
    label: "Ancient Woodland",
    description: "15-50m buffer required (NE/FC Standing Advice)",
    type: "wms",
    wmsUrl: "https://environment.data.gov.uk/spatialdata/ancient-woodland-england/wms",
    wmsLayers: "Ancient_Woodland__England_",
    color: "#15803d",
    opacity: 0.25,
    buffer_m: 15,
    recommended_buffer_m: 50,
    severity: "high",
  },
  heritage: {
    id: "heritage",
    label: "Heritage Assets",
    description: "Listed buildings, scheduled monuments (500m-1km screening)",
    type: "api",
    screening_distance_m: 500,
    severity: "medium",
  },
  access: {
    id: "access",
    label: "Emergency Access",
    description: "3.7m road width, 16.8m turning, 45m max distance",
    type: "computed",
    severity: "high",
    rules: {
      min_road_width_m: 3.7,
      preferred_road_width_m: 5.5,
      turning_circle_m: 16.8,
      max_distance_to_unit_m: 45,
      vehicle_weight_tonnes: 17.5,
      two_access_points: true,
    },
  },
  grid_corridor: {
    id: "grid_corridor",
    label: "Grid Connection Corridor",
    description: "Wayleave/easement width by voltage level",
    type: "computed",
    severity: "low",
    wayleave_widths_m: {
      "11kV": 6, "33kV": 10, "66kV": 15, "132kV": 25, "275kV": 40, "400kV": 55,
    },
  },
};

// ── Noise Modelling ──────────────────────────────────────────────────────────

/** Calculate distance at which sound attenuates to target dB (inverse square law) */
export function noiseContourRadius(sourceDb, targetDb) {
  if (sourceDb <= targetDb) return 0;
  return Math.round(Math.pow(10, (sourceDb - targetDb) / 20));
}

/** Generate noise contour rings for a source position */
export function noiseContours(sourceDb, sourceName) {
  return [
    { db: 65, radius: noiseContourRadius(sourceDb, 65), label: "65 dB", color: "#B5432A" },
    { db: 55, radius: noiseContourRadius(sourceDb, 55), label: "55 dB", color: "#C67A1A" },
    { db: 45, radius: noiseContourRadius(sourceDb, 45), label: "45 dB", color: "#F5B731" },
    { db: 35, radius: noiseContourRadius(sourceDb, 35), label: "35 dB (night limit)", color: "#2D7A4F" },
  ].filter(c => c.radius > 0);
}

// ── Fire Setback Zones ───────────────────────────────────────────────────────

/** Calculate bounding box + setback for battery/container positions */
export function fireSetbackZone(positions, setbackM = 25) {
  if (!positions.length) return null;
  const xs = positions.map(p => p.x);
  const ys = positions.map(p => p.y);
  const ws = positions.map(p => p.w || 0);
  const hs = positions.map(p => p.h || 0);
  return {
    x: Math.min(...xs) - setbackM,
    y: Math.min(...ys) - setbackM,
    width: Math.max(...xs.map((x, i) => x + ws[i])) - Math.min(...xs) + 2 * setbackM,
    height: Math.max(...ys.map((y, i) => y + hs[i])) - Math.min(...ys) + 2 * setbackM,
  };
}

// ── Site Area Estimation ─────────────────────────────────────────────────────

export function estimateSiteArea(mw, mode, duration = 2) {
  if (mode === "bess") {
    const mwh = mw * duration;
    const equipmentAcres = mwh / 100; // 80-120 MWh/acre benchmark
    return Math.round(equipmentAcres * 2.5 * 4047); // total site = 2.5x equipment, acres to m²
  }
  return Math.round((mw / 6) * 10000); // DC: 4-8 MW/ha average
}

// ── Grid Connection ──────────────────────────────────────────────────────────

export function gridConnectionVoltage(mw) {
  if (mw < 5) return { voltage: "11kV", cost_per_km: 80000, timeline_months: 12, total_est: 200000 };
  if (mw < 50) return { voltage: "33kV", cost_per_km: 150000, timeline_months: 24, total_est: 2000000 };
  if (mw < 150) return { voltage: "132kV", cost_per_km: 500000, timeline_months: 36, total_est: 12000000 };
  return { voltage: "275kV", cost_per_km: 1000000, timeline_months: 48, total_est: 30000000 };
}

// ── BESS Revenue Estimate (Modo Energy benchmarks 2025) ──────────────────────

export function bessRevenueEstimate(mw, duration = 2) {
  const durationMult = duration >= 4 ? 1.15 : duration >= 2 ? 1.0 : 0.85;
  const arbitrage = Math.round(25000 * durationMult);
  const freq = 20000;
  const cm = duration >= 4 ? 21000 : duration >= 2 ? 12000 : 5000;
  const bm = 15000;
  const total = arbitrage + freq + cm + bm;
  return {
    total_per_mw_yr: total,
    arbitrage, frequency_response: freq, capacity_market: cm, balancing_mechanism: bm,
    total_portfolio: total * mw,
  };
}

// ── DC Financial Estimate ────────────────────────────────────────────────────

export function dcFinancialEstimate(itLoadMw, tier = 3) {
  const pue = tier >= 4 ? 1.25 : tier >= 3 ? 1.3 : tier >= 2 ? 1.4 : 1.5;
  const totalMw = itLoadMw * pue;
  const buildCostPerMw = tier >= 4 ? 13000000 : tier >= 3 ? 10000000 : 8000000;
  const revenuePerKwMonth = 130;
  return {
    pue,
    total_facility_mw: Math.round(totalMw * 10) / 10,
    cooling_mw: Math.round((totalMw - itLoadMw) * 10) / 10,
    build_cost: itLoadMw * buildCostPerMw,
    annual_revenue: itLoadMw * 1000 * revenuePerKwMonth * 12,
    opex_per_mw_yr: 500000,
    free_cooling_hours_yr: 6500, // UK average
    wue: 0.4, // adiabatic cooling
  };
}
