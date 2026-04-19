import React from "react";

/**
 * Provenance — small uppercase footer under a metric, showing data source
 * and freshness. Models Aurora Energy Research's "bankability" pattern:
 * every number on screen is lender-defensible because its source + age is visible.
 *
 * Format:  SOURCE · TIME   or   SOURCE · PATHWAY
 * Example: "BMRS · TODAY 14:32", "NESO FES · LEADING THE WAY"
 */
function formatRelative(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const yest = new Date(now); yest.setDate(now.getDate() - 1);
  const isYesterday = d.toDateString() === yest.toDateString();
  const diffDays = Math.floor((now - d) / (1000 * 60 * 60 * 24));
  if (sameDay) {
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `today ${hh}:${mm}`;
  }
  if (isYesterday) return "yesterday";
  if (diffDays >= 0 && diffDays < 7) return `${diffDays}d ago`;
  return d.toISOString().slice(0, 10);
}

export default function Provenance({ source, fetchedAt = null, pathway = null }) {
  if (!source) return null;
  const rel = formatRelative(fetchedAt);
  const tail = pathway || rel;
  return (
    <div className="provenance">
      <span>{source}</span>
      {tail && <><span className="provenance-sep"> · </span><span>{tail}</span></>}
      <style>{`
        .provenance {
          font-size: 10px;
          letter-spacing: 1px;
          text-transform: uppercase;
          color: var(--cds-text-helper);
          font-weight: 500;
          margin-top: 6px;
          line-height: 1.4;
          border: none;
        }
        .provenance-sep { opacity: 0.6; }
      `}</style>
    </div>
  );
}
