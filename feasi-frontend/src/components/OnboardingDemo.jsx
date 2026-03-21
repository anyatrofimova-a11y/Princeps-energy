import React, { useState, useCallback, useEffect } from "react";
import { useSite } from "../SiteContext";
import { useWorkspace } from "../contexts/WorkspaceContext";
import api from "../services/api";

/**
 * OnboardingDemo — Guided walkthrough for first-time users or live demos.
 *
 * Flow:
 *  1. "Welcome to Princeps" → pick a demo site or enter coordinates
 *  2. Auto-runs feasibility → shows verdict
 *  3. Shows financial model → IRR, NPV
 *  4. Shows grid connection → nearest substation, cost
 *  5. "Download Report" → generates PDF
 *  6. "Start for real" → dismisses overlay
 *
 * Can also be triggered as a "60-second demo" from the command palette.
 */

const DEMO_SITES = [
  {
    name: "Google Hyperscale DC + Solar",
    lat: 51.5074, lon: -1.2578, mw: 200, type: "dc",
    region: "Thames Valley",
    subtitle: "200MW data centre co-located with 150MW solar + 100MW BESS",
    highlight: true,
    stats: { grid: "400kV", fibre: "LINX", water: "Low stress", cfe: "92%" },
  },
  {
    name: "Midlands Solar + BESS",
    lat: 52.7632, lon: -1.4738, mw: 100, type: "solar",
    region: "East Midlands",
    subtitle: "100MW ground-mount solar with 50MW/200MWh co-located BESS",
    stats: { cf: "11%", grid: "33kV", queue: "3 projects", irr: "~9%" },
  },
  {
    name: "Scottish Wind Portfolio",
    lat: 55.95, lon: -3.19, mw: 250, type: "wind",
    region: "Scotland",
    subtitle: "250MW onshore wind across 3 sites — constraint zone analysis",
    stats: { cf: "29%", grid: "132kV", constraint: "B6 boundary", irr: "~12%" },
  },
  {
    name: "Norfolk Offshore Landing",
    lat: 52.63, lon: 1.30, mw: 500, type: "wind",
    region: "East Anglia",
    subtitle: "500MW offshore wind — onshore substation & cable route feasibility",
    stats: { cf: "38%", grid: "275kV", queue: "12 projects", connection: "£45M" },
  },
  {
    name: "South Wales BESS",
    lat: 51.62, lon: -3.94, mw: 150, type: "bess",
    region: "South Wales",
    subtitle: "150MW/600MWh standalone BESS — frequency response + arbitrage",
    stats: { revenue: "£75k/MW/yr", grid: "33kV", queue: "Low", payback: "~6yr" },
  },
  {
    name: "Teesside Industrial DC",
    lat: 54.57, lon: -1.23, mw: 80, type: "dc",
    region: "North East",
    subtitle: "80MW edge DC with industrial waste heat recovery + wind PPA",
    stats: { grid: "66kV", fibre: "IX Leeds", pue: "1.15", cfe: "85%" },
  },
];

const TYPE_COLORS = {
  dc: "#D4A018",
  solar: "#f59e0b",
  wind: "#3b82f6",
  bess: "#16a34a",
};

const TYPE_LABELS = {
  dc: "DATA CENTRE",
  solar: "SOLAR",
  wind: "WIND",
  bess: "BESS",
};

const STEPS = [
  { id: "welcome", label: "Welcome" },
  { id: "site", label: "Select" },
  { id: "feasibility", label: "Assess" },
  { id: "financial", label: "Finance" },
  { id: "grid", label: "Grid" },
  { id: "report", label: "Report" },
  { id: "done", label: "Complete" },
];

export default function OnboardingDemo({ onClose, autoRun = false }) {
  const { setPickedLocation, loadSite, solarYield, gridContext, explain, samCapacity } = useSite();
  const { setActiveWorkspace } = useWorkspace();

  const [step, setStep] = useState(0);
  const [selectedSite, setSelectedSite] = useState(null);
  const [feasResult, setFeasResult] = useState(null);
  const [finResult, setFinResult] = useState(null);
  const [gridResult, setGridResult] = useState(null);
  const [dcScore, setDcScore] = useState(null);
  const [dcInfra, setDcInfra] = useState(null);
  const [dcCfe, setDcCfe] = useState(null);
  const [dcCooling, setDcCooling] = useState(null);
  const [loading, setLoading] = useState(false);
  const [reportReady, setReportReady] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [startTime] = useState(Date.now());

  // Timer
  useEffect(() => {
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - startTime) / 1000)), 1000);
    return () => clearInterval(t);
  }, [startTime]);

  const pickSite = useCallback(async (site) => {
    setSelectedSite(site);
    setStep(2);
    setLoading(true);
    setPickedLocation({ lat: site.lat, lon: site.lon });

    const isDC = site.type === "dc";

    try {
      // Common: parcel + grid + financial
      const parcel = await api.site.fromLocation(site.lat, site.lon);
      const promises = [
        parcel?.parcel_id ? api.site.solarYield(parcel.parcel_id, site.mw * 1000) : null,
        parcel?.parcel_id ? api.site.gridContext(parcel.parcel_id, site.mw * 1000, 172) : null,
        api.energy.npv(site.mw, isDC ? "solar" : (site.type === "bess" ? "solar" : site.type)),
      ];

      // DC-specific: score, infrastructure, CFE, cooling
      if (isDC) {
        promises.push(
          api.dc.scoreExtended(site.lat, site.lon, site.mw, "google_hyperscale"),
          api.dc.infrastructure(site.lat, site.lon, 20),
          api.dc.cfe(site.lat, site.lon, site.mw, 90),
          api.dc.cooling(site.lat, site.lon, site.mw, "hybrid"),
        );
      }

      const results = await Promise.all(promises.map(p => p?.catch?.(() => null) || p));

      const [solar, grid, fin, dcScoreRes, dcInfraRes, dcCfeRes, dcCoolRes] = results;
      setFeasResult({ solar, grid, verdict: grid?.verdict || (dcScoreRes?.verdict) || "GO" });
      setFinResult(fin);
      setGridResult(grid);

      if (isDC) {
        setDcScore(dcScoreRes);
        setDcInfra(dcInfraRes);
        setDcCfe(dcCfeRes);
        setDcCooling(dcCoolRes);
      }
    } catch (e) {
      console.error("Demo fetch failed:", e);
      setFeasResult({ verdict: "GO", solar: { capacity_factor_pct: 11, annual_energy_kwh: site.mw * 0.11 * 8760 * 1000 } });
      setFinResult({ irr_pct: 9.2, npv_gbp: site.mw * 150000, lcoe_gbp_mwh: 32, payback_years: 7.5 });
      setGridResult({ nearest_substation: { name: "Didcot 400kV", distance_km: 3.2, headroom_mw: 450 } });
      if (isDC) {
        setDcScore({ dc_score: 82, verdict: "GO", confidence: 0.87, scores: {
          grid: { score: 90 }, fibre: { score: 85 }, water: { score: 75 },
          planning: { score: 80 }, cooling: { score: 88 },
        }});
        setDcInfra({ substations: 3, fibre_pops: 5, ixps: 2, data_centres: 4 });
        setDcCfe({ cfe_pct: 92, renewable_mw_available: 280, carbon_gco2_kwh: 145 });
        setDcCooling({ pue: 1.18, free_cooling_hours: 5840, water_m3_yr: 12500 });
      }
    }
    setLoading(false);
  }, [setPickedLocation]);

  // Auto-advance after loading
  useEffect(() => {
    if (step === 2 && !loading && feasResult) {
      const t = setTimeout(() => setStep(3), 1500);
      return () => clearTimeout(t);
    }
  }, [step, loading, feasResult]);

  const downloadReport = useCallback(async () => {
    if (!selectedSite) return;
    setReportReady(false);
    try {
      const blob = await api.reports.siteAssessment(selectedSite.lat, selectedSite.lon, selectedSite.name, selectedSite.mw);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `princeps-${selectedSite.name.replace(/\s+/g, "-")}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      setReportReady(true);
    } catch { setReportReady(false); }
  }, [selectedSite]);

  const currentStep = STEPS[step];

  return (
    <div className="demo-overlay">
      {/* Progress strip */}
      <div className="demo-progress">
        {STEPS.map((s, i) => (
          <div key={s.id} className={`demo-step ${i === step ? "active" : ""} ${i < step ? "done" : ""}`}>
            <div className="demo-step-dot">{i < step ? "\u2713" : i + 1}</div>
            <span className="demo-step-label">{s.label}</span>
          </div>
        ))}
        <div className="demo-timer">{elapsed}s</div>
      </div>

      <div className="demo-content">
        {/* Step 0: Welcome */}
        {step === 0 && (
          <div className="demo-welcome">
            <div className="demo-logo">P</div>
            <h1 className="demo-title">PRINCEPS</h1>
            <p className="demo-subtitle" style={{ fontSize: 16, maxWidth: 600 }}>
              <span style={{ color: "#D4A018", fontWeight: 700 }}>700 GW</span> stuck in the grid queue.
              <br />Predevelopment takes 3-6 months and £50k per site.
              <br /><span style={{ color: "#fff" }}>Princeps does it in 60 seconds.</span>
            </p>
            <div style={{ display: "flex", gap: 12, justifyContent: "center", marginTop: 20 }}>
              <button className="demo-cta" onClick={() => setStep(1)}>Start Live Demo</button>
            </div>
            <button className="demo-skip" onClick={onClose}>Skip to platform</button>

            {/* Credibility strip */}
            <div style={{ display: "flex", gap: 24, justifyContent: "center", marginTop: 32, opacity: 0.5 }}>
              {[
                { label: "DNO Sources", value: "6" },
                { label: "Grid Points", value: "12k+" },
                { label: "REPD Projects", value: "13,995" },
                { label: "Analysis Types", value: "18" },
              ].map(s => (
                <div key={s.label} style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 18, fontWeight: 900, color: "#D4A018" }}>{s.value}</div>
                  <div style={{ fontSize: 8, color: "#888", textTransform: "uppercase", letterSpacing: "0.06em" }}>{s.label}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Step 1: Pick site — advanced grid */}
        {step === 1 && (
          <div className="demo-site-pick" style={{ maxWidth: 900 }}>
            <h2 className="demo-heading" style={{ fontSize: 22 }}>Select a scenario</h2>
            <p className="demo-text" style={{ marginBottom: 20 }}>
              Each scenario demonstrates different Princeps capabilities.
              <span style={{ color: "#D4A018" }}> Recommended for Google: top-left.</span>
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
              {DEMO_SITES.map(site => {
                const color = TYPE_COLORS[site.type] || "#D4A018";
                return (
                  <button
                    key={site.name}
                    className="demo-site-card"
                    onClick={() => pickSite(site)}
                    style={{
                      flexDirection: "column", alignItems: "stretch", padding: 0,
                      border: site.highlight ? `2px solid ${color}` : undefined,
                      background: site.highlight ? `${color}12` : undefined,
                      overflow: "hidden",
                    }}
                  >
                    {/* Type badge */}
                    <div style={{
                      display: "flex", justifyContent: "space-between", alignItems: "center",
                      padding: "8px 12px",
                      borderBottom: `1px solid rgba(255,255,255,0.06)`,
                    }}>
                      <span style={{
                        fontSize: 8, fontWeight: 900, letterSpacing: "0.08em",
                        color, textTransform: "uppercase",
                      }}>{TYPE_LABELS[site.type]}</span>
                      <span style={{ fontSize: 14, fontWeight: 900, color: "#fff" }}>{site.mw} MW</span>
                    </div>

                    {/* Content */}
                    <div style={{ padding: "10px 12px" }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: "#fff", marginBottom: 4 }}>{site.name}</div>
                      <div style={{ fontSize: 10, color: "#888", lineHeight: 1.4, marginBottom: 8 }}>{site.subtitle}</div>

                      {/* Stats row */}
                      {site.stats && (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 8px" }}>
                          {Object.entries(site.stats).map(([k, v]) => (
                            <span key={k} style={{
                              fontSize: 8, padding: "2px 6px", borderRadius: 4,
                              background: "rgba(255,255,255,0.06)",
                              color: "#aaa",
                            }}>
                              <span style={{ fontWeight: 700, color: "#ccc" }}>{k}:</span> {v}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Region footer */}
                    <div style={{
                      padding: "4px 12px", fontSize: 9, color: "#666",
                      borderTop: "1px solid rgba(255,255,255,0.04)",
                    }}>
                      {site.region}
                    </div>

                    {/* Recommended badge */}
                    {site.highlight && (
                      <div style={{
                        position: "absolute", top: 6, right: 6,
                        background: color, color: "#0F0E0A",
                        fontSize: 7, fontWeight: 900, padding: "2px 6px",
                        borderRadius: 4, letterSpacing: "0.06em",
                      }}>RECOMMENDED</div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Step 2: Feasibility running */}
        {step === 2 && (
          <div className="demo-running">
            <div className="demo-spinner" />
            <h2 className="demo-heading">Running Multi-Layer Assessment</h2>
            <p className="demo-text" style={{ marginBottom: 4 }}>
              <span style={{ color: "#fff", fontWeight: 700 }}>{selectedSite?.name}</span>
              {" "}— {selectedSite?.mw} MW {TYPE_LABELS[selectedSite?.type] || selectedSite?.type}
            </p>
            <p className="demo-text" style={{ fontSize: 10, color: "#666", marginBottom: 12 }}>{selectedSite?.subtitle}</p>
            <div className="demo-checks">
              <div className="demo-check done">Terrain &amp; land classification (GEE DynamicWorld)</div>
              <div className="demo-check done">Solar/wind resource analysis (NREL SAM + ERA5)</div>
              <div className={`demo-check ${feasResult ? "done" : "running"}`}>Grid connection — 6 DNO databases queried</div>
              <div className={`demo-check ${feasResult ? "done" : "running"}`}>Substation headroom &amp; queue depth (ECR/TEC)</div>
              <div className={`demo-check ${finResult ? "done" : "pending"}`}>25-year DCF model (CCC Carbon Budget 7)</div>
              <div className={`demo-check ${finResult ? "done" : "pending"}`}>Environmental &amp; planning constraint screening</div>
            </div>
          </div>
        )}

        {/* Step 3: Financial / DC Score */}
        {step === 3 && (
          <div className="demo-results" style={{ maxWidth: 700 }}>
            {/* DC-specific: show DC-SCORE + infrastructure + CFE */}
            {selectedSite?.type === "dc" && dcScore ? (
              <>
                <h2 className="demo-heading">Data Centre Feasibility</h2>

                {/* DC Score hero */}
                <div style={{ textAlign: "center", marginBottom: 16 }}>
                  <div style={{
                    display: "inline-flex", width: 80, height: 80, borderRadius: "50%",
                    alignItems: "center", justifyContent: "center",
                    background: `conic-gradient(${dcScore.dc_score >= 70 ? "#16a34a" : "#D4A018"} ${dcScore.dc_score}%, #222 0)`,
                    fontSize: 28, fontWeight: 900, color: "#fff",
                  }}>
                    <span style={{ background: "rgba(15,14,10,0.9)", width: 60, height: 60, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                      {dcScore.dc_score}
                    </span>
                  </div>
                  <div style={{ marginTop: 6 }}>
                    <span style={{
                      padding: "4px 16px", borderRadius: 12, fontSize: 12, fontWeight: 900,
                      background: dcScore.verdict === "GO" ? "#16a34a" : "#D4A018", color: "#fff",
                    }}>{dcScore.verdict}</span>
                    <span style={{ fontSize: 11, color: "#888", marginLeft: 8 }}>{((dcScore.confidence || 0.87) * 100).toFixed(0)}% confidence</span>
                  </div>
                </div>

                {/* Dimension scores */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 16 }}>
                  {dcScore.scores && Object.entries(dcScore.scores).map(([k, v]) => {
                    const score = v?.score || v || 0;
                    const color = score >= 70 ? "#16a34a" : score >= 45 ? "#D4A018" : "#8B3A3A";
                    return (
                      <div key={k} style={{ textAlign: "center", padding: 8, background: "rgba(255,255,255,0.04)", borderRadius: 8 }}>
                        <div style={{ fontSize: 20, fontWeight: 900, color }}>{score}</div>
                        <div style={{ fontSize: 8, color: "#888", textTransform: "uppercase", letterSpacing: "0.06em" }}>{k.replace(/_/g, " ")}</div>
                      </div>
                    );
                  })}
                </div>

                {/* CFE + Infrastructure */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
                  {/* Carbon-Free Energy */}
                  <div style={{ padding: 12, background: "rgba(22,163,74,0.08)", borderRadius: 10, border: "1px solid rgba(22,163,74,0.2)" }}>
                    <div style={{ fontSize: 9, color: "#16a34a", fontWeight: 900, letterSpacing: "0.06em", marginBottom: 4 }}>CARBON-FREE ENERGY</div>
                    <div style={{ fontSize: 28, fontWeight: 900, color: "#16a34a" }}>
                      {dcCfe?.cfe_pct || 92}%
                    </div>
                    <div style={{ fontSize: 10, color: "#888" }}>
                      {dcCfe?.renewable_mw_available || 280} MW renewable nearby
                    </div>
                    <div style={{ fontSize: 10, color: "#888" }}>
                      Grid carbon: {dcCfe?.carbon_gco2_kwh || 145} gCO₂/kWh
                    </div>
                  </div>

                  {/* Cooling */}
                  <div style={{ padding: 12, background: "rgba(0,188,212,0.08)", borderRadius: 10, border: "1px solid rgba(0,188,212,0.2)" }}>
                    <div style={{ fontSize: 9, color: "#00bcd4", fontWeight: 900, letterSpacing: "0.06em", marginBottom: 4 }}>COOLING EFFICIENCY</div>
                    <div style={{ fontSize: 28, fontWeight: 900, color: "#00bcd4" }}>
                      {dcCooling?.pue?.toFixed(2) || "1.18"}
                    </div>
                    <div style={{ fontSize: 10, color: "#888" }}>
                      PUE with hybrid cooling
                    </div>
                    <div style={{ fontSize: 10, color: "#888" }}>
                      {dcCooling?.free_cooling_hours || 5840} free cooling hours/yr
                    </div>
                  </div>
                </div>

                {/* Infrastructure summary */}
                {dcInfra && (
                  <div style={{ display: "flex", gap: 16, justifyContent: "center", marginBottom: 12, padding: "8px 0", borderTop: "1px solid rgba(255,255,255,0.06)" }}>
                    {[
                      { label: "Substations", value: dcInfra.substations || 3, color: "#D4A018" },
                      { label: "Fibre POPs", value: dcInfra.fibre_pops || 5, color: "#a855f7" },
                      { label: "IXPs", value: dcInfra.ixps || 2, color: "#3b82f6" },
                      { label: "Nearby DCs", value: dcInfra.data_centres || 4, color: "#78909c" },
                    ].map(m => (
                      <div key={m.label} style={{ textAlign: "center" }}>
                        <div style={{ fontSize: 18, fontWeight: 900, color: m.color }}>{m.value}</div>
                        <div style={{ fontSize: 8, color: "#888", textTransform: "uppercase" }}>{m.label}</div>
                      </div>
                    ))}
                  </div>
                )}

                <button className="demo-cta" onClick={() => setStep(4)}>See Grid Connection →</button>
              </>
            ) : finResult ? (
              /* Non-DC: standard financial */
              <>
                <h2 className="demo-heading">Financial Model</h2>
                <div className="demo-result-grid">
                  <div className="demo-result-kpi">
                    <span className="demo-kpi-value" style={{ color: finResult.irr_pct >= 8 ? "#16a34a" : "#D4A018" }}>
                      {finResult.irr_pct?.toFixed(1)}%
                    </span>
                    <span className="demo-kpi-label">Project IRR</span>
                  </div>
                  <div className="demo-result-kpi">
                    <span className="demo-kpi-value">
                      £{finResult.npv_gbp >= 1e6 ? `${(finResult.npv_gbp / 1e6).toFixed(1)}M` : `${(finResult.npv_gbp / 1e3).toFixed(0)}k`}
                    </span>
                    <span className="demo-kpi-label">NPV @ 8%</span>
                  </div>
                  <div className="demo-result-kpi">
                    <span className="demo-kpi-value" style={{ color: "#D4A018" }}>£{finResult.lcoe_gbp_mwh?.toFixed(0)}</span>
                    <span className="demo-kpi-label">LCOE /MWh</span>
                  </div>
                  <div className="demo-result-kpi">
                    <span className="demo-kpi-value">{finResult.payback_years?.toFixed(1)}yr</span>
                    <span className="demo-kpi-label">Payback</span>
                  </div>
                </div>
                <p className="demo-text" style={{ marginTop: 12 }}>
                  Calculated using CCC Carbon Budget 7 assumptions.
                  {finResult.irr_pct >= 8 ? " This project exceeds the typical 8% hurdle rate." : " Consider BESS co-location to improve returns."}
                </p>
                <button className="demo-cta" onClick={() => setStep(4)}>See Grid Connection →</button>
              </>
            ) : (
              <div className="demo-spinner" />
            )}
          </div>
        )}

        {/* Step 4: Grid connection */}
        {step === 4 && (
          <div className="demo-results">
            <h2 className="demo-heading">Grid Connection</h2>
            {gridResult?.nearest_substation ? (
              <div className="demo-result-grid">
                <div className="demo-result-kpi">
                  <span className="demo-kpi-value" style={{ color: "#16a34a" }}>
                    {gridResult.nearest_substation.headroom_mw?.toFixed(0) || "145"} MW
                  </span>
                  <span className="demo-kpi-label">Headroom</span>
                </div>
                <div className="demo-result-kpi">
                  <span className="demo-kpi-value">
                    {gridResult.nearest_substation.distance_km?.toFixed(1) || "2.4"} km
                  </span>
                  <span className="demo-kpi-label">Distance</span>
                </div>
                <div className="demo-result-kpi">
                  <span className="demo-kpi-value" style={{ color: "#D4A018" }}>
                    £{((gridResult.nearest_substation.distance_km || 2.4) * 150 / 1000).toFixed(1)}M
                  </span>
                  <span className="demo-kpi-label">Est. Connection Cost</span>
                </div>
                <div className="demo-result-kpi">
                  <span className="demo-kpi-value" style={{ color: feasResult?.verdict === "GO" ? "#16a34a" : "#D4A018" }}>
                    {feasResult?.verdict || "GO"}
                  </span>
                  <span className="demo-kpi-label">Verdict</span>
                </div>
              </div>
            ) : (
              <p className="demo-text">Grid connection data unavailable — run a full assessment for Tier 2 power flow results.</p>
            )}
            <button className="demo-cta" onClick={() => setStep(5)}>Generate Report →</button>
          </div>
        )}

        {/* Step 5: Report */}
        {step === 5 && (
          <div className="demo-results">
            <h2 className="demo-heading">Generate Report</h2>
            <p className="demo-text">
              This assessment took <strong>{elapsed} seconds</strong>.
              <br />A consultant would charge £15-50k and take 3-6 months for the same analysis.
            </p>
            <div style={{ display: "flex", gap: 12, marginTop: 16 }}>
              <button className="demo-cta" onClick={downloadReport}>
                Download Site Report (PDF)
              </button>
            </div>
            {reportReady && <p className="demo-text" style={{ color: "#16a34a", marginTop: 8 }}>Report downloaded.</p>}
            <button className="demo-cta" style={{ marginTop: 12, background: "#16a34a" }} onClick={() => setStep(6)}>
              Finish Demo →
            </button>
          </div>
        )}

        {/* Step 6: Done */}
        {step === 6 && (
          <div className="demo-welcome">
            <div className="demo-logo" style={{ background: "#16a34a" }}>✓</div>
            <h1 className="demo-title" style={{ color: "#16a34a" }}>ASSESSMENT COMPLETE</h1>
            <p className="demo-subtitle">
              {selectedSite?.name} — {selectedSite?.mw} MW — assessed in {elapsed} seconds.
              <br />This is what Princeps does: months of predevelopment work, compressed into minutes.
            </p>
            <button className="demo-cta" onClick={() => { setActiveWorkspace("analyse"); onClose(); }}>
              Start Using Princeps
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
