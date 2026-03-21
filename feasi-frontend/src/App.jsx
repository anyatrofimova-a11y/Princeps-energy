import React, { useState, useEffect, useRef, useCallback, lazy, Suspense } from "react";
import mapboxgl from "mapbox-gl";
import { useSite } from "./SiteContext";
import api from "./services/api";

// ── Core layout (always loaded) ──
import AppShell from "./components/shell/AppShell";
import WorkspaceRouter from "./components/workspace/WorkspaceRouter";
import MapView from "./components/MapView";
import CopilotWidget from "./components/CopilotWidget";
import ErrorBoundary from "./components/ErrorBoundary";
import LayerRail from "./components/LayerRail";
import MapLegend from "./components/MapLegend";
import MapAssetLayer from "./components/MapAssetLayer";
import DCMapOverlay from "./components/DCMapOverlay";
import Asset3DOverlay from "./components/Asset3DOverlay";
import CameraToolbar from "./components/CameraToolbar";
import SitePicker from "./components/SitePicker";

// ── Lazy-loaded overlays (split into separate chunks) ──
const DigitalTwin = lazy(() => import("./components/DigitalTwin"));
const GridTwin = lazy(() => import("./components/GridTwin"));
const BEMSDigitalTwin = lazy(() => import("./components/BEMSDigitalTwin"));
const BESSFacilityTwin = lazy(() => import("./components/BESSFacilityTwin"));
const DataCentreTwin = lazy(() => import("./components/DataCentreTwin"));
const AssetInspector = lazy(() => import("./components/AssetInspector"));
const GridGraphView = lazy(() => import("./components/GridGraphView"));
const HardwareConfigurator = lazy(() => import("./components/HardwareConfigurator"));
const ThermalModelPanel = lazy(() => import("./components/ThermalModelPanel"));
const DCLandingPage = lazy(() => import("./components/DCLandingPage"));
const DCComparisonDashboard = lazy(() => import("./components/DCComparisonDashboard"));
const NOMExplorer = lazy(() => import("./components/NOMExplorer"));
const SettingsPage = lazy(() => import("./components/SettingsPage"));
const PitchPage = lazy(() => import("./components/PitchPage"));
const ProjectPipeline = lazy(() => import("./components/ProjectPipeline"));
const SiteDashboard = lazy(() => import("./components/SiteDashboard"));
const CommandPalette = lazy(() => import("./components/shell/CommandPalette"));
const DrawingToolbar = lazy(() => import("./components/DrawingToolbar"));
const ComponentPalette = lazy(() => import("./components/ComponentPalette"));
const AssetDock = lazy(() => import("./components/AssetDock"));
const EnergyFlowPanel = lazy(() => import("./components/EnergyFlowPanel"));

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
    digitalTwinOpen, setDigitalTwinOpen, twinData, realSiteContext,
    workflowStage,
    gridTwinOpen, setGridTwinOpen,
    bemsOpen, setBemsOpen,
    assetInspectorOpen, setAssetInspectorOpen,
    gridGraphOpen, setGridGraphOpen,
    bessFacilityOpen, setBessFacilityOpen,
    hwConfigOpen, setHwConfigOpen,
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

  const [mapInstance, setMapInstance] = useState(null);
  const [pipelineOpen, setPipelineOpen] = useState(false);

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
    api.inventory.catalogue().then(d => { if (d) setSolarCatalogue(d); });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch demand forecast + Agile pricing on mount
  useEffect(() => {
    api.grid.demandForecast().then(d => { if (d) setDemandForecast(d); });
    api.grid.agilePricing("C").then(d => { if (d && !d.error) setAgilePricing(d); });
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
    setDrawState(s => ({ ...s, mode, clickSequence: [], mouseCoord: null, selectedIndex: -1 }));
  }, []);

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
      return state;
    });
  }, []);

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

      <MapAssetLayer map={mapInstance} />
      <DCMapOverlay mapInstance={mapInstance} dcAssets={placedAssets.filter(a => a.assetType === "data_centre")} />
      <Asset3DOverlay mapInstance={mapInstance} assets={placedAssets} validations={assetValidations} />

      <LayerRail chatLayers={chatLayers} onRemoveChatLayer={removeChatLayer} />
      <MapLegend chatLayers={chatLayers} />

      <CameraToolbar map={mapInstance} pickedLocation={pickedLocation} />

      <DrawingToolbar
        drawMode={drawState.mode}
        onModeChange={handleDrawModeChange}
        featureCount={drawState.features.features.length}
        selectedIndex={drawState.selectedIndex}
        onDeleteFeature={handleDeleteDrawFeature}
        onClearAll={handleClearDrawFeatures}
        onExportGeoJSON={handleExportGeoJSON}
        measurement={measurement}
      />

      {/* Site picker — SITE stage floating search */}
      {workflowStage === "site" && (
        <SitePicker map={mapInstance} onPick={handleMapPick} />
      )}

      {pickMode && workflowStage !== "site" && (
        <div className="pick-banner">Click anywhere on the map to select a site</div>
      )}

      {layoutMode && solarCatalogue && (
        <ComponentPalette catalogue={solarCatalogue} />
      )}

      {/* Asset Dock — drag components onto map */}
      <AssetDock
        placedAssets={placedAssets}
        mapInstance={mapInstance}
        onAssetPlaced={addPlacedAsset}
      />

      {/* Energy Flow Panel — right side Sankey */}
      {energyFlowOpen && (
        <EnergyFlowPanel
          placedAssets={placedAssets}
          solarYield={solarYield}
          gridContext={gridContext}
          onClose={() => setEnergyFlowOpen(false)}
        />
      )}

      {/* Site dashboard overlay */}
      {dashboardOpen && (
        <SiteDashboard onClose={() => setDashboardOpen(false)} />
      )}

    </div>
  );

  const handleCmdAction = useCallback((action) => {
    switch (action) {
      case "twin": setGridTwinOpen(true); break;
      case "bems": setBemsOpen(true); break;
      case "inspect": setAssetInspectorOpen(true); break;
      case "graph": setGridGraphOpen(true); break;
      case "pitch": setPitchMode(true); break;
      case "nom": setNomMode(true); break;
      case "bess-facility": setBessFacilityOpen(true); break;
      case "hardware": setHwConfigOpen(true); break;
      case "thermal": setThermalModelOpen(true); break;
      case "dc-twin": setDcTwinOpen(true); break;
      case "dc-landing": setDcLandingOpen(true); break;
      case "dc-compare": setDcComparisonOpen(true); break;
      case "pipeline": setPipelineOpen(true); break;
      case "settings": setSettingsMode(true); break;
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
      onThermal={() => setThermalModelOpen(true)}
      onDcTwin={() => setDcTwinOpen(true)}
      onDcLanding={() => setDcLandingOpen(true)}
      onDcCompare={() => setDcComparisonOpen(true)}
      onPipeline={() => setPipelineOpen(true)}
      onPitch={() => setPitchMode(true)}
      onNomExplorer={() => setNomMode(true)}
      onSettings={() => setSettingsMode(true)}
      onCommandPalette={() => setCmdPaletteOpen(true)}
    >
      <div className="app-shell-content">
        <WorkspaceRouter mapContent={mapContent} />
      </div>

      <CopilotWidget onMapLayer={handleChatMapLayer} onZoomTo={handleChatZoomTo} onAction={handleCmdAction} />

      {/* Command Palette */}
      <CommandPalette
        open={cmdPaletteOpen}
        onClose={() => setCmdPaletteOpen(false)}
        onAction={handleCmdAction}
      />

      {/* Project Pipeline — Kanban board */}
      {pipelineOpen && (
        <ProjectPipeline
          onClose={() => setPipelineOpen(false)}
          onSelectProject={(p) => {
            if (p.lat && p.lon) setPickedLocation({ lat: p.lat, lon: p.lon });
          }}
        />
      )}

      {/* 3D Site Digital Twin overlay — works with or without data */}
      {digitalTwinOpen && (
        <DigitalTwin data={twinData} realContext={realSiteContext} onClose={() => setDigitalTwinOpen(false)} />
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

      {/* Thermal Model panel */}
      {thermalModelOpen && (
        <ThermalModelPanel onClose={() => setThermalModelOpen(false)} />
      )}
    </AppShell>
  );
}
