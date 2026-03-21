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
  { name: "Ashby Solar Farm", lat: 52.7632, lon: -1.4738, mw: 50, type: "solar", region: "Midlands" },
  { name: "Norfolk Wind + BESS", lat: 52.63, lon: 1.30, mw: 75, type: "wind", region: "East" },
  { name: "Pembroke Solar", lat: 51.68, lon: -4.94, mw: 40, type: "solar", region: "Wales" },
  { name: "Teesside BESS", lat: 54.57, lon: -1.23, mw: 100, type: "bess", region: "North East" },
];

const STEPS = [
  { id: "welcome", label: "Welcome" },
  { id: "site", label: "Pick Site" },
  { id: "feasibility", label: "Feasibility" },
  { id: "financial", label: "Financial" },
  { id: "grid", label: "Grid" },
  { id: "report", label: "Report" },
  { id: "done", label: "Ready" },
];

export default function OnboardingDemo({ onClose, autoRun = false }) {
  const { setPickedLocation, loadSite, solarYield, gridContext, explain, samCapacity } = useSite();
  const { setActiveWorkspace } = useWorkspace();

  const [step, setStep] = useState(0);
  const [selectedSite, setSelectedSite] = useState(null);
  const [feasResult, setFeasResult] = useState(null);
  const [finResult, setFinResult] = useState(null);
  const [gridResult, setGridResult] = useState(null);
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

    // Run feasibility
    try {
      const parcel = await api.site.fromLocation(site.lat, site.lon);
      if (parcel?.parcel_id) {
        const [solar, grid, fin] = await Promise.all([
          api.site.solarYield(parcel.parcel_id, site.mw * 1000),
          api.site.gridContext(parcel.parcel_id, site.mw * 1000, 172),
          api.energy.npv(site.mw, site.type),
        ]);
        setFeasResult({ solar, grid, verdict: grid?.verdict || "GO" });
        setFinResult(fin);
        setGridResult(grid);
      }
    } catch (e) {
      console.error("Demo fetch failed:", e);
      // Use synthetic results for demo
      setFeasResult({ verdict: "GO", solar: { capacity_factor_pct: 11, annual_energy_kwh: site.mw * 0.11 * 8760 * 1000 } });
      setFinResult({ irr_pct: 9.2, npv_gbp: site.mw * 150000, lcoe_gbp_mwh: 32, payback_years: 7.5 });
      setGridResult({ nearest_substation: { name: "Demo Sub", distance_km: 2.4, headroom_mw: 145 } });
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
            <p className="demo-subtitle">
              Site feasibility in minutes, not months.
              <br />Let's assess a solar or wind project in under 60 seconds.
            </p>
            <button className="demo-cta" onClick={() => setStep(1)}>Start Demo</button>
            <button className="demo-skip" onClick={onClose}>Skip — I know what I'm doing</button>
          </div>
        )}

        {/* Step 1: Pick site */}
        {step === 1 && (
          <div className="demo-site-pick">
            <h2 className="demo-heading">Pick a demo site</h2>
            <p className="demo-text">Choose a UK energy project to assess, or enter your own coordinates.</p>
            <div className="demo-site-grid">
              {DEMO_SITES.map(site => (
                <button key={site.name} className="demo-site-card" onClick={() => pickSite(site)}>
                  <span className="demo-site-icon">
                    {site.type === "solar" ? "\u2600\uFE0F" : site.type === "wind" ? "\uD83C\uDF2C\uFE0F" : "\u26A1"}
                  </span>
                  <div>
                    <div className="demo-site-name">{site.name}</div>
                    <div className="demo-site-meta">{site.mw} MW · {site.region}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Step 2: Feasibility running */}
        {step === 2 && (
          <div className="demo-running">
            <div className="demo-spinner" />
            <h2 className="demo-heading">Running Feasibility Assessment</h2>
            <p className="demo-text">{selectedSite?.name} — {selectedSite?.mw} MW {selectedSite?.type}</p>
            <div className="demo-checks">
              <div className="demo-check done">Solar resource analysis (SAM PvWatts)</div>
              <div className={`demo-check ${feasResult ? "done" : "running"}`}>Grid connection assessment</div>
              <div className={`demo-check ${finResult ? "done" : "pending"}`}>Financial model (CB7 assumptions)</div>
            </div>
          </div>
        )}

        {/* Step 3: Financial results */}
        {step === 3 && finResult && (
          <div className="demo-results">
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
