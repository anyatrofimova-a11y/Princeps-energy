import React, { useState, useEffect, useRef, useCallback } from "react";
import { useSite } from "./SiteContext";
import api from "./services/api";
import MapView from "./components/MapView";
import ComponentPalette from "./components/ComponentPalette";
import Dashboard from "./components/Dashboard";
import ChatPanel from "./components/ChatPanel";
import DrawingToolbar from "./components/DrawingToolbar";
import ErrorBoundary from "./components/ErrorBoundary";
import NOMExplorer from "./components/NOMExplorer";
import { AITopBanner, AIBottomBar } from "./components/AIIntelStrip";
import {
  MODES, createDrawState, handleClick as drawHandleClick, handleDoubleClick as drawHandleDoubleClick,
  moveVertex, insertVertex, deleteFeature, getMeasurements, findSnapTarget,
} from "./lib/draw-modes";

export default function App() {
  const {
    // Identity
    parcelId, setParcelId,
    pickedLocation, setPickedLocation,
    pickMode, setPickMode,
    // Parameters
    samCapacity, setSamCapacity,
    samDay, setSamDay,
    // Loading
    loading,
    // Layers
    layers, toggleLayer, slopeOpacity, setSlopeOpacity,
    // EPC fields
    epcZonesField, setEpcZonesField,
    epcDomField, setEpcDomField,
    epcNondomField, setEpcNondomField,
    postcodesField, setPostcodesField,
    // Layout
    layoutMode, setLayoutMode,
    componentLayout, setComponentLayout,
    setCustomBom, bomAbortRef,
    solarCatalogue, setSolarCatalogue,
    // Actions
    loadSite, runDeferral,
    setDemandForecast, setAgilePricing,
    // Chat layers
    chatLayers, setChatLayers,
    // UI
    setActiveTab, setPanelOpen,
    setSelectedLsoa,
  } = useSite();

  // Handle map layers from chat
  const handleChatMapLayer = useCallback((layer) => {
    setChatLayers(prev => [...prev, layer]);
  }, [setChatLayers]);

  const removeChatLayer = useCallback((layerId) => {
    setChatLayers(prev => prev.filter(l => l.id !== layerId));
  }, [setChatLayers]);

  // NOM Explorer mode
  const [nomMode, setNomMode] = useState(false);

  const handleNomAnalyse = useCallback((sub) => {
    setNomMode(false);
    // Switch to the substation's location on the main map
    if (sub && sub.lat && sub.lon) {
      setPickedLocation({ lat: sub.lat, lon: sub.lon });
    }
  }, [setPickedLocation]);

  // Fetch solar catalogue once on mount
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

  // Handle map click in pick mode -> create parcel -> run analysis
  const handleMapPick = async ({ lat, lon }) => {
    setPickMode(false);
    setPickedLocation({ lat, lon });
    try {
      const data = await api.site.fromLocation(lat, lon);
      if (data?.parcel_id) {
        setParcelId(data.parcel_id);
        setPickedLocation({ lat: data.lat, lon: data.lon });
        await loadSite(data.parcel_id, samCapacity, samDay);
        runDeferral(5, 4);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleAnalyse = () => {
    loadSite(parcelId, samCapacity, samDay);
    runDeferral(5, 4);
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
    const handler = (e) => {
      if (e.key === "Escape") handleDrawModeChange(MODES.VIEW);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleDrawModeChange]);

  const measurement = getMeasurements(drawState);

  if (nomMode) {
    return (
      <NOMExplorer
        onExit={() => setNomMode(false)}
        onAnalyseSubstation={handleNomAnalyse}
      />
    );
  }

  return (
    <div className={`app-fullscreen${layers.flowFocus ? " flow-focus" : ""}`}>
      {/* Map fills viewport */}
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
        />
      </ErrorBoundary>

      {/* AI Intelligence Banner (top) */}
      <AITopBanner />

      {/* Top bar */}
      <div className="topbar">
        <div className="topbar-brand">Feasibly</div>
        <button
          className={`btn-pick ${pickMode ? "active" : ""}`}
          onClick={() => setPickMode(p => !p)}
          title="Click map to pick a site location"
        >
          {pickMode ? "Cancel" : "Pick Site"}
        </button>
        {pickedLocation && (
          <span className="topbar-coords">
            {pickedLocation.lat.toFixed(5)}, {pickedLocation.lon.toFixed(5)}
          </span>
        )}
        {parcelId && (
          <span className="topbar-parcel" title={parcelId}>
            {parcelId.slice(0, 8)}...
          </span>
        )}
        <span className="topbar-param">
          <input type="number" value={samCapacity}
            onChange={e => setSamCapacity(Number(e.target.value))}
            style={{ width: 55 }} min={1} /> kW
        </span>
        <span className="topbar-param">
          Day <input type="number" value={samDay}
            onChange={e => setSamDay(Number(e.target.value))}
            style={{ width: 45 }} min={1} max={365} />
        </span>
        <button className="btn-primary" onClick={handleAnalyse} disabled={loading || !parcelId}>
          {loading ? "..." : "Analyse"}
        </button>
        <button className="btn-nom" onClick={() => setNomMode(true)}>
          NOM Explorer
        </button>
        <button
          className={`btn-layout ${layoutMode ? "active" : ""}`}
          onClick={() => {
            setLayoutMode(p => !p);
            if (!layoutMode) { setActiveTab("terrain"); setPanelOpen(true); }
          }}
          disabled={!parcelId}
        >
          {layoutMode ? "Exit Layout" : "Layout"}
        </button>
      </div>
      {pickMode && (
        <div className="pick-banner">Click anywhere on the map to select a site location</div>
      )}

      {/* Layer controls (left) */}
      <div className="layer-panel">
        <div className="layer-title">Layers</div>
        {[
          { id: "hillshade", label: "Hillshade", color: "#8d6e63" },
          { id: "slope", label: "Slope", color: "#2196f3" },
          { id: "carbon", label: "Carbon (PBCC)", color: "#e91e63" },
          { id: "la", label: "Local Authority", color: "#ff9800" },
          { id: "transport", label: "Transport", color: "#00bcd4" },
          { id: "contours", label: "Contours", color: "#00ff88" },
          { id: "environment", label: "Energy Assets", color: "#ff9800" },
        ].map(l => (
          <label key={l.id} className="layer-item">
            <input type="checkbox" checked={layers[l.id]} onChange={() => toggleLayer(l.id)} />
            <span className="layer-dot" style={{ background: l.color }} />
            {l.label}
          </label>
        ))}
        {layers.slope && (
          <div style={{ marginTop: 6, paddingLeft: 4 }}>
            <input type="range" min="0" max="1" step="0.05" value={slopeOpacity}
              onChange={e => setSlopeOpacity(parseFloat(e.target.value))}
              style={{ width: "100%" }} />
          </div>
        )}

        <div className="layer-divider" />
        <div className="layer-title">Grid Network</div>
        <label className="layer-item">
          <input type="checkbox" checked={layers.gridFlow} onChange={() => toggleLayer("gridFlow")} />
          <span className="layer-dot" style={{ background: "#00e676" }} />
          Grid Flow
        </label>
        <label className="layer-item">
          <input type="checkbox" checked={layers.agilePricing} onChange={() => toggleLayer("agilePricing")} />
          <span className="layer-dot" style={{ background: "#ff9800" }} />
          Agile Pricing
        </label>
        <label className="layer-item">
          <input type="checkbox" checked={layers.demandOverlay} onChange={() => toggleLayer("demandOverlay")} />
          <span className="layer-dot" style={{ background: "#e040fb" }} />
          Smart Meter Demand
        </label>
        <label className="layer-item">
          <input type="checkbox" checked={layers.flowFocus} onChange={() => toggleLayer("flowFocus")} />
          <span className="layer-dot" style={{ background: "#00ffcc" }} />
          Flow Focus
        </label>

        <div className="layer-divider" />
        <div className="layer-title">EPC / Retrofit</div>
        <label className="layer-item">
          <input type="checkbox" checked={layers.epcZones} onChange={() => toggleLayer("epcZones")} />
          <span className="layer-dot" style={{ background: "#1a9850" }} />
          Neighbourhoods
        </label>
        {layers.epcZones && (
          <select className="layer-select" value={epcZonesField} onChange={e => setEpcZonesField(e.target.value)}>
            <option value="epc_score_avg">Avg EPC Score</option>
            <option value="floor_area_avg">Avg Floor Area</option>
            <option value="modal_age">Building Age</option>
            <option value="modal_wall">Wall Rating</option>
            <option value="modal_roof">Roof Rating</option>
            <option value="modal_heat">Heating Rating</option>
            <option value="modal_window">Window Rating</option>
            <option value="modal_mainheat">Heating Type</option>
            <option value="modal_mainfuel">Fuel Type</option>
            <option value="modal_floord">Floor Type</option>
            <option value="modal_type">Building Type</option>
            <option value="percent_EPC">% with EPC</option>
          </select>
        )}

        <label className="layer-item">
          <input type="checkbox" checked={layers.epcDom} onChange={() => toggleLayer("epcDom")} />
          <span className="layer-dot" style={{ background: "#0e7e58" }} />
          Domestic EPC
        </label>
        {layers.epcDom && (
          <select className="layer-select" value={epcDomField} onChange={e => setEpcDomField(e.target.value)}>
            <option value="cur_rate">EPC Rating</option>
            <option value="b_type">Building Type</option>
            <option value="p_type">Property Type</option>
            <option value="age">Building Age</option>
            <option value="year">Last Assessed</option>
            <option value="area">Floor Area</option>
            <option value="floor_ee">Floor Rating</option>
            <option value="water_ee">Hot Water Rating</option>
            <option value="wind_ee">Window Rating</option>
            <option value="wall_ee">Wall Rating</option>
            <option value="roof_ee">Roof Rating</option>
            <option value="heat_ee">Heating Rating</option>
            <option value="con_ee">Controls Rating</option>
            <option value="light_ee">Lighting Rating</option>
            <option value="sol_wat">Solar Thermal</option>
          </select>
        )}

        <label className="layer-item">
          <input type="checkbox" checked={layers.epcNondom} onChange={() => toggleLayer("epcNondom")} />
          <span className="layer-dot" style={{ background: "#f6cc15" }} />
          Non-Domestic EPC
        </label>
        {layers.epcNondom && (
          <select className="layer-select" value={epcNondomField} onChange={e => setEpcNondomField(e.target.value)}>
            <option value="band">Rating Band</option>
            <option value="transaction">Transaction Type</option>
            <option value="area">Floor Area</option>
            <option value="year">Last Assessed</option>
          </select>
        )}

        <label className="layer-item">
          <input type="checkbox" checked={layers.postcodes} onChange={() => toggleLayer("postcodes")} />
          <span className="layer-dot" style={{ background: "#4575b4" }} />
          Postcodes Energy
        </label>
        {layers.postcodes && (
          <select className="layer-select" value={postcodesField} onChange={e => setPostcodesField(e.target.value)}>
            <option value="combined">Combined Emissions</option>
            <option value="gas">Gas Emissions</option>
            <option value="elec">Electricity Emissions</option>
          </select>
        )}

        <div className="layer-divider" />
        <div className="layer-title">Remote Sensing</div>
        {[
          { id: "ndvi", label: "NDVI (MODIS)", color: "#2e7d32" },
          { id: "satellite", label: "Sentinel-2", color: "#1565c0" },
          { id: "aerial", label: "Aerial (ESRI)", color: "#6a1b9a" },
          { id: "lidarDtm", label: "LIDAR DTM", color: "#ef6c00" },
          { id: "lidarDsm", label: "LIDAR DSM", color: "#d84315" },
          { id: "landsat", label: "Landsat 30m", color: "#1b5e20" },
          { id: "viirs", label: "VIIRS Daily", color: "#0d47a1" },
        ].map(l => (
          <label key={l.id} className="layer-item">
            <input type="checkbox" checked={layers[l.id]} onChange={() => toggleLayer(l.id)} />
            <span className="layer-dot" style={{ background: l.color }} />
            {l.label}
          </label>
        ))}

        {/* Chat Layers (from AI chat) */}
        {chatLayers.length > 0 && <>
          <div className="layer-divider" />
          <div className="layer-title">Chat Layers</div>
          {chatLayers.map(l => (
            <label key={l.id} className="layer-item">
              <span className="layer-dot" style={{ background: l.color || "#00e5ff" }} />
              {l.name}
              <button className="chat-layer-remove" onClick={() => removeChatLayer(l.id)} title="Remove">&times;</button>
            </label>
          ))}
        </>}
      </div>

      {/* Drawing toolbar (nebula.gl-style) */}
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

      {/* Chat Panel */}
      <ChatPanel onMapLayer={handleChatMapLayer} />

      {/* Component Palette (layout mode) */}
      {layoutMode && solarCatalogue && (
        <ComponentPalette catalogue={solarCatalogue} />
      )}

      {/* Right panel — Dashboard with cards */}
      <Dashboard />

      {/* AI Intelligence Status Bar (bottom) */}
      <AIBottomBar />
    </div>
  );
}
