import React, { useState, useCallback, useRef, useEffect } from "react";
import { useSite } from "../SiteContext";

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || "";

export default function SitePicker({ map, onPick }) {
  const { pickMode, setPickMode } = useSite();
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState("search"); // search | coords | pin
  const [coordLat, setCoordLat] = useState("");
  const [coordLon, setCoordLon] = useState("");
  const debounceRef = useRef(null);

  // Geocode via Mapbox
  const geocode = useCallback(async (text) => {
    if (!text || text.length < 3) {
      setSuggestions([]);
      return;
    }
    setLoading(true);
    try {
      const token = MAPBOX_TOKEN || map?._requestManager?._skuToken?.token || "";
      // Try Mapbox geocoding API
      const res = await fetch(
        `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(text)}.json?country=gb&limit=5&access_token=${token}`
      );
      if (res.ok) {
        const data = await res.json();
        setSuggestions(
          (data.features || []).map((f) => ({
            name: f.place_name,
            lat: f.center[1],
            lon: f.center[0],
          }))
        );
      }
    } catch (err) {
      console.error("Geocode error:", err);
    } finally {
      setLoading(false);
    }
  }, [map]);

  const handleQueryChange = (e) => {
    const val = e.target.value;
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => geocode(val), 300);
  };

  const handleSelectSuggestion = (s) => {
    setQuery(s.name);
    setSuggestions([]);
    onPick({ lat: s.lat, lon: s.lon });
  };

  const handleCoordsSubmit = () => {
    const lat = parseFloat(coordLat);
    const lon = parseFloat(coordLon);
    if (!isNaN(lat) && !isNaN(lon)) {
      onPick({ lat, lon });
    }
  };

  const handlePinMode = () => {
    console.log("[SitePicker] entering pin mode");
    setMode("pin");
    setPickMode(true);
  };

  // Close suggestions on outside click
  const wrapperRef = useRef(null);
  useEffect(() => {
    const handler = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setSuggestions([]);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // In pin mode, show only a minimal banner so the map is fully clickable
  if (mode === "pin") {
    return (
      <div className="site-picker pin-active" ref={wrapperRef}>
        <div className="sp-pin-info">
          <div className="sp-pin-pulse" />
          <span>Click anywhere on the map to place a pin</span>
          <button
            className="sp-pin-cancel"
            style={{ pointerEvents: "auto" }}
            onClick={() => { setMode("search"); setPickMode(false); }}
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="site-picker" ref={wrapperRef}>
      <div className="sp-header">
        <span className="sp-title">Find a Site</span>
      </div>

      {/* Mode tabs */}
      <div className="sp-tabs">
        <button
          className={`sp-tab${mode === "search" ? " active" : ""}`}
          onClick={() => { setMode("search"); setPickMode(false); }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
          </svg>
          Search
        </button>
        <button
          className={`sp-tab${mode === "coords" ? " active" : ""}`}
          onClick={() => { setMode("coords"); setPickMode(false); }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" /><path d="M2 12h20M12 2v20" />
          </svg>
          Coordinates
        </button>
        <button
          className={`sp-tab${mode === "pin" ? " active" : ""}`}
          onClick={handlePinMode}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" /><circle cx="12" cy="10" r="3" />
          </svg>
          Map Pin
        </button>
      </div>

      {/* Search mode */}
      {mode === "search" && (
        <div className="sp-search">
          <input
            className="sp-input"
            type="text"
            value={query}
            onChange={handleQueryChange}
            placeholder="Address, postcode, or place name..."
            autoFocus
          />
          {loading && <div className="sp-loading">Searching...</div>}
          {suggestions.length > 0 && (
            <div className="sp-suggestions">
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  className="sp-suggestion"
                  onClick={() => handleSelectSuggestion(s)}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" /><circle cx="12" cy="10" r="3" />
                  </svg>
                  <span>{s.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Coordinates mode */}
      {mode === "coords" && (
        <div className="sp-coords">
          <div className="sp-coord-row">
            <label>Lat</label>
            <input
              className="sp-coord-input"
              type="number"
              step="0.0001"
              value={coordLat}
              onChange={(e) => setCoordLat(e.target.value)}
              placeholder="52.4862"
            />
          </div>
          <div className="sp-coord-row">
            <label>Lon</label>
            <input
              className="sp-coord-input"
              type="number"
              step="0.0001"
              value={coordLon}
              onChange={(e) => setCoordLon(e.target.value)}
              placeholder="-1.8904"
            />
          </div>
          <button
            className="sp-go-btn"
            onClick={handleCoordsSubmit}
            disabled={!coordLat || !coordLon}
          >
            Go to Site
          </button>
        </div>
      )}
    </div>
  );
}
