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
        onProgress({ type: "done", memo: p?.latest_memo || null, pdf_url: "#mock-pdf" });
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
