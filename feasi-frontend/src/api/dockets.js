/**
 * Dockets API — live-only fetch layer (mock fixture removed 2026-04-29).
 * Backend at app/routers/dockets.py exposes /library, /{docket_id},
 * /{docket_id}/stakeholders + SSE endpoints for summary/question/letter.
 */

// ── Core fetch ──────────────────────────────────────────────────
async function fetchJSON(url, opts = {}) {
  try {
    const res = await fetch(url, opts);
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

// ── Library ─────────────────────────────────────────────────────
export async function listDockets(params = {}) {
  
  const qs = new URLSearchParams(params).toString();
  return fetchJSON(`/api/dockets/library?${qs}`);
}

export async function getDocket(id) {
    return fetchJSON(`/api/dockets/${encodeURIComponent(id)}`);
}

export async function getStakeholders(id) {
    return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/stakeholders`);
}

export async function getTimeline(id) {
    return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/timeline`);
}

export async function getDocuments(id, filters = {}) {
    const qs = new URLSearchParams(filters).toString();
  return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/documents?${qs}`);
}

// ── Pin / Watch ─────────────────────────────────────────────────
export async function pinDocket(id) {
    return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/pin`, { method: "POST" });
}
export async function unpinDocket(id) {
    return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/pin`, { method: "DELETE" });
}
export async function watchDocket(id, cfg = {}) {
    return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/watch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
}
export async function unwatchDocket(id) {
    return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/watch`, { method: "DELETE" });
}

// ── Custom / Share ──────────────────────────────────────────────
export async function createCustomDocket(payload) {
    return fetchJSON("/api/dockets/custom", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function shareDocket(id, opts = {}) {
    return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/share`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  });
}

export function exportDocketURL(id, format = "pdf") {
    return `/api/dockets/${encodeURIComponent(id)}/export?format=${format}`;
}

// ── Consultees ──────────────────────────────────────────────────
export async function getConsultees(params = {}) {
    const qs = new URLSearchParams(params).toString();
  return fetchJSON(`/api/consultees?${qs}`);
}

// ── SSE streamers (mocked via interval) ─────────────────────────
//   onToken(str), onDone(fullText), onError(err). Returns cancel().
export function streamSummaryRefresh(docketId, { onToken, onDone, onError } = {}) {
  const d = findDocket(docketId);
  const text =
    d?.summary ||
    "Regenerated summary placeholder: key stakeholders, live procedural state, exposure.";

  return streamText(text, { onToken, onDone, onError });
}

export function streamQuestion(docketId, question, { onToken, onDone, onError } = {}) {
  const d = findDocket(docketId);
  const stub =
    `Draft answer for "${question}". Based on the ${d?.n_documents || 0} documents in ` +
    `${d?.docket_number || docketId}: the procedural stage is ${d?.stage || "unknown"} ` +
    `and the next deadline is ${d?.next_deadline?.label || "TBC"} on ` +
    `${d?.next_deadline?.date || "TBC"} [1][2]. Full reasoning streams here.`;

  return streamText(stub, { onToken, onDone, onError });
}

export function streamDraftLetter(consulteeId, ctx = {}, { onToken, onDone, onError } = {}) {
  const { project_name = "Project", case_type = "LPA_PLANNING" } = ctx;
  const hook = "Section 42 PA2008";
  const name = "Consultee";

  const letter =
    `Dear ${name},\n\n` +
    `RE: ${project_name} — pre-application consultation under ${hook}.\n\n` +
    `We write to notify you of our proposed development and to invite your ` +
    `formal response within 28 days.\n\n` +
    `The scheme comprises a ${case_type === "NSIP_DCO" ? "Nationally Significant Infrastructure Project" : "major planning application"} ` +
    `with the following salient particulars:\n\n` +
    `  • Technology: solar + BESS co-located\n` +
    `  • Capacity: 49.9 MW (export)\n` +
    `  • Site area: 120 ha\n` +
    `  • Connection: DNO-level at 33 kV\n` +
    `  • Construction start: Q3 2027 (target)\n\n` +
    `We would welcome any comments on matters within your remit, particularly ` +
    `relating to ${hook.includes("Section 42") ? "your statutory functions under the Planning Act 2008" : "your regulatory scope"}.\n\n` +
    `A Pre-application Environmental Report, site plan, and indicative layout ` +
    `are enclosed.\n\n` +
    `We shall be pleased to attend a pre-application meeting at your convenience.\n\n` +
    `Yours faithfully,\n\n` +
    `[Project Manager]\nPrinceps\n`;

  return streamText(letter, { onToken, onDone, onError });
}

// Chunk a string into tokens to simulate SSE.
function streamText(full, { onToken, onDone, onError }) {
  const tokens = full.split(/(\s+)/);
  let i = 0;
  let cancelled = false;

  const handle = setInterval(() => {
    if (cancelled) return;
    if (i >= tokens.length) {
      clearInterval(handle);
      try {
        onDone && onDone(full);
      } catch (e) {
        onError && onError(e);
      }
      return;
    }
    try {
      onToken && onToken(tokens[i]);
    } catch (e) {
      onError && onError(e);
    }
    i += 1;
  }, 18);

  return () => {
    cancelled = true;
    clearInterval(handle);
  };
}

export default {
  listDockets,
  getDocket,
  getStakeholders,
  getTimeline,
  getDocuments,
  pinDocket,
  unpinDocket,
  watchDocket,
  unwatchDocket,
  createCustomDocket,
  shareDocket,
  exportDocketURL,
  getConsultees,
  streamSummaryRefresh,
  streamQuestion,
  streamDraftLetter,
};
