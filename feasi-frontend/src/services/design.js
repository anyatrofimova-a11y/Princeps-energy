/**
 * design.js — API client for the unified design orchestrator, constraint gate,
 * shade, optimiser, and layout persistence. Paired with DesignCanvas.jsx.
 */

async function j(url, opts = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${t ? " — " + t.slice(0, 160) : ""}`);
  }
  return res.json();
}

/* ── Unified orchestrator — called on every design edit ───────────────── */
export const generate = (body) =>
  j("/api/design/generate", { method: "POST", body: JSON.stringify(body) });

/* ── Constraint gate — fires as user draws boundary ───────────────────── */
export const constraintGate = (boundary) =>
  j("/api/design/constraint-gate", { method: "POST", body: JSON.stringify({ boundary }) });

/* ── Shade — returns shadow GeoJSON for a bbox + time ─────────────────── */
export const computeShade = (bbox, timestamp, product = "dsm") =>
  j("/api/design/shade", {
    method: "POST",
    body: JSON.stringify({ bbox, timestamp, product }),
  });

/* ── Optimiser — scipy search over design variables ───────────────────── */
export const optimise = (body) =>
  j("/api/design/optimise", { method: "POST", body: JSON.stringify(body) });

/* ── Layouts CRUD + versioning ────────────────────────────────────────── */
export const saveLayout = (body) =>
  j("/api/design/layouts", { method: "POST", body: JSON.stringify(body) });

export const listLayouts = ({ candidate_id, project_id } = {}) => {
  const q = new URLSearchParams();
  if (candidate_id) q.set("candidate_id", candidate_id);
  if (project_id) q.set("project_id", project_id);
  const qs = q.toString();
  return j(`/api/design/layouts${qs ? "?" + qs : ""}`);
};

export const getLayout = (id) => j(`/api/design/layouts/${id}`);

export const updateLayout = (id, body) =>
  j(`/api/design/layouts/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export const deleteLayout = (id) =>
  j(`/api/design/layouts/${id}`, { method: "DELETE" });

/* ── Engineering outputs (Phase 4) ────────────────────────────────────── */
export const buildBom = (layout_id) =>
  j("/api/design/bom", { method: "POST", body: JSON.stringify({ layout_id }) });

export const buildSld = (layout_id) =>
  j("/api/design/sld", { method: "POST", body: JSON.stringify({ layout_id }) });

export const exportLayout = (layout_id, format = "pdf") =>
  j("/api/design/export", {
    method: "POST",
    body: JSON.stringify({ layout_id, format }),
  });

/* ── Conversational agent (Phase 5) ───────────────────────────────────── */
export const askAgent = (body) =>
  j("/api/design/agent", { method: "POST", body: JSON.stringify(body) });

export const explainKpi = (layout_id, kpi_key) =>
  j("/api/design/explain-kpi", {
    method: "POST",
    body: JSON.stringify({ layout_id, kpi_key }),
  });
