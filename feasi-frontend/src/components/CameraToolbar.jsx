import React, { useState, useCallback } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

const VIEW_PRESETS = [
  { label: "Overview", icon: "🌐", zoom: 7, pitch: 30, bearing: 0, duration: 2000 },
  { label: "Inspect", icon: "🔍", zoom: 15, pitch: 70, bearing: -20, duration: 2500 },
  { label: "Terrain", icon: "⛰", zoom: 11, pitch: 55, bearing: 30, duration: 2000 },
];

export default function CameraToolbar({ map, pickedLocation }) {
  const { parcelId, setTwinData, setDigitalTwinOpen } = useSite();
  const [is3D, setIs3D] = useState(true);
  const [exaggeration, setExaggeration] = useState(2);
  const [twinLoading, setTwinLoading] = useState(false);

  const flyToPreset = useCallback((preset) => {
    if (!map) return;
    const center = preset.label === "Inspect" && pickedLocation
      ? [pickedLocation.lon, pickedLocation.lat]
      : map.getCenter().toArray();
    map.flyTo({
      center,
      zoom: preset.zoom,
      pitch: preset.pitch,
      bearing: preset.bearing,
      duration: preset.duration,
      essential: true,
    });
    if (preset.pitch > 0) setIs3D(true);
  }, [map, pickedLocation]);

  const toggle3D = useCallback(async () => {
    if (!map) return;
    // If parcel is selected, launch 3D Digital Twin with satellite imagery
    if (parcelId) {
      setTwinLoading(true);
      try {
        const data = await api.vision.getTwinData(parcelId, 500);
        if (data) {
          setTwinData(data);
          setDigitalTwinOpen(true);
        }
      } catch (e) {
        console.error("3D Twin error:", e);
      } finally {
        setTwinLoading(false);
      }
      return;
    }
    // Fallback: just tilt the map camera
    const next = !is3D;
    setIs3D(next);
    map.easeTo({
      pitch: next ? 60 : 0,
      bearing: next ? -15 : 0,
      duration: 1500,
    });
  }, [map, is3D, parcelId, setTwinData, setDigitalTwinOpen]);

  const handleExaggeration = useCallback((e) => {
    const val = parseFloat(e.target.value);
    setExaggeration(val);
    if (!map) return;
    if (val === 0) {
      map.setTerrain(null);
    } else {
      map.setTerrain({ source: "terrainSource", exaggeration: val });
    }
  }, [map]);

  return (
    <div className="camera-toolbar">
      <div className="camera-toolbar-section">
        {VIEW_PRESETS.map((p) => (
          <button
            key={p.label}
            className="camera-btn"
            onClick={() => flyToPreset(p)}
            title={p.label}
          >
            <span className="camera-btn-icon">{p.icon}</span>
            <span className="camera-btn-label">{p.label}</span>
          </button>
        ))}
      </div>
      <div className="camera-toolbar-divider" />
      <button
        className={`camera-btn camera-btn-toggle ${is3D || parcelId ? "active" : ""}`}
        onClick={toggle3D}
        disabled={twinLoading}
        title={parcelId ? "Open 3D Digital Twin" : is3D ? "Switch to 2D" : "Switch to 3D"}
      >
        {twinLoading ? "..." : parcelId ? "3D" : is3D ? "3D" : "2D"}
      </button>
      <div className="camera-toolbar-divider" />
      <div className="camera-exaggeration">
        <label className="camera-exag-label">
          Terrain <span className="camera-exag-value">{exaggeration.toFixed(1)}x</span>
        </label>
        <input
          type="range"
          min="0"
          max="3"
          step="0.1"
          value={exaggeration}
          onChange={handleExaggeration}
          className="camera-exag-slider"
        />
      </div>
    </div>
  );
}
