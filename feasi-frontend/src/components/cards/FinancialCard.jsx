import React, { useState, useEffect, useCallback } from "react";
import { useSite } from "../../SiteContext";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import MetricCard from "../ui/MetricCard";
import api from "../../services/api";

/**
 * FinancialCard — headline project economics visible in Overview.
 *
 * Shows IRR, NPV, LCOE, payback, PPA price at a glance.
 * Auto-calculates when site capacity and solar yield are available.
 * "Deep dive" opens the full InvestmentPanel in Comply workspace.
 *
 * Uses both:
 *  - /api/energy/npv (CB7 quick model)
 *  - /api/investment/finance/project (full DCF model)
 */

const fmtGbp = (v) => {
  if (v == null) return "—";
  if (Math.abs(v) >= 1e9) return `£${(v / 1e9).toFixed(1)}B`;
  if (Math.abs(v) >= 1e6) return `£${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `£${(v / 1e3).toFixed(0)}k`;
  return `£${v.toFixed(0)}`;
};

function Gauge({ value, max = 20, label, suffix = "%", color }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const gaugeColor = color || (value >= 10 ? "#16a34a" : value >= 6 ? "#D4A018" : "#8B3A3A");
  return (
    <div className="fin-gauge">
      <div className="fin-gauge-track">
        <div className="fin-gauge-fill" style={{ width: `${pct}%`, background: gaugeColor }} />
      </div>
      <div className="fin-gauge-label">
        <span className="fin-gauge-value" style={{ color: gaugeColor }}>
          {value != null ? `${value.toFixed(1)}${suffix}` : "—"}
        </span>
        <span className="fin-gauge-name">{label}</span>
      </div>
    </div>
  );
}

function KPI({ label, value, sub, color }) {
  return (
    <div className="fin-kpi">
      <span className="fin-kpi-value" style={{ color: color || "var(--cds-text-primary)" }}>{value}</span>
      <span className="fin-kpi-label">{label}</span>
      {sub && <span className="fin-kpi-sub">{sub}</span>}
    </div>
  );
}

export default function FinancialCard() {
  const { samCapacity, solarYield, gridContext, parcelId } = useSite();
  const { setActiveWorkspace, setDetailSection, setDetailOpen } = useWorkspace();

  const [finance, setFinance] = useState(null);
  const [cb7, setCb7] = useState(null);
  const [ppa, setPpa] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tech, setTech] = useState("solar");

  const capacityMw = (samCapacity || 100) / 1000;

  const loadFinancials = useCallback(async () => {
    if (capacityMw <= 0) return;
    setLoading(true);
    try {
      const [finRes, cb7Res, ppaRes] = await Promise.all([
        api.investment.projectFinance(capacityMw, tech, "Midlands", 55),
        api.energy.npv(capacityMw, tech),
        api.investment.equityReturns(capacityMw, tech, 0.7, 55),
      ]);
      if (finRes) setFinance(finRes);
      if (cb7Res) setCb7(cb7Res);
      if (ppaRes) setPpa(ppaRes);
    } catch (err) {
      console.error("Financial load error:", err);
    }
    setLoading(false);
  }, [capacityMw, tech]);

  // Auto-load when capacity or yield changes
  useEffect(() => {
    if (capacityMw > 0) loadFinancials();
  }, [capacityMw, tech]);

  const irr = finance?.project_irr ?? cb7?.irr_pct;
  const npv = finance?.npv_8pct ?? cb7?.npv_gbp;
  const lcoe = finance?.lcoe ?? cb7?.lcoe_gbp_mwh;
  const payback = finance?.simple_payback_years ?? cb7?.payback_years;
  const totalCapex = finance?.total_capex ?? cb7?.total_capex_gbp;
  const annualGen = finance?.annual_generation_mwh ?? cb7?.annual_yield_mwh;
  const equityIrr = ppa?.equity_irr;

  const verdictColor = irr >= 10 ? "#16a34a" : irr >= 6 ? "#D4A018" : "#8B3A3A";
  const verdict = irr >= 10 ? "ATTRACTIVE" : irr >= 6 ? "MARGINAL" : "BELOW HURDLE";

  const openDeepDive = () => {
    setActiveWorkspace("comply");
    setDetailSection("investment");
    setDetailOpen(true);
  };

  if (!samCapacity && !parcelId) {
    return (
      <MetricCard title="Financial Model" accentColor="#D4A018">
        <span className="muted">Select a site to see project economics</span>
      </MetricCard>
    );
  }

  return (
    <MetricCard
      title="Financial Model"
      accentColor="#D4A018"
      headerValue={irr != null ? `${irr.toFixed(1)}% IRR` : loading ? "..." : null}
      aiInsight={irr != null ? `${verdict} — ${capacityMw.toFixed(0)} MW ${tech} at £55/MWh PPA` : null}
    >
      {/* Technology selector */}
      <div className="fin-tech-row">
        {["solar", "wind", "bess", "offshore_wind"].map(t => (
          <button
            key={t}
            className={`fin-tech-btn ${tech === t ? "active" : ""}`}
            onClick={() => setTech(t)}
          >
            {t === "offshore_wind" ? "Offshore" : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {loading && <div className="fin-loading">Calculating...</div>}

      {!loading && irr != null && (
        <>
          {/* IRR Gauge */}
          <Gauge value={irr} max={20} label="Project IRR" />

          {/* KPI Grid */}
          <div className="fin-kpi-grid">
            <KPI label="NPV" value={fmtGbp(npv)} sub="@ 8% discount" color={npv > 0 ? "#16a34a" : "#8B3A3A"} />
            <KPI label="LCOE" value={lcoe != null ? `£${lcoe.toFixed(0)}` : "—"} sub="/MWh" color="#D4A018" />
            <KPI label="Payback" value={payback != null ? `${payback}yr` : "—"} sub="simple" />
            <KPI label="CAPEX" value={fmtGbp(totalCapex)} />
          </div>

          {/* Secondary metrics */}
          <div className="fin-secondary">
            <div className="fin-sec-row">
              <span>Annual Generation</span>
              <span>{annualGen ? `${(annualGen / 1000).toFixed(1)} GWh` : "—"}</span>
            </div>
            {equityIrr != null && (
              <div className="fin-sec-row">
                <span>Equity IRR (70% gearing)</span>
                <span style={{ color: equityIrr >= 12 ? "#16a34a" : "#D4A018" }}>{equityIrr.toFixed(1)}%</span>
              </div>
            )}
            <div className="fin-sec-row">
              <span>CB7 Reference LCOE</span>
              <span>{cb7?.lcoe_gbp_mwh != null ? `£${cb7.lcoe_gbp_mwh.toFixed(0)}/MWh` : "—"}</span>
            </div>
            {gridContext?.nearest_substation?.distance_km != null && (
              <div className="fin-sec-row">
                <span>Grid Connection (est.)</span>
                <span>{fmtGbp(gridContext.nearest_substation.distance_km * 150000)}</span>
              </div>
            )}
          </div>

          {/* Cashflow sparkline */}
          {finance?.cashflow_truncated?.length > 0 && (
            <div className="fin-cashflow">
              <div className="fin-cashflow-label">CASHFLOW (Yr 1-5)</div>
              <div className="fin-cashflow-bars">
                {finance.cashflow_truncated.slice(0, 5).map((yr, i) => {
                  const maxCf = Math.max(...finance.cashflow_truncated.map(y => Math.abs(y.net_cashflow || 0)));
                  const h = Math.abs(yr.net_cashflow || 0) / (maxCf || 1) * 100;
                  return (
                    <div key={i} className="fin-cf-bar-wrap" title={`Yr ${yr.year}: ${fmtGbp(yr.net_cashflow)}`}>
                      <div
                        className="fin-cf-bar"
                        style={{
                          height: `${h}%`,
                          background: (yr.net_cashflow || 0) >= 0 ? "#16a34a" : "#8B3A3A",
                        }}
                      />
                      <span className="fin-cf-yr">{yr.year}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Verdict banner */}
          <div className="fin-verdict" style={{ background: `${verdictColor}10`, borderColor: `${verdictColor}30` }}>
            <span className="fin-verdict-dot" style={{ background: verdictColor }} />
            <span className="fin-verdict-text" style={{ color: verdictColor }}>{verdict}</span>
            <span className="fin-verdict-detail">
              {irr >= 10 ? "Exceeds typical 8-10% hurdle rate"
                : irr >= 6 ? "Below typical hurdle — consider BESS co-location"
                : "Does not meet minimum return threshold"}
            </span>
          </div>

          {/* Deep dive button */}
          <button className="fin-deepdive-btn" onClick={openDeepDive}>
            Full Investment Analysis →
          </button>
        </>
      )}
    </MetricCard>
  );
}
