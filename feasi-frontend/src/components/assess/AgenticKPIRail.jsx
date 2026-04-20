import React, { useEffect, useMemo, useState } from "react";

/**
 * AgenticKPIRail — floating rail of KPI chips over the project twin.
 *
 * Pulls from (best-effort, graceful fallback):
 *   GET /api/projects/{id}/kpis           — server-side heuristic bundle
 *   GET /api/agent/kpis?project_id={id}   — BOT-GG agent bundle (if live)
 *   GET /api/analysis/headroom?lat=&lon=  — BOT-I headroom
 *   GET /api/grid/queue-depth/{sub_id}    — BOT-B queue
 *
 * Any chip that can't resolve renders "— / pending" in muted colour,
 * never an error. Includes an "Ask agent about this site" button that
 * dispatches the `princeps-chat` window event with a prefilled prompt.
 */

const CHIP_DEFS = [
  { key: "grid_viability",       label: "Grid viability",     unit: "/100", bandKey: "grid_band" },
  { key: "planning_likelihood",  label: "Planning likelihood", unit: "/100", bandKey: "planning_band" },
  { key: "buildable",            label: "Buildable",           unit: "ha",   isRatio: true },
  { key: "connection_cost_p50",  label: "Conn. cost P50",      unit: "£m" },
  { key: "queue_position",       label: "Queue ahead",         unit: "proj" },
  { key: "verdict",              label: "Verdict",             isVerdict: true },
  { key: "revenue_p50",          label: "Revenue P50",         unit: "£m/yr" },
  { key: "lcoe",                 label: "LCOE",                unit: "£/MWh" },
];

const VERDICT_STYLE = {
  "GO":      { bg: "rgba(34,139,34,0.18)",  dot: "#2E8B57" },
  "CAUTION": { bg: "rgba(201,166,75,0.22)", dot: "#C9A64B" },
  "NO-GO":   { bg: "rgba(200,50,50,0.18)",  dot: "#C83232" },
  "PENDING": { bg: "rgba(255,255,255,0.08)", dot: "#888" },
};

function bandDot(score) {
  if (score == null || Number.isNaN(+score)) return "#888";
  const n = +score;
  if (n >= 70) return "#2E8B57";
  if (n >= 40) return "#C9A64B";
  return "#C83232";
}

async function safeJson(url) {
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

/** Extract the 8 expected chip values from whichever bundles we got. */
function assembleKpis({ projectKpis, agentKpis, headroom, queue, project }) {
  const out = {};
  const pk = projectKpis || {};
  const ak = agentKpis || {};

  out.grid_viability = ak.grid_viability ?? pk.grid_viability ?? pk.grid_score ?? null;
  out.planning_likelihood = ak.planning_likelihood ?? pk.planning_likelihood ?? pk.planning_prob ?? null;

  // buildable: "X of Y ha"
  const buildableHa = ak.buildable_ha ?? pk.buildable_ha ?? headroom?.buildable_ha ?? null;
  const totalHa = pk.site_area_ha ?? project?.metadata?.area_ha ?? project?.area_ha ?? null;
  out.buildable = buildableHa != null && totalHa != null
    ? `${Number(buildableHa).toFixed(1)} / ${Number(totalHa).toFixed(0)}`
    : buildableHa != null ? `${Number(buildableHa).toFixed(1)}` : null;

  out.connection_cost_p50 = ak.connection_cost_p50_m ?? pk.connection_cost_p50_m ?? pk.cost_p50 ?? null;
  out.queue_position = ak.queue_ahead ?? queue?.queued_ahead ?? queue?.ahead_count ?? null;
  out.verdict = (ak.verdict || pk.verdict || pk.grid_verdict || null)?.toString().toUpperCase() || null;
  out.revenue_p50 = ak.revenue_p50_m_per_yr ?? pk.revenue_p50_m_per_yr ?? pk.revenue_p50 ?? null;
  out.lcoe = ak.lcoe_gbp_per_mwh ?? pk.lcoe_gbp_per_mwh ?? pk.lcoe ?? null;

  return out;
}

export default function AgenticKPIRail({ project }) {
  const pid = project?.id || project?.project_id;
  const lat = project?.lat;
  const lon = project?.lon;
  const [kpis, setKpis] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      const [projectKpis, agentKpis, headroom] = await Promise.all([
        pid ? safeJson(`/api/projects/${pid}/kpis`) : Promise.resolve(null),
        pid ? safeJson(`/api/agent/kpis?project_id=${pid}`) : Promise.resolve(null),
        lat != null && lon != null
          ? safeJson(`/api/analysis/headroom?lat=${lat}&lon=${lon}`)
          : Promise.resolve(null),
      ]);
      let queue = null;
      const subId = agentKpis?.substation_id || projectKpis?.substation_id || headroom?.substation_id;
      if (subId) {
        queue = await safeJson(`/api/grid/queue-depth/${subId}`);
      }
      if (cancelled) return;
      setKpis(assembleKpis({ projectKpis, agentKpis, headroom, queue, project }));
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [pid, lat, lon]); // eslint-disable-line react-hooks/exhaustive-deps

  const chips = useMemo(() => CHIP_DEFS.map((def) => {
    const raw = kpis?.[def.key];
    const pending = raw == null || raw === "";
    let valueText = pending ? "—" : String(raw);
    let dot = null;
    let bg = null;

    if (def.isVerdict) {
      const v = pending ? "PENDING" : raw;
      const sty = VERDICT_STYLE[v] || VERDICT_STYLE.PENDING;
      dot = sty.dot;
      bg = sty.bg;
      valueText = pending ? "pending" : raw;
    } else if (def.key === "grid_viability" || def.key === "planning_likelihood") {
      dot = pending ? "#888" : bandDot(raw);
      if (!pending) valueText = `${Math.round(Number(raw))}`;
    } else if (!pending && typeof raw === "number") {
      // cost/revenue/lcoe number formatting
      if (def.unit === "£m" || def.unit === "£m/yr") {
        valueText = raw >= 10 ? raw.toFixed(1) : raw.toFixed(2);
      } else if (def.unit === "£/MWh") {
        valueText = raw.toFixed(0);
      } else if (def.unit === "proj") {
        valueText = `${Math.round(raw)}`;
      } else {
        valueText = Number(raw).toFixed(2);
      }
    }

    return { def, valueText, pending, dot, bg };
  }), [kpis]);

  function askAgent() {
    const name = project?.name || "this site";
    const text = `Write a 1-paragraph memo on ${name}'s viability including grid, planning, and environmental.`;
    window.dispatchEvent(new CustomEvent("princeps-chat", { detail: { text } }));
  }

  return (
    <div className="akr-rail" role="region" aria-label="Agentic KPIs">
      <div className="akr-header">
        <span className="akr-eyebrow">AGENTIC KPIs</span>
        <button className="akr-ask" onClick={askAgent} title="Ask agent for a memo">
          Ask agent ↗
        </button>
      </div>
      <div className="akr-chips">
        {chips.map(({ def, valueText, pending, dot, bg }) => (
          <div
            key={def.key}
            className={"akr-chip" + (pending ? " akr-pending" : "")}
            style={bg ? { background: bg } : undefined}
          >
            <div className="akr-chip-label">
              {dot && <span className="akr-dot" style={{ background: dot }} />}
              {def.label}
            </div>
            <div className="akr-chip-value">
              <span className="akr-mono">{valueText}</span>
              {!pending && def.unit && !def.isVerdict && (
                <span className="akr-unit">{def.unit}</span>
              )}
              {pending && <span className="akr-unit">pending</span>}
            </div>
          </div>
        ))}
      </div>

      <style>{`
        .akr-rail {
          position: absolute;
          top: 12px;
          right: 12px;
          z-index: 5;
          background: rgba(18, 20, 24, 0.82);
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          border: 1px solid rgba(201, 166, 75, 0.28);
          border-radius: 10px;
          padding: 10px 12px;
          max-width: 280px;
          font-family: "DM Sans", -apple-system, sans-serif;
          color: rgba(255,255,255,0.92);
          box-shadow: 0 8px 28px rgba(0,0,0,0.35);
        }
        .akr-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
          gap: 8px;
        }
        .akr-eyebrow {
          font-size: 9.5px;
          font-weight: 700;
          letter-spacing: 0.12em;
          color: #C9A64B;
        }
        .akr-ask {
          background: transparent;
          border: 1px solid rgba(201, 166, 75, 0.5);
          color: #F5E9C8;
          border-radius: 4px;
          padding: 3px 8px;
          font-family: inherit;
          font-size: 10px;
          font-weight: 600;
          cursor: pointer;
          transition: all 120ms;
        }
        .akr-ask:hover {
          background: #C9A64B;
          color: #1a1a1a;
          border-color: #C9A64B;
        }
        .akr-chips {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 6px;
        }
        .akr-chip {
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 6px;
          padding: 6px 8px;
          min-width: 0;
        }
        .akr-chip.akr-pending {
          opacity: 0.55;
        }
        .akr-chip-label {
          font-size: 9.5px;
          color: rgba(255,255,255,0.6);
          letter-spacing: 0.03em;
          text-transform: uppercase;
          display: flex;
          align-items: center;
          gap: 5px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .akr-dot {
          display: inline-block;
          width: 6px;
          height: 6px;
          border-radius: 50%;
          flex-shrink: 0;
        }
        .akr-chip-value {
          margin-top: 2px;
          display: flex;
          align-items: baseline;
          gap: 4px;
          white-space: nowrap;
          overflow: hidden;
        }
        .akr-mono {
          font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
          font-size: 14px;
          font-weight: 600;
          color: #F5E9C8;
        }
        .akr-unit {
          font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
          font-size: 10px;
          color: rgba(255,255,255,0.5);
        }
      `}</style>
    </div>
  );
}
