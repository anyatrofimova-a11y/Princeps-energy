import React, { useState, useEffect, useCallback } from "react";

const SOURCES = ["All", "Ofgem", "NESO", "DNO"];
const RELEVANCE_OPTS = ["ALL", "HIGH", "MEDIUM"];
const TABS = ["Alerts", "BESS Pipeline", "RIIO", "Market"];

const RELEVANCE_COLOR = { HIGH: "#C0392B", MEDIUM: "#D4A017", LOW: "#6B7280" };

const formatDate = (d) => {
  if (!d) return "";
  try { return new Date(d).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); }
  catch { return d; }
};

export default function IntelligencePanel({ onClose }) {
  const [tab, setTab] = useState(0);
  const [source, setSource] = useState("All");
  const [relevance, setRelevance] = useState("ALL");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState(null);

  const [alerts, setAlerts] = useState(null);
  const [bess, setBess] = useState(null);
  const [riio, setRiio] = useState(null);
  const [market, setMarket] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.allSettled([
      fetch("/api/regulatory/alerts").then(r => r.ok ? r.json() : null),
      fetch("/api/bess/statistics").then(r => r.ok ? r.json() : null),
      fetch("/api/regulatory/riio").then(r => r.ok ? r.json() : null),
      fetch("/api/grid/demand-forecast-dc").then(r => r.ok ? r.json() : null),
    ]).then(([a, b, r, m]) => {
      if (cancelled) return;
      setAlerts(a.status === "fulfilled" ? a.value : null);
      setBess(b.status === "fulfilled" ? b.value : null);
      setRiio(r.status === "fulfilled" ? r.value : null);
      setMarket(m.status === "fulfilled" ? m.value : null);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  // Derive alert list — filter out junk nav links (Cookie policy, Privacy, etc.)
  const rawAlerts = Array.isArray(alerts) ? alerts : (alerts?.alerts || []);
  const alertList = rawAlerts.filter(a => {
    const t = (a.title || "").toLowerCase();
    return !t.includes("cookie") && !t.includes("privacy") && !t.includes("accessibility")
      && !t.includes("terms and conditions") && !t.includes("contact us") && !t.includes("careers")
      && !t.includes("subscribe") && !t.includes("modern slavery") && !t.includes("freedom of information")
      && !t.includes("responsible disclosure") && !t.includes("security") && !t.includes("help centre")
      && !t.includes("suppliers") && !t.includes("corporate information") && !t.includes(": home")
      && !t.includes("our people") && !t.includes("media centre") && !t.includes("about")
      && t.length > 10;
  });

  const filtered = alertList.filter(a => {
    if (source !== "All" && !(a.source || "").toLowerCase().includes(source.toLowerCase())) return false;
    if (relevance !== "ALL" && a.relevance !== relevance) return false;
    if (search && !(a.title || "").toLowerCase().includes(search.toLowerCase()) &&
        !(a.summary || "").toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const highCount = alertList.filter(a => a.relevance === "HIGH").length;
  const sourceCount = new Set(alertList.map(a => a.source)).size;

  const toggle = useCallback((id) => setExpanded(p => p === id ? null : id), []);

  return (
    <div className="intel-panel">
      {/* Header */}
      <div className="intel-panel-header">
        <div className="intel-panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#007A8C" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
          </svg>
          Intelligence
        </div>
        <button className="intel-panel-close" onClick={onClose}>&times;</button>
      </div>

      {/* Hero metrics */}
      <div className="intel-hero">
        <div className="intel-hero-stat">
          <span className="intel-hero-num">{alertList.length}</span>
          <span className="intel-hero-label">Alerts</span>
        </div>
        <div className="intel-hero-divider" />
        <div className="intel-hero-stat">
          <span className="intel-hero-num" style={{ color: "#C0392B" }}>{highCount}</span>
          <span className="intel-hero-label">HIGH Priority</span>
        </div>
        <div className="intel-hero-divider" />
        <div className="intel-hero-stat">
          <span className="intel-hero-num">{sourceCount}</span>
          <span className="intel-hero-label">Sources</span>
        </div>
      </div>

      {/* Tabs */}
      <div className="intel-tabs">
        {TABS.map((t, i) => (
          <button key={t} className={`intel-tab${tab === i ? " active" : ""}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>

      {/* Filter bar (Alerts tab only) */}
      {tab === 0 && (
        <div className="intel-filter-bar">
          <select className="intel-filter-select" value={source} onChange={e => setSource(e.target.value)}>
            {SOURCES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select className="intel-filter-select" value={relevance} onChange={e => setRelevance(e.target.value)}>
            {RELEVANCE_OPTS.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
          <input className="intel-filter-search" placeholder="Search..." value={search} onChange={e => setSearch(e.target.value)} />
        </div>
      )}

      {/* Body */}
      <div className="intel-panel-body">
        {loading && <div className="intel-loading"><div className="intel-spinner" />Loading intelligence data...</div>}

        {/* ── Alerts tab ── */}
        {!loading && tab === 0 && (
          filtered.length === 0
            ? <div className="intel-empty">No alerts match your filters.</div>
            : filtered.map((a, i) => {
                const isOpen = expanded === i;
                return (
                  <div key={i} className={`intel-card${isOpen ? " intel-card-open" : ""}`} onClick={() => toggle(i)}>
                    <div className="intel-card-top">
                      <span className="intel-source-badge" data-source={a.source}>{a.source || "Unknown"}</span>
                      <span className="intel-relevance" style={{ background: RELEVANCE_COLOR[a.relevance] || "#6B7280" }}>
                        {a.relevance || "LOW"}
                      </span>
                    </div>
                    <div className="intel-card-title">{a.title}</div>
                    <div className="intel-card-summary">{a.summary}</div>
                    {isOpen && (
                      <div className="intel-card-detail">
                        {a.detail && <p className="intel-card-detail-text">{a.detail}</p>}
                        {a.impact_areas && (
                          <div className="intel-card-tags">
                            {(Array.isArray(a.impact_areas) ? a.impact_areas : [a.impact_areas]).map((tag, j) => (
                              <span key={j} className="intel-tag">{tag}</span>
                            ))}
                          </div>
                        )}
                        {a.url && <a className="intel-card-link" href={a.url} target="_blank" rel="noopener noreferrer">View source &rarr;</a>}
                      </div>
                    )}
                    <div className="intel-card-footer">
                      {a.published && <span className="intel-card-date">{formatDate(a.published)}</span>}
                      <span className="intel-card-expand">{isOpen ? "Collapse" : "Details"}</span>
                    </div>
                  </div>
                );
              })
        )}

        {/* ── BESS Pipeline tab ── */}
        {!loading && tab === 1 && (
          bess ? (
            <div className="intel-data-section">
              <div className="intel-data-grid">
                <div className="intel-data-cell"><span className="intel-data-value">{bess.total_projects?.toLocaleString() || "—"}</span><span className="intel-data-label">Total Projects</span></div>
                <div className="intel-data-cell"><span className="intel-data-value" style={{color:"#22c55e"}}>{bess.operational_mw?.toLocaleString() || "—"} MW</span><span className="intel-data-label">Operational</span></div>
                <div className="intel-data-cell"><span className="intel-data-value" style={{color:"#3b82f6"}}>{bess.total_pipeline_mw?.toLocaleString() || "—"} MW</span><span className="intel-data-label">Total Pipeline</span></div>
                <div className="intel-data-cell"><span className="intel-data-value">{bess.operational_count || "—"}</span><span className="intel-data-label">Operational Sites</span></div>
              </div>
              {bess.by_region?.length > 0 && (
                <>
                  <div className="intel-section-label">Top Regions</div>
                  {bess.by_region.slice(0, 8).map((r, i) => (
                    <div key={i} className="intel-row"><span>{r.region}</span><span>{r.mw} MW ({r.count} projects)</span></div>
                  ))}
                </>
              )}
              {bess.top_developers?.length > 0 && (
                <>
                  <div className="intel-section-label">Top Developers</div>
                  {bess.top_developers.slice(0, 6).map((d, i) => (
                    <div key={i} className="intel-row"><span>{d.operator}</span><span>{d.mw} MW</span></div>
                  ))}
                </>
              )}
            </div>
          ) : <div className="intel-empty">BESS pipeline data unavailable.</div>
        )}

        {/* ── RIIO tab ── */}
        {!loading && tab === 2 && (
          riio ? (
            <div className="intel-data-section">
              {riio.totals && (
                <div className="intel-data-grid">
                  <div className="intel-data-cell"><span className="intel-data-value">£{riio.totals.total_totex_bn}bn</span><span className="intel-data-label">Total RIIO-ED2 Allowance</span></div>
                  <div className="intel-data-cell"><span className="intel-data-value">{riio.totals.total_solar_pipeline_gw} GW</span><span className="intel-data-label">Solar Pipeline</span></div>
                  <div className="intel-data-cell"><span className="intel-data-value">{riio.totals.total_bess_pipeline_gw} GW</span><span className="intel-data-label">BESS Pipeline</span></div>
                  <div className="intel-data-cell"><span className="intel-data-value">£{riio.totals.total_flexibility_spend_m}m</span><span className="intel-data-label">Flexibility Spend</span></div>
                </div>
              )}
              <div className="intel-section-label">DNO Comparison ({riio.period || "2023-2028"})</div>
              {(riio.dnos || []).map((d, i) => (
                <div key={i} className="intel-card" style={{padding:"8px 12px",marginBottom:4}}>
                  <div className="intel-card-title" style={{fontSize:12}}>{d.full_name || d.dno}</div>
                  <div style={{display:"flex",gap:12,fontSize:10,color:"#9ca3af",marginTop:2}}>
                    <span>Totex: £{d.totex_bn}bn</span>
                    <span>Solar: {d.solar_pipeline_gw}GW</span>
                    <span>BESS: {d.bess_pipeline_gw}GW</span>
                    <span>DSO: {d.dso_maturity}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : <div className="intel-empty">RIIO data unavailable.</div>
        )}

        {/* ── Market tab ── */}
        {!loading && tab === 3 && (
          market ? (
            <div className="intel-data-section">
              <div className="intel-data-grid">
                <div className="intel-data-cell"><span className="intel-data-value" style={{color:"#f59e0b"}}>{market.current_gw || "—"} GW</span><span className="intel-data-label">Current UK DC Demand</span></div>
                <div className="intel-data-cell"><span className="intel-data-value" style={{color:"#3b82f6"}}>{market.projected_2030_gw || "—"} GW</span><span className="intel-data-label">Projected 2030</span></div>
                <div className="intel-data-cell"><span className="intel-data-value" style={{color:"#22c55e"}}>{market.growth_rate_pct_yr || "—"}%/yr</span><span className="intel-data-label">Growth Rate</span></div>
              </div>
              {market.drivers?.length > 0 && (
                <>
                  <div className="intel-section-label">Demand Drivers</div>
                  {market.drivers.map((d, i) => (
                    <div key={i} className="intel-row"><span>{d}</span></div>
                  ))}
                </>
              )}
              {market.grid_implications?.length > 0 && (
                <>
                  <div className="intel-section-label">Grid Implications</div>
                  {market.grid_implications.map((g, i) => (
                    <div key={i} className="intel-row" style={{color:"#C0392B"}}><span>{g}</span></div>
                  ))}
                </>
              )}
              {market.forecast && (
                <>
                  <div className="intel-section-label">Demand Forecast</div>
                  {Object.entries(market.forecast).map(([year, data]) => (
                    <div key={year} className="intel-row"><span>{year}</span><span>{data.total_gw} GW</span></div>
                  ))}
                </>
              )}
            </div>
          ) : <div className="intel-empty">Market intelligence unavailable.</div>
        )}
      </div>
    </div>
  );
}
