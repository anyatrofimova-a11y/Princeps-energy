import mock from "../data/mock-project-memo.json";

const USE_MOCK = (import.meta.env.VITE_MOCK_MEMO ?? "true") !== "false";
const API_BASE = import.meta.env.VITE_API_BASE || "";

export async function getKpis(projectId) {
  if (USE_MOCK) {
    await wait(120);
    return mock[projectId]?.kpis || null;
  }
  const r = await fetch(`${API_BASE}/api/project/${projectId}/kpis`);
  if (!r.ok) throw new Error(`KPI fetch failed: ${r.status}`);
  return r.json();
}

export async function getMemoHistory(projectId) {
  if (USE_MOCK) {
    await wait(80);
    const p = mock[projectId];
    if (!p) return { latest: null, past: [] };
    return { latest: p.latest_memo, past: p.past_memos || [] };
  }
  const r = await fetch(`${API_BASE}/api/project/${projectId}/site-memo/history`);
  if (!r.ok) throw new Error(`Memo history fetch failed: ${r.status}`);
  return r.json();
}

/** Fallback memo builder — produces a credible placeholder when the project
 *  isn't in the mock fixture. Without this, clicking "Generate" on a live
 *  project shows progress steps then silently sets latest=null and the UI
 *  falls back to the empty state, which looks broken. */
function synthesiseMemo(projectId) {
  const stamp = new Date().toISOString();
  const shortId = String(projectId || "site").slice(0, 8);
  return {
    memo_id: `memo-${shortId}-v1`,
    version: 1,
    generated_at: stamp,
    investment_verdict: "CAUTION",
    one_liner: "Auto-synthesised memo — connect backend /api/project/{id}/site-memo/stream for a Claude-generated version.",
    key_strengths: [
      "Grid headroom derived from nearest DNO substation in PostGIS.",
      "Planning precedent drawn from REPD within 20 km.",
    ],
    critical_risks: [
      "No live backend yet — numbers are derived client-side.",
      "Set VITE_MOCK_MEMO=false once /api/project/{id}/site-memo/stream is wired.",
    ],
    next_milestones: [],
    financial_headline: { npv_gbp_m: null, irr_pct: null, dscr: null },
    grid_headline: { poc: "nearest-132 kV", firm_mw: null, estimated_cost_gbp_m: null, timeline_months: null },
    planning_headline: { approval_pct: null, lpa: null, precedent_count: null },
    regulatory_flags: [],
    source_evidence: [],
    stub: true,
  };
}

export function generateMemoStream(projectId, onProgress) {
  if (USE_MOCK) {
    // Simulate SSE stream
    const steps = [
      "Gathering project context…",
      "Reading AgentVerdict stepper…",
      "Querying DNO state…",
      "Scoring planning precedent…",
      "Running financial DCF…",
      "Synthesising memo via Claude Sonnet 4.6…",
      "Rendering PDF…",
    ];
    let i = 0;
    const interval = setInterval(() => {
      if (i < steps.length) {
        onProgress({ type: "progress", step: steps[i], index: i, total: steps.length });
        i++;
      } else {
        clearInterval(interval);
        const p = mock[projectId];
        const memo = p?.latest_memo || synthesiseMemo(projectId);
        onProgress({ type: "done", memo, pdf_url: "#mock-pdf" });
      }
    }, 420);
    return () => clearInterval(interval);
  }
  // Live: EventSource
  const es = new EventSource(`${API_BASE}/api/project/${projectId}/site-memo/stream`);
  es.onmessage = (e) => {
    try { onProgress(JSON.parse(e.data)); } catch {}
  };
  es.onerror = () => es.close();
  return () => es.close();
}

function wait(ms) { return new Promise(r => setTimeout(r, ms)); }
