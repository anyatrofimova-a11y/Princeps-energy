// Alerts fetch layer — live backend only.
// ---------------------------------------------------------------
// As of 2026-04-29 the mock fallback (mock-alerts.json + the local
// keyword scorer) has been removed. Every function in here calls
// the FastAPI /api/alerts/* surface defined in app/routers/alerts.py.
// If the backend isn't reachable, errors propagate — DigestFeed +
// SubscribeModal + StarterPacks + QueryView render their own empty
// states.

// ── Library ────────────────────────────────────────────────────
export async function getAlertLibrary() {
  const r = await fetch("/api/alerts/library");
  if (!r.ok) throw new Error(`library ${r.status}`);
  return r.json();
}

// ── Subscribe / unsubscribe ────────────────────────────────────
export async function subscribeAlert(alertId) {
  const r = await fetch("/api/alerts/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ alert_id: alertId }),
  });
  if (!r.ok) throw new Error(`subscribe ${r.status}`);
  return r.json();
}

export async function unsubscribeAlert(subscriptionId) {
  const r = await fetch(`/api/alerts/subscribe/${encodeURIComponent(subscriptionId)}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error(`unsubscribe ${r.status}`);
  return r.json();
}

// ── Digest feed ────────────────────────────────────────────────
export async function getDigest({ since = null, alertId = null } = {}) {
  const qs = new URLSearchParams();
  if (since) qs.set("since", since);
  if (alertId) qs.set("alert_id", alertId);
  const r = await fetch(`/api/alerts/digest?${qs.toString()}`);
  if (!r.ok) throw new Error(`digest ${r.status}`);
  return r.json();
}

// ── Digest SSE stream ──────────────────────────────────────────
export function openDigestStream(onEvent) {
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
  const r = await fetch(`/api/alerts/doc/${encodeURIComponent(docId)}`);
  if (!r.ok) throw new Error(`doc ${r.status}`);
  return r.json();
}

export async function getDocumentsForAlert(alertId) {
  const r = await fetch(`/api/alerts/doc?alert_id=${encodeURIComponent(alertId)}`);
  if (!r.ok) throw new Error(`docs ${r.status}`);
  return r.json();
}

export async function getAllDocuments() {
  const r = await fetch("/api/alerts/doc");
  if (!r.ok) throw new Error(`docs ${r.status}`);
  return r.json();
}

// ── Pin to project ─────────────────────────────────────────────
export async function pinDocument({ docId, projectId }) {
  const r = await fetch("/api/alerts/pin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_id: docId, project_id: projectId }),
  });
  if (!r.ok) throw new Error(`pin ${r.status}`);
  return r.json();
}

// ── Starter packs ──────────────────────────────────────────────
export async function getStarterPacks() {
  const r = await fetch("/api/alerts/starter-packs");
  if (!r.ok) throw new Error(`starter-packs ${r.status}`);
  return r.json();
}

export async function subscribeStarterPack(packSlug) {
  const r = await fetch(`/api/alerts/starter-pack/${encodeURIComponent(packSlug)}/subscribe`, {
    method: "POST",
  });
  if (!r.ok) throw new Error(`starter-pack subscribe ${r.status}`);
  return r.json();
}

// ── Query stream (SSE) ─────────────────────────────────────────
// Mirrors the /chat streaming contract. Protocol:
//   onCitation({ n, doc_id, title, source, date, label })
//   onDelta(text)
//   onDone()
//   onError(msg)
export async function streamQuery({ question, scope, signal, onDelta, onCitation, onDone, onError }) {
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

// Removed: rankMockDocs / MOCK_MODE — call sites should hit the live
// /api/alerts/search endpoint. If you grep for `rankMockDocs` and find a
// caller, replace the call with /api/alerts/search.
