import React from "react";
import { useNavigate } from "react-router-dom";
import ProvenanceFooter from "./ProvenanceFooter";

/**
 * TopOwnersTile — top 10 owners by total_capacity_mw across REPD + TEC,
 * with best-effort CCOD CH-number linkage via pg_trgm similarity.
 */
function fmtMw(mw) {
  if (mw == null) return "—";
  if (mw >= 1000) return `${(mw / 1000).toFixed(1)} GW`;
  return `${Math.round(mw)} MW`;
}

export default function TopOwnersTile({ data }) {
  const navigate = useNavigate();
  const owners = (data && data.owners) || [];
  const max = Math.max(1, ...owners.map(o => o.total_capacity_mw || 0));

  return (
    <div className="mcv2-tile mcv2-area-owners">
      <div className="mcv2-tile-head">
        <div className="mcv2-tile-title">Industrial graph · top owners</div>
        <div className="mcv2-tile-tag">REPD × CCOD × TEC</div>
      </div>
      <div className="mcv2-tile-body">
        {owners.length === 0 ? (
          <div className="mcv2-empty">No owner aggregates available — REPD developer column may be empty.</div>
        ) : (
          <div className="mcv2-owners">
            {owners.map((o) => (
              <div
                key={o.owner_name}
                className="mcv2-owner-row"
                onClick={() => navigate(`/v2/object/Entity/${encodeURIComponent(o.owner_name)}`)}
                title={`${o.n_projects} project(s) · ${o.ch_number ? `CH ${o.ch_number}` : "no CH match"}`}
              >
                <div>
                  <div className="mcv2-owner-name">
                    {o.owner_name}
                    {o.ch_number && <span className="mcv2-ch">CH {o.ch_number}</span>}
                  </div>
                  <div className="mcv2-owner-bar-row">
                    <div className="mcv2-owner-bar">
                      <div
                        className="mcv2-owner-bar-fill"
                        style={{
                          width: `${Math.round(((o.total_capacity_mw || 0) / max) * 100)}%`,
                        }}
                      />
                    </div>
                    <div className="mcv2-owner-mw">{fmtMw(o.total_capacity_mw)}</div>
                  </div>
                </div>
                <div style={{ textAlign: "right", fontFamily: "var(--mcv2-font-mono)", fontSize: 11, color: "#8A9099" }}>
                  ×{o.n_projects}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <ProvenanceFooter provenance={data?.provenance} />
    </div>
  );
}
