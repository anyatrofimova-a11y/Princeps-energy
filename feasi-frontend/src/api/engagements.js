/**
 * Engagements API — fetch layer for /intelligence/engagements.
 *
 *   Backend isn't wired yet. Set VITE_MOCK_ENGAGEMENTS=true (default) to
 *   fall back to the fixture at /data/mock-engagements.json so the tab
 *   renders end-to-end without a backend.
 *
 * Same pattern as src/api/dockets.js and src/api/alerts.js — keep this
 * file identical in spirit so the three Intelligence tabs share a single
 * mock-vs-live contract.
 *
 * Target backend contract (when live):
 *   GET  /api/intelligence/engagements?status=&team=
 *          → { engagements: Engagement[] }
 *
 * Filter semantics (mirrors EngagementsIndex.FILTERS):
 *   - status=sent           → awaiting response
 *   - status=sent,responded → sent to DNO (includes already-responded)
 *   - team=self             → only engagements owned by the current user
 */

import mock from "../data/mock-engagements.json";

const MOCK = (() => {
  try {
    return String(import.meta.env?.VITE_MOCK_ENGAGEMENTS || "true") === "true";
  } catch {
    return true;
  }
})();

const SELF_EMAIL = mock?._meta?.team_self_owner || "anya.trofimova@princeps.energy";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function matchesStatus(eng, statusParam) {
  if (!statusParam) return true;
  const wanted = String(statusParam)
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (wanted.length === 0) return true;
  return wanted.includes(eng.status);
}

function matchesTeam(eng, teamParam) {
  if (!teamParam) return true;
  // "self" → only engagements owned by the signed-in user.
  if (teamParam === "self") return eng.owner_email === SELF_EMAIL;
  // Anything else is treated as an owner_email filter.
  return eng.owner_email === teamParam;
}

export async function listEngagements(params = {}) {
  if (MOCK) {
    await sleep(50);
    const rows = (mock.engagements || []).filter(
      (e) => matchesStatus(e, params.status) && matchesTeam(e, params.team)
    );
    return { engagements: rows };
  }

  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.team) qs.set("team", params.team);
  const url = "/api/intelligence/engagements" + (qs.toString() ? "?" + qs : "");
  const res = await fetch(url);
  if (!res.ok) throw new Error(`engagements ${res.status}`);
  return res.json();
}

export async function getEngagement(id) {
  if (MOCK) {
    await sleep(30);
    return (mock.engagements || []).find((e) => e.id === id) || null;
  }
  const res = await fetch(`/api/intelligence/engagements/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`engagement ${res.status}`);
  return res.json();
}

export const MOCK_MODE = MOCK;

export default {
  listEngagements,
  getEngagement,
  MOCK_MODE,
};
