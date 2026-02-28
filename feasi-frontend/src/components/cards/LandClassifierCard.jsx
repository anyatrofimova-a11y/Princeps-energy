import React, { useState, useCallback, useEffect } from "react";
import { useSite } from "../../SiteContext";

/**
 * LandClassifierCard — 3-tab card for enriched 21-class land use
 * classification, retrofitting assessment, and land use forecasting.
 */
export default function LandClassifierCard() {
  const { pickedLocation, setChatLayers } = useSite();
  const lat = pickedLocation?.[0];
  const lon = pickedLocation?.[1];
  const [view, setView] = useState("classify"); // classify | retrofit | forecast
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Reset result when view changes
  useEffect(() => setResult(null), [view]);

  const runClassify = useCallback(async () => {
    if (!lat || !lon) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/classify/land-use?lat=${lat}&lon=${lon}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [lat, lon]);

  const runRetrofit = useCallback(async () => {
    if (!lat || !lon) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/classify/retrofitting?lat=${lat}&lon=${lon}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [lat, lon]);

  const runForecast = useCallback(async () => {
    if (!lat || !lon) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/classify/forecast?lat=${lat}&lon=${lon}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [lat, lon]);

  const showOnMap = useCallback(async () => {
    if (!lat || !lon) return;
    try {
      const res = await fetch(`/classify/map-overlay?lat=${lat}&lon=${lon}`);
      if (!res.ok) return;
      const geojson = await res.json();
      setChatLayers(prev => [
        ...prev.filter(l => l.id !== "chat-land-classify"),
        {
          id: "chat-land-classify",
          geojson,
          layer_type: "fill",
          color: ["get", "color"],
        },
      ]);
    } catch {
      // ignore
    }
  }, [lat, lon, setChatLayers]);

  const themeColor = "#ff6f00";

  const recColor = (rec) => {
    if (rec === "HIGH_RETROFIT_POTENTIAL") return "#4caf50";
    if (rec === "MODERATE_RETROFIT_POTENTIAL") return "#ff9800";
    return "#f44336";
  };

  const pressureColor = (p) => {
    if (p === "high") return "#f44336";
    if (p === "moderate") return "#ff9800";
    return "#4caf50";
  };

  return (
    <div className="card" style={{ borderLeft: `3px solid ${themeColor}` }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, color: themeColor, flex: 1 }}>Land Classifier</h3>
        {["classify", "retrofit", "forecast"].map(v => (
          <button
            key={v}
            className={`tab-btn-sm ${view === v ? "active" : ""}`}
            style={view === v ? { background: themeColor, color: "#fff" } : { color: themeColor }}
            onClick={() => setView(v)}
          >{v === "classify" ? "Classify" : v === "retrofit" ? "Retrofit" : "Forecast"}</button>
        ))}
      </div>

      <button
        onClick={view === "classify" ? runClassify : view === "retrofit" ? runRetrofit : runForecast}
        disabled={loading || !lat || !lon}
        style={{
          background: themeColor, color: "#fff", border: "none", borderRadius: 4,
          padding: "6px 14px", fontSize: 12, cursor: "pointer", width: "100%", marginBottom: 8,
        }}
      >
        {loading ? "Analysing..." : view === "classify" ? "Run Classification" : view === "retrofit" ? "Assess Retrofitting" : "Forecast Changes"}
      </button>

      {error && <p style={{ color: "#f44336", fontSize: 12 }}>{error}</p>}

      {/* ── Classify tab ─────────────────────────────────── */}
      {view === "classify" && result && result.metadata && (
        <div>
          <div style={{ fontSize: 11, color: "#aaa", marginBottom: 6 }}>
            {result.metadata.total_cells} cells classified ({result.metadata.taxonomy_version})
          </div>

          {/* Class distribution stacked bar */}
          {result.metadata.class_distribution && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ display: "flex", height: 18, borderRadius: 4, overflow: "hidden", marginBottom: 6 }}>
                {Object.entries(result.metadata.class_distribution).map(([cls, pct]) => {
                  const tax = result.features?.find(f => f.properties?.class === cls);
                  const color = tax?.properties?.color || "#666";
                  return pct > 1 ? (
                    <div
                      key={cls}
                      style={{ width: `${pct}%`, background: color, minWidth: 2 }}
                      title={`${cls.replace(/_/g, " ")}: ${pct}%`}
                    />
                  ) : null;
                })}
              </div>
              {/* Legend */}
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {Object.entries(result.metadata.class_distribution).filter(([, p]) => p > 2).map(([cls, pct]) => {
                  const tax = result.features?.find(f => f.properties?.class === cls);
                  const color = tax?.properties?.color || "#666";
                  return (
                    <div key={cls} style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 10 }}>
                      <div style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
                      <span style={{ color: "#ccc" }}>{cls.replace(/_/g, " ")} {pct}%</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <button
            onClick={showOnMap}
            style={{
              background: "transparent", color: themeColor, border: `1px solid ${themeColor}`,
              borderRadius: 4, padding: "4px 12px", fontSize: 11, cursor: "pointer", width: "100%",
            }}
          >
            Show on Map
          </button>
        </div>
      )}

      {/* ── Retrofit tab ─────────────────────────────────── */}
      {view === "retrofit" && result && result.overall_retrofit_score !== undefined && (
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: recColor(result.recommendation) }}>
              {result.overall_retrofit_score}
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: recColor(result.recommendation) }}>
                {result.recommendation?.replace(/_/g, " ")}
              </div>
              <div style={{ fontSize: 11, color: "#aaa" }}>
                {result.total_solar_potential_kw?.toLocaleString()} kW solar potential
              </div>
            </div>
          </div>

          {/* Technology score bars */}
          {result.technology_scores && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {Object.entries(result.technology_scores).map(([tech, data]) => (
                <div key={tech}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#ccc", marginBottom: 2 }}>
                    <span>{tech.replace(/_/g, " ")}</span>
                    <span>{data.potential_kw ? `${data.potential_kw.toLocaleString()} kW` : `${data.units || 0} units`}</span>
                  </div>
                  <div style={{ height: 6, background: "#222", borderRadius: 3, overflow: "hidden" }}>
                    <div style={{
                      width: `${Math.min(data.score, 100)}%`, height: "100%",
                      background: data.score >= 70 ? "#4caf50" : data.score >= 40 ? "#ff9800" : "#f44336",
                      borderRadius: 3,
                    }} />
                  </div>
                </div>
              ))}
            </div>
          )}

          <div style={{ marginTop: 8, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            <div className="stat-box">
              <div className="stat-value" style={{ fontSize: 14 }}>{result.total_bess_potential_kw?.toLocaleString()}</div>
              <div className="stat-label">BESS kW</div>
            </div>
            <div className="stat-box">
              <div className="stat-value" style={{ fontSize: 14 }}>{result.total_ev_charging_units}</div>
              <div className="stat-label">EV Units</div>
            </div>
          </div>
        </div>
      )}

      {/* ── Forecast tab ─────────────────────────────────── */}
      {view === "forecast" && result && result.historical && (
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: pressureColor(result.development_pressure) }}>
              Development Pressure: {result.development_pressure?.toUpperCase()}
            </div>
            <div style={{ fontSize: 10, color: "#888" }}>
              Confidence: {Math.round((result.forecast_confidence || 0) * 100)}%
            </div>
          </div>

          {/* Trends */}
          {result.trends && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: "#aaa", marginBottom: 4 }}>Trends (%/yr)</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {Object.entries(result.trends)
                  .filter(([, v]) => Math.abs(v) > 0.05)
                  .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
                  .slice(0, 6)
                  .map(([cls, rate]) => (
                    <span key={cls} style={{
                      fontSize: 10, padding: "2px 6px", borderRadius: 3,
                      background: rate > 0 ? "rgba(76,175,80,0.15)" : "rgba(244,67,54,0.15)",
                      color: rate > 0 ? "#4caf50" : "#f44336",
                    }}>
                      {cls.replace(/_/g, " ")}: {rate > 0 ? "+" : ""}{rate.toFixed(2)}
                    </span>
                  ))}
              </div>
            </div>
          )}

          {/* Forecast table */}
          {result.forecast && (
            <div style={{ fontSize: 10 }}>
              <div style={{ color: "#aaa", marginBottom: 4 }}>Forecast ({result.forecast_years}yr)</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 4 }}>
                {Object.entries(result.forecast).slice(0, 3).map(([yr, data]) => (
                  <div key={yr} className="stat-box" style={{ padding: 4 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: themeColor, marginBottom: 2 }}>{yr}</div>
                    {Object.entries(data)
                      .sort((a, b) => b[1] - a[1])
                      .slice(0, 3)
                      .map(([cls, pct]) => (
                        <div key={cls} style={{ display: "flex", justifyContent: "space-between", color: "#ccc" }}>
                          <span>{cls.replace(/_/g, " ").slice(0, 10)}</span>
                          <span>{pct}%</span>
                        </div>
                      ))}
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.risk_summary && (
            <div style={{ marginTop: 8, fontSize: 11, color: "#aaa", fontStyle: "italic" }}>
              {result.risk_summary}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
