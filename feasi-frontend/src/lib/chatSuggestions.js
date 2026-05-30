// chatSuggestions.js
// Context-aware suggested-prompt pills for the Princeps ChatRail empty state.
//
// Called by ChatRail each render with the current workspace/viewMode plus
// optional lifecycleTab (from the project-page verb tabs) and pathname (so
// Intelligence sub-routes and /design, /tracker surfaces can override).
//
// Contract:
//   getSuggestions({
//     workspace,      // "home" | "analyse" | "design" | "pipeline" | "comply"
//     viewMode,       // "map" | "grid_graph" | "dc_twin" | "dashboard" | ...
//     lifecycleTab,   // "overview" | "discover" | "assess" | "decide" | "file" | "operate"
//     pathname,       // window.location.pathname (used for /intelligence/* and /design/*)
//     projectContext, // optional {hasProject: bool}
//   }) -> { header: string|null, pills: [{label, prompt}] }
//
// Pills rule-of-thumb: 3-5 per context, short imperative label, fuller prompt
// sent to Claude on click.

// ── Raw context packs ───────────────────────────────────────────────────────
const PACKS = {
  // ── Mission Control / Home / Pipeline ─────────────────────────────────────
  mission_control: {
    header: "Ask across your pipeline.",
    pills: [
      // Curated demo starters — surfaced first so a cold visitor can land a
      // working tool-call stream in one click. Keep these four in slot 0-3
      // (they're the agreed demo surface for partner/investor walk-throughs).
      { label: "Thames BESS — connection capacity", prompt: "What is the realistic connection capacity at Thames BESS?" },
      { label: "Slough DC — grid sensitivity",      prompt: "Run grid sensitivity for Slough Hyperscale DC." },
      { label: "BNG risk across pipeline",          prompt: "Compare BNG risk across pipeline." },
      { label: "Lower Farm Drointon — Gate 2",      prompt: "Draft Gate 2 application for Lower Farm Drointon." },
      // Legacy portfolio-wide prompts retained beneath the demo set.
      { label: "Biggest pipeline risk",   prompt: "What's my biggest pipeline risk right now across all active projects?" },
      { label: "Grid slip watch",         prompt: "Which projects are at risk of grid connection slip in the next 6 months?" },
      { label: "This week's activity",    prompt: "Summarise this week's activity across my portfolio — new alerts, stage changes, risks." },
      { label: "Low-headroom sites",      prompt: "Show projects connected to substations with less than 10 MW firm headroom." },
      { label: "Cashflow stress",         prompt: "Which projects fail DSCR stress at PPA £55/MWh?" },
    ],
  },

  portfolio: {
    header: "Portfolio view.",
    pills: [
      { label: "Portfolio summary",       prompt: "Give me a one-page summary of my portfolio — MW under management, stage mix, weighted IRR." },
      { label: "Stage bottleneck",        prompt: "Where is my pipeline bottlenecking? Count projects per stage and flag the choke point." },
      { label: "Value at risk",           prompt: "Rank projects by NPV at risk from grid or planning slippage." },
      { label: "Best next action",        prompt: "For each live project, what is the single most valuable next action this week?" },
    ],
  },

  // ── Map surfaces ──────────────────────────────────────────────────────────
  map: {
    header: "Ask about what's on the map.",
    pills: [
      { label: "Similar sites ≤50km",     prompt: "Find similar sites within 50 km of the current view, ranked by resource and grid proximity." },
      { label: "Substations >20MW",       prompt: "Show substations in view with more than 20 MW of firm headroom." },
      { label: "What blocks connection?", prompt: "For the currently selected site, what's the biggest blocker to grid connection?" },
      { label: "Constraint map",          prompt: "Overlay all planning, environmental, and grid constraints affecting this area." },
      { label: "Score this parcel",       prompt: "Score the parcel under the cursor on resource, terrain, land use, grid, and planning." },
    ],
  },

  grid_graph: {
    header: "Grid graph — ask about topology.",
    pills: [
      { label: "Explain this substation", prompt: "Explain the selected substation's role in the network — voltage, upstream GSP, downstream feeders." },
      { label: "Trace to GSP",            prompt: "Trace the path from the selected node to its grid supply point and show voltage transitions." },
      { label: "Nearest spare capacity",  prompt: "Find the nearest alternative substation with spare firm capacity for a 50 MW connection." },
      { label: "N-1 risk",                prompt: "Which nodes in view fail N-1 contingency under current loading?" },
    ],
  },

  grid_twin: {
    header: "Live grid twin.",
    pills: [
      { label: "Live system state",       prompt: "Summarise live GB system state — demand, generation mix, frequency, notable constraints." },
      { label: "Congestion hotspots",     prompt: "Which substations are currently most congested on the twin?" },
      { label: "FES 2035 stress",         prompt: "Project this network to 2035 under FES Leading-the-Way and show stressed assets." },
    ],
  },

  dc_twin: {
    header: "Data centre twin.",
    pills: [
      { label: "Auto-design 50MW",        prompt: "Auto-design a 50 MW hyperscale campus on this site — buildings, cooling, substation." },
      { label: "Thermal + noise",         prompt: "Run a thermal and noise-contour analysis for the current DC layout." },
      { label: "LCOE + PUE",              prompt: "Compute LCOE and expected PUE for this data centre design." },
      { label: "Cut capex 10%",           prompt: "Suggest three layout changes that could cut capex by around 10%." },
    ],
  },

  forecast: {
    header: "Demand forecast.",
    pills: [
      { label: "Short-term forecast",     prompt: "Show the 7-day P10/P50/P90 demand forecast for the selected GSP." },
      { label: "Time to constraint",      prompt: "When does this GSP first breach its firm capacity under FES Consumer Transformation?" },
      { label: "Scenario spread",         prompt: "Compare FES 4 pathways for this GSP out to 2040 — annual GWh and peak MW." },
    ],
  },

  // ── Intelligence sub-routes ───────────────────────────────────────────────
  intelligence_alerts: {
    header: "Alerts feed.",
    pills: [
      { label: "Today's alerts",          prompt: "Summarise today's alerts grouped by severity and the projects they affect." },
      { label: "Ofgem this month",        prompt: "What Ofgem decisions or consultations dropped in the last 30 days and which of my projects are exposed?" },
      { label: "REMA update",             prompt: "What's the latest on REMA reform and how should it change my route-to-market assumptions?" },
      { label: "Filter noise",            prompt: "Which of this week's alerts are genuinely actionable vs informational?" },
    ],
  },

  intelligence_dockets: {
    header: "Regulatory dockets.",
    pills: [
      { label: "Live docket exposure",    prompt: "Show my exposure across all live dockets — which projects, what MW, what decision dates." },
      { label: "Draft consultee reply",   prompt: "Draft a response to the open consultee query on the currently selected docket." },
      { label: "Docket timeline",         prompt: "What are the key milestones on the selected docket and what's the next deadline?" },
      { label: "Precedent search",        prompt: "Find precedent decisions similar to the selected docket and summarise the outcomes." },
    ],
  },

  intelligence_datasets: {
    header: "Datasets.",
    pills: [
      { label: "REPD delta",              prompt: "What changed in REPD this week — new consents, refusals, withdrawals relevant to my pipeline?" },
      { label: "Compare to consents",     prompt: "Compare my pipeline to the latest REPD consents in the same region and flag competitive risk." },
      { label: "Dataset freshness",       prompt: "Which of my connected datasets haven't updated in the last 30 days?" },
      { label: "NESO TEC changes",        prompt: "Summarise the latest TEC register changes and flag impacts on my connection offers." },
    ],
  },

  intelligence_engagements: {
    header: "Engagements.",
    pills: [
      { label: "Open engagements",        prompt: "List all open engagements by owner and next action." },
      { label: "Stale threads",           prompt: "Which stakeholder engagements have had no contact in over 30 days?" },
      { label: "Draft follow-up",         prompt: "Draft a follow-up note for the selected engagement based on the last exchange." },
    ],
  },

  // ── Project lifecycle verb tabs ───────────────────────────────────────────
  project_overview: {
    header: "Project overview.",
    pills: [
      { label: "Grid status",             prompt: "Summarise grid connection status for this project — offer, cost, energisation date, risks." },
      { label: "Nearest comparable",      prompt: "Compare this project to its nearest comparable consented scheme." },
      { label: "What's next",             prompt: "Given the current stage, what's the next action in the workflow and who owns it?" },
      { label: "Exec one-liner",          prompt: "Write a one-paragraph executive summary of this project suitable for a weekly report." },
    ],
  },

  project_discover: {
    header: "Discover — find and score.",
    pills: [
      { label: "Find similar sites",      prompt: "Find 5 similar sites to this one within 100 km, ranked on resource and grid proximity." },
      { label: "Score this parcel",       prompt: "Score this parcel on resource, terrain, land use, grid proximity, and planning risk." },
      { label: "Planning risks",          prompt: "Show planning risks for this site — designations, precedent refusals, local plan status." },
      { label: "Lat-lon lookup",          prompt: "What does a 3 km buffer around this site look like for constraints and opportunities?" },
    ],
  },

  project_assess: {
    header: "Assess — is it buildable?",
    pills: [
      { label: "Buildable-area check",    prompt: "Run a buildable-area check on this site and report usable hectares and MW potential." },
      { label: "3 comparables",           prompt: "Pull 3 comparable consented projects and benchmark LCOE, DSCR, and timeline against this one." },
      { label: "Environmental blockers",  prompt: "List environmental blockers for this site — habitats, flood risk, heritage, BNG." },
      { label: "SAM yield",               prompt: "Run a SAM yield simulation at 50 MW and show P50/P90 annual production." },
      { label: "Grid headroom",           prompt: "What's the firm headroom at the nearest viable substation and at what voltage?" },
    ],
  },

  project_decide: {
    header: "Decide — go/no-go.",
    pills: [
      { label: "Draft IC memo",           prompt: "Draft an investment committee memo for this project — thesis, risks, returns, asks." },
      { label: "Downside scenario",       prompt: "Run a downside scenario — 20% capex overrun, 12-month grid slip, PPA £45 — and show IRR impact." },
      { label: "DSCR stress @ £55",       prompt: "Calculate DSCR stress with merchant tail at PPA £55/MWh and flag covenant breaches." },
      { label: "Sensitivity tornado",     prompt: "Produce an NPV tornado chart for the top 8 sensitivities on this project." },
      { label: "Go / no-go verdict",      prompt: "Based on the current assessment, should I greenlight this project? Give a reasoned verdict." },
    ],
  },

  project_file: {
    header: "File — generate packs.",
    pills: [
      { label: "DNO G99 pack",            prompt: "Draft the DNO G99 connection application for this project with all required fields pre-filled." },
      { label: "NPPF FVA pack",           prompt: "Generate an NPPF-compliant Financial Viability Appraisal pack for this project." },
      { label: "Lender pack",             prompt: "Compile a lender pack — project brief, grid letter, planning status, financial model summary." },
      { label: "CDM pack",                prompt: "Generate a CDM pre-construction information pack for this site." },
      { label: "EIA screening",           prompt: "Draft an EIA screening request for this project against the Schedule 2 thresholds." },
    ],
  },

  project_operate: {
    header: "Operate — live asset.",
    pills: [
      { label: "Live PUE",                prompt: "Show live PUE and IT load for this operational asset and compare to design target." },
      { label: "Noise contours",          prompt: "Check current noise contours against the planning condition thresholds." },
      { label: "Maintenance schedule",    prompt: "Pull the next 90 days of maintenance activities and flag resource clashes." },
      { label: "Curtailment this month",  prompt: "How much curtailment did this asset see this month and what was the revenue impact?" },
    ],
  },

  // ── Design / tracker surfaces ─────────────────────────────────────────────
  design: {
    header: "Design workspace.",
    pills: [
      { label: "Optimise 50MW layout",    prompt: "Optimise the current site layout for a 50 MW capacity target." },
      { label: "Cable route study",       prompt: "Suggest three cable-route options to the nearest substation with cost and loss estimates." },
      { label: "Electrical single-line",  prompt: "Draft an electrical single-line diagram for the current design." },
    ],
  },

  tracker: {
    header: "Tracker.",
    pills: [
      { label: "Due this week",           prompt: "What's due this week across all my tracked items?" },
      { label: "Blocked items",           prompt: "Show blocked tracker items and their blockers." },
      { label: "Throughput",              prompt: "What's my throughput — items completed per week over the last 8 weeks?" },
    ],
  },
};

// ── Default fallback ────────────────────────────────────────────────────────
const DEFAULT_PACK = {
  header: null, // keep existing empty-state sub-copy
  pills: [
    { label: "Find similar sites",   prompt: "Find similar sites within 50 km of my selection." },
    { label: "Substations >20MW",    prompt: "Show substations with more than 20 MW of firm headroom nearby." },
    { label: "Planning risks",       prompt: "What are the planning risks at this location?" },
    { label: "Score this site",      prompt: "Score this site on resource, grid, and planning." },
  ],
};

// ── Resolver ────────────────────────────────────────────────────────────────

// Map /intelligence/<slug> → pack key.
function resolveIntelligencePack(pathname) {
  if (!pathname) return null;
  if (pathname.startsWith("/intelligence/alerts"))      return "intelligence_alerts";
  if (pathname.startsWith("/intelligence/dockets"))     return "intelligence_dockets";
  if (pathname.startsWith("/intelligence/datasets"))    return "intelligence_datasets";
  if (pathname.startsWith("/intelligence/engagements")) return "intelligence_engagements";
  return null;
}

// Map project lifecycleTab → pack key.
const LIFECYCLE_PACKS = {
  overview: "project_overview",
  discover: "project_discover",
  assess:   "project_assess",
  decide:   "project_decide",
  file:     "project_file",
  operate:  "project_operate",
};

// Map viewMode → pack key (used when not in a project lifecycle).
const VIEWMODE_PACKS = {
  map:         "map",
  grid_graph:  "grid_graph",
  grid_twin:   "grid_twin",
  dc_twin:     "dc_twin",
  dc_connection: "dc_twin",
  forecast:    "forecast",
  neso098:     "grid_twin",
  pulse:       "mission_control",
  dashboard:   "mission_control",
  projects:    "portfolio",
};

// Map workspace → fallback pack key when viewMode doesn't match.
const WORKSPACE_FALLBACK = {
  home:     "mission_control",
  analyse:  "map",
  design:   "design",
  pipeline: "portfolio",
  comply:   "portfolio",
};

// Focus-aware pill packs — when the user has just clicked on a specific
// entity (alert, docket, substation, candidate site, project row) the chat
// should offer prompts that operate on THAT entity rather than the whole
// surface. These take precedence over every other resolver.
function focusPack(focus) {
  if (!focus || !focus.type) return null;
  // Never leak a raw UUID / numeric id into user-visible pill prompts.
  // If no label arrived, synthesise a readable fallback from the type.
  const typeLabel = {
    alert: "this alert",
    docket: "this docket",
    dataset: "this dataset",
    substation: "this substation",
    candidate_site: "this site",
    project: "this project",
  }[focus.type] || "this item";
  const label = (focus.label && String(focus.label).trim()) || typeLabel;
  switch (focus.type) {
    case "alert":
      return {
        header: `Alert: ${label}`,
        pills: [
          { label: "Summarise", prompt: `Summarise this alert in two lines and tell me which of my projects are exposed: ${label}.` },
          { label: "Impacted projects", prompt: `Which of my projects are materially impacted by this alert (${label}) and how?` },
          { label: "Draft action", prompt: `Draft the action I should take on this alert (${label}) — who owns it, what's the deadline, what's the recommended response.` },
          { label: "Trace sources", prompt: `Cite the primary sources behind this alert (${label}) and show the underlying docket or register entries.` },
        ],
      };
    case "docket":
      return {
        header: `Docket: ${label}`,
        pills: [
          { label: "Timeline + deadlines", prompt: `What are the key milestones and next deadlines on docket ${label}?` },
          { label: "Exposure", prompt: `Which of my projects are exposed to docket ${label} and by how much MW / £?` },
          { label: "Draft consultee reply", prompt: `Draft a consultee reply to docket ${label} reflecting my portfolio position.` },
          { label: "Precedent", prompt: `Find precedent decisions similar to ${label} and summarise the outcomes.` },
        ],
      };
    case "dataset":
      return {
        header: `Dataset: ${label}`,
        pills: [
          { label: "What's in it", prompt: `Describe the ${label} dataset — schema, coverage, refresh cadence, provenance.` },
          { label: "Pipeline delta", prompt: `What changed in ${label} in the last 7 days relevant to my pipeline?` },
          { label: "Query it", prompt: `Give me the SQL or tool call to query ${label} for projects within 10 km of my active site.` },
        ],
      };
    case "substation":
      return {
        header: `Substation: ${label}`,
        pills: [
          { label: "Role + topology", prompt: `Explain ${label}'s role in the network — voltage, upstream GSP, downstream feeders.` },
          { label: "Firm headroom", prompt: `What's the current firm and non-firm headroom at ${label}, and what's the queue ahead of me?` },
          { label: "N-1 behaviour", prompt: `Does ${label} survive N-1 contingency at summer peak under FES Leading the Way?` },
          { label: "Connection cost", prompt: `Estimate P10/P50/P90 connection cost from my active site to ${label} with CCCM v19 methodology.` },
        ],
      };
    case "candidate_site":
      return {
        header: `Site: ${label}`,
        pills: [
          { label: "Score it", prompt: `Score ${label} on resource, terrain, land use, grid proximity, and planning — single composite plus breakdown.` },
          { label: "Biggest blocker", prompt: `For ${label}, what's the single biggest blocker and how do I de-risk it?` },
          { label: "Design it", prompt: `Auto-design the primary workload on ${label} and give me MW, CapEx, OpEx, LCOE.` },
          { label: "Compare to peers", prompt: `Compare ${label} against the two best peer candidates in this shortlist.` },
        ],
      };
    case "project":
      return {
        header: `Project: ${label}`,
        pills: [
          { label: "What's next", prompt: `For project ${label}, what's the single most valuable action I can take this week?` },
          { label: "Grid status", prompt: `Summarise grid connection status on ${label} — offer, cost, energisation date, risks.` },
          { label: "Downside case", prompt: `Run a downside scenario on ${label} — 20% capex overrun, 12-month grid slip, PPA £45 — and show IRR impact.` },
        ],
      };
    case "location": {
      const data = focus.data || {};
      const lat = data.lat != null ? Number(data.lat).toFixed(5) : null;
      const lon = data.lon != null ? Number(data.lon).toFixed(5) : null;
      const coord = (lat != null && lon != null) ? `${lat}, ${lon}` : label;
      return {
        header: `Picked ${coord}`,
        pills: [
          { label: "What's here?", prompt: `What's at ${coord}? Identify the land use, LPA, postcode, and nearest substation.` },
          { label: "Nearest POC", prompt: `Find the nearest 3 DNO-published substations to ${coord} with their firm headroom and voltage.` },
          { label: "Screen as DC site", prompt: `Screen ${coord} as a data centre site — flood risk, constraints, and connection feasibility for 40 MW IT load.` },
          { label: "Screen as BESS site", prompt: `Screen ${coord} as a 50 MW / 100 MWh BESS site — constraints, headroom, and likely blockers.` },
        ],
      };
    }
    default:
      return null;
  }
}

export function getSuggestions({
  workspace = "home",
  viewMode = null,
  lifecycleTab = null,
  pathname = null,
  projectContext = null,
  focus = null,
} = {}) {
  const hasProject = !!(projectContext && projectContext.hasProject);

  // 0. Focus pack wins — user is asking about a specific thing.
  const fp = focusPack(focus);
  if (fp) return fp;

  // 1. Intelligence routes win (global-shell mount).
  const intelKey = resolveIntelligencePack(pathname);
  if (intelKey) return PACKS[intelKey];

  // 2. Inside a project → lifecycle verb tab.
  if (hasProject && lifecycleTab && LIFECYCLE_PACKS[lifecycleTab]) {
    return PACKS[LIFECYCLE_PACKS[lifecycleTab]];
  }

  // 3. /design/* — twin-heavy surface.
  if (pathname && pathname.startsWith("/design")) {
    return PACKS.dc_twin;
  }

  // 4. /tracker/*.
  if (pathname && pathname.startsWith("/tracker")) {
    return PACKS.tracker;
  }

  // 5. Workspace + viewMode pairing.
  if (viewMode && VIEWMODE_PACKS[viewMode]) {
    return PACKS[VIEWMODE_PACKS[viewMode]];
  }

  // 6. Workspace fallback.
  if (workspace && WORKSPACE_FALLBACK[workspace]) {
    return PACKS[WORKSPACE_FALLBACK[workspace]];
  }

  return DEFAULT_PACK;
}

export default getSuggestions;
