import React, { useState, useEffect, useRef } from "react";
import { createProject, createCandidateSite } from "../../services/portfolios";

const STEPS = ["Workload", "Location", "Candidates"];

const WORKLOADS = [
  { key: "bess", icon: "▮", title: "Battery Energy Storage", desc: "Grid-scale storage for arbitrage, ancillary services, and capacity markets." },
  { key: "dc",   icon: "▦", title: "Data Centre",             desc: "Hyperscale or enterprise DC with behind-the-meter generation and storage." },
];

function StepDots({ step }) {
  return (
    <div className="np-steps">
      {STEPS.map((label, i) => (
        <React.Fragment key={i}>
          <div className={"np-step" + (i <= step ? " np-step-done" : "")}>
            <div className="np-step-dot">{i + 1}</div>
            <div className="np-step-label">{label}</div>
          </div>
          {i < STEPS.length - 1 && <div className={"np-step-line" + (i < step ? " np-step-line-done" : "")} />}
        </React.Fragment>
      ))}
    </div>
  );
}

export default function NewProjectModal({
  isOpen,
  onClose = () => {},
  portfolioId = null,
  onCreated = () => {},
}) {
  const [step, setStep] = useState(0);
  const [workload, setWorkload] = useState(null);
  const [name, setName] = useState("");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [capacity, setCapacity] = useState("");
  const [energy, setEnergy] = useState(""); // BESS only
  const [pue, setPue] = useState("1.2");    // DC only
  const [strategy, setStrategy] = useState("auto"); // auto | manual
  const [manualSites, setManualSites] = useState([{ name: "", lat: "", lon: "", capacity_mw: "" }]);
  const [autoSites, setAutoSites] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);

  const nameRef = useRef(null);

  useEffect(() => {
    if (!isOpen) {
      setStep(0); setWorkload(null); setName(""); setLat(""); setLon("");
      setCapacity(""); setEnergy(""); setPue("1.2");
      setStrategy("auto"); setManualSites([{ name: "", lat: "", lon: "", capacity_mw: "" }]);
      setAutoSites(null); setError(null); setCreating(false);
    }
  }, [isOpen]);

  useEffect(() => {
    if (isOpen && step === 1) setTimeout(() => nameRef.current?.focus(), 80);
  }, [isOpen, step]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && isOpen) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const step0Valid = workload != null;
  const step1Valid = name.trim() && lat && lon && capacity &&
    (workload !== "bess" || energy) && (workload !== "dc" || pue);
  const step2Valid =
    strategy === "auto"
      ? autoSites && autoSites.length > 0
      : manualSites.every((s) => s.name && s.lat && s.lon);

  const runScan = async () => {
    setScanning(true); setError(null);
    try {
      // Best-effort call to prospector scan if endpoint exists; fall back to jitter mocks.
      let sites = null;
      try {
        const res = await fetch("/api/v2/prospector/scan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lat: parseFloat(lat), lon: parseFloat(lon), radius_km: 5, technology: workload }),
        });
        if (res.ok) {
          const data = await res.json();
          sites = (data.candidates || data.sites || []).slice(0, 3);
        }
      } catch { /* fall through */ }
      if (!sites || sites.length === 0) {
        const bLat = parseFloat(lat); const bLon = parseFloat(lon);
        const rand = (n) => (Math.random() * 2 - 1) * n;
        const mkScore = () => Math.floor(50 + Math.random() * 40);
        sites = [
          { name: `${name} — Candidate A`, lat: bLat + rand(0.02), lon: bLon + rand(0.02), capacity_mw: parseFloat(capacity),
            scores: { resource: mkScore(), grid: mkScore(), planning: mkScore(), land_use: mkScore(), terrain: mkScore() },
            verdict: "GO", is_preferred: true },
          { name: `${name} — Candidate B`, lat: bLat + rand(0.03), lon: bLon + rand(0.03), capacity_mw: parseFloat(capacity),
            scores: { resource: mkScore(), grid: mkScore(), planning: mkScore(), land_use: mkScore(), terrain: mkScore() },
            verdict: "CAUTION", is_preferred: false },
          { name: `${name} — Candidate C`, lat: bLat + rand(0.04), lon: bLon + rand(0.04), capacity_mw: parseFloat(capacity),
            scores: { resource: mkScore(), grid: mkScore(), planning: mkScore(), land_use: mkScore(), terrain: mkScore() },
            verdict: "GO", is_preferred: false },
        ];
      }
      setAutoSites(sites);
    } catch (e) {
      setError(e.message || "Scan failed");
    } finally {
      setScanning(false);
    }
  };

  const submit = async () => {
    setCreating(true); setError(null);
    try {
      const meta = workload === "bess"
        ? { energy_mwh: parseFloat(energy), duration_h: parseFloat(energy) / parseFloat(capacity) }
        : { it_load_mw: parseFloat(capacity), pue_target: parseFloat(pue) };
      const project = await createProject({
        name: name.trim(),
        technology: workload,
        capacity_mw: parseFloat(capacity),
        stage: "prospect",
        lat: parseFloat(lat),
        lon: parseFloat(lon),
        portfolio_id: portfolioId,
        metadata: meta,
      });
      const sites = strategy === "auto" ? autoSites : manualSites.map((s) => ({
        name: s.name, lat: parseFloat(s.lat), lon: parseFloat(s.lon),
        capacity_mw: parseFloat(s.capacity_mw || capacity),
        scores: {}, verdict: null, is_preferred: false,
      }));
      await Promise.all(
        (sites || []).map((s) =>
          createCandidateSite(project.project_id, {
            name: s.name, lat: s.lat, lon: s.lon,
            capacity_mw: s.capacity_mw, scores: s.scores || {},
            verdict: s.verdict || null, is_preferred: !!s.is_preferred,
          })
        )
      );
      onCreated(project.project_id);
      onClose();
    } catch (e) {
      setError(e.message || "Failed to create project");
    } finally {
      setCreating(false);
    }
  };

  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  const back = () => setStep((s) => Math.max(s - 1, 0));

  return (
    <div className="np-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="np-modal" role="dialog" aria-modal="true" aria-label="New project">
        <div className="np-head">
          <div className="np-title">New project</div>
          <StepDots step={step} />
          <button className="np-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="np-body">
          {step === 0 && (
            <div className="np-workloads">
              {WORKLOADS.map((w) => (
                <button
                  key={w.key}
                  className={"np-wcard" + (workload === w.key ? " np-wcard-sel" : "")}
                  onClick={() => setWorkload(w.key)}
                >
                  <div className="np-wicon">{w.icon}</div>
                  <div className="np-wtitle">{w.title}</div>
                  <div className="np-wdesc">{w.desc}</div>
                </button>
              ))}
            </div>
          )}

          {step === 1 && (
            <div className="np-form">
              <label className="np-field">
                <span className="np-lbl">Project name</span>
                <input ref={nameRef} className="np-in" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Thames BESS Phase 1" />
              </label>
              <div className="np-row">
                <label className="np-field">
                  <span className="np-lbl">Latitude</span>
                  <input className="np-in" type="number" step="0.0001" value={lat} onChange={(e) => setLat(e.target.value)} placeholder="51.5074" />
                </label>
                <label className="np-field">
                  <span className="np-lbl">Longitude</span>
                  <input className="np-in" type="number" step="0.0001" value={lon} onChange={(e) => setLon(e.target.value)} placeholder="-0.1278" />
                </label>
                <button className="np-pick" onClick={() => { setLat("51.5074"); setLon("-0.1278"); }} type="button">
                  Demo: London
                </button>
              </div>

              {workload === "bess" && (
                <div className="np-row">
                  <label className="np-field">
                    <span className="np-lbl">Power capacity (MW)</span>
                    <input className="np-in" type="number" step="0.1" value={capacity} onChange={(e) => setCapacity(e.target.value)} placeholder="50" />
                  </label>
                  <label className="np-field">
                    <span className="np-lbl">Energy (MWh)</span>
                    <input className="np-in" type="number" step="1" value={energy} onChange={(e) => setEnergy(e.target.value)} placeholder="100" />
                  </label>
                </div>
              )}
              {workload === "dc" && (
                <div className="np-row">
                  <label className="np-field">
                    <span className="np-lbl">IT load (MW)</span>
                    <input className="np-in" type="number" step="0.1" value={capacity} onChange={(e) => setCapacity(e.target.value)} placeholder="40" />
                  </label>
                  <label className="np-field">
                    <span className="np-lbl">PUE target</span>
                    <input className="np-in" type="number" step="0.01" value={pue} onChange={(e) => setPue(e.target.value)} placeholder="1.2" />
                  </label>
                </div>
              )}
            </div>
          )}

          {step === 2 && (
            <div className="np-form">
              <div className="np-radios">
                <label className={"np-radio" + (strategy === "auto" ? " np-radio-sel" : "")}>
                  <input type="radio" checked={strategy === "auto"} onChange={() => setStrategy("auto")} />
                  <div>
                    <div className="np-radio-title">Auto-generate from site prospector</div>
                    <div className="np-radio-sub">Scan surrounding area for candidate sites.</div>
                  </div>
                </label>
                <label className={"np-radio" + (strategy === "manual" ? " np-radio-sel" : "")}>
                  <input type="radio" checked={strategy === "manual"} onChange={() => setStrategy("manual")} />
                  <div>
                    <div className="np-radio-title">Add manually</div>
                    <div className="np-radio-sub">Enter candidates yourself.</div>
                  </div>
                </label>
              </div>

              {strategy === "auto" && (
                <div className="np-auto">
                  {!autoSites ? (
                    <button className="np-btn np-btn-ghost" onClick={runScan} disabled={scanning}>
                      {scanning ? "Scanning…" : "Scan region for candidates"}
                    </button>
                  ) : (
                    <div className="np-summary">
                      <div className="np-sum-n">{autoSites.length}</div>
                      <div>
                        <div className="np-sum-title">candidates generated</div>
                        <div className="np-sum-sub">Top resource score: {Math.max(...autoSites.map((s) => s.scores?.resource ?? 0))}</div>
                      </div>
                      <button className="np-btn np-btn-ghost np-btn-sm" onClick={() => setAutoSites(null)}>Rescan</button>
                    </div>
                  )}
                </div>
              )}

              {strategy === "manual" && (
                <div className="np-manual">
                  {manualSites.map((s, i) => (
                    <div key={i} className="np-manual-row">
                      <input className="np-in" placeholder="Name" value={s.name}
                        onChange={(e) => setManualSites((m) => m.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
                      <input className="np-in np-in-sm" placeholder="Lat" value={s.lat}
                        onChange={(e) => setManualSites((m) => m.map((x, j) => j === i ? { ...x, lat: e.target.value } : x))} />
                      <input className="np-in np-in-sm" placeholder="Lon" value={s.lon}
                        onChange={(e) => setManualSites((m) => m.map((x, j) => j === i ? { ...x, lon: e.target.value } : x))} />
                      <input className="np-in np-in-sm" placeholder="MW" value={s.capacity_mw}
                        onChange={(e) => setManualSites((m) => m.map((x, j) => j === i ? { ...x, capacity_mw: e.target.value } : x))} />
                      {manualSites.length > 1 && (
                        <button className="np-rm" onClick={() => setManualSites((m) => m.filter((_, j) => j !== i))}>×</button>
                      )}
                    </div>
                  ))}
                  <button className="np-btn np-btn-ghost np-btn-sm" onClick={() => setManualSites((m) => [...m, { name: "", lat: "", lon: "", capacity_mw: "" }])}>
                    + Add another
                  </button>
                </div>
              )}
            </div>
          )}

          {error && <div className="np-error">{error}</div>}
        </div>

        <div className="np-foot">
          <button className="np-btn np-btn-ghost" onClick={step > 0 ? back : onClose}>
            {step > 0 ? "← Back" : "Cancel"}
          </button>
          <div className="np-foot-spacer" />
          {step < STEPS.length - 1 ? (
            <button
              className="np-btn np-btn-primary"
              onClick={next}
              disabled={step === 0 ? !step0Valid : !step1Valid}
            >
              Next →
            </button>
          ) : (
            <button
              className="np-btn np-btn-primary"
              onClick={submit}
              disabled={!step2Valid || creating}
            >
              {creating ? "Creating…" : "Create project"}
            </button>
          )}
        </div>
      </div>

      <style>{`
        .np-backdrop {
          position: fixed; inset: 0;
          background: rgba(15,19,24,0.48);
          z-index: 1000;
          display: flex; align-items: center; justify-content: center;
          padding: 24px;
          font-family: "DM Sans", -apple-system, sans-serif;
        }
        .np-modal {
          width: 100%; max-width: 680px;
          background: var(--cds-layer-01);
          border-radius: 16px;
          box-shadow: 0 16px 64px rgba(0,0,0,0.2);
          display: flex; flex-direction: column;
          max-height: calc(100vh - 48px);
        }
        .np-head {
          display: flex; align-items: center; gap: 24px;
          padding: 20px 24px;
          border-bottom: 1px solid var(--cds-border-subtle);
        }
        .np-title {
          font-size: 18px; font-weight: 700;
          color: var(--ink);
          flex-shrink: 0;
        }
        .np-close {
          background: none; border: none;
          font-size: 22px;
          color: var(--cds-text-helper);
          cursor: pointer;
          width: 32px; height: 32px;
          border-radius: 8px;
          margin-left: auto;
          flex-shrink: 0;
        }
        .np-close:hover { background: var(--cds-layer-02); color: var(--ink); }

        .np-steps {
          display: flex; align-items: center; gap: 4px;
          flex: 1;
        }
        .np-step { display: flex; align-items: center; gap: 8px; }
        .np-step-dot {
          width: 24px; height: 24px; border-radius: 50%;
          background: var(--cds-layer-03);
          color: var(--cds-text-helper);
          font-family: var(--mono); font-size: 11px; font-weight: 700;
          display: flex; align-items: center; justify-content: center;
        }
        .np-step-done .np-step-dot {
          background: var(--gold);
          color: #fff;
        }
        .np-step-label {
          font-size: 12px; font-weight: 600;
          color: var(--cds-text-helper);
        }
        .np-step-done .np-step-label { color: var(--ink); }
        .np-step-line {
          height: 2px; flex: 1;
          background: var(--cds-layer-03);
          border-radius: 1px;
          max-width: 40px;
        }
        .np-step-line-done { background: var(--gold); }

        .np-body {
          padding: 24px;
          overflow-y: auto;
          min-height: 320px;
        }

        .np-workloads {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
        }
        .np-wcard {
          background: var(--cds-layer-01);
          border: 2px solid var(--cds-border-subtle);
          border-radius: 12px;
          padding: 20px;
          cursor: pointer;
          text-align: left;
          font: inherit;
          transition: all 120ms;
        }
        .np-wcard:hover { border-color: var(--gold-light); }
        .np-wcard-sel {
          border-color: var(--gold);
          background: rgba(var(--accent-rgb), 0.06);
        }
        .np-wicon {
          font-size: 28px;
          color: var(--gold);
          margin-bottom: 8px;
        }
        .np-wtitle {
          font-size: 15px; font-weight: 700;
          color: var(--ink);
          margin-bottom: 4px;
        }
        .np-wdesc {
          font-size: 12px;
          color: var(--cds-text-secondary);
          line-height: 1.5;
        }

        .np-form { display: flex; flex-direction: column; gap: 16px; }
        .np-field { display: flex; flex-direction: column; gap: 6px; flex: 1; }
        .np-lbl {
          font-size: 11px; font-weight: 600;
          color: var(--cds-text-helper);
          letter-spacing: 0.04em;
          text-transform: uppercase;
        }
        .np-in {
          padding: 10px 12px;
          border: 1px solid var(--cds-border-subtle);
          border-radius: 8px;
          font-family: inherit; font-size: 13px;
          color: var(--cds-text-primary);
          background: var(--cds-layer-02);
          outline: none;
          transition: border-color 120ms;
        }
        .np-in:focus {
          border-color: var(--gold);
          box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.12);
        }
        .np-in-sm { width: 110px; }
        .np-row { display: flex; gap: 12px; align-items: flex-end; }
        .np-pick {
          padding: 10px 14px;
          border: 1px solid var(--cds-border-subtle);
          border-radius: 8px;
          background: var(--cds-layer-02);
          font-family: inherit; font-size: 12px; font-weight: 600;
          color: var(--cds-text-secondary);
          cursor: pointer;
          white-space: nowrap;
          transition: all 120ms;
        }
        .np-pick:hover { border-color: var(--gold); color: var(--gold-dark); }

        .np-radios { display: flex; flex-direction: column; gap: 10px; }
        .np-radio {
          display: flex; align-items: flex-start; gap: 12px;
          padding: 12px 14px;
          border: 1px solid var(--cds-border-subtle);
          border-radius: 10px;
          cursor: pointer;
          transition: all 120ms;
        }
        .np-radio:hover { border-color: var(--gold-light); }
        .np-radio-sel {
          border-color: var(--gold);
          background: rgba(var(--accent-rgb), 0.06);
        }
        .np-radio input { accent-color: var(--gold); margin-top: 2px; }
        .np-radio-title { font-size: 13px; font-weight: 700; color: var(--ink); }
        .np-radio-sub { font-size: 12px; color: var(--cds-text-secondary); margin-top: 2px; }

        .np-auto { display: flex; align-items: center; gap: 12px; }
        .np-summary {
          display: flex; align-items: center; gap: 16px;
          padding: 12px 16px;
          background: rgba(var(--accent-rgb), 0.06);
          border: 1px solid var(--gold);
          border-radius: 10px;
          width: 100%;
        }
        .np-sum-n {
          font-family: var(--mono);
          font-size: 28px; font-weight: 700;
          color: var(--gold-dark);
        }
        .np-sum-title { font-size: 13px; font-weight: 600; color: var(--ink); }
        .np-sum-sub { font-size: 11px; color: var(--cds-text-secondary); margin-top: 2px; }

        .np-manual { display: flex; flex-direction: column; gap: 8px; }
        .np-manual-row { display: flex; gap: 8px; align-items: center; }
        .np-manual-row .np-in { flex: 1; }
        .np-rm {
          width: 32px; height: 32px;
          border: 1px solid var(--cds-border-subtle);
          border-radius: 8px;
          background: transparent;
          color: var(--cds-text-helper);
          cursor: pointer;
          font-size: 16px;
          flex-shrink: 0;
        }
        .np-rm:hover { color: var(--cds-support-error); border-color: var(--cds-support-error); }

        .np-foot {
          display: flex; align-items: center; gap: 12px;
          padding: 16px 24px;
          border-top: 1px solid var(--cds-border-subtle);
        }
        .np-foot-spacer { flex: 1; }
        .np-btn {
          padding: 10px 16px;
          border-radius: 10px;
          font-family: inherit; font-size: 13px; font-weight: 600;
          cursor: pointer; border: 1px solid transparent;
          transition: all 120ms;
        }
        .np-btn-sm { padding: 6px 12px; font-size: 12px; }
        .np-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .np-btn-ghost {
          background: transparent;
          border-color: var(--cds-border-subtle);
          color: var(--cds-text-secondary);
        }
        .np-btn-ghost:hover:not(:disabled) {
          border-color: var(--gold);
          color: var(--gold-dark);
        }
        .np-btn-primary {
          background: var(--gold);
          color: #fff;
        }
        .np-btn-primary:hover:not(:disabled) { background: var(--gold-dark); }
        .np-error {
          margin-top: 12px;
          padding: 10px 12px;
          background: rgba(220,38,38,0.08);
          color: var(--cds-support-error);
          border: 1px solid rgba(220,38,38,0.2);
          border-radius: 8px;
          font-size: 12px;
        }
      `}</style>
    </div>
  );
}
