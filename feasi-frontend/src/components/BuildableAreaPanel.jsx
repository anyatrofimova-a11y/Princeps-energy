import React, { useEffect, useMemo, useState } from "react";

/**
 * BuildableAreaPanel — slide-in right panel.
 *
 * POSTs /api/analysis/buildable-area with filter state, displays resulting
 * buildable hectares, a sparkline of past evaluations vs. number-of-exclusions,
 * and emits a `princeps-inject-layer` CustomEvent so the map picks up the
 * buildable polygon.
 */

const COLOR = {
  gold: "#caa24a",
  ink: "#0f1318",
  ink_soft: "#6b7280",
  border: "#e5e7eb",
  bg: "#ffffff",
  shimmer: "#f3f4f6",
};

const DEFAULT_FILTERS = {
  exclude_aonb: true,
  exclude_sssi: true,
  exclude_flood_zone_3: true,
  exclude_alc_grade_1_2: true,
  slope_max_deg: 10,
  max_distance_to_substation_km: null,
};

const FILTER_LABELS = {
  exclude_aonb: "Exclude AONB / National Landscape",
  exclude_sssi: "Exclude SSSI",
  exclude_flood_zone_3: "Exclude Flood Zone 3",
  exclude_alc_grade_1_2: "Exclude ALC Grade 1–2 (BMV)",
};

function Sparkline({ series, width = 200, height = 36 }) {
  if (!series || series.length < 2) return null;
  const min = Math.min(...series);
  const max = Math.max(...series);
  const range = max - min || 1;
  const step = width / (series.length - 1);
  const pts = series.map((v, i) => {
    const x = i * step;
    const y = height - ((v - min) / range) * (height - 2) - 1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <polyline points={pts} fill="none" stroke={COLOR.gold} strokeWidth={2} />
    </svg>
  );
}

export default function BuildableAreaPanel({ open, onClose, parcelId }) {
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [state, setState] = useState({ loading: false, data: null, error: null });
  const [history, setHistory] = useState([]);

  const run = useMemo(
    () => async (f) => {
      if (!parcelId) {
        setState({ loading: false, data: null, error: "No parcel selected." });
        return;
      }
      setState((s) => ({ ...s, loading: true, error: null }));
      try {
        const res = await fetch("/api/analysis/buildable-area", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ parcel_id: parcelId, filters: f }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const d = await res.json();
        setState({ loading: false, data: d, error: null });
        const ha = d?.value ?? d?.buildable_ha ?? 0;
        setHistory((h) => [...h.slice(-19), ha]);
        const geom = d?.provenance?.geometry;
        if (geom) {
          window.dispatchEvent(new CustomEvent("princeps-inject-layer", {
            detail: { id: "buildable", kind: "geojson", data: geom, color: COLOR.gold },
          }));
        }
      } catch (e) {
        setState({ loading: false, data: null, error: e.message || String(e) });
      }
    },
    [parcelId],
  );

  useEffect(() => {
    if (open && parcelId) run(filters);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, parcelId]);

  const onToggle = (key) => {
    const next = { ...filters, [key]: !filters[key] };
    setFilters(next);
    run(next);
  };
  const onSlope = (v) => {
    const next = { ...filters, slope_max_deg: v };
    setFilters(next);
    run(next);
  };

  if (!open) return null;

  const d = state.data || {};
  const ha = d?.value ?? d?.buildable_ha ?? 0;
  const confidence = d?.confidence ?? 0;
  const exclusions = d?.provenance?.exclusions_applied || [];
  const activeFilterCount = Object.entries(filters).filter(([k, v]) => v && k.startsWith("exclude_")).length;

  return (
    <aside style={wrap}>
      <div style={head}>
        <div>
          <div style={eyebrow}>Analysis</div>
          <h2 style={title}>Buildable Area</h2>
        </div>
        <button type="button" onClick={onClose} style={closeBtn}>×</button>
      </div>

      <div style={body}>
        {!parcelId && (
          <div style={{ color: COLOR.ink_soft, fontSize: 13, padding: 12, background: COLOR.shimmer, borderRadius: 4 }}>
            Select a parcel on the map to compute buildable area.
          </div>
        )}

        <section style={section}>
          <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 1, color: COLOR.ink_soft }}>Exclusions</div>
          {Object.keys(FILTER_LABELS).map((key) => (
            <label key={key} style={row}>
              <input type="checkbox" checked={!!filters[key]} onChange={() => onToggle(key)} />
              <span>{FILTER_LABELS[key]}</span>
            </label>
          ))}
        </section>

        <section style={section}>
          <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 1, color: COLOR.ink_soft }}>Slope limit</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <input
              type="range" min={5} max={25} step={1} value={filters.slope_max_deg}
              onChange={(e) => onSlope(Number(e.target.value))}
              style={{ flex: 1 }}
            />
            <span style={{ fontVariantNumeric: "tabular-nums", fontSize: 13, minWidth: 44 }}>
              {filters.slope_max_deg}°
            </span>
          </div>
        </section>

        <section style={section}>
          <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 1, color: COLOR.ink_soft, marginBottom: 4 }}>Result</div>
          {state.loading ? (
            <div style={{ color: COLOR.ink_soft }}>Computing…</div>
          ) : state.error ? (
            <div style={{ color: "#b23b3b", fontSize: 12 }}>{state.error}</div>
          ) : (
            <>
              <div style={{ fontSize: 36, fontWeight: 600, color: COLOR.gold, lineHeight: 1 }}>
                {Number(ha).toFixed(1)}
                <span style={{ fontSize: 14, color: COLOR.ink_soft, marginLeft: 6 }}>ha buildable</span>
              </div>
              <div style={{ fontSize: 11, color: COLOR.ink_soft, marginTop: 4 }}>
                confidence {(confidence * 100).toFixed(0)}% · {exclusions.length} exclusion layers applied ·
                {activeFilterCount} filters active
              </div>
              <div style={{ marginTop: 10 }}>
                <Sparkline series={history} />
                {history.length > 1 && (
                  <div style={{ fontSize: 10, color: COLOR.ink_soft }}>
                    history — {history.length} evaluations
                  </div>
                )}
              </div>
              {exclusions.length > 0 && (
                <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12, color: COLOR.ink_soft }}>
                  {exclusions.map((x, i) => (
                    <li key={i}>
                      {x.layer}: {Number(x.overlap_ha || 0).toFixed(2)} ha
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>

        <section style={{ ...section, borderTop: `1px solid ${COLOR.border}`, paddingTop: 12, fontSize: 11, color: COLOR.ink_soft }}>
          Output: value / P10 / P50 / P90 with provenance + GeoJSON overlay injected into the map.
        </section>
      </div>
    </aside>
  );
}

const wrap = {
  position: "fixed", top: 0, right: 0, bottom: 0, width: 380,
  background: COLOR.bg, borderLeft: `1px solid ${COLOR.border}`,
  boxShadow: "-2px 0 12px rgba(15,19,24,0.08)",
  fontFamily: "'DM Sans', -apple-system, sans-serif", color: COLOR.ink,
  display: "flex", flexDirection: "column", zIndex: 40,
};
const head = {
  display: "flex", justifyContent: "space-between", alignItems: "start",
  padding: "16px 20px", borderBottom: `1px solid ${COLOR.border}`,
};
const title = { fontSize: 18, margin: "4px 0 0", letterSpacing: -0.3 };
const eyebrow = { fontSize: 10, letterSpacing: 2, textTransform: "uppercase", color: COLOR.gold, fontWeight: 600 };
const closeBtn = {
  background: "none", border: "none", fontSize: 20, cursor: "pointer",
  color: COLOR.ink_soft, lineHeight: 1, padding: 4,
};
const body = { padding: "16px 20px", overflow: "auto", flex: 1 };
const section = { marginBottom: 18 };
const row = {
  display: "flex", alignItems: "center", gap: 8, fontSize: 13, padding: "4px 0", cursor: "pointer",
};
