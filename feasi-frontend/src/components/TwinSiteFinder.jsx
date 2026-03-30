/**
 * TwinSiteFinder — Find a Site panel for the Cesium digital twin.
 *
 * Three modes: Search (geocode), Coordinates (lat/lon), Map Pin (click globe).
 * Flies the Cesium camera to the selected location and drops a marker entity.
 *
 * Props:
 *   viewer           — Cesium.Viewer instance
 *   onSiteSelected   — callback({ lat, lon, name })
 */
import React, { useState, useCallback, useRef, useEffect } from "react";
import * as Cesium from "cesium";

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || "";

export default function TwinSiteFinder({ viewer, onSiteSelected }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState("search");
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [coordLat, setCoordLat] = useState("");
  const [coordLon, setCoordLon] = useState("");
  const [pinMode, setPinMode] = useState(false);
  const [selectedSite, setSelectedSite] = useState(null);
  const debounceRef = useRef(null);
  const markerRef = useRef(null);
  const pinHandlerRef = useRef(null);

  /* ── Geocode via Mapbox ── */
  const geocode = useCallback(async (text) => {
    if (!text || text.length < 3) { setSuggestions([]); return; }
    setLoading(true);
    try {
      const res = await fetch(
        `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(text)}.json?country=gb&limit=6&access_token=${MAPBOX_TOKEN}`
      );
      if (res.ok) {
        const data = await res.json();
        setSuggestions(
          (data.features || []).map(f => ({
            name: f.place_name,
            lat: f.center[1],
            lon: f.center[0],
            type: f.place_type?.[0] || "place",
          }))
        );
      }
    } catch {}
    setLoading(false);
  }, []);

  const handleQueryChange = (e) => {
    const val = e.target.value;
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => geocode(val), 300);
  };

  /* ── Fly to location and drop marker ── */
  const flyToSite = useCallback((lat, lon, name) => {
    if (!viewer || viewer.isDestroyed()) return;

    // Remove old marker
    if (markerRef.current) {
      viewer.entities.remove(markerRef.current);
    }

    // Add pin marker
    markerRef.current = viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(lon, lat, 100),
      billboard: {
        image: buildPinCanvas(),
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        scale: 0.8,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
      },
      label: {
        text: name || `${lat.toFixed(4)}, ${lon.toFixed(4)}`,
        font: "13px 'DM Sans', sans-serif",
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK.withAlpha(0.8),
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -45),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        showBackground: true,
        backgroundColor: Cesium.Color.fromCssColorString("rgba(212,160,24,0.85)"),
        backgroundPadding: new Cesium.Cartesian2(8, 4),
      },
    });

    // Fly camera
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lon, lat, 15000),
      orientation: {
        heading: Cesium.Math.toRadians(350),
        pitch: Cesium.Math.toRadians(-40),
        roll: 0,
      },
      duration: 2,
    });

    const site = { lat, lon, name: name || `${lat.toFixed(4)}, ${lon.toFixed(4)}` };
    setSelectedSite(site);
    onSiteSelected?.(site);
  }, [viewer, onSiteSelected]);

  /* ── Search result click ── */
  const handleSelect = (s) => {
    setQuery(s.name);
    setSuggestions([]);
    flyToSite(s.lat, s.lon, s.name);
  };

  /* ── Coordinates submit ── */
  const handleCoordsSubmit = () => {
    const lat = parseFloat(coordLat);
    const lon = parseFloat(coordLon);
    if (!isNaN(lat) && !isNaN(lon)) {
      flyToSite(lat, lon);
    }
  };

  /* ── Map pin mode ── */
  useEffect(() => {
    if (!pinMode || !viewer || viewer.isDestroyed()) return;

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((click) => {
      const cartesian = viewer.camera.pickEllipsoid(click.position, viewer.scene.globe.ellipsoid);
      if (cartesian) {
        const carto = Cesium.Cartographic.fromCartesian(cartesian);
        const lat = Cesium.Math.toDegrees(carto.latitude);
        const lon = Cesium.Math.toDegrees(carto.longitude);
        flyToSite(lat, lon);
        setPinMode(false);
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    pinHandlerRef.current = handler;
    // Change cursor
    viewer.scene.canvas.style.cursor = "crosshair";

    return () => {
      handler.destroy();
      if (viewer && !viewer.isDestroyed()) {
        viewer.scene.canvas.style.cursor = "default";
      }
    };
  }, [pinMode, viewer, flyToSite]);

  /* ── Build pin icon as canvas ── */
  function buildPinCanvas() {
    const c = document.createElement("canvas");
    c.width = 40; c.height = 52;
    const ctx = c.getContext("2d");
    // Pin shape
    ctx.fillStyle = "#D4A018";
    ctx.beginPath();
    ctx.arc(20, 18, 14, Math.PI, 0);
    ctx.quadraticCurveTo(34, 30, 20, 52);
    ctx.quadraticCurveTo(6, 30, 6, 18);
    ctx.fill();
    // Inner circle
    ctx.fillStyle = "#fff";
    ctx.beginPath();
    ctx.arc(20, 18, 6, 0, Math.PI * 2);
    ctx.fill();
    return c;
  }

  if (!open) {
    return (
      <button className="tsf-toggle" onClick={() => setOpen(true)} title="Find a Site">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
        </svg>
      </button>
    );
  }

  return (
    <div className="tsf-panel">
      {/* Header */}
      <div className="tsf-header">
        <span className="tsf-title">Find a Site</span>
        <button className="tsf-close" onClick={() => { setOpen(false); setPinMode(false); }}>&times;</button>
      </div>

      {/* Mode tabs */}
      <div className="tsf-tabs">
        <button className={`tsf-tab ${mode === "search" ? "active" : ""}`} onClick={() => setMode("search")}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
          </svg>
          Search
        </button>
        <button className={`tsf-tab ${mode === "coords" ? "active" : ""}`} onClick={() => setMode("coords")}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>
          </svg>
          Coordinates
        </button>
        <button className={`tsf-tab ${mode === "pin" ? "active" : ""} ${pinMode ? "pinning" : ""}`}
          onClick={() => { setMode("pin"); setPinMode(true); }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/>
          </svg>
          Map Pin
        </button>
      </div>

      {/* Search mode */}
      {mode === "search" && (
        <div className="tsf-body">
          <input
            className="tsf-input"
            type="text"
            placeholder="Address, postcode, or place name..."
            value={query}
            onChange={handleQueryChange}
            autoFocus
          />
          {loading && <div className="tsf-loading">Searching...</div>}
          {suggestions.length > 0 && (
            <div className="tsf-suggestions">
              {suggestions.map((s, i) => (
                <button key={i} className="tsf-suggestion" onClick={() => handleSelect(s)}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/>
                  </svg>
                  <div className="tsf-suggestion-text">
                    <div className="tsf-suggestion-name">{s.name}</div>
                    <div className="tsf-suggestion-coord">{s.lat.toFixed(4)}, {s.lon.toFixed(4)}</div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Coordinates mode */}
      {mode === "coords" && (
        <div className="tsf-body">
          <div className="tsf-coord-row">
            <label>Lat</label>
            <input className="tsf-input" type="number" step="0.0001" placeholder="51.5074"
              value={coordLat} onChange={e => setCoordLat(e.target.value)} />
          </div>
          <div className="tsf-coord-row">
            <label>Lon</label>
            <input className="tsf-input" type="number" step="0.0001" placeholder="-0.1278"
              value={coordLon} onChange={e => setCoordLon(e.target.value)} />
          </div>
          <button className="tsf-go-btn" onClick={handleCoordsSubmit}>Go</button>
        </div>
      )}

      {/* Pin mode */}
      {mode === "pin" && (
        <div className="tsf-body">
          <div className="tsf-pin-msg">
            {pinMode
              ? "Click anywhere on the globe to drop a pin"
              : "Pin dropped. Click again or switch mode."}
          </div>
        </div>
      )}

      {/* Selected site info */}
      {selectedSite && (
        <div className="tsf-selected">
          <div className="tsf-selected-name">{selectedSite.name}</div>
          <div className="tsf-selected-coord">{selectedSite.lat.toFixed(5)}, {selectedSite.lon.toFixed(5)}</div>
        </div>
      )}
    </div>
  );
}
