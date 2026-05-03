import React, { createContext, useContext, useState, useCallback, useRef, useMemo, useEffect } from "react";
import api from "./services/api";
import { usePanel } from "./hooks/useUiPanels.js";
import { useSettings } from "./hooks/useSettings.js";
import { useSiteTarget } from "./hooks/useSiteTarget.js";

const SiteContext = createContext(null);

const SETTINGS_DEFAULTS = {
  // Map & Display
  mapStyle: "dark",
  defaultSlopeOpacity: 0.6,
  defaultLayers: ["hillshade", "contours", "environment", "aerial"],
  theme: "dark",
  // API & Connections
  mapboxToken: "",
  geeProjectId: "",
  backendUrl: "",
  // Profile & Notifications
  displayName: "",
  email: "",
  exportFormat: "csv",
  notifications: true,
};

function loadSettings() {
  try {
    const raw = localStorage.getItem("princeps_settings");
    if (raw) return { ...SETTINGS_DEFAULTS, ...JSON.parse(raw) };
  } catch { /* ignore corrupt data */ }
  return { ...SETTINGS_DEFAULTS };
}

export function SiteProvider({ children }) {
  // ── Settings (Stage B2 — backed by useSettings hook, localStorage-persisted) ──
  const [settings, setSettings] = useSettings();
  const [settingsForm, setSettingsForm] = useState(() => settings);

  // Keep settingsForm in sync with persisted settings (cross-tab edits, etc.).
  useEffect(() => {
    setSettingsForm(settings);
  }, [settings]);

  const saveSettings = useCallback((form) => {
    setSettings(form);          // useSettings handles localStorage write
    setSettingsForm(form);
  }, [setSettings]);

  const resetSettingsForm = useCallback(() => {
    setSettingsForm(settings);
  }, [settings]);

  const updateSettingsForm = useCallback((updates) => {
    setSettingsForm(prev => ({ ...prev, ...updates }));
  }, []);
  // ── Site identity (Stage B3 — URL-search-param-backed via useSiteTarget) ──
  const {
    parcelId, setParcelId,
    pickedLocation, setPickedLocation,
    pickMode, setPickMode,
  } = useSiteTarget();

  // ── SAM parameters ──
  const [samCapacity, setSamCapacity] = useState(100);
  const [samDay, setSamDay] = useState(172);
  const [loadMw, setLoadMw] = useState(5);
  const [genMw, setGenMw] = useState(4);

  // ── Data slices (populated by loadSite) ──
  const [heightmap, setHeightmap] = useState(null);
  const [explain, setExplain] = useState(null);
  const [slopeStats, setSlopeStats] = useState(null);
  const [solarYield, setSolarYield] = useState(null);
  const [solarHourly, setSolarHourly] = useState(null);
  const [mlSolar, setMlSolar] = useState(null);
  const [deferral, setDeferral] = useState(null);
  const [energyPrice, setEnergyPrice] = useState(null);
  const [gridContext, setGridContext] = useState(null);
  const [planningApps, setPlanningApps] = useState(null);
  const [energySystem, setEnergySystem] = useState(null);
  const [siteBom, setSiteBom] = useState(null);
  const [bomAvail, setBomAvail] = useState(null);
  const [agentResult, setAgentResult] = useState(null);
  const [demandForecast, setDemandForecast] = useState(null);
  const [agilePricing, setAgilePricing] = useState(null);
  const [stabilityData, setStabilityData] = useState(null);

  // ── GeeFlow / Satellite ──
  const [geeflowData, setGeeflowData] = useState(null);
  const [geeflowLoading, setGeeflowLoading] = useState(false);
  const [geeflowJobId, setGeeflowJobId] = useState(null);

  // ── Grid Connection Panel ──
  const [gridConnectionOpen, setGridConnectionOpen] = usePanel('grid-connection');
  const [gridHighlightSub, setGridHighlightSub] = useState(null); // candidate substation to highlight on map

  // ── Demand Forecast Panel ──
  const [demandForecastOpen, setDemandForecastOpen] = usePanel('demand-forecast');

  // ── Council Search Panel ──
  const [councilSearchOpen, setCouncilSearchOpen] = usePanel('council-search');

  // ── Grid Digital Twin ──
  const [gridTwinOpen, setGridTwinOpen] = usePanel('grid-twin');

  // ── Advanced Grid Panel ──
  const [advancedGridOpen, setAdvancedGridOpen] = usePanel('advanced-grid');

  // ── Connection Strategy Panel ──
  const [connectionStrategyOpen, setConnectionStrategyOpen] = usePanel('connection-strategy');

  // ── Dispatch Panel ──
  const [dispatchOpen, setDispatchOpen] = usePanel('dispatch');

  // ── Route-to-Market Panel ──
  const [rtmOpen, setRtmOpen] = usePanel('rtm');

  // ── Sustainability Panel ──
  const [sustainabilityOpen, setSustainabilityOpen] = usePanel('sustainability');

  // ── Investment Panel ──
  const [investmentOpen, setInvestmentOpen] = usePanel('investment');

  // ── Financial Model Panel ──
  const [financialModelOpen, setFinancialModelOpen] = usePanel('financial-model');

  // ── Site Prospector Panel ──
  const [siteProspectorOpen, setSiteProspectorOpen] = usePanel('site-prospector');

  // ── Data Centre Twin (unified) ──
  const [dcTwinOpen, setDcTwinOpen] = usePanel('dc-twin');
  const [dcLandingOpen, setDcLandingOpen] = usePanel('dc-landing');
  const [dcComparisonOpen, setDcComparisonOpen] = usePanel('dc-comparison');
  const [dcComparisonSites, setDcComparisonSites] = useState([]);

  // ── BEMS Digital Twin ──
  const [bemsOpen, setBemsOpen] = usePanel('bems');

  // ── Asset Inspector (LiDAR) ──
  const [assetInspectorOpen, setAssetInspectorOpen] = usePanel('asset-inspector');

  // ── Grid Graph Topology ──
  const [gridGraphOpen, setGridGraphOpen] = usePanel('grid-graph');

  // ── Planning Intelligence Panel ──
  const [planningIntelOpen, setPlanningIntelOpen] = usePanel('planning-intel');

  // ── BESS Panel ──
  const [bessPanelOpen, setBessPanelOpen] = usePanel('bess-panel');

  // ── Portfolio Panel ──
  const [portfolioPanelOpen, setPortfolioPanelOpen] = usePanel('portfolio-panel');

  // ── Cable Routing Panel ──
  const [cableRoutingOpen, setCableRoutingOpen] = usePanel('cable-routing');

  // ── Yield Assessment Panel ──
  const [yieldAssessmentOpen, setYieldAssessmentOpen] = usePanel('yield-assessment');

  // ── Construction Panel ──
  const [constructionPanelOpen, setConstructionPanelOpen] = usePanel('construction-panel');

  // ── BESS Facility Twin ──
  const [bessFacilityOpen, setBessFacilityOpen] = usePanel('bess-facility');

  // ── Hardware Configurator ──
  const [hwConfigOpen, setHwConfigOpen] = usePanel('hw-config');

  // ── Gemini 3D Asset Modeller ──
  const [asset3dOpen, setAsset3dOpen] = usePanel('asset3d');

  // ── Thermal Model (TEASER) ──
  const [thermalModelOpen, setThermalModelOpen] = usePanel('thermal-model');

  // ── Terrain Analysis Panel ──
  const [terrainAnalysisOpen, setTerrainAnalysisOpen] = usePanel('terrain-analysis');

  // ── Reports Hub Panel ──
  const [reportsHubOpen, setReportsHubOpen] = usePanel('reports-hub');

  // ── Electrical Design Panel ──
  const [electricalDesignOpen, setElectricalDesignOpen] = usePanel('electrical-design');

  // ── Documents Panel ──
  const [documentsPanelOpen, setDocumentsPanelOpen] = usePanel('documents');

  // ── Tier 3 Panels ──
  const [ppaOriginationOpen, setPpaOriginationOpen] = usePanel('ppa-origination');
  const [workflowPanelOpen, setWorkflowPanelOpen] = usePanel('workflow');
  const [assessmentSnapshotOpen, setAssessmentSnapshotOpen] = usePanel('assessment-snapshot');
  const [exportPanelOpen, setExportPanelOpen] = usePanel('export');
  const [alertRulesOpen, setAlertRulesOpen] = usePanel('alert-rules');
  const [prospectorV2Open, setProspectorV2Open] = usePanel('prospector-v2');

  // ── Palantir-style shared entity selection (cross-view linking) ──
  const [selectedEntity, setSelectedEntity] = useState(null);
  // Shape: { type: "substation"|"project"|"constraint"|"ecr"|"site", id, data, source }
  const [actionSidebarOpen, setActionSidebarOpen] = usePanel('action-sidebar');

  // ── Real Site Context (REPD, OSM, grid, TEC) ──
  const [realSiteContext, setRealSiteContext] = useState(null);

  // ── Vision AI ──
  const [visionData, setVisionData] = useState(null);
  const [visionLoading, setVisionLoading] = useState(false);
  const [visionUploads, setVisionUploads] = useState([]);
  const [digitalTwinOpen, setDigitalTwinOpen] = usePanel('digital-twin');
  const [terrainTwinOpen, setTerrainTwinOpen] = usePanel('terrain-twin');
  const [twinData, setTwinData] = useState(null);

  // ── Loading flags ──
  const [loading, setLoading] = useState(false);
  const [agentLoading, setAgentLoading] = useState(false);

  // ── Layout mode ──
  const [layoutMode, setLayoutMode] = useState(false);
  const [componentLayout, setComponentLayout] = useState([]);
  const [selectedLayoutItem, setSelectedLayoutItem] = useState(null);
  const [customBom, setCustomBom] = useState(null);
  const [solarCatalogue, setSolarCatalogue] = useState(null);
  const bomAbortRef = useRef(null);

  // ── DesignCanvas view mode — "canvas" (2D Mapbox) | "twin" (3D Site Twin) ──
  const [designCanvasMode, setDesignCanvasMode] = useState(() => {
    try { return localStorage.getItem("princeps_design_canvas_mode") === "twin" ? "twin" : "canvas"; }
    catch { return "canvas"; }
  });

  // ── Placed assets (map drag-drop) with persistence + validation ──
  const [placedAssets, setPlacedAssets] = useState([]);
  const [energyFlowOpen, setEnergyFlowOpen] = usePanel('energy-flow');
  const [assetValidations, setAssetValidations] = useState({});
  const [designProjectId, setDesignProjectId] = useState(null);
  const [designDirty, setDesignDirty] = useState(false);

  const addPlacedAsset = useCallback((asset) => {
    const newAsset = { ...asset, id: `${asset.assetType}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}` };
    setPlacedAssets(prev => [...prev, newAsset]);
    setEnergyFlowOpen(true);
    setDesignDirty(true);

    // Auto-validate placement (fire-and-forget, no Suspense)
    if (asset.lat && asset.lon) {
      api.design?.validate(asset.lat, asset.lon, asset.assetType, asset.mw || 0).then(val => {
        if (val) setAssetValidations(prev => ({ ...prev, [newAsset.id]: val }));
      }).catch(() => {});
    }
  }, []);

  const removePlacedAsset = useCallback((id) => {
    setPlacedAssets(prev => prev.filter(a => a.id !== id));
    setAssetValidations(prev => { const n = { ...prev }; delete n[id]; return n; });
    setDesignDirty(true);
  }, []);

  const clearPlacedAssets = useCallback(() => {
    setPlacedAssets([]);
    setAssetValidations({});
    setDesignDirty(true);
  }, []);

  // Save design to backend (called manually or on finalize)
  const saveDesign = useCallback(async (projectId) => {
    if (!projectId || placedAssets.length === 0) return null;
    const assets = placedAssets.map((a, i) => ({
      asset_type: a.assetType, lat: a.lat, lon: a.lon || a.lng,
      capacity_mw: a.mw || 0, label: a.label, color: a.color,
      rotation_deg: a.rotation || 0, sort_order: i,
      bom_item_id: a.bomItemId || null,
    }));
    const result = await api.design.saveBulk(projectId, assets);
    if (result) setDesignDirty(false);
    return result;
  }, [placedAssets]);

  // Load design from backend
  const loadDesign = useCallback(async (projectId) => {
    const assets = await api.design.listAssets(projectId);
    if (assets && Array.isArray(assets)) {
      setPlacedAssets(assets.map(a => ({
        id: a.asset_id, assetType: a.asset_type, label: a.label,
        mw: a.capacity_mw, lat: a.lat, lon: a.lon, lng: a.lon,
        color: a.color, rotation: a.rotation_deg,
        bomItemId: a.bom_item_id, validation: a.validation,
      })));
      setDesignProjectId(projectId);
      setDesignDirty(false);
    }
  }, []);

  // ── EPC ──
  const [selectedLsoa, setSelectedLsoa] = useState(null);
  const [epcZonesField, setEpcZonesField] = useState("epc_score_avg");
  const [epcDomField, setEpcDomField] = useState("cur_rate");
  const [epcNondomField, setEpcNondomField] = useState("band");
  const [postcodesField, setPostcodesField] = useState("combined");

  // ── Chat layers (injected from ChatPanel) ──
  const [chatLayers, setChatLayers] = useState([]);

  // ── UI ──
  const [activeTab, setActiveTab] = useState("score");
  const [panelOpen, setPanelOpen] = useState(true);
  const [slopeOpacity, setSlopeOpacity] = useState(0.6);

  // ── Intent-driven UI ──
  const [activeIntent, setActiveIntent] = useState("overview");
  const [commandCollapsed, setCommandCollapsed] = useState(false);
  const [analyticsCollapsed, setAnalyticsCollapsed] = useState(false);

  // ── Workflow ──
  const [workflowStage, setWorkflowStage] = useState("site"); // site | study | connect | plan | impact | act
  const [studySubStep, setStudySubStep] = useState("feasibility");
  const [workflowHistory, setWorkflowHistory] = useState(["site"]);
  const [dashboardOpen, setDashboardOpen] = usePanel('dashboard');

  // ── Chained Workflows ──
  const [workflowResults, setWorkflowResults] = useState({});  // intent → agent result
  const [workflowSummary, setWorkflowSummary] = useState(null);
  const [workflowRunning, setWorkflowRunning] = useState(false);
  const [workflowProgress, setWorkflowProgress] = useState(null); // { step, total, intent, preset }
  const workflowAbortRef = useRef(null);

  const navigateWorkflow = useCallback(async (stage) => {
    setWorkflowStage(stage);
    setWorkflowHistory(prev => prev.includes(stage) ? prev : [...prev, stage]);
    if (stage === "site") { setPickMode(true); setLayoutMode(false); }
    if (stage === "study") { setLayoutMode(false); setStudySubStep("feasibility"); setActiveIntent("feasibility"); }
    if (stage === "connect") { setLayoutMode(false); setActiveIntent("grid_connection"); }
    if (stage === "plan") { setLayoutMode(true); }
    if (stage === "impact") { setLayoutMode(false); setActiveIntent("planning"); }
    if (stage === "act") {
      setLayoutMode(false);
      // Auto-create pipeline project when entering ACT stage
      const siteName = explain?.location_name || parcelId || "Untitled Site";
      const lat = explain?.lat ?? pickedLocation?.lat;
      const lon = explain?.lon ?? pickedLocation?.lon;
      if (lat && lon && parcelId) {
        try {
          await api.projects.create({
            name: siteName,
            capacity_mw: (samCapacity || 5000) / 1000,
            technology: "solar",
            stage: "screened",
            verdict: agentResult?.verdict || "CAUTION",
            lat, lon,
            description: agentResult?.summary || `Site assessment for ${siteName}`,
          });
        } catch (e) {
          // Silently fail — pipeline creation is best-effort
          console.warn("Auto-create pipeline project failed:", e);
        }
      }
    }
  }, [setPickMode, setLayoutMode, setActiveIntent, explain, pickedLocation, parcelId, samCapacity, agentResult]);

  // ── Layers ──
  const [layers, setLayers] = useState({
    slope: true, carbon: false, la: false, transport: false, hillshade: true,
    contours: true, environment: true, gridFlow: true, agilePricing: false,
    demandOverlay: false, flowFocus: false, osmPower: false,
    ndvi: false, satellite: false, aerial: true, lidarDtm: false, lidarDsm: false, landsat: false, viirs: false,
    ngedSubs: false,
    gridCapacity: false,
    demandGsps: false,
    tecPipeline: false,
    repdProjects: false,
    geeflowLandUse: false,
    geeflowOpportunities: false,
    electricityZones: false,
    epcZones: false, epcDom: false, epcNondom: false, postcodes: false,
    dcCapacity: false, dcFibre: false, dcIxp: false,
    gridTwin3d: false,
    google3d: false,
    cesiumGlobe: false,
    gibsModis: false,
    gibsViirs: false,
    gibsNightlights: false,
    gibsNdvi: false,
    gibsLandTemp: false,
    gibsCloudFraction: false,
    gibsFire: false,
    gridConstraints: false,
    envConstraints: true,        // Default-on 2026-04-19 — flood/SSSI/AONB are first-pass feasibility filters
    // ── BOT-FLOOD: first-class EA flood overlays via WMS proxy (2026-04-29) ──
    eaFloodZone3:    false,    // 1-in-100y fluvial / 1-in-200y tidal
    eaFloodZone2:    false,    // 1-in-1000y outline (Flood Map for Planning)
    eaRofrs:         false,    // Risk of Flooding from Rivers and Sea (NaFRA 2024)
    eaRofrsw:        false,    // Risk of Flooding from Surface Water
    eaReservoir:     false,    // Reservoir inundation (wet day, national)
    // ── BOT-LR: land-rights overlays via /api/land-rights/{layer} ────────────
    lrCrown:         false,    // Crown Estate land
    lrMod:           false,    // MOD safeguarding zones
    lrForestry:      false,    // Forestry England subcompartments
    lrNationalTrust: false,    // National Trust always-open land
    lrCommon:        false,    // CRoW s.4 conclusively-registered common land
    lrProw:          false,    // Public rights of way (lines)
    lrParcelsOwn:    false,    // INSPIRE parcels coloured by ownership category
    queueDepth: false,
    landParcels: true,           // Default-on — HMLR parcels are a primary discovery surface
    planningDensity: false,
    planningConstraints: true,   // Default-on 2026-04-19 — LPA constraints visible on Map without opt-in
    // Pulse · NGED live-intelligence layers
    nged_headroom: false,
    nged_ecr: false,
    nged_gsp: false,
    nged_licence: false,
    // BOT-CC substrate — OS MasterMap / EA LiDAR / OSM pylons
    substrateBuildings: false,
    substrateRoads: false,
    substrateWater: false,
    substrateWoodland: false,
    substratePylons: false,
    substrateOverheadLines: false,
    substrateLidar: false,
  });
  const toggleLayer = useCallback((id) => {
    setLayers(l => ({ ...l, [id]: !l[id] }));
  }, []);

  // Bridge "Show on Map" deep-links from the Intelligence Datasets page.
  // The Datasets browser uses backend slugs (tec_register, land_parcels,
  // dno_capacity, repd, nsip, flood_zones, ...) which differ from the
  // SiteContext's internal layer ids (tecPipeline, landParcels, gridCapacity,
  // repdProjects, ...). Map both, accept either via URL query (?layer= or
  // ?layer= + ?dataset=) AND via the runtime CustomEvent fired by
  // useDatasetLayer for in-app transitions.
  useEffect(() => {
    const SLUG_TO_LAYER = {
      // Backend slug → SiteContext layer id
      tec_register:  "tecPipeline",
      tecpipeline:   "tecPipeline",
      land_parcels:  "landParcels",
      landparcels:   "landParcels",
      dno_capacity:  "gridCapacity",
      gridcapacity:  "gridCapacity",
      repd:          "repdProjects",
      repdprojects:  "repdProjects",
      // NSIP — disambiguated from REPD. We expose `nsipProjects` as its own
      // layer key; MapView can register a filtered view (>50MW solar /
      // >100MW onshore wind per Energy Act 2023). Until a dedicated NSIP
      // layer ships, the URL fallback also activates `repdProjects` as the
      // honest surface (data overlap) — consumers can filter on
      // sessionStorage flag `princeps_nsip_scale_filter` which the bridge
      // sets when a NSIP CTA is fired.
      nsip:          ["nsipProjects", "repdProjects"],
      nsipprojects:  ["nsipProjects", "repdProjects"],
      // Grid reliability — N-1 contingency heatmap; falls back to the
      // gridCapacity surface until a dedicated `n1Heat` layer lands.
      n1_reliability_heat: ["n1Heat", "gridCapacity"],
      n1heat:              ["n1Heat", "gridCapacity"],
      // Flood maps — EA Flood Map for Planning → existing env constraints surface
      ea_flood_planning:   "envConstraints",
      flood_zones:         "envConstraints",
      floodzones:          "envConstraints",
      flood:               "envConstraints",
      // Planning / aviation / defence safeguarding — all map to the
      // shared planning-constraints surface for now; each gets its own
      // virtual id so future dedicated layers can be slotted in without
      // renaming call-sites in mock-datasets.json.
      planning:            "planningConstraints",
      lpa:                 "planningConstraints",
      mod_safeguarding:         ["modSafeguarding", "planningConstraints"],
      caa_aerodrome_safeguarding: ["caaAerodromeSafeguarding", "planningConstraints"],
      aerodrome_safeguarding:     ["caaAerodromeSafeguarding", "planningConstraints"],
      grid_lines:    "osmPower",
      osm_power:     "osmPower",
      substations:   "gridFlow",
      gridflow:      "gridFlow",
    };
    const resolve = (raw) => {
      if (!raw) return null;
      const k = String(raw).toLowerCase();
      if (k in SLUG_TO_LAYER) return SLUG_TO_LAYER[k];
      // Allow callers to pass the camelCase id directly
      return raw;
    };
    const activate = (rawIds) => {
      // Flatten: a single slug may resolve to an array of layer ids
      // (primary + honest fallback for slugs whose dedicated layer hasn't
      // shipped yet). Filter out nulls after resolution.
      const ids = rawIds
        .map(resolve)
        .flatMap(r => Array.isArray(r) ? r : [r])
        .filter(Boolean);
      if (ids.length === 0) return;
      setLayers(l => {
        const next = { ...l };
        ids.forEach(id => { if (id in next) next[id] = true; });
        return next;
      });
    };

    // 1. URL params on mount
    try {
      const url = new URL(window.location.href);
      const single = url.searchParams.get("layer");
      const multi = url.searchParams.get("layers");
      const raw = [
        ...(single ? [single] : []),
        ...(multi ? multi.split(",").map(s => s.trim()).filter(Boolean) : []),
      ];
      if (raw.length > 0) {
        activate(raw);
        url.searchParams.delete("layer");
        url.searchParams.delete("layers");
        url.searchParams.delete("dataset");
        window.history.replaceState({}, "", url);
      }
    } catch {}

    // 2. Runtime event from useDatasetLayer (in-app transitions)
    const onActivate = (e) => {
      const layer = e.detail?.layer;
      if (layer) activate([layer]);
    };
    window.addEventListener("princeps-activate-dataset-layer", onActivate);
    return () => window.removeEventListener("princeps-activate-dataset-layer", onActivate);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Tab selection ──
  const selectTab = useCallback((id) => {
    setActiveTab(prev => {
      if (prev === id) { setPanelOpen(p => !p); return prev; }
      setPanelOpen(true);
      return id;
    });
  }, []);

  // ── Load all site data ──
  const loadSite = useCallback(async (id, kw, day) => {
    if (!id) return;
    setLoading(true);
    setAgentResult(null);
    setActiveIntent("feasibility");
    try {
      const results = await Promise.allSettled([
        api.site.heightmap(id, 128),
        api.site.explain(id),
        api.site.slopeStats(id),
        api.site.solarYield(id, kw),
        api.site.solarHourly(id, kw, day),
        api.site.solarMl(id, kw, day),
        api.site.energyPrice(id, kw, day),
        api.site.gridContext(id, kw, day),
        api.planning.summary(),
        api.site.energySystem(id, kw),
        api.site.bom(id, kw),
        api.site.bomAvail(id, kw),
      ]);
      const API_NAMES = ["heightmap","explain","slopeStats","solarYield","solarHourly","mlSolar","energyPrice","gridContext","planning","energySystem","bom","bomAvail"];
      const val = (r, i) => {
        if (r.status === "fulfilled" && r.value != null) return r.value;
        if (r.status === "rejected") console.warn(`[loadSite] ${API_NAMES[i]} FAILED:`, r.reason?.message || r.reason);
        else if (!r.value) console.warn(`[loadSite] ${API_NAMES[i]} returned null`);
        return null;
      };
      setHeightmap(val(results[0], 0));
      setExplain(val(results[1], 1));
      setSlopeStats(val(results[2], 2));
      setSolarYield(val(results[3], 3));
      setSolarHourly(val(results[4], 4));
      setMlSolar(val(results[5], 5));
      setEnergyPrice(val(results[6], 6));
      setGridContext(val(results[7], 7));
      setPlanningApps(val(results[8], 8));
      setEnergySystem(val(results[9], 9));
      setSiteBom(val(results[10], 10));
      setBomAvail(val(results[11], 11));
      setActiveTab("score");
      setPanelOpen(true);
      setWorkflowStage("study");
      setStudySubStep("feasibility");
      setWorkflowHistory(prev => prev.includes("study") ? prev : [...prev, "study"]);
      setDashboardOpen(true);

      // Auto-enable constraint + grid layers when site selected
      setLayers(prev => ({ ...prev, envConstraints: true, gridCapacity: true }));

      // Auto-fetch satellite image → instant Claude Vision analysis
      try {
        const loc = val(results[1]); // explain has lat/lon
        const lat = loc?.lat ?? loc?.location?.lat;
        const lon = loc?.lon ?? loc?.location?.lon;
        if (lat && lon) {
          setVisionLoading(true);
          const satResult = await api.vision.fetchSatellite(lat, lon, 2);
          if (satResult?.upload_ids?.length) {
            const instant = await api.vision.instantAnalyse(
              satResult.upload_ids[0], lat, lon, id, "satellite"
            );
            if (instant) setVisionData(instant);
          }
          setVisionLoading(false);
        }
      } catch (visionErr) {
        console.warn("Vision auto-fetch failed:", visionErr);
        setVisionLoading(false);
      }

      // Auto-load 3D digital twin data so it's ready when user opens twin
      try {
        const td = await api.vision.getTwinData(id, 500);
        if (td) setTwinData(td);
      } catch (twinErr) {
        console.warn("Twin data auto-fetch failed:", twinErr);
      }

      // Fetch real nearby infrastructure data for twin enrichment (REPD, OSM, grid, TEC)
      try {
        const loc = val(results[1]); // explain has context with lat/lon
        const lat = loc?.context?.location?.lat ?? loc?.lat ?? pickedLocation?.lat;
        const lon = loc?.context?.location?.lon ?? loc?.lon ?? pickedLocation?.lon;
        if (lat && lon) {
          const ctx = await api.site.realContext(lat, lon, 5);
          if (ctx) setRealSiteContext(ctx);
        }
      } catch (rcErr) {
        console.warn("Real site context fetch failed:", rcErr);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  // ── Run agent analysis ──
  const runAgent = useCallback(async (id, intent, kw, day) => {
    if (!id) return;
    setAgentLoading(true);
    try {
      const data = await api.site.agent(id, intent, kw, day);
      if (data?.agent) {
        setAgentResult(data.agent);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setAgentLoading(false);
    }
  }, []);

  // ── Run deferral ──
  const runDeferral = useCallback(async (load, gen) => {
    try {
      const data = await api.opt.run(load, gen);
      if (data) setDeferral(data);
    } catch (err) { console.error(err); }
  }, []);

  // ── Run chained workflow ──
  const runWorkflow = useCallback(async (id, preset, kw, day) => {
    if (!id || workflowRunning) return;
    setWorkflowRunning(true);
    setWorkflowResults({});
    setWorkflowSummary(null);
    setWorkflowProgress(null);

    // Abort any previous workflow SSE
    if (workflowAbortRef.current) workflowAbortRef.current.abort();
    const controller = new AbortController();
    workflowAbortRef.current = controller;

    try {
      const res = await api.workflow.run(id, preset, kw, day);
      if (!res.ok) {
        console.error("Workflow request failed:", res.status);
        setWorkflowRunning(false);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Parse SSE lines
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let eventType = null;
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith("data: ") && eventType) {
            try {
              const data = JSON.parse(line.slice(6));
              if (eventType === "step_start") {
                setWorkflowProgress({ step: data.step, total: data.total, intent: data.intent, preset });
                setActiveIntent(data.intent);
                setStudySubStep(data.intent);
              } else if (eventType === "step_complete") {
                setWorkflowResults(prev => ({ ...prev, [data.intent]: data.result }));
                setAgentResult(data.result);
              } else if (eventType === "step_error") {
                setWorkflowResults(prev => ({
                  ...prev,
                  [data.intent]: { verdict: "ERROR", confidence: 0, summary: data.error, intent: data.intent, risks: [], opportunities: [], next_steps: [] },
                }));
              } else if (eventType === "workflow_summary") {
                setWorkflowSummary(data.summary);
              }
            } catch { /* skip malformed JSON */ }
            eventType = null;
          }
        }
      }
    } catch (err) {
      if (err.name !== "AbortError") console.error("Workflow stream error:", err);
    } finally {
      setWorkflowRunning(false);
      setWorkflowProgress(null);
    }
  }, [workflowRunning]);

  const value = {
    // Identity
    parcelId, setParcelId,
    pickedLocation, setPickedLocation,
    pickMode, setPickMode,
    // Parameters
    samCapacity, setSamCapacity,
    samDay, setSamDay,
    loadMw, setLoadMw,
    genMw, setGenMw,
    // Data
    heightmap, setHeightmap, explain, setExplain, slopeStats, setSlopeStats, solarYield, setSolarYield, solarHourly, setSolarHourly, mlSolar,
    deferral, setDeferral, energyPrice, setEnergyPrice, gridContext, setGridContext, planningApps, energySystem,
    siteBom, bomAvail, agentResult, setAgentResult,
    demandForecast, setDemandForecast,
    agilePricing, setAgilePricing,
    stabilityData, setStabilityData,
    // Grid Connection Panel
    gridConnectionOpen, setGridConnectionOpen,
    gridHighlightSub, setGridHighlightSub,
    // Demand Forecast Panel
    demandForecastOpen, setDemandForecastOpen,
    // Council Search Panel
    councilSearchOpen, setCouncilSearchOpen,
    // Grid Digital Twin
    gridTwinOpen, setGridTwinOpen,
    // Advanced Grid Panel
    advancedGridOpen, setAdvancedGridOpen,
    // Connection Strategy Panel
    connectionStrategyOpen, setConnectionStrategyOpen,
    // Dispatch Panel
    dispatchOpen, setDispatchOpen,
    // Route-to-Market Panel
    rtmOpen, setRtmOpen,
    // Sustainability Panel
    sustainabilityOpen, setSustainabilityOpen,
    // Investment Panel
    investmentOpen, setInvestmentOpen,
    // Financial Model Panel
    financialModelOpen, setFinancialModelOpen,
    // Site Prospector Panel
    siteProspectorOpen, setSiteProspectorOpen,
    // Data Centre Panel
    dcTwinOpen, setDcTwinOpen,
    dcLandingOpen, setDcLandingOpen,
    dcComparisonOpen, setDcComparisonOpen,
    dcComparisonSites, setDcComparisonSites,
    // BEMS Digital Twin
    bemsOpen, setBemsOpen,
    // Asset Inspector (LiDAR)
    assetInspectorOpen, setAssetInspectorOpen,
    // Grid Graph Topology
    gridGraphOpen, setGridGraphOpen,
    // Planning Intelligence Panel
    planningIntelOpen, setPlanningIntelOpen,
    // BESS Panel
    bessPanelOpen, setBessPanelOpen,
    // Portfolio Panel
    portfolioPanelOpen, setPortfolioPanelOpen,
    // Cable Routing Panel
    cableRoutingOpen, setCableRoutingOpen,
    // Yield Assessment Panel
    yieldAssessmentOpen, setYieldAssessmentOpen,
    // Construction Panel
    constructionPanelOpen, setConstructionPanelOpen,
    // BESS Facility Twin
    bessFacilityOpen, setBessFacilityOpen,
    // Hardware Configurator
    hwConfigOpen, setHwConfigOpen,
    // Gemini 3D Asset Modeller
    asset3dOpen, setAsset3dOpen,
    // Palantir-style shared selection
    selectedEntity, setSelectedEntity,
    actionSidebarOpen, setActionSidebarOpen,
    // Thermal Model (TEASER)
    thermalModelOpen, setThermalModelOpen,
    // Terrain Analysis Panel
    terrainAnalysisOpen, setTerrainAnalysisOpen,
    // Reports Hub Panel
    reportsHubOpen, setReportsHubOpen,
    // Electrical Design Panel
    electricalDesignOpen, setElectricalDesignOpen,
    // Documents Panel
    documentsPanelOpen, setDocumentsPanelOpen,
    // Tier 3 Panels
    ppaOriginationOpen, setPpaOriginationOpen,
    workflowPanelOpen, setWorkflowPanelOpen,
    assessmentSnapshotOpen, setAssessmentSnapshotOpen,
    exportPanelOpen, setExportPanelOpen,
    alertRulesOpen, setAlertRulesOpen,
    prospectorV2Open, setProspectorV2Open,
    // GeeFlow
    geeflowData, setGeeflowData,
    geeflowLoading, setGeeflowLoading,
    geeflowJobId, setGeeflowJobId,
    // Real Site Context
    realSiteContext, setRealSiteContext,
    // Vision AI
    visionData, setVisionData,
    visionLoading, setVisionLoading,
    visionUploads, setVisionUploads,
    digitalTwinOpen, setDigitalTwinOpen,
    terrainTwinOpen, setTerrainTwinOpen,
    twinData, setTwinData,
    // Loading
    loading, agentLoading,
    // Layout
    layoutMode, setLayoutMode,
    componentLayout, setComponentLayout,
    selectedLayoutItem, setSelectedLayoutItem,
    customBom, setCustomBom,
    solarCatalogue, setSolarCatalogue,
    bomAbortRef,
    // DesignCanvas view mode
    designCanvasMode, setDesignCanvasMode,
    // Placed assets (map drag-drop)
    placedAssets, setPlacedAssets, addPlacedAsset, removePlacedAsset, clearPlacedAssets,
    assetValidations, designProjectId, setDesignProjectId, designDirty, saveDesign, loadDesign,
    energyFlowOpen, setEnergyFlowOpen,
    // EPC
    selectedLsoa, setSelectedLsoa,
    epcZonesField, setEpcZonesField,
    epcDomField, setEpcDomField,
    epcNondomField, setEpcNondomField,
    postcodesField, setPostcodesField,
    // UI
    activeTab, setActiveTab, selectTab,
    panelOpen, setPanelOpen,
    slopeOpacity, setSlopeOpacity,
    // Intent-driven UI
    activeIntent, setActiveIntent,
    commandCollapsed, setCommandCollapsed,
    analyticsCollapsed, setAnalyticsCollapsed,
    // Workflow
    workflowStage, setWorkflowStage, studySubStep, setStudySubStep,
    workflowHistory, navigateWorkflow,
    dashboardOpen, setDashboardOpen,
    // Layers
    layers, setLayers, toggleLayer,
    // Chat layers
    chatLayers, setChatLayers,
    // Chained Workflows
    workflowResults, setWorkflowResults,
    workflowSummary, setWorkflowSummary,
    workflowRunning, workflowProgress,
    runWorkflow,
    // Actions
    loadSite, runAgent, runDeferral,
    // Settings
    settings, settingsForm,
    saveSettings, resetSettingsForm, updateSettingsForm,
  };

  return <SiteContext.Provider value={value}>{children}</SiteContext.Provider>;
}

export function useSite() {
  const ctx = useContext(SiteContext);
  if (!ctx) throw new Error("useSite must be used within SiteProvider");
  return ctx;
}

export default SiteContext;
