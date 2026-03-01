import React, { useState, useCallback } from "react";
import api from "../services/api";

const TABS = ["Finance", "Scenarios", "Due Diligence", "Report"];
const TECHS = ["wind", "solar", "bess", "offshore_wind"];
const REGIONS = ["Scotland", "Wales", "South West", "South East", "East", "Midlands", "North West", "North East"];

/* ── tiny SVG charts ───────────────────────────────────────────── */

function StackedBarChart({ items, height = 180 }) {
  if (!items?.length) return null;
  const w = 300;
  const maxVal = Math.max(...items.map(d => Math.max(Math.abs(d.revenue || 0), Math.abs(d.opex || 0) + Math.abs(d.tax || 0))));
  const barW = Math.min(16, (w - 20) / items.length - 2);
  return (
    <svg viewBox={`0 0 ${w} ${height}`} style={{ width: "100%", maxHeight: height }}>
      {items.map((d, i) => {
        const x = 30 + i * (barW + 4);
        const revH = (d.revenue || 0) / (maxVal || 1) * (height - 30);
        const opexH = (d.opex || 0) / (maxVal || 1) * (height - 30);
        const taxH = (d.tax || 0) / (maxVal || 1) * (height - 30);
        return (
          <g key={i}>
            <rect x={x} y={height - 20 - revH} width={barW} height={revH} fill="#22d3ee" opacity={0.7} rx={1} />
            <rect x={x} y={height - 20 - opexH} width={barW / 2} height={opexH} fill="#f87171" opacity={0.5} rx={1} />
            <rect x={x + barW / 2} y={height - 20 - taxH} width={barW / 2} height={taxH} fill="#fbbf24" opacity={0.5} rx={1} />
            <text x={x + barW / 2} y={height - 6} textAnchor="middle" fontSize={7} fill="#64748b">{d.year}</text>
          </g>
        );
      })}
      <text x={2} y={12} fontSize={8} fill="#64748b">Revenue / Opex / Tax</text>
    </svg>
  );
}

function TornadoChart({ items, height = 200 }) {
  if (!items?.length) return null;
  const w = 320, barH = Math.min(22, (height - 10) / items.length - 4);
  const maxSwing = Math.max(...items.map(d => Math.max(Math.abs(d.low_irr - d.base_irr), Math.abs(d.high_irr - d.base_irr))));
  const mid = w * 0.5;
  return (
    <svg viewBox={`0 0 ${w} ${items.length * (barH + 6) + 10}`} style={{ width: "100%", maxHeight: height }}>
      <line x1={mid} y1={0} x2={mid} y2={items.length * (barH + 6)} stroke="#475569" strokeWidth={1} strokeDasharray="3,3" />
      {items.map((d, i) => {
        const y = i * (barH + 6) + 4;
        const lowOff = (d.low_irr - d.base_irr) / (maxSwing || 1) * (w * 0.35);
        const highOff = (d.high_irr - d.base_irr) / (maxSwing || 1) * (w * 0.35);
        const x1 = mid + Math.min(lowOff, highOff);
        const x2 = mid + Math.max(lowOff, highOff);
        return (
          <g key={i}>
            <text x={30} y={y + barH * 0.7} fontSize={9} fill="#94a3b8" textAnchor="end">
              {d.variable.replace(/_/g, " ")}
            </text>
            <rect x={x1} y={y} width={Math.max(2, x2 - x1)} height={barH} rx={2} fill="#22d3ee" opacity={0.75} />
            <text x={x1 - 3} y={y + barH * 0.7} textAnchor="end" fontSize={7} fill="#cbd5e1">{d.low_irr}%</text>
            <text x={x2 + 3} y={y + barH * 0.7} textAnchor="start" fontSize={7} fill="#cbd5e1">{d.high_irr}%</text>
          </g>
        );
      })}
    </svg>
  );
}

function HistogramChart({ bins, p10, p50, p90, height = 140 }) {
  if (!bins?.length) return null;
  const w = 300, maxCount = Math.max(...bins.map(b => b.count));
  const barW = (w - 40) / bins.length;
  const lo = bins[0].bin_low, hi = bins[bins.length - 1].bin_high;
  const range = hi - lo || 1;
  const pctX = (v) => 20 + ((v - lo) / range) * (w - 40);
  return (
    <svg viewBox={`0 0 ${w} ${height}`} style={{ width: "100%", maxHeight: height }}>
      {bins.map((b, i) => {
        const bh = (b.count / (maxCount || 1)) * (height - 35);
        return (
          <rect key={i} x={20 + i * barW} y={height - 25 - bh} width={barW - 1} height={bh}
            fill="#22d3ee" opacity={0.6} rx={1} />
        );
      })}
      {p10 != null && <line x1={pctX(p10)} y1={5} x2={pctX(p10)} y2={height - 25} stroke="#f87171" strokeWidth={1.5} strokeDasharray="3,2" />}
      {p50 != null && <line x1={pctX(p50)} y1={5} x2={pctX(p50)} y2={height - 25} stroke="#fbbf24" strokeWidth={1.5} />}
      {p90 != null && <line x1={pctX(p90)} y1={5} x2={pctX(p90)} y2={height - 25} stroke="#34d399" strokeWidth={1.5} strokeDasharray="3,2" />}
      {p10 != null && <text x={pctX(p10)} y={height - 4} textAnchor="middle" fontSize={7} fill="#f87171">P10</text>}
      {p50 != null && <text x={pctX(p50)} y={height - 4} textAnchor="middle" fontSize={7} fill="#fbbf24">P50</text>}
      {p90 != null && <text x={pctX(p90)} y={height - 4} textAnchor="middle" fontSize={7} fill="#34d399">P90</text>}
    </svg>
  );
}

function RadarChart({ pillars, size = 160 }) {
  if (!pillars) return null;
  const keys = Object.keys(pillars);
  const n = keys.length;
  const cx = size / 2, cy = size / 2, r = size / 2 - 20;
  const angle = (i) => (i / n) * 2 * Math.PI - Math.PI / 2;
  const pts = keys.map((k, i) => {
    const v = (pillars[k].score || 0) / 100;
    return `${cx + r * v * Math.cos(angle(i))},${cy + r * v * Math.sin(angle(i))}`;
  });
  return (
    <svg viewBox={`0 0 ${size} ${size}`} style={{ width: size, height: size }}>
      {[0.25, 0.5, 0.75, 1].map(s => (
        <polygon key={s} points={keys.map((_, i) => `${cx + r * s * Math.cos(angle(i))},${cy + r * s * Math.sin(angle(i))}`).join(" ")}
          fill="none" stroke="#334155" strokeWidth={0.5} />
      ))}
      <polygon points={pts.join(" ")} fill="#22d3ee" fillOpacity={0.2} stroke="#22d3ee" strokeWidth={1.5} />
      {keys.map((k, i) => (
        <text key={k} x={cx + (r + 12) * Math.cos(angle(i))} y={cy + (r + 12) * Math.sin(angle(i))}
          textAnchor="middle" fontSize={8} fill="#94a3b8" dominantBaseline="middle">
          {k.charAt(0).toUpperCase() + k.slice(1)}
        </text>
      ))}
    </svg>
  );
}

function RiskGrid({ grid }) {
  if (!grid) return null;
  const labels = ["Very Low", "Low", "Medium", "High", "Very High"];
  const colors = ["#1e3a2f", "#2d4a1f", "#4a3a1f", "#5a2a1f", "#6a1a1f"];
  return (
    <div className="inv-risk-grid">
      <div className="inv-risk-axis-y">Impact</div>
      {[4, 3, 2, 1, 0].map(row => (
        <div key={row} className="inv-risk-row">
          <span className="inv-risk-label">{labels[row]}</span>
          {[0, 1, 2, 3, 4].map(col => {
            const risks = grid[col]?.[row] || [];
            const score = (col + 1) * (row + 1);
            const bg = score >= 15 ? "#6a1a1f" : score >= 9 ? "#5a3a1f" : score >= 4 ? "#2d3a2f" : "#1e293b";
            return (
              <div key={col} className="inv-risk-cell" style={{ background: bg }} title={risks.join("\n")}>
                {risks.length > 0 && <span className="inv-risk-count">{risks.length}</span>}
              </div>
            );
          })}
        </div>
      ))}
      <div className="inv-risk-row">
        <span className="inv-risk-label" />
        {labels.map(l => <span key={l} className="inv-risk-col-label">{l}</span>)}
      </div>
      <div className="inv-risk-axis-x">Likelihood</div>
    </div>
  );
}

/* ── formatting ───────────────────────────────────────────── */

const fmt = (v) => {
  if (v == null) return "—";
  if (typeof v !== "number") return v;
  if (Math.abs(v) >= 1e6) return `£${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `£${(v / 1e3).toFixed(0)}k`;
  return v.toLocaleString();
};

const pct = (v) => v != null ? `${v}%` : "—";
const ragColor = (r) => r === "GREEN" ? "#34d399" : r === "AMBER" ? "#fbbf24" : "#f87171";

/* ── stat pill ───────────────────────────────────────────── */

function Stat({ label, value, sub, color }) {
  return (
    <div className="inv-stat">
      <div className="inv-stat-label">{label}</div>
      <div className="inv-stat-value" style={color ? { color } : {}}>{value}</div>
      {sub && <div className="inv-stat-sub">{sub}</div>}
    </div>
  );
}

/* ── main panel ───────────────────────────────────────────── */

export default function InvestmentPanel({ onClose }) {
  const [tab, setTab] = useState(0);
  const [mw, setMw] = useState(50);
  const [tech, setTech] = useState("wind");
  const [region, setRegion] = useState("Scotland");
  const [gearing, setGearing] = useState(70);
  const [ppa, setPpa] = useState(55);
  const [taxRate, setTaxRate] = useState(25);

  const [finance, setFinance] = useState(null);
  const [debt, setDebt] = useState(null);
  const [equity, setEquity] = useState(null);
  const [stress, setStress] = useState(null);
  const [mc, setMc] = useState(null);
  const [be, setBe] = useState(null);
  const [dd, setDd] = useState(null);
  const [memo, setMemo] = useState(null);
  const [risks, setRisks] = useState(null);
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(false);

  const g = gearing / 100;
  const t = taxRate / 100;

  const loadFinance = useCallback(async () => {
    setLoading(true);
    try {
      const [f, d, e] = await Promise.all([
        api.investment.projectFinance(mw, tech, region, ppa),
        api.investment.debtStructure(mw, tech, 1.3, g, ppa),
        api.investment.equityReturns(mw, tech, g, ppa, t),
      ]);
      setFinance(f); setDebt(d); setEquity(e);
    } catch (err) { console.error("finance load:", err); }
    setLoading(false);
  }, [mw, tech, region, ppa, g, t]);

  const loadScenarios = useCallback(async () => {
    setLoading(true);
    try {
      const [s, m, b] = await Promise.all([
        api.investment.stressTest(mw, tech, g),
        api.investment.montecarlo(mw, tech, 2000, g),
        api.investment.breakEven(mw, tech, g),
      ]);
      setStress(s); setMc(m); setBe(b);
    } catch (err) { console.error("scenario load:", err); }
    setLoading(false);
  }, [mw, tech, g]);

  const loadDD = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.investment.ddChecklist(mw, tech, region);
      setDd(d);
    } catch (err) { console.error("dd load:", err); }
    setLoading(false);
  }, [mw, tech, region]);

  const loadReport = useCallback(async () => {
    setLoading(true);
    try {
      const [m, r, p] = await Promise.all([
        api.investment.memo(mw, tech, region, ppa, g),
        api.investment.riskMatrix(mw, tech, region),
        api.investment.actionPlan(mw, tech, region),
      ]);
      setMemo(m); setRisks(r); setPlan(p);
    } catch (err) { console.error("report load:", err); }
    setLoading(false);
  }, [mw, tech, region, ppa, g]);

  const run = () => {
    if (tab === 0) loadFinance();
    else if (tab === 1) loadScenarios();
    else if (tab === 2) loadDD();
    else loadReport();
  };

  return (
    <div className="inv-panel">
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid #1e293b" }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#e2e8f0" }}>Investment Readiness</span>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "#94a3b8", cursor: "pointer", fontSize: 18 }}>×</button>
      </div>

      {/* controls */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: "8px 14px", borderBottom: "1px solid #1e293b" }}>
        <label className="inv-ctrl">
          <span>MW</span>
          <input type="number" value={mw} min={1} max={1000} onChange={e => setMw(+e.target.value)} />
        </label>
        <label className="inv-ctrl">
          <span>Tech</span>
          <select value={tech} onChange={e => setTech(e.target.value)}>
            {TECHS.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="inv-ctrl">
          <span>Region</span>
          <select value={region} onChange={e => setRegion(e.target.value)}>
            {REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <label className="inv-ctrl">
          <span>Gear %</span>
          <input type="range" min={50} max={90} value={gearing} onChange={e => setGearing(+e.target.value)} />
          <span style={{ fontSize: 9, color: "#94a3b8", width: 24 }}>{gearing}%</span>
        </label>
        <label className="inv-ctrl">
          <span>PPA £</span>
          <input type="number" value={ppa} min={20} max={150} onChange={e => setPpa(+e.target.value)} />
        </label>
        <label className="inv-ctrl">
          <span>Tax %</span>
          <input type="number" value={taxRate} min={0} max={50} onChange={e => setTaxRate(+e.target.value)} />
        </label>
        <button onClick={run} disabled={loading} className="inv-run-btn">
          {loading ? "..." : "Run"}
        </button>
      </div>

      {/* tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid #1e293b" }}>
        {TABS.map((t, i) => (
          <button key={t} onClick={() => setTab(i)}
            style={{ flex: 1, padding: "6px 0", fontSize: 10, background: i === tab ? "#1e293b" : "transparent",
              color: i === tab ? "#22d3ee" : "#64748b", border: "none", cursor: "pointer",
              borderBottom: i === tab ? "2px solid #22d3ee" : "2px solid transparent" }}>
            {t}
          </button>
        ))}
      </div>

      {/* body */}
      <div style={{ flex: 1, overflow: "auto", padding: "10px 14px" }}>
        {tab === 0 && <FinanceTab finance={finance} debt={debt} equity={equity} />}
        {tab === 1 && <ScenariosTab stress={stress} mc={mc} be={be} />}
        {tab === 2 && <DDTab dd={dd} />}
        {tab === 3 && <ReportTab memo={memo} risks={risks} plan={plan} />}
      </div>
    </div>
  );
}

/* ── Finance Tab ───────────────────────────────────────────── */

function FinanceTab({ finance, debt, equity }) {
  if (!finance) return <p style={{ color: "#64748b", fontSize: 11 }}>Click Run to generate project finance model.</p>;
  return (
    <>
      <div className="inv-stats-row">
        <Stat label="Project IRR" value={pct(finance.project_irr)} color={finance.project_irr >= 6 ? "#34d399" : "#fbbf24"} />
        <Stat label="NPV @8%" value={fmt(finance.npv_8pct)} color={finance.npv_8pct >= 0 ? "#34d399" : "#f87171"} />
        <Stat label="LCOE" value={`£${finance.lcoe}/MWh`} />
        <Stat label="Payback" value={finance.simple_payback_years ? `${finance.simple_payback_years}yr` : "—"} />
      </div>

      <div className="inv-section-hd">Cashflow (Years 1-5 + Final)</div>
      <StackedBarChart items={finance.cashflow_truncated} />

      {debt && (
        <>
          <div className="inv-section-hd">Debt Structure</div>
          <div className="inv-stats-row">
            <Stat label="Gearing" value={pct(debt.gearing_pct)} />
            <Stat label="Debt" value={fmt(debt.debt_amount)} />
            <Stat label="Avg DSCR" value={debt.avg_dscr?.toFixed(2) + "x"} color={debt.avg_dscr >= 1.2 ? "#34d399" : "#f87171"} />
            <Stat label="Min DSCR" value={debt.min_dscr?.toFixed(2) + "x"} color={debt.min_dscr >= 1.1 ? "#34d399" : "#f87171"} />
          </div>
          <div className="inv-stat-sub" style={{ marginTop: 4 }}>
            Covenants: Lock-up {debt.lock_up_dscr}x / Default {debt.default_dscr}x —{" "}
            <span style={{ color: debt.covenant_status === "PASS" ? "#34d399" : "#f87171" }}>{debt.covenant_status}</span>
          </div>
        </>
      )}

      {equity && (
        <>
          <div className="inv-section-hd">Equity Returns</div>
          <div className="inv-stats-row">
            <Stat label="Equity IRR (pre)" value={pct(equity.equity_irr_pre_tax_pct)} color="#22d3ee" />
            <Stat label="Equity IRR (post)" value={pct(equity.equity_irr_post_tax_pct)} color="#a78bfa" />
            <Stat label="Multiple" value={equity.equity_multiple?.toFixed(2) + "x"} />
            <Stat label="CoC Yield" value={pct(equity.cash_on_cash_yield_pct)} />
          </div>
        </>
      )}
    </>
  );
}

/* ── Scenarios Tab ──────────────────────────────────────────── */

function ScenariosTab({ stress, mc, be }) {
  if (!stress && !mc) return <p style={{ color: "#64748b", fontSize: 11 }}>Click Run to generate scenario analysis.</p>;
  return (
    <>
      {stress && (
        <>
          <div className="inv-section-hd">Tornado — Equity IRR Sensitivity</div>
          <TornadoChart items={stress.tornado} />
          <div className="inv-stat-sub">Most sensitive: <strong>{stress.most_sensitive?.replace(/_/g, " ")}</strong></div>
        </>
      )}

      {mc && (
        <>
          <div className="inv-section-hd">Monte Carlo — IRR Distribution ({mc.n_simulations} sims)</div>
          <HistogramChart bins={mc.histogram} p10={mc.equity_irr_p10} p50={mc.equity_irr_p50} p90={mc.equity_irr_p90} />
          <div className="inv-stats-row">
            <Stat label="P10 IRR" value={pct(mc.equity_irr_p10)} color="#f87171" />
            <Stat label="P50 IRR" value={pct(mc.equity_irr_p50)} color="#fbbf24" />
            <Stat label="P90 IRR" value={pct(mc.equity_irr_p90)} color="#34d399" />
            <Stat label="P(NPV<0)" value={pct(mc.prob_negative_npv_pct)} color={mc.prob_negative_npv_pct < 10 ? "#34d399" : "#f87171"} />
          </div>
        </>
      )}

      {be && (
        <>
          <div className="inv-section-hd">Break-Even Analysis</div>
          <table className="inv-table">
            <thead>
              <tr><th>Variable</th><th>Base</th><th>Break-Even</th><th>Headroom</th></tr>
            </thead>
            <tbody>
              {be.break_even_analysis?.map((b, i) => (
                <tr key={i}>
                  <td>{b.variable.replace(/_/g, " ")}</td>
                  <td>{typeof b.base_value === "number" && b.base_value < 1 ? (b.base_value * 100).toFixed(1) + "%" : fmt(b.base_value)}</td>
                  <td>{typeof b.break_even_value === "number" && b.break_even_value < 1 ? (b.break_even_value * 100).toFixed(1) + "%" : fmt(b.break_even_value)}</td>
                  <td style={{ color: b.headroom_pct > 20 ? "#34d399" : b.headroom_pct > 10 ? "#fbbf24" : "#f87171" }}>
                    {b.headroom_pct}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="inv-stat-sub">Most fragile: <strong>{be.most_fragile?.replace(/_/g, " ")}</strong></div>
        </>
      )}
    </>
  );
}

/* ── DD Tab ─────────────────────────────────────────────────── */

function DDTab({ dd }) {
  if (!dd) return <p style={{ color: "#64748b", fontSize: 11 }}>Click Run to generate due diligence assessment.</p>;
  return (
    <>
      <div style={{ display: "flex", gap: 16, alignItems: "center", marginBottom: 10 }}>
        <RadarChart pillars={dd.pillars} />
        <div>
          <div className="inv-dd-score" style={{ color: ragColor(dd.overall_rag) }}>{dd.overall_score}/100</div>
          <div className="inv-dd-grade">Grade {dd.grade}</div>
          <div className={`inv-verdict inv-verdict-${dd.verdict?.toLowerCase()}`}>{dd.verdict?.replace(/_/g, " ")}</div>
        </div>
      </div>

      {Object.entries(dd.pillars || {}).map(([name, pillar]) => (
        <div key={name}>
          <div className="inv-section-hd">
            {name.charAt(0).toUpperCase() + name.slice(1)} — {pillar.score}/100
            <span className="inv-rag-pill" style={{ background: ragColor(pillar.rag) }}>{pillar.rag}</span>
          </div>
          {pillar.items?.map((item, i) => (
            <div key={i} className="inv-dd-item">
              <span className="inv-rag-dot" style={{ background: ragColor(item.rag) }} />
              <span className="inv-dd-item-name">{item.item}</span>
              <span className="inv-dd-item-score">{item.score}</span>
              <span className="inv-dd-item-note">{item.note}</span>
            </div>
          ))}
        </div>
      ))}
    </>
  );
}

/* ── Report Tab ─────────────────────────────────────────────── */

function ReportTab({ memo, risks, plan }) {
  if (!memo) return <p style={{ color: "#64748b", fontSize: 11 }}>Click Run to generate investment report.</p>;
  const es = memo.executive_summary || {};
  const verdictClass = memo.verdict === "INVEST" ? "go" : memo.verdict === "CONDITIONAL" ? "caution" : "no-go";
  return (
    <>
      {/* Verdict badge */}
      <div className={`inv-verdict-badge inv-verdict-${verdictClass}`}>
        <span className="inv-verdict-label">{memo.verdict}</span>
        <span className="inv-verdict-conf">{memo.confidence_pct}% confidence</span>
      </div>

      <div className="inv-section-hd">Executive Summary</div>
      <div className="inv-stats-row">
        <Stat label="CAPEX" value={fmt(es.total_capex)} />
        <Stat label="Equity IRR" value={pct(es.equity_irr_post_tax_pct)} />
        <Stat label="NPV @8%" value={fmt(es.npv_8pct)} />
        <Stat label="LCOE" value={es.lcoe ? `£${es.lcoe}/MWh` : "—"} />
      </div>
      <div className="inv-stats-row">
        <Stat label="Min DSCR" value={es.min_dscr ? es.min_dscr.toFixed(2) + "x" : "—"} />
        <Stat label="DD Score" value={`${es.dd_score}/100`} sub={`Grade ${es.dd_grade}`} />
        <Stat label="Gearing" value={pct(es.gearing_pct)} />
        <Stat label="Payback" value={es.simple_payback_years ? `${es.simple_payback_years}yr` : "—"} />
      </div>

      {memo.investment_highlights?.length > 0 && (
        <>
          <div className="inv-section-hd">Investment Highlights</div>
          <ul className="inv-highlights">
            {memo.investment_highlights.map((h, i) => <li key={i}>{h}</li>)}
          </ul>
        </>
      )}

      {memo.key_risks?.length > 0 && (
        <>
          <div className="inv-section-hd">Key Risks</div>
          <ul className="inv-risks-list">
            {memo.key_risks.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </>
      )}

      {risks && (
        <>
          <div className="inv-section-hd">Risk Matrix ({risks.total_risks} risks, {risks.critical_count} critical)</div>
          <RiskGrid grid={risks.grid_5x5} />
        </>
      )}

      {plan && (
        <>
          <div className="inv-section-hd">Action Plan — {plan.total_development_months} months to COD</div>
          <div className="inv-timeline">
            {plan.phases?.slice(0, 4).map((p, i) => (
              <div key={i} className="inv-timeline-phase">
                <div className="inv-timeline-dot" />
                <div className="inv-timeline-content">
                  <div className="inv-timeline-title">{p.phase} ({p.duration_months}mo)</div>
                  <div className="inv-timeline-dates">{p.start} → {typeof p.end === "string" && p.end.length <= 12 ? p.end : p.end?.slice(0, 10)}</div>
                  {p.milestones?.filter(m => m.critical).map((m, j) => (
                    <div key={j} className="inv-timeline-milestone">{m.task}</div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {plan.next_actions?.length > 0 && (
            <>
              <div className="inv-section-hd">Next Actions</div>
              <table className="inv-table">
                <thead><tr><th>Action</th><th>Deadline</th><th>Priority</th></tr></thead>
                <tbody>
                  {plan.next_actions.map((a, i) => (
                    <tr key={i}>
                      <td>{a.action}</td>
                      <td>{a.deadline}</td>
                      <td style={{ color: a.priority === "HIGH" ? "#f87171" : "#fbbf24" }}>{a.priority}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </>
  );
}
