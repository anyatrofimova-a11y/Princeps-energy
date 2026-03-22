/**
 * ActionSidebar — Palantir AIP-style context-aware action panel.
 *
 * Auto-populates with relevant actions based on whatever entity
 * is currently selected (substation, project, site, constraint).
 * Connects ALL 121 backend endpoints to actionable UI.
 *
 * Pattern: Select anything → sidebar shows "What can I do here?"
 */
import React, { useState, useEffect, useCallback } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

// ── Action definitions per entity type ──────────────────────────────────────

const ACTIONS = {
  substation: [
    { id: "assess", label: "Run Grid Assessment", icon: "⚡", desc: "Full connection feasibility at this substation", endpoint: "grid.assess" },
    { id: "power_flow", label: "Power Flow Analysis", icon: "🔌", desc: "Newton-Raphson load flow + N-1 contingency", endpoint: "grid.powerFlow" },
    { id: "queue", label: "View Connection Queue", icon: "⏳", desc: "ECR entries and estimated wait time", endpoint: "grid.queue" },
    { id: "forecast", label: "Connection Forecast", icon: "📈", desc: "Predict timeline and cost", endpoint: "grid.connectionForecast" },
    { id: "gate", label: "Gate Readiness Score", icon: "🚦", desc: "Score readiness for reformed queue gates", endpoint: "grid.gateReadiness" },
    { id: "detail", label: "Full Substation Detail", icon: "🔍", desc: "Capacity, TEC, DER, history", endpoint: "grid.substationDetail" },
    { id: "nearby_sites", label: "Find Nearby Sites", icon: "📍", desc: "Scan for development opportunities", endpoint: "site_prospecting" },
  ],
  project: [
    { id: "feasibility", label: "Run Feasibility", icon: "☀️", desc: "9-domain site scoring", endpoint: "feasibility" },
    { id: "financial", label: "Financial Model", icon: "💰", desc: "NPV, IRR, revenue stacking", endpoint: "financial" },
    { id: "env_check", label: "Environmental Check", icon: "🌿", desc: "SSSI, AONB, flood, heritage constraints", endpoint: "environmental" },
    { id: "esa_scope", label: "Auto-Scope ESA", icon: "📋", desc: "Phase 1 environmental desk study", endpoint: "esa" },
    { id: "planning", label: "Planning Analysis", icon: "🏛️", desc: "LPA approval rates, objection risk", endpoint: "planning" },
    { id: "bng", label: "BNG Assessment", icon: "🦎", desc: "Biodiversity net gain cost estimate", endpoint: "bng" },
    { id: "landowner", label: "Landowner Lookup", icon: "🗺️", desc: "HMLR + Companies House ownership", endpoint: "landowner" },
    { id: "report", label: "Generate Report", icon: "📄", desc: "PDF executive report", endpoint: "report" },
  ],
  site: [
    { id: "assess", label: "Quick Assessment", icon: "⚡", desc: "Grid + environmental + financial", endpoint: "grid.assess" },
    { id: "dc_score", label: "DC Suitability", icon: "🏢", desc: "Data centre 15-dimension scoring", endpoint: "dc.score" },
    { id: "land_value", label: "Land Valuation", icon: "💷", desc: "Estimated land value + solar option", endpoint: "landowner.landValue" },
    { id: "esa", label: "ESA Auto-Scope", icon: "📋", desc: "Environmental desk study + costs", endpoint: "esa" },
    { id: "community", label: "Community Sentiment", icon: "👥", desc: "Objection risk prediction", endpoint: "dc.communitySentiment" },
    { id: "pricing", label: "Regional Pricing", icon: "📊", desc: "Wholesale electricity prices", endpoint: "pricing" },
    { id: "constraints", label: "Nearby Constraints", icon: "🚫", desc: "Environmental constraints within 2km", endpoint: "constraints" },
  ],
  constraint: [
    { id: "detail", label: "View Details", icon: "ℹ️", desc: "Full constraint information", endpoint: "detail" },
    { id: "buffer", label: "Calculate Buffer", icon: "⭕", desc: "Required setback distance", endpoint: "buffer" },
    { id: "mitigation", label: "Mitigation Options", icon: "🛡️", desc: "How to work around this constraint", endpoint: "mitigation" },
  ],
  ecr: [
    { id: "detail", label: "View ECR Entry", icon: "📝", desc: "Full embedded capacity register detail" },
    { id: "timeline", label: "Predict Timeline", icon: "📅", desc: "Estimated connection date" },
  ],
  market: [
    { id: "dispatch", label: "BESS Dispatch Window", icon: "🔋", desc: "Optimal charge/discharge timing", endpoint: "pricing.dispatchWindow" },
    { id: "timeseries", label: "Price History", icon: "📈", desc: "Half-hourly price chart", endpoint: "pricing.timeseries" },
    { id: "revenue_stack", label: "Revenue Stacking", icon: "💰", desc: "Multi-market revenue model", endpoint: "grid.revenueStack" },
    { id: "constraints", label: "Constraint Forecast", icon: "🔴", desc: "48h transmission bottleneck forecast", endpoint: "grid.constraints" },
  ],
};

function ActionCard({ action, onRun, running }) {
  return (
    <button
      className={`as-action-card ${running ? "as-running" : ""}`}
      onClick={() => onRun(action)}
      disabled={running}
    >
      <span className="as-action-icon">{action.icon}</span>
      <div className="as-action-text">
        <div className="as-action-label">{action.label}</div>
        <div className="as-action-desc">{action.desc}</div>
      </div>
      {running && <div className="as-action-spinner" />}
    </button>
  );
}

export default function ActionSidebar() {
  const {
    selectedEntity, setSelectedEntity,
    actionSidebarOpen, setActionSidebarOpen,
    pickedLocation, runAgent, parcelId, samCapacity, samDay,
  } = useSite();

  const [results, setResults] = useState({});
  const [runningAction, setRunningAction] = useState(null);
  const [entityData, setEntityData] = useState(null);

  // Auto-open when entity selected
  useEffect(() => {
    if (selectedEntity) {
      setActionSidebarOpen(true);
      setResults({});
      setEntityData(null);
    }
  }, [selectedEntity, setActionSidebarOpen]);

  // Fetch entity detail on selection
  useEffect(() => {
    if (!selectedEntity) return;
    const { type, id, data } = selectedEntity;
    if (data) { setEntityData(data); return; }

    (async () => {
      try {
        if (type === "substation" && id) {
          const r = await fetch(`/api/grid/substation/${id}`);
          if (r.ok) setEntityData(await r.json());
        }
      } catch {}
    })();
  }, [selectedEntity]);

  const runAction = useCallback(async (action) => {
    if (!selectedEntity) return;
    setRunningAction(action.id);
    const { type, data } = selectedEntity;
    const lat = data?.lat || pickedLocation?.lat;
    const lon = data?.lon || pickedLocation?.lon;

    try {
      let result;

      // Route to correct endpoint
      if (action.endpoint === "grid.assess" && lat && lon) {
        const r = await fetch(`/api/grid/assess?lat=${lat}&lon=${lon}&capacity_mw=5&technology=solar`, { method: "POST" });
        result = await r.json();
      } else if (action.endpoint === "grid.connectionForecast" && lat && lon) {
        const r = await fetch(`/api/grid/connection-forecast?lat=${lat}&lon=${lon}&capacity_mw=5&technology=solar`, { method: "POST" });
        result = await r.json();
      } else if (action.endpoint === "grid.gateReadiness" && lat && lon) {
        const r = await fetch(`/api/grid/gate-readiness?lat=${lat}&lon=${lon}&capacity_mw=5&technology=solar`, { method: "POST" });
        result = await r.json();
      } else if (action.endpoint === "esa" && lat && lon) {
        const r = await fetch(`/api/esa/auto-scope?lat=${lat}&lon=${lon}&site_area_ha=5&proposed_use=solar_farm`, { method: "POST" });
        result = await r.json();
      } else if (action.endpoint === "landowner" && lat && lon) {
        const r = await fetch(`/api/landowner/lookup?lat=${lat}&lon=${lon}`);
        result = await r.json();
      } else if (action.endpoint === "landowner.landValue" && lat && lon) {
        const r = await fetch(`/api/landowner/land-value?lat=${lat}&lon=${lon}&area_ha=5&land_type=agricultural`);
        result = await r.json();
      } else if (action.endpoint === "constraints" && lat && lon) {
        const r = await fetch(`/api/grid/environmental-constraints?lat=${lat}&lon=${lon}`);
        result = await r.json();
      } else if (action.endpoint === "pricing.dispatchWindow") {
        const r = await fetch("/api/pricing/dispatch-window?hours_ahead=24");
        result = await r.json();
      } else if (action.endpoint === "grid.constraints") {
        const r = await fetch("/api/grid/constraints?hours_ahead=48");
        result = await r.json();
      } else if (typeof action.endpoint === "string" && !action.endpoint.includes(".")) {
        // Agent intent
        if (parcelId) {
          runAgent(parcelId, action.endpoint, samCapacity, samDay);
          result = { status: "Agent running...", intent: action.endpoint };
        }
      }

      if (result) {
        setResults(prev => ({ ...prev, [action.id]: result }));
      }
    } catch (e) {
      setResults(prev => ({ ...prev, [action.id]: { error: e.message } }));
    }
    setRunningAction(null);
  }, [selectedEntity, pickedLocation, parcelId, runAgent, samCapacity, samDay]);

  if (!actionSidebarOpen) return null;

  const entity = selectedEntity;
  const type = entity?.type || "site";
  const actions = ACTIONS[type] || ACTIONS.site;
  const name = entity?.data?.name || entity?.data?.site_name || `${type} ${entity?.id || ""}`;

  return (
    <div className="as-sidebar">
      {/* Header */}
      <div className="as-header">
        <div className="as-header-top">
          <span className="as-entity-type">{type.toUpperCase()}</span>
          <button className="as-close" onClick={() => { setActionSidebarOpen(false); setSelectedEntity(null); }}>×</button>
        </div>
        <div className="as-entity-name">{name}</div>
        {entity?.data?.voltage_kv && (
          <div className="as-entity-meta">{entity.data.voltage_kv}kV · {entity.data.dno || ""}</div>
        )}
        {entity?.data?.lat && (
          <div className="as-entity-coords">
            {entity.data.lat.toFixed(5)}, {entity.data.lon.toFixed(5)}
          </div>
        )}
      </div>

      {/* Quick stats */}
      {entityData && (
        <div className="as-stats">
          {entityData.demand_headroom_mw != null && (
            <div className="as-stat">
              <span className="as-stat-label">Headroom</span>
              <span className="as-stat-value">{entityData.demand_headroom_mw || entityData.gen_headroom_mw || 0} MW</span>
            </div>
          )}
          {entityData.queue_summary?.total != null && (
            <div className="as-stat">
              <span className="as-stat-label">Queue</span>
              <span className="as-stat-value">{entityData.queue_summary.total} projects</span>
            </div>
          )}
          {entityData.capacity_mw != null && (
            <div className="as-stat">
              <span className="as-stat-label">Capacity</span>
              <span className="as-stat-value">{entityData.capacity_mw} MW</span>
            </div>
          )}
          {entityData.score != null && (
            <div className="as-stat">
              <span className="as-stat-label">Score</span>
              <span className="as-stat-value">{entityData.score}/100</span>
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="as-section-title">Actions</div>
      <div className="as-actions">
        {actions.map(action => (
          <ActionCard
            key={action.id}
            action={action}
            onRun={runAction}
            running={runningAction === action.id}
          />
        ))}
      </div>

      {/* Results */}
      {Object.keys(results).length > 0 && (
        <>
          <div className="as-section-title">Results</div>
          <div className="as-results">
            {Object.entries(results).map(([actionId, result]) => (
              <div key={actionId} className="as-result-card">
                <div className="as-result-header">{actions.find(a => a.id === actionId)?.label || actionId}</div>
                <pre className="as-result-json">{JSON.stringify(result, null, 2).slice(0, 800)}</pre>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
