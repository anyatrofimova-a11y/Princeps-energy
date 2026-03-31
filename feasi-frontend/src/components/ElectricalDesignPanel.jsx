import React, { useState, useCallback, useMemo } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/* ── Helpers ──────────────────────────────────────────────────────────────── */
function fmtNum(v, dp = 0) { return v != null ? Number(v).toFixed(dp) : "--"; }
function fmtGbp(v) {
  if (v == null) return "--";
  if (v >= 1_000_000) return `\u00A3${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1000) return `\u00A3${(v / 1000).toFixed(0)}k`;
  return `\u00A3${v.toFixed(0)}`;
}
function fmtPct(v) { return v != null ? `${Number(v).toFixed(1)}%` : "--"; }

/* ── Cable voltage drop bar (SVG) ────────────────────────────────────────── */
function VoltageDropBar({ dropPct, limit = 3, width = 200, height = 18 }) {
  const pct = Math.min(dropPct || 0, limit * 2);
  const ratio = pct / (limit * 2);
  const color = pct <= limit * 0.6 ? "#16A34A" : pct <= limit ? "#F5B731" : "#DC2626";
  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", maxWidth: width, height: "auto" }}>
      <rect x={0} y={4} width={width} height={10} rx={3} fill="rgba(255,255,255,0.06)" />
      <rect x={0} y={4} width={Math.max(4, ratio * width)} height={10} rx={3} fill={color} opacity={0.85} />
      <line x1={width * 0.5} y1={2} x2={width * 0.5} y2={height - 2} stroke="var(--cds-text-helper)" strokeWidth={0.5} strokeDasharray="2,2" />
      <text x={width * 0.5 + 4} y={height - 3} fill="var(--cds-text-helper)" fontSize="7">{limit}% limit</text>
    </svg>
  );
}

/* ════════════════════════════════════════════════════════════════════════════ */
/*  ElectricalDesignPanel                                                     */
/* ════════════════════════════════════════════════════════════════════════════ */
export default function ElectricalDesignPanel({ onClose, embedded }) {
  const { samCapacity } = useSite();
  const [tab, setTab] = useState("inverters");
  const [loading, setLoading] = useState(false);

  // System capacity in kWp
  const [capacityKwp, setCapacityKwp] = useState(() => samCapacity || 5000);
  const [dcAcRatio, setDcAcRatio] = useState(1.25);

  // ── Inverter state ──
  const [inverterData, setInverterData] = useState(null);
  const [selectedInverter, setSelectedInverter] = useState(null);

  // ── Transformer state ──
  const [transformerData, setTransformerData] = useState(null);

  // ── Cable state ──
  const [cableData, setCableData] = useState(null);

  /* ── Fetch inverters ───────────────────────────────────────────────────── */
  const fetchInverters = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.electrical.inverters(capacityKwp, dcAcRatio);
      setInverterData(data);
      if (data?.recommended && data.recommended.length > 0) {
        setSelectedInverter(data.recommended[0]);
      }
    } catch (e) { console.warn("[ElectricalDesign] inverters error:", e); }
    setLoading(false);
  }, [capacityKwp, dcAcRatio]);

  /* ── Fetch transformers ────────────────────────────────────────────────── */
  const fetchTransformers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.electrical.transformers(capacityKwp, selectedInverter?.model);
      setTransformerData(data);
    } catch (e) { console.warn("[ElectricalDesign] transformers error:", e); }
    setLoading(false);
  }, [capacityKwp, selectedInverter]);

  /* ── Fetch cables ──────────────────────────────────────────────────────── */
  const fetchCables = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.electrical.cables(capacityKwp);
      setCableData(data);
    } catch (e) { console.warn("[ElectricalDesign] cables error:", e); }
    setLoading(false);
  }, [capacityKwp]);

  /* ── Computed: AC capacity ─────────────────────────────────────────────── */
  const acCapacityKw = useMemo(() => capacityKwp / dcAcRatio, [capacityKwp, dcAcRatio]);

  /* ── String config summary ─────────────────────────────────────────────── */
  const stringConfig = useMemo(() => {
    if (!inverterData) return null;
    return {
      modulesPerString: inverterData.modules_per_string || 20,
      stringsPerMppt: inverterData.strings_per_mppt || 2,
      totalInverters: inverterData.total_inverters || Math.ceil(capacityKwp / (selectedInverter?.rated_power_kw || 100)),
      totalStrings: inverterData.total_strings || 0,
    };
  }, [inverterData, capacityKwp, selectedInverter]);

  const TABS = [
    { id: "inverters",    label: "Inverters" },
    { id: "transformers", label: "Transformers" },
    { id: "cables",       label: "Cables" },
  ];

  return (
    <div className={`ed-panel${embedded ? " ed-embedded" : ""}`}>
      {!embedded && (
        <div className="ed-header">
          <span className="ed-title">Electrical System Design</span>
          <button className="ed-close" onClick={onClose}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
      )}

      {/* ── Tabs ── */}
      <div className="ed-tabs">
        {TABS.map(t => (
          <button key={t.id} className={`ed-tab${tab === t.id ? " active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="ed-body">
        {/* ── Shared capacity input ── */}
        <div className="ed-capacity-strip">
          <div className="ed-cap-field">
            <label className="ed-label">System DC (kWp)</label>
            <input className="ed-input" type="number" min="10" step="100" value={capacityKwp}
              onChange={e => setCapacityKwp(+e.target.value)} />
          </div>
          <div className="ed-cap-field">
            <label className="ed-label">DC/AC Ratio</label>
            <input className="ed-input" type="number" min="1.0" max="1.6" step="0.05" value={dcAcRatio}
              onChange={e => setDcAcRatio(+e.target.value)} />
          </div>
          <div className="ed-cap-field">
            <label className="ed-label">AC Output</label>
            <span className="ed-cap-val">{fmtNum(acCapacityKw, 1)} kW</span>
          </div>
        </div>

        {/* ════════════════════ TAB 1: INVERTERS ════════════════════ */}
        {tab === "inverters" && (
          <div className="ed-section">
            <button className="ed-btn" onClick={fetchInverters} disabled={loading}>
              {loading && tab === "inverters" ? "Loading..." : "Load Inverter Options"}
            </button>

            {inverterData?.recommended && (
              <>
                <div className="ed-table-wrap">
                  <table className="ed-table">
                    <thead>
                      <tr>
                        <th>Brand</th>
                        <th>Model</th>
                        <th>Power (kW)</th>
                        <th>Eff (%)</th>
                        <th>MPPT</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {inverterData.recommended.map((inv, i) => (
                        <tr key={i} className={selectedInverter?.model === inv.model ? "ed-row-selected" : ""}>
                          <td>{inv.brand}</td>
                          <td className="ed-mono">{inv.model}</td>
                          <td className="ed-mono">{fmtNum(inv.rated_power_kw, 1)}</td>
                          <td className="ed-mono">{fmtPct(inv.efficiency)}</td>
                          <td className="ed-mono">{inv.mppt_count || "--"}</td>
                          <td>
                            <button className="ed-btn-sm" onClick={() => setSelectedInverter(inv)}>
                              {selectedInverter?.model === inv.model ? "Selected" : "Select"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* String configuration */}
                {stringConfig && (
                  <div className="ed-subsection">
                    <h4 className="ed-sub-title">String Configuration</h4>
                    <div className="ed-stats-grid">
                      <div className="ed-stat">
                        <span className="ed-stat-label">Modules/String</span>
                        <span className="ed-stat-val">{stringConfig.modulesPerString}</span>
                      </div>
                      <div className="ed-stat">
                        <span className="ed-stat-label">Strings/MPPT</span>
                        <span className="ed-stat-val">{stringConfig.stringsPerMppt}</span>
                      </div>
                      <div className="ed-stat">
                        <span className="ed-stat-label">Total Inverters</span>
                        <span className="ed-stat-val">{stringConfig.totalInverters}</span>
                      </div>
                      <div className="ed-stat">
                        <span className="ed-stat-label">Total Strings</span>
                        <span className="ed-stat-val">{stringConfig.totalStrings}</span>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ════════════════════ TAB 2: TRANSFORMERS ════════════════════ */}
        {tab === "transformers" && (
          <div className="ed-section">
            <button className="ed-btn" onClick={fetchTransformers} disabled={loading}>
              {loading && tab === "transformers" ? "Loading..." : "Size Transformers"}
            </button>

            {transformerData && (
              <>
                {/* Transformer recommendations */}
                {transformerData.recommended && (
                  <div className="ed-table-wrap">
                    <table className="ed-table">
                      <thead>
                        <tr>
                          <th>Rating (kVA)</th>
                          <th>Voltage Ratio</th>
                          <th>Impedance (%)</th>
                          <th>Count</th>
                        </tr>
                      </thead>
                      <tbody>
                        {transformerData.recommended.map((tx, i) => (
                          <tr key={i}>
                            <td className="ed-mono">{fmtNum(tx.rating_kva, 0)}</td>
                            <td className="ed-mono">{tx.voltage_ratio || "--"}</td>
                            <td className="ed-mono">{fmtPct(tx.impedance_pct)}</td>
                            <td className="ed-mono">{tx.count || 1}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Switchgear */}
                {transformerData.switchgear && (
                  <div className="ed-subsection">
                    <h4 className="ed-sub-title">Switchgear and Protection</h4>
                    <div className="ed-stats-grid">
                      <div className="ed-stat">
                        <span className="ed-stat-label">Switchgear Rating</span>
                        <span className="ed-stat-val">{transformerData.switchgear.rating || "--"}</span>
                      </div>
                      <div className="ed-stat">
                        <span className="ed-stat-label">Fault Level</span>
                        <span className="ed-stat-val">{transformerData.switchgear.fault_level || "--"}</span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Protection scheme */}
                {transformerData.protection && (
                  <div className="ed-subsection">
                    <h4 className="ed-sub-title">Protection Scheme</h4>
                    <div className="ed-protection-list">
                      {(transformerData.protection.schemes || []).map((p, i) => (
                        <div key={i} className="ed-prot-item">
                          <span className="ed-prot-dot" />
                          <div>
                            <span className="ed-prot-name">{p.name}</span>
                            <span className="ed-prot-desc">{p.description}</span>
                          </div>
                        </div>
                      ))}
                      {(!transformerData.protection.schemes || transformerData.protection.schemes.length === 0) && (
                        <>
                          <div className="ed-prot-item"><span className="ed-prot-dot" /><div><span className="ed-prot-name">Overcurrent (IDMT)</span><span className="ed-prot-desc">51/51N with grading study</span></div></div>
                          <div className="ed-prot-item"><span className="ed-prot-dot" /><div><span className="ed-prot-name">Earth Fault</span><span className="ed-prot-desc">Restricted earth fault (64) on transformer</span></div></div>
                          <div className="ed-prot-item"><span className="ed-prot-dot" /><div><span className="ed-prot-name">Anti-Islanding</span><span className="ed-prot-desc">ROCOF + vector shift per G99</span></div></div>
                          <div className="ed-prot-item"><span className="ed-prot-dot" /><div><span className="ed-prot-name">Differential</span><span className="ed-prot-desc">Transformer differential (87T) for &gt;5MVA</span></div></div>
                        </>
                      )}
                    </div>
                  </div>
                )}

                {/* SLD reference */}
                <div className="ed-subsection">
                  <h4 className="ed-sub-title">Single Line Diagram</h4>
                  <p className="ed-desc">
                    {transformerData.sld_summary || `${fmtNum(capacityKwp / 1000, 1)} MWp solar array -- ${transformerData.recommended?.[0]?.count || 1}x ${fmtNum(transformerData.recommended?.[0]?.rating_kva, 0)} kVA transformer(s) -- ${transformerData.switchgear?.rating || "11kV"} RMU -- DNO point of connection`}
                  </p>
                </div>
              </>
            )}
          </div>
        )}

        {/* ════════════════════ TAB 3: CABLES ════════════════════ */}
        {tab === "cables" && (
          <div className="ed-section">
            <button className="ed-btn" onClick={fetchCables} disabled={loading}>
              {loading && tab === "cables" ? "Loading..." : "Calculate Cable Schedule"}
            </button>

            {cableData && (
              <>
                {/* Cable run table */}
                {cableData.runs && (
                  <div className="ed-table-wrap">
                    <table className="ed-table">
                      <thead>
                        <tr>
                          <th>From</th>
                          <th>To</th>
                          <th>Length (m)</th>
                          <th>Voltage</th>
                          <th>Current (A)</th>
                          <th>Size (mm2)</th>
                          <th>V-Drop (%)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {cableData.runs.map((run, i) => (
                          <tr key={i}>
                            <td>{run.from}</td>
                            <td>{run.to}</td>
                            <td className="ed-mono">{fmtNum(run.length_m, 0)}</td>
                            <td className="ed-mono">{run.voltage || "--"}</td>
                            <td className="ed-mono">{fmtNum(run.current_a, 1)}</td>
                            <td className="ed-mono">{run.cable_size || "--"}</td>
                            <td>
                              <div className="ed-vdrop-cell">
                                <span className="ed-mono">{fmtPct(run.voltage_drop_pct)}</span>
                                <VoltageDropBar dropPct={run.voltage_drop_pct} />
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Summary stats */}
                <div className="ed-stats-grid">
                  <div className="ed-stat">
                    <span className="ed-stat-label">Total Cable Cost</span>
                    <span className="ed-stat-val">{fmtGbp(cableData.total_cost)}</span>
                  </div>
                  <div className="ed-stat">
                    <span className="ed-stat-label">Total Length</span>
                    <span className="ed-stat-val">{fmtNum(cableData.total_length_m, 0)}m</span>
                  </div>
                  <div className="ed-stat">
                    <span className="ed-stat-label">Cable Losses</span>
                    <span className="ed-stat-val">{fmtPct(cableData.losses_pct)}</span>
                  </div>
                  <div className="ed-stat">
                    <span className="ed-stat-label">Max Voltage Drop</span>
                    <span className="ed-stat-val">{fmtPct(cableData.max_voltage_drop_pct)}</span>
                  </div>
                </div>

                {/* Export */}
                <div className="ed-export-row">
                  <button className="ed-btn ed-btn-export" onClick={() => {
                    // Trigger cable schedule CSV download
                    if (cableData.runs) {
                      const csv = ["From,To,Length (m),Voltage,Current (A),Cable Size (mm2),V-Drop (%)"];
                      cableData.runs.forEach(r => csv.push(`${r.from},${r.to},${r.length_m},${r.voltage},${r.current_a},${r.cable_size},${r.voltage_drop_pct}`));
                      const blob = new Blob([csv.join("\n")], { type: "text/csv" });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url; a.download = "cable_schedule.csv"; a.click();
                      URL.revokeObjectURL(url);
                    }
                  }}>
                    Export Cable Schedule (CSV)
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
