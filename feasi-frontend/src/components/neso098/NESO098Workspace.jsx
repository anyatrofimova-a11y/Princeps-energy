/**
 * NESO098 DC Optimiser Workspace — implements NIA2_NESO098 methodology.
 *
 * Light-themed analytical workspace with four zones:
 *   • Left — input controls (lat/lon/capacity/latency/dc_type/overrides)
 *   • Top-center — the 9-criteria radar chart + composite score + verdict
 *   • Middle — demand forecast heatmap (scenario × year × type × latency)
 *   • Right — consolidated DC estate summary
 *
 * Positions Princeps as the productised implementation of the NESO098 project
 * (NESO × McKinsey, Dec 2024 – Feb 2025, £530k NIA2, fed FES 2025 + SSEP).
 */
import React, { useState, useEffect, useCallback, useMemo } from "react";
import api from "../../services/api";

const C = {
  bg:        "#f7f8fa",
  card:      "#ffffff",
  border:    "#e5e7eb",
  text:      "#0f172a",
  textDim:   "#64748b",
  textMuted: "#94a3b8",
  gold:      "#f5b731",
  green:     "#16a34a",
  amber:     "#d97706",
  red:       "#dc2626",
  blue:      "#2563eb",
  purple:    "#7c3aed",
  heatLow:   "#dbeafe",
  heatMid:   "#fde68a",
  heatHi:    "#fecaca",
};

const ST = {
  page: {
    height: "100%",
    overflowY: "auto",
    background: C.bg,
    fontFamily: "'DM Sans', 'Inter', system-ui, sans-serif",
    color: C.text,
  },
  inner: { maxWidth: 1600, margin: "0 auto", padding: "22px 28px 64px" },
  header: { marginBottom: 18 },
  title: { fontSize: 22, fontWeight: 800, margin: 0, letterSpacing: -0.3 },
  subtitle: {
    fontSize: 12, color: C.textDim, marginTop: 4, maxWidth: 900,
  },
  sourceTag: {
    display: "inline-block",
    marginTop: 8,
    padding: "4px 10px",
    background: C.gold + "22",
    color: "#92400e",
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 0.4,
    textTransform: "uppercase",
    borderRadius: 10,
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "280px 1fr 320px",
    gap: 16,
    marginTop: 18,
  },
  panel: {
    background: C.card,
    border: `1px solid ${C.border}`,
    borderRadius: 12,
    padding: 18,
    boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
  },
  panelTitle: {
    fontSize: 11, fontWeight: 700, color: C.textDim,
    textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 14,
  },
  label: {
    fontSize: 10, fontWeight: 700, color: C.textDim,
    letterSpacing: 0.6, textTransform: "uppercase", marginBottom: 5,
  },
  input: {
    width: "100%",
    padding: "8px 12px",
    border: `1px solid ${C.border}`,
    borderRadius: 8,
    fontSize: 13,
    fontFamily: "'DM Sans', sans-serif",
    background: "#fff",
    marginBottom: 12,
  },
  select: {
    width: "100%",
    padding: "8px 12px",
    border: `1px solid ${C.border}`,
    borderRadius: 8,
    fontSize: 13,
    fontFamily: "'DM Sans', sans-serif",
    background: "#fff",
    marginBottom: 12,
    cursor: "pointer",
  },
  runButton: {
    width: "100%",
    padding: "10px 18px",
    background: C.text,
    color: "#fff",
    border: "none",
    borderRadius: 8,
    fontSize: 12,
    fontWeight: 700,
    cursor: "pointer",
    letterSpacing: 0.3,
    marginTop: 6,
  },
  verdictBadge: (col) => ({
    display: "inline-block",
    padding: "6px 14px",
    borderRadius: 14,
    background: col,
    color: "#fff",
    fontSize: 12,
    fontWeight: 800,
    letterSpacing: 0.8,
  }),
  compositeValue: {
    fontSize: 48,
    fontWeight: 800,
    fontFamily: "'JetBrains Mono', monospace",
    color: C.text,
    lineHeight: 1,
    letterSpacing: -1,
  },
  compositeLabel: {
    fontSize: 10,
    color: C.textDim,
    textTransform: "uppercase",
    letterSpacing: 0.6,
    marginTop: 4,
  },
  criterionRow: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "7px 0",
    borderBottom: `1px dashed ${C.border}`,
    fontSize: 12,
  },
  criterionLabel: { flex: 1, color: C.textDim, textTransform: "capitalize" },
  criterionBar: {
    flex: 2,
    height: 6,
    background: "#eef2f7",
    borderRadius: 3,
    overflow: "hidden",
    position: "relative",
  },
  criterionFill: (score) => ({
    width: `${score}%`,
    height: "100%",
    background: score >= 70 ? C.green : score >= 50 ? C.amber : C.red,
    transition: "width 0.5s",
  }),
  criterionScore: {
    width: 32,
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 11,
    fontWeight: 700,
    textAlign: "right",
  },
  headerNumbers: {
    display: "flex",
    gap: 22,
    marginBottom: 16,
    alignItems: "center",
  },
  headerNumberBlock: {
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  scenarioRow: {
    display: "flex",
    gap: 6,
    flexWrap: "wrap",
    marginBottom: 10,
  },
  scenarioPill: (active) => ({
    padding: "5px 10px",
    fontSize: 10,
    fontWeight: 600,
    background: active ? C.text : C.card,
    color: active ? "#fff" : C.text,
    border: `1px solid ${active ? C.text : C.border}`,
    borderRadius: 14,
    cursor: "pointer",
    letterSpacing: 0.3,
  }),
  row: {
    display: "flex",
    justifyContent: "space-between",
    padding: "6px 0",
    borderBottom: `1px dashed ${C.border}`,
    fontSize: 12,
  },
  rowLabel: { color: C.textDim },
  rowValue: { fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 },
};


export default function NESO098Workspace() {
  const [criteriaMeta, setCriteriaMeta] = useState(null);
  const [estate, setEstate] = useState(null);
  const [params, setParams] = useState({
    site_id: "test-site",
    lat: 51.55,
    lon: -0.27,
    capacity_mva: 120,
    dc_type: "hyperscaler",
    latency_class: "regionally_constrained",
  });
  const [score, setScore] = useState(null);
  const [forecast, setForecast] = useState([]);
  const [scenario, setScenario] = useState("moderate");
  const [loadingScore, setLoadingScore] = useState(false);
  const [loadingForecast, setLoadingForecast] = useState(false);

  // Initial load — criteria + estate summary + existing forecast
  useEffect(() => {
    (async () => {
      try {
        const [meta, est] = await Promise.allSettled([
          api.neso098.criteria(),
          api.neso098.estateSummary(),
        ]);
        if (meta.status === "fulfilled") setCriteriaMeta(meta.value);
        if (est.status === "fulfilled") setEstate(est.value);
      } catch (e) {
        console.warn("[NESO098] load failed:", e);
      }
    })();
  }, []);

  // Load forecast when scenario changes (build if empty)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoadingForecast(true);
      try {
        let data = await api.neso098.forecast(scenario);
        if (!data.rows || data.rows.length === 0) {
          await api.neso098.forecastBuild(scenario);
          data = await api.neso098.forecast(scenario);
        }
        if (!cancelled) setForecast(data.rows || []);
      } catch (e) {
        console.warn("[NESO098] forecast failed:", e);
      } finally {
        if (!cancelled) setLoadingForecast(false);
      }
    })();
    return () => { cancelled = true; };
  }, [scenario]);

  const runScore = useCallback(async () => {
    setLoadingScore(true);
    try {
      const res = await api.neso098.scoreSite({
        ...params,
        lat: Number(params.lat),
        lon: Number(params.lon),
        capacity_mva: Number(params.capacity_mva),
      });
      setScore(res);
    } catch (e) {
      console.warn("[NESO098] score failed:", e);
    } finally {
      setLoadingScore(false);
    }
  }, [params]);

  const update = (k) => (e) => setParams(p => ({ ...p, [k]: e.target.value }));

  const verdictColour =
    score?.verdict === "GO" ? C.green :
    score?.verdict === "CAUTION" ? C.amber : C.red;

  // Aggregate forecast by year for the headline chart
  const forecastByYear = useMemo(() => {
    const map = {};
    for (const row of forecast) {
      if (!map[row.year]) map[row.year] = { year: row.year, demand: 0, gap: 0 };
      map[row.year].demand += Number(row.mw_demand || 0);
      map[row.year].gap += Math.max(0, Number(row.gap_mw || 0));
    }
    return Object.values(map).sort((a, b) => a.year - b.year);
  }, [forecast]);

  const SCENARIOS = [
    { id: "conservative",    label: "Conservative" },
    { id: "moderate",        label: "Moderate" },
    { id: "ai_heavy",        label: "AI Heavy" },
    { id: "fes_leading_the_way", label: "FES LTW" },
    { id: "fes_consumer_transf", label: "FES CT" },
    { id: "fes_system_transf",   label: "FES ST" },
    { id: "fes_falling_short",   label: "FES FS" },
  ];

  return (
    <div style={ST.page}>
      <div style={ST.inner}>
        <div style={ST.header}>
          <h1 style={ST.title}>NESO098 DC Optimiser</h1>
          <div style={ST.subtitle}>
            Productised implementation of NIA2_NESO098 "Options for optimising GB Data Centres"
            (NESO × McKinsey, Dec 2024 – Feb 2025, £530k NIA2). 9-criteria location scorecard + top-down
            demand forecast 2024-2040 + consolidated GB DC estate view.
          </div>
          <div style={ST.sourceTag}>
            FES 2025 · SSEP · AI Opportunities Action Plan methodology
          </div>
        </div>

        {/* ── 3-column grid ── */}
        <div style={ST.grid}>
          {/* LEFT — Inputs */}
          <div style={ST.panel}>
            <div style={ST.panelTitle}>Site parameters</div>

            <div style={ST.label}>Site ID</div>
            <input style={ST.input} value={params.site_id} onChange={update("site_id")} />

            <div style={ST.label}>Latitude</div>
            <input style={ST.input} type="number" step="0.001" value={params.lat} onChange={update("lat")} />

            <div style={ST.label}>Longitude</div>
            <input style={ST.input} type="number" step="0.001" value={params.lon} onChange={update("lon")} />

            <div style={ST.label}>Capacity (MVA)</div>
            <input style={ST.input} type="number" value={params.capacity_mva} onChange={update("capacity_mva")} />

            <div style={ST.label}>DC type</div>
            <select style={ST.select} value={params.dc_type} onChange={update("dc_type")}>
              <option value="hyperscaler">Hyperscaler (100+ MW)</option>
              <option value="colocation">Co-location (multi-tenant)</option>
              <option value="enterprise">Enterprise (on-premise)</option>
            </select>

            <div style={ST.label}>Latency class</div>
            <select style={ST.select} value={params.latency_class} onChange={update("latency_class")}>
              <option value="locally_constrained">Locally constrained (≤5ms)</option>
              <option value="regionally_constrained">Regionally constrained (≤20ms)</option>
              <option value="nationally_constrained">Nationally constrained (GB only)</option>
              <option value="unconstrained">Unconstrained (globally flex)</option>
            </select>

            <button style={ST.runButton} onClick={runScore} disabled={loadingScore}>
              {loadingScore ? "Scoring…" : "Score site"}
            </button>
          </div>

          {/* CENTER — Score + Forecast */}
          <div>
            {/* Score panel */}
            <div style={{ ...ST.panel, marginBottom: 16 }}>
              <div style={ST.panelTitle}>9-criteria location score</div>
              {score ? (
                <>
                  <div style={ST.headerNumbers}>
                    <div style={ST.headerNumberBlock}>
                      <div style={ST.compositeValue}>{score.composite}</div>
                      <div style={ST.compositeLabel}>Composite / 100</div>
                    </div>
                    <div style={ST.headerNumberBlock}>
                      <div style={ST.verdictBadge(verdictColour)}>{score.verdict}</div>
                      <div style={{ fontSize: 11, color: C.textDim, marginTop: 6 }}>
                        {params.dc_type} · {params.latency_class.replace(/_/g, " ")} · {params.capacity_mva} MVA
                      </div>
                    </div>
                  </div>

                  {Object.entries(score.scores).map(([k, v]) => (
                    <div key={k} style={ST.criterionRow}>
                      <span style={ST.criterionLabel}>
                        {k.replace(/_/g, " ")}
                        <span style={{ fontSize: 9, color: C.textMuted, marginLeft: 6 }}>
                          ({(score.weights[k] * 100).toFixed(0)}%)
                        </span>
                      </span>
                      <div style={ST.criterionBar}>
                        <div style={ST.criterionFill(Number(v))} />
                      </div>
                      <span style={ST.criterionScore}>{Number(v).toFixed(0)}</span>
                    </div>
                  ))}
                </>
              ) : (
                <div style={{ padding: 24, color: C.textDim, fontSize: 12, textAlign: "center" }}>
                  Enter site parameters and click <b>Score site</b> to run the 9-criteria scorecard.
                </div>
              )}
            </div>

            {/* Forecast panel */}
            <div style={ST.panel}>
              <div style={ST.panelTitle}>GB DC demand forecast 2024–2040</div>
              <div style={ST.scenarioRow}>
                {SCENARIOS.map(s => (
                  <button
                    key={s.id}
                    style={ST.scenarioPill(s.id === scenario)}
                    onClick={() => setScenario(s.id)}
                  >
                    {s.label}
                  </button>
                ))}
              </div>

              {loadingForecast ? (
                <div style={{ padding: 20, color: C.textDim, fontSize: 12, textAlign: "center" }}>
                  Building {scenario} scenario…
                </div>
              ) : forecastByYear.length > 0 ? (
                <ForecastChart data={forecastByYear} />
              ) : (
                <div style={{ padding: 20, color: C.textMuted, fontSize: 12, textAlign: "center" }}>
                  No forecast data
                </div>
              )}
            </div>
          </div>

          {/* RIGHT — Estate summary */}
          <div style={ST.panel}>
            <div style={ST.panelTitle}>Consolidated GB DC estate</div>

            {estate?.totals ? (
              <>
                <div style={{ ...ST.headerNumberBlock, marginBottom: 12 }}>
                  <div style={{ ...ST.compositeValue, fontSize: 32 }}>
                    {(estate.totals.total || 0).toLocaleString()}
                  </div>
                  <div style={ST.compositeLabel}>DCs tracked</div>
                </div>

                <div style={ST.row}>
                  <span style={ST.rowLabel}>Operational</span>
                  <span style={{ ...ST.rowValue, color: C.green }}>{estate.totals.operational || 0}</span>
                </div>
                <div style={ST.row}>
                  <span style={ST.rowLabel}>Pipeline</span>
                  <span style={{ ...ST.rowValue, color: C.amber }}>{estate.totals.pipeline || 0}</span>
                </div>
                <div style={ST.row}>
                  <span style={ST.rowLabel}>Total IT power</span>
                  <span style={ST.rowValue}>{Math.round(estate.totals.total_it_power_mw || 0).toLocaleString()} MW</span>
                </div>
                <div style={ST.row}>
                  <span style={ST.rowLabel}>Total facility</span>
                  <span style={ST.rowValue}>{Math.round(estate.totals.total_facility_power_mw || 0).toLocaleString()} MW</span>
                </div>
                <div style={ST.row}>
                  <span style={ST.rowLabel}>Avg PUE</span>
                  <span style={ST.rowValue}>{Number(estate.totals.avg_pue || 0).toFixed(2)}</span>
                </div>

                {estate.by_type?.length > 0 && (
                  <div style={{ marginTop: 14 }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: C.textMuted, letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 6 }}>
                      By DC type
                    </div>
                    {estate.by_type.map(t => (
                      <div key={t.dc_type} style={ST.row}>
                        <span style={ST.rowLabel}>{t.dc_type}</span>
                        <span style={ST.rowValue}>{t.n} · {Math.round(t.mw_total)} MW</span>
                      </div>
                    ))}
                  </div>
                )}

                {estate.by_latency?.length > 0 && (
                  <div style={{ marginTop: 14 }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: C.textMuted, letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 6 }}>
                      By latency class
                    </div>
                    {estate.by_latency.map(t => (
                      <div key={t.latency_class} style={ST.row}>
                        <span style={{ ...ST.rowLabel, fontSize: 10 }}>{t.latency_class?.replace(/_/g, " ")}</span>
                        <span style={{ ...ST.rowValue, fontSize: 11 }}>{t.n} · {Math.round(t.mw_total)} MW</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <div style={{ fontSize: 11, color: C.textMuted }}>
                Estate is empty. Drop the <code>UKPN_ODS_APIKEY</code> and I'll populate from the UKPN Large Demand List + NGED ECR.
              </div>
            )}

            {criteriaMeta?.source && (
              <div style={{
                marginTop: 18,
                padding: "8px 10px",
                background: "#f8fafc",
                borderLeft: `3px solid ${C.gold}`,
                fontSize: 10,
                color: C.textDim,
                fontStyle: "italic",
                lineHeight: 1.45,
              }}>
                {criteriaMeta.source}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}


function ForecastChart({ data }) {
  if (!data || data.length === 0) return null;
  const maxDemand = Math.max(...data.map(d => d.demand));
  const h = 180;
  const w = Math.max(520, data.length * 24);
  const step = w / Math.max(1, data.length - 1);
  const points = data.map((d, i) => {
    const x = i * step;
    const y = h - (d.demand / maxDemand) * (h - 20) - 10;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  return (
    <div style={{ overflowX: "auto" }}>
      <svg width={w + 40} height={h + 30} style={{ display: "block" }}>
        {/* Bars for gap */}
        {data.map((d, i) => {
          const x = 20 + i * step - 6;
          const gapH = (d.gap / maxDemand) * (h - 20);
          return (
            <rect
              key={d.year}
              x={x}
              y={h - gapH - 10}
              width={12}
              height={gapH}
              fill="#fecaca"
              opacity={0.6}
            />
          );
        })}
        {/* Demand line */}
        <polyline
          points={points.split(" ").map(p => {
            const [x, y] = p.split(",");
            return `${Number(x) + 20},${y}`;
          }).join(" ")}
          fill="none"
          stroke="#0f172a"
          strokeWidth={2}
        />
        {/* Axis labels */}
        {data.filter((_, i) => i % 4 === 0).map((d, i) => (
          <text
            key={d.year}
            x={20 + data.indexOf(d) * step}
            y={h + 16}
            fontSize={9}
            fill="#64748b"
            textAnchor="middle"
          >{d.year}</text>
        ))}
      </svg>
      <div style={{ display: "flex", gap: 18, marginTop: 6, fontSize: 10, color: "#64748b" }}>
        <span><span style={{ display: "inline-block", width: 12, height: 2, background: "#0f172a", marginRight: 4, verticalAlign: "middle" }} /> Total MW demand</span>
        <span><span style={{ display: "inline-block", width: 10, height: 10, background: "#fecaca", marginRight: 4, verticalAlign: "middle" }} /> Supply gap</span>
      </div>
    </div>
  );
}
