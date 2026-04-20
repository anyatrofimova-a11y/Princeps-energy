import React, { useState, useEffect, useMemo } from "react";

/**
 * MonteCarloCard — P10/P50/P90 bands for IRR / DSCR / NPV / LCOE plus a
 * correlation-aware tornado. Drops into Decide tab or any finance surface.
 *
 * Data source: POST /api/finance/monte-carlo
 */

function hist(data, bins = 30) {
  if (!data?.length) return { bins: [], max: 0, min: 0, range: 1 };
  const min = Math.min(...data), max = Math.max(...data);
  if (min === max) return { bins: [data.length], min, max, range: 1 };
  const step = (max - min) / bins;
  const counts = new Array(bins).fill(0);
  for (const v of data) {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((v - min) / step)));
    counts[idx]++;
  }
  const peak = Math.max(...counts);
  return { bins: counts, min, max, range: max - min, peak };
}

function HistogramSvg({ data, bands, unit = "%" }) {
  const h = hist(data);
  const w = 420, height = 96;
  const barW = h.bins.length ? (w / h.bins.length) : 0;
  // Map band values to x positions
  const fx = (v) => ((v - h.min) / (h.range || 1)) * w;
  return (
    <svg viewBox={`0 0 ${w} ${height}`} className="mc-hist" preserveAspectRatio="none">
      {h.bins.map((c, i) => {
        const bh = (c / (h.peak || 1)) * (height - 14);
        return (
          <rect key={i} x={i * barW} y={height - 14 - bh}
                width={Math.max(0.5, barW - 0.5)} height={bh}
                fill="rgba(245,183,49,0.55)" />
        );
      })}
      {/* P10 / P50 / P90 markers */}
      {bands?.p10 != null && (
        <g>
          <line x1={fx(bands.p10)} x2={fx(bands.p10)} y1={0} y2={height - 14}
                stroke="#DC2626" strokeWidth="1.5" strokeDasharray="4,3" />
          <text x={fx(bands.p10)} y={height - 4} fontSize="8" fill="#DC2626" fontFamily="monospace" textAnchor="middle">P10 {bands.p10}{unit}</text>
        </g>
      )}
      {bands?.p50 != null && (
        <g>
          <line x1={fx(bands.p50)} x2={fx(bands.p50)} y1={0} y2={height - 14}
                stroke="var(--ink)" strokeWidth="2" />
          <text x={fx(bands.p50)} y={10} fontSize="9" fill="var(--ink)" fontFamily="monospace" fontWeight="700" textAnchor="middle">P50 {bands.p50}{unit}</text>
        </g>
      )}
      {bands?.p90 != null && (
        <g>
          <line x1={fx(bands.p90)} x2={fx(bands.p90)} y1={0} y2={height - 14}
                stroke="#16A34A" strokeWidth="1.5" strokeDasharray="4,3" />
          <text x={fx(bands.p90)} y={height - 4} fontSize="8" fill="#16A34A" fontFamily="monospace" textAnchor="middle">P90 {bands.p90}{unit}</text>
        </g>
      )}
    </svg>
  );
}

export default function MonteCarloCard({
  capex_gbp_m, opex_gbp_m_yr, revenue_gbp_m_yr,
  curtail_pct = 2, timeline_months = 24, discount_rate_pct = 8,
  life_years = 15,
  autoRun = true,
}) {
  const [res, setRes] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [metric, setMetric] = useState("irr_pct");

  const params = { capex_gbp_m, opex_gbp_m_yr, revenue_gbp_m_yr,
    curtail_pct, timeline_months, discount_rate_pct, life_years };

  useEffect(() => {
    if (!autoRun) return;
    if (capex_gbp_m == null || revenue_gbp_m_yr == null) return;
    let cancelled = false;
    setLoading(true); setError(null);
    fetch("/api/finance/monte-carlo", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...params, n_samples: 1000 }),
    })
      .then((r) => r.ok ? r.json() : Promise.reject(`${r.status}`))
      .then((j) => { if (!cancelled) setRes(j); })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [capex_gbp_m, opex_gbp_m_yr, revenue_gbp_m_yr, curtail_pct, timeline_months, discount_rate_pct, life_years, autoRun]);

  const metricMeta = {
    irr_pct:      { label: "IRR",  unit: "%", },
    dscr:         { label: "DSCR", unit: "×" },
    npv_gbp_m:    { label: "NPV",  unit: "M£" },
    lcoe_gbp_mwh: { label: "LCOE", unit: "£/MWh" },
  };
  const bands = res?.[metric];
  const dist = res?.distributions?.[metric];

  return (
    <div className="mc-root">
      <header className="mc-head">
        <h3 className="mc-title">Risk-adjusted returns · Monte Carlo</h3>
        <div className="mc-tabs">
          {Object.keys(metricMeta).map((k) => (
            <button key={k} onClick={() => setMetric(k)}
                    className={"mc-tab" + (metric === k ? " mc-tab-on" : "")}>
              {metricMeta[k].label}
            </button>
          ))}
        </div>
      </header>

      {loading && <div className="mc-loading">Running 1000 correlated draws…</div>}
      {error && <div className="mc-err">Monte Carlo failed: {error}</div>}

      {res && (
        <>
          <div className="mc-bands">
            <div className="mc-band mc-band-p10">
              <div className="mc-band-lbl">P10</div>
              <div className="mc-band-val">{bands?.p10}{metricMeta[metric].unit}</div>
            </div>
            <div className="mc-band mc-band-p50">
              <div className="mc-band-lbl">P50 · base</div>
              <div className="mc-band-val">{bands?.p50}{metricMeta[metric].unit}</div>
            </div>
            <div className="mc-band mc-band-p90">
              <div className="mc-band-lbl">P90</div>
              <div className="mc-band-val">{bands?.p90}{metricMeta[metric].unit}</div>
            </div>
            <div className="mc-band">
              <div className="mc-band-lbl">Mean</div>
              <div className="mc-band-val">{bands?.mean}{metricMeta[metric].unit}</div>
            </div>
          </div>

          <div className="mc-chart">
            <HistogramSvg data={dist} bands={bands} unit={metricMeta[metric].unit} />
            <div className="mc-chart-sub">{res.samples} runs · correlated inputs: capex × timeline × opex × revenue × curtailment × rate</div>
          </div>

          <div className="mc-tornado">
            <h4 className="mc-sub">Tornado — drivers ranked by correlation with IRR</h4>
            {(res.tornado || []).slice(0, 6).map((t) => {
              const w = Math.abs(t.corr_with_irr) * 100;
              const dir = t.corr_with_irr >= 0 ? "pos" : "neg";
              return (
                <div key={t.driver} className="mc-tbar">
                  <div className="mc-tbar-lbl">{t.driver.replace(/_/g, " ")}</div>
                  <div className="mc-tbar-track">
                    <div className={"mc-tbar-fill mc-tbar-" + dir} style={{ width: `${w}%` }} />
                  </div>
                  <div className="mc-tbar-val">{t.corr_with_irr >= 0 ? "+" : ""}{t.corr_with_irr}</div>
                </div>
              );
            })}
          </div>
        </>
      )}

      <style>{`
        .mc-root { padding: 16px; background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle); border-radius: 12px; font-family: "DM Sans", -apple-system, sans-serif; display: flex; flex-direction: column; gap: 12px; }
        .mc-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
        .mc-title { margin: 0; font-size: 13px; font-weight: 700; color: var(--ink); }
        .mc-tabs { display: flex; gap: 2px; }
        .mc-tab { padding: 4px 10px; background: none; border: 1px solid var(--cds-border-subtle); border-radius: 6px; font: inherit; font-size: 10px; font-weight: 700; color: var(--cds-text-secondary); cursor: pointer; }
        .mc-tab-on { background: var(--ink); color: #fff; border-color: var(--ink); }
        .mc-loading, .mc-err { font-size: 12px; color: var(--cds-text-helper); padding: 8px 0; }
        .mc-err { color: var(--cds-support-error); }
        .mc-bands { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
        .mc-band { padding: 10px; background: var(--cds-layer-02); border-radius: 8px; }
        .mc-band-lbl { font-size: 9px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--cds-text-helper); }
        .mc-band-val { font-family: var(--mono); font-size: 16px; font-weight: 700; color: var(--ink); margin-top: 3px; }
        .mc-band-p10 .mc-band-val { color: var(--cds-support-error); }
        .mc-band-p50 { background: rgba(var(--accent-rgb),0.1); }
        .mc-band-p50 .mc-band-val { color: var(--gold-dark); }
        .mc-band-p90 .mc-band-val { color: var(--cds-support-success); }
        .mc-chart { display: flex; flex-direction: column; gap: 4px; }
        .mc-hist { width: 100%; height: 96px; display: block; }
        .mc-chart-sub { font-size: 10px; color: var(--cds-text-helper); }
        .mc-tornado { display: flex; flex-direction: column; gap: 4px; }
        .mc-sub { font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--cds-text-helper); margin: 6px 0 4px; }
        .mc-tbar { display: grid; grid-template-columns: 140px 1fr 50px; gap: 8px; align-items: center; font-size: 11px; }
        .mc-tbar-lbl { color: var(--cds-text-secondary); text-transform: capitalize; }
        .mc-tbar-track { height: 10px; background: var(--cds-layer-03); border-radius: 3px; overflow: hidden; }
        .mc-tbar-fill { height: 100%; }
        .mc-tbar-pos { background: var(--cds-support-success); }
        .mc-tbar-neg { background: var(--cds-support-error); }
        .mc-tbar-val { font-family: var(--mono); font-size: 11px; font-weight: 700; color: var(--ink); text-align: right; }
      `}</style>
    </div>
  );
}
