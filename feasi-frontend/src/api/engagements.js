/**
 * Engagements API — fetch layer for /intelligence/engagements.
 *
 * Live backend (app/routers/dno_engagement.py):
 *   GET /api/intelligence/engagements?status=&team=
 *   GET /api/intelligence/engagements/{id}
 *
 * As of 2026-04-29 the mock fallback (mock-engagements.json) has been
 * removed. If the backend isn't reachable, errors propagate; the page
 * renders an empty state.
 */

export async function listEngagements(params = {}) {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.team) qs.set("team", params.team);
  const url = "/api/intelligence/engagements" + (qs.toString() ? "?" + qs : "");
  const res = await fetch(url);
  if (!res.ok) throw new Error(`engagements ${res.status}`);
  return res.json();
}

export async function getEngagement(id) {
  const res = await fetch(`/api/intelligence/engagements/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`engagement ${res.status}`);
  return res.json();
}

// Removed: MOCK_MODE — call sites no longer need to switch behaviour.
export const MOCK_MODE = false;

export default {
  listEngagements,
  getEngagement,
  MOCK_MODE,
};
