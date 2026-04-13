/**
 * DeveloperConsole — Palantir-inspired API explorer, ontology browser, and data inspector.
 *
 * Provides:
 *   - API endpoint browser with live testing (like Foundry's Developer Console)
 *   - Ontology object type viewer (like Foundry's Object Explorer)
 *   - Data table inspector with BlueprintJS Table
 *   - Real-time WebSocket monitor
 */
import React, { useState, useCallback, useEffect } from "react";
import { Button, InputGroup, HTMLSelect, Tag, Tabs, Tab, Card, Spinner, Icon, Callout } from "@blueprintjs/core";

/* ── API Catalog ─────────────────────────────────────────────────────── */
const API_CATALOG = [
  { group: "Grid", endpoints: [
    { method: "POST", path: "/api/grid/assess", params: ["lat", "lon", "capacity_mw", "technology"], desc: "Grid connection feasibility" },
    { method: "POST", path: "/api/grid/power-flow", params: ["lat", "lon", "capacity_mw"], desc: "Power flow simulation" },
    { method: "POST", path: "/api/grid/operating-envelope", params: ["lat", "lon", "capacity_mw"], desc: "Dynamic operating envelope" },
    { method: "POST", path: "/api/grid/connection-strategies", params: ["lat", "lon", "capacity_mw"], desc: "Firm vs flexible comparison" },
  ]},
  { group: "Analysis", endpoints: [
    { method: "POST", path: "/api/analysis/constraint-check", params: ["lat", "lon", "radius_km"], desc: "UK planning constraints" },
    { method: "POST", path: "/api/analysis/connectivity-score", params: ["lat", "lon"], desc: "Fiber & IXP connectivity" },
    { method: "POST", path: "/api/analysis/water-stress", params: ["lat", "lon"], desc: "Water stress assessment" },
    { method: "POST", path: "/api/analysis/cooling-strategy", params: ["it_load_mw", "lat", "lon"], desc: "DC cooling comparison" },
    { method: "POST", path: "/api/analysis/cfe-score", params: ["load_24h", "solar_24h"], desc: "24/7 CFE matching" },
    { method: "POST", path: "/api/analysis/optimize-system", params: ["land_area_ha", "load_profile_24h"], desc: "Multi-asset MILP optimizer" },
    { method: "POST", path: "/api/analysis/btm-dispatch", params: ["load_mw", "solar_mw", "bess_mwh"], desc: "BTM power dispatch" },
    { method: "POST", path: "/api/analysis/construction-timeline", params: ["project_type", "capacity_mw"], desc: "Construction timeline" },
    { method: "POST", path: "/api/analysis/construction-monte-carlo", params: ["project_type", "capacity_mw"], desc: "Monte Carlo schedule" },
    { method: "POST", path: "/api/analysis/supply-chain", params: ["project_type", "capacity_mw"], desc: "Supply chain assessment" },
  ]},
  { group: "Design", endpoints: [
    { method: "POST", path: "/api/design/auto-layout", params: ["type", "boundary"], desc: "Auto-generate site layout" },
    { method: "POST", path: "/api/design/buildable-area", params: ["boundary", "constraints"], desc: "Buildable area analysis" },
  ]},
  { group: "Parcels", endpoints: [
    { method: "POST", path: "/api/parcels/search", params: ["bbox", "min_area_ha"], desc: "Search parcels by criteria" },
    { method: "POST", path: "/api/parcels/score", params: ["lat", "lon", "area_ha"], desc: "Score a parcel" },
  ]},
  { group: "Regulatory", endpoints: [
    { method: "POST", path: "/api/regulatory/search", params: ["query"], desc: "Search regulatory docs" },
    { method: "POST", path: "/api/regulatory/ingest", params: ["url", "source", "doc_type"], desc: "Ingest a document" },
  ]},
  { group: "Countries", endpoints: [
    { method: "GET", path: "/api/analysis/countries", params: [], desc: "List supported countries" },
    { method: "GET", path: "/api/analysis/country/GB", params: [], desc: "UK adapter details" },
  ]},
];

/* ── Ontology Types ──────────────────────────────────────────────────── */
const ONTOLOGY = [
  { type: "Site", table: "parcels", icon: "map-marker", props: ["parcel_id", "boundary (geom)", "area_ha", "centroid", "alc_grade", "tenure"], links: ["→ GridSubstation (nearest)", "→ DNOBoundary (contains)", "→ PlanningApplication (overlaps)"] },
  { type: "GridSubstation", table: "grid_substations", icon: "flash", props: ["id", "name", "dno", "voltage_kv", "demand_mw", "generation_mw", "headroom_mw", "geom"], links: ["→ GridLine (connected)", "→ DNOBoundary (within)", "← Site (nearest)"] },
  { type: "GridLine", table: "grid_lines", icon: "horizontal-distribution", props: ["id", "voltage_kv", "from_sub", "to_sub", "length_km", "rating_mva", "geom"], links: ["→ GridSubstation (from)", "→ GridSubstation (to)"] },
  { type: "DemandForecast", table: "demand_forecasts", icon: "timeline-line-chart", props: ["gsp_id", "datetime", "demand_mw", "method", "scenario"], links: ["→ GSPProfile (gsp)"] },
  { type: "GeeFlowExtraction", table: "geeflow_extractions", icon: "satellite", props: ["id", "lat", "lon", "land_use", "ndvi", "slope", "solar_resource"], links: ["→ Site (location)"] },
  { type: "LegacyAsset", table: "legacy_assets", icon: "build", props: ["id", "name", "technology", "capacity_mw", "status", "commission_date"], links: ["→ Site (location)", "→ GridSubstation (connection)"] },
  { type: "RegulatoryDoc", table: "regulatory_docs", icon: "document", props: ["id", "url", "source", "doc_type", "title", "date", "chunk_text"], links: [] },
];

/* ── Styles ───────────────────────────────────────────────────────────── */
const S = {
  wrap: { position: "fixed", inset: 0, zIndex: 9999, display: "flex", flexDirection: "column", background: "#1C2127", color: "#F6F7F9", fontFamily: "'Inter', system-ui, sans-serif" },
  header: { display: "flex", alignItems: "center", gap: 12, padding: "10px 16px", borderBottom: "1px solid #383E47", background: "#111418" },
  title: { fontSize: 15, fontWeight: 700, color: "#D4A018", flex: 1 },
  body: { flex: 1, display: "flex", overflow: "hidden" },
  sidebar: { width: 240, borderRight: "1px solid #383E47", overflowY: "auto", padding: 8 },
  main: { flex: 1, overflowY: "auto", padding: 16 },
  groupTitle: { fontSize: 11, fontWeight: 700, color: "#ABB3BF", textTransform: "uppercase", letterSpacing: 1, padding: "12px 8px 4px", marginTop: 4 },
  ep: (sel) => ({ padding: "6px 10px", borderRadius: 4, cursor: "pointer", fontSize: 12, background: sel ? "rgba(212,160,24,0.15)" : "transparent", color: sel ? "#D4A018" : "#ABB3BF", display: "flex", alignItems: "center", gap: 6 }),
  method: (m) => ({ fontSize: 10, fontWeight: 700, color: m === "GET" ? "#3DCC91" : "#2B95D6", minWidth: 32 }),
  result: { background: "#111418", borderRadius: 6, padding: 12, marginTop: 12, maxHeight: 400, overflowY: "auto", fontSize: 12, fontFamily: "'IBM Plex Mono', monospace", whiteSpace: "pre-wrap", color: "#F6F7F9", border: "1px solid #383E47" },
};

/* ── API Tester ──────────────────────────────────────────────────────── */
function APITester({ endpoint }) {
  const [params, setParams] = useState({});
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(null);

  useEffect(() => {
    setParams({});
    setResult(null);
  }, [endpoint?.path]);

  const run = useCallback(async () => {
    if (!endpoint) return;
    setLoading(true);
    const t0 = performance.now();
    try {
      const qs = new URLSearchParams(params).toString();
      const url = endpoint.method === "GET" ? `${endpoint.path}${qs ? "?" + qs : ""}` : `${endpoint.path}?${qs}`;
      const opts = endpoint.method === "GET" ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params) };
      const r = await fetch(url, opts);
      const data = await r.json();
      setResult(data);
      setElapsed(Math.round(performance.now() - t0));
    } catch (e) {
      setResult({ error: e.message });
      setElapsed(Math.round(performance.now() - t0));
    }
    setLoading(false);
  }, [endpoint, params]);

  if (!endpoint) return <div style={{ color: "#5C7080", padding: 24 }}>Select an endpoint from the sidebar</div>;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <Tag intent={endpoint.method === "GET" ? "success" : "primary"} minimal>{endpoint.method}</Tag>
        <code style={{ fontSize: 14, color: "#D4A018" }}>{endpoint.path}</code>
      </div>
      <p style={{ fontSize: 12, color: "#ABB3BF", marginBottom: 12 }}>{endpoint.desc}</p>

      {endpoint.params.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
          {endpoint.params.map(p => (
            <InputGroup key={p} placeholder={p} value={params[p] || ""} onChange={e => setParams(prev => ({ ...prev, [p]: e.target.value }))}
              small fill style={{ fontFamily: "'IBM Plex Mono', monospace" }} />
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button intent="warning" icon="play" onClick={run} loading={loading} small>Execute</Button>
        {elapsed != null && <Tag minimal>{elapsed}ms</Tag>}
      </div>

      {result && (
        <div style={S.result}>
          {JSON.stringify(result, null, 2)}
        </div>
      )}
    </div>
  );
}

/* ── Ontology Browser ────────────────────────────────────────────────── */
function OntologyBrowser() {
  const [selected, setSelected] = useState(null);

  return (
    <div style={{ display: "flex", gap: 16 }}>
      <div style={{ width: 200 }}>
        {ONTOLOGY.map(obj => (
          <div key={obj.type} style={S.ep(selected?.type === obj.type)} onClick={() => setSelected(obj)}>
            <Icon icon={obj.icon} size={14} color={selected?.type === obj.type ? "#D4A018" : "#5C7080"} />
            <span>{obj.type}</span>
          </div>
        ))}
      </div>
      {selected && (
        <Card style={{ flex: 1, background: "#111418", color: "#F6F7F9" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <Icon icon={selected.icon} size={18} color="#D4A018" />
            <h3 style={{ margin: 0, fontSize: 16 }}>{selected.type}</h3>
            <Tag minimal>table: {selected.table}</Tag>
          </div>

          <h4 style={{ fontSize: 12, color: "#ABB3BF", margin: "12px 0 6px" }}>PROPERTIES</h4>
          {selected.props.map(p => (
            <div key={p} style={{ padding: "3px 0", fontSize: 12, fontFamily: "'IBM Plex Mono', monospace", color: "#F6F7F9" }}>{p}</div>
          ))}

          <h4 style={{ fontSize: 12, color: "#ABB3BF", margin: "12px 0 6px" }}>LINKS</h4>
          {selected.links.map(l => (
            <div key={l} style={{ padding: "3px 0", fontSize: 12, color: "#2B95D6" }}>{l}</div>
          ))}
        </Card>
      )}
    </div>
  );
}

/* ── Main Component ───────────────────────────────────────────────────── */
export default function DeveloperConsole({ onClose }) {
  const [selectedEndpoint, setSelectedEndpoint] = useState(null);
  const [activeTab, setActiveTab] = useState("api");

  return (
    <div style={S.wrap} className="bp5-dark">
      <div style={S.header}>
        <Icon icon="code" size={18} color="#D4A018" />
        <span style={S.title}>Developer Console</span>
        <Tag minimal intent="warning">Princeps API v2</Tag>
        <Button icon="cross" minimal onClick={onClose} />
      </div>

      <div style={{ padding: "0 16px", borderBottom: "1px solid #383E47" }}>
        <Tabs selectedTabId={activeTab} onChange={setActiveTab} animate={false}>
          <Tab id="api" title="API Explorer" icon="code-block" />
          <Tab id="ontology" title="Ontology" icon="data-connection" />
          <Tab id="ws" title="WebSocket" icon="pulse" />
        </Tabs>
      </div>

      {activeTab === "api" && (
        <div style={S.body}>
          <div style={S.sidebar}>
            {API_CATALOG.map(group => (
              <div key={group.group}>
                <div style={S.groupTitle}>{group.group}</div>
                {group.endpoints.map(ep => (
                  <div key={ep.path} style={S.ep(selectedEndpoint?.path === ep.path)} onClick={() => setSelectedEndpoint(ep)}>
                    <span style={S.method(ep.method)}>{ep.method}</span>
                    <span style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ep.path.replace("/api/", "")}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
          <div style={S.main}>
            <APITester endpoint={selectedEndpoint} />
          </div>
        </div>
      )}

      {activeTab === "ontology" && (
        <div style={S.main}>
          <Callout icon="info-sign" intent="primary" title="Princeps Ontology" style={{ marginBottom: 16 }}>
            Object types map to PostGIS tables. Links are computed via spatial queries and foreign keys.
          </Callout>
          <OntologyBrowser />
        </div>
      )}

      {activeTab === "ws" && (
        <div style={S.main}>
          <Callout icon="pulse" intent="success" title="WebSocket Feeds">
            <p>Active feeds:</p>
            <ul>
              <li><code>ws://host/ws/grid-twin</code> — Real-time grid state (5s updates)</li>
              <li><code>ws://host/ws/chat/{'{session_id}'}</code> — Chat streaming</li>
            </ul>
          </Callout>
        </div>
      )}
    </div>
  );
}
