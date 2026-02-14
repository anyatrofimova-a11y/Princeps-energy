/**
 * Centralized API service — replaces scattered fetch() calls.
 * All endpoints return JSON or null on failure.
 */

const json = async (res) => {
  try { return res.ok ? await res.json() : null; }
  catch { return null; }
};

const get = (url) => fetch(url).then(json);

const post = (url, body) =>
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(json);

const enc = encodeURIComponent;

const api = {
  site: {
    explain:      (id) => get(`/site/${enc(id)}/explain`),
    heightmap:    (id, size = 64) => get(`/site/${enc(id)}/heightmap?size=${size}`),
    slopeStats:   (id) => get(`/site/${enc(id)}/slope_stats`),
    solarYield:   (id, kw) => get(`/site/${enc(id)}/solar_yield?capacity_kw=${kw}`),
    solarHourly:  (id, kw, day) => get(`/site/${enc(id)}/solar_hourly?capacity_kw=${kw}&day_of_year=${day}`),
    solarMl:      (id, kw, day) => get(`/site/${enc(id)}/solar_yield_ml?capacity_kw=${kw}&day_of_year=${day}`),
    energyPrice:  (id, kw, day) => get(`/site/${enc(id)}/energy_price?capacity_kw=${kw}&day_of_year=${day}`),
    gridContext:  (id, kw, day) => get(`/site/${enc(id)}/grid_context?capacity_kw=${kw}&day_of_year=${day}`),
    energySystem: (id, kw) => get(`/site/${enc(id)}/energy_system_context?capacity_kw=${kw}`),
    bom:          (id, kw) => get(`/site/${enc(id)}/bom?capacity_kw=${kw}`),
    bomAvail:     (id, kw) => get(`/site/${enc(id)}/bom/availability?capacity_kw=${kw}`),
    bomCustom:    (id, layout, signal) =>
      fetch(`/site/${enc(id)}/bom/custom`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ layout }),
        signal,
      }).then(json),
    fromLocation: (lat, lon, area = 50000) =>
      post("/site/from-location", { lat, lon, area_m2: area }),
    agent: (id, intent, kw, day) =>
      post(`/site/${enc(id)}/agent`, { intent, capacity_kw: kw, day_of_year: day }),
  },

  grid: {
    demandForecast: () => get("/grid/demand-forecast"),
    storageSim:     (gw = 250, twh = 692) => get(`/grid/storage-sim?renewable_gw=${gw}&demand_twh=${twh}`),
    agilePricing:   (region = "C", tariff) =>
      get(`/grid/agile-pricing?region=${region}${tariff ? `&tariff=${tariff}` : ""}`),
    agileMap:       () => get("/grid/agile-map"),
    demandMap:      () => get("/grid/demand-map"),
    topology:       () => get("/grid/topology"),
    live:           () => get("/grid/live"),
    stability:      (params = {}) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) q.set(k, v);
      return get(`/grid/stability?${q}`);
    },
    osmLines: (bbox, minKv = 0) => get(`/grid/osm/lines?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}&min_voltage_kv=${minKv}`),
    osmSubstations: (bbox) => get(`/grid/osm/substations?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`),
    osmTowers: (bbox) => get(`/grid/osm/towers?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`),
    osmGenerators: (bbox) => get(`/grid/osm/generators?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`),
    osmPlants: (bbox) => get(`/grid/osm/plants?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`),
    osmSummary: () => get("/grid/osm/summary"),
    ngedSubstations: (bbox) => get(`/nged/substations?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`),
    ngedOpportunities: (bbox, minMw = 1) => get(`/nged/opportunities?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}&min_headroom_mw=${minMw}`),
    ngedSummary: () => get("/nged/summary"),
    ngedSubstation: (id) => get(`/nged/substation/${enc(id)}`),
  },

  planning: {
    summary: () => get("/planning/energy/summary"),
  },

  opt: {
    run: (load, gen) => post(`/opt/run?plan_name=ui_plan&load_mw=${load}&gen_mw=${gen}`),
  },

  inventory: {
    catalogue: () => get("/inventory/catalogue"),
  },

  tenders: {
    energy: () => get("/tenders/energy"),
  },

  electricity: {
    carbonIntensity: (zone) => get(`/electricity/carbon-intensity/${enc(zone)}`),
    powerBreakdown: (zone) => get(`/electricity/power-breakdown/${enc(zone)}`),
    carbonIntensityAll: () => get("/electricity/carbon-intensity-all"),
  },

  nom: {
    substations: (params = {}) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v != null && v !== "") q.set(k, v);
      return get(`/nom/substations?${q}`);
    },
    geojson: (params = {}) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v != null && v !== "") q.set(k, v);
      return get(`/nom/substations/geojson?${q}`);
    },
    detail: (subNumber) => get(`/nom/substations/${enc(subNumber)}`),
    summary: () => get("/nom/summary"),
    licenceAreas: () => get("/nom/licence-areas"),
    localAuthorities: () => get("/nom/local-authorities"),
  },

  geeflow: {
    extract: (mode, lat, lon, radiusKm = 5, year = 2024) =>
      get(`/geeflow/extract/${enc(mode)}?lat=${lat}&lon=${lon}&radius_km=${radiusKm}&year=${year}`),
    submitAnalysis: (lat, lon, radiusKm = 5, modes = ["land_use", "terrain", "solar_resource", "vegetation"]) =>
      post("/job/geeflow_analysis", { lat, lon, radius_km: radiusKm, modes }),
    jobStatus: (jobId) => get(`/job/${enc(jobId)}`),
  },

  analytics: {
    solarForecast: (kw = 100, day = 172) => get(`/analytics/solar-forecast?capacity_kw=${kw}&day_of_year=${day}`),
    consumptionHeatmap: (scale = 1) => get(`/analytics/consumption-heatmap?scale=${scale}`),
    gridStability: (params = {}) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) q.set(k, v);
      return get(`/analytics/grid-stability?${q}`);
    },
    prosumerProfile: (kw = 10, biz = false, month = 6) =>
      get(`/analytics/prosumer-profile?installed_kw=${kw}&is_business=${biz}&month=${month}`),
    turbineHealth: () => get("/analytics/turbine-health"),
    transmissionFaults: () => get("/analytics/transmission-faults"),
    energyAssets: () => get("/analytics/energy-assets"),
  },
};

export default api;
