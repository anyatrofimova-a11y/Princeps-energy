import React, { useState, useCallback, useMemo } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/* ── Constants ─────────────────────────────────────────────────────────── */
const VOLTAGE_OPTIONS = [
  { kv: 11,  label: "11 kV",  cost_per_km: 80,   capacity_mw: 6,   loss_pct: 3.5 },
  { kv: 33,  label: "33 kV",  cost_per_km: 150,   capacity_mw: 23,  loss_pct: 1.8 },
  { kv: 132, label: "132 kV", cost_per_km: 500,   capacity_mw: 180, loss_pct: 0.5 },
];

const TERRAIN_TYPES = [
  { id: "farmland", label: "Farmland", cost_mult: 1.0 },
  { id: "woodland", label: "Woodland", cost_mult: 1.4 },
  { id: "urban", label: "Urban", cost_mult: 1.8 },
  { id: "moorland", label: "Moorland", cost_mult: 1.1 },
  { id: "road_crossing", label: "Road Crossing", cost_each: 15000 },
  { id: "rail_crossing", label: "Rail Crossing", cost_each: 45000 },
  { id: "water_crossing", label: "Water Crossing", cost_each: 35000 },
];

/* ── Helpers ────────────────────────────────────────────────────────────── */
function fmtGbp(v) {
  if (v == null) return "--";
  if (v >= 1_000_000) return `\u00A3${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1000) return `\u00A3${(v / 1000).toFixed(0)}k`;
  return `\u00A3${v.toFixed(0)}`;
}
function fmtKm(v) { return v != null ? `${v.toFixed(2)} km` : "--"; }

/* ── SVG Route Map (schematic) ─────────────────────────────────────────── */
function RouteSchematic({ routes, selectedIdx = 0, width = 370, height = 180 }) {
  if (!routes?.length) return null;
  const pad = { l: 30, r: 30, t: 20, b: 20 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;

  const colors = ["var(--gold)", "#3b82f6", "#8b5cf6"];

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      {/* Start marker */}
      <circle cx={pad.l} cy={pad.t + h / 2} r={8} fill="var(--gold)" opacity={0.9} />
      <text x={pad.l} y={pad.t + h / 2 + 3} textAnchor="middle" fill="#fff" fontSize="8" fontWeight="700">S</text>
      <text x={pad.l} y={pad.t + h / 2 + 20} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="8">Site</text>

      {/* End marker */}
      <circle cx={pad.l + w} cy={pad.t + h / 2} r={8} fill="#16A34A" opacity={0.9} />
      <text x={pad.l + w} y={pad.t + h / 2 + 3} textAnchor="middle" fill="#fff" fontSize="8" fontWeight="700">G</text>
      <text x={pad.l + w} y={pad.t + h / 2 + 20} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="8">Grid</text>

      {/* Route paths */}
      {routes.map((route, i) => {
        const offset = (i - 1) * 18;
        const midX = pad.l + w * 0.5;
        const midY = pad.t + h / 2 + offset;
        const isActive = i === selectedIdx;
        return (
          <g key={i}>
            <path
              d={`M${pad.l + 10},${pad.t + h / 2} Q${midX},${midY} ${pad.l + w - 10},${pad.t + h / 2}`}
              fill="none" stroke={colors[i] || "#999"} strokeWidth={isActive ? 3 : 1.5}
              opacity={isActive ? 1 : 0.35} strokeDasharray={isActive ? "none" : "4,4"} />
            <text x={midX} y={midY - 6} textAnchor="middle" fill={colors[i] || "#999"}
              fontSize="8" fontWeight={isActive ? "700" : "400"}>
              {route.label} ({fmtKm(route.distance_km)})
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ── SVG Cost Breakdown Bar ────────────────────────────────────────────── */
function CostBreakdownBar({ items, width = 370, height = 160 }) {
  if (!items?.length) return null;
  const pad = { l: 100, r: 20, t: 8, b: 8 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const maxVal = Math.max(...items.map(i => i.cost || 0), 1);
  const barH = Math.min(18, (h - items.length * 4) / items.length);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      {items.map((item, i) => {
        const y = pad.t + i * (barH + 5);
        const barW = ((item.cost || 0) / maxVal) * w;
        return (
          <g key={i}>
            <text x={pad.l - 6} y={y + barH / 2 + 4} textAnchor="end" fill="var(--cds-text-secondary)" fontSize="9">{item.label}</text>
            <rect x={pad.l} y={y} width={Math.max(2, barW)} height={barH} rx={3} fill="var(--gold)" opacity={0.7} />
            <text x={pad.l + barW + 6} y={y + barH / 2 + 4} fill="var(--cds-text-primary)" fontSize="10"
              fontFamily="JetBrains Mono, monospace" fontWeight="600">{fmtGbp(item.cost)}</text>
          </g>
        );
      })}
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   CableRoutingPanel
   ═══════════════════════════════════════════════════════════════════════════ */
export default function CableRoutingPanel({ onClose }) {
  const { explain, selectedParcel, lat, lon } = useSite();
  const [activeTab, setActiveTab] = useState("route");

  // Route tab state
  const [voltageKv, setVoltageKv] = useState(33);
  const [avoidRoads, setAvoidRoads] = useState(false);
  const [avoidWater, setAvoidWater] = useState(true);
  const [avoidProtected, setAvoidProtected] = useState(true);
  const [maxSlope, setMaxSlope] = useState(15);
  const [routeResult, setRouteResult] = useState(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [selectedRoute, setSelectedRoute] = useState(0);

  const TABS = [
    { id: "route", label: "Route" },
    { id: "cost", label: "Cost" },
  ];

  const selectedVoltage = VOLTAGE_OPTIONS.find(v => v.kv === voltageKv) || VOLTAGE_OPTIONS[1];

  /* ── Find Route ── */
  const findRoute = useCallback(async () => {
    setRouteLoading(true);
    try {
      const data = await api.cableRouting.findRoute(
        lat || 52.0, lon || -1.5, voltageKv,
        { avoid_roads: avoidRoads, avoid_water: avoidWater, avoid_protected: avoidProtected, max_slope: maxSlope }
      );
      if (data) {
        setRouteResult(data);
      } else {
        // Synthetic result
        const baseDist = 3.2 + Math.random() * 4;
        const costPerKm = selectedVoltage.cost_per_km * 1000;
        const routes = [
          { label: "Optimal", distance_km: baseDist, cost: baseDist * costPerKm + 45000, terrain: "farmland" },
          { label: "Road-adjacent", distance_km: baseDist * 1.15, cost: baseDist * 1.15 * costPerKm * 1.1 + 60000, terrain: "mixed" },
          { label: "Direct", distance_km: baseDist * 0.85, cost: baseDist * 0.85 * costPerKm * 1.3 + 80000, terrain: "woodland" },
        ];
        setRouteResult({
          routes,
          waypoints: [
            { name: "Site boundary", dist_km: 0 },
            { name: "Field crossing A", dist_km: baseDist * 0.3 },
            { name: "Road crossing B507", dist_km: baseDist * 0.55 },
            { name: "Substation entry", dist_km: baseDist },
          ],
          cost_breakdown: [
            { label: "Cable supply", cost: baseDist * costPerKm * 0.45 },
            { label: "Civil works", cost: baseDist * costPerKm * 0.35 },
            { label: "Wayleaves", cost: 28000 + Math.random() * 15000 },
            { label: "Crossings", cost: 15000 + Math.random() * 30000 },
          ],
          nearest_substation: "Banbury 33/11kV",
        });
      }
    } catch { /* ignore */ }
    setRouteLoading(false);
  }, [lat, lon, voltageKv, avoidRoads, avoidWater, avoidProtected, maxSlope, selectedVoltage]);

  /* ── Cost tab segments (synthetic) ── */
  const segments = useMemo(() => {
    if (!routeResult?.routes?.[selectedRoute]) return [];
    const route = routeResult.routes[selectedRoute];
    const totalDist = route.distance_km;
    return [
      { segment: "Section A", length_km: totalDist * 0.35, terrain: "Farmland", cost_per_m: selectedVoltage.cost_per_km, total: totalDist * 0.35 * selectedVoltage.cost_per_km * 1000 },
      { segment: "Road Crossing", length_km: 0.02, terrain: "Road", cost_per_m: 750, total: 15000 },
      { segment: "Section B", length_km: totalDist * 0.4, terrain: "Farmland", cost_per_m: selectedVoltage.cost_per_km, total: totalDist * 0.4 * selectedVoltage.cost_per_km * 1000 },
      { segment: "Section C", length_km: totalDist * 0.23, terrain: "Woodland", cost_per_m: selectedVoltage.cost_per_km * 1.4, total: totalDist * 0.23 * selectedVoltage.cost_per_km * 1400 },
    ];
  }, [routeResult, selectedRoute, selectedVoltage]);

  return (
    <div className="gc-panel cr-panel">
      <div className="gc-panel-header">
        <div className="gc-panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="2"><path d="M2 12h4l3-9 4 18 3-9h6"/></svg>
          CABLE ROUTING
        </div>
        <button className="gc-panel-close" onClick={onClose}>&times;</button>
      </div>

      <div className="df-tabs" style={{ padding: "0 16px" }}>
        {TABS.map(t => (
          <button key={t.id} className={`df-tab ${activeTab === t.id ? "active" : ""}`}
            onClick={() => setActiveTab(t.id)}>{t.label}</button>
        ))}
      </div>

      <div className="gc-panel-body">
        {/* ──────── ROUTE TAB ──────── */}
        {activeTab === "route" && (
          <div className="cr-section">
            <div className="cr-sub-section">
              <div className="cr-sub-title">Connection Points</div>
              <div className="cr-endpoints">
                <div className="cr-endpoint">
                  <span className="cr-ep-dot cr-ep-start" />
                  <div>
                    <div className="cr-ep-label">Start: Site Location</div>
                    <div className="cr-ep-coord">{lat?.toFixed(4) || "52.0000"}, {lon?.toFixed(4) || "-1.5000"}</div>
                  </div>
                </div>
                <div className="cr-endpoint">
                  <span className="cr-ep-dot cr-ep-end" />
                  <div>
                    <div className="cr-ep-label">End: {routeResult?.nearest_substation || "Nearest Substation"}</div>
                    <div className="cr-ep-coord">Auto-detected</div>
                  </div>
                </div>
              </div>
            </div>

            <div className="cr-sub-section">
              <div className="cr-sub-title">Voltage</div>
              <div className="cr-voltage-grid">
                {VOLTAGE_OPTIONS.map(v => (
                  <button key={v.kv} className={`cr-voltage-btn${voltageKv === v.kv ? " active" : ""}`}
                    onClick={() => setVoltageKv(v.kv)}>
                    <div className="cr-v-label">{v.label}</div>
                    <div className="cr-v-detail">{v.capacity_mw} MW | {fmtGbp(v.cost_per_km * 1000)}/km</div>
                  </button>
                ))}
              </div>
            </div>

            <div className="cr-sub-section">
              <div className="cr-sub-title">Constraints</div>
              <div className="cr-constraints">
                <label className="cr-check"><input type="checkbox" checked={avoidRoads} onChange={e => setAvoidRoads(e.target.checked)} /> Avoid roads</label>
                <label className="cr-check"><input type="checkbox" checked={avoidWater} onChange={e => setAvoidWater(e.target.checked)} /> Avoid water crossings</label>
                <label className="cr-check"><input type="checkbox" checked={avoidProtected} onChange={e => setAvoidProtected(e.target.checked)} /> Avoid protected land</label>
                <div className="cr-slope-row">
                  <span className="cr-slope-label">Max slope</span>
                  <input type="range" min={5} max={30} step={1} value={maxSlope}
                    onChange={e => setMaxSlope(+e.target.value)} className="pf-slider" />
                  <span className="cr-slope-value">{maxSlope}%</span>
                </div>
              </div>
            </div>

            <button className="pf-action-btn" onClick={findRoute} disabled={routeLoading}>
              {routeLoading ? "Finding Route..." : "Find Route"}
            </button>

            {routeResult && (
              <>
                <div className="cr-sub-section">
                  <div className="cr-sub-title">Route Options</div>
                  <RouteSchematic routes={routeResult.routes} selectedIdx={selectedRoute} />
                  <div className="cr-route-list">
                    {routeResult.routes.map((r, i) => (
                      <div key={i} className={`cr-route-card${selectedRoute === i ? " active" : ""}`}
                        onClick={() => setSelectedRoute(i)}>
                        <div className="cr-route-rank">#{i + 1}</div>
                        <div className="cr-route-info">
                          <div className="cr-route-label">{r.label}</div>
                          <div className="cr-route-meta">{fmtKm(r.distance_km)} | {r.terrain}</div>
                        </div>
                        <div className="cr-route-cost">{fmtGbp(r.cost)}</div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="cr-sub-section">
                  <div className="cr-sub-title">Cost Breakdown</div>
                  <CostBreakdownBar items={routeResult.cost_breakdown} />
                </div>

                <div className="cr-sub-section">
                  <div className="cr-sub-title">Waypoints</div>
                  <div className="cr-waypoints">
                    {routeResult.waypoints.map((wp, i) => (
                      <div key={i} className="cr-waypoint">
                        <span className="cr-wp-num">{i + 1}</span>
                        <span className="cr-wp-name">{wp.name}</span>
                        <span className="cr-wp-dist">{fmtKm(wp.dist_km)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ──────── COST TAB ──────── */}
        {activeTab === "cost" && (
          <div className="cr-section">
            {!routeResult ? (
              <div className="cr-empty">Run a route analysis first to see detailed costs.</div>
            ) : (
              <>
                <div className="cr-sub-section">
                  <div className="cr-sub-title">Per-Segment Breakdown</div>
                  <div className="cr-segment-table">
                    <div className="cr-seg-header">
                      <span>Segment</span><span>Length</span><span>Terrain</span><span>Cost/m</span><span>Total</span>
                    </div>
                    {segments.map((s, i) => (
                      <div key={i} className="cr-seg-row">
                        <span className="cr-seg-name">{s.segment}</span>
                        <span className="cr-seg-mono">{(s.length_km * 1000).toFixed(0)}m</span>
                        <span className="cr-seg-terrain">{s.terrain}</span>
                        <span className="cr-seg-mono">{fmtGbp(s.cost_per_m)}/m</span>
                        <span className="cr-seg-mono cr-seg-total">{fmtGbp(s.total)}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="cr-sub-section">
                  <div className="cr-sub-title">Crossing Costs</div>
                  <div className="cr-crossing-list">
                    <div className="cr-crossing-row"><span>Road crossings (x1)</span><span className="cr-seg-mono">{fmtGbp(15000)}</span></div>
                    <div className="cr-crossing-row"><span>Rail crossings (x0)</span><span className="cr-seg-mono">{fmtGbp(0)}</span></div>
                    <div className="cr-crossing-row"><span>Water crossings (x0)</span><span className="cr-seg-mono">{fmtGbp(0)}</span></div>
                  </div>
                </div>

                <div className="cr-sub-section">
                  <div className="cr-sub-title">Wayleave Estimate</div>
                  <div className="cr-wayleave-box">
                    <span className="cr-wayleave-val">{fmtGbp(routeResult.cost_breakdown?.find(c => c.label === "Wayleaves")?.cost || 28000)}</span>
                    <span className="cr-wayleave-note">Based on {routeResult.routes?.[selectedRoute]?.distance_km?.toFixed(1) || "3.2"} km route through agricultural land</span>
                  </div>
                </div>

                <div className="cr-sub-section">
                  <div className="cr-sub-title">Total Cable Cost (P10/P50/P90)</div>
                  {(() => {
                    const base = routeResult.routes?.[selectedRoute]?.cost || 500000;
                    return (
                      <div className="cr-prange">
                        <div className="cr-prange-row"><span className="cr-p-label">P10 (optimistic)</span><span className="cr-p-val">{fmtGbp(base * 0.82)}</span></div>
                        <div className="cr-prange-row cr-p-main"><span className="cr-p-label">P50 (central)</span><span className="cr-p-val">{fmtGbp(base)}</span></div>
                        <div className="cr-prange-row"><span className="cr-p-label">P90 (conservative)</span><span className="cr-p-val">{fmtGbp(base * 1.28)}</span></div>
                      </div>
                    );
                  })()}
                </div>

                <div className="cr-sub-section">
                  <div className="cr-sub-title">Voltage Comparison</div>
                  <div className="cr-voltage-compare">
                    <div className="cr-vc-header">
                      <span></span><span>11 kV</span><span>33 kV</span><span>132 kV</span>
                    </div>
                    <div className="cr-vc-row">
                      <span>Cost/km</span>
                      {VOLTAGE_OPTIONS.map(v => <span key={v.kv} className={`cr-vc-val${v.kv === voltageKv ? " cr-vc-active" : ""}`}>{fmtGbp(v.cost_per_km * 1000)}</span>)}
                    </div>
                    <div className="cr-vc-row">
                      <span>Losses</span>
                      {VOLTAGE_OPTIONS.map(v => <span key={v.kv} className={`cr-vc-val${v.kv === voltageKv ? " cr-vc-active" : ""}`}>{v.loss_pct}%</span>)}
                    </div>
                    <div className="cr-vc-row">
                      <span>Capacity</span>
                      {VOLTAGE_OPTIONS.map(v => <span key={v.kv} className={`cr-vc-val${v.kv === voltageKv ? " cr-vc-active" : ""}`}>{v.capacity_mw} MW</span>)}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
