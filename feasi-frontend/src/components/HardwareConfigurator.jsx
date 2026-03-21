import React, { useState, useEffect, useCallback } from "react";
import { useSite } from "../SiteContext";

const SITE_TYPES = [
  { value: "solar_farm", label: "Solar Farm" },
  { value: "bess", label: "Battery Storage" },
  { value: "wind_farm", label: "Wind Farm" },
  { value: "substation", label: "Substation" },
  { value: "met_mast", label: "Met Station" },
];

const CATEGORY_ICONS = {
  irradiance: "\u2600",    // ☀
  weather: "\u2601",       // ☁
  power_meter: "\u26A1",   // ⚡
  string_monitor: "\u25A3",// ▣
  environmental: "\u2618", // ☘
  thermal: "\u2668",       // ♨
  gateway: "\u25C8",       // ◈
  connectivity: "\u25CE",  // ◎
  power_supply: "\u25A0",  // ■
};

const CATEGORY_COLORS = {
  irradiance: "#f59e0b",
  weather: "#3b82f6",
  power_meter: "#10b981",
  string_monitor: "#8b5cf6",
  environmental: "#22c55e",
  thermal: "#ef4444",
  gateway: "#6366f1",
  connectivity: "#06b6d4",
  power_supply: "#78716c",
};

function fmtGbp(val) {
  if (val == null) return "--";
  if (val >= 1_000_000) return `\u00A3${(val / 1_000_000).toFixed(1)}M`;
  if (val >= 1000) return `\u00A3${Math.round(val / 1000)}k`;
  return `\u00A3${val}`;
}

function ModuleCard({ mod, qty, onAdd, onRemove, expanded, onToggle }) {
  const color = CATEGORY_COLORS[mod.category] || "#888";
  const icon = CATEGORY_ICONS[mod.category] || "\u25CF";

  return (
    <div style={{
      background: "var(--cds-layer-01, #262626)",
      borderRadius: 8,
      border: qty > 0 ? `1.5px solid ${color}` : "1.5px solid var(--cds-border-subtle, #393939)",
      padding: "10px 12px",
      marginBottom: 6,
      transition: "border-color 0.2s",
    }}>
      {/* Module header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}
           onClick={onToggle}>
        <div style={{
          width: 28, height: 28, borderRadius: 6,
          background: `${color}22`, color, display: "flex",
          alignItems: "center", justifyContent: "center",
          fontSize: 14, fontWeight: 700, flexShrink: 0,
        }}>{icon}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--cds-text-primary, #f4f4f4)", lineHeight: 1.3 }}>
            {mod.name}
          </div>
          <div style={{ fontSize: 10, color: "var(--cds-text-secondary, #c6c6c6)", marginTop: 1 }}>
            {mod.role || mod.measurement || mod.category}
          </div>
        </div>
        <div style={{ fontSize: 12, color: "var(--cds-text-secondary, #c6c6c6)", fontWeight: 500, minWidth: 50, textAlign: "right" }}>
          {fmtGbp(mod.unit_cost_gbp)}
        </div>
        {/* Qty controls */}
        <div style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: 4 }}>
          <button onClick={e => { e.stopPropagation(); onRemove(); }}
                  disabled={qty <= 0}
                  style={{
                    width: 22, height: 22, borderRadius: 4, border: "none",
                    background: qty > 0 ? "#da1e2830" : "transparent",
                    color: qty > 0 ? "#da1e28" : "#525252",
                    cursor: qty > 0 ? "pointer" : "default",
                    fontSize: 14, fontWeight: 700, display: "flex",
                    alignItems: "center", justifyContent: "center",
                  }}>&minus;</button>
          <div style={{
            width: 24, textAlign: "center", fontSize: 13, fontWeight: 700,
            color: qty > 0 ? color : "var(--cds-text-secondary, #c6c6c6)",
          }}>{qty}</div>
          <button onClick={e => { e.stopPropagation(); onAdd(); }}
                  style={{
                    width: 22, height: 22, borderRadius: 4, border: "none",
                    background: `${color}30`, color,
                    cursor: "pointer", fontSize: 14, fontWeight: 700,
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>+</button>
        </div>
      </div>
      {/* Expanded details */}
      {expanded && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--cds-border-subtle, #393939)" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 12px", fontSize: 10 }}>
            {mod.accuracy && <Detail label="Accuracy" value={mod.accuracy} />}
            {mod.interface && <Detail label="Interface" value={mod.interface} />}
            {mod.ip_rating && <Detail label="IP Rating" value={mod.ip_rating} />}
            {mod.operating_temp && <Detail label="Temp Range" value={mod.operating_temp} />}
            {mod.measurement && <Detail label="Measures" value={mod.measurement} />}
            {mod.range && <Detail label="Range" value={mod.range} />}
            {mod.power_w != null && <Detail label="Power" value={`${mod.power_w}W`} />}
            {mod.weight_kg != null && <Detail label="Weight" value={`${mod.weight_kg}kg`} />}
          </div>
          {mod.description && (
            <div style={{ fontSize: 10, color: "var(--cds-text-helper, #a8a8a8)", marginTop: 6, lineHeight: 1.4 }}>
              {mod.description}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Detail({ label, value }) {
  return (
    <div>
      <span style={{ color: "var(--cds-text-helper, #a8a8a8)" }}>{label}: </span>
      <span style={{ color: "var(--cds-text-primary, #f4f4f4)", fontWeight: 500 }}>{value}</span>
    </div>
  );
}

function WiringDiagram({ wiring }) {
  if (!wiring) return null;
  const { interfaces, total_analog_channels, total_modbus_devices, total_sdi12_devices } = wiring;
  return (
    <div style={{ padding: "8px 0" }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--cds-text-primary, #f4f4f4)", marginBottom: 6 }}>
        Connectivity Summary
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {Object.entries(interfaces || {}).map(([proto, count]) => (
          <div key={proto} style={{
            background: "var(--cds-layer-02, #393939)", borderRadius: 4,
            padding: "3px 8px", fontSize: 10, color: "var(--cds-text-secondary, #c6c6c6)",
          }}>
            <span style={{ fontWeight: 600, color: "var(--cds-text-primary, #f4f4f4)" }}>{count}x</span> {proto}
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 12, marginTop: 8, fontSize: 10, color: "var(--cds-text-secondary, #c6c6c6)" }}>
        {total_analog_channels > 0 && <span>Analog: {total_analog_channels}ch</span>}
        {total_modbus_devices > 0 && <span>Modbus: {total_modbus_devices} dev</span>}
        {total_sdi12_devices > 0 && <span>SDI-12: {total_sdi12_devices} dev</span>}
      </div>
    </div>
  );
}

function MqttTopics({ topics }) {
  if (!topics?.length) return null;
  return (
    <div style={{ padding: "8px 0" }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--cds-text-primary, #f4f4f4)", marginBottom: 6 }}>
        MQTT Topics
      </div>
      {topics.map((t, i) => (
        <div key={i} style={{ display: "flex", gap: 8, marginBottom: 3, fontSize: 10 }}>
          <code style={{
            background: "var(--cds-layer-02, #393939)", borderRadius: 3,
            padding: "1px 6px", color: "#78a9ff", fontFamily: "monospace", fontSize: 9,
            whiteSpace: "nowrap",
          }}>{t.topic}</code>
          <span style={{ color: "var(--cds-text-secondary, #c6c6c6)", flex: 1 }}>{t.purpose}</span>
          <span style={{ color: "var(--cds-text-helper, #a8a8a8)", fontSize: 9 }}>QoS {t.qos}</span>
        </div>
      ))}
    </div>
  );
}

function ComplianceNotes({ notes }) {
  if (!notes?.length) return null;
  return (
    <div style={{ padding: "8px 0" }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--cds-text-primary, #f4f4f4)", marginBottom: 6 }}>
        Compliance & Standards
      </div>
      {notes.map((n, i) => (
        <div key={i} style={{ fontSize: 10, color: "var(--cds-text-secondary, #c6c6c6)", marginBottom: 3, paddingLeft: 10, position: "relative" }}>
          <span style={{ position: "absolute", left: 0, color: "var(--cds-text-helper, #a8a8a8)" }}>&bull;</span>
          {n}
        </div>
      ))}
    </div>
  );
}

export default function HardwareConfigurator({ onClose }) {
  const { samCapacity } = useSite();
  const [siteType, setSiteType] = useState("solar_farm");
  const [capacityMw, setCapacityMw] = useState(() => samCapacity ? samCapacity / 1000 : 5);
  const [includeOptional, setIncludeOptional] = useState(false);
  const [kit, setKit] = useState(null);
  const [catalogue, setCatalogue] = useState([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("kit"); // kit | catalogue | wiring
  const [expandedModule, setExpandedModule] = useState(null);
  const [customQty, setCustomQty] = useState({}); // module_id -> qty override

  // Sync capacity from SAM
  useEffect(() => {
    if (samCapacity) setCapacityMw(samCapacity / 1000);
  }, [samCapacity]);

  // Fetch recommended kit
  const fetchKit = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        site_type: siteType,
        capacity_mw: capacityMw,
        include_optional: includeOptional,
      });
      const res = await fetch(`/hardware/recommend?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setKit(data);
      // Initialize custom quantities
      const qtyMap = {};
      for (const m of data.modules || []) {
        qtyMap[m.module_id] = m.qty;
      }
      setCustomQty(qtyMap);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [siteType, capacityMw, includeOptional]);

  // Fetch catalogue
  useEffect(() => {
    fetch("/hardware/catalogue")
      .then(r => r.json())
      .then(d => setCatalogue(d))
      .catch(console.error);
  }, []);

  // Auto-fetch kit on mount
  useEffect(() => { fetchKit(); }, [fetchKit]);

  // Adjust quantity
  const adjustQty = (moduleId, delta) => {
    setCustomQty(prev => {
      const next = { ...prev };
      const current = next[moduleId] || 0;
      next[moduleId] = Math.max(0, current + delta);
      return next;
    });
  };

  // Compute totals from custom quantities
  const computeTotals = () => {
    if (!kit?.modules) return { cost: 0, power: 0, weight: 0, count: 0 };
    let cost = 0, power = 0, weight = 0, count = 0;
    for (const m of kit.modules) {
      const qty = customQty[m.module_id] ?? m.qty;
      cost += qty * m.unit_cost_gbp;
      count += qty;
      // Approximate power/weight from catalogue
      const cat = catalogue.find(c => c.id === m.module_id);
      if (cat) {
        power += qty * (cat.power_w || 0);
        weight += qty * (cat.weight_kg || 0);
      }
    }
    return { cost, power: Math.round(power * 10) / 10, weight: Math.round(weight * 10) / 10, count };
  };

  const totals = computeTotals();

  // Add module from catalogue
  const addFromCatalogue = (moduleId) => {
    // If module already in kit, increment
    if (customQty[moduleId] != null) {
      adjustQty(moduleId, 1);
      return;
    }
    // Otherwise add to kit
    const catMod = catalogue.find(c => c.id === moduleId);
    if (!catMod || !kit) return;
    setCustomQty(prev => ({ ...prev, [moduleId]: 1 }));
    setKit(prev => ({
      ...prev,
      modules: [...prev.modules, {
        module_id: catMod.id,
        name: catMod.name,
        category: catMod.category,
        qty: 1,
        unit_cost_gbp: catMod.unit_cost_gbp,
        line_cost_gbp: catMod.unit_cost_gbp,
        interface: catMod.interface,
        role: "User-added",
        optional: false,
        measurement: catMod.measurement || "",
        accuracy: catMod.accuracy || "",
        ip_rating: catMod.ip_rating || "",
      }],
    }));
    setActiveTab("kit");
  };

  return (
    <div style={{
      position: "fixed", top: 0, right: 0, bottom: 0,
      width: 420, background: "var(--cds-background, #161616)",
      borderLeft: "1px solid var(--cds-border-subtle, #393939)",
      display: "flex", flexDirection: "column",
      zIndex: 1200, boxShadow: "-4px 0 24px rgba(0,0,0,0.5)",
    }}>
      {/* Header */}
      <div style={{
        padding: "12px 16px", borderBottom: "1px solid var(--cds-border-subtle, #393939)",
        display: "flex", alignItems: "center", gap: 10, flexShrink: 0,
      }}>
        <div style={{
          width: 28, height: 28, borderRadius: 6,
          background: "#D4A01822", color: "#D4A018",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 14, fontWeight: 700,
        }}>{"\u25A3"}</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--cds-text-primary, #f4f4f4)" }}>
            Hardware Configurator
          </div>
          <div style={{ fontSize: 10, color: "var(--cds-text-secondary, #c6c6c6)" }}>
            Modular IoT monitoring kit builder
          </div>
        </div>
        <button onClick={onClose} style={{
          background: "none", border: "none", color: "var(--cds-text-secondary, #c6c6c6)",
          fontSize: 20, cursor: "pointer", padding: "0 4px",
        }}>&times;</button>
      </div>

      {/* Input bar */}
      <div style={{
        padding: "10px 16px", borderBottom: "1px solid var(--cds-border-subtle, #393939)",
        display: "flex", gap: 8, flexShrink: 0, alignItems: "end",
      }}>
        <div style={{ flex: 1 }}>
          <label style={{ fontSize: 10, color: "var(--cds-text-helper, #a8a8a8)", display: "block", marginBottom: 3 }}>
            Site Type
          </label>
          <select value={siteType} onChange={e => setSiteType(e.target.value)}
                  style={{
                    width: "100%", background: "var(--cds-layer-01, #262626)",
                    border: "1px solid var(--cds-border-subtle, #393939)",
                    borderRadius: 4, color: "var(--cds-text-primary, #f4f4f4)",
                    padding: "5px 8px", fontSize: 11,
                  }}>
            {SITE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
        <div style={{ width: 80 }}>
          <label style={{ fontSize: 10, color: "var(--cds-text-helper, #a8a8a8)", display: "block", marginBottom: 3 }}>
            MW
          </label>
          <input type="number" value={capacityMw} min={0.01} step={0.5}
                 onChange={e => setCapacityMw(+e.target.value)}
                 style={{
                   width: "100%", background: "var(--cds-layer-01, #262626)",
                   border: "1px solid var(--cds-border-subtle, #393939)",
                   borderRadius: 4, color: "var(--cds-text-primary, #f4f4f4)",
                   padding: "5px 8px", fontSize: 11,
                 }} />
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: "var(--cds-text-secondary, #c6c6c6)", cursor: "pointer", whiteSpace: "nowrap", paddingBottom: 2 }}>
          <input type="checkbox" checked={includeOptional} onChange={e => setIncludeOptional(e.target.checked)} />
          Optional
        </label>
      </div>

      {/* Summary strip */}
      {kit && (
        <div style={{
          padding: "8px 16px", borderBottom: "1px solid var(--cds-border-subtle, #393939)",
          display: "flex", gap: 16, flexShrink: 0,
          background: "var(--cds-layer-01, #262626)",
        }}>
          <Stat label="Modules" value={totals.count} />
          <Stat label="Total Cost" value={fmtGbp(totals.cost)} accent />
          <Stat label="Power" value={`${totals.power}W`} />
          <Stat label="Weight" value={`${totals.weight}kg`} />
        </div>
      )}

      {/* Tabs */}
      <div style={{
        display: "flex", borderBottom: "1px solid var(--cds-border-subtle, #393939)",
        flexShrink: 0,
      }}>
        {[
          { key: "kit", label: "Kit" },
          { key: "catalogue", label: "Catalogue" },
          { key: "wiring", label: "Wiring" },
        ].map(tab => (
          <button key={tab.key} onClick={() => setActiveTab(tab.key)}
                  style={{
                    flex: 1, padding: "8px 0", fontSize: 11, fontWeight: 600,
                    background: "none", border: "none", cursor: "pointer",
                    color: activeTab === tab.key ? "#D4A018" : "var(--cds-text-secondary, #c6c6c6)",
                    borderBottom: activeTab === tab.key ? "2px solid #D4A018" : "2px solid transparent",
                  }}>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflow: "auto", padding: "10px 16px" }}>
        {loading && (
          <div style={{ textAlign: "center", padding: 40, color: "var(--cds-text-secondary, #c6c6c6)", fontSize: 12 }}>
            Loading kit...
          </div>
        )}

        {/* Kit tab */}
        {activeTab === "kit" && kit && !loading && (
          <>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--cds-text-secondary, #c6c6c6)", marginBottom: 8 }}>
              {kit.kit_name} &mdash; {kit.capacity_mw} MW
            </div>
            {kit.modules?.map((m) => (
              <ModuleCard
                key={m.module_id}
                mod={m}
                qty={customQty[m.module_id] ?? m.qty}
                onAdd={() => adjustQty(m.module_id, 1)}
                onRemove={() => adjustQty(m.module_id, -1)}
                expanded={expandedModule === m.module_id}
                onToggle={() => setExpandedModule(expandedModule === m.module_id ? null : m.module_id)}
              />
            ))}

            {/* Compliance */}
            <ComplianceNotes notes={kit.compliance} />
          </>
        )}

        {/* Catalogue tab */}
        {activeTab === "catalogue" && (
          <>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--cds-text-secondary, #c6c6c6)", marginBottom: 8 }}>
              All Modules ({catalogue.length})
            </div>
            {catalogue.map(m => {
              const inKit = customQty[m.id] != null && customQty[m.id] > 0;
              return (
                <div key={m.id} style={{
                  background: "var(--cds-layer-01, #262626)",
                  borderRadius: 8,
                  border: inKit
                    ? `1.5px solid ${CATEGORY_COLORS[m.category] || "#888"}`
                    : "1.5px solid var(--cds-border-subtle, #393939)",
                  padding: "8px 12px",
                  marginBottom: 6,
                  cursor: "pointer",
                }} onClick={() => setExpandedModule(expandedModule === m.id ? null : m.id)}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{
                      width: 24, height: 24, borderRadius: 5,
                      background: `${CATEGORY_COLORS[m.category] || "#888"}22`,
                      color: CATEGORY_COLORS[m.category] || "#888",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 12, flexShrink: 0,
                    }}>{CATEGORY_ICONS[m.category] || "\u25CF"}</div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--cds-text-primary, #f4f4f4)" }}>
                        {m.name}
                      </div>
                      <div style={{ fontSize: 9, color: "var(--cds-text-secondary, #c6c6c6)" }}>
                        {m.category} &middot; {m.interface}
                      </div>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--cds-text-secondary, #c6c6c6)", fontWeight: 500, marginRight: 6 }}>
                      {fmtGbp(m.unit_cost_gbp)}
                    </div>
                    <button onClick={e => { e.stopPropagation(); addFromCatalogue(m.id); }}
                            style={{
                              background: inKit ? "#D4A01830" : "var(--cds-layer-02, #393939)",
                              border: "none", borderRadius: 4, color: inKit ? "#D4A018" : "var(--cds-text-secondary, #c6c6c6)",
                              padding: "3px 10px", fontSize: 10, fontWeight: 600, cursor: "pointer",
                            }}>
                      {inKit ? `${customQty[m.id]}x` : "+ Add"}
                    </button>
                  </div>
                  {expandedModule === m.id && (
                    <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--cds-border-subtle, #393939)" }}>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 12px", fontSize: 10 }}>
                        {m.accuracy && <Detail label="Accuracy" value={m.accuracy} />}
                        {m.ip_rating && <Detail label="IP Rating" value={m.ip_rating} />}
                        {m.operating_temp && <Detail label="Temp" value={m.operating_temp} />}
                        {m.measurement && <Detail label="Measures" value={m.measurement} />}
                        {m.power_w != null && <Detail label="Power" value={`${m.power_w}W`} />}
                        {m.weight_kg != null && <Detail label="Weight" value={`${m.weight_kg}kg`} />}
                      </div>
                      {m.description && (
                        <div style={{ fontSize: 10, color: "var(--cds-text-helper, #a8a8a8)", marginTop: 6 }}>
                          {m.description}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </>
        )}

        {/* Wiring tab */}
        {activeTab === "wiring" && kit && (
          <>
            <WiringDiagram wiring={kit.wiring} />
            <MqttTopics topics={kit.mqtt_topics} />
          </>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, accent }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{
        fontSize: 14, fontWeight: 700,
        color: accent ? "#D4A018" : "var(--cds-text-primary, #f4f4f4)",
      }}>{value}</div>
      <div style={{ fontSize: 9, color: "var(--cds-text-helper, #a8a8a8)", marginTop: 1 }}>{label}</div>
    </div>
  );
}
