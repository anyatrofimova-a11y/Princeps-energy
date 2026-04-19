import React, { useMemo, useState, lazy, Suspense } from "react";
import COAMatrix from "../COAMatrix";
import { WhenWorkload } from "../../lib/workload";

const FinancialModelPanel = lazy(() => import("../FinancialModelPanel"));

/**
 * DecideTab — courses-of-action comparison for a project.
 *
 * Renders a COA matrix of capacity / configuration permutations against the
 * key financial + grid + planning criteria. Selecting a row reveals the
 * scenario detail panel (stub for now) plus a lazy-loaded financial model.
 */
export default function DecideTab({ project }) {
  const baseCapacity = Number(project?.capacity_mw) || 50;
  const workload = (project?.workload_type || "solar").toString().toUpperCase();
  const projectName = project?.name || "Project";

  const scenarios = useMemo(() => buildScenarios(projectName, workload, baseCapacity), [projectName, workload, baseCapacity]);
  const [selectedId, setSelectedId] = useState(scenarios[0]?.id || null);

  const columns = [
    { key: "capacity", label: "Capacity" },
    { key: "lcoe", label: "LCOE" },
    { key: "irr", label: "IRR" },
    { key: "grid_cost", label: "Grid cost" },
    { key: "planning_risk", label: "Planning" },
    { key: "capex", label: "Capex" },
  ];

  const selected = scenarios.find((s) => s.id === selectedId) || null;

  return (
    <div className="dc-tab">
      <header className="dc-head">
        <div className="dc-eyebrow">Decide</div>
        <h2 className="dc-title">Compare scenarios</h2>
        <p className="dc-lede">
          Side-by-side comparison of capacity and configuration permutations against
          the financial, grid, and planning criteria your IC will ask about.
          Click a scenario to drill into its breakdown.
        </p>
      </header>

      <section className="dc-section">
        <COAMatrix
          rows={scenarios}
          columns={columns}
          onRowClick={setSelectedId}
          selectedRowId={selectedId}
        />
      </section>

      <section className="dc-section">
        <div className="dc-subhead">
          <div className="dc-eyebrow">Selected scenario</div>
          <h3 className="dc-subtitle">{selected ? selected.label : "No scenario selected"}</h3>
        </div>
        <div className="dc-stub">
          {selected
            ? "Click a scenario above to see its detailed financial breakdown — full IRR waterfall, debt sizing, and curtailment-adjusted dispatch coming next sprint."
            : "Select a scenario from the matrix to see the breakdown."}
        </div>
      </section>

      <section className="dc-section">
        <div className="dc-subhead">
          <div className="dc-eyebrow">Financial model</div>
          <h3 className="dc-subtitle">Live project financials</h3>
        </div>
        <Suspense fallback={<div className="dc-loading">Loading financial model…</div>}>
          <FinancialModelPanel project={project} />
        </Suspense>
      </section>

      <section className="dc-section dc-wl-section">
        <WhenWorkload project={project} only="bess">
          <div className="dc-wl-card">
            <div className="dc-wl-eyebrow">Route to market</div>
            <div className="dc-wl-title">BESS revenue stack optimiser</div>
            <div className="dc-wl-body">
              Wires to <span className="dc-wl-mono">/api/finance/route-to-market</span>.
            </div>
          </div>
        </WhenWorkload>
        <WhenWorkload project={project} only="dc">
          <div className="dc-wl-card">
            <div className="dc-wl-eyebrow">CFE 24/7 score</div>
            <div className="dc-wl-title">Carbon-free energy match</div>
            <div className="dc-wl-body">Hourly CFE matching against grid + PPA mix — coming next sprint.</div>
          </div>
        </WhenWorkload>
        <WhenWorkload project={project} only="hybrid">
          <div className="dc-wl-card">
            <div className="dc-wl-eyebrow">Hybrid sizing</div>
            <div className="dc-wl-title">Hybrid sizing optimiser</div>
            <div className="dc-wl-body">Coming next sprint.</div>
          </div>
        </WhenWorkload>
      </section>

      <style>{`
        .dc-tab { padding: 32px 40px; max-width: 1200px; }
        .dc-head { margin-bottom: 28px; }
        .dc-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
          color: var(--cds-text-helper); margin-bottom: 8px; }
        .dc-title { font-size: 32px; font-weight: 600; color: var(--ink); margin: 0 0 12px 0;
          letter-spacing: -0.5px; }
        .dc-lede { font-size: 15px; line-height: 1.55; color: var(--cds-text-secondary);
          max-width: 640px; margin: 0; }
        .dc-section { margin-top: 32px; }
        .dc-subhead { margin-bottom: 14px; }
        .dc-subtitle { font-size: 18px; font-weight: 600; color: var(--ink);
          margin: 4px 0 0 0; letter-spacing: -0.2px; }
        .dc-stub { background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          border-radius: 10px; padding: 20px 22px; font-size: 13px;
          color: var(--cds-text-secondary); line-height: 1.55; }
        .dc-loading { padding: 18px; color: var(--cds-text-helper); font-size: 13px;
          font-family: var(--mono); }
        .dc-wl-section { display: flex; flex-direction: column; gap: 12px; }
        .dc-wl-card { background: var(--cds-layer-01); border: 1px dashed var(--cds-border-subtle);
          border-radius: 10px; padding: 20px; }
        .dc-wl-eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 1.5px;
          text-transform: uppercase; color: var(--cds-text-helper); margin-bottom: 8px; }
        .dc-wl-title { font-size: 14px; font-weight: 600; color: var(--ink); margin-bottom: 6px; }
        .dc-wl-body { font-size: 12px; color: var(--cds-text-secondary); line-height: 1.5; }
        .dc-wl-mono { font-family: var(--mono); font-size: 11px; color: var(--cds-text-secondary); }
      `}</style>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Stub scenario generator — varies capacity ±20% from project base.   */
/* Will be replaced by a backend solver in a later sprint.             */
/* ------------------------------------------------------------------ */
function buildScenarios(projectName, workload, baseMw) {
  const variants = [
    { id: "base", suffix: "Base case", multiplier: 1.0 },
    { id: "upside", suffix: "+20% capacity", multiplier: 1.2 },
    { id: "downside", suffix: "-20% capacity", multiplier: 0.8 },
  ];

  return variants.map((v) => {
    const mw = Math.round(baseMw * v.multiplier);
    // Stub econ — bigger schemes get cheaper LCOE & higher IRR up to a point,
    // but grid cost grows roughly with sqrt(capacity).
    const lcoe = Math.round(48 / Math.pow(v.multiplier, 0.35));
    const irr = (10 + (v.multiplier - 1) * 6).toFixed(1);
    const gridCostK = Math.round(480 * Math.pow(v.multiplier, 0.6));
    const capexM = (mw * 0.85).toFixed(1);
    const planningProb = Math.round(78 - Math.max(0, (v.multiplier - 1) * 30));

    return {
      id: v.id,
      label: `${projectName} — ${v.suffix}`,
      subtitle: `${workload} · ${mw} MW`,
      cells: {
        capacity: { value: `${mw} MW`, score: "neutral" },
        lcoe: { value: `£${lcoe}/MWh`, score: scoreLcoe(lcoe) },
        irr: { value: `${irr}%`, score: scoreIrr(Number(irr)) },
        grid_cost: { value: formatGbp(gridCostK), score: scoreGridCost(gridCostK) },
        planning_risk: { value: `${labelRisk(planningProb)} (${planningProb}%)`, score: scoreRisk(planningProb) },
        capex: { value: `£${capexM}M`, score: "neutral" },
      },
    };
  });
}

function scoreLcoe(v) { if (v <= 50) return "good"; if (v <= 65) return "ok"; return "bad"; }
function scoreIrr(v) { if (v >= 11) return "good"; if (v >= 9) return "ok"; return "bad"; }
function scoreGridCost(k) { if (k <= 600) return "good"; if (k <= 1000) return "ok"; return "bad"; }
function scoreRisk(p) { if (p >= 70) return "good"; if (p >= 50) return "ok"; return "bad"; }
function labelRisk(p) { if (p >= 70) return "Low"; if (p >= 50) return "Med"; return "High"; }
function formatGbp(k) { return k >= 1000 ? `£${(k / 1000).toFixed(1)}M` : `£${k}K`; }
