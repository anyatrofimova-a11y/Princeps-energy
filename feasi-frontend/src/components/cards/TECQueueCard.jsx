import React, { useState, useEffect, useCallback } from "react";
import api from "../../services/api";

const ACCENT = "#00bcd4";

export default function TECQueueCard() {
  const [summary, setSummary] = useState(null);
  const [queue, setQueue] = useState(null);
  const [loading, setLoading] = useState(false);
  const [siteFilter, setSiteFilter] = useState("");
  const [view, setView] = useState("summary");

  const loadSummary = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.tracker.tecSummary();
      setSummary(data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  const loadQueue = useCallback(async () => {
    if (!siteFilter) return;
    setLoading(true);
    try {
      const data = await api.tracker.tecQueue(siteFilter);
      setQueue(data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [siteFilter]);

  useEffect(() => {
    if (view === "summary" && !summary) loadSummary();
  }, [view, summary, loadSummary]);

  return (
    <div className="card" style={{ borderLeft: `3px solid ${ACCENT}` }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, color: ACCENT, flex: 1 }}>TEC Connection Queue</h3>
        <button
          className={`tab-btn-sm ${view === "summary" ? "active" : ""}`}
          style={view === "summary" ? { background: ACCENT, color: "#000" } : { color: ACCENT }}
          onClick={() => setView("summary")}
        >Summary</button>
        <button
          className={`tab-btn-sm ${view === "queue" ? "active" : ""}`}
          style={view === "queue" ? { background: ACCENT, color: "#000" } : { color: ACCENT }}
          onClick={() => setView("queue")}
        >Queue</button>
      </div>

      {loading && <div className="spinner-sm" />}

      {view === "summary" && summary && (
        <div>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 8 }}>
            <div><strong>{summary.total_entries?.toLocaleString()}</strong> entries</div>
            <div><strong>{summary.total_mw?.toLocaleString()} MW</strong> total TEC</div>
          </div>
          {summary.by_fuel_type?.map((f) => (
            <div key={f.tech_category} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "2px 0" }}>
              <span style={{ textTransform: "capitalize" }}>{f.tech_category || "other"}</span>
              <span>{f.cnt} ({Number(f.total_mw).toLocaleString()} MW)</span>
            </div>
          ))}
          {summary.top_connection_sites?.length > 0 && (
            <>
              <div style={{ marginTop: 8, fontSize: 12, color: "#888" }}>Top Connection Sites</div>
              {summary.top_connection_sites.slice(0, 8).map((s) => (
                <div
                  key={s.connection_site}
                  style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "2px 0", cursor: "pointer" }}
                  onClick={() => { setSiteFilter(s.connection_site); setView("queue"); }}
                >
                  <span style={{ color: ACCENT }}>{s.connection_site}</span>
                  <span>{Number(s.total_mw).toLocaleString()} MW ({s.cnt})</span>
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {view === "queue" && (
        <div>
          <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
            <input
              type="text"
              placeholder="Connection site name..."
              value={siteFilter}
              onChange={(e) => setSiteFilter(e.target.value)}
              style={{ flex: 1, padding: 4, fontSize: 12, background: "#F7F8FA", border: `1px solid ${ACCENT}`, color: "#1A1D23", borderRadius: 4 }}
            />
            <button className="tab-btn-sm" style={{ background: ACCENT, color: "#000" }} onClick={loadQueue}>Search</button>
          </div>
          {queue && (
            <>
              <div style={{ fontSize: 13, marginBottom: 4 }}>
                <strong>{queue.queue_depth}</strong> entries, <strong>{queue.total_mw} MW</strong> total
              </div>
              <div style={{ maxHeight: 250, overflowY: "auto" }}>
                {queue.entries?.map((e) => (
                  <div key={e.tec_id} style={{ borderBottom: "1px solid #333", padding: "4px 0", fontSize: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span>{e.customer_name || "Unknown"}</span>
                      <span style={{ color: ACCENT }}>{e.tec_mw ? `${e.tec_mw} MW` : ""}</span>
                    </div>
                    <div style={{ color: "#888" }}>{e.fuel_type} — {e.status}</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
