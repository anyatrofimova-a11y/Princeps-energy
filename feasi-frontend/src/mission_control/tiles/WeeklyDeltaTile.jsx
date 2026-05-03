import React from "react";
import ProvenanceFooter from "./ProvenanceFooter";

/**
 * WeeklyDeltaTile — what changed since last refresh of REPD + NSIP.
 *
 * Two-column delta card: left=REPD (count + top-5 newcomers), right=NSIP
 * (count + status breakdown).
 */
function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-GB", {
      day: "numeric", month: "short",
    });
  } catch {
    return "—";
  }
}

export default function WeeklyDeltaTile({ data }) {
  const repd = (data && data.repd) || {};
  const nsip = (data && data.nsip) || {};
  const top5 = repd.top_5_new_projects || [];
  const statusRows = (nsip.status_breakdown || []).slice(0, 5);

  return (
    <div className="mcv2-tile mcv2-area-delta">
      <div className="mcv2-tile-head">
        <div className="mcv2-tile-title">Weekly delta</div>
        <div className="mcv2-tile-tag">since last refresh</div>
      </div>
      <div className="mcv2-tile-body">
        <div className="mcv2-delta-cols">
          <div className="mcv2-delta-col">
            <h4>REPD</h4>
            <div className="mcv2-delta-bignum">{repd.new_count ?? 0}</div>
            <div className="mcv2-delta-sub">new rows · {repd.rows_total ?? "—"} total</div>
            {top5.length === 0 ? (
              <div className="mcv2-empty" style={{ padding: "6px 0" }}>No recent submissions.</div>
            ) : (
              top5.map((p, i) => (
                <div key={p.repd_id || i} className="mcv2-delta-newrow">
                  <span style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    flex: 1,
                  }}>{p.site_name || p.repd_id}</span>
                  <span style={{
                    fontFamily: "var(--mcv2-font-mono)",
                    color: "#8A9099",
                  }}>
                    {p.capacity_mw ? `${Math.round(p.capacity_mw)}MW` : ""} · {fmtDate(p.date_submitted)}
                  </span>
                </div>
              ))
            )}
          </div>
          <div className="mcv2-delta-col">
            <h4>NSIP / DCO</h4>
            <div className="mcv2-delta-bignum">{nsip.new_count ?? 0}</div>
            <div className="mcv2-delta-sub">new rows · {nsip.rows_total ?? "—"} total</div>
            {statusRows.length === 0 ? (
              <div className="mcv2-empty" style={{ padding: "6px 0" }}>No status data.</div>
            ) : (
              statusRows.map((s, i) => (
                <div key={i} className="mcv2-delta-newrow">
                  <span style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    flex: 1,
                  }}>{s.status}</span>
                  <span style={{
                    fontFamily: "var(--mcv2-font-mono)",
                    color: "#8A9099",
                  }}>{s.n}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
      <ProvenanceFooter provenance={data?.provenance} />
    </div>
  );
}
