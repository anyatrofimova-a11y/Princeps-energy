// BOT-FF parcel dossier fetch layer.
// ---------------------------------------------------------------
// Targets GET /api/parcel/{inspire_id}.
//
// When VITE_MOCK_PARCEL=true (the default) the module returns fixtures from
// src/data/mock-parcels.json so the drawer renders end-to-end without a
// backend. If the INSPIRE id is not in the fixtures, the first fixture is
// returned with its inspire_id rewritten so the UI can still demo.
//
// Usage:
//   import { getParcelDossier } from "../api/parcel";
//   const dossier = await getParcelDossier("GB-INSPIRE-0000000001");

import mockParcels from "../data/mock-parcels.json";

const MOCK = (() => {
  try {
    const v = import.meta.env?.VITE_MOCK_PARCEL;
    // Default ON unless explicitly set to "false".
    return v == null ? true : String(v).toLowerCase() !== "false";
  } catch {
    return true;
  }
})();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function pickMock(inspireId) {
  if (mockParcels[inspireId]) {
    return structuredClone(mockParcels[inspireId]);
  }
  const firstKey = Object.keys(mockParcels)[0];
  const clone = structuredClone(mockParcels[firstKey]);
  clone.inspire_id = inspireId;
  clone.mock_reason = "unknown_inspire_id_fell_back_to_fixture_1";
  return clone;
}

export async function getParcelDossier(inspireId, { signal } = {}) {
  if (!inspireId) throw new Error("inspire_id is required");

  if (MOCK) {
    await sleep(120);
    return pickMock(inspireId);
  }

  let resp;
  try {
    resp = await fetch(`/api/parcel/${encodeURIComponent(inspireId)}`, { signal });
  } catch (err) {
    // Network failure — degrade to mock to keep the drawer useful.
    console.warn("parcel dossier fetch failed, falling back to mock:", err);
    return pickMock(inspireId);
  }

  if (!resp.ok) {
    if (resp.status === 429) {
      const body = await resp.json().catch(() => ({}));
      const e = new Error("rate_limited");
      e.status = 429;
      e.retryAfter = body?.detail?.retry_after_s ?? 60;
      throw e;
    }
    // Any other status — try JSON body then fallback.
    console.warn(`parcel dossier ${resp.status} — falling back to mock`);
    return pickMock(inspireId);
  }

  return resp.json();
}

export const MOCK_PARCEL_IDS = Object.keys(mockParcels);

// Thin action helpers — these fire events / call tiny endpoints. All are
// safe to no-op in mock mode so the drawer footer buttons feel responsive.

export async function pinParcelToProject(inspireId, projectId = null) {
  if (MOCK) {
    await sleep(80);
    return { pinned: true, inspire_id: inspireId, project_id: projectId };
  }
  const r = await fetch(`/api/parcel/${encodeURIComponent(inspireId)}/pin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId }),
  });
  if (!r.ok) throw new Error(`pin ${r.status}`);
  return r.json();
}

export async function shortlistParcel(inspireId) {
  if (MOCK) {
    await sleep(80);
    return { shortlisted: true, inspire_id: inspireId };
  }
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
  if (MOCK) {
    await sleep(120);
    return { url: `data:application/pdf;base64,mock-${inspireId}` };
  }
  const r = await fetch(`/api/parcel/${encodeURIComponent(inspireId)}/export.pdf`);
  if (!r.ok) throw new Error(`export ${r.status}`);
  const blob = await r.blob();
  return { url: URL.createObjectURL(blob) };
}
