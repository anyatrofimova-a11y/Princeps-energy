import React from "react";

const MODES = [
  { id: "draw_polygon", icon: "⬠", label: "Polygon", group: "draw" },
  { id: "draw_rect", icon: "▬", label: "Rectangle", group: "draw" },
  { id: "draw_line", icon: "╱", label: "Line", group: "draw" },
  { id: "draw_point", icon: "●", label: "Point", group: "draw" },
  { id: "select", icon: "↖", label: "Select", group: "edit" },
  { id: "translate", icon: "✥", label: "Move", group: "edit" },
  { id: "rotate", icon: "↻", label: "Rotate", group: "edit" },
];

const FEATURE_TYPES = [
  { id: "site_boundary", label: "Site Boundary", color: "#00DCff" },
  { id: "exclusion_zone", label: "Exclusion Zone", color: "#DA1E28" },
  { id: "solar_array", label: "Solar Array", color: "#6478DC" },
  { id: "bess_pad", label: "BESS Pad", color: "#24A148" },
  { id: "dc_building", label: "DC Building", color: "#9333EA" },
  { id: "access_road", label: "Access Road", color: "#D4A018" },
  { id: "substation", label: "Substation", color: "#78909C" },
];

const S = {
  bar: {
    position: "absolute", bottom: 24, left: "50%", transform: "translateX(-50%)",
    display: "flex", alignItems: "center", gap: 6, padding: "6px 10px",
    background: "rgba(15,17,23,0.94)", borderRadius: 10,
    border: "1px solid rgba(212,160,24,0.25)", backdropFilter: "blur(12px)",
    zIndex: 1000, fontFamily: "Inter, system-ui, sans-serif",
  },
  group: { display: "flex", gap: 2 },
  sep: { width: 1, height: 28, background: "rgba(255,255,255,0.12)", margin: "0 4px" },
  btn: (active) => ({
    width: 36, height: 36, display: "flex", alignItems: "center", justifyContent: "center",
    border: active ? "1px solid #D4A018" : "1px solid transparent",
    borderRadius: 6, cursor: "pointer", fontSize: 16,
    background: active ? "rgba(212,160,24,0.18)" : "transparent",
    color: active ? "#D4A018" : "#9CA3AF",
    transition: "all 0.15s",
  }),
  select: {
    background: "rgba(15,17,23,0.9)", color: "#E8E6E1", border: "1px solid rgba(212,160,24,0.3)",
    borderRadius: 6, padding: "4px 8px", fontSize: 12, outline: "none", cursor: "pointer",
  },
  dot: (color) => ({
    width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block",
    marginRight: 6,
  }),
  count: {
    fontSize: 11, color: "#9CA3AF", padding: "0 6px", whiteSpace: "nowrap",
  },
};

export default function SiteDesignToolbarV2({ mode, onModeChange, featureType, onFeatureTypeChange, featureCount = 0, onDelete, onUndo }) {
  const ft = FEATURE_TYPES.find((f) => f.id === featureType) || FEATURE_TYPES[0];

  return (
    <div style={S.bar}>
      {/* Draw tools */}
      <div style={S.group}>
        {MODES.filter((m) => m.group === "draw").map((m) => (
          <div key={m.id} style={S.btn(mode === m.id)} onClick={() => onModeChange(mode === m.id ? "view" : m.id)} title={m.label}>
            {m.icon}
          </div>
        ))}
      </div>

      <div style={S.sep} />

      {/* Edit tools */}
      <div style={S.group}>
        {MODES.filter((m) => m.group === "edit").map((m) => (
          <div key={m.id} style={S.btn(mode === m.id)} onClick={() => onModeChange(mode === m.id ? "view" : m.id)} title={m.label}>
            {m.icon}
          </div>
        ))}
      </div>

      <div style={S.sep} />

      {/* Feature type selector */}
      <select style={S.select} value={featureType} onChange={(e) => onFeatureTypeChange(e.target.value)}>
        {FEATURE_TYPES.map((f) => (
          <option key={f.id} value={f.id}>{f.label}</option>
        ))}
      </select>
      <span style={S.dot(ft.color)} />

      <div style={S.sep} />

      {/* Actions */}
      <div style={S.btn(false)} onClick={onUndo} title="Undo">↩</div>
      <div style={S.btn(false)} onClick={onDelete} title="Delete selected">🗑</div>

      <span style={S.count}>{featureCount} features</span>

      {mode !== "view" && (
        <div style={{ ...S.btn(false), fontSize: 11, width: "auto", padding: "0 8px" }}
          onClick={() => onModeChange("view")}>
          ESC
        </div>
      )}
    </div>
  );
}
