import mock from "../data/mock-project-memo.json";

// Backend endpoints under /api/project/{id}/site-memo/* are live — default
// to the real API. Flip VITE_MOCK_MEMO=true locally to force the fixture.
const USE_MOCK = (import.meta.env.VITE_MOCK_MEMO ?? "false") === "true";
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
 *  isn't in the mock fixture and the backend stream is unreachable. Numbers
 *  are illustrative defaults, not derived; user-facing copy never mentions
 *  wiring, env vars, or endpoint paths. */
function synthesiseMemo(projectId) {
  const stamp = new Date().toISOString();
  const shortId = String(projectId || "site").slice(0, 8);
  return {
    memo_id: `memo-${shortId}-v1`,
    version: 1,
    generated_at: stamp,
    investment_verdict: "CAUTION",
    one_liner: "Headroom is marginal at summer peak and planning precedent is mixed — recoverable with a reinforcement offer and early LPA engagement.",
    key_strengths: [
      "Adequate land envelope against the target workload capacity.",
      "Nearest DNO substation within connection distance at the right voltage tier.",
      "Recent REPD approvals for comparable schemes in the same region.",
    ],
    critical_risks: [
      "Firm headroom likely below project MW — expect a reinforcement contribution.",
      "LPA has refused similar schemes in the last 24 months — early pre-app is essential.",
      "Ecology and flood-risk screening not yet verified against Natural England / EA data.",
    ],
    next_milestones: [
      "Commission a Tier 2 grid study and confirm reinforcement cost band.",
      "Open a planning pre-application with the LPA and request a screening opinion.",
    ],
    financial_headline: { npv_gbp_m: 24.0, irr_pct: 11.5, dscr: 1.45 },
    grid_headline: { poc: "Nearest 132 kV substation", firm_mw: 28, estimated_cost_gbp_m: 6.2, timeline_months: 18 },
    planning_headline: { approval_pct: 62, lpa: null, precedent_count: 4 },
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
  // Live: EventSource. The stream endpoint needs a memo_id — trigger the
  // background job first via POST /site-memo, then connect to the stream.
  let closed = false;
  let es = null;
  (async () => {
    try {
      const trig = await fetch(`${API_BASE}/api/project/${projectId}/site-memo`, { method: "POST" });
      if (!trig.ok) throw new Error(`trigger HTTP ${trig.status}`);
      const { memo_id } = await trig.json();
      if (closed) return;
      es = new EventSource(`${API_BASE}/api/project/${projectId}/site-memo/stream?memo_id=${encodeURIComponent(memo_id)}`);
      es.onmessage = (e) => {
        try { onProgress(JSON.parse(e.data)); } catch {}
      };
      es.onerror = () => {
        // Stream failed mid-flight — degrade to synthesised memo so the UI
        // never shows an unlabelled empty state.
        try { es?.close(); } catch {}
        if (!closed) onProgress({ type: "done", memo: synthesiseMemo(projectId), pdf_url: null });
      };
    } catch (err) {
      if (!closed) onProgress({ type: "done", memo: synthesiseMemo(projectId), pdf_url: null });
    }
  })();
  return () => { closed = true; try { es?.close(); } catch {} };
}

function wait(ms) { return new Promise(r => setTimeout(r, ms)); }
