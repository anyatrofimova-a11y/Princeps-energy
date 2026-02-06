import React, { useState, useCallback } from "react";
import MapView from "./components/MapView";
import ThreeView from "./components/ThreeView";

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function Overlay({ id, title, open, onToggle, position, children, color = "#fff" }) {
  return (
    <div className={`overlay overlay-${position} ${open ? "open" : "closed"}`}>
      <div className="overlay-header" onClick={() => onToggle(id)} style={{ borderLeftColor: color }}>
        <span className="overlay-title">{title}</span>
        <span className="overlay-toggle">{open ? "\u25B2" : "\u25BC"}</span>
      </div>
      {open && <div className="overlay-body">{children}</div>}
    </div>
  );
}

export default function App() {
  const [parcelId, setParcelId] = useState("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
  const [heightmap, setHeightmap] = useState(null);
  const [explain, setExplain] = useState(null);
  const [slopeStats, setSlopeStats] = useState(null);
  const [solarYield, setSolarYield] = useState(null);
  const [solarHourly, setSolarHourly] = useState(null);
  const [mlSolar, setMlSolar] = useState(null);
  const [deferral, setDeferral] = useState(null);
  const [agentResult, setAgentResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [agentLoading, setAgentLoading] = useState(false);

  const [samCapacity, setSamCapacity] = useState(100);
  const [samDay, setSamDay] = useState(172);
  const [loadMw, setLoadMw] = useState(5);
  const [genMw, setGenMw] = useState(4);
  const [slopeOpacity, setSlopeOpacity] = useState(0.6);

  // Overlay panel visibility
  const [panels, setPanels] = useState({
    score: true, solar: false, terrain: false, agent: false, deferral: false,
  });
  const togglePanel = useCallback((id) => {
    setPanels(p => ({ ...p, [id]: !p[id] }));
  }, []);

  // Layer visibility
  const [layers, setLayers] = useState({
    slope: true, carbon: false, la: false, transport: false, hillshade: true,
  });
  const toggleLayer = useCallback((id) => {
    setLayers(l => ({ ...l, [id]: !l[id] }));
  }, []);

  const safeJson = async (res) => {
    try { return res.status === "fulfilled" && res.value.ok ? await res.value.json() : null; }
    catch { return null; }
  };

  async function loadParcel(id) {
    if (!id) return;
    setLoading(true);
    try {
      const [hmRes, exRes, ssRes, syRes, shRes, mlRes] = await Promise.allSettled([
        fetch(`/site/${encodeURIComponent(id)}/heightmap?size=64`),
        fetch(`/site/${encodeURIComponent(id)}/explain`),
        fetch(`/site/${encodeURIComponent(id)}/slope_stats`),
        fetch(`/site/${encodeURIComponent(id)}/solar_yield?capacity_kw=${samCapacity}`),
        fetch(`/site/${encodeURIComponent(id)}/solar_hourly?capacity_kw=${samCapacity}&day_of_year=${samDay}`),
        fetch(`/site/${encodeURIComponent(id)}/solar_yield_ml?capacity_kw=${samCapacity}&day_of_year=${samDay}`),
      ]);
      setHeightmap(await safeJson(hmRes));
      setExplain(await safeJson(exRes));
      setSlopeStats(await safeJson(ssRes));
      setSolarYield(await safeJson(syRes));
      setSolarHourly(await safeJson(shRes));
      setMlSolar(await safeJson(mlRes));
      setPanels(p => ({ ...p, score: true }));
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  async function runAgentAnalysis() {
    if (!parcelId) return;
    setAgentLoading(true);
    try {
      const res = await fetch(
        `/site/${encodeURIComponent(parcelId)}/agent_analysis?capacity_kw=${samCapacity}&day_of_year=${samDay}`
      );
      if (res.ok) {
        const data = await res.json();
        setAgentResult(data.agent);
        setPanels(p => ({ ...p, agent: true }));
      }
    } catch (err) {
      console.error(err);
    } finally {
      setAgentLoading(false);
    }
  }

  async function runDeferral() {
    try {
      const res = await fetch(`/opt/run?plan_name=ui_plan&load_mw=${loadMw}&gen_mw=${genMw}`, { method: "POST" });
      if (res.ok) {
        setDeferral(await res.json());
        setPanels(p => ({ ...p, deferral: true }));
      }
    } catch (err) { console.error(err); }
  }

  const verdictColor = (v) =>
    v === "GO" ? "#4caf50" : v === "CAUTION" ? "#ff9800" : "#f44336";

  return (
    <div className="app-fullscreen">
      {/* ── Map fills viewport ── */}
      <MapView slopeOpacity={slopeOpacity} layers={layers} />

      {/* ── Top bar ── */}
      <div className="topbar">
        <div className="topbar-brand">Feasibly</div>
        <input
          value={parcelId}
          onChange={(e) => setParcelId(e.target.value)}
          placeholder="Parcel UUID"
          className="topbar-input"
          onKeyDown={(e) => e.key === "Enter" && loadParcel(parcelId)}
        />
        <span className="topbar-param">
          <input type="number" value={samCapacity}
            onChange={(e) => setSamCapacity(Number(e.target.value))}
            style={{ width: 55 }} min={1} /> kW
        </span>
        <span className="topbar-param">
          Day <input type="number" value={samDay}
            onChange={(e) => setSamDay(Number(e.target.value))}
            style={{ width: 45 }} min={1} max={365} />
        </span>
        <button className="btn-primary" onClick={() => loadParcel(parcelId)} disabled={loading}>
          {loading ? "..." : "Analyse"}
        </button>
        <button className="btn-agent" onClick={runAgentAnalysis} disabled={agentLoading}>
          {agentLoading ? "Thinking..." : "Agent"}
        </button>
      </div>

      {/* ── Layer controls (left) ── */}
      <div className="layer-panel">
        <div className="layer-title">Layers</div>
        {[
          { id: "hillshade", label: "Hillshade", color: "#8d6e63" },
          { id: "slope", label: "Slope", color: "#2196f3" },
          { id: "carbon", label: "Carbon (PBCC)", color: "#e91e63" },
          { id: "la", label: "Local Authority", color: "#ff9800" },
          { id: "transport", label: "Transport", color: "#00bcd4" },
        ].map(l => (
          <label key={l.id} className="layer-item">
            <input type="checkbox" checked={layers[l.id]} onChange={() => toggleLayer(l.id)} />
            <span className="layer-dot" style={{ background: l.color }} />
            {l.label}
          </label>
        ))}
        {layers.slope && (
          <div style={{ marginTop: 6, paddingLeft: 4 }}>
            <input type="range" min="0" max="1" step="0.05" value={slopeOpacity}
              onChange={(e) => setSlopeOpacity(parseFloat(e.target.value))}
              style={{ width: "100%" }} />
          </div>
        )}
      </div>

      {/* ── Right overlays ── */}
      <div className="overlay-stack right-stack">
        <Overlay id="score" title="Feasibility Score" open={panels.score}
          onToggle={togglePanel} position="right" color="#4caf50">
          {explain ? (
            <div>
              <div className="score-row">
                <span className="score-badge" style={badgeStyle(explain.score_total)}>
                  {explain.score_total}/120
                </span>
                {explain.context?.score_components && Object.entries(explain.context.score_components).map(([k,v]) => (
                  <span key={k} className="score-chip">{k}: {v}</span>
                ))}
              </div>
              <pre className="overlay-pre">{explain.explanation}</pre>
            </div>
          ) : <span className="muted">Click Analyse</span>}
        </Overlay>

        <Overlay id="solar" title="Solar Analysis" open={panels.solar}
          onToggle={togglePanel} position="right" color="#ff9800">
          {solarYield ? (
            <div>
              <div className="stat-grid">
                <div><strong>{solarYield.annual_energy_kwh?.toLocaleString()}</strong> kWh/yr</div>
                <div><strong>{solarYield.capacity_factor_pct}%</strong> CF</div>
              </div>
              {solarYield.monthly_energy_kwh && (
                <div className="bar-chart">
                  {solarYield.monthly_energy_kwh.map((v, i) => {
                    const max = Math.max(...solarYield.monthly_energy_kwh);
                    return <div key={i} className="bar" title={`${MONTHS[i]}: ${v.toLocaleString()} kWh`}
                      style={{ height: `${(v/max)*100}%`, background: "#4caf50" }} />;
                  })}
                </div>
              )}
              <div className="bar-labels">{MONTHS.map(m => <span key={m}>{m[0]}</span>)}</div>

              {/* SAM hourly */}
              {solarHourly?.hourly_kw && (
                <>
                  <div className="section-label">SAM 24h (day {samDay})</div>
                  <div className="bar-chart small">
                    {solarHourly.hourly_kw.map((v, i) => {
                      const max = Math.max(...solarHourly.hourly_kw) || 1;
                      return <div key={i} className="bar" title={`${i}:00 ${v.toFixed(1)} kW`}
                        style={{ height: `${(v/max)*100}%`, background: v > 0 ? "#ff9800" : "#ddd", minHeight: v > 0 ? 2 : 1 }} />;
                    })}
                  </div>
                  <div className="stat-inline">Daily: <strong>{solarHourly.daily_total_kwh} kWh</strong></div>
                </>
              )}

              {/* ML hourly */}
              {mlSolar?.hourly_kwh && (
                <>
                  <div className="section-label">ML 24h (GBM)</div>
                  <div className="bar-chart small">
                    {mlSolar.hourly_kwh.map((v, i) => {
                      const max = Math.max(...mlSolar.hourly_kwh) || 1;
                      return <div key={i} className="bar" title={`${i}:00 ${v.toFixed(2)} kWh`}
                        style={{ height: `${(v/max)*100}%`, background: v > 0 ? "#9c27b0" : "#ddd", minHeight: v > 0 ? 2 : 1 }} />;
                    })}
                  </div>
                  <div className="stat-inline">ML daily: <strong>{mlSolar.daily_total_kwh} kWh</strong> | annual est: {mlSolar.annual_estimate_kwh?.toLocaleString()} kWh</div>
                </>
              )}
            </div>
          ) : <span className="muted">No solar data</span>}
        </Overlay>

        <Overlay id="terrain" title="Terrain" open={panels.terrain}
          onToggle={togglePanel} position="right" color="#2196f3">
          {slopeStats?.stats ? (
            <div>
              <div className="stat-grid three">
                <div>Mean: {slopeStats.stats.mean?.toFixed(1)}</div>
                <div>Min: {slopeStats.stats.min?.toFixed(1)}</div>
                <div>Max: {slopeStats.stats.max?.toFixed(1)}</div>
              </div>
              {slopeStats.histogram && (
                <div className="bar-chart small">
                  {slopeStats.histogram.map((bin, i) => {
                    const max = Math.max(...slopeStats.histogram.map(b => b.count)) || 1;
                    return <div key={i} className="bar"
                      title={`${bin.min.toFixed(1)}-${bin.max.toFixed(1)}: ${bin.count} px`}
                      style={{ height: `${(bin.count/max)*100}%`, background: "#2196f3" }} />;
                  })}
                </div>
              )}
              <ThreeView heightmap={heightmap} />
            </div>
          ) : <span className="muted">No terrain data</span>}
        </Overlay>

        <Overlay id="deferral" title="Network Deferral" open={panels.deferral}
          onToggle={togglePanel} position="right" color="#607d8b">
          <div className="inline-controls">
            <label>Load <input type="number" value={loadMw} onChange={(e) => setLoadMw(Number(e.target.value))}
              style={{ width: 45 }} min={0} /> MW</label>
            <label>Gen <input type="number" value={genMw} onChange={(e) => setGenMw(Number(e.target.value))}
              style={{ width: 45 }} min={0} /> MW</label>
            <button onClick={runDeferral}>Run</button>
          </div>
          {deferral ? (
            <div className="deferral-table-wrap">
              <table className="deferral-table">
                <thead><tr><th>Node</th><th>Load kW</th><th>Gen kW</th></tr></thead>
                <tbody>
                  {Object.entries(deferral.allocations || {}).map(([nid, a]) => (
                    <tr key={nid}><td>{nid}</td><td>{a.load_kw?.toFixed(1)}</td><td>{a.gen_kw?.toFixed(1)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <span className="muted">Click Run</span>}
        </Overlay>
      </div>

      {/* ── Agent analysis overlay (bottom) ── */}
      {(panels.agent || agentResult) && (
        <div className="agent-overlay">
          <div className="overlay-header" onClick={() => togglePanel("agent")}
            style={{ borderLeftColor: agentResult ? verdictColor(agentResult.verdict) : "#666" }}>
            <span className="overlay-title">Agent Analysis</span>
            <span className="overlay-toggle">{panels.agent ? "\u25BC" : "\u25B2"}</span>
          </div>
          {panels.agent && agentResult && (
            <div className="overlay-body agent-body">
              <div className="agent-verdict" style={{ background: verdictColor(agentResult.verdict) }}>
                {agentResult.verdict}
                <span className="agent-conf">
                  {Math.round((agentResult.confidence || 0) * 100)}% conf
                </span>
              </div>
              <p className="agent-summary">{agentResult.summary}</p>
              <div className="agent-columns">
                {agentResult.risks?.length > 0 && (
                  <div className="agent-col">
                    <div className="agent-col-title risk">Risks</div>
                    <ul>{agentResult.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
                  </div>
                )}
                {agentResult.opportunities?.length > 0 && (
                  <div className="agent-col">
                    <div className="agent-col-title opp">Opportunities</div>
                    <ul>{agentResult.opportunities.map((o, i) => <li key={i}>{o}</li>)}</ul>
                  </div>
                )}
                {agentResult.next_steps?.length > 0 && (
                  <div className="agent-col">
                    <div className="agent-col-title steps">Next Steps</div>
                    <ol>{agentResult.next_steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
                  </div>
                )}
              </div>
              {agentResult.recommended_capacity_kw != null && (
                <div className="agent-meta">
                  Recommended capacity: <strong>{agentResult.recommended_capacity_kw} kW</strong>
                  {agentResult.estimated_roi_years != null && (
                    <> | Est. ROI: <strong>{agentResult.estimated_roi_years} years</strong></>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function badgeStyle(score) {
  const pct = score / 120;
  const bg = pct > 0.7 ? "#4caf50" : pct > 0.4 ? "#ff9800" : "#f44336";
  return {
    display: "inline-block", padding: "2px 10px", borderRadius: 12,
    background: bg, color: "#fff", fontWeight: "bold", fontSize: 15,
  };
}
