import React, { useState, useCallback } from "react";
import { useSite } from "../../SiteContext";

const RAG_COLORS = { green: "#4caf50", amber: "#ff9800", red: "#f44336" };
const VERDICT_COLORS = { GO: "#4caf50", CAUTION: "#ff9800", "NO-GO": "#f44336" };

export default function GridConnectionCard() {
  const { selectedParcel } = useSite();
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [capacityMw, setCapacityMw] = useState(5);
  const [technology, setTechnology] = useState("solar");
  const [expandedSub, setExpandedSub] = useState(null);

  const assess = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const lat = selectedParcel?.lat || 52.5;
      const lon = selectedParcel?.lon || -1.5;
      const params = new URLSearchParams({
        lat, lon, capacity_mw: capacityMw, technology,
      });
      const res = await fetch(`/api/grid/assess?${params}`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [selectedParcel, capacityMw, technology]);

  return (
    <div className="card" style={{ borderLeft: "3px solid #0288d1" }}>
      <h3 style={{ margin: "0 0 8px", color: "#0288d1" }}>Grid Connection</h3>

      {/* Input form */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 6, marginBottom: 8 }}>
        <div>
          <label style={{ fontSize: 10, color: "#aaa" }}>Capacity (MW)</label>
          <input
            type="number" value={capacityMw} min={0.01} step={0.5}
            onChange={e => setCapacityMw(+e.target.value)}
            className="settings-input" style={{ padding: "4px 6px", fontSize: 12 }}
          />
        </div>
        <div>
          <label style={{ fontSize: 10, color: "#aaa" }}>Technology</label>
          <select
            value={technology} onChange={e => setTechnology(e.target.value)}
            className="settings-input" style={{ padding: "4px 6px", fontSize: 12 }}
          >
            <option value="solar">Solar PV</option>
            <option value="wind">Wind</option>
            <option value="bess">BESS</option>
            <option value="demand">Demand</option>
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "flex-end" }}>
          <button
            onClick={assess} disabled={loading}
            className="btn-sm" style={{ background: "#0288d1", color: "#fff", fontSize: 11 }}
          >
            {loading ? "..." : "Assess"}
          </button>
        </div>
      </div>

      {error && <div style={{ color: "#f44336", fontSize: 11, marginBottom: 6 }}>{error}</div>}

      {result && (
        <>
          {/* Verdict banner */}
          <div style={{
            background: VERDICT_COLORS[result.verdict] || "#666",
            color: "#fff", padding: "6px 10px", borderRadius: 4, marginBottom: 8,
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}>
            <span style={{ fontWeight: 700 }}>{result.verdict}</span>
            <span style={{ fontSize: 11 }}>{(result.confidence * 100).toFixed(0)}% confidence</span>
          </div>

          <div style={{ fontSize: 12, color: "#ccc", marginBottom: 8 }}>{result.summary}</div>

          {/* DNO area */}
          {result.dno_area && (
            <div style={{ fontSize: 11, color: "#888", marginBottom: 6 }}>
              DNO: <strong>{result.dno_area.name}</strong>
            </div>
          )}

          {/* Cost estimate */}
          {result.cost_estimate && (
            <div style={{
              background: "rgba(2,136,209,0.1)", padding: 8, borderRadius: 4, marginBottom: 8,
            }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#0288d1", marginBottom: 4 }}>
                Connection Cost (P10/P50/P90)
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, fontSize: 12 }}>
                <div>
                  <span style={{ color: "#888", fontSize: 10 }}>Optimistic</span>
                  <div style={{ fontWeight: 600 }}>
                    {"\u00A3"}{(result.cost_estimate.cost_gbp.p10 / 1000).toFixed(0)}k
                  </div>
                </div>
                <div>
                  <span style={{ color: "#888", fontSize: 10 }}>Expected</span>
                  <div style={{ fontWeight: 700, color: "#0288d1" }}>
                    {"\u00A3"}{(result.cost_estimate.cost_gbp.p50 / 1000).toFixed(0)}k
                  </div>
                </div>
                <div>
                  <span style={{ color: "#888", fontSize: 10 }}>Conservative</span>
                  <div style={{ fontWeight: 600 }}>
                    {"\u00A3"}{(result.cost_estimate.cost_gbp.p90 / 1000).toFixed(0)}k
                  </div>
                </div>
              </div>
              <div style={{ fontSize: 10, color: "#888", marginTop: 4 }}>
                Timeline: {result.cost_estimate.timeline_weeks.p50} weeks (P50)
              </div>
            </div>
          )}

          {/* Candidate substations */}
          <div style={{ fontSize: 11, fontWeight: 600, color: "#0288d1", marginBottom: 4 }}>
            Connection Candidates ({result.candidates?.length || 0})
          </div>
          {result.candidates?.map((c, i) => (
            <div
              key={c.id || i}
              onClick={() => setExpandedSub(expandedSub === i ? null : i)}
              style={{
                background: i === 0 ? "rgba(2,136,209,0.08)" : "rgba(255,255,255,0.03)",
                padding: "6px 8px", borderRadius: 4, marginBottom: 4, cursor: "pointer",
                borderLeft: `3px solid ${RAG_COLORS[c.rag_generation] || "#666"}`,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <span style={{ fontWeight: 600, fontSize: 12 }}>{c.name}</span>
                  <span style={{ fontSize: 10, color: "#888", marginLeft: 6 }}>
                    {c.voltage_kv}kV {c.dno?.toUpperCase()}
                  </span>
                </div>
                <div style={{ textAlign: "right" }}>
                  <span style={{
                    background: c.suitability_score >= 70 ? "#4caf50" : c.suitability_score >= 40 ? "#ff9800" : "#f44336",
                    color: "#fff", padding: "1px 6px", borderRadius: 3, fontSize: 10, fontWeight: 700,
                  }}>
                    {c.suitability_score}/100
                  </span>
                </div>
              </div>
              <div style={{ fontSize: 10, color: "#aaa", marginTop: 2 }}>
                {c.distance_km} km
                {c.gen_headroom_mw != null && ` | ${c.gen_headroom_mw} MW headroom`}
                {c.queue?.ecr_queued > 0 && ` | ${c.queue.ecr_queued} in queue (${c.queue.ecr_queued_mw} MW)`}
              </div>

              {expandedSub === i && (
                <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px solid rgba(255,255,255,0.1)" }}>
                  {c.notes?.map((n, j) => (
                    <div key={j} style={{ fontSize: 10, color: "#bbb", marginBottom: 2 }}>{n}</div>
                  ))}
                  {c.risks?.length > 0 && (
                    <div style={{ marginTop: 4 }}>
                      {c.risks.map((r, j) => (
                        <div key={j} style={{ fontSize: 10, color: "#f44336", marginBottom: 2 }}>{r}</div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {/* Risks */}
          {result.risks?.length > 0 && (
            <div style={{ marginTop: 6 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#f44336", marginBottom: 4 }}>Risks</div>
              {result.risks.map((r, i) => (
                <div key={i} style={{ fontSize: 10, color: "#f44336", marginBottom: 2 }}>{r}</div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
