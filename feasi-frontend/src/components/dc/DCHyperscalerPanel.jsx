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


/** Coloured pill used inside the dockets. */
function Pill({ label, tone = "neutral" }) {
  const tones = {
    go:       { bg: "#dcfce7", fg: "#166534" },
    caution:  { bg: "#fef3c7", fg: "#92400e" },
    blocker:  { bg: "#fee2e2", fg: "#991b1b" },
    info:     { bg: "#dbeafe", fg: "#1e40af" },
    neutral:  { bg: "#f1f5f9", fg: "#334155" },
  };
  const t = tones[tone] || tones.neutral;
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 10, background: t.bg, color: t.fg,
      fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5,
    }}>{label}</span>
  );
}

/** Three-card strip: Planning approval prediction · Comparable nearby
 *  consents · Regulatory + Gate 2 readiness. Renders skeletons while
 *  loading and graceful empty states when an endpoint returns nothing. */
function DocketStrip({ dockets, tech, mw, targetEnergisation }) {
  const { planning, comparables, regulatory, gateReadiness, loading } = dockets;

  // Planning: hand-pick the 1-2 numbers we trust. Backend predict_approval
  // returns probability + key drivers in shifting shapes across versions, so
  // be defensive.
  const planProb = planning?.approval_probability ?? planning?.probability
                ?? planning?.predicted_probability ?? null;
  const planConf = planning?.confidence ?? null;
  const planDrivers = planning?.key_drivers || planning?.drivers || [];
  const planTone = planProb == null ? "neutral"
                  : planProb >= 0.7 ? "go"
                  : planProb >= 0.45 ? "caution" : "blocker";

  const compRows = (comparables?.projects || comparables?.results || comparables || []).slice(0, 4);

  // Regulatory: collapse whatever the endpoint returns into a flat list of
  // (title, status, date) triples so the UI doesn't break on schema drift.
  const regItems = (() => {
    const r = regulatory || {};
    if (Array.isArray(r.items)) return r.items.slice(0, 5);
    if (Array.isArray(r.regulatory_items)) return r.regulatory_items.slice(0, 5);
    if (Array.isArray(r.consultations)) return r.consultations.slice(0, 5);
    // Synthesise a minimal docket from named scalar fields when present
    const synth = [];
    if (r.eu_eed_compliant != null) synth.push({ title: "EU EED Article 12 reporting", status: r.eu_eed_compliant ? "compliant" : "action_required" });
    if (r.tnuos_zone) synth.push({ title: `TNUoS zone ${r.tnuos_zone}`, status: "info" });
    if (r.bng_required != null) synth.push({ title: "BNG 10% net gain", status: r.bng_required ? "required" : "n/a" });
    if (r.epn5_thermal_limit_mw != null) synth.push({ title: `EPN-5 thermal limit ${r.epn5_thermal_limit_mw} MW`, status: "info" });
    return synth;
  })();

  // Gate 2 readiness: backend returns a checklist with go/caution/blocker.
  const gateItems = (() => {
    const g = gateReadiness || {};
    if (Array.isArray(g.checklist)) return g.checklist;
    if (Array.isArray(g.items)) return g.items;
    if (g.criteria && typeof g.criteria === "object") {
      return Object.entries(g.criteria).map(([k, v]) => ({
        title: k.replace(/_/g, " "),
        status: v?.status || (v === true ? "go" : v === false ? "blocker" : "caution"),
        note: v?.note,
      }));
    }
    return [];
  })();
  const gateScore = gateReadiness?.readiness_score ?? gateReadiness?.score ?? null;

  const gridStyle = {
    display: "grid",
    gridTemplateColumns: "1fr 1fr 1fr",
    gap: 14, marginBottom: 18,
  };
  const card = {
    background: "#ffffff",
    border: `1px solid #e5e7eb`,
    borderRadius: 12,
    padding: 16,
    minHeight: 180,
  };
  const title = {
    fontSize: 11, fontWeight: 700, color: "#64748b",
    textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 10,
    display: "flex", alignItems: "center", justifyContent: "space-between",
  };
  const headline = { fontSize: 22, fontWeight: 800, color: "#0f172a", lineHeight: 1, fontFamily: "'JetBrains Mono', monospace" };
  const sub = { fontSize: 11, color: "#64748b", marginTop: 4 };
  const row = { display: "flex", justifyContent: "space-between", padding: "6px 0", fontSize: 11, borderTop: "1px solid #f1f5f9" };
  const empty = { fontSize: 11, color: "#94a3b8", fontStyle: "italic" };

  return (
    <div style={gridStyle}>
      {/* Planning approval prediction */}
      <div style={card}>
        <div style={title}>
          <span>Planning · {tech.replace(/_/g, " ")}</span>
          <Pill label={planTone === "neutral" ? "—" : planTone} tone={planTone} />
        </div>
        <div style={headline}>
          {planProb == null ? "—" : `${Math.round(planProb * 100)}%`}
        </div>
        <div style={sub}>
          {loading ? "Loading REPD ML prediction…"
            : planProb == null ? "No prediction available for this site"
            : `Approval probability${planConf != null ? ` · confidence ${Math.round(planConf * 100)}%` : ""}`}
        </div>
        {planDrivers.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <div style={{ ...sub, marginBottom: 4, fontWeight: 700 }}>Drivers</div>
            {planDrivers.slice(0, 3).map((d, i) => (
              <div key={i} style={row}>
                <span>{typeof d === "string" ? d : d.name || d.feature}</span>
                <span style={{ color: "#475569" }}>
                  {typeof d === "object" ? (d.impact || d.value || "") : ""}
                </span>
              </div>
            ))}
          </div>
        )}
        <div style={{ marginTop: 10 }}>
          <div style={{ ...sub, marginBottom: 4, fontWeight: 700 }}>Comparable nearby</div>
          {compRows.length === 0 ? (
            <div style={empty}>{loading ? "…" : "No comparables within 20 km"}</div>
          ) : compRows.map((c, i) => (
            <div key={i} style={row}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 200 }}>
                {c.name || c.site_name || c.project || "—"}
              </span>
              <span style={{ color: c.decision === "Approved" ? "#166534" : c.decision === "Refused" ? "#991b1b" : "#475569" }}>
                {c.decision || c.status || c.outcome || "—"}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Regulatory dockets */}
      <div style={card}>
        <div style={title}>
          <span>Regulatory · live dockets</span>
          <Pill label="2026" tone="info" />
        </div>
        {regItems.length === 0 ? (
          <div style={empty}>
            {loading ? "Loading regulatory snapshot…" :
              "No active dockets returned for this site/capacity"}
          </div>
        ) : regItems.map((r, i) => {
          const status = (r.status || r.state || "").toLowerCase();
          const tone = /comply|compliant|met|approved|complete/.test(status) ? "go"
                     : /pending|review|consult|action/.test(status) ? "caution"
                     : /block|fail|breach|reject/.test(status) ? "blocker"
                     : "info";
          return (
            <div key={i} style={{ ...row, alignItems: "center" }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 220 }}>
                {r.title || r.name || r.docket || "—"}
              </span>
              <Pill label={r.status || r.state || "info"} tone={tone} />
            </div>
          );
        })}
        <div style={{ ...sub, marginTop: 10, fontStyle: "italic" }}>
          Sources: Ofgem RIIO-T3, NESO TMO4+, EU EED Art.12, DEFRA BNG, Town &amp; Country Planning (EIA) Regs.
        </div>
      </div>

      {/* Gate 2 readiness */}
      <div style={card}>
        <div style={title}>
          <span>Gate 2 readiness · {targetEnergisation}</span>
          <Pill
            label={gateScore == null ? "—" : `${Math.round((gateScore <= 1 ? gateScore * 100 : gateScore))}%`}
            tone={gateScore == null ? "neutral"
                  : (gateScore <= 1 ? gateScore : gateScore / 100) >= 0.7 ? "go"
                  : (gateScore <= 1 ? gateScore : gateScore / 100) >= 0.4 ? "caution" : "blocker"}
          />
        </div>
        {gateItems.length === 0 ? (
          <div style={empty}>
            {loading ? "Loading Gate 2 checklist…" :
              `Capacity ${mw} MVA — checklist not returned for this configuration`}
          </div>
        ) : gateItems.slice(0, 7).map((g, i) => {
          const s = (g.status || "").toLowerCase();
          const tone = /go|met|complete|ready|compliant/.test(s) ? "go"
                     : /caution|partial|pending|action/.test(s) ? "caution"
                     : /block|missing|fail|gap/.test(s) ? "blocker"
                     : "neutral";
          return (
            <div key={i} style={{ ...row, alignItems: "center" }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 200, textTransform: "capitalize" }}>
                {g.title || g.criterion || "—"}
              </span>
              <Pill label={g.status || "—"} tone={tone} />
            </div>
          );
        })}
        <div style={{ ...sub, marginTop: 10, fontStyle: "italic" }}>
          NESO TMO4+ Gate 2 criteria: land rights, planning, MW, route to FID, PPA, licences.
        </div>
      </div>
    </div>
  );
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
    // Pre-FID context (added 2026-04-19): drives planning/regulatory/Gate 2 dockets
    target_energisation: "2030-Q1",
    parcel_area_ha: 8,
    is_greenfield: false,
    fibre_pop_km: 1.5,
    water_source: "closed_loop",   // closed_loop | evaporative | air_only
    embedded_gen_mw: 0,
    demand_profile: "24x7",        // 24x7 | interruptible | flexible
    anm_acceptable: false,
    planning_zone_flags: [],       // greenbelt | aonb | sssi | flood_z3 | conservation
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
  // Planning + regulatory + Gate 2 dockets (added 2026-04-19)
  const [dockets, setDockets] = useState({
    planning: null,
    comparables: null,
    regulatory: null,
    gateReadiness: null,
    loading: false,
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
            has_dual_feed: (opt.has_dual_feed ?? opt.dual_feed ?? false),
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
            has_dual_feed: (opt.has_dual_feed ?? opt.dual_feed ?? false),
          }),
          api.dcHyperscaler.connectionBom({
            capacity_mva: Number(params.capacity_mva),
            voltage_kv: opt.voltage_kv,
            has_dual_feed: (opt.has_dual_feed ?? opt.dual_feed ?? false),
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

  // Planning + regulatory + Gate 2 dockets — refresh on coords/capacity change
  // and once after every optioneering run so the dockets reflect the case the
  // user is actually optioning.
  useEffect(() => {
    let cancelled = false;
    setDockets(d => ({ ...d, loading: true }));
    const lat = Number(params.lat);
    const lon = Number(params.lon);
    const mw = Number(params.capacity_mva);  // MVA ≈ MW at PF≈1 for first-pass
    (async () => {
      const safe = async (p) => { try { return await p; } catch { return null; } };
      const [planning, comparables, regulatory, gate] = await Promise.all([
        safe(api.planning.predictApproval(lat, lon, mw, "data_centre")),
        safe(api.planning.comparableProjects(lat, lon, mw, "data_centre", 5)),
        safe(api.dc.regulatory(lat, lon, mw)),
        safe(api.grid.gateReadiness(lat, lon, mw, "data_centre", {
          target_energisation: params.target_energisation,
          land_rights: false,
          planning_status: params.is_greenfield ? "pre-app" : "consented_use",
          ppa_status: "term_sheet",
          parcel_area_ha: Number(params.parcel_area_ha) || null,
        })),
      ]);
      if (cancelled) return;
      setDockets({ planning, comparables, regulatory, gateReadiness: gate, loading: false });
    })();
    return () => { cancelled = true; };
  }, [params.lat, params.lon, params.capacity_mva, params.target_energisation,
      params.parcel_area_ha, params.is_greenfield, result]);

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
            <div style={ST.label}>Target energisation</div>
            <select style={ST.input} value={params.target_energisation} onChange={update("target_energisation")}>
              <option value="2027-Q4">2027 Q4</option>
              <option value="2028-Q4">2028 Q4</option>
              <option value="2029-Q2">2029 Q2</option>
              <option value="2030-Q1">2030 Q1</option>
              <option value="2031-Q1">2031 Q1</option>
              <option value="2032-Q1">2032+ </option>
            </select>
          </div>
          <div>
            <div style={ST.label}>Parcel area (ha)</div>
            <input style={ST.input} value={params.parcel_area_ha} onChange={update("parcel_area_ha")} type="number" step="0.5" />
          </div>
          <div>
            <div style={ST.label}>Fibre POP (km)</div>
            <input style={ST.input} value={params.fibre_pop_km} onChange={update("fibre_pop_km")} type="number" step="0.1" />
          </div>
          <div>
            <div style={ST.label}>Cooling water</div>
            <select style={ST.input} value={params.water_source} onChange={update("water_source")}>
              <option value="closed_loop">Closed-loop (low water)</option>
              <option value="evaporative">Evaporative tower</option>
              <option value="air_only">Air-only / dry</option>
            </select>
          </div>
          <div>
            <div style={ST.label}>Demand profile</div>
            <select style={ST.input} value={params.demand_profile} onChange={update("demand_profile")}>
              <option value="24x7">24×7 firm</option>
              <option value="flexible">Flexible (DSR)</option>
              <option value="interruptible">Interruptible</option>
            </select>
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
            <label style={ST.checkbox}>
              <input type="checkbox" checked={params.is_greenfield} onChange={update("is_greenfield")} />
              Greenfield
            </label>
            <label style={ST.checkbox}>
              <input type="checkbox" checked={params.anm_acceptable} onChange={update("anm_acceptable")} />
              ANM / Flex connection OK
            </label>
          </div>
          <button style={ST.runButton} onClick={run} disabled={loading}>
            {loading ? "Running…" : "Run optioneering"}
          </button>
        </div>

        {/* Planning + Regulatory + Gate 2 dockets — ambient context that
            updates as the user changes coords, capacity or energisation date.
            Sits ABOVE results so it informs option selection, not the other
            way round. */}
        <DocketStrip
          dockets={dockets}
          tech="data_centre"
          mw={params.capacity_mva}
          targetEnergisation={params.target_energisation}
        />

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
