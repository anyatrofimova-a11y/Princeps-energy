import React, { useState, useCallback } from "react";
import api from "../services/api";

const TABS = [
  { id: "routes", label: "Routes" },
  { id: "ppa", label: "PPA" },
  { id: "offtake", label: "Offtake" },
  { id: "risk", label: "Risk" },
];

const REGIONS = ["Scotland", "North", "Midlands", "South"];
const TECHNOLOGIES = ["wind", "solar", "bess"];
const PPA_STRUCTURES = ["fixed", "indexed", "floor_cap", "baseload", "shaped", "synthetic"];
const ROUTES_LIST = ["merchant", "cfd", "corporate_ppa", "sleeved_ppa", "synthetic_ppa", "private_wire"];

function fmt(v) { return v == null ? "—" : typeof v === "number" ? v.toLocaleString() : String(v); }

/* ── SVG Charts ──────────────────────────────────────────────────────── */

function RouteComparisonChart({ routes }) {
  if (!routes?.length) return null;
  const w = 460, h = 140, pad = 30;
  const maxNpv = Math.max(...routes.map(r => r.total_npv_gbp || 0), 1);
  const barH = Math.min(16, (h - pad) / routes.length - 2);

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="rtm-chart" style={{ width: "100%", height: Math.min(h, 140) }}>
      {routes.map((r, i) => {
        const bW = ((r.total_npv_gbp || 0) / maxNpv) * (w - pad - 120);
        const y = pad / 2 + i * (barH + 4);
        const certColor = r.revenue_certainty >= 0.8 ? "#22c55e" : r.revenue_certainty >= 0.5 ? "#f59e0b" : "#ef4444";
        return (
          <g key={i}>
            <text x={pad - 4} y={y + barH / 2 + 3} textAnchor="end" fontSize="8" fill="#94a3b8">
              {r.label?.split(" ")[0]}
            </text>
            <rect x={pad} y={y} width={Math.max(2, bW)} height={barH} fill="#3b82f6" rx={2} opacity={0.7}>
              <title>{r.label}: NPV £{fmt(r.total_npv_gbp)}, Certainty {(r.revenue_certainty * 100).toFixed(0)}%</title>
            </rect>
            <circle cx={pad + bW + 10} cy={y + barH / 2} r={4} fill={certColor} />
            <text x={pad + bW + 20} y={y + barH / 2 + 3} fontSize="7" fill="#c6c6c6">
              £{(r.total_npv_gbp / 1e6).toFixed(1)}M
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function PpaTermChart({ terms }) {
  if (!terms?.length) return null;
  const w = 460, h = 100, pad = 30;
  const maxNpv = Math.max(...terms.map(t => t.lifetime_npv_gbp || 0), 1);

  const points = terms.map((t, i) => {
    const x = pad + (i / (terms.length - 1)) * (w - pad * 2);
    const y = h - pad - ((t.lifetime_npv_gbp || 0) / maxNpv) * (h - pad - 10);
    return `${x},${y}`;
  }).join(" ");

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="rtm-chart" style={{ width: "100%", height: 100 }}>
      <polyline points={points} fill="none" stroke="#78a9ff" strokeWidth={1.5} />
      {terms.map((t, i) => {
        const x = pad + (i / (terms.length - 1)) * (w - pad * 2);
        const y = h - pad - ((t.lifetime_npv_gbp || 0) / maxNpv) * (h - pad - 10);
        return (
          <g key={i}>
            <circle cx={x} cy={y} r={3} fill="#78a9ff" />
            <text x={x} y={h - pad + 12} textAnchor="middle" fontSize="7" fill="#64748b">{t.term_years}yr</text>
          </g>
        );
      })}
      <line x1={pad} y1={h - pad} x2={w - 10} y2={h - pad} stroke="#334155" strokeWidth={0.5} />
    </svg>
  );
}

function TornadoChart({ tornado, baseNpv }) {
  if (!tornado?.length) return null;
  const w = 460, h = 160, pad = 100, rightPad = 20;
  const barH = Math.min(14, (h - 20) / tornado.length - 2);
  const top5 = tornado.slice(0, 5);
  const maxSwing = Math.max(...top5.map(t => Math.max(Math.abs(t.npv_low_gbp - baseNpv), Math.abs(t.npv_high_gbp - baseNpv))), 1);
  const centerX = pad + (w - pad - rightPad) / 2;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="rtm-chart" style={{ width: "100%", height: Math.min(h, 160) }}>
      <line x1={centerX} y1={5} x2={centerX} y2={h - 10} stroke="#475569" strokeWidth={0.5} strokeDasharray="3,2" />
      {top5.map((t, i) => {
        const y = 10 + i * (barH + 6);
        const halfW = (w - pad - rightPad) / 2;
        const lowDelta = t.npv_low_gbp - baseNpv;
        const highDelta = t.npv_high_gbp - baseNpv;
        const lowX = centerX + (lowDelta / maxSwing) * halfW * 0.9;
        const highX = centerX + (highDelta / maxSwing) * halfW * 0.9;

        return (
          <g key={i}>
            <text x={pad - 4} y={y + barH / 2 + 3} textAnchor="end" fontSize="8" fill="#94a3b8">{t.variable}</text>
            <rect x={Math.min(lowX, centerX)} y={y} width={Math.abs(centerX - lowX)} height={barH} fill="#ef4444" opacity={0.6} rx={1}>
              <title>-20%: £{(t.npv_low_gbp / 1e6).toFixed(1)}M</title>
            </rect>
            <rect x={centerX} y={y} width={Math.abs(highX - centerX)} height={barH} fill="#22c55e" opacity={0.6} rx={1}>
              <title>+20%: £{(t.npv_high_gbp / 1e6).toFixed(1)}M</title>
            </rect>
            <text x={w - rightPad} y={y + barH / 2 + 3} fontSize="7" fill="#6f6f6f">{t.npv_swing_pct}%</text>
          </g>
        );
      })}
    </svg>
  );
}

function CorrelationChart({ hourly }) {
  if (!hourly?.length) return null;
  const w = 460, h = 100, pad = 30;

  const genPts = hourly.map((hr, i) => {
    const x = pad + (i / 23) * (w - pad * 2);
    const y = h - pad - hr.generation * (h - pad - 10);
    return `${x},${y}`;
  }).join(" ");

  const demPts = hourly.map((hr, i) => {
    const x = pad + (i / 23) * (w - pad * 2);
    const y = h - pad - hr.demand * (h - pad - 10);
    return `${x},${y}`;
  }).join(" ");

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="rtm-chart" style={{ width: "100%", height: 100 }}>
      <polyline points={genPts} fill="none" stroke="#22c55e" strokeWidth={1.5} />
      <polyline points={demPts} fill="none" stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="4,2" />
      <line x1={pad} y1={h - pad} x2={w - 10} y2={h - pad} stroke="#334155" strokeWidth={0.5} />
      <circle cx={pad + 10} cy={h - 5} r={3} fill="#22c55e" />
      <text x={pad + 18} y={h - 2} fontSize="7" fill="#94a3b8">Generation</text>
      <circle cx={pad + 85} cy={h - 5} r={3} fill="#f59e0b" />
      <text x={pad + 93} y={h - 2} fontSize="7" fill="#94a3b8">Demand</text>
    </svg>
  );
}

/* ── Main Panel ──────────────────────────────────────────────────────── */

export default function RouteToMarketPanel({ onClose }) {
  const [tab, setTab] = useState("routes");
  const [loading, setLoading] = useState(false);

  // Shared controls
  const [capacityMw, setCapacityMw] = useState(50);
  const [region, setRegion] = useState("Scotland");
  const [technology, setTechnology] = useState("wind");
  const [termYears, setTermYears] = useState(15);

  // Tab data
  const [routesData, setRoutesData] = useState(null);
  const [ppaData, setPpaData] = useState(null);
  const [ppaTerms, setPpaTerms] = useState(null);
  const [offtakeData, setOfftakeData] = useState(null);
  const [correlationData, setCorrelationData] = useState(null);
  const [riskData, setRiskData] = useState(null);
  const [sensitivityData, setSensitivityData] = useState(null);

  const run = useCallback(async (fn) => {
    setLoading(true);
    try { await fn(); } catch (e) { console.error(e); }
    setLoading(false);
  }, []);

  const loadRoutes = () => run(async () => {
    const d = await api.rtm.routesCompare(capacityMw, technology, region);
    setRoutesData(d);
  });

  const loadPpa = () => run(async () => {
    const [structs, terms] = await Promise.all([
      api.rtm.ppaStructures(capacityMw, technology, region, termYears),
      api.rtm.ppaTerms(capacityMw, technology, region),
    ]);
    setPpaData(structs);
    setPpaTerms(terms);
  });

  const loadOfftake = () => run(async () => {
    const [matches, corr] = await Promise.all([
      api.rtm.offtakeMatch(capacityMw, technology, region),
      api.rtm.offtakeCorrelation(technology, "data_centre"),
    ]);
    setOfftakeData(matches);
    setCorrelationData(corr);
  });

  const loadRisk = () => run(async () => {
    const best = routesData?.recommendation?.best_route || "cfd";
    const [risk, sens] = await Promise.all([
      api.rtm.riskAssessment(capacityMw, technology, region, best),
      api.rtm.riskSensitivity(capacityMw, technology, region, best),
    ]);
    setRiskData(risk);
    setSensitivityData(sens);
  });

  const handleRun = () => {
    if (tab === "routes") loadRoutes();
    else if (tab === "ppa") loadPpa();
    else if (tab === "offtake") loadOfftake();
    else if (tab === "risk") loadRisk();
  };

  return (
    <div className="gc-panel rtm-panel">
      <div className="gc-panel-header">
        <span className="gc-panel-title">Route to Market</span>
        <button className="gc-panel-close" onClick={onClose}>&times;</button>
      </div>

      <div className="dp-tabs">
        {TABS.map(t => (
          <button key={t.id} className={`dp-tab${tab === t.id ? " active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="dp-controls">
        <label>Capacity<input type="number" value={capacityMw} onChange={e => setCapacityMw(+e.target.value)} min={1} max={500} /></label>
        <label>Region<select value={region} onChange={e => setRegion(e.target.value)}>
          {REGIONS.map(r => <option key={r}>{r}</option>)}
        </select></label>
        <label>Tech<select value={technology} onChange={e => setTechnology(e.target.value)}>
          {TECHNOLOGIES.map(t => <option key={t}>{t}</option>)}
        </select></label>
        {tab === "ppa" && (
          <label>Term<input type="number" value={termYears} onChange={e => setTermYears(+e.target.value)} min={3} max={25} /></label>
        )}
      </div>

      <button className="dp-run-btn" onClick={handleRun} disabled={loading}>
        {loading ? "Loading..." : "Run Analysis"}
      </button>

      <div className="dp-body">
        {/* ═══ ROUTES TAB ═══ */}
        {tab === "routes" && routesData && (
          <>
            {routesData.recommendation && (
              <div className={`rtm-verdict rtm-verdict-${routesData.recommendation.verdict?.toLowerCase()}`}>
                <div className="rtm-verdict-label">{routesData.recommendation.verdict}</div>
                <div className="rtm-verdict-route">{routesData.recommendation.best_label}</div>
                <div className="rtm-verdict-score">Score: {routesData.recommendation.composite_score}</div>
              </div>
            )}

            <h4 className="dp-section-title">Route Comparison (NPV)</h4>
            <RouteComparisonChart routes={routesData.routes} />

            <div className="dp-table-wrap">
              <table className="dp-table">
                <thead><tr><th>Route</th><th>Price</th><th>NPV</th><th>Certainty</th><th>Bank.</th><th>Score</th></tr></thead>
                <tbody>
                  {routesData.routes?.map((r, i) => (
                    <tr key={i} className={r.route === routesData.recommendation?.best_route ? "dp-row-highlight" : ""}>
                      <td>{r.label}</td>
                      <td>£{r.effective_price_gbp_mwh}</td>
                      <td>£{(r.total_npv_gbp / 1e6).toFixed(1)}M</td>
                      <td>{(r.revenue_certainty * 100).toFixed(0)}%</td>
                      <td>{(r.bankability * 100).toFixed(0)}%</td>
                      <td><strong>{r.composite_score}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* ═══ PPA TAB ═══ */}
        {tab === "ppa" && ppaData && (
          <>
            <div className="dp-stat-row">
              <div className="dp-stat">
                <span className="dp-stat-label">Recommended</span>
                <span className="dp-stat-value" style={{ fontSize: 11 }}>
                  {ppaData.structures?.[0]?.label}
                </span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Capture Ratio</span>
                <span className="dp-stat-value">{(ppaData.market_context?.capture_ratio * 100)?.toFixed(1)}%</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Fwd Curve</span>
                <span className="dp-stat-value">£{ppaData.market_context?.forward_curve_avg}</span>
              </div>
            </div>

            <div className="dp-table-wrap">
              <table className="dp-table">
                <thead><tr><th>Structure</th><th>Price</th><th>NPV</th><th>Certainty</th><th>Bank.</th></tr></thead>
                <tbody>
                  {ppaData.structures?.map((s, i) => (
                    <tr key={i} className={i === 0 ? "dp-row-highlight" : ""}>
                      <td>{s.label}</td>
                      <td>£{s.ppa_price_gbp_mwh}</td>
                      <td>£{(s.lifetime_npv_gbp / 1e6).toFixed(1)}M</td>
                      <td>{(s.revenue_certainty * 100).toFixed(0)}%</td>
                      <td>{s.bankability_score}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {ppaTerms?.terms && (
              <>
                <h4 className="dp-section-title">Term Analysis (NPV by Term Length)</h4>
                <PpaTermChart terms={ppaTerms.terms} />
                {ppaTerms.recommendation && (
                  <div className="rtm-recommendation">{ppaTerms.recommendation.rationale}</div>
                )}
              </>
            )}
          </>
        )}

        {/* ═══ OFFTAKE TAB ═══ */}
        {tab === "offtake" && offtakeData && (
          <>
            <div className="dp-stat-row">
              <div className="dp-stat">
                <span className="dp-stat-label">Top Match</span>
                <span className="dp-stat-value" style={{ fontSize: 11 }}>{offtakeData.top_match?.label}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Score</span>
                <span className="dp-stat-value">{offtakeData.top_match?.score}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Strong</span>
                <span className="dp-stat-value">{offtakeData.market_summary?.strong_matches}</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Suitable</span>
                <span className="dp-stat-value">{offtakeData.market_summary?.suitable_matches}</span>
              </div>
            </div>

            <div className="dp-table-wrap">
              <table className="dp-table">
                <thead><tr><th>Buyer</th><th>Credit</th><th>Score</th><th>Vol</th><th>Shape</th><th>Rec</th></tr></thead>
                <tbody>
                  {offtakeData.matches?.map((m, i) => (
                    <tr key={i} className={m.recommendation === "STRONG" ? "dp-row-highlight" : ""}>
                      <td>{m.label}</td>
                      <td style={{ fontSize: 9 }}>{m.credit_rating?.replace("_", " ")}</td>
                      <td><strong>{m.composite_score}</strong></td>
                      <td>{m.volume_match?.toFixed(0)}</td>
                      <td>{m.shape_correlation?.toFixed(2)}</td>
                      <td>
                        <span className={`dp-risk-pill dp-risk-${m.recommendation === "STRONG" ? "low" : m.recommendation === "SUITABLE" ? "medium" : "high"}`}>
                          {m.recommendation}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {correlationData?.hourly_analysis && (
              <>
                <h4 className="dp-section-title">
                  Generation vs Demand Correlation ({correlationData.correlation_label})
                </h4>
                <CorrelationChart hourly={correlationData.hourly_analysis} />
              </>
            )}
          </>
        )}

        {/* ═══ RISK TAB ═══ */}
        {tab === "risk" && riskData && (
          <>
            <div className="dp-stat-row">
              <div className="dp-stat">
                <span className="dp-stat-label">P10 Revenue</span>
                <span className="dp-stat-value">£{(riskData.revenue_at_risk?.p10_annual_gbp / 1e6)?.toFixed(1)}M</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">P50 Revenue</span>
                <span className="dp-stat-value">£{(riskData.revenue_at_risk?.p50_annual_gbp / 1e6)?.toFixed(1)}M</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">P90 Revenue</span>
                <span className="dp-stat-value">£{(riskData.revenue_at_risk?.p90_annual_gbp / 1e6)?.toFixed(1)}M</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">DSCR P50</span>
                <span className="dp-stat-value">{riskData.dscr_distribution?.p50}x</span>
              </div>
            </div>

            <div className="dp-stat-row">
              <div className="dp-stat">
                <span className="dp-stat-label">P10 NPV</span>
                <span className="dp-stat-value">£{(riskData.npv_distribution?.p10_gbp / 1e6)?.toFixed(1)}M</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">P50 NPV</span>
                <span className="dp-stat-value">£{(riskData.npv_distribution?.p50_gbp / 1e6)?.toFixed(1)}M</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">DSCR Breach</span>
                <span className="dp-stat-value">{riskData.dscr_distribution?.prob_below_1_1}%</span>
              </div>
              <div className="dp-stat">
                <span className="dp-stat-label">Risks</span>
                <span className="dp-stat-value">{riskData.risk_summary?.total_risks}</span>
              </div>
            </div>

            {sensitivityData?.tornado && (
              <>
                <h4 className="dp-section-title">Sensitivity Tornado (±20%)</h4>
                <TornadoChart tornado={sensitivityData.tornado} baseNpv={sensitivityData.base_case?.npv_gbp || 0} />
              </>
            )}

            {riskData.risk_summary?.category_summary && (
              <>
                <h4 className="dp-section-title">Risk by Category</h4>
                <div className="dp-breakdown">
                  {riskData.risk_summary.category_summary.map((c, i) => (
                    <div className="dp-breakdown-row" key={i}>
                      <span>{c.category} ({c.risk_count})</span>
                      <span className={`dp-risk-pill dp-risk-${c.severity?.toLowerCase()}`}>
                        {c.weighted_impact_pct}%
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {riskData.top_risks?.length > 0 && (
              <>
                <h4 className="dp-section-title">Top Risks</h4>
                <div className="dp-table-wrap">
                  <table className="dp-table">
                    <thead><tr><th>Risk</th><th>Cat</th><th>Prob</th><th>Impact</th><th>Mitigation</th></tr></thead>
                    <tbody>
                      {riskData.top_risks.slice(0, 6).map((r, i) => (
                        <tr key={i}>
                          <td>{r.name}</td>
                          <td style={{ fontSize: 9 }}>{r.category}</td>
                          <td>{(r.probability * 100).toFixed(0)}%</td>
                          <td>{r.impact_pct}%</td>
                          <td style={{ fontSize: 9 }}>{r.mitigation}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}

        {!loading && !routesData && !ppaData && !offtakeData && !riskData && (
          <div className="dp-empty">Click "Run Analysis" to load data for the selected tab.</div>
        )}
      </div>

      <div className="dp-footer">
        Phase 10 — PPA Structuring & Route-to-Market
      </div>
    </div>
  );
}
