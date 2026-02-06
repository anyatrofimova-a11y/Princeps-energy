import React, { useState } from "react";
import MapView from "./components/MapView";
import ThreeView from "./components/ThreeView";

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

export default function App() {
  const [parcelId, setParcelId] = useState("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
  const [heightmap, setHeightmap] = useState(null);
  const [explain, setExplain] = useState(null);
  const [slopeStats, setSlopeStats] = useState(null);
  const [solarYield, setSolarYield] = useState(null);
  const [solarHourly, setSolarHourly] = useState(null);
  const [deferral, setDeferral] = useState(null);
  const [slopeOpacity, setSlopeOpacity] = useState(0.8);
  const [loading, setLoading] = useState(false);

  // SAM parameters
  const [samCapacity, setSamCapacity] = useState(100);
  const [samDay, setSamDay] = useState(172); // summer solstice

  // Deferral parameters
  const [loadMw, setLoadMw] = useState(5);
  const [genMw, setGenMw] = useState(4);

  async function loadParcel(id) {
    if (!id) return alert("Enter a parcel id");
    setLoading(true);
    try {
      const [hmRes, exRes, ssRes, syRes, shRes] = await Promise.allSettled([
        fetch(`/site/${encodeURIComponent(id)}/heightmap?size=64`),
        fetch(`/site/${encodeURIComponent(id)}/explain`),
        fetch(`/site/${encodeURIComponent(id)}/slope_stats`),
        fetch(`/site/${encodeURIComponent(id)}/solar_yield?capacity_kw=${samCapacity}`),
        fetch(`/site/${encodeURIComponent(id)}/solar_hourly?capacity_kw=${samCapacity}&day_of_year=${samDay}`),
      ]);

      const safeJson = async (res) => {
        try { return res.status === "fulfilled" && res.value.ok ? await res.value.json() : null; }
        catch { return null; }
      };
      setHeightmap(await safeJson(hmRes));
      setExplain(await safeJson(exRes));
      setSlopeStats(await safeJson(ssRes));
      setSolarYield(await safeJson(syRes));
      setSolarHourly(await safeJson(shRes));
    } catch (err) {
      console.error(err);
      alert("Failed to load parcel: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function runDeferral() {
    setLoading(true);
    try {
      const res = await fetch(
        `/opt/run?plan_name=ui_plan&load_mw=${loadMw}&gen_mw=${genMw}`,
        { method: "POST" }
      );
      if (res.ok) {
        setDeferral(await res.json());
      } else {
        alert("Deferral run failed: " + res.statusText);
      }
    } catch (err) {
      alert("Deferral error: " + err.message);
    } finally {
      setLoading(false);
    }
  }

  async function downloadCSV() {
    if (!parcelId) return alert("Enter parcel id");
    const res = await fetch(`/site/${encodeURIComponent(parcelId)}/slope_stats?format=csv`);
    if (!res.ok) return alert("CSV download failed");
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${parcelId}_slope_stats.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  return (
    <div className="app">
      <div className="left">
        <MapView slopeOpacity={slopeOpacity} />
      </div>

      <div className="right">
        <h2 style={{ margin: "0 0 8px", fontSize: 18 }}>Feasibly</h2>
        <p style={{ margin: "0 0 12px", fontSize: 12, color: "#666" }}>
          Solar site feasibility — PostGIS + SAM + Claude AI
        </p>

        {/* ── Parcel input ── */}
        <div className="panel">
          <h3>Site Selection</h3>
          <input
            value={parcelId}
            onChange={(e) => setParcelId(e.target.value)}
            placeholder="Parcel UUID"
            style={{ marginBottom: 6 }}
            onKeyDown={(e) => e.key === "Enter" && loadParcel(parcelId)}
          />
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            <button onClick={() => loadParcel(parcelId)} disabled={loading}>
              {loading ? "Loading..." : "Analyse"}
            </button>
            <button onClick={downloadCSV}>Slope CSV</button>
            <span style={{ fontSize: 11, color: "#999" }}>
              Cap: <input type="number" value={samCapacity}
                onChange={(e) => setSamCapacity(Number(e.target.value))}
                style={{ width: 60, padding: 2, fontSize: 11 }} min={1} /> kW
            </span>
          </div>
        </div>

        {/* ── Slope opacity ── */}
        <div className="control">
          <label>Slope overlay: {slopeOpacity.toFixed(2)}</label>
          <input type="range" min="0" max="1" step="0.01"
            value={slopeOpacity}
            onChange={(e) => setSlopeOpacity(parseFloat(e.target.value))} />
        </div>

        {/* ── Explain (Claude) ── */}
        <div className="panel">
          <h3>Feasibility Score</h3>
          {explain ? (
            <div style={{ fontSize: 13 }}>
              <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
                <span className="badge" style={badgeStyle(explain.score_total)}>
                  {explain.score_total}/120
                </span>
                {explain.context?.score_components && Object.entries(explain.context.score_components).map(([k,v]) => (
                  <span key={k} style={{ fontSize: 11, color: "#555" }}>{k}: {v}</span>
                ))}
              </div>
              <pre className="json">{explain.explanation}</pre>
            </div>
          ) : <pre className="json">No data — click Analyse</pre>}
        </div>

        {/* ── SAM Solar Yield ── */}
        <div className="panel">
          <h3>SAM Solar Yield (PvWattsv8)</h3>
          {solarYield ? (
            <div style={{ fontSize: 13 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, marginBottom: 8 }}>
                <div><strong>Annual:</strong> {solarYield.annual_energy_kwh?.toLocaleString()} kWh</div>
                <div><strong>CF:</strong> {solarYield.capacity_factor_pct}%</div>
                <div><strong>Irrad:</strong> {solarYield.annual_solar_radiation_kwh_m2_day} kWh/m²/day</div>
                {solarYield.yield_kwh_per_m2 != null && (
                  <div><strong>Yield/m²:</strong> {solarYield.yield_kwh_per_m2} kWh</div>
                )}
              </div>
              {solarYield.monthly_energy_kwh && (
                <div>
                  <strong>Monthly generation:</strong>
                  <div style={{ display: "flex", gap: 2, height: 60, alignItems: "flex-end", marginTop: 4 }}>
                    {solarYield.monthly_energy_kwh.map((v, i) => {
                      const max = Math.max(...solarYield.monthly_energy_kwh);
                      return (
                        <div key={i}
                          title={`${MONTHS[i]}: ${v.toLocaleString()} kWh`}
                          style={{
                            flex: 1, background: "#4caf50",
                            height: `${(v / max) * 100}%`, borderRadius: 2,
                          }} />
                      );
                    })}
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#888", marginTop: 2 }}>
                    {MONTHS.map(m => <span key={m}>{m[0]}</span>)}
                  </div>
                </div>
              )}
            </div>
          ) : <pre className="json">No data</pre>}
        </div>

        {/* ── Solar Hourly Profile ── */}
        <div className="panel">
          <h3>24h Generation Profile</h3>
          <div style={{ marginBottom: 6, fontSize: 12 }}>
            Day of year: <input type="number" value={samDay}
              onChange={(e) => setSamDay(Number(e.target.value))}
              style={{ width: 50, padding: 2, fontSize: 12 }} min={1} max={365} />
            <span style={{ marginLeft: 8, color: "#888" }}>
              {samDay <= 31 ? "Jan" : samDay <= 59 ? "Feb" : samDay <= 90 ? "Mar" :
               samDay <= 120 ? "Apr" : samDay <= 151 ? "May" : samDay <= 181 ? "Jun" :
               samDay <= 212 ? "Jul" : samDay <= 243 ? "Aug" : samDay <= 273 ? "Sep" :
               samDay <= 304 ? "Oct" : samDay <= 334 ? "Nov" : "Dec"}
            </span>
          </div>
          {solarHourly && solarHourly.hourly_kw ? (
            <div>
              <div style={{ display: "flex", gap: 1, height: 50, alignItems: "flex-end" }}>
                {solarHourly.hourly_kw.map((v, i) => {
                  const max = Math.max(...solarHourly.hourly_kw) || 1;
                  return (
                    <div key={i}
                      title={`${i}:00 — ${v.toFixed(1)} kW`}
                      style={{
                        flex: 1, borderRadius: 1,
                        background: v > 0 ? "#ff9800" : "#eee",
                        height: `${(v / max) * 100}%`,
                        minHeight: v > 0 ? 2 : 1,
                      }} />
                  );
                })}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#888", marginTop: 2 }}>
                <span>0</span><span>6</span><span>12</span><span>18</span><span>23</span>
              </div>
              <div style={{ fontSize: 12, marginTop: 4 }}>
                Daily total: <strong>{solarHourly.daily_total_kwh} kWh</strong>
              </div>
            </div>
          ) : <pre className="json">No data</pre>}
        </div>

        {/* ── Slope Stats ── */}
        <div className="panel">
          <h3>Slope Statistics</h3>
          {slopeStats?.stats ? (
            <div style={{ fontSize: 12 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 4 }}>
                <div>Mean: {slopeStats.stats.mean?.toFixed(1)}°</div>
                <div>Min: {slopeStats.stats.min?.toFixed(1)}°</div>
                <div>Max: {slopeStats.stats.max?.toFixed(1)}°</div>
              </div>
              {slopeStats.histogram && (
                <div style={{ display: "flex", gap: 1, height: 40, alignItems: "flex-end", marginTop: 6 }}>
                  {slopeStats.histogram.map((bin, i) => {
                    const max = Math.max(...slopeStats.histogram.map(b => b.count)) || 1;
                    return (
                      <div key={i}
                        title={`${bin.min.toFixed(1)}°–${bin.max.toFixed(1)}°: ${bin.count} px`}
                        style={{
                          flex: 1, background: "#2196f3", borderRadius: 1,
                          height: `${(bin.count / max) * 100}%`,
                        }} />
                    );
                  })}
                </div>
              )}
            </div>
          ) : <pre className="json">No slope data</pre>}
        </div>

        {/* ── 3D Heightmap ── */}
        <div className="panel">
          <h3>3D Terrain</h3>
          <ThreeView heightmap={heightmap} />
        </div>

        {/* ── Network Deferral ── */}
        <div className="panel">
          <h3>Network Deferral Optimiser</h3>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, fontSize: 12 }}>
            <label>Load: <input type="number" value={loadMw}
              onChange={(e) => setLoadMw(Number(e.target.value))}
              style={{ width: 50, padding: 2 }} min={0} /> MW</label>
            <label>Gen: <input type="number" value={genMw}
              onChange={(e) => setGenMw(Number(e.target.value))}
              style={{ width: 50, padding: 2 }} min={0} /> MW</label>
            <button onClick={runDeferral} disabled={loading}>Run</button>
          </div>
          {deferral ? (
            <div style={{ fontSize: 12 }}>
              <div style={{ marginBottom: 6 }}>
                <strong>{deferral.plan_name}</strong> —
                Load: {deferral.total_load_kw} kW, Gen: {deferral.total_gen_kw} kW
              </div>
              <div style={{ maxHeight: 140, overflowY: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                  <thead>
                    <tr style={{ background: "#f5f5f5" }}>
                      <th style={thStyle}>Node</th>
                      <th style={thStyle}>Load (kW)</th>
                      <th style={thStyle}>Gen (kW)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deferral.allocations && Object.entries(deferral.allocations).map(([nodeId, a]) => (
                      <tr key={nodeId} style={{ borderBottom: "1px solid #eee" }}>
                        <td style={tdStyle}>{nodeId}</td>
                        <td style={tdStyle}>{a.load_kw?.toFixed(1)}</td>
                        <td style={tdStyle}>{a.gen_kw?.toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : <pre className="json">Click Run to allocate</pre>}
        </div>
      </div>
    </div>
  );
}

/* Helpers */
function badgeStyle(score) {
  const pct = score / 120;
  const bg = pct > 0.7 ? "#4caf50" : pct > 0.4 ? "#ff9800" : "#f44336";
  return {
    display: "inline-block", padding: "2px 8px", borderRadius: 12,
    background: bg, color: "#fff", fontWeight: "bold", fontSize: 14,
  };
}

const thStyle = { textAlign: "left", padding: "3px 6px", borderBottom: "2px solid #ddd" };
const tdStyle = { padding: "3px 6px" };
