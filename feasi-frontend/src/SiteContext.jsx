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

  // ── Layers ──
  const [layers, setLayers] = useState({
    slope: true, carbon: false, la: false, transport: false, hillshade: true,
    contours: true, environment: true, gridFlow: true, agilePricing: false,
    demandOverlay: false, flowFocus: false, osmPower: false,
    ndvi: false, satellite: false, aerial: true, lidarDtm: false, lidarDsm: false, landsat: false, viirs: false,
    ngedSubs: false,
    geeflowLandUse: false,
    geeflowOpportunities: false,
    electricityZones: false,
    epcZones: false, epcDom: false, epcNondom: false, postcodes: false,
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
    try {
      const results = await Promise.allSettled([
        api.site.heightmap(id),
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
    heightmap, explain, slopeStats, solarYield, solarHourly, mlSolar,
    deferral, energyPrice, gridContext, planningApps, energySystem,
    siteBom, bomAvail, agentResult, setAgentResult,
    demandForecast, setDemandForecast,
    agilePricing, setAgilePricing,
    stabilityData, setStabilityData,
    // GeeFlow
    geeflowData, setGeeflowData,
    geeflowLoading, setGeeflowLoading,
    geeflowJobId, setGeeflowJobId,
    // Loading
    loading, agentLoading,
    // Layout
    layoutMode, setLayoutMode,
    componentLayout, setComponentLayout,
    selectedLayoutItem, setSelectedLayoutItem,
    customBom, setCustomBom,
    solarCatalogue, setSolarCatalogue,
    bomAbortRef,
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
    // Layers
    layers, setLayers, toggleLayer,
    // Chat layers
    chatLayers, setChatLayers,
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
