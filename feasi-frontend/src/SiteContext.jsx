import React, { createContext, useContext, useState, useCallback, useRef, useMemo } from "react";
import api from "./services/api";

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
  // ── Settings ──
  const [settings, setSettings] = useState(loadSettings);
  const [settingsForm, setSettingsForm] = useState(loadSettings);

  const saveSettings = useCallback((form) => {
    setSettings(form);
    setSettingsForm(form);
    localStorage.setItem("princeps_settings", JSON.stringify(form));
  }, []);

  const resetSettingsForm = useCallback(() => {
    setSettingsForm(settings);
  }, [settings]);

  const updateSettingsForm = useCallback((updates) => {
    setSettingsForm(prev => ({ ...prev, ...updates }));
  }, []);
  // ── Site identity ──
  const [parcelId, setParcelId] = useState("");
  const [pickedLocation, setPickedLocation] = useState(null);
  const [pickMode, setPickMode] = useState(false);

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
  const [gridConnectionOpen, setGridConnectionOpen] = useState(false);
  const [gridHighlightSub, setGridHighlightSub] = useState(null); // candidate substation to highlight on map

  // ── Demand Forecast Panel ──
  const [demandForecastOpen, setDemandForecastOpen] = useState(false);

  // ── Grid Digital Twin ──
  const [gridTwinOpen, setGridTwinOpen] = useState(false);

  // ── Advanced Grid Panel ──
  const [advancedGridOpen, setAdvancedGridOpen] = useState(false);

  // ── Connection Strategy Panel ──
  const [connectionStrategyOpen, setConnectionStrategyOpen] = useState(false);

  // ── Dispatch Panel ──
  const [dispatchOpen, setDispatchOpen] = useState(false);

  // ── Route-to-Market Panel ──
  const [rtmOpen, setRtmOpen] = useState(false);

  // ── Sustainability Panel ──
  const [sustainabilityOpen, setSustainabilityOpen] = useState(false);

  // ── Investment Panel ──
  const [investmentOpen, setInvestmentOpen] = useState(false);

  // ── Data Centre Twin (unified) ──
  const [dcTwinOpen, setDcTwinOpen] = useState(false);
  const [dcLandingOpen, setDcLandingOpen] = useState(false);
  const [dcComparisonOpen, setDcComparisonOpen] = useState(false);
  const [dcComparisonSites, setDcComparisonSites] = useState([]);

  // ── BEMS Digital Twin ──
  const [bemsOpen, setBemsOpen] = useState(false);

  // ── Asset Inspector (LiDAR) ──
  const [assetInspectorOpen, setAssetInspectorOpen] = useState(false);

  // ── Grid Graph Topology ──
  const [gridGraphOpen, setGridGraphOpen] = useState(false);

  // ── BESS Facility Twin ──
  const [bessFacilityOpen, setBessFacilityOpen] = useState(false);

  // ── Hardware Configurator ──
  const [hwConfigOpen, setHwConfigOpen] = useState(false);

  // ── Gemini 3D Asset Modeller ──
  const [asset3dOpen, setAsset3dOpen] = useState(false);

  // ── Thermal Model (TEASER) ──
  const [thermalModelOpen, setThermalModelOpen] = useState(false);

  // ── Real Site Context (REPD, OSM, grid, TEC) ──
  const [realSiteContext, setRealSiteContext] = useState(null);

  // ── Vision AI ──
  const [visionData, setVisionData] = useState(null);
  const [visionLoading, setVisionLoading] = useState(false);
  const [visionUploads, setVisionUploads] = useState([]);
  const [digitalTwinOpen, setDigitalTwinOpen] = useState(false);
  const [terrainTwinOpen, setTerrainTwinOpen] = useState(false);
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

  // ── Placed assets (map drag-drop) with persistence + validation ──
  const [placedAssets, setPlacedAssets] = useState([]);
  const [energyFlowOpen, setEnergyFlowOpen] = useState(false);
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
  const [dashboardOpen, setDashboardOpen] = useState(false);

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
    google3d: false,
    gridConstraints: false,
    envConstraints: false,
    queueDepth: false,
    landParcels: false,
    planningDensity: false,
  });
  const toggleLayer = useCallback((id) => {
    setLayers(l => ({ ...l, [id]: !l[id] }));
  }, []);

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
      const val = (r) => r.status === "fulfilled" ? r.value : null;
      setHeightmap(val(results[0]));
      setExplain(val(results[1]));
      setSlopeStats(val(results[2]));
      setSolarYield(val(results[3]));
      setSolarHourly(val(results[4]));
      setMlSolar(val(results[5]));
      setEnergyPrice(val(results[6]));
      setGridContext(val(results[7]));
      setPlanningApps(val(results[8]));
      setEnergySystem(val(results[9]));
      setSiteBom(val(results[10]));
      setBomAvail(val(results[11]));
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
    // BESS Facility Twin
    bessFacilityOpen, setBessFacilityOpen,
    // Hardware Configurator
    hwConfigOpen, setHwConfigOpen,
    // Gemini 3D Asset Modeller
    asset3dOpen, setAsset3dOpen,
    // Thermal Model (TEASER)
    thermalModelOpen, setThermalModelOpen,
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
