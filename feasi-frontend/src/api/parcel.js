// BOT-FF parcel dossier fetch layer — live backend only.
// As of 2026-04-29 the mock fallback (mock-parcels.json) has been removed.
// Errors propagate so the drawer can render a clear empty/error state.
//
// Backend routes (app/routers/parcel.py):
//   GET  /api/parcel/{inspire_id}                  → dossier
//   POST /api/parcel/{inspire_id}/pin              → pin to project
//   POST /api/parcel/{inspire_id}/shortlist        → shortlist
//   GET  /api/parcel/{inspire_id}/export.pdf       → dossier PDF

export async function getParcelDossier(inspireId, { signal } = {}) {
  if (!inspireId) throw new Error("inspire_id is required");
  const resp = await fetch(`/api/parcel/${encodeURIComponent(inspireId)}`, { signal });
  if (resp.status === 429) {
    const body = await resp.json().catch(() => ({}));
    const e = new Error("rate_limited");
    e.status = 429;
    e.retryAfter = body?.detail?.retry_after_s ?? 60;
    throw e;
  }
  if (!resp.ok) throw new Error(`parcel dossier ${resp.status}`);
  return resp.json();
}

export async function pinParcelToProject(inspireId, projectId = null) {
  const r = await fetch(`/api/parcel/${encodeURIComponent(inspireId)}/pin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId }),
  });
  if (!r.ok) throw new Error(`pin ${r.status}`);
  return r.json();
}

export async function shortlistParcel(inspireId) {
  const r = await fetch(`/api/parcel/${encodeURIComponent(inspireId)}/shortlist`, {
    method: "POST",
  });
  if (!r.ok) throw new Error(`shortlist ${r.status}`);
  return r.json();
}

export function hmlrPrimarySourceUrl(titleNumber) {
  if (!titleNumber) return "https://landregistry.data.gov.uk/";
  return `https://landregistry.data.gov.uk/app/qonsole#lrcommon=${encodeURIComponent(titleNumber)}`;
}

export async function exportParcelPdf(inspireId) {
  const r = await fetch(`/api/parcel/${encodeURIComponent(inspireId)}/export.pdf`);
  if (!r.ok) throw new Error(`export ${r.status}`);
  const blob = await r.blob();
  return { url: URL.createObjectURL(blob) };
}

// Removed: MOCK_PARCEL_IDS — call sites should hit /api/parcels/search.
