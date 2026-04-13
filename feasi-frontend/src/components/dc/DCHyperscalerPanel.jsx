/**
 * DCHyperscalerPanel — dedicated UI for the 9 MSIP extractions.
 *
 * Full workspace (light theme) that lets a user:
 *   • Enter DC connection parameters
 *   • Run the optioneering engine across all 8 templates
 *   • See the ranked options with cost / timeline / risk / needs_case /
 *     optioneering_defensibility scores
 *   • Drill into the selected option for MVS gap, SQSS, switchgear, BOM,
 *     MSIP eligibility, and escalate cost between price bases
 */
import React, { useState, useCallback, useEffect } from "react";
import api from "../../services/api";

const C = {
  bg:        "#f6f7f9",
  card:      "#ffffff",
  border:    "#e5e7eb",
  text:      "#0f172a",
  textDim:   "#64748b",
  textMuted: "#94a3b8",
  gold:      "#f5b731",
  green:     "#16a34a",
  amber:     "#d97706",
  red:       "#dc2626",
  blue:      "#2563eb",
  purple:    "#7c3aed",
};

const ST = {
  page: {
    height: "100%",
    overflowY: "auto",
    background: C.bg,
    fontFamily: "'DM Sans', 'Inter', system-ui, sans-serif",
    color: C.text,
  },
  inner: { maxWidth: 1400, margin: "0 auto", padding: "24px 32px 64px" },
  header: { marginBottom: 22 },
  title: { fontSize: 22, fontWeight: 800, margin: 0, letterSpacing: -0.3 },
  subtitle: { fontSize: 12, color: C.textDim, marginTop: 4, maxWidth: 800 },
  ref: { fontSize: 10, color: C.textMuted, marginTop: 6, fontFamily: "'JetBrains Mono', monospace" },

  inputGrid: {
    background: C.card,
    border: `1px solid ${C.border}`,
    borderRadius: 12,
    padding: 18,
    marginBottom: 18,
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
    gap: 14,
    alignItems: "end",
  },
  label: {
    fontSize: 10, fontWeight: 700, textTransform: "uppercase",
    letterSpacing: 0.6, color: C.textDim, marginBottom: 5,
  },
  input: {
    width: "100%",
    padding: "8px 12px",
    border: `1px solid ${C.border}`,
    borderRadius: 8,
    fontSize: 13,
    fontFamily: "'DM Sans', sans-serif",
    background: "#fff",
  },
  checkbox: { display: "flex", alignItems: "center", gap: 8, fontSize: 12, marginTop: 8 },
  runButton: {
    gridColumn: "span 1",
    padding: "10px 18px",
    background: C.text,
    color: "#fff",
    border: "none",
    borderRadius: 8,
    fontSize: 12,
    fontWeight: 700,
    cursor: "pointer",
    letterSpacing: 0.3,
  },

  panelGrid: {
    display: "grid",
    gridTemplateColumns: "1.5fr 1fr",
    gap: 18,
    marginBottom: 18,
  },
  panel: {
    background: C.card,
    border: `1px solid ${C.border}`,
    borderRadius: 12,
    padding: 18,
  },
  panelTitle: {
    fontSize: 12, fontWeight: 700, color: C.textDim,
    textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 12,
  },

  optionCard: (selected, feasible) => ({
    border: `1px solid ${selected ? C.text : C.border}`,
    background: !feasible ? "#fafafa" : (selected ? "#f8fafc" : C.card),
    borderRadius: 10,
    padding: "12px 14px",
    marginBottom: 10,
    cursor: feasible ? "pointer" : "not-allowed",
    opacity: feasible ? 1 : 0.55,
    transition: "all 0.15s",
    borderLeft: `4px solid ${selected ? C.gold : "transparent"}`,
  }),
  optHeader: { display: "flex", alignItems: "center", gap: 10, marginBottom: 6 },
  optId: { fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: C.textMuted },
  optName: { flex: 1, fontSize: 13, fontWeight: 700, color: C.text },
  optScore: { fontSize: 18, fontWeight: 800, fontFamily: "'JetBrains Mono', monospace" },
  optDesc: { fontSize: 11, color: C.textDim, marginBottom: 8 },
  optMeta: { display: "flex", gap: 12, fontSize: 10, color: C.textDim, flexWrap: "wrap" },
  optChip: (bg, fg) => ({
    padding: "2px 7px", borderRadius: 10, background: bg, color: fg,
    fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5,
  }),

  row: {
    display: "flex", justifyContent: "space-between",
    padding: "7px 0", borderBottom: `1px dashed ${C.border}`, fontSize: 12,
  },
  rowLabel: { color: C.textDim },
  rowValue: { fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 },

  bar: {
    height: 6, background: C.border, borderRadius: 3, overflow: "hidden",
    marginTop: 4, marginBottom: 8,
  },
  barFill: (pct, colour) => ({
    width: `${Math.min(100, pct)}%`, height: "100%", background: colour,
    transition: "width 0.4s",
  }),
};


function formatGbp(v) {
  if (v == null || Number.isNaN(v)) return "—";
  const n = Number(v);
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${sign}£${(abs / 1e9).toFixed(2)}bn`;
  if (abs >= 1e6) return `${sign}£${(abs / 1e6).toFixed(1)}m`;
  if (abs >= 1e3) return `${sign}£${(abs / 1e3).toFixed(0)}k`;
  return `${sign}£${abs.toFixed(0)}`;
}


export default function DCHyperscalerPanel() {
  const [params, setParams] = useState({
    lat: 51.55,
    lon: -0.27,
    capacity_mva: 120,
    urban: true,
    in_london_dc_cluster: true,
    nearest_400kv_km: 2.5,
    accelerated: false,
    strategic_demand: false,
    customer_role: "demand",
    risk_allowance_pct: 7.5,
  });
  const [result, setResult] = useState(null);
  const [selectedOptionId, setSelectedOptionId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState({
    mvsGap: null,
    msip: null,
    sqss: null,
    bom: null,
  });

  const update = (key) => (e) => {
    const v = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setParams(p => ({ ...p, [key]: v }));
  };

  const run = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.dcHyperscaler.optioneer({
        ...params,
        lat: Number(params.lat),
        lon: Number(params.lon),
        capacity_mva: Number(params.capacity_mva),
        nearest_400kv_km: params.nearest_400kv_km ? Number(params.nearest_400kv_km) : null,
        risk_allowance_pct: Number(params.risk_allowance_pct),
      });
      setResult(res);
      setSelectedOptionId(res.selected_option_id);
    } catch (e) {
      console.warn("[DC hyperscaler] optioneer failed:", e);
    } finally {
      setLoading(false);
    }
  }, [params]);

  // On option selection, pull all the auxiliary endpoints in parallel
  useEffect(() => {
    if (!result || !selectedOptionId) return;
    const opt = result.options.find(o => o.option_id === selectedOptionId);
    if (!opt) return;
    let cancelled = false;

    (async () => {
      try {
        const [mvs, msip, sqss, bom] = await Promise.allSettled([
          api.dcHyperscaler.mvsGap({
            capacity_mva: Number(params.capacity_mva),
            has_dual_feed: opt.dual_feed,
            uses_gis_switchgear: opt.switchgear?.recommended === "GIS",
            voltage_kv: opt.voltage_kv,
            urban: params.urban,
            accelerated_delivery: params.accelerated,
          }),
          api.dcHyperscaler.msipEligibility({
            capacity_mva: Number(params.capacity_mva),
            estimated_cost_gbp: opt.cost.total_connection_cost_gbp,
            risk_allowance_pct: Number(params.risk_allowance_pct),
          }),
          api.dcHyperscaler.sqssCheck({
            capacity_mva: Number(params.capacity_mva),
            voltage_kv: opt.voltage_kv,
            has_dual_feed: opt.dual_feed,
          }),
          api.dcHyperscaler.connectionBom({
            capacity_mva: Number(params.capacity_mva),
            voltage_kv: opt.voltage_kv,
            has_dual_feed: opt.dual_feed,
            uses_gis: opt.switchgear?.recommended === "GIS",
          }),
        ]);
        if (cancelled) return;
        setDetail({
          mvsGap: mvs.status === "fulfilled" ? mvs.value : null,
          msip: msip.status === "fulfilled" ? msip.value : null,
          sqss: sqss.status === "fulfilled" ? sqss.value : null,
          bom: bom.status === "fulfilled" ? bom.value : null,
        });
      } catch (e) {
        console.warn("[DC hyperscaler] detail load failed:", e);
      }
    })();

    return () => { cancelled = true; };
  }, [result, selectedOptionId, params]);

  const selectedOption = result?.options.find(o => o.option_id === selectedOptionId);

  return (
    <div style={ST.page}>
      <div style={ST.inner}>
        <div style={ST.header}>
          <h1 style={ST.title}>DC Hyperscaler Connection Suite</h1>
          <div style={ST.subtitle}>
            Optioneering engine + MVS gap + SQSS compliance + MSIP eligibility +
            switchgear recommendation + BOM + price escalation. Calibrated against
            RIIO-T3 Final Determinations (Dec 2025) and the NGET Microsoft Willesden
            MSIP re-opener (Jan 2024).
          </div>
          <div style={ST.ref}>
            Rules applied: {result?.rules_applied?.join(" · ") || "none yet — run an analysis"}
          </div>
        </div>

        {/* Inputs */}
        <div style={ST.inputGrid}>
          <div>
            <div style={ST.label}>Latitude</div>
            <input style={ST.input} value={params.lat} onChange={update("lat")} type="number" step="0.001" />
          </div>
          <div>
            <div style={ST.label}>Longitude</div>
            <input style={ST.input} value={params.lon} onChange={update("lon")} type="number" step="0.001" />
          </div>
          <div>
            <div style={ST.label}>Capacity (MVA)</div>
            <input style={ST.input} value={params.capacity_mva} onChange={update("capacity_mva")} type="number" step="10" />
          </div>
          <div>
            <div style={ST.label}>Nearest 400kV (km)</div>
            <input style={ST.input} value={params.nearest_400kv_km} onChange={update("nearest_400kv_km")} type="number" step="0.1" />
          </div>
          <div>
            <div style={ST.label}>Customer role</div>
            <select style={ST.input} value={params.customer_role} onChange={update("customer_role")}>
              <option value="demand">Demand (DC)</option>
              <option value="gen">Generation</option>
              <option value="bess">BESS</option>
              <option value="reactive_support">Reactive / ancillary</option>
            </select>
          </div>
          <div>
            <div style={ST.label}>Risk allowance %</div>
            <input style={ST.input} value={params.risk_allowance_pct} onChange={update("risk_allowance_pct")} type="number" step="0.5" />
          </div>
          <div>
            <label style={ST.checkbox}>
              <input type="checkbox" checked={params.urban} onChange={update("urban")} />
              Urban
            </label>
            <label style={ST.checkbox}>
              <input type="checkbox" checked={params.in_london_dc_cluster} onChange={update("in_london_dc_cluster")} />
              London DC cluster
            </label>
            <label style={ST.checkbox}>
              <input type="checkbox" checked={params.accelerated} onChange={update("accelerated")} />
              Accelerated delivery
            </label>
            <label style={ST.checkbox}>
              <input type="checkbox" checked={params.strategic_demand} onChange={update("strategic_demand")} />
              Strategic demand (AI GZ)
            </label>
          </div>
          <button style={ST.runButton} onClick={run} disabled={loading}>
            {loading ? "Running…" : "Run optioneering"}
          </button>
        </div>

        {/* Results */}
        {result && (
          <div style={ST.panelGrid}>
            {/* LEFT — ranked options */}
            <div style={ST.panel}>
              <div style={ST.panelTitle}>
                Ranked options ({result.options_considered} considered · {result.dual_feed_pairs_available} dual-feed pairs found)
              </div>
              {result.options.map(opt => {
                const selected = opt.option_id === selectedOptionId;
                const feasible = opt.feasibility === "feasible";
                return (
                  <div
                    key={opt.option_id}
                    style={ST.optionCard(selected, feasible)}
                    onClick={() => feasible && setSelectedOptionId(opt.option_id)}
                  >
                    <div style={ST.optHeader}>
                      <span style={ST.optId}>{opt.option_id}</span>
                      <span style={ST.optName}>{opt.name}</span>
                      <span style={{
                        ...ST.optScore,
                        color: opt.composite_score >= 50 ? C.green : opt.composite_score >= 0 ? C.amber : C.red,
                      }}>{opt.composite_score}</span>
                    </div>
                    <div style={ST.optDesc}>{opt.description}</div>
                    <div style={ST.optMeta}>
                      <span style={ST.optChip("#dbeafe", C.blue)}>{opt.voltage_kv} kV</span>
                      <span style={ST.optChip("#e0e7ff", "#4338ca")}>{opt.redundancy}</span>
                      <span style={ST.optChip(
                        opt.switchgear?.recommended === "GIS" ? "#fde68a" : "#dcfce7",
                        opt.switchgear?.recommended === "GIS" ? "#92400e" : "#166534",
                      )}>{opt.switchgear?.recommended || "—"}</span>
                      <span>{formatGbp(opt.cost.total_connection_cost_gbp)}</span>
                      <span>{opt.delivery_months}mo</span>
                      <span>Needs case: {opt.needs_case_score}</span>
                      <span>Defensibility: {opt.optioneering_defensibility_score}</span>
                      {opt.msip_route_required && (
                        <span style={ST.optChip("#fef3c7", "#92400e")}>MSIP</span>
                      )}
                      {opt.apm_eligible && (
                        <span style={ST.optChip("#ede9fe", "#6d28d9")}>APM</span>
                      )}
                    </div>
                    {opt.feasibility_notes?.length > 0 && (
                      <div style={{ fontSize: 10, color: C.textDim, marginTop: 6, fontStyle: "italic" }}>
                        {opt.feasibility_notes.join(" · ")}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* RIGHT — selected option detail */}
            <div>
              {selectedOption && (
                <>
                  {/* MVS gap */}
                  {detail.mvsGap && (
                    <div style={{ ...ST.panel, marginBottom: 14 }}>
                      <div style={ST.panelTitle}>MVS gap & customer one-off charge</div>
                      <div style={ST.row}>
                        <span style={ST.rowLabel}>Total connection cost</span>
                        <span style={ST.rowValue}>{formatGbp(detail.mvsGap.total_connection_cost_gbp)}</span>
                      </div>
                      <div style={ST.row}>
                        <span style={ST.rowLabel}>Ofgem allowance (MVS)</span>
                        <span style={{ ...ST.rowValue, color: C.green }}>
                          {formatGbp(detail.mvsGap.mvs_gbp)} ({detail.mvsGap.ofgem_allowance_pct}%)
                        </span>
                      </div>
                      <div style={ST.row}>
                        <span style={ST.rowLabel}>Customer one-off charge</span>
                        <span style={{ ...ST.rowValue, color: C.red }}>
                          {formatGbp(detail.mvsGap.customer_one_off_charge_gbp)} ({detail.mvsGap.customer_funded_pct}%)
                        </span>
                      </div>
                      <div style={ST.bar}>
                        <div style={ST.barFill(detail.mvsGap.ofgem_allowance_pct, C.green)} />
                      </div>
                      {detail.mvsGap.line_items?.length > 0 && (
                        <div style={{ marginTop: 8 }}>
                          <div style={{ fontSize: 10, color: C.textMuted, marginBottom: 4 }}>Above-MVS line items</div>
                          {detail.mvsGap.line_items.map((li, i) => (
                            <div key={i} style={ST.row}>
                              <span style={ST.rowLabel}>{li.item}</span>
                              <span style={ST.rowValue}>{formatGbp(li.cost_gbp)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* MSIP */}
                  {detail.msip && (
                    <div style={{ ...ST.panel, marginBottom: 14 }}>
                      <div style={ST.panelTitle}>MSIP re-opener eligibility</div>
                      <div style={{
                        padding: "8px 10px", borderRadius: 8, marginBottom: 10,
                        background: detail.msip.eligible ? "#dcfce7" : "#fee2e2",
                        color: detail.msip.eligible ? "#166534" : "#991b1b",
                        fontSize: 12, fontWeight: 700,
                      }}>
                        {detail.msip.eligible ? "ELIGIBLE" : "NOT ELIGIBLE"}
                      </div>
                      {detail.msip.warnings?.map((w, i) => (
                        <div key={i} style={{ fontSize: 11, color: C.amber, marginBottom: 6 }}>⚠ {w}</div>
                      ))}
                      {detail.msip.notes?.map((n, i) => (
                        <div key={i} style={{ fontSize: 11, color: C.textDim, marginBottom: 4 }}>• {n}</div>
                      ))}
                      {detail.msip.next_steps?.length > 0 && (
                        <div style={{ marginTop: 8 }}>
                          <div style={{ fontSize: 10, color: C.textMuted, marginBottom: 4 }}>Next steps</div>
                          {detail.msip.next_steps.map((s, i) => (
                            <div key={i} style={{ fontSize: 11, marginBottom: 3 }}>→ {s}</div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* SQSS */}
                  {detail.sqss && (
                    <div style={{ ...ST.panel, marginBottom: 14 }}>
                      <div style={ST.panelTitle}>SQSS compliance</div>
                      <div style={{
                        padding: "8px 10px", borderRadius: 8, marginBottom: 10,
                        background: detail.sqss.overall === "PASS" ? "#dcfce7" : "#fee2e2",
                        color: detail.sqss.overall === "PASS" ? "#166534" : "#991b1b",
                        fontSize: 12, fontWeight: 700, letterSpacing: 0.5,
                      }}>
                        {detail.sqss.overall}
                      </div>
                      {detail.sqss.clauses?.map(c => (
                        <div key={c.clause_id} style={ST.row}>
                          <span style={{ ...ST.rowLabel, fontSize: 10 }}>
                            {c.clause_id.split("_").slice(0, 3).join("_")}
                          </span>
                          <span style={{
                            ...ST.rowValue,
                            color: c.status === "pass" ? C.green : C.red,
                            fontSize: 10,
                          }}>{c.status}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* BOM summary */}
                  {detail.bom && (
                    <div style={ST.panel}>
                      <div style={ST.panelTitle}>Connection BOM (Ofgem-format)</div>
                      {detail.bom.bom?.slice(0, 8).map((item, i) => (
                        <div key={i} style={ST.row}>
                          <span style={{ ...ST.rowLabel, fontSize: 11 }}>
                            {item.asset_class} · {item.quantity}×
                          </span>
                          <span style={ST.rowValue}>{formatGbp(item.total_gbp)}</span>
                        </div>
                      ))}
                      <div style={{ ...ST.row, marginTop: 6, borderTop: `1px solid ${C.text}`, paddingTop: 8 }}>
                        <span style={{ ...ST.rowLabel, fontWeight: 700, color: C.text }}>Total direct</span>
                        <span style={ST.rowValue}>{formatGbp(detail.bom.total_direct_gbp)}</span>
                      </div>
                      <div style={ST.row}>
                        <span style={ST.rowLabel}>Contingency (18%)</span>
                        <span style={ST.rowValue}>{formatGbp(detail.bom.contingency_gbp)}</span>
                      </div>
                      <div style={{ ...ST.row, fontWeight: 700, color: C.text }}>
                        <span>Total w/ contingency</span>
                        <span style={ST.rowValue}>{formatGbp(detail.bom.total_with_contingency_gbp)}</span>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
