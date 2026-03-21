/**
 * DashboardBuilder — Pinnable KPI widget dashboard (Envision EnOS-style).
 *
 * Users can add/remove/reorder widgets showing live metrics from any
 * Princeps data source. Persists layout to localStorage.
 *
 * Widget types: kpi_card, sparkline, gauge, map_mini, table, chart
 */
import React, { useState, useEffect, useCallback } from "react";

const WIDGET_CATALOG = [
  { id: "grid_frequency", type: "kpi", label: "Grid Frequency", unit: "Hz", endpoint: "/api/grid/live-status", field: "frequency_hz", format: "fixed3", thresholds: { warn: [49.9, 50.1], crit: [49.8, 50.2] } },
  { id: "carbon_intensity", type: "kpi", label: "Carbon Intensity", unit: "gCO₂/kWh", endpoint: "/api/grid/live-status", field: "carbon_intensity", thresholds: { warn: [null, 200], crit: [null, 300] } },
  { id: "wholesale_price", type: "kpi", label: "Wholesale Price", unit: "£/MWh", endpoint: "/api/grid/live-status", field: "price_gbp_mwh", format: "fixed0", thresholds: { warn: [null, 100], crit: [null, 200] } },
  { id: "total_generation", type: "kpi", label: "GB Generation", unit: "GW", endpoint: "/api/grid/live-status", field: "total_generation_mw", format: "div1000", thresholds: {} },
  { id: "wind_generation", type: "kpi", label: "Wind Output", unit: "GW", endpoint: "/api/grid/live-status", field: "wind_mw", format: "div1000" },
  { id: "solar_generation", type: "kpi", label: "Solar Output", unit: "GW", endpoint: "/api/grid/live-status", field: "solar_mw", format: "div1000" },
  { id: "renewable_pct", type: "kpi", label: "Renewable %", unit: "%", endpoint: "/api/grid/live-status", field: "renewable_pct", format: "fixed1" },
  { id: "net_imports", type: "kpi", label: "Net Imports", unit: "GW", endpoint: "/api/grid/live-status", field: "net_imports_mw", format: "div1000" },
  { id: "constraint_risk", type: "kpi", label: "Constraint Risk", unit: "", endpoint: "/api/grid/constraints?hours_ahead=12", field: "summary.system_risk" },
  { id: "queue_depth", type: "kpi", label: "Queue Substations", unit: "", endpoint: "/api/grid/queue-depth", field: "features.length" },
];

function formatValue(val, fmt) {
  if (val == null) return "—";
  if (fmt === "fixed3") return Number(val).toFixed(3);
  if (fmt === "fixed1") return Number(val).toFixed(1);
  if (fmt === "fixed0") return Math.round(val);
  if (fmt === "div1000") return (Number(val) / 1000).toFixed(1);
  return String(val);
}

function getNestedField(obj, path) {
  return path.split(".").reduce((o, k) => {
    if (o == null) return null;
    if (k === "length" && Array.isArray(o)) return o.length;
    return o[k];
  }, obj);
}

function statusColor(val, thresholds) {
  if (!thresholds || !val) return "#D4A018";
  const { warn, crit } = thresholds;
  if (crit) {
    if (crit[0] != null && val < crit[0]) return "#f44336";
    if (crit[1] != null && val > crit[1]) return "#f44336";
  }
  if (warn) {
    if (warn[0] != null && val < warn[0]) return "#ff9800";
    if (warn[1] != null && val > warn[1]) return "#ff9800";
  }
  return "#4caf50";
}

function KPIWidget({ widget, onRemove }) {
  const [value, setValue] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      try {
        const r = await fetch(widget.endpoint);
        if (!r.ok) return;
        const d = await r.json();
        if (!cancelled) {
          setValue(getNestedField(d, widget.field));
          setLoading(false);
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    };
    fetchData();
    const id = setInterval(fetchData, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [widget.endpoint, widget.field]);

  const formatted = formatValue(value, widget.format);
  const color = statusColor(value, widget.thresholds);

  return (
    <div className="db-widget">
      <div className="db-widget-header">
        <span className="db-widget-label">{widget.label}</span>
        <button className="db-widget-remove" onClick={() => onRemove(widget.id)}>&times;</button>
      </div>
      <div className="db-widget-value" style={{ color }}>
        {loading ? "…" : formatted}
      </div>
      <div className="db-widget-unit">{widget.unit}</div>
    </div>
  );
}

const STORAGE_KEY = "princeps_dashboard_widgets";

export default function DashboardBuilder({ onClose }) {
  const [activeWidgets, setActiveWidgets] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved ? JSON.parse(saved) : ["grid_frequency", "carbon_intensity", "wholesale_price", "renewable_pct", "wind_generation", "solar_generation"];
    } catch { return ["grid_frequency", "carbon_intensity", "wholesale_price"]; }
  });
  const [addMenuOpen, setAddMenuOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(activeWidgets));
  }, [activeWidgets]);

  const addWidget = (id) => {
    if (!activeWidgets.includes(id)) {
      setActiveWidgets(prev => [...prev, id]);
    }
    setAddMenuOpen(false);
  };

  const removeWidget = (id) => {
    setActiveWidgets(prev => prev.filter(w => w !== id));
  };

  const available = WIDGET_CATALOG.filter(w => !activeWidgets.includes(w.id));

  return (
    <div className="db-overlay">
      <div className="db-header">
        <div className="db-header-left">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#D4A018" strokeWidth="2">
            <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
            <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
          </svg>
          <span className="db-title">Live Dashboard</span>
          <span className="db-subtitle">{activeWidgets.length} widgets</span>
        </div>
        <div className="db-header-right">
          <button className="db-add-btn" onClick={() => setAddMenuOpen(!addMenuOpen)}>
            + Add Widget
          </button>
          <button className="db-close" onClick={onClose}>&times;</button>
        </div>
      </div>

      {/* Add widget menu */}
      {addMenuOpen && (
        <div className="db-add-menu">
          {available.length === 0 && <div className="db-add-empty">All widgets added</div>}
          {available.map(w => (
            <button key={w.id} className="db-add-item" onClick={() => addWidget(w.id)}>
              <span>{w.label}</span>
              <span className="db-add-unit">{w.unit}</span>
            </button>
          ))}
        </div>
      )}

      {/* Widget grid */}
      <div className="db-grid">
        {activeWidgets.map(id => {
          const widget = WIDGET_CATALOG.find(w => w.id === id);
          if (!widget) return null;
          return <KPIWidget key={id} widget={widget} onRemove={removeWidget} />;
        })}
      </div>
    </div>
  );
}
