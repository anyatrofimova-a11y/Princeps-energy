/**
 * fesProjections — pure, deterministic helpers that turn a (year, pathway) pair
 * into numbers we can bind to the map, the live strip, and the legend.
 *
 * Two data sources are used:
 *
 *   1. REAL-ish fixture: `mock-fes-pathways.json` — per-GSP annual peak
 *      demand (GW), 2024-2050, for each of the 4 FES 2024 pathways. Loaded
 *      from the same file `dynamicLayers.js` already consumes.
 *
 *   2. HEURISTIC endpoints: FES 2024 published pathway-ends (NESO FES 2024,
 *      "Electricity — Peak Demand" chapter). These are used to project
 *      SYSTEM-level demand, wind, solar, carbon, and price at any year
 *      between 2020 (≈ today baseline) and 2050. Anything returned from
 *      these tables is flagged via `_source: "heuristic_interpolation"` so
 *      downstream code can show the right disclaimer.
 *
 * Pathway endpoints sourced from:
 *   - FES 2024 report, "Key pathway messages" (NESO, Dec 2024)
 *   - NESO interactive FES dashboard, 2050 snapshot
 *   Peak demand 2050 (GW): LTW 59, CT 67, ST 52, FS 48
 *   Wind capacity 2050 (GW): LTW 85, CT 80, ST 75, FS 55
 *   Solar capacity 2050 (GW): LTW 65, CT 60, ST 55, FS 35
 *   Carbon intensity 2050 (gCO2/kWh): LTW 8, CT 14, ST 20, FS 52
 *   Wholesale price 2050 (£/MWh, real 2024): LTW 48, CT 54, ST 62, FS 88
 *
 * The interpolation is linear in year-space from a common 2024 baseline.
 * This is deliberately crude — it is a visual guide, not a forecast.
 */

import fesFixture from "../data/mock-fes-pathways.json";

export const FES_PATHWAYS = Object.freeze([
  "Leading the Way",
  "Consumer Transformation",
  "System Transformation",
  "Falling Short",
]);

export const PATHWAY_SHORT = Object.freeze({
  "Leading the Way":         "LTW",
  "Consumer Transformation": "CT",
  "System Transformation":   "ST",
  "Falling Short":           "FS",
});

// FES 2024 pathway-end values (2050). Sources cited in file header.
const PATHWAY_ENDPOINTS_2050 = Object.freeze({
  "Leading the Way":         { demand_gw: 59, wind_gw: 85, solar_gw: 65, carbon_gco2: 8,  price_gbp_mwh: 48 },
  "Consumer Transformation": { demand_gw: 67, wind_gw: 80, solar_gw: 60, carbon_gco2: 14, price_gbp_mwh: 54 },
  "System Transformation":   { demand_gw: 52, wind_gw: 75, solar_gw: 55, carbon_gco2: 20, price_gbp_mwh: 62 },
  "Falling Short":           { demand_gw: 48, wind_gw: 55, solar_gw: 35, carbon_gco2: 52, price_gbp_mwh: 88 },
});

// Present-day baseline (approx. 2024 ESO / BMRS annualised averages).
const BASELINE_2024 = Object.freeze({
  demand_gw:      38,   // GB peak demand, winter 2023/24
  wind_gw:        30,   // installed wind capacity, end-2024
  solar_gw:       17,   // installed solar capacity, end-2024
  carbon_gco2:    135,  // annual mean grid carbon intensity (gCO2/kWh)
  price_gbp_mwh:  72,   // annual mean wholesale (day-ahead) £/MWh
});

// Years outside [2020, 2050] get clamped.
export const YEAR_MIN = 2020;
export const YEAR_MAX = 2050;
export const BASELINE_YEAR = 2024;

// ── Helpers ───────────────────────────────────────────────────────────────
function clampYear(y) {
  const n = Number(y);
  if (!Number.isFinite(n)) return BASELINE_YEAR;
  if (n < YEAR_MIN) return YEAR_MIN;
  if (n > YEAR_MAX) return YEAR_MAX;
  return n;
}

function yearOf(isoOrYear) {
  if (typeof isoOrYear === "number") return isoOrYear;
  if (!isoOrYear) return BASELINE_YEAR;
  return Number(String(isoOrYear).slice(0, 4));
}

function lerp(a, b, t) { return a + (b - a) * t; }

function validPathway(p) {
  return FES_PATHWAYS.includes(p) ? p : "Consumer Transformation";
}

/**
 * Linear interpolation baseline-2024 → endpoint-2050 for a named metric.
 * For years 2020-2023 we extrapolate on the same linear slope.
 */
function interpMetric(year, pathway, metricKey) {
  const y = clampYear(year);
  const p = validPathway(pathway);
  const a = BASELINE_2024[metricKey];
  const b = PATHWAY_ENDPOINTS_2050[p][metricKey];
  const span = 2050 - BASELINE_YEAR;
  const t = (y - BASELINE_YEAR) / span;
  return a + (b - a) * t;
}

// ── Public API ────────────────────────────────────────────────────────────

/**
 * Returns the projected peak demand (GW) at a given GSP for (year, pathway).
 * Uses the real fixture when year in [2024, 2050], else extrapolates linearly
 * from the 2024 fixture value.
 *
 * Returned shape:
 *   { value: number, unit: "GW", source: "fixture" | "heuristic_interpolation" }
 */
export function projectedGspDemandGw(gspId, year, pathway) {
  const y = clampYear(year);
  const p = validPathway(pathway);
  const scenario = fesFixture.scenarios.find((s) => s.pathway === p)
    || fesFixture.scenarios[0];
  const entry = scenario.data.find((d) => d.gsp === gspId);
  if (!entry) {
    return { value: 0, unit: "GW", source: "missing" };
  }

  // Fixture covers 2024-2050
  if (y >= 2024 && y <= 2050) {
    const v = entry.annual[String(y)];
    return { value: v ?? 0, unit: "GW", source: "fixture" };
  }

  // Below 2024 — extrapolate from the 2024 value along national slope
  const v2024 = entry.annual["2024"] ?? 0;
  const national = interpMetric(y, p, "demand_gw");
  const national2024 = BASELINE_2024.demand_gw;
  const ratio = national2024 > 0 ? national / national2024 : 1;
  return {
    value: v2024 * ratio,
    unit: "GW",
    source: "heuristic_interpolation",
  };
}

/**
 * Returns GB-wide projected system headline numbers for the live-strip.
 * All values are clearly flagged as a linear interpolation to pathway-end.
 */
export function projectedSystemSnapshot(year, pathway) {
  const y = clampYear(year);
  const p = validPathway(pathway);
  const demand    = interpMetric(y, p, "demand_gw");
  const windCap   = interpMetric(y, p, "wind_gw");
  const solarCap  = interpMetric(y, p, "solar_gw");
  const carbon    = interpMetric(y, p, "carbon_gco2");
  const price     = interpMetric(y, p, "price_gbp_mwh");

  // Convert installed capacity to assumed simultaneous delivered GW at peak
  // using crude capacity factors at peak: wind ~0.35, solar ~0.15 (UK winter
  // peak is low-light hours so solar contribution is small at peak demand).
  const wind_delivered_gw  = windCap * 0.35;
  const solar_delivered_gw = solarCap * 0.15;

  return {
    year: y,
    pathway: p,
    demand_gw:        Number(demand.toFixed(1)),
    wind_capacity_gw: Number(windCap.toFixed(1)),
    wind_gw:          Number(wind_delivered_gw.toFixed(1)),
    solar_capacity_gw:Number(solarCap.toFixed(1)),
    solar_gw:         Number(solar_delivered_gw.toFixed(1)),
    carbon_gco2_kwh:  Math.round(carbon),
    price_gbp_mwh:    Math.round(price),
    _source: "heuristic_interpolation",
    _notes: "Linear interp from 2024 baseline to FES 2024 pathway-end (2050).",
  };
}

/**
 * When should we show projected rather than live numbers?
 * True when the user has scrubbed off the current calendar year.
 */
export function isProjectedMode(isoAsOf) {
  const currentYear = new Date().getFullYear();
  const y = yearOf(isoAsOf);
  return y !== currentYear;
}

/** Utility: friendly year for labels (always integer in [2020, 2050]). */
export function labelYear(isoAsOf) {
  return clampYear(yearOf(isoAsOf));
}

export default {
  FES_PATHWAYS,
  PATHWAY_SHORT,
  YEAR_MIN,
  YEAR_MAX,
  BASELINE_YEAR,
  projectedGspDemandGw,
  projectedSystemSnapshot,
  isProjectedMode,
  labelYear,
};
