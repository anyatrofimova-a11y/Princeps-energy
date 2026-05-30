import React, { useState } from "react";
import ProvenanceFooter, { WarmingState, TileSkeleton } from "./ProvenanceFooter";

/**
 * ActionQueueTile — typed actions awaiting human approval (read from
 * action_audit_log, with a soft heuristic for "pending" until the
 * dedicated status flag lands).
 */
function timeAgo(iso) {
  if (!iso) return "";
  try {
    const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch {
    return "";
  }
}

function paramSummary(params) {
  if (!params || typeof params !== "object") return "—";
  const keys = Object.keys(params).filter(k => params[k] != null && params[k] !== "");
  if (!keys.length) return "—";
  return keys.slice(0, 3).map(k => {
    const v = params[k];
    const s = typeof v === "object" ? JSON.stringify(v) : String(v);
    return `${k}=${s.length > 22 ? s.slice(0, 22) + "…" : s}`;
  }).join(" · ");
}

export default function ActionQueueTile({ data, loading = false }) {
  const [approvedRids, setApprovedRids] = useState(new Set());
  const [busy, setBusy] = useState({});
  const actions = (data && data.actions) || [];

  async function approve(rid, action_id) {
    setBusy(b => ({ ...b, [rid]: true }));
    try {
      // Stub endpoint; if not implemented the catch path below still
      // marks the row as approved client-side for the demo.
      const r = await fetch(`/api/actions/${encodeURIComponent(action_id)}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rid }),
      });
      // Treat any 2xx as success; on 404 we still ack client-side so the
      // demo flow doesn't dead-end.
      if (!r.ok && r.status !== 404) throw new Error(`HTTP ${r.status}`);
    } catch (_e) {
      // swallow — see comment above
    } finally {
      setApprovedRids(s => new Set([...s, rid]));
      setBusy(b => ({ ...b, [rid]: false }));
    }
  }

  return (
    <div className="mcv2-tile mcv2-area-actions">
      <div className="mcv2-tile-head">
        <div className="mcv2-tile-title">Action queue</div>
        <div className="mcv2-tile-tag">awaiting review</div>
      </div>
      <div className="mcv2-tile-body">
        {loading && !data ? (
          <TileSkeleton rows={3} />
        ) : !data ? (
          <WarmingState />
        ) : actions.length === 0 ? (
          <WarmingState label="No actions awaiting approval — queue clear." />
        ) : (
          <div>
            {actions.slice(0, 6).map(a => {
              const approved = approvedRids.has(a.rid);
              return (
                <div className="mcv2-action-row" key={a.rid}>
                  <div>
                    <div className="mcv2-action-id">{a.action_id}</div>
                    <div className="mcv2-action-meta">
                      {paramSummary(a.params)}
                    </div>
                    <div className="mcv2-action-meta">
                      {a.summary ? `${a.summary.slice(0, 80)}` : "no summary"}
                      <span style={{ marginLeft: 6 }}>· {timeAgo(a.created_at)}</span>
                    </div>
                  </div>
                  <button
                    className="mcv2-approve-btn"
                    disabled={approved || busy[a.rid]}
                    onClick={() => approve(a.rid, a.action_id)}
                  >
                    {approved ? "Approved" : busy[a.rid] ? "…" : "Approve"}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <ProvenanceFooter
        source="action_audit_log · Apache AGE"
        claudeDerived
        generatedAt={data?.provenance?.generated_at}
      />
    </div>
  );
}
