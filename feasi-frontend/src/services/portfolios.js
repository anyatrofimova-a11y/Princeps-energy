/**
 * portfolios.js — API client helpers for the portfolio/project/candidate-site hierarchy
 * powering the redesigned project-centric UI.
 *
 * Paired routers (backend):
 *   /api/v1/portfolios       — app/routers/portfolios_crud.py
 *   /api/v1/projects         — app/routers/projects.py
 *   /api/v1/projects/{id}/candidate-sites — same file
 */

const BASE = "";

async function j(url, opts = {}) {
  const res = await fetch(BASE + url, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${text ? ` — ${text}` : ""}`);
  }
  return res.json();
}

export const listPortfolios = () => j("/api/v1/portfolios");
export const getPortfolio = (id) => j(`/api/v1/portfolios/${id}`);
export const createPortfolio = (body) => j("/api/v1/portfolios", { method: "POST", body: JSON.stringify(body) });
export const updatePortfolio = (id, body) => j(`/api/v1/portfolios/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deletePortfolio = (id) => j(`/api/v1/portfolios/${id}`, { method: "DELETE" });
export const listPortfolioProjects = (id) => j(`/api/v1/portfolios/${id}/projects`);

/** Full nested tree — use this for the ProjectTree sidebar (one roundtrip). */
export const getPortfolioTree = () => j("/api/v1/portfolios/tree/full");

export const listProjects = (filters = {}) => {
  const qs = new URLSearchParams(filters).toString();
  return j(`/api/v1/projects${qs ? "?" + qs : ""}`);
};
export const getProject = (id) => j(`/api/v1/projects/${id}`);
export const createProject = (body) => j("/api/v1/projects", { method: "POST", body: JSON.stringify(body) });
export const updateProject = (id, body) =>
  j(`/api/v1/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export const listCandidateSites = (projectId) => j(`/api/v1/projects/${projectId}/candidate-sites`);
export const createCandidateSite = (projectId, body) =>
  j(`/api/v1/projects/${projectId}/candidate-sites`, { method: "POST", body: JSON.stringify(body) });
export const updateCandidateSite = (projectId, candidateId, body) =>
  j(`/api/v1/projects/${projectId}/candidate-sites/${candidateId}`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteCandidateSite = (projectId, candidateId) =>
  j(`/api/v1/projects/${projectId}/candidate-sites/${candidateId}`, { method: "DELETE" });
