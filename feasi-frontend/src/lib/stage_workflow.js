/**
 * stage_workflow.js — the canonical "what's the next action?" mapping for
 * every pipeline stage, plus per-stage filings schedule. Used by:
 *   - StageRibbon   (CTA card: "Your next step: …")
 *   - FilingsTimeline (which artefacts are due, locked, or complete)
 *   - MissionControl "This week" card
 *
 * Stage values mirror app/routers/projects.py VALID_STAGES.
 */

export const STAGES = [
  { key: "prospect",     label: "Prospect",     short: "PROS" },
  { key: "screened",     label: "Screened",     short: "SCRN" },
  { key: "grid_applied", label: "Grid applied", short: "GAPP" },
  { key: "grid_offer",   label: "Grid offer",   short: "GOFF" },
  { key: "planning",     label: "Planning",     short: "PLAN" },
  { key: "fid",          label: "FID",          short: "FID"  },
  { key: "construction", label: "Construction", short: "CONS" },
  { key: "energised",    label: "Energised",    short: "ENRG" },
];

export const STAGE_INDEX = STAGES.reduce((a, s, i) => ({ ...a, [s.key]: i }), {});

/** The *single* next step that advances the project from the given stage. */
export const STAGE_CTA = {
  prospect: {
    title: "Commission grid capacity study",
    rationale: "Confirm headroom at the nearest GSP before committing to design spend.",
    due_days: 14,
    action: "open-assess-grid",
  },
  screened: {
    title: "Submit DNO application (G99 / G100)",
    rationale: "Lock a queue position — DNO lead times are 6–18 months.",
    due_days: 7,
    action: "open-file",
  },
  grid_applied: {
    title: "Chase DNO for grid offer",
    rationale: "Follow up weekly; prepare connection agreement review in parallel.",
    due_days: 30,
    action: "agent-grid",
  },
  grid_offer: {
    title: "Sign acceptance letter & pay deposit",
    rationale: "30-day window — missing it forfeits the queue slot.",
    due_days: 7,
    action: "open-file",
  },
  planning: {
    title: "Submit planning application to LPA",
    rationale: "Validate screening opinion, ecology, noise, FRA before lodging.",
    due_days: 14,
    action: "open-file",
  },
  fid: {
    title: "Reach financial close",
    rationale: "Finalise debt + equity commitments, execute PPA.",
    due_days: 30,
    action: "open-decide",
  },
  construction: {
    title: "Track delivery milestones",
    rationale: "Weekly progress reports; update commissioning date.",
    due_days: 60,
    action: "open-operate",
  },
  energised: {
    title: "Begin operations",
    rationale: "Asset in service — monitor dispatch and ancillary revenue.",
    due_days: null,
    action: "open-operate",
  },
};

/**
 * Filings schedule. Each entry says which stage *unlocks* it (locked=true
 * beforehand) and which stage *requires* it (submitted/approved by then).
 * Duplicated across workloads where meaningful; the filtering to
 * workload-specific items happens in the component.
 */
export const FILINGS = [
  { code: "feasibility_memo",   name: "Feasibility memo",              unlock: "prospect",     require: "screened",     workload: "all",   doc_template: "internal/feasibility-memo.md" },
  { code: "eia_screening",      name: "EIA screening opinion",         unlock: "screened",     require: "planning",     workload: "all",   doc_template: "external/eia-screening.pdf" },
  { code: "g99_application",    name: "G99 grid connection (≤50 MW)",  unlock: "screened",     require: "grid_offer",   workload: ["bess", "solar", "hybrid"], doc_template: "external/g99-form.pdf" },
  { code: "g100_application",   name: "G100 grid connection (>50 MW)", unlock: "screened",     require: "grid_offer",   workload: ["bess", "solar", "dc"], conditional: "capacity_mw>50", doc_template: "external/g100-form.pdf" },
  { code: "ecology_survey",     name: "Ecology survey",                unlock: "screened",     require: "planning",     workload: "all",   doc_template: "external/ecology.pdf" },
  { code: "noise_assessment",   name: "Noise assessment (BS 4142)",    unlock: "screened",     require: "planning",     workload: ["bess", "dc"], doc_template: "external/noise-bs4142.pdf" },
  { code: "glint_glare",        name: "Glint & glare study",           unlock: "screened",     require: "planning",     workload: "solar", doc_template: "external/glint-glare.pdf" },
  { code: "flood_risk",         name: "Flood risk assessment",         unlock: "screened",     require: "planning",     workload: "all",   doc_template: "external/fra.pdf" },
  { code: "heritage_impact",    name: "Heritage impact assessment",    unlock: "screened",     require: "planning",     workload: "all",   doc_template: "external/heritage.pdf" },
  { code: "transport_assess",   name: "Construction transport assessment", unlock: "screened", require: "planning",     workload: "all",   doc_template: "external/transport.pdf" },
  { code: "bng_plan",           name: "BNG 10% biodiversity net gain", unlock: "screened",     require: "planning",     workload: "all",   doc_template: "external/bng-plan.pdf" },
  { code: "planning_app",       name: "Planning application (TCPA)",   unlock: "planning",     require: "fid",          workload: "all",   doc_template: "external/tcpa-application.pdf" },
  { code: "connection_agreement", name: "Grid connection agreement",   unlock: "grid_offer",   require: "fid",          workload: "all",   doc_template: "external/connection-agreement.pdf" },
  { code: "ppa_draft",          name: "PPA / route-to-market",         unlock: "planning",     require: "fid",          workload: "all",   doc_template: "internal/ppa-term-sheet.pdf" },
  { code: "cdm_plan",           name: "CDM construction plan",         unlock: "fid",          require: "construction", workload: "all",   doc_template: "external/cdm-plan.pdf" },
  { code: "commissioning_cert", name: "Commissioning certificate",     unlock: "construction", require: "energised",    workload: "all",   doc_template: "external/commissioning.pdf" },
  { code: "fat_report",         name: "Factory acceptance test",       unlock: "fid",          require: "construction", workload: "bess",  doc_template: "external/fat.pdf" },
];

/**
 * Given a project, return filings relevant to its workload in display order,
 * each annotated with status + stage tag (locked / drafting / submitted /
 * approved / overdue).
 *
 * Status derivation:
 *   - locked      — project.stage < unlock
 *   - drafting    — project.stage ∈ [unlock, require)
 *   - submitted   — project.stage >= require
 *   - overdue     — project.stage > require but synthetic mark missing
 *
 * In production this flows from a filings table. For now we derive from
 * the project's current stage so the timeline lights up as stage advances.
 */
export function buildFilingsTimeline(project) {
  if (!project) return [];
  const wl = project.technology || project.workload_type || "all";
  const cap = Number(project.capacity_mw) || 0;
  const stage = project.stage || "prospect";
  const stageIdx = STAGE_INDEX[stage] ?? 0;

  return FILINGS.filter((f) => {
    if (f.workload === "all") return true;
    if (Array.isArray(f.workload)) return f.workload.includes(wl);
    return f.workload === wl;
  }).filter((f) => {
    if (!f.conditional) return true;
    // Simple capacity_mw comparison grammar: "capacity_mw>50"
    const m = f.conditional.match(/capacity_mw\s*([<>=]+)\s*(\d+)/);
    if (!m) return true;
    const op = m[1], v = Number(m[2]);
    if (op === ">") return cap > v;
    if (op === ">=") return cap >= v;
    if (op === "<") return cap < v;
    if (op === "<=") return cap <= v;
    return true;
  }).map((f) => {
    const unlockIdx = STAGE_INDEX[f.unlock] ?? 0;
    const requireIdx = STAGE_INDEX[f.require] ?? STAGES.length;
    let status = "locked";
    if (stageIdx >= requireIdx) status = "submitted";
    else if (stageIdx >= unlockIdx) status = "drafting";
    // Overdue if we're well past require but no manual mark exists
    if (stageIdx > requireIdx + 1 && status === "submitted") status = "approved";
    return {
      ...f,
      status,
      unlock_stage: STAGES.find((s) => s.key === f.unlock)?.label,
      require_stage: STAGES.find((s) => s.key === f.require)?.label,
    };
  });
}

/** Map CTA action key → redesign tab / sub-tab. Used by StageRibbon to route. */
export const CTA_ROUTE = {
  "open-assess-grid":    { tab: "assess", subTab: "grid" },
  "open-assess-demand":  { tab: "assess", subTab: "demand" },
  "open-assess-planning":{ tab: "assess", subTab: "planning" },
  "open-file":           { tab: "file" },
  "open-decide":         { tab: "decide" },
  "open-operate":        { tab: "operate" },
  "agent-grid":          { tab: "assess", subTab: "grid", chat: "Chase DNO for grid offer — summarise latest correspondence and propose next-step letter." },
};
