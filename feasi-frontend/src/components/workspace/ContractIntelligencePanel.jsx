import React, { useState, useEffect, useRef, useCallback } from "react";

/**
 * ContractIntelligencePanel — left chat / right rail (rating + citations
 * + sources). Mirrors the Cairn screenshot layout: every assistant turn
 * gets a confidence pill with a "Justify →" affordance that opens the
 * right rail.
 */
export default function ContractIntelligencePanel({ projectRid, projectName }) {
  const [documents, setDocuments] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [selectedDocs, setSelectedDocs] = useState([]);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [activeRail, setActiveRail] = useState(null); // { question, citations, verdict }
  const [diffOpen, setDiffOpen] = useState(false);
  const [alerts, setAlerts] = useState([]);
  const chatBottomRef = useRef(null);

  /* ── load documents + alerts ───────────────────────────────── */
  useEffect(() => {
    if (!projectRid) return;
    fetch(`/api/contracts/documents?project_rid=${encodeURIComponent(projectRid)}`)
      .then((r) => r.json()).then((d) => setDocuments(d.items || []))
      .catch(() => setDocuments([]));
    fetch(`/api/contracts/projects/${encodeURIComponent(projectRid)}/alerts`)
      .then((r) => r.json()).then((d) => setAlerts(d.items || []))
      .catch(() => setAlerts([]));
  }, [projectRid]);

  /* Load drafts for each document so the doc list can show counts. */
  useEffect(() => {
    documents.forEach((d) => {
      if (drafts[d.document_rid]) return;
      fetch(`/api/contracts/documents/${encodeURIComponent(d.document_rid)}/drafts`)
        .then((r) => r.json()).then((res) =>
          setDrafts((prev) => ({ ...prev, [d.document_rid]: res.items || [] })));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documents]);

  /* ── chat send → cite → render ─────────────────────────────── */
  const send = useCallback(async () => {
    const q = input.trim();
    if (!q || pending) return;
    setInput("");
    const userMsg = { role: "user", text: q, id: `m_${Date.now()}` };
    setMessages((m) => [...m, userMsg]);
    setPending(true);

    try {
      const res = await fetch("/api/contracts/cite", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_rid: projectRid, query: q, top_k: 6 }),
      });
      const data = await res.json();
      const cites = data.citations || [];
      const grounded = cites.filter((c) => (c.similarity || 0) > 0.3);
      const rating = grounded.length === 0 ? "low"
                   : grounded.every((c) => (c.similarity || 0) > 0.6) ? "high"
                   : "med";
      const coverage = grounded.length / Math.max(cites.length, 1);

      const sectionsCovered = new Set(cites.map((c) => c.section).filter(Boolean));
      const bounds = [];
      if (cites.length === 0) bounds.push("No clauses matched the query — the workspace may be empty or the question outside scope.");
      else if (rating !== "high") bounds.push(`Only ${grounded.length} of ${cites.length} retrieved clauses cross the confidence threshold.`);
      const schedulesSeen = [...sectionsCovered].filter((s) => /SCHEDULE/i.test(s));
      if (schedulesSeen.length === 0 && cites.length) bounds.push("No schedules were touched in the answer — main body only.");

      const answer = cites.length
        ? `Found ${cites.length} relevant clauses${cites[0]?.section ? `, top match in §${cites[0].section} on page ${cites[0].page}` : ""}. Open the citations rail for verbatim text.`
        : "No clauses retrieved — upload a draft to this project's documents first.";

      const justification = rating === "high"
        ? "Every retrieved clause crosses the similarity threshold; the answer is grounded in verbatim text the chat tool can show."
        : rating === "med"
          ? "Some retrieved clauses fall below the high-confidence threshold — the answer may need a human pass on the lower-similarity rows."
          : "Either no clauses matched the query or none scored above the floor — treat the answer as a stub.";

      const asstId = `m_${Date.now() + 1}`;
      const asstMsg = {
        role: "assistant", text: answer, id: asstId,
        verdict: { rating, coverage: Number(coverage.toFixed(2)), justification, bounds },
        citations: cites,
        question: q,
      };
      setMessages((m) => [...m, asstMsg]);

      /* Persist the verdict for audit. */
      fetch("/api/contracts/chat/verdict", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message_id: asstId, session_id: projectRid || "anon",
          project_rid: projectRid, rating,
          coverage: Number(coverage.toFixed(2)),
          justification, bounds,
        }),
      }).catch(() => {});
    } catch (exc) {
      setMessages((m) => [...m, {
        role: "assistant",
        text: `Error: ${exc.message || exc}`,
        id: `m_err_${Date.now()}`,
        verdict: { rating: "low", justification: String(exc), bounds: [] },
        citations: [],
        question: q,
      }]);
    } finally {
      setPending(false);
      setTimeout(() => chatBottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  }, [input, pending, projectRid]);

  /* ── upload draft ──────────────────────────────────────────── */
  const onUpload = async (documentRid, file, versionLabel) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("version_label", versionLabel || `v${(drafts[documentRid]?.length || 0) + 1}`);
    const res = await fetch(`/api/contracts/documents/${encodeURIComponent(documentRid)}/drafts`, {
      method: "POST", body: fd,
    });
    const data = await res.json();
    setDrafts((prev) => ({
      ...prev,
      [documentRid]: [...(prev[documentRid] || []), { draft_rid: data.draft_rid, version_label: fd.get("version_label"), uploaded_at: new Date().toISOString() }],
    }));
    return data;
  };

  const onNewDocument = async () => {
    const title = prompt("Document title (e.g. 'Common Terms Agreement')");
    if (!title) return;
    const kind = prompt("Kind (CTA / OEM / EPC / PPA / GridAgreement / OTHER)", "CTA") || "OTHER";
    const res = await fetch("/api/contracts/documents", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_rid: projectRid, kind, title }),
    });
    const doc = await res.json();
    setDocuments((d) => [doc, ...d]);
  };

  const openDiff = async () => {
    const docsWithMulti = documents.filter((d) => (drafts[d.document_rid]?.length || 0) >= 2);
    if (!docsWithMulti.length) { alert("No document has two drafts to diff yet."); return; }
    setDiffOpen({ document: docsWithMulti[0], result: null });
    const [a, b] = drafts[docsWithMulti[0].document_rid].slice(0, 2);
    const res = await fetch("/api/contracts/diff", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ draft_rid_a: a.draft_rid, draft_rid_b: b.draft_rid }),
    });
    const result = await res.json();
    setDiffOpen((cur) => ({ ...(cur || {}), result }));
  };

  return (
    <div className="ci-root">
      {/* Documents column */}
      <div className="ci-docs">
        <div className="ci-docs-head">
          <div className="ci-docs-title">Documents</div>
          <button className="ci-btn ci-btn-ghost" onClick={onNewDocument}>+ New</button>
        </div>
        {documents.length === 0 ? (
          <div className="ci-empty">
            <div>No documents yet</div>
            <button className="ci-btn" onClick={onNewDocument}>Create the first one</button>
          </div>
        ) : (
          <ul className="ci-doc-list">
            {documents.map((d) => (
              <DocumentRow
                key={d.document_rid}
                doc={d}
                drafts={drafts[d.document_rid] || []}
                selected={selectedDocs.includes(d.document_rid)}
                onToggleSelect={() =>
                  setSelectedDocs((s) =>
                    s.includes(d.document_rid)
                      ? s.filter((x) => x !== d.document_rid)
                      : [...s, d.document_rid]
                  )
                }
                onUpload={(file, lbl) => onUpload(d.document_rid, file, lbl)}
              />
            ))}
          </ul>
        )}
        {alerts.length > 0 && (
          <div className="ci-alerts">
            <div className="ci-alerts-head">Change alerts ({alerts.length})</div>
            {alerts.slice(0, 5).map((a) => (
              <div key={a.alert_rid} className="ci-alert">
                {a.summary}
              </div>
            ))}
          </div>
        )}
        <div className="ci-docs-foot">
          <button className="ci-btn ci-btn-ghost" onClick={openDiff}>Compare drafts</button>
          <button className="ci-btn ci-btn-ghost" onClick={async () => {
            if (!projectRid) return;
            const res = await fetch(`/api/contracts/projects/${encodeURIComponent(projectRid)}/scan`, { method: "POST" });
            const out = await res.json();
            alert(`Scan complete — ${out.alerts?.length || 0} change alerts emitted`);
            fetch(`/api/contracts/projects/${encodeURIComponent(projectRid)}/alerts`)
              .then((r) => r.json()).then((d) => setAlerts(d.items || []));
          }}>Re-scan project</button>
        </div>
      </div>

      {/* Chat column */}
      <div className="ci-chat">
        <div className="ci-chat-head">
          <span className="ci-chat-crumb">CAIRN-style · {projectName || "Project"}</span>
          <span className="ci-chat-sub">Contract Intelligence</span>
        </div>
        <div className="ci-chat-body">
          {messages.length === 0 && (
            <div className="ci-msg ci-asst">
              <div className="ci-asst-name">PRINCEPS AI</div>
              <div className="ci-asst-text">Hi. Ask me anything about the documents loaded into this project — I'll cite §section · page with verbatim text.</div>
            </div>
          )}
          {messages.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="ci-msg ci-user">
                <div className="ci-user-name">YOU</div>
                <div className="ci-user-text">{m.text}</div>
              </div>
            ) : (
              <div key={m.id} className="ci-msg ci-asst">
                <div className="ci-asst-head">
                  <span className="ci-asst-name">PRINCEPS AI</span>
                  <span className={`ci-pill ci-pill-${m.verdict?.rating || "low"}`}>
                    confidence&nbsp;<b>{(m.verdict?.rating || "low").toUpperCase()}</b>
                  </span>
                  <button
                    className="ci-justify-btn"
                    onClick={() => setActiveRail({ question: m.question, citations: m.citations || [], verdict: m.verdict })}
                  >
                    JUSTIFY →
                  </button>
                </div>
                <div className="ci-asst-text">{m.text}</div>
              </div>
            )
          )}
          {pending && <div className="ci-pending">Thinking…</div>}
          <div ref={chatBottomRef} />
        </div>
        <div className="ci-chat-input">
          <input
            type="text"
            placeholder="Ask a follow-up…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") send(); }}
            disabled={pending}
          />
          <div className="ci-chat-hint">PRESS ENTER TO SEND</div>
        </div>
      </div>

      {/* Right rail (Justifying) */}
      {activeRail && (
        <div className="ci-rail">
          <div className="ci-rail-head">
            <span className="ci-rail-title">JUSTIFYING</span>
            <button className="ci-rail-close" onClick={() => setActiveRail(null)}>×</button>
          </div>
          <div className="ci-rail-q">{activeRail.question}</div>

          <div className="ci-rail-section">
            <div className="ci-rail-section-head">RATING</div>
            <div className="ci-rating-bar">
              <span className={`ci-rating-step ${activeRail.verdict?.rating === "low" ? "active" : ""}`}>LOW</span>
              <span className={`ci-rating-step ${activeRail.verdict?.rating === "med" ? "active" : ""}`}>MEDIUM</span>
              <span className={`ci-rating-step ${activeRail.verdict?.rating === "high" ? "active" : ""}`}>HIGH</span>
            </div>
            <div className="ci-rail-just">{activeRail.verdict?.justification}</div>
            {(activeRail.verdict?.bounds || []).map((b, i) => (
              <div key={i} className="ci-rail-bound">⚠ {b}</div>
            ))}
          </div>

          <div className="ci-rail-section">
            <div className="ci-rail-section-head">CITATIONS</div>
            {(activeRail.citations || []).length === 0 ? (
              <div className="ci-rail-empty">No citations.</div>
            ) : (
              activeRail.citations.map((c, idx) => (
                <div key={c.clause_rid} className="ci-cite">
                  <div className="ci-cite-no">{String(idx + 1).padStart(2, "0")}</div>
                  <div className="ci-cite-body">
                    <div className="ci-cite-meta">
                      {c.section || "—"} · P.{c.page || "?"}
                      {c.similarity != null && (
                        <span className="ci-cite-sim"> · sim {Number(c.similarity).toFixed(2)}</span>
                      )}
                    </div>
                    <div className="ci-cite-text">"{c.verbatim}"</div>
                  </div>
                </div>
              ))
            )}
          </div>

          <div className="ci-rail-section">
            <div className="ci-rail-section-head">SOURCES</div>
            <div className="ci-rail-sources">
              {documents.map((d) => (
                <div key={d.document_rid} className="ci-rail-source-row">
                  <span>{d.title}</span>
                  <span>{(drafts[d.document_rid]?.length || 0)} drafts</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Diff overlay */}
      {diffOpen && diffOpen.result && (
        <div className="ci-diff" onClick={(e) => { if (e.target.classList.contains("ci-diff")) setDiffOpen(false); }}>
          <div className="ci-diff-card">
            <div className="ci-diff-head">
              <div>
                <div className="ci-diff-title">{diffOpen.document.title} — draft comparison</div>
                <div className="ci-diff-sub">
                  {diffOpen.result.summary.unchanged} unchanged · {diffOpen.result.summary.modified} modified · {diffOpen.result.summary.added} added · {diffOpen.result.summary.removed} removed
                </div>
              </div>
              <button className="ci-rail-close" onClick={() => setDiffOpen(false)}>×</button>
            </div>
            <div className="ci-diff-body">
              {(diffOpen.result.deltas || []).filter((d) => d.status !== "unchanged").map((d) => (
                <div key={`${d.section}-${d.status}`} className={`ci-diff-row ci-diff-${d.status}`}>
                  <div className="ci-diff-row-head">
                    {d.status.toUpperCase()} · §{d.section || "—"} · {d.heading || ""}
                  </div>
                  <div className="ci-diff-sides">
                    <div className="ci-diff-side">
                      <div className="ci-diff-side-label">A (p.{d.page_a ?? "—"})</div>
                      <pre>{d.verbatim_a || "(removed)"}</pre>
                    </div>
                    <div className="ci-diff-side">
                      <div className="ci-diff-side-label">B (p.{d.page_b ?? "—"})</div>
                      <pre>{d.verbatim_b || "(added)"}</pre>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <style>{`
        .ci-root {
          display: grid;
          grid-template-columns: 280px 1fr auto;
          height: 100%; min-height: 480px;
          background: var(--bg, #0a0a0a);
          color: var(--ink, #e7e7e7);
          font-family: "DM Sans", -apple-system, sans-serif;
        }
        .ci-docs {
          border-right: 1px solid #1f1f1f;
          display: flex; flex-direction: column;
          padding: 12px;
          background: #0d0d0d;
        }
        .ci-docs-head { display:flex; justify-content:space-between; align-items:center; margin-bottom: 12px; }
        .ci-docs-title { font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; color: #C9A64B; }
        .ci-doc-list { list-style: none; margin: 0; padding: 0; overflow: auto; flex: 1; }
        .ci-empty { padding: 16px; color: #8d8d8d; font-size: 13px; text-align: center; display:flex; flex-direction:column; gap: 8px; }
        .ci-btn { padding: 6px 10px; border-radius: 6px; border: 1px solid #2a2a2a; background: #161616; color: #e7e7e7; font-size: 12px; cursor: pointer; }
        .ci-btn:hover { background: #1d1d1d; }
        .ci-btn-ghost { background: transparent; }
        .ci-docs-foot { display: flex; gap: 6px; padding-top: 8px; border-top: 1px solid #1f1f1f; }
        .ci-alerts { margin-top: 10px; padding-top: 10px; border-top: 1px solid #1f1f1f; }
        .ci-alerts-head { font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; color: #C9A64B; margin-bottom: 6px; }
        .ci-alert { font-size: 12px; color: #c0c0c0; padding: 4px 0; border-bottom: 1px solid #161616; }
        .ci-doc-row { padding: 8px; border: 1px solid #1f1f1f; border-radius: 8px; margin-bottom: 8px; }
        .ci-doc-row-head { display:flex; justify-content:space-between; align-items:center; }
        .ci-doc-row-title { font-size: 13px; font-weight: 600; }
        .ci-doc-row-kind { font-size: 10px; color: #C9A64B; }
        .ci-doc-row-meta { font-size: 11px; color: #8d8d8d; margin-top: 4px; }
        .ci-doc-row-upload { margin-top: 6px; }
        .ci-doc-row-upload input { font-size: 11px; }

        .ci-chat {
          display:flex; flex-direction: column;
          background: #0a0a0a;
        }
        .ci-chat-head {
          padding: 14px 18px; border-bottom: 1px solid #1f1f1f;
          display: flex; align-items: baseline; gap: 12px;
        }
        .ci-chat-crumb { font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; color: #C9A64B; font-weight: 600; }
        .ci-chat-sub { font-size: 11px; color: #8d8d8d; text-transform: uppercase; letter-spacing: 0.05em; }
        .ci-chat-body { flex: 1; overflow: auto; padding: 16px 24px; display: flex; flex-direction: column; gap: 16px; }
        .ci-msg { display:flex; flex-direction: column; gap: 4px; }
        .ci-user-name, .ci-asst-name { font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; color: #8d8d8d; }
        .ci-user-text, .ci-asst-text { font-size: 14px; line-height: 1.55; color: #e7e7e7; }
        .ci-asst-head { display:flex; align-items:center; gap: 10px; }
        .ci-pill { padding: 2px 8px; border-radius: 999px; font-size: 10px; letter-spacing: 0.05em; }
        .ci-pill-high { background: rgba(106,187,107,0.15); color: #6abb6b; border: 1px solid #6abb6b; }
        .ci-pill-med  { background: rgba(201,166,75,0.15); color: #C9A64B; border: 1px solid #C9A64B; }
        .ci-pill-low  { background: rgba(220,90,90,0.15);  color: #dc5a5a; border: 1px solid #dc5a5a; }
        .ci-justify-btn {
          background: transparent; border: 1px solid #2a2a2a;
          padding: 2px 8px; border-radius: 6px;
          color: #C9A64B; font-size: 10px; letter-spacing: 0.06em; cursor: pointer;
        }
        .ci-pending { font-size: 12px; color: #8d8d8d; padding: 4px 0; }
        .ci-chat-input {
          padding: 12px 18px; border-top: 1px solid #1f1f1f;
          display: flex; flex-direction: column; gap: 4px;
        }
        .ci-chat-input input {
          width: 100%; background: transparent; border: none;
          color: #e7e7e7; font-size: 14px; padding: 8px 0;
          outline: none;
        }
        .ci-chat-hint { font-size: 9px; letter-spacing: 0.08em; color: #5a5a5a; }

        .ci-rail {
          width: 380px; background: #0d0d0d;
          border-left: 1px solid #1f1f1f;
          padding: 16px;
          overflow: auto;
          display: flex; flex-direction: column;
        }
        .ci-rail-head { display:flex; justify-content:space-between; align-items:center; }
        .ci-rail-title { font-size: 10px; letter-spacing: 0.08em; color: #C9A64B; }
        .ci-rail-close { background: transparent; border: none; color: #8d8d8d; font-size: 20px; cursor: pointer; }
        .ci-rail-q { font-size: 13px; color: #e7e7e7; padding: 8px 0 16px; border-bottom: 1px solid #1f1f1f; }
        .ci-rail-section { margin-top: 14px; }
        .ci-rail-section-head { font-size: 10px; letter-spacing: 0.08em; color: #C9A64B; padding: 6px 0; border-bottom: 1px solid #1f1f1f; }
        .ci-rating-bar { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; margin: 10px 0; }
        .ci-rating-step {
          background: #161616; padding: 6px 4px; text-align: center;
          font-size: 10px; letter-spacing: 0.05em; color: #5a5a5a;
          border: 1px solid #2a2a2a;
        }
        .ci-rating-step.active { background: #1d2a1d; color: #6abb6b; border-color: #6abb6b; font-weight: 700; }
        .ci-rating-step.active:nth-child(1) { background: #2a1d1d; color: #dc5a5a; border-color: #dc5a5a; }
        .ci-rating-step.active:nth-child(2) { background: #2a261d; color: #C9A64B; border-color: #C9A64B; }
        .ci-rail-just { font-size: 12px; color: #c0c0c0; line-height: 1.55; margin-top: 6px; }
        .ci-rail-bound { font-size: 11px; color: #C9A64B; margin-top: 4px; }
        .ci-rail-empty { font-size: 12px; color: #5a5a5a; padding: 12px 0; }
        .ci-cite { display: flex; gap: 10px; padding: 10px 0; border-bottom: 1px solid #161616; }
        .ci-cite-no { font-size: 10px; color: #C9A64B; min-width: 18px; }
        .ci-cite-meta { font-size: 11px; color: #c0c0c0; }
        .ci-cite-sim { color: #8d8d8d; }
        .ci-cite-text { font-size: 12px; color: #e7e7e7; margin-top: 4px; line-height: 1.55; font-style: italic; }
        .ci-rail-sources { display: flex; flex-direction: column; gap: 4px; padding-top: 6px; }
        .ci-rail-source-row { display: flex; justify-content: space-between; font-size: 11px; color: #c0c0c0; padding: 4px 0; border-bottom: 1px solid #161616; }

        .ci-diff { position: fixed; inset: 0; background: rgba(0,0,0,0.7); display:flex; align-items:center; justify-content:center; z-index: 1000; }
        .ci-diff-card { width: min(1100px, 92vw); max-height: 88vh; overflow: auto; background: #0d0d0d; border: 1px solid #2a2a2a; border-radius: 12px; padding: 16px; }
        .ci-diff-head { display:flex; justify-content:space-between; align-items:flex-start; padding-bottom: 12px; border-bottom: 1px solid #1f1f1f; }
        .ci-diff-title { font-size: 14px; color: #C9A64B; }
        .ci-diff-sub { font-size: 11px; color: #8d8d8d; margin-top: 2px; }
        .ci-diff-body { padding-top: 12px; display:flex; flex-direction: column; gap: 12px; }
        .ci-diff-row { border: 1px solid #1f1f1f; border-radius: 8px; padding: 10px; }
        .ci-diff-row-head { font-size: 11px; letter-spacing: 0.05em; color: #C9A64B; margin-bottom: 6px; }
        .ci-diff-sides { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .ci-diff-side pre { white-space: pre-wrap; word-break: break-word; font-size: 11px; background: #0a0a0a; padding: 8px; border-radius: 6px; max-height: 280px; overflow: auto; color: #c0c0c0; margin: 0; }
        .ci-diff-side-label { font-size: 10px; color: #8d8d8d; margin-bottom: 4px; }
        .ci-diff-modified .ci-diff-row-head { color: #C9A64B; }
        .ci-diff-added    .ci-diff-row-head { color: #6abb6b; }
        .ci-diff-removed  .ci-diff-row-head { color: #dc5a5a; }
      `}</style>
    </div>
  );
}

function DocumentRow({ doc, drafts, selected, onToggleSelect, onUpload }) {
  const fileRef = useRef(null);
  return (
    <li className="ci-doc-row">
      <div className="ci-doc-row-head">
        <label style={{ display:"flex", alignItems:"center", gap:6, cursor:"pointer" }}>
          <input type="checkbox" checked={selected} onChange={onToggleSelect} />
          <span className="ci-doc-row-title">{doc.title}</span>
        </label>
        <span className="ci-doc-row-kind">{doc.kind}</span>
      </div>
      <div className="ci-doc-row-meta">{drafts.length} draft{drafts.length === 1 ? "" : "s"}</div>
      <div className="ci-doc-row-upload">
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf"
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            await onUpload(f, `v${drafts.length + 1}`);
            if (fileRef.current) fileRef.current.value = "";
          }}
        />
      </div>
    </li>
  );
}
