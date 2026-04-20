/**
 * dynamicLayers — factory that builds time-aware deck.gl layer configs.
 *
 * Consumers call `buildDynamicLayers({ asOf, fesPathway })` from inside
 * MapView (or any deck.gl overlay owner) and get back an array of layer
 * configs ready for MapboxOverlay / DeckGL.
 *
 * Each layer is wrapped via DynamicLayerAdapter.withTime where possible, and
 * otherwise derives visual state at `asOf` via local helpers. Heavy lifting
 * (timeseries interpolation, state machine transitions) lives here so the
 * adapter stays generic.
 *
 * Layers produced (7):
 *   1. tec            — TEC register queue (ScatterplotLayer)
 *   2. ecr            — DNO ECR headroom (ScatterplotLayer, colour=utilisation)
 *   3. fes            — NESO FES 4-pathway demand (ColumnLayer by GSP point)
 *   4. repd           — REPD planning apps (IconLayer/ScatterplotLayer)
 *   5. lpa            — LPA decisions backlog halos (ScatterplotLayer)
 *   6. carbon         — carbon intensity regional ramp (ScatterplotLayer)
 *   7. ppa            — PPA zonal premium choropleth (ScatterplotLayer)
 *
 * Fixtures are imported eagerly — they are small (≈30KB total).
 */

import { ScatterplotLayer, ColumnLayer } from "@deck.gl/layers";

import tecFixture   from "../../data/mock-tec-timeline.json";
import ecrFixture   from "../../data/mock-ecr-timeseries.json";
import fesFixture   from "../../data/mock-fes-pathways.json";
import repdFixture  from "../../data/mock-repd-timeline.json";

import {
  tecStateAt,
  tecColourForState,
  repdStateAt,
  repdColourForState,
  pickTimeseriesValue,
} from "./DynamicLayerAdapter";

// ─── Memoisation: year-stepping is cached so scrub playback stays cheap ────
const yearCache = new Map();
const YEAR_CACHE_MAX = 64;
function yearCacheGet(k)      { return yearCache.get(k); }
function yearCachePut(k, v)   {
  if (yearCache.size >= YEAR_CACHE_MAX) {
    yearCache.delete(yearCache.keys().next().value);
  }
  yearCache.set(k, v);
}
function yearOf(iso) { return (iso || "").slice(0, 4); }
function monthOf(iso){ return (iso || "").slice(0, 7); }

// ─── Generic helpers ──────────────────────────────────────────────────────
function lerp(a, b, t) { return a + (b - a) * t; }
function rampInkGold(t) {
  // t 0..1: ink (#0F1318) → gold (#F5B731)
  const ink  = [15, 19, 24];
  const gold = [245, 183, 49];
  return [
    Math.round(lerp(ink[0], gold[0], t)),
    Math.round(lerp(ink[1], gold[1], t)),
    Math.round(lerp(ink[2], gold[2], t)),
    220,
  ];
}
function rampGreenRed(t) {
  // 0 → green (abundant headroom), 1 → red (no headroom)
  const green = [ 40, 190,  90];
  const amber = [245, 183,  49];
  const red   = [220,  60,  60];
  if (t < 0.5) {
    const u = t * 2;
    return [
      Math.round(lerp(green[0], amber[0], u)),
      Math.round(lerp(green[1], amber[1], u)),
      Math.round(lerp(green[2], amber[2], u)),
      230,
    ];
  }
  const u = (t - 0.5) * 2;
  return [
    Math.round(lerp(amber[0], red[0], u)),
    Math.round(lerp(amber[1], red[1], u)),
    Math.round(lerp(amber[2], red[2], u)),
    240,
  ];
}

// ─── 1. TEC register ──────────────────────────────────────────────────────
function buildTecLayer(asOf) {
  const key = `tec|${monthOf(asOf)}`;
  const cached = yearCacheGet(key);
  const rows = cached
    ? cached
    : tecFixture.projects
        .filter((p) => asOf >= p.offered_date) // not yet appeared → hide
        .map((p) => ({
          ...p,
          _state:  tecStateAt(p, asOf),
          _colour: tecColourForState(tecStateAt(p, asOf)),
          _radius: 6 + Math.sqrt(p.mw) * 0.9,
        }));
  yearCachePut(key, rows);

  return new ScatterplotLayer({
    id: "dyn-tec",
    data: rows,
    getPosition: (d) => [d.lon, d.lat],
    getRadius:   (d) => d._radius,
    radiusUnits: "pixels",
    radiusMinPixels: 4,
    radiusMaxPixels: 30,
    getFillColor: (d) => d._colour,
    getLineColor: [15, 19, 24, 160],
    lineWidthMinPixels: 1,
    stroked: true,
    pickable: true,
    updateTriggers: {
      getFillColor: [asOf],
      getRadius:    [asOf],
    },
  });
}

// ─── 2. DNO ECR headroom ──────────────────────────────────────────────────
function buildEcrLayer(asOf) {
  const key = `ecr|${monthOf(asOf)}`;
  const cached = yearCacheGet(key);
  const rows = cached ? cached : ecrFixture.substations.map((ss) => {
    const delta = pickTimeseriesValue(ss.headroom_delta_series, asOf) ?? 0;
    const headroom = Math.max(0, ss.baseline_headroom_mw + delta);
    // utilisation = 1 - headroom/capacity (1 = full, 0 = wide open)
    const util = Math.max(0, Math.min(1, 1 - headroom / ss.capacity_mw));
    return {
      ...ss,
      _headroom: headroom,
      _util:     util,
      _colour:   rampGreenRed(util),
      _radius:   10 + Math.sqrt(ss.capacity_mw) * 0.5,
    };
  });
  yearCachePut(key, rows);

  return new ScatterplotLayer({
    id: "dyn-ecr",
    data: rows,
    getPosition: (d) => [d.lon, d.lat],
    getRadius:   (d) => d._radius,
    radiusUnits: "pixels",
    radiusMinPixels: 6,
    radiusMaxPixels: 40,
    getFillColor: (d) => d._colour,
    getLineColor: [15, 19, 24, 200],
    lineWidthMinPixels: 1.5,
    stroked: true,
    pickable: true,
    updateTriggers: { getFillColor: [asOf], getRadius: [asOf] },
  });
}

// ─── 3. FES pathway demand (GSP columns) ──────────────────────────────────
function buildFesLayer(asOf, pathway) {
  const year = yearOf(asOf);
  const scenario = fesFixture.scenarios.find((s) => s.pathway === pathway)
    || fesFixture.scenarios[0];
  const key = `fes|${pathway}|${year}`;
  const cached = yearCacheGet(key);

  const rows = cached ? cached : fesFixture.gsps.map((g) => {
    const entry = scenario.data.find((d) => d.gsp === g.id);
    const rawYear = Number(year);
    const clampedYear = rawYear < 2024 ? 2024 : (rawYear > 2050 ? 2050 : rawYear);
    const demand = entry ? entry.annual[String(clampedYear)] : 0;
    // normalise against 6 GW envelope for colour
    const t = Math.max(0, Math.min(1, demand / 6));
    return {
      ...g,
      _demand: demand,
      _colour: rampInkGold(t),
      _height: demand * 1500,
    };
  });
  yearCachePut(key, rows);

  return new ColumnLayer({
    id: "dyn-fes",
    data: rows,
    diskResolution: 24,
    radius: 6000,
    extruded: true,
    pickable: true,
    elevationScale: 1,
    getPosition:  (d) => [d.lon, d.lat],
    getFillColor: (d) => d._colour,
    getElevation: (d) => d._height,
    updateTriggers: {
      getFillColor: [asOf, pathway],
      getElevation: [asOf, pathway],
    },
  });
}

// ─── 4. REPD planning apps ────────────────────────────────────────────────
function buildRepdLayer(asOf) {
  const key = `repd|${monthOf(asOf)}`;
  const cached = yearCacheGet(key);
  const rows = cached ? cached : repdFixture.applications
    .filter((a) => asOf >= a.submission_date)
    .map((a) => ({
      ...a,
      _state:  repdStateAt(a, asOf),
      _colour: repdColourForState(repdStateAt(a, asOf)),
      _radius: 5 + Math.sqrt(a.mw) * 0.6,
    }));
  yearCachePut(key, rows);

  return new ScatterplotLayer({
    id: "dyn-repd",
    data: rows,
    getPosition:  (d) => [d.lon, d.lat],
    getRadius:    (d) => d._radius,
    radiusUnits:  "pixels",
    radiusMinPixels: 3,
    radiusMaxPixels: 24,
    getFillColor: (d) => d._colour,
    getLineColor: [15, 19, 24, 180],
    lineWidthMinPixels: 1,
    stroked: true,
    pickable: true,
    updateTriggers: { getFillColor: [asOf], getRadius: [asOf] },
  });
}

// ─── 5. LPA decisions backlog halos ───────────────────────────────────────
// Computes, per LPA, the number of applications submitted but awaiting a
// decision > 6 months. If > 0 at `asOf`, a halo is drawn at the LPA's
// centroid (using the mean of its REPD app coords as a stand-in centroid).
function buildLpaLayer(asOf) {
  const key = `lpa|${monthOf(asOf)}`;
  const cached = yearCacheGet(key);
  if (cached) {
    return new ScatterplotLayer({
      id: "dyn-lpa",
      data: cached,
      getPosition: (d) => [d.lon, d.lat],
      getRadius:   (d) => d._radius,
      radiusUnits: "pixels",
      radiusMinPixels: 10,
      radiusMaxPixels: 80,
      getFillColor: (d) => d._colour,
      getLineColor: [245, 183, 49, 220],
      lineWidthMinPixels: 2,
      filled: true,
      stroked: true,
      pickable: true,
      updateTriggers: { getFillColor: [asOf], getRadius: [asOf] },
    });
  }

  const byLpa = new Map();
  const SIX_MONTHS_MS = 1000 * 60 * 60 * 24 * 30 * 6;
  const asOfMs = Date.parse(asOf);
  for (const app of repdFixture.applications) {
    if (app.submission_date > asOf) continue;
    const pending = !app.decision_date || app.decision_date > asOf;
    if (!pending) continue;
    const ageMs = asOfMs - Date.parse(app.submission_date);
    if (ageMs < SIX_MONTHS_MS) continue;
    const slot = byLpa.get(app.lpa) || { lpa: app.lpa, count: 0, lon: 0, lat: 0 };
    slot.count += 1;
    slot.lon += app.lon;
    slot.lat += app.lat;
    byLpa.set(app.lpa, slot);
  }
  const rows = Array.from(byLpa.values()).map((s) => ({
    lpa:   s.lpa,
    count: s.count,
    lon:   s.lon / s.count,
    lat:   s.lat / s.count,
    _radius: 18 + s.count * 6,
    _colour: [245, 183, 49, Math.min(200, 80 + s.count * 40)],
  }));
  yearCachePut(key, rows);

  return new ScatterplotLayer({
    id: "dyn-lpa",
    data: rows,
    getPosition: (d) => [d.lon, d.lat],
    getRadius:   (d) => d._radius,
    radiusUnits: "pixels",
    radiusMinPixels: 10,
    radiusMaxPixels: 80,
    getFillColor: (d) => d._colour,
    getLineColor: [245, 183, 49, 220],
    lineWidthMinPixels: 2,
    filled: true,
    stroked: true,
    pickable: true,
    updateTriggers: { getFillColor: [asOf], getRadius: [asOf] },
  });
}

// ─── 6. Carbon intensity regional ramp ────────────────────────────────────
// Real 2020-2025 (approximate annual average gCO2/kWh for GB), modelled
// 2026-2050 tapering to pathway-dependent floor. Rendered per GSP point.
const CARBON_HIST = {
  "2020": 181, "2021": 199, "2022": 196, "2023": 162, "2024": 135, "2025": 118,
};
function carbonAt(asOf, pathway) {
  const y = Number(yearOf(asOf));
  if (y <= 2025) return CARBON_HIST[String(y)] ?? 150;
  const floor = pathway === "Leading the Way" ? 8
              : pathway === "Consumer Transformation" ? 14
              : pathway === "System Transformation"   ? 20
              : 52; // Falling Short
  const start = CARBON_HIST["2025"];
  const dy = y - 2025;
  const span = 2050 - 2025;
  const t = Math.min(1, dy / span);
  return Math.round(lerp(start, floor, t));
}
function buildCarbonLayer(asOf, pathway) {
  const key = `carbon|${pathway}|${yearOf(asOf)}`;
  const cached = yearCacheGet(key);
  const intensity = carbonAt(asOf, pathway);
  // 250 gCO2/kWh → dirty red, 0 → clean green
  const t = Math.max(0, Math.min(1, intensity / 250));
  const rows = cached ? cached : fesFixture.gsps.map((g) => ({
    ...g,
    _intensity: intensity,
    _colour:    rampGreenRed(t),
    _radius:    18,
  }));
  yearCachePut(key, rows);

  return new ScatterplotLayer({
    id: "dyn-carbon",
    data: rows,
    getPosition: (d) => [d.lon, d.lat],
    getRadius:   (d) => d._radius,
    radiusUnits: "pixels",
    radiusMinPixels: 12,
    radiusMaxPixels: 40,
    getFillColor: (d) => d._colour,
    opacity: 0.35,
    stroked: false,
    pickable: true,
    updateTriggers: { getFillColor: [asOf, pathway] },
  });
}

// ─── 7. PPA zonal premium ─────────────────────────────────────────────────
// Mock UK zonal premium vs national average £/MWh — evolves over time.
// 7 zones keyed off GSP groupings; premium becomes more dispersed post-REMA.
const PPA_ZONES = [
  { id: "Z-NORTH",   gsps: ["GSP-EDIN", "GSP-GLAS", "GSP-NEWC"] },
  { id: "Z-YORKS",   gsps: ["GSP-LEED", "GSP-SHEF"] },
  { id: "Z-NWEST",   gsps: ["GSP-LIVE", "GSP-MANC"] },
  { id: "Z-EMID",    gsps: ["GSP-BEDF", "GSP-PETE"] },
  { id: "Z-EAST",    gsps: ["GSP-NORW", "GSP-CANT"] },
  { id: "Z-LON-SE",  gsps: ["GSP-BARK", "GSP-READ"] },
  { id: "Z-WALES",   gsps: ["GSP-CARD"] },
];
function ppaPremiumAt(year, zoneId) {
  // pre-REMA (<=2027): narrow spread ±5. post-REMA: ±30 depending on region.
  const y = Number(year);
  const postRema = Math.max(0, (y - 2027) / 10);
  const base = {
    "Z-NORTH":   -12,
    "Z-YORKS":   -6,
    "Z-NWEST":   -3,
    "Z-EMID":     2,
    "Z-EAST":     4,
    "Z-LON-SE":  18,
    "Z-WALES":   -8,
  }[zoneId] ?? 0;
  return Math.round(base * (0.5 + postRema * 1.2));
}
function buildPpaLayer(asOf) {
  const year = yearOf(asOf);
  const key = `ppa|${year}`;
  const cached = yearCacheGet(key);
  const rows = cached ? cached : PPA_ZONES.flatMap((z) => {
    const premium = ppaPremiumAt(year, z.id);
    // map premium range −30..+30 → 0..1 (1 = most expensive)
    const t = Math.max(0, Math.min(1, (premium + 30) / 60));
    const colour = rampInkGold(t);
    return z.gsps.map((gspId) => {
      const gsp = fesFixture.gsps.find((g) => g.id === gspId);
      if (!gsp) return null;
      return {
        zone: z.id,
        gsp:  gspId,
        lon:  gsp.lon,
        lat:  gsp.lat,
        _premium: premium,
        _colour:  colour,
        _radius:  26,
      };
    }).filter(Boolean);
  });
  yearCachePut(key, rows);

  return new ScatterplotLayer({
    id: "dyn-ppa",
    data: rows,
    getPosition: (d) => [d.lon, d.lat],
    getRadius:   (d) => d._radius,
    radiusUnits: "pixels",
    radiusMinPixels: 16,
    radiusMaxPixels: 48,
    getFillColor: (d) => d._colour,
    opacity: 0.45,
    stroked: false,
    pickable: true,
    updateTriggers: { getFillColor: [asOf] },
  });
}

// ─── Public factory ───────────────────────────────────────────────────────
export function buildDynamicLayers({ asOf, fesPathway, visible } = {}) {
  if (!asOf) return [];
  const on = (id) => !visible || visible[id] !== false;
  const layers = [];
  if (on("carbon")) layers.push(buildCarbonLayer(asOf, fesPathway));
  if (on("ppa"))    layers.push(buildPpaLayer(asOf));
  if (on("fes"))    layers.push(buildFesLayer(asOf, fesPathway));
  if (on("ecr"))    layers.push(buildEcrLayer(asOf));
  if (on("tec"))    layers.push(buildTecLayer(asOf));
  if (on("repd"))   layers.push(buildRepdLayer(asOf));
  if (on("lpa"))    layers.push(buildLpaLayer(asOf));
  return layers;
}

export function clearDynamicLayerCache() {
  yearCache.clear();
}

export default buildDynamicLayers;
