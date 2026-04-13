import React, { useState, useCallback, useMemo } from "react";
import LayerTree from "./LayerTree";
import AnalysisPanel from "./AnalysisPanel";
import { generateBESSLayout, calculateBESSMetrics } from "./bessAutoLayout";
import { generateDCLayout, calculateDCMetrics } from "./dcAutoLayout";

const C = {
  gold: "#F5B731", goldDark: "#E8A012", goldSurface: "rgba(245,183,49,0.06)",
  goldBorder: "rgba(245,183,49,0.25)",
  ink: "#1A1714", secondary: "#6B6560", tertiary: "#9C9590",
  border: "#E8E5DF", card: "#FFFFFF", bg: "#F7F8FA",
};

function ToolbarButton({ label, active, onClick, gold, icon }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "6px 14px",
        fontSize: 12,
        fontWeight: active || gold ? 600 : 500,
        fontFamily: "'DM Sans', sans-serif",
        borderRadius: 8,
        border: `1px solid ${active ? C.gold : gold ? C.goldBorder : C.border}`,
        background: active ? C.gold : gold ? C.goldSurface : C.card,
        color: active ? "#fff" : gold ? C.goldDark : C.ink,
        cursor: "pointer",
        transition: "all 0.15s",
        display: "flex",
        alignItems: "center",
        gap: 5,
        whiteSpace: "nowrap",
      }}
    >
      {icon}
      {label}
    </button>
  );
}

function NumberInput({ label, value, onChange, unit, min = 0, max = 1000, step = 1 }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ fontSize: 11, color: C.secondary, fontWeight: 500, whiteSpace: "nowrap" }}>{label}</span>
      <input
        type="number"
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        min={min}
        max={max}
        step={step}
        style={{
          width: 64,
          padding: "5px 8px",
          fontSize: 13,
          fontWeight: 700,
          fontFamily: "var(--mono, 'JetBrains Mono'), monospace",
          border: `1px solid ${C.border}`,
          borderRadius: 6,
          outline: "none",
          background: C.card,
          color: C.ink,
          textAlign: "right",
        }}
        onFocus={e => { e.target.style.borderColor = C.gold; e.target.style.boxShadow = `0 0 0 2px ${C.goldSurface}`; }}
        onBlur={e => { e.target.style.borderColor = C.border; e.target.style.boxShadow = "none"; }}
      />
      {unit && <span style={{ fontSize: 11, color: C.tertiary }}>{unit}</span>}
    </div>
  );
}

function SelectInput({ label, value, onChange, options }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ fontSize: 11, color: C.secondary, fontWeight: 500, whiteSpace: "nowrap" }}>{label}</span>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          padding: "5px 8px",
          fontSize: 12,
          fontFamily: "'DM Sans', sans-serif",
          border: `1px solid ${C.border}`,
          borderRadius: 6,
          outline: "none",
          background: C.card,
          color: C.ink,
          cursor: "pointer",
        }}
      >
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

export default function UnifiedSiteDesigner() {
  const [mode, setMode] = useState("bess");
  const [mwTarget, setMwTarget] = useState(50);
  const [duration, setDuration] = useState(2);
  const [tier, setTier] = useState(3);
  const [objects, setObjects] = useState([]);
  const [constraints, setConstraints] = useState({ fire_setback: true, access: true, noise: true });
  const [metrics, setMetrics] = useState(null);
  const [showAnalysis, setShowAnalysis] = useState(true);
  const [canvasScale, setCanvasScale] = useState(1);

  const handleAutoLayout = useCallback(() => {
    let result;
    if (mode === "bess") {
      result = generateBESSLayout(mwTarget, duration);
    } else {
      result = generateDCLayout(mwTarget, tier);
    }
    setObjects(result.objects);
    setMetrics(result.metrics);
  }, [mode, mwTarget, duration, tier]);

  const handleClear = useCallback(() => {
    setObjects([]);
    setMetrics(null);
  }, []);

  const handleToggleObject = useCallback((id) => {
    setObjects(prev => prev.map(o => o.id === id ? { ...o, visible: o.visible === false ? true : false } : o));
  }, []);

  const handleDeleteObject = useCallback((id) => {
    setObjects(prev => {
      const next = prev.filter(o => o.id !== id);
      if (mode === "bess") setMetrics(calculateBESSMetrics(next, mwTarget, duration));
      else setMetrics(calculateDCMetrics(next, mwTarget, tier));
      return next;
    });
  }, [mode, mwTarget, duration, tier]);

  const handleToggleConstraint = useCallback((key) => {
    setConstraints(prev => ({ ...prev, [key]: !prev[key] }));
  }, []);

  // Canvas rendering — simplified 2D plan view
  const canvasContent = useMemo(() => {
    if (!objects.length) return null;
    const maxX = Math.max(...objects.map(o => o.x + o.w)) + 60;
    const maxY = Math.max(...objects.map(o => o.y + o.h)) + 60;
    const scale = Math.min(1, 800 / maxX, 600 / maxY);

    const typeColors = {
      battery_container_20ft: "#F5B731", battery_container_40ft: "#E8A012",
      pcs_inverter: "#C67A1A", transformer_mv: "#6B6560", transformer_hv: "#6B6560",
      transformer_compound: "#6B6560", switchgear: "#9C9590", control_room: "#2D7A4F",
      fire_water_tank: "#3b82f6", fire_pump: "#3b82f6",
      server_hall_standard: "#F5B731", server_hall_large: "#E8A012", server_hall_hyperscale: "#E8A012",
      primary_substation: "#6B6560", mv_switchgear: "#9C9590",
      generator: "#B5432A", fuel_storage: "#C67A1A",
      ups_building: "#2D7A4F", cooling_plant: "#3b82f6",
      office_noc: "#9C9590", loading_dock: "#9C9590", gatehouse: "#9C9590",
      car_park: "#E8E5DF", suds_tank: "#60a5fa", fire_pump_room: "#3b82f6",
      aux_transformer: "#6B6560", lightning_mast: "#9C9590",
      water_treatment: "#3b82f6",
    };

    return (
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${maxX} ${maxY}`}
        style={{ background: "#F7F8FA" }}
      >
        {/* Grid */}
        <defs>
          <pattern id="grid" width="10" height="10" patternUnits="userSpaceOnUse">
            <path d="M 10 0 L 0 0 0 10" fill="none" stroke={C.border} strokeWidth="0.3" />
          </pattern>
        </defs>
        <rect width={maxX} height={maxY} fill="url(#grid)" />

        {/* Setback zone */}
        {metrics?.site_area_m2 && (
          <rect
            x={0} y={0} width={maxX} height={maxY}
            fill="none" stroke={C.goldBorder} strokeWidth="1" strokeDasharray="4 2"
          />
        )}

        {/* Objects */}
        {objects.filter(o => o.visible !== false).map(o => {
          const fill = typeColors[o.type] || "#9C9590";
          return (
            <g key={o.id}>
              <rect
                x={o.x} y={o.y} width={o.w} height={o.h}
                fill={fill} fillOpacity={0.2}
                stroke={fill} strokeWidth={0.8}
                rx={1}
              />
              {o.w > 4 && o.h > 2 && (
                <text
                  x={o.x + o.w / 2} y={o.y + o.h / 2}
                  textAnchor="middle" dominantBaseline="middle"
                  fontSize={Math.min(2.5, o.w / 4)}
                  fill={C.ink} fontFamily="DM Sans, sans-serif" fontWeight="600"
                >
                  {(o.label || o.type).replace(/_/g, " ").replace("battery container", "BAT").replace("server hall", "HALL").substring(0, 12)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    );
  }, [objects, metrics]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: C.bg }}>
      {/* Toolbar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "10px 16px",
        background: C.card,
        borderBottom: `1px solid ${C.border}`,
        flexShrink: 0,
        flexWrap: "wrap",
      }}>
        {/* Mode toggle */}
        <div style={{ display: "flex", gap: 4, background: C.bg, borderRadius: 8, padding: 2 }}>
          <ToolbarButton label="BESS" active={mode === "bess"} onClick={() => { setMode("bess"); handleClear(); }} />
          <ToolbarButton label="Data Centre" active={mode === "dc"} onClick={() => { setMode("dc"); handleClear(); }} />
        </div>

        <div style={{ width: 1, height: 24, background: C.border }} />

        <NumberInput label="Target" value={mwTarget} onChange={setMwTarget} unit="MW" min={1} max={500} />

        {mode === "bess" && (
          <SelectInput label="Duration" value={duration} onChange={v => setDuration(Number(v))} options={[
            { value: 1, label: "1 hr" },
            { value: 2, label: "2 hr" },
            { value: 4, label: "4 hr" },
            { value: 8, label: "8 hr" },
          ]} />
        )}

        {mode === "dc" && (
          <SelectInput label="Tier" value={tier} onChange={v => setTier(Number(v))} options={[
            { value: 1, label: "Tier I" },
            { value: 2, label: "Tier II" },
            { value: 3, label: "Tier III" },
            { value: 4, label: "Tier IV" },
          ]} />
        )}

        <div style={{ width: 1, height: 24, background: C.border }} />

        <ToolbarButton
          label="Auto Layout"
          gold
          onClick={handleAutoLayout}
          icon={<svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6.5 1L2 7h4l-.5 4L10 5H6l.5-4z" fill={C.goldDark} /></svg>}
        />
        <ToolbarButton label="Clear" onClick={handleClear} />

        <div style={{ flex: 1 }} />

        <ToolbarButton
          label={showAnalysis ? "Hide Analysis" : "Show Analysis"}
          onClick={() => setShowAnalysis(!showAnalysis)}
        />
      </div>

      {/* Main layout */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Left — Layer tree */}
        <div style={{ width: 260, flexShrink: 0, overflowY: "auto" }}>
          <LayerTree
            objects={objects}
            constraints={constraints}
            onToggleObject={handleToggleObject}
            onDeleteObject={handleDeleteObject}
            onToggleConstraint={handleToggleConstraint}
          />
        </div>

        {/* Centre — Canvas */}
        <div style={{
          flex: 1, position: "relative", overflow: "hidden",
          background: C.bg,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          {objects.length > 0 ? (
            canvasContent
          ) : (
            <div style={{ textAlign: "center", padding: 40 }}>
              <div style={{
                width: 56, height: 56, borderRadius: 14,
                background: C.goldSurface, border: `1px solid ${C.goldBorder}`,
                display: "flex", alignItems: "center", justifyContent: "center",
                margin: "0 auto 16px",
              }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={C.gold} strokeWidth="1.5">
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <path d="M3 9h18M9 3v18" />
                </svg>
              </div>
              <div style={{ fontSize: 15, fontWeight: 600, color: C.ink, marginBottom: 6 }}>
                {mode === "bess" ? "BESS Site Designer" : "Data Centre Site Designer"}
              </div>
              <div style={{ fontSize: 12, color: C.secondary, lineHeight: 1.5, maxWidth: 320 }}>
                Set your {mode === "bess" ? "MW target and duration" : "IT load and tier"}, then click
                <strong style={{ color: C.goldDark }}> Auto Layout </strong>
                to generate an optimised site layout. Drag objects to adjust.
              </div>
            </div>
          )}
        </div>

        {/* Right — Analysis panel */}
        {showAnalysis && (
          <div style={{ width: 300, flexShrink: 0, overflowY: "auto" }}>
            <AnalysisPanel
              mode={mode}
              metrics={metrics}
              objects={objects}
            />
          </div>
        )}
      </div>
    </div>
  );
}
