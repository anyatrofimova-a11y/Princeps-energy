import React, { useState, useCallback, useEffect } from "react";
import { useSite } from "../SiteContext";

const TIMELINE_PHASES = [
  { key: "design", label: "Design", color: "#D4A018", pct: 15 },
  { key: "application", label: "Apply", color: "#3b82f6", pct: 20 },
  { key: "assessment", label: "Assess", color: "#6366f1", pct: 25 },
  { key: "construction", label: "Build", color: "#8b5cf6", pct: 30 },
  { key: "commissioning", label: "Commission", color: "#a78bfa", pct: 10 },
];

const COST_BREAKDOWN = [
  { key: "reinforcement", label: "Reinforcement", share: 0.35 },
  { key: "cabling", label: "Cabling & Civils", share: 0.25 },
  { key: "switchgear", label: "Switchgear", share: 0.15 },
  { key: "dno_fees", label: "DNO Fees", share: 0.15 },
  { key: "design_legal", label: "Design & Legal", share: 0.10 },
];

function scoreClass(s) {
  if (s >= 70) return "high";
  if (s >= 40) return "mid";
  return "low";
}

function headroomClass(pct) {
  if (pct >= 50) return "green";
  if (pct >= 20) return "amber";
  return "red";
}

function verdictClass(v) {
  if (v === "GO") return "go";
  if (v === "CAUTION") return "caution";
  return "no-go";
}

function fmtGbp(val) {
  if (val == null) return "--";
  if (val >= 1_000_000) return `\u00A3${(val / 1_000_000).toFixed(1)}M`;
  if (val >= 1000) return `\u00A3${(val / 1000).toFixed(0)}k`;
  return `\u00A3${val.toFixed(0)}`;
}

export default function GridConnectionPanel({ onClose, onHighlightSubstation }) {
  const { selectedParcel, parcelId, explain, samCapacity } = useSite();
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [capacityMw, setCapacityMw] = useState(() => samCapacity ? samCapacity / 1000 : 5);
  const [technology, setTechnology] = useState("solar");
  const [expandedSub, setExpandedSub] = useState(null);
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [pfResult, setPfResult] = useState(null);
  const [pfLoading, setPfLoading] = useState(false);
  const [pfError, setPfError] = useState(null);

  // Sync capacity from samCapacity
  useEffect(() => {
    if (samCapacity) setCapacityMw(samCapacity / 1000);
  }, [samCapacity]);

  const assess = useCallback(async () => {
    setLoading(true);
    setError(null);
    setExpandedSub(null);
    setSelectedCandidate(null);
    try {
      const lat = explain?.lat ?? explain?.location?.lat ?? selectedParcel?.lat ?? 52.5;
      const lon = explain?.lon ?? explain?.location?.lon ?? selectedParcel?.lon ?? -1.5;
      const params = new URLSearchParams({
        lat, lon, capacity_mw: capacityMw, technology,
      });
      const res = await fetch(`/api/grid/assess?${params}`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResult(data);
      // Auto-select best candidate
      if (data.candidates?.length > 0) {
        setSelectedCandidate(0);
        onHighlightSubstation?.(data.candidates[0]);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [explain, selectedParcel, capacityMw, technology, onHighlightSubstation]);

  const runPowerFlow = useCallback(async (substationId) => {
    setPfLoading(true);
    setPfError(null);
    try {
      const lat = explain?.lat ?? explain?.location?.lat ?? selectedParcel?.lat ?? 52.5;
      const lon = explain?.lon ?? explain?.location?.lon ?? selectedParcel?.lon ?? -1.5;
      const params = new URLSearchParams({
        lat, lon, capacity_mw: capacityMw, technology,
        ...(substationId != null && { substation_id: substationId }),
      });
      const res = await fetch(`/api/grid/power-flow?${params}`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setPfResult(data);
    } catch (e) {
      setPfError(e.message);
    } finally {
      setPfLoading(false);
    }
  }, [explain, selectedParcel, capacityMw, technology]);

  // Auto-assess when panel opens with a valid parcel
  useEffect(() => {
    if (parcelId && !result && !loading) {
      assess();
    }
  }, [parcelId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleCandidateClick = (i) => {
    setExpandedSub(expandedSub === i ? null : i);
    setSelectedCandidate(i);
    if (result?.candidates?.[i]) {
      onHighlightSubstation?.(result.candidates[i]);
    }
  };

  const cost = result?.cost_estimate;
  const maxCost = cost?.breakdown
    ? Math.max(...Object.values(cost.breakdown).map(v => v || 0))
    : cost?.cost_gbp?.p90 || 1;

  return (
    <div className="gc-panel">
      {/* Header */}
      <div className="gc-panel-header">
        <span className="gc-panel-title">Grid Connection</span>
        <button className="gc-panel-close" onClick={onClose}>&times;</button>
      </div>

      {/* Input bar */}
      <div className="gc-input-bar">
        <div className="gc-input-group">
          <label className="gc-input-label">Capacity (MW)</label>
          <input
            type="number" value={capacityMw} min={0.01} step={0.5}
            onChange={e => setCapacityMw(+e.target.value)}
            className="gc-input"
          />
        </div>
        <div className="gc-input-group">
          <label className="gc-input-label">Technology</label>
          <select
            value={technology} onChange={e => setTechnology(e.target.value)}
            className="gc-input"
          >
            <option value="solar">Solar PV</option>
            <option value="wind">Wind</option>
            <option value="bess">BESS</option>
            <option value="demand">Demand</option>
          </select>
        </div>
        <button
          onClick={assess}
          disabled={loading}
          className={`gc-assess-btn${loading ? " gc-assess-btn--loading" : ""}`}
        >
          {loading ? "Assessing..." : "Assess"}
        </button>
      </div>

      {/* Body */}
      <div className="gc-panel-body">
        {error && (
          <div style={{ padding: "12px 16px", color: "#da1e28", fontSize: 11 }}>{error}</div>
        )}

        {!result && !loading && !error && (
          <div className="gc-empty">
            <div className="gc-empty-icon">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--cds-interactive)" strokeWidth="1.5">
                <path d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <div className="gc-empty-text">
              Click <strong>Assess</strong> to analyse grid connection<br />
              feasibility for this site
            </div>
          </div>
        )}

        {result && (
          <>
            {/* Verdict */}
            <div className={`gc-verdict gc-verdict--${verdictClass(result.verdict)}`}>
              <div className={`gc-verdict-badge gc-verdict-badge--${verdictClass(result.verdict)}`}>
                {result.verdict}
              </div>
              <div className="gc-verdict-info">
                <div className="gc-verdict-title">
                  Connection {result.verdict === "GO" ? "Viable" : result.verdict === "CAUTION" ? "Possible" : "Constrained"}
                </div>
                <div className="gc-verdict-summary">{result.summary}</div>
                <div className="gc-verdict-confidence">
                  {(result.confidence * 100).toFixed(0)}% confidence
                </div>
              </div>
            </div>

            {/* DNO badge */}
            {result.dno_area && (
              <div style={{ padding: "8px 16px 0" }}>
                <span className="gc-dno-badge">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  {result.dno_area.name}
                </span>
              </div>
            )}

            {/* Cost Range P10/P50/P90 */}
            {cost && (
              <div className="gc-section">
                <div className="gc-section-header">
                  <span className="gc-section-title">Connection Cost</span>
                  <span className="gc-section-badge">
                    {cost.timeline_weeks?.p50 ? `~${cost.timeline_weeks.p50} weeks` : ""}
                  </span>
                </div>

                <div className="gc-cost-range">
                  <div className="gc-cost-range-item">
                    <div className="gc-cost-range-label">P10</div>
                    <div className="gc-cost-range-value">{fmtGbp(cost.cost_gbp?.p10)}</div>
                  </div>
                  <div className="gc-cost-range-item gc-cost-range-item--p50">
                    <div className="gc-cost-range-label">P50</div>
                    <div className="gc-cost-range-value">{fmtGbp(cost.cost_gbp?.p50)}</div>
                  </div>
                  <div className="gc-cost-range-item">
                    <div className="gc-cost-range-label">P90</div>
                    <div className="gc-cost-range-value">{fmtGbp(cost.cost_gbp?.p90)}</div>
                  </div>
                </div>

                {/* Cost waterfall breakdown */}
                {cost.breakdown ? (
                  <div className="gc-cost-waterfall" style={{ marginTop: 12 }}>
                    {Object.entries(cost.breakdown).map(([k, v]) => (
                      <div className="gc-cost-row" key={k}>
                        <span className="gc-cost-label">{k.replace(/_/g, " ")}</span>
                        <div className="gc-cost-bar-track">
                          <div className="gc-cost-bar-fill" style={{ width: `${(v / maxCost) * 100}%` }} />
                        </div>
                        <span className="gc-cost-value">{fmtGbp(v)}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="gc-cost-waterfall" style={{ marginTop: 12 }}>
                    {COST_BREAKDOWN.map(item => {
                      const val = (cost.cost_gbp?.p50 || 0) * item.share;
                      return (
                        <div className="gc-cost-row" key={item.key}>
                          <span className="gc-cost-label">{item.label}</span>
                          <div className="gc-cost-bar-track">
                            <div className="gc-cost-bar-fill" style={{ width: `${item.share * 100}%` }} />
                          </div>
                          <span className="gc-cost-value">{fmtGbp(val)}</span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Timeline */}
            {cost?.timeline_weeks && (
              <div className="gc-section">
                <div className="gc-section-header">
                  <span className="gc-section-title">Connection Timeline</span>
                  <span className="gc-section-badge">
                    {cost.timeline_weeks.p10}–{cost.timeline_weeks.p90} weeks
                  </span>
                </div>
                <div className="gc-timeline-bar">
                  {TIMELINE_PHASES.map(p => (
                    <div
                      key={p.key}
                      className="gc-timeline-phase"
                      style={{ flex: p.pct, background: p.color }}
                    >
                      {p.label}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Candidate Substations */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">Connection Candidates</span>
                <span className="gc-section-badge">{result.candidates?.length || 0}</span>
              </div>

              {result.candidates?.map((c, i) => {
                const expanded = expandedSub === i;
                const selected = selectedCandidate === i;
                const headroomPct = c.gen_headroom_mw != null && c.gen_capacity_mw
                  ? Math.min(100, (c.gen_headroom_mw / c.gen_capacity_mw) * 100)
                  : c.gen_headroom_mw != null
                    ? Math.min(100, c.gen_headroom_mw * 10) // rough scale if no capacity
                    : null;

                return (
                  <div
                    key={c.id || i}
                    className={`gc-candidate${selected ? " gc-candidate--selected" : ""}${i === 0 ? " gc-candidate--best" : ""}`}
                    onClick={() => handleCandidateClick(i)}
                  >
                    <div className="gc-candidate-row">
                      <div className={`gc-candidate-score gc-score--${scoreClass(c.suitability_score)}`}>
                        {c.suitability_score}
                      </div>
                      <div className="gc-candidate-info">
                        <div className="gc-candidate-name">{c.name}</div>
                        <div className="gc-candidate-meta">
                          <span>{c.voltage_kv}kV</span>
                          <span>{c.distance_km?.toFixed(1)} km</span>
                          {c.dno && <span>{c.dno.toUpperCase()}</span>}
                          <span className={`gc-rag gc-rag--${c.rag_generation || "amber"}`} />
                        </div>
                      </div>
                    </div>

                    {/* Headroom bar */}
                    {headroomPct != null && (
                      <>
                        <div className="gc-headroom-bar">
                          <div
                            className={`gc-headroom-fill gc-headroom-fill--${headroomClass(headroomPct)}`}
                            style={{ width: `${headroomPct}%` }}
                          />
                        </div>
                        <div className="gc-headroom-labels">
                          <span>{c.gen_headroom_mw?.toFixed(1)} MW available</span>
                          <span>{c.gen_capacity_mw ? `${c.gen_capacity_mw} MW total` : ""}</span>
                        </div>
                      </>
                    )}

                    {/* Queue */}
                    {c.queue?.ecr_queued > 0 && (
                      <div style={{ marginTop: 4 }}>
                        <div className="gc-queue-bar">
                          {Array.from({ length: Math.min(c.queue.ecr_queued, 8) }).map((_, j) => (
                            <div
                              key={j}
                              className="gc-queue-seg"
                              style={{
                                flex: 1,
                                background: j < 3 ? "#da1e28" : j < 5 ? "#f1c21b" : "#24a148",
                              }}
                            />
                          ))}
                        </div>
                        <div style={{ fontSize: 9, color: "var(--cds-text-helper)", marginTop: 2 }}>
                          {c.queue.ecr_queued} queued ({c.queue.ecr_queued_mw?.toFixed(0)} MW)
                        </div>
                      </div>
                    )}

                    {/* Expanded details */}
                    {expanded && (
                      <div className="gc-candidate-details">
                        <div className="gc-stat-grid">
                          {c.gen_headroom_mw != null && (
                            <div className="gc-stat">
                              <span className="gc-stat-label">Gen Headroom</span>
                              <span className="gc-stat-value">{c.gen_headroom_mw} MW</span>
                            </div>
                          )}
                          {c.dem_headroom_mw != null && (
                            <div className="gc-stat">
                              <span className="gc-stat-label">Dem Headroom</span>
                              <span className="gc-stat-value">{c.dem_headroom_mw} MW</span>
                            </div>
                          )}
                          {c.voltage_kv && (
                            <div className="gc-stat">
                              <span className="gc-stat-label">Voltage</span>
                              <span className="gc-stat-value">{c.voltage_kv} kV</span>
                            </div>
                          )}
                          {c.distance_km != null && (
                            <div className="gc-stat">
                              <span className="gc-stat-label">Distance</span>
                              <span className="gc-stat-value">{c.distance_km?.toFixed(2)} km</span>
                            </div>
                          )}
                        </div>

                        {/* Notes */}
                        {c.notes?.length > 0 && (
                          <div style={{ marginTop: 8 }}>
                            {c.notes.map((n, j) => (
                              <div className="gc-risk-item" key={j}>
                                <span className="gc-risk-dot gc-risk-dot--note" />
                                <span>{n}</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Risks */}
                        {c.risks?.length > 0 && (
                          <div style={{ marginTop: 6 }}>
                            {c.risks.map((r, j) => (
                              <div className="gc-risk-item" key={j}>
                                <span className="gc-risk-dot gc-risk-dot--risk" />
                                <span>{r}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Power Flow Analysis (Tier 2) */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">Power Flow Analysis</span>
                {pfResult?.verdict && (
                  <span
                    className="gc-section-badge"
                    style={{
                      background: pfResult.verdict === "PASS" ? "rgba(36,161,72,0.12)"
                        : pfResult.verdict === "MARGINAL" ? "rgba(241,194,27,0.1)"
                        : "rgba(218,30,40,0.12)",
                      color: pfResult.verdict === "PASS" ? "#24a148"
                        : pfResult.verdict === "MARGINAL" ? "#b28600"
                        : "#da1e28",
                    }}
                  >
                    {pfResult.verdict}
                  </span>
                )}
              </div>

              {!pfResult && !pfLoading && (
                <button
                  onClick={() => {
                    const bestId = result?.best_candidate?.id ?? (result?.candidates?.[selectedCandidate ?? 0]?.id);
                    runPowerFlow(bestId);
                  }}
                  disabled={pfLoading}
                  className="gc-assess-btn"
                  style={{ width: "100%", marginBottom: 4 }}
                >
                  Run Power Flow Simulation
                </button>
              )}

              {pfLoading && (
                <div style={{ textAlign: "center", padding: "12px 0", fontSize: 11, color: "var(--cds-text-helper)" }}>
                  <span className="gc-assess-btn--loading" style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "var(--cds-interactive)", marginRight: 6 }} />
                  Running pandapower simulation...
                </div>
              )}

              {pfError && (
                <div style={{ color: "#da1e28", fontSize: 11, padding: "4px 0" }}>{pfError}</div>
              )}

              {pfResult?.success && pfResult.converged && (
                <>
                  {/* Summary stats */}
                  <div className="gc-stat-grid" style={{ marginBottom: 8 }}>
                    <div className="gc-stat">
                      <span className="gc-stat-label">Voltage Range</span>
                      <span className="gc-stat-value">
                        {pfResult.summary?.min_voltage_pu?.toFixed(3)}–{pfResult.summary?.max_voltage_pu?.toFixed(3)} pu
                      </span>
                    </div>
                    <div className="gc-stat">
                      <span className="gc-stat-label">Max Loading</span>
                      <span className="gc-stat-value" style={{
                        color: pfResult.summary?.max_loading_pct > 80 ? "#da1e28"
                          : pfResult.summary?.max_loading_pct > 60 ? "#f1c21b" : "#24a148",
                      }}>
                        {pfResult.summary?.max_loading_pct?.toFixed(1)}%
                      </span>
                    </div>
                    <div className="gc-stat">
                      <span className="gc-stat-label">Voltage Rise</span>
                      <span className="gc-stat-value" style={{
                        color: Math.abs(pfResult.summary?.voltage_rise_pu || 0) > 0.03 ? "#f1c21b" : "var(--cds-text-primary)",
                      }}>
                        {pfResult.summary?.voltage_rise_pu >= 0 ? "+" : ""}{(pfResult.summary?.voltage_rise_pu * 100)?.toFixed(2)}%
                      </span>
                    </div>
                    <div className="gc-stat">
                      <span className="gc-stat-label">Losses</span>
                      <span className="gc-stat-value">{pfResult.summary?.total_losses_mw?.toFixed(3)} MW</span>
                    </div>
                    {pfResult.summary?.thermal_headroom_mw != null && (
                      <div className="gc-stat">
                        <span className="gc-stat-label">Thermal Headroom</span>
                        <span className="gc-stat-value" style={{ color: "#24a148" }}>
                          {pfResult.summary.thermal_headroom_mw} MW
                        </span>
                      </div>
                    )}
                    {pfResult.summary?.reverse_power_flow && (
                      <div className="gc-stat">
                        <span className="gc-stat-label">Reverse Flow</span>
                        <span className="gc-stat-value" style={{ color: "#f1c21b" }}>Yes</span>
                      </div>
                    )}
                  </div>

                  {/* Bus voltage profile */}
                  {pfResult.bus_results?.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: 9, color: "var(--cds-text-helper)", marginBottom: 4, textTransform: "uppercase", letterSpacing: 1 }}>
                        Bus Voltages
                      </div>
                      {pfResult.bus_results.map((b, i) => {
                        const pct = ((b.vm_pu - 0.9) / 0.2) * 100; // scale 0.9-1.1 to 0-100
                        const inRange = b.vm_pu >= 0.94 && b.vm_pu <= 1.06;
                        return (
                          <div key={i} style={{ display: "grid", gridTemplateColumns: "90px 1fr 50px", gap: 6, alignItems: "center", fontSize: 10, marginBottom: 2 }}>
                            <span style={{ color: "var(--cds-text-helper)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {b.name}
                            </span>
                            <div style={{ height: 6, background: "rgba(82,82,82,0.15)", borderRadius: 3, position: "relative", overflow: "hidden" }}>
                              <div style={{
                                position: "absolute", left: "20%", right: "20%", top: 0, bottom: 0,
                                background: "rgba(36,161,72,0.08)", borderLeft: "1px solid rgba(36,161,72,0.3)", borderRight: "1px solid rgba(36,161,72,0.3)",
                              }} />
                              <div style={{
                                position: "absolute", left: `${Math.max(0, Math.min(100, pct))}%`,
                                top: -1, width: 8, height: 8, borderRadius: "50%",
                                background: inRange ? "#24a148" : "#da1e28",
                                transform: "translateX(-50%)",
                              }} />
                            </div>
                            <span style={{ textAlign: "right", fontWeight: 600, fontFamily: "var(--mono)", color: inRange ? "var(--cds-text-primary)" : "#da1e28" }}>
                              {b.vm_pu.toFixed(3)}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Line/trafo loading bars */}
                  {(pfResult.line_results?.length > 0 || pfResult.trafo_results?.length > 0) && (
                    <div style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: 9, color: "var(--cds-text-helper)", marginBottom: 4, textTransform: "uppercase", letterSpacing: 1 }}>
                        Thermal Loading
                      </div>
                      {[...(pfResult.line_results || []), ...(pfResult.trafo_results || [])].map((el, i) => {
                        const pct = el.loading_pct || 0;
                        const color = pct > 80 ? "#da1e28" : pct > 60 ? "#f1c21b" : "#24a148";
                        return (
                          <div key={i} className="gc-cost-row">
                            <span className="gc-cost-label">{el.name?.replace(/^(line_|trafo_)/, "")}</span>
                            <div className="gc-cost-bar-track">
                              <div style={{
                                height: "100%", borderRadius: 3, width: `${Math.min(100, pct)}%`,
                                background: `linear-gradient(90deg, ${color}, ${color}aa)`,
                                transition: "width 0.5s cubic-bezier(0.16,1,0.3,1)",
                              }} />
                            </div>
                            <span className="gc-cost-value" style={{ color }}>{pct.toFixed(1)}%</span>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Violations */}
                  {pfResult.violations?.length > 0 && (
                    <div style={{ marginBottom: 4 }}>
                      {pfResult.violations.map((v, i) => (
                        <div className="gc-risk-item" key={i}>
                          <span className="gc-risk-dot gc-risk-dot--risk" />
                          <span>{v.detail}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Notes */}
                  {pfResult.notes?.map((n, i) => (
                    <div className="gc-risk-item" key={i}>
                      <span className="gc-risk-dot gc-risk-dot--note" />
                      <span>{n}</span>
                    </div>
                  ))}

                  {/* Contingency summary */}
                  {pfResult.contingency && (
                    <div style={{ marginTop: 8, padding: "6px 0", borderTop: "1px solid rgba(82,82,82,0.1)" }}>
                      <div style={{ fontSize: 10, fontWeight: 600, color: pfResult.contingency.n1_secure ? "#24a148" : "#da1e28" }}>
                        N-1 Contingency: {pfResult.contingency.n1_secure ? "SECURE" : "INSECURE"}
                        <span style={{ fontWeight: 400, color: "var(--cds-text-helper)", marginLeft: 6 }}>
                          {pfResult.contingency.passed}/{pfResult.contingency.total_contingencies} passed
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Network info */}
                  <div style={{ fontSize: 9, color: "var(--cds-text-helper)", marginTop: 6, opacity: 0.7 }}>
                    {pfResult.network_size?.substations} buses, {pfResult.network_size?.lines} lines | {pfResult.elapsed_s}s
                  </div>
                </>
              )}

              {pfResult && !pfResult.converged && pfResult.success && (
                <div className="gc-risk-item">
                  <span className="gc-risk-dot gc-risk-dot--risk" />
                  <span>Power flow did not converge — network may be unstable with proposed connection</span>
                </div>
              )}

              {pfResult && !pfResult.success && (
                <div style={{ color: "#da1e28", fontSize: 11, padding: "4px 0" }}>
                  {pfResult.error || "Power flow analysis failed"}
                </div>
              )}
            </div>

            {/* Overall Risks */}
            {result.risks?.length > 0 && (
              <div className="gc-section">
                <div className="gc-section-header">
                  <span className="gc-section-title">Risk Assessment</span>
                  <span className="gc-section-badge" style={{ background: "rgba(218,30,40,0.12)", color: "#da1e28" }}>
                    {result.risks.length}
                  </span>
                </div>
                {result.risks.map((r, i) => (
                  <div className="gc-risk-item" key={i}>
                    <span className="gc-risk-dot gc-risk-dot--risk" />
                    <span>{r}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Opportunities */}
            {result.opportunities?.length > 0 && (
              <div className="gc-section">
                <div className="gc-section-header">
                  <span className="gc-section-title">Opportunities</span>
                </div>
                {result.opportunities.map((o, i) => (
                  <div className="gc-risk-item" key={i}>
                    <span className="gc-risk-dot gc-risk-dot--note" />
                    <span>{o}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
