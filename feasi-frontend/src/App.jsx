import React, { useState, useEffect, useRef, useCallback, lazy, Suspense } from "react";
import mapboxgl from "mapbox-gl";
import { useSite } from "./SiteContext";
import api from "./services/api";

// ── Core layout (always loaded) ──
import AppShell from "./components/shell/AppShell";
import WorkspaceRouter from "./components/workspace/WorkspaceRouter";
import MapView from "./components/MapView";
import OnboardingDemo from "./components/OnboardingDemo";
import ErrorBoundary from "./components/ErrorBoundary";
import LayerRail from "./components/LayerRail";
import MapLegend from "./components/MapLegend";
import MapAssetLayer from "./components/MapAssetLayer";
import DCMapOverlay from "./components/DCMapOverlay";
import PortfolioMapOverlay from "./components/PortfolioMapOverlay";
import IntelligencePanel from "./components/IntelligencePanel";
import Asset3DOverlay from "./components/Asset3DOverlay";
import Google3DTilesOverlay from "./components/Google3DTilesOverlay";
import GridTwinOverlay from "./components/GridTwinOverlay";
import NGEDLiveLayer from "./components/pulse/NGEDLiveLayer";
import DCEstateLayer from "./components/pulse/DCEstateLayer";
import GridIntelPanel from "./components/pulse/GridIntelPanel";
const CesiumMapOverlay = lazy(() => import("./components/CesiumMapOverlay"));
import CameraToolbar from "./components/CameraToolbar";
import SitePicker from "./components/SitePicker";
import ConstraintTimeline from "./components/ConstraintTimeline";
import MissionControl from "./components/MissionControl";
import ChatRail from "./components/shell/ChatRail";
import InboxBridge from "./components/InboxBridge";
import { useWorkspace } from "./contexts/WorkspaceContext";

const DeveloperConsole = lazy(() => import("./components/DeveloperConsole"));
const RedesignLayout = lazy(() => import("./components/shell/RedesignLayout"));

// ── Lazy-loaded overlays (split into separate chunks) ──
const DigitalTwin = lazy(() => import("./components/DigitalTwin"));
const TerrainTwin = lazy(() => import("./components/TerrainTwin"));
const UnifiedTwin = lazy(() => import("./components/UnifiedTwin"));
const GridTwin = lazy(() => import("./components/GridTwinCesium"));
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
const CapabilitiesPage = lazy(() => import("./components/CapabilitiesPage"));
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

  const { activeWorkspace, setActiveWorkspace, activeViewMode, setActiveViewMode } = useWorkspace();

  const [mapInstance, setMapInstance] = useState(null);
  const [devConsoleOpen, setDevConsoleOpen] = useState(false);
  const [dashV2Closed, setDashV2Closed] = useState(false);
  // Pulse · right-hand grid intel panel selection (substation / ECR / GSP / licence area)
  const [pulseSelection, setPulseSelection] = useState(null);
  const handlePulseSelect = useCallback((sel) => setPulseSelection(sel), []);
  const handlePulseClose = useCallback(() => setPulseSelection(null), []);

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

  // Dataset-layer activation from Datasets tab "Show on Map" buttons.
  // Reads ?dataset=<slug>&layer=<map_layer_slug> on mount, and also
  // subscribes to the runtime event so tab-switches without a reload work.
  useEffect(() => {
    const applyDataset = (slug, layer) => {
      if (!slug) return;
      try {
        window.dispatchEvent(new CustomEvent("princeps-apply-dataset-layer", {
          detail: { slug, layer, ts: Date.now() },
        }));
      } catch {}
    };
    try {
      const qs = new URLSearchParams(window.location.search);
      const slug = qs.get("dataset");
      const layer = qs.get("layer");
      if (slug) applyDataset(slug, layer);
    } catch {}
    const onActivate = (e) => {
      const { slug, layer } = e.detail || {};
      applyDataset(slug, layer);
    };
    window.addEventListener("princeps-activate-dataset-layer", onActivate);
    return () => window.removeEventListener("princeps-activate-dataset-layer", onActivate);
  }, []);

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
  const [capabilitiesMode, setCapabilitiesMode] = useState(false);
  const [cmdPaletteOpen, setCmdPaletteOpen] = useState(false);
  const [intelligenceOpen, setIntelligenceOpen] = useState(false);

  // Cmd+K / Ctrl+K to open command palette, Cmd+Shift+D for developer console
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCmdPaletteOpen(p => !p);
      }
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "d") {
        e.preventDefault();
        setDevConsoleOpen(p => !p);
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
  const handleMapPick = ({ lat, lon }) => {
    console.log("[App] handleMapPick called:", { lat, lon });
    setPickMode(false);
    setPickedLocation({ lat, lon });
    if (mapInstance) {
      mapInstance.flyTo({
        center: [lon, lat], zoom: 14, pitch: 60, bearing: 0,
        duration: 3000, essential: true,
      });
    }
    // Announce the agent — don't auto-run any analysis. User drives what happens next.
    window.dispatchEvent(new CustomEvent("princeps-chat", {
      detail: { announce: true, lat, lon },
    }));
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
  if (capabilitiesMode) {
    return <Suspense fallback={null}><CapabilitiesPage onExit={() => setCapabilitiesMode(false)} /></Suspense>;
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
      <ErrorBoundary name="GridTwinOverlay" fallback={null}>
        <GridTwinOverlay map={mapInstance} enabled={!!layers.gridTwin3d} />
      </ErrorBoundary>

      {/* Pulse · NGED live intelligence layers (headroom / ECR / GSP / licence areas) */}
      <ErrorBoundary name="NGEDLiveLayer" fallback={null}>
        <NGEDLiveLayer map={mapInstance} layers={layers} onSelect={handlePulseSelect} />
      </ErrorBoundary>

      {/* NESO098 · Consolidated DC estate (UKPN Large Demand List + DC-by-LA) */}
      <ErrorBoundary name="DCEstateLayer" fallback={null}>
        <DCEstateLayer map={mapInstance} layers={layers} onSelect={handlePulseSelect} />
      </ErrorBoundary>

      {/* Pulse · right-hand detail panel — only when a feature is selected */}
      {pulseSelection && (
        <GridIntelPanel selection={pulseSelection} onClose={handlePulseClose} />
      )}
      {layers.cesiumGlobe && (
        <ErrorBoundary name="CesiumMapOverlay" fallback={null}>
          <Suspense fallback={null}>
            <CesiumMapOverlay enabled={!!layers.cesiumGlobe} layers={layers} />
          </Suspense>
        </ErrorBoundary>
      )}

      {/* Portfolio pins — all pipeline projects on map. Always visible so the
          229-prospect / 188-energised pipeline shown in the header has a
          spatial counterpart on the Map tab (2026-04-19). */}
      <ErrorBoundary name="PortfolioMapOverlay" fallback={null}>
        <PortfolioMapOverlay
          map={mapInstance}
          visible={true}
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

      {/* Site picker — SITE stage floating search.
          Suppressed on grid-native views (Grid Graph, Pulse, Twin, …) which
          ship their own search in a quiet inner toolbar; a floating modal
          over the map just competes with the map. */}
      {workflowStage === "site" && !["grid_graph", "pulse", "neso098", "dc_twin", "dc_connection", "network", "circuit", "data", "forecast", "compare"].includes(activeViewMode) && (
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
          <ErrorBoundary name="SiteDashboardV2" fallback={null}>
            <SiteDashboardV2 onClose={() => setDashV2Closed(true)} />
          </ErrorBoundary>
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
      case "capabilities": setCapabilitiesMode(true); break;
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
      case "dc-score": {
        // Score the current site for DC feasibility
        const lat = pickedLocation?.lat;
        const lon = pickedLocation?.lon;
        if (!lat || !lon) { alert("Select a site first"); break; }
        window.dispatchEvent(new CustomEvent("princeps-chat", {
          detail: { text: `Score this location for data centre feasibility at ${lat.toFixed(4)}, ${lon.toFixed(4)}` },
        }));
        break;
      }
      case "dc-report": {
        const lat = pickedLocation?.lat;
        const lon = pickedLocation?.lon;
        if (!lat || !lon) { alert("Select a site first"); break; }
        window.dispatchEvent(new CustomEvent("princeps-chat", {
          detail: { text: `Generate a data centre feasibility report for ${lat.toFixed(4)}, ${lon.toFixed(4)}` },
        }));
        break;
      }
      case "pipeline": setActiveWorkspace("pipeline"); break;
      case "compare": setScenarioCompareOpen(true); break;
      case "demo": setDemoOpen(true); break;
      case "settings": setSettingsMode(true); break;
      case "intelligence": setIntelligenceOpen(true); break;
      default: break;
    }
  }, []);

  // ── Redesign gate — `?redesign=1` swaps the main content area for the
  // Gallatin-inspired project-first IA while keeping AppShell, all overlays,
  // CommandPalette etc. intact. All existing launchers are exposed via the
  // ActionsMenu inside the ProjectHeader.
  const _redesignActive = typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).get("redesign") === "1";

  // Intelligence routes (/intelligence/alerts|dockets|datasets) own their
  // own chat surface inside DocRail's right-hand panel. Suppress the global
  // floating ChatRail there so we don't end up with two stacked chats.
  // (main.jsx already mounts IntelligenceShell at /intelligence/*, so this
  // gate is mostly defensive — it kicks in if the catch-all ever wins.)
  const _isIntelligenceRoute = typeof window !== "undefined" &&
    window.location.pathname.startsWith("/intelligence");

  const _redesignActions = {
    gridTwin:        () => setGridTwinOpen(true),
    dcTwin:          () => setDcTwinOpen(true),
    bessFacility:    () => setBessFacilityOpen(true),
    bems:            () => setBemsOpen(true),
    digitalTwin:     () => setDigitalTwinOpen(true),
    terrainTwin:     () => setTerrainTwinOpen(true),
    asset3d:         () => setAsset3dOpen(true),
    assetInspector:  () => setAssetInspectorOpen(true),
    gridGraph:       () => setGridGraphOpen(true),
    nomExplorer:     () => setNomMode(true),
    scenarioCompare: () => setScenarioCompareOpen(true),
    dcLanding:       () => setDcLandingOpen(true),
    dcCompare:       () => setDcComparisonOpen(true),
    intelligence:    () => setIntelligenceOpen(true),
    hwConfig:        () => setHwConfigOpen(true),
    thermalModel:    () => setThermalModelOpen(true),
    dashboardBuilder: () => setDashboardBuilderOpen(true),
    assessmentWizard: () => setWizardOpen(true),
    pipeline:        () => setActiveWorkspace("pipeline"),
    pitch:           () => setPitchMode(true),
    capabilities:    () => setCapabilitiesMode(true),
    settings:        () => setSettingsMode(true),
    commandPalette:  () => setCmdPaletteOpen(true),
  };

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
      onCapabilities={() => setCapabilitiesMode(true)}
      onNomExplorer={() => setNomMode(true)}
      onSettings={() => setSettingsMode(true)}
      onCommandPalette={() => setCmdPaletteOpen(true)}
      onIntelligence={() => setIntelligenceOpen(true)}
    >
      <div className="app-shell-content">
        {_redesignActive ? (
          <Suspense fallback={<LazyFallback />}>
            <RedesignLayout
              actions={_redesignActions}
              mapSlot={mapContent}
            />
          </Suspense>
        ) : (
          <WorkspaceRouter mapContent={mapContent} />
        )}
      </div>

      {/* Chat consolidation 2026-04-19: AIOrb + CopilotWidget retired in favour
          of a single global ChatRail. The ChatRail listens for cmd-K and the
          legacy "princeps-chat" custom event so existing AssetBrowser
          suggestion-pills still expand the chat.

          Intelligence routes (/intelligence/alerts, /dockets, /datasets) host
          the chat inside the right-hand DocRail panel instead — having the
          floating bubble too would put two chat surfaces on screen at once.
          See DocRail.jsx, which mounts <ChatRail inline /> in its Chat tab. */}
      {!_isIntelligenceRoute && (
        <ErrorBoundary name="ChatRail" fallback={null}>
          <ChatRail parcelId={parcelId || null} projectId={null} />
        </ErrorBoundary>
      )}

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

      {/* 3D Digital Twin overlays — each in own Suspense+ErrorBoundary */}
      {gridTwinOpen && (
        <Suspense fallback={<LazyFallback />}>
          <ErrorBoundary name="GridTwin" fallback={<div style={{position:"fixed",inset:0,zIndex:9999,background:"#fff",display:"flex",alignItems:"center",justifyContent:"center",flexDirection:"column",gap:12}}><h2>Grid Twin failed to load</h2><button onClick={()=>setGridTwinOpen(false)} style={{padding:"8px 16px",cursor:"pointer"}}>Close</button></div>}>
            <GridTwin onClose={() => setGridTwinOpen(false)} />
          </ErrorBoundary>
        </Suspense>
      )}
      {bemsOpen && (
        <Suspense fallback={<LazyFallback />}>
          <ErrorBoundary name="BEMSTwin" fallback={<div style={{position:"fixed",inset:0,zIndex:9999,background:"#fff",display:"flex",alignItems:"center",justifyContent:"center",flexDirection:"column",gap:12}}><h2>BEMS Twin failed to load</h2><button onClick={()=>setBemsOpen(false)} style={{padding:"8px 16px",cursor:"pointer"}}>Close</button></div>}>
            <BEMSDigitalTwin onClose={() => setBemsOpen(false)} />
          </ErrorBoundary>
        </Suspense>
      )}
      {assetInspectorOpen && (
        <Suspense fallback={<LazyFallback />}>
          <AssetInspector onClose={() => setAssetInspectorOpen(false)} />
        </Suspense>
      )}
      {gridGraphOpen && (
        <Suspense fallback={<LazyFallback />}>
          <GridGraphView lat={pickedLocation?.lat} lon={pickedLocation?.lon} onClose={() => setGridGraphOpen(false)} />
        </Suspense>
      )}
      {bessFacilityOpen && (
        <Suspense fallback={<LazyFallback />}>
          <ErrorBoundary name="BESSTwin" fallback={<div style={{position:"fixed",inset:0,zIndex:9999,background:"#fff",display:"flex",alignItems:"center",justifyContent:"center",flexDirection:"column",gap:12}}><h2>BESS Twin failed to load</h2><button onClick={()=>setBessFacilityOpen(false)} style={{padding:"8px 16px",cursor:"pointer"}}>Close</button></div>}>
            <BESSFacilityTwin onClose={() => setBessFacilityOpen(false)} />
          </ErrorBoundary>
        </Suspense>
      )}
      {dcTwinOpen && (
        <Suspense fallback={<LazyFallback />}>
          <ErrorBoundary name="DCTwin" fallback={<div style={{position:"fixed",inset:0,zIndex:9999,background:"#fff",display:"flex",alignItems:"center",justifyContent:"center",flexDirection:"column",gap:12}}><h2>DC Twin failed to load</h2><button onClick={()=>setDcTwinOpen(false)} style={{padding:"8px 16px",cursor:"pointer"}}>Close</button></div>}>
            <DataCentreTwin onClose={() => setDcTwinOpen(false)} />
          </ErrorBoundary>
        </Suspense>
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
        <ErrorBoundary name="Asset3DModeller" fallback={<div style={{position:"fixed",inset:0,zIndex:9999,background:"#fff",display:"flex",alignItems:"center",justifyContent:"center",flexDirection:"column",gap:12}}><h2>3D Modeller failed to load</h2><button onClick={()=>setAsset3dOpen(false)} style={{padding:"8px 16px",cursor:"pointer"}}>Close</button></div>}>
          <Asset3DModeller
            onClose={() => setAsset3dOpen(false)}
            onPlaceOnMap={(spec) => {
              setAsset3dOpen(false);
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
        </ErrorBoundary>
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
      </Suspense>

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

      {/* Intelligence Panel — regulatory alerts & market data */}
      {intelligenceOpen && (
        <IntelligencePanel onClose={() => setIntelligenceOpen(false)} />
      )}

      {/* Backend-ready signal — keep the original handler firing on first
          render so legacy StartupOverlay logic still settles. */}
      {!backendReady && <span style={{ display: "none" }} ref={() => handleBackendReady()} />}

      {/* MISSION CONTROL TAKEOVER — when user is on Home → Dashboard view,
          render MissionControl as a full-screen overlay that hides the
          legacy AppShell chat-empty-state. This is the actual landing
          experience per 2026-04-19 redesign brief. */}
      {activeWorkspace === "home" && (activeViewMode === "dashboard" || !activeViewMode) && (
        <div style={{
          position: "fixed",
          top: 0, left: "var(--sidebar-width, 240px)", right: 0, bottom: 32,
          zIndex: 100,
          background: "var(--bg, #F2F3F5)",
          overflow: "auto",
        }}>
          <Suspense fallback={<div style={{padding:40,fontFamily:"DM Sans"}}>Loading Mission Control…</div>}>
            <MissionControl
              onSelectProject={(pid) => {
                // Flip redesign on + select project + switch viewMode so this
                // overlay unmounts and the project page renders underneath.
                const url = new URL(window.location.href);
                url.searchParams.set("redesign", "1");
                if (pid) url.searchParams.set("project", pid);
                window.history.replaceState({}, "", url);
                setActiveViewMode("map");
                window.dispatchEvent(new CustomEvent("princeps-redesign-select-project", { detail: { projectId: pid } }));
              }}
              onNewProject={() => {
                const url = new URL(window.location.href);
                url.searchParams.set("redesign", "1");
                window.history.replaceState({}, "", url);
                setActiveViewMode("map");
                window.dispatchEvent(new CustomEvent("princeps-redesign-new-project"));
              }}
              onPickWorkload={(workload) => {
                const url = new URL(window.location.href);
                url.searchParams.set("redesign", "1");
                window.history.replaceState({}, "", url);
                setActiveViewMode("map");
                window.dispatchEvent(new CustomEvent("princeps-redesign-new-project", { detail: { workload } }));
              }}
            />
          </Suspense>
        </div>
      )}

      {/* Inbox Bridge — global modal triggered by 'princeps-inbox-open'
          event from Mission Control or cmd-K command palette. */}
      <InboxBridgeModal />
    </AppShell>
  );
}

function InboxBridgeModal() {
  const [open, setOpen] = React.useState(false);
  React.useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener("princeps-inbox-open", onOpen);
    return () => window.removeEventListener("princeps-inbox-open", onOpen);
  }, []);
  if (!open) return null;
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 200,
      background: "rgba(15,19,24,0.45)",
      display: "flex", alignItems: "flex-start", justifyContent: "center",
      padding: "5vh 4vw", overflow: "auto",
    }} onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
      <div style={{
        background: "#fff", borderRadius: 12, maxWidth: 900, width: "100%",
        boxShadow: "0 20px 60px rgba(0,0,0,0.25)", position: "relative",
      }}>
        <button onClick={() => setOpen(false)} style={{
          position: "absolute", top: 12, right: 12, background: "transparent",
          border: "none", fontSize: 22, color: "#6B7280", cursor: "pointer", lineHeight: 1,
        }} aria-label="Close">×</button>
        <InboxBridge />
      </div>
    </div>
  );
}
