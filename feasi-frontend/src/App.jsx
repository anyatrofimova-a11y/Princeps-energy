import React, { useState, useEffect, useRef, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import { useSite } from "./SiteContext";
// WorkspaceContext is used by child components (AssetBrowser, DetailPanel, etc.)
import api from "./services/api";
import MapView from "./components/MapView";
import ComponentPalette from "./components/ComponentPalette";
import AppShell from "./components/shell/AppShell";
import WorkspaceRouter from "./components/workspace/WorkspaceRouter";
import LayerRail from "./components/LayerRail";
import CommandBar from "./components/CommandBar";
import DrawingToolbar from "./components/DrawingToolbar";
import CameraToolbar from "./components/CameraToolbar";
import ErrorBoundary from "./components/ErrorBoundary";
import NOMExplorer from "./components/NOMExplorer";
import SettingsPage from "./components/SettingsPage";
import PitchPage from "./components/PitchPage";
import SiteDashboard from "./components/SiteDashboard";
import SitePicker from "./components/SitePicker";
import DigitalTwin from "./components/DigitalTwin";
import GridTwin from "./components/GridTwin";
import MapLegend from "./components/MapLegend";
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
    digitalTwinOpen, setDigitalTwinOpen, twinData,
    workflowStage,
    gridTwinOpen, setGridTwinOpen,
    activeIntent,
  } = useSite();

  const [mapInstance, setMapInstance] = useState(null);

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
    <div className="map-area-inner">
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

      {/* Site dashboard overlay */}
      {dashboardOpen && (
        <SiteDashboard onClose={() => setDashboardOpen(false)} />
      )}
    </div>
  );

  return (
    <AppShell
      onGridTwin={() => setGridTwinOpen(true)}
      onPitch={() => setPitchMode(true)}
      onNomExplorer={() => setNomMode(true)}
      onSettings={() => setSettingsMode(true)}
    >
      <div className="app-shell-content">
        <WorkspaceRouter mapContent={mapContent} />
      </div>

      <CommandBar onMapLayer={handleChatMapLayer} onZoomTo={handleChatZoomTo} />

      {/* 3D Site Digital Twin overlay */}
      {digitalTwinOpen && twinData && (
        <DigitalTwin data={twinData} onClose={() => setDigitalTwinOpen(false)} />
      )}

      {/* 3D Grid Digital Twin overlay */}
      {gridTwinOpen && (
        <GridTwin onClose={() => setGridTwinOpen(false)} />
      )}
    </AppShell>
  );
}
