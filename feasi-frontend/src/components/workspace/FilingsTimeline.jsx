import React, { useMemo, useState } from "react";
import { buildFilingsTimeline, STAGES, STAGE_INDEX } from "../../lib/stage_workflow";

/**
 * FilingsTimeline — first-class view of every regulatory + commercial
 * artefact the project needs, in stage order. Status lights up as stage
 * advances. Built.inc-style.
 *
 * Filter chips: all / due soon / submitted / overdue.
 * Each row clickable — opens the artefact (draft link / submitted link).
 */

const STATUS_STYLES = {
  locked:    { bg: "var(--cds-layer-03)",           fg: "var(--cds-text-helper)",     label: "Locked"    },
  drafting:  { bg: "rgba(232,160,18,0.12)",         fg: "var(--cds-support-warning)", label: "Drafting"  },
  submitted: { bg: "rgba(45,108,176,0.12)",         fg: "#2D6CB0",                    label: "Submitted" },
  approved:  { bg: "rgba(22,163,74,0.12)",          fg: "var(--cds-support-success)", label: "Approved"  },
  rejected:  { bg: "rgba(220,38,38,0.12)",          fg: "var(--cds-support-error)",   label: "Rejected"  },
  overdue:   { bg: "rgba(220,38,38,0.14)",          fg: "var(--cds-support-error)",   label: "Overdue"   },
};

const FILTERS = [
  { key: "all",       label: "All"       },
  { key: "active",    label: "Active"    },
  { key: "submitted", label: "Submitted" },
  { key: "locked",    label: "Locked"    },
];

function fmtDeadline(d) {
  if (d == null) return "";
  if (d <= 0) return "due now";
  if (d === 1) return "1d";
  if (d < 14) return `${d}d`;
  return `${Math.round(d / 7)}w`;
}

export default function FilingsTimeline({ project, compact = false, onOpenFiling = null }) {
  const [filter, setFilter] = useState("all");
  const items = useMemo(() => buildFilingsTimeline(project), [project]);

  const filtered = useMemo(() => {
    if (filter === "all") return items;
    if (filter === "active") return items.filter((i) => i.status === "drafting");
    if (filter === "submitted") return items.filter((i) => i.status === "submitted" || i.status === "approved");
    if (filter === "locked") return items.filter((i) => i.status === "locked");
    return items;
  }, [items, filter]);

  const counts = useMemo(() => {
    const c = { all: items.length, active: 0, submitted: 0, locked: 0 };
    items.forEach((i) => {
      if (i.status === "drafting") c.active++;
      if (i.status === "submitted" || i.status === "approved") c.submitted++;
      if (i.status === "locked") c.locked++;
    });
    return c;
  }, [items]);

  if (items.length === 0) {
    return (
      <div className="ft-root ft-empty">
        <div className="ft-empty-title">No filings required</div>
        <div className="ft-empty-sub">This project doesn't require regulatory submissions in its current config.</div>
      </div>
    );
  }

  return (
    <div className={"ft-root" + (compact ? " ft-compact" : "")}>
      <header className="ft-head">
        <h3 className="ft-title">Filings & artefacts</h3>
        <div className="ft-filters">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              className={"ft-chip" + (filter === f.key ? " ft-chip-active" : "")}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
              <span className="ft-count">{counts[f.key]}</span>
            </button>
          ))}
        </div>
      </header>
      <ul className="ft-list">
        {filtered.map((it) => {
          const s = STATUS_STYLES[it.status] || STATUS_STYLES.locked;
          const stageLabel = it.status === "locked" ? `unlocks @ ${it.unlock_stage}` : it.require_stage;
          return (
            <li key={it.code} className={"ft-item ft-item-" + it.status} onClick={() => onOpenFiling?.(it)}>
              <span className="ft-status" style={{ background: s.bg, color: s.fg }}>{s.label}</span>
              <div className="ft-body">
                <div className="ft-name">{it.name}</div>
                <div className="ft-meta">
                  <span>{stageLabel}</span>
                  {it.doc_template && <span className="ft-tpl">{it.doc_template}</span>}
                </div>
              </div>
              <span className="ft-go">{it.status === "locked" ? "🔒" : "→"}</span>
            </li>
          );
        })}
      </ul>
      <style>{`
        .ft-root { display: flex; flex-direction: column; gap: 10px; font-family: "DM Sans", -apple-system, sans-serif; }
        .ft-empty { padding: 32px; text-align: center; background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle); border-radius: 12px; }
        .ft-empty-title { font-size: 13px; font-weight: 600; color: var(--cds-text-secondary); margin-bottom: 4px; }
        .ft-empty-sub { font-size: 12px; color: var(--cds-text-helper); }
        .ft-head { display: flex; align-items: center; justify-content: space-between; }
        .ft-title { margin: 0; font-size: 13px; font-weight: 700; color: var(--ink); }
        .ft-filters { display: flex; gap: 4px; }
        .ft-chip {
          display: inline-flex; align-items: center; gap: 4px;
          padding: 4px 10px; border: 1px solid var(--cds-border-subtle);
          border-radius: 6px; background: transparent; cursor: pointer;
          font: inherit; font-size: 11px; font-weight: 600;
          color: var(--cds-text-secondary);
        }
        .ft-chip:hover { border-color: var(--gold); color: var(--gold-dark); }
        .ft-chip-active { background: rgba(var(--accent-rgb), 0.1); border-color: var(--gold); color: var(--gold-dark); }
        .ft-count { font-family: var(--mono); font-size: 9px; opacity: 0.7; }
        .ft-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
        .ft-item {
          display: flex; align-items: center; gap: 12px;
          padding: 10px 12px; border: 1px solid var(--cds-border-subtle);
          border-radius: 8px; background: var(--cds-layer-01);
          cursor: pointer; transition: all 120ms;
        }
        .ft-item:hover { border-color: var(--gold); transform: translateY(-1px); }
        .ft-item-locked { opacity: 0.55; cursor: default; }
        .ft-item-locked:hover { transform: none; border-color: var(--cds-border-subtle); }
        .ft-status {
          font-family: var(--mono); font-size: 9px; font-weight: 700;
          padding: 2px 7px; border-radius: 4px; text-transform: uppercase;
          letter-spacing: 0.04em; min-width: 72px; text-align: center;
        }
        .ft-body { flex: 1; min-width: 0; }
        .ft-name { font-size: 13px; font-weight: 600; color: var(--ink); }
        .ft-meta { display: flex; gap: 10px; font-size: 10px; color: var(--cds-text-helper); margin-top: 2px; }
        .ft-tpl { font-family: var(--mono); opacity: 0.7; }
        .ft-go { color: var(--cds-text-helper); font-size: 14px; flex-shrink: 0; }
        .ft-item:hover .ft-go { color: var(--gold); }

        .ft-compact .ft-item { padding: 6px 10px; }
        .ft-compact .ft-name { font-size: 12px; }
        .ft-compact .ft-meta { font-size: 9px; }
      `}</style>
    </div>
  );
}
