/**
 * SmartOverlays — Proactive intelligence cards that auto-appear on the map.
 *
 * Unlike the reactive FloatingCards system (user must click an intent),
 * SmartOverlays detect opportunities, risks, and insights from live data
 * and surface them as floating cards WITHOUT user action.
 *
 * Triggers:
 * - Site picked → grid, environmental, landowner, planning insights
 * - Map idle → live market, constraint, pricing insights
 * - Periodic → BESS dispatch, carbon windows, price alerts
 *
 * This is what makes Princeps feel like a Bloomberg terminal for energy.
 */
import React, { useState, useEffect, useCallback, useRef } from "react";
import { useSite } from "../SiteContext";

const INSIGHT_ICONS = {
  grid: "GRD", environmental: "ENV", financial: "FIN", planning: "PLN",
  market: "MKT", constraint: "CST", opportunity: "OPP", warning: "WRN",
  land: "LND", carbon: "CO2", bess: "BES", queue: "QUE",
};

const SEVERITY_COLORS = {
  opportunity: "#16A34A",
  info: "#E8A012",
  warning: "#E8A012",
  critical: "#DC2626",
};

function InsightCard({ insight, onDismiss, onAction }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={`so-card so-${insight.severity}`}
      style={{ borderLeftColor: SEVERITY_COLORS[insight.severity] || "#F5B731" }}
    >
      <div className="so-card-header" onClick={() => setExpanded(!expanded)}>
        <span className="so-card-icon">{INSIGHT_ICONS[insight.category] || "💡"}</span>
        <div className="so-card-text">
          <div className="so-card-title">{insight.title}</div>
          <div className="so-card-subtitle">{insight.subtitle}</div>
        </div>
        <button className="so-dismiss" onClick={(e) => { e.stopPropagation(); onDismiss(insight.id); }}>×</button>
      </div>
      {expanded && insight.detail && (
        <div className="so-card-detail">
          {insight.detail}
          {insight.action && (
            <button className="so-action-btn" onClick={() => onAction(insight.action)}>
              {insight.action.label}
            </button>
          )}
        </div>
      )}
      {insight.metric && (
        <div className="so-card-metric">
          <span className="so-metric-value">
            {insight.metric.value}
          </span>
          <span className="so-metric-unit">{insight.metric.unit}</span>
        </div>
      )}
    </div>
  );
}

export default function SmartOverlays() {
  const { pickedLocation, layers } = useSite();
  const [insights, setInsights] = useState([]);
  const [dismissed, setDismissed] = useState(new Set());
  const fetchRef = useRef(null);
  const marketRef = useRef(null);

  const addInsight = useCallback((insight) => {
    setInsights(prev => {
      // Deduplicate by id
      if (prev.find(i => i.id === insight.id)) return prev;
      return [insight, ...prev].slice(0, 8); // Max 8 visible
    });
  }, []);

  const dismissInsight = useCallback((id) => {
    setDismissed(prev => new Set([...prev, id]));
    setInsights(prev => prev.filter(i => i.id !== id));
  }, []);

  // ── Site-triggered insights (when user picks a location) ──
  useEffect(() => {
    if (!pickedLocation) return;
    const { lat, lon } = pickedLocation;
    if (fetchRef.current) clearTimeout(fetchRef.current);

    fetchRef.current = setTimeout(async () => {
      // 1. Grid headroom check
      try {
        const r = await fetch(`/api/grid/assess?lat=${lat}&lon=${lon}&capacity_mw=5&technology=solar`, { method: "POST" });
        if (r.ok) {
          const d = await r.json();
          const sub = d.candidates?.[0] || d.nearest_substation;
          if (sub) {
            const headroom = sub.gen_headroom_mw || sub.headroom_mw;
            if (headroom > 0) {
              addInsight({
                id: `grid-headroom-${lat.toFixed(3)}`,
                category: "grid",
                severity: headroom > 20 ? "opportunity" : headroom > 5 ? "info" : "warning",
                title: `${headroom.toFixed(0)}MW headroom at ${sub.name || "nearest substation"}`,
                subtitle: `${(sub.distance_km || 0).toFixed(1)}km away · ${sub.voltage_kv || 33}kV · ${d.verdict || ""}`,
                detail: `Queue depth: ${sub.queue_depth || sub.ecr_queued || "unknown"} projects. Connection cost estimate: £${((d.connection_cost?.p50 || 0) / 1e6).toFixed(1)}M`,
                metric: { value: `${headroom.toFixed(0)}`, unit: "MW free" },
                action: { label: "Run full grid study", intent: "grid_study" },
              });
            }
          }
        }
      } catch {}

      // 2. Environmental constraints
      try {
        const r = await fetch(`/api/grid/environmental-constraints?lat=${lat}&lon=${lon}&radius_m=1000`);
        if (r.ok) {
          const d = await r.json();
          if (d.checks?.length > 0) {
            const hardCount = d.checks.filter(c => c.type === "hard").length;
            const softCount = d.checks.filter(c => c.type === "soft").length;
            addInsight({
              id: `env-${lat.toFixed(3)}`,
              category: "environmental",
              severity: hardCount > 0 ? "critical" : softCount > 2 ? "warning" : "info",
              title: hardCount > 0 ? `${hardCount} hard constraints detected` : `${d.checks.length} environmental factors`,
              subtitle: d.verdict || "Review environmental setting",
              detail: d.checks.slice(0, 3).map(c => `${c.designation || c.type}: ${c.name || ""} (${c.distance_m?.toFixed(0) || "?"}m)`).join("\n"),
              action: { label: "Run ESA scoping", intent: "environmental" },
            });
          }
        }
      } catch {}

      // 3. Land value estimate
      try {
        const r = await fetch(`/api/landowner/land-value?lat=${lat}&lon=${lon}&area_ha=5&land_type=agricultural`);
        if (r.ok) {
          const d = await r.json();
          addInsight({
            id: `land-${lat.toFixed(3)}`,
            category: "land",
            severity: "info",
            title: `Land value: £${(d.estimated_value_gbp?.mid / 1000).toFixed(0)}k (5ha ${d.land_type})`,
            subtitle: `${d.region} · Solar option: £${(d.solar_option?.annual_fee || 0).toLocaleString()}/yr`,
            metric: { value: `£${(d.per_acre_gbp?.mid / 1000).toFixed(0)}k`, unit: "/acre" },
          });
        }
      } catch {}

      // 4. ESA auto-scope cost
      try {
        const r = await fetch(`/api/esa/auto-scope?lat=${lat}&lon=${lon}&site_area_ha=5&proposed_use=solar_farm`, { method: "POST" });
        if (r.ok) {
          const d = await r.json();
          if (d.recommended_surveys?.length > 0) {
            addInsight({
              id: `esa-${lat.toFixed(3)}`,
              category: "planning",
              severity: d.overall_risk === "HIGH" ? "warning" : "info",
              title: `${d.recommended_surveys.length} surveys needed (£${(d.estimated_cost?.mid / 1000).toFixed(0)}k)`,
              subtitle: `Overall risk: ${d.overall_risk} · ${d.site?.district || ""}`,
              detail: d.recommended_surveys.slice(0, 4).map(s => `${s.name}: £${s.cost_mid.toLocaleString()}`).join("\n"),
              action: { label: "View full ESA scope", intent: "environmental" },
            });
          }
        }
      } catch {}
    }, 800); // Debounce 800ms after site pick

    return () => clearTimeout(fetchRef.current);
  }, [pickedLocation, addInsight]);

  // ── Market-triggered insights (periodic, every 60s) ──
  useEffect(() => {
    const checkMarket = async () => {
      try {
        const r = await fetch("/api/grid/live-status");
        if (!r.ok) return;
        const d = await r.json();

        // Price spike
        if (d.price_gbp_mwh > 100) {
          addInsight({
            id: "price-spike",
            category: "market",
            severity: d.price_gbp_mwh > 200 ? "critical" : "warning",
            title: `£${d.price_gbp_mwh.toFixed(0)}/MWh wholesale price spike`,
            subtitle: "Consider BESS discharge or load deferral",
            metric: { value: `£${d.price_gbp_mwh.toFixed(0)}`, unit: "/MWh" },
          });
        }

        // Low carbon window
        if (d.carbon_intensity && d.carbon_intensity < 100 && d.renewable_pct > 50) {
          addInsight({
            id: "carbon-low",
            category: "carbon",
            severity: "opportunity",
            title: `${d.carbon_intensity}g CO₂ · ${d.renewable_pct}% renewable`,
            subtitle: "Excellent window for energy-intensive operations",
            metric: { value: `${d.renewable_pct}%`, unit: "renewable" },
          });
        }

        // Frequency deviation
        if (d.frequency_hz && Math.abs(d.frequency_hz - 50) > 0.1) {
          addInsight({
            id: "freq-dev",
            category: "warning",
            severity: "critical",
            title: `Grid frequency: ${d.frequency_hz.toFixed(3)} Hz`,
            subtitle: `${Math.abs(d.frequency_hz - 50) > 0.15 ? "Significant" : "Minor"} deviation from 50Hz`,
            metric: { value: d.frequency_hz.toFixed(3), unit: "Hz" },
          });
        }
      } catch {}

      // BESS dispatch window
      try {
        const r = await fetch("/api/pricing/dispatch-window?hours_ahead=24");
        if (r.ok) {
          const d = await r.json();
          if (d.spread_gbp_mwh > 30) {
            addInsight({
              id: "bess-spread",
              category: "bess",
              severity: "opportunity",
              title: `BESS spread £${d.spread_gbp_mwh}/MWh today`,
              subtitle: `Charge: ${d.charge_window?.start?.slice(11, 16) || "?"} · Discharge: ${d.discharge_window?.start?.slice(11, 16) || "?"}`,
              detail: `Estimated revenue: £${(d.estimated_daily_revenue_100mw || 0).toLocaleString()}/day (100MW)`,
              metric: { value: `£${d.spread_gbp_mwh}`, unit: "spread" },
            });
          }
        }
      } catch {}

      // Constraint forecast
      try {
        const r = await fetch("/api/grid/constraints?hours_ahead=12");
        if (r.ok) {
          const d = await r.json();
          if (d.summary?.boundaries_at_risk > 0) {
            const worst = d.features?.sort((a, b) => b.properties.peak_constraint_prob - a.properties.peak_constraint_prob)[0];
            addInsight({
              id: "constraint-alert",
              category: "constraint",
              severity: d.summary.system_risk === "HIGH" ? "critical" : "warning",
              title: `${d.summary.boundaries_at_risk} constraint boundaries at risk`,
              subtitle: worst ? `${worst.properties.name}: ${worst.properties.peak_loading_pct}% loaded` : "",
              detail: `${d.summary.total_constrained_boundary_hours} constrained hours forecast in next 12h`,
              action: { label: "View constraint map", layer: "gridConstraints" },
            });
          }
        }
      } catch {}
    };

    checkMarket();
    marketRef.current = setInterval(checkMarket, 60_000);
    return () => clearInterval(marketRef.current);
  }, [addInsight]);

  // Filter dismissed
  const visible = insights.filter(i => !dismissed.has(i.id));

  if (visible.length === 0) return null;

  return (
    <div className="so-container">
      <div className="so-header">
        <span className="so-header-dot" />
        <span className="so-header-title">Intelligence</span>
        <span className="so-header-count">{visible.length}</span>
        {visible.length > 1 && (
          <button className="so-clear-all" onClick={() => visible.forEach(i => dismissInsight(i.id))}>
            Clear all
          </button>
        )}
      </div>
      <div className="so-cards">
        {visible.map(insight => (
          <InsightCard
            key={insight.id}
            insight={insight}
            onDismiss={dismissInsight}
            onAction={(action) => {
              if (action.intent) {
                // Trigger agent intent via custom event
                window.dispatchEvent(new CustomEvent("princeps-run-intent", { detail: { intent: action.intent } }));
              }
              if (action.layer) {
                // Toggle a map layer
                window.dispatchEvent(new CustomEvent("princeps-toggle-layer", { detail: { layer: action.layer } }));
              }
            }}
          />
        ))}
      </div>
    </div>
  );
}
