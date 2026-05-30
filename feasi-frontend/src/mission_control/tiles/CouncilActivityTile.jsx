import React from "react";
import { useNavigate } from "react-router-dom";
import ProvenanceFooter, { WarmingState, TileSkeleton } from "./ProvenanceFooter";

/**
 * CouncilActivityTile — last 5 council sessions, click to replay.
 *
 * Reads /api/mission-control/council-sessions (read-only mirror — does not
 * touch app/routers/council.py which is owned by a parallel agent).
 */
function timeAgo(iso) {
  if (!iso) return "—";
  try {
    const delta = Date.now() - new Date(iso).getTime();
    if (delta < 0) return "just now";
    const m = Math.floor(delta / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch {
    return "—";
  }
}

function verdictClass(v) {
  if (!v) return "unknown";
  const u = String(v).toUpperCase().replace(/[^A-Z]/g, "");
  if (u === "GO") return "go";
  if (u === "CAUTION") return "caution";
  if (u === "NOGO" || u === "NO" || u === "NO-GO") return "no-go";
  return "unknown";
}

export default function CouncilActivityTile({ data, loading = false }) {
  const navigate = useNavigate();
  const sessions = (data && data.sessions) || [];
  return (
    <div className="mcv2-tile mcv2-area-council">
      <div className="mcv2-tile-head">
        <div className="mcv2-tile-title">Council activity</div>
        <div className="mcv2-tile-tag">audited</div>
      </div>
      <div className="mcv2-tile-body">
        {loading && !data ? (
          <TileSkeleton rows={4} />
        ) : !data ? (
          <WarmingState />
        ) : sessions.length === 0 ? (
          <WarmingState label="No council sessions yet — start one from the Council page." />
        ) : (
          <div className="mcv2-list">
            {sessions.slice(0, 5).map(s => (
              <div
                key={s.session_rid}
                className="mcv2-list-row"
                onClick={() => navigate(`/v2/council/${s.session_rid}`)}
                title="Replay this council session"
              >
                <div className="mcv2-list-q">{s.query || "(no query)"}</div>
                <div className="mcv2-list-meta">
                  <span>
                    <span className={`mcv2-verdict-pill ${verdictClass(s.final_verdict)}`}>
                      {s.final_verdict || s.status || "—"}
                    </span>
                    {s.confidence != null && (
                      <span style={{ marginLeft: 6 }}>
                        conf {Math.round(Number(s.confidence) * (s.confidence > 1 ? 1 : 100))}%
                      </span>
                    )}
                  </span>
                  <span>{timeAgo(s.started_at)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <ProvenanceFooter
        source="council_session_log · Apache AGE"
        claudeDerived
        generatedAt={data?.provenance?.generated_at}
      />
    </div>
  );
}
