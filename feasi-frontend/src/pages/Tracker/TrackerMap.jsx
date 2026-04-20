import React, { useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ScatterplotLayer } from "@deck.gl/layers";
import { getGeoJSON } from "../../api/tracker";
import TrackerDetail from "./TrackerDetail";

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN || "";

/* ─────────────────────────────────────────────────────────────────
   TrackerMap — deck.gl ScatterplotLayer over Mapbox GL, plotting
   every substation from /api/tracker/substations/geojson.

   Colour by construction_status.
   Radius by voltage_kv_primary (400 kV → 24 px, 132 kV → 16 px, …).
   Click marker → right-rail TrackerDetail drawer.
   ──────────────────────────────────────────────────────────────── */

const C = {
  gold: "#F5B731",
  goldSoft: "#C9A64B",
  goldBorder: "rgba(245,183,49,0.32)",
  ivory: "#FBF8F2",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  bg: "#FFFFFF",
};

// status → RGBA
const STATUS_RGBA = {
  planned:            [245, 183, 49, 210],   // amber gold
  under_construction: [213, 148, 12, 230],   // deeper gold
  complete:           [47, 168, 79, 220],    // green
  cancelled:          [214, 69, 69, 210],    // red
};

function statusRgba(status) {
  return STATUS_RGBA[status] || [140, 140, 140, 180];
}

// Radius in metres (scaled by zoom via deck.gl). Tuned so 400 kV reads
// large at mid zoom; the `radiusUnits: "pixels"` below converts
// getRadius into px directly.
function radiusForVoltage(v) {
  if (!v) return 7;
  if (v >= 400) return 14;
  if (v >= 275) return 12;
  if (v >= 132) return 9;
  if (v >= 66)  return 7;
  if (v >= 33)  return 5;
  return 4;
}

const LEGEND_STATUSES = [
  { key: "planned",            label: "Planned",            hex: "#F5B731" },
  { key: "under_construction", label: "Under construction", hex: "#D5940C" },
  { key: "complete",           label: "Complete",           hex: "#2FA84F" },
  { key: "cancelled",          label: "Cancelled",          hex: "#D64545" },
];

const LEGEND_VOLTAGES = [
  { kv: 400, px: 14 },
  { kv: 275, px: 12 },
  { kv: 132, px: 9 },
  { kv: 33,  px: 5 },
];

export default function TrackerMap({ admin = false }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const overlayRef = useRef(null);
  const [features, setFeatures] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [hover, setHover] = useState(null);
  const [error, setError] = useState(null);

  // Fetch substations
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const gj = await getGeoJSON();
        if (cancelled) return;
        setFeatures(gj.features || []);
      } catch (e) {
        if (!cancelled) setError(e.message || String(e));
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Init Mapbox + deck.gl overlay
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    if (!mapboxgl.accessToken) {
      setError("Missing VITE_MAPBOX_TOKEN — map cannot initialise");
      return;
    }
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/streets-v12",
      center: [-2.5, 53.5],
      zoom: 5.4,
      maxZoom: 14,
      attributionControl: false,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new mapboxgl.AttributionControl({ compact: true }), "bottom-right");

    const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
    map.once("load", () => {
      map.addControl(overlay);
      overlayRef.current = overlay;
    });

    mapRef.current = map;
    return () => {
      try { overlay.finalize?.(); } catch {}
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, []);

  // Update layers on data change
  useEffect(() => {
    if (!overlayRef.current) return;
    const layer = new ScatterplotLayer({
      id: "tracker-substations",
      data: features,
      pickable: true,
      stroked: true,
      filled: true,
      radiusUnits: "pixels",
      lineWidthUnits: "pixels",
      getPosition: (f) => f.geometry.coordinates,
      getRadius: (f) => radiusForVoltage(f.properties?.voltage_kv_primary),
      getFillColor: (f) => statusRgba(f.properties?.construction_status),
      getLineColor: [15, 19, 24, 120],
      getLineWidth: 1,
      onHover: ({ object, x, y }) => {
        if (object) setHover({ f: object, x, y });
        else setHover(null);
      },
      onClick: ({ object }) => {
        if (object?.properties?.project_id) setSelectedId(object.properties.project_id);
      },
      updateTriggers: {
        getFillColor: [features.length],
        getRadius: [features.length],
      },
    });
    overlayRef.current.setProps({ layers: [layer] });
  }, [features]);

  return (
    <div style={{ position: "relative", flex: 1, minHeight: 0, background: "#1e1e1e" }}>
      <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />

      {error && (
        <div
          style={{
            position: "absolute",
            top: 16,
            left: "50%",
            transform: "translateX(-50%)",
            background: "#FBD8D5",
            color: "#8E1E1E",
            border: "1px solid #E89A94",
            padding: "8px 14px",
            borderRadius: 6,
            fontSize: 12,
            fontFamily: "'DM Sans', sans-serif",
            zIndex: 10,
          }}
        >
          {error}
        </div>
      )}

      {/* Legend */}
      <div
        style={{
          position: "absolute",
          left: 16,
          bottom: 16,
          background: "rgba(255,255,255,0.96)",
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          padding: "12px 14px",
          fontFamily: "'DM Sans', sans-serif",
          color: C.ink,
          boxShadow: "0 4px 16px rgba(15,19,24,0.08)",
          zIndex: 5,
          minWidth: 210,
        }}
      >
        <div style={{ fontSize: 10, color: C.tertiary, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 8 }}>
          Legend · {features.length} substations
        </div>
        <div style={{ fontSize: 10, color: C.tertiary, fontWeight: 600, marginBottom: 4 }}>Status</div>
        <div style={{ display: "grid", gap: 4, marginBottom: 10 }}>
          {LEGEND_STATUSES.map((s) => (
            <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11 }}>
              <span
                style={{
                  width: 10, height: 10, borderRadius: 5,
                  background: s.hex, border: "1px solid rgba(15,19,24,0.2)",
                  display: "inline-block",
                }}
              />
              {s.label}
            </div>
          ))}
        </div>
        <div style={{ fontSize: 10, color: C.tertiary, fontWeight: 600, marginBottom: 4 }}>Voltage (radius)</div>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
          {LEGEND_VOLTAGES.map((v) => (
            <div key={v.kv} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
              <span
                style={{
                  width: v.px * 2,
                  height: v.px * 2,
                  borderRadius: "50%",
                  background: C.gold,
                  border: "1px solid rgba(15,19,24,0.25)",
                }}
              />
              <span style={{ fontSize: 10, color: C.secondary, fontFamily: "'JetBrains Mono', monospace" }}>
                {v.kv} kV
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Hover tooltip */}
      {hover?.f && (
        <div
          style={{
            position: "absolute",
            left: hover.x + 14,
            top: hover.y + 14,
            background: C.ink,
            color: "#fff",
            padding: "8px 10px",
            borderRadius: 6,
            fontSize: 11,
            fontFamily: "'DM Sans', sans-serif",
            pointerEvents: "none",
            zIndex: 20,
            maxWidth: 260,
            boxShadow: "0 4px 14px rgba(0,0,0,0.35)",
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 4, fontSize: 12 }}>
            {hover.f.properties?.substation_name}
          </div>
          <div style={{ opacity: 0.8, fontFamily: "'JetBrains Mono', monospace" }}>
            {hover.f.properties?.voltage_kv_primary} kV · {hover.f.properties?.construction_status?.replace(/_/g, " ")}
          </div>
          <div style={{ opacity: 0.7, marginTop: 2 }}>
            {hover.f.properties?.developer} · {hover.f.properties?.region}
          </div>
        </div>
      )}

      <TrackerDetail
        id={selectedId}
        onClose={() => setSelectedId(null)}
        admin={admin}
      />
    </div>
  );
}
