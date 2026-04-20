/**
 * Dockets API — fetch layer targeting spec endpoints.
 *
 *   Backend isn't live yet. Set VITE_MOCK_DOCKETS=true (or leave the backend
 *   unreachable) to fall back to the fixture at /data/mock-dockets.json.
 *
 *   SSE endpoints (summary refresh, question, draft-letter) mock by chunking
 *   a pre-written string and emitting it with setInterval so consumers can
 *   exercise real EventSource UI without wiring the backend.
 */

import mockData from "../data/mock-dockets.json";

const MOCK =
  typeof import.meta !== "undefined"
    ? String(import.meta.env?.VITE_MOCK_DOCKETS || "true").toLowerCase() === "true"
    : true;

// ── Mock helpers ────────────────────────────────────────────────
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const delay = async () => wait(80 + Math.random() * 120);

const findDocket = (id) =>
  mockData.dockets.find((d) => d.id === id || d.docket_number === id);

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
  if (MOCK) {
    await delay();
    let rows = [...mockData.dockets];
    const { case_type, publisher, status, region, industry, technology, capacity_band, q } =
      params;
    if (case_type) rows = rows.filter((r) => r.case_type === case_type);
    if (publisher) rows = rows.filter((r) => r.publisher === publisher);
    if (status) rows = rows.filter((r) => r.status === status);
    if (region) rows = rows.filter((r) => r.region === region);
    if (industry) rows = rows.filter((r) => r.industry === industry);
    if (technology) rows = rows.filter((r) => r.technology === technology);
    if (capacity_band) {
      rows = rows.filter((r) => {
        const cap = r.capacity_mw;
        if (cap == null) return capacity_band === "n_a";
        if (capacity_band === "sub_50") return cap < 50;
        if (capacity_band === "50_to_100") return cap >= 50 && cap < 100;
        if (capacity_band === "100_to_500") return cap >= 100 && cap < 500;
        if (capacity_band === "500_plus") return cap >= 500;
        return true;
      });
    }
    if (q) {
      const needle = q.toLowerCase();
      rows = rows.filter(
        (r) =>
          r.title.toLowerCase().includes(needle) ||
          r.docket_number.toLowerCase().includes(needle) ||
          r.applicant.toLowerCase().includes(needle)
      );
    }
    return { rows, total: rows.length };
  }

  const qs = new URLSearchParams(params).toString();
  return fetchJSON(`/api/dockets/library?${qs}`);
}

export async function getDocket(id) {
  if (MOCK) {
    await delay();
    return findDocket(id) || null;
  }
  return fetchJSON(`/api/dockets/${encodeURIComponent(id)}`);
}

export async function getStakeholders(id) {
  if (MOCK) {
    await delay();
    return findDocket(id)?.stakeholders || [];
  }
  return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/stakeholders`);
}

export async function getTimeline(id) {
  if (MOCK) {
    await delay();
    return findDocket(id)?.timeline || [];
  }
  return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/timeline`);
}

export async function getDocuments(id, filters = {}) {
  if (MOCK) {
    await delay();
    let docs = findDocket(id)?.documents || [];
    if (filters.stage) docs = docs.filter((d) => d.stage === filters.stage);
    if (filters.q) {
      const needle = filters.q.toLowerCase();
      docs = docs.filter(
        (d) =>
          d.title.toLowerCase().includes(needle) ||
          (d.author && d.author.toLowerCase().includes(needle))
      );
    }
    return docs;
  }
  const qs = new URLSearchParams(filters).toString();
  return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/documents?${qs}`);
}

// ── Pin / Watch ─────────────────────────────────────────────────
export async function pinDocket(id) {
  if (MOCK) {
    await delay();
    const d = findDocket(id);
    if (d) d.pinned = true;
    return { ok: true };
  }
  return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/pin`, { method: "POST" });
}
export async function unpinDocket(id) {
  if (MOCK) {
    await delay();
    const d = findDocket(id);
    if (d) d.pinned = false;
    return { ok: true };
  }
  return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/pin`, { method: "DELETE" });
}
export async function watchDocket(id, cfg = {}) {
  if (MOCK) {
    await delay();
    const d = findDocket(id);
    if (d) d.watched = true;
    return { ok: true, ...cfg };
  }
  return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/watch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
}
export async function unwatchDocket(id) {
  if (MOCK) {
    await delay();
    const d = findDocket(id);
    if (d) d.watched = false;
    return { ok: true };
  }
  return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/watch`, { method: "DELETE" });
}

// ── Custom / Share ──────────────────────────────────────────────
export async function createCustomDocket(payload) {
  if (MOCK) {
    await delay();
    return { id: `dck_custom_${Date.now()}`, ...payload };
  }
  return fetchJSON("/api/dockets/custom", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function shareDocket(id, opts = {}) {
  if (MOCK) {
    await delay();
    return {
      ok: true,
      share_url: `https://princeps.app/share/dockets/${id}?t=${Date.now()}`,
      ...opts,
    };
  }
  return fetchJSON(`/api/dockets/${encodeURIComponent(id)}/share`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  });
}

export function exportDocketURL(id, format = "pdf") {
  if (MOCK) {
    return `data:text/plain;charset=utf-8,Mock%20export%20of%20${encodeURIComponent(
      id
    )}%20as%20${format}`;
  }
  return `/api/dockets/${encodeURIComponent(id)}/export?format=${format}`;
}

// ── Consultees ──────────────────────────────────────────────────
export async function getConsultees(params = {}) {
  if (MOCK) {
    await delay();
    return mockData.consultees;
  }
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
  const consultee = mockData.consultees.find((c) => c.id === consulteeId);
  const hook = consultee?.statutory_hook || "Section 42 PA2008";
  const name = consultee?.name || "Consultee";

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
