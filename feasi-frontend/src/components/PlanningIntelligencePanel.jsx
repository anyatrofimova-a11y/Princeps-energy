import React, { useState, useCallback, useEffect } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/* ── UK Regulatory Requirements ─────────────────────────────────────────── */
const REGULATIONS = [
  { id: "g99",       label: "G99 Grid Connection",        category: "grid",        description: "Engineering recommendation for connecting generation >16A per phase" },
  { id: "cdm",       label: "CDM Construction",           category: "safety",      description: "Construction (Design and Management) Regulations 2015" },
  { id: "bng",       label: "BNG Biodiversity Net Gain",  category: "environment", description: "10% mandatory biodiversity net gain under Environment Act 2021" },
  { id: "eia",       label: "EIA Environmental Impact",   category: "environment", description: "EIA screening/scoping for developments >0.5 ha or sensitive areas" },
  { id: "tcpa",      label: "TCPA Town & Country Planning",category: "planning",   description: "Planning permission under Town and Country Planning Act 1990" },
  { id: "noise",     label: "Noise Assessment",           category: "amenity",     description: "BS 4142:2014+A1:2019 assessment of industrial noise" },
  { id: "glint",     label: "Glint & Glare",              category: "amenity",     description: "Solar reflection assessment for aviation and residential receptors" },
  { id: "heritage",  label: "Heritage Impact",            category: "heritage",    description: "Assessment of impact on listed buildings and scheduled monuments" },
  { id: "flood",     label: "Flood Risk Assessment",      category: "environment", description: "FRA required in Flood Zones 2 and 3 (EA standing advice)" },
  { id: "transport", label: "Transport Assessment",       category: "logistics",   description: "Construction traffic management and abnormal loads routing" },
];

const TECH_OPTIONS = [
  { value: "solar", label: "Solar PV" },
  { value: "wind", label: "Wind" },
  { value: "bess", label: "BESS" },
  { value: "hybrid", label: "Hybrid" },
];

/* ── Helpers ────────────────────────────────────────────────────────────── */
function pct(v) { return v != null ? `${(v * 100).toFixed(0)}%` : "--"; }
function fmtDate(d) {
  if (!d) return "--";
  return new Date(d).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/* ── Approval Gauge (SVG ring) ──────────────────────────────────────────── */
function ApprovalGauge({ probability, size = 140 }) {
  const r = (size - 16) / 2;
  const circ = 2 * Math.PI * r;
  const val = Math.max(0, Math.min(1, probability || 0));
  const offset = circ * (1 - val);
  const color = val >= 0.7 ? "#16A34A" : val >= 0.4 ? "#E8A012" : "#DC2626";

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="pi-gauge">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(0,0,0,0.06)" strokeWidth={8} />
      <circle
        cx={size / 2} cy={size / 2} r={r} fill="none"
        stroke={color} strokeWidth={8} strokeLinecap="round"
        strokeDasharray={circ} strokeDashoffset={offset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dashoffset 0.8s cubic-bezier(0.16,1,0.3,1)" }}
      />
      <text x={size / 2} y={size / 2 - 6} textAnchor="middle" fill="var(--cds-text-primary)" fontSize="28" fontWeight="800" fontFamily="JetBrains Mono, monospace">
        {(val * 100).toFixed(0)}%
      </text>
      <text x={size / 2} y={size / 2 + 14} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="10" fontWeight="500">
        Approval Probability
      </text>
    </svg>
  );
}

/* ── Compliance Ring (smaller) ──────────────────────────────────────────── */
function ComplianceRing({ score, total, size = 100 }) {
  const r = (size - 12) / 2;
  const circ = 2 * Math.PI * r;
  const val = total > 0 ? score / total : 0;
  const offset = circ * (1 - val);
  const color = val >= 0.8 ? "#16A34A" : val >= 0.5 ? "#E8A012" : "#DC2626";

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="pi-compliance-ring">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(0,0,0,0.06)" strokeWidth={6} />
      <circle
        cx={size / 2} cy={size / 2} r={r} fill="none"
        stroke={color} strokeWidth={6} strokeLinecap="round"
        strokeDasharray={circ} strokeDashoffset={offset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dashoffset 0.8s cubic-bezier(0.16,1,0.3,1)" }}
      />
      <text x={size / 2} y={size / 2 - 2} textAnchor="middle" fill="var(--cds-text-primary)" fontSize="18" fontWeight="800" fontFamily="JetBrains Mono, monospace">
        {score}/{total}
      </text>
      <text x={size / 2} y={size / 2 + 12} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="9">
        Complete
      </text>
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   PlanningIntelligencePanel
   ═══════════════════════════════════════════════════════════════════════════ */
export default function PlanningIntelligencePanel({ onClose }) {
  const { explain, selectedParcel } = useSite();

  /* ── State ── */
  const [activeTab, setActiveTab] = useState("predict");
  const [lat, setLat] = useState(() => explain?.lat ?? explain?.location?.lat ?? selectedParcel?.lat ?? 52.48);
  const [lon, setLon] = useState(() => explain?.lon ?? explain?.location?.lon ?? selectedParcel?.lon ?? -1.89);
  const [technology, setTechnology] = useState("solar");
  const [capacityMw, setCapacityMw] = useState(50);

  // Predict tab
  const [prediction, setPrediction] = useState(null);
  const [comparables, setComparables] = useState(null);
  const [predLoading, setPredLoading] = useState(false);
  const [predError, setPredError] = useState(null);

  // Compliance tab
  const [complianceData, setComplianceData] = useState(null);
  const [compLoading, setCompLoading] = useState(false);
  const [regStatuses, setRegStatuses] = useState(() =>
    REGULATIONS.reduce((acc, r) => ({ ...acc, [r.id]: "pending" }), {})
  );

  // Monitor tab
  const [monitorData, setMonitorData] = useState(null);
  const [monLoading, setMonLoading] = useState(false);

  // Sync coords from site context
  useEffect(() => {
    const newLat = explain?.lat ?? explain?.location?.lat ?? selectedParcel?.lat;
    const newLon = explain?.lon ?? explain?.location?.lon ?? selectedParcel?.lon;
    if (newLat != null) setLat(newLat);
    if (newLon != null) setLon(newLon);
  }, [explain, selectedParcel]);

  /* ── Predict ── */
  const runPrediction = useCallback(async () => {
    setPredLoading(true);
    setPredError(null);
    try {
      const [pred, comp] = await Promise.all([
        api.planning.predictApproval(lat, lon, capacityMw, technology),
        api.planning.comparableProjects(lat, lon, capacityMw, technology, 5),
      ]);
      setPrediction(pred);
      setComparables(comp);
    } catch (e) {
      setPredError(e.message || "Prediction failed");
    }
    setPredLoading(false);
  }, [lat, lon, capacityMw, technology]);

  /* ── Compliance ── */
  const loadCompliance = useCallback(async () => {
    setCompLoading(true);
    try {
      const data = await api.planning.compliance(lat, lon, capacityMw, technology);
      setComplianceData(data);
      // Map returned requirements to statuses
      if (data?.requirements) {
        const newStatuses = { ...regStatuses };
        data.requirements.forEach(req => {
          if (req.id && req.status) newStatuses[req.id] = req.status;
        });
        setRegStatuses(newStatuses);
      }
    } catch (e) { /* silent */ }
    setCompLoading(false);
  }, [lat, lon, capacityMw, technology]);

  /* ── Monitor ── */
  const loadMonitor = useCallback(async () => {
    setMonLoading(true);
    try {
      const [nsipData, constraintsData] = await Promise.all([
        api.planning.nsipConflicts(lat, lon, 20),
        api.planning.constraints(lat, lon, 5000),
      ]);
      setMonitorData({ nsip: nsipData, constraints: constraintsData });
    } catch (e) { /* silent */ }
    setMonLoading(false);
  }, [lat, lon]);

  // Auto-load on tab switch
  useEffect(() => {
    if (activeTab === "compliance" && !complianceData && !compLoading) loadCompliance();
    if (activeTab === "monitor" && !monitorData && !monLoading) loadMonitor();
  }, [activeTab]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleRegStatus = (id) => {
    setRegStatuses(prev => {
      const cycle = { pending: "required", required: "complete", complete: "not_required", not_required: "pending" };
      return { ...prev, [id]: cycle[prev[id]] || "pending" };
    });
  };

  const completedCount = Object.values(regStatuses).filter(s => s === "complete").length;
  const requiredCount = Object.values(regStatuses).filter(s => s === "required" || s === "complete").length;

  const statusBadge = (status) => {
    const map = {
      pending: { label: "Pending", cls: "pi-badge--pending" },
      required: { label: "Required", cls: "pi-badge--required" },
      complete: { label: "Complete", cls: "pi-badge--complete" },
      not_required: { label: "N/A", cls: "pi-badge--na" },
    };
    const m = map[status] || map.pending;
    return <span className={`pi-badge ${m.cls}`}>{m.label}</span>;
  };

  return (
    <div className="gc-panel pi-panel">
      {/* Header */}
      <div className="gc-panel-header">
        <div className="gc-panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 21h18M9 8h1M9 12h1M9 16h1M14 8h1M14 12h1M14 16h1M5 21V5a2 2 0 012-2h10a2 2 0 012 2v16" />
          </svg>
          Planning Intelligence
        </div>
        <button className="gc-panel-close" onClick={onClose}>&times;</button>
      </div>

      {/* Input bar */}
      <div className="pi-input-bar">
        <div className="gc-input-group">
          <label className="gc-input-label">Lat / Lon</label>
          <div className="pi-coord-inputs">
            <input type="number" value={lat} step={0.01} onChange={e => setLat(+e.target.value)} className="gc-input pi-coord-input" />
            <input type="number" value={lon} step={0.01} onChange={e => setLon(+e.target.value)} className="gc-input pi-coord-input" />
          </div>
        </div>
        <div className="gc-input-group">
          <label className="gc-input-label">Technology</label>
          <select value={technology} onChange={e => setTechnology(e.target.value)} className="gc-input">
            {TECH_OPTIONS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
        <div className="gc-input-group">
          <label className="gc-input-label">Capacity (MW)</label>
          <input type="number" value={capacityMw} min={0.1} step={5} onChange={e => setCapacityMw(+e.target.value)} className="gc-input" />
        </div>
      </div>

      {/* Tab bar */}
      <div className="df-tabs">
        {[
          { id: "predict", label: "Predict" },
          { id: "compliance", label: "Compliance" },
          { id: "monitor", label: "Monitor" },
        ].map(tab => (
          <button key={tab.id}
            className={`df-tab ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
          >{tab.label}</button>
        ))}
      </div>

      <div className="gc-panel-body">

        {/* ═══════════════════ TAB: Predict ═══════════════════ */}
        {activeTab === "predict" && (
          <>
            <div className="pi-action-row">
              <button
                onClick={runPrediction}
                disabled={predLoading}
                className={`gc-assess-btn${predLoading ? " gc-assess-btn--loading" : ""}`}
                style={{ width: "100%" }}
              >
                {predLoading ? "Analysing..." : "Predict Approval"}
              </button>
            </div>

            {predError && <div className="gc-error" style={{ padding: "8px 16px", color: "#DC2626", fontSize: 11 }}>{predError}</div>}

            {prediction && (
              <>
                {/* Gauge */}
                <div className="pi-gauge-wrap">
                  <ApprovalGauge probability={prediction.approval_probability ?? prediction.probability ?? 0} />
                  {prediction.verdict && (
                    <div className={`pi-verdict pi-verdict--${prediction.verdict === "LIKELY" || prediction.approval_probability > 0.6 ? "go" : prediction.verdict === "UNCERTAIN" || (prediction.approval_probability >= 0.3 && prediction.approval_probability <= 0.6) ? "caution" : "nogo"}`}>
                      {prediction.verdict || (prediction.approval_probability > 0.6 ? "LIKELY APPROVED" : prediction.approval_probability > 0.3 ? "UNCERTAIN" : "LIKELY REFUSED")}
                    </div>
                  )}
                </div>

                {/* Key metrics */}
                <div className="pi-metrics">
                  {prediction.authority && (
                    <div className="pi-metric">
                      <span className="pi-metric-label">Planning Authority</span>
                      <span className="pi-metric-value">{prediction.authority}</span>
                    </div>
                  )}
                  {prediction.approval_rate != null && (
                    <div className="pi-metric">
                      <span className="pi-metric-label">Authority Approval Rate</span>
                      <span className="pi-metric-value">{pct(prediction.approval_rate)}</span>
                    </div>
                  )}
                  {prediction.avg_determination_weeks != null && (
                    <div className="pi-metric">
                      <span className="pi-metric-label">Avg Determination</span>
                      <span className="pi-metric-value">{prediction.avg_determination_weeks} weeks</span>
                    </div>
                  )}
                  {prediction.model_version && (
                    <div className="pi-metric">
                      <span className="pi-metric-label">Model</span>
                      <span className="pi-metric-value">{prediction.model_version}</span>
                    </div>
                  )}
                </div>

                {/* Risk factors */}
                {prediction.risk_factors?.length > 0 && (
                  <div className="pi-section">
                    <div className="pi-section-title">Risk Factors</div>
                    {prediction.risk_factors.map((r, i) => (
                      <div className="gc-risk-item" key={i}>
                        <span className={`gc-risk-dot gc-risk-dot--${r.severity === "high" ? "risk" : "note"}`} />
                        <span>{r.description || r.factor || r}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Mitigations */}
                {prediction.mitigations?.length > 0 && (
                  <div className="pi-section">
                    <div className="pi-section-title">Recommended Mitigations</div>
                    {prediction.mitigations.map((m, i) => (
                      <div className="gc-risk-item" key={i}>
                        <span className="gc-risk-dot gc-risk-dot--note" />
                        <span>{m.description || m}</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            {/* Comparable decisions */}
            {comparables?.projects?.length > 0 && (
              <div className="pi-section">
                <div className="pi-section-title">
                  Comparable Decisions
                  <span className="gc-section-badge">{comparables.projects.length}</span>
                </div>
                <div className="pi-comparables-table">
                  <div className="pi-comp-header">
                    <span>Project</span>
                    <span>MW</span>
                    <span>Distance</span>
                    <span>Outcome</span>
                  </div>
                  {comparables.projects.slice(0, 5).map((p, i) => (
                    <div key={i} className="pi-comp-row">
                      <span className="pi-comp-name" title={p.name || p.site_name}>
                        {(p.name || p.site_name || "Project").slice(0, 28)}
                      </span>
                      <span className="pi-comp-mw">{p.capacity_mw?.toFixed(0) || "--"}</span>
                      <span className="pi-comp-dist">{p.distance_km?.toFixed(1) || "--"} km</span>
                      <span className={`pi-comp-outcome pi-comp-outcome--${(p.status || p.outcome || "").toLowerCase().includes("approv") ? "approved" : (p.status || p.outcome || "").toLowerCase().includes("refus") ? "refused" : "other"}`}>
                        {p.status || p.outcome || "--"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {!prediction && !predLoading && (
              <div className="gc-empty">
                <div className="gc-empty-icon">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--cds-interactive)" strokeWidth="1.5">
                    <path d="M3 21h18M9 8h1M9 12h1M9 16h1M14 8h1M14 12h1M14 16h1M5 21V5a2 2 0 012-2h10a2 2 0 012 2v16" />
                  </svg>
                </div>
                <div className="gc-empty-text">
                  Configure site parameters and click<br /><strong>Predict Approval</strong> to run ML analysis
                </div>
              </div>
            )}
          </>
        )}

        {/* ═══════════════════ TAB: Compliance ═══════════════════ */}
        {activeTab === "compliance" && (
          <>
            {compLoading ? (
              <div className="gc-loading" style={{ padding: 24, textAlign: "center", fontSize: 11, color: "var(--cds-text-helper)" }}>Loading compliance data...</div>
            ) : (
              <>
                {/* Compliance ring + summary */}
                <div className="pi-compliance-header">
                  <ComplianceRing score={completedCount} total={requiredCount || REGULATIONS.length} />
                  <div className="pi-compliance-summary">
                    <div className="pi-compliance-stat">
                      <span className="pi-compliance-stat-val">{completedCount}</span>
                      <span className="pi-compliance-stat-label">Complete</span>
                    </div>
                    <div className="pi-compliance-stat">
                      <span className="pi-compliance-stat-val">{Object.values(regStatuses).filter(s => s === "required").length}</span>
                      <span className="pi-compliance-stat-label">Outstanding</span>
                    </div>
                    <div className="pi-compliance-stat">
                      <span className="pi-compliance-stat-val">{Object.values(regStatuses).filter(s => s === "not_required").length}</span>
                      <span className="pi-compliance-stat-label">N/A</span>
                    </div>
                  </div>
                </div>

                {/* Regulation checklist */}
                <div className="pi-reg-list">
                  {REGULATIONS.map(reg => {
                    const status = regStatuses[reg.id] || "pending";
                    const compItem = complianceData?.requirements?.find(r => r.id === reg.id);
                    return (
                      <div key={reg.id} className={`pi-reg-item pi-reg-item--${status}`}>
                        <div className="pi-reg-main" onClick={() => toggleRegStatus(reg.id)}>
                          <div className={`pi-reg-checkbox pi-reg-checkbox--${status}`}>
                            {status === "complete" && (
                              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                                <polyline points="20 6 9 17 4 12" />
                              </svg>
                            )}
                            {status === "not_required" && <span style={{ fontSize: 8 }}>--</span>}
                          </div>
                          <div className="pi-reg-info">
                            <div className="pi-reg-name">{reg.label}</div>
                            <div className="pi-reg-desc">{compItem?.detail || reg.description}</div>
                          </div>
                          {statusBadge(status)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </>
        )}

        {/* ═══════════════════ TAB: Monitor ═══════════════════ */}
        {activeTab === "monitor" && (
          <>
            {monLoading ? (
              <div className="gc-loading" style={{ padding: 24, textAlign: "center", fontSize: 11, color: "var(--cds-text-helper)" }}>Loading planning data...</div>
            ) : (
              <>
                {/* Planning constraints near site */}
                {monitorData?.constraints && (
                  <div className="pi-section">
                    <div className="pi-section-title">
                      Planning Constraints
                      {monitorData.constraints.total_constraints != null && (
                        <span className="gc-section-badge">{monitorData.constraints.total_constraints}</span>
                      )}
                    </div>
                    {monitorData.constraints.constraints?.length > 0 ? (
                      monitorData.constraints.constraints.map((c, i) => (
                        <div className="pi-constraint-item" key={i}>
                          <div className="pi-constraint-type">{c.type || c.category || "Constraint"}</div>
                          <div className="pi-constraint-name">{c.name || c.description}</div>
                          {c.distance_m != null && (
                            <div className="pi-constraint-dist">{(c.distance_m / 1000).toFixed(1)} km</div>
                          )}
                        </div>
                      ))
                    ) : (
                      <div className="pi-no-data">No planning constraints identified within 5 km</div>
                    )}
                  </div>
                )}

                {/* NSIP Projects nearby */}
                {monitorData?.nsip && (
                  <div className="pi-section">
                    <div className="pi-section-title">
                      Nationally Significant Infrastructure
                      {monitorData.nsip.projects?.length > 0 && (
                        <span className="gc-section-badge" style={{ background: "rgba(220,38,38,0.1)", color: "#DC2626" }}>
                          {monitorData.nsip.projects.length}
                        </span>
                      )}
                    </div>
                    {monitorData.nsip.projects?.length > 0 ? (
                      monitorData.nsip.projects.map((p, i) => (
                        <div className="pi-nsip-item" key={i}>
                          <div className="pi-nsip-header">
                            <span className="pi-nsip-name">{p.name || p.project_name}</span>
                            <span className={`pi-nsip-status pi-nsip-status--${(p.status || "").toLowerCase().replace(/\s+/g, "-")}`}>
                              {p.status || "Unknown"}
                            </span>
                          </div>
                          {p.technology && <div className="pi-nsip-tech">{p.technology} -- {p.capacity_mw ? `${p.capacity_mw} MW` : ""}</div>}
                          {p.distance_km != null && <div className="pi-nsip-dist">{p.distance_km.toFixed(1)} km from site</div>}
                        </div>
                      ))
                    ) : (
                      <div className="pi-no-data">No NSIP projects within 20 km</div>
                    )}
                  </div>
                )}

                {/* Decision timeline info */}
                <div className="pi-section">
                  <div className="pi-section-title">Typical Decision Timeline</div>
                  <div className="pi-timeline">
                    {[
                      { phase: "Pre-application", weeks: "2-4", color: "#F5B731" },
                      { phase: "Validation", weeks: "1-2", color: "#3b82f6" },
                      { phase: "Consultation", weeks: "3-4", color: "#6366f1" },
                      { phase: "Assessment", weeks: "4-8", color: "#8b5cf6" },
                      { phase: "Committee", weeks: "1-2", color: "#a78bfa" },
                      { phase: "Decision", weeks: "1", color: "#16A34A" },
                    ].map((p, i) => (
                      <div key={i} className="pi-timeline-phase">
                        <div className="pi-timeline-bar" style={{ background: p.color }} />
                        <div className="pi-timeline-info">
                          <span className="pi-timeline-name">{p.phase}</span>
                          <span className="pi-timeline-weeks">{p.weeks} wk</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Energy Pulse */}
                <div className="pi-section">
                  <div className="pi-section-title">Regional Energy Pulse</div>
                  <div className="pi-pulse-note">
                    Recent energy planning activity is aggregated from REPD and local authority records.
                    Use the agent chat for detailed regional analysis.
                  </div>
                </div>

                {!monitorData && (
                  <div className="gc-empty">
                    <div className="gc-empty-text">No monitoring data available for this location</div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>

      {/* Footer */}
      <div className="pi-footer">
        <span>REPD ML v2 -- 13,995 UK projects</span>
        <span>{lat.toFixed(2)}, {lon.toFixed(2)}</span>
      </div>
    </div>
  );
}
