/**
 * AssessTwinInspector — right-side inspector pane that opens when a user clicks
 * a pickable element on the AssessProjectTwin deck.gl map.
 *
 * Shows engineering-grade spec per selected element, with standards citations.
 * Ported from DCDesignTwin's InspectorPane pattern — adapted for the
 * project-centred (not DC-centred) Assess view, which only has:
 *   polygon      — the project site outline
 *   poc          — the POC substation + line
 *   grid_line:N  — an individual nearby transmission/distribution line
 */
import React from "react";

const GOLD = "#F5B731";
const IVORY = "#FBF8F2";
const INK = "#0F1318";

export default function AssessTwinInspector({ selected, ctx, tech, capacity_mw, onClose }) {
  if (!selected) return null;

  let title = "";
  let rows = [];
  let standards = [];

  if (selected === "polygon" && ctx?.polygon) {
    const areaHa = polygonAreaHa(ctx.polygon);
    const perimeterKm = polygonPerimeterKm(ctx.polygon);
    title = "Project site";
    rows = [
      ["Tech", tech || "—"],
      ["Capacity", capacity_mw ? `${capacity_mw} MW` : "—"],
      ["Area", areaHa ? `${areaHa.toFixed(2)} ha` : "—"],
      ["Perimeter", perimeterKm ? `${perimeterKm.toFixed(2)} km` : "—"],
      ["Density", capacity_mw && areaHa ? `${(capacity_mw / areaHa).toFixed(1)} MW/ha` : "—"],
    ];
    standards = [
      "NPPF Dec 2024 para 187 (BMV + biodiversity protection)",
      "EN 50600-1 (DC site facility conditions)",
    ];
  } else if (selected === "poc" && ctx?.poc_substation) {
    const s = ctx.poc_substation;
    const distKm = centroidKm(ctx.polygon, s);
    title = `POC substation — ${s.name || "unnamed"}`;
    rows = [
      ["Voltage", s.voltage_kv ? `${s.voltage_kv} kV` : "—"],
      ["Operator", s.operator || "—"],
      ["Firm headroom", s.firm_headroom_mw != null ? `${s.firm_headroom_mw} MW` : "—"],
      ["Non-firm headroom", s.non_firm_headroom_mw != null ? `${s.non_firm_headroom_mw} MW` : "—"],
      ["Distance from site", distKm != null ? `${distKm.toFixed(2)} km` : "—"],
      ["Est. cable cost",
        distKm == null ? "—" :
        s.voltage_kv >= 132 ? `£${Math.round(distKm * 500)}k (132 kV OHL)` :
        s.voltage_kv >= 33  ? `£${Math.round(distKm * 150)}k (33 kV UG)` :
                              `£${Math.round(distKm * 80)}k (11 kV UG)`],
      ["Connection tier", s.voltage_kv >= 132 ? "Tier 3 — pandapower power flow required" : "Tier 1 — CCCM data-driven"],
    ];
    standards = [
      "ENA EREC G99 Issue 2 (generator connection)",
      "CCCM v19 (Common Connection Charging Methodology)",
      "ENA EREC P28 Issue 2 (voltage fluctuation)",
    ];
  } else if (selected?.startsWith("grid_line:") && Array.isArray(ctx?.nearest_grid_lines)) {
    const idx = parseInt(selected.slice("grid_line:".length), 10);
    const ln = ctx.nearest_grid_lines[idx];
    if (ln) {
      title = `Grid line — ${ln.voltage_kv || "?"} kV`;
      rows = [
        ["Voltage class", ln.voltage_kv ? `${ln.voltage_kv} kV` : "—"],
        ["Length", ln.length_km ? `${ln.length_km.toFixed(2)} km` : "—"],
        ["Type", ln.conductor_type || (ln.underground ? "Underground cable" : "Overhead line")],
        ["Thermal rating", ln.rating_mva ? `${ln.rating_mva} MVA` : "—"],
        ["Owner", ln.operator || ln.owner || "—"],
        ["Asset class", ln.asset_class || (ln.voltage_kv >= 275 ? "Transmission" : "Distribution")],
      ];
      standards = [
        "BS 7671 Chapter 52 (cable ampacity)",
        "ENA EREC P2/7 (security standards)",
        "NESO System Operability Framework",
      ];
    }
  }

  return (
    <>
      {/* Click-outside dismissal layer (invisible). */}
      <div
        onClick={onClose}
        style={{ position: "absolute", inset: 0, zIndex: 40 }}
      />
      <aside
        style={{
          position: "absolute",
          top: 16, right: 16, bottom: 16,
          width: 340,
          background: IVORY,
          borderRadius: 10,
          border: "1px solid rgba(15,19,24,0.10)",
          boxShadow: "0 8px 24px rgba(15,19,24,0.18)",
          zIndex: 50,
          overflowY: "auto",
          fontFamily: "'DM Sans', sans-serif",
          color: INK,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <header style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          padding: "14px 16px 10px",
          borderBottom: "1px solid rgba(15,19,24,0.08)",
          position: "sticky", top: 0, background: IVORY, zIndex: 2,
        }}>
          <div>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10, letterSpacing: "0.06em",
              textTransform: "uppercase", color: "#6B7280", fontWeight: 700,
            }}>Inspector</div>
            <h3 style={{ margin: "3px 0 0", fontSize: 15, fontWeight: 700 }}>{title || "Select an element"}</h3>
          </div>
          <button
            onClick={onClose}
            aria-label="Close inspector"
            style={{
              background: "transparent", border: "none", fontSize: 20,
              color: INK, cursor: "pointer", padding: 0, lineHeight: 1,
            }}
          >×</button>
        </header>

        <div style={{ padding: "14px 16px" }}>
          {rows.length === 0 && (
            <div style={{ fontSize: 13, color: "#6B7280", fontStyle: "italic" }}>
              No data for this element. Click a different layer.
            </div>
          )}
          {rows.map(([label, value], i) => (
            <div
              key={i}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "6px 0",
                borderBottom: i < rows.length - 1 ? "1px dashed rgba(15,19,24,0.08)" : "none",
                fontSize: 13,
              }}
            >
              <span style={{ color: "#6B7280" }}>{label}</span>
              <span style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 600,
                fontVariantNumeric: "tabular-nums",
                textAlign: "right",
              }}>{value}</span>
            </div>
          ))}

          {standards.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{
                fontSize: 10, fontWeight: 700, letterSpacing: "0.06em",
                textTransform: "uppercase", color: "#6B7280", marginBottom: 6,
              }}>Standards</div>
              <ul style={{ margin: 0, paddingLeft: 14, fontSize: 11, color: "#4B5563", lineHeight: 1.5 }}>
                {standards.map((s, i) => <li key={i}>{s}</li>)}
              </ul>
            </div>
          )}
        </div>

        <footer style={{
          padding: "10px 16px 14px",
          borderTop: "1px solid rgba(15,19,24,0.08)",
          display: "flex", gap: 8,
        }}>
          <button
            style={{
              padding: "6px 12px",
              fontSize: 12,
              fontWeight: 600,
              background: GOLD,
              color: INK,
              border: "none",
              borderRadius: 5,
              cursor: "pointer",
              fontFamily: "inherit",
            }}
            onClick={() => {
              // Pin this element as project evidence. Dispatches an app-level event.
              if (typeof window !== "undefined") {
                window.dispatchEvent(new CustomEvent("princeps-pin-asset", {
                  detail: { kind: selected, ts: Date.now() },
                }));
              }
            }}
          >Pin to project ◆</button>
        </footer>
      </aside>
    </>
  );
}

// ── Geometry helpers ────────────────────────────────────────────────────────

function polygonAreaHa(polygon) {
  const coords = getOuterRing(polygon);
  if (!coords || coords.length < 4) return null;
  // Shoelace in projected metres (local equirectangular).
  const lat0 = coords[0][1];
  const latRad = (lat0 * Math.PI) / 180;
  const mPerLon = 111320 * Math.cos(latRad);
  const mPerLat = 110540;
  let a = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    const [x1, y1] = [coords[i][0] * mPerLon, coords[i][1] * mPerLat];
    const [x2, y2] = [coords[i + 1][0] * mPerLon, coords[i + 1][1] * mPerLat];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a) / 2 / 10_000;
}

function polygonPerimeterKm(polygon) {
  const coords = getOuterRing(polygon);
  if (!coords || coords.length < 2) return null;
  let total = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    total += haversineKm(coords[i], coords[i + 1]);
  }
  return total;
}

function centroidKm(polygon, pt) {
  const coords = getOuterRing(polygon);
  if (!coords || coords.length === 0 || !pt) return null;
  let sx = 0, sy = 0;
  for (const c of coords) { sx += c[0]; sy += c[1]; }
  const cx = sx / coords.length, cy = sy / coords.length;
  return haversineKm([cx, cy], [pt.lon, pt.lat]);
}

function getOuterRing(polygon) {
  if (!polygon) return null;
  if (polygon.type === "Feature") return polygon.geometry?.coordinates?.[0];
  if (polygon.type === "Polygon") return polygon.coordinates?.[0];
  if (polygon.type === "MultiPolygon") return polygon.coordinates?.[0]?.[0];
  return null;
}

function haversineKm(a, b) {
  const R = 6371;
  const dLat = ((b[1] - a[1]) * Math.PI) / 180;
  const dLon = ((b[0] - a[0]) * Math.PI) / 180;
  const la1 = (a[1] * Math.PI) / 180;
  const la2 = (b[1] * Math.PI) / 180;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
