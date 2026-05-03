/**
 * EquipmentPalette — left-side collapsible drawer of draggable equipment.
 *
 * 5 categories: Power, Cooling, Civil, Grid, Safety. Each item carries a
 * realistic footprint (width × height in metres) drawn from vendor spec
 * sheets (Tesla Megapack 2 XL ≈ 7.0×1.6 m, 132/33 kV GIS transformer ≈
 * 6×5 m, ~5 MW data hall ≈ 80×40 m, etc.).
 *
 * Drag-and-drop: we set two DataTransfer payloads so the canvas can decode
 * either — a JSON blob ("application/x-princeps-equipment") and a fallback
 * text/plain "equipment:{type_id}". The canvas listens for dragover/drop.
 */
import React, { useMemo, useState } from "react";

export const EQUIPMENT_CATALOGUE = [
  // ── POWER ────────────────────────────────────────────────────────────
  { type_id: "megapack",        category: "power",   name: "Tesla Megapack",        footprint_m: [7.0, 1.6],  icon: "▬",  phase: 2 },
  { type_id: "bess_container",  category: "power",   name: "BESS 20ft Container",   footprint_m: [6.1, 2.4],  icon: "▬",  phase: 2 },
  { type_id: "inverter",        category: "power",   name: "Central Inverter",      footprint_m: [2.5, 1.5],  icon: "⚙",  phase: 2 },
  { type_id: "transformer",     category: "power",   name: "132/33 kV Transformer", footprint_m: [6.0, 5.0],  icon: "Ψ",  phase: 2 },
  { type_id: "switchgear",      category: "power",   name: "Switchgear Room",       footprint_m: [8.0, 4.0],  icon: "⚡", phase: 2 },

  // ── COOLING ──────────────────────────────────────────────────────────
  { type_id: "chiller",         category: "cooling", name: "Chilled Water Plant",   footprint_m: [20.0, 15.0], icon: "❄", phase: 2 },
  { type_id: "cooling_tower",   category: "cooling", name: "Cooling Tower",         footprint_m: [6.0, 6.0],   icon: "≡", phase: 2 },
  { type_id: "crac_unit",       category: "cooling", name: "CRAC Unit",             footprint_m: [2.0, 1.0],   icon: "▦", phase: 2 },
  { type_id: "dry_cooler",      category: "cooling", name: "Dry Cooler",            footprint_m: [12.0, 3.0],  icon: "▤", phase: 2 },

  // ── CIVIL ────────────────────────────────────────────────────────────
  { type_id: "shell",           category: "civil",   name: "Building Shell",        footprint_m: [100.0, 60.0], icon: "▭", phase: 1 },
  { type_id: "data_hall",       category: "civil",   name: "5 MW Data Hall",        footprint_m: [80.0, 40.0],  icon: "▭", phase: 1 },
  { type_id: "office",          category: "civil",   name: "Office Block",          footprint_m: [30.0, 15.0],  icon: "◻", phase: 1 },
  { type_id: "gatehouse",       category: "civil",   name: "Gatehouse",             footprint_m: [6.0, 4.0],    icon: "▣", phase: 1 },
  { type_id: "loading_bay",     category: "civil",   name: "Loading Bay",           footprint_m: [18.0, 10.0],  icon: "▢", phase: 1 },

  // ── GRID ─────────────────────────────────────────────────────────────
  { type_id: "substation_icon", category: "grid",    name: "Substation",            footprint_m: [40.0, 30.0],  icon: "⬢", phase: 2 },
  { type_id: "cable_route",     category: "grid",    name: "Cable Route Marker",    footprint_m: [2.0, 2.0],    icon: "—", phase: 2 },
  { type_id: "poc_point",       category: "grid",    name: "Point of Connection",   footprint_m: [3.0, 3.0],    icon: "◉", phase: 3 },

  // ── SAFETY ───────────────────────────────────────────────────────────
  { type_id: "fire_pump",       category: "safety",  name: "Fire Pump Room",        footprint_m: [8.0, 6.0],    icon: "▣", phase: 2 },
  { type_id: "spill_container", category: "safety",  name: "Spill Containment",     footprint_m: [10.0, 5.0],   icon: "◇", phase: 1 },
];

const CATEGORY_LABELS = {
  power:   { label: "Power",   hint: "Batteries, inverters, transformers" },
  cooling: { label: "Cooling", hint: "Chillers, towers, CRACs" },
  civil:   { label: "Civil",   hint: "Shell, halls, gatehouse" },
  grid:    { label: "Grid",    hint: "Substations, cable routes, POC" },
  safety:  { label: "Safety",  hint: "Fire pumps, containment" },
};

export default function EquipmentPalette({
  collapsed = false,
  onToggle = () => {},
  onDragStart = () => {},
  highlightTypeIds = [],      // for scale-chip hover — pulse matching items
}) {
  const [openCat, setOpenCat] = useState("power");

  const byCategory = useMemo(() => {
    const out = {};
    for (const it of EQUIPMENT_CATALOGUE) {
      if (!out[it.category]) out[it.category] = [];
      out[it.category].push(it);
    }
    return out;
  }, []);

  const handleDragStart = (e, item) => {
    try {
      e.dataTransfer.setData("application/x-princeps-equipment", JSON.stringify(item));
    } catch { /* some browsers block custom mime — fall through */ }
    e.dataTransfer.setData("text/plain", `equipment:${item.type_id}`);
    e.dataTransfer.effectAllowed = "copy";
    onDragStart(item);
  };

  if (collapsed) {
    return (
      <div className="dc-palette dc-palette-collapsed" aria-label="Equipment palette (collapsed)">
        <button className="dc-palette-handle" onClick={onToggle} title="Open equipment palette">▸</button>
      </div>
    );
  }

  return (
    <div className="dc-palette" role="complementary" aria-label="Equipment palette">
      <div className="dc-palette-head">
        <span className="dc-palette-title">Equipment</span>
        <button className="dc-palette-close" onClick={onToggle} title="Collapse">◂</button>
      </div>

      {Object.keys(CATEGORY_LABELS).map((cat) => {
        const items = byCategory[cat] || [];
        const isOpen = openCat === cat;
        return (
          <div key={cat} className={"dc-palette-cat" + (isOpen ? " dc-palette-cat-open" : "")}>
            <button
              className="dc-palette-cat-head"
              onClick={() => setOpenCat(isOpen ? null : cat)}
              title={CATEGORY_LABELS[cat].hint}
            >
              <span className="dc-palette-cat-chev">{isOpen ? "▾" : "▸"}</span>
              <span className="dc-palette-cat-label">{CATEGORY_LABELS[cat].label}</span>
              <span className="dc-palette-cat-count">{items.length}</span>
            </button>

            {isOpen && (
              <div className="dc-palette-items">
                {items.map((it) => {
                  const pulsing = highlightTypeIds.includes(it.type_id);
                  return (
                    <div
                      key={it.type_id}
                      className={"dc-palette-item" + (pulsing ? " dc-palette-item-pulse" : "")}
                      draggable
                      onDragStart={(e) => handleDragStart(e, it)}
                      title={`${it.name} — drag to place (${it.footprint_m[0]}×${it.footprint_m[1]} m)`}
                    >
                      <span className="dc-palette-item-icon" aria-hidden>{it.icon}</span>
                      <span className="dc-palette-item-body">
                        <span className="dc-palette-item-name">{it.name}</span>
                        <span className="dc-palette-item-dims">
                          {it.footprint_m[0]} × {it.footprint_m[1]} m
                        </span>
                      </span>
                      <span className="dc-palette-item-grab" aria-hidden>⋮⋮</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      <div className="dc-palette-foot">
        <span className="dc-palette-foot-hint">Drag → drop on canvas</span>
      </div>
    </div>
  );
}
