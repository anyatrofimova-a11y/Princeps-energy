/**
 * GridCameraChoreography — AI-driven cinematic flythrough for GridTwin.
 *
 * Detects anomalies (high utilisation, congested lines, constraint hotspots)
 * and smoothly orbits/zooms to each one with eased camera transitions.
 * Auto-narration labels describe what the camera is looking at.
 *
 * Usage:
 *   <GridCameraChoreography
 *     map={mapRef.current}
 *     gridState={gridState}
 *     active={choreographyActive}
 *     onStop={() => setChoreographyActive(false)}
 *   />
 */
import React, { useState, useEffect, useRef, useCallback } from "react";

// Easing functions
const easeInOutCubic = (t) => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

// Detect anomalies worth zooming to
function detectAnomalies(gridState) {
  if (!gridState) return [];
  const anomalies = [];

  // High-utilisation substations
  for (const s of gridState.substations || []) {
    if (s.utilisation >= 0.85) {
      anomalies.push({
        type: "substation",
        priority: s.utilisation >= 0.95 ? 3 : 2,
        label: `${s.name} — ${(s.utilisation * 100).toFixed(0)}% utilisation`,
        sublabel: `${Math.round(s.demand_mw)} MW demand, ${Math.round(s.headroom_mw)} MW headroom`,
        center: [s.lon, s.lat],
        zoom: 10,
        pitch: 60,
        bearing: -30,
        duration: 4000,
        color: s.utilisation >= 0.95 ? "#f5222d" : "#fa8c16",
      });
    }
  }

  // Congested transmission lines
  for (const l of gridState.lines || []) {
    if (l.congested || l.loading_pct > 75) {
      const midLon = (l.from_coords[0] + l.to_coords[0]) / 2;
      const midLat = (l.from_coords[1] + l.to_coords[1]) / 2;
      anomalies.push({
        type: "line",
        priority: l.loading_pct > 90 ? 3 : 2,
        label: `${l.from} → ${l.to} — ${l.loading_pct.toFixed(0)}% loaded`,
        sublabel: `${Math.abs(l.flow_mw).toFixed(0)} MW flow on ${l.voltage_kv} kV`,
        center: [midLon, midLat],
        zoom: 8.5,
        pitch: 50,
        bearing: Math.atan2(l.to_coords[0] - l.from_coords[0], l.to_coords[1] - l.from_coords[1]) * 180 / Math.PI,
        duration: 3500,
        color: l.loading_pct > 90 ? "#f5222d" : "#fa8c16",
      });
    }
  }

  // System overview (always include as first and last stop)
  anomalies.unshift({
    type: "overview",
    priority: 1,
    label: "GB Transmission Grid — Live Overview",
    sublabel: `${(gridState.system?.total_demand_mw / 1000).toFixed(1)} GW demand · ${(gridState.system?.system_utilisation * 100).toFixed(0)}% utilisation`,
    center: [-1.5, 53.5],
    zoom: 5.8,
    pitch: 55,
    bearing: -10,
    duration: 5000,
    color: "#D4A018",
  });

  // Sort by priority (highest first), then add final overview
  anomalies.sort((a, b) => b.priority - a.priority);

  // Cap at 8 stops to keep flythrough under ~40s
  return anomalies.slice(0, 8);
}

export default function GridCameraChoreography({ map, gridState, active, onStop }) {
  const [currentIdx, setCurrentIdx] = useState(0);
  const [anomalies, setAnomalies] = useState([]);
  const [narration, setNarration] = useState(null);
  const timerRef = useRef(null);

  // Detect anomalies when state changes
  useEffect(() => {
    if (!active || !gridState) return;
    const detected = detectAnomalies(gridState);
    setAnomalies(detected);
    setCurrentIdx(0);
  }, [active, gridState]);

  // Fly to current anomaly
  useEffect(() => {
    if (!active || !map || anomalies.length === 0) return;

    const anomaly = anomalies[currentIdx];
    if (!anomaly) {
      onStop?.();
      return;
    }

    // Set narration
    setNarration(anomaly);

    // Fly camera
    map.flyTo({
      center: anomaly.center,
      zoom: anomaly.zoom,
      pitch: anomaly.pitch,
      bearing: anomaly.bearing,
      duration: anomaly.duration,
      essential: true,
      easing: easeInOutCubic,
    });

    // Schedule next stop
    timerRef.current = setTimeout(() => {
      if (currentIdx < anomalies.length - 1) {
        setCurrentIdx((i) => i + 1);
      } else {
        // Loop back or stop
        onStop?.();
      }
    }, anomaly.duration + 2000); // Dwell 2s at each stop

    return () => clearTimeout(timerRef.current);
  }, [active, map, anomalies, currentIdx, onStop]);

  // Cleanup on deactivate
  useEffect(() => {
    if (!active) {
      clearTimeout(timerRef.current);
      setNarration(null);
      setCurrentIdx(0);
    }
  }, [active]);

  if (!active || !narration) return null;

  return (
    <div className="gc-choreo-narration">
      <div className="gc-choreo-progress">
        {anomalies.map((_, i) => (
          <div
            key={i}
            className={`gc-choreo-dot ${i === currentIdx ? "active" : ""} ${i < currentIdx ? "done" : ""}`}
          />
        ))}
      </div>
      <div className="gc-choreo-label" style={{ borderLeftColor: narration.color }}>
        <div className="gc-choreo-type">{narration.type.toUpperCase()}</div>
        <div className="gc-choreo-text">{narration.label}</div>
        <div className="gc-choreo-sub">{narration.sublabel}</div>
      </div>
      <button className="gc-choreo-stop" onClick={onStop}>
        Stop Tour
      </button>
    </div>
  );
}
