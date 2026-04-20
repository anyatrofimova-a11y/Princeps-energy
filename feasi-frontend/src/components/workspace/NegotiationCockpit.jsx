import React, { useState, useMemo, useEffect } from "react";

/**
 * NegotiationCockpit — sliders for PPA floor / tenor / escalation with
 * live IRR / DSCR / LCOE response. Designed for a counterparty meeting:
 * you adjust a slider, the lender tests flip on the right.
 *
 * Data source: POST /api/finance/negotiate
 */

const PPA_FLOORS = [40, 45, 50, 55, 60, 65, 70, 75, 80, 85];
const TENORS = [5, 7, 10, 12, 15];
const ESCALATIONS = [0, 1.5, 2.5, 3.5];

export default function NegotiationCockpit({
  capex_gbp_m = 40, opex_gbp_m_yr = 2.5, base_revenue_gbp_m_yr = 6,
}) {
  const [ppaFloor, setPpaFloor] = useState(55);
  const [tenor, setTenor] = useState(10);
  const [esc, setEsc] = useState(2.5);
  const [surface, setSurface] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch("/api/finance/negotiate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        capex_gbp_m, opex_gbp_m_yr, base_revenue_gbp_m_yr,
        ppa_floor_range: PPA_FLOORS, tenor_range_years: TENORS, escalation_pct_range: ESCALATIONS,
      }),
    }).then(r => r.json()).then(j => { if (!cancelled) setSurface(j.surface || []); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [capex_gbp_m, opex_gbp_m_yr, base_revenue_gbp_m_yr]);

  const current = useMemo(() => {
    return surface.find(r => r.ppa_floor_gbp_mwh === ppaFloor
                          && r.tenor_years === tenor
                          && r.escalation_pct === esc) || null;
  }, [surface, ppaFloor, tenor, esc]);

  const base = useMemo(() => {
    return surface.find(r => r.ppa_floor_gbp_mwh === 55 && r.tenor_years === 10 && r.escalation_pct === 2.5) || null;
  }, [surface]);

  const dscrPass = current && current.dscr >= 1.30;

  return (
    <div className="nc-root">
      <header className="nc-head">
        <h3 className="nc-title">Negotiation cockpit · PPA terms</h3>
        <span className={"nc-verdict" + (dscrPass ? " nc-verdict-go" : " nc-verdict-warn")}>
          {dscrPass ? "PASSES LENDER COVENANT" : "BELOW 1.30× DSCR"}
        </span>
      </header>

      <div className="nc-sliders">
        <Slider label="PPA floor" unit="£/MWh" value={ppaFloor} options={PPA_FLOORS} onChange={setPpaFloor} />
        <Slider label="Tenor"     unit="yrs"    value={tenor}    options={TENORS}    onChange={setTenor} />
        <Slider label="Escalation" unit="%/yr"  value={esc}      options={ESCALATIONS} onChange={setEsc} />
      </div>

      <div className="nc-kpis">
        <Kpi label="IRR"  value={current?.irr_pct} unit="%"  base={base?.irr_pct}  higherBetter />
        <Kpi label="DSCR" value={current?.dscr}    unit="×"  base={base?.dscr}    higherBetter />
        <Kpi label="NPV"  value={current?.npv_gbp_m} unit="£M" base={base?.npv_gbp_m} higherBetter />
        <Kpi label="LCOE" value={current?.lcoe_gbp_mwh} unit="£/MWh" base={base?.lcoe_gbp_mwh} higherBetter={false} />
      </div>

      <div className="nc-hint">
        Sliders pivot around base-case PPA £55/MWh · 10y · 2.5%/yr. Values above recalculate live
        against {surface.length} scenario points.
      </div>

      <style>{`
        .nc-root { padding: 16px; background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle); border-radius: 12px; font-family: "DM Sans", -apple-system, sans-serif; display: flex; flex-direction: column; gap: 14px; }
        .nc-head { display: flex; justify-content: space-between; align-items: center; }
        .nc-title { margin: 0; font-size: 13px; font-weight: 700; color: var(--ink); }
        .nc-verdict {
          font-family: var(--mono); font-size: 10px; font-weight: 700; letter-spacing: 0.06em;
          padding: 3px 8px; border-radius: 4px;
        }
        .nc-verdict-go { background: rgba(22,163,74,0.12); color: var(--cds-support-success); }
        .nc-verdict-warn { background: rgba(232,160,18,0.14); color: var(--cds-support-warning); }
        .nc-sliders { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
        .nc-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; padding-top: 8px; border-top: 1px dashed var(--cds-border-subtle); }
        .nc-hint { font-size: 10px; color: var(--cds-text-helper); font-style: italic; }
      `}</style>
    </div>
  );
}

function Slider({ label, unit, value, options, onChange }) {
  const idx = Math.max(0, options.indexOf(value));
  return (
    <div className="nc-s">
      <div className="nc-s-lbl">{label} <span className="nc-s-u">{unit}</span></div>
      <div className="nc-s-row">
        <input
          type="range"
          min="0" max={options.length - 1} step="1"
          value={idx}
          onChange={(e) => onChange(options[Number(e.target.value)])}
        />
        <span className="nc-s-val">{value}{unit === "%/yr" ? "%" : ""}</span>
      </div>
      <style>{`
        .nc-s { display: flex; flex-direction: column; gap: 6px; }
        .nc-s-lbl { font-size: 11px; font-weight: 600; color: var(--cds-text-secondary); }
        .nc-s-u { color: var(--cds-text-helper); font-weight: 500; }
        .nc-s-row { display: flex; align-items: center; gap: 10px; }
        .nc-s-row input[type=range] { flex: 1; accent-color: var(--gold); }
        .nc-s-val { font-family: var(--mono); font-size: 13px; font-weight: 700; color: var(--ink); min-width: 46px; text-align: right; }
      `}</style>
    </div>
  );
}

function Kpi({ label, value, unit, base, higherBetter }) {
  const delta = (value != null && base != null) ? (value - base) : null;
  const good = delta != null && (higherBetter ? delta > 0 : delta < 0);
  const colour = delta == null ? "var(--cds-text-helper)"
               : Math.abs(delta) < 0.01 ? "var(--cds-text-helper)"
               : good ? "var(--cds-support-success)" : "var(--cds-support-error)";
  return (
    <div className="nc-k">
      <div className="nc-k-l">{label}</div>
      <div className="nc-k-v">{value != null ? value : "—"}<span className="nc-k-u">{unit}</span></div>
      {delta != null && Math.abs(delta) > 0.001 && (
        <div className="nc-k-d" style={{ color: colour }}>
          {delta > 0 ? "+" : ""}{typeof delta === "number" ? delta.toFixed(2) : delta} vs base
        </div>
      )}
      <style>{`
        .nc-k { padding: 10px 12px; background: var(--cds-layer-02); border-radius: 8px; }
        .nc-k-l { font-size: 9px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--cds-text-helper); }
        .nc-k-v { font-family: var(--mono); font-size: 16px; font-weight: 700; color: var(--ink); margin-top: 3px; }
        .nc-k-u { font-size: 10px; color: var(--cds-text-helper); margin-left: 2px; font-weight: 500; }
        .nc-k-d { font-family: var(--mono); font-size: 10px; font-weight: 700; margin-top: 3px; }
      `}</style>
    </div>
  );
}
