import React, { useEffect, useMemo, useState } from "react";
import { buildFilingsTimeline, STAGES } from "../lib/stage_workflow";

/**
 * FilingsTimeline — vertical timeline of planning filings, grid applications
 * and environmental notices tied to a project. Reads (in order):
 *   1. GET /api/projects/{id}/filings
 *   2. GET /api/planning/filings?project_id=
 *   3. derived schedule from stage_workflow.buildFilingsTimeline(project)
 *
 * Clicking a row opens a side drawer with the decision letter / response
 * body inline. Status derives from project stage when no live data lands.
 *
 * Light-gold palette, sticky stage dots on the left spine.
 */

const STATUS_STYLE = {
  locked:    { bg: "var(--cds-layer-03)",    fg: "var(--cds-text-helper)",     label: "Locked",    dot: "var(--cds-layer-03)" },
  drafting:  { bg: "rgba(232,160,18,0.14)",  fg: "var(--cds-support-warning)", label: "Drafting",  dot: "var(--cds-support-warning)" },
  submitted: { bg: "rgba(45,108,176,0.14)",  fg: "#2D6CB0",                    label: "Submitted", dot: "#2D6CB0" },
  approved:  { bg: "rgba(22,163,74,0.14)",   fg: "var(--cds-support-success)", label: "Approved",  dot: "var(--cds-support-success)" },
  rejected:  { bg: "rgba(220,38,38,0.14)",   fg: "var(--cds-support-error)",   label: "Rejected",  dot: "var(--cds-support-error)" },
  overdue:   { bg: "rgba(220,38,38,0.18)",   fg: "var(--cds-support-error)",   label: "Overdue",   dot: "var(--cds-support-error)" },
};

const FILTERS = [
  { key: "all",       label: "All"       },
  { key: "active",    label: "Active"    },
  { key: "submitted", label: "Submitted" },
  { key: "locked",    label: "Locked"    },
];

function normaliseRemote(items) {
  // Map whatever the API returns onto the shape the UI consumes.
  if (!Array.isArray(items)) return [];
  return items.map((it, i) => ({
    code: it.code || it.id || String(i),
    name: it.name || it.title || it.filing_type || "Filing",
    status: (it.status || "drafting").toLowerCase(),
    require_stage: it.require_stage || it.stage_label || it.stage || "",
    unlock_stage: it.unlock_stage || "",
    doc_template: it.doc_template || it.template || "",
    submitted_at: it.submitted_at || it.filed_at || it.date || null,
    decision: it.decision || null,
    decision_letter: it.decision_letter || it.letter || it.body || null,
    reference: it.reference || it.ref || null,
    authority: it.authority || it.lpa || it.dno || null,
    url: it.url || it.link || null,
  }));
}

function fmtDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch { return ""; }
}

function FilingDrawer({ filing, onClose }) {
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  if (!filing) return null;
  const s = STATUS_STYLE[filing.status] || STATUS_STYLE.drafting;
  return (
    <div className="ftx-drawer-wrap" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="ftx-drawer" role="dialog" aria-modal="true" aria-label={filing.name}>
        <header className="ftx-drawer-head">
          <div className="ftx-drawer-eyebrow">{filing.authority || filing.require_stage || "Filing"}</div>
          <h3 className="ftx-drawer-title">{filing.name}</h3>
          <button className="ftx-drawer-close" onClick={onClose} aria-label="Close">{"\u00D7"}</button>
        </header>
        <div className="ftx-drawer-meta">
          <span className="ftx-drawer-status" style={{ background: s.bg, color: s.fg }}>{s.label}</span>
          {filing.reference && <span className="ftx-drawer-ref">Ref: {filing.reference}</span>}
          {filing.submitted_at && <span className="ftx-drawer-ts">Filed {fmtDate(filing.submitted_at)}</span>}
        </div>
        <section className="ftx-drawer-body">
          {filing.decision_letter ? (
            <pre className="ftx-drawer-letter">{filing.decision_letter}</pre>
          ) : filing.decision ? (
            <div className="ftx-drawer-decision">
              <div className="ftx-drawer-decision-label">Decision</div>
              <div className="ftx-drawer-decision-val">{filing.decision}</div>
            </div>
          ) : (
            <div className="ftx-drawer-empty">
              <div className="ftx-drawer-empty-title">No decision letter yet</div>
              <div className="ftx-drawer-empty-sub">
                This filing is in status "{s.label}". When the authority returns a
                response it will appear here inline.
              </div>
              {filing.doc_template && (
                <div className="ftx-drawer-tpl">
                  <span className="ftx-drawer-tpl-lbl">Template</span>
                  <code>{filing.doc_template}</code>
                </div>
              )}
            </div>
          )}
        </section>
        {filing.url && (
          <footer className="ftx-drawer-foot">
            <a className="ftx-drawer-link" href={filing.url} target="_blank" rel="noreferrer">
              Open source document {"\u2197"}
            </a>
          </footer>
        )}
      </aside>
    </div>
  );
}

export default function FilingsTimeline({
  project = null,
  projectId = null,
  compact = false,
  title = "Filings & applications",
}) {
  const [remote, setRemote] = useState(null);
  const [remoteErr, setRemoteErr] = useState(null);
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(null);

  const pid = projectId || project?.project_id || null;

  useEffect(() => {
    if (!pid) return;
    let cancelled = false;
    (async () => {
      // Primary — project-specific endpoint (future)
      try {
        const res = await fetch(`/api/projects/${pid}/filings`);
        if (res.ok) {
          const j = await res.json();
          const items = Array.isArray(j) ? j : (j.filings || j.items || []);
          if (!cancelled && items.length) { setRemote(normaliseRemote(items)); return; }
        }
      } catch {}
      // Secondary — planning filings table
      try {
        const res = await fetch(`/api/planning/filings?project_id=${encodeURIComponent(pid)}`);
        if (res.ok) {
          const j = await res.json();
          const items = Array.isArray(j) ? j : (j.filings || j.items || []);
          if (!cancelled && items.length) { setRemote(normaliseRemote(items)); return; }
        }
      } catch (e) {
        if (!cancelled) setRemoteErr(e.message || null);
      }
      if (!cancelled) setRemote([]);  // mark as fetched but empty
    })();
    return () => { cancelled = true; };
  }, [pid]);

  const derived = useMemo(() => buildFilingsTimeline(project), [project]);
  const items = (remote && remote.length) ? remote : derived;

  const counts = useMemo(() => {
    const c = { all: items.length, active: 0, submitted: 0, locked: 0 };
    items.forEach((i) => {
      if (i.status === "drafting") c.active++;
      if (i.status === "submitted" || i.status === "approved") c.submitted++;
      if (i.status === "locked") c.locked++;
    });
    return c;
  }, [items]);

  const filtered = useMemo(() => {
    if (filter === "all") return items;
    if (filter === "active") return items.filter((i) => i.status === "drafting" || i.status === "overdue");
    if (filter === "submitted") return items.filter((i) => i.status === "submitted" || i.status === "approved");
    if (filter === "locked") return items.filter((i) => i.status === "locked");
    return items;
  }, [items, filter]);

  if (!project) return null;

  return (
    <section className={"ftx-root" + (compact ? " ftx-compact" : "")}>
      <header className="ftx-head">
        <h3 className="ftx-title">{title}</h3>
        <div className="ftx-filters">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              className={"ftx-chip" + (filter === f.key ? " ftx-chip-active" : "")}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
              <span className="ftx-count">{counts[f.key]}</span>
            </button>
          ))}
        </div>
      </header>

      {items.length === 0 ? (
        <div className="ftx-empty">
          <div className="ftx-empty-title">No filings required yet</div>
          <div className="ftx-empty-sub">
            This project doesn't have any filings in its current config. They will
            appear once the stage advances past Prospect.
          </div>
        </div>
      ) : (
        <ol className="ftx-list">
          {filtered.map((it, i) => {
            const s = STATUS_STYLE[it.status] || STATUS_STYLE.drafting;
            const stageLabel = it.status === "locked"
              ? `unlocks @ ${it.unlock_stage || "later"}`
              : (it.require_stage || "any stage");
            return (
              <li key={it.code || i} className={"ftx-item ftx-item-" + it.status}>
                <button
                  type="button"
                  className="ftx-item-btn"
                  onClick={() => setSelected(it)}
                  disabled={it.status === "locked"}
                >
                  <span className="ftx-spine">
                    <span className="ftx-spine-dot" style={{ background: s.dot }} />
                  </span>
                  <span className="ftx-body">
                    <span className="ftx-row-top">
                      <span className="ftx-name">{it.name}</span>
                      <span className="ftx-status" style={{ background: s.bg, color: s.fg }}>{s.label}</span>
                    </span>
                    <span className="ftx-meta">
                      <span>{stageLabel}</span>
                      {it.submitted_at && <span className="ftx-ts">{fmtDate(it.submitted_at)}</span>}
                      {it.authority && <span className="ftx-auth">{it.authority}</span>}
                      {it.doc_template && <span className="ftx-tpl">{it.doc_template}</span>}
                    </span>
                  </span>
                  <span className="ftx-go" aria-hidden="true">
                    {it.status === "locked" ? "\u2014" : "\u2192"}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}

      {remoteErr && remote === null && (
        <div className="ftx-note">Live filings feed unavailable — showing derived schedule.</div>
      )}

      {selected && <FilingDrawer filing={selected} onClose={() => setSelected(null)} />}

      <style>{`
        .ftx-root {
          font-family: "DM Sans", -apple-system, sans-serif;
          display: flex; flex-direction: column; gap: 12px;
        }
        .ftx-head {
          display: flex; align-items: center; justify-content: space-between;
          gap: 12px; flex-wrap: wrap;
        }
        .ftx-title { margin: 0; font-size: 14px; font-weight: 700; color: var(--ink); }
        .ftx-filters { display: flex; gap: 4px; flex-wrap: wrap; }
        .ftx-chip {
          display: inline-flex; align-items: center; gap: 4px;
          padding: 4px 10px;
          border: 1px solid var(--cds-border-subtle);
          border-radius: 6px;
          background: transparent;
          font: inherit; font-size: 11px; font-weight: 600;
          color: var(--cds-text-secondary);
          cursor: pointer;
        }
        .ftx-chip:hover { border-color: var(--gold); color: var(--gold-dark); }
        .ftx-chip-active {
          background: rgba(var(--accent-rgb), 0.1);
          border-color: var(--gold);
          color: var(--gold-dark);
        }
        .ftx-count {
          font-family: var(--mono); font-size: 9px; opacity: 0.75;
        }

        .ftx-list {
          list-style: none; margin: 0; padding: 0;
          display: flex; flex-direction: column; gap: 0;
          position: relative;
        }
        .ftx-list::before {
          content: ""; position: absolute;
          left: 11px; top: 10px; bottom: 10px; width: 2px;
          background: var(--cds-layer-03);
        }
        .ftx-item { position: relative; }
        .ftx-item-btn {
          display: flex; align-items: stretch; gap: 14px;
          width: 100%; padding: 12px 14px 12px 0;
          background: transparent;
          border: none; border-bottom: 1px solid var(--cds-border-subtle);
          font: inherit; text-align: left;
          cursor: pointer;
          transition: background 120ms ease;
        }
        .ftx-item-btn:hover {
          background: rgba(var(--accent-rgb), 0.06);
        }
        .ftx-item-btn:disabled {
          cursor: default;
          opacity: 0.6;
        }
        .ftx-item-btn:disabled:hover { background: transparent; }

        .ftx-spine {
          width: 24px; flex-shrink: 0;
          display: flex; align-items: center; justify-content: center;
        }
        .ftx-spine-dot {
          width: 10px; height: 10px; border-radius: 50%;
          background: var(--cds-layer-03);
          border: 2px solid var(--cds-layer-01);
          box-shadow: 0 0 0 1px var(--cds-border-subtle);
        }

        .ftx-body { flex: 1; min-width: 0; }
        .ftx-row-top {
          display: flex; align-items: center; justify-content: space-between;
          gap: 12px;
        }
        .ftx-name {
          font-size: 13px; font-weight: 600; color: var(--ink);
          overflow: hidden; text-overflow: ellipsis;
        }
        .ftx-status {
          font-family: var(--mono); font-size: 9px; font-weight: 700;
          padding: 2px 7px; border-radius: 4px;
          text-transform: uppercase; letter-spacing: 0.04em;
          flex-shrink: 0;
        }
        .ftx-meta {
          display: flex; flex-wrap: wrap; gap: 10px;
          margin-top: 4px;
          font-size: 11px; color: var(--cds-text-helper);
        }
        .ftx-tpl, .ftx-ts { font-family: var(--mono); }
        .ftx-auth { color: var(--cds-text-secondary); }

        .ftx-go {
          color: var(--cds-text-helper); font-size: 16px;
          flex-shrink: 0; align-self: center;
        }
        .ftx-item-btn:hover .ftx-go { color: var(--gold-dark); }

        .ftx-empty {
          padding: 28px 20px; text-align: center;
          background: var(--cds-layer-02);
          border: 1px dashed var(--cds-border-subtle);
          border-radius: 12px;
        }
        .ftx-empty-title { font-size: 13px; font-weight: 600; color: var(--cds-text-secondary); }
        .ftx-empty-sub { font-size: 12px; color: var(--cds-text-helper); margin-top: 4px; }

        .ftx-note {
          font-size: 11px; color: var(--cds-text-helper);
          padding: 8px 12px;
          background: var(--cds-layer-02);
          border-radius: 6px;
        }

        .ftx-compact .ftx-item-btn { padding: 8px 10px 8px 0; }
        .ftx-compact .ftx-name { font-size: 12px; }

        /* Drawer */
        .ftx-drawer-wrap {
          position: fixed; inset: 0; z-index: 200;
          background: rgba(15,19,24,0.35);
          display: flex; justify-content: flex-end;
          animation: ftx-fade 160ms ease;
        }
        @keyframes ftx-fade { from { background: rgba(15,19,24,0); } to { background: rgba(15,19,24,0.35); } }
        .ftx-drawer {
          width: min(480px, 100%);
          height: 100%;
          background: var(--cds-layer-01);
          border-left: 1px solid var(--cds-border-subtle);
          display: flex; flex-direction: column;
          animation: ftx-slide 200ms cubic-bezier(.2,.8,.2,1);
        }
        @keyframes ftx-slide { from { transform: translateX(100%); } to { transform: translateX(0); } }
        .ftx-drawer-head {
          padding: 18px 20px 14px;
          border-bottom: 1px solid var(--cds-border-subtle);
          position: relative;
        }
        .ftx-drawer-eyebrow {
          font-size: 10px; font-weight: 700;
          letter-spacing: 0.1em; text-transform: uppercase;
          color: var(--gold-dark);
        }
        .ftx-drawer-title {
          margin: 6px 0 0; font-size: 18px; font-weight: 700; color: var(--ink);
          line-height: 1.3;
          padding-right: 32px;
        }
        .ftx-drawer-close {
          position: absolute; top: 14px; right: 14px;
          width: 28px; height: 28px;
          background: transparent; border: none; cursor: pointer;
          font-size: 22px; line-height: 1; color: var(--cds-text-helper);
          border-radius: 4px;
        }
        .ftx-drawer-close:hover { background: var(--cds-layer-02); color: var(--ink); }

        .ftx-drawer-meta {
          padding: 10px 20px;
          display: flex; flex-wrap: wrap; gap: 10px;
          border-bottom: 1px solid var(--cds-border-subtle);
          font-size: 11px; color: var(--cds-text-helper);
        }
        .ftx-drawer-status {
          font-family: var(--mono); font-size: 10px; font-weight: 700;
          padding: 3px 8px; border-radius: 4px;
          text-transform: uppercase; letter-spacing: 0.04em;
        }
        .ftx-drawer-ref, .ftx-drawer-ts {
          font-family: var(--mono);
        }

        .ftx-drawer-body { flex: 1; padding: 18px 20px; overflow-y: auto; }
        .ftx-drawer-letter {
          white-space: pre-wrap; word-break: break-word;
          font-family: "DM Sans", serif; font-size: 13px; line-height: 1.6;
          color: var(--cds-text-primary);
          margin: 0;
        }
        .ftx-drawer-decision {
          background: var(--cds-layer-02);
          border-left: 3px solid var(--gold);
          padding: 10px 14px;
          border-radius: 4px;
        }
        .ftx-drawer-decision-label {
          font-size: 10px; font-weight: 700; letter-spacing: 0.08em;
          text-transform: uppercase; color: var(--gold-dark);
        }
        .ftx-drawer-decision-val {
          font-size: 14px; font-weight: 600; color: var(--ink); margin-top: 4px;
        }
        .ftx-drawer-empty {
          text-align: center; padding: 24px 12px;
        }
        .ftx-drawer-empty-title { font-size: 13px; font-weight: 600; color: var(--cds-text-secondary); }
        .ftx-drawer-empty-sub { font-size: 12px; color: var(--cds-text-helper); margin-top: 6px; line-height: 1.5; }
        .ftx-drawer-tpl {
          margin-top: 18px;
          padding: 10px 12px;
          background: var(--cds-layer-02);
          border-radius: 6px;
          font-size: 11px;
        }
        .ftx-drawer-tpl-lbl {
          font-weight: 700; color: var(--cds-text-helper);
          text-transform: uppercase; letter-spacing: 0.06em;
          font-size: 9px; margin-right: 6px;
        }
        .ftx-drawer-tpl code {
          font-family: var(--mono);
          color: var(--cds-text-primary);
        }

        .ftx-drawer-foot {
          border-top: 1px solid var(--cds-border-subtle);
          padding: 12px 20px;
        }
        .ftx-drawer-link {
          font-size: 12px; font-weight: 600;
          color: var(--gold-dark);
          text-decoration: none;
        }
        .ftx-drawer-link:hover { color: var(--gold); text-decoration: underline; }
      `}</style>
    </section>
  );
}
