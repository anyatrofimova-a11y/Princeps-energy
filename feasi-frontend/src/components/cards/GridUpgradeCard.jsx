import React, { useState, useEffect, useCallback } from "react";
import api from "../../services/api";

const ACCENT = "#e91e63";
const DNO_PILLS = ["all", "nged", "ukpn", "ssen"];

function statusColor(status) {
  if (!status) return "#607d8b";
  const s = status.toLowerCase();
  if (s.includes("complete")) return "#4caf50";
  if (s.includes("progress") || s.includes("construct")) return "#ff9800";
  if (s.includes("plan")) return "#2196f3";
  return "#607d8b";
}

function formatGBP(val) {
  if (val == null) return "—";
  if (val >= 1e9) return `\u00a3${(val / 1e9).toFixed(1)}B`;
  if (val >= 1e6) return `\u00a3${(val / 1e6).toFixed(0)}M`;
  if (val >= 1e3) return `\u00a3${(val / 1e3).toFixed(0)}K`;
  return `\u00a3${val}`;
}

export default function GridUpgradeCard() {
  const [summary, setSummary] = useState(null);
  const [investment, setInvestment] = useState(null);
  const [loading, setLoading] = useState(false);
  const [dno, setDno] = useState("all");
  const [view, setView] = useState("summary");

  const loadSummary = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.tracker.gridUpgradesSummary();
      setSummary(data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  const loadInvestment = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.tracker.dnoInvestment(dno === "all" ? null : dno);
      setInvestment(data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [dno]);

  useEffect(() => {
    if (view === "summary" && !summary) loadSummary();
    if (view === "investment") loadInvestment();
  }, [view, summary, dno, loadSummary, loadInvestment]);

  return (
    <div className="card" style={{ borderLeft: `3px solid ${ACCENT}` }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, color: ACCENT, flex: 1 }}>Grid Upgrades</h3>
        <button
          className={`tab-btn-sm ${view === "summary" ? "active" : ""}`}
          style={view === "summary" ? { background: ACCENT, color: "#fff" } : { color: ACCENT }}
          onClick={() => setView("summary")}
        >Upgrades</button>
        <button
          className={`tab-btn-sm ${view === "investment" ? "active" : ""}`}
          style={view === "investment" ? { background: ACCENT, color: "#fff" } : { color: ACCENT }}
          onClick={() => setView("investment")}
        >RIIO-ED2</button>
      </div>

      {loading && <div className="spinner-sm" />}

      {view === "summary" && summary && (
        <div>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 8 }}>
            <div><strong>{summary.total_projects}</strong> projects</div>
            <div><strong>{formatGBP(summary.total_capex_gbp)}</strong> total capex</div>
          </div>
          {summary.by_dno?.map((d) => (
            <div key={d.dno} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "2px 0" }}>
              <span style={{ textTransform: "uppercase" }}>{d.dno || "unknown"}</span>
              <span>{d.cnt} projects ({formatGBP(Number(d.total_capex))})</span>
            </div>
          ))}
          {summary.by_status?.map((s) => (
            <div key={s.status} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "1px 0" }}>
              <span style={{ color: statusColor(s.status) }}>{s.status || "Unknown"}</span>
              <span>{s.cnt}</span>
            </div>
          ))}
        </div>
      )}

      {view === "investment" && (
        <div>
          <div style={{ display: "flex", gap: 4, marginBottom: 8, flexWrap: "wrap" }}>
            {DNO_PILLS.map((d) => (
              <button
                key={d}
                className="tab-btn-sm"
                style={dno === d ? { background: ACCENT, color: "#fff" } : { color: ACCENT }}
                onClick={() => setDno(d)}
              >{d.toUpperCase()}</button>
            ))}
          </div>
          {investment?.plans?.length > 0 ? (
            <div style={{ maxHeight: 300, overflowY: "auto" }}>
              {investment.plans.map((p) => (
                <div key={p.plan_id} style={{ borderBottom: "1px solid #333", padding: "6px 0", fontSize: 13 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <strong>{p.programme}</strong>
                    <span style={{ color: ACCENT }}>{p.dno?.toUpperCase()}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", color: "#999", fontSize: 12 }}>
                    <span>Capex: {formatGBP(p.total_capex_gbp)}</span>
                    <span>Delivery: {p.delivery_pct}%</span>
                  </div>
                  <div style={{ height: 4, background: "#333", borderRadius: 2, marginTop: 4 }}>
                    <div style={{ height: 4, background: ACCENT, borderRadius: 2, width: `${Math.min(p.delivery_pct, 100)}%` }} />
                  </div>
                </div>
              ))}
            </div>
          ) : !loading && (
            <div style={{ color: "#666", fontSize: 13 }}>No investment plans found</div>
          )}
        </div>
      )}
    </div>
  );
}
