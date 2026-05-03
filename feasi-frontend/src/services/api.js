/**
 * Centralized API service — replaces scattered fetch() calls.
 * All endpoints return JSON or null on failure.
 * Includes retry with exponential backoff and health polling.
 */

const json = async (res) => {
  if (!res) return null;
  try {
    if (!res.ok) {
      console.warn(`[API] ${res.url} → ${res.status} ${res.statusText}`);
      return null;
    }
    return await res.json();
  } catch (e) {
    console.warn(`[API] JSON parse failed for ${res?.url}:`, e.message);
    return null;
  }
};

const MAX_RETRIES = 3;
const BASE_DELAY_MS = 1000;

/**
 * Fetch with exponential backoff retry (1s, 2s, 4s).
 * Only retries on network errors or 502/503/504 (backend starting).
 */
const fetchWithRetry = async (url, opts = {}) => {
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const res = await fetch(url, opts);
      if (res.ok || attempt === MAX_RETRIES || (res.status < 502 || res.status > 504)) {
        return res;
      }
      // 502/503/504 — backend likely still starting, retry
    } catch (err) {
      // Network error (backend unreachable)
      if (attempt === MAX_RETRIES) throw err;
    }
    await new Promise(r => setTimeout(r, BASE_DELAY_MS * Math.pow(2, attempt)));
  }
};

const get = (url) => fetchWithRetry(url).then(json);

const post = (url, body) =>
  fetchWithRetry(url, {
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
    realContext: (lat, lon, radiusKm = 5) =>
      get(`/api/site/real-context?lat=${lat}&lon=${lon}&radius_km=${radiusKm}`),
    constructionPlan: (mw, tech = "solar", area, gridDist) =>
      post("/api/site/construction-plan", { capacity_mw: mw, technology: tech, site_area_ha: area, grid_distance_km: gridDist }),
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
    substationDetail: (id) => get(`/api/grid/substation/${enc(id)}/detail`),
    circuit: (subId, depth = 3) => get(`/grid/cim/circuit/${enc(subId)}?depth=${depth}`),
    circuitSearch: (q) => get(`/grid/cim/search?q=${enc(q)}`),
    circuitPath: (fromId, toId) => get(`/grid/cim/path?from_id=${enc(fromId)}&to_id=${enc(toId)}`),
    circuitDownstream: (subId) => get(`/grid/cim/downstream/${enc(subId)}`),
    circuitHealth: () => get("/grid/cim/health"),
    // National Grid overlays
    constraints:  (hoursAhead = 48) => get(`/api/grid/constraints?hours_ahead=${hoursAhead}`),
    environmentalConstraints: (lat, lon, radiusM = 2000) => get(`/api/grid/environmental-constraints?lat=${lat}&lon=${lon}&radius_m=${radiusM}`),
    queueDepth:   (substationId) => get(`/api/grid/queue-depth/${substationId}`),
    queueSummary: (bbox) => bbox ? get(`/api/grid/queue-summary?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`) : get("/api/grid/queue-summary"),
    liveStatus:   () => get("/api/grid/live-status"),
    // Revenue Stacking
    revenueStack: (mw, tech, bessMwh, lat, lon) => {
      const q = new URLSearchParams({ capacity_mw: mw, technology: tech });
      if (bessMwh != null) q.set("bess_mwh", bessMwh);
      if (lat != null) q.set("lat", lat);
      if (lon != null) q.set("lon", lon);
      return post(`/api/grid/revenue-stack?${q}`);
    },
    // DNO Pre-Application Intelligence
    dnoIntelligence: (dno) => get(`/api/grid/dno-intelligence/${enc(dno)}`),
    dnoIntelligenceNear: (lat, lon) => get(`/api/grid/dno-intelligence?lat=${lat}&lon=${lon}`),
    dnoIntelligenceAll: () => get("/api/grid/dno-intelligence"),
    // Connection offer forecasting
    connectionForecast: (lat, lon, mw = 50, tech = "solar") =>
      post(`/api/grid/connection-forecast?lat=${lat}&lon=${lon}&capacity_mw=${mw}&technology=${enc(tech)}`),
    batchConnectionForecast: (sites) =>
      post("/api/grid/batch-connection-forecast", sites),
    // TEC Timeline prediction
    tecTimelines: () => get("/api/grid/tec-timelines"),
    predictTimeline: (mw = 50, tech = "solar", hostTo) => {
      const q = new URLSearchParams({ capacity_mw: mw, technology: tech });
      if (hostTo) q.set("host_to", hostTo);
      return post(`/api/grid/predict-timeline?${q}`);
    },
    // GridFinder — unmapped grid detection
    unmappedGrid: (lat, lon, km = 10) => get(`/api/grid/unmapped?lat=${lat}&lon=${lon}&radius_km=${km}`),
    // Grid connection capacity endpoints
    capacityMap: (bbox) => get(`/grid/capacity-map?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`),
    gridLines: (bbox) => get(`/grid/lines?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`),
    powerFlow: (lat, lon, capacityMw, technology, substationId, contingency) => {
      const q = new URLSearchParams({ lat, lon, capacity_mw: capacityMw, technology });
      if (substationId != null) q.set("substation_id", substationId);
      if (contingency) q.set("contingency", "true");
      return post(`/grid/power-flow?${q}`);
    },
    // Time-to-Energisation estimator
    energisationTimeline: (lat, lon, mw, tech) =>
      post("/api/grid/energisation-timeline", { lat, lon, capacity_mw: mw, technology: tech }),
    // Connection optimization (UK reform 2025-2026)
    gateReadiness: (lat, lon, mw, tech, details) =>
      post("/api/grid/gate-readiness", { lat, lon, capacity_mw: mw, technology: tech, ...details }),
    queueReformImpact: (lat, lon, mw) =>
      post("/api/grid/queue-reform-impact", { lat, lon, capacity_mw: mw }),
    strategicAlignment: (lat, lon, mw, tech) =>
      post("/api/grid/strategic-alignment", { lat, lon, capacity_mw: mw, technology: tech }),
    optimizeConnection: (lat, lon, mw, tech) =>
      post("/api/grid/optimize-connection", { lat, lon, capacity_mw: mw, technology: tech }),
  },

  energy: {
    assumptions: () => get("/api/energy/assumptions"),
    npv: (capacityMw = 50, technology = "solar", ppaPrice, lifetime) => {
      const q = new URLSearchParams({ capacity_mw: capacityMw, technology });
      if (ppaPrice != null) q.set("ppa_price", ppaPrice);
      if (lifetime != null) q.set("lifetime", lifetime);
      return get(`/api/energy/npv?${q}`);
    },
    compare: (capacityMw = 50) => get(`/api/energy/compare?capacity_mw=${capacityMw}`),
  },

  liveGrid: {
    snapshot: () => get("/api/live/snapshot"),
    demandForecast: (hours = 48) => get(`/api/live/demand-forecast?hours_ahead=${hours}`),
    windSolarForecast: () => get("/api/live/wind-solar-forecast"),
    generationMix: () => get("/api/live/generation-mix"),
    systemPrice: () => get("/api/live/system-price"),
    carbonRegional: () => get("/api/live/carbon-regional"),
    wholesalePrices: (days = 7) => get(`/api/live/wholesale-prices?days=${days}`),
    dayAheadPrices: (date) => get(`/api/live/day-ahead-prices${date ? `?date=${enc(date)}` : ""}`),
    currentPrice: () => get("/api/live/current-price"),
  },

  land: {
    parcels:  (bbox) => get(`/api/land/parcels?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`),
    alc:      (lat, lon) => get(`/api/land/alc?lat=${lat}&lon=${lon}`),
    alcDetailed: (lat, lon) => get(`/api/land/alc-detailed?lat=${lat}&lon=${lon}`),
    listings: (lat, lon, radiusKm = 10) => get(`/api/land/listings?lat=${lat}&lon=${lon}&radius_km=${radiusKm}`),
    pricePaid: (postcode) => get(`/api/land/price-paid?postcode=${enc(postcode)}`),
    planningDensity: (lat, lon, radiusKm = 10) => get(`/api/land/planning-density?lat=${lat}&lon=${lon}&radius_km=${radiusKm}`),
    companies: (lat, lon, km = 5) => get(`/api/land/companies?lat=${lat}&lon=${lon}&radius_km=${km}`),
    companyDetail: (companyNumber) => get(`/api/land/company/${enc(companyNumber)}`),
    classificationHeatmap: (params) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v != null) q.set(k, v);
      return get(`/api/land/classification-heatmap?${q}`);
    },
  },

  parcels: {
    getInBbox: (params) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v != null) q.set(k, v);
      return get(`/api/parcels?${q}`);
    },
    getDetail: (titleNumber) => get(`/api/parcels/${enc(titleNumber)}`),
    search: (params) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v != null) q.set(k, v);
      return get(`/api/parcels/search?${q}`);
    },
    selectForProject: (data) => post("/api/parcels/select", data),
    getProjectParcels: (projectName) => get(`/api/parcels/project/${enc(projectName)}`),
  },

  environment: {
    assess: (lat, lon, capacityMw = 50, radiusM = 1000) =>
      get(`/api/environment/assess?lat=${lat}&lon=${lon}&capacity_mw=${capacityMw}&radius_m=${radiusM}`),
    constraints: (lat, lon, radiusM = 2000) =>
      get(`/api/environment/constraints?lat=${lat}&lon=${lon}&radius_m=${radiusM}`),
    noise: (sources, opts = {}) =>
      post("/api/environment/noise", { sources, ...opts }),
  },

  carbon: {
    history:  (regionId = 13, days = 14) => get(`/api/carbon/history?region_id=${regionId}&days=${days}`),
    forecast: (regionId = 13, horizonHours = 48, model = "analytical", historyDays = 14, epochs = 15) =>
      get(`/api/carbon/forecast?region_id=${regionId}&horizon_hours=${horizonHours}&model=${enc(model)}&history_days=${historyDays}&epochs=${epochs}`),
  },

  demand: {
    gsps:       () => get("/api/demand/gsps"),
    historical: (gspId, days = 30, startDate) =>
      get(`/api/demand/historical?gsp_id=${enc(gspId)}&days=${days}${startDate ? `&start_date=${startDate}` : ""}`),
    forecast:   (gspId, horizonHours = 168, model = "analytical", peakMw, minMw, capacityMw) => {
      const q = new URLSearchParams({ gsp_id: gspId, horizon_hours: horizonHours, model });
      if (peakMw != null) q.set("peak_mw", peakMw);
      if (minMw != null) q.set("min_mw", minMw);
      if (capacityMw != null) q.set("capacity_mw", capacityMw);
      return get(`/api/demand/forecast?${q}`);
    },
    scenarios:  (gspId, peakMw, minMw, capacityMw, yearsAhead = 10) =>
      get(`/api/demand/scenarios?gsp_id=${enc(gspId)}&peak_mw=${peakMw}&min_mw=${minMw}&capacity_mw=${capacityMw}&years_ahead=${yearsAhead}`),
    summary:    () => get("/api/demand/summary"),
  },

  gridTwin: {
    state:    () => get("/api/grid-twin/state"),
    scenario: (name, year = 2030) => get(`/api/grid-twin/scenario/${enc(name)}?year=${year}`),
  },

  connectionStrategy: {
    curtailmentEstimate: (capacityMw = 50, region = "Midlands", technology = "solar", connType = "firm", queueDepth = 0) =>
      get(`/api/connection-strategy/curtailment/estimate?capacity_mw=${capacityMw}&region=${enc(region)}&technology=${enc(technology)}&connection_type=${enc(connType)}&queue_depth=${queueDepth}`),
    curtailmentRevenue: (capacityMw = 50, region = "Midlands", technology = "solar", connType = "firm", price = 55) =>
      get(`/api/connection-strategy/curtailment/revenue-impact?capacity_mw=${capacityMw}&region=${enc(region)}&technology=${enc(technology)}&connection_type=${enc(connType)}&wholesale_price_mwh=${price}`),
    curtailmentRegions: () => get("/api/connection-strategy/curtailment/regions"),
    flexibleCompare: (capacityMw, headroomMw, region, technology, voltageKv) =>
      post("/api/connection-strategy/flexible/compare", { capacity_mw: capacityMw, headroom_mw: headroomMw, region, technology, voltage_kv: voltageKv }),
    anmProfile: (capacityMw = 50, headroomMw = 30, technology = "solar") =>
      get(`/api/connection-strategy/flexible/anm-profile?capacity_mw=${capacityMw}&headroom_mw=${headroomMw}&technology=${enc(technology)}`),
    optimalSizing: (headroomMw = 30, region = "Midlands", technology = "solar", target = 5) =>
      get(`/api/connection-strategy/flexible/optimal-sizing?headroom_mw=${headroomMw}&region=${enc(region)}&technology=${enc(technology)}&target_curtailment_pct=${target}`),
    timelineGenerate: (capacityMw, voltageKv, connType, startDate) =>
      post("/api/connection-strategy/timeline/generate", { capacity_mw: capacityMw, voltage_kv: voltageKv, connection_type: connType, start_date: startDate }),
    timelineMilestones: (capacityMw = 50) => get(`/api/connection-strategy/timeline/milestones?capacity_mw=${capacityMw}`),
    strategy: (lat, lon, capacityMw, technology, voltageKv, headroomMw, distanceKm) =>
      post("/api/connection-strategy/strategy", { lat, lon, capacity_mw: capacityMw, technology, voltage_kv: voltageKv, headroom_mw: headroomMw, distance_km: distanceKm }),
    compare: (capacityMw, region, headroomMw, technology) =>
      post("/api/connection-strategy/compare", { capacity_mw: capacityMw, region, headroom_mw: headroomMw, technology }),
  },

  sustainability: {
    carbonFootprint: (capacityMw = 50, technology = "wind", projectLifeYears = 25) =>
      get(`/api/sustainability/carbon/footprint?capacity_mw=${capacityMw}&technology=${enc(technology)}&project_life_years=${projectLifeYears}`),
    gridDisplacement: (capacityMw = 50, technology = "wind", region = "Scotland", projectLifeYears = 25) =>
      get(`/api/sustainability/carbon/displacement?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&project_life_years=${projectLifeYears}`),
    esgScore: (capacityMw = 50, technology = "wind", region = "Scotland", communityFund = true, sharedOwnership = false, bng = true) =>
      get(`/api/sustainability/esg/score?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&community_fund=${communityFund}&shared_ownership=${sharedOwnership}&biodiversity_net_gain=${bng}`),
    portfolioSummary: (sites) =>
      post("/api/sustainability/portfolio/summary", { sites }),
    portfolioDiversification: (sites) =>
      post("/api/sustainability/portfolio/diversification", { sites }),
    portfolioOptimisation: (budgetMw = 200, target = "max_revenue") =>
      get(`/api/sustainability/portfolio/optimisation?budget_mw=${budgetMw}&target=${enc(target)}`),
    communityPackage: (capacityMw = 50, technology = "wind", region = "Scotland", communityFund = true, sharedOwnershipPct = 0) =>
      get(`/api/sustainability/community/package?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&community_fund=${communityFund}&shared_ownership_pct=${sharedOwnershipPct}`),
    sharedOwnership: (capacityMw = 50, technology = "wind", communityStakePct = 25) =>
      get(`/api/sustainability/community/shared-ownership?capacity_mw=${capacityMw}&technology=${enc(technology)}&community_stake_pct=${communityStakePct}`),
    socialValue: (capacityMw = 50, technology = "wind", region = "Scotland", communityFund = true, apprenticeships = 3) =>
      get(`/api/sustainability/community/social-value?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&community_fund=${communityFund}&apprenticeships=${apprenticeships}`),
    decomEstimate: (capacityMw = 50, technology = "wind", ageYears = 25) =>
      get(`/api/sustainability/decom/estimate?capacity_mw=${capacityMw}&technology=${enc(technology)}&age_years=${ageYears}`),
    repoweringComparison: (capacityMw = 50, technology = "wind", region = "Scotland") =>
      get(`/api/sustainability/decom/repowering?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}`),
    materialRecovery: (capacityMw = 50, technology = "wind") =>
      get(`/api/sustainability/decom/material-recovery?capacity_mw=${capacityMw}&technology=${enc(technology)}`),
  },

  rtm: {
    ppaPrice: (capacityMw = 50, technology = "wind", region = "Scotland", structure = "fixed", termYears = 15, creditTier = "investment_grade") =>
      get(`/api/rtm/ppa/price?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&structure=${enc(structure)}&term_years=${termYears}&credit_tier=${enc(creditTier)}`),
    ppaTerms: (capacityMw = 50, technology = "solar", region = "Midlands", structure = "fixed") =>
      get(`/api/rtm/ppa/term-analysis?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&structure=${enc(structure)}`),
    ppaStructures: (capacityMw = 50, technology = "wind", region = "Scotland", termYears = 15) =>
      get(`/api/rtm/ppa/structures?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&term_years=${termYears}`),
    offtakeMatch: (capacityMw = 50, technology = "wind", region = "Scotland") =>
      get(`/api/rtm/offtake/match?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}`),
    offtakeBuyer: (buyerType = "data_centre") =>
      get(`/api/rtm/offtake/buyer?buyer_type=${enc(buyerType)}`),
    offtakeCorrelation: (technology = "wind", buyerType = "industrial") =>
      get(`/api/rtm/offtake/correlation?technology=${enc(technology)}&buyer_type=${enc(buyerType)}`),
    routesCompare: (capacityMw = 50, technology = "wind", region = "Scotland") =>
      get(`/api/rtm/routes/compare?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}`),
    routeDetail: (route = "cfd", capacityMw = 50, technology = "wind") =>
      get(`/api/rtm/routes/detail?route=${enc(route)}&capacity_mw=${capacityMw}&technology=${enc(technology)}`),
    routeBankability: (capacityMw = 50, technology = "wind", region = "Scotland", route = "corporate_ppa") =>
      get(`/api/rtm/routes/bankability?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&route=${enc(route)}`),
    riskAssessment: (capacityMw = 50, technology = "wind", region = "Scotland", route = "cfd") =>
      get(`/api/rtm/risk/assessment?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&route=${enc(route)}`),
    riskSensitivity: (capacityMw = 50, technology = "wind", region = "Scotland", route = "cfd") =>
      get(`/api/rtm/risk/sensitivity?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&route=${enc(route)}`),
    riskBankability: (capacityMw = 50, technology = "wind", region = "Scotland", route = "corporate_ppa") =>
      get(`/api/rtm/risk/bankability?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&route=${enc(route)}`),
  },

  dispatch: {
    constraintForecast: (hoursAhead = 48, date) =>
      get(`/api/dispatch/constraints/forecast?hours_ahead=${hoursAhead}${date ? `&date=${enc(date)}` : ""}`),
    constraintBoundary: (boundaryId = "B1", hoursAhead = 48, date) =>
      get(`/api/dispatch/constraints/boundary?boundary_id=${enc(boundaryId)}&hours_ahead=${hoursAhead}${date ? `&date=${enc(date)}` : ""}`),
    constraintWindows: (hoursAhead = 48, threshold = 0.5, date) =>
      get(`/api/dispatch/constraints/windows?hours_ahead=${hoursAhead}&threshold=${threshold}${date ? `&date=${enc(date)}` : ""}`),
    schedule: (capacityMw = 50, technology = "solar", region = "Midlands", connType = "anm", headroomMw = 30, hoursAhead = 24, month = 1) =>
      get(`/api/dispatch/schedule?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&connection_type=${enc(connType)}&headroom_mw=${headroomMw}&hours_ahead=${hoursAhead}&month=${month}`),
    bessSchedule: (powerMw, energyMwh, socPct, region, hoursAhead, month) =>
      post("/api/dispatch/bess-schedule", { power_mw: powerMw, energy_mwh: energyMwh, soc_pct: socPct, region, hours_ahead: hoursAhead, month }),
    revenueComparison: (capacityMw = 50, technology = "solar", region = "Midlands") =>
      get(`/api/dispatch/revenue-comparison?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}`),
    bmRevenue: (capacityMw = 50, technology = "wind", region = "Scotland") =>
      get(`/api/dispatch/bm/revenue?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}`),
    bmBoaProfile: (capacityMw = 50, region = "Scotland", technology = "wind", hoursAhead = 24, month = 1) =>
      get(`/api/dispatch/bm/boa-profile?capacity_mw=${capacityMw}&region=${enc(region)}&technology=${enc(technology)}&hours_ahead=${hoursAhead}&month=${month}`),
    bmSystemPrices: (date = "2025-01-15") =>
      get(`/api/dispatch/bm/system-prices?date=${enc(date)}`),
    revenueStack: (capacityMw = 50, technology = "wind", region = "Scotland", connType = "anm", headroomMw = 30, cfdEnabled = true) =>
      get(`/api/dispatch/revenue/stack?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&connection_type=${enc(connType)}&headroom_mw=${headroomMw}&cfd_enabled=${cfdEnabled}`),
    revenueMonthly: (capacityMw = 50, technology = "solar", region = "Midlands", connType = "anm", headroomMw = 30) =>
      get(`/api/dispatch/revenue/monthly?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&connection_type=${enc(connType)}&headroom_mw=${headroomMw}`),
    revenueScenarios: (capacityMw = 50, technology = "wind", region = "Scotland") =>
      get(`/api/dispatch/revenue/scenarios?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}`),
  },

  advancedGrid: {
    dlrRate: (conductor = "Zebra", temp = 20, wind = 0.5, angle = 45, solar = 0) =>
      get(`/api/advanced-grid/dlr/rate?conductor=${enc(conductor)}&ambient_temp_c=${temp}&wind_speed_ms=${wind}&wind_angle_deg=${angle}&solar_irradiance_wm2=${solar}`),
    dlrRateLine: (voltageKv = 132, temp = 20, wind = 0.5, angle = 45, solar = 0) =>
      get(`/api/advanced-grid/dlr/rate-line?voltage_kv=${voltageKv}&ambient_temp_c=${temp}&wind_speed_ms=${wind}&wind_angle_deg=${angle}&solar_irradiance_wm2=${solar}`),
    dlrSeasonal: (conductor = "Zebra", lat = 52) =>
      get(`/api/advanced-grid/dlr/seasonal?conductor=${enc(conductor)}&lat=${lat}`),
    dlrConductors: () => get("/api/advanced-grid/dlr/conductors"),
    congestionPredict: (params = {}) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) q.set(k, v);
      return get(`/api/advanced-grid/congestion/predict?${q}`);
    },
    congestionDay: (date, demandGw = 40) =>
      get(`/api/advanced-grid/congestion/predict-day?date=${enc(date)}&demand_base_gw=${demandGw}`),
    congestionBoundaries: () => get("/api/advanced-grid/congestion/boundaries"),
    optimise: (lat, lon, capacityMw, technology = "solar", candidates) =>
      post("/api/advanced-grid/optimise", { lat, lon, capacity_mw: capacityMw, technology, candidates }),
    reinforcementEstimate: (distKm = 5, voltageKv = 132, capacityMw = 50, headroomMw = 0, terrain = "rural", type = "cable") =>
      get(`/api/advanced-grid/reinforcement/estimate?distance_km=${distKm}&voltage_kv=${voltageKv}&capacity_mw=${capacityMw}&headroom_mw=${headroomMw}&terrain=${enc(terrain)}&connection_type=${enc(type)}`),
    reinforcementBenchmarks: () => get("/api/advanced-grid/reinforcement/benchmarks"),
  },

  planning: {
    summary: () => get("/planning/energy/summary"),
    nsip: (tech, status) => get(`/api/planning/nsip${tech || status ? '?' : ''}${tech ? `technology=${enc(tech)}` : ''}${tech && status ? '&' : ''}${status ? `status=${enc(status)}` : ''}`),
    nsipConflicts: (lat, lon, km = 20) => get(`/api/planning/nsip-conflicts?lat=${lat}&lon=${lon}&radius_km=${km}`),
    // ML Planning Intelligence
    predict: (lat, lon, mw = 50, technology = "solar", landHa, isGreenfield = true) =>
      post("/api/planning/predict", { lat, lon, capacity_mw: mw, technology, land_area_ha: landHa, is_greenfield: isGreenfield }),
    constraints: (lat, lon, radius = 2000) =>
      get(`/api/planning/constraints?lat=${lat}&lon=${lon}&radius_m=${radius}`),
    compliance: (lat, lon, mw = 50, technology = "solar", landAreaHa) =>
      get(`/api/planning/compliance?lat=${lat}&lon=${lon}&capacity_mw=${mw}&technology=${enc(technology)}${landAreaHa != null ? `&land_area_ha=${landAreaHa}` : ""}`),
    authorityProfile: (name, technology = "solar") =>
      get(`/api/planning/authority-profile?name=${enc(name)}&technology=${enc(technology)}`),
    comparable: (lat, lon, mw = 50, technology = "solar", radiusKm = 20) =>
      get(`/api/planning/comparable-decisions?lat=${lat}&lon=${lon}&capacity_mw=${mw}&technology=${enc(technology)}&radius_km=${radiusKm}`),
    modelStatus: () => get("/api/planning/model-stats"),
    // REPD ML v2 — trained on 13,995 real UK planning outcomes
    predictApproval: (lat, lon, mw, tech) =>
      post("/api/planning/predict-approval", { lat, lon, capacity_mw: mw, technology: tech }),
    repdModelStats: () => get("/api/planning/model-stats"),
    comparableProjects: (lat, lon, mw, tech, limit = 10) =>
      get(`/api/planning/comparable-projects?lat=${lat}&lon=${lon}&capacity_mw=${mw}&technology=${enc(tech)}&limit=${limit}`),
    retrainModel: () => post("/api/planning/retrain-v2", {}),
    // Site benchmarking against 14K REPD projects
    benchmarkSite: (lat, lon, mw = 50, tech = "solar") =>
      post("/api/planning/benchmark-site", { lat, lon, capacity_mw: mw, technology: tech }),
    constraintMap: () => get("/api/planning/constraint-map"),
  },

  bmrs: {
    windSolar: () => get("/api/bmrs/wind-solar"),
    windForecast: () => get("/api/bmrs/wind-forecast"),
    warnings: () => get("/api/bmrs/warnings"),
    temperature: () => get("/api/bmrs/temperature"),
    frequency: () => get("/api/bmrs/frequency"),
    generation: () => get("/api/bmrs/generation"),
    snapshot: () => get("/api/bmrs/snapshot"),
  },

  tenderSearch: {
    energy: (daysBack = 30, limit = 50, keywords) =>
      get(`/api/tenders/energy?days_back=${daysBack}&limit=${limit}${keywords ? `&keywords=${enc(keywords)}` : ""}`),
  },

  opportunities: {
    scan: (opts = {}) => {
      const q = new URLSearchParams();
      if (opts.technology) q.set("technology", opts.technology);
      if (opts.min_mw != null) q.set("min_mw", opts.min_mw);
      if (opts.max_mw != null) q.set("max_mw", opts.max_mw);
      if (opts.region) q.set("region", opts.region);
      return get(`/api/opportunities/scan?${q}`);
    },
    actionPackage: (opportunity, capacityMw) =>
      post(`/api/opportunities/action-package${capacityMw ? `?capacity_mw=${capacityMw}` : ""}`, opportunity),
  },

  // Generational capabilities
  alerts: {
    subscribe: (config) => post("/api/alerts/subscribe", config),
    check: () => get("/api/alerts/check"),
  },
  g99: {
    generate: (project) =>
      post("/api/g99/generate", {
        name: project.name || "Site",
        capacity_mw: project.capacity_mw || 50,
        technology: project.technology || "solar",
        lat: project.lat, lon: project.lon,
        developer: project.developer,
        nearest_substation: project.nearest_substation,
        headroom_mw: project.headroom_mw,
      }),
  },
  landOwnership: {
    lookup: (lat, lon, radius = 500) =>
      get(`/api/land/ownership?lat=${lat}&lon=${lon}&radius_m=${radius}`),
  },
  competitive: {
    heatmap: (technology, bbox) => {
      const q = new URLSearchParams();
      if (technology) q.set("technology", technology);
      if (bbox) { q.set("west", bbox[0]); q.set("south", bbox[1]); q.set("east", bbox[2]); q.set("north", bbox[3]); }
      return get(`/api/competitive/heatmap?${q}`);
    },
  },
  marketTiming: {
    analyse: (mw = 50, technology = "solar", region = "England") =>
      get(`/api/market/timing?capacity_mw=${mw}&technology=${enc(technology)}&region=${enc(region)}`),
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

  geoai: {
    analyse: (lat, lon, mode = "asset_condition", params = {}) => {
      const q = new URLSearchParams({ lat, lon, mode, ...params });
      return get(`/geoai/analyse?${q}`);
    },
    modes: () => get("/geoai/modes"),
  },

  classification: {
    classes: () => get("/api/classification/classes"),
    classify: (bands) => post("/api/classification/classify", { bands }),
    location: (lat, lon, date) => get(`/api/classification/location?lat=${lat}&lon=${lon}${date ? `&date=${date}` : ""}`),
    compare: (eurosatClass, dwClass) => get(`/api/classification/compare?eurosat_class=${enc(eurosatClass)}&dw_class=${enc(dwClass)}`),
  },

  bess: {
    score: (lat, lon) => get(`/bess/score?lat=${lat}&lon=${lon}`),
    sizing: (capacityMw, durationHours, strategy, gridConstraintMw) =>
      post("/bess/sizing", { capacity_mw: capacityMw, duration_hours: durationHours, revenue_strategy: strategy, grid_constraint_mw: gridConstraintMw }),
    revenue: (powerMw, energyMwh, strategy) =>
      post("/bess/revenue", { power_mw: powerMw, energy_mwh: energyMwh, strategy }),
    bidder: (powerMw, energyMwh, strategy = "coordinated", hours = 24, efficiency = 0.86) =>
      get(`/bess/bidder/simulate?power_mw=${powerMw}&energy_mwh=${energyMwh}&strategy=${enc(strategy)}&hours=${hours}&efficiency=${efficiency}`),
  },

  bipv: {
    catalogue: () => get("/bipv/catalogue"),
    annual: (parcelId, area, moduleType, surfaceType) =>
      get(`/site/${enc(parcelId)}/bipv/annual?area_m2=${area}&module_type=${enc(moduleType)}&surface_type=${enc(surfaceType)}`),
    profile: (parcelId, date, area, moduleType, surfaceType) =>
      get(`/site/${enc(parcelId)}/bipv/profile?date=${enc(date)}&area_m2=${area}&module_type=${enc(moduleType)}&surface_type=${enc(surfaceType)}`),
  },

  scoring: {
    learned: (lat, lon) => get(`/scoring/learned?lat=${lat}&lon=${lon}`),
    similar: (lat, lon, k = 5) => get(`/sites/similar?lat=${lat}&lon=${lon}&k=${k}`),
  },

  vision: {
    upload: (file, lat, lon, parcelId) => {
      const fd = new FormData();
      fd.append("file", file);
      const q = new URLSearchParams();
      if (lat != null) q.set("lat", lat);
      if (lon != null) q.set("lon", lon);
      if (parcelId) q.set("parcel_id", parcelId);
      return fetch(`/vision/upload?${q}`, { method: "POST", body: fd }).then(json);
    },
    instantAnalyse: (uploadId, lat, lon, parcelId, imageType) =>
      post("/vision/analyse/instant", { upload_id: uploadId, lat, lon, parcel_id: parcelId, image_type: imageType }),
    deepAnalyse: (uploadId, lat, lon, parcelId, modes) =>
      post("/vision/analyse/deep", { upload_id: uploadId, lat, lon, parcel_id: parcelId, modes }),
    fetchSatellite: (lat, lon, radiusKm = 2) =>
      post("/vision/fetch/satellite", { lat, lon, radius_km: radiusKm }),
    fetchStreetView: (lat, lon) =>
      post("/vision/fetch/street_view", { lat, lon }),
    getTwinData: (parcelId, radiusM = 500) =>
      get(`/vision/twin/${enc(parcelId)}?radius_m=${radiusM}`),
    getLayers: (parcelId) =>
      get(`/vision/layers/${enc(parcelId)}`),
    listAnalyses: (parcelId) =>
      get(`/vision/site/${enc(parcelId)}/analyses`),
    jobStatus: (jobId) => get(`/job/${enc(jobId)}`),
    // Google Open Buildings
    buildings: (lat, lon, r = 500) => get(`/api/vision/buildings?lat=${lat}&lon=${lon}&radius_m=${r}`),
    buildingsSummary: (lat, lon, r = 1000) => get(`/api/vision/buildings/summary?lat=${lat}&lon=${lon}&radius_m=${r}`),
    torchgeoClassify: (lat, lon, radiusM = 500, model = "resnet50", year = 2024) =>
      post("/api/vision/torchgeo-classify", { lat, lon, radius_m: radiusM, model, year }),
    torchgeoChange: (lat, lon, radiusM = 500, yearBefore = 2020, yearAfter = 2024) =>
      post("/api/vision/torchgeo-change", { lat, lon, radius_m: radiusM, year_before: yearBefore, year_after: yearAfter }),
    torchgeoCrop: (lat, lon, radiusM = 500, model = "resnet50", year = 2024) =>
      post("/api/vision/torchgeo-crop", { lat, lon, radius_m: radiusM, model, year }),
    torchgeoModels: () => get("/api/vision/torchgeo-models"),
    clayAnalyse: (lat, lon, radiusM = 500) =>
      post("/api/vision/clay-analyse", { lat, lon, radius_m: radiusM }),
    shadowFlicker: (lat, lon, turbineSpecs, receptors = []) =>
      post("/api/vision/shadow-flicker", { lat, lon, turbine_specs: turbineSpecs, receptors }),
    glintGlare: (lat, lon, panelSpecs, receptors = []) =>
      post("/api/vision/glint-glare", { lat, lon, panel_specs: panelSpecs, receptors }),
    photomontageCamera: (siteLat, siteLon, vpLat, vpLon, targetHeight = 80, opts = {}) =>
      post("/api/vision/photomontage-camera", { site_lat: siteLat, site_lon: siteLon, viewpoint_lat: vpLat, viewpoint_lon: vpLon, target_height_m: targetHeight, ...opts }),
    visualImpact: (siteLat, siteLon, targetHeight, viewpoints, siteElevation = 0) =>
      post("/api/vision/visual-impact", { site_lat: siteLat, site_lon: siteLon, target_height_m: targetHeight, viewpoints, site_elevation_m: siteElevation }),
  },

  homeRetrofit: {
    assess: (body) => post("/home-retrofit/assess", body),
    options: (parcelId) => get(`/home-retrofit/options/${enc(parcelId)}`),
    precedents: (parcelId, radiusKm = 10) => get(`/home-retrofit/precedents/${enc(parcelId)}?radius_km=${radiusKm}`),
    archetypes: () => get("/home-retrofit/archetypes"),
    interventions: () => get("/home-retrofit/interventions"),
  },

  workflow: {
    presets: () => get("/workflows"),
    run: (parcelId, preset = "full_feasibility", capacityKw = 100, dayOfYear = 172) =>
      fetch(`/site/${enc(parcelId)}/workflow`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preset, capacity_kw: capacityKw, day_of_year: dayOfYear }),
      }),
  },

  eso: {
    tecGeojson: (bbox, plantType, status) => {
      const q = new URLSearchParams({ west: bbox[0], south: bbox[1], east: bbox[2], north: bbox[3] });
      if (plantType) q.set("plant_type", plantType);
      if (status) q.set("status", status);
      return get(`/eso/tec?${q}`);
    },
    tecSummary: () => get("/eso/tec/summary"),
    tecProject: (id) => get(`/eso/tec/project/${enc(id)}`),
  },

  repd: {
    geojson: (bbox, technology, status, minMw = 0) => {
      const q = new URLSearchParams({ west: bbox[0], south: bbox[1], east: bbox[2], north: bbox[3] });
      if (technology) q.set("technology", technology);
      if (status) q.set("status", status);
      if (minMw > 0) q.set("min_mw", minMw);
      return get(`/repd/projects?${q}`);
    },
    summary: () => get("/repd/summary"),
    project: (refId) => get(`/repd/project/${enc(refId)}`),
    pipeline: () => get("/grid/pipeline"),
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

  tracker: {
    repd: (params = {}) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v != null && v !== "") q.set(k, v);
      return get(`/tracker/repd?${q}`);
    },
    repdSummary: () => get("/tracker/repd/summary"),
    repdGeojson: (tech, status) => {
      const q = new URLSearchParams();
      if (tech) q.set("tech_category", tech);
      if (status) q.set("status", status);
      return get(`/tracker/repd/geojson?${q}`);
    },
    repdIngest: () => post("/tracker/repd/ingest"),
    tec: (params = {}) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v != null && v !== "") q.set(k, v);
      return get(`/tracker/tec?${q}`);
    },
    tecSummary: () => get("/tracker/tec/summary"),
    tecQueue: (site) => get(`/tracker/tec/queue/${enc(site)}`),
    gridUpgrades: (params = {}) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v != null && v !== "") q.set(k, v);
      return get(`/tracker/grid-upgrades?${q}`);
    },
    gridUpgradesSummary: () => get("/tracker/grid-upgrades/summary"),
    dnoInvestment: (dno) => get(`/tracker/dno-investment${dno ? `?dno=${enc(dno)}` : ""}`),
  },

  rag: {
    query: (query, source, topK = 5) => post("/rag/query", { query, source, top_k: topK }),
    search: (q, topK = 5, source, docType) => {
      const params = new URLSearchParams({ q, top_k: topK });
      if (source) params.set("source", source);
      if (docType) params.set("doc_type", docType);
      return get(`/rag/search?${params}`);
    },
    ingest: () => post("/rag/ingest"),
  },

  investment: {
    projectFinance: (mw = 50, tech = "wind", region = "Scotland", ppa = 55) =>
      get(`/api/investment/finance/project?capacity_mw=${mw}&technology=${enc(tech)}&region=${enc(region)}&ppa_price=${ppa}`),
    debtStructure: (mw = 50, tech = "wind", dscr = 1.3, gearing = 0.7, ppa = 55) =>
      get(`/api/investment/finance/debt?capacity_mw=${mw}&technology=${enc(tech)}&target_dscr=${dscr}&gearing=${gearing}&ppa_price=${ppa}`),
    equityReturns: (mw = 50, tech = "wind", gearing = 0.7, ppa = 55, tax = 0.25) =>
      get(`/api/investment/finance/equity?capacity_mw=${mw}&technology=${enc(tech)}&gearing=${gearing}&ppa_price=${ppa}&tax_rate=${tax}`),
    stressTest: (mw = 50, tech = "wind", gearing = 0.7) =>
      get(`/api/investment/scenario/stress-test?capacity_mw=${mw}&technology=${enc(tech)}&gearing=${gearing}`),
    montecarlo: (mw = 50, tech = "wind", nSims = 2000, gearing = 0.7) =>
      get(`/api/investment/scenario/montecarlo?capacity_mw=${mw}&technology=${enc(tech)}&n_sims=${nSims}&gearing=${gearing}`),
    breakEven: (mw = 50, tech = "wind", gearing = 0.7) =>
      get(`/api/investment/scenario/break-even?capacity_mw=${mw}&technology=${enc(tech)}&gearing=${gearing}`),
    ddChecklist: (mw = 50, tech = "wind", region = "Scotland") =>
      get(`/api/investment/dd/checklist?capacity_mw=${mw}&technology=${enc(tech)}&region=${enc(region)}`),
    ddTechnical: (mw = 50, tech = "wind") =>
      get(`/api/investment/dd/technical?capacity_mw=${mw}&technology=${enc(tech)}`),
    ddCommercial: (mw = 50, tech = "wind", ppa = 55) =>
      get(`/api/investment/dd/commercial?capacity_mw=${mw}&technology=${enc(tech)}&ppa_price=${ppa}`),
    memo: (mw = 50, tech = "wind", region = "Scotland", ppa = 55, gearing = 0.7) =>
      get(`/api/investment/report/memo?capacity_mw=${mw}&technology=${enc(tech)}&region=${enc(region)}&ppa_price=${ppa}&gearing=${gearing}`),
    riskMatrix: (mw = 50, tech = "wind", region = "Scotland") =>
      get(`/api/investment/report/risk-matrix?capacity_mw=${mw}&technology=${enc(tech)}&region=${enc(region)}`),
    actionPlan: (mw = 50, tech = "wind", region = "Scotland") =>
      get(`/api/investment/report/action-plan?capacity_mw=${mw}&technology=${enc(tech)}&region=${enc(region)}`),
  },

  dc: {
    score: (lat, lon, mw = 10, profile = "colocation") =>
      post(`/api/dc/score?lat=${lat}&lon=${lon}&capacity_mw=${mw}&profile=${enc(profile)}`),
    scoreExtended: (lat, lon, mw = 100, profile = "google_hyperscale") =>
      post(`/api/dc/score-extended?lat=${lat}&lon=${lon}&capacity_mw=${mw}&profile=${enc(profile)}`),
    scan: (profile = "colocation", mw = 10, limit = 50) =>
      post(`/api/dc/scan?profile=${enc(profile)}&capacity_mw=${mw}&limit=${limit}`),
    compare: (sites, capacityMw = 100, profile = "google_hyperscale", customWeights) =>
      post("/api/dc/compare", { sites, capacity_mw: capacityMw, profile, custom_weights: customWeights }),
    infrastructure: (lat, lon, radius = 20) =>
      get(`/api/dc/infrastructure?lat=${lat}&lon=${lon}&radius_km=${radius}`),
    profiles: () => get("/api/dc/profiles"),
    capacityMap: (profile = "colocation", minHr = 5) =>
      get(`/api/dc/capacity-map?profile=${enc(profile)}&min_headroom_mw=${minHr}`),
    cfe: (lat, lon, mw = 100, target = 90) =>
      get(`/api/dc/cfe?lat=${lat}&lon=${lon}&capacity_mw=${mw}&target_cfe_pct=${target}`),
    cooling: (lat, lon, mw = 10, coolingType = "hybrid") =>
      get(`/api/dc/cooling?lat=${lat}&lon=${lon}&capacity_mw=${mw}&cooling_type=${enc(coolingType)}`),
    constraints: (lat, lon, radiusM = 1000) =>
      get(`/api/dc/constraints?lat=${lat}&lon=${lon}&radius_m=${radiusM}`),
    waterStress: (lat, lon, mw = 10) =>
      get(`/api/dc/water-stress?lat=${lat}&lon=${lon}&capacity_mw=${mw}`),
    incentives: (lat, lon, mw = 100) =>
      get(`/api/dc/incentives?lat=${lat}&lon=${lon}&capacity_mw=${mw}`),
    regulatory: (lat, lon, mw = 100) =>
      get(`/api/dc/regulatory?lat=${lat}&lon=${lon}&capacity_mw=${mw}`),
    report: (lat, lon, siteName = "Candidate Site", mw = 100, profile = "google_hyperscale") =>
      fetch(`/api/dc/report?lat=${lat}&lon=${lon}&site_name=${enc(siteName)}&capacity_mw=${mw}&profile=${enc(profile)}`, { method: "POST" })
        .then(r => { if (!r.ok) throw new Error(`Report failed: ${r.status}`); return r.blob(); }),
    googleSites: (mw = 100, profile = "google_hyperscale") =>
      get(`/api/dc/google-sites?capacity_mw=${mw}&profile=${enc(profile)}`),
    prospect: (query, mw = 100, profile = "google_hyperscale", minHr = 50, limit = 20) =>
      post("/api/dc/prospect", { query, capacity_mw: mw, profile, min_headroom_mw: minHr, limit }),
    // Advanced DC design endpoints
    hourlyCfe: (lat, lon, mw, solarMw, windMw, bessMwh) =>
      post("/api/dc/hourly-cfe", { lat, lon, capacity_mw: mw, solar_mw: solarMw, wind_mw: windMw, bess_mwh: bessMwh }),
    ashrae: (lat, lon) => get(`/api/dc/ashrae?lat=${lat}&lon=${lon}`),
    tierCheck: (params) => post("/api/dc/tier-check", params),
    powerDensityDesign: (params) => post("/api/dc/power-density-design", params),
    powerChain: (params) => post("/api/dc/power-chain", params),
    constructionTimeline: (params) => post("/api/dc/construction-timeline", params),
    financialModel: (params) => post("/api/dc/financial-model", params),
  },

  landMgmt: {
    // Boundaries
    createBoundary: (data) => post("/api/v1/land/boundaries", data),
    listBoundaries: (projectId) => get(`/api/v1/land/boundaries${projectId ? `?project_id=${enc(projectId)}` : ""}`),
    getBoundary: (id) => get(`/api/v1/land/boundaries/${enc(id)}`),
    updateBoundary: (id, data) =>
      fetch(`/api/v1/land/boundaries/${enc(id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }).then(json),
    deleteBoundary: (id) =>
      fetch(`/api/v1/land/boundaries/${enc(id)}`, { method: "DELETE" }).then(json),
    analyseBoundary: (id) => get(`/api/v1/land/boundaries/${enc(id)}/analysis`),
    // Land options
    createOption: (data) => post("/api/v1/land/options", data),
    listOptions: (projectId) => get(`/api/v1/land/options${projectId ? `?project_id=${enc(projectId)}` : ""}`),
    getOption: (id) => get(`/api/v1/land/options/${enc(id)}`),
    updateOption: (id, data) =>
      fetch(`/api/v1/land/options/${enc(id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }).then(json),
    deleteOption: (id) =>
      fetch(`/api/v1/land/options/${enc(id)}`, { method: "DELETE" }).then(json),
    // Project summary
    projectLandSummary: (projectId) => get(`/api/v1/land/projects/${enc(projectId)}/summary`),
  },

  design: {
    assetTypes: () => get("/api/v1/design/asset-types"),
    // Asset CRUD
    listAssets: (projectId) => get(`/api/v1/design/projects/${enc(projectId)}/assets`),
    createAsset: (projectId, data) => post(`/api/v1/design/projects/${enc(projectId)}/assets`, data),
    saveBulk: (projectId, assets) => post(`/api/v1/design/projects/${enc(projectId)}/assets/bulk`, { assets }),
    updateAsset: (assetId, data) =>
      fetch(`/api/v1/design/assets/${enc(assetId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }).then(json),
    deleteAsset: (assetId) =>
      fetch(`/api/v1/design/assets/${enc(assetId)}`, { method: "DELETE" }).then(json),
    // Validation
    validate: (lat, lon, assetType = "solar_array", capacityMw = 50) =>
      get(`/api/v1/design/validate?lat=${lat}&lon=${lon}&asset_type=${enc(assetType)}&capacity_mw=${capacityMw}`),
    validateProject: (projectId) => post(`/api/v1/design/projects/${enc(projectId)}/validate`),
    // BOM
    matchBom: (assetType, capacityMw) =>
      get(`/api/v1/design/bom/match?asset_type=${enc(assetType)}&capacity_mw=${capacityMw}`),
    linkBom: (assetId, bomItemId, qty = 1) =>
      fetch(`/api/v1/design/assets/${enc(assetId)}/link-bom?bom_item_id=${enc(bomItemId)}&qty=${qty}`, { method: "PATCH" }).then(json),
    // Finalize
    finalize: (projectId, data = {}) => post(`/api/v1/design/projects/${enc(projectId)}/finalize`, data),
  },

  projects: {
    list: (params = {}) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v != null && v !== "") q.set(k, v);
      return get(`/api/v1/projects?${q}`);
    },
    summary: () => get("/api/v1/projects/summary"),
    get: (id) => get(`/api/v1/projects/${enc(id)}`),
    create: (data) => post("/api/v1/projects", data),
    update: (id, data) =>
      fetch(`/api/v1/projects/${enc(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }).then(json),
    delete: (id) =>
      fetch(`/api/v1/projects/${enc(id)}`, { method: "DELETE" }).then(json),
    timeline: (id) => get(`/api/v1/projects/${enc(id)}/timeline`),
    importRepd: (repdId) => post(`/api/v1/projects/import-repd/${enc(repdId)}`),
    importRepdBulk: (opts = {}) => {
      const q = new URLSearchParams();
      if (opts.technology) q.set("technology", opts.technology);
      if (opts.min_mw != null) q.set("min_capacity_mw", opts.min_mw);
      if (opts.max_mw != null) q.set("max_capacity_mw", opts.max_mw);
      if (opts.status) q.set("status", opts.status);
      if (opts.region) q.set("region", opts.region);
      if (opts.limit) q.set("limit", opts.limit);
      return post(`/api/v1/projects/import-repd-bulk?${q}`);
    },
    importTec: (tecId) => post(`/api/v1/projects/import-tec/${enc(tecId)}`),
    // Documents
    listDocuments: (id) => get(`/api/v1/projects/${enc(id)}/documents`),
    uploadDocument: (id, file, docType = "other", title) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("doc_type", docType);
      if (title) fd.append("title", title);
      return fetch(`/api/v1/projects/${enc(id)}/documents`, { method: "POST", body: fd }).then(json);
    },
    downloadDocument: (docId) => `/api/v1/projects/documents/${enc(docId)}/download`,
    deleteDocument: (docId) =>
      fetch(`/api/v1/projects/documents/${enc(docId)}`, { method: "DELETE" }).then(json),
  },

  assessments: {
    createSnapshot: (parcelId, projectId, label) =>
      post("/api/v1/assessments/snapshot", { parcel_id: parcelId, project_id: projectId, label }),
    listSnapshots: (parcelId) => get(`/api/v1/assessments/${enc(parcelId)}`),
    getSnapshot: (id) => get(`/api/v1/assessments/snapshot/${enc(id)}`),
    compare: (a, b) => get(`/api/v1/assessments/compare/${enc(a)}/${enc(b)}`),
    addEvidence: (snapId, data) =>
      post(`/api/v1/assessments/snapshot/${enc(snapId)}/evidence`, data),
    addNote: (snapId, text) =>
      post(`/api/v1/assessments/snapshot/${enc(snapId)}/note`, { text }),
  },

  reports: {
    siteAssessment: (lat, lon, siteName, capacityMw = 50) =>
      fetch(`/api/reports/site-assessment?lat=${lat}&lon=${lon}&site_name=${enc(siteName)}&capacity_mw=${capacityMw}`, { method: "POST" })
        .then(r => { if (!r.ok) throw new Error(`Report failed: ${r.status}`); return r.blob(); }),
    gridConnection: (lat, lon, siteName, capacityMw = 50) =>
      fetch(`/api/reports/grid-connection?lat=${lat}&lon=${lon}&site_name=${enc(siteName)}&capacity_mw=${capacityMw}`, { method: "POST" })
        .then(r => { if (!r.ok) throw new Error(`Report failed: ${r.status}`); return r.blob(); }),
    financial: (lat, lon, siteName, capacityMw = 50, technology = "solar", ppaPrice = 55) =>
      fetch(`/api/reports/financial?lat=${lat}&lon=${lon}&site_name=${enc(siteName)}&capacity_mw=${capacityMw}&technology=${enc(technology)}&ppa_price=${ppaPrice}`, { method: "POST" })
        .then(r => { if (!r.ok) throw new Error(`Report failed: ${r.status}`); return r.blob(); }),
  },

  prospector: {
    planningRisk: (lat, lon, mw, tech) =>
      post("/api/prospector/planning-risk", { lat, lon, capacity_mw: mw, technology: tech }),
    batchScreen: (candidates, topN = 20) =>
      post("/api/prospector/batch-screen", { candidates, top_n: topN }),
  },

  bipv: {
    catalogue: () => get("/bipv/catalogue"),
    annual: (parcelId, area, moduleType, surfaceType) => get(`/site/${enc(parcelId)}/bipv/annual?area_m2=${area}&module_type=${enc(moduleType)}&surface_type=${enc(surfaceType)}`),
    profile: (parcelId, date, area, moduleType, surfaceType) => get(`/site/${enc(parcelId)}/bipv/profile?date=${enc(date)}&area_m2=${area}&module_type=${enc(moduleType)}&surface_type=${enc(surfaceType)}`),
  },

  terrain: {
    lidar: (lat, lon, radiusM = 500, resolutionM = 2) =>
      post("/api/terrain/lidar", { lat, lon, radius_m: radiusM, resolution_m: resolutionM }),
    analyse: (lat, lon, radiusM = 500) =>
      post("/api/terrain/analyse", { lat, lon, radius_m: radiusM }),
    viewshed: (lat, lon, heightM = 3, radiusM = 2000, observerM = 1.6) =>
      post("/api/terrain/viewshed", { lat, lon, target_height_m: heightM, radius_m: radiusM, observer_height_m: observerM }),
    hydrology: (lat, lon, radiusM = 500) =>
      post("/api/terrain/hydrology", { lat, lon, radius_m: radiusM }),
  },

  notifications: {
    list: (unreadOnly = false, limit = 50) =>
      get(`/notifications?unread_only=${unreadOnly}&limit=${limit}`),
    markRead: (id) => post(`/notifications/${enc(id)}/read`),
    markAllRead: () => post("/notifications/mark-all-read"),
    rules: () => get("/alerts/rules"),
    createRule: (rule) => post("/alerts/rules", rule),
    deleteRule: (id) =>
      fetch(`/alerts/rules/${enc(id)}`, { method: "DELETE" }).then(json),
    checkNow: () => post("/alerts/check-now"),
  },

  ppa: {
    match: (lat, lon, technology = "solar", capacityMw = 50, structure, termYears, additionality) => {
      const q = new URLSearchParams({ lat, lon, technology, capacity_mw: capacityMw });
      if (structure) q.set("structure", structure);
      if (termYears != null) q.set("term_years", termYears);
      if (additionality != null) q.set("additionality", additionality);
      return get(`/api/ppa/match?${q}`);
    },
    buyers: () => get("/api/ppa/buyers"),
    priceEstimate: (technology = "solar", capacityMw = 50, region = "Midlands", termYears = 15, structure = "fixed") =>
      get(`/api/ppa/price-estimate?technology=${enc(technology)}&capacity_mw=${capacityMw}&region=${enc(region)}&term_years=${termYears}&structure=${enc(structure)}`),
    structures: () => get("/api/ppa/structures"),
  },

  dispatchModel: {
    snapshot: (params = {}) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v != null) q.set(k, v);
      return get(`/api/dispatch-model/snapshot?${q}`);
    },
    forecast: (hours = 48, params = {}) => {
      const q = new URLSearchParams({ hours });
      for (const [k, v] of Object.entries(params)) if (v != null) q.set(k, v);
      return get(`/api/dispatch-model/forecast?${q}`);
    },
    zonalPrices: (hours = 48, zones, params = {}) => {
      const q = new URLSearchParams({ hours });
      if (zones) q.set("zones", zones);
      for (const [k, v] of Object.entries(params)) if (v != null) q.set(k, v);
      return get(`/api/dispatch-model/zonal-prices?${q}`);
    },
    curtailment: (capacityMw = 50, technology = "solar", region = "Midlands", hours = 48, connType = "firm") =>
      get(`/api/dispatch-model/curtailment?capacity_mw=${capacityMw}&technology=${enc(technology)}&region=${enc(region)}&hours=${hours}&connection_type=${enc(connType)}`),
    siteImpact: (lat, lon, capacityMw = 50, technology = "solar", region) => {
      const q = new URLSearchParams({ lat, lon, capacity_mw: capacityMw, technology });
      if (region) q.set("region", region);
      return get(`/api/dispatch-model/site-impact?${q}`);
    },
    revenueForecast: (capacityMw = 50, technology = "solar", region = "Midlands", ppaPriceMwh, years = 25) => {
      const q = new URLSearchParams({ capacity_mw: capacityMw, technology, region, years });
      if (ppaPriceMwh != null) q.set("ppa_price_gbp_mwh", ppaPriceMwh);
      return get(`/api/dispatch-model/revenue-forecast?${q}`);
    },
  },

  bessRevenue: {
    stack: (powerMw = 50, durationHours = 2, region = "Midlands", year = "2026", strategy = "balanced") =>
      get(`/api/bess/revenue-stack?power_mw=${powerMw}&duration_hours=${durationHours}&region=${enc(region)}&year=${enc(year)}&strategy=${enc(strategy)}`),
    forecast: (powerMw = 50, durationHours = 2, region = "Midlands", years = 10, strategy = "balanced") =>
      get(`/api/bess/revenue-forecast?power_mw=${powerMw}&duration_hours=${durationHours}&region=${enc(region)}&years=${years}&strategy=${enc(strategy)}`),
    benchmark: (powerMw = 50, durationHours = 2, region = "Midlands", year = "2026") =>
      get(`/api/bess/benchmark?power_mw=${powerMw}&duration_hours=${durationHours}&region=${enc(region)}&year=${enc(year)}`),
    streams: () => get("/api/bess/streams"),
    optimalDuration: (powerMw = 50, region = "Midlands", year = "2026") =>
      get(`/api/bess/optimal-duration?power_mw=${powerMw}&region=${enc(region)}&year=${enc(year)}`),
  },

  cableRoute: {
    route: (siteLat, siteLon, subLat, subLon, capacityMw, voltageKv) => {
      const q = new URLSearchParams({ site_lat: siteLat, site_lon: siteLon, sub_lat: subLat, sub_lon: subLon, capacity_mw: capacityMw });
      if (voltageKv != null) q.set("voltage_kv", voltageKv);
      return get(`/api/cable/route?${q}`);
    },
    bestRoute: (lat, lon, capacityMw, radiusKm = 20, maxCandidates = 5) => {
      const q = new URLSearchParams({ lat, lon, capacity_mw: capacityMw, radius_km: radiusKm, max_candidates: maxCandidates });
      return get(`/api/cable/best-route?${q}`);
    },
    costEstimate: (distanceKm, voltageKv = 33, terrain = "rural") =>
      get(`/api/cable/cost-estimate?distance_km=${distanceKm}&voltage_kv=${voltageKv}&terrain=${enc(terrain)}`),
    voltageOptions: (capacityMw, distanceKm = 5) =>
      get(`/api/cable/voltage-options?capacity_mw=${capacityMw}&distance_km=${distanceKm}`),
  },

  construction: {
    detect: (lat, lon, radiusM = 500) =>
      get(`/api/construction/detect?lat=${lat}&lon=${lon}&radius_m=${radiusM}`),
    monitorPipeline: () => get("/api/construction/monitor-pipeline"),
    timeline: (technology = "solar", capacityMw = 50) =>
      get(`/api/construction/timeline?technology=${enc(technology)}&capacity_mw=${capacityMw}`),
    estimate: (projectId) => get(`/api/construction/estimate/${enc(projectId)}`),
  },

  yield: {
    solar: (lat, lon, capacityMwp, tracking = "fixed", tilt, azimuth = 180) => {
      const q = new URLSearchParams({ lat, lon, capacity_mwp: capacityMwp, tracking, azimuth });
      if (tilt != null) q.set("tilt", tilt);
      return get(`/api/yield/solar?${q}`);
    },
    wind: (lat, lon, capacityMw, hubHeight = 80, turbineClass = "IEC2", numTurbines = 1) =>
      get(`/api/yield/wind?lat=${lat}&lon=${lon}&capacity_mw=${capacityMw}&hub_height=${hubHeight}&turbine_class=${enc(turbineClass)}&num_turbines=${numTurbines}`),
    compare: (lat, lon, capacityMw) =>
      get(`/api/yield/compare?lat=${lat}&lon=${lon}&capacity_mw=${capacityMw}`),
    uncertainty: (technology, lat, lon, capacityMw) =>
      get(`/api/yield/uncertainty?technology=${enc(technology)}&lat=${lat}&lon=${lon}&capacity_mw=${capacityMw}`),
    degradation: (capacityMwp, annualYieldMwh, years = 25, degradationRate = 0.5) =>
      get(`/api/yield/degradation?capacity_mwp=${capacityMwp}&annual_yield_mwh=${annualYieldMwh}&years=${years}&degradation_rate=${degradationRate}`),
  },

  portfolio: {
    optimise: (budgetGbp, sites, constraints = {}) =>
      post("/api/portfolio/optimise", { budget_gbp: budgetGbp, sites, constraints }),
    diversification: (sites) =>
      post("/api/portfolio/diversification", { sites }),
    sensitivity: (portfolio, variables, nMontecarlo = 2000) =>
      post("/api/portfolio/sensitivity", { portfolio, variables, n_montecarlo: nMontecarlo }),
    compare: (portfolios) =>
      post("/api/portfolio/compare", { portfolios }),
    auto: (budgetGbp, targetIrr = 8, region, technologies) => {
      const q = new URLSearchParams({ budget_gbp: budgetGbp, target_irr: targetIrr });
      if (region) q.set("region", region);
      if (technologies) q.set("technologies", technologies);
      return get(`/api/portfolio/auto?${q}`);
    },
  },

  gridQueue: {
    analyse: (connectionSite) => get(`/api/grid-queue/analyse/${enc(connectionSite)}`),
    predict: (lat, lon, capacityMw, technology = "solar", voltageKv, radiusKm = 30) => {
      const q = new URLSearchParams({ lat, lon, capacity_mw: capacityMw, technology, radius_km: radiusKm });
      if (voltageKv != null) q.set("voltage_kv", voltageKv);
      return get(`/api/grid-queue/predict?${q}`);
    },
    benchmark: (capacityMw, voltageKv = 33, distanceKm = 5, region) => {
      const q = new URLSearchParams({ capacity_mw: capacityMw, voltage_kv: voltageKv, distance_km: distanceKm });
      if (region) q.set("region", region);
      return get(`/api/grid-queue/benchmark?${q}`);
    },
    opportunities: (region, technology, minHeadroomMw = 10, limit = 30) => {
      const q = new URLSearchParams({ min_headroom_mw: minHeadroomMw, limit });
      if (region) q.set("region", region);
      if (technology) q.set("technology", technology);
      return get(`/api/grid-queue/opportunities?${q}`);
    },
    summary: () => get("/api/grid-queue/summary"),
  },

  electrical: {
    design: (layoutSummary, opts = {}) =>
      post("/api/electrical/design", {
        layout_summary: layoutSummary,
        panel_watts: opts.panelWatts,
        panel_voc: opts.panelVoc,
        panel_isc: opts.panelIsc,
        modules_per_string: opts.modulesPerString,
        inverter_type: opts.inverterType,
        transformer_voltage_kv: opts.transformerVoltageKv,
        poc_lat: opts.pocLat,
        poc_lon: opts.pocLon,
      }),
    inverters: () => get("/api/electrical/inverters"),
    transformers: () => get("/api/electrical/transformers"),
    cables: () => get("/api/electrical/cables"),
  },

  dcLayout: {
    generate: (data) => post("/api/dc-layout/generate", data),
    modules: () => get("/api/dc-layout/modules"),
    tiers: () => get("/api/dc-layout/tiers"),
    quick: (params = {}) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v != null) q.set(k, v);
      return get(`/api/dc-layout/quick?${q}`);
    },
  },

  yieldIntel: {
    shadeAnalysis: (rowPitchM, panelHeightM = 1.134, tiltDeg = 25, latitude) =>
      get(`/api/yield-intel/shade-analysis?row_pitch_m=${rowPitchM}&panel_height_m=${panelHeightM}&tilt_deg=${tiltDeg}&latitude=${latitude}`),
    compareLayouts: (latitude, siteAreaHa, panelWatts = 600, panelWidthM = 2.278, panelHeightM = 1.134) =>
      get(`/api/yield-intel/compare-layouts?latitude=${latitude}&site_area_ha=${siteAreaHa}&panel_watts=${panelWatts}&panel_width_m=${panelWidthM}&panel_height_m=${panelHeightM}`),
    hourlyProfile: (capacityMwp, latitude, tiltDeg = 25, tracking = "fixed", month = 6) =>
      get(`/api/yield-intel/hourly-profile?capacity_mwp=${capacityMwp}&latitude=${latitude}&tilt_deg=${tiltDeg}&tracking=${enc(tracking)}&month=${month}`),
  },

  solarLayout: {
    generate: (data) => post("/api/solar-layout/generate", data),
    presets: () => get("/api/solar-layout/presets"),
    quick: (lat, lon, areaHa = 50, capacityMwp, tracking = "fixed", gcrTarget = 0.40, tiltDeg, setbackM = 5) => {
      const q = new URLSearchParams({ lat, lon, area_ha: areaHa, tracking, gcr_target: gcrTarget, setback_m: setbackM });
      if (capacityMwp != null) q.set("capacity_mwp", capacityMwp);
      if (tiltDeg != null) q.set("tilt_deg", tiltDeg);
      return get(`/api/solar-layout/quick?${q}`);
    },
  },

  /**
   * Health check — GET /health (no retry, fast fail).
   * Returns { status, checks: { database, sam, claude, pool } } or null.
   */
  health: () => fetch("/health").then(json).catch(() => null),

  /**
   * Poll /health every 2s until status === "healthy".
   * Calls onProgress({ status, checks }) on each poll so the UI can
   * show per-subsystem progress. Returns a promise that resolves when ready.
   * Pass an AbortSignal via opts.signal to cancel polling.
   */
  waitForReady: (onProgress, opts = {}) => new Promise((resolve) => {
    const poll = async () => {
      if (opts.signal?.aborted) return;
      try {
        const res = await fetch("/health", { signal: opts.signal });
        const data = res.ok ? await res.json() : null;
        if (data) {
          onProgress?.(data);
          if (data.status === "healthy") { resolve(data); return; }
        } else {
          onProgress?.({ status: "unreachable", checks: {} });
        }
      } catch (err) {
        if (err.name === "AbortError") return;
        onProgress?.({ status: "unreachable", checks: {} });
      }
      setTimeout(poll, 2000);
    };
    poll();
  }),
};

// ── Competitive intelligence integrations ──
// Merge into existing api.planning (don't overwrite the full planning namespace)
api.planning.extract = (text) => post("/api/planning/extract", null, { params: { text } });
api.planning.classify = (text) => get(`/api/planning/classify?text=${encodeURIComponent(text)}`);

api.landowner = {
  lookup:        (lat, lon) => get(`/api/landowner/lookup?lat=${lat}&lon=${lon}`),
  transactions:  (lat, lon, radiusKm = 2) => get(`/api/landowner/transactions?lat=${lat}&lon=${lon}&radius_km=${radiusKm}`),
  company:       (name) => get(`/api/landowner/company?name=${encodeURIComponent(name)}`),
  landValue:     (lat, lon, areaHa, landType) => get(`/api/landowner/land-value?lat=${lat}&lon=${lon}&area_ha=${areaHa}&land_type=${landType}`),
};

api.pricing = {
  regional:       () => get("/api/pricing/regional"),
  timeseries:     (region = "C", hours = 48) => get(`/api/pricing/timeseries?region=${region}&hours=${hours}`),
  dispatchWindow: (hours = 24) => get(`/api/pricing/dispatch-window?hours_ahead=${hours}`),
};

api.esa = {
  autoScope:     (lat, lon, areaHa = 5, use = "solar_farm") => post(`/api/esa/auto-scope?lat=${lat}&lon=${lon}&site_area_ha=${areaHa}&proposed_use=${use}`),
  contamination: (lat, lon) => post(`/api/esa/contamination?lat=${lat}&lon=${lon}`),
  floodRisk:     (lat, lon) => post(`/api/esa/flood-risk?lat=${lat}&lon=${lon}`),
};

// ── G99/G100 Compliance ──
api.compliance = {
  g99Application: (lat, lon, mw, tech, kv, dno) =>
    post(`/api/compliance/g99?lat=${lat}&lon=${lon}&capacity_mw=${mw}&technology=${enc(tech)}&voltage_kv=${kv}${dno ? `&dno=${enc(dno)}` : ""}`),
  g99Check: (mw, kv, tech) =>
    get(`/api/compliance/g99-check?capacity_mw=${mw}&voltage_kv=${kv}&technology=${enc(tech)}`),
  g99Protection: (mw, kv, tech) =>
    get(`/api/compliance/g99-protection?capacity_mw=${mw}&voltage_kv=${kv}&technology=${enc(tech)}`),
};

// ── Council Search — planning intelligence ──
api.council = {
  search: (q, authority, dateFrom, dateTo, limit = 50, offset = 0) => {
    const p = new URLSearchParams({ q, limit, offset });
    if (authority) p.set("authority", authority);
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    return get(`/api/council/search?${p}`);
  },
  authorities: () => get("/api/council/authorities"),
  refresh:     (authorities) => post("/api/council/refresh", { authorities }),
  energySummary: () => get("/api/council/energy-summary"),
};

// ── Export Engine ──
api.exports = {
  siteReport: (lat, lon, mw, tech) =>
    post(`/api/export/site-report?lat=${lat}&lon=${lon}&capacity_mw=${mw}&technology=${enc(tech)}`),
  csv: (sites) => post("/api/export/csv", sites),
};

// ── Usage Tracking ──
api.usage = {
  check: (userId = "default", tier = "free") => get(`/api/usage/check?user_id=${enc(userId)}&tier=${enc(tier)}`),
  record: (userId, endpoint, tier) => post(`/api/usage/record?user_id=${enc(userId)}&endpoint=${enc(endpoint)}&tier=${enc(tier)}`),
  summary: (userId = "default") => get(`/api/usage/summary?user_id=${enc(userId)}`),
};

// ── Energy Data APIs ──
api.energyData = {
  renewablesNinja: (lat, lon, type = "pv", opts = {}) => {
    const p = new URLSearchParams({ lat, lon, type });
    if (opts.date_from) p.set("date_from", opts.date_from);
    if (opts.date_to) p.set("date_to", opts.date_to);
    if (opts.capacity) p.set("capacity", opts.capacity);
    if (opts.tilt != null) p.set("tilt", opts.tilt);
    if (opts.azim != null) p.set("azim", opts.azim);
    if (opts.hub_height) p.set("hub_height", opts.hub_height);
    if (opts.turbine) p.set("turbine", opts.turbine);
    return get(`/api/energy-data/renewables-ninja?${p}`);
  },
  carbonIntensity:  (postcode) => get(`/api/energy-data/carbon-intensity${postcode ? `?postcode=${enc(postcode)}` : ""}`),
  carbonForecast:   (hours = 48) => get(`/api/energy-data/carbon-intensity/forecast?hours=${hours}`),
  emissions:        (year = 2025) => get(`/api/energy-data/emissions?year=${year}`),
  wholesalePrices:  (year = 2025) => get(`/api/energy-data/wholesale-prices?year=${year}`),
  generationMix:    () => get("/api/energy-data/generation-mix"),
  systemDemand:     (dateFrom, dateTo) => get(`/api/energy-data/system-demand?date_from=${enc(dateFrom)}&date_to=${enc(dateTo)}`),
  systemPrice:      (dateFrom, dateTo) => get(`/api/energy-data/system-price?date_from=${enc(dateFrom)}&date_to=${enc(dateTo)}`),
};

// ── Energy Modelling Tools — atlite, GLAES, BESS optimizer, neural forecast, reV ──

api.resource = {
  capacityMap: (lonMin, latMin, lonMax, latMax, technology = "pv", year = 2023, turbine) => {
    const q = new URLSearchParams({ lon_min: lonMin, lat_min: latMin, lon_max: lonMax, lat_max: latMax, technology, year });
    if (turbine) q.set("turbine", turbine);
    return get(`/api/resource/capacity-map?${q}`);
  },
};

api.site.landEligibility = (lonMin, latMin, lonMax, latMax, technology = "solar", countryCode = "GB") =>
  get(`/api/site/land-eligibility?lon_min=${lonMin}&lat_min=${latMin}&lon_max=${lonMax}&lat_max=${latMax}&technology=${enc(technology)}&country_code=${enc(countryCode)}`);

api.site.supplyCurve = (lonMin, latMin, lonMax, latMax, technology = "pv") =>
  get(`/api/site/supply-curve?lon_min=${lonMin}&lat_min=${latMin}&lon_max=${lonMax}&lat_max=${latMax}&technology=${enc(technology)}`);

api.bess.optimize = (capacityMwh, powerMw, prices, pricesIntraday, pricesBalancing, efficiency = 0.88, degradationCost = 5) =>
  post("/api/bess/optimize", {
    capacity_mwh: capacityMwh, power_mw: powerMw, prices,
    prices_intraday: pricesIntraday, prices_balancing: pricesBalancing,
    efficiency, degradation_cost: degradationCost,
  });

api.bess.revenueEstimate = (capacityMwh = 100, powerMw = 50, year = 2025, region = "GB") =>
  get(`/api/bess/revenue-estimate?capacity_mwh=${capacityMwh}&power_mw=${powerMw}&year=${year}&region=${enc(region)}`);

api.bess.financial = (capexGbp, annualRevenueGbp, opexPct = 0.02, years = 20, discountRate = 0.08) =>
  post("/bess/financial", { capex_gbp: capexGbp, annual_revenue_gbp: annualRevenueGbp, opex_pct: opexPct, years, discount_rate: discountRate });

api.bess.colocation = (solarKw, lat = 52.5, lon = -1.5) =>
  get(`/bess/colocation?solar_kw=${solarKw}&lat=${lat}&lon=${lon}`);

api.bess.scan = (region = "south_west", minMw = 10, maxMw = 100) =>
  get(`/bess/scan?region=${enc(region)}&min_mw=${minMw}&max_mw=${maxMw}`);

api.bess.benchmarks = () => get("/bess/benchmarks");

api.demand = api.demand || {};
api.demand.neuralForecast = (gspId = "ABHA", horizon = 48, model = "nhits", daysHistory = 90) =>
  get(`/api/demand/neural-forecast?gsp_id=${enc(gspId)}&horizon=${horizon}&model=${enc(model)}&days_history=${daysHistory}`);

/* ── Site Design ────────────────────────────────────────────────────────── */
api.design = {
  autoLayout: (boundaryGeojson, technology = "solar", params = {}) =>
    post("/api/design/auto-layout", { boundary_geojson: boundaryGeojson, technology, params }),
};

/* ── Finance (extended) ─────────────────────────────────────────────────── */
api.finance = {
  projectModel: (params) => post('/api/finance/project-model', params),
  debtStructure: (params) => post('/api/finance/debt-structure', params),
  ppaPrice: (params) => post('/api/finance/ppa-price', params),
  sensitivity: (params) => post('/api/finance/sensitivity', params),
  dispatch: (params) => post('/api/finance/dispatch', params),
};

/* ── Prospector ────────────────────────────────────────────────────────── */
api.prospector = {
  score: (lat, lon, technology) => get(`/prospector/score?lat=${lat}&lon=${lon}&technology=${enc(technology)}`),
  scan: (region, technology, gridPoints) => get(`/prospector/scan?region=${enc(region)}&technology=${enc(technology)}&grid_points=${gridPoints}`),
  similar: (lat, lon, radiusKm, technology, n) => get(`/prospector/similar?lat=${lat}&lon=${lon}&radius_km=${radiusKm}&technology=${enc(technology)}&num_candidates=${n}`),
  regions: () => get('/prospector/regions'),
};

/* ── PPA Origination ───────────────────────────────────────────────────── */
api.ppa = {
  match: (params) => post("/api/ppa/match", params),
  priceEstimate: (params) => post("/api/ppa/price-estimate", params),
};

/* ── Workflow Engine ───────────────────────────────────────────────────── */
api.workflows = {
  run: (params) => post("/api/workflows/run", params),
  list: () => get("/api/workflows"),
  status: (id) => get(`/api/workflows/${enc(id)}/status`),
  pause: (id) => post(`/api/workflows/${enc(id)}/pause`),
  resume: (id) => post(`/api/workflows/${enc(id)}/resume`),
  cancel: (id) => post(`/api/workflows/${enc(id)}/cancel`),
};

/* ── Export Hub (extends api.exports) ──────────────────────────────────── */
api.exports.generate = (params) => post("/api/exports/generate", params);
api.exports.list = () => get("/api/exports");
api.exports.download = (id) => get(`/api/exports/${enc(id)}/download`);

/* ── Alert Rules ──────────────────────────────────────────────────────── */
api.alerts = {
  createRule: (rule) => post("/api/alerts/rules", rule),
  listRules: () => get("/api/alerts/rules"),
  updateRule: (id, data) => post(`/api/alerts/rules/${enc(id)}`, data),
  deleteRule: (id) => fetchWithRetry(`/api/alerts/rules/${enc(id)}`, { method: "DELETE" }).then(json),
  testRule: (rule) => post("/api/alerts/test", rule),
  listAlerts: (limit = 20) => get(`/api/alerts?limit=${limit}`),
};

/* ── Prospector V2 ────────────────────────────────────────────────────── */
api.prospectorV2 = {
  heatmap: (params) => post("/api/prospector/v2/heatmap", params),
  substationDetail: (id) => get(`/api/prospector/v2/substation/${enc(id)}`),
  candidates: (params) => post("/api/prospector/v2/candidates", params),
};

/* ── Terrain & Environmental Analysis ──────────────────────────────────── */
api.terrain = {
  analyse: (lat, lon, slopeThreshold = 15, technology = "solar") =>
    get(`/api/terrain/analyse?lat=${lat}&lon=${lon}&slope_threshold=${slopeThreshold}&technology=${enc(technology)}`),
  viewshed: (lat, lon, observerHeight = 1.7, targetHeight = 3.5, radiusKm = 5) =>
    post("/api/terrain/viewshed", { lat, lon, observer_height_m: observerHeight, target_height_m: targetHeight, radius_km: radiusKm }),
  hydrology: (lat, lon) =>
    get(`/api/terrain/hydrology?lat=${lat}&lon=${lon}`),
  buildableArea: (lat, lon, slopeThreshold = 15, technology = "solar") =>
    get(`/api/terrain/buildable-area?lat=${lat}&lon=${lon}&slope_threshold=${slopeThreshold}&technology=${enc(technology)}`),
};

/* ── Reports Hub ──────────────────────────────────────────────────────── */
api.reports = {
  generate: (params) => post("/api/reports/generate", params),
  list: () => get("/api/reports/list"),
  download: (reportId) => get(`/api/reports/download/${enc(reportId)}`),
};

/* ── Electrical Design ────────────────────────────────────────────────── */
api.electrical = {
  inverters: (capacityKwp, dcAcRatio = 1.25) =>
    get(`/api/electrical/inverters?capacity_kwp=${capacityKwp}&dc_ac_ratio=${dcAcRatio}`),
  transformers: (capacityKwp, inverterModel) =>
    get(`/api/electrical/transformers?capacity_kwp=${capacityKwp}${inverterModel ? `&inverter_model=${enc(inverterModel)}` : ""}`),
  cables: (capacityKwp) =>
    get(`/api/electrical/cables?capacity_kwp=${capacityKwp}`),
  design: (capacityKwp, technology = "solar") =>
    post("/api/electrical/design", { capacity_kwp: capacityKwp, technology }),
};

/* ── Document Automation ──────────────────────────────────────────────── */
api.documents = {
  generate: (params) => post("/api/documents/generate", params),
  list: () => get("/api/documents/list"),
  types: () => get("/api/documents/types"),
  checklist: (lat, lon, capacityMw, technology) =>
    get(`/api/documents/checklist?lat=${lat}&lon=${lon}&capacity_mw=${capacityMw}&technology=${enc(technology)}`),
};

/* ── Portfolio Optimisation ─────────────────────────────────────────────── */
api.portfolio = {
  summary: (sites) => post("/api/sustainability/portfolio/summary", { sites }),
  diversification: (sites) => post("/api/sustainability/portfolio/diversification", { sites }),
  optimise: (budgetMw = 200, target = "max_revenue") =>
    get(`/api/sustainability/portfolio/optimisation?budget_mw=${budgetMw}&target=${enc(target)}`),
};

/* ── Cable Routing ─────────────────────────────────────────────────────── */
api.cableRouting = {
  findRoute: (lat, lon, voltageKv, constraints = {}) =>
    post("/api/advanced-grid/reinforcement/estimate", {
      lat, lon, voltage_kv: voltageKv, ...constraints,
    }),
  benchmarks: () => get("/api/advanced-grid/reinforcement/benchmarks"),
};

/* ── Yield Assessment ──────────────────────────────────────────────────── */
api.yieldAssessment = {
  solar: (lat, lon, capacityKwp, tilt, azimuth, tracking, losses) => {
    const q = new URLSearchParams({ lat, lon, capacity_kwp: capacityKwp });
    if (tilt != null) q.set("tilt", tilt);
    if (azimuth != null) q.set("azimuth", azimuth);
    if (tracking) q.set("tracking", tracking);
    if (losses != null) q.set("losses_pct", losses);
    return get(`/api/yield/solar?${q}`);
  },
  wind: (lat, lon, capacityKw, hubHeightM) =>
    get(`/api/yield/wind?lat=${lat}&lon=${lon}&capacity_kw=${capacityKw}&hub_height_m=${hubHeightM}`),
  compare: (lat, lon, solarKwp, windKw) =>
    get(`/api/yield/compare?lat=${lat}&lon=${lon}&solar_kwp=${solarKwp}&wind_kw=${windKw}`),
};

/* ── Construction Timeline ─────────────────────────────────────────────── */
api.construction = {
  plan: (capacityMw, technology, siteAreaHa, gridDistKm) =>
    post("/api/site/construction-plan", {
      capacity_mw: capacityMw, technology, site_area_ha: siteAreaHa, grid_distance_km: gridDistKm,
    }),
  progress: (projectId) => get(`/api/construction/progress/${enc(projectId)}`),
};


/* ════════════════════════════════════════════════════════════════════════
   PULSE SUITE — Cluster graph, events, portfolio delta, NGED, curtailment
   ════════════════════════════════════════════════════════════════════════ */

api.cluster = {
  stats:           () => get("/api/cluster/stats"),
  studies:         () => get("/api/cluster/studies"),
  ingest:          (dryRun = false) => post(`/api/cluster/ingest?dry_run=${dryRun}`),
  recompute:       (studyId) => post(`/api/cluster/recompute-dependencies${studyId ? `?study_id=${enc(studyId)}` : ""}`),
  view:            (projectId) => get(`/api/cluster/${enc(projectId)}`),
  withdraw:        (projectId) => post(`/api/cluster/${enc(projectId)}/withdraw`),
  graphGeojson:    (studyId) => get(`/api/cluster/graph/${enc(studyId)}.geojson`),
};

api.events = {
  list:            (params = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v != null && v !== "") q.set(k, v);
    return get(`/api/events/?${q}`);
  },
  emit:            (event) => post("/api/events/emit", event),
  runDiff:         () => post("/api/events/diff/run"),
  stats:           () => get("/api/events/stats"),
  notifications:   (userId = "default", unreadOnly = false, limit = 100) =>
    get(`/api/events/notifications?user_id=${enc(userId)}&unread_only=${unreadOnly}&limit=${limit}`),
  markRead:        (notificationId) => post(`/api/events/notifications/${notificationId}/read`),
  listRules:       (userId = "default") => get(`/api/events/rules?user_id=${enc(userId)}`),
  createRule:      (rule) => post("/api/events/rules", rule),
  wsUrl:           () => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/api/events/ws`;
  },
};

api.portfolioDelta = {
  snapshot:        (takenAt) => post(`/api/portfolio/snapshot/take${takenAt ? `?taken_at=${takenAt}` : ""}`),
  deltas:          (fromDate, toDate) => {
    const q = new URLSearchParams();
    if (fromDate) q.set("from_date", fromDate);
    if (toDate)   q.set("to_date", toDate);
    return get(`/api/portfolio/deltas?${q}`);
  },
  latest:          (limit = 50) => get(`/api/portfolio/deltas/latest?limit=${limit}`),
  weeklySummary:   () => get("/api/portfolio/weekly-summary"),
};

api.nged = {
  // Live Data Feed (licence-area aggregate)
  liveIngest:      () => post("/api/nged/live/ingest"),
  liveLatest:      () => get("/api/nged/live/latest"),
  liveLicenceAreasGeojson: () => get("/api/nged/live/licence-areas.geojson"),
  liveHistory:     (licenceArea, hours = 24) => {
    const q = new URLSearchParams({ hours });
    if (licenceArea) q.set("licence_area", licenceArea);
    return get(`/api/nged/live/history?${q}`);
  },

  // Live GSP Data (per-GSP 5-min time series)
  regions:         () => get("/api/nged/regions"),
  gspIngest:       (region, maxRowsPerGsp = 500) => {
    const q = new URLSearchParams({ max_rows_per_gsp: maxRowsPerGsp });
    if (region) q.set("region", region);
    return post(`/api/nged/gsp/ingest?${q}`);
  },
  gspResolve:      () => post("/api/nged/gsp/resolve-locations"),
  gspGeojson:      (region) => get(`/api/nged/gsp.geojson${region ? `?region=${enc(region)}` : ""}`),
  gspTimeseries:   (region, gspName, hours = 48) =>
    get(`/api/nged/gsp/${enc(region)}/${enc(gspName)}/timeseries?hours=${hours}`),
  gspStats:        () => get("/api/nged/gsp/stats"),

  // Embedded Capacity Register
  ecrIngest:       (limit) => post(`/api/nged/ecr/ingest${limit ? `?limit=${limit}` : ""}`),
  ecrGeojson:      (params = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v != null && v !== "") q.set(k, v);
    return get(`/api/nged/ecr.geojson?${q}`);
  },
  ecrStats:        () => get("/api/nged/ecr/stats"),

  // Network Opportunity Map headroom
  headroomGeojson: (kind = "demand", dno, minVoltageKv = 11, limit = 5000) => {
    const q = new URLSearchParams({ kind, min_voltage_kv: minVoltageKv, limit });
    if (dno) q.set("dno", dno);
    return get(`/api/nged/headroom.geojson?${q}`);
  },
  headroomStats:   (dno) => get(`/api/nged/headroom/stats${dno ? `?dno=${enc(dno)}` : ""}`),
};

api.dcHyperscaler = {
  dualFeedPairs: (lat, lon, capacityMva, maxRadiusKm = 25, minVoltageKv = 33) =>
    get(`/api/dc/hyperscaler/dual-feed-pairs?lat=${lat}&lon=${lon}&capacity_mva=${capacityMva}&max_radius_km=${maxRadiusKm}&min_voltage_kv=${minVoltageKv}`),
  mvsGap:          (params) => post("/api/dc/hyperscaler/mvs-gap", params),
  optioneer:       (params) => post("/api/dc/hyperscaler/optioneer", params),
  idnos:           (region) => get(`/api/dc/hyperscaler/idnos${region ? `?region=${enc(region)}` : ""}`),
  pathwaySplit:    (params) => post("/api/dc/hyperscaler/pathway-split", params),
  sqssCheck:       (params) => post("/api/dc/hyperscaler/sqss-check", params),
  msipEligibility: (params) => post("/api/dc/hyperscaler/msip-eligibility", params),
  switchgear:      (params) => {
    const q = new URLSearchParams(params);
    return get(`/api/dc/hyperscaler/switchgear?${q}`);
  },
  connectionBom:   (params) => post("/api/dc/hyperscaler/connection-bom", params),
  escalate:        (costGbp, fromYear, toYear) =>
    get(`/api/dc/hyperscaler/escalate?cost_gbp=${costGbp}&from_year=${fromYear}&to_year=${toYear}`),
  stats:           () => get("/api/dc/hyperscaler/stats"),
};


api.neso098 = {
  criteria:          () => get("/api/neso098/criteria"),
  scoreSite:         (params) => post("/api/neso098/score-site", params),
  power:             (itPowerMw, dcType = "hyperscaler", pueOverride = null) => {
    const q = new URLSearchParams({ it_power_mw: itPowerMw, dc_type: dcType });
    if (pueOverride != null) q.set("pue_override", pueOverride);
    return get(`/api/neso098/power?${q}`);
  },
  forecastBuild:     (scenario = "moderate", startYear = 2024, endYear = 2040) =>
    post(`/api/neso098/forecast/build?scenario=${enc(scenario)}&start_year=${startYear}&end_year=${endYear}`),
  forecast:          (scenario = "moderate") => get(`/api/neso098/forecast?scenario=${enc(scenario)}`),
  queueDedupe:       (applications) => post("/api/neso098/queue/dedupe", { applications }),
  queueAttrition:    (applications) => post("/api/neso098/queue/attrition", { applications }),
  estateUpsert:      (record) => post("/api/neso098/estate/upsert", record),
  estateSummary:     () => get("/api/neso098/estate/summary"),
  estateGeojson:     () => get("/api/neso098/estate.geojson"),
};


api.gu = {
  lric:             (params) => post("/api/gu/lric", params),
  hostingCapacity:  (params) => post("/api/gu/hosting-capacity", params),
  carbonLcoe:       (params) => post("/api/gu/carbon-lcoe", params),
  tclRevenue:       (params) => post("/api/gu/tcl-revenue", params),
  drlBess:          (params) => post("/api/gu/drl-bess", params),
  marketSim:        (params) => post("/api/gu/market-sim", params),
  climateResilience:(params) => post("/api/gu/climate-resilience", params),
  waterNexus:       (params) => post("/api/gu/water-nexus", params),
  hydrogen:         (params) => post("/api/gu/hydrogen", params),
  regulatorySeed:   () => post("/api/gu/regulatory/seed"),
  regulatorySearch: (q, k = 5) => get(`/api/gu/regulatory/search?q=${enc(q)}&k=${k}`),
  regulatoryAnswer: (question, context) => post("/api/gu/regulatory/answer", { question, context }),
  dnoIngest:        (dno) => post(`/api/gu/dno/ingest${dno ? `?dno=${enc(dno)}` : ""}`),
  dnoStatus:        () => get("/api/gu/dno/status"),
  dnoAdapters:      () => get("/api/gu/dno/adapters"),
  largeDemandGeojson:(dno) => get(`/api/gu/dno/large-demand.geojson${dno ? `?dno=${enc(dno)}` : ""}`),
};


api.ltds = {
  ingest:           (downloadDir) => post(`/api/ltds/ingest${downloadDir ? `?download_dir=${enc(downloadDir)}` : ""}`),
  matchCoordinates: () => post("/api/ltds/match-coordinates"),
  stats:            () => get("/api/ltds/stats"),
  substations:      (params = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v != null && v !== "") q.set(k, v);
    return get(`/api/ltds/substations?${q}`);
  },
  substationsGeojson:() => get("/api/ltds/substations.geojson"),
  substationDetail: (mrid) => get(`/api/ltds/substations/${enc(mrid)}`),
};


api.scan = {
  zone: (bbox) => post("/api/scan/zone", { bbox }),
  constraintsUnion: (bbox) =>
    get(`/api/constraints/union?bbox=${bbox.join(",")}`),
  gridCorridors: (bbox, capacityMw = 50) =>
    get(`/api/scan/grid-corridors?bbox=${bbox.join(",")}&capacity_mw=${capacityMw}`),
};

api.landRights = {
  // GET /api/land-rights/{layer}?bbox=…
  layer: (key, bbox) =>
    get(`/api/land-rights/${enc(key)}?bbox=${bbox.join(",")}`),
  ownershipParcels: (bbox) =>
    get(`/api/land-rights/parcels/ownership-coloured?bbox=${bbox.join(",")}`),
  status: () => get("/api/land-rights/status"),
};

api.curtailment = {
  analyse:         (params) => post("/api/curtailment/analyse", params),
  analyseGet:      (params) => {
    const q = new URLSearchParams(params);
    return get(`/api/curtailment/analyse?${q}`);
  },
  portfolioScreen: (scenario = "base", limit = 200) =>
    post(`/api/curtailment/portfolio/screen?scenario=${enc(scenario)}&limit=${limit}`),
  constraintsNear: (lat, lon, limit = 20) =>
    get(`/api/curtailment/constraints/near?lat=${lat}&lon=${lon}&limit=${limit}`),
  queueRank:       (projectId, constraintGroup = "") =>
    get(`/api/curtailment/queue-rank/${enc(projectId)}?constraint_group=${enc(constraintGroup)}`),
  scenarios:       () => get("/api/curtailment/scenarios"),
  profile:         (profileId) => get(`/api/curtailment/profiles/${enc(profileId)}`),
  stats:           () => get("/api/curtailment/stats"),
};

export default api;
