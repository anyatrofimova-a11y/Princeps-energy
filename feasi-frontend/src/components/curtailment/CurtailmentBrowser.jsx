/**
 * CurtailmentBrowser — the Quantail-inspired analytical browser.
 *
 * Light theme (deliberately distinct from Pulse which is dark).
 * Single-project focus: pick a project, see its curtailment risk with
 * financial translation (revenue Δ / IRR Δ / NPV Δ), heatmap, binding
 * constraints, queue rank, scenario compare, challenge verdict.
 */
import React, { useEffect, useMemo, useState, useCallback } from "react";
import api from "../../services/api";
import { useSite } from "../../SiteContext";

const C = {
  bg:        "#f7f8fa",
  card:      "#ffffff",
  border:    "#e5e7eb",
  text:      "#0f172a",
  textDim:   "#64748b",
  textMuted: "#94a3b8",
  accent:    "#f5b731",
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
  header: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    marginBottom: 22,
  },
  title: { fontSize: 22, fontWeight: 800, margin: 0, letterSpacing: -0.3 },
  subtitle: { fontSize: 12, color: C.textDim, marginTop: 4 },
  projectPicker: {
    background: C.card,
    border: `1px solid ${C.border}`,
    borderRadius: 10,
    padding: "8px 14px 8px 12px",
    fontSize: 13,
    fontWeight: 600,
    minWidth: 260,
    color: C.text,
    cursor: "pointer",
  },
  headlineGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(4, 1fr)",
    gap: 14,
    marginBottom: 18,
  },
  headlineCard: (accent) => ({
    background: C.card,
    border: `1px solid ${C.border}`,
    borderLeft: `3px solid ${accent}`,
    borderRadius: 12,
    padding: "16px 20px",
    boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
  }),
  headlineValue: {
    fontSize: 30,
    fontWeight: 800,
    color: C.text,
    fontFamily: "'JetBrains Mono', monospace",
    letterSpacing: -0.5,
  },
  headlineLabel: {
    fontSize: 11,
    color: C.textDim,
    marginTop: 6,
    textTransform: "uppercase",
    letterSpacing: 0.6,
    fontWeight: 600,
  },
  headlineSub: { fontSize: 10, color: C.textMuted, marginTop: 2 },
  grid: {
    display: "grid",
    gridTemplateColumns: "2fr 1fr",
    gap: 18,
    marginBottom: 18,
  },
  panel: {
    background: C.card,
    border: `1px solid ${C.border}`,
    borderRadius: 12,
    padding: 18,
    boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
  },
  panelTitle: {
    fontSize: 12,
    fontWeight: 700,
    color: C.textDim,
    textTransform: "uppercase",
    letterSpacing: 0.6,
    marginBottom: 14,
  },
  verdict: (colour) => ({
    background: `${colour}0e`,
    border: `1px solid ${colour}33`,
    borderLeft: `4px solid ${colour}`,
    borderRadius: 12,
    padding: "16px 20px",
    marginBottom: 18,
    display: "flex",
    alignItems: "center",
    gap: 14,
  }),
  verdictBadge: (colour) => ({
    background: colour,
    color: "#fff",
    padding: "6px 14px",
    borderRadius: 14,
    fontSize: 11,
    fontWeight: 800,
    letterSpacing: 0.8,
  }),
  scenarioRow: {
    display: "flex",
    gap: 8,
    flexWrap: "wrap",
    marginBottom: 16,
  },
  scenarioPill: (active) => ({
    padding: "7px 14px",
    fontSize: 11,
    fontWeight: 600,
    background: active ? C.text : C.card,
    color: active ? "#fff" : C.text,
    border: `1px solid ${active ? C.text : C.border}`,
    borderRadius: 18,
    cursor: "pointer",
    transition: "all 0.15s",
  }),
  row: {
    display: "flex",
    justifyContent: "space-between",
    padding: "9px 0",
    borderBottom: `1px dashed ${C.border}`,
    fontSize: 12,
  },
  rowLabel: { color: C.textDim },
  rowValue: { fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, color: C.text },
  empty: { padding: 40, textAlign: "center", color: C.textDim, fontSize: 13 },
};


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

function formatPct(v, decimals = 1) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(decimals)}%`;
}


export default function CurtailmentBrowser() {
  const { pickedLocation } = useSite();
  const [projects, setProjects] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [scenarios, setScenarios] = useState([]);
  const [scenario, setScenario] = useState("base");

  // Load projects + scenarios once
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [ps, scs] = await Promise.allSettled([
          api.projects.list({ limit: 200 }),
          api.curtailment.scenarios(),
        ]);
        if (cancelled) return;
        if (ps.status === "fulfilled" && Array.isArray(ps.value)) {
          setProjects(ps.value);
          if (ps.value.length && !selectedId) setSelectedId(ps.value[0].project_id);
        }
        if (scs.status === "fulfilled" && Array.isArray(scs.value)) setScenarios(scs.value);
      } catch (e) {
        console.warn("[CurtailmentBrowser] load failed:", e);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Fetch analysis when project/scenario changes
  const selected = projects.find(p => p.project_id === selectedId);
  useEffect(() => {
    if (!selected) return;
    if (selected.lat == null || selected.lon == null) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const res = await api.curtailment.analyse({
          lat: selected.lat,
          lon: selected.lon,
          capacity_mw: selected.capacity_mw || 50,
          technology: selected.technology || "solar",
          project_id: String(selected.project_id),
          scenario,
        });
        if (!cancelled) setAnalysis(res);
      } catch (e) {
        console.warn("[CurtailmentBrowser] analyse failed:", e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [selected, scenario]);

  const hasData = analysis != null;

  return (
    <div style={ST.page}>
      <div style={ST.inner}>
        {/* Header */}
        <div style={ST.header}>
          <div>
            <h1 style={ST.title}>Curtailment Browser</h1>
            <div style={ST.subtitle}>
              Real-time curtailment modelling anchored to empirical headroom and sensitivity factors.
              Translated into revenue / IRR / NPV impact.
            </div>
          </div>
          <select
            style={ST.projectPicker}
            value={selectedId || ""}
            onChange={(e) => setSelectedId(e.target.value)}
          >
            {projects.length === 0 && <option value="">No projects in portfolio</option>}
            {projects.map(p => (
              <option key={p.project_id} value={p.project_id}>
                {p.name} · {p.technology || "—"} · {p.capacity_mw || "—"} MW
              </option>
            ))}
          </select>
        </div>

        {/* Scenario picker */}
        {scenarios.length > 0 && (
          <div style={ST.scenarioRow}>
            {scenarios.map(s => (
              <button
                key={s.scenario_id}
                style={ST.scenarioPill(s.scenario_id === scenario)}
                onClick={() => setScenario(s.scenario_id)}
              >
                {s.name}
              </button>
            ))}
          </div>
        )}

        {!hasData && !loading && (
          <div style={ST.empty}>
            Pick a project above to run a curtailment analysis.
          </div>
        )}

        {loading && (
          <div style={ST.empty}>Running analysis…</div>
        )}

        {hasData && (
          <>
            {/* Challenge verdict */}
            <div style={ST.verdict(analysis.challenge_verdict_colour)}>
              <div style={ST.verdictBadge(analysis.challenge_verdict_colour)}>
                {analysis.challenge_verdict.replace("_", " ")}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 16, fontWeight: 700 }}>
                  {analysis.challenge_verdict_text}
                </div>
                <div style={{ fontSize: 11, color: C.textDim, marginTop: 2 }}>
                  {selected?.name} · {scenario} scenario · {analysis.binding_constraints?.length || 0} binding constraints
                </div>
              </div>
            </div>

            {/* 4 headline tiles */}
            <div style={ST.headlineGrid}>
              <div style={ST.headlineCard(analysis.challenge_verdict_colour)}>
                <div style={ST.headlineValue}>{analysis.curtailment_pct}%</div>
                <div style={ST.headlineLabel}>Curtailment</div>
                <div style={ST.headlineSub}>{analysis.curtailed_mwh?.toLocaleString()} MWh/yr curtailed</div>
              </div>
              <div style={ST.headlineCard(C.blue)}>
                <div style={ST.headlineValue}>{formatGbp(analysis.revenue_delta_gbp)}</div>
                <div style={ST.headlineLabel}>Revenue Δ (annual)</div>
                <div style={ST.headlineSub}>@ £{analysis.price_assumption_gbp_mwh}/MWh assumption</div>
              </div>
              <div style={ST.headlineCard(C.purple)}>
                <div style={ST.headlineValue}>{formatPct(analysis.irr_delta_pct)}</div>
                <div style={ST.headlineLabel}>IRR Δ</div>
                <div style={ST.headlineSub}>vs unconstrained baseline</div>
              </div>
              <div style={ST.headlineCard(C.amber)}>
                <div style={ST.headlineValue}>{formatGbp(analysis.npv_delta_gbp)}</div>
                <div style={ST.headlineLabel}>NPV Impact</div>
                <div style={ST.headlineSub}>25y project life, 8% discount</div>
              </div>
            </div>

            {/* Heatmap + constraints */}
            <div style={ST.grid}>
              <div style={ST.panel}>
                <div style={ST.panelTitle}>Curtailment heatmap · 24h × 30d</div>
                <Heatmap data={analysis.heatmap} />
                <div style={{ fontSize: 10, color: C.textMuted, marginTop: 10, display: "flex", justifyContent: "space-between" }}>
                  <span>← darker = more curtailment</span>
                  <span>max hourly: {Math.round((Math.max(...analysis.heatmap.flat()) || 0) * 100)}%</span>
                </div>
              </div>

              <div style={ST.panel}>
                <div style={ST.panelTitle}>Binding constraints</div>
                {(analysis.binding_constraints || []).slice(0, 8).map((c, i) => (
                  <div key={i} style={ST.row}>
                    <span style={ST.rowLabel}>{(c.name || c.constraint_group || "").substring(0, 22)}</span>
                    <span style={ST.rowValue}>
                      <span style={{ color: C.textDim, fontSize: 10 }}>×</span>{c.factor}
                    </span>
                  </div>
                ))}
                {(!analysis.binding_constraints || analysis.binding_constraints.length === 0) && (
                  <div style={{ fontSize: 11, color: C.textMuted }}>No binding constraints detected</div>
                )}
              </div>
            </div>

            {/* Bottom row: queue rank + metrics */}
            <div style={ST.grid}>
              <div style={ST.panel}>
                <div style={ST.panelTitle}>Queue position (LIFO)</div>
                {analysis.queue_rank?.rank != null ? (
                  <>
                    <div style={{ fontSize: 26, fontWeight: 800, fontFamily: "'JetBrains Mono', monospace" }}>
                      #{analysis.queue_rank.rank} <span style={{ fontSize: 14, color: C.textDim, fontWeight: 500 }}>of {analysis.queue_rank.queue_size}</span>
                    </div>
                    <div style={{ fontSize: 11, color: C.textDim, marginTop: 4 }}>
                      Lower = earlier in queue = curtailed first under LIFO ordering
                    </div>
                  </>
                ) : (
                  <div style={{ fontSize: 11, color: C.textMuted }}>
                    No cluster dependency found for this project. Run cluster ingest to populate queue rank.
                  </div>
                )}
              </div>

              <div style={ST.panel}>
                <div style={ST.panelTitle}>Model inputs</div>
                <div style={ST.row}>
                  <span style={ST.rowLabel}>Capacity</span>
                  <span style={ST.rowValue}>{analysis.capacity_mw} MW</span>
                </div>
                <div style={ST.row}>
                  <span style={ST.rowLabel}>Technology</span>
                  <span style={ST.rowValue}>{analysis.technology}</span>
                </div>
                <div style={ST.row}>
                  <span style={ST.rowLabel}>Annual baseline</span>
                  <span style={ST.rowValue}>{analysis.annual_mwh_baseline?.toLocaleString()} MWh</span>
                </div>
                <div style={ST.row}>
                  <span style={ST.rowLabel}>Scenario</span>
                  <span style={ST.rowValue}>{analysis.scenario}</span>
                </div>
                <div style={ST.row}>
                  <span style={ST.rowLabel}>Historical actions used</span>
                  <span style={ST.rowValue}>{analysis.historical_actions_used}</span>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}


function Heatmap({ data }) {
  if (!data || !data.length) return null;
  const rows = data.length;
  const cols = data[0].length;
  const cellW = 12, cellH = 10;
  const w = cols * cellW + 40;
  const h = rows * cellH + 30;

  const colour = (v) => {
    if (v <= 0.02) return "#f1f5f9";
    if (v <= 0.05) return "#fde68a";
    if (v <= 0.10) return "#fbbf24";
    if (v <= 0.20) return "#f59e0b";
    if (v <= 0.35) return "#ea580c";
    return "#b91c1c";
  };

  return (
    <svg width={w} height={h} style={{ display: "block", maxWidth: "100%" }}>
      {data.map((row, y) => row.map((v, x) => (
        <rect
          key={`${x}-${y}`}
          x={30 + x * cellW}
          y={y * cellH}
          width={cellW - 1}
          height={cellH - 1}
          fill={colour(v)}
          rx={1}
        >
          <title>{`Day ${y + 1}, Hour ${x}: ${(v * 100).toFixed(1)}%`}</title>
        </rect>
      )))}
      {[0, 6, 12, 18, 23].map(x => (
        <text
          key={x}
          x={30 + x * cellW + cellW / 2}
          y={rows * cellH + 16}
          fontSize={9}
          fill="#64748b"
          textAnchor="middle"
        >{String(x).padStart(2, "0")}</text>
      ))}
      {[0, 7, 14, 21, 28].map(y => (
        <text
          key={y}
          x={22}
          y={y * cellH + 9}
          fontSize={9}
          fill="#64748b"
          textAnchor="end"
        >D{y + 1}</text>
      ))}
    </svg>
  );
}
