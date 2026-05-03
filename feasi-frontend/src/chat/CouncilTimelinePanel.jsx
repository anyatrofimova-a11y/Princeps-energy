/**
 * CouncilTimelinePanel — vertical event stream rendering for the
 * Princeps AI ChatRail when a query has been routed to the Council
 * surface (GRID + BESS + DC pods + Adjudicator).
 *
 * Reads the SSE events array + reduced state shape from
 * useCouncilDispatch and renders one row per event with pod chip,
 * status, optional verdict pill, and an expandable tools section.
 *
 * Princeps tokens — cream, gold, glass shadow, DM Sans, JetBrains
 * Mono numbers. No emojis.
 */

import React, { useState } from "react";

const POD_LABEL = {
  grid: "GRID",
  bess: "BESS",
  dc: "DC",
  adjudicator: "ADJ",
};

const VERDICT_COLOR = {
  GO: "var(--cds-support-success, #10B981)",
  CAUTION: "var(--cds-support-warning, #F59E0B)",
  "NO-GO": "var(--cds-support-error, #EF4444)",
};

function podBadge(pod) {
  const label = POD_LABEL[pod] || (pod || "").toUpperCase();
  return (
    <span className="ctp-chip" data-pod={pod}>
      {label}
    </span>
  );
}

function statusBadge(status) {
  const map = { running: "running", complete: "done", error: "error" };
  return <span className={`ctp-status ctp-status-${status || "pending"}`}>{map[status] || status || "pending"}</span>;
}

function verdictPill(v) {
  if (!v) return null;
  const c = VERDICT_COLOR[v.verdict] || "var(--cds-text-helper)";
  return (
    <span className="ctp-verdict" style={{ color: c, borderColor: c }}>
      {v.verdict} {v.confidence != null ? `${(v.confidence * 100) | 0}%` : ""}
    </span>
  );
}

function eventTitle(evt) {
  switch (evt.type) {
    case "session_started":
      return `Council session opened (${(evt.pods || []).join(", ")})`;
    case "pod_started":
      return `${POD_LABEL[evt.pod] || evt.pod} pod started`;
    case "pod_verdict":
      return `${POD_LABEL[evt.pod] || evt.pod} returned verdict`;
    case "pod_error":
      return `${POD_LABEL[evt.pod] || "pod"} errored`;
    case "adjudication":
      return `Adjudication ${evt.stage || ""}`.trim();
    case "clarification_needed":
      return "Clarification requested";
    case "final_verdict":
      return "Final verdict";
    case "done":
      return "Session complete";
    case "error":
      return "Stream error";
    default:
      return evt.type || "event";
  }
}

function eventSummary(evt) {
  if (evt.type === "pod_verdict" && evt.verdict?.summary) return evt.verdict.summary;
  if (evt.type === "final_verdict" && evt.result?.rationale) return evt.result.rationale;
  if (evt.type === "clarification_needed" && evt.question) return evt.question;
  if (evt.type === "pod_error" && evt.error) return String(evt.error).slice(0, 200);
  if (evt.type === "error" && evt.message) return evt.message;
  return null;
}

function EventRow({ evt, idx }) {
  const [open, setOpen] = useState(false);
  const pod = evt.pod || (evt.type === "final_verdict" || evt.type === "adjudication" ? "adjudicator" : null);
  const v = evt.verdict || (evt.type === "final_verdict" ? evt.result : null);
  const summary = eventSummary(evt);
  const trace = evt.trace || null;
  const expandable = !!trace || !!summary;
  return (
    <li className="ctp-row">
      <div className="ctp-rail">
        <span className="ctp-dot" data-type={evt.type} />
        <span className="ctp-line" />
      </div>
      <div className="ctp-body">
        <button type="button" className="ctp-head" onClick={() => expandable && setOpen((x) => !x)}>
          <span className="ctp-idx">{String(idx + 1).padStart(2, "0")}</span>
          {pod && podBadge(pod)}
          <span className="ctp-title">{eventTitle(evt)}</span>
          {evt.type === "pod_verdict" && verdictPill(v)}
          {evt.type === "final_verdict" && verdictPill(v)}
          {evt.type === "pod_started" && statusBadge("running")}
          {evt.type === "pod_verdict" && statusBadge("complete")}
          {evt.type === "pod_error" && statusBadge("error")}
        </button>
        {summary && (
          <div className="ctp-summary">{summary}</div>
        )}
        {expandable && open && (
          <div className="ctp-details">
            {trace && Array.isArray(trace.tool_calls) && trace.tool_calls.length > 0 && (
              <div className="ctp-tools">
                <div className="ctp-tools-h">Tools</div>
                {trace.tool_calls.map((tc, i) => (
                  <div key={i} className="ctp-tool">
                    <span className="ctp-tool-name">{tc.name}</span>
                    {tc.result != null && (
                      <pre className="ctp-tool-out">
                        {(typeof tc.result === "string" ? tc.result : JSON.stringify(tc.result)).slice(0, 200)}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

export default function CouncilTimelinePanel({
  events,
  state,
  classification,
  onBack,
  onViewFull,
}) {
  const final = state?.final || null;
  const sessionRid = state?.session_rid || null;
  const verdict = final?.verdict || null;
  const confidence = final?.confidence != null ? final.confidence.toFixed(2) : "—";
  const domains = classification?.domains || [];

  return (
    <div className="ctp-root">
      <div className="ctp-banner">
        <div className="ctp-banner-l">
          <span className="ctp-banner-dot" />
          <span className="ctp-banner-title">Council mode</span>
          {domains.length > 0 && (
            <span className="ctp-banner-doms">
              {domains.map((d) => (
                <span key={d} className="ctp-banner-dom">{d}</span>
              ))}
            </span>
          )}
        </div>
        <button type="button" className="ctp-back" onClick={onBack}>back to chat</button>
      </div>

      <ol className="ctp-list">
        {events.length === 0 && (
          <li className="ctp-empty">opening session...</li>
        )}
        {events.map((evt, i) => (
          <EventRow key={i} idx={i} evt={evt} />
        ))}
      </ol>

      <div className="ctp-footer">
        <div className="ctp-footer-l">
          {final ? (
            <span>
              Final verdict:{" "}
              <span style={{ color: VERDICT_COLOR[verdict] || "inherit", fontWeight: 700 }}>
                {verdict}
              </span>{" "}
              <span className="ctp-conf">at confidence {confidence}</span>
            </span>
          ) : (
            <span className="ctp-pending">awaiting adjudication...</span>
          )}
        </div>
        {sessionRid && (
          <a
            className="ctp-link"
            href={`/v2/council/${encodeURIComponent(sessionRid)}`}
            onClick={(e) => { if (onViewFull) { e.preventDefault(); onViewFull(sessionRid); } }}
          >
            view full session
          </a>
        )}
      </div>

      <style>{ctpCSS}</style>
    </div>
  );
}

const ctpCSS = `
.ctp-root {
  display: flex; flex-direction: column;
  height: 100%; min-height: 0;
  background: var(--cds-layer-01);
  font-family: "DM Sans", -apple-system, sans-serif;
  color: var(--cds-text-primary);
}
.ctp-banner {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--cds-border-subtle);
  background: linear-gradient(180deg, rgba(var(--accent-rgb), 0.08), rgba(var(--accent-rgb), 0.02));
  flex-shrink: 0;
}
.ctp-banner-l { display: flex; align-items: center; gap: 8px; min-width: 0; }
.ctp-banner-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--gold);
  box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.25);
}
.ctp-banner-title {
  font-size: 12px; font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--ink);
}
.ctp-banner-doms { display: inline-flex; gap: 4px; flex-wrap: wrap; }
.ctp-banner-dom {
  font-family: var(--mono, "JetBrains Mono", monospace);
  font-size: 9.5px; letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 2px 6px; border-radius: 4px;
  background: rgba(var(--accent-rgb), 0.10);
  color: var(--ink);
  border: 1px solid rgba(var(--accent-rgb), 0.25);
}
.ctp-back {
  background: none; border: 1px solid var(--cds-border-subtle);
  color: var(--cds-text-secondary);
  font-size: 11px; padding: 4px 10px; border-radius: 999px;
  cursor: pointer; font-family: inherit;
}
.ctp-back:hover { border-color: var(--gold); color: var(--ink); }
.ctp-list {
  list-style: none; margin: 0; padding: 12px 14px 4px;
  flex: 1; min-height: 0; overflow-y: auto;
}
.ctp-empty {
  font-size: 12px; color: var(--cds-text-helper);
  padding: 24px 0; text-align: center;
}
.ctp-row { display: flex; gap: 10px; padding: 6px 0; }
.ctp-rail {
  display: flex; flex-direction: column; align-items: center;
  width: 12px; padding-top: 6px;
}
.ctp-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--gold);
  box-shadow: 0 0 0 2px rgba(var(--accent-rgb), 0.18);
}
.ctp-dot[data-type="pod_started"] { background: var(--cds-text-helper); }
.ctp-dot[data-type="pod_verdict"] { background: var(--gold); }
.ctp-dot[data-type="final_verdict"] { background: var(--cds-support-success, #10B981); }
.ctp-dot[data-type="pod_error"], .ctp-dot[data-type="error"] { background: var(--cds-support-error, #EF4444); }
.ctp-line {
  flex: 1; width: 1px;
  background: var(--cds-border-subtle);
  margin-top: 4px;
}
.ctp-body { flex: 1; min-width: 0; }
.ctp-head {
  width: 100%;
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  background: none; border: none; padding: 4px 0;
  font-family: inherit; cursor: pointer;
  text-align: left; color: inherit;
}
.ctp-head:hover { color: var(--ink); }
.ctp-idx {
  font-family: var(--mono, "JetBrains Mono", monospace);
  font-size: 10px; color: var(--cds-text-helper);
  letter-spacing: 0.04em;
}
.ctp-chip {
  font-family: var(--mono, "JetBrains Mono", monospace);
  font-size: 9.5px; letter-spacing: 0.08em; font-weight: 700;
  padding: 2px 6px; border-radius: 4px;
  background: var(--cds-layer-02);
  border: 1px solid var(--cds-border-subtle);
  color: var(--ink);
}
.ctp-chip[data-pod="adjudicator"] {
  background: rgba(var(--accent-rgb), 0.12);
  border-color: var(--gold);
  color: var(--ink);
}
.ctp-title { font-size: 12.5px; font-weight: 600; flex: 1; }
.ctp-status {
  font-family: var(--mono, "JetBrains Mono", monospace);
  font-size: 9.5px; letter-spacing: 0.06em;
  padding: 2px 6px; border-radius: 4px;
  background: var(--cds-layer-02);
  color: var(--cds-text-secondary);
}
.ctp-status-running { color: var(--gold); }
.ctp-status-error { color: var(--cds-support-error, #EF4444); }
.ctp-status-done { color: var(--cds-support-success, #10B981); }
.ctp-verdict {
  font-family: var(--mono, "JetBrains Mono", monospace);
  font-size: 10px; font-weight: 700; letter-spacing: 0.06em;
  padding: 2px 7px; border-radius: 999px;
  border: 1px solid var(--cds-border-subtle);
  background: rgba(0,0,0,0);
}
.ctp-summary {
  font-size: 12px; line-height: 1.45;
  color: var(--cds-text-secondary);
  padding: 2px 0 4px 0;
}
.ctp-details { margin-top: 4px; }
.ctp-tools-h {
  font-family: var(--mono, "JetBrains Mono", monospace);
  font-size: 9.5px; letter-spacing: 0.08em;
  color: var(--cds-text-helper);
  margin-bottom: 4px;
}
.ctp-tool {
  display: flex; flex-direction: column; gap: 2px;
  margin-bottom: 6px;
  padding: 6px 8px;
  background: var(--cds-layer-02);
  border: 1px solid var(--cds-border-subtle);
  border-radius: 6px;
}
.ctp-tool-name {
  font-family: var(--mono, "JetBrains Mono", monospace);
  font-size: 11px; color: var(--ink); font-weight: 600;
}
.ctp-tool-out {
  margin: 0; padding: 0;
  font-family: var(--mono, "JetBrains Mono", monospace);
  font-size: 10px;
  color: var(--cds-text-secondary);
  white-space: pre-wrap; word-wrap: break-word;
  max-height: 100px; overflow-y: auto;
}
.ctp-footer {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px;
  border-top: 1px solid var(--cds-border-subtle);
  background: var(--cds-layer-01);
  font-size: 12px; color: var(--cds-text-secondary);
  flex-shrink: 0;
}
.ctp-conf {
  font-family: var(--mono, "JetBrains Mono", monospace);
  font-size: 11px; color: var(--cds-text-helper);
}
.ctp-pending { color: var(--cds-text-helper); }
.ctp-link {
  font-size: 11.5px; color: var(--gold);
  text-decoration: none;
  border-bottom: 1px dashed rgba(var(--accent-rgb), 0.4);
}
.ctp-link:hover { color: var(--gold-dark, var(--gold)); }
`;
