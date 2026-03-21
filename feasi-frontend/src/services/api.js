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
    circuit: (subId, depth = 3) => get(`/grid/cim/circuit/${enc(subId)}?depth=${depth}`),
    circuitSearch: (q) => get(`/grid/cim/search?q=${enc(q)}`),
    circuitPath: (fromId, toId) => get(`/grid/cim/path?from_id=${enc(fromId)}&to_id=${enc(toId)}`),
    circuitDownstream: (subId) => get(`/grid/cim/downstream/${enc(subId)}`),
    circuitHealth: () => get("/grid/cim/health"),
    // National Grid overlays
    constraints:  (bbox) => bbox ? get(`/api/grid/constraints?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`) : get("/api/grid/constraints"),
    queueDepth:   (substationId) => get(`/api/grid/queue-depth/${substationId}`),
    queueSummary: (bbox) => bbox ? get(`/api/grid/queue-summary?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`) : get("/api/grid/queue-summary"),
    liveStatus:   () => get("/api/grid/live-status"),
    // Grid connection capacity endpoints
    capacityMap: (bbox) => get(`/grid/capacity-map?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`),
    gridLines: (bbox) => get(`/grid/lines?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`),
    powerFlow: (lat, lon, capacityMw, technology, substationId, contingency) => {
      const q = new URLSearchParams({ lat, lon, capacity_mw: capacityMw, technology });
      if (substationId != null) q.set("substation_id", substationId);
      if (contingency) q.set("contingency", "true");
      return post(`/grid/power-flow?${q}`);
    },
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

  land: {
    parcels:  (bbox) => get(`/api/land/parcels?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`),
    alc:      (lat, lon) => get(`/api/land/alc?lat=${lat}&lon=${lon}`),
    listings: (lat, lon, radiusKm = 10) => get(`/api/land/listings?lat=${lat}&lon=${lon}&radius_km=${radiusKm}`),
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
  },

  bipv: {
    catalogue: () => get("/bipv/catalogue"),
    annual: (parcelId, area, moduleType, surfaceType) => get(`/site/${enc(parcelId)}/bipv/annual?area_m2=${area}&module_type=${enc(moduleType)}&surface_type=${enc(surfaceType)}`),
    profile: (parcelId, date, area, moduleType, surfaceType) => get(`/site/${enc(parcelId)}/bipv/profile?date=${enc(date)}&area_m2=${area}&module_type=${enc(moduleType)}&surface_type=${enc(surfaceType)}`),
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
};

export default api;
