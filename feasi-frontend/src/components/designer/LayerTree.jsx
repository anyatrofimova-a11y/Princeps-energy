import React, { useState } from "react";
import { CONSTRAINT_LAYERS } from "./constraintService";

const C = {
  gold: "#F5B731", goldDark: "#E8A012", goldSurface: "rgba(245,183,49,0.06)",
  ink: "#1A1714", secondary: "#6B6560", tertiary: "#9C9590",
  border: "#E8E5DF", card: "#FFFFFF", danger: "#B5432A",
};

const CATEGORIES = {
  infrastructure: { label: "Infrastructure", types: ["battery_container_20ft", "battery_container_40ft", "server_hall_standard", "server_hall_large", "server_hall_hyperscale", "cooling_plant", "generator", "loading_dock", "office_noc", "gatehouse", "control_room", "fuel_storage", "water_treatment"] },
  electrical: { label: "Electrical", types: ["pcs_inverter", "transformer_mv", "transformer_hv", "transformer_compound", "mv_switchgear", "switchgear", "ups_building", "aux_transformer", "primary_substation"] },
  safety: { label: "Safety", types: ["fire_water_tank", "fire_pump", "lightning_mast", "perimeter_fence"] },
  site: { label: "Site", types: ["car_park", "suds_tank", "landscape_buffer"] },
};

function EyeIcon({ visible, size = 14 }) {
  return visible ? (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke={C.gold} strokeWidth="1.5">
      <path d="M1.5 8c1.5-4 4.5-5.5 6.5-5.5s5 1.5 6.5 5.5c-1.5 4-4.5 5.5-6.5 5.5S3 12 1.5 8z" />
      <circle cx="8" cy="8" r="2.5" />
    </svg>
  ) : (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke={C.tertiary} strokeWidth="1.5">
      <path d="M1.5 8c1.5-4 4.5-5.5 6.5-5.5s5 1.5 6.5 5.5c-1.5 4-4.5 5.5-6.5 5.5S3 12 1.5 8z" />
      <path d="M2 2l12 12" />
    </svg>
  );
}

function Section({ title, count, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ marginBottom: 4 }}>
      <div
        onClick={() => setOpen(!open)}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "8px 12px", cursor: "pointer",
          borderBottom: `1px solid ${C.border}`,
        }}
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none"
          style={{ transform: open ? "rotate(90deg)" : "rotate(0)", transition: "transform 0.15s" }}>
          <path d="M3 1.5L7 5L3 8.5" stroke={C.tertiary} strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: C.secondary, flex: 1 }}>
          {title}
        </span>
        {count > 0 && (
          <span style={{
            fontSize: 9, fontWeight: 700, color: C.goldDark,
            background: C.goldSurface, padding: "1px 6px", borderRadius: 8,
          }}>
            {count}
          </span>
        )}
      </div>
      {open && <div style={{ padding: "2px 0" }}>{children}</div>}
    </div>
  );
}

function ObjectRow({ obj, onToggle, onDelete }) {
  const [hovered, setHovered] = useState(false);
  const visible = obj.visible !== false;
  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "6px 12px 6px 24px",
        background: hovered ? C.goldSurface : "transparent",
        transition: "background 0.12s",
      }}
    >
      <div onClick={() => onToggle(obj.id)} style={{ cursor: "pointer", flexShrink: 0 }}>
        <EyeIcon visible={visible} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 500, color: C.ink, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {obj.label || obj.type.replace(/_/g, " ")}
      </span>
      <span style={{
        fontSize: 9, fontWeight: 600, color: C.goldDark, background: C.goldSurface,
        padding: "1px 6px", borderRadius: 8, flexShrink: 0,
      }}>
        {obj.category || ""}
      </span>
      {hovered && (
        <div onClick={() => onDelete(obj.id)} style={{ cursor: "pointer", flexShrink: 0 }}>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke={C.danger} strokeWidth="1.5">
            <path d="M3 3l6 6M9 3l-6 6" strokeLinecap="round" />
          </svg>
        </div>
      )}
    </div>
  );
}

function ConstraintRow({ constraint, enabled, onToggle }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={() => onToggle(constraint.id)}
      style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "6px 12px 6px 24px", cursor: "pointer",
        background: hovered ? C.goldSurface : "transparent",
        transition: "background 0.12s",
      }}
    >
      <div style={{
        width: 14, height: 14, borderRadius: 3,
        border: `1.5px solid ${enabled ? C.gold : C.border}`,
        background: enabled ? C.gold : "transparent",
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "all 0.15s",
      }}>
        {enabled && (
          <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
            <path d="M1.5 4L3.5 6L6.5 2" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </div>
      <span style={{ fontSize: 12, fontWeight: 500, color: enabled ? C.ink : C.secondary, flex: 1 }}>
        {constraint.label}
      </span>
      {constraint.severity === "high" && (
        <span style={{ fontSize: 8, fontWeight: 700, color: C.danger, background: `${C.danger}15`, padding: "1px 5px", borderRadius: 6 }}>
          !
        </span>
      )}
    </div>
  );
}

export default function LayerTree({ objects = [], constraints = {}, onToggleObject, onDeleteObject, onToggleConstraint }) {
  const categorised = {};
  for (const [key, cat] of Object.entries(CATEGORIES)) {
    categorised[key] = objects.filter(o => cat.types.includes(o.type));
  }

  const constraintList = Object.values(CONSTRAINT_LAYERS);

  return (
    <div style={{
      height: "100%", overflowY: "auto", background: C.card,
      borderRight: `1px solid ${C.border}`,
    }}>
      <div style={{
        padding: "12px 12px 8px", fontSize: 11, fontWeight: 700,
        color: C.ink, borderBottom: `1px solid ${C.border}`,
      }}>
        Layers
        <span style={{ fontSize: 10, color: C.tertiary, fontWeight: 400, marginLeft: 8 }}>
          {objects.length} objects
        </span>
      </div>

      {Object.entries(CATEGORIES).map(([key, cat]) => (
        <Section key={key} title={cat.label} count={categorised[key]?.length || 0}>
          {(categorised[key] || []).map(obj => (
            <ObjectRow
              key={obj.id}
              obj={{ ...obj, label: obj.properties?.hall_number ? `${obj.type.replace(/_/g, " ")} #${obj.properties.hall_number}` : undefined }}
              onToggle={onToggleObject}
              onDelete={onDeleteObject}
            />
          ))}
          {(!categorised[key] || categorised[key].length === 0) && (
            <div style={{ padding: "8px 24px", fontSize: 11, color: C.tertiary, fontStyle: "italic" }}>
              No objects placed
            </div>
          )}
        </Section>
      ))}

      <div style={{ height: 1, background: C.border, margin: "4px 0" }} />

      <Section title="Constraints" count={Object.values(constraints).filter(Boolean).length} defaultOpen={false}>
        {constraintList.map(c => (
          <ConstraintRow
            key={c.id}
            constraint={c}
            enabled={!!constraints[c.id]}
            onToggle={onToggleConstraint}
          />
        ))}
      </Section>
    </div>
  );
}
