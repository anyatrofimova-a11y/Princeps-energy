import React, { useState, useCallback, useEffect } from "react";
import { useSite } from "../../SiteContext";

/**
 * SiteProspectorCard — Site scoring, regional scanning, and similar site search.
 */
export default function SiteProspectorCard() {
  const { pickedLocation } = useSite();
  const lat = pickedLocation?.[0];
  const lon = pickedLocation?.[1];
  const [view, setView] = useState("score"); // score | scan | similar
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [technology, setTechnology] = useState("solar");
  const [region, setRegion] = useState("south_west");

  const scoreSite = useCallback(async () => {
    if (!lat || !lon) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/prospector/score?lat=${lat}&lon=${lon}&technology=${technology}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [lat, lon, technology]);

  const scanRegion = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/prospector/scan?region=${region}&technology=${technology}&grid_points=25`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [region, technology]);

  const findSimilar = useCallback(async () => {
    if (!lat || !lon) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/prospector/similar?lat=${lat}&lon=${lon}&radius_km=50&technology=${technology}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [lat, lon, technology]);

  // Reset result when view changes
  useEffect(() => setResult(null), [view]);

  const recColor = (rec) => {
    if (rec === "HIGH_PRIORITY") return "#4caf50";
    if (rec === "PROMISING") return "#ff9800";
    if (rec === "MARGINAL") return "#ff5722";
    return "#f44336";
  };

  const themeColor = "#009688";

  return (
    <div className="card" style={{ borderLeft: `3px solid ${themeColor}` }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, color: themeColor, flex: 1 }}>Site Prospector</h3>
        {["score", "scan", "similar"].map(v => (
          <button
            key={v}
            className={`tab-btn-sm ${view === v ? "active" : ""}`}
            style={view === v ? { background: themeColor, color: "#fff" } : { color: themeColor }}
            onClick={() => setView(v)}
          >{v === "score" ? "Score" : v === "scan" ? "Scan" : "Similar"}</button>
        ))}
      </div>

      {/* Technology selector */}
      <div style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center" }}>
        <label style={{ fontSize: 10, color: "#aaa" }}>Tech:</label>
        <select
          value={technology} onChange={e => setTechnology(e.target.value)}
          className="settings-select" style={{ padding: "3px 6px", fontSize: 11, flex: 1 }}
        >
          <option value="solar">Solar</option>
          <option value="wind">Wind</option>
          <option value="battery">Battery</option>
        </select>

        {view === "scan" && (
          <>
            <label style={{ fontSize: 10, color: "#aaa" }}>Region:</label>
            <select
              value={region} onChange={e => setRegion(e.target.value)}
              className="settings-select" style={{ padding: "3px 6px", fontSize: 11, flex: 1 }}
            >
              {["south_east", "south_west", "east_anglia", "midlands", "wales",
                "north_west", "north_east", "scotland_central", "scotland_north"].map(r => (
                <option key={r} value={r}>{r.replace(/_/g, " ")}</option>
              ))}
            </select>
          </>
        )}
      </div>

      <button
        onClick={view === "score" ? scoreSite : view === "scan" ? scanRegion : findSimilar}
        disabled={loading || ((view === "score" || view === "similar") && (!lat || !lon))}
        style={{
          background: themeColor, color: "#fff", border: "none", borderRadius: 4,
          padding: "6px 14px", fontSize: 12, cursor: "pointer", width: "100%", marginBottom: 8,
        }}
      >
        {loading ? "Analysing..." : view === "score" ? "Score Site" : view === "scan" ? "Scan Region" : "Find Similar"}
      </button>

      {error && <p style={{ color: "#f44336", fontSize: 12 }}>{error}</p>}

      {/* Score result */}
      {view === "score" && result && result.total_score !== undefined && (
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
            <div style={{
              fontSize: 28, fontWeight: 700, color: recColor(result.recommendation),
            }}>{result.total_score}</div>
            <div>
              <div style={{
                fontSize: 13, fontWeight: 600, color: recColor(result.recommendation),
              }}>{result.recommendation}</div>
              <div style={{ fontSize: 11, color: "#aaa" }}>{result.region?.replace(/_/g, " ")}</div>
            </div>
          </div>
          {result.scores && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {Object.entries(result.scores).map(([k, v]) => (
                <div key={k} className="stat-box">
                  <div className="stat-value" style={{ fontSize: 14 }}>{v}</div>
                  <div className="stat-label">{k.replace(/_/g, " ")}</div>
                </div>
              ))}
            </div>
          )}
          {result.constraints?.length > 0 && (
            <div style={{ marginTop: 6, fontSize: 11, color: "#f44336" }}>
              Constraints: {result.constraints.join(", ")}
            </div>
          )}
        </div>
      )}

      {/* Scan result */}
      {view === "scan" && result && result.top_sites && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginBottom: 8 }}>
            <div className="stat-box">
              <div className="stat-value">{result.total_scanned}</div>
              <div className="stat-label">Scanned</div>
            </div>
            <div className="stat-box">
              <div className="stat-value" style={{ color: "#4caf50" }}>{result.high_priority_count}</div>
              <div className="stat-label">High Priority</div>
            </div>
            <div className="stat-box">
              <div className="stat-value" style={{ color: "#ff9800" }}>{result.promising_count}</div>
              <div className="stat-label">Promising</div>
            </div>
          </div>
          <div style={{ fontSize: 11, color: "#aaa", marginBottom: 4 }}>
            Top Sites (avg score: {result.avg_score})
          </div>
          {result.top_sites.slice(0, 8).map((s, i) => (
            <div key={i} style={{
              display: "flex", justifyContent: "space-between",
              padding: "3px 0", fontSize: 12, borderBottom: "1px solid #222",
            }}>
              <span style={{ color: "#ccc" }}>
                {s.lat.toFixed(3)}, {s.lon.toFixed(3)}
              </span>
              <span style={{ color: recColor(s.recommendation), fontWeight: 600 }}>
                {s.total_score} — {s.recommendation}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Similar sites result */}
      {view === "similar" && result && result.top_matches && (
        <div>
          <div style={{ fontSize: 11, color: "#aaa", marginBottom: 4 }}>
            {result.candidates_scanned} candidates scanned within {result.search_radius_km}km
          </div>
          {result.top_matches.slice(0, 8).map((s, i) => (
            <div key={i} style={{
              display: "flex", justifyContent: "space-between",
              padding: "3px 0", fontSize: 12, borderBottom: "1px solid #222",
            }}>
              <span style={{ color: "#ccc" }}>
                {s.lat.toFixed(3)}, {s.lon.toFixed(3)} ({s.distance_from_reference_km}km)
              </span>
              <span style={{ color: recColor(s.recommendation) }}>
                {s.total_score} / {s.similarity_pct}% sim
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
