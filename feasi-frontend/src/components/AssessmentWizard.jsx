/**
 * AssessmentWizard — Guided step-by-step site assessment flow.
 *
 * Walks users through: Select site → Choose profile → Run assessment →
 * Review results → Generate report. Progress bar and back/next navigation.
 *
 * Replaces ad-hoc panel interactions with a structured workflow
 * that enterprise clients expect.
 */
import React, { useState, useCallback } from "react";

const STEPS = [
  { id: "site", label: "Select Site", icon: "📍" },
  { id: "profile", label: "Asset Profile", icon: "⚡" },
  { id: "assess", label: "Run Assessment", icon: "🔍" },
  { id: "results", label: "Review Results", icon: "📊" },
  { id: "report", label: "Export Report", icon: "📄" },
];

const PROFILES = [
  { id: "solar", label: "Solar Farm", desc: "Ground-mount PV, 5-200 MW", icon: "☀️", default_mw: 50 },
  { id: "wind", label: "Wind Farm", desc: "Onshore turbines, 10-100 MW", icon: "🌬️", default_mw: 30 },
  { id: "bess", label: "Battery Storage", desc: "Grid-scale BESS, 20-500 MW", icon: "🔋", default_mw: 100 },
  { id: "data_centre", label: "Data Centre", desc: "Hyperscale / colo, 5-200 MW", icon: "🏢", default_mw: 30 },
  { id: "hydrogen", label: "Green Hydrogen", desc: "Electrolyser, 10-100 MW", icon: "⚗️", default_mw: 50 },
  { id: "hybrid", label: "Hybrid Site", desc: "Solar + BESS co-location", icon: "🔄", default_mw: 75 },
];

export default function AssessmentWizard({ onClose, pickedLocation, onRunAssessment }) {
  const [step, setStep] = useState(0);
  const [profile, setProfile] = useState(null);
  const [capacity, setCapacity] = useState(50);
  const [siteName, setSiteName] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [reportUrl, setReportUrl] = useState(null);

  const lat = pickedLocation?.lat;
  const lon = pickedLocation?.lon;

  const runAssessment = useCallback(async () => {
    if (!lat || !lon || !profile) return;
    setLoading(true);
    try {
      // Run grid assessment
      const gridR = await fetch(`/api/grid/assess?lat=${lat}&lon=${lon}&capacity_mw=${capacity}&technology=${profile.id}`, { method: "POST" });
      const grid = await gridR.json();

      // Run environmental constraints
      let env = null;
      try {
        const envR = await fetch(`/api/grid/environmental-constraints?lat=${lat}&lon=${lon}`);
        if (envR.ok) env = await envR.json();
      } catch {}

      // Run DC-specific if data centre
      let dc = null;
      if (profile.id === "data_centre") {
        try {
          const dcR = await fetch(`/api/dc/score?lat=${lat}&lon=${lon}&capacity_mw=${capacity}`, { method: "POST" });
          if (dcR.ok) dc = await dcR.json();
        } catch {}
      }

      setResults({ grid, env, dc, profile: profile.id, capacity, lat, lon });
      setStep(3); // Jump to results
    } catch (e) {
      console.warn("Assessment failed:", e);
    }
    setLoading(false);
  }, [lat, lon, profile, capacity]);

  const generateReport = useCallback(async () => {
    if (!results) return;
    setLoading(true);
    try {
      if (profile.id === "data_centre") {
        const r = await fetch(`/api/dc/report?lat=${lat}&lon=${lon}&capacity_mw=${capacity}`, { method: "POST" });
        if (r.ok) {
          const blob = await r.blob();
          const url = URL.createObjectURL(blob);
          setReportUrl(url);
        }
      }
      setStep(4);
    } catch {}
    setLoading(false);
  }, [results, profile, lat, lon, capacity]);

  const currentStep = STEPS[step];
  const canNext = step === 0 ? !!lat : step === 1 ? !!profile : step === 2 ? true : step === 3 ? !!results : false;

  return (
    <div className="wiz-overlay">
      <div className="wiz-panel">
        {/* Header */}
        <div className="wiz-header">
          <span className="wiz-header-title">Site Assessment</span>
          <button className="wiz-close" onClick={onClose}>&times;</button>
        </div>

        {/* Progress bar */}
        <div className="wiz-progress">
          {STEPS.map((s, i) => (
            <div key={s.id} className={`wiz-step ${i === step ? "active" : ""} ${i < step ? "done" : ""}`}>
              <div className="wiz-step-dot">{i < step ? "✓" : s.icon}</div>
              <span className="wiz-step-label">{s.label}</span>
              {i < STEPS.length - 1 && <div className="wiz-step-line" />}
            </div>
          ))}
        </div>

        {/* Content */}
        <div className="wiz-content">
          {/* Step 0: Site */}
          {step === 0 && (
            <div className="wiz-section">
              <h3 className="wiz-section-title">Select a site location</h3>
              {lat && lon ? (
                <div className="wiz-site-info">
                  <div className="wiz-site-coords">
                    <span className="wiz-label">Latitude</span>
                    <span className="wiz-value">{lat.toFixed(6)}</span>
                  </div>
                  <div className="wiz-site-coords">
                    <span className="wiz-label">Longitude</span>
                    <span className="wiz-value">{lon.toFixed(6)}</span>
                  </div>
                  <input
                    className="wiz-input"
                    placeholder="Site name (optional)"
                    value={siteName}
                    onChange={e => setSiteName(e.target.value)}
                  />
                </div>
              ) : (
                <div className="wiz-empty">
                  Click on the map to select a site location, then return here.
                </div>
              )}
            </div>
          )}

          {/* Step 1: Profile */}
          {step === 1 && (
            <div className="wiz-section">
              <h3 className="wiz-section-title">Choose asset profile</h3>
              <div className="wiz-profile-grid">
                {PROFILES.map(p => (
                  <button
                    key={p.id}
                    className={`wiz-profile-card ${profile?.id === p.id ? "active" : ""}`}
                    onClick={() => { setProfile(p); setCapacity(p.default_mw); }}
                  >
                    <span className="wiz-profile-icon">{p.icon}</span>
                    <span className="wiz-profile-label">{p.label}</span>
                    <span className="wiz-profile-desc">{p.desc}</span>
                  </button>
                ))}
              </div>
              {profile && (
                <div className="wiz-capacity">
                  <label className="wiz-label">Capacity (MW)</label>
                  <input
                    type="range"
                    min="1"
                    max="500"
                    value={capacity}
                    onChange={e => setCapacity(Number(e.target.value))}
                    className="wiz-slider"
                  />
                  <span className="wiz-capacity-val">{capacity} MW</span>
                </div>
              )}
            </div>
          )}

          {/* Step 2: Running */}
          {step === 2 && (
            <div className="wiz-section wiz-center">
              {loading ? (
                <>
                  <div className="wiz-spinner" />
                  <p>Running {profile?.label} assessment at {lat?.toFixed(4)}, {lon?.toFixed(4)}...</p>
                  <p className="wiz-sub">Grid connection • Environmental constraints • Financial model</p>
                </>
              ) : (
                <>
                  <h3 className="wiz-section-title">Ready to assess</h3>
                  <p>{profile?.label} — {capacity} MW at ({lat?.toFixed(4)}, {lon?.toFixed(4)})</p>
                  <button className="wiz-run-btn" onClick={runAssessment}>
                    Run Full Assessment
                  </button>
                </>
              )}
            </div>
          )}

          {/* Step 3: Results */}
          {step === 3 && results && (
            <div className="wiz-section">
              <h3 className="wiz-section-title">Assessment Results</h3>
              <div className="wiz-results-grid">
                {/* Grid verdict */}
                <div className="wiz-result-card">
                  <span className="wiz-result-label">Grid Connection</span>
                  <span className={`wiz-result-verdict ${(results.grid?.verdict || "").toLowerCase()}`}>
                    {results.grid?.verdict || "—"}
                  </span>
                  {results.grid?.nearest_substation && (
                    <span className="wiz-result-detail">
                      {results.grid.nearest_substation.name} — {results.grid.nearest_substation.distance_km?.toFixed(1)} km
                    </span>
                  )}
                </div>

                {/* Headroom */}
                <div className="wiz-result-card">
                  <span className="wiz-result-label">Available Headroom</span>
                  <span className="wiz-result-value">
                    {results.grid?.nearest_substation?.gen_headroom_mw?.toFixed(0) || "—"} MW
                  </span>
                </div>

                {/* Connection cost */}
                <div className="wiz-result-card">
                  <span className="wiz-result-label">Connection Cost (P50)</span>
                  <span className="wiz-result-value">
                    £{((results.grid?.connection_cost?.p50 || 0) / 1_000_000).toFixed(1)}M
                  </span>
                </div>

                {/* Environmental */}
                {results.env && (
                  <div className="wiz-result-card">
                    <span className="wiz-result-label">Environmental</span>
                    <span className={`wiz-result-verdict ${(results.env?.verdict || "clear").toLowerCase()}`}>
                      {results.env?.verdict || "CLEAR"}
                    </span>
                    <span className="wiz-result-detail">
                      {results.env?.checks?.length || 0} constraints checked
                    </span>
                  </div>
                )}

                {/* DC Score */}
                {results.dc && (
                  <div className="wiz-result-card">
                    <span className="wiz-result-label">DC Suitability</span>
                    <span className="wiz-result-value wiz-score">
                      {results.dc?.score || "—"}/100
                    </span>
                    <span className="wiz-result-detail">
                      {results.dc?.verdict}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Step 4: Report */}
          {step === 4 && (
            <div className="wiz-section wiz-center">
              <h3 className="wiz-section-title">Report Generated</h3>
              {reportUrl ? (
                <a href={reportUrl} download={`princeps-report-${siteName || "site"}.pdf`} className="wiz-download-btn">
                  Download PDF Report
                </a>
              ) : (
                <p>Report ready for download</p>
              )}
            </div>
          )}
        </div>

        {/* Footer nav */}
        <div className="wiz-footer">
          <button
            className="wiz-btn wiz-btn-back"
            disabled={step === 0}
            onClick={() => setStep(s => Math.max(0, s - 1))}
          >
            ← Back
          </button>
          <span className="wiz-step-count">Step {step + 1} of {STEPS.length}</span>
          {step === 3 ? (
            <button className="wiz-btn wiz-btn-next" onClick={generateReport}>
              Generate Report →
            </button>
          ) : step < 4 ? (
            <button
              className="wiz-btn wiz-btn-next"
              disabled={!canNext || loading}
              onClick={() => {
                if (step === 2 && !results) {
                  runAssessment();
                } else {
                  setStep(s => Math.min(STEPS.length - 1, s + 1));
                }
              }}
            >
              {step === 2 ? "Run Assessment →" : "Next →"}
            </button>
          ) : (
            <button className="wiz-btn wiz-btn-next" onClick={onClose}>
              Done ✓
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
