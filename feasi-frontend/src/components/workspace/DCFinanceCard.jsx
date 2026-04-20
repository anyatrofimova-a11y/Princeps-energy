import React, { useState, useEffect } from "react";

/**
 * DCFinanceCard — DC-native financial view: tenant contract tier selector,
 * ramp schedule, capacity + energy revenue split, IRR/DSCR/NPV.
 * Data source: POST /api/finance/dc
 */

const TIERS = [
  { key: "hyperscale", label: "Hyperscale", hint: "1-2 tenants · 15y · take-or-pay 85%" },
  { key: "enterprise", label: "Enterprise", hint: "5-15 tenants · 7y · 65% take-or-pay" },
  { key: "colocation", label: "Colocation", hint: "20+ tenants · 3y · 55% take-or-pay" },
];

export default function DCFinanceCard({
  it_load_mw = 40, pue_target = 1.2, grid_connection_km = 3,
}) {
  const [tier, setTier] = useState("hyperscale");
  const [ppa, setPpa] = useState(75);
  const [equity, setEquity] = useState(40);
  const [res, setRes] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch("/api/finance/dc", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        it_load_mw, pue_target, tier,
        grid_connection_km, ppa_gbp_mwh: ppa, equity_pct: equity / 100,
      }),
    }).then(r => r.json()).then(j => { if (!cancelled) setRes(j); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [it_load_mw, pue_target, tier, grid_connection_km, ppa, equity]);

  return (
    <div className="dcf-root">
      <header className="dcf-head">
        <h3 className="dcf-title">DC project finance</h3>
        <span className="dcf-sub">{it_load_mw} MW IT · PUE {pue_target}</span>
      </header>

      <div className="dcf-tiers">
        {TIERS.map((t) => (
          <button key={t.key}
                  className={"dcf-tier" + (tier === t.key ? " dcf-tier-on" : "")}
                  onClick={() => setTier(t.key)}>
            <div className="dcf-tier-lbl">{t.label}</div>
            <div className="dcf-tier-hint">{t.hint}</div>
          </button>
        ))}
      </div>

      <div className="dcf-sliders">
        <label className="dcf-s">
          <span className="dcf-s-lbl">PPA price <span className="dcf-s-u">£/MWh</span></span>
          <div className="dcf-s-row">
            <input type="range" min="40" max="120" step="5" value={ppa} onChange={e => setPpa(+e.target.value)} />
            <span className="dcf-s-val">£{ppa}</span>
          </div>
        </label>
        <label className="dcf-s">
          <span className="dcf-s-lbl">Equity stack <span className="dcf-s-u">%</span></span>
          <div className="dcf-s-row">
            <input type="range" min="20" max="100" step="5" value={equity} onChange={e => setEquity(+e.target.value)} />
            <span className="dcf-s-val">{equity}%</span>
          </div>
        </label>
      </div>

      {loading && <div className="dcf-loading">Running…</div>}

      {res && (
        <>
          <div className="dcf-kpis">
            <div className="dcf-k"><div className="dcf-k-l">CAPEX</div><div className="dcf-k-v">£{res.capex_gbp_m}M</div></div>
            <div className="dcf-k"><div className="dcf-k-l">SS revenue</div><div className="dcf-k-v">£{res.annual_revenue_steady_state_gbp_m}M/yr</div></div>
            <div className="dcf-k"><div className="dcf-k-l">IRR</div><div className="dcf-k-v dcf-k-hero">{res.irr_pct}%</div></div>
            <div className="dcf-k"><div className="dcf-k-l">DSCR</div><div className={"dcf-k-v " + (res.dscr >= 1.30 ? "dcf-good" : "dcf-warn")}>{res.dscr}×</div></div>
            <div className="dcf-k"><div className="dcf-k-l">NPV</div><div className="dcf-k-v">£{res.npv_gbp_m}M</div></div>
            <div className="dcf-k"><div className="dcf-k-l">Payback</div><div className="dcf-k-v">{res.payback_years || "—"} yr</div></div>
          </div>

          <div className="dcf-ramp">
            <div className="dcf-ramp-title">MW online + tenant utilisation ramp</div>
            <div className="dcf-ramp-bars">
              {res.ramp_schedule?.map((r) => (
                <div key={r.year} className="dcf-ramp-col">
                  <div className="dcf-ramp-util"
                       title={`Y${r.year}: ${r.mw_online} MW online, ${r.utilisation_pct}% utilisation`}>
                    <div className="dcf-ramp-fill"
                         style={{ height: `${(r.mw_online / it_load_mw) * 100}%` }} />
                  </div>
                  <div className="dcf-ramp-y">Y{r.year}</div>
                  <div className="dcf-ramp-mw">{r.mw_online} MW</div>
                  <div className="dcf-ramp-ut">{r.utilisation_pct}%</div>
                </div>
              ))}
            </div>
          </div>

          <div className="dcf-contract">
            <div className="dcf-c-title">Contract assumptions · {tier}</div>
            <div className="dcf-c-grid">
              <span>£{res.contract_assumptions.capacity_charge_gbp_mw_mo?.toLocaleString()}</span>
              <span className="dcf-c-lbl">/ MW / month capacity charge</span>
              <span>£{res.contract_assumptions.energy_markup_gbp_mwh}</span>
              <span className="dcf-c-lbl">/ MWh energy markup</span>
              <span>{Math.round(res.contract_assumptions.take_or_pay_pct * 100)}%</span>
              <span className="dcf-c-lbl">take-or-pay floor</span>
              <span>{res.contract_assumptions.escalation_pct_yr}%</span>
              <span className="dcf-c-lbl">annual escalation</span>
            </div>
          </div>
        </>
      )}

      <style>{`
        .dcf-root { padding: 16px; background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle); border-radius: 12px; font-family: "DM Sans", -apple-system, sans-serif; display: flex; flex-direction: column; gap: 14px; }
        .dcf-head { display: flex; justify-content: space-between; align-items: baseline; }
        .dcf-title { margin: 0; font-size: 13px; font-weight: 700; color: var(--ink); }
        .dcf-sub { font-family: var(--mono); font-size: 11px; color: var(--cds-text-helper); }
        .dcf-tiers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
        .dcf-tier { padding: 10px; background: var(--cds-layer-02); border: 2px solid transparent; border-radius: 8px; cursor: pointer; text-align: left; font: inherit; }
        .dcf-tier-on { border-color: var(--gold); background: rgba(var(--accent-rgb),0.08); }
        .dcf-tier-lbl { font-size: 12px; font-weight: 700; color: var(--ink); }
        .dcf-tier-hint { font-size: 10px; color: var(--cds-text-helper); margin-top: 3px; }
        .dcf-sliders { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
        .dcf-s { display: flex; flex-direction: column; gap: 6px; }
        .dcf-s-lbl { font-size: 11px; font-weight: 600; color: var(--cds-text-secondary); }
        .dcf-s-u { color: var(--cds-text-helper); font-weight: 500; }
        .dcf-s-row { display: flex; align-items: center; gap: 10px; }
        .dcf-s-row input[type=range] { flex: 1; accent-color: var(--gold); }
        .dcf-s-val { font-family: var(--mono); font-size: 13px; font-weight: 700; color: var(--ink); min-width: 50px; text-align: right; }
        .dcf-loading { color: var(--cds-text-helper); font-size: 12px; }
        .dcf-kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; }
        .dcf-k { padding: 8px; background: var(--cds-layer-02); border-radius: 6px; }
        .dcf-k-l { font-size: 8px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--cds-text-helper); }
        .dcf-k-v { font-family: var(--mono); font-size: 13px; font-weight: 700; color: var(--ink); margin-top: 3px; }
        .dcf-k-hero { font-size: 17px; color: var(--gold-dark); }
        .dcf-good { color: var(--cds-support-success); }
        .dcf-warn { color: var(--cds-support-warning); }
        .dcf-ramp-title { font-size: 10px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--cds-text-helper); margin-bottom: 6px; }
        .dcf-ramp-bars { display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; }
        .dcf-ramp-col { display: flex; flex-direction: column; align-items: center; gap: 3px; }
        .dcf-ramp-util { width: 100%; height: 60px; background: var(--cds-layer-03); border-radius: 4px; display: flex; align-items: flex-end; overflow: hidden; }
        .dcf-ramp-fill { width: 100%; background: linear-gradient(180deg, var(--gold), var(--gold-dark)); }
        .dcf-ramp-y { font-family: var(--mono); font-size: 10px; font-weight: 700; color: var(--ink); }
        .dcf-ramp-mw { font-family: var(--mono); font-size: 9px; color: var(--cds-text-secondary); }
        .dcf-ramp-ut { font-family: var(--mono); font-size: 8px; color: var(--cds-text-helper); }
        .dcf-contract { padding: 10px; background: var(--cds-layer-02); border-radius: 8px; }
        .dcf-c-title { font-size: 10px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--cds-text-helper); margin-bottom: 6px; }
        .dcf-c-grid { display: grid; grid-template-columns: auto 1fr; gap: 4px 10px; font-size: 11px; color: var(--cds-text-secondary); }
        .dcf-c-grid > span:nth-child(odd) { font-family: var(--mono); font-weight: 700; color: var(--ink); }
        .dcf-c-lbl { color: var(--cds-text-secondary); }
      `}</style>
    </div>
  );
}
