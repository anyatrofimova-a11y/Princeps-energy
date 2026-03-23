import React, { useState, useEffect, useRef, useCallback, lazy, Suspense } from "react";
import mapboxgl from "mapbox-gl";
import { useSite } from "./SiteContext";
import api from "./services/api";

// ── Core layout (always loaded) ──
import AppShell from "./components/shell/AppShell";
import WorkspaceRouter from "./components/workspace/WorkspaceRouter";
import MapView from "./components/MapView";
import CopilotWidget from "./components/CopilotWidget";
import OnboardingDemo from "./components/OnboardingDemo";
import ErrorBoundary from "./components/ErrorBoundary";
import LayerRail from "./components/LayerRail";
import MapLegend from "./components/MapLegend";
import MapAssetLayer from "./components/MapAssetLayer";
import DCMapOverlay from "./components/DCMapOverlay";
import PortfolioMapOverlay from "./components/PortfolioMapOverlay";
import FinancialStrip from "./components/FinancialStrip";
import IntelligencePanel from "./components/IntelligencePanel";
import Asset3DOverlay from "./components/Asset3DOverlay";
import Google3DTilesOverlay from "./components/Google3DTilesOverlay";
import CameraToolbar from "./components/CameraToolbar";
import SitePicker from "./components/SitePicker";
import LiveStrip from "./components/LiveStrip";
import ConstraintTimeline from "./components/ConstraintTimeline";
import ThemeToggle from "./components/ThemeToggle";
// SmartOverlays removed — replaced by copilot auto-suggestions
import ActionSidebar from "./components/ActionSidebar";
import AIOrb from "./components/AIOrb";
import NotificationCentre from "./components/NotificationCentre";
import StartupOverlay, { saveRecentSite } from "./components/StartupOverlay";
import { useWorkspace } from "./contexts/WorkspaceContext";

// ── Lazy-loaded overlays (split into separate chunks) ──
const DigitalTwin = lazy(() => import("./components/DigitalTwin"));
const TerrainTwin = lazy(() => import("./components/TerrainTwin"));
const UnifiedTwin = lazy(() => import("./components/UnifiedTwin"));
const GridTwin = lazy(() => import("./components/GridTwin"));
const BEMSDigitalTwin = lazy(() => import("./components/BEMSDigitalTwin"));
const BESSFacilityTwin = lazy(() => import("./components/BESSFacilityTwin"));
const DataCentreTwin = lazy(() => import("./components/DataCentreTwin"));
const AssetInspector = lazy(() => import("./components/AssetInspector"));
const GridGraphView = lazy(() => import("./components/GridGraphView"));
const HardwareConfigurator = lazy(() => import("./components/HardwareConfigurator"));
const Asset3DModeller = lazy(() => import("./components/Asset3DModeller"));
const ThermalModelPanel = lazy(() => import("./components/ThermalModelPanel"));
const DCLandingPage = lazy(() => import("./components/DCLandingPage"));
const DCComparisonDashboard = lazy(() => import("./components/DCComparisonDashboard"));
const NOMExplorer = lazy(() => import("./components/NOMExplorer"));
const SettingsPage = lazy(() => import("./components/SettingsPage"));
const PitchPage = lazy(() => import("./components/PitchPage"));
const ProjectPipeline = lazy(() => import("./components/ProjectPipeline"));
const SiteDashboard = lazy(() => import("./components/SiteDashboard"));
const SiteDashboardV2 = lazy(() => import("./components/SiteDashboardV2"));
const CommandPalette = lazy(() => import("./components/shell/CommandPalette"));
const DrawingToolbar = lazy(() => import("./components/DrawingToolbar"));
const DashboardBuilder = lazy(() => import("./components/DashboardBuilder"));
const AssessmentWizard = lazy(() => import("./components/AssessmentWizard"));
const ComponentPalette = lazy(() => import("./components/ComponentPalette"));
const AssetDock = lazy(() => import("./components/AssetDock"));
const EnergyFlowPanel = lazy(() => import("./components/EnergyFlowPanel"));
const ScenarioCompare = lazy(() => import("./components/ScenarioCompare"));

const LazyFallback = () => <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.5)", zIndex: 9999, color: "#fff", fontSize: 13 }}>Loading...</div>;
import {
  MODES, createDrawState, handleClick as drawHandleClick, handleDoubleClick as drawHandleDoubleClick,
  moveVertex, insertVertex, deleteFeature, getMeasurements, findSnapTarget,
} from "./lib/draw-modes";

export default function App() {
  const {
    parcelId, setParcelId,
    pickedLocation, setPickedLocation,
    pickMode, setPickMode,
    samCapacity, samDay,
    loading,
    layers, setLayers,
    slopeOpacity,
    epcZonesField, epcDomField, epcNondomField, postcodesField,
    layoutMode, setLayoutMode,
    componentLayout, setCustomBom, bomAbortRef,
    solarCatalogue, setSolarCatalogue,
    loadSite, runDeferral,
    setDemandForecast, setAgilePricing,
    chatLayers, setChatLayers,
    setActiveTab, setPanelOpen,
    setSelectedLsoa,
    dashboardOpen, setDashboardOpen,
    digitalTwinOpen, setDigitalTwinOpen, terrainTwinOpen, setTerrainTwinOpen, twinData, realSiteContext,
    workflowStage,
    gridTwinOpen, setGridTwinOpen,
    bemsOpen, setBemsOpen,
    assetInspectorOpen, setAssetInspectorOpen,
    gridGraphOpen, setGridGraphOpen,
    bessFacilityOpen, setBessFacilityOpen,
    hwConfigOpen, setHwConfigOpen,
    asset3dOpen, setAsset3dOpen,
    setSelectedEntity,
    thermalModelOpen, setThermalModelOpen,
    dcTwinOpen, setDcTwinOpen,
    dcLandingOpen, setDcLandingOpen,
    dcComparisonOpen, setDcComparisonOpen,
    dcComparisonSites, setDcComparisonSites,
    activeIntent,
    placedAssets, addPlacedAsset, removePlacedAsset, clearPlacedAssets,
    assetValidations, designProjectId, setDesignProjectId, designDirty, saveDesign, loadDesign,
    energyFlowOpen, setEnergyFlowOpen,
    solarYield, gridContext,
  } = useSite();

  const { activeWorkspace, setActiveWorkspace, navigateToIntent } = useWorkspace();

  const [mapInstance, setMapInstance] = useState(null);
  const [pipelineOpen, setPipelineOpen] = useState(false);
  const [dashV2Closed, setDashV2Closed] = useState(false);

  // Re-open dashboard when a new site is picked
  useEffect(() => { if (pickedLocation) setDashV2Closed(false); }, [pickedLocation]);
  const [scenarioCompareOpen, setScenarioCompareOpen] = useState(false);
  const [dashboardBuilderOpen, setDashboardBuilderOpen] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [demoOpen, setDemoOpen] = useState(() => !localStorage.getItem("princeps_onboarded"));
  const [backendReady, setBackendReady] = useState(false);
  const handleBackendReady = useCallback(() => setBackendReady(true), []);

  // ── Linked Views: bridge map entity clicks to ActionSidebar ──
  useEffect(() => {
    const handler = (e) => {
      const d = e.detail;
      if (d) {
        setSelectedEntity({
          type: d.voltage_kv ? "substation" : "site",
          id: d.id || d.name,
          data: d,
          source: "map",
        });
      }
    };
    window.addEventListener("princeps-node-click", handler);
    return () => window.removeEventListener("princeps-node-click", handler);
  }, [setSelectedEntity]);

  // ── Linked Views: bridge intent triggers from SmartOverlays ──
  useEffect(() => {
    const handler = (e) => {
      const { intent } = e.detail || {};
      if (intent && parcelId) {
        runAgent(parcelId, intent, samCapacity, samDay);
      }
    };
    window.addEventListener("princeps-run-intent", handler);
    return () => window.removeEventListener("princeps-run-intent", handler);
  }, [parcelId, samCapacity, samDay]);

  // Handle intent selection from StartupOverlay
  const handleStartupIntent = useCallback((intentId, siteData) => {
    switch (intentId) {
      case "find":
        setActiveWorkspace("analyse");
        setPickMode(true);
        break;
      case "assess":
        setActiveWorkspace("analyse");
        navigateToIntent("feasibility");
        break;
      case "grid":
        setActiveWorkspace("analyse");
        navigateToIntent("grid_connection");
        break;
      case "portfolio":
        setActiveWorkspace("home");
        setPipelineOpen(true);
        break;
      case "recent":
        if (siteData?.lat && siteData?.lon) {
          setPickedLocation({ lat: siteData.lat, lon: siteData.lon });
          if (siteData.parcelId) {
            setParcelId(siteData.parcelId);
            loadSite(siteData.parcelId, samCapacity, samDay);
          }
          setActiveWorkspace("analyse");
        }
        break;
      default:
        break;
    }
  }, [setActiveWorkspace, navigateToIntent, setPickMode, setPickedLocation, setParcelId, loadSite, samCapacity, samDay]);

  // ── Map drop handler: place asset at lat/lon ──
  const handleMapDrop = useCallback((e) => {
    e.preventDefault();
    const raw = e.dataTransfer.getData("application/princeps-asset");
    if (!raw || !mapInstance) return;
    try {
      const asset = JSON.parse(raw);
      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const lngLat = mapInstance.unproject([x, y]);
      addPlacedAsset({
        assetType: asset.id,
        label: asset.label,
        color: asset.color,
        mw: asset.defaultMW || 0,
        lat: lngLat.lat,
        lon: lngLat.lng,
      });
    } catch (err) {
      console.error("Drop parse error:", err);
    }
  }, [mapInstance, addPlacedAsset]);

  const handleMapDragOver = useCallback((e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  // Handle map layers from chat — add layer + auto-zoom to fit
  const handleChatMapLayer = useCallback((layer) => {
    setChatLayers(prev => [...prev, layer]);
    if (mapInstance && layer.geojson?.features?.length) {
      const bounds = new mapboxgl.LngLatBounds();
      for (const f of layer.geojson.features) {
        const geom = f.geometry;
        if (!geom) continue;
        if (geom.type === "Point") {
          bounds.extend(geom.coordinates);
        } else if (geom.type === "MultiPoint" || geom.type === "LineString") {
          geom.coordinates.forEach(c => bounds.extend(c));
        } else if (geom.type === "Polygon" || geom.type === "MultiLineString") {
          geom.coordinates.forEach(ring => ring.forEach(c => bounds.extend(c)));
        } else if (geom.type === "MultiPolygon") {
          geom.coordinates.forEach(poly => poly.forEach(ring => ring.forEach(c => bounds.extend(c))));
        }
      }
      if (!bounds.isEmpty()) {
        mapInstance.fitBounds(bounds, { padding: 60, maxZoom: 16, duration: 2000 });
      }
    }
  }, [setChatLayers, mapInstance]);

  const removeChatLayer = useCallback((layerId) => {
    setChatLayers(prev => prev.filter(l => l.id !== layerId));
  }, [setChatLayers]);

  // Handle zoom-to events from chat
  const handleChatZoomTo = useCallback(({ lat, lon, zoom, label }) => {
    if (!mapInstance) return;
    mapInstance.flyTo({
      center: [lon, lat],
      zoom: zoom || 14,
      pitch: 45,
      duration: 2000,
      essential: true,
    });
  }, [mapInstance]);

  // NOM Explorer + Settings modes
  const [nomMode, setNomMode] = useState(false);
  const [settingsMode, setSettingsMode] = useState(false);
  const [pitchMode, setPitchMode] = useState(false);
  const [cmdPaletteOpen, setCmdPaletteOpen] = useState(false);
  const [intelligenceOpen, setIntelligenceOpen] = useState(false);

  // Cmd+K / Ctrl+K to open command palette
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCmdPaletteOpen(p => !p);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const handleNomAnalyse = useCallback((sub) => {
    setNomMode(false);
    if (sub && sub.lat && sub.lon) {
      setPickedLocation({ lat: sub.lat, lon: sub.lon });
    }
  }, [setPickedLocation]);

  // Fetch solar catalogue on mount
  useEffect(() => {
    api.inventory.catalogue().then(d => { if (d) setSolarCatalogue(d); }).catch(err => console.warn("[App] catalogue fetch failed:", err));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch demand forecast + Agile pricing on mount
  useEffect(() => {
    api.grid.demandForecast().then(d => { if (d) setDemandForecast(d); }).catch(err => console.warn("[App] demand forecast fetch failed:", err));
    api.grid.agilePricing("C").then(d => { if (d && !d.error) setAgilePricing(d); }).catch(err => console.warn("[App] agile pricing fetch failed:", err));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Debounced custom BOM recalculation
  useEffect(() => {
    if (!layoutMode || !parcelId || componentLayout.length === 0) {
      if (componentLayout.length === 0) setCustomBom(null);
      return;
    }
    const timer = setTimeout(async () => {
      if (bomAbortRef.current) bomAbortRef.current.abort();
      bomAbortRef.current = new AbortController();
      try {
        const data = await api.site.bomCustom(parcelId, componentLayout, bomAbortRef.current.signal);
        if (data) setCustomBom(data);
      } catch (err) {
        if (err.name !== "AbortError") console.error(err);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [componentLayout, layoutMode, parcelId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Handle zone click -> show EPC summary
  const handleZoneClick = (lsoaId) => {
    setSelectedLsoa(lsoaId);
    setActiveTab("epc");
    setPanelOpen(true);
  };

  // Handle map click in pick mode
  const handleMapPick = async ({ lat, lon }) => {
    console.log("[App] handleMapPick called:", { lat, lon });
    setPickMode(false);
    setPickedLocation({ lat, lon });
    if (mapInstance) {
      mapInstance.flyTo({
        center: [lon, lat], zoom: 14, pitch: 60, bearing: 0,
        duration: 3000, essential: true,
      });
    }
    try {
      const data = await api.site.fromLocation(lat, lon);
      if (data?.parcel_id) {
        setParcelId(data.parcel_id);
        setPickedLocation({ lat: data.lat, lon: data.lon });
        await loadSite(data.parcel_id, samCapacity, samDay);
        runDeferral(5, 4);
        // Save to recent sites for StartupOverlay
        saveRecentSite({
          id: data.parcel_id,
          name: data.location_name || data.parcel_id,
          lat: data.lat, lon: data.lon,
          parcelId: data.parcel_id,
          lastModified: new Date().toLocaleDateString("en-GB"),
        });
      }
    } catch (err) { console.error(err); }
  };

  const handleAnalyse = () => {
    loadSite(parcelId, samCapacity, samDay);
    runDeferral(5, 4);
  };

  const handleLayoutToggle = () => {
    setLayoutMode(p => !p);
    if (!layoutMode) { setActiveTab("terrain"); setPanelOpen(true); }
  };

  // ── Drawing state (nebula.gl-style) ──
  const [drawState, setDrawState] = useState(createDrawState);

  const handleDrawModeChange = useCallback((mode) => {
    // Clear pick mode when entering a draw mode — they are mutually exclusive
    if (mode && mode !== "view") {
      setPickMode(false);
    }
    setDrawState(s => ({ ...s, mode, clickSequence: [], mouseCoord: null, selectedIndex: -1 }));
  }, [setPickMode]);

  const handleDrawClick = useCallback((coord, handleIndex) => {
    setDrawState(s => {
      const snapped = findSnapTarget(s, coord);
      const finalCoord = snapped || coord;
      const { state } = drawHandleClick(s, finalCoord, handleIndex);
      return state;
    });
  }, []);

  const handleDrawDoubleClick = useCallback(() => {
    setDrawState(s => {
      const { state } = drawHandleDoubleClick(s);

      // ── Draw-to-Analyze: when a polygon is completed, auto-run feasibility ──
      const lastFeature = state.features.features[state.features.features.length - 1];
      if (lastFeature?.geometry?.type === "Polygon" && lastFeature.geometry.coordinates[0]?.length >= 4) {
        const coords = lastFeature.geometry.coordinates[0];
        let sumLat = 0, sumLon = 0;
        for (const [lon, lat] of coords) { sumLat += lat; sumLon += lon; }
        const centLat = sumLat / coords.length;
        const centLon = sumLon / coords.length;

        let area = 0;
        for (let i = 0; i < coords.length - 1; i++) {
          area += coords[i][0] * coords[i + 1][1] - coords[i + 1][0] * coords[i][1];
        }
        const areaM2 = Math.abs(area) * 0.5 * 111320 * 111320 * Math.cos(centLat * Math.PI / 180);
        const areaHa = (areaM2 / 10000).toFixed(1);

        // Auto-pick centroid as site
        setTimeout(() => {
          handleMapPick({ lat: centLat, lon: centLon });
        }, 300);

        // Auto-persist boundary + create project (fire-and-forget)
        setTimeout(async () => {
          try {
            const projectName = `Site ${centLat.toFixed(4)}N, ${Math.abs(centLon).toFixed(4)}W`;
            const project = await api.projects.create({
              name: projectName,
              technology: "solar",
              capacity_mw: Math.round(parseFloat(areaHa) * 0.5 * 10) / 10,
              stage: "prospect",
              lat: centLat, lon: centLon,
              description: `${areaHa} ha site boundary drawn on map`,
            });
            if (project?.project_id) {
              setDesignProjectId(project.project_id);
              await api.landMgmt.createBoundary({
                project_id: project.project_id,
                name: `${projectName} — Site Boundary`,
                boundary_type: "site",
                geojson: lastFeature.geometry,
              });
            }
          } catch (e) {
            console.warn("Auto-save boundary:", e);
          }
        }, 500);
      }

      return state;
    });
  }, [handleMapPick, setDesignProjectId]);

  const handleDrawMouseMove = useCallback((coord) => {
    setDrawState(s => ({ ...s, mouseCoord: coord }));
  }, []);

  const handleDrawSelectFeature = useCallback((createdTs) => {
    setDrawState(s => {
      const idx = s.features.features.findIndex(f => String(f.properties.created) === String(createdTs));
      return { ...s, selectedIndex: idx };
    });
  }, []);

  const handleDrawDragVertex = useCallback((action, featureIndex, vertexIndex, coord) => {
    setDrawState(s => {
      if (action === "move") return moveVertex(s, featureIndex, vertexIndex, coord);
      if (action === "insert") return insertVertex(s, featureIndex, vertexIndex, coord);
      return s;
    });
  }, []);

  const handleDeleteDrawFeature = useCallback((idx) => {
    setDrawState(s => deleteFeature(s, idx));
  }, []);

  const handleClearDrawFeatures = useCallback(() => {
    setDrawState(s => ({ ...s, features: { type: "FeatureCollection", features: [] }, selectedIndex: -1 }));
  }, []);

  const handleExportGeoJSON = useCallback(() => {
    const json = JSON.stringify(drawState.features, null, 2);
    navigator.clipboard.writeText(json).catch(() => {});
  }, [drawState.features]);

  // Escape key to cancel drawing
  useEffect(() => {
    const handler = (e) => { if (e.key === "Escape") handleDrawModeChange(MODES.VIEW); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleDrawModeChange]);

  const measurement = getMeasurements(drawState);

  // Full-screen overlays
  if (nomMode) {
    return <NOMExplorer onExit={() => setNomMode(false)} onAnalyseSubstation={handleNomAnalyse} />;
  }
  if (settingsMode) {
    return <SettingsPage onExit={() => setSettingsMode(false)} />;
  }
  if (pitchMode) {
    return <PitchPage onExit={() => setPitchMode(false)} />;
  }

  // Map content (rendered inside CenterCanvas via WorkspaceRouter)
  const mapContent = (
    <div className="map-area-inner" onDrop={handleMapDrop} onDragOver={handleMapDragOver}>
      <ErrorBoundary name="Map">
        <MapView
          slopeOpacity={slopeOpacity}
          layers={layers}
          pickMode={pickMode}
          onPick={handleMapPick}
          pickedLocation={pickedLocation}
          onZoneClick={handleZoneClick}
          epcFields={{ epcZones: epcZonesField, epcDom: epcDomField, epcNondom: epcNondomField, postcodes: postcodesField }}
          drawState={drawState}
          onDrawClick={handleDrawClick}
          onDrawDoubleClick={handleDrawDoubleClick}
          onDrawMouseMove={handleDrawMouseMove}
          onDrawSelectFeature={handleDrawSelectFeature}
          onDrawDragVertex={handleDrawDragVertex}
          chatLayers={chatLayers}
          onMapReady={setMapInstance}
        />
      </ErrorBoundary>

      <ErrorBoundary name="MapAssetLayer" fallback={null}>
        <MapAssetLayer map={mapInstance} />
      </ErrorBoundary>
      <ErrorBoundary name="DCMapOverlay" fallback={null}>
        <DCMapOverlay mapInstance={mapInstance} dcAssets={placedAssets.filter(a => a.assetType === "data_centre")} />
      </ErrorBoundary>
      <ErrorBoundary name="Asset3DOverlay" fallback={null}>
        <Asset3DOverlay mapInstance={mapInstance} assets={placedAssets} validations={assetValidations} />
      </ErrorBoundary>
      <ErrorBoundary name="Google3DTilesOverlay" fallback={null}>
        <Google3DTilesOverlay mapInstance={mapInstance} enabled={!!layers.google3d} />
      </ErrorBoundary>

      {/* Portfolio pins — all pipeline projects on map */}
      <ErrorBoundary name="PortfolioMapOverlay" fallback={null}>
        <PortfolioMapOverlay
          map={mapInstance}
          visible={workflowStage === "site" || !parcelId}
          onSelectProject={(p) => {
            if (p.lat && p.lon) {
              setPickedLocation({ lat: p.lat, lon: p.lon });
              mapInstance?.flyTo({ center: [p.lon, p.lat], zoom: 13, duration: 1500 });
            }
          }}
        />
      </ErrorBoundary>

      {/* Layer controls */}
      <LayerRail chatLayers={chatLayers} onRemoveChatLayer={removeChatLayer} />
      {chatLayers.length > 0 && <MapLegend chatLayers={chatLayers} />}
      {layers.gridConstraints && <ConstraintTimeline map={mapInstance} visible />}

      {/* Camera toolbar — only when a site is selected */}
      {pickedLocation && <CameraToolbar map={mapInstance} pickedLocation={pickedLocation} />}

      <Suspense fallback={null}>
        <DrawingToolbar
          drawMode={drawState.mode}
          onModeChange={handleDrawModeChange}
          featureCount={drawState.features.features.length}
          selectedIndex={drawState.selectedIndex}
          onDeleteFeature={handleDeleteDrawFeature}
          onClearAll={handleClearDrawFeatures}
          onExportGeoJSON={handleExportGeoJSON}
          measurement={measurement}
          onAnalyseArea={() => {
            // Get centroid of last drawn polygon and run feasibility
            const lastFeature = drawState.features.features[drawState.features.features.length - 1];
            if (lastFeature?.geometry?.type === "Polygon") {
              const coords = lastFeature.geometry.coordinates[0];
              let sumLat = 0, sumLon = 0;
              for (const [lon, lat] of coords) { sumLat += lat; sumLon += lon; }
              const centLat = sumLat / coords.length;
              const centLon = sumLon / coords.length;
              handleMapPick({ lat: centLat, lon: centLon });
            }
          }}
        />
      </Suspense>

      {/* Site picker — SITE stage floating search */}
      {workflowStage === "site" && (
        <SitePicker map={mapInstance} onPick={handleMapPick} />
      )}

      {pickMode && workflowStage !== "site" && (
        <div className="pick-banner">Click anywhere on the map to select a site</div>
      )}

      <Suspense fallback={null}>
        {layoutMode && solarCatalogue && (
          <ComponentPalette catalogue={solarCatalogue} />
        )}

        {/* Asset Dock — only visible in Design workspace or Plan stage */}
        {(activeWorkspace === "design" || workflowStage === "plan") && (
          <ErrorBoundary name="AssetDock" fallback={null}>
            <AssetDock
              placedAssets={placedAssets}
              mapInstance={mapInstance}
              onAssetPlaced={addPlacedAsset}
            />
          </ErrorBoundary>
        )}

        {/* Energy Flow Panel — only shows when assets are actually placed */}
        {energyFlowOpen && placedAssets.length > 0 && (
          <EnergyFlowPanel
            placedAssets={placedAssets}
            solarYield={solarYield}
            gridContext={gridContext}
            onClose={() => setEnergyFlowOpen(false)}
          />
        )}

        {/* SiteDashboardV2 — auto-shows when site is selected, past discovery stage */}
        {pickedLocation && workflowStage !== "site" && !dashV2Closed && (
          <SiteDashboardV2 onClose={() => setDashV2Closed(true)} />
        )}
      </Suspense>

    </div>
  );

  const handleCmdAction = useCallback((action) => {
    switch (action) {
      case "twin": setGridTwinOpen(true); break;
      case "site-twin": setDigitalTwinOpen(true); break;
      case "terrain": setTerrainTwinOpen(true); break;
      case "bems": setBemsOpen(true); break;
      case "inspect": setAssetInspectorOpen(true); break;
      case "graph": setGridGraphOpen(true); break;
      case "pitch": setPitchMode(true); break;
      case "nom": setNomMode(true); break;
      case "bess-facility": setBessFacilityOpen(true); break;
      case "hardware": setHwConfigOpen(true); break;
      case "asset-3d": setAsset3dOpen(true); break;
      case "wizard": setWizardOpen(true); break;
      case "dashboard": setDashboardBuilderOpen(true); break;
      case "thermal": setThermalModelOpen(true); break;
      case "dc-twin": setDcTwinOpen(true); break;
      case "dc-landing": setDcLandingOpen(true); break;
      case "dc-compare": setDcComparisonOpen(true); break;
      case "pipeline": setActiveWorkspace("pipeline"); break;
      case "compare": setScenarioCompareOpen(true); break;
      case "demo": setDemoOpen(true); break;
      case "settings": setSettingsMode(true); break;
      case "intelligence": setIntelligenceOpen(true); break;
      default: break;
    }
  }, []);

  return (
    <AppShell
      onGridTwin={() => setGridTwinOpen(true)}
      onBems={() => setBemsOpen(true)}
      onAssetInspect={() => setAssetInspectorOpen(true)}
      onGridGraph={() => setGridGraphOpen(true)}
      onBessFacility={() => setBessFacilityOpen(true)}
      onHardware={() => setHwConfigOpen(true)}
      onAsset3d={() => setAsset3dOpen(true)}
      onThermal={() => setThermalModelOpen(true)}
      onDcTwin={() => setDcTwinOpen(true)}
      onDcLanding={() => setDcLandingOpen(true)}
      onDcCompare={() => setDcComparisonOpen(true)}
      onPipeline={() => setActiveWorkspace("pipeline")}
      onPitch={() => setPitchMode(true)}
      onNomExplorer={() => setNomMode(true)}
      onSettings={() => setSettingsMode(true)}
      onCommandPalette={() => setCmdPaletteOpen(true)}
      onIntelligence={() => setIntelligenceOpen(true)}
    >
      <div className="app-shell-content">
        <WorkspaceRouter mapContent={mapContent} />
      </div>

      <ErrorBoundary name="CopilotWidget" fallback={null}>
        <CopilotWidget onMapLayer={handleChatMapLayer} onZoomTo={handleChatZoomTo} onAction={handleCmdAction} />
      </ErrorBoundary>

      {/* AI Orb — click to open copilot with context-aware suggestion */}
      <AIOrb
        onOpenChat={(suggestion) => {
          // Dispatch event to copilot to open and optionally send a message
          window.dispatchEvent(new CustomEvent("princeps-chat", {
            detail: { text: suggestion || "" },
          }));
        }}
        chatOpen={false}
      />

      {/* Command Palette */}
      <Suspense fallback={null}>
      <CommandPalette
        open={cmdPaletteOpen}
        onClose={() => setCmdPaletteOpen(false)}
        onAction={handleCmdAction}
      />

      {/* Onboarding Demo */}
      {demoOpen && (
        <OnboardingDemo onClose={() => { setDemoOpen(false); localStorage.setItem("princeps_onboarded", "1"); }} />
      )}

      {/* Pipeline is now a workspace tab — no floating overlay */}

      {/* Unified Digital Twin — Site view + Terrain analysis in one overlay */}
      {(digitalTwinOpen || terrainTwinOpen) && (
        <Suspense fallback={<LazyFallback />}>
          <UnifiedTwin
            initialMode={terrainTwinOpen ? "terrain" : "site"}
            data={twinData}
            realContext={realSiteContext}
            lat={pickedLocation?.lat || 52.5}
            lon={pickedLocation?.lon || -1.5}
            placedAssets={placedAssets}
            onClose={() => { setDigitalTwinOpen(false); setTerrainTwinOpen(false); }}
          />
        </Suspense>
      )}

      {/* 3D Grid Digital Twin overlay */}
      {gridTwinOpen && (
        <GridTwin onClose={() => setGridTwinOpen(false)} />
      )}

      {/* BEMS Digital Twin overlay */}
      {bemsOpen && (
        <BEMSDigitalTwin onClose={() => setBemsOpen(false)} />
      )}

      {/* Asset Inspector (LiDAR) overlay */}
      {assetInspectorOpen && (
        <AssetInspector onClose={() => setAssetInspectorOpen(false)} />
      )}

      {/* Grid Graph Topology overlay */}
      {gridGraphOpen && (
        <GridGraphView
          lat={pickedLocation?.lat}
          lon={pickedLocation?.lon}
          onClose={() => setGridGraphOpen(false)}
        />
      )}

      {/* BESS Facility Digital Twin overlay */}
      {bessFacilityOpen && (
        <BESSFacilityTwin onClose={() => setBessFacilityOpen(false)} />
      )}

      {/* Data Centre Digital Twin overlay */}
      {dcTwinOpen && (
        <DataCentreTwin onClose={() => setDcTwinOpen(false)} />
      )}

      {/* DC Landing Page overlay */}
      {dcLandingOpen && (
        <DCLandingPage
          onClose={() => setDcLandingOpen(false)}
          onScoreSite={(lat, lon, mw, profile) => {
            setDcLandingOpen(false);
            setPickedLocation({ lat, lon });
          }}
          onCompareSites={(sites) => {
            setDcLandingOpen(false);
            setDcComparisonSites(sites);
            setDcComparisonOpen(true);
          }}
        />
      )}

      {/* DC Comparison Dashboard overlay */}
      {dcComparisonOpen && (
        <DCComparisonDashboard
          onClose={() => setDcComparisonOpen(false)}
          initialSites={dcComparisonSites}
        />
      )}

      {/* Hardware Configurator panel */}
      {hwConfigOpen && (
        <HardwareConfigurator onClose={() => setHwConfigOpen(false)} />
      )}

      {/* Gemini 3D Asset Modeller */}
      {asset3dOpen && (
        <Asset3DModeller
          onClose={() => setAsset3dOpen(false)}
          onPlaceOnMap={(spec) => {
            setAsset3dOpen(false);
            // Add placed asset via existing system
            if (pickedLocation && spec) {
              addPlacedAsset({
                assetType: spec.name?.includes("Data Centre") ? "data_centre" : "generic",
                lat: pickedLocation.lat,
                lon: pickedLocation.lon,
                spec,
              });
            }
          }}
        />
      )}

      {/* Live Dashboard Builder */}
      {dashboardBuilderOpen && (
        <DashboardBuilder onClose={() => setDashboardBuilderOpen(false)} />
      )}

      {/* Assessment Wizard */}
      {wizardOpen && (
        <AssessmentWizard
          onClose={() => setWizardOpen(false)}
          pickedLocation={pickedLocation}
        />
      )}

      {/* Thermal Model panel */}
      {thermalModelOpen && (
        <ThermalModelPanel onClose={() => setThermalModelOpen(false)} />
      )}

      {/* Scenario Comparison overlay */}
      {scenarioCompareOpen && (
        <ScenarioCompare
          scenarios={[]}
          onClose={() => setScenarioCompareOpen(false)}
          onRunAnalysis={async (scenario, callback) => {
            try {
              const data = await api.site.fromLocation(scenario.lat, scenario.lon);
              if (data) {
                const hw = data.grid_headroom_mw || data.headroom_mw || 0;
                callback({
                  solar_cf: data.capacity_factor || 0.105,
                  grid_headroom_mw: hw,
                  connection_cost_k: data.connection_cost_k || (hw > 50 ? 200 : 400),
                  timeline_months: data.timeline_months || 24,
                  revenue_yr: data.revenue_yr || (scenario.capacity_mw * 0.105 * 8760 * 50),
                  irr: data.irr || 0.08,
                  planning_risk: data.planning_risk || 0.3,
                  verdict: hw >= 50 ? "GO" : hw >= 10 ? "CAUTION" : "NO-GO",
                });
              }
            } catch (err) {
              console.error("Scenario analysis error:", err);
            }
          }}
        />
      )}
      </Suspense>

      {/* Intelligence Panel — regulatory alerts & market data */}
      {intelligenceOpen && (
        <IntelligencePanel onClose={() => setIntelligenceOpen(false)} />
      )}

      {/* Startup overlay — shown until backend health check passes */}
      {!backendReady && <StartupOverlay onReady={handleBackendReady} onIntent={handleStartupIntent} />}
    </AppShell>
  );
}
