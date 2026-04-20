import React, { useState, useCallback, useMemo } from "react";

/* Lender Covenant Table — year-by-year DSCR/LLCR/PLCR/ICR/Gearing with
   red/amber/green cells, fed by POST /api/finance/dcf-evaluate.
   Props:
     capex (number £), revenueSchedule (number[]), opexSchedule (number[]),
     debtPrincipal (number £), debtRate (decimal e.g. 0.06), debtTermYears,
     wacc (decimal), costOfEquity (decimal), taxRate, terminalGrowth,
     thresholds (optional override), onResult (optional callback with summary). */

const DEFAULT_THRESHOLDS = {
  dscr_min: 1.20,
  llcr_min: 1.30,
  plcr_min: 1.40,
  icr_min: 2.00,
  gearing_max: 0.75,
};

function fmtGbp(v) {
  if (v == null || isNaN(v)) return "--";
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}\u00A3${(abs / 1e9).toFixed(2)}bn`;
  if (abs >= 1e6) return `${sign}\u00A3${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}\u00A3${(abs / 1e3).toFixed(0)}k`;
  return `${sign}\u00A3${abs.toFixed(0)}`;
}
function fmtX(v) {
  if (v == null || isNaN(v)) return "--";
  return `${v.toFixed(2)}x`;
}
function fmtPct(v) {
  if (v == null || isNaN(v)) return "--";
  return `${(v * 100).toFixed(1)}%`;
}

function cellClass(value, min, higherIsBetter = true) {
  if (value == null || isNaN(value)) return "lct-cell-na";
  if (higherIsBetter) {
    if (value < min) return "lct-cell-red";
    if (value < min * 1.10) return "lct-cell-amber";
    return "lct-cell-green";
  } else {
    if (value > min) return "lct-cell-red";
    if (value > min * 0.95) return "lct-cell-amber";
    return "lct-cell-green";
  }
}

export default function LenderCovenantTable({
  capex,
  revenueSchedule,
  opexSchedule,
  debtPrincipal = null,
  debtRate = 0.06,
  debtTermYears = 15,
  wacc = 0.08,
  costOfEquity = 0.12,
  taxRate = 0.25,
  terminalGrowth = 0.02,
  thresholds = DEFAULT_THRESHOLDS,
  title = "Lender Covenants",
  compact = false,
  autoLoad = true,
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);

  const payload = useMemo(() => {
    const life = Math.min(revenueSchedule?.length || 0, opexSchedule?.length || 0);
    if (!life || !capex) return null;
    const principal = debtPrincipal != null ? debtPrincipal : capex * 0.7;
    return {
      capex,
      revenue_schedule: revenueSchedule.slice(0, life),
      opex_schedule: opexSchedule.slice(0, life),
      tax_rate: taxRate,
      wacc,
      cost_of_equity: costOfEquity,
      terminal_growth: terminalGrowth,
      debt_schedule: { principal, rate: debtRate, term_years: debtTermYears },
      thresholds,
    };
  }, [capex, revenueSchedule, opexSchedule, debtPrincipal, debtRate, debtTermYears,
      wacc, costOfEquity, taxRate, terminalGrowth, thresholds]);

  const fetchCovenants = useCallback(async () => {
    if (!payload) return;
    setLoading(true); setError(null);
    try {
      const res = await fetch("/api/finance/dcf-evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      setData(body);
    } catch (e) {
      setError(e.message || String(e));
    }
    setLoading(false);
  }, [payload]);

  React.useEffect(() => {
    if (autoLoad && payload) fetchCovenants();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(payload), autoLoad]);

  if (!payload) {
    return (
      <div className="lct-empty">
        <em>Provide capex + schedules to load covenants.</em>
      </div>
    );
  }

  const summary = data?.summary;
  const covs = data?.covenants || [];
  const th = summary?.thresholds || thresholds;

  return (
    <div className={`lct-wrap ${compact ? "lct-compact" : ""}`}>
      <div className="lct-header">
        <div className="lct-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 21h18M5 21V10l7-5 7 5v11M9 21v-8h6v8" />
          </svg>
          {title}
        </div>
        <div className="lct-actions">
          {loading && <span className="lct-loading">Loading...</span>}
          {!loading && <button className="lct-refresh" onClick={fetchCovenants}>Refresh</button>}
        </div>
      </div>

      {error && <div className="lct-error">Error: {error}</div>}

      {summary && (
        <div className="lct-summary-strip">
          <div className="lct-sum">
            <div className="lct-sum-lbl">Min DSCR</div>
            <div className={`lct-sum-val ${cellClass(summary.min_dscr, th.dscr_min)}`}>
              {fmtX(summary.min_dscr)}
            </div>
            <div className="lct-sum-sub">req {th.dscr_min.toFixed(2)}x</div>
          </div>
          <div className="lct-sum">
            <div className="lct-sum-lbl">Min LLCR</div>
            <div className={`lct-sum-val ${cellClass(summary.min_llcr, th.llcr_min)}`}>
              {fmtX(summary.min_llcr)}
            </div>
            <div className="lct-sum-sub">req {th.llcr_min.toFixed(2)}x</div>
          </div>
          <div className="lct-sum">
            <div className="lct-sum-lbl">Min PLCR</div>
            <div className={`lct-sum-val ${cellClass(summary.min_plcr, th.plcr_min)}`}>
              {fmtX(summary.min_plcr)}
            </div>
            <div className="lct-sum-sub">req {th.plcr_min.toFixed(2)}x</div>
          </div>
          <div className="lct-sum">
            <div className="lct-sum-lbl">Min ICR</div>
            <div className={`lct-sum-val ${cellClass(summary.min_icr, th.icr_min)}`}>
              {fmtX(summary.min_icr)}
            </div>
            <div className="lct-sum-sub">req {th.icr_min.toFixed(2)}x</div>
          </div>
          <div className="lct-sum">
            <div className="lct-sum-lbl">Max Gearing</div>
            <div className={`lct-sum-val ${cellClass(summary.max_gearing, th.gearing_max, false)}`}>
              {fmtPct(summary.max_gearing)}
            </div>
            <div className="lct-sum-sub">cap {(th.gearing_max * 100).toFixed(0)}%</div>
          </div>
          <div className="lct-sum">
            <div className="lct-sum-lbl">NPV</div>
            <div className={`lct-sum-val ${summary.npv >= 0 ? "lct-cell-green" : "lct-cell-red"}`}>
              {fmtGbp(summary.npv)}
            </div>
            <div className="lct-sum-sub">IRR {summary.irr_pct != null ? `${summary.irr_pct.toFixed(2)}%` : "--"}</div>
          </div>
        </div>
      )}

      {summary?.any_breach && (
        <div className="lct-breach-note">
          Covenant breach in year(s): <strong>{(summary.breach_years || []).join(", ")}</strong>
        </div>
      )}

      {covs.length > 0 && (
        <div className="lct-table-wrap">
          <table className="lct-table">
            <thead>
              <tr>
                <th>Year</th>
                <th>CFADS</th>
                <th>Debt Svc</th>
                <th>Outstanding</th>
                <th>DSCR</th>
                <th>LLCR</th>
                <th>PLCR</th>
                <th>ICR</th>
                <th>Gearing</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {covs.map(c => (
                <tr key={c.year}>
                  <td className="lct-year">{c.year}</td>
                  <td className="lct-num">{fmtGbp(c.cfads)}</td>
                  <td className="lct-num">{fmtGbp(c.debt_service)}</td>
                  <td className="lct-num">{fmtGbp(c.debt_outstanding)}</td>
                  <td className={`lct-num ${cellClass(c.dscr, th.dscr_min)}`}>{fmtX(c.dscr)}</td>
                  <td className={`lct-num ${cellClass(c.llcr, th.llcr_min)}`}>{fmtX(c.llcr)}</td>
                  <td className={`lct-num ${cellClass(c.plcr, th.plcr_min)}`}>{fmtX(c.plcr)}</td>
                  <td className={`lct-num ${cellClass(c.icr, th.icr_min)}`}>{fmtX(c.icr)}</td>
                  <td className={`lct-num ${cellClass(c.gearing, th.gearing_max, false)}`}>{fmtPct(c.gearing)}</td>
                  <td className={`lct-status lct-status-${c.status}`}>
                    {c.breaches?.length ? c.breaches.join(", ") : "ok"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <style>{`
        .lct-wrap { color: rgba(255,255,255,0.9); font-size: 11px; }
        .lct-header { display:flex; justify-content:space-between; align-items:center;
          padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.06);
          background: rgba(255,255,255,0.02); }
        .lct-title { display:flex; align-items:center; gap:6px; font-weight:600;
          color: var(--gold, #F5B731); text-transform: uppercase; letter-spacing: 0.06em;
          font-size: 10px; }
        .lct-refresh { background: transparent; border: 1px solid rgba(245,183,49,0.4);
          color: var(--gold, #F5B731); padding: 3px 10px; font-size: 10px; border-radius: 2px;
          cursor: pointer; }
        .lct-refresh:hover { border-color: var(--gold-dark, #E8A012); }
        .lct-loading { color: rgba(255,255,255,0.5); font-size: 10px; font-style: italic; }
        .lct-error { padding: 8px 12px; color: #f5222d; font-size: 11px;
          background: rgba(245,34,45,0.08); border-bottom: 1px solid rgba(245,34,45,0.2); }
        .lct-empty { padding: 20px; text-align:center; color: rgba(255,255,255,0.4); font-size: 11px; }
        .lct-summary-strip { display: grid; grid-template-columns: repeat(6, 1fr);
          gap: 1px; background: rgba(255,255,255,0.04);
          border-bottom: 1px solid rgba(255,255,255,0.06); }
        .lct-sum { padding: 8px 10px; background: rgba(0,0,0,0.15); text-align: center; }
        .lct-sum-lbl { font-size: 9px; color: rgba(255,255,255,0.5);
          text-transform: uppercase; letter-spacing: 0.08em; }
        .lct-sum-val { font-size: 14px; font-weight: 600; margin: 3px 0;
          font-family: var(--mono, ui-monospace, monospace); }
        .lct-sum-sub { font-size: 9px; color: rgba(255,255,255,0.35); font-family: var(--mono, monospace); }
        .lct-breach-note { padding: 6px 12px; background: rgba(245,34,45,0.08);
          color: #fca5a5; font-size: 10px; border-bottom: 1px solid rgba(245,34,45,0.15); }
        .lct-table-wrap { overflow-x: auto; max-height: 420px; overflow-y: auto; }
        .lct-table { width: 100%; border-collapse: collapse; font-size: 10.5px;
          font-family: var(--mono, ui-monospace, monospace); }
        .lct-table thead th { position: sticky; top: 0; background: rgba(0,0,0,0.9);
          color: rgba(255,255,255,0.5); font-weight: 600; font-size: 9px;
          text-transform: uppercase; letter-spacing: 0.06em; padding: 6px 8px;
          border-bottom: 1px solid rgba(245,183,49,0.25); text-align: right; }
        .lct-table thead th:first-child, .lct-table thead th:last-child { text-align: left; }
        .lct-table tbody tr:hover { background: rgba(245,183,49,0.04); }
        .lct-table td { padding: 5px 8px; border-bottom: 1px solid rgba(255,255,255,0.04);
          text-align: right; }
        .lct-year { font-weight: 600; color: var(--gold, #F5B731); text-align: left !important; }
        .lct-num { text-align: right; }
        .lct-status { text-align: left !important; font-size: 9px;
          text-transform: uppercase; letter-spacing: 0.06em; }
        .lct-status-ok { color: #4ade80; }
        .lct-status-breach { color: #fca5a5; }
        .lct-cell-green { color: #4ade80; }
        .lct-cell-amber { color: var(--gold, #F5B731); }
        .lct-cell-red { color: #fca5a5; background: rgba(245,34,45,0.08); }
        .lct-cell-na { color: rgba(255,255,255,0.3); }
        .lct-compact .lct-summary-strip { grid-template-columns: repeat(3, 1fr); }
        .lct-compact .lct-sum-val { font-size: 12px; }
      `}</style>
    </div>
  );
}
