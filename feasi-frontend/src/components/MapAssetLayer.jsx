/**
 * MapAssetLayer — deck.gl 3D asset placement on Mapbox map.
 *
 * Replaces the standalone THREE.js LayoutEditor with real-coordinate
 * asset placement directly on the map. Components are rendered as
 * deck.gl ColumnLayer (3D extruded shapes) at real lat/lon positions.
 *
 * Drop targets: user drags from ComponentPalette → drops on map.
 * Assets snap to the dropped lat/lon and render as 3D columns.
 */
import React, { useCallback, useRef, useState, useEffect } from "react";
import { useSite } from "../SiteContext";

// Asset type visual config
const ASSET_CONFIG = {
  PNL: { color: [30, 136, 229, 200], height: 3,   radius: 8,   label: "Solar Panel" },
  INV: { color: [255, 152, 0, 200],  height: 5,   radius: 4,   label: "Inverter" },
  BAT: { color: [76, 175, 80, 200],  height: 8,   radius: 12,  label: "Battery" },
  TRF: { color: [158, 158, 158, 200],height: 10,  radius: 6,   label: "Transformer" },
  MON: { color: [233, 30, 99, 200],  height: 12,  radius: 2,   label: "Monitoring" },
  CBL: { color: [96, 125, 139, 200], height: 1,   radius: 1,   label: "Cable" },
  MNT: { color: [121, 85, 72, 200],  height: 2,   radius: 3,   label: "Mounting" },
  BOS: { color: [0, 188, 212, 200],  height: 4,   radius: 5,   label: "BOS" },
};

/**
 * MapAssetOverlay — rendered inside MapView as an HTML overlay.
 * Handles drop events, renders asset markers as positioned divs over the map.
 * For full deck.gl ColumnLayer, this would be integrated into the MapboxOverlay.
 */
export default function MapAssetLayer({ map }) {
  const {
    layoutMode, componentLayout, setComponentLayout, pickedLocation,
  } = useSite();
  const [selectedId, setSelectedId] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const overlayRef = useRef(null);

  // Handle drop from ComponentPalette or AssetDock
  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    if (!map) return;

    let compData;
    try {
      // Try new AssetDock format first, then legacy ComponentPalette
      const raw = e.dataTransfer.getData("application/princeps-asset") || e.dataTransfer.getData("application/json");
      if (!raw) return;
      compData = JSON.parse(raw);
    } catch { return; }

    // Convert screen coords to map lat/lon
    const rect = overlayRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const lngLat = map.unproject([x, y]);

    const newAsset = {
      id: `${compData.componentId}-${Date.now()}`,
      componentId: compData.componentId,
      name: compData.name || compData.componentId,
      lat: lngLat.lat,
      lon: lngLat.lng,
      // Keep legacy x/y for BOM compatibility
      x: Math.round((lngLat.lng - (pickedLocation?.lon || 0)) * 111320),
      y: Math.round((lngLat.lat - (pickedLocation?.lat || 0)) * 110540),
      z: 0,
      rotation: 0,
      placed_at: new Date().toISOString(),
    };

    setComponentLayout(prev => [...prev, newAsset]);
  }, [map, layoutMode, pickedLocation, setComponentLayout]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => setDragOver(false), []);

  const handleRemoveAsset = useCallback((id) => {
    setComponentLayout(prev => prev.filter(a => a.id !== id));
    setSelectedId(null);
  }, [setComponentLayout]);

  // Project lat/lon to screen coords
  const projectToScreen = useCallback((lat, lon) => {
    if (!map) return null;
    const point = map.project([lon, lat]);
    return { x: point.x, y: point.y };
  }, [map]);

  // Force re-render on map move
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!map) return;
    const handler = () => setTick(t => t + 1);
    map.on("move", handler);
    return () => map.off("move", handler);
  }, [map]);

  // Show overlay when in layout mode OR when assets have been placed via AssetDock
  const { placedAssets } = useSite();
  if (!layoutMode && componentLayout.length === 0 && placedAssets.length === 0) return null;

  return (
    <div
      ref={overlayRef}
      className={`map-asset-overlay${dragOver ? " drag-over" : ""}`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      {/* Render placed assets as positioned markers */}
      {componentLayout.map(asset => {
        if (!asset.lat || !asset.lon) return null;
        const pos = projectToScreen(asset.lat, asset.lon);
        if (!pos) return null;

        const prefix = asset.componentId.split("-")[0];
        const config = ASSET_CONFIG[prefix] || ASSET_CONFIG.BOS;
        const isSelected = selectedId === asset.id;

        return (
          <div
            key={asset.id}
            className={`map-asset-marker${isSelected ? " selected" : ""}`}
            style={{
              left: pos.x,
              top: pos.y,
              "--asset-color": `rgb(${config.color.slice(0, 3).join(",")})`,
              "--asset-size": `${config.radius * 2 + 8}px`,
            }}
            onClick={(e) => { e.stopPropagation(); setSelectedId(isSelected ? null : asset.id); }}
          >
            <div className="map-asset-dot" style={{
              width: config.radius * 2,
              height: config.radius * 2,
              background: `rgba(${config.color.join(",")})`,
            }} />
            <span className="map-asset-label">{config.label}</span>
            {isSelected && (
              <div className="map-asset-tooltip">
                <div className="map-asset-tooltip-name">{asset.name}</div>
                <div className="map-asset-tooltip-coords">
                  {asset.lat.toFixed(5)}, {asset.lon.toFixed(5)}
                </div>
                <button className="map-asset-remove" onClick={() => handleRemoveAsset(asset.id)}>
                  Remove
                </button>
              </div>
            )}
          </div>
        );
      })}

      {/* Drop zone indicator */}
      {dragOver && (
        <div className="map-asset-drop-indicator">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M5 12h14" />
          </svg>
          Drop component here
        </div>
      )}

      {/* Asset count strip */}
      {componentLayout.length > 0 && (
        <div className="map-asset-count">
          {componentLayout.length} component{componentLayout.length !== 1 ? "s" : ""} placed
        </div>
      )}
    </div>
  );
}
