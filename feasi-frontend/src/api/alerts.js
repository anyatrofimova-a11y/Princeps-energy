// Alerts fetch layer.
// ---------------------------------------------------------------
// Targets the backend spec. When VITE_MOCK_ALERTS=true (or the env
// var is absent and the live endpoint is unreachable), returns
// fixture data from src/data/mock-alerts.json so the Alerts tab
// renders end-to-end without a backend.

import mock from "../data/mock-alerts.json";

const MOCK = (() => {
  try {
    // Vite — read at build time; default to mock mode when backend isn't live.
    return String(import.meta.env?.VITE_MOCK_ALERTS || "true") === "true";
  } catch {
    return true;
  }
})();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── Library ────────────────────────────────────────────────────
export async function getAlertLibrary() {
  if (MOCK) {
    await sleep(60);
    return { alerts: mock.alerts };
  }
  const r = await fetch("/api/alerts/library");
  if (!r.ok) throw new Error(`library ${r.status}`);
  return r.json();
}

// ── Subscribe / unsubscribe ────────────────────────────────────
export async function subscribeAlert(alertId) {
  if (MOCK) {
    await sleep(60);
    return { subscription_id: `sub-${alertId}-${Date.now()}` };
  }
  const r = await fetch("/api/alerts/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ alert_id: alertId }),
  });
  if (!r.ok) throw new Error(`subscribe ${r.status}`);
  return r.json();
}

export async function unsubscribeAlert(subscriptionId) {
  if (MOCK) {
    await sleep(30);
    return { ok: true };
  }
  const r = await fetch(`/api/alerts/subscribe/${encodeURIComponent(subscriptionId)}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error(`unsubscribe ${r.status}`);
  return r.json();
}

// ── Digest feed ────────────────────────────────────────────────
export async function getDigest({ since = null, alertId = null } = {}) {
  if (MOCK) {
    await sleep(60);
    // Digest is the combined daily roll-up; filter by alertId if given.
    const digests = mock.digests
      .map((day) => ({
        ...day,
        entries: alertId ? day.entries.filter((e) => e.alert_id === alertId) : day.entries,
      }))
      .filter((d) => d.entries.length > 0);
    return { digests };
  }
  const qs = new URLSearchParams();
  if (since) qs.set("since", since);
  if (alertId) qs.set("alert_id", alertId);
  const r = await fetch(`/api/alerts/digest?${qs.toString()}`);
  if (!r.ok) throw new Error(`digest ${r.status}`);
  return r.json();
}

// ── Digest SSE stream ──────────────────────────────────────────
// Returns an AbortController so callers can cancel the stream.
export function openDigestStream(onEvent) {
  if (MOCK) {
    // No-op stream; keep the connection alive but never emit — the
    // cadence is daily so we don't fake realtime for the fixture.
    return { close: () => {} };
  }
  const es = new EventSource("/api/alerts/digest/stream");
  es.onmessage = (e) => {
    try {
      onEvent?.(JSON.parse(e.data));
    } catch {
      /* ignore */
    }
  };
  return { close: () => es.close() };
}

// ── Document fetch ─────────────────────────────────────────────
export async function getDocument(docId) {
  if (MOCK) {
    await sleep(30);
    const doc = mock.documents.find((d) => d.id === docId);
    if (!doc) throw new Error(`doc ${docId} not found`);
    return doc;
  }
  const r = await fetch(`/api/alerts/doc/${encodeURIComponent(docId)}`);
  if (!r.ok) throw new Error(`doc ${r.status}`);
  return r.json();
}

export async function getDocumentsForAlert(alertId) {
  if (MOCK) {
    await sleep(30);
    return {
      documents: mock.documents
        .filter((d) => d.alert_id === alertId)
        .sort((a, b) => (a.date < b.date ? 1 : -1)),
    };
  }
  const r = await fetch(`/api/alerts/doc?alert_id=${encodeURIComponent(alertId)}`);
  if (!r.ok) throw new Error(`docs ${r.status}`);
  return r.json();
}

export async function getAllDocuments() {
  if (MOCK) {
    await sleep(30);
    return {
      documents: [...mock.documents].sort((a, b) => (a.date < b.date ? 1 : -1)),
    };
  }
  const r = await fetch("/api/alerts/doc");
  if (!r.ok) throw new Error(`docs ${r.status}`);
  return r.json();
}

// ── Pin to project ─────────────────────────────────────────────
export async function pinDocument({ docId, projectId }) {
  if (MOCK) {
    await sleep(30);
    return { ok: true };
  }
  const r = await fetch("/api/alerts/pin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_id: docId, project_id: projectId }),
  });
  if (!r.ok) throw new Error(`pin ${r.status}`);
  return r.json();
}

// ── Question-aware mock scorer ─────────────────────────────────
const STOPWORDS = new Set([
  "the","a","an","of","in","on","this","that","these","those","year","month","week",
  "at","to","for","with","is","are","was","were","be","been","being",
  "what","which","how","who","when","where","why","do","does","did",
  "and","or","but","if","so","than","then","into","from","by","as","it","its",
  "about","any","some","all","i","me","my","we","our","you","your","they","their",
  "will","would","could","should","can","may","might","shall","have","has","had",
  "new","latest","recent","update","show","tell","list","give","get","find"
]);

function tokenise(s) {
  if (!s) return [];
  return String(s)
    .toLowerCase()
    .replace(/[^a-z0-9\s+/-]/g, " ")
    .split(/\s+/)
    .filter((t) => t && t.length > 1 && !STOPWORDS.has(t));
}

function withinDays(isoDate, days) {
  if (!isoDate) return false;
  const d = new Date(isoDate).getTime();
  if (Number.isNaN(d)) return false;
  return (Date.now() - d) <= days * 24 * 60 * 60 * 1000;
}

function isIn2026(isoDate) {
  if (!isoDate) return false;
  return String(isoDate).startsWith("2026");
}

function scoreDoc(doc, qTokens, qRaw) {
  const titleToks = new Set(tokenise(doc.title));
  const bodyToks = new Set(tokenise(doc.body || doc.extract || ""));
  const tagToks = new Set((doc.topic_tags || doc.topics || []).flatMap((t) => tokenise(t)));
  const fieldToks = new Set(
    Object.values(doc.extracted_fields || doc.structured || {})
      .flatMap((v) => tokenise(String(v ?? "")))
  );

  let score = 0;
  let titleHits = 0;
  let tagHits = 0;
  let bodyHits = 0;
  let fieldHits = 0;

  for (const tok of qTokens) {
    if (titleToks.has(tok)) { score += 2 * 10; titleHits += 1; }
    if (tagToks.has(tok))   { score += 3 * 10; tagHits += 1; }
    if (bodyToks.has(tok))  { score += 1 * 10; bodyHits += 1; }
    if (fieldToks.has(tok)) { score += 1.5 * 10; fieldHits += 1; }
  }

  // Phrase bonus — whole-phrase match in title/body gives bigger credit for DC etc.
  const qPhrase = qRaw.toLowerCase();
  if (qPhrase.includes("data centre") || qPhrase.includes("data center") || qPhrase.includes(" dc ")) {
    if ((doc.topic_tags || []).some((t) => /data centre|data centres|hyperscale/.test(t.toLowerCase()))) {
      score += 30;
    }
  }
  if (/\bbess\b|battery|batteries/.test(qPhrase)) {
    if ((doc.topic_tags || []).some((t) => /bess|battery/.test(t.toLowerCase()))) {
      score += 15;
    }
  }

  // Date bonus
  if (/(this year|2026)/i.test(qRaw) && isIn2026(doc.published_at || doc.date)) score += 20;
  if (/last month|past month/i.test(qRaw) && withinDays(doc.published_at || doc.date, 30)) score += 30;
  if (/last week|past week/i.test(qRaw) && withinDays(doc.published_at || doc.date, 7)) score += 40;

  // Approval intent bonus — if user asked for approvals, prefer "approval" / "approved" docs
  if (/approv/i.test(qRaw)) {
    const fields = JSON.stringify(doc.extracted_fields || {}).toLowerCase();
    const titleLo = (doc.title || "").toLowerCase();
    if (fields.includes("approv") || titleLo.includes("approv") || titleLo.includes("granted") || titleLo.includes("accepted")) {
      score += 25;
    }
  }

  // UK bonus — if user asks about UK, favour UK docs (all our mock docs are UK so small bump)
  if (/\buk\b|british|britain|england|scotland|wales/i.test(qRaw)) {
    score += 2;
  }

  return {
    score,
    titleHits, tagHits, bodyHits, fieldHits,
    matched: titleHits + tagHits + bodyHits + fieldHits,
  };
}

function rankDocs(question, { topK = 5, minScore = 10 } = {}) {
  const qTokens = tokenise(question);
  if (qTokens.length === 0) return [];
  const scored = mock.documents
    .map((d) => ({ doc: d, ...scoreDoc(d, qTokens, question) }))
    .filter((r) => r.score >= minScore && r.matched > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, topK);
  return scored;
}

function shortDate(iso) {
  if (!iso) return "";
  return String(iso).slice(0, 10);
}

function composeAnswer(question, ranked) {
  // Opens with a paraphrase, synthesises 2-3 findings, closes with a caveat.
  const opener = `On "${question.trim()}" — ${ranked.length} document${ranked.length === 1 ? "" : "s"} in the current feed match.`;
  const findings = [];
  const take = Math.min(ranked.length, 3);
  for (let i = 0; i < take; i++) {
    const r = ranked[i];
    const d = r.doc;
    const cap = d.extracted_fields?.capacity_mw || d.structured?.capacity_mw;
    const party = d.extracted_fields?.counterparty || d.structured?.counterparty;
    let oneLine = d.title;
    if (cap) oneLine = `${d.title} (${cap}MW${party ? `, ${party}` : ""})`;
    else if (party) oneLine = `${d.title} (${party})`;
    findings.push(`${oneLine} [${i + 1}]`);
  }
  const body = `Key findings: ${findings.join("; ")}.`;
  const caveat = `This reflects documents ingested through 2026-04-19; earlier filings may exist but are not in the current feed.`;
  return `${opener} ${body} ${caveat}`;
}

function noMatchAnswer() {
  const suggestions = ["TEC Register delta", "AR7 allocation round notices", "Major solar/BESS/DC planning apps"];
  return `No documents in the current feed match this query. Try rephrasing, or expand your alert subscriptions — e.g. ${suggestions.map((s) => `"${s}"`).join(", ")}.`;
}

// ── Query stream (SSE) ─────────────────────────────────────────
// Mirrors the /chat streaming contract. Protocol:
//   onCitation({ n, doc_id, title, source, date, label })  — emitted first, one per matched doc
//   onDelta(text)   — token-ish chunks of the composed answer
//   onDone()        — when complete
//   onError(msg)    — on fetch/stream error
export async function streamQuery({ question, scope, signal, onDelta, onCitation, onDone, onError }) {
  if (MOCK) {
    const ranked = rankDocs(question || "");
    const text = ranked.length === 0 ? noMatchAnswer() : composeAnswer(question, ranked);

    // Emit citations first, matching the [1][2][3] in the composed answer.
    if (ranked.length > 0) {
      const citations = ranked.map((r, i) => ({
        n: i + 1,
        doc_id: r.doc.id,
        title: r.doc.title,
        source: r.doc.source,
        date: shortDate(r.doc.published_at || r.doc.date),
        label: `${r.doc.title} — ${r.doc.source} ${shortDate(r.doc.published_at || r.doc.date)}`,
        score: Math.round(r.score),
      }));
      for (let i = 0; i < citations.length; i++) {
        if (signal?.aborted) return;
        await sleep(60);
        onCitation?.(citations[i]);
      }
    }

    // Stream tokens at ~40ms intervals (split on whitespace keeping the space).
    const pieces = text.split(/(\s+)/);
    for (let i = 0; i < pieces.length; i++) {
      if (signal?.aborted) return;
      await sleep(40);
      onDelta?.(pieces[i]);
    }
    onDone?.();
    return;
  }

  try {
    const res = await fetch("/api/alerts/query/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, scope }),
      signal,
    });
    if (!res.ok || !res.body) throw new Error(`query ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        let ev;
        try { ev = JSON.parse(line.slice(6)); } catch { continue; }
        if (ev.type === "text_delta" || ev.type === "token") onDelta?.(ev.content ?? ev.text);
        else if (ev.type === "citation" || ev.type === "citations") {
          if (Array.isArray(ev.citations)) ev.citations.forEach((c) => onCitation?.(c));
          else onCitation?.(ev);
        }
        else if (ev.type === "done") onDone?.();
        else if (ev.type === "error") onError?.(ev.message);
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") onError?.(e.message || String(e));
  }
}

// Exposed for QueryView to render the Documents tab (mock mode only).
export function rankMockDocs(question, opts) {
  if (!MOCK) return [];
  return rankDocs(question, opts);
}

export const MOCK_MODE = MOCK;
