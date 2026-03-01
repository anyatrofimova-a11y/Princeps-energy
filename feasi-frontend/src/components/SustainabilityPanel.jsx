import React, { useState, useCallback } from "react";
import api from "../services/api";

const TABS = ["Carbon", "Portfolio", "Community", "Decommission"];
const TECHS = ["wind", "solar", "bess"];
const REGIONS = ["Scotland", "North", "Midlands", "South"];

/* ── tiny SVG charts ───────────────────────────────────────────── */

function BarChart({ items, valueKey, labelKey, maxVal, color = "#22d3ee", height = 120 }) {
  if (!items?.length) return null;
  const mx = maxVal || Math.max(...items.map(d => Math.abs(d[valueKey])));
  const w = 280, barH = Math.min(18, height / items.length - 2);
  return (
    <svg viewBox={`0 0 ${w} ${items.length * (barH + 4)}`} style={{ width: "100%", maxHeight: height }}>
      {items.map((d, i) => {
        const val = d[valueKey];
        const bw = Math.abs(val) / (mx || 1) * (w * 0.55);
        const neg = val < 0;
        return (
          <g key={i} transform={`translate(0,${i * (barH + 4)})`}>
            <text x={w * 0.35 - 4} y={barH * 0.72} textAnchor="end" fontSize={9} fill="#94a3b8">{d[labelKey]}</text>
            <rect x={neg ? w * 0.35 - bw : w * 0.35} y={1} width={bw} height={barH - 2} rx={2} fill={neg ? "#f87171" : color} opacity={0.85} />
            <text x={neg ? w * 0.35 - bw - 3 : w * 0.35 + bw + 3} y={barH * 0.72} textAnchor={neg ? "end" : "start"} fontSize={8} fill="#cbd5e1">
              {typeof val === "number" ? (Math.abs(val) >= 1e6 ? `${(val / 1e6).toFixed(1)}M` : Math.abs(val) >= 1e3 ? `${(val / 1e3).toFixed(0)}k` : val.toLocaleString()) : val}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function PieChart({ slices, size = 90 }) {
  if (!slices?.length) return null;
  const r = size / 2 - 4, cx = size / 2, cy = size / 2;
  const colors = ["#22d3ee", "#a78bfa", "#34d399", "#fbbf24", "#f87171", "#60a5fa"];
  let angle = 0;
  return (
    <svg viewBox={`0 0 ${size} ${size}`} style={{ width: size, height: size }}>
      {slices.map((s, i) => {
        const a = (s.pct / 100) * 360;
        const startRad = (angle - 90) * Math.PI / 180;
        const endRad = ((angle + a) - 90) * Math.PI / 180;
        const large = a > 180 ? 1 : 0;
        const x1 = cx + r * Math.cos(startRad), y1 = cy + r * Math.sin(startRad);
        const x2 = cx + r * Math.cos(endRad), y2 = cy + r * Math.sin(endRad);
        angle += a;
        if (a < 1) return null;
        return <path key={i} d={`M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${large},1 ${x2},${y2} Z`} fill={colors[i % colors.length]} opacity={0.8} />;
      })}
    </svg>
  );
}

function EsgGauge({ score, rating, size = 100 }) {
  const r = size / 2 - 10, cx = size / 2, cy = size / 2;
  const pct = score / 100;
  const circum = 2 * Math.PI * r;
  const color = score >= 80 ? "#22d3ee" : score >= 60 ? "#fbbf24" : "#f87171";
  return (
    <svg viewBox={`0 0 ${size} ${size}`} style={{ width: size, height: size }}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#1e293b" strokeWidth={6} />
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth={6}
        strokeDasharray={`${pct * circum} ${circum}`} strokeLinecap="round"
        transform={`rotate(-90 ${cx} ${cy})`} />
      <text x={cx} y={cy - 4} textAnchor="middle" fontSize={18} fontWeight={700} fill={color}>{score}</text>
      <text x={cx} y={cy + 12} textAnchor="middle" fontSize={11} fill="#94a3b8">{rating}</text>
    </svg>
  );
}

/* ── panel ──────────────────────────────────────────────────────── */

export default function SustainabilityPanel({ onClose }) {
  const [tab, setTab] = useState(0);
  const [capacity, setCapacity] = useState(50);
  const [tech, setTech] = useState("wind");
  const [region, setRegion] = useState("Scotland");
  const [loading, setLoading] = useState(false);

  // Carbon tab
  const [carbon, setCarbon] = useState(null);
  const [displacement, setDisplacement] = useState(null);
  const [esg, setEsg] = useState(null);

  // Portfolio tab
  const [portfolio, setPortfolio] = useState(null);
  const [diversification, setDiversification] = useState(null);
  const [optimisation, setOptimisation] = useState(null);

  // Community tab
  const [community, setCommunity] = useState(null);
  const [ownership, setOwnership] = useState(null);
  const [socialVal, setSocialVal] = useState(null);

  // Decommission tab
  const [decom, setDecom] = useState(null);
  const [repower, setRepower] = useState(null);
  const [materials, setMaterials] = useState(null);

  const run = useCallback(async (fn) => {
    setLoading(true);
    try { await fn(); } catch (e) { console.error(e); } finally { setLoading(false); }
  }, []);

  const runCarbon = () => run(async () => {
    const [c, d, e] = await Promise.all([
      api.sustainability.carbonFootprint(capacity, tech),
      api.sustainability.gridDisplacement(capacity, tech, region),
      api.sustainability.esgScore(capacity, tech, region),
    ]);
    setCarbon(c); setDisplacement(d); setEsg(e);
  });

  const runPortfolio = () => run(async () => {
    const sites = [
      { name: `${tech} ${region}`, capacity_mw: capacity, technology: tech, region },
      { name: "Solar Midlands", capacity_mw: 30, technology: "solar", region: "Midlands" },
    ];
    const [s, div, opt] = await Promise.all([
      api.sustainability.portfolioSummary(sites),
      api.sustainability.portfolioDiversification(sites),
      api.sustainability.portfolioOptimisation(200),
    ]);
    setPortfolio(s); setDiversification(div); setOptimisation(opt);
  });

  const runCommunity = () => run(async () => {
    const [c, o, sv] = await Promise.all([
      api.sustainability.communityPackage(capacity, tech, region, true, 20),
      api.sustainability.sharedOwnership(capacity, tech, 25),
      api.sustainability.socialValue(capacity, tech, region),
    ]);
    setCommunity(c); setOwnership(o); setSocialVal(sv);
  });

  const runDecom = () => run(async () => {
    const [d, r, m] = await Promise.all([
      api.sustainability.decomEstimate(capacity, tech, 25),
      api.sustainability.repoweringComparison(capacity, tech, region),
      api.sustainability.materialRecovery(capacity, tech),
    ]);
    setDecom(d); setRepower(r); setMaterials(m);
  });

  const fmt = (v) => v == null ? "-" : typeof v === "number"
    ? (Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : Math.abs(v) >= 1e3 ? `${(v / 1e3).toFixed(0)}k` : v.toLocaleString())
    : v;
  const fmtGbp = (v) => v == null ? "-" : `\u00a3${fmt(v)}`;

  return (
    <div className="gc-panel" style={{ zIndex: 900 }}>
      {/* header */}
      <div className="gc-panel-hdr">
        <span className="gc-panel-title">Sustainability & Lifecycle</span>
        <button className="gc-panel-close" onClick={onClose}>&times;</button>
      </div>

      {/* tabs */}
      <div className="dp-tabs">
        {TABS.map((t, i) => (
          <button key={t} className={`dp-tab${tab === i ? " dp-tab--active" : ""}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>

      {/* controls */}
      <div className="dp-controls">
        <label className="dp-ctrl">
          <span>MW</span>
          <input type="number" min={1} max={500} value={capacity} onChange={e => setCapacity(+e.target.value)} />
        </label>
        <label className="dp-ctrl">
          <span>Tech</span>
          <select value={tech} onChange={e => setTech(e.target.value)}>
            {TECHS.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="dp-ctrl">
          <span>Region</span>
          <select value={region} onChange={e => setRegion(e.target.value)}>
            {REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <button className="dp-run-btn" disabled={loading}
          onClick={() => { [runCarbon, runPortfolio, runCommunity, runDecom][tab](); }}>
          {loading ? "Running\u2026" : "Run"}
        </button>
      </div>

      <div className="dp-body" style={{ overflowY: "auto", flex: 1, padding: "8px 12px" }}>

        {/* ── Carbon Tab ── */}
        {tab === 0 && (
          <>
            {!carbon && !esg && <div className="dp-empty">Click Run to calculate carbon footprint &amp; ESG score</div>}

            {esg?.composite && (
              <div className="sus-esg-row">
                <EsgGauge score={esg.composite.score} rating={esg.composite.rating} />
                <div className="sus-esg-pillars">
                  {["environmental", "social", "governance"].map(p => (
                    <div key={p} className="sus-pill-row">
                      <span className="sus-pill-label">{p.charAt(0).toUpperCase() + p.slice(1)}</span>
                      <div className="sus-pill-bar"><div style={{ width: `${esg[p]?.score || 0}%`, background: p === "environmental" ? "#22d3ee" : p === "social" ? "#a78bfa" : "#34d399" }} /></div>
                      <span className="sus-pill-val">{esg[p]?.score}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {carbon && (
              <>
                <div className="dp-stat-row">
                  <div className="dp-stat"><div className="dp-stat-val">{fmt(carbon.lifecycle_emissions_tco2e?.total)}</div><div className="dp-stat-label">Total tCO2e</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{carbon.intensity?.g_co2_per_kwh}</div><div className="dp-stat-label">gCO2/kWh</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{carbon.carbon_payback?.years}yr</div><div className="dp-stat-label">Payback</div></div>
                </div>
                <h4 className="sus-section-hd">Lifecycle Emissions</h4>
                <BarChart items={[
                  { name: "Construction", val: carbon.lifecycle_emissions_tco2e?.construction },
                  { name: "Operation", val: carbon.lifecycle_emissions_tco2e?.operation },
                  { name: "Decommission", val: carbon.lifecycle_emissions_tco2e?.decommissioning },
                ]} valueKey="val" labelKey="name" color="#22d3ee" />
              </>
            )}

            {displacement && (
              <>
                <h4 className="sus-section-hd">Grid Displacement</h4>
                <div className="dp-stat-row">
                  <div className="dp-stat"><div className="dp-stat-val">{fmt(displacement.annual_displacement?.marginal_tco2e)}</div><div className="dp-stat-label">tCO2e/yr</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{fmt(displacement.lifetime?.total_displaced_tco2e)}</div><div className="dp-stat-label">Lifetime tCO2e</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(displacement.lifetime?.carbon_value_gbp)}</div><div className="dp-stat-label">Carbon value</div></div>
                </div>
                <div className="sus-equiv">
                  <span>{fmt(displacement.equivalents?.homes_heated_gas)} homes</span>
                  <span>{fmt(displacement.equivalents?.cars_removed)} cars</span>
                  <span>{fmt(displacement.equivalents?.flights_ldn_nyc)} flights</span>
                </div>
              </>
            )}

            {esg?.recommendations?.length > 0 && (
              <>
                <h4 className="sus-section-hd">Recommendations</h4>
                <ul className="sus-recs">{esg.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul>
              </>
            )}
          </>
        )}

        {/* ── Portfolio Tab ── */}
        {tab === 1 && (
          <>
            {!portfolio && <div className="dp-empty">Click Run to analyse portfolio diversification</div>}

            {portfolio?.portfolio && (
              <>
                <div className="dp-stat-row">
                  <div className="dp-stat"><div className="dp-stat-val">{portfolio.portfolio.total_capacity_mw} MW</div><div className="dp-stat-label">Total capacity</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(portfolio.portfolio.total_annual_revenue_gbp)}</div><div className="dp-stat-label">Annual revenue</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{portfolio.portfolio.simple_irr_pct}%</div><div className="dp-stat-label">Simple IRR</div></div>
                </div>

                {portfolio.technology_mix && (
                  <div className="sus-mix-row">
                    <PieChart slices={Object.entries(portfolio.technology_mix).map(([k, v]) => ({ label: k, pct: v.pct }))} />
                    <div className="sus-mix-legend">
                      {Object.entries(portfolio.technology_mix).map(([k, v]) => (
                        <div key={k} className="sus-mix-item"><span className="sus-mix-dot" />{k}: {v.mw} MW ({v.pct}%)</div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            {diversification?.diversification && (
              <>
                <h4 className="sus-section-hd">Diversification</h4>
                <div className="dp-stat-row">
                  <div className="dp-stat"><div className="dp-stat-val">{diversification.diversification.diversification_benefit_pct}%</div><div className="dp-stat-label">Benefit</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{diversification.diversification.portfolio_volatility_pct}%</div><div className="dp-stat-label">Portfolio vol</div></div>
                  <div className="dp-stat"><div className="dp-stat-val sus-conc">{diversification.diversification.concentration}</div><div className="dp-stat-label">Concentration</div></div>
                </div>
              </>
            )}

            {optimisation?.allocation && (
              <>
                <h4 className="sus-section-hd">Optimal Allocation ({optimisation.summary?.allocated_mw} MW)</h4>
                <BarChart items={optimisation.allocation.map(a => ({ name: `${a.technology} ${a.region}`, val: a.allocated_mw }))}
                  valueKey="val" labelKey="name" color="#a78bfa" />
              </>
            )}
          </>
        )}

        {/* ── Community Tab ── */}
        {tab === 2 && (
          <>
            {!community && <div className="dp-empty">Click Run to model community benefits</div>}

            {community && (
              <>
                <div className="dp-stat-row">
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(community.total_value?.annual_community_value_gbp)}</div><div className="dp-stat-label">Annual value</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(community.total_value?.lifetime_community_value_gbp)}</div><div className="dp-stat-label">Lifetime value</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(community.total_value?.value_per_mw_gbp)}/MW</div><div className="dp-stat-label">Per MW</div></div>
                </div>

                <h4 className="sus-section-hd">Community Fund</h4>
                <div className="dp-stat-row">
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(community.community_fund?.annual_gbp)}/yr</div><div className="dp-stat-label">Standard</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(community.community_fund?.lifetime_gbp)}</div><div className="dp-stat-label">Lifetime</div></div>
                </div>

                <h4 className="sus-section-hd">Employment</h4>
                <div className="dp-stat-row">
                  <div className="dp-stat"><div className="dp-stat-val">{community.employment?.construction_fte}</div><div className="dp-stat-label">Construction FTE</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{community.employment?.local_construction_fte}</div><div className="dp-stat-label">Local FTE</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{community.employment?.permanent_operation_fte}</div><div className="dp-stat-label">Permanent ops</div></div>
                </div>
              </>
            )}

            {ownership && (
              <>
                <h4 className="sus-section-hd">Shared Ownership ({ownership.parameters?.community_stake_pct}%)</h4>
                <div className="dp-stat-row">
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(ownership.financials?.community_capex_gbp)}</div><div className="dp-stat-label">Investment</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(ownership.financials?.community_profit_gbp)}/yr</div><div className="dp-stat-label">Annual return</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">Year {ownership.payback_year}</div><div className="dp-stat-label">Payback</div></div>
                </div>
                <table className="sus-table">
                  <thead><tr><th>Model</th><th>Investment</th><th>Annual return</th></tr></thead>
                  <tbody>{ownership.ownership_models?.map(m => (
                    <tr key={m.model}>
                      <td>{m.label}</td>
                      <td>{fmtGbp(m.community_investment_gbp)}</td>
                      <td>{fmtGbp(m.annual_return_gbp || m.annual_coupon_gbp || m.annual_dividend_gbp)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </>
            )}

            {socialVal && (
              <>
                <h4 className="sus-section-hd">Social Value — {socialVal.rating}</h4>
                <div className="dp-stat-row">
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(socialVal.social_value_breakdown?.total_lifetime_gbp)}</div><div className="dp-stat-label">Total TOMS value</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{socialVal.per_mw?.vs_benchmark_pct}%</div><div className="dp-stat-label">vs Benchmark</div></div>
                </div>
                <BarChart items={Object.entries(socialVal.social_value_breakdown || {}).filter(([k]) => k !== "total_lifetime_gbp").map(([k, v]) => ({ name: k.replace(/_gbp$/, "").replace(/_/g, " "), val: v }))}
                  valueKey="val" labelKey="name" color="#34d399" height={100} />
              </>
            )}
          </>
        )}

        {/* ── Decommission Tab ── */}
        {tab === 3 && (
          <>
            {!decom && <div className="dp-empty">Click Run to estimate decommissioning costs</div>}

            {decom && (
              <>
                <div className="dp-stat-row">
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(decom.totals?.net_decommission_cost_gbp)}</div><div className="dp-stat-label">Net decom cost</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(decom.totals?.cost_per_mw_gbp)}/MW</div><div className="dp-stat-label">Cost per MW</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(decom.totals?.material_recovery_credit_gbp)}</div><div className="dp-stat-label">Recovery credit</div></div>
                </div>

                <h4 className="sus-section-hd">Cost Breakdown</h4>
                <BarChart items={Object.entries(decom.cost_breakdown || {}).map(([k, v]) => ({ name: k.replace(/_/g, " "), val: v }))}
                  valueKey="val" labelKey="name" color="#fbbf24" />

                <h4 className="sus-section-hd">Bond / Escrow</h4>
                <div className="dp-stat-row">
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(decom.bond_escrow?.required_bond_gbp)}</div><div className="dp-stat-label">Required bond</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(decom.bond_escrow?.annual_provision_gbp)}/yr</div><div className="dp-stat-label">Annual provision</div></div>
                </div>
              </>
            )}

            {repower?.options && (
              <>
                <h4 className="sus-section-hd">Repowering Comparison</h4>
                <table className="sus-table">
                  <thead><tr><th>Option</th><th>Cost</th><th>NPV (25yr)</th><th>Risk</th></tr></thead>
                  <tbody>{repower.options.map(o => (
                    <tr key={o.option} className={o.recommendation === "RECOMMENDED" ? "sus-rec-row" : ""}>
                      <td>{o.label}</td>
                      <td>{fmtGbp(o.cost_gbp)}</td>
                      <td>{fmtGbp(o.npv_25yr_gbp)}</td>
                      <td><span className={`dp-risk-pill dp-risk-${o.planning_risk?.toLowerCase()}`}>{o.planning_risk}</span></td>
                    </tr>
                  ))}</tbody>
                </table>
                {repower.savings && (
                  <div className="sus-savings">Repowering saves {fmtGbp(repower.savings.repower_vs_new_gbp)} vs new build, +{repower.savings.capacity_uplift_pct}% capacity</div>
                )}
              </>
            )}

            {materials?.materials && (
              <>
                <h4 className="sus-section-hd">Material Recovery — {materials.summary?.circular_economy_rating}</h4>
                <div className="dp-stat-row">
                  <div className="dp-stat"><div className="dp-stat-val">{fmt(materials.summary?.total_mass_tonnes)}t</div><div className="dp-stat-label">Total mass</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{materials.summary?.overall_recovery_pct}%</div><div className="dp-stat-label">Recovery rate</div></div>
                  <div className="dp-stat"><div className="dp-stat-val">{fmtGbp(materials.summary?.total_scrap_value_gbp)}</div><div className="dp-stat-label">Scrap value</div></div>
                </div>
                <BarChart items={materials.materials.map(m => ({ name: m.material, val: m.total_value_gbp }))}
                  valueKey="val" labelKey="name" color="#22d3ee" />
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
