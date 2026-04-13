/**
 * GridIntelPanel — right-hand slide-in detail panel.
 *
 * Shows contextual intelligence for whatever the user clicked on the Pulse map:
 * a substation, an ECR site, a GSP, or a licence area. Fetches additional
 * detail (curtailment risk, time series) on click.
 */
import React, { useEffect, useState, useMemo } from "react";
import api from "../../services/api";

const PANEL_WIDTH = 420;

const ST = {
  panel: {
    position: "absolute",
    top: 60,
    right: 20,
    bottom: 20,
    width: PANEL_WIDTH,
    background: "#ffffff",
    borderRadius: 14,
    boxShadow: "0 24px 60px rgba(15, 23, 42, 0.22), 0 2px 8px rgba(15, 23, 42, 0.08)",
    border: "1px solid rgba(15,23,42,0.08)",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    zIndex: 30,
    fontFamily: "'DM Sans', 'Inter', system-ui, sans-serif",
  },
  header: {
    padding: "14px 18px 12px",
    borderBottom: "1px solid #e6e8eb",
    display: "flex",
    alignItems: "center",
    gap: 10,
  },
  kindPill: (colour) => ({
    padding: "3px 10px",
    borderRadius: 12,
    fontSize: 10,
    fontWeight: 700,
    background: colour,
    color: "#fff",
    letterSpacing: 0.4,
    textTransform: "uppercase",
  }),
  title: { flex: 1, fontSize: 15, fontWeight: 700, color: "#0f172a", lineHeight: 1.25 },
  close: {
    width: 26, height: 26, borderRadius: 13, border: "none",
    background: "#f1f5f9", color: "#475569", cursor: "pointer",
    fontSize: 16, lineHeight: 1, fontWeight: 600,
  },
  body: { flex: 1, overflowY: "auto", padding: "16px 18px 24px" },
  section: { marginBottom: 18 },
  sectionLabel: {
    fontSize: 10, fontWeight: 700, color: "#64748b",
    letterSpacing: 0.7, textTransform: "uppercase", marginBottom: 6,
  },
  row: {
    display: "flex", justifyContent: "space-between",
    padding: "6px 0", borderBottom: "1px dashed #e2e8f0",
    fontSize: 12, color: "#0f172a",
  },
  rowLabel: { color: "#64748b" },
  rowValue: { fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 },
  headlineGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 14 },
  headlineCard: (accent) => ({
    background: "#f8fafc",
    border: `1px solid ${accent}22`,
    borderLeft: `3px solid ${accent}`,
    borderRadius: 8,
    padding: "10px 12px",
  }),
  headlineValue: { fontSize: 18, fontWeight: 800, color: "#0f172a", fontFamily: "'JetBrains Mono', monospace" },
  headlineLabel: { fontSize: 10, color: "#64748b", marginTop: 2, textTransform: "uppercase", letterSpacing: 0.5 },
  verdict: (colour) => ({
    padding: "14px 16px",
    borderRadius: 10,
    background: `${colour}11`,
    border: `1px solid ${colour}44`,
    borderLeft: `4px solid ${colour}`,
    marginBottom: 14,
  }),
  verdictText: (colour) => ({ fontSize: 13, fontWeight: 700, color: colour }),
  verdictSub: { fontSize: 11, color: "#64748b", marginTop: 3 },
  button: {
    width: "100%",
    padding: "9px 12px",
    fontSize: 12,
    fontWeight: 700,
    background: "#0f172a",
    color: "#fff",
    border: "none",
    borderRadius: 8,
    cursor: "pointer",
    marginTop: 8,
    letterSpacing: 0.3,
  },
  sparkline: { width: "100%", height: 56, marginTop: 6 },
  loading: { padding: 24, fontSize: 12, color: "#64748b", textAlign: "center" },
};

const KIND_META = {
  substation:    { label: "Substation",   colour: "#0891b2" },
  ecr:           { label: "ECR Site",     colour: "#7c3aed" },
  gsp:           { label: "GSP",          colour: "#2563eb" },
  licence_area:  { label: "Licence Area", colour: "#059669" },
};


function formatNumber(v, suffix = "", decimals = 1) {
  if (v == null || Number.isNaN(v)) return "—";
  const n = Number(v);
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(decimals)}k${suffix}`;
  return `${n.toFixed(decimals)}${suffix}`;
}

function formatGbp(v) {
  if (v == null || Number.isNaN(v)) return "—";
  const n = Number(v);
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${sign}£${(abs / 1e9).toFixed(2)}bn`;
  if (abs >= 1e6) return `${sign}£${(abs / 1e6).toFixed(2)}m`;
  if (abs >= 1e3) return `${sign}£${(abs / 1e3).toFixed(0)}k`;
  return `${sign}£${abs.toFixed(0)}`;
}


export default function GridIntelPanel({ selection, onClose }) {
  const [timeseries, setTimeseries] = useState(null);
  const [curtailment, setCurtailment] = useState(null);
  const [loading, setLoading] = useState(false);

  const kind = selection?.kind;
  const props = selection?.feature?.properties || {};
  const meta = KIND_META[kind] || { label: "Feature", colour: "#475569" };

  // Fetch detail when selection changes
  useEffect(() => {
    setTimeseries(null);
    setCurtailment(null);
    if (!selection) return;

    let cancelled = false;
    setLoading(true);

    (async () => {
      try {
        if (kind === "gsp" && props.region && props.gsp_name) {
          const ts = await api.nged.gspTimeseries(props.region, props.gsp_name, 48);
          if (!cancelled) setTimeseries(ts);
        }

        // Curtailment estimate for any geographic feature
        if (kind === "ecr" || kind === "gsp") {
          const lat = selection.lngLat?.lat ?? props.lat;
          const lon = selection.lngLat?.lng ?? props.lon;
          const capacity = Number(props.capacity_mw || props.gsp_capacity_mw || 50);
          const tech = props.technology || "solar";
          if (lat && lon) {
            const c = await api.curtailment.analyse({
              lat, lon, capacity_mw: capacity, technology: tech,
              project_id: props.gsp_name || props.customer || null,
            });
            if (!cancelled) setCurtailment(c);
          }
        }
      } catch (e) {
        console.warn("[GridIntelPanel] detail fetch failed:", e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [selection, kind]);

  if (!selection) return null;

  const title = props.name || props.customer || props.gsp_name || meta.label;
  const subtitle =
    kind === "substation" ? `${props.dno || ""} · ${props.voltage_kv || "—"} kV`
  : kind === "ecr" ? `${props.technology || "—"} · ${props.status || "—"}`
  : kind === "gsp" ? `${props.region?.toUpperCase() || ""} · ${formatNumber(props.net_demand_mw, " MW")}`
  : kind === "licence_area" ? `${formatNumber(props.demand_mw, " MW demand")}`
  : "";

  return (
    <div style={ST.panel}>
      <div style={ST.header}>
        <span style={ST.kindPill(meta.colour)}>{meta.label}</span>
        <div style={ST.title}>{title}</div>
        <button style={ST.close} onClick={onClose} title="Close">×</button>
      </div>

      <div style={ST.body}>
        {subtitle && (
          <div style={{ fontSize: 12, color: "#64748b", marginBottom: 14 }}>{subtitle}</div>
        )}

        {/* Kind-specific headline tiles */}
        {kind === "substation" && (
          <div style={ST.headlineGrid}>
            <div style={ST.headlineCard(props.colour || "#10b981")}>
              <div style={ST.headlineValue}>{formatNumber(props.headroom_mw, " MW", 0)}</div>
              <div style={ST.headlineLabel}>{props.kind === "generation" ? "Gen headroom" : "Demand headroom"}</div>
            </div>
            <div style={ST.headlineCard("#64748b")}>
              <div style={ST.headlineValue}>{props.voltage_kv || "—"}<span style={{ fontSize: 12 }}> kV</span></div>
              <div style={ST.headlineLabel}>{props.site_type || "Substation"}</div>
            </div>
          </div>
        )}

        {kind === "ecr" && (
          <div style={ST.headlineGrid}>
            <div style={ST.headlineCard(props.colour || "#7c3aed")}>
              <div style={ST.headlineValue}>{formatNumber(props.capacity_mw, " MW", 1)}</div>
              <div style={ST.headlineLabel}>Registered capacity</div>
            </div>
            <div style={ST.headlineCard("#64748b")}>
              <div style={ST.headlineValue}>{props.voltage_kv || "—"}<span style={{ fontSize: 12 }}> kV</span></div>
              <div style={ST.headlineLabel}>{props.technology || "—"}</div>
            </div>
          </div>
        )}

        {kind === "gsp" && (
          <>
            <div style={ST.headlineGrid}>
              <div style={ST.headlineCard(props.colour || "#2563eb")}>
                <div style={ST.headlineValue}>{formatNumber(props.net_demand_mw, " MW", 0)}</div>
                <div style={ST.headlineLabel}>Net demand</div>
              </div>
              <div style={ST.headlineCard("#059669")}>
                <div style={ST.headlineValue}>{formatNumber(props.generation_mw, " MW", 0)}</div>
                <div style={ST.headlineLabel}>Generation</div>
              </div>
            </div>

            {props.utilisation != null && (
              <div style={ST.section}>
                <div style={ST.sectionLabel}>Utilisation vs capacity</div>
                <div style={{
                  height: 8, background: "#e2e8f0", borderRadius: 4, overflow: "hidden",
                  position: "relative",
                }}>
                  <div style={{
                    width: `${Math.min(100, (props.utilisation || 0) * 100)}%`,
                    height: "100%",
                    background: props.colour || "#2563eb",
                    transition: "width 0.4s ease",
                  }} />
                </div>
                <div style={{ fontSize: 10, color: "#64748b", marginTop: 4 }}>
                  {((props.utilisation || 0) * 100).toFixed(1)}% of GSP capacity
                </div>
              </div>
            )}

            {/* Fuel split */}
            <div style={ST.section}>
              <div style={ST.sectionLabel}>Fuel split (last 5 min)</div>
              <div style={ST.row}><span style={ST.rowLabel}>Solar</span><span style={ST.rowValue}>{formatNumber(props.solar_mw, " MW")}</span></div>
              <div style={ST.row}><span style={ST.rowLabel}>Wind</span><span style={ST.rowValue}>{formatNumber(props.wind_mw, " MW")}</span></div>
              <div style={ST.row}><span style={ST.rowLabel}>Storage</span><span style={ST.rowValue}>{formatNumber(props.storage_mw, " MW")}</span></div>
              <div style={ST.row}><span style={ST.rowLabel}>Other</span><span style={ST.rowValue}>{formatNumber(props.other_mw, " MW")}</span></div>
              <div style={ST.row}><span style={ST.rowLabel}>Import</span><span style={ST.rowValue}>{formatNumber(props.import_mw, " MW")}</span></div>
            </div>

            {timeseries && timeseries.length > 0 && (
              <div style={ST.section}>
                <div style={ST.sectionLabel}>48-hour flow</div>
                <Sparkline data={timeseries.map(d => d.net_demand_mw)} colour="#2563eb" />
              </div>
            )}
          </>
        )}

        {kind === "licence_area" && (
          <>
            <div style={ST.headlineGrid}>
              <div style={ST.headlineCard("#dc2626")}>
                <div style={ST.headlineValue}>{formatNumber(props.demand_mw, " MW", 0)}</div>
                <div style={ST.headlineLabel}>Demand</div>
              </div>
              <div style={ST.headlineCard("#059669")}>
                <div style={ST.headlineValue}>{formatNumber(props.generation_mw, " MW", 0)}</div>
                <div style={ST.headlineLabel}>Generation</div>
              </div>
            </div>
            <div style={ST.section}>
              <div style={ST.sectionLabel}>Renewable breakdown</div>
              <div style={ST.row}><span style={ST.rowLabel}>Solar</span><span style={ST.rowValue}>{formatNumber(props.solar_mw, " MW")}</span></div>
              <div style={ST.row}><span style={ST.rowLabel}>Wind</span><span style={ST.rowValue}>{formatNumber(props.wind_mw, " MW")}</span></div>
              <div style={ST.row}><span style={ST.rowLabel}>Storage</span><span style={ST.rowValue}>{formatNumber(props.storage_mw, " MW")}</span></div>
              <div style={ST.row}><span style={ST.rowLabel}>Other</span><span style={ST.rowValue}>{formatNumber(props.other_mw, " MW")}</span></div>
            </div>
          </>
        )}

        {/* Curtailment analysis (gsp + ecr) */}
        {curtailment && (
          <>
            <div style={ST.sectionLabel}>Curtailment risk</div>
            <div style={ST.verdict(curtailment.challenge_verdict_colour)}>
              <div style={ST.verdictText(curtailment.challenge_verdict_colour)}>
                {curtailment.challenge_verdict.replace("_", " ")} · {curtailment.curtailment_pct}%
              </div>
              <div style={ST.verdictSub}>{curtailment.challenge_verdict_text}</div>
            </div>
            <div style={ST.headlineGrid}>
              <div style={ST.headlineCard("#0891b2")}>
                <div style={ST.headlineValue}>{formatGbp(curtailment.revenue_delta_gbp)}</div>
                <div style={ST.headlineLabel}>Annual revenue Δ</div>
              </div>
              <div style={ST.headlineCard("#7c3aed")}>
                <div style={ST.headlineValue}>{curtailment.irr_delta_pct}%</div>
                <div style={ST.headlineLabel}>IRR delta</div>
              </div>
            </div>
            <div style={ST.row}>
              <span style={ST.rowLabel}>NPV impact</span>
              <span style={ST.rowValue}>{formatGbp(curtailment.npv_delta_gbp)}</span>
            </div>
            <div style={ST.row}>
              <span style={ST.rowLabel}>Curtailed MWh/yr</span>
              <span style={ST.rowValue}>{formatNumber(curtailment.curtailed_mwh, "", 0)}</span>
            </div>
            <div style={ST.row}>
              <span style={ST.rowLabel}>Binding constraints</span>
              <span style={ST.rowValue}>{curtailment.binding_constraints?.length || 0}</span>
            </div>
            <button style={ST.button} onClick={() => {
              window.dispatchEvent(new CustomEvent("princeps-open-curtailment", {
                detail: { curtailment, selection },
              }));
            }}>
              Open in Curtailment Browser →
            </button>
          </>
        )}

        {loading && <div style={ST.loading}>Loading detail…</div>}
      </div>
    </div>
  );
}


function Sparkline({ data = [], colour = "#2563eb" }) {
  if (!data.length) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 384, h = 56;
  const step = w / Math.max(1, data.length - 1);
  const pts = data.map((v, i) => {
    const x = i * step;
    const y = h - ((v - min) / range) * (h - 6) - 3;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <polyline fill="none" stroke={colour} strokeWidth="1.5" points={pts} />
      <polyline
        fill={`${colour}22`}
        stroke="none"
        points={`0,${h} ${pts} ${w},${h}`}
      />
    </svg>
  );
}
